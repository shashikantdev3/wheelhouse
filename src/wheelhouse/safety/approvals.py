"""Approvals: bound to the exact step, signed, expiring and single use.

A Touch step is identified by a SHA-256 hash of its canonical JSON form (RFC 8785):
host, action name, tier and the full rendered argument list. If anything in the step
changes, the hash changes and the approval no longer applies.

Approvals are signed with HMAC-SHA256 by an ApprovalAuthority that holds a secret key,
so an approval cannot be made up by code that does not hold the key. Each approval has
a random nonce, and Lockkeeper refuses a nonce it has already used.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import rfc8785

from wheelhouse.safety.catalog import RenderedAction

DEFAULT_APPROVAL_TTL = timedelta(minutes=30)
MAX_APPROVAL_TTL = timedelta(hours=8)
MIN_KEY_BYTES = 32


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


@dataclass(frozen=True)
class Approval:
    step_hash: str
    approver: str
    approved_at: datetime
    expires_at: datetime
    nonce: str
    signature: str

    def signed_payload(self) -> bytes:
        return rfc8785.dumps(
            {
                "step_hash": self.step_hash,
                "approver": self.approver,
                "approved_at": self.approved_at.astimezone(UTC).isoformat(),
                "expires_at": self.expires_at.astimezone(UTC).isoformat(),
                "nonce": self.nonce,
            }
        )


class ApprovalAuthority:
    """Grants and verifies approvals. Holds the signing key; never logs it."""

    def __init__(self, key: bytes) -> None:
        if len(key) < MIN_KEY_BYTES:
            raise ValueError(f"approval key must be at least {MIN_KEY_BYTES} bytes")
        self._key = key

    def __repr__(self) -> str:
        return "ApprovalAuthority(key=***)"

    def _sign(self, payload: bytes) -> str:
        return hmac.new(self._key, payload, hashlib.sha256).hexdigest()

    def grant(
        self,
        step: str,
        approver: str,
        now: datetime | None = None,
        ttl: timedelta = DEFAULT_APPROVAL_TTL,
    ) -> Approval:
        if not isinstance(approver, str) or not approver.strip():
            raise ValueError("an approval needs a named approver")
        if not isinstance(step, str) or not step:
            raise ValueError("an approval needs a step hash")
        if not timedelta(0) < ttl <= MAX_APPROVAL_TTL:
            raise ValueError("approval lifetime must be between 0 and 8 hours")
        now = now or datetime.now(UTC)
        if not _aware(now):
            raise ValueError("times must be time-zone aware")
        unsigned = Approval(step, approver.strip(), now, now + ttl, secrets.token_hex(16), "")
        return Approval(
            unsigned.step_hash,
            unsigned.approver,
            unsigned.approved_at,
            unsigned.expires_at,
            unsigned.nonce,
            self._sign(unsigned.signed_payload()),
        )

    def problem(self, approval: Approval, expected_hash: str, now: datetime) -> str | None:
        """Why this approval does not cover the step, or None if it does.
        Does not check single use; Lockkeeper does that."""
        if not isinstance(approval, Approval):
            return "not an approval"
        if not all(
            isinstance(v, str)
            for v in (approval.step_hash, approval.approver, approval.nonce, approval.signature)
        ) or not all(isinstance(v, datetime) for v in (approval.approved_at, approval.expires_at)):
            return "approval fields have the wrong types"
        if not isinstance(now, datetime) or not _aware(now):
            return "time is not time-zone aware"
        if not (_aware(approval.approved_at) and _aware(approval.expires_at)):
            return "approval times are not time-zone aware"
        if not approval.approver.strip():
            return "approval has no named approver"
        if not approval.nonce or not approval.signature:
            return "approval is not signed"
        expected = self._sign(approval.signed_payload())
        if not hmac.compare_digest(expected, approval.signature):
            return "approval signature is not valid"
        if approval.step_hash != expected_hash:
            return "approval is for a different step"
        if now < approval.approved_at:
            return "approval is dated in the future"
        if now >= approval.expires_at:
            return "approval has expired"
        if approval.expires_at - approval.approved_at > MAX_APPROVAL_TTL:
            return "approval lifetime is longer than allowed"
        return None
