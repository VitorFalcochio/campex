from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import api
from app.auth import create_user
from app.database import connect, init_db
from app.models import criar_camera, criar_cliente, criar_unidade, obter_evento, registrar_evento, registrar_operational_sample
from app.operational_context import criar_operational_area, criar_operational_asset, criar_operational_process
from app.operational_read_model import ReadModelFilters, comparison, current_operation, daily_report, intelligence, losses, operational_data, operational_timeline, parse_datetime, period_summary


NOW = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)
START = parse_datetime("2026-08-07T08:00:00+00:00")
END = parse_datetime("2026-08-07T12:00:00+00:00")


def make_context():
    temp_dir = tempfile.TemporaryDirectory()
    db_path = Path(temp_dir.name) / "read-model.sqlite3"
    connection = connect(db_path)
    init_db(connection)
    cliente_id = criar_cliente(connection, "Cliente")
    site_id = criar_unidade(connection, cliente_id, "Fabrica")
    area_id = criar_operational_area(connection, cliente_id=cliente_id, unidade_id=site_id, nome="Corte")
    process_id = criar_operational_process(connection, cliente_id=cliente_id, unidade_id=site_id, area_id=area_id, nome="Linha A6")
    asset_id = criar_operational_asset(connection, cliente_id=cliente_id, unidade_id=site_id, area_id=area_id, process_id=process_id, nome="A6")
    camera_id = criar_camera(connection, site_id, "Camera A6", cliente_id=cliente_id, area_context_id=area_id, process_id=process_id, asset_id=asset_id)
    return temp_dir, db_path, connection, cliente_id, site_id, area_id, process_id, asset_id, camera_id


def add_event(
    connection,
    cliente_id: str,
    site_id: str,
    camera_id: str,
    tipo: str,
    *,
    start: str,
    end: str | None = None,
    duration: float | None = None,
    event_uuid: str,
    workflow_status: str = "new",
    confirmed_cause: str | None = None,
    action_taken: str | None = None,
) -> str:
    event_id = registrar_evento(
        connection,
        cliente_id,
        site_id,
        camera_id,
        tipo,
        inicio=start,
        fim=end,
        duracao=duration,
        event_uuid=event_uuid,
    )
    connection.execute(
        """
        UPDATE eventos
        SET status = ?,
            workflow_status = ?,
            confirmed_cause = ?,
            action_taken = ?
        WHERE id = ?
        """,
        ("closed" if end else "open", workflow_status, confirmed_cause, action_taken, event_id),
    )
    connection.commit()
    return event_id


def add_sample(
    connection,
    cliente_id: str,
    site_id: str,
    camera_id: str,
    machine_id: str,
    at: str,
    machine_state: str | None,
    operator_present: bool | None,
    *,
    camera_online: bool = True,
    inference_fps: float | None = 5.0,
    metadata: dict | None = None,
) -> None:
    registrar_operational_sample(
        connection,
        sample_uuid=f"sample-{at}-{machine_state}-{operator_present}".replace(":", "").replace("+", ""),
        tenant_id=cliente_id,
        unit_id=site_id,
        camera_id=camera_id,
        machine_id=machine_id,
        machine_state=machine_state,
        operator_present=operator_present,
        activity_score=10.0 if machine_state == "ACTIVE" else 1.0 if machine_state == "STOPPED" else None,
        confidence=0.9 if machine_state in {"ACTIVE", "STOPPED"} else 0.0,
        capture_fps=15.0 if camera_online else 0.0,
        inference_fps=inference_fps,
        frames_analyzed=10 if inference_fps else 0,
        camera_online=camera_online,
        sample_at=at,
        metadata=metadata or {"people_count": 1 if operator_present else 0},
    )


def test_summary_separates_families_unknown_and_traceability() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, area_id, process_id, asset_id, camera_id = make_context()
    with temp_dir, connection:
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T09:00:00+00:00", end="2026-08-07T09:10:00+00:00", duration=600, event_uuid="evt-int-1")
        add_event(connection, cliente_id, site_id, camera_id, "workstation_unattended", start="2026-08-07T10:00:00+00:00", end="2026-08-07T10:05:00+00:00", duration=300, event_uuid="evt-abs-1")
        add_event(connection, cliente_id, site_id, camera_id, "restricted_area_occupied", start="2026-08-07T11:00:00+00:00", end="2026-08-07T11:02:00+00:00", duration=120, event_uuid="evt-unk-1")
        summary = period_summary(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=END), now=NOW)

    families = {item["key"]: item for item in summary["events_by_family"]}
    assert families["interruption"]["total_duration_seconds"] == 600
    assert families["absence"]["total_duration_seconds"] == 300
    assert families["unknown"]["total_duration_seconds"] == 120
    assert set(summary["event_uuids"]) == {"evt-int-1", "evt-abs-1", "evt-unk-1"}
    assert summary["events_pending_human_analysis"]["total"] == 3
    assert area_id in {item["key"] for item in summary["events_by_area"]}
    assert process_id in {item["key"] for item in summary["events_by_process"]}
    assert asset_id in {item["key"] for item in summary["events_by_asset"]}


def test_open_event_duration_uses_now_without_modifying_record() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, _asset_id, camera_id = make_context()
    with temp_dir, connection:
        event_id = add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T11:30:00+00:00", event_uuid="evt-open-1")
        current = current_operation(connection, ReadModelFilters(cliente_id=cliente_id), now=NOW)
        event_after = obter_evento(connection, event_id)

    assert current["total_open_events"] == 1
    assert current["open_events"][0]["current_duration_seconds"] == 1800
    assert event_after["fim"] is None
    assert event_after["duracao"] is None


def test_filters_by_site_area_process_asset_family_and_workflow() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, area_id, process_id, asset_id, camera_id = make_context()
    with temp_dir, connection:
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T09:00:00+00:00", end="2026-08-07T09:10:00+00:00", duration=600, event_uuid="evt-filter-1", workflow_status="acknowledged")
        filters = ReadModelFilters(
            cliente_id=cliente_id,
            site_id=site_id,
            area_context_id=area_id,
            process_id=process_id,
            asset_id=asset_id,
            event_family="interruption",
            workflow_status="acknowledged",
            start=START,
            end=END,
        )
        summary = period_summary(connection, filters, now=NOW)

    assert summary["total_events"] == 1
    assert summary["event_uuids"] == ["evt-filter-1"]


def test_losses_rank_by_asset_and_exclude_unknown() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, asset_id, camera_id = make_context()
    with temp_dir, connection:
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T09:00:00+00:00", end="2026-08-07T09:10:00+00:00", duration=600, event_uuid="evt-loss-1")
        add_event(connection, cliente_id, site_id, camera_id, "restricted_area_occupied", start="2026-08-07T10:00:00+00:00", end="2026-08-07T10:10:00+00:00", duration=600, event_uuid="evt-unknown-1")
        ranked = losses(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=END), now=NOW)

    assert ranked["by_asset"][0]["key"] == asset_id
    assert ranked["by_asset"][0]["event_uuids"] == ["evt-loss-1"]
    assert ranked["excluded_unknown_or_non_loss_event_uuids"] == ["evt-unknown-1"]


def test_confirmed_causes_and_actions_are_human_only() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, _asset_id, camera_id = make_context()
    with temp_dir, connection:
        add_event(
            connection,
            cliente_id,
            site_id,
            camera_id,
            "machine_stoppage",
            start="2026-08-07T09:00:00+00:00",
            end="2026-08-07T09:20:00+00:00",
            duration=1200,
            event_uuid="evt-cause-1",
            confirmed_cause="falta de material",
            action_taken="abastecimento solicitado",
        )
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T10:00:00+00:00", end="2026-08-07T10:10:00+00:00", duration=600, event_uuid="evt-no-cause-1")
        summary = period_summary(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=END), now=NOW)

    causes = {item["key"]: item for item in summary["confirmed_causes"]}
    assert causes["falta de material"]["total_duration_seconds"] == 1200
    assert causes["causa não informada"]["total_duration_seconds"] == 600
    assert summary["actions_taken"][0]["key"] == "abastecimento solicitado"


def test_comparison_handles_zero_previous_period_safely() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, _asset_id, camera_id = make_context()
    with temp_dir, connection:
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T09:00:00+00:00", end="2026-08-07T09:10:00+00:00", duration=600, event_uuid="evt-current-1")
        result = comparison(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=END), now=NOW)

    assert result["metrics"]["total_events"]["current"] == 1
    assert result["metrics"]["total_events"]["previous"] == 0
    assert result["metrics"]["total_events"]["percent_change"] is None
    assert result["current_event_uuids"] == ["evt-current-1"]
    assert result["previous_event_uuids"] == []


def test_workflow_status_does_not_change_physical_duration() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, _asset_id, camera_id = make_context()
    with temp_dir, connection:
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T09:00:00+00:00", end="2026-08-07T09:10:00+00:00", duration=600, event_uuid="evt-workflow-1", workflow_status="resolved")
        new_only = period_summary(connection, ReadModelFilters(cliente_id=cliente_id, workflow_status="new", start=START, end=END), now=NOW)
        resolved = period_summary(connection, ReadModelFilters(cliente_id=cliente_id, workflow_status="resolved", start=START, end=END), now=NOW)

    assert new_only["total_events"] == 0
    assert resolved["total_duration_seconds"] == 600


def test_coverage_unknown_when_no_samples_and_observed_when_samples_exist() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, _asset_id, camera_id = make_context()
    with temp_dir, connection:
        empty = period_summary(connection, ReadModelFilters(cliente_id=cliente_id, camera_id=camera_id, start=START, end=END), now=NOW)
        registrar_operational_sample(
            connection,
            sample_uuid="sample-read-1",
            tenant_id=cliente_id,
            unit_id=site_id,
            camera_id=camera_id,
            machine_id="machine_a6",
            machine_state="ACTIVE",
            operator_present=True,
            activity_score=10,
            confidence=0.9,
            capture_fps=15,
            inference_fps=5,
            frames_analyzed=100,
            camera_online=True,
            sample_at="2026-08-07T09:00:00+00:00",
        )
        observed = period_summary(connection, ReadModelFilters(cliente_id=cliente_id, camera_id=camera_id, start=START, end=END), now=NOW)

    assert empty["coverage"]["status"] == "unknown"
    assert observed["coverage"]["sample_count"] == 1
    assert observed["coverage"]["status"] == "partial"


def test_read_model_api_summary_endpoint() -> None:
    temp_dir, db_path, connection, cliente_id, site_id, _area_id, _process_id, _asset_id, camera_id = make_context()
    with temp_dir:
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T09:00:00+00:00", end="2026-08-07T09:10:00+00:00", duration=600, event_uuid="evt-api-1")
        create_user(connection, "gestor@example.com", "senha", "admin_cliente", cliente_id)
        connection.close()

        def test_connect(_path=None):
            return connect(db_path)

        with patch("app.api.connect", test_connect):
            client = TestClient(api)
            client.post("/auth/login", json={"email": "gestor@example.com", "senha": "senha"})
            response = client.get("/operations/read-model/summary", params={"start": "2026-08-07T08:00:00+00:00", "end": "2026-08-07T12:00:00+00:00", "camera_id": camera_id})

    assert response.status_code == 200
    assert response.json()["event_uuids"] == ["evt-api-1"]


def test_intelligence_excludes_unknown_from_insights_and_keeps_quality_note() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, _asset_id, camera_id = make_context()
    with temp_dir, connection:
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T09:00:00+00:00", end="2026-08-07T09:20:00+00:00", duration=1200, event_uuid="evt-intel-known")
        add_event(connection, cliente_id, site_id, camera_id, "restricted_area_occupied", start="2026-08-07T10:00:00+00:00", end="2026-08-07T10:15:00+00:00", duration=900, event_uuid="evt-intel-unknown")
        payload = intelligence(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=END), now=NOW)

    insight_uuids = {uuid for item in [*payload["attention"], *payload["patterns"]] for uuid in item["event_uuids"]}
    assert "evt-intel-known" in insight_uuids
    assert "evt-intel-unknown" not in insight_uuids
    assert payload["data_quality"]["unknown_events"] == 1
    assert payload["data_quality"]["unknown_event_uuids"] == ["evt-intel-unknown"]


def test_intelligence_uses_only_confirmed_cause_not_observed_context() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, _asset_id, camera_id = make_context()
    with temp_dir, connection:
        event_id = add_event(
            connection,
            cliente_id,
            site_id,
            camera_id,
            "machine_stoppage",
            start="2026-08-07T09:00:00+00:00",
            end="2026-08-07T09:10:00+00:00",
            duration=600,
            event_uuid="evt-observed-not-cause",
        )
        connection.execute("UPDATE eventos SET metadata_json = ? WHERE id = ?", ('{"observed_context": "falta de material aparente"}', event_id))
        add_event(
            connection,
            cliente_id,
            site_id,
            camera_id,
            "machine_stoppage",
            start="2026-08-07T10:00:00+00:00",
            end="2026-08-07T10:10:00+00:00",
            duration=600,
            event_uuid="evt-confirmed-cause",
            confirmed_cause="manutenção",
        )
        payload = intelligence(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=END), now=NOW)

    causes = {item["key"]: item for item in payload["confirmed_causes"]}
    assert "falta de material aparente" not in causes
    assert causes["manutenção"]["event_uuids"] == ["evt-confirmed-cause"]
    assert causes["causa não informada"]["event_uuids"] == ["evt-observed-not-cause"]


def test_intelligence_comparison_is_safe_and_traceable() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, _asset_id, camera_id = make_context()
    with temp_dir, connection:
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T09:00:00+00:00", end="2026-08-07T09:10:00+00:00", duration=600, event_uuid="evt-intel-current")
        payload = intelligence(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=END), now=NOW)

    duration_metric = payload["comparison"]["metrics"]["total_duration_seconds"]
    assert duration_metric["current"] == 600
    assert duration_metric["previous"] == 0
    assert duration_metric["percent_change"] is None
    assert payload["traceability"]["event_uuids"] == ["evt-intel-current"]
    assert payload["coverage"]["status"] == "unknown"


def test_intelligence_api_endpoint() -> None:
    temp_dir, db_path, connection, cliente_id, site_id, _area_id, _process_id, _asset_id, camera_id = make_context()
    with temp_dir:
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T09:00:00+00:00", end="2026-08-07T09:10:00+00:00", duration=600, event_uuid="evt-intel-api")
        create_user(connection, "intel@example.com", "senha", "admin_cliente", cliente_id)
        connection.close()

        def test_connect(_path=None):
            return connect(db_path)

        with patch("app.api.connect", test_connect):
            client = TestClient(api)
            client.post("/auth/login", json={"email": "intel@example.com", "senha": "senha"})
            response = client.get("/operations/read-model/insights", params={"start": "2026-08-07T08:00:00+00:00", "end": "2026-08-07T12:00:00+00:00", "camera_id": camera_id})

    assert response.status_code == 200
    payload = response.json()
    assert payload["attention"][0]["event_uuids"] == ["evt-intel-api"]


def test_vision_v1_operational_data_daily_report_and_intelligence_are_traceable() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, area_id, process_id, asset_id, camera_id = make_context()
    start = parse_datetime("2026-08-07T08:00:00+00:00")
    end = parse_datetime("2026-08-07T09:40:00+00:00")
    with temp_dir, connection:
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T08:00:00+00:00", "ACTIVE", True)
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T08:30:00+00:00", "STOPPED", True)
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T08:40:00+00:00", "ACTIVE", True)
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T09:00:00+00:00", "ACTIVE", False)
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T09:10:00+00:00", "ACTIVE", True)
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T09:30:00+00:00", "UNKNOWN", None, inference_fps=0.0)
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T09:40:00+00:00", "ACTIVE", True)
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T08:30:00+00:00", end="2026-08-07T08:40:00+00:00", duration=600, event_uuid="evt-a6-stop")
        add_event(connection, cliente_id, site_id, camera_id, "workstation_unattended", start="2026-08-07T09:00:00+00:00", end="2026-08-07T09:10:00+00:00", duration=600, event_uuid="evt-a6-absence")
        add_event(connection, cliente_id, site_id, camera_id, "restricted_zone_occupied", start="2026-08-07T09:15:00+00:00", end="2026-08-07T09:17:00+00:00", duration=120, event_uuid="evt-a6-zone")
        data = operational_data(connection, ReadModelFilters(cliente_id=cliente_id, start=start, end=end), now=end)
        report = daily_report(connection, ReadModelFilters(cliente_id=cliente_id, start=start, end=end), now=end)

    assert data["machine_data"]["active_seconds"] == 4800
    assert data["machine_data"]["stopped_seconds"] == 600
    assert data["machine_data"]["unknown_seconds"] == 600
    assert data["machine_data"]["stoppage_count"] == 1
    assert data["machine_data"]["average_stoppage_seconds"] == 600
    assert data["human_operation_data"]["presence_seconds"] == 4800
    assert data["human_operation_data"]["absence_seconds"] == 600
    assert data["human_operation_data"]["unknown_seconds"] == 600
    assert data["human_operation_data"]["absence_count"] == 1
    assert data["coverage"]["status"] == "GOOD"
    assert data["coverage"]["unknown_percent"] == 10.0
    assert data["data_quality"]["unknown_is_not_counted_as_active_or_stopped"] is True
    assert data["zone_safety_data"]["occupancy_event_count"] == 1
    assert data["zone_safety_data"]["person_vehicle_proximity"]["status"] == "OBSERVATION_SUPPORTED_EVENT_NOT_YET_DEFINED"
    assert report["report_type"] == "daily_operational_report_v1"
    assert "evt-a6-stop" in report["traceability"]["event_uuids"]
    assert report["summary"]["machines"]["traceability"]["observation_types"] == ["machine_activity"]
    assert all("causou" not in str(item).lower() for item in report["intelligence"]["attention"])


def test_operational_timeline_emits_state_transitions_without_frame_duplicates() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, asset_id, camera_id = make_context()
    start = parse_datetime("2026-08-07T08:00:00+00:00")
    end = parse_datetime("2026-08-07T08:30:00+00:00")
    with temp_dir, connection:
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T08:00:00+00:00", "ACTIVE", True)
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T08:05:00+00:00", "ACTIVE", True)
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T08:10:00+00:00", "STOPPED", True)
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T08:20:00+00:00", "STOPPED", False)
        payload = operational_timeline(connection, ReadModelFilters(cliente_id=cliente_id, start=start, end=end), now=end)

    machine_items = [item for item in payload["items"] if item["type"] == "machine_activity"]
    presence_items = [item for item in payload["items"] if item["type"] == "person_presence"]
    assert [item["new_state"] for item in machine_items] == ["ACTIVE", "STOPPED"]
    assert machine_items[0]["duration_seconds"] == 600
    assert machine_items[1]["duration_seconds"] == 1200
    assert [item["new_state"] for item in presence_items] == ["PRESENT", "ABSENT"]
    assert payload["items"] == sorted(payload["items"], key=lambda item: (item["timestamp"], item["type"], item.get("event_uuid") or ""))


def test_operational_timeline_preserves_unknown_zone_camera_and_event_evidence_traceability() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, asset_id, camera_id = make_context()
    start = parse_datetime("2026-08-07T08:00:00+00:00")
    end = parse_datetime("2026-08-07T08:20:00+00:00")
    zone_id = "zone-a6"
    with temp_dir, connection:
        add_sample(
            connection,
            cliente_id,
            site_id,
            camera_id,
            asset_id,
            "2026-08-07T08:00:00+00:00",
            "UNKNOWN",
            None,
            camera_online=False,
            inference_fps=0.0,
            metadata={
                "canonical_observations": [
                    {
                        "observation_type": "zone_occupancy",
                        "value": "UNKNOWN",
                        "zone_id": zone_id,
                        "confidence": 0.0,
                        "data_quality": "unknown",
                    }
                ]
            },
        )
        add_sample(
            connection,
            cliente_id,
            site_id,
            camera_id,
            asset_id,
            "2026-08-07T08:05:00+00:00",
            "ACTIVE",
            True,
            metadata={
                "canonical_observations": [
                    {
                        "observation_type": "zone_occupancy",
                        "value": "OCCUPIED",
                        "zone_id": zone_id,
                        "confidence": 0.85,
                        "data_quality": "observed",
                    }
                ]
            },
        )
        event_id = add_event(
            connection,
            cliente_id,
            site_id,
            camera_id,
            "machine_stoppage",
            start="2026-08-07T08:10:00+00:00",
            end="2026-08-07T08:15:00+00:00",
            duration=300,
            event_uuid="evt-timeline-evidence",
        )
        connection.execute("UPDATE eventos SET midia_path = ? WHERE id = ?", ("data/evidence/evt-timeline.jpg", event_id))
        connection.commit()
        payload = operational_timeline(connection, ReadModelFilters(cliente_id=cliente_id, start=start, end=end), now=end)

    zone_items = [item for item in payload["items"] if item["type"] == "zone_occupancy"]
    camera_items = [item for item in payload["items"] if item["type"] == "camera_status"]
    event_items = [item for item in payload["items"] if item["event_uuid"] == "evt-timeline-evidence"]
    assert [item["new_state"] for item in zone_items] == ["UNKNOWN", "OCCUPIED"]
    assert [item["new_state"] for item in camera_items] == ["OFFLINE", "ONLINE"]
    assert {item["type"] for item in event_items} == {"event_started", "event_closed"}
    assert all(item["evidence_refs"] == [{"type": "image", "path": "data/evidence/evt-timeline.jpg"}] for item in event_items)


def test_operations_timeline_endpoint_is_tenant_isolated() -> None:
    temp_dir, db_path, connection, cliente_id, site_id, _area_id, _process_id, asset_id, camera_id = make_context()
    with temp_dir:
        other_cliente = criar_cliente(connection, "Outro cliente")
        other_site = criar_unidade(connection, other_cliente, "Outra fabrica")
        other_camera = criar_camera(connection, other_site, "Camera externa", cliente_id=other_cliente)
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T08:00:00+00:00", "ACTIVE", True)
        add_sample(connection, other_cliente, other_site, other_camera, "asset-outro", "2026-08-07T08:00:00+00:00", "STOPPED", False)
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T08:05:00+00:00", end="2026-08-07T08:10:00+00:00", duration=300, event_uuid="evt-own")
        add_event(connection, other_cliente, other_site, other_camera, "machine_stoppage", start="2026-08-07T08:05:00+00:00", end="2026-08-07T08:10:00+00:00", duration=300, event_uuid="evt-other")
        create_user(connection, "timeline@example.com", "senha", "admin_cliente", cliente_id)
        connection.close()

        def test_connect(_path=None):
            return connect(db_path)

        with patch("app.api.connect", test_connect):
            client = TestClient(api)
            client.post("/auth/login", json={"email": "timeline@example.com", "senha": "senha"})
            response = client.get(
                "/operations/timeline",
                params={"start": "2026-08-07T08:00:00+00:00", "end": "2026-08-07T09:00:00+00:00"},
            )

    assert response.status_code == 200
    payload = response.json()
    event_uuids = {item["event_uuid"] for item in payload["items"] if item.get("event_uuid")}
    assert event_uuids == {"evt-own"}
    assert all(item["context"].get("camera_id") != other_camera for item in payload["items"])


def test_operational_timeline_reports_empty_period_without_inventing_states() -> None:
    temp_dir, _db_path, connection, cliente_id, _site_id, _area_id, _process_id, _asset_id, _camera_id = make_context()
    start = parse_datetime("2026-08-07T08:00:00+00:00")
    end = parse_datetime("2026-08-07T09:00:00+00:00")
    with temp_dir, connection:
        payload = operational_timeline(connection, ReadModelFilters(cliente_id=cliente_id, start=start, end=end), now=end)

    assert payload["items"] == []
    assert payload["count"] == 0
    assert payload["coverage"]["status"] == "unknown"
    assert payload["sources"] == ["operational_samples", "eventos"]


def test_operational_data_without_samples_has_insufficient_coverage_and_no_strong_conclusion() -> None:
    temp_dir, _db_path, connection, cliente_id, _site_id, _area_id, _process_id, _asset_id, _camera_id = make_context()
    with temp_dir, connection:
        data = operational_data(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=END), now=NOW)
        report = daily_report(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=END), now=NOW)

    assert data["coverage"]["status"] == "INSUFFICIENT"
    assert data["machine_data"]["active_seconds"] == 0
    assert data["machine_data"]["stopped_seconds"] == 0
    assert data["machine_data"]["unknown_seconds"] == 14400
    assert report["intelligence"]["briefing"] == ["Ainda não existem eventos operacionais classificados suficientes neste período."]


def test_operational_data_tenant_isolation() -> None:
    temp_dir, _db_path, connection, cliente_a, site_a, _area_a, _process_a, asset_a, camera_a = make_context()
    with temp_dir, connection:
        cliente_b = criar_cliente(connection, "Cliente B")
        site_b = criar_unidade(connection, cliente_b, "Fabrica B")
        camera_b = criar_camera(connection, site_b, "Camera B", cliente_id=cliente_b)
        add_sample(connection, cliente_a, site_a, camera_a, asset_a, "2026-08-07T08:00:00+00:00", "ACTIVE", True)
        add_sample(connection, cliente_a, site_a, camera_a, asset_a, "2026-08-07T09:00:00+00:00", "STOPPED", True)
        add_event(connection, cliente_a, site_a, camera_a, "machine_stoppage", start="2026-08-07T09:00:00+00:00", end="2026-08-07T09:10:00+00:00", duration=600, event_uuid="evt-tenant-a")
        add_event(connection, cliente_b, site_b, camera_b, "machine_stoppage", start="2026-08-07T09:00:00+00:00", end="2026-08-07T09:20:00+00:00", duration=1200, event_uuid="evt-tenant-b")
        data_a = operational_data(connection, ReadModelFilters(cliente_id=cliente_a, start=START, end=END), now=NOW)
        data_b = operational_data(connection, ReadModelFilters(cliente_id=cliente_b, start=START, end=END), now=NOW)

    assert data_a["machine_data"]["traceability"]["event_uuids"] == ["evt-tenant-a"]
    assert data_b["machine_data"]["traceability"]["event_uuids"] == ["evt-tenant-b"]

def test_machine_coverage_does_not_depend_on_person_inference_fps() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, asset_id, camera_id = make_context()
    start = parse_datetime("2026-08-07T08:00:00+00:00")
    end = parse_datetime("2026-08-07T08:10:00+00:00")

    with temp_dir, connection:
        add_sample(
            connection,
            cliente_id,
            site_id,
            camera_id,
            asset_id,
            "2026-08-07T08:00:00+00:00",
            "ACTIVE",
            None,
            camera_online=True,
            inference_fps=0.0,
            metadata={
                "canonical_observations": [
                    {
                        "observation_type": "machine_activity",
                        "value": "ACTIVE",
                        "confidence": 0.9,
                        "data_quality": "observed",
                    }
                ]
            },
        )

        data = operational_data(
            connection,
            ReadModelFilters(cliente_id=cliente_id, start=start, end=end),
            now=end,
        )

    assert data["machine_data"]["active_seconds"] == 600
    assert data["machine_data"]["unknown_seconds"] == 0
    assert data["coverage"]["valid_percent"] == 100.0
    assert data["coverage"]["status"] == "GOOD"
