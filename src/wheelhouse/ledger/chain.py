"""Purser's ledger: an append-only, hash-chained JSONL file of AI Decision Records.

Records follow the ProvenKit AI Decision Record format, version 0.1
(https://github.com/shashikantdev3/provenkit, spec/v0.1). Canonical form (section 5):
drop nulls, empty objects and empty arrays recursively, then serialise with RFC 8785.
record_hash is SHA-256 over that form with integrity.record_hash and
integrity.signature removed. prev_hash is the recomputed hash of the previous record.

Writers take a file lock, re-verify the last record before appending, and never trust a
stored hash.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import rfc8785
from filelock import FileLock

GENESIS = "sha256:" + "0" * 64
MAX_LINE_BYTES = 1_000_000


class LedgerError(RuntimeError):
    """The ledger is unreadable or has been tampered with."""


def _strip(value: Any) -> Any:
    if isinstance(value, dict):
        out = {k: _strip(v) for k, v in value.items()}
        return {k: v for k, v in out.items() if v is not None and v != {} and v != []}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def canonical_bytes(record: dict[str, Any]) -> bytes:
    """ProvenKit section 5 canonical form."""
    return rfc8785.dumps(_strip(record))


def compute_record_hash(record: dict[str, Any]) -> str:
    body = copy.deepcopy(record)
    integrity = body.get("integrity")
    if isinstance(integrity, dict):
        integrity.pop("record_hash", None)
        integrity.pop("signature", None)
    return "sha256:" + hashlib.sha256(canonical_bytes(body)).hexdigest()


def _read_last_line(path: Path) -> str | None:
    if not path.exists() or path.stat().st_size == 0:
        return None
    with path.open("rb") as fh:
        fh.seek(0, os.SEEK_END)
        end = fh.tell()
        pos = end
        chunk = b""
        while pos > 0:
            step = min(65536, pos)
            pos -= step
            fh.seek(pos)
            chunk = fh.read(step) + chunk
            stripped = chunk.rstrip(b"\n")
            idx = stripped.rfind(b"\n")
            if idx != -1:
                return stripped[idx + 1 :].decode("utf-8")
            if len(chunk) > MAX_LINE_BYTES:
                raise LedgerError("ledger line too long")
        return chunk.rstrip(b"\n").decode("utf-8") or None


@dataclass
class VerifyResult:
    ok: bool
    count: int
    head_hash: str
    errors: list[str] = field(default_factory=list)


class Ledger:
    def __init__(self, path: str | Path, chain_id: str = "wheelhouse") -> None:
        self.path = Path(path)
        self.chain_id = chain_id
        self._lock = FileLock(str(self.path) + ".lock")

    @contextmanager
    def locked(self) -> Iterator[None]:
        """Hold the ledger's file lock across several steps (re-entrant in one thread).
        Used so 'is this approval unused?' and 'record it as used' happen atomically."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            yield

    def _tail(self) -> tuple[int, str]:
        """(next seq, prev_hash) after re-verifying the last record's own hash."""
        line = _read_last_line(self.path)
        if line is None:
            return 0, GENESIS
        try:
            last = json.loads(line)
        except json.JSONDecodeError as err:
            raise LedgerError("last ledger record is not valid JSON") from err
        recomputed = compute_record_hash(last)
        if last.get("integrity", {}).get("record_hash") != recomputed:
            raise LedgerError("last ledger record fails its own hash check; run verify")
        return int(last["integrity"]["seq"]) + 1, recomputed

    def append(self, body: dict[str, Any]) -> dict[str, Any]:
        """Add integrity fields to a record body and append it. Returns the full record."""
        if "integrity" in body:
            raise ValueError("record body must not carry integrity fields")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            seq, prev = self._tail()
            record = copy.deepcopy(body)
            record["integrity"] = {"chain_id": self.chain_id, "seq": seq, "prev_hash": prev}
            record["integrity"]["record_hash"] = compute_record_hash(record)
            line = json.dumps(_strip(record), ensure_ascii=False, separators=(",", ":"))
            with self.path.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(line + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        return record

    def records(self) -> Iterator[dict[str, Any]]:
        if not self.path.exists():
            return
        with self.path.open(encoding="utf-8") as fh:
            for n, line in enumerate(fh):
                if not line.strip():
                    continue
                if len(line) > MAX_LINE_BYTES:
                    raise LedgerError(f"line {n + 1} is too long")
                yield json.loads(line)

    def used_nonces(self) -> set[str]:
        return {
            r["labels"]["approval_nonce"]
            for r in self.records()
            if isinstance(r.get("labels"), dict) and "approval_nonce" in r["labels"]
        }

    def verify(self) -> VerifyResult:
        """ProvenKit section 6.1: seq order, own hash, prev_hash against the recomputed
        hash of the previous record, unique decision ids."""
        errors: list[str] = []
        prev = GENESIS
        seen: set[str] = set()
        count = 0
        try:
            for index, record in enumerate(self.records()):
                count += 1
                integ = record.get("integrity", {})
                if integ.get("seq") != index:
                    errors.append(f"record {index}: seq is {integ.get('seq')}")
                recomputed = compute_record_hash(record)
                if integ.get("record_hash") != recomputed:
                    errors.append(f"record {index}: record_hash does not match content")
                if integ.get("prev_hash") != prev:
                    errors.append(f"record {index}: prev_hash does not match previous record")
                did = record.get("decision_id")
                if did in seen:
                    errors.append(f"record {index}: decision_id repeated")
                seen.add(str(did))
                prev = recomputed
        except (json.JSONDecodeError, LedgerError, UnicodeDecodeError, KeyError, TypeError) as err:
            errors.append(f"unreadable ledger: {err}")
        return VerifyResult(not errors, count, prev, errors)
