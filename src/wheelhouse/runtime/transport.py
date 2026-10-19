"""SSH transport.

Runs the system ssh client with an argument list (no local shell). The remote command
is always RenderedAction.remote_command(), which quotes every argument with shlex.join,
because the remote side passes the string to the account's login shell.

Safety properties:
- user ssh config is ignored (-F none); host keys must already be pinned
  (StrictHostKeyChecking=yes with a dedicated known_hosts file); no agent or X11
  forwarding; batch mode, so it never prompts.
- the remote command runs under `timeout -k 5 N`, so it is stopped on the server too,
  not only the local client; the local client has its own, slightly longer, limit.
- output is capped.
- before the first command on a host, the login shell is checked to be a POSIX shell,
  because shlex quoting is only correct for POSIX shells.
"""

from __future__ import annotations

import posixpath
import shlex
import subprocess
import time
from dataclasses import dataclass
from typing import Protocol

from wheelhouse.runtime.inventory import Host, Limits
from wheelhouse.safety.catalog import RenderedAction

POSIX_SHELLS = frozenset({"sh", "bash", "dash", "ksh", "zsh", "ash"})
_SHELL_PROBE = 'printf "%s" "$SHELL"'


@dataclass(frozen=True)
class CommandResult:
    status: str  # ok, failed, timeout, error
    exit_code: int | None
    output: bytes
    duration_ms: int
    truncated: bool = False


class Transport(Protocol):
    def run(self, name: str, host: Host, action: RenderedAction) -> CommandResult: ...


class SSHTransport:
    def __init__(self, known_hosts: str, limits: Limits, ssh_binary: str = "ssh") -> None:
        if any(c in known_hosts for c in '"%\n\r'):
            raise ValueError("known_hosts path must not contain quotes, % or line breaks")
        self.known_hosts = known_hosts
        self.limits = limits
        self.ssh_binary = ssh_binary
        self._shell_ok: dict[str, str] = {}

    def _base(self, host: Host) -> list[str]:
        return [
            self.ssh_binary,
            "-F", "none",
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=yes",
            "-o", f'UserKnownHostsFile="{self.known_hosts}"',
            "-o", "GlobalKnownHostsFile=none",
            "-o", "IdentitiesOnly=yes",
            "-o", "ForwardAgent=no",
            "-o", "ForwardX11=no",
            "-o", "ClearAllForwardings=yes",
            "-o", "PermitLocalCommand=no",
            "-o", f"ConnectTimeout={self.limits.connect_timeout_s}",
            "-o", "ServerAliveInterval=5",
            "-o", "ServerAliveCountMax=2",
            "-o", "LogLevel=ERROR",
            "-i", str(host.identity_file),
            "-p", str(host.port),
            "-l", host.user,
            "-T",
            host.address,
            "--",
        ]  # fmt: skip

    def _exec(self, host: Host, remote: str, timeout_s: int) -> CommandResult:
        cmd = [*self._base(host), remote]
        local_limit = timeout_s + self.limits.connect_timeout_s + 10
        start = time.monotonic()
        try:
            proc = subprocess.run(  # noqa: S603 - argument list, no shell
                cmd,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=local_limit,
                check=False,
            )
        except subprocess.TimeoutExpired as err:
            out = (err.stdout or b"") + (err.stderr or b"")
            return self._result("timeout", None, out, start)
        except OSError as err:
            return self._result("error", None, str(err).encode(), start)
        out = proc.stdout + (b"\n--- stderr ---\n" + proc.stderr if proc.stderr else b"")
        if proc.returncode == 255:
            return self._result("error", 255, out, start)
        if proc.returncode in (124, 137):  # remote `timeout` stopped the command
            return self._result("timeout", proc.returncode, out, start)
        return self._result("ok" if proc.returncode == 0 else "failed", proc.returncode, out, start)

    def _result(self, status: str, code: int | None, out: bytes, start: float) -> CommandResult:
        cap = self.limits.max_output_bytes
        return CommandResult(
            status,
            code,
            out[:cap],
            int((time.monotonic() - start) * 1000),
            truncated=len(out) > cap,
        )

    def shell_problem(self, name: str, host: Host) -> str | None:
        """None if the account's login shell is POSIX; otherwise why not."""
        if name in self._shell_ok:
            return None
        res = self._exec(host, _SHELL_PROBE, self.limits.connect_timeout_s + 5)
        if res.status != "ok":
            return f"could not reach {name} ({res.status})"
        shell = posixpath.basename(res.output.decode("utf-8", "replace").strip())
        if shell not in POSIX_SHELLS:
            return f"login shell '{shell or '?'}' on {name} is not a POSIX shell"
        self._shell_ok[name] = shell
        return None

    def run(self, name: str, host: Host, action: RenderedAction) -> CommandResult:
        problem = self.shell_problem(name, host)
        if problem:
            return CommandResult("error", None, problem.encode(), 0)
        remote = shlex.join(["timeout", "-k", "5", str(action.timeout_s), *action.argv])
        return self._exec(host, remote, action.timeout_s)


class RateLimiter:
    """Sliding one-minute window per host."""

    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self._events: dict[str, list[float]] = {}

    def allow(self, host: str, now: float | None = None) -> bool:
        t = time.monotonic() if now is None else now
        window = [x for x in self._events.get(host, []) if t - x < 60.0]
        if len(window) >= self.per_minute:
            self._events[host] = window
            return False
        window.append(t)
        self._events[host] = window
        return True
