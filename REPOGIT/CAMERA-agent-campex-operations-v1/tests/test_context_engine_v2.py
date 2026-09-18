from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api import api
from app.auth import create_user
from app.context_engine import ContextPackAccessError, ContextPackNotFoundError, build_context_pack
from app.database import connect, init_db
from app.models import criar_camera, criar_cliente, criar_unidade, registrar_evento, registrar_evidence_index, registrar_operational_sample
from app.operational_context import apply_context_to_camera, criar_operational_area, criar_operational_asset, criar_operational_process


START = "2026-08-07T10:00:00+00:00"
END = "2026-08-07T10:10:00+00:00"
NOW = datetime(2026, 8, 7, 10, 12, tzinfo=timezone.utc)


def _make_db():
    temp_dir = tempfile.TemporaryDirectory()
    db_path = Path(temp_dir.name) / "context.sqlite3"
    connection = connect(db_path)
    init_db(connection)
    cliente_id = criar_cliente(connection, "Cliente A")
    unidade_id = criar_unidade(connection, cliente_id, "Fabrica")
    area_id = criar_operational_area(connection, cliente_id=cliente_id, unidade_id=unidade_id, nome="Corte")
    process_id = criar_operational_process(connection, cliente_id=cliente_id, unidade_id=unidade_id, area_id=area_id, nome="Serra")
    asset_id = criar_operational_asset(connection, cliente_id=cliente_id, unidade_id=unidade_id, area_id=area_id, process_id=process_id, nome="A6")
    camera_id = criar_camera(connection, unidade_id, "Camera A6", cliente_id=cliente_id, rtsp_host="10.0.0.10", rtsp_username="user", rtsp_password="super-secret")
    apply_context_to_camera(connection, camera_id, area_context_id=area_id, process_id=process_id, asset_id=asset_id)
    event_id = registrar_evento(
        connection,
        cliente_id,
        unidade_id,
        camera_id,
        "machine_stoppage",
        inicio=START,
        fim=END,
        duracao=600,
        operador_presente=False,
        confianca=0.91,
        midia_path="data/evidence/a6.jpg",
        event_uuid="evt-context-a6",
    )
    connection.execute(
        """
        UPDATE eventos
        SET severidade = 'high',
            metadata_json = ?
        WHERE id = ?
        """,
        (json.dumps({"observed_context": {"machine_state": "STOPPED", "operator_present": False}}), event_id),
    )
    _sample(connection, cliente_id, unidade_id, camera_id, asset_id, "sample-before", "2026-08-07T09:59:00+00:00", "ACTIVE", True, 8.2, 0.87)
    _sample(connection, cliente_id, unidade_id, camera_id, asset_id, "sample-during", "2026-08-07T10:03:00+00:00", "STOPPED", False, 0.4, 0.92)
    _sample(connection, cliente_id, unidade_id, camera_id, asset_id, "sample-unknown", "2026-08-07T10:09:00+00:00", "UNKNOWN", None, None, 0.0, camera_online=False)
    _sample(connection, cliente_id, unidade_id, camera_id, asset_id, "sample-after", "2026-08-07T10:11:00+00:00", "ACTIVE", True, 7.9, 0.86)
    registrar_evidence_index(
        connection,
        evidence_id="evidence-a6",
        event_id=event_id,
        event_uuid="evt-context-a6",
        tenant_id=cliente_id,
        unit_id=unidade_id,
        camera_id=camera_id,
        machine_id=asset_id,
        path="data/evidence/a6.jpg",
        size_bytes=1234,
        metadata={"source": "real_frame_reference"},
    )
    connection.commit()
    return temp_dir, db_path, connection, cliente_id, unidade_id, camera_id, asset_id, event_id


def _sample(connection, tenant_id, unit_id, camera_id, asset_id, sample_uuid, sample_at, machine_state, operator_present, activity_score, confidence, camera_online=True):
    registrar_operational_sample(
        connection,
        sample_uuid=sample_uuid,
        tenant_id=tenant_id,
        unit_id=unit_id,
        camera_id=camera_id,
        machine_id=asset_id,
        machine_state=machine_state,
        operator_present=operator_present,
        activity_score=activity_score,
        confidence=confidence,
        capture_fps=14.0,
        inference_fps=5.0 if camera_online else 0.0,
        frames_analyzed=42,
        camera_online=camera_online,
        sample_at=sample_at,
        metadata={
            "people_count": 1 if operator_present else 0,
            "analysis_status": "ANALYZING" if camera_online else "FRAME_STALE",
            "signal_quality": "OK" if camera_online else "UNKNOWN",
            "canonical_observations": [
                {
                    "observation_type": "zone_occupancy",
                    "zone_id": "zone-a6",
                    "state": "OCCUPIED" if operator_present else "EMPTY",
                    "data_quality": "OBSERVED" if camera_online else "UNKNOWN",
                    "seconds_persistent": 30,
                    "rtsp_url": "rtsp://user:password@10.0.0.10/stream",
                }
            ],
        },
    )


def test_context_pack_contains_event_timeline_unknown_evidence_and_traceability() -> None:
    temp_dir, _db_path, connection, cliente_id, _unidade_id, _camera_id, _asset_id, _event_id = _make_db()
    with temp_dir, connection:
        pack = build_context_pack(connection, "evt-context-a6", tenant_id=cliente_id, now=NOW)

    assert pack["event"]["event_uuid"] == "evt-context-a6"
    assert pack["event"]["event_type"] == "machine_stoppage"
    assert pack["event"]["event_family"] == "interruption"
    assert pack["operational_context"]["asset"]["nome"] == "A6"
    assert pack["operational_context"]["process"]["nome"] == "Serra"
    assert pack["timeline"]["before"]
    assert pack["timeline"]["during"]
    assert pack["timeline"]["after"]
    assert "machine_activity" in pack["observations"]
    assert "zone_occupancy" in pack["observations"]
    assert pack["data_quality"]["unknown_sample_count"] >= 1
    assert pack["evidence"]["available"] is True
    assert pack["evidence"]["items"][0]["path"] == "data/evidence/a6.jpg"
    assert {item["sample_uuid"] for item in pack["traceability"]["sample_refs"]} >= {"sample-before", "sample-during", "sample-after"}


def test_context_pack_uses_similar_history_and_never_invents_current_cause() -> None:
    temp_dir, _db_path, connection, cliente_id, unidade_id, camera_id, _asset_id, _event_id = _make_db()
    with temp_dir, connection:
        previous_id = registrar_evento(
            connection,
            cliente_id,
            unidade_id,
            camera_id,
            "machine_stoppage",
            inicio="2026-08-06T10:00:00+00:00",
            fim="2026-08-06T10:05:00+00:00",
            duracao=300,
            event_uuid="evt-previous-a6",
        )
        connection.execute(
            """
            UPDATE eventos
            SET confirmed_cause = 'falta de material',
                action_taken = 'abastecimento solicitado',
                human_notes = 'confirmado pelo lider'
            WHERE id = ?
            """,
            (previous_id,),
        )
        connection.commit()
        pack = build_context_pack(connection, "evt-context-a6", tenant_id=cliente_id, now=NOW)

    assert pack["human_confirmed"]["confirmed_cause"] is None
    assert pack["human_confirmed"]["cause_is_human_confirmed_only"] is True
    assert pack["history"]["events"][0]["event_uuid"] == "evt-previous-a6"
    assert pack["history"]["events"][0]["confirmed_cause"] == "falta de material"


def test_context_pack_handles_event_without_evidence() -> None:
    temp_dir, _db_path, connection, cliente_id, unidade_id, camera_id, _asset_id, _event_id = _make_db()
    with temp_dir, connection:
        event_id = registrar_evento(connection, cliente_id, unidade_id, camera_id, "workstation_unattended", inicio=START, event_uuid="evt-no-evidence")
        connection.execute("UPDATE eventos SET midia_path = NULL WHERE id = ?", (event_id,))
        connection.commit()
        pack = build_context_pack(connection, "evt-no-evidence", tenant_id=cliente_id, now=NOW)

    assert pack["evidence"]["available"] is False
    assert pack["evidence"]["items"] == []


def test_context_pack_enforces_tenant_isolation_missing_events_and_determinism() -> None:
    temp_dir, _db_path, connection, cliente_id, unidade_id, camera_id, _asset_id, _event_id = _make_db()
    with temp_dir, connection:
        other_tenant = criar_cliente(connection, "Cliente B")
        other_unit = criar_unidade(connection, other_tenant, "Outra unidade")
        other_camera = criar_camera(connection, other_unit, "Camera B", cliente_id=other_tenant)
        registrar_evento(connection, other_tenant, other_unit, other_camera, "machine_stoppage", inicio=START, event_uuid="evt-other")
        first = build_context_pack(connection, "evt-context-a6", tenant_id=cliente_id, now=NOW)
        second = build_context_pack(connection, "evt-context-a6", tenant_id=cliente_id, now=NOW)

        with pytest.raises(ContextPackAccessError):
            build_context_pack(connection, "evt-other", tenant_id=cliente_id, now=NOW)
        with pytest.raises(ContextPackNotFoundError):
            build_context_pack(connection, "evt-missing", tenant_id=cliente_id, now=NOW)

    assert first == second
    dumped = json.dumps(first, ensure_ascii=False).lower()
    assert "rtsp://" not in dumped
    assert "super-secret" not in dumped
    assert "password@10.0.0.10" not in dumped


def test_context_pack_api_requires_auth_and_filters_tenant() -> None:
    temp_dir, db_path, connection, cliente_id, _unidade_id, _camera_id, _asset_id, _event_id = _make_db()
    with temp_dir:
        other_tenant = criar_cliente(connection, "Cliente B")
        other_unit = criar_unidade(connection, other_tenant, "Outra unidade")
        other_camera = criar_camera(connection, other_unit, "Camera B", cliente_id=other_tenant)
        registrar_evento(connection, other_tenant, other_unit, other_camera, "machine_stoppage", inicio=START, event_uuid="evt-other")
        create_user(connection, "gestor@example.com", "senha", "admin_cliente", cliente_id)
        connection.close()

        def test_connect(_path=None):
            return connect(db_path)

        with patch("app.api.connect", test_connect):
            client = TestClient(api)
            unauthenticated = client.get("/events/evt-context-a6/context")
            login = client.post("/auth/login", json={"email": "gestor@example.com", "senha": "senha"})
            allowed = client.get("/events/evt-context-a6/context")
            forbidden = client.get("/events/evt-other/context")
            missing = client.get("/events/evt-missing/context")

    assert unauthenticated.status_code == 401
    assert login.status_code == 200
    assert allowed.status_code == 200
    assert allowed.json()["event"]["event_uuid"] == "evt-context-a6"
    assert forbidden.status_code == 403
    assert missing.status_code == 404
