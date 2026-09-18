from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import api
from app.auth import create_user
from app.database import connect
from app.models import listar_alert_deliveries
from app.operational_alerting import evaluate_alert_decisions
from app.operational_briefing import operational_shift_briefing
from app.operational_read_model import ReadModelFilters, parse_datetime
from app.operational_understanding import validate_normalize_and_persist_understanding
from app.video_understanding import build_understanding_request
from tests.test_operational_read_model import add_event, add_sample, make_context
from tests.test_validated_operational_understanding_v1 import _context_with_visual_evidence, _result


START = parse_datetime("2026-08-07T08:00:00+00:00")
END = parse_datetime("2026-08-07T10:00:00+00:00")


def test_normal_period_without_incidents_is_factual_and_does_not_create_delivery_or_ai_call() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, asset_id, camera_id = make_context()
    with temp_dir, connection, patch("app.video_understanding.OpenAIVideoUnderstandingProvider.analyze") as openai:
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T08:00:00+00:00", "ACTIVE", True)
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T09:59:00+00:00", "ACTIVE", True)
        before_deliveries = len(listar_alert_deliveries(connection))
        payload = operational_shift_briefing(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=END), now=END)
        after_deliveries = len(listar_alert_deliveries(connection))

    assert payload["overall_status"] == "NORMAL"
    assert "sem incidentes relevantes" in payload["headline"]
    assert payload["critical_incidents"] == []
    assert payload["financial_impact_calculated"] is False
    assert payload["cause_inferred"] is False
    assert before_deliveries == after_deliveries
    openai.assert_not_called()


def test_alert_period_attention_metrics_stoppages_asset_summary_and_traceability() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, asset_id, camera_id = make_context()
    with temp_dir, connection:
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-06T08:00:00+00:00", end="2026-08-06T08:05:00+00:00", duration=300, event_uuid="evt-brief-history")
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T08:10:00+00:00", end="2026-08-07T08:40:00+00:00", duration=1800, event_uuid="evt-brief-long")
        evaluate_alert_decisions(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=END), now=END)
        payload = operational_shift_briefing(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=END), now=END)

    assert payload["overall_status"] == "ATTENTION"
    assert payload["metrics"]["stoppage_count"] == 1
    assert payload["metrics"]["stoppage_total_seconds"] == 1800
    assert payload["metrics"]["longest_stoppage_seconds"] == 1800
    assert payload["metrics"]["alert_decisions"] == 1
    assert payload["critical_incidents"][0]["event_refs"] == ["evt-brief-long"]
    assert payload["assets"][0]["asset_id"] == asset_id
    assert payload["assets"][0]["stoppage_count"] == 1
    assert "evt-brief-long" in payload["source_refs"]["event_uuids"]


def test_escalation_same_incident_is_single_briefing_incident_with_max_severity() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, _asset_id, camera_id = make_context()
    with temp_dir, connection:
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-06T08:00:00+00:00", end="2026-08-06T08:05:00+00:00", duration=300, event_uuid="evt-brief-escalation-history")
        event_id = add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T08:10:00+00:00", end="2026-08-07T08:40:00+00:00", duration=1800, event_uuid="evt-brief-escalation")
        evaluate_alert_decisions(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=END), now=END)
        connection.execute("UPDATE eventos SET duracao = ?, fim = ? WHERE id = ?", (3900, "2026-08-07T09:15:00+00:00", event_id))
        connection.commit()
        evaluate_alert_decisions(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=END), now=END)
        payload = operational_shift_briefing(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=END), now=END)

    assert len(payload["critical_incidents"]) == 1
    assert payload["critical_incidents"][0]["max_severity"] == "critical"
    assert len(payload["critical_incidents"][0]["alert_decision_refs"]) == 2
    assert payload["overall_status"] == "CRITICAL"


def test_unknown_and_camera_offline_are_reported_as_data_quality_not_normal() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, asset_id, camera_id = make_context()
    with temp_dir, connection:
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T08:00:00+00:00", "UNKNOWN", None, camera_online=False, inference_fps=0.0)
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T09:59:00+00:00", "UNKNOWN", None, camera_online=False, inference_fps=0.0)
        evaluate_alert_decisions(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=END), now=END)
        payload = operational_shift_briefing(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=END), now=END)

    assert payload["overall_status"] == "UNKNOWN"
    assert payload["data_quality"]["offline_cameras"] == [camera_id]
    assert "camera_offline_periods_present" in payload["data_quality"]["limitations"]
    assert payload["data_quality"]["unknown_is_not_interpreted_as_normal"] is True


def test_recurrence_and_operational_activity_are_summarized() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, asset_id, camera_id = make_context()
    with temp_dir, connection:
        for index, minute in enumerate([0, 8, 16, 24, 32], start=1):
            add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start=f"2026-08-07T08:{minute:02d}:00+00:00", end=f"2026-08-07T08:{minute + 1:02d}:00+00:00", duration=60, event_uuid=f"evt-brief-recur-{index}")
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T08:00:00+00:00", "STOPPED", False, metadata={"canonical_observations": [{"observation_type": "lighting_state", "value": "OFF", "confidence": 0.9, "data_quality": "observed"}]})
        evaluate_alert_decisions(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=END), now=END)
        payload = operational_shift_briefing(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=END), now=END)

    assert payload["metrics"]["recurrence_count"] == 1
    assert payload["operational_activity"]["states"].get("NO_ACTIVITY") == 1
    assert any(item["alert_type"] == "recurrent_stoppages" for item in payload["critical_incidents"])


def test_valid_and_partial_understanding_enrich_incident_rejected_does_not() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, _asset_id, camera_id, context = _context_with_visual_evidence(partial=True)
    with temp_dir, connection:
        connection.execute("UPDATE eventos SET fim = ?, duracao = ? WHERE event_uuid = ?", ("2026-08-07T08:45:00+00:00", 2100, "evt-vou"))
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-06T08:00:00+00:00", end="2026-08-06T08:05:00+00:00", duration=300, event_uuid="evt-brief-vu-history")
        connection.commit()
        request = build_understanding_request(context, request_id="vur-brief")
        partial = _result(request, understanding_id="vu-brief-partial")
        partial["uncertainties"] = ["Timestamp mismatch reported."]
        validate_normalize_and_persist_understanding(connection, video_context=context, request=request, result=partial)
        rejected = _result(request, understanding_id="vu-brief-rejected")
        rejected["cause_inferred"] = True
        validate_normalize_and_persist_understanding(connection, video_context=context, request=request, result=rejected)
        evaluate_alert_decisions(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=END), now=END)
        payload = operational_shift_briefing(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=END), now=END)

    incident = payload["critical_incidents"][0]
    assert "vu-brief-partial" in incident["understanding_refs"]
    assert "vu-brief-rejected" not in incident["understanding_refs"]
    assert incident["uncertainties"]
    assert incident["cause_inferred"] is False


def test_empty_window_is_honest_and_tenant_isolation_works() -> None:
    temp_dir, db_path, connection, cliente_id, _site_id, _area_id, _process_id, _asset_id, camera_id = make_context()
    with temp_dir:
        create_user(connection, "briefing@example.com", "senha", "admin_cliente", cliente_id)
        connection.close()

        def test_connect(_path=None):
            return connect(db_path)

        with patch("app.api.connect", test_connect):
            client = TestClient(api)
            client.post("/auth/login", json={"email": "briefing@example.com", "senha": "senha"})
            response = client.get("/operations/briefing", params={"start": START.isoformat(), "end": END.isoformat(), "camera_id": camera_id})

    assert response.status_code == 200
    payload = response.json()
    assert payload["overall_status"] == "UNKNOWN"
    assert payload["metrics"]["relevant_events"] == 0
    assert payload["critical_incidents"] == []
    assert payload["data_quality"]["coverage_status"] == "unknown"
