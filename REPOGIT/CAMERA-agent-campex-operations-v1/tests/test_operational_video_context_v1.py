from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import api
from app.auth import create_user
from app.database import connect
from app.models import criar_camera, criar_cliente, criar_unidade
from app.operational_read_model import ReadModelFilters, parse_datetime, video_context_by_id, video_contexts
from tests.test_operational_change_anomaly_v1 import lighting_metadata
from tests.test_operational_read_model import add_event, add_sample, make_context


def _period():
    return parse_datetime("2026-08-07T08:00:00+00:00"), parse_datetime("2026-08-07T09:00:00+00:00")


def _context_by_trigger(payload: dict, trigger_type: str) -> dict:
    return next(item for item in payload["contexts"] if item["trigger"]["type"] == trigger_type)


def test_video_context_complete_before_transition_during_after_with_evidence() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, asset_id, camera_id = make_context()
    start, end = _period()
    with temp_dir, connection:
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T08:05:00+00:00", "ACTIVE", True)
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T08:10:00+00:00", "STOPPED", True)
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T08:20:00+00:00", "STOPPED", False)
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T08:35:00+00:00", "ACTIVE", True)
        event_id = add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T08:10:00+00:00", end="2026-08-07T08:30:00+00:00", duration=1200, event_uuid="evt-video-context")
        connection.execute("UPDATE eventos SET midia_path = ? WHERE id = ?", ("data/evidence/evt-video-context.jpg", event_id))
        connection.commit()
        payload = video_contexts(connection, ReadModelFilters(cliente_id=cliente_id, start=start, end=end), trigger_type="event_started", now=end)

    context = _context_by_trigger(payload, "event_started")
    assert set(context["phases"]) == {"before", "transition", "during", "after"}
    assert context["trigger"]["ref"] == "evt-video-context"
    assert context["evidence_refs"] == [{"type": "image", "path": "data/evidence/evt-video-context.jpg"}]
    assert context["cause_inferred"] is False
    assert context["events"]


def test_video_context_open_event_has_no_after_phase() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, asset_id, camera_id = make_context()
    start, end = _period()
    with temp_dir, connection:
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T08:05:00+00:00", "ACTIVE", True)
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T08:15:00+00:00", "STOPPED", True)
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T08:20:00+00:00", "STOPPED", False)
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T08:15:00+00:00", event_uuid="evt-open-context")
        payload = video_contexts(connection, ReadModelFilters(cliente_id=cliente_id, start=start, end=end), trigger_type="event_started", now=end)

    context = _context_by_trigger(payload, "event_started")
    assert "after" not in context["phases"]
    assert "during" in context["phases"]
    assert context["window"]["trigger_end"] is None


def test_video_context_marks_partial_when_data_is_missing_offline_or_unknown() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, asset_id, camera_id = make_context()
    start, end = _period()
    with temp_dir, connection:
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T08:30:00+00:00", "UNKNOWN", None, camera_online=False, inference_fps=0.0)
        payload = video_contexts(connection, ReadModelFilters(cliente_id=cliente_id, start=start, end=end), trigger_type="camera_status_change", now=end)

    context = _context_by_trigger(payload, "camera_status_change")
    assert context["data_quality"]["status"] == "partial"
    assert context["data_quality"]["has_unknown"] is True
    assert context["data_quality"]["gaps"]


def test_video_context_associates_anomaly_and_change_without_inferring_cause() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, _asset_id, camera_id = make_context()
    start, end = _period()
    with temp_dir, connection:
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T08:10:00+00:00", end="2026-08-07T08:40:00+00:00", duration=1800, event_uuid="evt-long-context")
        payload = video_contexts(connection, ReadModelFilters(cliente_id=cliente_id, start=start, end=end), trigger_type="exceptionally_long_stoppage", now=end)

    context = _context_by_trigger(payload, "exceptionally_long_stoppage")
    assert context["anomalies"][0]["anomaly_type"] == "exceptionally_long_stoppage"
    assert "evt-long-context" in {item["event_uuid"] for item in context["events"]}
    assert context["cause_inferred"] is False
    assert "causou" not in str(context).lower()


def test_video_context_evidence_outside_window_is_not_associated() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, _asset_id, camera_id = make_context()
    start, end = _period()
    with temp_dir, connection:
        inside_id = add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T08:10:00+00:00", end="2026-08-07T08:20:00+00:00", duration=600, event_uuid="evt-inside")
        outside_id = add_event(connection, cliente_id, site_id, camera_id, "workstation_unattended", start="2026-08-07T08:55:00+00:00", end="2026-08-07T08:56:00+00:00", duration=60, event_uuid="evt-outside")
        connection.execute("UPDATE eventos SET midia_path = ? WHERE id = ?", ("data/evidence/inside.jpg", inside_id))
        connection.execute("UPDATE eventos SET midia_path = ? WHERE id = ?", ("data/evidence/outside.jpg", outside_id))
        connection.commit()
        payload = video_contexts(connection, ReadModelFilters(cliente_id=cliente_id, start=start, end=end), trigger_type="event_started", before_seconds=60, after_seconds=60, now=end)

    context = next(item for item in payload["contexts"] if item["trigger"]["ref"] == "evt-inside")
    paths = {ref["path"] for ref in context["evidence_refs"]}
    assert paths == {"data/evidence/inside.jpg"}


def test_video_context_two_triggers_are_distinct_and_same_input_is_deterministic() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, asset_id, camera_id = make_context()
    start, end = _period()
    with temp_dir, connection:
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T08:00:00+00:00", "ACTIVE", True, metadata=lighting_metadata("ON", 160))
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T08:10:00+00:00", "STOPPED", True, metadata=lighting_metadata("OFF", 8))
        first = video_contexts(connection, ReadModelFilters(cliente_id=cliente_id, start=start, end=end), now=end)
        second = video_contexts(connection, ReadModelFilters(cliente_id=cliente_id, start=start, end=end), now=end)

    ids = [item["context_id"] for item in first["contexts"]]
    assert len(ids) == len(set(ids))
    assert any(item["trigger"]["type"] == "machine_activity_change" for item in first["contexts"])
    assert any(item["trigger"]["type"] == "lighting_state_change" for item in first["contexts"])
    assert first == second


def test_video_context_id_can_recover_same_context_without_period() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, asset_id, camera_id = make_context()
    start, end = _period()
    with temp_dir, connection:
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T08:00:00+00:00", "ACTIVE", True)
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T08:10:00+00:00", "STOPPED", False)
        listed = video_contexts(connection, ReadModelFilters(cliente_id=cliente_id, start=start, end=end), trigger_type="machine_activity_change", now=end)
        original = next(item for item in listed["contexts"] if item["trigger"]["type"] == "machine_activity_change" and item["trigger"]["timestamp"] == "2026-08-07T08:10:00+00:00")
        recovered = video_context_by_id(connection, ReadModelFilters(cliente_id=cliente_id), original["context_id"], now=end)

    assert recovered is not None
    assert recovered["context_id"] == original["context_id"]
    assert recovered["trigger"] == original["trigger"]
    assert recovered["phases"] == original["phases"]
    assert recovered["evidence_refs"] == original["evidence_refs"]


def test_video_context_unknown_id_returns_none() -> None:
    temp_dir, _db_path, connection, cliente_id, _site_id, _area_id, _process_id, _asset_id, _camera_id = make_context()
    with temp_dir, connection:
        assert video_context_by_id(connection, ReadModelFilters(cliente_id=cliente_id), "ctx-does-not-exist") is None


def test_video_context_api_filters_and_tenant_isolation() -> None:
    temp_dir, db_path, connection, cliente_id, site_id, _area_id, _process_id, asset_id, camera_id = make_context()
    with temp_dir:
        other_cliente = criar_cliente(connection, "Outro")
        other_site = criar_unidade(connection, other_cliente, "Outra")
        other_camera = criar_camera(connection, other_site, "Camera outro", cliente_id=other_cliente)
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T08:00:00+00:00", "ACTIVE", True)
        add_sample(connection, other_cliente, other_site, other_camera, "asset-other", "2026-08-07T08:00:00+00:00", "STOPPED", False)
        create_user(connection, "video-context@example.com", "senha", "admin_cliente", cliente_id)
        connection.close()

        def test_connect(_path=None):
            return connect(db_path)

        with patch("app.api.connect", test_connect):
            client = TestClient(api)
            client.post("/auth/login", json={"email": "video-context@example.com", "senha": "senha"})
            response = client.get(
                "/operations/video-contexts",
                params={
                    "start": "2026-08-07T08:00:00+00:00",
                    "end": "2026-08-07T09:00:00+00:00",
                    "trigger_type": "machine_activity_change",
                },
            )
            payload = response.json()
            context_id = payload["contexts"][0]["context_id"]
            detail = client.get(f"/operations/video-contexts/{context_id}")
            missing = client.get("/operations/video-contexts/ctx-missing")

    assert response.status_code == 200
    assert detail.status_code == 200
    assert missing.status_code == 404
    assert payload["count"] == 1
    assert all(item["camera_id"] != other_camera for item in payload["contexts"])
    assert detail.json()["context_id"] == context_id


def test_video_context_legacy_event_without_context_still_builds() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, _asset_id, camera_id = make_context()
    start, end = _period()
    with temp_dir, connection:
        event_id = add_event(connection, cliente_id, site_id, camera_id, "legacy_custom_event", start="2026-08-07T08:10:00+00:00", end="2026-08-07T08:11:00+00:00", duration=60, event_uuid="evt-legacy")
        connection.execute("UPDATE eventos SET area_context_id = NULL, process_id = NULL, asset_id = NULL WHERE id = ?", (event_id,))
        connection.commit()
        payload = video_contexts(connection, ReadModelFilters(cliente_id=cliente_id, start=start, end=end), trigger_type="event_started", now=end)

    context = _context_by_trigger(payload, "event_started")
    assert context["trigger"]["ref"] == "evt-legacy"
    assert context["camera_id"] == camera_id
    assert context["cause_inferred"] is False
