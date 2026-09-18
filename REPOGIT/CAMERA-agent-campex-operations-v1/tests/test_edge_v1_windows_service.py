from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from app.edge_service import (
    install_service,
    start_service,
    stop_service,
    service_status,
)


def completed(returncode: int = 0, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess(
        args=["schtasks"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def test_windows_install_creates_scheduled_task(monkeypatch, tmp_path: Path) -> None:
    launcher = tmp_path / "run_campex_edge_windows.py"
    launcher.write_text("print('campex')")

    monkeypatch.setattr("app.edge_service._is_windows", lambda: True)
    monkeypatch.setattr("app.edge_service.WINDOWS_LAUNCHER_PATH", launcher)

    calls = []

    def fake_schtasks(args):
        calls.append(args)
        return completed()

    monkeypatch.setattr("app.edge_service._run_schtasks", fake_schtasks)

    powershell_calls = []

    def fake_powershell(script):
        powershell_calls.append(script)
        return completed()

    monkeypatch.setattr("app.edge_service._run_powershell", fake_powershell)

    with patch("app.edge_service.validate_edge_config"):
        result = install_service()

    assert result.ok
    assert calls
    assert calls[0][0] == "/Create"
    assert "Campex Edge" in calls[0]
    assert "ONSTART" in calls[0]
    assert "/RU" in calls[0]
    assert "SYSTEM" in calls[0]
    assert "/RL" in calls[0]
    assert "HIGHEST" in calls[0]

    assert powershell_calls
    settings = powershell_calls[0]
    assert "-RestartCount 999" in settings
    assert "-RestartInterval (New-TimeSpan -Minutes 1)" in settings
    assert "-StartWhenAvailable" in settings
    assert "-ExecutionTimeLimit ([TimeSpan]::Zero)" in settings
    assert "-MultipleInstances IgnoreNew" in settings


def test_windows_start_runs_task_and_waits_for_health(monkeypatch) -> None:
    monkeypatch.setattr("app.edge_service._is_windows", lambda: True)

    calls = []

    def fake_schtasks(args):
        calls.append(args)
        if args[0] == "/Query":
            return completed(stdout="Campex Edge")
        return completed()

    monkeypatch.setattr("app.edge_service._run_schtasks", fake_schtasks)
    monkeypatch.setattr(
        "app.edge_service._wait_for_api_health",
        lambda timeout_seconds=25.0: (
            True,
            "API pronta em http://127.0.0.1:8000/health",
        ),
    )

    result = start_service()

    assert result.ok
    assert any(call[0] == "/Run" for call in calls)


def test_windows_stop_ends_task(monkeypatch) -> None:
    monkeypatch.setattr("app.edge_service._is_windows", lambda: True)
    monkeypatch.setattr(
        "app.edge_service._run_schtasks",
        lambda args: completed(),
    )

    result = stop_service()

    assert result.ok


def test_windows_status_queries_task(monkeypatch) -> None:
    monkeypatch.setattr("app.edge_service._is_windows", lambda: True)
    monkeypatch.setattr(
        "app.edge_service._run_schtasks",
        lambda args: completed(stdout="Status: Running"),
    )

    result = service_status()

    assert result.ok
    assert "Running" in result.message
