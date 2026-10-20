"""Navigator: turns a verified diagnosis into a short remediation plan.

The model proposes; plain code validates. Every step must be a Touch action from the
catalog that the gate would accept with an approval, on an inventory host and a
service listed for it. Every step carries a read-only check and the text that output
must contain once the fix has worked, and the catalog's rollback note. The exact
command and its step hash are fixed here, and that is what a person approves.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict

from wheelhouse.crew.assayer import verified_claims
from wheelhouse.crew.incidents import Check, Incident, Plan, PlanStep
from wheelhouse.crew.llm import DATA_RULE, Model, ModelReplyError, as_args, data_tag, fence
from wheelhouse.crew.llm import parse_reply as _parse
from wheelhouse.runtime.runner import Runner
from wheelhouse.safety.tiers import Tier, Verdict

WHO = "navigator"
MAX_PLAN_STEPS = 3
MIN_EXPECT = 3
MAX_EXPECT = 120

SYSTEM = f"""You are Navigator, the planner in Wheelhouse, an IT operations crew.
Given a verified diagnosis, propose the smallest safe fix using catalog actions only.
A named person will review and approve every step before anything runs.

Reply with exactly one JSON object and nothing else, either:
  {{"plan": {{
      "summary": "one plain sentence",
      "risk": "what could go wrong, in one sentence",
      "steps": [{{"host": "...", "action": "...", "args": {{...}}, "why": "...",
                 "verify": {{"action": "...", "args": {{...}},
                            "expect": "text the output contains once fixed"}}}}]}}}}
or, if no listed action is a safe fix:
  {{"no_fix": "why, in one sentence"}}

Rules:
- 1 to {MAX_PLAN_STEPS} steps, each a change action from the list; prefer one step.
- Each step has a read-only verify action on the same host and an 'expect' string of
  {MIN_EXPECT} to {MAX_EXPECT} characters that appears in its output when the fix worked.
  Service changes are checked with service_status on the same service, expecting
  "active (running)" after a start or restart and "inactive (dead)" after a stop.
- Never invent actions, hosts or services. Nothing can delete or purge data.
- {DATA_RULE}"""


# Which read-only check proves each change worked, and which arguments it must share.
# A Touch action without an entry here cannot be planned, so a check cannot be chosen
# to pass regardless of the outcome.
VERIFY_WITH: dict[str, tuple[str, tuple[str, ...]]] = {
    "service_start": ("service_status", ("service",)),
    "service_restart": ("service_status", ("service",)),
    "service_stop": ("service_status", ("service",)),
}
# For these the expected result is fixed, not chosen by the model, and Helmsman checks it
# by parsing the systemd state rather than searching for text.
FIXED_EXPECT: dict[str, str] = {
    "service_start": "active (running)",
    "service_restart": "active (running)",
    "service_stop": "inactive (dead)",
}


def check_problem(
    action: str, args: dict[str, str], verify_action: str, verify_args: dict[str, str], expect: str
) -> str | None:
    """Why a step's check could not prove the step worked, or None if it can."""
    rule = VERIFY_WITH.get(action)
    if rule is None:
        return f"no check is defined for '{action}'"
    want_action, shared = rule
    if verify_action != want_action:
        return f"'{action}' must be checked with '{want_action}'"
    if verify_args != {k: args.get(k, "") for k in shared}:
        return f"the check must use the same {', '.join(shared)} as the step"
    text = expect.strip().casefold()
    fixed = FIXED_EXPECT.get(action)
    if fixed is not None and text != fixed:
        return f"'{action}' must expect '{fixed}'"
    if not MIN_EXPECT <= len(text) <= MAX_EXPECT:
        return f"'expect' must be {MIN_EXPECT} to {MAX_EXPECT} characters"
    if any(text in v.casefold() for v in verify_args.values()):
        return "'expect' must not be part of the check's own arguments"
    return None


class _Verify(BaseModel):
    model_config = ConfigDict(extra="ignore")
    action: str
    args: dict[str, Any] | None = None
    expect: str


class _Step(BaseModel):
    model_config = ConfigDict(extra="ignore")
    host: str
    action: str
    args: dict[str, Any] | None = None
    why: str = ""
    verify: _Verify


class _Plan(BaseModel):
    model_config = ConfigDict(extra="ignore")
    summary: str
    risk: str = ""
    steps: list[_Step]


class _Reply(BaseModel):
    model_config = ConfigDict(extra="ignore")
    plan: _Plan | None = None
    no_fix: str | None = None


class Navigator:
    def __init__(self, runner: Runner, model: Model) -> None:
        self.runner = runner
        self.model = model

    def _actions(self) -> list[dict[str, Any]]:
        return [
            {
                "action": s.name,
                "tier": s.tier.value,
                "description": s.description,
                "args": {k: p.description for k, p in s.params.items()},
                **({"rollback": s.rollback_note} if s.rollback_note else {}),
            }
            for s in self.runner.lockkeeper.catalog.specs()
            if s.tier in (Tier.LOOK, Tier.TOUCH)
        ]

    def _prompt(self, incident: Incident, problems: list[str]) -> str:
        assert incident.diagnosis is not None and incident.verification is not None
        good = verified_claims(incident.diagnosis, incident.verification)
        cited = {e for c in good for e in c.evidence}
        evidence = [e for e in incident.evidence if e.id in cited]
        findings = "\n".join(f"- {c.text} (evidence {', '.join(c.evidence)})" for c in good)
        # Claim text is model output about host output: fenced like the evidence itself.
        tag = data_tag(incident.title, findings, *(e.output for e in evidence))
        blocks = "\n\n".join(
            fence(tag, f'id="{e.id}" host="{e.host}" action="{e.action}"', e.output)
            for e in evidence
        )
        hosts = {
            n: {"role": h.role, "services": list(h.services)}
            for n, h in self.runner.inventory.hosts.items()
        }
        parts = [
            f"Incident on host {incident.host} ({incident.kind}, {incident.subject}):",
            fence(tag, 'kind="title"', incident.title),
            "Verified findings:",
            fence(tag, 'kind="findings"', findings),
            f"Hosts: {json.dumps(hosts)}",
            f"Catalog actions: {json.dumps(self._actions())}",
            "Evidence behind the findings:",
            blocks,
        ]
        if problems:
            parts.append(
                "Your previous plan was rejected by Wheelhouse's checks:\n- "
                + "\n- ".join(problems)
                + "\nFix these problems."
            )
        return "\n\n".join(parts)

    def _validate(self, draft: _Plan) -> tuple[Plan | None, list[str]]:
        problems: list[str] = []
        if not 1 <= len(draft.steps) <= MAX_PLAN_STEPS:
            return None, [f"a plan has 1 to {MAX_PLAN_STEPS} steps"]
        specs = {s.name: s for s in self.runner.lockkeeper.catalog.specs()}
        steps: list[PlanStep] = []
        seen: set[str] = set()
        for n, st in enumerate(draft.steps, 1):
            where = f"step {n}"
            spec = specs.get(st.action)
            args = as_args(st.args)
            vargs = as_args(st.verify.args)
            if spec is None or spec.tier is not Tier.TOUCH:
                problems.append(f"{where}: '{st.action}' is not a change action in the catalog")
                continue
            if args is None or vargs is None:
                problems.append(f"{where}: args must be flat objects of text values")
                continue
            gate = self.runner.preview(st.host, st.action, args)
            if gate.verdict is not Verdict.NEEDS_APPROVAL or not gate.step_hash:
                problems.append(f"{where}: the gate refuses it ({gate.reason})")
                continue
            if gate.step_hash in seen:
                problems.append(f"{where}: repeats an earlier step")
                continue
            vspec = specs.get(st.verify.action)
            if vspec is None or vspec.tier is not Tier.LOOK:
                problems.append(f"{where}: verify must be a read-only catalog action")
                continue
            expect = st.verify.expect.strip()
            bad_check = check_problem(st.action, args, st.verify.action, vargs, expect)
            if bad_check:
                problems.append(f"{where}: {bad_check}")
                continue
            vgate = self.runner.preview(st.host, st.verify.action, vargs)
            if vgate.verdict is not Verdict.RUN:
                problems.append(f"{where}: verify action is refused ({vgate.reason})")
                continue
            seen.add(gate.step_hash)
            steps.append(
                PlanStep(
                    host=st.host,
                    action=st.action,
                    args=args,
                    why=st.why[:500],
                    argv=list(gate.argv),
                    step_hash=gate.step_hash,
                    rollback=spec.rollback_note or "no rollback note in the catalog",
                    verify=Check(action=st.verify.action, args=vargs, expect=expect),
                )
            )
        if problems:
            return None, problems
        return Plan(summary=draft.summary[:500], risk=draft.risk[:500], steps=steps), []

    def plan(self, incident: Incident) -> Plan | None:
        """A validated plan, or None (the reason is logged on the incident)."""
        problems: list[str] = []
        for _attempt in range(2):
            try:
                text = self.model.ask(incident, WHO, SYSTEM, self._prompt(incident, problems))
                reply = _parse(text, _Reply)
            except ModelReplyError as err:
                problems = [f"reply could not be used: {err}"]
                incident.log(WHO, problems[0])
                continue
            if reply.no_fix is not None and reply.plan is None:
                incident.log(WHO, f"no safe fix proposed: {reply.no_fix[:300]}")
                return None
            if reply.plan is None:
                problems = ["reply had neither 'plan' nor 'no_fix'"]
                continue
            plan, problems = self._validate(reply.plan)
            if plan is not None:
                incident.log(WHO, f"plan: {plan.summary[:200]}")
                return plan
            incident.log(WHO, "plan rejected by checks: " + "; ".join(problems)[:400])
        return None
