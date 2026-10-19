"""End-to-end tests against the Docker lab. Skipped unless WHEELHOUSE_LAB=1.

python lab/setup_lab.py
docker compose -f lab/docker-compose.yml --profile build build base
docker compose -f lab/docker-compose.yml up -d --build
WHEELHOUSE_LAB=1 uv run pytest tests/lab -v
"""

import os
from pathlib import Path

import pytest

from wheelhouse.ledger import Ledger
from wheelhouse.runtime import Inventory, Runner, SSHTransport
from wheelhouse.safety import ApprovalAuthority, Verdict

pytestmark = pytest.mark.skipif(
    os.environ.get("WHEELHOUSE_LAB") != "1", reason="set WHEELHOUSE_LAB=1 with the lab running"
)

ROOT = Path(__file__).resolve().parents[2]
KEY = b"lab-test-key-" + b"x" * 32


@pytest.fixture
def runner(tmp_path: Path) -> Runner:
    inv = Inventory.load(ROOT / "lab" / "wheelhouse.lab.yaml")
    inv = inv.model_copy(update={"ledger": tmp_path / "ledger.jsonl"})
    return Runner(
        inv,
        SSHTransport(str(inv.known_hosts), inv.limits),
        Ledger(inv.ledger),
        authority=ApprovalAuthority(KEY),
        key=KEY,
        principal="lab-test",
    )


def out(res) -> str:  # type: ignore[no-untyped-def]
    assert res.result is not None, res.decision.reason
    return res.result.output.decode()


def test_every_host_is_reachable_with_a_posix_shell(runner: Runner) -> None:
    transport = runner.transport
    assert isinstance(transport, SSHTransport)
    for name, host in runner.inventory.hosts.items():
        assert transport.shell_problem(name, host) is None, name


@pytest.mark.parametrize(
    ("host", "action", "args", "expect"),
    [
        ("web01", "service_status", {"service": "nginx"}, "nginx.service"),
        ("app01", "service_status", {"service": "orders-api"}, "active (running)"),
        (
            "db01",
            "mysql_query",
            {"database": "app", "sql": "SELECT COUNT(*) AS n FROM orders"},
            "n",
        ),
        ("mq01", "rabbitmq_queues", {"vhost": "/"}, "Listing queues"),
        ("etl01", "service_logs", {"service": "orders-daily", "lines": "20"}, "orders"),
        ("app01", "disk_usage", {}, "Filesystem"),
    ],
)
def test_look_actions(runner: Runner, host: str, action: str, args: dict, expect: str) -> None:
    res = runner.request(host, action, args)
    assert res.decision.verdict is Verdict.RUN
    assert expect in out(res)


def test_read_only_account_cannot_write_or_see_credentials(runner: Runner) -> None:
    # The gate refuses writes before anything runs.
    refused = runner.request(
        "db01", "mysql_query", {"database": "app", "sql": "DELETE FROM orders"}
    )
    assert refused.decision.verdict is Verdict.REFUSED and not refused.executed
    # The account itself has no access to mysql.user, even for a SELECT that passes the gate.
    res = runner.request(
        "db01", "mysql_query", {"database": "app", "sql": "SELECT user FROM mysql.user"}
    )
    assert res.result is not None and res.result.status == "failed"


def test_touch_needs_approval_runs_once_and_is_recorded(runner: Runner) -> None:
    args = {"service": "memcached"}
    asked = runner.request("app01", "service_restart", args, execute=False)
    assert asked.decision.verdict is Verdict.NEEDS_APPROVAL and asked.decision.step_hash
    approval = ApprovalAuthority(KEY).grant(asked.decision.step_hash, "lab-tester")
    ran = runner.request("app01", "service_restart", args, approval)
    assert ran.result is not None and ran.result.status == "ok"
    again = runner.request("app01", "service_restart", args, approval)
    assert not again.executed
    assert runner.ledger.verify().ok


def test_inventory_service_list_is_enforced_by_the_runner(runner: Runner) -> None:
    res = runner.request("web01", "service_logs", {"service": "cron", "lines": "5"})
    assert res.decision.verdict is Verdict.REFUSED and not res.executed


def test_host_sudo_rules_are_a_separate_boundary(runner: Runner) -> None:
    # Bypass Wheelhouse's own gate on purpose to show the host refuses on its own:
    # cron is not in web01's sudo rules.
    from wheelhouse.safety import default_catalog

    action = default_catalog().render("service_restart", {"service": "cron"})
    host = runner.inventory.hosts["web01"]
    res = runner.transport.run("web01", host, action)
    assert res.status == "failed" and "password is required" in res.output.decode()


def test_server_side_sql_time_limit_is_set(runner: Runner) -> None:
    res = runner.request(
        "db01", "mysql_query", {"database": "app", "sql": "SELECT @@max_statement_time AS t"}
    )
    assert "30" in out(res)
