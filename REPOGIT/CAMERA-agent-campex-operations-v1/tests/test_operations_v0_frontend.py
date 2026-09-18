from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import api as api_module
from app.api import api
from app.config import ROOT


def test_operations_view_route_serves_workspace_shell() -> None:
    client = TestClient(api)

    with patch.object(api_module, "_request_has_valid_session", return_value=True):
        response = client.get("/operations-view")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "workspace.js" in response.text
    assert "campex-intelligence-v1-20260817" in response.text
    assert "SQLite persistente" not in response.text
    assert "Sem credenciais no navegador" not in response.text
    assert "<h2 id=\"workspaceTableTitle\">Registros</h2>" not in response.text


def test_operations_view_uses_read_model_endpoints_for_aggregations() -> None:
    script = Path(ROOT / "frontend" / "workspace.js").read_text(encoding="utf-8")
    start = script.index("async function renderOperationsReadModelPage")
    end = script.index("function intelligenceBriefingText")
    operations_block = script[start:end]

    assert "/operations/read-model/current" in operations_block
    assert "/operations/read-model/summary" in operations_block
    assert "/operations/timeline" in operations_block
    assert "/setup/operation" in operations_block
    assert "/eventos" in operations_block
    assert "/operations/read-model/losses" not in operations_block
    assert "/operations/read-model/comparison" not in operations_block
    assert "/operations/summary" not in operations_block
    assert "/operations/events" not in operations_block


def test_operations_view_replaces_legacy_dashboard_content() -> None:
    script = Path(ROOT / "frontend" / "workspace.js").read_text(encoding="utf-8")
    start = script.index("async function renderOperationsReadModelPage")
    end = script.index("function intelligenceBriefingText")
    operations_block = script[start:end]

    for expected in [
        "Operação",
        "Estado operacional da sua planta.",
        "Veja o que está em operação, parado ou exigindo atenção agora.",
        "Ativos monitorados",
        "Atividade recente",
        "Qualidade dos dados",
        "Dados insuficientes",
    ]:
        assert expected in operations_block

    for table_label in ["Status", "Leitura operacional", "Atualização"]:
        assert table_label in script[
            script.index("function renderOperationsAssetList"):
            script.index("function renderOperationsRecentActivity")
        ]

    for legacy_label in [
        "Como está sua operação?",
        "Briefing operacional",
        "Principais perdas",
        "Comparação",
        "Adicionar câmera",
        "Revisar eventos",
        "Configurar alerta",
        "Gerar relatório",
        "Status das câmeras",
        "SQLite persistente",
        "credenciais",
        "cards de implantação",
    ]:
        assert legacy_label not in operations_block

    for family_label in ["Interrupções", "Esperas", "Ausências", "Fluxo"]:
        assert family_label in operations_block or family_label in script


def test_operations_formats_period_and_keeps_unknown_secondary() -> None:
    script = Path(ROOT / "frontend" / "workspace.js").read_text(encoding="utf-8")

    assert "function formatOperationsPeriod" in script
    assert "toLocaleDateString" in script
    assert "toLocaleTimeString" in script
    assert "function officialFamilyRows" in script
    assert "function unknownEventCount" in script
    assert "function renderUnknownQualityNote" in script
    assert "não entram nos indicadores oficiais da Operations" in script
    assert "Sem eventos operacionais classificados suficientes neste período." in script
    assert "officialFamilyRows(summary)" in script
    assert "event_family = unknown" not in script[
        script.index("async function renderOperationsReadModelPage"):
        script.index("function intelligenceBriefingText")
    ]


def test_operations_current_uses_canonical_context_labels() -> None:
    script = Path(ROOT / "frontend" / "workspace.js").read_text(encoding="utf-8")

    block = script[
        script.index("function operationsAssetRows"):
        script.index("function operationsFilterRows")
    ]

    assert "asset.nome || asset.name" in block
    assert "asset.area_name || asset.area || asset.area_id || asset.area_context_id" in block
    assert "eventContextLabel(event)" in block
    assert "Contexto operacional não informado" in script
    assert "Ativo operacional" in block


def test_operations_view_maps_technical_states_to_human_labels() -> None:
    script = Path(ROOT / "frontend" / "workspace.js").read_text(encoding="utf-8")
    block = script[
        script.index("function operationsStateLabel"):
        script.index("function operationsStateTone")
    ]

    for expected in [
        'RUNNING: "Em operação"',
        'STOPPED: "Parado"',
        'LOW_ACTIVITY: "Baixa atividade"',
        'UNKNOWN: "Dados insuficientes"',
        'OFFLINE: "Offline"',
    ]:
        assert expected in block

    assert "operationsStateDot" in script
    assert "cx-ops-state" in script


def test_operations_filters_are_functional() -> None:
    script = Path(ROOT / "frontend" / "workspace.js").read_text(encoding="utf-8")

    assert "let operationsSelectedState" in script
    assert "let operationsSelectedAsset" in script
    assert "function operationsFilterRows" in script
    assert "#operationsStateFilter" in script
    assert "#operationsAssetFilter" in script
    assert "operationsSelectedState = stateSelect.value" in script
    assert "operationsSelectedAsset = assetSelect.value" in script


def test_operations_load_page_does_not_inject_legacy_shell_cards() -> None:
    script = Path(ROOT / "frontend" / "workspace.js").read_text(encoding="utf-8")

    assert "function usesProductMemoryShell" in script
    assert 'path === "/home-view" || path === "/operations-view" || path === "/events" || path === "/insights"' in script
    assert "cards.innerHTML = usesProductMemoryShell(path) ? \"\"" in script
    assert "renderOperationsAuthState" in script
    assert "Entre para acessar os dados da operação." in script
    assert "/login?next=${target}" in script

    for legacy_label in [
        "Registros",
        "SQLite persistente",
        "Sem credenciais no navegador",
        "Adicionar câmera",
        "Gerar relatório",
        "Status das câmeras",
    ]:
        assert legacy_label not in script[
            script.index("function renderOperationsAuthState"):
            script.index("function renderRows")
        ]


def test_login_redirect_can_return_to_operations_view() -> None:
    app_script = Path(ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert 'new URLSearchParams(window.location.search).get("next")' in app_script
    assert 'next.startsWith("/")' in app_script
    assert 'window.location.href = next' in app_script


def test_operations_view_is_not_rendered_from_dashboard_html() -> None:
    client = TestClient(api)

    with patch.object(api_module, "_request_has_valid_session", return_value=True):
        response = client.get("/operations-view")

    assert response.status_code == 200
    assert "workspace.js" in response.text
    assert "operations-dashboard.js" not in response.text
    assert "dashboard.html" not in response.text


def test_operations_traceability_keeps_event_uuid_links() -> None:
    script = Path(ROOT / "frontend" / "workspace.js").read_text(encoding="utf-8")

    assert "data-event-uuids" in script
    assert "renderTraceDrawer" in script
    assert "event_uuids" in script
