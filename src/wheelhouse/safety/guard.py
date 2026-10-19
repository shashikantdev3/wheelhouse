"""Command guard: a second, independent allowlist.

Defence in depth. The catalog decides which actions exist; this guard re-checks every
rendered argument list against its own rules and fails closed: a program it does not
know, an option it does not know or a subcommand it does not know is refused. Adding a
new program to the catalog therefore also means adding a rule here, with tests.

The guard checks argument lists, not shell strings. A small set of wrappers (sudo with
a target user, timeout, nice) is unwrapped so the real program is checked.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from wheelhouse.safety.sql import read_only_sql_reason

Rule = Callable[[Sequence[str]], str | None]

_BAD_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_NUMBER = re.compile(r"[0-9]{1,6}")
_DURATION = re.compile(r"[0-9]{1,5}(?:\.[0-9]{1,3})?[smh]?")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.@:\-]{0,127}")
_HOST = re.compile(r"[A-Za-z0-9][A-Za-z0-9.\-]{0,252}")
_DB = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_]{0,63}")

# Units a Wheelhouse action must never start, stop or restart: they reboot, power off,
# isolate the machine, or cut off the agent's own access and logging.
PROTECTED_UNITS: frozenset[str] = frozenset(
    {
        "reboot",
        "poweroff",
        "halt",
        "kexec",
        "rescue",
        "emergency",
        "shutdown",
        "sshd",
        "ssh",
        "systemd-journald",
        "systemd-logind",
        "dbus",
        "dbus-broker",
        "systemd-networkd",
        "networkmanager",
        "network",
        "networking",
        "systemd-resolved",
        "auditd",
        "polkit",
        "systemd-udevd",
        "init",
        "user",
        "getty",
        "serial-getty",
        "autovt",
        "console-getty",
        "firewalld",
        "nftables",
        "iptables",
        "ip6tables",
        "ufw",
        "chronyd",
        "systemd-timesyncd",
    }
)


def program_name(token: str) -> str:
    """Basename of a program token, lower-cased: '/usr/bin/RM' -> 'rm'."""
    return posixpath.basename(token.replace("\\", "/")).lower()


@dataclass(frozen=True)
class Options:
    """A strict option grammar: known flags, known options with a value, positionals."""

    flags: frozenset[str] = frozenset()
    valued: dict[str, re.Pattern[str]] = field(default_factory=dict)
    positional: re.Pattern[str] | None = None
    max_positional: int = 0

    def check(self, args: Sequence[str]) -> tuple[list[str], str | None]:
        """Return (positionals, problem)."""
        positionals: list[str] = []
        i = 0
        while i < len(args):
            tok = args[i]
            if tok.startswith("-"):
                if tok in self.flags:
                    i += 1
                    continue
                name, eq, value = tok.partition("=")
                if name in self.valued:
                    if not eq:
                        if i + 1 >= len(args):
                            return positionals, f"option '{name}' needs a value"
                        value = args[i + 1]
                        i += 1
                    if not self.valued[name].fullmatch(value):
                        return positionals, f"value for '{name}' is not allowed"
                    i += 1
                    continue
                return positionals, f"option '{tok}' is not on the allowed list"
            if self.positional is None or not self.positional.fullmatch(tok):
                return positionals, f"argument '{tok}' is not allowed"
            positionals.append(tok)
            if len(positionals) > self.max_positional:
                return positionals, "too many arguments"
            i += 1
        return positionals, None


def _simple(options: Options) -> Rule:
    def rule(args: Sequence[str]) -> str | None:
        return options.check(args)[1]

    return rule


def _cat(args: Sequence[str]) -> str | None:
    allowed = {"/proc/loadavg", "/proc/meminfo", "/proc/cpuinfo", "/proc/uptime", "/etc/os-release"}
    if len(args) != 1 or args[0] not in allowed:
        return "cat may only read a fixed set of system files"
    return None


_SYSTEMCTL_READ = frozenset(
    {
        "status",
        "show",
        "is-active",
        "is-failed",
        "is-enabled",
        "list-units",
        "list-timers",
        "list-unit-files",
    }
)
_SYSTEMCTL_CHANGE = frozenset({"start", "stop", "restart", "reload", "try-restart"})
_SYSTEMCTL_OPTS = Options(
    flags=frozenset({"--no-pager", "--plain", "--no-legend", "--full", "--failed"}),
    valued={
        "--type": re.compile(r"service|timer|socket"),
        "--state": re.compile(r"[a-z,\-]{1,64}"),
    },
    positional=_NAME,
    max_positional=8,
)


def _unit_problem(unit: str) -> str | None:
    base = unit.lower()
    if base.endswith(".service"):
        base = base[: -len(".service")]
    elif "." in base.rsplit("@", 1)[-1]:
        return f"unit '{unit}' must be a service"
    base = base.split("@", 1)[0]
    if base in PROTECTED_UNITS:
        return f"unit '{unit}' is protected"
    return None


def _systemctl(args: Sequence[str]) -> str | None:
    if not args:
        return "systemctl needs a subcommand"
    sub, rest = args[0], args[1:]
    if sub not in _SYSTEMCTL_READ | _SYSTEMCTL_CHANGE:
        return f"systemctl '{sub}' is not on the allowed list"
    units, problem = _SYSTEMCTL_OPTS.check(rest)
    if problem:
        return problem
    if sub in _SYSTEMCTL_CHANGE:
        if len(units) != 1:
            return f"systemctl {sub} takes exactly one unit"
        return _unit_problem(units[0])
    return None


_JOURNALCTL = Options(
    flags=frozenset({"--no-pager", "-q", "--quiet", "-r", "--reverse"}),
    valued={
        "-u": _NAME,
        "--unit": _NAME,
        "-n": _NUMBER,
        "--lines": _NUMBER,
        "--since": re.compile(r"[0-9A-Za-z :\-]{1,32}"),
        "--until": re.compile(r"[0-9A-Za-z :\-]{1,32}"),
        "-p": re.compile(r"[0-7a-z.]{1,16}"),
        "--priority": re.compile(r"[0-7a-z.]{1,16}"),
        "-o": re.compile(r"short|short-iso|cat|json"),
        "--output": re.compile(r"short|short-iso|cat|json"),
    },
)


def _journalctl(args: Sequence[str]) -> str | None:
    problem = _JOURNALCTL.check(args)[1]
    if problem:
        return problem
    if (
        "-n" not in args
        and "--lines" not in args
        and not any(a.startswith("--lines=") for a in args)
    ):
        return "journalctl must be bounded with -n"
    return None


def _ss(args: Sequence[str]) -> str | None:
    for tok in args:
        if not re.fullmatch(r"-[ltnuaps46x]{1,8}", tok):
            return f"ss option '{tok}' is not allowed"
    if any("K" in t or "D" in t for t in args):
        return "ss kill or dump options are not allowed"
    return None


_PS = Options(
    flags=frozenset({"-e", "-A", "aux", "-ef", "--no-headers"}),
    valued={
        "-o": re.compile(r"[a-z%,]{1,128}"),
        "-eo": re.compile(r"[a-z%,]{1,128}"),
        "--sort": re.compile(r"[+\-]?[a-z%]{1,16}"),
        "-p": _NUMBER,
    },
)

_PING = Options(
    valued={
        "-c": re.compile(r"[1-9]|10"),
        "-W": re.compile(r"[1-9]"),
        "-w": re.compile(r"[1-9]|[1-5][0-9]"),
    },
    positional=_HOST,
    max_positional=1,
)


def _ping(args: Sequence[str]) -> str | None:
    positionals, problem = _PING.check(args)
    if problem:
        return problem
    if len(positionals) != 1:
        return "ping needs exactly one target"
    if "-c" not in args:
        return "ping must be bounded with -c"
    target = positionals[0]
    if re.fullmatch(r"(?:22[4-9]|23[0-9]|24[0-9]|25[0-5])\..*", target):
        return "multicast and broadcast targets are not allowed"
    return None


_MYSQL_OPTS = Options(
    flags=frozenset(
        {
            "--batch",
            "-B",
            "--table",
            "-t",
            "--skip-column-names",
            "-N",
            "--raw",
            "-r",
            "--silent",
            "-s",
            "--vertical",
            "-E",
            "--safe-updates",
            "--no-auto-rehash",
            "-A",
        }
    ),
    valued={
        "--database": _DB,
        "-D": _DB,
        "--host": _HOST,
        "-h": _HOST,
        "--port": _NUMBER,
        "-P": _NUMBER,
        "--user": _DB,
        "-u": _DB,
        "--connect-timeout": _NUMBER,
        "--execute": re.compile(r"(?s).+"),
        "-e": re.compile(r"(?s).+"),
    },
)


def _sql_client(dialect: str, statement_flags: tuple[str, ...], opts: Options) -> Rule:
    def rule(args: Sequence[str]) -> str | None:
        problem = opts.check(args)[1]
        if problem:
            return problem
        statements: list[str] = []
        i = 0
        while i < len(args):
            name, eq, value = args[i].partition("=")
            if args[i].startswith("-") and name in opts.valued:
                if not eq:
                    value = args[i + 1]
                    i += 1
                if name in statement_flags:
                    statements.append(value)
            i += 1
        if len(statements) != 1:
            return "a database client needs exactly one statement"
        reason = read_only_sql_reason(statements[0], dialect)
        return f"database statement refused: {reason}" if reason else None

    return rule


_PSQL_OPTS = Options(
    flags=frozenset(
        {
            "--no-psqlrc",
            "-X",
            "--no-align",
            "-A",
            "--tuples-only",
            "-t",
            "--quiet",
            "-q",
            "--no-password",
            "-w",
        }
    ),
    valued={
        "--dbname": _DB,
        "-d": _DB,
        "--host": _HOST,
        "-h": _HOST,
        "--port": _NUMBER,
        "-p": _NUMBER,
        "--username": _DB,
        "-U": _DB,
        "--command": re.compile(r"(?s).+"),
        "-c": re.compile(r"(?s).+"),
    },
)

_MYSQLADMIN_READ = frozenset({"status", "extended-status", "version", "ping", "variables"})


def _mysqladmin(args: Sequence[str]) -> str | None:
    opts = Options(
        valued={
            "--host": _HOST,
            "-h": _HOST,
            "--port": _NUMBER,
            "-P": _NUMBER,
            "--user": _DB,
            "-u": _DB,
            "--connect-timeout": _NUMBER,
        },
        positional=re.compile(r"[a-z\-]{1,32}"),
        max_positional=4,
    )
    commands, problem = opts.check(args)
    if problem:
        return problem
    if not commands:
        return "mysqladmin needs a command"
    for cmd in commands:
        if cmd not in _MYSQLADMIN_READ:
            return f"mysqladmin '{cmd}' is not on the allowed list"
    return None


def _rabbitmqctl(args: Sequence[str]) -> str | None:
    opts = Options(
        flags=frozenset({"-q", "--quiet", "--no-table-headers"}),
        valued={
            "-p": re.compile(r"/|[A-Za-z0-9_][A-Za-z0-9_.\-]{0,63}"),
            "--vhost": re.compile(r"/|[A-Za-z0-9_][A-Za-z0-9_.\-]{0,63}"),
            "-n": _NAME,
            "--node": _NAME,
            "--formatter": re.compile(r"json|table|pretty_table"),
        },
        positional=re.compile(r"[a-z_]{1,64}"),
        max_positional=12,
    )
    words, problem = opts.check(args)
    if problem:
        return problem
    if not words:
        return "rabbitmqctl needs a command"
    cmd = words[0]
    if not (
        cmd.startswith("list_") or cmd in {"status", "cluster_status", "node_health_check", "ping"}
    ):
        return f"rabbitmqctl '{cmd}' is not on the allowed list"
    return None


PROGRAM_RULES: dict[str, Rule] = {
    "uptime": _simple(Options(flags=frozenset({"-p", "--pretty", "-s", "--since"}))),
    "df": _simple(Options(flags=frozenset({"-h", "-i", "-T", "-P", "-l", "--local"}))),
    "free": _simple(Options(flags=frozenset({"-m", "-g", "-h", "-k", "-b", "-t", "-w"}))),
    "cat": _cat,
    "ps": _simple(_PS),
    "ss": _ss,
    "ping": _ping,
    "systemctl": _systemctl,
    "journalctl": _journalctl,
    "mysql": _sql_client("mysql", ("--execute", "-e"), _MYSQL_OPTS),
    "mariadb": _sql_client("mysql", ("--execute", "-e"), _MYSQL_OPTS),
    "psql": _sql_client("postgres", ("--command", "-c"), _PSQL_OPTS),
    "mysqladmin": _mysqladmin,
    "rabbitmqctl": _rabbitmqctl,
}


def _strip_wrappers(argv: Sequence[str]) -> tuple[list[str], str | None]:
    """Unwrap 'sudo -n -u USER', 'timeout DURATION' and 'nice -n N'. Any other use of a
    wrapper, or any other wrapper, is refused."""
    rest = list(argv)
    seen_sudo = False
    while rest:
        prog = program_name(rest[0])
        if prog == "sudo":
            if seen_sudo:
                return [], "nested sudo is not allowed"
            seen_sudo = True
            rest = rest[1:]
            while rest and rest[0].startswith("-"):
                tok = rest[0]
                if tok in {"-n", "--non-interactive", "-H"}:
                    rest = rest[1:]
                elif tok in {"-u", "--user"} and len(rest) > 1 and _DB.fullmatch(rest[1]):
                    rest = rest[2:]
                elif tok.startswith("--user=") and _DB.fullmatch(tok.split("=", 1)[1]):
                    rest = rest[1:]
                else:
                    return [], f"sudo option '{tok}' is not allowed"
        elif prog == "timeout":
            if len(rest) < 2 or not _DURATION.fullmatch(rest[1]):
                return [], "timeout must be followed by a plain duration"
            rest = rest[2:]
        elif prog == "nice":
            if len(rest) < 3 or rest[1] != "-n" or not re.fullmatch(r"1?[0-9]", rest[2]):
                return [], "nice must be used as 'nice -n N'"
            rest = rest[3:]
        else:
            break
    return rest, None


def changes_state(argv: Sequence[str]) -> bool:
    """True if the guard knows this command changes state. Lockkeeper refuses such a
    command when the catalog labels it Look, so a mis-tiered catalog entry cannot run
    without approval. Unknown commands are refused by destructive_reason anyway."""
    rest, reason = _strip_wrappers(argv)
    if reason or not rest:
        return True
    prog = program_name(rest[0])
    if prog == "systemctl":
        return len(rest) > 1 and rest[1] in _SYSTEMCTL_CHANGE
    return False


def destructive_reason(argv: Sequence[str]) -> str | None:
    """Return why this argument list may not run, or None if the guard's own allowlist
    accepts it. None does not mean 'allowed': the catalog and the tier still decide.
    Any unexpected error is a refusal, never a pass."""
    try:
        return _destructive_reason(argv)
    except Exception as err:  # noqa: BLE001 - the guard must fail closed
        return f"guard could not check this command ({type(err).__name__})"


def _destructive_reason(argv: Sequence[str]) -> str | None:
    if not isinstance(argv, (list, tuple)) or not argv:
        return "empty command"
    for tok in argv:
        if not isinstance(tok, str):
            return "non-text argument"
        if _BAD_CHARS.search(tok):
            return "control character in an argument"

    rest, reason = _strip_wrappers(argv)
    if reason:
        return reason
    if not rest:
        return "wrapper with no command"
    if rest[0] != posixpath.basename(rest[0]):
        return "programs must be named, not given as paths"

    prog = program_name(rest[0])
    rule = PROGRAM_RULES.get(prog)
    if rule is None or rest[0] != prog:
        return f"'{rest[0]}' is not on the guard's allowlist"
    return rule(rest[1:])
