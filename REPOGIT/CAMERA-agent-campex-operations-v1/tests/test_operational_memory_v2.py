from __future__ import annotations

import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import api
from app.auth import create_user
from app.context_engine import build_context_pack
from app.database import connect
from app.event_workflow import event_detail, update_operational_memory
from app.intelligence_reasoning import ReasoningEngine
from app.recommendation_engine import RecommendationEngine
from app.models import criar_camera, criar_cliente, criar_unidade, registrar_evento
from tests.test_intelligence_reasoning_v2 import FakeProvider as FakeReasoningProvider, _make_context_db, _reasoning_payload
from tests.test_recommendation_engine_v2 import FakeRecommendationProvider, _recommendation_payload


def test_ai_hypothesis_does_not_become_confirmed_cause_without_human_action() -> None:
    temp_dir, _db_path, connection, cliente_id, _unit_id, _camera_id, event_id = _make_context_db()
    with temp_dir, connection:
        context_pack = build_context_pack(connection, "evt-reason-a6", tenant_id=cliente_id)
        reasoning = ReasoningEngine(provider=FakeReasoningProvider(), model="test-model").reason(context_pack)["reasoning"]
        detail = event_detail(connection, event_id)

    assert reasoning["hypotheses"]
    assert detail["human_context"]["confirmed_cause"] is None


def test_human_confirmation_action_feedback_and_outcome_are_persisted_and_audited() -> None:
    temp_dir, db_path, connection, cliente_id, _unit_id, _camera_id, event_id = _make_context_db()
    with temp_dir:
        updated = update_operational_memory(
            connection,
            event_id,
            actor="gestor@campex.test",
            confirmed_cause="falta de material",
            action_taken="reabastecimento",
            recommendation_id="rec-1",
            recommendation_accepted=True,
            outcome_status="resolved",
            outcome_notes="linha voltou ao ritmo normal",
            human_notes="validado no turno",
            at="2026-08-07T10:20:00+00:00",
        )
        connection.close()
        reopened = connect(db_path)
        try:
            detail = event_detail(reopened, event_id)
            audit_count = reopened.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'event.operational_memory.update'").fetchone()[0]
        finally:
            reopened.close()

    assert updated["confirmed_cause"] == "falta de material"
    assert detail["human_context"]["confirmed_cause"] == "falta de material"
    assert detail["human_context"]["confirmed_by"] == "gestor@campex.test"
    assert detail["human_context"]["action_taken"] == "reabastecimento"
    assert detail["human_context"]["recommendation_id"] == "rec-1"
    assert detail["human_context"]["recommendation_accepted"] is True
    assert detail["human_context"]["outcome_status"] == "resolved"
    assert detail["human_context"]["resolution_time_seconds"] == 1200
    assert audit_count == 1


def test_recommendation_rejection_and_unknown_or_not_resolved_outcomes_are_distinct() -> None:
    temp_dir, _db_path, connection, _cliente_id, _unit_id, _camera_id, event_id = _make_context_db()
    with temp_dir, connection:
        rejected = update_operational_memory(
            connection,
            event_id,
            actor="gestor@campex.test",
            recommendation_id="rec-2",
            recommendation_accepted=False,
            action_taken="acionar manutencao",
            outcome_status="not_resolved",
            outcome_notes="acao nao resolveu",
        )
        unknown = update_operational_memory(connection, event_id, actor="gestor@campex.test", outcome_status="unknown")

    assert rejected["recommendation_accepted"] == 0
    assert rejected["outcome_status"] == "not_resolved"
    assert rejected["resolution_time_seconds"] is None
    assert unknown["outcome_status"] == "unknown"


def test_future_similar_event_receives_previous_operational_memory_in_context_pack() -> None:
    temp_dir, _db_path, connection, cliente_id, unidade_id, camera_id, event_id = _make_context_db()
    with temp_dir, connection:
        update_operational_memory(
            connection,
            event_id,
            actor="gestor@campex.test",
            confirmed_cause="falta de material",
            action_taken="reabastecimento",
            recommendation_id="rec-1",
            recommendation_accepted=True,
            outcome_status="resolved",
            outcome_notes="resolveu",
        )
        registrar_evento(
            connection,
            cliente_id,
            unidade_id,
            camera_id,
            "machine_stoppage",
            inicio="2026-08-08T10:00:00+00:00",
            event_uuid="evt-reason-a6-future",
        )
        context_pack = build_context_pack(connection, "evt-reason-a6-future", tenant_id=cliente_id)

    previous = context_pack["history"]["events"][0]
    assert context_pack["human_confirmed"]["confirmed_cause"] is None
    assert previous["confirmed_cause"] == "falta de material"
    assert previous["action_taken"] == "reabastecimento"
    assert previous["recommendation_accepted"] is True
    assert previous["outcome_status"] == "resolved"


def test_reasoning_and_recommendation_can_consume_memory_as_support_not_current_confirmation() -> None:
    temp_dir, _db_path, connection, cliente_id, unidade_id, camera_id, event_id = _make_context_db()
    with temp_dir, connection:
        update_operational_memory(
            connection,
            event_id,
            actor="gestor@campex.test",
            confirmed_cause="falta de material",
            action_taken="reabastecimento",
            recommendation_id="rec-1",
            recommendation_accepted=True,
            outcome_status="resolved",
        )
        registrar_evento(connection, cliente_id, unidade_id, camera_id, "machine_stoppage", event_uuid="evt-reason-a6-future")
        context_pack = build_context_pack(connection, "evt-reason-a6-future", tenant_id=cliente_id)
        reasoning = ReasoningEngine(provider=FakeReasoningProvider(), model="test-model").reason(context_pack)["reasoning"]
        provider = FakeRecommendationProvider(_recommendation_payload())
        provider.result["event_uuid"] = "evt-reason-a6-future"
        recommendation = RecommendationEngine(provider=provider, model="test-model").recommend(context_pack, reasoning)["recommendation"]

    assert context_pack["human_confirmed"]["confirmed_cause"] is None
    assert reasoning["hypotheses"][0]["status"] == "POSSIBLE"
    assert recommendation["recommendations"][0]["historical_support"] == ["event_uuid:evt-reason-prev"]
    assert recommendation["recommendations"][0]["requires_human_approval"] is True


def test_tenant_isolation_for_operational_memory_endpoint_and_context_recall() -> None:
    temp_dir, db_path, connection, cliente_id, _unit_id, _camera_id, event_id = _make_context_db()
    with temp_dir:
        other_tenant = criar_cliente(connection, "Cliente B")
        other_unit = criar_unidade(connection, other_tenant, "Outra unidade")
        other_camera = criar_camera(connection, other_unit, "Camera B", cliente_id=other_tenant)
        other_event_id = registrar_evento(connection, other_tenant, other_unit, other_camera, "machine_stoppage", event_uuid="evt-memory-other")
        create_user(connection, "gestor@example.com", "senha", "admin_cliente", cliente_id)
        connection.close()

        def test_connect(_path=None):
            return connect(db_path)

        with patch("app.api.connect", test_connect):
            client = TestClient(api)
            unauthenticated = client.patch(f"/eventos/{event_id}/memory", json={"confirmed_cause": "falta de material"})
            client.post("/auth/login", json={"email": "gestor@example.com", "senha": "senha"})
            allowed = client.patch(
                f"/eventos/{event_id}/memory",
                json={
                    "confirmed_cause": "falta de material",
                    "action_taken": "reabastecimento",
                    "recommendation_id": "rec-1",
                    "recommendation_accepted": True,
                    "outcome_status": "resolved",
                },
            )
            forbidden = client.patch(f"/eventos/{other_event_id}/memory", json={"confirmed_cause": "manutencao"})

    assert unauthenticated.status_code == 401
    assert allowed.status_code == 200
    assert allowed.json()["human_context"]["confirmed_cause"] == "falta de material"
    assert forbidden.status_code == 403


def test_operational_memory_payload_has_no_secret_fields() -> None:
    temp_dir, _db_path, connection, cliente_id, _unit_id, _camera_id, event_id = _make_context_db()
    with temp_dir, connection:
        update_operational_memory(connection, event_id, actor="gestor@campex.test", confirmed_cause="falta de material", action_taken="reabastecimento")
        context_pack = build_context_pack(connection, "evt-reason-a6", tenant_id=cliente_id)

    dumped = json.dumps(context_pack, ensure_ascii=False).lower()
    assert "rtsp://" not in dumped
    assert "password" not in dumped
    assert "secret" not in dumped
