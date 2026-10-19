import shlex
import stat
import sys
from pathlib import Path

import pytest

from wheelhouse.runtime import Host, Limits, SSHTransport
from wheelhouse.safety import default_catalog

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="uses a POSIX fake ssh")


def fake_ssh(tmp_path: Path, shell: str = "/bin/bash", sleep: float = 0) -> Path:
    """A stand-in for ssh: records its argv, answers the shell probe, echoes the command."""
    log = tmp_path / "argv.log"
    script = tmp_path / "ssh"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import sys, json, time\n"
        f"open({str(log)!r}, 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "import shlex\n"
        "remote = sys.argv[-1]\n"
        "if 'SHELL' in remote:\n"
        f"    sys.stdout.write({shell!r}); sys.exit(0)\n"
        "words = shlex.split(remote)\n"
        "limit = float(words[3]) if words[:1] == ['timeout'] else 1e9\n"
        f"if {sleep} > limit:\n"
        "    time.sleep(limit); sys.exit(124)\n"
        f"time.sleep({sleep})\n"
        "sys.stdout.write('ran: ' + remote)\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def host(tmp_path: Path) -> Host:
    return Host(address="10.0.0.11", user="wheelhouse", identity_file=tmp_path / "id")


def test_command_is_quoted_and_options_are_strict(tmp_path: Path) -> None:
    import json

    t = SSHTransport(str(tmp_path / "kh"), Limits(), ssh_binary=str(fake_ssh(tmp_path)))
    action = default_catalog().render(
        "mysql_query", {"database": "app", "sql": "SELECT '$(id)' FROM t WHERE a = 'x;y'"}
    )
    res = t.run("db01", host(tmp_path), action)
    assert res.status == "ok"
    calls = [json.loads(line) for line in (tmp_path / "argv.log").read_text().splitlines()]
    argv = calls[-1]
    assert shlex.split(argv[-1]) == ["timeout", "-k", "5", str(action.timeout_s), *action.argv]
    assert f'UserKnownHostsFile="{tmp_path / "kh"}"' in argv
    assert argv[argv.index("--") - 1] == "10.0.0.11"
    for opt in (
        "BatchMode=yes",
        "StrictHostKeyChecking=yes",
        "ForwardAgent=no",
        "PermitLocalCommand=no",
    ):
        assert opt in argv
    assert argv[0:2] == ["-F", "none"]


def test_non_posix_shell_is_refused(tmp_path: Path) -> None:
    t = SSHTransport(
        str(tmp_path / "kh"), Limits(), ssh_binary=str(fake_ssh(tmp_path, shell="/usr/bin/fish"))
    )
    res = t.run("web01", host(tmp_path), default_catalog().render("uptime", {}))
    assert res.status == "error" and b"not a POSIX shell" in res.output


def test_timeout_is_enforced(tmp_path: Path) -> None:
    from wheelhouse.safety import ActionSpec, Catalog, Tier

    t = SSHTransport(str(tmp_path / "kh"), Limits(), ssh_binary=str(fake_ssh(tmp_path, sleep=5)))
    slow = Catalog([ActionSpec("up", Tier.LOOK, "x", ("uptime",), timeout_s=1)]).render("up", {})
    res = t.run("web01", host(tmp_path), slow)
    assert res.status == "timeout" and res.duration_ms < 4000


def test_output_is_capped(tmp_path: Path) -> None:
    t = SSHTransport(
        str(tmp_path / "kh"), Limits(max_output_bytes=1000), ssh_binary=str(fake_ssh(tmp_path))
    )
    action = default_catalog().render(
        "mysql_query", {"database": "app", "sql": "SELECT '" + "a" * 3000 + "'"}
    )
    res = t.run("db01", host(tmp_path), action)
    assert len(res.output) == 1000 and res.truncated


def test_known_hosts_path_with_quote_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        SSHTransport('/tmp/a"b', Limits())
