"""Saving and loading approvals as small JSON files, so a person can approve a step in
one place and the runner can use it in another."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from wheelhouse.safety.approvals import Approval


def approval_to_dict(approval: Approval) -> dict[str, str]:
    return {
        "step_hash": approval.step_hash,
        "approver": approval.approver,
        "approved_at": approval.approved_at.isoformat(),
        "expires_at": approval.expires_at.isoformat(),
        "nonce": approval.nonce,
        "signature": approval.signature,
        "context": approval.context,
    }


def dump_approval(approval: Approval) -> str:
    return json.dumps(approval_to_dict(approval), indent=2)


def load_approval(path: str | Path) -> Approval:
    return approval_from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def approval_from_dict(data: object) -> Approval:
    if not isinstance(data, dict):
        raise ValueError("an approval must be an object")
    return Approval(
        step_hash=str(data["step_hash"]),
        approver=str(data["approver"]),
        approved_at=datetime.fromisoformat(str(data["approved_at"])),
        expires_at=datetime.fromisoformat(str(data["expires_at"])),
        nonce=str(data["nonce"]),
        signature=str(data["signature"]),
        context=str(data.get("context", "")),
    )
