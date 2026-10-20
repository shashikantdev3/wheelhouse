"""Sprint 2 exit check, in the lab: one incident end to end over real SSH and systemd.

nginx is stopped on web01. Lookout detects it, Diver investigates with real read-only
actions, Assayer checks the quotes against the real output, Navigator plans, the
lab-operator approves with an Ed25519 key, Helmsman starts nginx with sudo and checks
it. The model is scripted so the test is repeatable; a live model run is described in
lab/README.md.
"""

import os
import subprocess
from pathlib import Path

import pytest

from wheelhouse.console import Console
from wheelhouse.crew import Crew, IncidentStore, Model, Status
from wheelhouse.ledger import Ledger
from wheelhouse.runtime import Inventory, Runner, SSHTransport
from wheelhouse.safety import ApprovalAuthority, ApproverKey

from tests.crew_fakes import ScriptedModel

pytestmark = pytest.mark.skipif(
    os.environ.get("WHEELHOUSE_LAB") != "1", reason="set WHEELHOUSE_LAB=1 with the lab running"
)

ROOT = Path(__file__).resolve().parents[2]
OPERATOR = ROOT / "lab" / ".secrets" / "approvers" / "lab-operator.key"


def docker(*args: str) -> None:
    subprocess.run(["docker", *args], check=True, capture_output=True)  # noqa: S603, S607


def test_nginx_stop_goes_end_to_end(tmp_path: Path) -> None:
    inv = Inventory.load(ROOT / "lab" / "wheelhouse.lab.yaml")
    inv = inv.model_copy(update={"ledger": tmp_path / "ledger.jsonl", "state": tmp_path})
    runner = Runner(
        inv,
        SSHTransport(str(inv.known_hosts), inv.limits),
        Ledger(inv.ledger),
        authority=ApprovalAuthority(inv.approvers),
    )
    store = IncidentStore(inv.state)
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
                    "summary": "nginx was stopped cleanly by systemd and not started again.",
                    "root_cause": {
                        "text": "systemd stopped nginx",
                        "evidence": ["E2"],
                        "quote": "Stopped nginx.service",
                    },
                    "supporting": [
                        {
                            "text": "nginx is inactive",
                            "evidence": ["E1"],
                            "quote": "inactive (dead)",
                        }
                    ],
                    "confidence": "high",
                }
            },
            {
                "plan": {
                    "summary": "Start nginx on web01.",
                    "risk": "nginx may fail to start if its configuration is broken.",
                    "steps": [
                        {
                            "host": "web01",
                            "action": "service_start",
                            "args": {"service": "nginx"},
                            "why": "it is stopped",
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
    crew = Crew(runner, store, Model(model))
    docker("exec", "lab-web01-1", "systemctl", "stop", "nginx")
    try:
        first = crew.run_once()
        assert len(first.sweep.opened) == 1
        iid = first.sweep.opened[0]
        assert first.investigated == {iid: "awaiting_approval"}
        inc = store.get(iid)
        assert inc.verification is not None and inc.verification.verified
        assert inc.plan is not None
        assert inc.plan.steps[0].argv == ["sudo", "-n", "systemctl", "start", "nginx"]

        console = Console(store, ApproverKey.load("lab-operator", OPERATOR), inv)
        assert console.approve(iid, inc.plan.digest(), 15) is None
        second = crew.run_once()
        assert second.executed == {iid: "resolved"}
        assert store.get(iid).status is Status.RESOLVED
        assert crew.run_once().sweep.opened == []
        assert runner.ledger.verify().ok
        tools = [r["lineage"]["tool"]["name"] for r in runner.ledger.records()]
        assert "service_start" in tools
    finally:
        docker("exec", "lab-web01-1", "systemctl", "start", "nginx")
