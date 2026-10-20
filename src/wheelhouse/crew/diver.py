"""Diver: investigates an incident with read-only actions and writes a diagnosis.

The model chooses the next Look action; plain code checks that it is a Look action on
an inventory host and runs it through the gate. Diver never passes an approval, so
even a mistake here cannot change anything. The final diagnosis must cite evidence:
every claim names evidence ids and quotes the exact text it relies on, which Assayer
then checks word for word.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict

from wheelhouse.crew.evidence import run_look
from wheelhouse.crew.incidents import Claim, Diagnosis, Incident
from wheelhouse.crew.llm import DATA_RULE, Model, ModelReplyError, as_args, data_tag, fence
from wheelhouse.crew.llm import parse_reply as _parse
from wheelhouse.runtime.runner import Runner
from wheelhouse.safety.tiers import Tier

WHO = "diver"
MAX_STEPS = 6
MAX_BAD_REPLIES = 2

SYSTEM = f"""You are Diver, the investigator in Wheelhouse, an IT operations crew.
You find the root cause of one incident using read-only actions only.

Each turn, reply with exactly one JSON object and nothing else, either:
  {{"next": {{"host": "...", "action": "...", "args": {{...}}, "why": "..."}}}}
to run one more read-only action from the list you are given, or, when you know enough:
  {{"diagnosis": {{
      "summary": "one or two plain sentences",
      "root_cause": {{"text": "...", "evidence": ["E2"], "quote": "exact text from E2"}},
      "supporting": [{{"text": "...", "evidence": ["E1"], "quote": "exact text from E1"}}],
      "confidence": "high|medium|low"}}}}

Rules:
- Use only the actions and hosts listed. You cannot change anything.
- Every claim cites evidence ids and quotes a short exact substring of that evidence
  (copy it character for character, 6 to 300 characters). Claims without an exact quote
  are discarded.
- Be brief: the summary under 300 characters, each claim under 200, at most 3
  supporting claims.
- Prefer the fewest actions. Stay with the incident's host unless the evidence points
  elsewhere. Do not repeat an action you already have.
- If the evidence does not show a cause, say so with confidence "low".
- {DATA_RULE}"""


class _Next(BaseModel):
    model_config = ConfigDict(extra="ignore")
    host: str
    action: str
    args: dict[str, Any] | None = None
    why: str = ""


class _Reply(BaseModel):
    model_config = ConfigDict(extra="ignore")
    next: _Next | None = None
    diagnosis: Diagnosis | None = None


class Diver:
    def __init__(self, runner: Runner, model: Model, max_steps: int = MAX_STEPS) -> None:
        self.runner = runner
        self.model = model
        self.max_steps = max_steps

    def _look_actions(self) -> list[dict[str, Any]]:
        return [
            {
                "action": s.name,
                "description": s.description,
                "args": {k: p.description for k, p in s.params.items()},
            }
            for s in self.runner.lockkeeper.catalog.specs()
            if s.tier is Tier.LOOK
        ]

    def _prompt(self, incident: Incident, note: str) -> str:
        hosts = {
            n: {"role": h.role, "services": list(h.services)}
            for n, h in self.runner.inventory.hosts.items()
        }
        detail = incident.signals[0].detail if incident.signals else ""
        outputs = [e.output for e in incident.evidence]
        tag = data_tag(incident.title, detail, *outputs)
        blocks = "\n\n".join(
            fence(
                tag,
                f'id="{e.id}" host="{e.host}" action="{e.action}" '
                f'args="{json.dumps(e.args)}" status="{e.status}" exit="{e.exit_code}"',
                e.output,
            )
            for e in incident.evidence
        )
        parts = [
            f"Incident on host {incident.host} ({incident.kind}, {incident.subject}):",
            fence(tag, 'kind="title"', incident.title),
            "What Lookout saw:",
            fence(tag, 'kind="detection"', detail),
            f"Hosts: {json.dumps(hosts)}",
            f"Read-only actions you may request: {json.dumps(self._look_actions())}",
            f"Evidence so far ({len(incident.evidence)} items, "
            f"{self.max_steps - self._steps(incident)} actions left):",
            blocks,
        ]
        if note:
            parts.append(f"Note from Wheelhouse: {note}")
        return "\n\n".join(p for p in parts if p)

    @staticmethod
    def _steps(incident: Incident) -> int:
        return sum(1 for e in incident.evidence if e.collected_by == WHO)

    def _check_next(self, incident: Incident, nxt: _Next) -> tuple[dict[str, str] | None, str]:
        spec = next(
            (s for s in self.runner.lockkeeper.catalog.specs() if s.name == nxt.action), None
        )
        if spec is None:
            return None, f"'{nxt.action}' is not in the action list"
        if spec.tier is not Tier.LOOK:
            return None, f"'{nxt.action}' changes state; Diver may only use read-only actions"
        if self.runner.inventory.host(nxt.host) is None:
            return None, f"'{nxt.host}' is not an inventory host"
        args = as_args(nxt.args)
        if args is None:
            return None, "args must be a flat object of text values"
        host = self.runner.inventory.hosts[nxt.host]
        if "service" in args and args["service"] not in host.services:
            return None, f"service '{args['service']}' is not listed for {nxt.host}"
        if "database" in args and args["database"] not in host.databases:
            return None, f"database '{args['database']}' is not listed for {nxt.host}"
        if "target" in args:
            known = set(self.runner.inventory.hosts) | {
                h.address for h in self.runner.inventory.hosts.values()
            }
            if args["target"] not in known:
                return None, "ping targets must be inventory hosts"
        for e in incident.evidence:
            if e.host == nxt.host and e.action == nxt.action and e.args == args:
                return None, f"you already have this as {e.id}; use it"
        return args, ""

    def investigate(self, incident: Incident) -> Diagnosis | None:
        """Adds evidence to the incident and returns a diagnosis, or None if none was
        reached (the reason is logged on the incident)."""
        note = ""
        bad = 0
        while True:
            budget_left = self.max_steps - self._steps(incident)
            if budget_left <= 0 and not note.startswith("No actions left"):
                note = "No actions left. Give your diagnosis now from the evidence you have."
            try:
                text = self.model.ask(incident, WHO, SYSTEM, self._prompt(incident, note))
                reply = _parse(text, _Reply)
            except ModelReplyError as err:
                bad += 1
                incident.log(WHO, f"unusable model reply: {err}")
                if bad > MAX_BAD_REPLIES:
                    return None
                note = f"Your last reply could not be used ({err}). Reply with one JSON object."
                continue
            if reply.diagnosis is not None:
                incident.log(WHO, f"diagnosis: {reply.diagnosis.summary[:200]}")
                return reply.diagnosis
            if reply.next is None:
                bad += 1
                if bad > MAX_BAD_REPLIES:
                    incident.log(WHO, "no diagnosis reached")
                    return None
                note = "Reply with either 'next' or 'diagnosis'."
                continue
            if budget_left <= 0:
                bad += 1
                if bad > MAX_BAD_REPLIES:
                    incident.log(WHO, "action budget used up without a diagnosis")
                    return None
                continue
            args, problem = self._check_next(incident, reply.next)
            if args is None:
                bad += 1
                incident.log(WHO, f"request not run: {problem}")
                if bad > MAX_BAD_REPLIES:
                    return None
                note = problem
                continue
            ev = run_look(self.runner, incident, WHO, reply.next.host, reply.next.action, args)
            incident.log(WHO, f"{ev.id}: {ev.action} on {ev.host} ({ev.status})")
            note = ""


def claims(diagnosis: Diagnosis) -> list[tuple[str, Claim]]:
    """The diagnosis claims with their roles, root cause first."""
    out = [("root_cause", diagnosis.root_cause)]
    out += [(f"supporting-{n}", c) for n, c in enumerate(diagnosis.supporting, 1)]
    return out
