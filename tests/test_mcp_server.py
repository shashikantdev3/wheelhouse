import asyncio
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from wheelhouse.mcp_server import build_server  # noqa: E402

from tests.test_runner import make  # noqa: E402


def call(server, name: str, args: dict) -> str:  # type: ignore[no-untyped-def]
    result = asyncio.run(server.call_tool(name, args))
    return "".join(getattr(c, "text", "") for c in result.content)


def test_look_runs_and_output_is_marked_as_data(tmp_path: Path) -> None:
    runner, fake, _ = make(tmp_path)
    out = call(build_server(runner), "run_look_action", {"host": "web01", "action": "uptime"})
    assert "<host-output" in out and "fine" in out and fake.calls


def test_touch_is_never_run_through_mcp(tmp_path: Path) -> None:
    runner, fake, ledger = make(tmp_path)
    server = build_server(runner)
    out = call(
        server,
        "run_look_action",
        {"host": "web01", "action": "service_restart", "args": {"service": "nginx"}},
    )
    assert out.startswith("refused") and not fake.calls
    out = call(
        server,
        "request_change",
        {"host": "web01", "action": "service_restart", "args": {"service": "nginx"}},
    )
    assert "needs approval" in out and not fake.calls
    assert ledger.verify().ok


def test_refusals_come_back_as_text(tmp_path: Path) -> None:
    runner, fake, _ = make(tmp_path)
    out = call(
        build_server(runner),
        "run_look_action",
        {"host": "web01", "action": "service_status", "args": {"service": "x;reboot"}},
    )
    assert out.startswith("refused") and not fake.calls
