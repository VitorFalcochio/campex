from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

import cv2
import numpy as np
import pytest

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

from backend.cameras.frame_buffer import LatestFrameBuffer, LatestFrameSnapshot
from backend.cameras.manager import CameraManager
from backend.cameras.repository import CameraRepository
from backend.config import Settings
from backend.database.db import initialize_database
from backend.vision.detector import (
    DetectorUnavailable,
    RFDETRDetector,
    VisionDetector,
    YOLODetector,
    create_detector,
    normalize_rfdetr_result,
    normalize_yolo_result,
)
from backend.vision.engine import VisionEngine, VisionSession
from backend.vision.models import BoundingBox, Detection, TrackedObject, VisionMetrics
from backend.vision.overlay import OverlayRenderer
from backend.vision.tracker import ByteTrackAdapter, ObjectTracker
from tests.helpers import make_settings


class FakeDetector(VisionDetector):
    name = "FakeDetector"

    def __init__(self, class_names: list[str] | None = None) -> None:
        self._device = "CPU"
        self._class_names = class_names or ["person"]
        self.load_calls = 0
        self.detect_calls = 0

    def load(self) -> None:
        self.load_calls += 1

    def detect(self, frame: Any) -> tuple[list[Detection], float]:
        self.detect_calls += 1
        detections = [
            Detection(
                class_name="person",
                confidence=0.95,
                bounding_box=BoundingBox(x1=10, y1=10, x2=100, y2=200),
            ),
            Detection(
                class_name="car",
                confidence=0.80,
                bounding_box=BoundingBox(x1=200, y1=200, x2=400, y2=400),
            ),
        ]
        return detections, 12.5

    @property
    def device(self) -> str:
        return self._device


class FakeTracker(ObjectTracker):
    name = "FakeTracker"

    def __init__(self) -> None:
        self.updates: list[tuple[str, list[Detection], datetime]] = []

    def update(
        self, camera_id: str, detections: list[Detection], timestamp: datetime
    ) -> list[TrackedObject]:
        self.updates.append((camera_id, detections, timestamp))
        objects: list[TrackedObject] = []
        for index, detection in enumerate(detections):
            objects.append(
                TrackedObject(
                    track_id=index + 1,
                    camera_id=camera_id,
                    class_name=detection.class_name,
                    confidence=detection.confidence,
                    bounding_box=detection.bounding_box,
                    timestamp=timestamp,
                )
            )
        return objects


class FailingTracker(ObjectTracker):
    name = "FailingTracker"

    def update(
        self, camera_id: str, detections: list[Detection], timestamp: datetime
    ) -> list[TrackedObject]:
        raise RuntimeError("tracker offline")


class SupervisionLikeDetection:
    """Mimics a supervision.Detections object."""

    def __init__(
        self,
        xyxy: list[list[float]],
        confidence: list[float] | None = None,
        class_id: list[int] | None = None,
        class_names_in_data: list[str] | None = None,
    ) -> None:
        self.xyxy = np.array(xyxy, dtype=np.float32)
        self.confidence = (
            np.array(confidence, dtype=np.float32) if confidence else np.array([])
        )
        self.class_id = np.array(class_id, dtype=np.int64) if class_id else np.array([])
        self.data: dict[str, Any] = {}
        if class_names_in_data:
            self.data["class_name"] = np.array(class_names_in_data, dtype=object)
        self.data["source_shape"] = np.array([[480, 640]], dtype=np.int64)


class RawDetections:
    xyxy = [[10, 20, 110, 220], [0, 0, 5, 5]]
    confidence = [0.91, 0.2]
    class_name = ["person", "car"]


class YoloBoxes:
    xyxy = np.array([[10, 20, 110, 220], [200, 200, 400, 400]], dtype=np.float32)
    conf = np.array([0.91, 0.99], dtype=np.float32)
    cls = np.array([0, 2], dtype=np.float32)


class YoloResult:
    boxes = YoloBoxes()


def _make_session(
    camera_id: str = "cam_1",
    settings: Settings | None = None,
    detector: VisionDetector | None = None,
    tracker: ObjectTracker | None = None,
) -> VisionSession:
    settings = settings or make_settings(Path("/tmp/test_vision.sqlite3"))
    detector = detector or FakeDetector()
    tracker = tracker or FakeTracker()
    return VisionSession(camera_id, settings, detector, tracker)


def test_vision_detector_is_abstract():
    assert issubclass(RFDETRDetector, VisionDetector)
    assert issubclass(ByteTrackAdapter, ObjectTracker)
    with pytest.raises(TypeError):
        VisionDetector.__init__(object())
    with pytest.raises(TypeError):
        ObjectTracker.__init__(object())


def test_normalize_rfdetr_result_filters_and_maps_detections():
    detections = normalize_rfdetr_result(RawDetections(), confidence_threshold=0.5)

    assert len(detections) == 1
    assert detections[0].class_name == "person"
    assert detections[0].confidence == 0.91
    assert detections[0].bounding_box.as_list() == [10.0, 20.0, 110.0, 220.0]


def test_normalize_rfdetr_result_handles_supervision_detections():
    raw = SupervisionLikeDetection(
        xyxy=[[10, 20, 110, 220], [0, 0, 50, 50]],
        confidence=[0.95, 0.3],
        class_id=[0, 2],
        class_names_in_data=["person", "car"],
    )
    detections = normalize_rfdetr_result(raw, confidence_threshold=0.5)

    assert len(detections) == 1
    assert detections[0].class_name == "person"
    assert detections[0].confidence == 0.95
    assert detections[0].bounding_box.as_list() == [10.0, 20.0, 110.0, 220.0]


def test_normalize_rfdetr_result_falls_back_to_data_class_name():
    raw = SupervisionLikeDetection(
        xyxy=[[5, 5, 50, 50]],
        confidence=[0.8],
        class_id=[0],
        class_names_in_data=["person"],
    )
    detections = normalize_rfdetr_result(raw, confidence_threshold=0.5)
    assert len(detections) == 1
    assert detections[0].class_name == "person"


def test_normalize_rfdetr_result_resolves_class_from_class_id():
    raw = SupervisionLikeDetection(
        xyxy=[[5, 5, 50, 50]],
        confidence=[0.8],
        class_id=[0],
    )
    detections = normalize_rfdetr_result(
        raw, confidence_threshold=0.5, class_names=["person", "car", "truck"]
    )
    assert len(detections) == 1
    assert detections[0].class_name == "person"


def test_normalize_rfdetr_result_empty_result():
    raw = SupervisionLikeDetection(xyxy=[], confidence=[], class_id=[])
    detections = normalize_rfdetr_result(raw, confidence_threshold=0.5)
    assert detections == []


def test_normalize_yolo_result_filters_to_person_class():
    detections = normalize_yolo_result([YoloResult()], confidence_threshold=0.35)

    assert len(detections) == 1
    assert detections[0].class_name == "person"
    assert detections[0].confidence == 0.91
    assert detections[0].bounding_box.as_list() == [10.0, 20.0, 110.0, 220.0]


def test_yolo_detector_fallback_reason_when_load_fails(monkeypatch, tmp_path):
    settings = make_settings(tmp_path / "yolo-fallback.sqlite3")
    detector = YOLODetector(settings)

    def fail_load():
        detector._load_error = "ultralytics import failed"
        fallback = RFDETRDetector(settings)
        fallback._load_hog_fallback()
        detector._fallback = fallback

    monkeypatch.setattr(detector, "_do_load", fail_load)

    detector.load()

    assert detector.fallback_used is True
    assert detector.fallback_reason == "ultralytics import failed"


def test_normalize_rfdetr_result_handles_missing_confidence():
    raw = SupervisionLikeDetection(
        xyxy=[[10, 20, 110, 220]],
        confidence=None,
        class_id=[0],
        class_names_in_data=["person"],
    )
    detections = normalize_rfdetr_result(raw, confidence_threshold=0.0)
    assert len(detections) == 1
    assert detections[0].class_name == "person"


def test_tracker_keeps_track_id_for_overlapping_detection():
    tracker = ByteTrackAdapter(minimum_consecutive_frames=1)
    timestamp = datetime.now(timezone.utc)

    # Frame 1: first detection creates an unconfirmed track (no ID returned)
    first = tracker.update(
        "cam_1",
        [Detection("person", 0.9, BoundingBox(10, 10, 100, 200))],
        timestamp,
    )
    # Frame 2: same object detected again — track is now confirmed with a stable ID
    second = tracker.update(
        "cam_1",
        [Detection("person", 0.88, BoundingBox(14, 12, 104, 202))],
        timestamp,
    )

    # First frame returns empty (track not yet confirmed by ByteTrack)
    assert len(first) == 0
    # Second frame returns the confirmed track
    assert len(second) == 1
    assert second[0].track_id >= 0
    assert second[0].camera_id == "cam_1"

    # Frame 3: track ID must remain stable
    third = tracker.update(
        "cam_1",
        [Detection("person", 0.92, BoundingBox(18, 14, 108, 204))],
        timestamp,
    )
    assert len(third) == 1
    assert third[0].track_id == second[0].track_id


def test_tracker_assigns_new_ids_for_new_objects():
    tracker = ByteTrackAdapter(minimum_consecutive_frames=1)
    timestamp = datetime.now(timezone.utc)

    # Frame 1: two new objects — no confirmed tracks yet
    first = tracker.update(
        "cam_1",
        [
            Detection("person", 0.9, BoundingBox(10, 10, 100, 200)),
            Detection("person", 0.8, BoundingBox(300, 100, 400, 300)),
        ],
        timestamp,
    )
    assert len(first) == 0

    # Frame 2: same objects — both should now be confirmed with distinct IDs
    second = tracker.update(
        "cam_1",
        [
            Detection("person", 0.9, BoundingBox(12, 12, 102, 202)),
            Detection("person", 0.8, BoundingBox(302, 102, 402, 302)),
        ],
        timestamp,
    )
    assert len(second) == 2
    assert second[0].track_id != second[1].track_id
    assert second[0].track_id >= 0
    assert second[1].track_id >= 0


def test_tracker_different_classes_get_different_ids():
    tracker = ByteTrackAdapter(minimum_consecutive_frames=1)
    timestamp = datetime.now(timezone.utc)

    # Frame 1: person + car — no confirmed tracks
    first = tracker.update(
        "cam_1",
        [
            Detection("person", 0.9, BoundingBox(10, 10, 100, 200)),
            Detection("car", 0.9, BoundingBox(10, 10, 100, 200)),
        ],
        timestamp,
    )
    assert len(first) == 0

    # Frame 2: both objects confirmed — different classes get independent IDs
    second = tracker.update(
        "cam_1",
        [
            Detection("person", 0.9, BoundingBox(12, 12, 102, 202)),
            Detection("car", 0.9, BoundingBox(12, 12, 102, 202)),
        ],
        timestamp,
    )
    assert len(second) == 2
    assert second[0].track_id != second[1].track_id
    assert second[0].class_name == "person"
    assert second[1].class_name == "car"


def test_tracker_expired_tracks_are_removed():
    tracker = ByteTrackAdapter(
        minimum_consecutive_frames=1,
        lost_track_buffer=1,
    )
    timestamp = datetime.now(timezone.utc)

    # Frame 1: detect object — track created (unconfirmed)
    tracker.update(
        "cam_1",
        [Detection("person", 0.9, BoundingBox(10, 10, 100, 200))],
        timestamp,
    )
    # Frame 2: detect same object — track confirmed
    first = tracker.update(
        "cam_1",
        [Detection("person", 0.9, BoundingBox(10, 10, 100, 200))],
        timestamp,
    )
    assert len(first) == 1
    original_id = first[0].track_id

    # Frame 3-4: object disappears — track lost
    tracker.update("cam_1", [], timestamp)
    tracker.update("cam_1", [], timestamp)

    # Frame 5: same object reappears — should get a NEW track ID (old one expired)
    reappearing = tracker.update(
        "cam_1",
        [Detection("person", 0.9, BoundingBox(10, 10, 100, 200))],
        timestamp,
    )
    assert len(reappearing) == 0  # unconfirmed on this frame

    confirmed = tracker.update(
        "cam_1",
        [Detection("person", 0.9, BoundingBox(10, 10, 100, 200))],
        timestamp,
    )
    assert len(confirmed) == 1
    assert confirmed[0].track_id != original_id


def test_tracker_two_people_keep_independent_stable_ids():
    tracker = ByteTrackAdapter(minimum_consecutive_frames=1)
    timestamp = datetime.now(timezone.utc)

    tracker.update(
        "cam_1",
        [
            Detection("person", 0.9, BoundingBox(100, 100, 200, 300)),
            Detection("person", 0.9, BoundingBox(400, 100, 500, 300)),
        ],
        timestamp,
    )
    second = tracker.update(
        "cam_1",
        [
            Detection("person", 0.9, BoundingBox(110, 100, 210, 300)),
            Detection("person", 0.9, BoundingBox(390, 100, 490, 300)),
        ],
        timestamp,
    )
    third = tracker.update(
        "cam_1",
        [
            Detection("person", 0.9, BoundingBox(120, 100, 220, 300)),
            Detection("person", 0.9, BoundingBox(380, 100, 480, 300)),
        ],
        timestamp,
    )

    assert len(second) == 2
    assert len(third) == 2
    assert [obj.track_id for obj in third] == [obj.track_id for obj in second]
    assert third[0].track_id != third[1].track_id


def test_tracker_preserves_id_after_short_detection_gap():
    tracker = ByteTrackAdapter(minimum_consecutive_frames=1, lost_track_buffer=5)
    timestamp = datetime.now(timezone.utc)

    tracker.update(
        "cam_1",
        [Detection("person", 0.9, BoundingBox(100, 100, 200, 300))],
        timestamp,
    )
    confirmed = tracker.update(
        "cam_1",
        [Detection("person", 0.9, BoundingBox(105, 100, 205, 300))],
        timestamp,
    )
    tracker.update("cam_1", [], timestamp)
    returned = tracker.update(
        "cam_1",
        [Detection("person", 0.9, BoundingBox(110, 100, 210, 300))],
        timestamp,
    )

    assert len(confirmed) == 1
    assert len(returned) == 1
    assert returned[0].track_id == confirmed[0].track_id


def test_tracker_state_isolated_by_instance_per_camera():
    cam_1_tracker = ByteTrackAdapter(minimum_consecutive_frames=1)
    cam_2_tracker = ByteTrackAdapter(minimum_consecutive_frames=1)
    timestamp = datetime.now(timezone.utc)

    for tracker, camera_id in [(cam_1_tracker, "cam_1"), (cam_2_tracker, "cam_2")]:
        tracker.update(
            camera_id,
            [Detection("person", 0.9, BoundingBox(100, 100, 200, 300))],
            timestamp,
        )

    cam_1_objects = cam_1_tracker.update(
        "cam_1",
        [Detection("person", 0.9, BoundingBox(105, 100, 205, 300))],
        timestamp,
    )
    cam_2_objects = cam_2_tracker.update(
        "cam_2",
        [Detection("person", 0.9, BoundingBox(105, 100, 205, 300))],
        timestamp,
    )

    assert len(cam_1_objects) == 1
    assert len(cam_2_objects) == 1
    assert cam_1_objects[0].camera_id == "cam_1"
    assert cam_2_objects[0].camera_id == "cam_2"
    assert cam_1_objects[0].track_id == cam_2_objects[0].track_id


def test_tracker_reset_drops_previous_state():
    tracker = ByteTrackAdapter(minimum_consecutive_frames=1)
    timestamp = datetime.now(timezone.utc)

    tracker.update(
        "cam_1",
        [Detection("person", 0.9, BoundingBox(100, 100, 200, 300))],
        timestamp,
    )
    before_reset = tracker.update(
        "cam_1",
        [Detection("person", 0.9, BoundingBox(105, 100, 205, 300))],
        timestamp,
    )

    tracker.reset()

    after_reset = tracker.update(
        "cam_1",
        [Detection("person", 0.9, BoundingBox(105, 100, 205, 300))],
        timestamp,
    )

    assert len(before_reset) == 1
    assert after_reset == []


def test_bytetrack_adapter_stable_tracking_across_frames():
    """Validates that ByteTrackAdapter assigns stable track IDs across 3+
    consecutive frames for a moving object — the core requirement of the
    tracking upgrade."""
    tracker = ByteTrackAdapter(minimum_consecutive_frames=1)
    timestamp = datetime.now(timezone.utc)

    results: list[list[TrackedObject]] = []
    boxes = [
        BoundingBox(100, 100, 200, 300),
        BoundingBox(105, 105, 205, 305),
        BoundingBox(110, 110, 210, 310),
        BoundingBox(115, 115, 215, 315),
    ]
    for box in boxes:
        result = tracker.update(
            "cam_1",
            [Detection("person", 0.95, box)],
            timestamp,
        )
        results.append(result)

    # Frame 1 returns empty (unconfirmed)
    assert len(results[0]) == 0
    # Frames 2-4 should return the same track ID (stable tracking)
    for frame_result in results[1:]:
        assert len(frame_result) == 1
    track_id = results[1][0].track_id
    assert results[2][0].track_id == track_id
    assert results[3][0].track_id == track_id
    # Bounding boxes should be updated to detection positions
    assert results[3][0].bounding_box.x1 == 115
    assert results[3][0].bounding_box.y1 == 115


def test_bytetrack_adapter_empty_detections():
    """ByteTrackAdapter should handle empty detection lists without errors."""
    tracker = ByteTrackAdapter(minimum_consecutive_frames=1)
    timestamp = datetime.now(timezone.utc)
    result = tracker.update("cam_1", [], timestamp)
    assert result == []


def test_vision_session_processes_frame_and_tracks_objects():
    session = _make_session()

    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    timestamp = datetime.now(timezone.utc)

    session.process(frame, timestamp)

    assert session.status == "RUNNING"
    objects = session.objects()
    assert len(objects) == 2
    assert objects[0].track_id == 1
    assert objects[0].class_name == "person"
    assert objects[1].track_id == 2
    assert objects[1].class_name == "car"


def test_latest_frame_buffer_replaces_stale_frame():
    buffer = LatestFrameBuffer()
    first = np.zeros((8, 8, 3), dtype=np.uint8)
    second = np.ones((8, 8, 3), dtype=np.uint8)
    timestamp = datetime.now(timezone.utc)

    buffer.put(first, timestamp)
    buffer.put(second, timestamp)

    frame, frame_at = buffer.latest()
    stats = buffer.stats()

    assert frame_at == timestamp
    assert int(frame[0][0][0]) == 1
    assert stats.frames_received == 2
    assert stats.frames_replaced == 1


def test_latest_frame_buffer_does_not_accumulate_stale_frames():
    buffer = LatestFrameBuffer()
    timestamp = datetime.now(timezone.utc)

    for value in range(5):
        buffer.put(np.full((2, 2, 3), value, dtype=np.uint8), timestamp)

    snapshot = buffer.snapshot()

    assert int(snapshot.frame[0][0][0]) == 4
    assert snapshot.frames_received == 5
    assert snapshot.frames_replaced == 4


def test_vision_session_should_process_rate_limits():
    session = _make_session()
    timestamp = datetime.now(timezone.utc)

    assert session.should_process(timestamp) is True

    assert session.should_process(timestamp) is False

    new_timestamp = timestamp + timedelta(seconds=0.001)
    assert session.should_process(new_timestamp) is False

    time.sleep(1 / session.settings.vision_fps + 0.05)
    assert session.should_process(new_timestamp) is True


def test_vision_session_stop():
    session = _make_session()
    session.stop()

    assert session.status == "STOPPED"


def test_vision_session_restart():
    session = _make_session()

    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    timestamp = datetime.now(timezone.utc)
    session.process(frame, timestamp)
    assert session.status == "RUNNING"
    assert session.error is None

    session.restart()
    assert session.status == "STARTING"
    assert session.objects() == []
    assert session.error is None


def test_vision_session_fail_sets_error():
    session = _make_session()

    session.fail("Detector not loaded")

    assert session.status == "ERROR"
    assert session.error == "Detector not loaded"


def test_vision_session_status_contains_metrics():
    session = _make_session()
    status = session.as_status(camera_fps=30.0, frames_received=8, frames_dropped=3)

    assert status["camera_id"] == "cam_1"
    assert status["status"] in {"STARTING", "RUNNING", "RECOVER", "ERROR", "STOPPED"}
    assert status["vision_status"] == status["status"]
    assert status["metrics"] is not None
    assert status["metrics"]["detector"] == "FakeDetector"
    assert status["metrics"]["device"] == "CPU"
    assert status["metrics"]["camera_fps"] == 30.0
    assert status["metrics"]["frames_received"] == 8
    assert status["metrics"]["frames_dropped"] == 3


def test_vision_engine_disabled_status(tmp_path: Path):
    settings = make_settings(tmp_path / "vision-disabled.sqlite3")
    settings = settings.__class__(**{**settings.__dict__, "vision_enabled": False})
    initialize_database(settings)

    repository = CameraRepository(settings)
    manager = CameraManager(settings, repository)
    engine = VisionEngine(settings, manager)
    try:
        status = engine.start_session("cam_missing")
    finally:
        engine.shutdown()
        manager.shutdown()

    assert status["status"] == "DISABLED"


def test_vision_session_duplicate_start_reuses_session(tmp_path: Path):
    settings = make_settings(tmp_path / "vision.sqlite3")
    initialize_database(settings)
    repository = CameraRepository(settings)
    camera = repository.create(
        name="Video",
        area_id=None,
        source_type="video_file",
        source_uri=str(tmp_path / "missing.mp4"),
        enabled=False,
        vision_enabled=True,
    )
    manager = CameraManager(settings, repository)
    engine = VisionEngine(settings, manager)
    try:
        first = engine.start_session(camera.id)
        second = engine.start_session(camera.id)
    finally:
        engine.shutdown()
        manager.shutdown()

    assert first["camera_id"] == camera.id
    assert second["camera_id"] == camera.id
    assert first["status"] in {"STARTING", "ERROR"}
    assert second["status"] in {"STARTING", "ERROR"}


def test_vision_engine_stop_session(tmp_path: Path):
    settings = make_settings(tmp_path / "vision-stop.sqlite3")
    initialize_database(settings)
    repository = CameraRepository(settings)
    camera = repository.create(
        name="Video",
        area_id=None,
        source_type="video_file",
        source_uri=str(tmp_path / "missing.mp4"),
        enabled=False,
        vision_enabled=True,
    )
    manager = CameraManager(settings, repository)
    engine = VisionEngine(settings, manager)

    with patch("backend.vision.engine.create_detector", return_value=FakeDetector()):
        engine.start_session(camera.id)
        status = engine.status(camera.id)
        assert status["status"] in {"STARTING", "ERROR", "RUNNING"}

        stop_status = engine.stop_session(camera.id)
        assert stop_status["status"] == "STOPPED"

        after_stop = engine.status(camera.id)
        assert after_stop["status"] == "STOPPED"
    engine.shutdown()
    manager.shutdown()


def test_vision_engine_restart_session(tmp_path: Path):
    settings = make_settings(tmp_path / "vision-restart.sqlite3")
    initialize_database(settings)
    repository = CameraRepository(settings)
    camera = repository.create(
        name="Video",
        area_id=None,
        source_type="video_file",
        source_uri=str(tmp_path / "missing.mp4"),
        enabled=False,
        vision_enabled=True,
    )
    manager = CameraManager(settings, repository)
    engine = VisionEngine(settings, manager)

    with patch("backend.vision.engine.create_detector", return_value=FakeDetector()):
        start_status = engine.start_session(camera.id)
        assert start_status["status"] in {"STARTING", "ERROR", "RUNNING"}

        restart_status = engine.restart_session(camera.id)
        assert restart_status["camera_id"] == camera.id
        assert restart_status["status"] in {"STARTING", "ERROR", "RUNNING"}
    engine.shutdown()
    manager.shutdown()


def test_vision_engine_start_stop_start_without_restart(tmp_path: Path):
    settings = make_settings(tmp_path / "vision-cycle.sqlite3")
    initialize_database(settings)
    repository = CameraRepository(settings)
    camera = repository.create(
        name="Video",
        area_id=None,
        source_type="video_file",
        source_uri=str(tmp_path / "missing.mp4"),
        enabled=False,
        vision_enabled=True,
    )
    manager = CameraManager(settings, repository)
    engine = VisionEngine(settings, manager)

    with patch("backend.vision.engine.create_detector", return_value=FakeDetector()):
        first_start = engine.start_session(camera.id)
        assert first_start["camera_id"] == camera.id

        engine.stop_session(camera.id)
        assert engine.status(camera.id)["status"] == "STOPPED"

        second_start = engine.start_session(camera.id)
        assert second_start["camera_id"] == camera.id
        assert second_start["status"] in {"STARTING", "ERROR", "RUNNING"}
    engine.shutdown()
    manager.shutdown()


def test_vision_engine_camera_offline_sets_error(tmp_path: Path):
    settings = make_settings(tmp_path / "vision-offline.sqlite3")
    initialize_database(settings)
    repository = CameraRepository(settings)
    manager = CameraManager(settings, repository)
    engine = VisionEngine(settings, manager)

    with patch("backend.vision.engine.create_detector", return_value=FakeDetector()):
        engine.start_session("cam_nonexistent")
        time.sleep(0.3)
        status = engine.status("cam_nonexistent")
    engine.shutdown()
    manager.shutdown()

    assert status["status"] == "ERROR"
    assert "offline" in (status.get("error") or "").lower()


def test_vision_engine_detectors_singleton(tmp_path: Path):
    settings = make_settings(tmp_path / "vision-singleton.sqlite3")
    initialize_database(settings)
    repository = CameraRepository(settings, )
    manager = CameraManager(settings, repository)
    engine = VisionEngine(settings, manager)

    fake = FakeDetector()
    with patch("backend.vision.engine.create_detector", return_value=fake):
        engine.start_session("cam_1")
        engine.start_session("cam_2")
        time.sleep(0.2)

    assert fake.load_calls == 1
    engine.shutdown()
    manager.shutdown()


def test_vision_engine_error_does_not_crash(tmp_path: Path):
    settings = make_settings(tmp_path / "vision-crash.sqlite3")
    initialize_database(settings)
    repository = CameraRepository(settings)
    manager = CameraManager(settings, repository)
    engine = VisionEngine(settings, manager)
    started = False
    try:
        with patch("backend.vision.engine.create_detector", return_value=FakeDetector()):
            engine.start_session("cam_no_camera")
            time.sleep(0.3)
            status = engine.status("cam_no_camera")
            assert status["status"] in {"ERROR", "RUNNING", "STARTING"}
            assert engine._thread.is_alive()
            started = True
    finally:
        engine.shutdown()
        manager.shutdown()

    assert started
    assert not engine._thread.is_alive()


def test_tracker_failure_sets_vision_error_without_crashing_session():
    session = _make_session(tracker=FailingTracker())
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    timestamp = datetime.now(timezone.utc)

    with pytest.raises(RuntimeError):
        session.process(frame, timestamp)

    assert session.status == "ERROR"
    assert "tracker" in (session.error or "").lower()


def test_vision_metrics_has_all_required_fields():
    metrics = VisionMetrics(
        camera_fps=30.0,
        vision_fps=5.0,
        inference_ms=45.0,
        objects_detected=2,
        device="CPU",
        detector="RF-DETR Nano",
        tracker="ByteTrack",
        uptime=120.0,
        frames_received=100,
        frames_processed=20,
        frames_dropped=80,
        frame_age_ms=41.0,
    )
    data = metrics.as_dict()

    assert data["camera_fps"] == 30.0
    assert data["vision_fps"] == 5.0
    assert data["inference_ms"] == 45.0
    assert data["objects_detected"] == 2
    assert data["device"] == "CPU"
    assert data["detector"] == "RF-DETR Nano"
    assert data["tracker"] == "ByteTrack"
    assert data["uptime"] == 120.0
    assert data["frames_received"] == 100
    assert data["frames_processed"] == 20
    assert data["frames_dropped"] == 80
    assert data["frame_age_ms"] == 41.0


def test_tracked_object_as_dict():
    timestamp = datetime.now(timezone.utc)
    obj = TrackedObject(
        track_id=12,
        camera_id="cam_1",
        class_name="person",
        confidence=0.96,
        bounding_box=BoundingBox(x1=10, y1=20, x2=100, y2=200),
        timestamp=timestamp,
    )
    data = obj.as_dict()

    assert data["track_id"] == 12
    assert data["camera_id"] == "cam_1"
    assert data["class_name"] == "person"
    assert data["confidence"] == 0.96
    assert data["bounding_box"] == [10.0, 20.0, 100.0, 200.0]
    assert data["timestamp"] == timestamp.isoformat()


def test_detection_as_dict():
    detection = Detection(
        class_name="person",
        confidence=0.91,
        bounding_box=BoundingBox(x1=10, y1=20, x2=110, y2=220),
    )
    data = detection.as_dict()

    assert data["class_name"] == "person"
    assert data["confidence"] == 0.91
    assert data["bounding_box"] == [10.0, 20.0, 110.0, 220.0]


def test_overlay_renderer_accepts_tracked_objects():
    renderer = OverlayRenderer()
    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    obj = TrackedObject(
        track_id=12,
        camera_id="cam_1",
        class_name="person",
        confidence=0.94,
        bounding_box=BoundingBox(10, 20, 80, 100),
        timestamp=datetime.now(timezone.utc),
    )

    rendered = renderer.render(frame, [obj])

    assert rendered.shape == frame.shape
    assert int(rendered.sum()) > 0


def test_create_detector_unsupported_type():
    settings = make_settings(Path("/tmp/test_unsupported.sqlite3"))
    fields = {**settings.__dict__, "vision_detector": "yolox"}
    settings = settings.__class__(**fields)
    with pytest.raises(DetectorUnavailable):
        create_detector(settings)


def test_motion_detector_no_motion_on_blank_frame():
    from backend.vision.motion import MotionDetector, MotionResult

    detector = MotionDetector()
    frame = np.zeros((480, 640, 3), dtype=np.uint8)

    assert detector.has_reference is False
    result = detector.detect(frame)
    assert result.motion_detected is False
    assert detector.has_reference is True


def test_motion_detector_detects_frame_change():
    from backend.vision.motion import MotionDetector

    detector = MotionDetector()
    base = np.zeros((480, 640, 3), dtype=np.uint8)
    detector.detect(base)

    changed = base.copy()
    cv2.rectangle(changed, (100, 100), (200, 200), (255, 255, 255), -1)

    result = detector.detect(changed)
    assert result.motion_detected is True
    assert result.motion_pixels > 0
    assert len(result.regions) > 0


def test_motion_detector_reset_clears_reference():
    from backend.vision.motion import MotionDetector

    detector = MotionDetector()
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    detector.detect(frame)
    assert detector.has_reference is True

    detector.reset()
    assert detector.has_reference is False


def test_motion_detector_skips_detection_when_no_motion():
    session = _make_session()
    frame_a = np.zeros((480, 640, 3), dtype=np.uint8)
    frame_b = np.zeros((480, 640, 3), dtype=np.uint8)
    timestamp = datetime.now(timezone.utc)

    session.process(frame_a, timestamp)
    assert session.status == "RUNNING"

    session.process(frame_b, timestamp)
    objects = session.objects()
    assert len(objects) == 0


def test_motion_engine_detects_motion_v2():
    from backend.vision.motion import MotionEngine

    engine = MotionEngine(resize_width=96, minimum_motion_pixels=10)
    base = np.zeros((480, 640, 3), dtype=np.uint8)
    engine.detect(base)  # initialize background

    changed = base.copy()
    cv2.rectangle(changed, (100, 100), (300, 300), (255, 255, 255), -1)

    result = engine.detect(changed)
    assert result.motion_detected is True
    assert result.motion_pixels > 0
    assert len(result.regions) > 0
    assert result.motion_magnitude > 0.0
    assert result.motion_center is not None


def test_motion_engine_no_motion_on_blank_frame_v2():
    from backend.vision.motion import MotionEngine

    engine = MotionEngine(resize_width=96, minimum_motion_pixels=50)
    frame = np.zeros((480, 640, 3), dtype=np.uint8)

    result = engine.detect(frame)
    assert result.motion_detected is False
    assert result.motion_pixels == 0
    assert result.motion_magnitude == 0.0


def test_motion_engine_provides_direction_v2():
    from backend.vision.motion import MotionEngine

    engine = MotionEngine(resize_width=96, minimum_motion_pixels=10)
    base = np.full((480, 640, 3), 50, dtype=np.uint8)
    engine.detect(base)

    frame1 = base.copy()
    cv2.rectangle(frame1, (100, 100), (200, 200), (255, 255, 255), -1)
    engine.detect(frame1)

    frame2 = base.copy()
    cv2.rectangle(frame2, (150, 100), (250, 200), (255, 255, 255), -1)
    result = engine.detect(frame2)

    assert result.motion_detected is True
    assert result.motion_direction is not None
    # Movement shifted right, so x-direction should be positive
    assert result.motion_direction[0] > 0


def test_motion_engine_reset_v2():
    from backend.vision.motion import MotionEngine

    engine = MotionEngine(resize_width=96, minimum_motion_pixels=50)
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    engine.detect(frame)
    assert engine.has_reference is True

    engine.reset()
    assert engine.has_reference is False


def test_motion_engine_empty_detections_v2():
    from backend.vision.motion import MotionEngine

    engine = MotionEngine(resize_width=96, minimum_motion_pixels=50)
    result = engine.detect(None)
    assert result.motion_detected is False
    assert result.motion_pixels == 0


def test_spatial_engine_point_in_polygon():
    from backend.zones.engine import SpatialEngine
    from backend.zones.models import ZonePoint

    # Square polygon (0,0) to (1,1)
    points = [
        ZonePoint(x=0.0, y=0.0),
        ZonePoint(x=1.0, y=0.0),
        ZonePoint(x=1.0, y=1.0),
        ZonePoint(x=0.0, y=1.0),
    ]

    # Inside
    assert SpatialEngine.point_in_polygon(0.5, 0.5, points) is True
    assert SpatialEngine.point_in_polygon(0.1, 0.1, points) is True
    assert SpatialEngine.point_in_polygon(0.9, 0.9, points) is True

    # Outside
    assert SpatialEngine.point_in_polygon(-0.1, 0.5, points) is False
    assert SpatialEngine.point_in_polygon(1.1, 0.5, points) is False
    assert SpatialEngine.point_in_polygon(0.5, -0.1, points) is False
    assert SpatialEngine.point_in_polygon(0.5, 1.1, points) is False


def test_spatial_engine_zone_entry_exit():
    from backend.vision.models import BoundingBox, Detection, TrackedObject
    from backend.zones.engine import SpatialEngine
    from backend.zones.models import Zone, ZonePoint
    from datetime import datetime, timezone

    engine = SpatialEngine()

    # Create a restricted zone covering left half of frame
    zone = Zone(
        id="zone_1",
        camera_id="cam_1",
        name="Restricted",
        type="restricted",
        enabled=True,
        points=[
            ZonePoint(x=0.0, y=0.0),
            ZonePoint(x=0.5, y=0.0),
            ZonePoint(x=0.5, y=1.0),
            ZonePoint(x=0.0, y=1.0),
        ],
        created_at="2024-01-01T00:00:00",
        updated_at="2024-01-01T00:00:00",
    )
    engine.update_zones("cam_1", [zone])

    timestamp = datetime.now(timezone.utc)

    # Frame 1: track outside zone (x=0.75)
    obj1 = TrackedObject(
        track_id=1,
        camera_id="cam_1",
        class_name="person",
        confidence=0.9,
        bounding_box=BoundingBox(x1=480, y1=100, x2=580, y2=300),
        timestamp=timestamp,
    )
    obs, _ = engine.evaluate("cam_1", [obj1], 640, 480)
    assert len(obs) == 0  # No zone entry yet

    # Frame 2: track enters zone (x=0.25)
    obj2 = TrackedObject(
        track_id=1,
        camera_id="cam_1",
        class_name="person",
        confidence=0.9,
        bounding_box=BoundingBox(x1=60, y1=100, x2=160, y2=300),
        timestamp=timestamp,
    )
    obs, _ = engine.evaluate("cam_1", [obj2], 640, 480)
    # Should detect entry
    entry_obs = [o for o in obs if o.type == "person_entered_zone"]
    assert len(entry_obs) == 1
    assert entry_obs[0].zone_id == "zone_1"
    assert entry_obs[0].track_id == 1

    # Frame 3: track still in zone (presence)
    obj3 = TrackedObject(
        track_id=1,
        camera_id="cam_1",
        class_name="person",
        confidence=0.9,
        bounding_box=BoundingBox(x1=70, y1=110, x2=170, y2=310),
        timestamp=timestamp,
    )
    obs, _ = engine.evaluate("cam_1", [obj3], 640, 480)
    presence_obs = [o for o in obs if o.type == "person_presence"]
    assert len(presence_obs) == 1

    # Frame 4: track exits zone (x=0.75)
    obj4 = TrackedObject(
        track_id=1,
        camera_id="cam_1",
        class_name="person",
        confidence=0.9,
        bounding_box=BoundingBox(x1=480, y1=100, x2=580, y2=300),
        timestamp=timestamp,
    )
    obs, _ = engine.evaluate("cam_1", [obj4], 640, 480)
    exit_obs = [o for o in obs if o.type == "person_exited_zone"]
    assert len(exit_obs) == 1
    assert exit_obs[0].zone_id == "zone_1"
    assert exit_obs[0].track_id == 1


def test_spatial_engine_disappeared_track_emits_exit():
    from backend.vision.models import BoundingBox, TrackedObject
    from backend.zones.engine import SpatialEngine
    from backend.zones.models import Zone, ZonePoint
    from datetime import datetime, timezone

    engine = SpatialEngine()
    zone = Zone(
        id="zone_1",
        camera_id="cam_1",
        name="Restricted",
        type="restricted",
        enabled=True,
        points=[
            ZonePoint(x=0.0, y=0.0),
            ZonePoint(x=1.0, y=0.0),
            ZonePoint(x=1.0, y=1.0),
            ZonePoint(x=0.0, y=1.0),
        ],
        created_at="2024-01-01T00:00:00",
        updated_at="2024-01-01T00:00:00",
    )
    engine.update_zones("cam_1", [zone])

    timestamp = datetime.now(timezone.utc)

    # Frame 1: track inside zone
    obj1 = TrackedObject(
        track_id=1,
        camera_id="cam_1",
        class_name="person",
        confidence=0.9,
        bounding_box=BoundingBox(x1=100, y1=100, x2=200, y2=300),
        timestamp=timestamp,
    )
    engine.evaluate("cam_1", [obj1], 640, 480)

    # Frame 2: track disappears briefly (empty list), but we tolerate short gaps.
    obs, _ = engine.evaluate("cam_1", [], 640, 480)
    exit_obs = [o for o in obs if o.type == "person_exited_zone"]
    assert len(exit_obs) == 0

    engine.evaluate("cam_1", [], 640, 480)
    obs, _ = engine.evaluate("cam_1", [], 640, 480)
    exit_obs = [o for o in obs if o.type == "person_exited_zone"]
    assert len(exit_obs) == 1
    assert exit_obs[0].track_id == 1


def test_event_engine_restricted_zone_entry():
    from backend.events.engine import EventEngine
    from backend.events.repository import EventRepository
    from backend.zones.models import Observation, Zone
    from backend.config import Settings
    from pathlib import Path

    settings = Settings(
        environment="test",
        service_name="campex",
        version="0.1.0",
        log_level="INFO",
        database_url=f"sqlite:///{Path('/tmp/test_events.sqlite3')}",
        frontend_origins=["*"],
        camera_reconnect_seconds=5,
        camera_stale_seconds=10,
        camera_offline_seconds=30,
        camera_read_failure_limit=3,
        camera_test_timeout_seconds=5,
        vision_enabled=True,
        vision_detector="rfdetr",
        vision_device="auto",
        vision_fps=5,
        vision_confidence=0.5,
        vision_video_loop=False,
    )

    from backend.database.db import initialize_database
    initialize_database(settings)

    event_repo = EventRepository.for_settings(settings)
    engine = EventEngine(event_repo)

    # Create observation for restricted zone entry
    obs = Observation(
        type="person_entered_zone",
        camera_id="cam_1",
        track_id=1,
        zone_id="zone_1",
        state="present",
        confidence=0.9,
        timestamp=datetime.now(timezone.utc),
    )

    zone = Zone(
        id="zone_1",
        camera_id="cam_1",
        name="Restricted",
        type="restricted",
        enabled=True,
        points=[],
        created_at="2024-01-01T00:00:00",
        updated_at="2024-01-01T00:00:00",
    )

    events = engine.process("cam_1", [obs], [zone])
    assert len(events) == 1
    assert events[0].type == "PERSON_RESTRICTED_ZONE"
    assert events[0].severity == "critical"
    assert events[0].track_id == 1
    assert events[0].zone_id == "zone_1"
    assert events[0].status == "OPEN"

    # Second call with same track/zone should not create duplicate
    events2 = engine.process("cam_1", [obs], [zone])
    assert len(events2) == 0  # No duplicate


def test_event_engine_restricted_zone_exit():
    from backend.events.engine import EventEngine
    from backend.events.repository import EventRepository
    from backend.zones.models import Observation, Zone
    from backend.config import Settings
    from pathlib import Path
    from datetime import datetime, timezone

    settings = Settings(
        environment="test",
        service_name="campex",
        version="0.1.0",
        log_level="INFO",
        database_url=f"sqlite:///{Path('/tmp/test_events2.sqlite3')}",
        frontend_origins=["*"],
        camera_reconnect_seconds=5,
        camera_stale_seconds=10,
        camera_offline_seconds=30,
        camera_read_failure_limit=3,
        camera_test_timeout_seconds=5,
        vision_enabled=True,
        vision_detector="rfdetr",
        vision_device="auto",
        vision_fps=5,
        vision_confidence=0.5,
        vision_video_loop=False,
    )

    from backend.database.db import initialize_database
    initialize_database(settings)

    event_repo = EventRepository.for_settings(settings)
    engine = EventEngine(event_repo)

    obs_entry = Observation(
        type="person_entered_zone",
        camera_id="cam_1",
        track_id=1,
        zone_id="zone_1",
        state="present",
        confidence=0.9,
        timestamp=datetime.now(timezone.utc),
    )
    zone = Zone(
        id="zone_1",
        camera_id="cam_1",
        name="Restricted",
        type="restricted",
        enabled=True,
        points=[],
        created_at="2024-01-01T00:00:00",
        updated_at="2024-01-01T00:00:00",
    )

    # Create event
    events = engine.process("cam_1", [obs_entry], [zone])
    assert len(events) == 1
    event_id = events[0].id

    # Exit
    obs_exit = Observation(
        type="person_exited_zone",
        camera_id="cam_1",
        track_id=1,
        zone_id="zone_1",
        state="absent",
        confidence=0.9,
        timestamp=datetime.now(timezone.utc),
    )
    events = engine.process("cam_1", [obs_exit], [zone])
    assert len(events) == 1
    assert events[0].status == "CLOSED"
    assert events[0].duration is not None
    assert events[0].duration > 0


def test_event_engine_dwell_threshold():
    from backend.events.engine import EventEngine
    from backend.events.repository import EventRepository
    from backend.events.models import EventRule
    from backend.zones.models import Observation, Zone
    from backend.config import Settings
    from pathlib import Path
    from datetime import datetime, timezone
    import time

    settings = Settings(
        environment="test",
        service_name="campex",
        version="0.1.0",
        log_level="INFO",
        database_url=f"sqlite:///{Path('/tmp/test_events3.sqlite3')}",
        frontend_origins=["*"],
        camera_reconnect_seconds=5,
        camera_stale_seconds=10,
        camera_offline_seconds=30,
        camera_read_failure_limit=3,
        camera_test_timeout_seconds=5,
        vision_enabled=True,
        vision_detector="rfdetr",
        vision_device="auto",
        vision_fps=5,
        vision_confidence=0.5,
        vision_video_loop=False,
    )

    from backend.database.db import initialize_database
    initialize_database(settings)

    event_repo = EventRepository.for_settings(settings)
    # Custom rule with 0.1s dwell threshold
    custom_rules = [
        EventRule(
            name="restricted_zone_entry",
            observation_type="person_entered_zone",
            zone_type="restricted",
            event_type="PERSON_RESTRICTED_ZONE",
            severity="critical",
        ),
        EventRule(
            name="restricted_zone_dwell",
            observation_type="person_presence",
            zone_type="restricted",
            event_type="PERSON_RESTRICTED_ZONE_DWELL",
            severity="critical",
            duration_threshold_seconds=0.1,
        ),
    ]
    engine = EventEngine(event_repo, rules=custom_rules)

    zone = Zone(
        id="zone_1",
        camera_id="cam_1",
        name="Restricted",
        type="restricted",
        enabled=True,
        points=[],
        created_at="2024-01-01T00:00:00",
        updated_at="2024-01-01T00:00:00",
    )

    # First: person enters zone (starts dwell timer)
    obs_entry = Observation(
        type="person_entered_zone",
        camera_id="cam_1",
        track_id=1,
        zone_id="zone_1",
        state="present",
        confidence=0.9,
        timestamp=datetime.now(timezone.utc),
    )
    events = engine.process("cam_1", [obs_entry], [zone])
    # Entry creates the main event
    assert len(events) == 1
    assert events[0].type == "PERSON_RESTRICTED_ZONE"

    # Wait for dwell threshold
    time.sleep(0.15)

    # Second: person presence (should trigger dwell event)
    obs_presence = Observation(
        type="person_presence",
        camera_id="cam_1",
        track_id=1,
        zone_id="zone_1",
        state="present",
        confidence=0.9,
        timestamp=datetime.now(timezone.utc),
    )
    events = engine.process("cam_1", [obs_presence], [zone])
    assert len(events) == 1
    assert events[0].type == "PERSON_RESTRICTED_ZONE_DWELL"


def test_vision_session_recovers_from_error():
    session = _make_session()
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    timestamp = datetime.now(timezone.utc)

    session.process(frame, timestamp)
    assert session.status == "RUNNING"

    session.fail("Simulated detector failure")
    assert session.status == "ERROR"
    assert session.error == "Simulated detector failure"

    session.process(frame, timestamp)
    assert session.status == "RUNNING"
    assert session.error is None


def test_vision_engine_toggle_start_stop_start(tmp_path: Path):
    settings = make_settings(tmp_path / "vision-toggle.sqlite3")
    initialize_database(settings)
    repository = CameraRepository(settings)
    camera = repository.create(
        name="Video",
        area_id=None,
        source_type="video_file",
        source_uri=str(tmp_path / "missing.mp4"),
        enabled=False,
        vision_enabled=True,
    )
    manager = CameraManager(settings, repository)
    engine = VisionEngine(settings, manager)

    try:
        with patch("backend.vision.engine.create_detector", return_value=FakeDetector()):
            on_status = engine.start_session(camera.id)
            assert on_status["status"] in {"STARTING", "ERROR", "RUNNING"}

            off_status = engine.stop_session(camera.id)
            assert off_status["status"] == "STOPPED"

            on_status_2 = engine.start_session(camera.id)
            assert on_status_2["camera_id"] == camera.id
            assert on_status_2["status"] in {"STARTING", "ERROR", "RUNNING"}

            assert engine._thread.is_alive()
    finally:
        engine.shutdown()
        manager.shutdown()


def test_vision_engine_session_recovers_when_camera_comes_back(tmp_path: Path):
    settings = make_settings(tmp_path / "vision-recover.sqlite3")
    initialize_database(settings)
    repository = CameraRepository(settings)
    manager = CameraManager(settings, repository)
    engine = VisionEngine(settings, manager)

    camera_id = "cam_recover"

    try:
        with patch("backend.vision.engine.create_detector", return_value=FakeDetector()):
            engine.start_session(camera_id)
            time.sleep(0.3)

            error_status = engine.status(camera_id)
            assert error_status["status"] == "ERROR"

            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            frame_timestamp = datetime.now(timezone.utc)

            with patch.object(manager, "is_running", return_value=True), patch.object(
                manager,
                "latest_frame_snapshot",
                return_value=LatestFrameSnapshot(
                    frame=frame,
                    frame_at=frame_timestamp,
                    frame_id=1,
                    frames_received=1,
                    frames_replaced=0,
                ),
            ):
                time.sleep(0.5)

                recovered_status = engine.status(camera_id)
                assert recovered_status["status"] in {"RUNNING", "RECOVER", "STARTING"}
    finally:
        engine.shutdown()
        manager.shutdown()
