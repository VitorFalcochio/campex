from __future__ import annotations

import plistlib
import subprocess
from pathlib import Path
from unittest.mock import patch

from app.config import ROOT
from app.edge_config import EdgeConfigError
from app.edge_service import (
    LABEL,
    install_service,
    render_plist,
    run_edge_service_command,
    start_service,
)


def test_launcher_uses_venv_config_check_and_run_edge_production() -> None:
    script = (ROOT / "deployment" / "run-campex-edge.sh").read_text(encoding="utf-8")

    assert 'ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"' in script
    assert 'PYTHON="${ROOT}/.venv/bin/python"' in script
    assert 'manage.py edge-config-check' in script
    assert 'exec "${PYTHON}" manage.py run-edge-production' in script
    assert "CAMPEX_CREDENTIAL_KEY" not in script


def test_launchd_plist_template_is_valid_and_contains_no_secret() -> None:
    text = render_plist(ROOT)
    payload = plistlib.loads(text.encode("utf-8"))

    assert payload["Label"] == LABEL
    assert payload["RunAtLoad"] is True
    assert payload["KeepAlive"] is True
    assert payload["WorkingDirectory"] == str(ROOT)
    assert payload["ProgramArguments"] == [str(ROOT / "deployment" / "run-campex-edge.sh")]
    assert payload["StandardOutPath"].endswith("logs/edge.stdout.log")
    assert payload["StandardErrorPath"].endswith("logs/edge.stderr.log")
    assert "CAMPEX_CREDENTIAL_KEY" not in text
    assert "CAMPEX_EDGE_SECRET" not in text


def test_install_service_runs_config_check_before_writing_plist(tmp_path: Path, monkeypatch) -> None:
    plist_path = tmp_path / "LaunchAgents" / f"{LABEL}.plist"
    monkeypatch.setattr("app.edge_service.PLIST_PATH", plist_path)
    monkeypatch.setattr("app.edge_service.LAUNCH_AGENTS_DIR", plist_path.parent)
    monkeypatch.setattr("app.edge_service.LAUNCHER_PATH", ROOT / "deployment" / "run-campex-edge.sh")

    with patch("app.edge_service.validate_edge_config") as check:
        result = install_service()

    assert result.ok
    check.assert_called_once()
    assert plist_path.exists()
    assert plistlib.loads(plist_path.read_bytes())["Label"] == LABEL


def test_install_service_refuses_invalid_config(tmp_path: Path, monkeypatch) -> None:
    plist_path = tmp_path / "LaunchAgents" / f"{LABEL}.plist"
    monkeypatch.setattr("app.edge_service.PLIST_PATH", plist_path)
    monkeypatch.setattr("app.edge_service.LAUNCH_AGENTS_DIR", plist_path.parent)

    with patch("app.edge_service.validate_edge_config", side_effect=EdgeConfigError("chave invalida")):
        result = install_service()

    assert not result.ok
    assert "Campex Edge configuration error" in result.message
    assert not plist_path.exists()


def test_start_service_uses_launchctl_without_printing_secrets(tmp_path: Path, monkeypatch) -> None:
    plist_path = tmp_path / f"{LABEL}.plist"
    plist_path.write_text(render_plist(ROOT), encoding="utf-8")
    monkeypatch.setattr("app.edge_service.PLIST_PATH", plist_path)
    calls: list[list[str]] = []

    def fake_run(args: list[str]):
        calls.append(args)
        return subprocess.CompletedProcess(args=["launchctl", *args], returncode=0, stdout="", stderr="")

    monkeypatch.setattr("app.edge_service._run_launchctl", fake_run)
    monkeypatch.setattr("app.edge_service._wait_for_api_health", lambda: (True, "API pronta em http://127.0.0.1:8000/health"))

    result = start_service()

    assert result.ok
    assert calls[0][:2] == ["bootstrap", f"gui/{__import__('os').getuid()}"]
    assert calls[1] == ["kickstart", "-k", f"gui/{__import__('os').getuid()}/{LABEL}"]
    assert "CAMPEX_CREDENTIAL_KEY" not in result.message
    assert "API pronta" in result.message


def test_start_service_reports_clean_timeout_when_api_does_not_become_ready(tmp_path: Path, monkeypatch) -> None:
    plist_path = tmp_path / f"{LABEL}.plist"
    plist_path.write_text(render_plist(ROOT), encoding="utf-8")
    monkeypatch.setattr("app.edge_service.PLIST_PATH", plist_path)
    monkeypatch.setattr(
        "app.edge_service._run_launchctl",
        lambda args: subprocess.CompletedProcess(args=["launchctl", *args], returncode=0, stdout="", stderr=""),
    )
    monkeypatch.setattr("app.edge_service._wait_for_api_health", lambda: (False, "timeout aguardando /health"))

    result = start_service()

    assert not result.ok
    assert "Serviço carregado, mas API não ficou pronta" in result.message
    assert "timeout aguardando /health" in result.message


def test_edge_service_commands_dispatch_status(monkeypatch) -> None:
    completed = subprocess.CompletedProcess(args=["launchctl"], returncode=0, stdout="service = ok", stderr="")
    monkeypatch.setattr("app.edge_service._run_launchctl", lambda args: completed)

    result = run_edge_service_command("status")

    assert result.ok
    assert "service = ok" in result.message
