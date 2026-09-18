from __future__ import annotations

from app.observation_engine import (
    SPECIALIZED_MODEL_REQUIRED_CLASSES,
    SUPPORTED_VEHICLE_CLASSES,
    SafetyTemporalTracker,
    safety_observations_from_detections,
)
from app.person_detection import CentroidTracker, Detection, YOLO_CLASS_IDS


def detection(
    class_name: str,
    track_id: int,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    confidence: float = 0.9,
) -> Detection:
    return Detection(x1=x1, y1=y1, x2=x2, y2=y2, confidence=confidence, class_name=class_name, track_id=track_id)


def full_zone() -> dict[str, object]:
    return {
        "id": "zone_a6",
        "tipo": "work_area",
        "pontos": [
            {"x": 0.0, "y": 0.0},
            {"x": 1.0, "y": 0.0},
            {"x": 1.0, "y": 1.0},
            {"x": 0.0, "y": 1.0},
        ],
    }


def test_supported_vehicle_classes_are_generic_not_forklift() -> None:
    assert SUPPORTED_VEHICLE_CLASSES == {"bicycle", "car", "motorcycle", "bus", "truck"}
    assert "forklift" not in YOLO_CLASS_IDS
    assert "forklift" in SPECIALIZED_MODEL_REQUIRED_CLASSES


def test_tracker_keeps_person_and_vehicle_ids_separate_when_close() -> None:
    tracker = CentroidTracker(max_distance=80, grace_seconds=2.0, unknown_seconds=5.0)
    first = tracker.update(
        [
            Detection(10, 10, 40, 80, 0.9, class_name="person"),
            Detection(45, 12, 90, 82, 0.88, class_name="truck"),
        ],
        now=100.0,
    )
    second = tracker.update(
        [
            Detection(12, 10, 42, 80, 0.9, class_name="person"),
            Detection(47, 12, 92, 82, 0.88, class_name="truck"),
        ],
        now=100.5,
    )

    assert first[0].track_id == second[0].track_id
    assert first[1].track_id == second[1].track_id
    assert second[0].track_id != second[1].track_id


def test_person_and_vehicle_zone_occupancy_observations() -> None:
    tracker = SafetyTemporalTracker()
    observations = safety_observations_from_detections(
        camera_id="cam_a6",
        detections=[
            detection("person", 1, 20, 20, 50, 90),
            detection("truck", 2, 80, 20, 130, 90),
        ],
        tracker=tracker,
        frame_width=160,
        frame_height=120,
        zones=[full_zone()],
        cliente_id="cli_1",
        unidade_id="unit_1",
        now=100.0,
    )

    vehicle = next(item for item in observations if item["observation_type"] == "vehicle_presence")
    zone = next(item for item in observations if item["observation_type"] == "zone_occupancy")

    assert vehicle["value"] == "PRESENT"
    assert vehicle["metadata"]["vehicle_classes"] == ["truck"]
    assert vehicle["metadata"]["track_ids"] == [2]
    assert zone["value"] == "OCCUPIED"
    assert zone["metadata"]["people_track_ids"] == [1]
    assert zone["metadata"]["vehicle_track_ids"] == [2]
    assert zone["cliente_id"] == "cli_1"


def test_person_vehicle_close_frame_is_candidate_not_strong_conclusion() -> None:
    tracker = SafetyTemporalTracker(proximity_min_seconds=2.0)
    observations = safety_observations_from_detections(
        camera_id="cam_a6",
        detections=[
            detection("person", 1, 20, 20, 60, 90),
            detection("car", 2, 62, 20, 120, 90),
        ],
        tracker=tracker,
        frame_width=160,
        frame_height=120,
        zones=[],
        now=100.0,
    )
    proximity = next(item for item in observations if item["observation_type"] == "person_vehicle_proximity")

    assert proximity["value"] == "CANDIDATE"
    assert proximity["data_quality"] == "inferred"
    assert proximity["metadata"]["vehicle_class"] == "car"
    assert proximity["metadata"]["distance_metric_type"] == "normalized_bbox_gap"


def test_persistent_person_vehicle_proximity_becomes_near_observation() -> None:
    tracker = SafetyTemporalTracker(proximity_min_seconds=1.0)
    args = dict(
        camera_id="cam_a6",
        detections=[detection("person", 1, 20, 20, 60, 90), detection("truck", 2, 62, 20, 120, 90)],
        tracker=tracker,
        frame_width=160,
        frame_height=120,
        zones=[],
    )
    safety_observations_from_detections(**args, now=100.0)
    observations = safety_observations_from_detections(**args, now=101.2)
    proximity = next(item for item in observations if item["observation_type"] == "person_vehicle_proximity")

    assert proximity["value"] == "NEAR"
    assert proximity["confidence"] > 0
    assert proximity["metadata"]["seconds_persistent"] >= 1.0


def test_detector_short_loss_respects_grace_for_vehicle_zone_occupancy() -> None:
    tracker = SafetyTemporalTracker(grace_seconds=2.0)
    safety_observations_from_detections(
        camera_id="cam_a6",
        detections=[detection("truck", 2, 80, 20, 130, 90)],
        tracker=tracker,
        frame_width=160,
        frame_height=120,
        zones=[full_zone()],
        now=100.0,
    )
    observations = safety_observations_from_detections(
        camera_id="cam_a6",
        detections=[],
        tracker=tracker,
        frame_width=160,
        frame_height=120,
        zones=[full_zone()],
        now=101.0,
    )
    zone = next(item for item in observations if item["observation_type"] == "zone_occupancy")

    assert zone["value"] == "OCCUPIED"
    assert zone["metadata"]["vehicle_track_ids"] == [2]


def test_sensor_unavailable_returns_unknown() -> None:
    observations = safety_observations_from_detections(
        camera_id="cam_a6",
        detections=[],
        tracker=SafetyTemporalTracker(),
        frame_width=160,
        frame_height=120,
        zones=[full_zone()],
        camera_online=False,
        inference_available=True,
    )

    assert {item["value"] for item in observations} == {"UNKNOWN"}
    assert {item["data_quality"] for item in observations} == {"sensor_unavailable"}


def test_restart_starts_proximity_unknown() -> None:
    restarted = SafetyTemporalTracker(proximity_min_seconds=1.0)
    observations = safety_observations_from_detections(
        camera_id="cam_a6",
        detections=[],
        tracker=restarted,
        frame_width=160,
        frame_height=120,
        zones=[],
        now=200.0,
    )
    vehicle = next(item for item in observations if item["observation_type"] == "vehicle_presence")

    assert vehicle["value"] == "UNKNOWN"


def test_two_tenants_do_not_share_safety_track_memory() -> None:
    tracker_a = SafetyTemporalTracker()
    tracker_b = SafetyTemporalTracker()
    safety_observations_from_detections(
        camera_id="cam_a",
        detections=[detection("truck", 2, 80, 20, 130, 90)],
        tracker=tracker_a,
        frame_width=160,
        frame_height=120,
        zones=[full_zone()],
        cliente_id="tenant_a",
        now=100.0,
    )
    observations_b = safety_observations_from_detections(
        camera_id="cam_b",
        detections=[],
        tracker=tracker_b,
        frame_width=160,
        frame_height=120,
        zones=[full_zone()],
        cliente_id="tenant_b",
        now=101.0,
    )
    zone_b = next(item for item in observations_b if item["observation_type"] == "zone_occupancy")

    assert zone_b["cliente_id"] == "tenant_b"
    assert zone_b["metadata"]["vehicle_track_ids"] == []


def test_generic_vehicle_is_not_converted_to_forklift() -> None:
    observation = safety_observations_from_detections(
        camera_id="cam_a6",
        detections=[detection("truck", 2, 80, 20, 130, 90)],
        tracker=SafetyTemporalTracker(),
        frame_width=160,
        frame_height=120,
        zones=[],
        now=100.0,
    )[0]

    assert observation["metadata"]["vehicle_classes"] == ["truck"]
    assert "forklift" not in observation["metadata"]["vehicle_classes"]
    assert observation["metadata"]["forklift_detection"] == "SPECIALIZED_MODEL_REQUIRED"


def test_safety_observations_do_not_create_events() -> None:
    tracker = SafetyTemporalTracker(proximity_min_seconds=0.1)
    observations = safety_observations_from_detections(
        camera_id="cam_a6",
        detections=[detection("person", 1, 20, 20, 60, 90), detection("truck", 2, 62, 20, 120, 90)],
        tracker=tracker,
        frame_width=160,
        frame_height=120,
        zones=[full_zone()],
        now=100.0,
    )

    assert observations
    assert all("event_id" not in item for item in observations)
