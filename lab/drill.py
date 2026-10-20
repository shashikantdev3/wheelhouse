"""Lab drills: inject a fault, record what the hosts show, and replay it to the crew.

Record (needs the lab running):
    uv run python lab/drill.py record nginx-stopped
Replay with the configured model (no lab needed; uses ANTHROPIC_API_KEY or WHEELHOUSE_MODEL):
    uv run python lab/drill.py run nginx-stopped

A replay runs the real crew: Lookout, Diver, Assayer, Navigator, an approval signed with a
throwaway drill key, and Helmsman. Nothing touches a real host. Recordings hold lab
output only and are committed under lab/drills/.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

LAB = Path(__file__).resolve().parent
sys.path.insert(0, str(LAB.parent / "src"))
sys.path.insert(0, str(LAB))

from setup_lab import DATABASES, HOSTS  # noqa: E402

from wheelhouse.config import Settings  # noqa: E402
from wheelhouse.console import Console  # noqa: E402
from wheelhouse.crew import Crew, IncidentStore, Model  # noqa: E402
from wheelhouse.ledger import Ledger  # noqa: E402
from wheelhouse.providers import choose_provider  # noqa: E402
from wheelhouse.runtime import Host, Inventory, Limits, Runner, SSHTransport  # noqa: E402
from wheelhouse.runtime.replay import (  # noqa: E402
    FORMAT,
    ReplayTransport,
    record_result,
    recording_key,
)
from wheelhouse.safety import ApprovalAuthority, ApproverKey, Tier  # noqa: E402

DRILLS: dict[str, dict[str, list[list[str]]]] = {
    "nginx-stopped": {
        "inject": [["docker", "exec", "lab-web01-1", "systemctl", "stop", "nginx"]],
        "fix": [["docker", "exec", "lab-web01-1", "systemctl", "start", "nginx"]],
    },
    "memcached-stopped": {
        "inject": [["docker", "exec", "lab-app01-1", "systemctl", "stop", "memcached"]],
        "fix": [["docker", "exec", "lab-app01-1", "systemctl", "start", "memcached"]],
    },
}


def lab_inventory(state: Path) -> Inventory:
    secrets = LAB / ".secrets"
    return Inventory(
        known_hosts=secrets / "known_hosts",
        ledger=state / "ledger.jsonl",
        state=state,
        limits=Limits(actions_per_minute=600),
        hosts={
            name: Host(
                address="127.0.0.1",
                port=port,
                user="wheelhouse",
                identity_file=secrets / "wheelhouse_ed25519",
                role=role,
                services=services,
                databases=DATABASES.get(name, ()),
            )
            for name, (port, role, services) in HOSTS.items()
        },
    )


def _sh(commands: list[list[str]]) -> None:
    for cmd in commands:
        subprocess.run(cmd, check=True, capture_output=True)  # noqa: S603


def _arg_sets(spec_name: str, host_name: str, host: Host) -> list[dict[str, str]]:
    """Which argument sets to record for an action on a host."""
    if spec_name == "service_status":
        return [{"service": s} for s in host.services]
    if spec_name == "service_logs":
        return [{"service": s, "lines": "200"} for s in host.services]
    if spec_name == "rabbitmq_queues":
        return [{"vhost": "/"}] if host_name == "mq01" else []
    if spec_name == "mysql_status":
        return [{}] if host_name == "db01" else []
    if spec_name in ("ping", "mysql_query"):
        return []  # free-form arguments; not recorded
    return [{}]


def _snapshot(runner: Runner, only: tuple[str, ...] = ()) -> dict[str, object]:
    out: dict[str, object] = {}
    for name, host in runner.inventory.hosts.items():
        for spec in runner.lockkeeper.catalog.specs():
            if spec.tier is not Tier.LOOK or (only and spec.name not in only):
                continue
            for args in _arg_sets(spec.name, name, host):
                res = runner.request(name, spec.name, args)
                if res.result is not None and res.decision.rendered is not None:
                    out[recording_key(name, res.decision.rendered)] = record_result(res.result)
    return out


def record(name: str) -> int:
    drill = DRILLS[name]
    with tempfile.TemporaryDirectory() as tmp:
        inv = lab_inventory(Path(tmp))
        runner = Runner(inv, SSHTransport(str(inv.known_hosts), inv.limits), Ledger(inv.ledger))
        _sh(drill["inject"])
        time.sleep(2)
        try:
            broken = _snapshot(runner)
        finally:
            _sh(drill["fix"])
        time.sleep(3)
        fixed = _snapshot(runner, only=("service_status", "service_logs"))
    path = LAB / "drills" / f"{name}.json"
    path.parent.mkdir(exist_ok=True)
    body = {"format": FORMAT, "drill": name, "broken": broken, "fixed": fixed}
    path.write_text(json.dumps(body, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"recorded {len(broken)} broken and {len(fixed)} fixed outputs to {path}")
    return 0


def run(name: str) -> int:
    provider = choose_provider(Settings())
    if provider is None:
        print("no model configured (set ANTHROPIC_API_KEY, or WHEELHOUSE_MODEL)")
        return 2
    transport = ReplayTransport.load(LAB / "drills" / f"{name}.json")
    operator = ApproverKey.generate("drill-operator")
    with tempfile.TemporaryDirectory() as tmp:
        inv = lab_inventory(Path(tmp)).model_copy(
            update={"approvers": {"drill-operator": operator.public_text}}
        )
        runner = Runner(
            inv, transport, Ledger(inv.ledger), authority=ApprovalAuthority(inv.approvers)
        )
        store = IncidentStore(inv.state)
        crew = Crew(runner, store, Model(provider), sleep=lambda _s: None)
        first = crew.run_once()
        print(f"model: {getattr(provider, 'model', '?')}")
        print(f"detected: {first.sweep.opened}")
        for iid in first.sweep.opened:
            inc = store.get(iid)
            print(f"\n{iid}: {inc.title} -> {inc.status.value}")
            for e in inc.evidence:
                print(f"  {e.id} {e.action} {e.args or ''} on {e.host} ({e.status})")
            if inc.diagnosis and inc.verification:
                print(f"  diagnosis: {inc.diagnosis.summary}")
                for c in inc.verification.checks:
                    print(f"    [{'ok ' if c.ok else 'BAD'}] {c.role}: {c.text}")
            if inc.status.value == "needs_human":
                for ev in inc.events:
                    print(f"  - {ev.who}: {ev.what}")
            if inc.plan:
                for s in inc.plan.steps:
                    print(f"  plan: {' '.join(s.argv)} on {s.host}; check '{s.verify.expect}'")
                Console(store, operator, inv).approve(iid, inc.plan.digest(), 15)
        second = crew.run_once()
        for iid, status in second.executed.items():
            inc = store.get(iid)
            print(f"\n{iid} executed: {status}")
            for r in inc.results:
                print(f"  {r.detail}")
        for iid in first.sweep.opened:
            inc = store.get(iid)
            for agent, u in inc.usage.items():
                cost = f"${u.cost_usd:.5f}" if u.cost_known else "cost unknown"
                print(
                    f"  {agent}: {u.calls} calls, {u.input_tokens}+{u.output_tokens} tokens, {cost}"
                )
        print(f"\nledger ok: {runner.ledger.verify().ok}")
        resolved = all(s == "resolved" for s in second.executed.values())
        return 0 if first.sweep.opened and second.executed and resolved else 1


def main() -> int:
    parser = argparse.ArgumentParser(prog="drill")
    parser.add_argument("what", choices=["record", "run"])
    parser.add_argument("name", choices=sorted(DRILLS))
    ns = parser.parse_args()
    return record(ns.name) if ns.what == "record" else run(ns.name)


if __name__ == "__main__":
    raise SystemExit(main())
