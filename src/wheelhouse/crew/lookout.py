"""Lookout: sweeps the inventory with read-only probes and opens incidents.

System 1, rules only: probe output is parsed by plain code (systemd state, disk use),
so detection is cheap, deterministic and testable. No model is called here. A learned
decision model for triage is planned (see decision 0008); it will sit behind the same
interface and only be asked when the rules are unsure.

Deduplication: one active incident per fingerprint (host, kind, subject). A fingerprint
that was rejected or failed recently is not reopened during a cool-down, so a person is
not asked about the same thing every minute. An incident that clears on its own before
anything was approved is closed as recovered.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta

from wheelhouse.crew.evidence import evidence_from
from wheelhouse.crew.incidents import (
    ACTIVE,
    Incident,
    IncidentStore,
    Signal,
    Status,
    new_incident_id,
    utcnow,
)
from wheelhouse.runtime.inventory import Host
from wheelhouse.runtime.runner import Runner, RunResult

WHO = "lookout"
DISK_WARN = 90
DISK_HIGH = 95
_ACTIVE_LINE = re.compile(r"^\s*Active:\s+(\S+)(?:\s+\(([^)]*)\))?.*$", re.MULTILINE)
_SKIP_FS = ("tmpfs", "devtmpfs", "shm", "udev", "none", "proc", "sysfs", "cgroup")

# A parser returns the fingerprint prefixes it was able to check, and the signals found.
Parsed = tuple[list[str], list[Signal]]


def service_state(text: str) -> tuple[str, str, bool] | None:
    """(state, sub-state, crash loop) from the unit header of `systemctl status`, or
    None if there is no Active line. Journal lines after the header are ignored: log
    text, which anyone who can write a log controls, must not decide health."""
    header = re.split(r"\n\s*\n", text, maxsplit=1)[0]
    m = _ACTIVE_LINE.search(header)
    if m is None:
        return None
    sub = m.group(2) or ""
    crash = "auto-restart" in sub or re.search(r"Result: (?!success)", m.group(0)) is not None
    return m.group(1), sub, crash


def parse_service_status(host: str, service: str, text: str) -> Parsed:
    prefix = f"{host}:service_down:{service}"
    text = re.split(r"\n\s*\n", text, maxsplit=1)[0]
    m = _ACTIVE_LINE.search(text)
    if m is None:
        if "could not be found" in text:
            sig = Signal(
                kind="service_down",
                host=host,
                subject=service,
                detail=f"unit {service} could not be found",
                severity="high",
            )
            return [prefix], [sig]
        return [], []
    state, sub = m.group(1), (m.group(2) or "")
    line = m.group(0).strip()
    crash_loop = "auto-restart" in sub or re.search(r"Result: (?!success)", line) is not None
    if state in ("active", "activating", "reloading") and not crash_loop:
        return [prefix], []
    # Timer-driven jobs are inactive between runs; only a failed run is a problem.
    if "TriggeredBy:" in text and state != "failed":
        return [prefix], []
    severity = "high" if state == "failed" or sub == "failed" or crash_loop else "medium"
    return [prefix], [
        Signal(kind="service_down", host=host, subject=service, detail=line, severity=severity)
    ]


def parse_disk_usage(host: str, text: str) -> Parsed:
    lines = text.strip().splitlines()
    if not lines or not lines[0].lstrip().startswith("Filesystem"):
        return [], []
    signals: list[Signal] = []
    seen_devices: set[str] = set()
    for line in lines[1:]:
        cols = line.split()
        if len(cols) < 6 or not cols[4].endswith("%"):
            continue
        device, use, mount = cols[0], cols[4], cols[-1]
        if device.startswith(_SKIP_FS) or device in seen_devices:
            continue
        try:
            pct = int(use.rstrip("%"))
        except ValueError:
            continue
        seen_devices.add(device)
        if pct >= DISK_WARN:
            signals.append(
                Signal(
                    kind="disk_full",
                    host=host,
                    subject=mount,
                    detail=line.strip(),
                    severity="high" if pct >= DISK_HIGH else "medium",
                )
            )
    return [f"{host}:disk_full:"], signals


@dataclass
class _Found:
    signal: Signal
    res: RunResult
    action: str
    args: dict[str, str]


@dataclass
class SweepReport:
    opened: list[str] = field(default_factory=list)
    still_open: list[str] = field(default_factory=list)
    recovered: list[str] = field(default_factory=list)
    cooling_down: list[str] = field(default_factory=list)
    unreachable: list[str] = field(default_factory=list)


def _title(sig: Signal) -> str:
    if sig.kind == "service_down":
        return f"{sig.subject} is not running on {sig.host}"
    if sig.kind == "disk_full":
        return f"disk {sig.subject} is nearly full on {sig.host}"
    if sig.kind == "host_unreachable":
        return f"{sig.host} cannot be reached"
    return f"{sig.kind} on {sig.host}"


class Lookout:
    def __init__(
        self, runner: Runner, store: IncidentStore, cooldown: timedelta = timedelta(hours=1)
    ) -> None:
        self.runner = runner
        self.store = store
        self.cooldown = cooldown

    def _probes(
        self, name: str, host: Host
    ) -> list[tuple[str, dict[str, str], Callable[[str], Parsed]]]:
        probes: list[tuple[str, dict[str, str], Callable[[str], Parsed]]] = []
        for svc in host.services:
            probes.append(
                (
                    "service_status",
                    {"service": svc},
                    lambda text, s=svc: parse_service_status(name, s, text),  # type: ignore[misc]
                )
            )
        probes.append(("disk_usage", {}, lambda text: parse_disk_usage(name, text)))
        return probes

    def sweep(self) -> SweepReport:
        report = SweepReport()
        checked: list[str] = []
        found: list[_Found] = []
        self.runner.principal = WHO
        for name, host in self.runner.inventory.hosts.items():
            for action, args, parse in self._probes(name, host):
                res = self.runner.request(name, action, args)
                if res.result is None:
                    continue
                if res.result.status in ("timeout", "error") or res.result.exit_code == 255:
                    sig = Signal(
                        kind="host_unreachable",
                        host=name,
                        subject="ssh",
                        detail=f"{action}: {res.result.status} (exit {res.result.exit_code})",
                        severity="high",
                    )
                    found.append(_Found(sig, res, action, args))
                    report.unreachable.append(name)
                    break
                checked.append(f"{name}:host_unreachable:ssh")
                prefixes, signals = parse(res.result.output.decode("utf-8", "replace"))
                checked.extend(prefixes)
                found.extend(_Found(s, res, action, args) for s in signals)
        self._reconcile(found, checked, report)
        return report

    def _reconcile(self, found: list[_Found], checked: list[str], report: SweepReport) -> None:
        now = utcnow()
        current = {f.signal.fingerprint for f in found}
        with self.store.locked():
            existing = self.store.all()
            active = {i.fingerprint: i for i in existing if i.status in ACTIVE}
            cooling = {
                i.fingerprint
                for i in existing
                if i.status in (Status.FAILED, Status.REJECTED)
                and now - i.updated_at < self.cooldown
            }
            for f in found:
                fp = f.signal.fingerprint
                if fp in active:
                    report.still_open.append(active[fp].id)
                    continue
                if fp in cooling:
                    report.cooling_down.append(fp)
                    continue
                incident = Incident(
                    id=new_incident_id(now),
                    fingerprint=fp,
                    host=f.signal.host,
                    kind=f.signal.kind,
                    subject=f.signal.subject,
                    title=_title(f.signal),
                    severity=f.signal.severity,
                    signals=[f.signal],
                )
                incident.evidence.append(
                    evidence_from(f.res, "E1", f.signal.host, f.action, f.args, WHO)
                )
                incident.log(WHO, f"detected: {f.signal.detail}")
                self.store.create(incident)
                active[fp] = incident
                report.opened.append(incident.id)
            for fp, incident in active.items():
                if fp in current or not any(fp.startswith(p) for p in checked):
                    continue
                if incident.status in (Status.OPEN, Status.NEEDS_HUMAN, Status.AWAITING_APPROVAL):

                    def recover(i: Incident) -> None:
                        i.status = Status.RESOLVED
                        i.log(WHO, "recovered without a change; nothing was run")

                    self.store.update(incident.id, recover)
                    report.recovered.append(incident.id)
