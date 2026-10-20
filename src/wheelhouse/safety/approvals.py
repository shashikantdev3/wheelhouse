"""Approvals: bound to the exact step, signed by a named person, expiring and single use.

A Touch step is identified by a SHA-256 hash of its canonical JSON form (RFC 8785):
host, action name, tier and the full rendered argument list. If anything in the step
changes, the hash changes and the approval no longer applies.

Each approver has their own Ed25519 key pair. The private key stays with the person
(their machine, the approval console they run); Wheelhouse's runner holds only the
public keys listed in the inventory. So the process that executes changes cannot
create an approval, and every approval names, and proves, who gave it. Each approval
has a random nonce, and Lockkeeper refuses a nonce it has already used.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import secrets
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import rfc8785
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from wheelhouse.safety.catalog import RenderedAction

ALGORITHM = "ed25519"
FORMAT_VERSION = 1
DEFAULT_APPROVAL_TTL = timedelta(minutes=30)
MAX_APPROVAL_TTL = timedelta(hours=8)
CLOCK_SKEW = timedelta(seconds=60)
"""How far ahead an approver's clock may be before an approval counts as future-dated."""
APPROVER_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
_PUBLIC_PREFIX = "ed25519:"


def step_hash(host: str, action: RenderedAction) -> str:
    payload = {
        "host": host,
        "action": action.name,
        "tier": action.tier.value,
        "argv": list(action.argv),
    }
    return hashlib.sha256(rfc8785.dumps(payload)).hexdigest()


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    """Strict base64url: any character outside the alphabet is an error."""
    return base64.b64decode(text + "=" * (-len(text) % 4), altchars=b"-_", validate=True)


def public_key_text(key: Ed25519PublicKey) -> str:
    """The form used in inventories: 'ed25519:' plus the raw 32-byte key, base64url."""
    raw = key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return _PUBLIC_PREFIX + _b64(raw)


def parse_public_key(text: str) -> Ed25519PublicKey:
    if not isinstance(text, str) or not text.startswith(_PUBLIC_PREFIX):
        raise ValueError("approver public keys look like 'ed25519:<base64url>'")
    try:
        raw = _unb64(text[len(_PUBLIC_PREFIX) :])
    except ValueError:
        raise ValueError("approver public key is not valid base64url") from None
    if len(raw) != 32:
        raise ValueError("approver public key must be 32 bytes")
    return Ed25519PublicKey.from_public_bytes(raw)


def check_approver_name(name: str) -> str:
    if not isinstance(name, str) or not APPROVER_NAME.fullmatch(name):
        raise ValueError("approver names are lowercase letters, digits, '.', '_' or '-' (up to 64)")
    return name


@dataclass(frozen=True)
class Approval:
    step_hash: str
    approver: str
    approved_at: datetime
    expires_at: datetime
    nonce: str
    signature: str
    context: str = ""
    """What the approval was given for beyond the step: for the crew, the incident id and
    the digest of the plan the person saw. Empty for a one-off CLI approval. The runner
    only accepts an approval whose context matches the one it expects."""

    def signed_payload(self) -> bytes:
        return rfc8785.dumps(
            {
                "v": FORMAT_VERSION,
                "alg": ALGORITHM,
                "context": self.context,
                "step_hash": self.step_hash,
                "approver": self.approver,
                "approved_at": self.approved_at.astimezone(UTC).isoformat(),
                "expires_at": self.expires_at.astimezone(UTC).isoformat(),
                "nonce": self.nonce,
            }
        )


class ApproverKey:
    """One person's signing key. Never logged; saved only as a 0600 file."""

    def __init__(self, name: str, private_key: Ed25519PrivateKey) -> None:
        self.name = check_approver_name(name)
        self._key = private_key

    def __repr__(self) -> str:
        return f"ApproverKey(name={self.name!r}, key=***)"

    @classmethod
    def generate(cls, name: str) -> ApproverKey:
        return cls(name, Ed25519PrivateKey.generate())

    @property
    def public_key(self) -> Ed25519PublicKey:
        return self._key.public_key()

    @property
    def public_text(self) -> str:
        return public_key_text(self.public_key)

    def save(self, path: str | Path) -> Path:
        """Write the private key to a new file readable only by its owner."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        pem = self._key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(pem)
        return p

    @classmethod
    def load(cls, name: str, path: str | Path) -> ApproverKey:
        p = Path(path)
        if os.name == "posix" and stat.S_IMODE(p.stat().st_mode) & 0o077:
            raise ValueError(f"{p} is readable by other users; run: chmod 600 {p}")
        key = serialization.load_pem_private_key(p.read_bytes(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError(f"{p} is not an Ed25519 private key")
        return cls(name, key)

    def grant(
        self,
        step: str,
        now: datetime | None = None,
        ttl: timedelta = DEFAULT_APPROVAL_TTL,
        context: str = "",
    ) -> Approval:
        if not isinstance(step, str) or not re.fullmatch(r"[0-9a-f]{64}", step):
            raise ValueError("an approval needs a 64-character step hash")
        if not timedelta(0) < ttl <= MAX_APPROVAL_TTL:
            raise ValueError("approval lifetime must be between 0 and 8 hours")
        now = now or datetime.now(UTC)
        if not _aware(now):
            raise ValueError("times must be time-zone aware")
        if not isinstance(context, str) or len(context) > 200:
            raise ValueError("approval context must be text of at most 200 characters")
        unsigned = Approval(step, self.name, now, now + ttl, secrets.token_hex(16), "", context)
        signature = _b64(self._key.sign(unsigned.signed_payload()))
        return Approval(
            unsigned.step_hash,
            unsigned.approver,
            unsigned.approved_at,
            unsigned.expires_at,
            unsigned.nonce,
            signature,
            context,
        )


class ApprovalAuthority:
    """Verifies approvals against the approvers' public keys. Holds no secret."""

    def __init__(self, approvers: Mapping[str, Ed25519PublicKey | str]) -> None:
        keys: dict[str, Ed25519PublicKey] = {}
        for name, key in approvers.items():
            check_approver_name(name)
            keys[name] = parse_public_key(key) if isinstance(key, str) else key
        self._keys = keys

    def __repr__(self) -> str:
        return f"ApprovalAuthority(approvers={sorted(self._keys)!r})"

    @property
    def approvers(self) -> list[str]:
        return sorted(self._keys)

    def problem(
        self, approval: Approval, expected_hash: str, now: datetime, context: str = ""
    ) -> str | None:
        """Why this approval does not cover the step, or None if it does.
        Does not check single use; Lockkeeper does that."""
        if not isinstance(approval, Approval):
            return "not an approval"
        if not all(
            isinstance(v, str)
            for v in (
                approval.step_hash,
                approval.approver,
                approval.nonce,
                approval.signature,
                approval.context,
            )
        ) or not all(isinstance(v, datetime) for v in (approval.approved_at, approval.expires_at)):
            return "approval fields have the wrong types"
        if not isinstance(now, datetime) or not _aware(now):
            return "time is not time-zone aware"
        if not (_aware(approval.approved_at) and _aware(approval.expires_at)):
            return "approval times are not time-zone aware"
        if not approval.nonce or not approval.signature:
            return "approval is not signed"
        key = self._keys.get(approval.approver)
        if key is None:
            return "approver is not listed in the inventory"
        try:
            key.verify(_unb64(approval.signature), approval.signed_payload())
        except (InvalidSignature, ValueError):
            return "approval signature is not valid"
        if approval.step_hash != expected_hash:
            return "approval is for a different step"
        if approval.context != context:
            return "approval was given for a different incident or plan"
        if now + CLOCK_SKEW < approval.approved_at:
            return "approval is dated in the future"
        if now >= approval.expires_at:
            return "approval has expired"
        if approval.expires_at - approval.approved_at > MAX_APPROVAL_TTL:
            return "approval lifetime is longer than allowed"
        return None
