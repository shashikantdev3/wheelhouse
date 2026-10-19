"""Command line: wheelhouse doctor | catalog | check."""

from __future__ import annotations

import argparse
import platform
import sys
from collections.abc import Sequence

from wheelhouse import __version__
from wheelhouse.config import Settings
from wheelhouse.safety import Lockkeeper, Verdict


def _doctor() -> int:
    settings = Settings()
    keeper = Lockkeeper()
    print(f"wheelhouse {__version__} on Python {platform.python_version()}")
    print("model providers (presence only, values never shown):")
    for name, ok in settings.providers().items():
        print(f"  {name:<11} {'configured' if ok else 'not configured'}")
    key = settings.wheelhouse_approval_key
    key_ok = bool(key and len(key.get_secret_value().encode()) >= 32)
    print(
        f"approval key: {'configured' if key_ok else 'not configured (Touch actions cannot run)'}"
    )
    print(f"action catalog: {len(keeper.catalog)} actions")
    if not any(settings.providers().values()):
        print("no model provider configured: set ANTHROPIC_API_KEY or OPENROUTER_API_KEY in .env")
        return 1
    return 0


def _catalog() -> int:
    for spec in Lockkeeper().catalog.specs():
        params = ", ".join(spec.params) or "-"
        print(f"{spec.tier.value:<6} {spec.name:<16} {params:<14} {spec.description}")
    return 0


def _check(host: str, action: str, pairs: Sequence[str]) -> int:
    args: dict[str, object] = {}
    for pair in pairs:
        if "=" not in pair:
            print(f"argument '{pair}' must be key=value", file=sys.stderr)
            return 2
        key, value = pair.split("=", 1)
        args[key] = value
    decision = Lockkeeper().decide(host, action, args)
    print(f"verdict: {decision.verdict.value}")
    print(f"tier:    {decision.tier.value}")
    print(f"reason:  {decision.reason}")
    if decision.argv:
        print(f"argv:    {list(decision.argv)}")
    if decision.step_hash:
        print(f"step:    {decision.step_hash}")
    print("(dry run: nothing was executed)")
    return 0 if decision.verdict is not Verdict.REFUSED else 3


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wheelhouse")
    parser.add_argument("--version", action="version", version=f"wheelhouse {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="check the installation and which model keys are present")
    sub.add_parser("catalog", help="list the actions agents may request")
    check = sub.add_parser("check", help="ask Lockkeeper about an action (dry run)")
    check.add_argument("host")
    check.add_argument("action")
    check.add_argument("args", nargs="*", help="key=value")
    ns = parser.parse_args(argv)
    if ns.command == "doctor":
        return _doctor()
    if ns.command == "catalog":
        return _catalog()
    return _check(ns.host, ns.action, ns.args)


if __name__ == "__main__":
    raise SystemExit(main())
