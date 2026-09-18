from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.observation_engine import (
    Observation,
    ObservationEngine,
    machine_activity_observation,
    person_presence_observation,
    vehicle_presence_observation,
    zone_occupancy_observation,
)
from app.person_detection import Detection


def test_machine_activity_observation_active_stopped_and_unknown() -> None:
    active = machine_activity_observation(
        camera_id="cam_a6",
        machine_id="mon_a6",
        state="ACTIVE",
        activity_score=31.2,
        confidence=0.82,
    )
    stopped = machine_activity_observation(
        camera_id="cam_a6",
        machine_id="mon_a6",
        state="STOPPED",
        activity_score=2.4,
        confidence=0.91,
    )
    unknown = machine_activity_observation(
        camera_id="cam_a6",
        machine_id="mon_a6",
        state="NOT_READY",
        activity_score=None,
        confidence=0.0,
    )

    assert active.to_dict()["value"] == "ACTIVE"
    assert stopped.to_dict()["value"] == "STOPPED"
    assert unknown.to_dict()["value"] == "UNKNOWN"
    assert unknown.to_dict()["data_quality"] == "insufficient_data"


def test_person_detection_present_creates_observed_presence() -> None:
    observation = person_presence_observation(
        camera_id="cam_a6",
        detections=[
            Detection(
                x1=0.1,
                y1=0.1,
                x2=0.4,
                y2=0.7,
                confidence=0.77,
                track_id=12,
            )
        ],
    ).to_dict()

    assert observation["observation_type"] == "person_presence"
    assert observation["value"] == "PRESENT"
    assert observation["confidence"] == 0.77
    assert observation["data_quality"] == "observed"
    assert observation["metadata"]["people_count"] == 1
    assert observation["metadata"]["track_ids"] == [12]


def test_zero_people_does_not_become_absent_in_observation_contract() -> None:
    observation = person_presence_observation(camera_id="cam_a6", people_count=0).to_dict()

    assert observation["value"] == "UNKNOWN"
    assert observation["data_quality"] == "insufficient_data"


def test_absent_requires_explicit_confirmation() -> None:
    observation = person_presence_observation(
        camera_id="cam_a6",
        people_count=0,
        absence_confirmed=True,
        confidence=0.72,
    ).to_dict()

    assert observation["value"] == "ABSENT"
    assert observation["data_quality"] == "inferred"
    assert observation["confidence"] == 0.72


def test_sensor_unavailable_returns_unknown_quality() -> None:
    observation = person_presence_observation(
        camera_id="cam_a6",
        people_count=0,
        inference_available=False,
    ).to_dict()

    assert observation["value"] == "UNKNOWN"
    assert observation["confidence"] == 0.0
    assert observation["data_quality"] == "sensor_unavailable"


def test_zone_occupancy_observation() -> None:
    occupied = zone_occupancy_observation(
        camera_id="cam_a6",
        zone_id="zone_operator",
        zone_type="operator_zone",
        people_count=2,
        confidence=0.9,
    ).to_dict()
    empty = zone_occupancy_observation(
        camera_id="cam_a6",
        zone_id="zone_operator",
        zone_type="operator_zone",
        people_count=0,
        confidence=0.9,
    ).to_dict()

    assert occupied["value"] == "OCCUPIED"
    assert occupied["metadata"]["people_count"] == 2
    assert empty["value"] == "EMPTY"
    assert empty["data_quality"] == "observed"


def test_vehicle_presence_candidate_uses_current_detector_classes_only() -> None:
    observation = vehicle_presence_observation(
        camera_id="cam_a6",
        source="person_detector",
        vehicle_count=1,
    ).to_dict()

    assert observation["observation_type"] == "vehicle_presence"
    assert observation["value"] == "PRESENT"
    assert observation["metadata"]["vehicle_count"] == 1


def test_invalid_confidence_is_rejected() -> None:
    with pytest.raises(ValueError, match="confidence"):
        machine_activity_observation(
            camera_id="cam_a6",
            machine_id="mon_a6",
            state="ACTIVE",
            activity_score=10,
            confidence=1.4,
        )


def test_timestamp_must_be_timezone_aware() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        Observation(
            observation_type="machine_activity",
            camera_id="cam_a6",
            value="ACTIVE",
            confidence=0.8,
            source="test",
            data_quality="observed",
            timestamp=datetime(2026, 8, 12, 12, 0, 0),
        )

    observation = Observation(
        observation_type="machine_activity",
        camera_id="cam_a6",
        value="ACTIVE",
        confidence=0.8,
        source="test",
        data_quality="observed",
        timestamp=datetime(2026, 8, 12, 12, 0, 0, tzinfo=timezone.utc),
    ).to_dict()
    assert observation["timestamp"].endswith("+00:00")


def test_context_and_tenant_are_preserved() -> None:
    observation = machine_activity_observation(
        camera_id="cam_a6",
        machine_id="mon_a6",
        state="STOPPED",
        activity_score=1.1,
        confidence=0.9,
        cliente_id="cli_1",
        unidade_id="unit_1",
        area_id="area_corte",
        process_id="proc_a6",
        asset_id="asset_a6",
    ).to_dict()

    assert observation["cliente_id"] == "cli_1"
    assert observation["unidade_id"] == "unit_1"
    assert observation["area_id"] == "area_corte"
    assert observation["process_id"] == "proc_a6"
    assert observation["asset_id"] == "asset_a6"
    assert observation["machine_id"] == "mon_a6"


def test_observation_payload_sanitizes_secrets() -> None:
    observation = machine_activity_observation(
        camera_id="cam_a6",
        machine_id="mon_a6",
        state="ACTIVE",
        activity_score=10,
        confidence=0.9,
        metadata={
            "rtsp_url": "rtsp://camera.local/live",
            "nested": {"smtp_password": "value-to-redact"},
            "safe": "ok",
        },
    ).to_dict()

    assert observation["metadata"]["rtsp_url"] == "[redacted]"
    assert observation["metadata"]["nested"]["smtp_password"] == "[redacted]"
    assert observation["metadata"]["safe"] == "ok"
    assert "camera.local" not in str(observation)


def test_legacy_observation_engine_keeps_existing_fields_and_adds_contract() -> None:
    engine = ObservationEngine("cam_1")

    observation = engine.build(
        machine_id="mach_1",
        machine_state="ACTIVE",
        machine_activity_score=28.5,
        machine_confidence=0.87,
        operator_present=True,
        zone_states=[{"id": "zone_1", "tipo": "workstation", "pessoas_dentro": 1}],
        cliente_id="cli_1",
        unidade_id="unit_1",
        area_id="area_1",
        process_id="proc_1",
        asset_id="asset_1",
    )

    assert observation["camera_id"] == "cam_1"
    assert observation["machine_id"] == "mach_1"
    assert observation["machine_state"] == "ACTIVE"
    assert observation["people_in_operator_zone"] == 1
    assert "seconds_in_machine_state" in observation
    assert {item["observation_type"] for item in observation["observations"]} == {
        "machine_activity",
        "person_presence",
        "zone_occupancy",
    }
    assert observation["observations"][0]["cliente_id"] == "cli_1"
