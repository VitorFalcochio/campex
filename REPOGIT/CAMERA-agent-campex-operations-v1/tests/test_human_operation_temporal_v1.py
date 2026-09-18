from __future__ import annotations

from app.observation_engine import HumanPresenceTemporalTracker, ObservationEngine
from app.person_detection import YOLO_CLASS_IDS


def test_person_stays_in_zone_present_duration_increases() -> None:
    tracker = HumanPresenceTemporalTracker(grace_seconds=2.0, absence_tolerance_seconds=5.0)

    first = tracker.update(
        zone_id="operator_a6",
        valid_tracks_count=1,
        camera_online=True,
        inference_available=True,
        zone_configured=True,
        track_confidence=0.9,
        now=100.0,
    )
    second = tracker.update(
        zone_id="operator_a6",
        valid_tracks_count=1,
        camera_online=True,
        inference_available=True,
        zone_configured=True,
        track_confidence=0.85,
        now=104.0,
    )

    assert first.state == "PRESENT"
    assert second.state == "PRESENT"
    assert second.seconds_present == 4.0
    assert second.seconds_in_state(104.0) == 4.0


def test_short_yolo_failures_do_not_generate_absence() -> None:
    tracker = HumanPresenceTemporalTracker(grace_seconds=2.0, absence_tolerance_seconds=5.0)
    tracker.update(zone_id="operator_a6", valid_tracks_count=1, camera_online=True, inference_available=True, zone_configured=True, track_confidence=0.9, now=100.0)

    state = tracker.update(zone_id="operator_a6", valid_tracks_count=0, camera_online=True, inference_available=True, zone_configured=True, now=101.0)

    assert state.state == "PRESENT"
    assert 0 < state.confidence < 0.9
    assert state.absence_started_at is None


def test_track_expired_becomes_unknown_before_absent() -> None:
    tracker = HumanPresenceTemporalTracker(grace_seconds=2.0, absence_tolerance_seconds=5.0)
    tracker.update(zone_id="operator_a6", valid_tracks_count=1, camera_online=True, inference_available=True, zone_configured=True, now=100.0)

    state = tracker.update(zone_id="operator_a6", valid_tracks_count=0, camera_online=True, inference_available=True, zone_configured=True, now=103.0)

    assert state.state == "UNKNOWN"
    assert state.absence_started_at == 103.0


def test_persistent_absence_after_tolerance_becomes_absent() -> None:
    tracker = HumanPresenceTemporalTracker(grace_seconds=2.0, absence_tolerance_seconds=5.0)
    tracker.update(zone_id="operator_a6", valid_tracks_count=1, camera_online=True, inference_available=True, zone_configured=True, now=100.0)
    tracker.update(zone_id="operator_a6", valid_tracks_count=0, camera_online=True, inference_available=True, zone_configured=True, now=103.0)

    state = tracker.update(zone_id="operator_a6", valid_tracks_count=0, camera_online=True, inference_available=True, zone_configured=True, now=108.2)

    assert state.state == "ABSENT"
    assert state.seconds_absent >= 0
    assert state.transitions >= 3


def test_person_returns_from_absent_to_present() -> None:
    tracker = HumanPresenceTemporalTracker(grace_seconds=1.0, absence_tolerance_seconds=2.0)
    tracker.update(zone_id="operator_a6", valid_tracks_count=1, camera_online=True, inference_available=True, zone_configured=True, now=100.0)
    tracker.update(zone_id="operator_a6", valid_tracks_count=0, camera_online=True, inference_available=True, zone_configured=True, now=102.0)
    tracker.update(zone_id="operator_a6", valid_tracks_count=0, camera_online=True, inference_available=True, zone_configured=True, now=104.1)

    state = tracker.update(zone_id="operator_a6", valid_tracks_count=1, camera_online=True, inference_available=True, zone_configured=True, now=105.0)

    assert state.state == "PRESENT"
    assert state.absence_started_at is None
    assert state.transitions >= 4


def test_camera_offline_during_absence_is_unknown_not_absent() -> None:
    tracker = HumanPresenceTemporalTracker(grace_seconds=1.0, absence_tolerance_seconds=2.0)
    tracker.update(zone_id="operator_a6", valid_tracks_count=1, camera_online=True, inference_available=True, zone_configured=True, now=100.0)

    state = tracker.update(zone_id="operator_a6", valid_tracks_count=0, camera_online=False, inference_available=True, zone_configured=True, now=104.0)

    assert state.state == "UNKNOWN"
    assert state.confidence == 0.0


def test_inference_unavailable_is_unknown() -> None:
    tracker = HumanPresenceTemporalTracker(grace_seconds=1.0, absence_tolerance_seconds=2.0)
    state = tracker.update(zone_id="operator_a6", valid_tracks_count=0, camera_online=True, inference_available=False, zone_configured=True, now=100.0)

    assert state.state == "UNKNOWN"
    assert state.confidence == 0.0


def test_restart_starts_unknown() -> None:
    tracker = HumanPresenceTemporalTracker(grace_seconds=1.0, absence_tolerance_seconds=2.0)
    tracker.update(zone_id="operator_a6", valid_tracks_count=1, camera_online=True, inference_available=True, zone_configured=True, now=100.0)

    restarted = HumanPresenceTemporalTracker(grace_seconds=1.0, absence_tolerance_seconds=2.0)
    state = restarted.update(zone_id="operator_a6", valid_tracks_count=0, camera_online=True, inference_available=True, zone_configured=True, now=200.0)

    assert state.state == "UNKNOWN"
    assert state.last_presence_at is None


def test_two_people_keep_zone_present_while_one_valid_remains() -> None:
    tracker = HumanPresenceTemporalTracker(grace_seconds=1.0, absence_tolerance_seconds=2.0)
    tracker.update(zone_id="operator_a6", valid_tracks_count=2, camera_online=True, inference_available=True, zone_configured=True, now=100.0)

    state = tracker.update(zone_id="operator_a6", valid_tracks_count=1, camera_online=True, inference_available=True, zone_configured=True, now=102.0)

    assert state.state == "PRESENT"
    assert state.valid_tracks_count == 1


def test_observation_engine_emits_human_presence_with_context_and_durations() -> None:
    engine = ObservationEngine("cam_a6")

    observation = engine.build(
        machine_id="mach_a6",
        machine_state="UNKNOWN",
        machine_activity_score=None,
        machine_confidence=0.8,
        operator_present=True,
        zone_states=[{"id": "zone_operator_a6", "tipo": "operator_zone", "pessoas_dentro": 1}],
        cliente_id="cli_1",
        unidade_id="unit_1",
        area_id="area_1",
        process_id="proc_1",
        asset_id="asset_1",
        camera_online=True,
        inference_available=True,
        operator_absence_tolerance_seconds=5.0,
    )
    presence = next(item for item in observation["observations"] if item["observation_type"] == "person_presence")

    assert presence["value"] == "PRESENT"
    assert presence["cliente_id"] == "cli_1"
    assert presence["zone_id"] == "zone_operator_a6"
    assert presence["metadata"]["valid_tracks_count"] == 1
    assert "seconds_in_state" in presence["metadata"]


def test_phone_candidate_remains_experimental_without_detector_class() -> None:
    assert "cell phone" not in YOLO_CLASS_IDS
