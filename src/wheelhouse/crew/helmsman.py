"""Helmsman: runs approved plan steps, one at a time, and checks each one.

No model. Helmsman holds no signing key: it can only pass on approvals a person
signed, and Lockkeeper checks each one against the step's hash, the approver's public
key, its expiry and single use. After each step, the step's read-only check must show
the expected text (a few tries, because services take a moment to start). If a step is
refused, fails or does not check out, Helmsman stops: later steps do not run, nothing is
retried automatically, and the incident goes to a person.

Every approval must have been given for this incident and this exact plan (its context
is the incident id and the plan digest), so an approval cannot be carried to another
incident, to a changed plan, or to the command line. When Helmsman finishes, approvals
for steps it did not run are deleted.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable

from wheelhouse.crew.evidence import run_look
from wheelhouse.crew.incidents import Incident, IncidentStore, PlanStep, Status, StepResult
from wheelhouse.crew.lookout import service_state
from wheelhouse.crew.navigator import check_problem
from wheelhouse.runtime.runner import Runner
from wheelhouse.safety.approval_io import approval_from_dict

WHO = "helmsman"
CHECK_TRIES = 4
CHECK_WAIT_S = 3.0
_SPACE = re.compile(r"\s+")


def _norm(text: str) -> str:
    return _SPACE.sub(" ", text).strip().casefold()


def check_passes(action: str, expect: str, output: str) -> bool:
    """Whether a step's check output shows the step worked. Service changes are judged
    from the parsed systemd state (not a text search: 'active' is inside 'inactive')."""
    if action in ("service_start", "service_restart"):
        state = service_state(output)
        return state is not None and state[:2] == ("active", "running") and not state[2]
    if action == "service_stop":
        state = service_state(output)
        return state is not None and state[0] in ("inactive", "failed")
    return _norm(expect) in _norm(output)


def approval_context(incident: Incident) -> str:
    """What an approval for this incident's plan is bound to, besides each step's hash."""
    assert incident.plan is not None
    return f"{incident.id}:{incident.plan.digest()}"


class Helmsman:
    def __init__(
        self,
        runner: Runner,
        store: IncidentStore,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.runner = runner
        self.store = store
        self.sleep = sleep

    def _claim(self, incident_id: str) -> Incident | None:
        """Move APPROVED to EXECUTING under the store lock, so it runs once."""
        claimed: list[Incident] = []

        def change(i: Incident) -> None:
            if i.status is Status.APPROVED and i.plan is not None:
                i.status = Status.EXECUTING
                i.log(WHO, "executing the approved plan")
                claimed.append(i)

        self.store.update(incident_id, change)
        return claimed[0] if claimed else None

    def _step(self, incident: Incident, step: PlanStep, context: str) -> StepResult:
        bad_check = check_problem(
            step.action, step.args, step.verify.action, step.verify.args, step.verify.expect
        )
        if bad_check:
            return StepResult(
                step_hash=step.step_hash,
                ran=False,
                status="bad_plan",
                verified=False,
                detail=f"not run: {bad_check}",
            )
        raw = incident.approvals.get(step.step_hash)
        if raw is None:
            return StepResult(
                step_hash=step.step_hash,
                ran=False,
                status="no_approval",
                verified=False,
                detail="no approval for this step",
            )
        try:
            approval = approval_from_dict(raw)
        except (KeyError, ValueError) as err:
            return StepResult(
                step_hash=step.step_hash,
                ran=False,
                status="bad_approval",
                verified=False,
                detail=f"approval could not be read ({type(err).__name__})",
            )
        self.runner.principal = WHO
        res = self.runner.request(step.host, step.action, step.args, approval, context=context)
        if res.result is None:
            return StepResult(
                step_hash=step.step_hash,
                ran=False,
                status="refused",
                verified=False,
                detail=f"{res.decision.verdict.value}: {res.decision.reason}",
                decision_id=res.decision_id,
            )
        if res.result.status != "ok":
            return StepResult(
                step_hash=step.step_hash,
                ran=True,
                status=res.result.status,
                verified=False,
                detail=f"command {res.result.status} (exit {res.result.exit_code})",
                decision_id=res.decision_id,
            )
        for attempt in range(1, CHECK_TRIES + 1):
            ev = run_look(
                self.runner, incident, WHO, step.host, step.verify.action, step.verify.args
            )
            if ev.status in ("ok", "failed") and check_passes(
                step.action, step.verify.expect, ev.output
            ):
                return StepResult(
                    step_hash=step.step_hash,
                    ran=True,
                    status="ok",
                    verified=True,
                    detail=f"check passed ({ev.id}: found '{step.verify.expect}')",
                    decision_id=res.decision_id,
                )
            if attempt < CHECK_TRIES:
                self.sleep(CHECK_WAIT_S)
        return StepResult(
            step_hash=step.step_hash,
            ran=True,
            status="ok",
            verified=False,
            detail=f"check failed: '{step.verify.expect}' not found after {CHECK_TRIES} tries",
            decision_id=res.decision_id,
        )

    def execute(self, incident_id: str) -> Incident | None:
        """Run an approved incident's plan. Returns None if it was not ready to run."""
        incident = self._claim(incident_id)
        if incident is None or incident.plan is None:
            return None
        before = len(incident.evidence)
        context = approval_context(incident)
        results: list[StepResult] = []
        for n, step in enumerate(incident.plan.steps, 1):
            try:
                result = self._step(incident, step, context)
            except Exception as err:  # noqa: BLE001 - a crash must not leave it executing
                result = StepResult(
                    step_hash=step.step_hash,
                    ran=True,
                    status="error",
                    verified=False,
                    detail=f"crashed ({type(err).__name__}); the step may have run",
                )
            results.append(result)
            incident.log(WHO, f"step {n} {step.action} on {step.host}: {result.detail}")
            if not (result.ran and result.verified):
                incident.log(WHO, "stopped; later steps were not run; a person takes over")
                break
        ok = len(results) == len(incident.plan.steps) and all(r.verified for r in results)
        new_evidence = incident.evidence[before:]
        new_events = incident.events

        def finish(i: Incident) -> None:
            i.evidence.extend(new_evidence)
            i.results = results
            i.events = new_events
            i.approvals = {}  # used ones are spent; unused ones must not linger
            i.status = Status.RESOLVED if ok else Status.FAILED

        return self.store.update(incident_id, finish)
