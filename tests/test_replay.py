"""The committed lab recordings replay through the real crew with a scripted model."""

import json
from pathlib import Path

import pytest

from wheelhouse.console import Console
from wheelhouse.crew import Crew, IncidentStore, Model
from wheelhouse.ledger import Ledger
from wheelhouse.runtime import Host, Inventory, Limits, Runner
from wheelhouse.runtime.replay import ReplayTransport
from wheelhouse.safety import ApprovalAuthority, ApproverKey, RenderedAction, Tier

from tests.crew_fakes import ScriptedModel

DRILLS = Path(__file__).resolve().parents[1] / "lab" / "drills"
OPERATOR = ApproverKey.generate("drill-operator")


def lab_runner(tmp_path: Path, transport: ReplayTransport) -> Runner:
    hosts = {
        "web01": (2211, "web", ("nginx",)),
        "app01": (2212, "app", ("orders-api", "memcached")),
        "db01": (2213, "database", ("mariadb",)),
        "mq01": (2214, "queue", ("rabbitmq-server",)),
        "etl01": (2215, "etl", ("orders-daily",)),
    }
    inv = Inventory(
        known_hosts=tmp_path / "kh",
        ledger=tmp_path / "ledger.jsonl",
        state=tmp_path,
        limits=Limits(actions_per_minute=600),
        approvers={"drill-operator": OPERATOR.public_text},
        hosts={
            n: Host(
                address="127.0.0.1",
                port=p,
                user="wheelhouse",
                identity_file=tmp_path / "id",
                role=r,
                services=s,
            )
            for n, (p, r, s) in hosts.items()
        },
    )
    return Runner(inv, transport, Ledger(inv.ledger), authority=ApprovalAuthority(inv.approvers))


def test_replay_transport_states_and_line_trimming() -> None:
    t = ReplayTransport.load(DRILLS / "nginx-stopped.json")
    host = Host(address="127.0.0.1", user="w", identity_file=Path("id"))
    status = RenderedAction(
        "service_status", Tier.LOOK, ("systemctl", "status", "--no-pager", "nginx"), 30, ""
    )
    assert b"inactive (dead)" in t.run("web01", host, status).output
    logs = RenderedAction(
        "service_logs", Tier.LOOK, ("journalctl", "--no-pager", "-u", "nginx", "-n", "3"), 30, ""
    )
    assert len(t.run("web01", host, logs).output.decode().splitlines()) == 3
    start = RenderedAction(
        "service_start", Tier.TOUCH, ("sudo", "-n", "systemctl", "start", "nginx"), 120, ""
    )
    t.run("web01", host, start)
    assert b"active (running)" in t.run("web01", host, status).output
    unknown = RenderedAction("uptime", Tier.LOOK, ("uptime", "--weird"), 30, "")
    assert t.run("web01", host, unknown).status == "failed"
    with pytest.raises(ValueError):
        ReplayTransport({"format": "other"})


def test_recordings_hold_no_secrets() -> None:
    for path in DRILLS.glob("*.json"):
        text = path.read_text()
        assert "PRIVATE KEY" not in text and "password=" not in text.lower()
        assert json.loads(text)["format"] == "wheelhouse-recording/1"


def test_nginx_drill_replays_end_to_end(tmp_path: Path) -> None:
    transport = ReplayTransport.load(DRILLS / "nginx-stopped.json")
    runner = lab_runner(tmp_path, transport)
    store = IncidentStore(tmp_path)
    model = ScriptedModel(
        [
            {
                "next": {
                    "host": "web01",
                    "action": "service_logs",
                    "args": {"service": "nginx", "lines": "20"},
                }
            },
            {
                "diagnosis": {
                    "summary": "stopped",
                    "root_cause": {
                        "text": "systemd stopped nginx",
                        "evidence": ["E2"],
                        "quote": "Stopped nginx.service",
                    },
                }
            },
            {
                "plan": {
                    "summary": "start it",
                    "risk": "low",
                    "steps": [
                        {
                            "host": "web01",
                            "action": "service_start",
                            "args": {"service": "nginx"},
                            "verify": {
                                "action": "service_status",
                                "args": {"service": "nginx"},
                                "expect": "active (running)",
                            },
                        }
                    ],
                }
            },
        ]
    )
    crew = Crew(runner, store, Model(model), sleep=lambda _s: None)
    first = crew.run_once()
    assert len(first.sweep.opened) == 1, "only the injected fault is detected"
    iid = first.sweep.opened[0]
    inc = store.get(iid)
    assert inc.plan is not None and inc.fingerprint == "web01:service_down:nginx"
    Console(store, OPERATOR, runner.inventory).approve(iid, inc.plan.digest(), 15)
    assert crew.run_once().executed == {iid: "resolved"}
