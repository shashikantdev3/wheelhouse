from datetime import timedelta
from pathlib import Path

from wheelhouse.ledger import Ledger
from wheelhouse.runtime import CommandResult, Host, Inventory, Limits, Runner
from wheelhouse.safety import ApprovalAuthority, RenderedAction, Verdict

KEY = b"k" * 32


class FakeTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def run(self, name: str, host: Host, action: RenderedAction) -> CommandResult:
        self.calls.append((name, action.argv))
        return CommandResult("ok", 0, b"fine", 5)


def make(tmp_path: Path, per_minute: int = 30) -> tuple[Runner, FakeTransport, Ledger]:
    inv = Inventory(
        known_hosts=tmp_path / "known_hosts",
        ledger=tmp_path / "ledger.jsonl",
        limits=Limits(actions_per_minute=per_minute),
        hosts={
            "web01": Host(address="10.0.0.11", user="wheelhouse", identity_file=tmp_path / "id")
        },
    )
    fake = FakeTransport()
    ledger = Ledger(inv.ledger)
    runner = Runner(inv, fake, ledger, authority=ApprovalAuthority(KEY), key=KEY)
    return runner, fake, ledger


def test_look_runs_and_is_recorded_twice(tmp_path: Path) -> None:
    runner, fake, ledger = make(tmp_path)
    res = runner.request("web01", "disk_usage")
    assert res.executed and fake.calls == [("web01", ("df", "-h"))]
    events = [r["labels"]["event"] for r in ledger.records()]
    assert events == ["decision", "execution"]
    assert ledger.verify().ok


def test_unknown_host_is_refused_and_recorded(tmp_path: Path) -> None:
    runner, fake, ledger = make(tmp_path)
    res = runner.request("db99", "disk_usage")
    assert res.decision.verdict is Verdict.REFUSED and not fake.calls
    assert len(list(ledger.records())) == 1


def test_touch_flow_request_approve_run_and_no_reuse(tmp_path: Path) -> None:
    runner, fake, ledger = make(tmp_path)
    req = runner.request("web01", "service_restart", {"service": "nginx"}, execute=False)
    assert req.decision.verdict is Verdict.NEEDS_APPROVAL and not fake.calls
    assert req.decision.step_hash
    approval = ApprovalAuthority(KEY).grant(
        req.decision.step_hash, "shashikant", ttl=timedelta(minutes=5)
    )
    ran = runner.request("web01", "service_restart", {"service": "nginx"}, approval)
    assert ran.executed
    assert fake.calls == [("web01", ("sudo", "-n", "systemctl", "restart", "nginx"))]
    again = runner.request("web01", "service_restart", {"service": "nginx"}, approval)
    assert not again.executed
    # A new runner (a restart) reads used approvals back from the ledger.
    runner2 = Runner(runner.inventory, fake, ledger, authority=ApprovalAuthority(KEY), key=KEY)
    assert not runner2.request("web01", "service_restart", {"service": "nginx"}, approval).executed
    assert ledger.verify().ok


def test_request_does_not_use_up_an_approval(tmp_path: Path) -> None:
    runner, fake, _ = make(tmp_path)
    req = runner.request("web01", "service_stop", {"service": "nginx"}, execute=False)
    assert req.decision.step_hash
    approval = ApprovalAuthority(KEY).grant(req.decision.step_hash, "a")
    runner.request("web01", "service_stop", {"service": "nginx"}, approval, execute=False)
    assert runner.request("web01", "service_stop", {"service": "nginx"}, approval).executed


def test_rate_limit(tmp_path: Path) -> None:
    runner, fake, _ = make(tmp_path, per_minute=2)
    assert runner.request("web01", "uptime").executed
    assert runner.request("web01", "uptime").executed
    third = runner.request("web01", "uptime")
    assert not third.executed and "rate limit" in third.decision.reason


def test_hostile_host_name_still_records_a_valid_record(tmp_path: Path) -> None:
    runner, _, ledger = make(tmp_path)
    runner.request("x" * 1000, "uptime")
    assert ledger.verify().ok


# Sprint 1 review (decision 0007).


def test_two_processes_cannot_spend_one_approval(tmp_path: Path) -> None:
    runner_a, fake, ledger = make(tmp_path)
    runner_b = Runner(runner_a.inventory, fake, ledger, authority=ApprovalAuthority(KEY), key=KEY)
    req = runner_a.request("web01", "service_restart", {"service": "nginx"}, execute=False)
    assert req.decision.step_hash
    approval = ApprovalAuthority(KEY).grant(req.decision.step_hash, "a")
    first = runner_a.request("web01", "service_restart", {"service": "nginx"}, approval)
    second = runner_b.request("web01", "service_restart", {"service": "nginx"}, approval)
    assert first.executed and not second.executed
    assert len(fake.calls) == 1


class ShiftyArgs(dict):  # type: ignore[type-arg]
    """Returns a different value on every read: what is checked must be what runs."""

    def __init__(self) -> None:
        super().__init__(service="nginx")
        self.reads = 0

    def __getitem__(self, key):  # type: ignore[no-untyped-def]
        self.reads += 1
        return "nginx" if self.reads == 1 else "sshd"


def test_runs_exactly_what_was_checked(tmp_path: Path) -> None:
    runner, fake, _ = make(tmp_path)
    runner.request("web01", "service_status", ShiftyArgs())
    assert all(argv[-1] in ("nginx",) for _, argv in fake.calls)


def test_str_subclass_arguments_are_refused(tmp_path: Path) -> None:
    class Sneaky(str):
        def __str__(self) -> str:
            return "sshd"

    runner, fake, _ = make(tmp_path)
    res = runner.request("web01", "service_status", {"service": Sneaky("nginx")})
    assert res.decision.verdict is Verdict.REFUSED and not fake.calls


def test_service_must_be_listed_for_the_host(tmp_path: Path) -> None:
    runner, fake, _ = make(tmp_path)
    inv = runner.inventory
    host = inv.hosts["web01"].model_copy(update={"services": ("nginx",)})
    runner.inventory = inv.model_copy(update={"hosts": {"web01": host}})
    res = runner.request("web01", "service_logs", {"service": "cron", "lines": "10"})
    assert res.decision.verdict is Verdict.REFUSED and not fake.calls
    assert runner.request("web01", "service_logs", {"service": "nginx", "lines": "10"}).executed


def test_unknown_host_flood_is_not_written_past_the_limit(tmp_path: Path) -> None:
    runner, _, ledger = make(tmp_path, per_minute=3)
    for i in range(20):
        runner.request(f"ghost{i}", "uptime")
    assert len(list(ledger.records())) == 3


def test_lone_surrogates_do_not_crash_the_ledger(tmp_path: Path) -> None:
    runner, fake, ledger = make(tmp_path)
    runner.request("web01\udcff", "uptime")
    runner.request("web01", "uptime\udcff")
    assert ledger.verify().ok and not fake.calls
