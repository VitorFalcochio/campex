from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import app.alerts as alerts_module
from app import api as api_module
from app.api import api
from app.auth import create_user
from app.database import connect, init_db
from app.event_workflow import acknowledge_event, event_detail, resolve_event, update_human_context
from app.models import (
    criar_alert_recipient,
    criar_camera,
    criar_cliente,
    criar_evento_machine_operational,
    criar_machine_monitor,
    criar_unidade,
    fechar_evento_machine_stoppage,
    listar_alert_deliveries,
    obter_evento,
    registrar_evidence_index,
    registrar_operational_sample,
)
from app.operational_context import apply_context_to_camera, criar_operational_area, criar_operational_asset, criar_operational_process
from app.operational_read_model import ReadModelFilters, current_operation, intelligence, losses, parse_datetime, period_summary
from app.alerts import enqueue_event_alert, retry_delivery


def _wait_for_delivery_status(test_connect, event_id: str, statuses: set[str], timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        with test_connect() as connection:
            rows = listar_alert_deliveries(connection, evento_id=event_id)
            if rows:
                last = rows[0]
                if last["status"] in statuses:
                    return last
        time.sleep(0.05)
    assert last is not None
    return last


def _polygon() -> list[dict[str, float]]:
    return [
        {"x": 0.2, "y": 0.2},
        {"x": 0.8, "y": 0.2},
        {"x": 0.8, "y": 0.8},
    ]


def _create_chain_context(connection, *, client_name: str, email: str) -> dict[str, str]:
    cliente_id = criar_cliente(connection, client_name)
    unidade_id = criar_unidade(connection, cliente_id, "Unidade 01")
    area_id = criar_operational_area(connection, cliente_id=cliente_id, unidade_id=unidade_id, nome="Corte")
    process_id = criar_operational_process(
        connection,
        cliente_id=cliente_id,
        unidade_id=unidade_id,
        area_id=area_id,
        nome="Linha A6",
    )
    asset_id = criar_operational_asset(
        connection,
        cliente_id=cliente_id,
        unidade_id=unidade_id,
        area_id=area_id,
        process_id=process_id,
        nome="A6",
    )
    camera_id = criar_camera(
        connection,
        unidade_id,
        f"Câmera {client_name}",
        cliente_id=cliente_id,
        config_ref="file:///tmp/camera.mp4",
        source_type="file",
    )
    apply_context_to_camera(connection, camera_id, area_context_id=area_id, process_id=process_id, asset_id=asset_id)
    monitor_id = criar_machine_monitor(
        connection,
        cliente_id,
        unidade_id,
        camera_id,
        "A6",
        _polygon(),
        _polygon(),
        area_context_id=area_id,
        process_id=process_id,
        asset_id=asset_id,
    )
    recipient_id = criar_alert_recipient(
        connection,
        "Supervisor",
        email,
        cliente_id=cliente_id,
        event_types=["machine_stoppage"],
        severidade_minima="low",
    )
    user_id = create_user(connection, email, "senha-segura", "admin_cliente", cliente_id, "Gestor")
    return {
        "cliente_id": cliente_id,
        "unidade_id": unidade_id,
        "area_id": area_id,
        "process_id": process_id,
        "asset_id": asset_id,
        "camera_id": camera_id,
        "monitor_id": monitor_id,
        "recipient_id": recipient_id,
        "user_id": user_id,
        "email": email,
    }


def test_operational_chain_event_evidence_alert_history_operations_intelligence_and_tenant_isolation(tmp_path: Path) -> None:
    db_path = tmp_path / "chain.sqlite3"
    test_root = tmp_path / "root"
    evidence_dir = test_root / "data" / "evidence" / "chain"
    evidence_dir.mkdir(parents=True)
    evidence_file = evidence_dir / "frame-a6.jpg"
    evidence_file.write_bytes(b"\xff\xd8campex-evidence\xff\xd9")
    evidence_path = "data/evidence/chain/frame-a6.jpg"

    def test_connect(_path=None):
        return connect(db_path)

    with test_connect() as connection:
        init_db(connection)
        client_a = _create_chain_context(connection, client_name="Cliente A", email="gestor-a@campex.test")
        client_b = _create_chain_context(connection, client_name="Cliente B", email="gestor-b@campex.test")

        event_id = criar_evento_machine_operational(
            connection,
            cliente_id=client_a["cliente_id"],
            unidade_id=client_a["unidade_id"],
            camera_id=client_a["camera_id"],
            machine_monitor_id=client_a["monitor_id"],
            tipo="machine_stoppage",
            inicio="2026-08-10T10:00:00+00:00",
            motion_level=1.5,
            operator_present_start=False,
            confidence=0.91,
            midia_path=evidence_path,
            track_ids=[7],
            severidade="high",
            metadata={"operator_absent": True, "source": "operational_chain_v1"},
        )
        duplicate_event_id = criar_evento_machine_operational(
            connection,
            cliente_id=client_a["cliente_id"],
            unidade_id=client_a["unidade_id"],
            camera_id=client_a["camera_id"],
            machine_monitor_id=client_a["monitor_id"],
            tipo="machine_stoppage",
            inicio="2026-08-10T10:01:00+00:00",
            motion_level=1.8,
            operator_present_start=False,
            confidence=0.9,
            midia_path=evidence_path,
            track_ids=[7],
        )
        event = obter_evento(connection, event_id)
        registrar_evidence_index(
            connection,
            evidence_id="evd_chain_a6",
            event_id=event_id,
            event_uuid=event["event_uuid"],
            tenant_id=client_a["cliente_id"],
            unit_id=client_a["unidade_id"],
            camera_id=client_a["camera_id"],
            machine_id=client_a["monitor_id"],
            path=evidence_path,
            size_bytes=evidence_file.stat().st_size,
            metadata={"kind": "snapshot"},
        )
        registrar_operational_sample(
            connection,
            sample_uuid="sample-chain-1",
            tenant_id=client_a["cliente_id"],
            unit_id=client_a["unidade_id"],
            camera_id=client_a["camera_id"],
            machine_id=client_a["monitor_id"],
            machine_state="STOPPED",
            operator_present=False,
            activity_score=1.5,
            confidence=0.91,
            capture_fps=12.0,
            inference_fps=4.0,
            frames_analyzed=8,
            camera_online=True,
            sample_at="2026-08-10T10:02:00+00:00",
            metadata={"people_count": 0},
        )

    assert duplicate_event_id == event_id

    with (
        patch.object(api_module, "connect", test_connect),
        patch.object(alerts_module, "connect", test_connect),
        patch.object(api_module, "ROOT", test_root),
        patch.object(api_module, "EVIDENCE_DIR", test_root / "data" / "evidence"),
        patch.dict(os.environ, {"CAMPEX_EMAIL_MODE": "invalid", "CAMPEX_EMAIL_MAX_ATTEMPTS": "1", "CAMPEX_DIRECT_EVENT_EMAILS": "true"}),
    ):
        enqueue_event_alert(event_id)
        failed = _wait_for_delivery_status(test_connect, event_id, {"failed"})

    with test_connect() as connection:
        event = obter_evento(connection, event_id)
        deliveries = listar_alert_deliveries(connection, evento_id=event_id)
        outbox_rows = connection.execute("SELECT * FROM sync_outbox WHERE event_uuid = ?", (event["event_uuid"],)).fetchall()
        evidence_rows = connection.execute("SELECT * FROM evidences WHERE event_uuid = ?", (event["event_uuid"],)).fetchall()

    assert event["event_uuid"]
    assert event["cliente_id"] == client_a["cliente_id"]
    assert event["unidade_id"] == client_a["unidade_id"]
    assert event["site_id"] == client_a["unidade_id"]
    assert event["area_context_id"] == client_a["area_id"]
    assert event["process_id"] == client_a["process_id"]
    assert event["asset_id"] == client_a["asset_id"]
    assert event["camera_id"] == client_a["camera_id"]
    assert event["machine_monitor_id"] == client_a["monitor_id"]
    assert event["event_family"] == "interruption"
    assert event["event_subtype"] == "machine_stoppage"
    assert event["status"] == "open"
    assert event["workflow_status"] == "new"
    assert len(outbox_rows) == 1
    assert len(evidence_rows) == 1
    assert len(deliveries) == 1
    assert failed["status"] == "failed"
    assert failed["destinatario"] == client_a["email"]

    with patch.object(alerts_module, "connect", test_connect), patch.dict(os.environ, {"CAMPEX_EMAIL_MODE": "console"}):
        retried = retry_delivery(failed["id"])
        retried = _wait_for_delivery_status(test_connect, event_id, {"sent"})

    assert retried["status"] == "sent"

    with test_connect() as connection:
        fechar_evento_machine_stoppage(connection, event_id, "2026-08-10T10:12:00+00:00", 720)
        acknowledged = acknowledge_event(connection, event_id, actor="gestor-a@campex.test", human_notes="em análise", at="2026-08-10T10:13:00+00:00")
        update_human_context(
            connection,
            event_id,
            confirmed_cause="falta de material",
            action_taken="abastecimento solicitado",
            human_notes="validado pelo gestor",
            actor="gestor-a@campex.test",
            at="2026-08-10T10:14:00+00:00",
        )
        resolved = resolve_event(connection, event_id, actor="gestor-a@campex.test", at="2026-08-10T10:15:00+00:00")
        detail = event_detail(connection, event_id)
        filters = ReadModelFilters(
            cliente_id=client_a["cliente_id"],
            start=parse_datetime("2026-08-10T09:00:00+00:00"),
            end=parse_datetime("2026-08-10T11:00:00+00:00"),
        )
        current = current_operation(connection, ReadModelFilters(cliente_id=client_a["cliente_id"]), now=parse_datetime("2026-08-10T10:20:00+00:00"))
        summary = period_summary(connection, filters, now=parse_datetime("2026-08-10T11:00:00+00:00"))
        loss_payload = losses(connection, filters, now=parse_datetime("2026-08-10T11:00:00+00:00"))
        intel = intelligence(connection, filters, now=parse_datetime("2026-08-10T11:00:00+00:00"))
        b_summary = period_summary(
            connection,
            ReadModelFilters(
                cliente_id=client_b["cliente_id"],
                start=parse_datetime("2026-08-10T09:00:00+00:00"),
                end=parse_datetime("2026-08-10T11:00:00+00:00"),
            ),
            now=parse_datetime("2026-08-10T11:00:00+00:00"),
        )

    assert acknowledged["workflow_status"] == "acknowledged"
    assert resolved["workflow_status"] == "resolved"
    assert detail["status"] == "closed"
    assert detail["duracao"] == 720
    assert detail["midia_path"] == evidence_path
    assert detail["observed_context"]["operator_present_seconds"] in {None, 0}
    assert detail["human_context"]["confirmed_cause"] == "falta de material"
    assert detail["human_context"]["action_taken"] == "abastecimento solicitado"
    assert current["total_open_events"] == 0
    assert summary["total_events"] == 1
    assert summary["total_duration_seconds"] == 720
    assert summary["event_uuids"] == [event["event_uuid"]]
    assert summary["confirmed_causes"][0]["key"] == "falta de material"
    assert loss_payload["by_asset"][0]["key"] == client_a["asset_id"]
    assert event["event_uuid"] in loss_payload["by_asset"][0]["event_uuids"]
    assert intel["data_quality"]["classified_events"] == 1
    assert event["event_uuid"] in intel["traceability"]["event_uuids"]
    assert any(event["event_uuid"] in item["event_uuids"] for item in intel["attention"])
    assert b_summary["total_events"] == 0

    with patch.object(api_module, "connect", test_connect), patch.object(api_module, "ROOT", test_root), patch.object(api_module, "EVIDENCE_DIR", test_root / "data" / "evidence"):
        client = TestClient(api)
        assert client.post("/auth/login", json={"email": client_a["email"], "senha": "senha-segura"}).status_code == 200
        a_events = client.get("/eventos").json()
        evidence_response = client.get(f"/eventos/{event_id}/evidence")
        client.post("/auth/logout")
        assert client.post("/auth/login", json={"email": client_b["email"], "senha": "senha-segura"}).status_code == 200
        b_events = client.get("/eventos").json()
        b_detail = client.get(f"/eventos/{event_id}/detail")
        b_evidence = client.get(f"/eventos/{event_id}/evidence")
        b_deliveries = client.get("/alert-deliveries").json()

    assert len(a_events) == 1
    assert evidence_response.status_code == 200
    assert b_events == []
    assert b_detail.status_code == 403
    assert b_evidence.status_code == 403
    assert b_deliveries == []


def test_operational_chain_failure_paths_preserve_event_outbox_and_pending_delivery(tmp_path: Path) -> None:
    db_path = tmp_path / "failure-chain.sqlite3"

    def test_connect(_path=None):
        return connect(db_path)

    with test_connect() as connection:
        init_db(connection)
        context = _create_chain_context(connection, client_name="Cliente Falha", email="falha@campex.test")
        event_id = criar_evento_machine_operational(
            connection,
            cliente_id=context["cliente_id"],
            unidade_id=context["unidade_id"],
            camera_id=context["camera_id"],
            machine_monitor_id=context["monitor_id"],
            tipo="machine_stoppage",
            inicio="2026-08-10T12:00:00+00:00",
            motion_level=0.5,
            operator_present_start=False,
            confidence=0.7,
            midia_path=None,
            track_ids=[],
            severidade="medium",
            metadata={"evidence_error": "snapshot unavailable"},
        )

    with (
        patch.object(api_module, "connect", test_connect),
        patch.object(alerts_module, "connect", test_connect),
        patch.dict(os.environ, {"CAMPEX_EMAIL_MODE": "invalid", "CAMPEX_EMAIL_MAX_ATTEMPTS": "1", "CAMPEX_DIRECT_EVENT_EMAILS": "true"}),
    ):
        enqueue_event_alert(event_id)
        _wait_for_delivery_status(test_connect, event_id, {"failed"})

    with test_connect() as connection:
        event_before = obter_evento(connection, event_id)
        outbox_before = connection.execute("SELECT COUNT(*) AS total FROM sync_outbox WHERE event_uuid = ?", (event_before["event_uuid"],)).fetchone()["total"]
        delivery_before = listar_alert_deliveries(connection, evento_id=event_id)[0]

    with test_connect() as connection:
        event_after_restart = obter_evento(connection, event_id)
        outbox_after_restart = connection.execute("SELECT COUNT(*) AS total FROM sync_outbox WHERE event_uuid = ?", (event_after_restart["event_uuid"],)).fetchone()["total"]
        delivery_after_restart = listar_alert_deliveries(connection, evento_id=event_id)[0]
        fechar_evento_machine_stoppage(connection, event_id, "2026-08-10T12:04:00+00:00", 240)
        event_closed = obter_evento(connection, event_id)

    assert event_before["status"] == "open"
    assert event_after_restart["id"] == event_id
    assert outbox_before == 1
    assert outbox_after_restart == 1
    assert delivery_before["id"] == delivery_after_restart["id"]
    assert delivery_after_restart["status"] == "failed"
    assert event_closed["status"] == "closed"
    assert event_closed["duracao"] == 240
