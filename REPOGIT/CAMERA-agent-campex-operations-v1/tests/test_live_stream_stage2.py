from __future__ import annotations

import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from fastapi.testclient import TestClient

from app import api as api_module
from app.api import api, live_streams
from app.database import connect
from app.live_stream import LiveStreamManager
from app.person_detection import PersonAnalysisEngine
from edge_agent.camera_connector import CameraSource
from shared.schemas import now_iso


class FakeCapture:
    opened_count = 0

    def __init__(self, frames: list[np.ndarray], opened: bool = True) -> None:
        self.frames = frames
        self.opened = opened
        self.released = False

    def isOpened(self) -> bool:
        return self.opened and not self.released

    def read(self) -> tuple[bool, np.ndarray | None]:
        if not self.frames:
            self.opened = False
            return False, None
        time.sleep(0.01)
        return True, self.frames.pop(0)

    def get(self, prop: int) -> float:
        if prop == cv2.CAP_PROP_FRAME_WIDTH:
            return 64
        if prop == cv2.CAP_PROP_FRAME_HEIGHT:
            return 48
        if prop == cv2.CAP_PROP_FPS:
            return 12
        return 0

    def release(self) -> None:
        self.released = True


class FakeConnector:
    opened = 0

    def __init__(self, camera: CameraSource) -> None:
        self.camera = camera
        self.info = type(
            "Info",
            (),
            {"width": 64, "height": 48, "fps": 12.0, "error": None},
        )()
        self.capture: FakeCapture | None = None

    def open(self) -> bool:
        FakeConnector.opened += 1
        frame = np.zeros((48, 64, 3), dtype=np.uint8)
        self.capture = FakeCapture([frame.copy() for _ in range(200)])
        return True

    def stop(self) -> None:
        if self.capture:
            self.capture.release()

    def close(self) -> None:
        if self.capture:
            self.capture.release()


class FailingThenWorkingConnector(FakeConnector):
    attempts = 0

    def open(self) -> bool:
        FailingThenWorkingConnector.attempts += 1
        if FailingThenWorkingConnector.attempts == 1:
            self.info.error = "falha simulada"
            return False
        return super().open()


class FailingDetector:
    model_name = "fake-person-detector"

    def detect(self, frame):
        raise RuntimeError("falha IA simulada")


class LiveStreamStage2Test(unittest.TestCase):
    def setUp(self) -> None:
        self._ops_temp_dir = tempfile.TemporaryDirectory()
        self._ops_db_path = Path(self._ops_temp_dir.name) / "operations-history.sqlite3"
        with connect(self._ops_db_path) as connection:
            api_module.init_db(connection)
        self._ops_connect_patch = patch("app.operations_history.connect", lambda: connect(self._ops_db_path))
        self._ops_connect_patch.start()

    def tearDown(self) -> None:
        live_streams.stop_all()
        self._ops_connect_patch.stop()
        self._ops_temp_dir.cleanup()

    def test_live_stream_reuses_one_connection_for_same_camera(self) -> None:
        FakeConnector.opened = 0
        manager = LiveStreamManager(connector_factory=lambda camera: FakeConnector(camera))
        stream_a = manager.get_or_create("cam_1", "rtsp://user:pass@camera/stream")
        stream_b = manager.get_or_create("cam_1", "rtsp://user:pass@camera/stream")
        stream_a.start()
        stream_b.start()
        time.sleep(0.2)
        status = stream_a.public_status()
        manager.stop_all()

        self.assertIs(stream_a, stream_b)
        self.assertEqual(FakeConnector.opened, 1)
        self.assertNotIn("pass", str(status))

    def test_two_cameras_run_independently_and_stop_only_one(self) -> None:
        FakeConnector.opened = 0
        manager = LiveStreamManager(connector_factory=lambda camera: FakeConnector(camera))
        stream_a = manager.get_or_create("cam_a", "rtsp://user:pass@camera-a/stream")
        stream_b = manager.get_or_create("cam_b", "rtsp://user:pass@camera-b/stream")
        stream_a.start()
        stream_b.start()
        time.sleep(0.25)

        status_a = stream_a.public_status()
        status_b = stream_b.public_status()
        stopped = manager.stop("cam_a")
        remaining = manager.get("cam_b")
        remaining_status = remaining.public_status() if remaining else {}
        manager.stop_all()

        self.assertTrue(stopped)
        self.assertEqual(FakeConnector.opened, 2)
        self.assertIsNot(stream_a, stream_b)
        self.assertIn(status_a["status"], {"online", "reconectando", "offline"})
        self.assertIn(status_b["status"], {"online", "reconectando", "offline"})
        self.assertIsNotNone(remaining)
        self.assertIn(remaining_status["status"], {"online", "reconectando", "offline"})
        self.assertNotIn("pass", str(status_a) + str(status_b) + str(remaining_status))

    def test_live_grid_page_is_served(self) -> None:
        client = TestClient(api)
        logged_out = client.get("/live-grid", follow_redirects=False)
        self.assertEqual(logged_out.status_code, 303)
        self.assertTrue(logged_out.headers["location"].startswith("/login?next="))

        with patch("app.api._request_has_valid_session", return_value=True):
            response = client.get("/live-grid")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers.get("content-type", ""))
        self.assertIn("Veja sua operação em tempo real.", response.text)

    def test_live_streams_status_returns_resource_snapshot_without_credentials(self) -> None:
        original_manager = api_module.live_streams
        try:
            api_module.live_streams = LiveStreamManager(connector_factory=lambda camera: FakeConnector(camera))
            stream = api_module.live_streams.get_or_create("cam_resources", "rtsp://user:pass@camera/stream")
            stream.start()
            time.sleep(0.15)
            with tempfile.TemporaryDirectory() as temp_dir, patch("app.api.connect", lambda: connect(Path(temp_dir) / "live-status.sqlite3")):
                client = TestClient(api)
                response = client.get("/live-streams/status")
        finally:
            api_module.live_streams.stop_all()
            api_module.live_streams = original_manager

        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(response.json()["active_streams"], 1)
        self.assertIn("cpu_percent", response.json())
        self.assertNotIn("pass", response.text)

    def test_file_video_mode_explicitly_overrides_camera_source_for_local_validation(self) -> None:
        original_manager = api_module.live_streams
        try:
            with tempfile.TemporaryDirectory() as temp_dir, patch.dict("os.environ", {"CAMPEX_VIDEO_SOURCE_MODE": "file", "CAMPEX_VIDEO_FILE": str(Path(temp_dir) / "teste.mp4")}):
                video_path = Path(temp_dir) / "teste.mp4"
                video_path.write_bytes(b"fake")
                db_path = Path(temp_dir) / "video-mode.sqlite3"
                with connect(db_path) as connection:
                    api_module.init_db(connection)
                    cliente_id = api_module.criar_cliente(connection, "Cliente")
                    unidade_id = api_module.criar_unidade(connection, cliente_id, "Unidade")
                    camera_id = api_module.criar_camera(
                        connection,
                        unidade_id,
                        "Camera",
                        cliente_id=cliente_id,
                        rtsp_host="192.168.15.2",
                        rtsp_username="admin",
                        rtsp_password="segredo",
                    )
                with patch("app.api.connect", lambda: connect(db_path)):
                    camera, source = api_module.load_camera_source(camera_id)
        finally:
            api_module.live_streams = original_manager

        self.assertEqual(camera["id"], camera_id)
        self.assertEqual(source, str(video_path))
        self.assertNotIn("segredo", source)

    def test_live_stream_reconnects_after_initial_failure(self) -> None:
        FailingThenWorkingConnector.attempts = 0
        manager = LiveStreamManager(connector_factory=lambda camera: FailingThenWorkingConnector(camera))
        stream = manager.get_or_create("cam_2", "rtsp://user:pass@camera/stream")
        stream.start()
        time.sleep(1.4)
        status = stream.public_status()
        manager.stop_all()

        self.assertGreaterEqual(FailingThenWorkingConnector.attempts, 2)
        self.assertIn(status["status"], {"online", "reconectando", "offline"})
        self.assertNotIn("pass", str(status))

    def test_recent_frame_overrides_transient_reconnecting_status(self) -> None:
        manager = LiveStreamManager(connector_factory=lambda camera: FakeConnector(camera))
        stream = manager.get_or_create("cam_recent", "rtsp://user:pass@camera/stream")
        with stream._lock:
            stream._last_jpeg = b"jpeg"
            stream.status.status = "reconectando"
            stream.status.last_frame_at = now_iso()
            stream.status.error = "Stream parou de entregar frames."

        status = stream.public_status()
        manager.stop_all()

        self.assertEqual(status["status"], "online")
        self.assertIsNone(status["error"])

    def test_status_endpoint_does_not_return_credentials_for_missing_stream(self) -> None:
        client = TestClient(api)
        response = client.get("/cameras/cam_inexistente/status")
        self.assertIn(response.status_code, {401, 404})
        self.assertNotIn("senha", response.text.lower())

    def test_live_view_starts_without_camera_registration(self) -> None:
        original_manager = api_module.live_streams
        original_sessions = dict(api_module.live_view_sessions)
        try:
            api_module.live_streams = LiveStreamManager(connector_factory=lambda camera: FakeConnector(camera))
            api_module.live_view_sessions.clear()
            with tempfile.TemporaryDirectory() as temp_dir:
                db_path = Path(temp_dir) / "live.sqlite3"
                with patch("app.api.connect", lambda: connect(db_path)):
                    client = TestClient(api)
                    response = client.post(
                        "/live-view/start",
                        json={
                            "nome": "Intelbras Teste",
                            "host": "192.168.15.2",
                            "porta_rtsp": 554,
                            "usuario": "admin",
                            "senha": "segredo",
                            "caminho_rtsp": "/stream",
                        },
                    )
                    second_response = client.post(
                        "/live-view/start",
                        json={
                            "nome": "Intelbras Teste",
                            "host": "192.168.15.2",
                            "porta_rtsp": 554,
                            "usuario": "admin",
                            "senha": "segredo",
                            "caminho_rtsp": "/stream",
                        },
                    )
                    payload = response.json()
                    status = client.get(f"/live-view/{payload['session_id']}/status")
                with connect(db_path) as connection:
                    api_module.init_db(connection)
                    camera_count = connection.execute("SELECT COUNT(*) AS total FROM cameras").fetchone()["total"]
        finally:
            api_module.live_streams.stop_all()
            api_module.live_streams = original_manager
            api_module.live_view_sessions.clear()
            api_module.live_view_sessions.update(original_sessions)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(payload["nome"], "Intelbras Teste")
        self.assertEqual(camera_count, 0)
        self.assertNotIn("segredo", response.text + status.text)
        self.assertIn(status.status_code, {200})

    def test_live_view_ops_endpoints_do_not_expose_credentials(self) -> None:
        original_manager = api_module.live_streams
        original_sessions = dict(api_module.live_view_sessions)
        try:
            api_module.live_streams = LiveStreamManager(connector_factory=lambda camera: FakeConnector(camera))
            api_module.live_view_sessions.clear()
            with tempfile.TemporaryDirectory() as temp_dir, patch("app.api.connect", lambda: connect(Path(temp_dir) / "live-view.sqlite3")):
                client = TestClient(api)
                response = client.post(
                    "/live-view/start",
                    json={
                        "nome": "Intelbras Operacional",
                        "host": "192.168.15.2",
                        "usuario": "admin",
                        "senha": "segredo",
                        "caminho_rtsp": "/cam/realmonitor",
                    },
                )
                session_id = response.json()["session_id"]
                ai = client.post(f"/live-view/{session_id}/ai/start")
                machine = client.post(
                    f"/live-view/{session_id}/machine",
                    json={
                        "nome": "Extrusora principal",
                        "machine_polygon": [
                            {"x": 0.2, "y": 0.2},
                            {"x": 0.8, "y": 0.2},
                            {"x": 0.8, "y": 0.8},
                            {"x": 0.2, "y": 0.8},
                        ],
                    },
                )
                calibration = client.post(f"/live-view/{session_id}/machine/calibrate-active")
                status = client.get(f"/live-view/{session_id}/status")
        finally:
            api_module.live_streams.stop_all()
            api_module.live_streams = original_manager
            api_module.live_view_sessions.clear()
            api_module.live_view_sessions.update(original_sessions)

        combined = response.text + ai.text + machine.text + calibration.text + status.text
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ai.status_code, 200)
        self.assertEqual(machine.status_code, 200)
        self.assertEqual(calibration.status_code, 200)
        self.assertEqual(status.status_code, 200)
        self.assertTrue(ai.json()["ai_enabled"])
        self.assertEqual(machine.json()["machine"]["nome"], "Extrusora principal")
        self.assertEqual(calibration.json()["calibration_status"], "use_assisted_calibration_endpoint")
        self.assertIn("/machine-monitors/{id}/calibration/active/start", calibration.json()["message"])
        self.assertIn("ops", status.json())
        self.assertNotIn("segredo", combined)

    def test_live_view_machine_config_persists_for_registered_camera(self) -> None:
        original_manager = api_module.live_streams
        original_sessions = dict(api_module.live_view_sessions)
        try:
            api_module.live_streams = LiveStreamManager(connector_factory=lambda camera: FakeConnector(camera))
            api_module.live_view_sessions.clear()
            with tempfile.TemporaryDirectory() as temp_dir:
                db_path = Path(temp_dir) / "registered-live.sqlite3"
                with connect(db_path) as connection:
                    api_module.init_db(connection)
                    cliente_id = api_module.criar_cliente(connection, "Cliente")
                    unidade_id = api_module.criar_unidade(connection, cliente_id, "Unidade")
                    camera_id = api_module.criar_camera(
                        connection,
                        unidade_id,
                        "Camera registrada",
                        cliente_id=cliente_id,
                        rtsp_host="192.168.15.2",
                        rtsp_port=554,
                        rtsp_path="/stream",
                        rtsp_username="admin",
                        rtsp_password="segredo",
                    )
                with patch("app.api.connect", lambda: connect(db_path)), patch("app.operations_history.connect", lambda: connect(db_path)):
                    client = TestClient(api)
                    started = client.post("/live-view/start", json={"camera_id": camera_id, "nome": "Camera registrada"})
                    session_id = started.json()["session_id"]
                    machine = client.post(
                        f"/live-view/{session_id}/machine",
                        json={
                            "nome": "Máquina principal",
                            "machine_polygon": [
                                {"x": 0.1, "y": 0.1},
                                {"x": 0.7, "y": 0.1},
                                {"x": 0.7, "y": 0.7},
                                {"x": 0.1, "y": 0.7},
                            ],
                        },
                    )
                    operator = client.post(
                        f"/live-view/{session_id}/operator-zone",
                        json={
                            "operator_polygon": [
                                {"x": 0.75, "y": 0.1},
                                {"x": 0.95, "y": 0.1},
                                {"x": 0.95, "y": 0.7},
                                {"x": 0.75, "y": 0.7},
                            ],
                        },
                    )
                    calibration = client.post(f"/live-view/{session_id}/machine/calibrate-active")
                    api_module.live_streams.stop_all()
                    api_module.live_streams = LiveStreamManager(connector_factory=lambda camera: FakeConnector(camera))
                    restarted = client.post("/live-view/start", json={"camera_id": camera_id, "nome": "Camera registrada"})
                    reloaded_status = client.get(f"/live-view/{restarted.json()['session_id']}/status")
                with connect(db_path) as connection:
                    monitors = api_module.listar_machine_monitors_camera(connection, camera_id)
        finally:
            api_module.live_streams.stop_all()
            api_module.live_streams = original_manager
            api_module.live_view_sessions.clear()
            api_module.live_view_sessions.update(original_sessions)

        self.assertEqual(started.status_code, 200)
        self.assertEqual(machine.status_code, 200)
        self.assertEqual(operator.status_code, 200)
        self.assertEqual(calibration.status_code, 200)
        self.assertEqual(len(monitors), 1)
        self.assertEqual(monitors[0]["nome"], "Máquina principal")
        self.assertEqual(monitors[0]["calibration_status"], "not_calibrated")
        self.assertEqual(calibration.json()["calibration_status"], "use_assisted_calibration_endpoint")
        self.assertEqual(reloaded_status.json()["ops"]["machine"]["nome"], "Máquina principal")
        self.assertNotIn("segredo", started.text + reloaded_status.text)

    def test_registered_live_view_uses_camera_id_stream_so_zones_are_loaded(self) -> None:
        original_manager = api_module.live_streams
        original_sessions = dict(api_module.live_view_sessions)
        try:
            api_module.live_streams = LiveStreamManager(connector_factory=lambda camera: FakeConnector(camera))
            api_module.live_view_sessions.clear()
            with tempfile.TemporaryDirectory() as temp_dir:
                db_path = Path(temp_dir) / "registered-zone-live.sqlite3"
                with connect(db_path) as connection:
                    api_module.init_db(connection)
                    cliente_id = api_module.criar_cliente(connection, "Cliente")
                    unidade_id = api_module.criar_unidade(connection, cliente_id, "Unidade")
                    camera_id = api_module.criar_camera(
                        connection,
                        unidade_id,
                        "Camera registrada",
                        cliente_id=cliente_id,
                        rtsp_host="192.168.15.2",
                        rtsp_port=554,
                        rtsp_path="/stream",
                        rtsp_username="admin",
                        rtsp_password="segredo",
                    )
                    api_module.criar_area_monitorada(
                        connection,
                        camera_id,
                        "Posto 1",
                        [{"x": 0.1, "y": 0.1}, {"x": 0.7, "y": 0.1}, {"x": 0.7, "y": 0.7}],
                        tipo="workstation",
                        absence_tolerance_seconds=0,
                    )
                with patch("app.api.connect", lambda: connect(db_path)), patch("app.operations_history.connect", lambda: connect(db_path)):
                    client = TestClient(api)
                    started = client.post("/live-view/start", json={"camera_id": camera_id})
                    session_id = started.json()["session_id"]
                    ai = client.post(f"/live-view/{session_id}/ai/start")
                    time.sleep(0.3)
                    status = client.get(f"/live-view/{session_id}/status")
                    stopped = client.post(f"/live-view/{session_id}/stop")
                    camera_status = client.get(f"/cameras/{camera_id}/status")
        finally:
            api_module.live_streams.stop_all()
            api_module.live_streams = original_manager
            api_module.live_view_sessions.clear()
            api_module.live_view_sessions.update(original_sessions)

        self.assertEqual(started.status_code, 200)
        self.assertEqual(started.json()["stream_id"], camera_id)
        self.assertEqual(ai.status_code, 200)
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["camera_id"], camera_id)
        self.assertEqual(stopped.json()["stopped"], False)
        self.assertIn(camera_status.json()["status"], {"online", "reconectando", "offline"})
        self.assertNotIn("segredo", started.text + status.text + camera_status.text)

    def test_live_view_stream_stays_online_when_ai_fails(self) -> None:
        manager = LiveStreamManager(connector_factory=lambda camera: FakeConnector(camera))
        stream = manager.get_or_create("live_fail", "rtsp://user:pass@camera/stream")
        stream.enable_live_view_ops()
        stream._analysis_engine = PersonAnalysisEngine(detector=FailingDetector(), tracking_enabled=False)
        stream.start()
        stream.set_analysis(True)
        time.sleep(0.4)
        status = stream.public_status()
        manager.stop_all()

        self.assertIn(status["status"], {"online", "reconectando", "offline"})
        self.assertEqual(status["ai_status"], "indisponivel")
        self.assertIn("falha IA simulada", status["analysis_error"])
        self.assertNotIn("pass", str(status))


if __name__ == "__main__":
    unittest.main()

def test_camera_offline_invalidates_visual_operational_truth():
    """Offline must mean UNKNOWN, never operator absence."""
    from unittest.mock import MagicMock

    from app.live_stream import LiveCameraStream

    stream = LiveCameraStream("cam_p0_offline", "rtsp://invalid")

    fake_machine = MagicMock()
    stream._machine_engines = {"machine_1": fake_machine}
    stream._incident_manager = MagicMock()
    stream._people_zones = MagicMock()

    stream.status.machine_state = "ACTIVE"
    stream.status.machine_operator_present = False
    stream.status.machine_event_id = "evt_machine"
    stream.status.machine_seconds_in_state = 120
    stream.status.active_zone_events = [
        {
            "event_type": "workstation_unattended",
            "event_id": "evt_absence",
        }
    ]
    stream.status.incident_active = True
    stream.status.incident_id = "evt_absence"
    stream.status.incident_started_at = "2026-08-28T12:00:00-03:00"
    stream.status.incident_people = 0
    stream.status.observation = {"operator_present": False}

    stream._invalidate_operational_state_for_offline()

    fake_machine.close_interrupted.assert_called_once()
    stream._incident_manager.close_interrupted.assert_called_once()
    stream._people_zones.close_interrupted.assert_called_once()

    assert stream.status.machine_state == "unavailable"
    assert stream.status.machine_operator_present is None
    assert stream.status.machine_event_id is None
    assert stream.status.machine_seconds_in_state is None
    assert stream.status.active_zone_events == []
    assert stream.status.incident_active is False
    assert stream.status.incident_id is None
    assert stream.status.incident_started_at is None
    assert stream.status.observation == {}


def test_official_ops_state_exposes_live_stream_telemetry():
    from app.live_stream import LiveCameraStream

    stream = LiveCameraStream("cam_ops_telemetry", "rtsp://invalid")
    stream.status.status = "online"
    stream.status.fps = 24.0
    stream.status.ai_status = "ativa"
    stream.status.analysis_fps = 5.0
    stream.status.analysis_frames = 42

    state = stream._official_ops_state()

    assert state["capture_fps"] == 24.0
    assert state["inference_fps"] == 5.0
    assert state["frames_analyzed"] == 42
    assert state["machine_state"] == "NAO_CONFIGURADA"


def test_non_machine_stream_records_operational_sample_with_throttle():
    from unittest.mock import MagicMock, patch

    from app.live_stream import LiveCameraStream

    stream = LiveCameraStream("cam_ops_periodic", "rtsp://invalid")
    stream._operations_recorder = MagicMock()
    stream.status.status = "online"
    stream.status.fps = 24.0
    stream.status.ai_status = "ativa"
    stream.status.analysis_fps = 5.0
    stream.status.analysis_frames = 10

    with patch("app.live_stream.time.monotonic", return_value=100.0):
        stream._record_non_machine_operational_sample_if_due()
        stream._record_non_machine_operational_sample_if_due()

    stream._operations_recorder.update_status.assert_called_once()
    camera_status, state = stream._operations_recorder.update_status.call_args.args[:2]

    assert camera_status == "online"
    assert state["capture_fps"] == 24.0
    assert state["inference_fps"] == 5.0
    assert state["frames_analyzed"] == 10
