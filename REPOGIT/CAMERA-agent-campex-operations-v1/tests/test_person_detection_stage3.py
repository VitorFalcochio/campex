from __future__ import annotations

import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from app import api as api_module
from app.database import connect
from app.live_stream import LiveStreamManager
from app.person_detection import Detection, PersonAnalysisEngine, detector_cache_size, get_yolo_detector
from edge_agent.camera_connector import CameraSource


class FakeCapture:
    def __init__(self, frames: list[np.ndarray]) -> None:
        self.frames = frames
        self.released = False

    def isOpened(self) -> bool:
        return not self.released and bool(self.frames)

    def read(self) -> tuple[bool, np.ndarray | None]:
        if not self.frames:
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
    def __init__(self, camera: CameraSource) -> None:
        self.camera = camera
        self.info = type("Info", (), {"width": 64, "height": 48, "fps": 12.0, "error": None})()
        frame = np.zeros((48, 64, 3), dtype=np.uint8)
        self.capture = FakeCapture([frame.copy() for _ in range(200)])

    def open(self) -> bool:
        return True

    def stop(self) -> None:
        self.capture.release()

    def close(self) -> None:
        self.capture.release()


class FakeDetector:
    model_name = "fake-person-model"

    def detect(self, _frame: np.ndarray) -> list[Detection]:
        return [
            Detection(5, 5, 20, 30, 0.9, "person"),
            Detection(30, 5, 45, 30, 0.8, "car"),
        ]


class FailingDetector:
    model_name = "failing-model"

    def detect(self, _frame: np.ndarray) -> list[Detection]:
        raise RuntimeError("falha fake de IA sem credenciais")


class PersonDetectionStage3Test(unittest.TestCase):
    def setUp(self) -> None:
        self._ops_temp_dir = tempfile.TemporaryDirectory()
        self._ops_db_path = Path(self._ops_temp_dir.name) / "person-detection.sqlite3"
        with connect(self._ops_db_path) as connection:
            api_module.init_db(connection)
        self._ops_connect_patch = patch("app.operations_history.connect", lambda: connect(self._ops_db_path))
        self._ops_connect_patch.start()

    def tearDown(self) -> None:
        self._ops_connect_patch.stop()
        self._ops_temp_dir.cleanup()

    def test_analysis_filters_people_and_tracks_ids(self) -> None:
        engine = PersonAnalysisEngine(detector=FakeDetector(), analysis_fps=30, tracking_enabled=True)
        frame = np.zeros((48, 64, 3), dtype=np.uint8)
        detections = engine.analyze(frame)

        self.assertEqual(len(detections), 1)
        self.assertEqual(detections[0].class_name, "person")
        self.assertEqual(detections[0].track_id, 1)

    def test_live_stream_analysis_can_be_enabled_and_disabled(self) -> None:
        manager = LiveStreamManager(connector_factory=lambda camera: FakeConnector(camera))
        stream = manager.get_or_create("cam_ai", "rtsp://user:pass@camera/stream")
        stream._analysis_engine = PersonAnalysisEngine(detector=FakeDetector(), analysis_fps=30, tracking_enabled=True)
        stream.start()
        stream.set_analysis(True)
        time.sleep(0.4)
        active_status = stream.public_status()
        stream.set_analysis(False)
        inactive_status = stream.public_status()
        manager.stop_all()

        self.assertEqual(active_status["ai_status"], "ativa")
        self.assertGreaterEqual(active_status["people_count"], 1)
        self.assertEqual(inactive_status["ai_status"], "inativa")
        self.assertNotIn("pass", str(active_status))

    def test_ai_failure_keeps_stream_alive(self) -> None:
        manager = LiveStreamManager(connector_factory=lambda camera: FakeConnector(camera))
        stream = manager.get_or_create("cam_fail", "rtsp://user:pass@camera/stream")
        stream._analysis_engine = PersonAnalysisEngine(detector=FailingDetector(), analysis_fps=30, tracking_enabled=True)
        stream.start()
        stream.set_analysis(True)
        time.sleep(0.3)
        status = stream.public_status()
        manager.stop_all()

        self.assertEqual(status["status"], "online")
        self.assertEqual(status["ai_status"], "indisponivel")
        self.assertIn("falha fake", status["analysis_error"])
        self.assertNotIn("pass", str(status))

    def test_detector_cache_reuses_model_instance(self) -> None:
        before = detector_cache_size()
        first = get_yolo_detector("yolo11n.pt", 0.35)
        second = get_yolo_detector("yolo11n.pt", 0.35)
        after = detector_cache_size()

        self.assertIs(first, second)
        self.assertLessEqual(after, before + 1)


if __name__ == "__main__":
    unittest.main()
