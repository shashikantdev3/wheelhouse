"""Recorded estates: capture what read-only actions return on real hosts, then replay it.

Used for drills: a fault is injected in the lab once, every Look action's output is
recorded, and the crew can then be run against the recording as often as needed (with
a real model, or in CI) without the lab. A recording has two states, "broken" and
"fixed"; a successful Touch action moves the replay from broken to fixed.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from wheelhouse.runtime.inventory import Host
from wheelhouse.runtime.transport import CommandResult
from wheelhouse.safety.catalog import RenderedAction
from wheelhouse.safety.tiers import Tier

FORMAT = "wheelhouse-recording/1"


def recording_key(host: str, action: RenderedAction) -> str:
    """service_logs is keyed without its line count; replay trims to what was asked."""
    argv = list(action.argv)
    if action.name == "service_logs" and "-n" in argv:
        i = argv.index("-n")
        argv[i + 1] = "*"
    return f"{host} {json.dumps(argv)}"


class ReplayTransport:
    def __init__(self, recording: Mapping[str, Any]) -> None:
        if recording.get("format") != FORMAT:
            raise ValueError("not a Wheelhouse recording")
        self.states: dict[str, dict[str, Any]] = {
            "broken": dict(recording["broken"]),
            "fixed": dict(recording.get("fixed", {})),
        }
        self.state = "broken"
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    @classmethod
    def load(cls, path: str | Path) -> ReplayTransport:
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def run(self, name: str, host: Host, action: RenderedAction) -> CommandResult:
        self.calls.append((name, action.argv))
        if action.tier is Tier.TOUCH:
            self.state = "fixed"
            return CommandResult("ok", 0, b"", 1)
        rec = self.states[self.state].get(recording_key(name, action))
        if rec is None and self.state == "fixed":
            rec = self.states["broken"].get(recording_key(name, action))
        if rec is None:
            return CommandResult("failed", 1, b"replay: this action was not recorded\n", 1)
        out = str(rec["output"])
        if action.name == "service_logs":
            n = int(action.argv[action.argv.index("-n") + 1])
            out = "\n".join(out.splitlines()[-n:]) + "\n"
        return CommandResult(str(rec["status"]), rec.get("exit_code"), out.encode(), 1)


def record_result(result: CommandResult) -> dict[str, Any]:
    return {
        "status": result.status,
        "exit_code": result.exit_code,
        "output": result.output.decode("utf-8", "replace"),
    }
