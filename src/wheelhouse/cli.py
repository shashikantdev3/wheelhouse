"""Command line.

wheelhouse doctor [--live]            installation, keys, providers
wheelhouse catalog                    actions agents may request
wheelhouse check HOST ACTION k=v      Lockkeeper's verdict, dry run, nothing recorded
wheelhouse hosts                      inventory and reachability
wheelhouse run HOST ACTION k=v [--approval FILE]
wheelhouse request HOST ACTION k=v    record a change request, print its step hash
wheelhouse approve STEP_HASH --by NAME [--key FILE] [--minutes N] [--out FILE]
wheelhouse keys new NAME [--out FILE]  create an approver key pair
wheelhouse ledger verify | tail [-n N]
wheelhouse watch [--once] [--interval S]  Lookout, Diver, Assayer, Navigator, Helmsman
wheelhouse incidents [ID]             list incidents, or show one
wheelhouse console --as NAME [--key FILE] [--port N]   approve or reject plans
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
from wheelhouse.safety import ApprovalAuthority, ApproverKey, Lockkeeper, Verdict
from wheelhouse.safety.approval_io import dump_approval, load_approval

DEFAULT_INVENTORY = "wheelhouse.yaml"


def _ledger_key(settings: Settings) -> bytes | None:
    key = settings.wheelhouse_ledger_key
    if key is None:
        return None
    raw = key.get_secret_value().encode()
    return raw if len(raw) >= 32 else None


def _default_key_path(name: str) -> Path:
    return Path.home() / ".wheelhouse" / "approvers" / f"{name}.key"


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
        "ledger key: "
        + (
            "configured"
            if _ledger_key(settings)
            else "not configured (ledger pseudonyms use plain SHA-256)"
        )
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
    return Runner(
        inv,
        SSHTransport(str(inv.known_hosts), inv.limits),
        Ledger(inv.ledger),
        authority=ApprovalAuthority(inv.approvers) if inv.approvers else None,
        key=_ledger_key(settings),
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


def _approve(ns: argparse.Namespace) -> int:
    from datetime import timedelta

    from wheelhouse.runtime import Inventory

    if not re.fullmatch(r"[0-9a-f]{64}", ns.step_hash):
        print("step hash must be 64 lowercase hex characters", file=sys.stderr)
        return 2
    key_path = Path(ns.key) if ns.key else _default_key_path(ns.by)
    try:
        signer = ApproverKey.load(ns.by, key_path)
    except (OSError, ValueError) as err:
        print(f"cannot use approver key {key_path}: {err}", file=sys.stderr)
        return 2
    if Path(ns.inventory).exists():
        listed = Inventory.load(ns.inventory).approvers.get(ns.by)
        if listed != signer.public_text:
            print(
                f"approver '{ns.by}' with this key is not listed in {ns.inventory}; "
                "the runner would refuse the approval",
                file=sys.stderr,
            )
            return 2
    approval = signer.grant(ns.step_hash, ttl=timedelta(minutes=ns.minutes))
    path = Path(ns.out or f"approvals/{ns.step_hash[:16]}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print(f"{path} already exists; choose another --out", file=sys.stderr)
        return 2
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(dump_approval(approval))
    print(f"approved by {approval.approver} until {approval.expires_at.isoformat()}")
    print(f"approval file: {path} (single use)")
    return 0


def _keys_new(name: str, out: str | None) -> int:
    try:
        signer = ApproverKey.generate(name)
        path = signer.save(Path(out) if out else _default_key_path(name))
    except FileExistsError:
        print("that key file already exists; choose another --out", file=sys.stderr)
        return 2
    except ValueError as err:
        print(str(err), file=sys.stderr)
        return 2
    print(f"private key: {path} (keep it; readable by you only)")
    print("add this to the inventory under 'approvers:'")
    print(f"  {name}: {signer.public_text}")
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


def _store(inventory_path: str) -> object:
    from wheelhouse.crew import IncidentStore
    from wheelhouse.runtime import Inventory

    return IncidentStore(Inventory.load(inventory_path).state)


def _watch(ns: argparse.Namespace) -> int:
    import time

    from wheelhouse.crew import Crew, IncidentStore, Model
    from wheelhouse.providers import choose_provider
    from wheelhouse.runtime import Runner

    runner = _runner(ns.inventory)
    assert isinstance(runner, Runner)
    store = IncidentStore(runner.inventory.state)
    provider = choose_provider(Settings())
    if provider is None:
        print("no model configured: incidents will be detected but not investigated")
    # The watch loop runs approved changes; it never holds an approver's key.
    crew = Crew(runner, store, Model(provider) if provider else None)
    while True:
        try:
            report = crew.run_once()
        except Exception as err:  # noqa: BLE001 - report and keep watching
            print(f"pass failed ({type(err).__name__}: {err}); retrying next pass")
            if ns.once:
                return 1
            time.sleep(ns.interval)
            continue
        sw = report.sweep
        print(
            f"sweep: {len(sw.opened)} new, {len(sw.still_open)} still open, "
            f"{len(sw.recovered)} recovered, {len(sw.unreachable)} unreachable"
        )
        for iid, status in {**report.investigated, **report.executed}.items():
            print(f"  {iid}: {status}")
        for name in store.unreadable:
            print(f"  warning: incident file {name} could not be read; it was skipped")
        if ns.once:
            return 0
        time.sleep(ns.interval)


def _incidents(ns: argparse.Namespace) -> int:
    from wheelhouse.crew import IncidentStore

    store = _store(ns.inventory)
    assert isinstance(store, IncidentStore)
    if ns.id is None:
        for i in store.all():
            print(f"{i.id}  {i.status.value:<18} {i.host:<8} {i.title}")
        return 0
    try:
        print(store.get(ns.id).model_dump_json(indent=2))
    except KeyError:
        print("no such incident", file=sys.stderr)
        return 2
    return 0


def _console(ns: argparse.Namespace) -> int:
    from wheelhouse.console import Console
    from wheelhouse.crew import IncidentStore
    from wheelhouse.runtime import Inventory

    inv = Inventory.load(ns.inventory)
    key_path = Path(ns.key) if ns.key else _default_key_path(ns.approver)
    try:
        signer = ApproverKey.load(ns.approver, key_path)
    except (OSError, ValueError) as err:
        print(f"cannot use approver key {key_path}: {err}", file=sys.stderr)
        return 2
    if inv.approvers.get(ns.approver) != signer.public_text:
        print(
            f"approver '{ns.approver}' with this key is not listed in {ns.inventory}",
            file=sys.stderr,
        )
        return 2
    console = Console(IncidentStore(inv.state), signer, inv, port=ns.port)
    server = console.server()
    print(f"approval console for {signer.name} (it signs approvals; it never runs changes)")
    print(f"open once: http://127.0.0.1:{console.port}/login?token={console.login_token}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
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
    approve.add_argument("--by", required=True, help="your approver name in the inventory")
    approve.add_argument("--key", help="your private key (default ~/.wheelhouse/approvers/)")
    approve.add_argument("--minutes", type=int, default=30)
    approve.add_argument("--out")
    keys = sub.add_parser("keys", help="create an approver key pair")
    keys.add_argument("what", choices=["new"])
    keys.add_argument("name")
    keys.add_argument("--out")
    sub.add_parser("hosts", help="list inventory hosts and check they are reachable")
    sub.add_parser("mcp", help="serve the inventory to MCP clients over stdio (look only)")
    watch = sub.add_parser("watch", help="run the crew: detect, investigate, plan, execute")
    watch.add_argument("--once", action="store_true", help="one pass, then exit")
    watch.add_argument("--interval", type=int, default=60, help="seconds between passes")
    incidents = sub.add_parser("incidents", help="list incidents, or show one as JSON")
    incidents.add_argument("id", nargs="?")
    console = sub.add_parser("console", help="local web page to approve or reject plans")
    console.add_argument("--as", dest="approver", required=True, help="your approver name")
    console.add_argument("--key", help="your private key (default ~/.wheelhouse/approvers/)")
    console.add_argument("--port", type=int, default=8765)
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
        return _approve(ns)
    if ns.command == "keys":
        return _keys_new(ns.name, ns.out)
    if ns.command == "hosts":
        return _hosts(ns.inventory)
    if ns.command == "mcp":
        return _mcp(ns.inventory)
    if ns.command == "watch":
        return _watch(ns)
    if ns.command == "incidents":
        return _incidents(ns)
    if ns.command == "console":
        return _console(ns)
    return _ledger(ns.inventory, ns.what, ns.n)


if __name__ == "__main__":
    raise SystemExit(main())
