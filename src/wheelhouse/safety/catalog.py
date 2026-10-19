"""The action catalog: the allowlist of typed actions agents may request.

Agents never write commands. They name an action and give arguments. Every argument is
validated, then the action is rendered to an argument list with no shell. A placeholder
must be a whole argument ("{service}"), never part of one, so an argument value can
never change the shape of the command.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field

from wheelhouse.safety.sql import read_only_sql_reason
from wheelhouse.safety.tiers import Tier

_PLACEHOLDER = re.compile(r"^\{([a-z_][a-z0-9_]*)\}$")
_ANY_BRACE = re.compile(r"[{}]")

MAX_ARG_LENGTH = 10_000


class CatalogError(ValueError):
    """An action request that cannot be rendered."""


@dataclass(frozen=True)
class Param:
    """A parameter: a strict pattern, or a custom check that returns a reason or None."""

    description: str
    pattern: str | None = None
    check: Callable[[str], str | None] | None = None
    max_length: int = 255

    def problem(self, value: object) -> str | None:
        if not isinstance(value, str):
            return "must be text"
        if not value:
            return "must not be empty"
        if len(value) > min(self.max_length, MAX_ARG_LENGTH):
            return "too long"
        if value.startswith("-"):
            return "must not start with '-'"
        if self.pattern is not None and not re.fullmatch(self.pattern, value):
            return "does not match the allowed pattern"
        if self.check is not None:
            return self.check(value)
        if self.pattern is None:
            return "has no validation rule"
        return None


# Reusable parameter rules.
HOST = Param("Host name or IPv4 address", r"[A-Za-z0-9][A-Za-z0-9.\-]{0,252}")
SERVICE = Param(
    "systemd service name, bare or ending in .service (no targets or other unit types)",
    r"[A-Za-z0-9][A-Za-z0-9_\-]{0,63}(?:@[A-Za-z0-9_\-]{1,64})?(?:\.service)?",
)
LINES = Param("Number of lines, 1 to 500", r"(?:[1-9][0-9]?|[1-4][0-9]{2}|500)")
DATABASE = Param("Database name", r"[A-Za-z0-9_][A-Za-z0-9_]{0,63}")
QUEUE_VHOST = Param("RabbitMQ virtual host", r"/|[A-Za-z0-9_][A-Za-z0-9_.\-]{0,63}")
READ_ONLY_MYSQL = Param(
    "A single read-only MySQL statement",
    check=lambda v: read_only_sql_reason(v, "mysql"),
    max_length=10_000,
)


@dataclass(frozen=True)
class ActionSpec:
    name: str
    tier: Tier
    description: str
    argv: tuple[str, ...]
    params: Mapping[str, Param] = field(default_factory=dict)
    timeout_s: int = 30
    rollback_note: str = ""

    def __post_init__(self) -> None:
        if self.tier is Tier.NEVER:
            raise CatalogError(f"{self.name}: the catalog cannot contain Never actions")
        if self.tier is Tier.TOUCH and not self.rollback_note.strip():
            raise CatalogError(f"{self.name}: Touch actions must say how to roll back")
        if not self.argv:
            raise CatalogError(f"{self.name}: empty command")
        used: set[str] = set()
        for tok in self.argv:
            m = _PLACEHOLDER.match(tok)
            if m:
                used.add(m.group(1))
            elif _ANY_BRACE.search(tok):
                raise CatalogError(f"{self.name}: placeholders must be whole arguments")
        if _PLACEHOLDER.match(self.argv[0]):
            raise CatalogError(f"{self.name}: the program cannot be a parameter")
        if used != set(self.params):
            raise CatalogError(f"{self.name}: parameters and placeholders do not match")
        if not 1 <= self.timeout_s <= 600:
            raise CatalogError(f"{self.name}: timeout must be 1 to 600 seconds")


@dataclass(frozen=True)
class RenderedAction:
    name: str
    tier: Tier
    argv: tuple[str, ...]
    timeout_s: int
    rollback_note: str

    def remote_command(self) -> str:
        """The command string for SSH. A remote shell re-parses whatever string it gets,
        so every argument is quoted with shlex.join. Transports must use this, never a
        plain join."""
        return shlex.join(self.argv)


class Catalog:
    def __init__(self, specs: Iterable[ActionSpec]) -> None:
        self._specs: dict[str, ActionSpec] = {}
        for spec in specs:
            if spec.name in self._specs:
                raise CatalogError(f"duplicate action '{spec.name}'")
            self._specs[spec.name] = spec

    def __contains__(self, name: object) -> bool:
        return name in self._specs

    def __len__(self) -> int:
        return len(self._specs)

    def specs(self) -> list[ActionSpec]:
        return sorted(self._specs.values(), key=lambda s: (s.tier, s.name))

    def render(self, name: str, args: Mapping[str, object]) -> RenderedAction:
        spec = self._specs.get(name)
        if spec is None:
            raise CatalogError(f"unknown action '{name}'")
        unknown = set(args) - set(spec.params)
        if unknown:
            raise CatalogError(f"{name}: unknown arguments {sorted(unknown)}")
        missing = set(spec.params) - set(args)
        if missing:
            raise CatalogError(f"{name}: missing arguments {sorted(missing)}")
        for key, param in spec.params.items():
            problem = param.problem(args[key])
            if problem:
                raise CatalogError(f"{name}: argument '{key}' {problem}")
        argv: list[str] = []
        for tok in spec.argv:
            m = _PLACEHOLDER.match(tok)
            argv.append(str(args[m.group(1)]) if m else tok)
        return RenderedAction(spec.name, spec.tier, tuple(argv), spec.timeout_s, spec.rollback_note)


def default_catalog() -> Catalog:
    """Actions available out of the box for Linux hosts, MySQL and RabbitMQ."""
    look = Tier.LOOK
    touch = Tier.TOUCH
    return Catalog(
        [
            ActionSpec(
                "ping",
                look,
                "Check that a host answers (4 packets)",
                ("ping", "-c", "4", "-W", "2", "{target}"),
                {"target": HOST},
                timeout_s=15,
            ),
            ActionSpec("uptime", look, "Uptime and load averages", ("uptime",)),
            ActionSpec("disk_usage", look, "Disk usage per file system", ("df", "-h")),
            ActionSpec("inode_usage", look, "Inode usage per file system", ("df", "-i")),
            ActionSpec("memory", look, "Memory and swap in MB", ("free", "-m")),
            ActionSpec("load", look, "Load averages", ("cat", "/proc/loadavg")),
            ActionSpec(
                "top_processes",
                look,
                "Processes sorted by CPU",
                ("ps", "-eo", "pid,user,comm,%cpu,%mem,etime", "--sort=-%cpu"),
            ),
            ActionSpec("listening_ports", look, "Listening TCP ports", ("ss", "-ltn")),
            ActionSpec(
                "service_status",
                look,
                "Status of a systemd service",
                ("systemctl", "status", "--no-pager", "{service}"),
                {"service": SERVICE},
            ),
            ActionSpec(
                "service_logs",
                look,
                "Recent log lines of a systemd service",
                ("journalctl", "--no-pager", "-u", "{service}", "-n", "{lines}"),
                {"service": SERVICE, "lines": LINES},
            ),
            ActionSpec(
                "mysql_query",
                look,
                "Run one read-only MySQL statement",
                ("mysql", "--batch", "--database", "{database}", "--execute", "{sql}"),
                {"database": DATABASE, "sql": READ_ONLY_MYSQL},
                timeout_s=60,
            ),
            ActionSpec(
                "mysql_status", look, "MySQL server status counters", ("mysqladmin", "status")
            ),
            ActionSpec(
                "rabbitmq_queues",
                look,
                "Queues with message and consumer counts",
                ("rabbitmqctl", "list_queues", "-p", "{vhost}", "name", "messages", "consumers"),
                {"vhost": QUEUE_VHOST},
            ),
            ActionSpec(
                "service_restart",
                touch,
                "Restart a systemd service",
                ("systemctl", "restart", "{service}"),
                {"service": SERVICE},
                timeout_s=120,
                rollback_note="Restart is idempotent. If the service does not come "
                "back, check service_status and service_logs and "
                "escalate; no automatic retry.",
            ),
            ActionSpec(
                "service_start",
                touch,
                "Start a stopped systemd service",
                ("systemctl", "start", "{service}"),
                {"service": SERVICE},
                timeout_s=120,
                rollback_note="Roll back with service_stop on the same service.",
            ),
            ActionSpec(
                "service_stop",
                touch,
                "Stop a systemd service",
                ("systemctl", "stop", "{service}"),
                {"service": SERVICE},
                timeout_s=120,
                rollback_note="Roll back with service_start on the same service.",
            ),
        ]
    )
