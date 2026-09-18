from __future__ import annotations

import tempfile
from pathlib import Path

from app.database import connect, init_db
from app.models import (
    criar_camera,
    criar_cliente,
    criar_evento_machine_stoppage,
    criar_machine_monitor,
    criar_unidade,
    listar_eventos_filtrados,
    obter_evento,
    registrar_operational_sample,
)
from app.operational_context import (
    apply_context_to_camera,
    criar_operational_area,
    criar_operational_asset,
    criar_operational_process,
    resolve_context,
)


def make_connection():
    temp_dir = tempfile.TemporaryDirectory()
    db_path = Path(temp_dir.name) / "context.sqlite3"
    connection = connect(db_path)
    init_db(connection)
    return temp_dir, db_path, connection


def test_create_hierarchy_camera_asset_event_and_sample_share_context() -> None:
    temp_dir, _db_path, connection = make_connection()
    with temp_dir, connection:
        cliente_id = criar_cliente(connection, "Cliente")
        site_id = criar_unidade(connection, cliente_id, "Fabrica")
        area_id = criar_operational_area(connection, cliente_id=cliente_id, unidade_id=site_id, nome="Corte")
        process_id = criar_operational_process(connection, cliente_id=cliente_id, unidade_id=site_id, area_id=area_id, nome="Linha A6")
        asset_id = criar_operational_asset(
            connection,
            cliente_id=cliente_id,
            unidade_id=site_id,
            area_id=area_id,
            process_id=process_id,
            nome="Posto A6",
            tipo="workstation",
        )
        camera_id = criar_camera(connection, site_id, "A6", cliente_id=cliente_id)
        apply_context_to_camera(connection, camera_id, area_context_id=area_id, process_id=process_id, asset_id=asset_id)
        monitor_id = criar_machine_monitor(
            connection,
            cliente_id,
            site_id,
            camera_id,
            "Posto A6",
            [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.1}, {"x": 0.9, "y": 0.9}],
            [{"x": 0.1, "y": 0.1}, {"x": 0.5, "y": 0.1}, {"x": 0.5, "y": 0.5}],
            asset_id=asset_id,
            area_context_id=area_id,
            process_id=process_id,
        )
        event_id = criar_evento_machine_stoppage(
            connection,
            cliente_id=cliente_id,
            unidade_id=site_id,
            camera_id=camera_id,
            machine_monitor_id=monitor_id,
            inicio="2026-08-07T10:00:00+00:00",
            motion_level=2.0,
            operator_present_start=False,
            confidence=0.8,
            midia_path="data/evidence/a6.jpg",
            track_ids=[],
        )
        registrar_operational_sample(
            connection,
            sample_uuid="sample-a6-001",
            tenant_id=cliente_id,
            unit_id=site_id,
            camera_id=camera_id,
            machine_id=monitor_id,
            machine_state="STOPPED",
            operator_present=False,
            activity_score=2.0,
            confidence=0.8,
            capture_fps=15.0,
            inference_fps=5.0,
            frames_analyzed=20,
            camera_online=True,
            sample_at="2026-08-07T10:00:01+00:00",
        )

        event = obter_evento(connection, event_id)
        sample = connection.execute("SELECT * FROM operational_samples WHERE sample_uuid = 'sample-a6-001'").fetchone()
        context = resolve_context(connection, camera_id=camera_id, machine_monitor_id=monitor_id)

    assert context["site_id"] == site_id
    assert context["area_context_id"] == area_id
    assert context["process_id"] == process_id
    assert context["asset_id"] == asset_id
    assert event["site_id"] == site_id
    assert event["area_context_id"] == area_id
    assert event["process_id"] == process_id
    assert event["asset_id"] == asset_id
    assert sample["site_id"] == site_id
    assert sample["area_context_id"] == area_id
    assert sample["process_id"] == process_id
    assert sample["asset_id"] == asset_id


def test_event_filters_by_site_area_process_and_asset_and_restart_keeps_links() -> None:
    temp_dir, db_path, connection = make_connection()
    with temp_dir:
        with connection:
            cliente_id = criar_cliente(connection, "Cliente")
            site_id = criar_unidade(connection, cliente_id, "Fabrica")
            area_id = criar_operational_area(connection, cliente_id=cliente_id, unidade_id=site_id, nome="Corte")
            process_id = criar_operational_process(connection, cliente_id=cliente_id, unidade_id=site_id, area_id=area_id, nome="Linha A6")
            asset_id = criar_operational_asset(connection, cliente_id=cliente_id, unidade_id=site_id, area_id=area_id, process_id=process_id, nome="A6")
            camera_id = criar_camera(connection, site_id, "A6", cliente_id=cliente_id, area_context_id=area_id, process_id=process_id, asset_id=asset_id)
            monitor_id = criar_machine_monitor(
                connection,
                cliente_id,
                site_id,
                camera_id,
                "A6",
                [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.1}, {"x": 0.9, "y": 0.9}],
                [{"x": 0.1, "y": 0.1}, {"x": 0.5, "y": 0.1}, {"x": 0.5, "y": 0.5}],
            )
            event_id = criar_evento_machine_stoppage(
                connection,
                cliente_id=cliente_id,
                unidade_id=site_id,
                camera_id=camera_id,
                machine_monitor_id=monitor_id,
                inicio="2026-08-07T10:00:00+00:00",
                motion_level=2.0,
                operator_present_start=False,
                confidence=0.8,
                midia_path=None,
                track_ids=[],
            )
        reopened = connect(db_path)
        try:
            init_db(reopened)
            by_site = listar_eventos_filtrados(reopened, site_id=site_id)
            by_area = listar_eventos_filtrados(reopened, area_context_id=area_id)
            by_process = listar_eventos_filtrados(reopened, process_id=process_id)
            by_asset = listar_eventos_filtrados(reopened, asset_id=asset_id)
            event = obter_evento(reopened, event_id)
        finally:
            reopened.close()

    assert [event["id"] for event in by_site] == [event_id]
    assert [event["id"] for event in by_area] == [event_id]
    assert [event["id"] for event in by_process] == [event_id]
    assert [event["id"] for event in by_asset] == [event_id]
    assert event["asset_id"] == asset_id


def test_legacy_camera_without_operational_context_still_resolves_site() -> None:
    temp_dir, _db_path, connection = make_connection()
    with temp_dir, connection:
        cliente_id = criar_cliente(connection, "Cliente")
        site_id = criar_unidade(connection, cliente_id, "Fabrica")
        camera_id = criar_camera(connection, site_id, "Camera antiga", cliente_id=cliente_id)
        event_id = criar_evento_machine_stoppage(
            connection,
            cliente_id=cliente_id,
            unidade_id=site_id,
            camera_id=camera_id,
            machine_monitor_id="mach_legacy",
            inicio="2026-08-07T10:00:00+00:00",
            motion_level=1.0,
            operator_present_start=False,
            confidence=0.7,
            midia_path=None,
            track_ids=[],
        )
        event = obter_evento(connection, event_id)
        context = resolve_context(connection, camera_id=camera_id)

    assert context["site_id"] == site_id
    assert context["area_context_id"] is None
    assert context["process_id"] is None
    assert event["site_id"] == site_id
