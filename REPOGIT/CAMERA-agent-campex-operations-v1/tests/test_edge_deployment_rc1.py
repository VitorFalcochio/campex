from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import api
from app.database import connect, init_db
from app.edge_pilot_check import PilotCheckReport
from app.models import criar_camera, criar_cliente, criar_machine_monitor, criar_unidade, registrar_edge_heartbeat
from edge_agent.sync_outbox import enqueue_sync_event
from deployment.doctor import BLOCKED, FAIL, NOT_CONFIGURED, NOT_VERIFIED, PASS, WARNING, format_doctor, main as doctor_main, run_doctor
from deployment.preflight import main as preflight_main
from deployment.setup import PASS as SETUP_PASS, WARNING as SETUP_WARNING, run_setup


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ready_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, monitor: bool = True, outbox: int = 0) -> Path:
    db_path = tmp_path / "edge.sqlite3"
    evidence = tmp_path / "evidence"
    monkeypatch.setenv("CAMPEX_EDGE_ID", "edge_factory_01")
    monkeypatch.setenv("CAMPEX_CREDENTIAL_KEY", "credential-key-with-enough-length")
    monkeypatch.setattr("deployment.doctor.EVIDENCE_DIR", evidence)
    monkeypatch.setattr("deployment.setup.DATABASE_PATH", db_path)
    monkeypatch.setattr("deployment.setup.EVIDENCE_DIR", evidence)
    monkeypatch.setattr("deployment.setup.LOG_DIR", tmp_path / "logs")
    with connect(db_path) as connection:
        init_db(connection)
        cliente_id = criar_cliente(connection, "Cliente")
        unidade_id = criar_unidade(connection, cliente_id, "Fábrica")
        camera_id = criar_camera(
            connection,
            unidade_id,
            "Camera",
            cliente_id=cliente_id,
            edge_id="edge_factory_01",
            rtsp_host="10.0.0.10",
            rtsp_username="operador",
            rtsp_password="senha-super-secreta",
            status="online",
        )
        if monitor:
            monitor_id = criar_machine_monitor(
                connection,
                cliente_id,
                unidade_id,
                camera_id,
                "A6",
                [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.1}, {"x": 0.9, "y": 0.9}],
                [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.1}, {"x": 0.9, "y": 0.9}],
                ativo=True,
            )
            connection.execute("UPDATE machine_monitors SET calibration_result = 'READY' WHERE id = ?", (monitor_id,))
        for index in range(outbox):
            enqueue_sync_event(connection, f"evt-{index}", cliente_id, {"event_uuid": f"evt-{index}"}, edge_id="edge_factory_01")
        registrar_edge_heartbeat(
            connection,
            "edge_factory_01",
            heartbeat_at=_now_iso(),
            camera_online=True,
            last_frame_at=_now_iso(),
            capture_fps=15.0,
            inference_fps=4.0,
            frames_analyzed=50,
            outbox_pending=outbox,
            disk_free_bytes=50_000_000_000,
            disk_used_percent=10.0,
        )
    return db_path


def _patch_ready_runtime(monkeypatch: pytest.MonkeyPatch, *, camera: bool = True, inference: bool = True) -> None:
    monkeypatch.setattr("deployment.doctor.PLIST_PATH", Path("/tmp/com.campex.edge.plist"))
    monkeypatch.setattr("deployment.doctor.service_status", lambda: type("R", (), {"ok": True, "message": "state = running\npid = 123"})())
    monkeypatch.setattr("deployment.doctor._tcp_reachable", lambda host, port, timeout: (camera, f"{host}:{port}" if camera else "CAMERA_HOST_UNREACHABLE: verificar rede/IP/porta"))

    def fake_http(url: str, _timeout: float):
        if url.endswith("/health"):
            return 200, {"status": "ok"}, None
        if url.endswith("/ready"):
            return 200, {
                "status": "ready" if camera and inference else "not_ready",
                "camera_stream": "ready" if camera else "not_ready",
                "inference": "ready" if inference else "not_ready",
            }, None
        return 0, None, "unexpected"

    monkeypatch.setattr("deployment.doctor._http_json", fake_http)


def _status(report, label: str) -> str:
    return next(item.status for item in report.checks if item.label == label)


def test_doctor_ready_exit_code_and_sanitized_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    db_path = _ready_db(tmp_path, monkeypatch)
    _patch_ready_runtime(monkeypatch)

    code = doctor_main(["--db", str(db_path), "--api-url", "http://127.0.0.1:8000", "--min-free-gb", "0"])
    output = capsys.readouterr().out

    assert code == 0
    assert "CAMPEX EDGE DOCTOR" in output
    assert "RESULT: READY" in output
    assert "senha-super-secreta" not in output
    assert "credential-key" not in output


def test_doctor_separates_installed_service_from_running_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = _ready_db(tmp_path, monkeypatch)
    plist = tmp_path / "com.campex.edge.plist"
    plist.write_text("installed", encoding="utf-8")
    monkeypatch.setattr("deployment.doctor.PLIST_PATH", plist)
    monkeypatch.setattr(
        "deployment.doctor.service_status",
        lambda: type("R", (), {"ok": True, "message": "Serviço não carregado."})(),
    )

    def fake_http(url: str, _timeout: float):
        if url.endswith("/health"):
            return 0, None, "API local indisponível"
        if url.endswith("/ready"):
            return 0, None, "API local indisponível"
        if url.endswith("/edge/status"):
            return 0, None, "API local indisponível"
        return 0, None, "unexpected"

    monkeypatch.setattr("deployment.doctor._http_json", fake_http)

    report = run_doctor(db_path=db_path, min_free_gb=0)

    assert _status(report, "Service installed") == PASS
    assert _status(report, "Service running") == FAIL
    assert _status(report, "API responding") == FAIL
    assert report.exit_code == 1


def test_doctor_reports_camera_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = _ready_db(tmp_path, monkeypatch)
    _patch_ready_runtime(monkeypatch, camera=False)

    report = run_doctor(db_path=db_path, min_free_gb=0)

    assert report.exit_code == 1
    assert _status(report, "Frame freshness") == BLOCKED
    assert report.result == "NOT READY"


def test_doctor_reports_monitor_not_configured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = _ready_db(tmp_path, monkeypatch, monitor=False)
    _patch_ready_runtime(monkeypatch)

    report = run_doctor(db_path=db_path, min_free_gb=0)

    assert _status(report, "Machine monitor configured") == FAIL
    assert _status(report, "Machine monitor loaded/calibrated") == FAIL
    assert report.exit_code == 1


def test_doctor_reports_outbox_backlog_as_warning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = _ready_db(tmp_path, monkeypatch, outbox=2)
    _patch_ready_runtime(monkeypatch)

    report = run_doctor(db_path=db_path, min_free_gb=0)

    assert _status(report, "Outbox") == WARNING
    assert report.exit_code == 0


def test_doctor_does_not_classify_local_api_401_as_rtsp_credentials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = _ready_db(tmp_path, monkeypatch)
    monkeypatch.setattr("deployment.doctor.PLIST_PATH", Path("/tmp/com.campex.edge.plist"))
    monkeypatch.setattr("deployment.doctor.service_status", lambda: type("R", (), {"ok": True, "message": "state = running\npid = 123"})())
    monkeypatch.setattr("deployment.doctor._tcp_reachable", lambda host, port, timeout: (True, f"{host}:{port}"))

    def fake_http(url: str, _timeout: float):
        if url.endswith("/health"):
            return 200, {"status": "ok"}, None
        if url.endswith("/ready"):
            return 200, {"status": "not_ready", "camera_stream": "not_ready", "inference": "not_ready"}, None
        if url.endswith("/edge/status"):
            raise AssertionError("Doctor must not require protected /edge/status")
        return 0, None, "unexpected"

    monkeypatch.setattr("deployment.doctor._http_json", fake_http)

    output = format_doctor(run_doctor(db_path=db_path, min_free_gb=0))

    assert "Camera/RTSP network" in output
    assert "API_AUTH_ERROR" not in output
    assert "RTSP_AUTH_FAILED" not in output
    assert "Unauthorized" not in output


def test_edge_status_remains_protected_while_doctor_uses_local_readiness() -> None:
    response = TestClient(api).get("/edge/status")

    assert response.status_code == 401


def test_doctor_blocks_dependent_checks_when_camera_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = _ready_db(tmp_path, monkeypatch)
    _patch_ready_runtime(monkeypatch, camera=False, inference=False)

    report = run_doctor(db_path=db_path, min_free_gb=0)

    assert _status(report, "Camera/RTSP network") == FAIL
    assert _status(report, "Frame freshness") == BLOCKED
    assert _status(report, "Inference status") == BLOCKED


def test_doctor_open_rtsp_port_is_network_pass_not_auth_verification(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = _ready_db(tmp_path, monkeypatch)
    monkeypatch.setattr("deployment.doctor.PLIST_PATH", Path("/tmp/com.campex.edge.plist"))
    monkeypatch.setattr("deployment.doctor.service_status", lambda: type("R", (), {"ok": True, "message": "state = running\npid = 123"})())
    monkeypatch.setattr("deployment.doctor._tcp_reachable", lambda host, port, timeout: (True, f"{host}:{port}"))

    def fake_http(url: str, _timeout: float):
        if url.endswith("/health"):
            return 200, {"status": "ok"}, None
        if url.endswith("/ready"):
            return 200, {"status": "not_ready", "inference": "not_ready"}, None
        if url.endswith("/edge/status"):
            raise AssertionError("Doctor must not require protected /edge/status")
        return 0, None, "unexpected"

    monkeypatch.setattr("deployment.doctor._http_json", fake_http)

    report = run_doctor(db_path=db_path, min_free_gb=0)
    output = format_doctor(report)

    assert "Camera/RTSP network" in output
    assert "PASS" in output
    assert "RTSP credentials" in output
    assert _status(report, "RTSP credentials") == NOT_VERIFIED
    assert "NOT VERIFIED" in output
    assert "RTSP_AUTH_FAILED" not in output


def test_doctor_reports_cloud_not_configured_without_blocking(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = _ready_db(tmp_path, monkeypatch)
    monkeypatch.delenv("CAMPEX_CLOUD_URL", raising=False)
    monkeypatch.delenv("CAMPEX_EDGE_SECRET", raising=False)
    _patch_ready_runtime(monkeypatch)

    report = run_doctor(db_path=db_path, min_free_gb=0)

    assert _status(report, "Cloud configuration") == NOT_CONFIGURED
    assert report.exit_code == 0


def test_doctor_external_profile_requires_cloud_configuration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = _ready_db(tmp_path, monkeypatch)
    monkeypatch.delenv("CAMPEX_CLOUD_URL", raising=False)
    monkeypatch.delenv("CAMPEX_EDGE_SECRET", raising=False)
    _patch_ready_runtime(monkeypatch)

    report = run_doctor(db_path=db_path, min_free_gb=0, cloud_required=True)

    assert _status(report, "Cloud configuration") == FAIL
    assert report.exit_code == 1


def test_doctor_external_profile_accepts_reachable_cloud(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = _ready_db(tmp_path, monkeypatch)
    monkeypatch.setenv("CAMPEX_CLOUD_URL", "https://cloud.campex.example")
    monkeypatch.setenv("CAMPEX_EDGE_SECRET", "edge-secret-value")
    _patch_ready_runtime(monkeypatch)

    report = run_doctor(db_path=db_path, min_free_gb=0, cloud_required=True)

    assert _status(report, "Cloud configuration") == PASS
    assert _status(report, "Cloud reachability") == PASS
    assert report.exit_code == 0


def test_preflight_profiles_make_cloud_requirement_explicit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    db_path = _ready_db(tmp_path, monkeypatch)
    monkeypatch.delenv("CAMPEX_CLOUD_URL", raising=False)
    monkeypatch.delenv("CAMPEX_EDGE_SECRET", raising=False)
    monkeypatch.setattr("deployment.preflight.run_edge_pilot_check", lambda **_kwargs: PilotCheckReport(items=[], result="READY FOR PILOT"))
    _patch_ready_runtime(monkeypatch)

    local_code = preflight_main(["--db", str(db_path), "--profile", "local", "--min-free-gb", "0"])
    local_output = capsys.readouterr().out
    external_code = preflight_main(["--db", str(db_path), "--profile", "external", "--min-free-gb", "0"])
    external_output = capsys.readouterr().out

    assert local_code == 0
    assert "PROFILE: LOCAL" in local_output
    assert "Cloud configuration" in local_output
    assert external_code == 1
    assert "PROFILE: EXTERNAL" in external_output
    assert "Cloud configuration" in external_output


def test_doctor_output_masks_service_secrets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = _ready_db(tmp_path, monkeypatch)
    monkeypatch.setenv("CAMPEX_EDGE_SECRET", "edge-secret-value")
    monkeypatch.setattr(
        "deployment.doctor.service_status",
        lambda: type("R", (), {"ok": False, "message": "CAMPEX_EDGE_SECRET=edge-secret-value rtsp://admin:camera-pass@10.0.0.10"})(),
    )
    _patch_ready_runtime(monkeypatch)
    monkeypatch.setattr(
        "deployment.doctor.service_status",
        lambda: type("R", (), {"ok": False, "message": "CAMPEX_EDGE_SECRET=edge-secret-value rtsp://admin:camera-pass@10.0.0.10"})(),
    )

    output = format_doctor(run_doctor(db_path=db_path, min_free_gb=0))

    assert "edge-secret-value" not in output
    assert "camera-pass" not in output
    assert "admin:camera-pass" not in output


def test_setup_is_idempotent_when_pip_is_skipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "data" / "edge.sqlite3"
    evidence = tmp_path / "evidence"
    logs = tmp_path / "logs"
    monkeypatch.setattr("deployment.setup.DATABASE_PATH", db_path)
    monkeypatch.setattr("deployment.setup.EVIDENCE_DIR", evidence)
    monkeypatch.setattr("deployment.setup.LOG_DIR", logs)
    monkeypatch.setenv("CAMPEX_EDGE_ID", "edge_factory_01")
    monkeypatch.setenv("CAMPEX_CREDENTIAL_KEY", "credential-key-with-enough-length")
    venv = tmp_path / ".venv"

    def fake_run(command, **_kwargs):
        if command[:3] == [__import__("sys").executable, "-m", "venv"]:
            python = venv / "bin" / "python"
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text("#!/usr/bin/env python\n", encoding="utf-8")
            return True, str(venv)
        return True, "4.0.0"

    monkeypatch.setattr("deployment.setup._run", fake_run)

    first = run_setup(skip_pip=True, venv=venv)
    second = run_setup(skip_pip=True, venv=venv)

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert _status(type("R", (), {"checks": first.checks})(), "Banco") == SETUP_PASS
    assert any(item.label == "Dependências Python" and item.status == SETUP_WARNING for item in second.checks)


def test_setup_treats_missing_ffmpeg_as_non_blocking_recommendation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "data" / "edge.sqlite3"
    evidence = tmp_path / "evidence"
    logs = tmp_path / "logs"
    monkeypatch.setattr("deployment.setup.DATABASE_PATH", db_path)
    monkeypatch.setattr("deployment.setup.EVIDENCE_DIR", evidence)
    monkeypatch.setattr("deployment.setup.LOG_DIR", logs)
    monkeypatch.setattr("deployment.setup.shutil.which", lambda name: None if name == "ffmpeg" else "/usr/bin/tool")
    monkeypatch.setenv("CAMPEX_EDGE_ID", "edge_factory_01")
    monkeypatch.setenv("CAMPEX_CREDENTIAL_KEY", "credential-key-with-enough-length")
    venv = tmp_path / ".venv"

    def fake_run(command, **_kwargs):
        if command[:3] == [__import__("sys").executable, "-m", "venv"]:
            python = venv / "bin" / "python"
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text("#!/usr/bin/env python\n", encoding="utf-8")
            return True, str(venv)
        return True, "4.0.0"

    monkeypatch.setattr("deployment.setup._run", fake_run)

    report = run_setup(skip_pip=True, venv=venv)

    assert report.exit_code == 0
    assert any(item.label == "FFmpeg" and item.status == SETUP_WARNING for item in report.checks)
