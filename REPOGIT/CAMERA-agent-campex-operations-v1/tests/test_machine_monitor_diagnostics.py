from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient

from app import api as api_module
from app.api import api
from app.auth import create_user
from app.database import connect, init_db
from app.live_stream import LiveCameraStream
from app.machine_monitoring import MachineMonitorConfig, MachineMonitorEngine
from app.models import atualizar_machine_monitor, criar_camera, criar_cliente, criar_machine_monitor, criar_unidade
from app.restricted_area import AreaPoint


def _isolated_client(tmp_path: Path):
    db_path = tmp_path / "monitor_diagnostics.sqlite3"

    def test_connect(_path=None):
        return connect(db_path)

    with test_connect() as connection:
        init_db(connection)
    patcher = patch.object(api_module, "connect", test_connect)
    patcher.start()
    return TestClient(api), db_path, patcher, test_connect


def _polygon():
    return [
        {"x": 0.2, "y": 0.2},
        {"x": 0.8, "y": 0.2},
        {"x": 0.8, "y": 0.8},
        {"x": 0.2, "y": 0.8},
    ]


def _make_engine(monitor_id: str, camera_id: str) -> MachineMonitorEngine:
    config = MachineMonitorConfig(
        id=monitor_id,
        client_id="cli_1",
        unit_id="unit_1",
        camera_id=camera_id,
        nome="A6",
        machine_polygon=[AreaPoint(0.1, 0.1), AreaPoint(0.9, 0.1), AreaPoint(0.9, 0.9), AreaPoint(0.1, 0.9)],
        operator_polygon=[AreaPoint(0.0, 0.1), AreaPoint(0.2, 0.1), AreaPoint(0.2, 0.9), AreaPoint(0.0, 0.9)],
        active_baseline=30.0,
        stopped_baseline=2.0,
        active_noise=1.0,
        stopped_noise=0.5,
        motion_threshold=16.0,
        motion_sensitivity=25.0,
        calibration_result="READY",
        separation_score=28.0,
    )
    engine = MachineMonitorEngine(config)
    engine.state.state = "ACTIVE"
    engine.state.raw_activity_score = 25.0
    engine.state.smoothed_motion = 24.5
    engine.state.threshold = 16.0
    engine.state.confidence = 0.9
    engine.state.reason = "atividade visual proxima ao baseline ativo"
    engine.state.signal_quality = "READY"
    engine.state.analysis_status = "ANALYZING"
    engine.state.analysis_error = None
    engine.state.frames_analyzed = 10
    engine.state.roi_width = 100
    engine.state.roi_height = 80
    engine.state.window_samples = 5
    engine.state.window_mean = 24.0
    engine.state.window_median = 24.5
    engine.state.window_std = 1.0
    engine.state.state_since = _monotonic_minus(3.0)
    return engine


_MONOTONIC_NOW = 1000.0


def _monotonic_minus(seconds: float) -> float:
    return _MONOTONIC_NOW - seconds


class _FakeManager:
    def __init__(self, stream=None):
        self._stream = stream

    def get(self, camera_id: str):
        return self._stream


# --- Unit tests for machine_diagnostics on LiveCameraStream ---


def test_machine_diagnostics_returns_none_when_stream_offline():
    stream = LiveCameraStream("cam_offline", "fake.mp4")
    engine = _make_engine("mach_1", "cam_offline")
    stream._machine_engines["mach_1"] = engine
    # Do NOT set status to online
    assert stream.machine_diagnostics("mach_1") is None


def test_machine_diagnostics_returns_none_when_engine_not_loaded():
    stream = LiveCameraStream("cam_no_engine", "fake.mp4")
    stream.status.status = "online"
    assert stream.machine_diagnostics("mach_missing") is None


def test_machine_diagnostics_returns_real_state_when_engine_loaded():
    stream = LiveCameraStream("cam_online", "fake.mp4")
    stream.status.status = "online"
    engine = _make_engine("mach_real", "cam_online")
    stream._machine_engines["mach_real"] = engine

    with patch("app.live_stream.time.monotonic", return_value=_MONOTONIC_NOW):
        result = stream.machine_diagnostics("mach_real")

    assert result is not None
    rd = result["runtime_diagnostics"]
    assert rd["machine_state"] == "ACTIVE"
    assert rd["raw_activity_score"] == 25.0
    assert rd["smoothed_activity_score"] == 24.5
    assert rd["threshold"] == 16.0
    assert rd["confidence"] == 0.9
    assert rd["reason"] == "atividade visual proxima ao baseline ativo"
    assert rd["signal_quality"] == "READY"
    assert rd["analysis_status"] == "ANALYZING"
    assert rd["analysis_error"] is None
    assert rd["seconds_in_state"] == 3.0
    assert rd["frames_analyzed"] == 10
    assert rd["roi_width"] == 100
    assert rd["roi_height"] == 80
    assert rd["window_samples"] == 5
    assert rd["window_mean"] == 24.0
    assert rd["window_median"] == 24.5
    assert rd["window_std"] == 1.0

    cal = result["calibration"]
    assert cal["active_baseline"] == 30.0
    assert cal["stopped_baseline"] == 2.0
    assert cal["active_noise"] == 1.0
    assert cal["stopped_noise"] == 0.5
    assert cal["separation_score"] == 28.0
    assert cal["threshold"] == 16.0
    assert cal["calibration_result"] == "READY"


# --- Endpoint integration tests ---


def _setup_monitor(tmp_path: Path, calibration_result: str = "INVALID",
                   active_baseline=None, stopped_baseline=None):
    client, db_path, patcher, test_connect = _isolated_client(tmp_path)
    try:
        with test_connect() as connection:
            init_db(connection)
            cliente_id = criar_cliente(connection, "Cliente")
            unidade_id = criar_unidade(connection, cliente_id, "Unidade")
            create_user(connection, "admin@cliente.test", "senha-segura", "admin_campex", cliente_id, "Admin")
            camera_id = criar_camera(connection, unidade_id, "Câmera", cliente_id=cliente_id)
            monitor_id = criar_machine_monitor(
                connection,
                cliente_id,
                unidade_id,
                camera_id,
                "A6",
                _polygon(),
                _polygon(),
                ativo=True,
            )
            if calibration_result != "INVALID" or active_baseline is not None or stopped_baseline is not None:
                atualizar_machine_monitor(
                    connection,
                    monitor_id,
                    active_baseline=active_baseline,
                    stopped_baseline=stopped_baseline,
                    active_noise=1.0 if active_baseline is not None else None,
                    stopped_noise=0.5 if stopped_baseline is not None else None,
                    motion_threshold=16.0 if active_baseline is not None and stopped_baseline is not None else None,
                    calibration_result=calibration_result,
                    calibration_status="calibrated" if calibration_result == "READY" else "calibration_pending",
                )
        client.post("/auth/login", json={"email": "admin@cliente.test", "senha": "senha-segura"})
        return client, test_connect, camera_id, monitor_id, patcher
    except Exception:
        patcher.stop()
        raise


def test_calibration_status_null_runtime_when_no_stream(tmp_path: Path):
    client, test_connect, camera_id, monitor_id, patcher = _setup_monitor(tmp_path)
    try:
        with patch.object(api_module, "live_streams", _FakeManager(None)):
            response = client.get(f"/machine-monitors/{monitor_id}/calibration/status")
        assert response.status_code == 200
        data = response.json()
        assert data["runtime_diagnostics"] is None
        # Existing payload preserved
        assert data["machine_id"] == monitor_id
        assert data["calibration_result"] is not None
        assert "diagnostics" in data
    finally:
        patcher.stop()


def test_calibration_readiness_false_when_not_calibrated(tmp_path: Path):
    client, test_connect, camera_id, monitor_id, patcher = _setup_monitor(tmp_path)
    try:
        with patch.object(api_module, "live_streams", _FakeManager(None)):
            response = client.get(f"/machine-monitors/{monitor_id}/calibration/status")
        assert response.status_code == 200
        readiness = response.json()["calibration_readiness"]
        assert readiness["ready"] is False
        assert readiness["active_baseline"] is None
        assert readiness["stopped_baseline"] is None
        assert readiness["reason"] is not None
        assert "ready" in readiness
        assert "result" in readiness
        assert "active_noise" in readiness
        assert "stopped_noise" in readiness
        assert "separation_score" in readiness
        assert "threshold" in readiness
    finally:
        patcher.stop()


def test_calibration_readiness_true_when_calibrated(tmp_path: Path):
    client, test_connect, camera_id, monitor_id, patcher = _setup_monitor(
        tmp_path,
        calibration_result="READY",
        active_baseline=30.0,
        stopped_baseline=2.0,
    )
    try:
        with patch.object(api_module, "live_streams", _FakeManager(None)):
            response = client.get(f"/machine-monitors/{monitor_id}/calibration/status")
        assert response.status_code == 200
        readiness = response.json()["calibration_readiness"]
        assert readiness["ready"] is True
        assert readiness["result"] == "READY"
        assert readiness["active_baseline"] == 30.0
        assert readiness["stopped_baseline"] == 2.0
        assert readiness["active_noise"] == 1.0
        assert readiness["stopped_noise"] == 0.5
        assert readiness["threshold"] == 16.0
    finally:
        patcher.stop()


def test_calibration_readiness_never_ready_without_baselines(tmp_path: Path):
    client, test_connect, camera_id, monitor_id, patcher = _setup_monitor(
        tmp_path,
        calibration_result="READY",
        active_baseline=None,
        stopped_baseline=None,
    )
    try:
        with patch.object(api_module, "live_streams", _FakeManager(None)):
            response = client.get(f"/machine-monitors/{monitor_id}/calibration/status")
        assert response.status_code == 200
        readiness = response.json()["calibration_readiness"]
        assert readiness["ready"] is False
        assert readiness["result"] == "READY"
    finally:
        patcher.stop()


def test_calibration_status_runtime_and_readiness_from_engine(tmp_path: Path):
    client, test_connect, camera_id, monitor_id, patcher = _setup_monitor(
        tmp_path,
        calibration_result="READY",
        active_baseline=30.0,
        stopped_baseline=2.0,
    )
    try:
        stream = LiveCameraStream(camera_id, "fake.mp4")
        stream.status.status = "online"
        engine = _make_engine(monitor_id, camera_id)
        stream._machine_engines[monitor_id] = engine

        with patch.object(api_module, "live_streams", _FakeManager(stream)):
            response = client.get(f"/machine-monitors/{monitor_id}/calibration/status")
        assert response.status_code == 200
        data = response.json()
        rd = data["runtime_diagnostics"]
        assert rd is not None
        assert rd["machine_state"] == "ACTIVE"
        assert rd["raw_activity_score"] == 25.0
        assert rd["smoothed_activity_score"] == 24.5
        assert rd["threshold"] == 16.0
        assert rd["confidence"] == 0.9
        assert rd["frames_analyzed"] == 10
        assert rd["roi_width"] == 100
        assert rd["roi_height"] == 80
        assert rd["window_samples"] == 5

        readiness = data["calibration_readiness"]
        assert readiness["ready"] is True
        assert readiness["result"] == "READY"
        # Engine config values preferred
        assert readiness["active_baseline"] == 30.0
        assert readiness["stopped_baseline"] == 2.0
        assert readiness["separation_score"] == 28.0
    finally:
        patcher.stop()


def test_calibration_status_preserves_existing_payload(tmp_path: Path):
    client, test_connect, camera_id, monitor_id, patcher = _setup_monitor(
        tmp_path,
        calibration_result="READY",
        active_baseline=30.0,
        stopped_baseline=2.0,
    )
    try:
        with patch.object(api_module, "live_streams", _FakeManager(None)):
            response = client.get(f"/machine-monitors/{monitor_id}/calibration/status")
        assert response.status_code == 200
        data = response.json()
        for field in [
            "machine_id", "camera_id", "stream", "active_calibration",
            "stopped_calibration", "active_baseline", "stopped_baseline",
            "separation_score", "calibration_result", "calibration_status",
            "diagnostics",
        ]:
            assert field in data, f"Campo preservado ausente: {field}"
        assert data["stream"]["status"] == "idle"
    finally:
        patcher.stop()
