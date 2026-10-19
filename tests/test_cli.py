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
