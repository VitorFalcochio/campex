from __future__ import annotations

from app.observation_engine import person_presence_observation, person_track_observation
from app.person_detection import CentroidTracker, Detection
from app.restricted_area import AreaPresenceTracker, RestrictedArea, AreaPoint, evaluate_area


def person(x1: int = 40, y1: int = 10, x2: int = 80, y2: int = 95, confidence: float = 0.9) -> Detection:
    return Detection(x1=x1, y1=y1, x2=x2, y2=y2, confidence=confidence, class_name="person")


def test_continuous_detection_keeps_present_track() -> None:
    tracker = CentroidTracker(grace_seconds=2.0, unknown_seconds=5.0)

    first = tracker.update([person()], now=100.0)[0]
    second = tracker.update([person(x1=42, x2=82, confidence=0.85)], now=100.5)[0]

    assert first.track_id == second.track_id
    state = tracker.track_states()[0]
    assert state.state == "PRESENT"
    assert state.consecutive_seen == 2
    assert state.duration_seen == 0.5


def test_one_detector_miss_then_seen_again_keeps_same_id_and_presence() -> None:
    tracker = CentroidTracker(grace_seconds=2.0, unknown_seconds=5.0)

    first = tracker.update([person()], now=100.0)[0]
    tracker.update([], now=101.0)
    recent = tracker.recent_detections()
    second = tracker.update([person(x1=43, x2=83)], now=101.5)[0]

    assert recent[0].track_id == first.track_id
    assert recent[0].confidence < first.confidence
    assert second.track_id == first.track_id
    assert tracker.track_states()[0].state == "PRESENT"


def test_short_miss_sequence_degrades_confidence_but_remains_present() -> None:
    tracker = CentroidTracker(grace_seconds=2.0, unknown_seconds=5.0)
    tracker.update([person(confidence=0.8)], now=100.0)

    tracker.update([], now=100.5)
    tracker.update([], now=101.0)

    state = tracker.track_states()[0]
    assert state.state == "PRESENT"
    assert 0 < state.temporal_confidence < 0.8
    assert state.seconds_since_last_seen == 1.0


def test_misses_beyond_grace_period_become_unknown_not_absent() -> None:
    tracker = CentroidTracker(grace_seconds=2.0, unknown_seconds=5.0)
    tracker.update([person()], now=100.0)

    tracker.update([], now=103.0)
    state = tracker.track_states()[0]
    observation = person_track_observation(camera_id="cam_a6", track=state).to_dict()

    assert state.state == "UNKNOWN"
    assert observation["value"] == "UNKNOWN"
    assert observation["data_quality"] == "insufficient_data"


def test_absent_requires_zone_health_and_persistent_absence() -> None:
    instant = person_presence_observation(camera_id="cam_a6", people_count=0).to_dict()
    confirmed = person_presence_observation(
        camera_id="cam_a6",
        people_count=0,
        absence_confirmed=True,
        confidence=0.7,
        zone_id="operator_zone_a6",
        metadata={"healthy_inference_seconds": 20},
    ).to_dict()

    assert instant["value"] == "UNKNOWN"
    assert confirmed["value"] == "ABSENT"
    assert confirmed["data_quality"] == "inferred"


def test_sensor_unavailable_never_emits_absent() -> None:
    observation = person_presence_observation(
        camera_id="cam_a6",
        people_count=0,
        inference_available=False,
        absence_confirmed=True,
    ).to_dict()

    assert observation["value"] == "UNKNOWN"
    assert observation["data_quality"] == "sensor_unavailable"


def test_restart_starts_without_tracks_and_unknown_presence() -> None:
    tracker = CentroidTracker(grace_seconds=2.0, unknown_seconds=5.0)
    tracker.update([person()], now=100.0)

    restarted = CentroidTracker(grace_seconds=2.0, unknown_seconds=5.0)
    observation = person_presence_observation(camera_id="cam_a6", people_count=len(restarted.active_tracks())).to_dict()

    assert restarted.track_states() == []
    assert observation["value"] == "UNKNOWN"


def test_person_leaving_zone_does_not_disappear_immediately() -> None:
    area = RestrictedArea(
        id="zone_a6",
        camera_id="cam_a6",
        nome="Zona A6",
        pontos=[
            AreaPoint(0.1, 0.1),
            AreaPoint(0.9, 0.1),
            AreaPoint(0.9, 1.0),
            AreaPoint(0.1, 1.0),
        ],
    )
    zone_tracker = AreaPresenceTracker(enter_frames=1, exit_frames=1, exit_grace_seconds=2.0)
    inside = person()
    inside.track_id = 7
    outside = person(x1=180, x2=210)
    outside.track_id = 7

    occupied, _ = evaluate_area(area, [inside], 220, 120, zone_tracker)
    still_occupied, _ = evaluate_area(area, [outside], 220, 120, zone_tracker)

    assert occupied.pessoas_dentro == 1
    assert still_occupied.pessoas_dentro == 1


def test_zone_presence_expires_after_grace_period() -> None:
    zone_tracker = AreaPresenceTracker(enter_frames=1, exit_frames=1, exit_grace_seconds=2.0)
    assert zone_tracker.update({8}, {8}, now=100.0) == {8}
    assert zone_tracker.update(set(), {8}, now=101.0) == {8}
    assert zone_tracker.update(set(), {8}, now=103.5) == set()


def test_two_tracks_keep_stable_ids_in_simple_sequence() -> None:
    tracker = CentroidTracker(grace_seconds=2.0, unknown_seconds=5.0)
    first = tracker.update([person(x1=10, x2=30), person(x1=150, x2=180)], now=100.0)
    second = tracker.update([person(x1=12, x2=32), person(x1=152, x2=182)], now=100.5)

    assert [item.track_id for item in second] == [item.track_id for item in first]


def test_person_track_observation_preserves_context() -> None:
    tracker = CentroidTracker(grace_seconds=2.0, unknown_seconds=5.0)
    tracker.update([person()], now=100.0)
    track = tracker.track_states()[0]

    observation = person_track_observation(
        camera_id="cam_a6",
        track=track,
        cliente_id="cli_1",
        unidade_id="unit_1",
        area_id="area_1",
        process_id="proc_1",
        asset_id="asset_1",
        zone_id="zone_operator",
    ).to_dict()

    assert observation["observation_type"] == "person_track"
    assert observation["value"] == "PRESENT"
    assert observation["cliente_id"] == "cli_1"
    assert observation["metadata"]["track_id"] == 1
    assert "bbox" in observation["metadata"]
