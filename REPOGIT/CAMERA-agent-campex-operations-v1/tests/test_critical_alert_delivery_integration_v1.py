from __future__ import annotations

import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import app.alerts as alerts
import app.edge_runtime as edge_runtime_module
from app.api import api
from app.auth import create_user
from app.database import connect, init_db
from app.models import criar_alert_recipient, listar_alert_deliveries
from app.operational_alerting import AlertDecisionFilters, evaluate_alert_decisions, list_alert_decisions
from app.operational_read_model import ReadModelFilters, parse_datetime
from tests.test_operational_read_model import add_event, add_sample, make_context


START = parse_datetime("2026-08-07T08:00:00+00:00")
END = parse_datetime("2026-08-07T10:00:00+00:00")


def _long_stoppage_context():
    temp_dir, db_path, connection, cliente_id, site_id, area_id, process_id, asset_id, camera_id = make_context()
    add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-06T08:00:00+00:00", end="2026-08-06T08:05:00+00:00", duration=300, event_uuid="evt-history-delivery")
    event_id = add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T08:10:00+00:00", end="2026-08-07T08:40:00+00:00", duration=1800, event_uuid="evt-delivery")
    criar_alert_recipient(connection, "Operacao", "ops@example.com", cliente_id=cliente_id, camera_id=camera_id, event_types=["prolonged_stoppage"])
    return temp_dir, db_path, connection, cliente_id, site_id, area_id, process_id, asset_id, camera_id, event_id


def _test_connect(db_path: Path):
    def connect_db(_path=None):
        return connect(db_path)

    return connect_db


def test_alert_decision_creates_delivery_sse_payload_and_console_delivery() -> None:
    temp_dir, db_path, connection, cliente_id, *_rest = _long_stoppage_context()
    with temp_dir, patch.dict(os.environ, {"CAMPEX_EMAIL_MODE": "console"}), patch("app.alerts.connect", _test_connect(db_path)), patch("builtins.print") as printer:
        payload = evaluate_alert_decisions(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=END), now=END)
        subscriber = alerts.subscribe()
        try:
            delivery_ids = alerts.enqueue_alert_decisions_with_connection(connection, payload["decisions"])
            sse_payload = subscriber.get(timeout=1)
            for _ in range(20):
                deliveries = listar_alert_deliveries(connection)
                if deliveries and deliveries[0]["status"] == "sent":
                    break
                time.sleep(0.05)
        finally:
            alerts.unsubscribe(subscriber)

    assert len(delivery_ids) == 1
    assert sse_payload["type"] == "critical_alert_decision"
    assert sse_payload["decision_id"] == payload["decisions"][0]["decision_id"]
    assert sse_payload["incident_key"] == payload["decisions"][0]["incident_key"]
    assert deliveries[0]["decision_id"] == payload["decisions"][0]["decision_id"]
    assert deliveries[0]["incident_key"] == payload["decisions"][0]["incident_key"]
    assert deliveries[0]["severity"] == "high"
    assert deliveries[0]["payload"]["cause_inferred"] is False
    printer.assert_called()


def test_suppress_and_insufficient_data_never_create_delivery_or_sse() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, asset_id, camera_id = make_context()
    with temp_dir, patch("app.alerts.schedule_delivery") as scheduler:
        criar_alert_recipient(connection, "Operacao", "ops@example.com", cliente_id=cliente_id)
        resolved_id = add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-06T08:00:00+00:00", end="2026-08-06T08:05:00+00:00", duration=300, event_uuid="evt-history-suppress-delivery")
        resolved_id = add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T08:10:00+00:00", end="2026-08-07T08:45:00+00:00", duration=2100, event_uuid="evt-suppress-delivery")
        connection.execute("UPDATE eventos SET workflow_status = 'resolved' WHERE id = ?", (resolved_id,))
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T08:00:00+00:00", "ACTIVE", None, metadata={"person_presence": "UNKNOWN"})
        connection.commit()
        payload = evaluate_alert_decisions(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=END), now=END)
        subscriber = alerts.subscribe()
        try:
            ids = alerts.enqueue_alert_decisions_with_connection(connection, payload["decisions"])
        finally:
            alerts.unsubscribe(subscriber)
        deliveries = listar_alert_deliveries(connection)

    assert ids == []
    assert deliveries == []
    assert any(item["decision"] == "SUPPRESS" for item in payload["decisions"])
    assert scheduler.call_count == 0


def test_same_decision_retry_and_restart_do_not_duplicate_logical_delivery() -> None:
    temp_dir, db_path, connection, cliente_id, *_rest = _long_stoppage_context()
    with temp_dir, patch("app.alerts.connect", _test_connect(db_path)), patch("app.alerts.schedule_delivery") as scheduler:
        payload = evaluate_alert_decisions(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=END), now=END)
        first = alerts.enqueue_alert_decisions_with_connection(connection, payload["decisions"])
        second = alerts.enqueue_alert_decisions_with_connection(connection, payload["decisions"])
        alerts.retry_delivery(first[0])
        alerts.resume_pending_deliveries()
        reopened = connect(db_path)
        try:
            init_db(reopened)
            rows = listar_alert_deliveries(reopened)
        finally:
            reopened.close()

    assert first == second
    assert len(rows) == 1
    assert scheduler.call_count >= 2


def test_escalation_creates_second_delivery_for_same_incident() -> None:
    temp_dir, _db_path, connection, cliente_id, _site_id, _area_id, _process_id, _asset_id, _camera_id, event_id = _long_stoppage_context()
    with temp_dir, patch("app.alerts.schedule_delivery"):
        first = evaluate_alert_decisions(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=END), now=END)
        alerts.enqueue_alert_decisions_with_connection(connection, first["decisions"])
        connection.execute("UPDATE eventos SET duracao = ?, fim = ? WHERE id = ?", (3900, "2026-08-07T09:15:00+00:00", event_id))
        connection.commit()
        second = evaluate_alert_decisions(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=END), now=END)
        alerts.enqueue_alert_decisions_with_connection(connection, second["decisions"])
        deliveries = listar_alert_deliveries(connection)
        decisions = list_alert_decisions(connection, AlertDecisionFilters(tenant_id=cliente_id, alert_type="prolonged_stoppage"))

    assert len(deliveries) == 2
    assert {delivery["severity"] for delivery in deliveries} == {"high", "critical"}
    assert len({decision["incident_key"] for decision in decisions}) == 1


def test_api_evaluate_uses_delivery_pipeline_and_keeps_tenant_scope() -> None:
    temp_dir, db_path, connection, cliente_id, *_rest = _long_stoppage_context()
    with temp_dir, patch.dict(os.environ, {"CAMPEX_EMAIL_MODE": "console"}):
        create_user(connection, "delivery-api@example.com", "senha", "admin_cliente", cliente_id)
        connection.close()

        with patch("app.api.connect", _test_connect(db_path)), patch("app.alerts.connect", _test_connect(db_path)), patch("builtins.print"):
            client = TestClient(api)
            client.post("/auth/login", json={"email": "delivery-api@example.com", "senha": "senha"})
            response = client.post("/operations/alert-decisions/evaluate", params={"start": START.isoformat(), "end": END.isoformat()})
            listed = client.get("/alert-deliveries")

    assert response.status_code == 200
    assert len(response.json()["delivery_ids"]) == 1
    assert listed.status_code == 200
    assert listed.json()[0]["decision_id"] == response.json()["decisions"][0]["decision_id"]


def test_runtime_automatic_decisioning_evaluates_without_openai_or_frame_spam() -> None:
    with patch.dict(os.environ, {"CAMPEX_EMAIL_MODE": "console"}), patch("builtins.print"):
        temp_dir_obj, db_path, connection, cliente_id, site_id, _area_id, _process_id, _asset_id, camera_id = make_context()
        now = datetime.now(timezone.utc)
        add_event(
            connection,
            cliente_id,
            site_id,
            camera_id,
            "machine_stoppage",
            start=(now - timedelta(days=1)).isoformat(),
            end=(now - timedelta(days=1, minutes=-5)).isoformat(),
            duration=300,
            event_uuid="evt-runtime-history",
        )
        add_event(
            connection,
            cliente_id,
            site_id,
            camera_id,
            "machine_stoppage",
            start=(now - timedelta(minutes=45)).isoformat(),
            end=(now - timedelta(minutes=15)).isoformat(),
            duration=1800,
            event_uuid="evt-runtime-delivery",
        )
        criar_alert_recipient(connection, "Operacao", "ops@example.com", cliente_id=cliente_id, camera_id=camera_id, event_types=["prolonged_stoppage"])
        connection.close()
        runtime = edge_runtime_module.ProductionEdgeRuntime(
            edge_id="edge_test",
            db_path=db_path,
            heartbeat_seconds=0.1,
            sync_seconds=0.1,
            alert_decision_seconds=0.1,
        )
        original_alerts_connect = alerts.connect
        try:
            alerts.connect = _test_connect(db_path)
            with patch.object(runtime.stop_event, "wait", side_effect=lambda _seconds: runtime.stop_event.set() or True):
                runtime._run_alert_decisioning()
            with connect(db_path) as reopened:
                deliveries = listar_alert_deliveries(reopened)
        finally:
            alerts.connect = original_alerts_connect
            temp_dir_obj.cleanup()

    assert len(deliveries) == 1
