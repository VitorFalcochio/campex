from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import api
from app.auth import create_user
from app.database import connect
from app.models import criar_camera, criar_cliente, criar_unidade
from app.observation_engine import LightingStateDetector
from app.operational_read_model import ReadModelFilters, operational_change_anomalies, parse_datetime
from tests.test_operational_read_model import add_event, add_sample, make_context


def lighting_metadata(value: str, brightness: float, confidence: float = 0.9, data_quality: str = "observed") -> dict:
    return {
        "canonical_observations": [
            {
                "observation_type": "lighting_state",
                "value": value,
                "confidence": confidence,
                "data_quality": data_quality,
                "metadata": {"brightness": brightness},
            }
        ]
    }


def test_short_common_stoppage_is_not_anomaly_and_long_stoppage_is() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, _asset_id, camera_id = make_context()
    start = parse_datetime("2026-08-07T08:00:00+00:00")
    end = parse_datetime("2026-08-07T10:00:00+00:00")
    with temp_dir, connection:
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-06T08:00:00+00:00", end="2026-08-06T08:05:00+00:00", duration=300, event_uuid="evt-history")
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T08:05:00+00:00", end="2026-08-07T08:10:00+00:00", duration=300, event_uuid="evt-short")
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T09:00:00+00:00", end="2026-08-07T09:25:00+00:00", duration=1500, event_uuid="evt-long")
        payload = operational_change_anomalies(connection, ReadModelFilters(cliente_id=cliente_id, start=start, end=end), now=end)

    long_stops = [item for item in payload["anomalies"] if item["anomaly_type"] == "exceptionally_long_stoppage"]
    assert [item["event_refs"] for item in long_stops] == [["evt-long"]]
    assert "evt-short" not in {event_uuid for item in payload["anomalies"] for event_uuid in item["event_refs"]}


def test_recurrent_stoppages_and_long_absence_generate_temporal_anomalies() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, asset_id, camera_id = make_context()
    start = parse_datetime("2026-08-07T08:00:00+00:00")
    end = parse_datetime("2026-08-07T09:00:00+00:00")
    with temp_dir, connection:
        for index, minute in enumerate([0, 8, 16, 24, 32], start=1):
            add_event(
                connection,
                cliente_id,
                site_id,
                camera_id,
                "machine_stoppage",
                start=f"2026-08-07T08:{minute:02d}:00+00:00",
                end=f"2026-08-07T08:{minute + 1:02d}:00+00:00",
                duration=60,
                event_uuid=f"evt-recurrent-{index}",
            )
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T08:00:00+00:00", "ACTIVE", False)
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T08:18:00+00:00", "ACTIVE", True)
        payload = operational_change_anomalies(connection, ReadModelFilters(cliente_id=cliente_id, start=start, end=end), now=end)

    anomaly_types = {item["anomaly_type"] for item in payload["anomalies"]}
    assert "recurrent_stoppages_short_window" in anomaly_types
    assert "prolonged_operational_absence" in anomaly_types
    recurrent = next(item for item in payload["anomalies"] if item["anomaly_type"] == "recurrent_stoppages_short_window")
    assert len(recurrent["event_refs"]) == 5


def test_lighting_state_persistent_change_enters_timeline_and_black_frame_is_ignored() -> None:
    detector = LightingStateDetector(min_persistent_frames=3)
    assert detector.update([[180, 180], [180, 180]]).state == "ON"
    assert detector.update([[0, 0], [0, 0]]).state == "ON"
    assert detector.update([[0, 0], [0, 0]]).state == "ON"
    off_state = detector.update([[0, 0], [0, 0]])
    assert off_state.state == "OFF"

    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, asset_id, camera_id = make_context()
    start = parse_datetime("2026-08-07T05:40:00+00:00")
    end = parse_datetime("2026-08-07T07:10:00+00:00")
    with temp_dir, connection:
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T05:40:00+00:00", "ACTIVE", True, metadata=lighting_metadata("ON", 160))
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T05:48:00+00:00", "ACTIVE", True, metadata=lighting_metadata("OFF", 10))
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T06:55:00+00:00", "ACTIVE", True, metadata=lighting_metadata("ON", 150))
        payload = operational_change_anomalies(connection, ReadModelFilters(cliente_id=cliente_id, start=start, end=end), now=end)

    lighting_changes = [item for item in payload["changes"] if item["type"] == "lighting_state"]
    assert [item["new_state"] for item in lighting_changes] == ["ON", "OFF", "ON"]
    assert any(item["anomaly_type"] == "lighting_state_change" for item in payload["anomalies"])


def test_camera_offline_sets_lighting_unknown_and_excessive_unknown_is_preserved() -> None:
    detector = LightingStateDetector(min_persistent_frames=2)
    offline = detector.update([[200, 200], [200, 200]], camera_online=False)
    assert offline.state == "UNKNOWN"
    assert offline.data_quality == "sensor_unavailable"

    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, asset_id, camera_id = make_context()
    start = parse_datetime("2026-08-07T08:00:00+00:00")
    end = parse_datetime("2026-08-07T08:20:00+00:00")
    with temp_dir, connection:
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T08:00:00+00:00", "UNKNOWN", None, camera_online=False, inference_fps=0.0)
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T08:12:00+00:00", "ACTIVE", True)
        payload = operational_change_anomalies(connection, ReadModelFilters(cliente_id=cliente_id, start=start, end=end), now=end)

    assert any(item["anomaly_type"] == "excessive_unknown_period" for item in payload["anomalies"])
    assert any(item["anomaly_type"] == "prolonged_camera_offline" for item in payload["anomalies"])


def test_operational_activity_no_activity_is_supported_by_facts_and_no_cause() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, asset_id, camera_id = make_context()
    start = parse_datetime("2026-08-07T08:00:00+00:00")
    end = parse_datetime("2026-08-07T08:30:00+00:00")
    with temp_dir, connection:
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T08:00:00+00:00", "STOPPED", False, metadata=lighting_metadata("OFF", 8))
        payload = operational_change_anomalies(connection, ReadModelFilters(cliente_id=cliente_id, start=start, end=end), now=end)

    activity = [item for item in payload["operational_activity"] if item["new_state"] == "NO_ACTIVITY"]
    assert activity
    assert payload["no_cause_inferred"] is True
    assert "causa" not in str(payload["anomalies"]).lower()


def test_change_anomaly_endpoint_is_tenant_isolated() -> None:
    temp_dir, db_path, connection, cliente_id, site_id, _area_id, _process_id, asset_id, camera_id = make_context()
    with temp_dir:
        other_cliente = criar_cliente(connection, "Outro")
        other_site = criar_unidade(connection, other_cliente, "Outra unidade")
        other_camera = criar_camera(connection, other_site, "Camera outro", cliente_id=other_cliente)
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T08:00:00+00:00", "ACTIVE", True)
        add_sample(connection, other_cliente, other_site, other_camera, "asset-outro", "2026-08-07T08:00:00+00:00", "STOPPED", False)
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T08:10:00+00:00", end="2026-08-07T08:40:00+00:00", duration=1800, event_uuid="evt-tenant-ok")
        add_event(connection, other_cliente, other_site, other_camera, "machine_stoppage", start="2026-08-07T08:10:00+00:00", end="2026-08-07T08:40:00+00:00", duration=1800, event_uuid="evt-tenant-other")
        create_user(connection, "change@example.com", "senha", "admin_cliente", cliente_id)
        connection.close()

        def test_connect(_path=None):
            return connect(db_path)

        with patch("app.api.connect", test_connect):
            client = TestClient(api)
            client.post("/auth/login", json={"email": "change@example.com", "senha": "senha"})
            response = client.get(
                "/operations/change-anomalies",
                params={"start": "2026-08-07T08:00:00+00:00", "end": "2026-08-07T09:00:00+00:00"},
            )

    assert response.status_code == 200
    payload = response.json()
    refs = {event_uuid for item in payload["anomalies"] for event_uuid in item["event_refs"]}
    assert "evt-tenant-other" not in refs
    assert all(item["context"].get("camera_id") != other_camera for item in payload["changes"])
