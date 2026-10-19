"""Command line.

wheelhouse doctor [--live]            installation, keys, providers
wheelhouse catalog                    actions agents may request
wheelhouse check HOST ACTION k=v      Lockkeeper's verdict, dry run, nothing recorded
wheelhouse hosts                      inventory and reachability
wheelhouse run HOST ACTION k=v [--approval FILE]
wheelhouse request HOST ACTION k=v    record a change request, print its step hash
wheelhouse approve STEP_HASH --by NAME [--minutes N] [--out FILE]
wheelhouse ledger verify | tail [-n N]
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import sys
from collections.abc import Sequence
from pathlib import Path

from wheelhouse import __version__
from wheelhouse.config import Settings
from wheelhouse.safety import ApprovalAuthority, Lockkeeper, Verdict
from wheelhouse.safety.approval_io import dump_approval, load_approval

DEFAULT_INVENTORY = "wheelhouse.yaml"


def _key(settings: Settings) -> bytes | None:
    key = settings.wheelhouse_approval_key
    if key is None:
        return None
    raw = key.get_secret_value().encode()
    return raw if len(raw) >= 32 else None


def _pairs(pairs: Sequence[str]) -> dict[str, object] | None:
    args: dict[str, object] = {}
    for pair in pairs:
        if "=" not in pair:
            print(f"argument '{pair}' must be key=value", file=sys.stderr)
            return None
        key, value = pair.split("=", 1)
        args[key] = value
    return args


def _doctor(live: bool) -> int:
    settings = Settings()
    keeper = Lockkeeper()
    print(f"wheelhouse {__version__} on Python {platform.python_version()}")
    print("model providers (presence only, values never shown):")
    for name, ok in settings.providers().items():
        print(f"  {name:<11} {'configured' if ok else 'not configured'}")
    print(
        "approval key: "
        + ("configured" if _key(settings) else "not configured (Touch actions cannot run)")
    )
    print(f"action catalog: {len(keeper.catalog)} actions, policy {keeper.catalog.policy_hash()}")
    if live:
        from wheelhouse.providers import live_check

        for line in live_check(settings):
            print(line)
    if not any(settings.providers().values()):
        print("no model provider configured: set ANTHROPIC_API_KEY or OPENROUTER_API_KEY in .env")
        return 1
    return 0


def _catalog() -> int:
    for spec in Lockkeeper().catalog.specs():
        params = ", ".join(spec.params) or "-"
        print(f"{spec.tier.value:<6} {spec.name:<16} {params:<14} {spec.description}")
    return 0


def _print_decision(d: object) -> None:
    from wheelhouse.safety import Decision

    assert isinstance(d, Decision)
    print(f"verdict: {d.verdict.value}")
    print(f"tier:    {d.tier.value}")
    print(f"reason:  {d.reason}")
    if d.argv:
        print(f"argv:    {list(d.argv)}")
    if d.step_hash:
        print(f"step:    {d.step_hash}")


def _check(host: str, action: str, pairs: Sequence[str]) -> int:
    args = _pairs(pairs)
    if args is None:
        return 2
    decision = Lockkeeper().decide(host, action, args)
    _print_decision(decision)
    print("(dry run: nothing was executed or recorded)")
    return 0 if decision.verdict is not Verdict.REFUSED else 3


def _runner(inventory_path: str) -> object:
    from wheelhouse.ledger import Ledger
    from wheelhouse.runtime import Inventory, Runner, SSHTransport

    settings = Settings()
    inv = Inventory.load(inventory_path)
    key = _key(settings)
    return Runner(
        inv,
        SSHTransport(str(inv.known_hosts), inv.limits),
        Ledger(inv.ledger),
        authority=ApprovalAuthority(key) if key else None,
        key=key,
    )


def _run(ns: argparse.Namespace, execute: bool) -> int:
    from wheelhouse.runtime import Runner

    args = _pairs(ns.args)
    if args is None:
        return 2
    runner = _runner(ns.inventory)
    assert isinstance(runner, Runner)
    approval = load_approval(ns.approval) if getattr(ns, "approval", None) else None
    res = runner.request(ns.host, ns.action, args, approval, execute=execute)
    _print_decision(res.decision)
    if res.result is not None:
        print(
            f"status:  {res.result.status} (exit {res.result.exit_code}, "
            f"{res.result.duration_ms} ms{', output truncated' if res.result.truncated else ''})"
        )
        print("--- output ---")
        print(res.result.output.decode("utf-8", "replace").rstrip())
    elif res.decision.verdict is Verdict.NEEDS_APPROVAL and res.decision.step_hash:
        print(f"to approve: wheelhouse approve {res.decision.step_hash} --by <your name>")
    print(f"(recorded in {runner.ledger.path})")
    if res.decision.verdict is Verdict.REFUSED:
        return 3
    if res.result is not None and res.result.status != "ok":
        return 4
    return 0


def _approve(step: str, by: str, minutes: int, out: str | None) -> int:
    from datetime import timedelta

    key = _key(Settings())
    if key is None:
        print("WHEELHOUSE_APPROVAL_KEY (32+ characters) is not set in .env", file=sys.stderr)
        return 2
    if not re.fullmatch(r"[0-9a-f]{64}", step):
        print("step hash must be 64 lowercase hex characters", file=sys.stderr)
        return 2
    approval = ApprovalAuthority(key).grant(step, by, ttl=timedelta(minutes=minutes))
    path = Path(out or f"approvals/{step[:16]}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        # New file only, readable by the owner only: an approval is a bearer token.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print(f"{path} already exists; choose another --out", file=sys.stderr)
        return 2
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(dump_approval(approval))
    print(f"approved by {approval.approver} until {approval.expires_at.isoformat()}")
    print(f"approval file: {path} (single use)")
    return 0


def _hosts(inventory_path: str) -> int:
    from wheelhouse.runtime import Inventory, SSHTransport

    inv = Inventory.load(inventory_path)
    transport = SSHTransport(str(inv.known_hosts), inv.limits)
    worst = 0
    for name, host in inv.hosts.items():
        problem = transport.shell_problem(name, host)
        state = "ok" if problem is None else problem
        worst = worst if problem is None else 5
        print(f"{name:<10} {host.user}@{host.address}:{host.port:<6} {state}")
    return worst


def _mcp(inventory_path: str) -> int:
    try:
        from wheelhouse.mcp_server import build_server
    except ImportError:
        print("install the MCP extra: uv sync --extra mcp", file=sys.stderr)
        return 2
    from wheelhouse.runtime import Runner

    runner = _runner(inventory_path)
    assert isinstance(runner, Runner)
    runner.principal = "mcp-client"
    # The MCP server never runs Touch steps, so it gets no approval authority at all.
    runner.lockkeeper.authority = None
    build_server(runner).run("stdio")
    return 0


def _ledger(inventory_path: str, what: str, n: int) -> int:
    from wheelhouse.ledger import Ledger
    from wheelhouse.runtime import Inventory

    ledger = Ledger(Inventory.load(inventory_path).ledger)
    if what == "verify":
        res = ledger.verify()
        print(f"records: {res.count}  head: {res.head_hash}")
        for err in res.errors:
            print(f"  {err}")
        print("chain ok" if res.ok else "CHAIN BROKEN")
        return 0 if res.ok else 6
    records = list(ledger.records())[-n:]
    for r in records:
        labels = r.get("labels", {})
        print(
            json.dumps(
                {
                    "seq": r["integrity"]["seq"],
                    "ts": r["ts"],
                    "event": labels.get("event"),
                    "host": labels.get("host"),
                    "tool": r.get("lineage", {}).get("tool", {}).get("name"),
                    "action": r["outcome"]["action"],
                    "reason": r["outcome"].get("reason_code"),
                }
            )
        )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wheelhouse")
    parser.add_argument("--version", action="version", version=f"wheelhouse {__version__}")
    parser.add_argument("--inventory", default=DEFAULT_INVENTORY, help="inventory YAML file")
    sub = parser.add_subparsers(dest="command", required=True)
    doctor = sub.add_parser("doctor", help="check the installation and which keys are present")
    doctor.add_argument("--live", action="store_true", help="make one tiny call per provider")
    sub.add_parser("catalog", help="list the actions agents may request")
    for name, help_text in (
        ("check", "ask Lockkeeper about an action (dry run, nothing recorded)"),
        ("run", "gate, run and record an action on an inventory host"),
        ("request", "record a change request and print its step hash for approval"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("host")
        p.add_argument("action")
        p.add_argument("args", nargs="*", help="key=value")
        if name == "run":
            p.add_argument("--approval", help="approval file from 'wheelhouse approve'")
    approve = sub.add_parser("approve", help="approve one exact step (signed, single use)")
    approve.add_argument("step_hash")
    approve.add_argument("--by", required=True, help="your name, as the approver")
    approve.add_argument("--minutes", type=int, default=30)
    approve.add_argument("--out")
    sub.add_parser("hosts", help="list inventory hosts and check they are reachable")
    sub.add_parser("mcp", help="serve the inventory to MCP clients over stdio (look only)")
    ledger = sub.add_parser("ledger", help="verify or show the ledger")
    ledger.add_argument("what", choices=["verify", "tail"])
    ledger.add_argument("-n", type=int, default=20)
    ns = parser.parse_args(argv)

    if ns.command == "doctor":
        return _doctor(ns.live)
    if ns.command == "catalog":
        return _catalog()
    if ns.command == "check":
        return _check(ns.host, ns.action, ns.args)
    if ns.command == "run":
        return _run(ns, execute=True)
    if ns.command == "request":
        return _run(ns, execute=False)
    if ns.command == "approve":
        return _approve(ns.step_hash, ns.by, ns.minutes, ns.out)
    if ns.command == "hosts":
        return _hosts(ns.inventory)
    if ns.command == "mcp":
        return _mcp(ns.inventory)
    return _ledger(ns.inventory, ns.what, ns.n)


if __name__ == "__main__":
    raise SystemExit(main())
