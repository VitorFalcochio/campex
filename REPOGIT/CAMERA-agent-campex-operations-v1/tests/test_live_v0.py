from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import app.api as api_module
from app.api import api
from app.config import ROOT
from app.database import connect, init_db
from app.models import criar_camera, criar_cliente, criar_unidade, registrar_evento
from app.operational_context import criar_operational_area, criar_operational_asset, criar_operational_process


def _workspace_with_context():
    temp_dir = tempfile.TemporaryDirectory()
    db_path = Path(temp_dir.name) / "live-v0.sqlite3"
    connection = connect(db_path)
    init_db(connection)
    cliente_id = criar_cliente(connection, "Cliente")
    unidade_id = criar_unidade(connection, cliente_id, "Fábrica")
    area_id = criar_operational_area(connection, cliente_id=cliente_id, unidade_id=unidade_id, nome="Corte")
    process_id = criar_operational_process(connection, cliente_id=cliente_id, unidade_id=unidade_id, area_id=area_id, nome="Linha A6")
    asset_id = criar_operational_asset(connection, cliente_id=cliente_id, unidade_id=unidade_id, area_id=area_id, process_id=process_id, nome="A6")
    camera_id = criar_camera(connection, unidade_id, "Câmera A6", cliente_id=cliente_id, area_context_id=area_id, process_id=process_id, asset_id=asset_id)
    connection.close()
    return temp_dir, db_path, cliente_id, unidade_id, camera_id


def test_live_overview_prioritizes_operational_context_and_open_event() -> None:
    temp_dir, db_path, cliente_id, unidade_id, camera_id = _workspace_with_context()
    with temp_dir:
        with connect(db_path) as connection:
            event_id = registrar_evento(
                connection,
                cliente_id,
                unidade_id,
                camera_id,
                "machine_stoppage",
                inicio="2026-08-07T10:00:00+00:00",
                event_uuid="evt-live-open",
            )
            connection.execute("UPDATE eventos SET status = 'open' WHERE id = ?", (event_id,))
            connection.commit()

        with patch("app.api.connect", lambda: connect(db_path)):
            client = TestClient(api)
            response = client.get("/live/overview")

    assert response.status_code == 200
    item = response.json()["cameras"][0]
    assert item["status"]["context"]["primary_label"] == "A6"
    assert item["status"]["context"]["path_label"] == "Corte → Linha A6"
    assert item["status"]["context"]["current_event"]["event_uuid"] == "evt-live-open"
    assert item["status"]["context"]["operational_status"] == "evento_aberto"


def test_live_overview_does_not_show_closed_event_as_active() -> None:
    temp_dir, db_path, cliente_id, unidade_id, camera_id = _workspace_with_context()
    with temp_dir:
        with connect(db_path) as connection:
            event_id = registrar_evento(
                connection,
                cliente_id,
                unidade_id,
                camera_id,
                "machine_stoppage",
                inicio="2026-08-07T10:00:00+00:00",
                fim="2026-08-07T10:10:00+00:00",
                duracao=600,
                event_uuid="evt-live-closed",
            )
            connection.execute("UPDATE eventos SET status = 'closed' WHERE id = ?", (event_id,))
            connection.commit()

        with patch("app.api.connect", lambda: connect(db_path)):
            client = TestClient(api)
            response = client.get("/live/overview")

    assert response.status_code == 200
    context = response.json()["cameras"][0]["status"]["context"]
    assert context["current_event"] is None
    assert context["operational_status"] != "evento_aberto"


def test_live_v0_frontend_uses_context_and_hides_technical_priority() -> None:
    grid_script = Path(ROOT / "frontend" / "live-grid.js").read_text(encoding="utf-8")
    view_script = Path(ROOT / "frontend" / "live-view.js").read_text(encoding="utf-8")
    view_html = Path(ROOT / "frontend" / "live-view.html").read_text(encoding="utf-8")

    assert "/live/overview" in grid_script
    assert "primary_label" in grid_script
    assert "path_label" in grid_script
    assert "current_event" in grid_script
    assert "Ver evento" in grid_script
    assert "Camera ID" not in grid_script
    assert "hasOperationalContext" in grid_script
    assert "A Live mostra câmeras vinculadas a contexto operacional." in grid_script
    assert "Verifique a configuração no Setup." in grid_script
    assert "liveViewAsset" in view_script
    assert "liveCurrentEventLink" in view_script
    assert "Modo configuração" in view_html
    assert "Detalhes técnicos" in view_html
    assert "Configurar monitoramento" in view_html
    assert "Onde esta câmera está olhando?" in view_html
    assert "Paradas / interrupções" in view_html
    assert "Ausência de operador" in view_html
    assert "/setup/operation" in view_script
    assert "/setup/cameras/${currentCameraId}/context" in view_script
    assert "startMachineRegionWizard" in view_script
    assert "startOperatorZoneWizard" in view_script
    assert "saveWizardMonitor" in view_script
    assert "activateWizardMonitor" in view_script
    assert "hasOperatorContext" in view_script
    assert "Indeterminado" in view_script


def test_live_grid_page_uses_live_v0_language() -> None:
    client = TestClient(api)

    logged_out = client.get("/live-grid", follow_redirects=False)
    assert logged_out.status_code == 303
    assert logged_out.headers["location"].startswith("/login?next=")

    with patch("app.api._request_has_valid_session", return_value=True):
        response = client.get("/live-grid")

    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "Monitoramento" in response.text
    assert "workspace.js" not in response.text
