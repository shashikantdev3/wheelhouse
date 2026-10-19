"""Builders for the records Wheelhouse writes: gate decisions and executions.

Mapping to the ProvenKit AI Decision Record (AIDR 0.1):
- outcome.action: RUN -> allow, NEEDS_APPROVAL -> require_approval, REFUSED -> deny.
- control: the Lockkeeper policy (catalog hash), enforcement point and rules.
- lineage.tool: the catalog action and its side effect; lineage.outputs holds hashes of
  the argument list and, for executions, of the output. Content is never stored.
- origin.principal ids are pseudonymous (HMAC with a deployment key when one is set).
- labels carry the host, the step hash and, when an approval is used, its nonce.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import UTC, datetime
from typing import Any

import rfc8785

from wheelhouse import __version__
from wheelhouse.safety.approvals import Approval
from wheelhouse.safety.lockkeeper import Decision
from wheelhouse.safety.tiers import Tier, Verdict

POLICY_ID = "wheelhouse-lockkeeper"
POLICY_VERSION = "1.0.0"
RULES = ["catalog", "guard", "tier", "approval", "single-use"]

_ACTION = {
    Verdict.RUN: "allow",
    Verdict.NEEDS_APPROVAL: "require_approval",
    Verdict.REFUSED: "deny",
}
_SIDE_EFFECT = {Tier.LOOK: "read", Tier.TOUCH: "write", Tier.NEVER: "irreversible"}


def now_rfc3339(now: datetime | None = None) -> str:
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def sha256_tag(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _clean(text: str, limit: int = 256) -> str:
    """Text safe for canonical JSON: lone surrogates replaced, length capped."""
    return text.encode("utf-8", "replace").decode("utf-8")[:limit]


def pseudonym(name: str, key: bytes | None) -> tuple[str, str]:
    """A stable pseudonymous id for a person or agent, and the scheme used. The key used
    here is derived from the deployment key, so it differs from the approval-signing key."""
    if key:
        derived = hmac.new(key, b"wheelhouse-pseudonym-v1", hashlib.sha256).digest()
        digest = hmac.new(derived, _clean(name, 1024).encode(), hashlib.sha256).hexdigest()[:32]
        return digest, "hmac-sha256:derived-deployment-key"
    return hashlib.sha256(_clean(name, 1024).encode()).hexdigest()[:32], "sha256"


def _reason_code(decision: Decision) -> str:
    if decision.verdict is Verdict.RUN:
        return "LOOK" if decision.tier is Tier.LOOK else "TOUCH-APPROVED"
    if decision.verdict is Verdict.NEEDS_APPROVAL:
        return "TOUCH-NEEDS-APPROVAL"
    reason = decision.reason
    if reason.startswith("guard:"):
        return "REFUSED-GUARD"
    if reason.startswith("not in the catalog"):
        return "REFUSED-CATALOG"
    if "state-changing" in reason:
        return "REFUSED-TIER"
    return "REFUSED"


def decision_record(
    decision: Decision,
    *,
    policy_hash: str,
    principal: str,
    principal_type: str = "agent",
    agent: str = "wheelhouse-cli",
    key: bytes | None = None,
    approval: Approval | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    pid, scheme = pseudonym(principal, key)
    action = _ACTION[decision.verdict]
    rules_fired: list[dict[str, str]] = []
    if decision.verdict is not Verdict.RUN:
        rules_fired.append(
            {
                "rule_id": _reason_code(decision),
                "action": action,
                "detector": "lockkeeper",
                "detector_version": __version__,
            }
        )
    labels: dict[str, str] = {
        "event": "decision",
        "host": _clean(decision.host),
        "verdict": decision.verdict.value,
        "tier": decision.tier.value,
        # The approver's name stays out of the record; outcome.approval holds a pseudonym.
        "reason": "approved"
        if decision.reason.startswith("approved by")
        else _clean(decision.reason),
    }
    if decision.step_hash:
        labels["step_hash"] = decision.step_hash
    outcome: dict[str, Any] = {
        "action": action,
        "reason_code": _reason_code(decision),
        "severity": {Tier.LOOK: "info", Tier.TOUCH: "medium", Tier.NEVER: "high"}[decision.tier],
    }
    if approval is not None and decision.verdict is Verdict.RUN and decision.tier is Tier.TOUCH:
        approver_id, _ = pseudonym(approval.approver, key)
        outcome["approval"] = {
            "granted_by": approver_id,
            "granted_at": now_rfc3339(approval.approved_at),
        }
        labels["approval_nonce"] = approval.nonce
    outputs = []
    if decision.argv:
        argv_bytes = rfc8785.dumps(list(decision.argv))
        outputs.append(
            {
                "kind": "tool_arguments",
                "content_hash": sha256_tag(argv_bytes),
                "byte_length": len(argv_bytes),
            }
        )
    return {
        "aidr_version": "0.1",
        "decision_id": str(uuid.uuid4()),
        "ts": now_rfc3339(now),
        "stage": "tool_call",
        "outcome": outcome,
        "origin": {
            "principal": {"type": principal_type, "id": pid, "id_scheme": scheme},
            "agent": {"id": agent, "name": agent, "version": __version__},
        },
        "lineage": {
            "outputs": outputs,
            "tool": {
                "name": _clean(decision.action, 200),
                "server": f"ssh://{_clean(decision.host, 200)}",
                "side_effect": _SIDE_EFFECT[decision.tier],
            },
        },
        "control": {
            "policy_id": POLICY_ID,
            "policy_version": POLICY_VERSION,
            "policy_hash": policy_hash,
            "enforcement_point": {"type": "custom", "id": "lockkeeper", "version": __version__},
            "rules_evaluated": RULES,
            "rules_fired": rules_fired,
            "coverage": {"fail_mode": "closed"},
        },
        "temporal": {"model": {"provider": "wheelhouse", "name": "rules", "version": __version__}},
        "labels": labels,
    }


def execution_record(
    decision_id: str,
    decision: Decision,
    *,
    policy_hash: str,
    principal: str,
    exit_code: int | None,
    duration_ms: int,
    output: bytes,
    status: str,
    agent: str = "wheelhouse-cli",
    key: bytes | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """What happened when an allowed action ran. status: ok, failed, timeout, error."""
    pid, scheme = pseudonym(principal, key)
    return {
        "aidr_version": "0.1",
        "decision_id": str(uuid.uuid4()),
        "ts": now_rfc3339(now),
        "stage": "tool_call",
        "outcome": {
            "action": "allow",
            "reason_code": f"EXECUTED-{status.upper()}",
            "severity": "info" if status == "ok" else "medium",
        },
        "origin": {
            "principal": {"type": "agent", "id": pid, "id_scheme": scheme},
            "agent": {"id": agent, "name": agent, "version": __version__},
        },
        "lineage": {
            "outputs": [
                {
                    "kind": "structured",
                    "content_hash": sha256_tag(output),
                    "byte_length": len(output),
                }
            ],
            "tool": {
                "name": _clean(decision.action, 200),
                "server": f"ssh://{_clean(decision.host, 200)}",
                "side_effect": _SIDE_EFFECT[decision.tier],
            },
        },
        "control": {
            "policy_id": POLICY_ID,
            "policy_version": POLICY_VERSION,
            "policy_hash": policy_hash,
            "enforcement_point": {"type": "custom", "id": "helmsman", "version": __version__},
            "coverage": {"fail_mode": "closed"},
            "total_latency_ms": int(duration_ms),
        },
        "temporal": {"model": {"provider": "wheelhouse", "name": "rules", "version": __version__}},
        "labels": {
            "event": "execution",
            "host": _clean(decision.host),
            "status": status,
            "exit_code": "" if exit_code is None else str(exit_code),
            "duration_ms": str(duration_ms),
            "gate_decision_id": decision_id,
        },
    }
