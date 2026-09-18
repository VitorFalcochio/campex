from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import api as api_module
from app.api import api
from app.auth import create_user
from app.database import connect, init_db
from app.models import criar_cliente


class FakeGoogleResponse:
    def __init__(self, payload: dict[str, object], status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError("google request failed")

    def json(self) -> dict[str, object]:
        return self._payload


def _isolated_client(tmp_path: Path):
    db_path = tmp_path / "google-oauth.sqlite3"

    def test_connect(_path=None):
        return connect(db_path)

    with test_connect() as connection:
        init_db(connection)
    patcher = patch.object(api_module, "connect", test_connect)
    patcher.start()
    return TestClient(api), db_path, patcher, test_connect


def _oauth_env():
    return {
        "CAMPEX_GOOGLE_CLIENT_ID": "client-id.apps.googleusercontent.com",
        "CAMPEX_GOOGLE_CLIENT_SECRET": "client-secret",
        "CAMPEX_PUBLIC_BASE_URL": "http://127.0.0.1:8000",
    }


def _start_google(client: TestClient, next_url: str = "/settings/cameras"):
    response = client.get(f"/auth/oauth/google/start?next={quote(next_url, safe='')}", follow_redirects=False)
    assert response.status_code == 303
    location = response.headers["location"]
    parsed = urlparse(location)
    params = parse_qs(parsed.query)
    return response, location, params["state"][0]


def _cookie_value(response, name: str) -> str | None:
    value = response.cookies.get(name)
    return value.strip('"') if value else value


def test_google_oauth_start_generates_redirect_and_state(tmp_path: Path) -> None:
    client, _db_path, patcher, _test_connect = _isolated_client(tmp_path)
    try:
        with patch.dict("os.environ", _oauth_env(), clear=False):
            response, location, state = _start_google(client, "/settings/cameras#cliente")
        assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
        assert "openid+email+profile" in location
        assert state
        assert _cookie_value(response, "campex_google_oauth_state") == state
        assert _cookie_value(response, "campex_google_oauth_next") == "/settings/cameras#cliente"
    finally:
        patcher.stop()


def test_google_oauth_start_sanitizes_external_next(tmp_path: Path) -> None:
    client, _db_path, patcher, _test_connect = _isolated_client(tmp_path)
    try:
        with patch.dict("os.environ", _oauth_env(), clear=False):
            response, _location, _state = _start_google(client, "https://evil.example/phish")
        assert _cookie_value(response, "campex_google_oauth_next") == "/operations-view?view=home"
    finally:
        patcher.stop()


def test_google_oauth_callback_rejects_invalid_state(tmp_path: Path) -> None:
    client, _db_path, patcher, _test_connect = _isolated_client(tmp_path)
    try:
        with patch.dict("os.environ", _oauth_env(), clear=False):
            client.cookies.set("campex_google_oauth_state", "expected")
            response = client.get("/auth/oauth/google/callback?state=wrong&code=abc", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login?oauth_error=invalid_state"
    finally:
        patcher.stop()


def test_google_oauth_unprovisioned_email_does_not_create_user(tmp_path: Path) -> None:
    client, db_path, patcher, _test_connect = _isolated_client(tmp_path)
    try:
        with patch.dict("os.environ", _oauth_env(), clear=False):
            _response, _location, state = _start_google(client)
            with patch("app.api.httpx.post", return_value=FakeGoogleResponse({"access_token": "token"})), patch(
                "app.api.httpx.get",
                return_value=FakeGoogleResponse({"email": "novo@cliente.test", "email_verified": True, "name": "Novo"}),
            ):
                callback = client.get(f"/auth/oauth/google/callback?state={state}&code=abc", follow_redirects=False)
        assert callback.status_code == 303
        assert callback.headers["location"] == "/login?oauth_error=access_not_provisioned"
        with connect(db_path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM user_sessions").fetchone()[0] == 0
    finally:
        patcher.stop()


def test_google_oauth_existing_user_receives_campex_session_and_preserves_tenant_role(tmp_path: Path) -> None:
    client, db_path, patcher, test_connect = _isolated_client(tmp_path)
    try:
        with test_connect() as connection:
            cliente_id = criar_cliente(connection, "Cliente OAuth")
            user_id = create_user(connection, "gestor@cliente.test", "senha-tradicional", "admin_cliente", cliente_id, "Gestor OAuth")
        with patch.dict("os.environ", _oauth_env(), clear=False):
            _response, _location, state = _start_google(client, "/operations-view?view=home")
            with patch("app.api.httpx.post", return_value=FakeGoogleResponse({"access_token": "token"})) as token_call, patch(
                "app.api.httpx.get",
                return_value=FakeGoogleResponse({"email": "GESTOR@CLIENTE.TEST", "email_verified": True, "name": "Gestor Google"}),
            ) as userinfo_call:
                callback = client.get(f"/auth/oauth/google/callback?state={state}&code=abc", follow_redirects=False)
        assert callback.status_code == 303
        assert callback.headers["location"] == "/operations-view?view=home"
        assert callback.cookies.get("campex_session")
        assert token_call.called
        assert userinfo_call.called

        auth_status = client.get("/auth/status")
        assert auth_status.status_code == 200
        body = auth_status.json()
        assert body["authenticated"] is True
        assert body["user"]["id"] == user_id
        assert body["user"]["email"] == "gestor@cliente.test"
        assert body["user"]["role"] == "admin_cliente"
        assert body["user"]["cliente_id"] == cliente_id
        assert "password_hash" not in body["user"]

        with connect(db_path) as connection:
            audit = connection.execute("SELECT action, actor_email FROM audit_log ORDER BY created_at DESC LIMIT 1").fetchone()
            assert audit["action"] == "auth.oauth.google.login"
            assert audit["actor_email"] == "gestor@cliente.test"
    finally:
        patcher.stop()


def test_traditional_password_login_and_logout_still_work(tmp_path: Path) -> None:
    client, _db_path, patcher, test_connect = _isolated_client(tmp_path)
    try:
        with test_connect() as connection:
            cliente_id = criar_cliente(connection, "Cliente Tradicional")
            create_user(connection, "admin@cliente.test", "senha-segura", "admin_cliente", cliente_id, "Admin")

        login = client.post("/auth/login", json={"email": "admin@cliente.test", "senha": "senha-segura"})
        assert login.status_code == 200
        assert login.cookies.get("campex_session")

        status = client.get("/auth/status")
        assert status.json()["authenticated"] is True

        logout = client.post("/auth/logout")
        assert logout.status_code == 200
        assert client.get("/auth/status").json()["authenticated"] is False
    finally:
        patcher.stop()


def test_google_oauth_frontend_does_not_expose_secret() -> None:
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    script = Path("frontend/app.js").read_text(encoding="utf-8")
    assert "CAMPEX_GOOGLE_CLIENT_SECRET" not in html
    assert "CAMPEX_GOOGLE_CLIENT_SECRET" not in script
    assert "Continuar com Google" in html
    assert "/auth/oauth/google/start" in html
