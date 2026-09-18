from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import api
from app.database import connect, init_db
from app.models import criar_camera, criar_cliente, criar_unidade


def _client_workspace():
    temp_dir = tempfile.TemporaryDirectory()
    db_path = Path(temp_dir.name) / "setup-v0.sqlite3"
    connection = connect(db_path)
    init_db(connection)
    cliente_id = criar_cliente(connection, "Cliente Piloto")
    unidade_id = criar_unidade(connection, cliente_id, "Fábrica")
    camera_id = criar_camera(connection, unidade_id, "A6", cliente_id=cliente_id, status="online")
    connection.close()
    client = TestClient(api)
    patcher = patch("app.api.connect", lambda: connect(db_path))
    patcher.start()
    return temp_dir, patcher, client, db_path, cliente_id, unidade_id, camera_id


def _polygon():
    return [
        {"x": 0.2, "y": 0.2},
        {"x": 0.8, "y": 0.2},
        {"x": 0.8, "y": 0.8},
        {"x": 0.2, "y": 0.8},
    ]


def test_setup_v0_creates_hierarchy_associates_camera_and_is_idempotent() -> None:
    temp_dir, patcher, client, db_path, cliente_id, unidade_id, camera_id = _client_workspace()
    with temp_dir:
        try:
            area = client.post("/setup/areas", json={"cliente_id": cliente_id, "unidade_id": unidade_id, "nome": "Corte"}).json()
            duplicate_area = client.post("/setup/areas", json={"cliente_id": cliente_id, "unidade_id": unidade_id, "nome": "Corte"}).json()
            process = client.post(
                "/setup/processes",
                json={"cliente_id": cliente_id, "unidade_id": unidade_id, "area_id": area["id"], "nome": "Linha A6"},
            ).json()
            asset = client.post(
                "/setup/assets",
                json={
                    "cliente_id": cliente_id,
                    "unidade_id": unidade_id,
                    "area_id": area["id"],
                    "process_id": process["id"],
                    "nome": "A6",
                },
            ).json()

            assert area["id"] == duplicate_area["id"]
            assert duplicate_area["created"] is False

            response = client.post(
                f"/setup/cameras/{camera_id}/context",
                json={"area_context_id": area["id"], "process_id": process["id"], "asset_id": asset["id"]},
            )
            assert response.status_code == 200
            assert response.json()["context"]["asset_id"] == asset["id"]

            operation = client.get("/setup/operation").json()
            camera = next(item for item in operation["cameras"] if item["id"] == camera_id)
            assert camera["asset_id"] == asset["id"]
            assert operation["asset_status"][0]["status"] == "Configuração incompleta"

            with connect(db_path) as connection:
                rows = connection.execute("SELECT COUNT(*) AS total FROM operational_areas WHERE nome = 'Corte'").fetchone()
            assert rows["total"] == 1
        finally:
            patcher.stop()


def test_setup_v0_ready_after_zones_and_monitor_persist_after_restart() -> None:
    temp_dir, patcher, client, db_path, cliente_id, unidade_id, camera_id = _client_workspace()
    with temp_dir:
        try:
            area = client.post("/setup/areas", json={"cliente_id": cliente_id, "unidade_id": unidade_id, "nome": "Corte"}).json()
            process = client.post(
                "/setup/processes",
                json={"cliente_id": cliente_id, "unidade_id": unidade_id, "area_id": area["id"], "nome": "Linha A6"},
            ).json()
            asset = client.post(
                "/setup/assets",
                json={
                    "cliente_id": cliente_id,
                    "unidade_id": unidade_id,
                    "area_id": area["id"],
                    "process_id": process["id"],
                    "nome": "A6",
                },
            ).json()
            client.post(
                f"/setup/cameras/{camera_id}/context",
                json={"area_context_id": area["id"], "process_id": process["id"], "asset_id": asset["id"]},
            )
            for area_type in ("machine_region", "operator_zone"):
                response = client.post(
                    f"/cameras/{camera_id}/areas",
                    json={"name": area_type, "area_type": area_type, "polygon": _polygon(), "active": True},
                )
                assert response.status_code == 201
            monitor = client.post(
                f"/cameras/{camera_id}/machine-monitors",
                json={
                    "nome": "A6",
                    "machine_polygon": _polygon(),
                    "operator_polygon": _polygon(),
                    "ativo": True,
                    "stop_seconds": 30,
                    "operator_absence_seconds": 300,
                    "stopped_with_operator_seconds": 120,
                },
            )
            assert monitor.status_code == 200

            operation = client.get("/setup/operation").json()
            status = next(item for item in operation["asset_status"] if item["asset_id"] == asset["id"])
            assert status["ready"] is True
            assert status["status"] == "Pronto para monitorar"

            patcher.stop()
            with patch("app.api.connect", lambda: connect(db_path)):
                restarted = TestClient(api).get("/setup/operation").json()
            restarted_status = next(item for item in restarted["asset_status"] if item["asset_id"] == asset["id"])
            assert restarted_status["ready"] is True
            assert len(restarted["monitored_areas"]) == 2
            assert len(restarted["machine_monitors"]) == 1
        finally:
            try:
                patcher.stop()
            except RuntimeError:
                pass


def test_setup_v0_frontend_contains_operational_language() -> None:
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    script = Path("frontend/app.js").read_text(encoding="utf-8")

    assert "Estrutura da operação" in html
    assert "O que a Campex deve observar?" in html
    assert "Considere ausência após" in html
    assert "Pronto para monitorar" in script
    assert "Configuração incompleta" in script
    assert "/setup/operation" in script
    assert "/setup/areas" in script
    assert "/setup/processes" in script
    assert "/setup/assets" in script
    assert "/context" in script
