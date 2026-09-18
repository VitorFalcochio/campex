from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.auth import create_user
from cloud import database as cloud_database
from cloud.api import api as cloud_api


def _client(tmp_path: Path) -> TestClient:
    cloud_database.DATABASE_URL = ""
    cloud_database.SQLITE_CLOUD_PATH = tmp_path / "cloud-unified.sqlite3"
    return TestClient(cloud_api)


def _login_admin_campex(client: TestClient) -> None:
    with cloud_database.connect() as db:
        cloud_database.init_cloud_db(db)
        create_user(
            db,
            email="admin@campex.test",
            password="SenhaCampex123",
            role="admin_campex",
            nome="Admin",
        )
    response = client.post(
        "/auth/login",
        json={"email": "admin@campex.test", "senha": "SenhaCampex123"},
    )
    assert response.status_code == 200


def _create_tenant(client: TestClient) -> tuple[str, str]:
    cliente = client.post("/clientes", json={"nome": "FL Plásticos"})
    assert cliente.status_code == 200
    unidade = client.post(
        "/unidades",
        json={"cliente_id": cliente.json()["id"], "nome": "Fábrica Rio Preto"},
    )
    assert unidade.status_code == 200
    return cliente.json()["id"], unidade.json()["id"]


def test_cloud_frontend_routes_used_by_workspace_do_not_return_404(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _login_admin_campex(client)
    cliente_id, unidade_id = _create_tenant(client)

    static_gets = [
        "/auth/status",
        "/operations-view?view=home",
        "/operations-view",
        "/events",
        "/insights",
        "/reports",
        "/live-grid",
        "/settings/cameras",
        "/clientes",
        "/unidades",
        "/users",
        "/setup/operation",
        "/setup/readiness",
        "/cameras/estado",
        "/eventos",
        "/operations",
        "/operations/events",
        "/operations/summary",
        "/operations/timeline",
        "/operations/current-status",
        "/operations/read-model/current",
        "/operations/read-model/summary",
        "/operations/read-model/insights",
        "/operations/read-model/operational-data",
        "/visual-rules",
        "/alert-recipients",
        "/alert-deliveries",
        "/system/health",
        "/pilot/checklist",
        "/reports/tenants",
        f"/reports/schedule?tenant_id={cliente_id}",
        f"/reports/preview?tenant_id={cliente_id}",
        "/auth/oauth/google/start?next=%2Fsettings%2Fcameras",
    ]

    for route in static_gets:
        response = client.get(route)
        assert response.status_code != 404, route

    posts = [
        ("/setup/areas", {"unidade_id": unidade_id, "nome": "Corte"}),
        ("/cameras/test-connection", {"host": "10.0.0.10", "porta_rtsp": 554}),
        ("/alert-recipients", {"cliente_id": cliente_id, "nome": "Operação", "email": "ops@example.com"}),
        ("/visual-rules", {"cliente_id": cliente_id, "camera_id": "cam_cloud", "tipo_evento": "machine_stoppage"}),
    ]

    for route, payload in posts:
        response = client.post(route, json=payload)
        assert response.status_code != 404, route


def test_cloud_setup_flow_persists_operational_configuration(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _login_admin_campex(client)
    cliente_id, unidade_id = _create_tenant(client)

    area = client.post("/setup/areas", json={"unidade_id": unidade_id, "nome": "Corte"}).json()
    process = client.post(
        "/setup/processes",
        json={"area_id": area["id"], "nome": "Serra"},
    ).json()
    asset = client.post(
        "/setup/assets",
        json={"process_id": process["id"], "nome": "A6"},
    ).json()
    camera = client.post(
        "/cameras/rtsp",
        json={
            "cliente_id": cliente_id,
            "unidade_id": unidade_id,
            "nome": "Câmera A6",
            "host": "10.0.0.10",
            "porta_rtsp": 554,
        },
    ).json()["camera"]
    context = client.post(
        f"/setup/cameras/{camera['id']}/context",
        json={"asset_id": asset["id"], "process_id": process["id"], "area_context_id": area["id"]},
    )
    assert context.status_code == 200

    zone = client.post(
        f"/cameras/{camera['id']}/areas",
        json={
            "nome": "Região da máquina",
            "tipo": "machine_region",
            "pontos": [{"x": 0.1, "y": 0.1}, {"x": 0.4, "y": 0.1}, {"x": 0.4, "y": 0.4}],
        },
    )
    assert zone.status_code == 200

    monitor = client.post(
        f"/cameras/{camera['id']}/machine-monitors",
        json={
            "nome": "Monitor A6",
            "machine_polygon": [{"x": 0.1, "y": 0.1}, {"x": 0.4, "y": 0.1}, {"x": 0.4, "y": 0.4}],
            "operator_polygon": [{"x": 0.5, "y": 0.1}, {"x": 0.8, "y": 0.1}, {"x": 0.8, "y": 0.4}],
            "ativo": True,
        },
    )
    assert monitor.status_code == 200

    setup = client.get("/setup/operation")
    assert setup.status_code == 200
    payload = setup.json()
    assert payload["areas"][0]["nome"] == "Corte"
    assert payload["processes"][0]["nome"] == "Serra"
    assert payload["assets"][0]["nome"] == "A6"
    assert payload["cameras"][0]["asset_id"] == asset["id"]
    assert payload["machine_monitors"][0]["nome"] == "Monitor A6"


def test_cloud_admin_cliente_is_limited_to_own_tenant(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _login_admin_campex(client)
    tenant_a, unit_a = _create_tenant(client)
    tenant_b, unit_b = _create_tenant(client)

    with cloud_database.connect() as db:
        cloud_database.init_cloud_db(db)
        create_user(
            db,
            email="cliente@a.test",
            password="SenhaCampex123",
            role="admin_cliente",
            cliente_id=tenant_a,
            nome="Cliente A",
        )

    login = client.post(
        "/auth/login",
        json={"email": "cliente@a.test", "senha": "SenhaCampex123"},
    )
    assert login.status_code == 200

    assert client.patch(f"/clientes/{tenant_b}", json={"nome": "Hack"}).status_code == 403
    assert client.post("/setup/areas", json={"unidade_id": unit_b, "nome": "Outra"}).status_code == 403
    assert client.post("/setup/areas", json={"unidade_id": unit_a, "nome": "Minha área"}).status_code == 200
