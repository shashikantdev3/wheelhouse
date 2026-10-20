"""The watch loop: Lookout, then Diver, Assayer and Navigator for new incidents, and
Helmsman for incidents a person has approved.

Separation of duties: this loop can run changes but cannot approve them (it holds no
approver key). The approval console can sign approvals but never runs anything.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta

from wheelhouse.crew import assayer
from wheelhouse.crew.diver import Diver
from wheelhouse.crew.helmsman import Helmsman
from wheelhouse.crew.incidents import Incident, IncidentStore, Status, utcnow
from wheelhouse.crew.llm import Model
from wheelhouse.crew.lookout import Lookout, SweepReport
from wheelhouse.crew.navigator import Navigator
from wheelhouse.runtime.runner import Runner

STALE_INVESTIGATION = timedelta(minutes=15)
STALE_EXECUTION = timedelta(minutes=30)
MAX_INVESTIGATIONS = 2


@dataclass
class PassReport:
    sweep: SweepReport
    investigated: dict[str, str] = field(default_factory=dict)
    executed: dict[str, str] = field(default_factory=dict)


class Crew:
    def __init__(
        self,
        runner: Runner,
        store: IncidentStore,
        model: Model | None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.runner = runner
        self.store = store
        self.model = model
        self.lookout = Lookout(runner, store)
        self.helmsman = Helmsman(runner, store, sleep=sleep)

    def _claim(self, incident_id: str) -> Incident | None:
        claimed: list[Incident] = []

        def change(i: Incident) -> None:
            stale = (
                i.status is Status.INVESTIGATING and utcnow() - i.updated_at > STALE_INVESTIGATION
            )
            if not (i.status is Status.OPEN or stale):
                return
            if i.investigations >= MAX_INVESTIGATIONS:
                i.status = Status.NEEDS_HUMAN
                i.log("crew", "investigation did not finish twice; a person takes over")
                return
            i.investigations += 1
            i.status = Status.INVESTIGATING
            claimed.append(i)

        self.store.update(incident_id, change)
        return claimed[0] if claimed else None

    def investigate(self, incident_id: str) -> str:
        """Diver, then Assayer, then Navigator. Returns the incident's new status."""
        if self.model is None:
            return "skipped: no model configured"
        incident = self._claim(incident_id)
        if incident is None:
            return "skipped: not open"
        try:
            new_status = self._work(incident)
        except Exception as err:  # noqa: BLE001 - one incident must not stop the loop
            incident.log(
                "crew", f"investigation crashed ({type(err).__name__}); a person takes over"
            )
            new_status = Status.NEEDS_HUMAN

        def finish(i: Incident) -> None:
            if i.status is not Status.INVESTIGATING:
                i.log("crew", f"investigation finished after the incident became {i.status}")
                return
            i.evidence = incident.evidence
            i.diagnosis = incident.diagnosis
            i.verification = incident.verification
            i.plan = incident.plan
            i.usage = incident.usage
            i.events = incident.events
            i.status = new_status

        return self.store.update(incident_id, finish).status.value

    def _work(self, incident: Incident) -> Status:
        assert self.model is not None
        new_status = Status.NEEDS_HUMAN
        diagnosis = Diver(self.runner, self.model).investigate(incident)
        if diagnosis is None:
            incident.log("assayer", "no diagnosis to check; a person takes over")
        else:
            incident.diagnosis = diagnosis
            incident.verification = assayer.verify(diagnosis, incident.evidence)
            failed = [c for c in incident.verification.checks if not c.ok]
            for c in failed:
                incident.log("assayer", f"{c.role} not verified: {c.problem}")
            if not incident.verification.verified:
                incident.log("assayer", "root cause not verified; no plan will be made")
            else:
                incident.log("assayer", "root cause verified against the evidence")
                plan = Navigator(self.runner, self.model).plan(incident)
                if plan is not None:
                    incident.plan = plan
                    new_status = Status.AWAITING_APPROVAL
        return new_status

    def _release_stuck_executions(self) -> None:
        """An execution that never finished (a crash or a kill) goes to a person, marked
        as possibly run, instead of blocking new incidents for the same fingerprint."""
        for incident in self.store.all():
            if incident.status is not Status.EXECUTING:
                continue
            if utcnow() - incident.updated_at <= STALE_EXECUTION:
                continue

            def release(i: Incident) -> None:
                if i.status is Status.EXECUTING and utcnow() - i.updated_at > STALE_EXECUTION:
                    i.status = Status.FAILED
                    i.approvals = {}
                    i.log("crew", "execution never finished; steps may have run; check by hand")

            self.store.update(incident.id, release)

    def run_once(self) -> PassReport:
        self._release_stuck_executions()
        report = PassReport(sweep=self.lookout.sweep())
        for incident in self.store.all():
            if incident.status in (Status.OPEN, Status.INVESTIGATING):
                report.investigated[incident.id] = self.investigate(incident.id)
        for incident in self.store.all():
            if incident.status is Status.APPROVED:
                try:
                    done = self.helmsman.execute(incident.id)
                except Exception as err:  # noqa: BLE001 - keep the loop alive
                    report.executed[incident.id] = f"error ({type(err).__name__})"
                    continue
                report.executed[incident.id] = done.status.value if done else "skipped"
        return report
