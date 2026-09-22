from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.config import Settings
from backend.operations.video_intelligence import CampexOperationalEngine
from backend.vision.models import BoundingBox, TrackedObject


def _settings() -> Settings:
    return Settings.from_env()


def _person(track_id: int, x: float, timestamp: datetime) -> TrackedObject:
    return TrackedObject(
        track_id=track_id,
        camera_id="CAM_TEST",
        class_name="person",
        confidence=0.9,
        bounding_box=BoundingBox(x1=x, y1=10, x2=x + 20, y2=50),
        timestamp=timestamp,
    )


def test_stationary_event_opens_and_closes_when_motion_resumes(monkeypatch):
    monkeypatch.setenv("STATIONARY_THRESHOLD_SECONDS", "2")
    monkeypatch.setenv("MOVEMENT_THRESHOLD", "0.05")
    engine = CampexOperationalEngine(_settings(), camera_id="CAM_TEST", frame_width=100, frame_height=100)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)

    engine.process([_person(1, 10, start)], start)
    engine.process([_person(1, 11, start + timedelta(seconds=1))], start + timedelta(seconds=1))
    engine.process([_person(1, 11, start + timedelta(seconds=3))], start + timedelta(seconds=3))
    engine.process([_person(1, 60, start + timedelta(seconds=4))], start + timedelta(seconds=4))

    stationary = [event for event in engine.events if event["event_type"] == "person_stationary"]
    moving = [event for event in engine.events if event["event_type"] == "person_moving"]
    assert len(stationary) == 1
    assert stationary[0]["ended_at"] is not None
    assert stationary[0]["duration_seconds"] == 3.0
    assert len(moving) == 1


def test_person_entry_exit_and_metrics_are_recorded():
    engine = CampexOperationalEngine(_settings(), camera_id="CAM_TEST", frame_width=100, frame_height=100)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)

    engine.process([_person(7, 10, start)], start)
    engine.process([], start + timedelta(seconds=5))

    result = engine.as_result({"name": "sample.mp4"})
    event_types = [event["event_type"] for event in result["events"]]
    assert "person_detected" in event_types
    assert "person_entered" in event_types
    assert "person_exited" in event_types
    assert result["metrics"]["people"]["detected"] == 1
    assert result["metrics"]["people"]["entries"] == 1
    assert result["metrics"]["people"]["exits"] == 1
