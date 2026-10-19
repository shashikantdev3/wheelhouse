import json
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
import pytest

from wheelhouse.ledger import (
    GENESIS,
    Ledger,
    LedgerError,
    canonical_bytes,
    compute_record_hash,
    decision_record,
    execution_record,
)
from wheelhouse.safety import ApprovalAuthority, Lockkeeper

SCHEMA = json.loads(
    (Path(__file__).parents[1] / "src/wheelhouse/ledger/aidr-0.1.schema.json").read_text()
)
NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
KEY = b"k" * 32


def validate(record: dict) -> None:
    jsonschema.Draft202012Validator(
        SCHEMA, format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER
    ).validate(record)


def test_canonical_form_drops_nulls_and_empties_and_sorts() -> None:
    a = {"b": 1, "a": {"x": None, "y": [], "z": {}}, "c": [1, None]}
    assert canonical_bytes(a) == b'{"b":1,"c":[1,null]}'
    assert canonical_bytes({"n": 5001.0}) == b'{"n":5001}'


def test_records_chain_verify_and_match_the_schema(tmp_path: Path) -> None:
    k = Lockkeeper(authority=ApprovalAuthority(KEY))
    ledger = Ledger(tmp_path / "ledger.jsonl")
    policy = k.catalog.policy_hash()
    d1 = k.decide("web01", "disk_usage", now=NOW)
    r1 = ledger.append(decision_record(d1, policy_hash=policy, principal="cli", key=KEY))
    d2 = k.decide("web01", "service_restart", {"service": "nginx"}, now=NOW)
    r2 = ledger.append(decision_record(d2, policy_hash=policy, principal="cli", key=KEY))
    assert d2.step_hash
    appr = k.authority.grant(d2.step_hash, "shashikant", now=NOW)  # type: ignore[union-attr]
    d3 = k.decide("web01", "service_restart", {"service": "nginx"}, appr, now=NOW)
    r3 = ledger.append(
        decision_record(d3, policy_hash=policy, principal="cli", key=KEY, approval=appr)
    )
    r4 = ledger.append(
        execution_record(
            r3["decision_id"],
            d3,
            policy_hash=policy,
            principal="cli",
            exit_code=0,
            duration_ms=12,
            output=b"ok",
            status="ok",
            key=KEY,
        )
    )
    d5 = k.decide("web01", "service_status", {"service": "x;reboot"}, now=NOW)
    r5 = ledger.append(decision_record(d5, policy_hash=policy, principal="cli", key=KEY))
    for r in (r1, r2, r3, r4, r5):
        validate(r)
    assert r1["integrity"]["prev_hash"] == GENESIS
    assert r2["integrity"]["prev_hash"] == r1["integrity"]["record_hash"]
    assert r3["outcome"]["action"] == "allow" and "approval" in r3["outcome"]
    assert r2["outcome"]["action"] == "require_approval"
    assert r5["outcome"]["action"] == "deny"
    assert "shashikant" not in json.dumps(r3)
    result = ledger.verify()
    assert result.ok and result.count == 5
    assert ledger.used_nonces() == {appr.nonce}


def test_tampering_is_detected(tmp_path: Path) -> None:
    k = Lockkeeper()
    ledger = Ledger(tmp_path / "ledger.jsonl")
    for _ in range(3):
        d = k.decide("web01", "uptime", now=NOW)
        ledger.append(decision_record(d, policy_hash=k.catalog.policy_hash(), principal="cli"))
    lines = ledger.path.read_text().splitlines()
    rec = json.loads(lines[1])
    rec["labels"]["host"] = "db01"
    lines[1] = json.dumps(rec)
    ledger.path.write_text("\n".join(lines) + "\n")
    result = ledger.verify()
    assert not result.ok
    assert any("record 1" in e for e in result.errors)
    assert any("record 2: prev_hash" in e for e in result.errors)


def test_append_refuses_a_tampered_tail(tmp_path: Path) -> None:
    k = Lockkeeper()
    ledger = Ledger(tmp_path / "ledger.jsonl")
    d = k.decide("web01", "uptime", now=NOW)
    ledger.append(decision_record(d, policy_hash=k.catalog.policy_hash(), principal="cli"))
    rec = json.loads(ledger.path.read_text())
    rec["labels"]["verdict"] = "refused"
    ledger.path.write_text(json.dumps(rec) + "\n")
    with pytest.raises(LedgerError):
        ledger.append(decision_record(d, policy_hash=k.catalog.policy_hash(), principal="cli"))


def test_record_hash_ignores_signature_and_own_hash() -> None:
    rec = {"a": 1, "integrity": {"seq": 0, "prev_hash": GENESIS}}
    h = compute_record_hash(rec)
    rec["integrity"]["record_hash"] = h
    rec["integrity"]["signature"] = "x"
    assert compute_record_hash(rec) == h


def test_single_use_survives_restart(tmp_path: Path) -> None:
    auth = ApprovalAuthority(KEY)
    ledger = Ledger(tmp_path / "ledger.jsonl")
    k1 = Lockkeeper(authority=auth)
    first = k1.decide("web01", "service_restart", {"service": "nginx"}, now=NOW)
    assert first.step_hash
    appr = auth.grant(first.step_hash, "shashikant", now=NOW)
    ran = k1.decide("web01", "service_restart", {"service": "nginx"}, appr, now=NOW)
    ledger.append(
        decision_record(ran, policy_hash="sha256:" + "0" * 64, principal="cli", approval=appr)
    )
    k2 = Lockkeeper(authority=auth, used_nonces=ledger.used_nonces())
    again = k2.decide("web01", "service_restart", {"service": "nginx"}, appr, now=NOW)
    assert not again.may_run
