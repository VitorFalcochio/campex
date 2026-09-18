from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import api
from app.auth import create_user
from app.database import connect
from app.operational_alerting import AlertDecisionFilters, evaluate_alert_decisions, list_alert_decisions
from app.operational_read_model import ReadModelFilters, parse_datetime
from app.operational_understanding import validate_normalize_and_persist_understanding
from app.video_understanding import build_understanding_request
from tests.test_operational_read_model import add_event, add_sample, make_context
from tests.test_validated_operational_understanding_v1 import _context_with_visual_evidence, _result


START = parse_datetime("2026-08-07T08:00:00+00:00")
END = parse_datetime("2026-08-07T10:00:00+00:00")


def test_exceptionally_long_stoppage_generates_alert_and_does_not_deliver() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, _asset_id, camera_id = make_context()
    with temp_dir, connection:
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-06T08:00:00+00:00", end="2026-08-06T08:05:00+00:00", duration=300, event_uuid="evt-history-alert")
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T08:10:00+00:00", end="2026-08-07T08:40:00+00:00", duration=1800, event_uuid="evt-long-alert")
        before_deliveries = connection.execute("SELECT COUNT(*) FROM alert_deliveries").fetchone()[0]
        before_outbox = connection.execute("SELECT COUNT(*) FROM sync_outbox").fetchone()[0]
        payload = evaluate_alert_decisions(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=END), now=END)
        after_deliveries = connection.execute("SELECT COUNT(*) FROM alert_deliveries").fetchone()[0]
        after_outbox = connection.execute("SELECT COUNT(*) FROM sync_outbox").fetchone()[0]

    decisions = [item for item in payload["decisions"] if item["alert_type"] == "prolonged_stoppage"]
    assert decisions[0]["decision"] == "ALERT"
    assert decisions[0]["severity"] == "high"
    assert decisions[0]["event_refs"] == ["evt-long-alert"]
    assert "rule:exceptionally_long_stoppage" in decisions[0]["reason_codes"]
    assert decisions[0]["cause_inferred"] is False
    assert before_deliveries == after_deliveries
    assert before_outbox == after_outbox


def test_same_situation_and_small_duration_increase_do_not_duplicate_alert() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, _asset_id, camera_id = make_context()
    with temp_dir, connection:
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-06T08:00:00+00:00", end="2026-08-06T08:05:00+00:00", duration=300, event_uuid="evt-history-small")
        event_id = add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T08:10:00+00:00", end="2026-08-07T08:41:00+00:00", duration=1860, event_uuid="evt-small-increase")
        first = evaluate_alert_decisions(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=END), now=END)
        connection.execute("UPDATE eventos SET duracao = ?, fim = ? WHERE id = ?", (1920, "2026-08-07T08:42:00+00:00", event_id))
        connection.commit()
        second = evaluate_alert_decisions(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=END), now=END)
        rows = list_alert_decisions(connection, AlertDecisionFilters(tenant_id=cliente_id, alert_type="prolonged_stoppage"))

    assert len([item for item in first["decisions"] if item["alert_type"] == "prolonged_stoppage"]) == 1
    assert len([item for item in second["decisions"] if item["alert_type"] == "prolonged_stoppage"]) == 1
    assert len(rows) == 1


def test_material_escalation_creates_new_decision() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, _asset_id, camera_id = make_context()
    with temp_dir, connection:
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-06T08:00:00+00:00", end="2026-08-06T08:05:00+00:00", duration=300, event_uuid="evt-history-escalate")
        event_id = add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T08:10:00+00:00", end="2026-08-07T08:40:00+00:00", duration=1800, event_uuid="evt-escalate")
        evaluate_alert_decisions(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=END), now=END)
        connection.execute("UPDATE eventos SET duracao = ?, fim = ? WHERE id = ?", (3900, "2026-08-07T09:15:00+00:00", event_id))
        connection.commit()
        evaluate_alert_decisions(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=END), now=END)
        rows = list_alert_decisions(connection, AlertDecisionFilters(tenant_id=cliente_id, alert_type="prolonged_stoppage"))

    assert {row["severity"] for row in rows} == {"high", "critical"}
    assert all(row["decision"] == "ALERT" for row in rows)


def test_resolved_event_is_suppressed_and_reopened_event_has_new_incident() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, _asset_id, camera_id = make_context()
    with temp_dir, connection:
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-06T08:00:00+00:00", end="2026-08-06T08:05:00+00:00", duration=300, event_uuid="evt-history-resolved")
        resolved_id = add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T08:10:00+00:00", end="2026-08-07T08:45:00+00:00", duration=2100, event_uuid="evt-resolved")
        connection.execute("UPDATE eventos SET workflow_status = 'resolved' WHERE id = ?", (resolved_id,))
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T09:00:00+00:00", end="2026-08-07T09:35:00+00:00", duration=2100, event_uuid="evt-reopened")
        connection.commit()
        payload = evaluate_alert_decisions(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=END), now=END)

    by_ref = {item["event_refs"][0]: item for item in payload["decisions"] if item["alert_type"] == "prolonged_stoppage"}
    assert by_ref["evt-resolved"]["decision"] == "SUPPRESS"
    assert "event_already_resolved" in by_ref["evt-resolved"]["reason_codes"]
    assert by_ref["evt-reopened"]["decision"] == "ALERT"
    assert by_ref["evt-resolved"]["incident_key"] != by_ref["evt-reopened"]["incident_key"]


def test_recurrence_absence_camera_offline_lighting_and_activity_decisions() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, asset_id, camera_id = make_context()
    with temp_dir, connection:
        for index, minute in enumerate([0, 8, 16, 24, 32], start=1):
            add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start=f"2026-08-07T08:{minute:02d}:00+00:00", end=f"2026-08-07T08:{minute + 1:02d}:00+00:00", duration=60, event_uuid=f"evt-recur-alert-{index}")
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T08:00:00+00:00", "ACTIVE", False)
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T08:18:00+00:00", "ACTIVE", True)
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T08:30:00+00:00", "UNKNOWN", None, camera_online=False, inference_fps=0.0)
        payload = evaluate_alert_decisions(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=END), now=END)

    types = {item["alert_type"]: item for item in payload["decisions"]}
    assert types["recurrent_stoppages"]["decision"] == "ALERT"
    assert types["prolonged_operational_absence"]["decision"] == "ALERT"
    assert types["technical_camera_offline"]["decision"] == "ALERT"
    assert "technical_alert" in types["technical_camera_offline"]["reason_codes"]
    assert "no_visual_inference_while_offline" in types["technical_camera_offline"]["reason_codes"]


def test_insufficient_data_for_absence_does_not_alert() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, asset_id, camera_id = make_context()
    with temp_dir, connection:
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T08:00:00+00:00", "ACTIVE", None, metadata={"person_presence": "UNKNOWN"})
        payload = evaluate_alert_decisions(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=END), now=END)

    assert not [item for item in payload["decisions"] if item["alert_type"] == "prolonged_operational_absence" and item["decision"] == "ALERT"]


def test_validated_understanding_enriches_but_rejected_is_ignored_and_partial_does_not_replace_facts() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, _asset_id, camera_id, context = _context_with_visual_evidence(partial=True)
    with temp_dir, connection:
        connection.execute("UPDATE eventos SET fim = ?, duracao = ? WHERE event_uuid = ?", ("2026-08-07T08:45:00+00:00", 2100, "evt-vou"))
        connection.commit()
        request = build_understanding_request(context, request_id="vur-alert-context")
        partial = _result(request, understanding_id="vu-alert-partial")
        partial["uncertainties"] = ["Timestamp mismatch reported."]
        validate_normalize_and_persist_understanding(connection, video_context=context, request=request, result=partial)
        rejected = _result(request, understanding_id="vu-alert-rejected")
        rejected["cause_inferred"] = True
        validate_normalize_and_persist_understanding(connection, video_context=context, request=request, result=rejected)
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-06T08:00:00+00:00", end="2026-08-06T08:05:00+00:00", duration=300, event_uuid="evt-history-vu-alert")
        payload = evaluate_alert_decisions(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=END), now=END)

    decision = next(item for item in payload["decisions"] if item["alert_type"] == "prolonged_stoppage")
    assert "vu-alert-partial" in decision["understanding_refs"]
    assert "vu-alert-rejected" not in decision["understanding_refs"]
    assert "partial_understanding_used_as_context_only" in decision["reason_codes"]
    assert "rejected_understanding_ignored" in decision["reason_codes"]
    assert decision["cause_inferred"] is False
    assert decision["visual_summary"]


def test_decision_history_persists_and_api_filters_are_tenant_isolated() -> None:
    temp_dir, db_path, connection, cliente_id, site_id, _area_id, _process_id, _asset_id, camera_id = make_context()
    with temp_dir:
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-06T08:00:00+00:00", end="2026-08-06T08:05:00+00:00", duration=300, event_uuid="evt-history-api-alert")
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T08:10:00+00:00", end="2026-08-07T08:40:00+00:00", duration=1800, event_uuid="evt-api-alert")
        create_user(connection, "alerts-decision@example.com", "senha", "admin_cliente", cliente_id)
        connection.close()

        def test_connect(_path=None):
            return connect(db_path)

        with patch("app.api.connect", test_connect):
            client = TestClient(api)
            client.post("/auth/login", json={"email": "alerts-decision@example.com", "senha": "senha"})
            evaluated = client.post("/operations/alert-decisions/evaluate", params={"start": START.isoformat(), "end": END.isoformat()})
            listed = client.get("/operations/alert-decisions", params={"alert_type": "prolonged_stoppage"})
            detail = client.get(f"/operations/alert-decisions/{evaluated.json()['decisions'][0]['decision_id']}")
        reopened = connect(db_path)
        try:
            persisted = reopened.execute("SELECT COUNT(*) FROM operational_alert_decisions").fetchone()[0]
        finally:
            reopened.close()

    assert evaluated.status_code == 200
    assert evaluated.json()["delivery_performed"] is False
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert detail.status_code == 200
    assert persisted == 1
