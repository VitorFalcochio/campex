from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import api
from app.database import connect, init_db
from app.models import criar_camera, criar_cliente, criar_unidade, registrar_evento
from app.operational_context import criar_operational_area, criar_operational_asset, criar_operational_process


OFFICIAL_AREAS = {
    "/operations-view": "Visão geral",
    "/events": "Eventos",
    "/insights": "Intelligence",
    "/live-grid": "Ao vivo",
    "/settings/cameras": "Configurações",
}


def _workspace_with_event():
    temp_dir = tempfile.TemporaryDirectory()
    db_path = Path(temp_dir.name) / "campex-v0.sqlite3"
    connection = connect(db_path)
    init_db(connection)
    cliente_id = criar_cliente(connection, "Cliente")
    unidade_id = criar_unidade(connection, cliente_id, "Fábrica")
    area_id = criar_operational_area(connection, cliente_id=cliente_id, unidade_id=unidade_id, nome="Corte")
    process_id = criar_operational_process(connection, cliente_id=cliente_id, unidade_id=unidade_id, area_id=area_id, nome="Linha A6")
    asset_id = criar_operational_asset(connection, cliente_id=cliente_id, unidade_id=unidade_id, area_id=area_id, process_id=process_id, nome="A6")
    camera_id = criar_camera(connection, unidade_id, "Câmera A6", cliente_id=cliente_id, area_context_id=area_id, process_id=process_id, asset_id=asset_id)
    event_id = registrar_evento(
        connection,
        cliente_id,
        unidade_id,
        camera_id,
        "machine_stoppage",
        inicio="2026-08-07T09:00:00+00:00",
        fim="2026-08-07T09:10:00+00:00",
        duracao=600,
        event_uuid="evt-campex-v0-a6",
    )
    connection.execute(
        """
        UPDATE eventos
        SET site_id = ?, area_context_id = ?, process_id = ?, asset_id = ?, status = 'closed'
        WHERE id = ?
        """,
        (unidade_id, area_id, process_id, asset_id, event_id),
    )
    connection.commit()
    connection.close()
    return temp_dir, db_path


def test_campex_v0_official_areas_are_navigable_without_legacy_primary_nav() -> None:
    client = TestClient(api)

    for route, label in OFFICIAL_AREAS.items():
        logged_out = client.get(route, follow_redirects=False)
        assert logged_out.status_code == 303, route
        assert logged_out.headers["location"].startswith("/login?next="), route

        with patch("app.api._request_has_valid_session", return_value=True):
            response = client.get(route)
        assert response.status_code == 200, route
        assert "text/html" in response.headers.get("content-type", "")
        assert label in response.text
        assert 'href="/operations-view"' in response.text
        assert 'href="/events"' in response.text
        assert 'href="/insights"' in response.text
        assert 'href="/reports"' in response.text
        assert 'href="/live-grid"' in response.text
        assert 'href="/settings/cameras"' in response.text

    with patch("app.api._request_has_valid_session", return_value=True):
        shell = client.get("/operations-view").text
    primary_nav = shell[shell.index('<nav class="cx-nav') : shell.index('<div class="cx-account">')]
    for legacy in ["Home", "Câmeras", "Alertas", "Evidências", "Regras"]:
        assert legacy not in primary_nav


def test_campex_v0_same_event_uuid_flows_through_events_operations_intelligence_and_live() -> None:
    temp_dir, db_path = _workspace_with_event()
    with temp_dir, patch("app.api.connect", lambda: connect(db_path)):
        client = TestClient(api)
        events = client.get("/eventos").json()
        operations = client.get(
            "/operations/read-model/summary",
            params={"start": "2026-08-07T00:00:00+00:00", "end": "2026-08-08T00:00:00+00:00"},
        ).json()
        intelligence = client.get(
            "/operations/read-model/insights",
            params={"start": "2026-08-07T00:00:00+00:00", "end": "2026-08-08T00:00:00+00:00"},
        ).json()
        live = client.get("/live/overview").json()

    assert events[0]["event_uuid"] == "evt-campex-v0-a6"
    assert "evt-campex-v0-a6" in operations["event_uuids"]
    assert "evt-campex-v0-a6" in intelligence["traceability"]["event_uuids"]
    assert live["cameras"][0]["status"]["context"]["primary_label"] == "A6"
    assert live["cameras"][0]["status"]["context"]["path_label"] == "Corte → Linha A6"


def test_campex_v0_setup_exposes_supported_capabilities_without_fake_wait_or_flow() -> None:
    temp_dir, db_path = _workspace_with_event()
    with temp_dir, patch("app.api.connect", lambda: connect(db_path)):
        payload = TestClient(api).get("/setup/operation").json()

    capabilities = {item["id"]: item for item in payload["capabilities"]}
    assert capabilities["interruption"]["supported"] is True
    assert capabilities["absence"]["supported"] is True
    assert capabilities["wait"]["supported"] is False
    assert capabilities["flow"]["supported"] is False
