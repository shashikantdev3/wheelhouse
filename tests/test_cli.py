from pathlib import Path

import pytest

from wheelhouse.cli import main


def test_doctor_never_prints_secret_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret-value-123")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "secret-value" not in out
    assert "anthropic   configured" in out


def test_doctor_without_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    for name in ("ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "OLLAMA_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    assert main(["doctor"]) == 1


def test_check_is_a_dry_run(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["check", "web01", "service_restart", "service=nginx"]) == 0
    out = capsys.readouterr().out
    assert "needs_approval" in out and "nothing was executed" in out
    assert main(["check", "web01", "service_status", "service=nginx;reboot"]) == 3


def test_catalog_lists_actions(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["catalog"]) == 0
    assert "service_restart" in capsys.readouterr().out


def _inventory(tmp_path: Path, approver_line: str) -> Path:
    inv = tmp_path / "wheelhouse.yaml"
    inv.write_text(
        "known_hosts: known_hosts\n"
        "approvers:\n"
        f"  {approver_line}\n"
        "hosts:\n"
        "  web01: {address: 10.0.0.11, user: wheelhouse, identity_file: id, services: [nginx]}\n"
    )
    return inv


def test_keys_new_then_approve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    key = tmp_path / "dev.key"
    assert main(["keys", "new", "dev", "--out", str(key)]) == 0
    out = capsys.readouterr().out
    line = next(x.strip() for x in out.splitlines() if x.strip().startswith("dev: ed25519:"))
    assert "BEGIN PRIVATE KEY" not in out
    assert main(["keys", "new", "dev", "--out", str(key)]) == 2  # never overwrites
    inv = _inventory(tmp_path, line)
    step = "ab" * 32
    args = ["--inventory", str(inv), "approve", step, "--by", "dev", "--key", str(key)]
    assert main([*args, "--out", "a.json"]) == 0
    assert "approved by dev" in capsys.readouterr().out
    # A key that is not the listed one is refused before it is used.
    other = tmp_path / "other.key"
    main(["keys", "new", "dev", "--out", str(other)])
    bad = ["--inventory", str(inv), "approve", step, "--by", "dev", "--key", str(other)]
    assert main([*bad, "--out", "b.json"]) == 2
    assert main(["--inventory", str(inv), "incidents"]) == 0


def test_console_refuses_an_unlisted_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    key = tmp_path / "dev.key"
    assert main(["keys", "new", "dev", "--out", str(key)]) == 0
    inv = _inventory(tmp_path, "dev: ed25519:" + "A" * 43)
    assert main(["--inventory", str(inv), "console", "--as", "dev", "--key", str(key)]) == 2
