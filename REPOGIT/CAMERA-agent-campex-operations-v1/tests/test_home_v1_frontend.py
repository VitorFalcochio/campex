from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import api
from app.config import ROOT


def _workspace_script() -> str:
    return Path(ROOT / "frontend" / "workspace.js").read_text(encoding="utf-8")


def test_home_uses_workspace_shell_and_is_first_navigation_item() -> None:
    client = TestClient(api)
    logged_out = client.get("/operations-view?view=home", follow_redirects=False)
    assert logged_out.status_code == 303
    assert logged_out.headers["location"].startswith("/login?next=")

    with patch("app.api._request_has_valid_session", return_value=True):
        response = client.get("/operations-view?view=home")
    html = response.text

    assert response.status_code == 200
    assert "workspace.js" in html
    primary_nav = html[html.index('<nav class="cx-nav') : html.index('<div class="cx-account">')]
    assert 'href="/operations-view?view=home"' in primary_nav
    assert primary_nav.index("Início") < primary_nav.index("Visão geral")


def test_home_consumes_only_real_operational_endpoints() -> None:
    script = _workspace_script()
    start = script.index("async function renderHomePage")
    end = script.index("async function renderOperationsReadModelPage")
    home_block = script[start:end]

    for endpoint in [
        "/operations/read-model/current",
        "/operations/read-model/summary",
        "/operations/timeline",
        "/operations/read-model/insights",
        "/operations/read-model/operational-data",
        "/setup/operation",
        "/eventos",
    ]:
        assert endpoint in home_block

    for endpoint in [
        "/operations/change-anomalies",
        "/operations/alert-decisions",
        "/operations/briefing",
        "/operations/impact",
    ]:
        assert endpoint not in home_block

    forbidden = ["A1", "A2", "48 ativos", "downtime fictício", "mock", "hardcoded"]
    for item in forbidden:
        assert item not in home_block


def test_home_loads_sections_independently_without_fatal_promise_all() -> None:
    script = _workspace_script()
    start = script.index("async function renderHomePage")
    end = script.index("async function renderOperationsReadModelPage")
    home_block = script[start:end]

    assert "homeResource(" in home_block
    assert "Promise.allSettled" not in home_block
    assert "throw rejected.reason" not in home_block
    assert "Seções indisponíveis" in script
    assert 'body.closest("table")?.setAttribute("aria-hidden", "true")' in home_block


def test_home_empty_unknown_and_financial_states_are_honest() -> None:
    script = _workspace_script()
    start = script.index("async function renderHomePage")
    end = script.index("async function renderOperationsReadModelPage")
    home_block = script[start:end]

    assert "Sem dados operacionais suficientes neste período." in home_block
    assert "Cobertura insuficiente" in script
    assert "Impacto financeiro não configurado" in script
    assert "R$ 0" not in home_block
    assert "Indisponível" in script
    assert "function renderHomeAuthState" in script
    assert "Sem autenticação, a Campex não carrega tenant" in script


def test_home_hides_technical_ids_from_main_presentation() -> None:
    script = _workspace_script()

    assert "function homeContextName" in script
    assert "Ativo sem nome" in script
    assert "opasset" in script
    assert "homeContextName(item.asset_label || item.asset_id" in script


def test_home_route_preserves_backend_without_new_route() -> None:
    script = _workspace_script()
    shell = Path(ROOT / "frontend" / "shell.js").read_text(encoding="utf-8")
    html = Path(ROOT / "frontend" / "workspace.html").read_text(encoding="utf-8")

    assert '"/home-view"' in script
    assert '/operations-view?view=home' in html
    assert 'view") === "home"' in shell
