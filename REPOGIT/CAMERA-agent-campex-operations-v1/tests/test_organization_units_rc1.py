from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import api as api_module
from app.api import api
from app.auth import create_user
from app.database import connect, init_db
from app.models import criar_cliente, criar_unidade


def _isolated_client(tmp_path: Path):
    db_path = tmp_path / "organization-units-rc1.sqlite3"

    def test_connect(_path=None):
        return connect(db_path)

    with test_connect() as connection:
        init_db(connection)
    patcher = patch.object(api_module, "connect", test_connect)
    patcher.start()
    return TestClient(api), db_path, patcher, test_connect


def _login_admin_cliente(client: TestClient, test_connect, cliente_id: str, email: str = "admin@cliente.test") -> None:
    with test_connect() as connection:
        create_user(connection, email, "senha-segura", "admin_cliente", cliente_id, "Admin Cliente")
    response = client.post("/auth/login", json={"email": email, "senha": "senha-segura"})
    assert response.status_code == 200


def test_edit_organization_updates_current_client_without_duplicate(tmp_path: Path) -> None:
    client, db_path, patcher, test_connect = _isolated_client(tmp_path)
    try:
        with test_connect() as connection:
            cliente_id = criar_cliente(connection, "FL Plásticos", documento="old")
            criar_unidade(connection, cliente_id, "Fábrica Rio Preto")
        _login_admin_cliente(client, test_connect, cliente_id)

        response = client.patch(
            f"/clientes/{cliente_id}",
            json={"nome": "FL Plásticos Industrial", "documento": "novo"},
        )

        assert response.status_code == 200
        assert response.json()["id"] == cliente_id
        assert response.json()["nome"] == "FL Plásticos Industrial"
        assert response.json()["documento"] == "novo"
        with connect(db_path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM clientes").fetchone()[0] == 1
    finally:
        patcher.stop()


def test_admin_cliente_cannot_edit_other_tenant_organization(tmp_path: Path) -> None:
    client, db_path, patcher, test_connect = _isolated_client(tmp_path)
    try:
        with test_connect() as connection:
            tenant_a = criar_cliente(connection, "Empresa A")
            tenant_b = criar_cliente(connection, "Empresa B")
            criar_unidade(connection, tenant_a, "Unidade A")
            criar_unidade(connection, tenant_b, "Unidade B")
        _login_admin_cliente(client, test_connect, tenant_a)

        response = client.patch(f"/clientes/{tenant_b}", json={"nome": "Tentativa"})

        assert response.status_code == 403
        with connect(db_path) as connection:
            row = connection.execute("SELECT nome FROM clientes WHERE id = ?", (tenant_b,)).fetchone()
            assert row["nome"] == "Empresa B"
    finally:
        patcher.stop()


def test_organization_with_two_units_returns_both_for_same_tenant(tmp_path: Path) -> None:
    client, _db_path, patcher, test_connect = _isolated_client(tmp_path)
    try:
        with test_connect() as connection:
            cliente_id = criar_cliente(connection, "FL Plásticos")
            criar_unidade(connection, cliente_id, "Fábrica Rio Preto")
            criar_unidade(connection, cliente_id, "Fábrica Mirassol")
        _login_admin_cliente(client, test_connect, cliente_id)

        response = client.get("/unidades")

        assert response.status_code == 200
        assert {unit["nome"] for unit in response.json()} == {"Fábrica Rio Preto", "Fábrica Mirassol"}
        assert {unit["cliente_id"] for unit in response.json()} == {cliente_id}
    finally:
        patcher.stop()


def test_setup_frontend_uses_explicit_active_unit_not_known_units_first_item() -> None:
    script = Path("frontend/app.js").read_text(encoding="utf-8")

    assert "let activeUnitId = null" in script
    assert "campex_active_unit_id" in script
    assert "function resolveActiveUnit()" in script
    assert "function setActiveUnit(unitId)" in script
    assert "knownUnits[0]" not in script
    assert "window.addEventListener(\"campex:set-active-unit\"" in script


def test_workspace_switcher_lists_units_and_changes_active_unit() -> None:
    script = Path("frontend/shell.js").read_text(encoding="utf-8")

    assert "workspace.units" in script
    assert "data-popover-action=\"${sanitize(item.action)}\"" in script
    assert "data-unit-id" in script
    assert "campex:set-active-unit" in script
    assert "campex:workspace-context" in script
    assert "Configurar unidades" in script
    assert "Configurar organização" not in script
