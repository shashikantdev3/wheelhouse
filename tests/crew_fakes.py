"""A small simulated estate and a scripted model, for testing the crew without SSH or
a real model."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from wheelhouse.crew import IncidentStore
from wheelhouse.ledger import Ledger
from wheelhouse.providers.base import Completion, Usage
from wheelhouse.runtime import CommandResult, Host, Inventory, Limits, Runner
from wheelhouse.safety import RenderedAction

from tests.keys import LEDGER_KEY, SHASHIKANT, authority

DF_OK = """Filesystem      Size  Used Avail Use% Mounted on
overlay          59G   20G   37G  36% /
tmpfs            64M     0   64M   0% /dev
"""

DF_FULL = """Filesystem      Size  Used Avail Use% Mounted on
overlay          59G   57G  2.0G  97% /
tmpfs            64M     0   64M   0% /dev
"""


def status_text(service: str, running: bool) -> str:
    active = (
        "active (running) since Mon 2026-10-19 18:00:00 UTC; 5min ago"
        if running
        else "inactive (dead) since Mon 2026-10-19 18:04:10 UTC; 1min ago"
    )
    return (
        f"* {service}.service - {service}\n"
        f"     Loaded: loaded (/usr/lib/systemd/system/{service}.service; enabled)\n"
        f"     Active: {active}\n"
    )


class Estate:
    """Fake hosts. nginx on web01 can be stopped and started; logs say what happened."""

    def __init__(self) -> None:
        self.running = {("web01", "nginx"): True}
        self.disk = {"web01": DF_OK}
        self.unreachable: set[str] = set()
        self.start_works = True
        self.calls: list[tuple[str, tuple[str, ...]]] = []
        self.log_extra = ""

    def run(self, name: str, host: Host, action: RenderedAction) -> CommandResult:
        self.calls.append((name, action.argv))
        if name in self.unreachable:
            return CommandResult("failed", 255, b"ssh: connect to host: Connection refused", 3)
        argv = action.argv
        if action.name == "service_status":
            up = self.running.get((name, argv[-1]), False)
            return CommandResult(
                "ok" if up else "failed", 0 if up else 3, status_text(argv[-1], up).encode(), 4
            )
        if action.name == "disk_usage":
            return CommandResult("ok", 0, self.disk.get(name, DF_OK).encode(), 4)
        if action.name == "service_logs":
            text = (
                "Oct 19 18:04:10 web01 systemd[1]: Stopping nginx.service...\n"
                "Oct 19 18:04:10 web01 systemd[1]: nginx.service: Deactivated successfully.\n"
                "Oct 19 18:04:10 web01 systemd[1]: Stopped nginx.service.\n" + self.log_extra
            )
            return CommandResult("ok", 0, text.encode(), 4)
        if action.name in ("service_start", "service_restart"):
            if self.start_works:
                self.running[(name, argv[-1])] = True
            return CommandResult("ok", 0, b"", 30)
        return CommandResult("ok", 0, b"fine\n", 2)


class ScriptedModel:
    """Returns prepared replies in order and remembers every prompt."""

    name = "scripted"

    def __init__(self, replies: list[str | dict[str, object] | Callable[[str], str]]) -> None:
        self.replies = list(replies)
        self.prompts: list[tuple[str, str]] = []

    def complete(self, system: str, user: str, max_tokens: int = 512) -> Completion:
        self.prompts.append((system, user))
        if not self.replies:
            raise AssertionError("the model was asked more often than scripted")
        reply = self.replies.pop(0)
        if callable(reply):
            text = reply(user)
        elif isinstance(reply, dict):
            text = json.dumps(reply)
        else:
            text = reply
        return Completion(text, Usage("scripted", "scripted-1", 100, 20, 0.0001, "computed"), 5)


def make_runner(tmp_path: Path, estate: Estate) -> Runner:
    inv = Inventory(
        known_hosts=tmp_path / "known_hosts",
        ledger=tmp_path / "ledger.jsonl",
        state=tmp_path / "state",
        limits=Limits(actions_per_minute=600),
        approvers={"shashikant": SHASHIKANT.public_text},
        hosts={
            "web01": Host(
                address="10.0.0.11",
                user="wheelhouse",
                identity_file=tmp_path / "id",
                role="web",
                services=("nginx",),
            )
        },
    )
    return Runner(inv, estate, Ledger(inv.ledger), authority=authority(), key=LEDGER_KEY)


def make_store(runner: Runner) -> IncidentStore:
    return IncidentStore(runner.inventory.state)


# Replies a good model would give for "nginx stopped on web01".
NEXT_LOGS = {
    "next": {
        "host": "web01",
        "action": "service_logs",
        "args": {"service": "nginx", "lines": "50"},
        "why": "see why it stopped",
    }
}
DIAGNOSIS = {
    "diagnosis": {
        "summary": "nginx on web01 was stopped cleanly and has not been started again.",
        "root_cause": {
            "text": "systemd stopped nginx and nothing restarted it",
            "evidence": ["E2"],
            "quote": "Stopped nginx.service.",
        },
        "supporting": [
            {
                "text": "nginx is inactive",
                "evidence": ["E1"],
                "quote": "Active: inactive (dead)",
            }
        ],
        "confidence": "high",
    }
}
PLAN = {
    "plan": {
        "summary": "Start nginx on web01.",
        "risk": "If the configuration is broken, nginx will fail to start.",
        "steps": [
            {
                "host": "web01",
                "action": "service_start",
                "args": {"service": "nginx"},
                "why": "nginx is stopped",
                "verify": {
                    "action": "service_status",
                    "args": {"service": "nginx"},
                    "expect": "active (running)",
                },
            }
        ],
    }
}
