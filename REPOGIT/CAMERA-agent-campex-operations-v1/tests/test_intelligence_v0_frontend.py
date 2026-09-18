from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import api as api_module
from app.api import api
from app.config import ROOT


def _workspace_script() -> str:
    return Path(ROOT / "frontend" / "workspace.js").read_text(encoding="utf-8")


def test_intelligence_route_serves_product_shell() -> None:
    client = TestClient(api)

    with patch.object(api_module, "_request_has_valid_session", return_value=True):
        response = client.get("/insights")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "workspace.js" in response.text


def test_intelligence_consumes_read_model_insights_endpoint() -> None:
    script = _workspace_script()
    start = script.index('"/insights":')
    end = script.index('"/history":')
    route_block = script[start:end]
    render_start = script.index("async function renderIntelligencePage")
    render_end = script.index("async function loadAlertsWorkspace")
    render_block = script[render_start:render_end]

    assert 'endpoint: "/operations/read-model/insights"' in route_block
    assert "/operations/read-model/insights" in render_block
    assert "/operations/summary" not in render_block
    assert "/operations/events?limit=200" not in render_block


def test_intelligence_explains_and_traces_insights_without_legacy_loader() -> None:
    script = _workspace_script()
    render_start = script.index("async function renderIntelligencePage")
    render_end = script.index("async function loadAlertsWorkspace")
    render_block = script[render_start:render_end]

    assert "Padrões, comparações e resumos verificáveis da operação." in render_block
    assert "O que merece atenção" in render_block
    assert "Padrões verificáveis" in render_block
    assert "Ativos mais impactados" in render_block
    assert "Por que a Campex está destacando isso?" in script
    assert "Causas confirmadas" in render_block
    assert "Observações da câmera não viram causa automaticamente." in render_block
    assert "insightTraceAction(item" in script
    assert "loadInsightsWorkspace" not in script


def test_intelligence_uses_product_language_and_responsive_layout() -> None:
    script = _workspace_script()
    styles = Path(ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
    render_start = script.index("async function renderIntelligencePage")
    render_end = script.index("async function loadAlertsWorkspace")
    render_block = script[render_start:render_end]

    assert "eventos canônicos" not in render_block
    assert "Operational Read Model" not in render_block
    assert "Cada insight lista os event_uuid" not in render_block
    assert "Padrões, comparações e resumos verificáveis da operação." in render_block
    assert "humanInsightText(item.statement)" in render_block
    assert "humanTechnicalLabel(cause.key" in script
    assert "repeat(auto-fit, minmax(180px, 1fr))" in styles
    assert "minmax(520px, 1.32fr)" in styles
    assert ".campex-dashboard.cx-intelligence-mode .cx-work-table" in styles
