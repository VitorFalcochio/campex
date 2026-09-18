from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.analytics import confirmed_cause_summary, parse_dt
from app.api import api
from app.auth import create_user
from app.database import connect, init_db
from app.event_workflow import acknowledge_event, event_detail, resolve_event, update_human_context
from app.models import criar_camera, criar_cliente, criar_unidade, obter_evento, registrar_evento


def make_db():
    temp_dir = tempfile.TemporaryDirectory()
    db_path = Path(temp_dir.name) / "workflow.sqlite3"
    connection = connect(db_path)
    init_db(connection)
    cliente_id = criar_cliente(connection, "Cliente")
    unidade_id = criar_unidade(connection, cliente_id, "Unidade")
    camera_id = criar_camera(connection, unidade_id, "A6", cliente_id=cliente_id)
    event_id = registrar_evento(
        connection,
        cliente_id,
        unidade_id,
        camera_id,
        "machine_stoppage",
        inicio="2026-08-07T10:00:00+00:00",
        fim="2026-08-07T10:19:00+00:00",
        duracao=1140,
        operador_presente=False,
        confianca=0.88,
        midia_path="data/evidence/a6.jpg",
    )
    return temp_dir, db_path, connection, cliente_id, camera_id, event_id


def test_open_event_can_be_acknowledged_without_changing_physical_status() -> None:
    temp_dir, _db_path, connection, _cliente_id, _camera_id, event_id = make_db()
    with temp_dir, connection:
        connection.execute("UPDATE eventos SET status = 'open', fim = NULL, duracao = NULL WHERE id = ?", (event_id,))
        connection.commit()
        acknowledged = acknowledge_event(connection, event_id, actor="gestor@campex.test", human_notes="em análise", at="2026-08-07T10:05:00+00:00")

    assert acknowledged["status"] == "open"
    assert acknowledged["workflow_status"] == "acknowledged"
    assert acknowledged["acknowledged_by"] == "gestor@campex.test"


def test_closed_event_can_remain_new_then_be_resolved() -> None:
    temp_dir, _db_path, connection, _cliente_id, _camera_id, event_id = make_db()
    with temp_dir, connection:
        closed = obter_evento(connection, event_id)
        original_duration = closed["duracao"]
        original_evidence = closed["midia_path"]
        detail_before = event_detail(connection, event_id)
        resolved = resolve_event(
            connection,
            event_id,
            actor="supervisor@campex.test",
            confirmed_cause="falta de material",
            action_taken="abastecimento solicitado",
            human_notes="pedido aberto",
            at="2026-08-07T11:00:00+00:00",
        )
        detail_after = event_detail(connection, event_id)

    assert detail_before["status"] == "closed"
    assert detail_before["workflow_status"] == "new"
    assert resolved["status"] == "closed"
    assert resolved["workflow_status"] == "resolved"
    assert resolved["duracao"] == original_duration
    assert resolved["midia_path"] == original_evidence
    assert detail_after["human_context"]["confirmed_cause"] == "falta de material"
    assert detail_after["human_context"]["action_taken"] == "abastecimento solicitado"
    assert detail_after["observed_context"]["duracao"] == 1140


def test_human_context_does_not_change_observed_context_and_persists_after_restart() -> None:
    temp_dir, db_path, connection, _cliente_id, _camera_id, event_id = make_db()
    with temp_dir:
        before = event_detail(connection, event_id)["observed_context"]
        update_human_context(
            connection,
            event_id,
            confirmed_cause="setup",
            action_taken="ajuste feito",
            human_notes="confirmado pelo turno",
            actor="lider@campex.test",
            at="2026-08-07T10:40:00+00:00",
        )
        connection.close()
        reopened = connect(db_path)
        try:
            after = event_detail(reopened, event_id)
        finally:
            reopened.close()

    assert after["observed_context"] == before
    assert after["human_context"]["confirmed_cause"] == "setup"
    assert after["human_context"]["action_taken"] == "ajuste feito"


def test_analytics_groups_by_confirmed_cause() -> None:
    temp_dir, _db_path, connection, _cliente_id, _camera_id, event_id = make_db()
    with temp_dir, connection:
        update_human_context(connection, event_id, confirmed_cause="falta de material", action_taken="abastecer")
        grouped = confirmed_cause_summary(
            connection,
            start=parse_dt("2026-08-07T09:00:00+00:00"),
            end=parse_dt("2026-08-07T12:00:00+00:00"),
        )

    assert grouped[0]["confirmed_cause"] == "falta de material"
    assert grouped[0]["total_events"] == 1
    assert grouped[0]["total_duration_seconds"] == 1140


def test_event_workflow_api_endpoints() -> None:
    temp_dir, db_path, connection, cliente_id, _camera_id, event_id = make_db()
    with temp_dir:
        create_user(connection, "gestor@example.com", "senha", "admin_cliente", cliente_id)
        connection.close()

        def test_connect(_path=None):
            return connect(db_path)

        from unittest.mock import patch

        with patch("app.api.connect", test_connect):
            client = TestClient(api)
            client.post("/auth/login", json={"email": "gestor@example.com", "senha": "senha"})
            ack = client.post(f"/eventos/{event_id}/acknowledge", json={"human_notes": "vou analisar"})
            human = client.patch(f"/eventos/{event_id}/human-context", json={"confirmed_cause": "falta de material", "action_taken": "acionar abastecimento"})
            resolved = client.post(f"/eventos/{event_id}/resolve", json={"human_notes": "finalizado"})
            detail = client.get(f"/eventos/{event_id}/detail")

    assert ack.status_code == 200
    assert human.status_code == 200
    assert resolved.status_code == 200
    assert detail.status_code == 200
    assert detail.json()["status"] == "closed"
    assert detail.json()["workflow_status"] == "resolved"
    assert detail.json()["human_context"]["confirmed_cause"] == "falta de material"
