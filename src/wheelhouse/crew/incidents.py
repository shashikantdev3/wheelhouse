"""Incidents and the file store that holds them.

One JSON file per incident in the inventory's state folder. Every change goes through
IncidentStore.update, which holds a file lock, re-reads the file, applies the change and
replaces the file atomically, so the watch loop and the approval console can work on the
same incident without losing each other's writes.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from filelock import FileLock
from pydantic import BaseModel, ConfigDict, Field

INCIDENT_ID = re.compile(r"INC-\d{8}-\d{6}-[0-9a-f]{6}")


def utcnow() -> datetime:
    return datetime.now(UTC)


class Status(StrEnum):
    OPEN = "open"
    """Detected; not investigated yet."""
    INVESTIGATING = "investigating"
    NEEDS_HUMAN = "needs_human"
    """Wheelhouse could not reach a verified diagnosis or a valid plan. A person takes over."""
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    RESOLVED = "resolved"
    FAILED = "failed"
    """A step or its check failed. Nothing more runs; a person takes over."""


ACTIVE = frozenset(
    {
        Status.OPEN,
        Status.INVESTIGATING,
        Status.NEEDS_HUMAN,
        Status.AWAITING_APPROVAL,
        Status.APPROVED,
        Status.EXECUTING,
    }
)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Signal(_Model):
    kind: str
    host: str
    subject: str
    detail: str
    severity: str = "medium"

    @property
    def fingerprint(self) -> str:
        return f"{self.host}:{self.kind}:{self.subject}"


class Evidence(_Model):
    id: str
    host: str
    action: str
    args: dict[str, str] = {}
    status: str
    """ok, failed, timeout, error (it ran) or refused (the gate said no)."""
    exit_code: int | None = None
    output: str
    """What the agents saw: the command output, shortened if long."""
    output_sha256: str
    """Hash of the full output as it came back from the host."""
    decision_id: str | None = None
    """Ledger id of the gate decision behind this evidence."""
    collected_by: str
    at: datetime = Field(default_factory=utcnow)

    @property
    def ran(self) -> bool:
        return self.status != "refused"


class Claim(_Model):
    text: str
    evidence: list[str]
    quote: str


class ClaimCheck(_Model):
    role: str
    """root_cause or supporting-N"""
    text: str
    ok: bool
    problem: str | None = None


class Diagnosis(_Model):
    summary: str
    root_cause: Claim
    supporting: list[Claim] = []
    confidence: str = "medium"


class Verification(_Model):
    verified: bool
    checks: list[ClaimCheck]


class Check(_Model):
    action: str
    args: dict[str, str] = {}
    expect: str


class PlanStep(_Model):
    host: str
    action: str
    args: dict[str, str] = {}
    why: str
    argv: list[str]
    step_hash: str
    rollback: str
    verify: Check


class Plan(_Model):
    summary: str
    risk: str
    steps: list[PlanStep]

    def digest(self) -> str:
        """Identifies exactly what a person was shown, so a changed plan is never approved."""
        body = json.dumps([s.model_dump(mode="json") for s in self.steps], sort_keys=True)
        return hashlib.sha256(body.encode()).hexdigest()


class StepResult(_Model):
    step_hash: str
    ran: bool
    status: str
    verified: bool
    detail: str
    decision_id: str | None = None


class AgentUsage(_Model):
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    cost_known: bool = True


class Event(_Model):
    at: datetime = Field(default_factory=utcnow)
    who: str
    what: str


class Incident(_Model):
    id: str
    fingerprint: str
    host: str
    kind: str
    subject: str
    title: str
    severity: str
    status: Status = Status.OPEN
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    signals: list[Signal] = []
    evidence: list[Evidence] = []
    diagnosis: Diagnosis | None = None
    verification: Verification | None = None
    plan: Plan | None = None
    approvals: dict[str, dict[str, Any]] = {}
    """step_hash -> signed approval (see safety.approval_io)."""
    results: list[StepResult] = []
    usage: dict[str, AgentUsage] = {}
    investigations: int = 0
    """How many times an investigation was started; capped so a crash cannot loop."""
    events: list[Event] = []

    def log(self, who: str, what: str) -> None:
        self.events.append(Event(who=who, what=what[:500]))

    def next_evidence_id(self) -> str:
        return f"E{len(self.evidence) + 1}"

    def evidence_by_id(self) -> dict[str, Evidence]:
        return {e.id: e for e in self.evidence}


def new_incident_id(now: datetime | None = None) -> str:
    moment = (now or utcnow()).astimezone(UTC)
    return f"INC-{moment:%Y%m%d-%H%M%S}-{secrets.token_hex(3)}"


class IncidentStore:
    """Files are readable by their owner only: they hold host output and approvals."""

    def __init__(self, folder: str | Path) -> None:
        self.folder = Path(folder) / "incidents"
        self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name == "posix":
            os.chmod(self.folder, 0o700)
        self._lock = FileLock(str(self.folder / ".store.lock"))
        self.unreadable: list[str] = []

    def _path(self, incident_id: str) -> Path:
        if not isinstance(incident_id, str) or not INCIDENT_ID.fullmatch(incident_id):
            raise KeyError("not an incident id")
        return self.folder / f"{incident_id}.json"

    def _write(self, incident: Incident) -> None:
        incident.updated_at = utcnow()
        path = self._path(incident.id)
        tmp = path.with_suffix(f".{secrets.token_hex(4)}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(incident.model_dump_json(indent=2))
        os.replace(tmp, path)

    @contextmanager
    def locked(self) -> Iterator[None]:
        with self._lock:
            yield

    def create(self, incident: Incident) -> Incident:
        with self._lock:
            if self._path(incident.id).exists():
                raise FileExistsError(incident.id)
            self._write(incident)
        return incident

    def get(self, incident_id: str) -> Incident:
        path = self._path(incident_id)
        if not path.exists():
            raise KeyError(incident_id)
        return Incident.model_validate_json(path.read_text(encoding="utf-8"))

    def all(self) -> list[Incident]:
        """Every readable incident, newest first. Unreadable files are skipped and listed
        in self.unreadable, so one damaged file cannot stop the watch loop."""
        found = []
        bad = []
        for p in sorted(self.folder.glob("INC-*.json")):
            if not INCIDENT_ID.fullmatch(p.stem):
                continue
            try:
                found.append(Incident.model_validate_json(p.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                bad.append(p.name)
        self.unreadable = bad
        return sorted(found, key=lambda i: i.created_at, reverse=True)

    def update(self, incident_id: str, change: Callable[[Incident], None]) -> Incident:
        """Apply a change to the latest copy of an incident, under the store lock."""
        with self._lock:
            incident = self.get(incident_id)
            change(incident)
            self._write(incident)
            return incident
