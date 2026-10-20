"""Turning gated runs into evidence the crew can cite."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

from wheelhouse.crew.incidents import Evidence, Incident
from wheelhouse.crew.llm import shorten
from wheelhouse.runtime.runner import Runner, RunResult


def run_look(
    runner: Runner,
    incident: Incident,
    who: str,
    host: str,
    action: str,
    args: Mapping[str, str] | None = None,
) -> Evidence:
    """Run a read-only action through the gate as `who` and add the result as evidence.
    A refusal becomes evidence too, so the agent sees why and the record is complete."""
    runner.principal = who
    res = runner.request(host, action, dict(args or {}))
    ev = evidence_from(res, incident.next_evidence_id(), host, action, args, who)
    incident.evidence.append(ev)
    return ev


def evidence_from(
    res: RunResult,
    evidence_id: str,
    host: str,
    action: str,
    args: Mapping[str, str] | None,
    who: str,
) -> Evidence:
    if res.result is None:
        text = f"not run: {res.decision.verdict.value}: {res.decision.reason}"
        raw = text.encode()
        status, code = "refused", None
    else:
        raw = res.result.output
        text = raw.decode("utf-8", "replace")
        status, code = res.result.status, res.result.exit_code
    return Evidence(
        id=evidence_id,
        host=host,
        action=action,
        args=dict(args or {}),
        status=status,
        exit_code=code,
        output=shorten(text),
        output_sha256=hashlib.sha256(raw).hexdigest(),
        decision_id=res.decision_id,
        collected_by=who,
    )
