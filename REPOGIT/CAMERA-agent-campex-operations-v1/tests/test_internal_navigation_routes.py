import os
import re
import socket
import subprocess
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import app.api as api_module
from app.auth import create_user
from app.api import api
from app.config import ROOT
from app.database import connect, init_db
from app.models import criar_cliente, criar_unidade


INTERNAL_ROUTES = [
    "/overview",
    "/operations-view",
    "/cameras",
    "/events",
    "/alerts",
    "/evidence",
    "/rules",
    "/reports",
    "/insights",
    "/history",
    "/integrations",
    "/users",
    "/settings",
    "/settings/cameras",
    "/settings/notifications",
    "/settings/account",
    "/help",
]


STATIC_ASSETS = [
    "/static/styles.css",
    "/static/shell.js",
    "/static/workspace.js",
    "/static/operations-dashboard.js",
    "/static/app.js",
    "/static/campex-logo-oficial.png",
]


def assert_shell_response(route: str, response) -> None:
    assert response.status_code == 200, route
    assert "text/html" in response.headers["content-type"], route
    assert "application/json" not in response.headers["content-type"], route
    assert "Not Found" not in response.text, route
    assert '<aside class="cx-sidebar">' in response.text, route
    assert '<header class="cx-header cx-topbar">' in response.text, route
    assert 'href="/operations-view"' in response.text, route
    assert 'href="/events"' in response.text, route


def test_internal_navigation_routes_return_html() -> None:
    client = TestClient(api)

    for route in INTERNAL_ROUTES:
        logged_out = client.get(route, follow_redirects=False)
        assert logged_out.status_code == 303, route
        assert logged_out.headers["location"].startswith("/login?next="), route

        with patch.object(api_module, "_request_has_valid_session", return_value=True):
            response = client.get(route)

        assert_shell_response(route, response)


def test_dashboard_redirects_to_operations_view() -> None:
    client = TestClient(api)

    response = client.get("/dashboard", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/operations-view"


def test_sidebar_links_are_registered_internal_routes() -> None:
    html_files = [
        ROOT / "frontend" / "dashboard.html",
        ROOT / "frontend" / "workspace.html",
        ROOT / "frontend" / "index.html",
        ROOT / "frontend" / "live-view.html",
    ]
    expected = set(INTERNAL_ROUTES) | {"/live-view", "/live-grid"}

    for html_file in html_files:
        content = Path(html_file).read_text(encoding="utf-8")
        for route in [
            "/operations-view",
            "/events",
            "/insights",
            "/live-grid",
            "/settings/cameras",
        ]:
            assert f'href="{route}"' in content, f"{html_file.name} sem link para {route}"
            assert route in expected


def test_invalid_internal_route_returns_campex_404_shell() -> None:
    client = TestClient(api)

    response = client.get("/area-inexistente")

    assert response.status_code == 404
    assert "text/html" in response.headers["content-type"]
    assert "workspace.js" in response.text


def test_invalid_api_or_static_routes_do_not_return_shell_html() -> None:
    client = TestClient(api)

    api_response = client.get("/operations/rota-inexistente")
    static_response = client.get("/static/arquivo-inexistente.js")

    assert api_response.status_code == 404
    assert "text/html" not in api_response.headers["content-type"]
    assert static_response.status_code == 404
    assert "text/html" not in static_response.headers["content-type"]


def test_internal_shell_assets_load() -> None:
    client = TestClient(api)

    for asset in STATIC_ASSETS:
        response = client.get(asset)
        assert response.status_code == 200, asset
        assert "application/json" not in response.headers["content-type"], asset


def test_api_endpoints_keep_json_responses() -> None:
    client = TestClient(api)

    health = client.get("/health")
    operations = client.get("/operations/summary")
    cameras_state = client.get("/cameras/estado")

    assert health.status_code == 200
    assert health.headers["content-type"].startswith("application/json")
    assert operations.status_code in {200, 401, 403}
    assert operations.headers["content-type"].startswith("application/json")
    assert cameras_state.status_code in {200, 401, 403}
    assert cameras_state.headers["content-type"].startswith("application/json")


def test_direct_refresh_routes_return_correct_shell() -> None:
    client = TestClient(api)

    for route in ["/events", "/cameras", "/settings"]:
        logged_out = client.get(route, follow_redirects=False)
        assert logged_out.status_code == 303, route
        assert logged_out.headers["location"].startswith("/login?next="), route

        with patch.object(api_module, "_request_has_valid_session", return_value=True):
            response = client.get(route)
        assert_shell_response(route, response)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def browser_base_url(tmp_path_factory):
    port = _free_port()
    db_path = tmp_path_factory.mktemp("campex_nav") / "nav.sqlite3"
    with connect(db_path) as connection:
        init_db(connection)
        cliente_id = criar_cliente(connection, "Cliente Playwright")
        criar_unidade(connection, cliente_id, "Unidade principal")
        create_user(connection, "nav@example.com", "senha-segura", "admin_cliente", cliente_id, "Navegador")
    env = {
        **os.environ,
        "API_HOST": "127.0.0.1",
        "API_PORT": str(port),
        "DATABASE_PATH": str(db_path),
    }
    process = subprocess.Popen(
        ["python3", "-m", "app.main"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            output = process.stdout.read() if process.stdout else ""
            raise RuntimeError(f"Servidor de teste nao iniciou: {output}")
        yield base_url
    finally:
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()


@pytest.fixture(scope="module")
def browser():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            headless=True,
        )
        try:
            yield browser
        finally:
            browser.close()


def _open_page(browser, base_url: str, path: str, width: int = 1366, height: int = 900):
    page = browser.new_page(viewport={"width": width, "height": height})
    js_errors: list[str] = []
    page.on("pageerror", lambda error: js_errors.append(str(error)))
    login = page.request.post(
        f"{base_url}/auth/login",
        data={"email": "nav@example.com", "senha": "senha-segura"},
    )
    assert login.ok
    response = page.goto(f"{base_url}{path}", wait_until="domcontentloaded")
    page.locator(".cx-sidebar").wait_for(state="visible")
    assert response is not None
    return page, response, js_errors


def _assert_active(page, label: str) -> None:
    active = page.locator(".cx-nav a.active")
    assert active.count() == 1
    assert label in active.first.text_content()
    assert active.first.get_attribute("aria-current") == "page"
    assert active.first.get_attribute("title")


def _assert_page_top(page) -> None:
    assert page.locator(".cx-main").is_visible()


def test_browser_sidebar_navigation_back_forward_refresh_and_new_tab(browser, browser_base_url) -> None:
    page, response, js_errors = _open_page(browser, browser_base_url, "/operations-view")
    assert response.status == 200
    assert page.locator(".cx-sidebar").is_visible()
    _assert_page_top(page)
    _assert_active(page, "Operação")

    route_labels = [
        ("/events", "Eventos"),
        ("/insights", "Intelligence"),
        ("/live-grid", "Ao vivo"),
        ("/settings/cameras", "Configurações"),
    ]
    for route, label in route_labels:
        page.locator(f'.cx-nav a[href="{route}"]').first.click()
        page.wait_for_url(re.compile(re.escape(route) + r"$"))
        assert page.url.endswith(route)
        assert page.locator(".cx-sidebar").is_visible()
        _assert_page_top(page)
        _assert_active(page, label)
        assert "Not Found" not in page.content()

    for route, label in [("/operations-view", "Operação"), ("/events", "Eventos"), ("/settings/cameras", "Configurações")]:
        response = page.goto(f"{browser_base_url}{route}", wait_until="domcontentloaded")
        assert response.status == 200
        _assert_page_top(page)
        _assert_active(page, label)

    page.goto(f"{browser_base_url}/operations-view", wait_until="domcontentloaded")
    page.locator('.cx-nav a[href="/events"]').first.click()
    page.wait_for_url(re.compile(r".*/events$"))
    page.locator('.cx-nav a[href="/insights"]').first.click()
    page.wait_for_url(re.compile(r".*/insights$"))
    page.go_back(wait_until="domcontentloaded")
    assert page.url.endswith("/events")
    _assert_active(page, "Eventos")
    page.go_forward(wait_until="domcontentloaded")
    assert page.url.endswith("/insights")
    _assert_active(page, "Intelligence")

    new_page, new_response, new_errors = _open_page(browser, browser_base_url, "/insights")
    assert new_response.status == 200
    _assert_active(new_page, "Intelligence")
    assert not new_errors
    new_page.close()

    assert not js_errors
    page.close()


def test_browser_invalid_internal_route_shows_shell_404(browser, browser_base_url) -> None:
    page, response, js_errors = _open_page(browser, browser_base_url, "/area-inexistente")

    assert response.status == 404
    assert page.locator(".cx-sidebar").is_visible()
    _assert_page_top(page)
    assert page.get_by_text("Página não encontrada").first.is_visible()
    assert page.get_by_text("Voltar para Operação").first.is_visible()
    assert page.locator(".cx-nav a.active").count() == 0
    assert not js_errors
    page.close()


def test_browser_mobile_drawer_and_collapsed_sidebar(browser, browser_base_url) -> None:
    page, response, js_errors = _open_page(browser, browser_base_url, "/operations-view", width=390, height=844)

    assert response.status == 200
    page.locator(".cx-mobile-menu").click()
    assert page.locator(".cx-mobile-overlay").is_visible()
    page.wait_for_timeout(250)
    page.locator('.cx-nav a[href="/events"]').first.click()
    page.wait_for_url(re.compile(r".*/events$"))
    assert page.url.endswith("/events")
    assert not page.locator(".cx-mobile-overlay").is_visible()
    _assert_active(page, "Eventos")
    page.close()

    desktop, response, desktop_errors = _open_page(browser, browser_base_url, "/operations-view")
    assert response.status == 200
    desktop.locator(".cx-collapse").first.click()
    assert "sidebar-collapsed" in (desktop.locator("body").get_attribute("class") or "")
    for link in desktop.locator(".cx-nav a").all():
        assert link.get_attribute("title")
    _assert_active(desktop, "Operação")
    assert not js_errors
    assert not desktop_errors
    desktop.close()
