from __future__ import annotations

import tempfile
from pathlib import Path

from app.analytics import compute_summary, parse_dt, timeline
from app.database import connect, init_db
from app.event_taxonomy import EVENT_FAMILY_ABSENCE, EVENT_FAMILY_INTERRUPTION, EVENT_FAMILY_UNKNOWN, classify_event_type
from app.event_workflow import event_detail
from app.models import criar_camera, criar_cliente, criar_unidade, listar_eventos_filtrados, obter_evento, registrar_evento


def make_context():
    temp_dir = tempfile.TemporaryDirectory()
    db_path = Path(temp_dir.name) / "taxonomy.sqlite3"
    connection = connect(db_path)
    init_db(connection)
    cliente_id = criar_cliente(connection, "Cliente")
    unidade_id = criar_unidade(connection, cliente_id, "Unidade")
    camera_id = criar_camera(connection, unidade_id, "A6", cliente_id=cliente_id)
    return temp_dir, db_path, connection, cliente_id, unidade_id, camera_id


def test_known_event_types_have_explicit_business_family() -> None:
    assert classify_event_type("machine_stoppage").event_family == EVENT_FAMILY_INTERRUPTION
    assert classify_event_type("machine_stopped_with_operator").event_family == EVENT_FAMILY_INTERRUPTION
    assert classify_event_type("workstation_unattended").event_family == EVENT_FAMILY_ABSENCE


def test_unknown_and_legacy_adjacent_event_types_are_not_invented() -> None:
    ambiguous = classify_event_type("ambiguous_custom_event")
    restricted_area = classify_event_type("restricted_area_occupied")
    restricted_zone = classify_event_type("restricted_zone_occupied")

    assert ambiguous.event_family == EVENT_FAMILY_UNKNOWN
    assert ambiguous.event_subtype is None
    assert restricted_area.event_family == EVENT_FAMILY_UNKNOWN
    assert restricted_area.event_subtype is None
    assert restricted_zone.event_family == EVENT_FAMILY_UNKNOWN
    assert restricted_zone.event_subtype is None


def test_event_creation_preserves_technical_type_and_adds_taxonomy() -> None:
    temp_dir, _db_path, connection, cliente_id, unidade_id, camera_id = make_context()
    with temp_dir, connection:
        event_id = registrar_evento(connection, cliente_id, unidade_id, camera_id, "machine_stoppage")
        event = obter_evento(connection, event_id)
        detail = event_detail(connection, event_id)

    assert event["tipo"] == "machine_stoppage"
    assert event["event_family"] == "interruption"
    assert event["event_subtype"] == "machine_stoppage"
    assert detail["technical_type"] == "machine_stoppage"
    assert detail["business_taxonomy"]["event_family"] == "interruption"


def test_unknown_event_creation_keeps_unknown_family_without_renaming_type() -> None:
    temp_dir, _db_path, connection, cliente_id, unidade_id, camera_id = make_context()
    with temp_dir, connection:
        event_id = registrar_evento(connection, cliente_id, unidade_id, camera_id, "sensor_vendor_specific")
        event = obter_evento(connection, event_id)

    assert event["tipo"] == "sensor_vendor_specific"
    assert event["event_family"] == "unknown"
    assert event["event_subtype"] is None


def test_restricted_area_legacy_event_keeps_unknown_taxonomy() -> None:
    temp_dir, _db_path, connection, cliente_id, unidade_id, camera_id = make_context()
    with temp_dir, connection:
        event_id = registrar_evento(connection, cliente_id, unidade_id, camera_id, "restricted_area_occupied")
        event = obter_evento(connection, event_id)

    assert event["tipo"] == "restricted_area_occupied"
    assert event["event_family"] == "unknown"
    assert event["event_subtype"] is None


def test_old_events_are_backfilled_when_mapping_is_known() -> None:
    temp_dir, db_path, connection, cliente_id, unidade_id, camera_id = make_context()
    with temp_dir:
        connection.execute(
            """
            INSERT INTO eventos (id, event_uuid, cliente_id, unidade_id, camera_id, tipo, inicio)
            VALUES ('evt_old', 'evt-uuid-old', ?, ?, ?, 'workstation_unattended', '2026-08-07T10:00:00+00:00')
            """,
            (cliente_id, unidade_id, camera_id),
        )
        connection.commit()
        connection.close()
        reopened = connect(db_path)
        try:
            init_db(reopened)
            event = obter_evento(reopened, "evt_old")
        finally:
            reopened.close()

    assert event["tipo"] == "workstation_unattended"
    assert event["event_family"] == "absence"
    assert event["event_subtype"] == "work_area_unattended"


def test_legacy_restricted_area_flow_backfill_is_cleared() -> None:
    temp_dir, db_path, connection, cliente_id, unidade_id, camera_id = make_context()
    with temp_dir:
        connection.execute(
            """
            INSERT INTO eventos (
                id, event_uuid, cliente_id, unidade_id, camera_id, tipo, inicio,
                event_family, event_subtype
            ) VALUES (
                'evt_restricted_old', 'evt-uuid-restricted-old', ?, ?, ?,
                'restricted_area_occupied', '2026-08-07T10:00:00+00:00',
                'flow', 'restricted_zone_entry'
            )
            """,
            (cliente_id, unidade_id, camera_id),
        )
        connection.commit()
        connection.close()
        reopened = connect(db_path)
        try:
            init_db(reopened)
            event = obter_evento(reopened, "evt_restricted_old")
        finally:
            reopened.close()

    assert event["tipo"] == "restricted_area_occupied"
    assert event["event_family"] is None
    assert event["event_subtype"] is None


def test_filter_and_analytics_group_by_event_family() -> None:
    temp_dir, _db_path, connection, cliente_id, unidade_id, camera_id = make_context()
    with temp_dir, connection:
        registrar_evento(
            connection,
            cliente_id,
            unidade_id,
            camera_id,
            "machine_stoppage",
            inicio="2026-08-07T10:00:00+00:00",
            fim="2026-08-07T10:05:00+00:00",
            duracao=300,
        )
        registrar_evento(
            connection,
            cliente_id,
            unidade_id,
            camera_id,
            "workstation_unattended",
            inicio="2026-08-07T10:10:00+00:00",
            fim="2026-08-07T10:12:00+00:00",
            duracao=120,
        )
        absence_events = listar_eventos_filtrados(connection, event_family="absence")
        summary = compute_summary(
            connection,
            machine_id=None,
            camera_id=camera_id,
            start=parse_dt("2026-08-07T09:00:00+00:00"),
            end=parse_dt("2026-08-07T11:00:00+00:00"),
        )
        absence_timeline = timeline(
            connection,
            machine_id=None,
            camera_id=camera_id,
            event_family="absence",
            start=parse_dt("2026-08-07T09:00:00+00:00"),
            end=parse_dt("2026-08-07T11:00:00+00:00"),
        )

    assert [event["tipo"] for event in absence_events] == ["workstation_unattended"]
    assert summary["events_by_family"]["interruption"] == 1
    assert summary["events_by_family"]["absence"] == 1
    assert len(absence_timeline["segments"]) == 1
    assert absence_timeline["segments"][0]["event_family"] == "absence"
