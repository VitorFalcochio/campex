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
    db_path = tmp_path / "enterprise-access.sqlite3"

    def test_connect(_path=None):
        return connect(db_path)

    with test_connect() as connection:
        init_db(connection)
    patcher = patch.object(api_module, "connect", test_connect)
    patcher.start()
    return TestClient(api, follow_redirects=False), db_path, patcher, test_connect


def _signup_payload(email: str = "joao@empresa.test") -> dict[str, str]:
    return {
        "nome": "João Silva",
        "email": email,
        "senha": "SenhaSegura123!",
        "empresa_nome": "Empresa Exemplo",
    }


def _create_admin_campex(client: TestClient, email: str = "admin@campex.test", senha: str = "senha-segura") -> dict[str, str]:
    response = client.post(
        "/first-run/complete",
        json={
            "admin_nome": "Admin Campex",
            "admin_email": email,
            "admin_senha": senha,
            "empresa_nome": "Campex Admin",
            "unidade_nome": "Unidade principal",
        },
    )
    assert response.status_code == 201
    return {"email": email, "senha": senha, "cliente_id": response.json()["cliente_id"]}


def test_public_signup_is_disabled_and_does_not_create_tenant(tmp_path: Path) -> None:
    client, db_path, patcher, _test_connect = _isolated_client(tmp_path)
    try:
        response = client.post("/auth/signup", json={**_signup_payload(), "role": "admin_campex", "cliente_id": "cli_fake"})
        assert response.status_code == 403
        assert "Cadastro público desativado" in response.json()["detail"]
        assert response.cookies.get("campex_session") is None

        with connect(db_path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM clientes").fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM unidades").fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM user_sessions").fetchone()[0] == 0
    finally:
        patcher.stop()


def test_login_page_keeps_public_signup_hidden_until_auth_status_enables_it() -> None:
    html = Path("frontend/login.html").read_text(encoding="utf-8")
    js = Path("frontend/login.js").read_text(encoding="utf-8")

    assert "Entrar na Campex" in html
    assert "Ainda não tem acesso? Solicite uma demonstração." in html
    assert 'id="publicSignupAccess"' in html
    assert 'id="signupForm"' in html
    assert 'id="signupForm" class="cx-auth-form" method="post" autocomplete="on" hidden' in html
    assert "Cadastre-se" in html
    assert "Continuar com Google" in html

    assert "auth.public_signup" in js
    assert "publicSignupAccess.hidden = !publicSignupEnabled" in js
    assert "showSignupButton.hidden = !publicSignupEnabled" in js


def test_internal_product_route_redirects_unauthenticated_user_to_login(tmp_path: Path) -> None:
    client, _db_path, patcher, _test_connect = _isolated_client(tmp_path)
    try:
        response = client.get("/operations-view")
        assert response.status_code == 303
        assert response.headers["location"] == "/login?next=%2Foperations-view"

        settings = client.get("/settings/cameras")
        assert settings.status_code == 303
        assert settings.headers["location"] == "/login?next=%2Fsettings%2Fcameras"
    finally:
        patcher.stop()


def test_login_route_returns_dedicated_page_without_app_sidebar(tmp_path: Path) -> None:
    client, _db_path, patcher, _test_connect = _isolated_client(tmp_path)
    try:
        response = client.get("/login")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")
        assert "Entrar na Campex" in response.text
        assert '<base href="/static/"' in response.text
        assert "login.js" in response.text
        assert "cx-login-page" in response.text
        assert "cx-sidebar" not in response.text
        assert "workspace.js" not in response.text
    finally:
        patcher.stop()


def test_valid_login_access_refresh_and_logout_return_to_login(tmp_path: Path) -> None:
    client, _db_path, patcher, _test_connect = _isolated_client(tmp_path)
    try:
        admin = _create_admin_campex(client)
        client.post("/auth/logout")

        invalid = client.post("/auth/login", json={"email": admin["email"], "senha": "errada"})
        assert invalid.status_code == 401

        login = client.post("/auth/login", json={"email": admin["email"], "senha": admin["senha"]})
        assert login.status_code == 200
        assert login.cookies.get("campex_session")

        page = client.get("/operations-view")
        assert page.status_code == 200
        assert "workspace.js" in page.text

        refreshed = client.get("/auth/status")
        assert refreshed.status_code == 200
        assert refreshed.json()["authenticated"] is True

        logout = client.post("/auth/logout")
        assert logout.status_code == 200

        protected = client.get("/operations-view")
        assert protected.status_code == 303
        assert protected.headers["location"] == "/login?next=%2Foperations-view"
    finally:
        patcher.stop()


def test_admin_campex_can_still_create_client_and_user_for_onboarding(tmp_path: Path) -> None:
    client, _db_path, patcher, test_connect = _isolated_client(tmp_path)
    try:
        _create_admin_campex(client)

        cliente = client.post("/clientes", json={"nome": "Cliente Piloto"})
        assert cliente.status_code == 200
        cliente_id = cliente.json()["id"]

        unidade = client.post("/unidades", json={"cliente_id": cliente_id, "nome": "Unidade principal"})
        assert unidade.status_code == 200

        created = client.post(
            "/users",
            json={
                "nome": "Admin Cliente",
                "email": "cliente@empresa.test",
                "senha": "senha-segura",
                "role": "admin_cliente",
                "cliente_id": cliente_id,
            },
        )
        assert created.status_code == 201
        assert created.json()["role"] == "admin_cliente"
        assert created.json()["cliente_id"] == cliente_id

        client.post("/auth/logout")
        login = client.post("/auth/login", json={"email": "cliente@empresa.test", "senha": "senha-segura"})
        assert login.status_code == 200
        assert login.cookies.get("campex_session")

        with test_connect() as connection:
            assert connection.execute("SELECT COUNT(*) FROM users WHERE role = 'admin_campex'").fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM users WHERE role = 'admin_cliente'").fetchone()[0] == 1
    finally:
        patcher.stop()


def test_tenant_user_cannot_access_other_tenant_users(tmp_path: Path) -> None:
    client, _db_path, patcher, test_connect = _isolated_client(tmp_path)
    try:
        with test_connect() as connection:
            tenant_a = criar_cliente(connection, "Empresa A")
            criar_unidade(connection, tenant_a, "Unidade A")
            create_user(connection, "admin-a@empresa.test", "senha-segura", "admin_cliente", tenant_a, "Admin A")

            tenant_b = criar_cliente(connection, "Empresa B")
            criar_unidade(connection, tenant_b, "Unidade B")
            create_user(connection, "admin-b@empresa.test", "senha-segura", "admin_cliente", tenant_b, "Admin B")

        login = client.post("/auth/login", json={"email": "admin-a@empresa.test", "senha": "senha-segura"})
        assert login.status_code == 200

        users = client.get("/auth/users")
        assert users.status_code == 200
        body = users.json()
        assert len(body) == 1
        assert body[0]["email"] == "admin-a@empresa.test"
        assert body[0]["cliente_id"] == tenant_a
    finally:
        patcher.stop()


def test_first_run_and_users_management_flows_still_work(tmp_path: Path) -> None:
    client, _db_path, patcher, _test_connect = _isolated_client(tmp_path)
    try:
        first_run = _create_admin_campex(client)

        created = client.post(
            "/users",
            json={
                "nome": "Operador",
                "email": "operador@cliente.test",
                "senha": "senha-segura",
                "role": "operador",
                "cliente_id": first_run["cliente_id"],
            },
        )
        assert created.status_code == 201
        assert created.json()["role"] == "operador"
        assert created.json()["cliente_id"] == first_run["cliente_id"]

        listed = client.get("/auth/users")
        assert listed.status_code == 200
        assert {user["email"] for user in listed.json()} == {"admin@campex.test", "operador@cliente.test"}
    finally:
        patcher.stop()
