from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import api
from app.config import ROOT


def _workspace_script() -> str:
    return Path(ROOT / "frontend" / "workspace.js").read_text(encoding="utf-8")


def test_events_route_serves_product_shell() -> None:
    client = TestClient(api)

    logged_out = client.get("/events", follow_redirects=False)
    assert logged_out.status_code == 303
    assert logged_out.headers["location"].startswith("/login?next=")

    with patch("app.api._request_has_valid_session", return_value=True):
        response = client.get("/events")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "workspace.js" in response.text


def test_events_v0_uses_canonical_events_and_detail_endpoint() -> None:
    script = _workspace_script()
    start = script.index('"/events":')
    end = script.index('"/alerts":')
    route_block = script[start:end]

    assert 'endpoint: "/eventos"' in route_block
    assert 'title: "Eventos"' in route_block
    assert "Ocorrências e incidentes registrados pela operação." in route_block
    assert "Não classificados" in route_block
    assert "camera_id" not in route_block.lower()
    assert "customRender: renderEventsPage" in route_block
    assert "/eventos/${row.id}/detail" in script


def test_events_v0_separates_physical_status_from_workflow() -> None:
    script = _workspace_script()

    assert "function eventPhysicalStatus" in script
    assert "function eventWorkflow" in script
    assert "workflow_status || \"new\"" in script
    assert "Estado da ocorrência" in script
    assert "Workflow" in script
    assert "/acknowledge" in script
    assert "/human-context" in script
    assert "/resolve" in script


def test_events_v0_keeps_unknown_in_audit_tab_only() -> None:
    script = _workspace_script()

    assert 'currentTab === "não classificados"' in script
    assert 'eventFamily(row) === "unknown"' in script
    assert 'eventFamily(row) !== "unknown"' in script


def test_events_v0_deep_links_by_event_uuid() -> None:
    script = _workspace_script()

    assert "/events?event_uuid=" in script
    assert 'params.get("event_uuid")' in script
    assert "item.event_uuid === eventUuid" in script


def test_events_v0_removes_technical_shell_cards_from_events() -> None:
    script = _workspace_script()

    assert 'path === "/home-view" || path === "/operations-view" || path === "/events" || path === "/insights"' in script
    assert "cx-events-mode" in script
    styles = Path(ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
    assert "cx-events-v1-page" in styles
    assert "cx-events-list" in styles


def test_events_v0_uses_product_empty_state_and_known_filter_controls() -> None:
    script = _workspace_script()
    start = script.index('"/events":')
    end = script.index('"/alerts":')
    route_block = script[start:end]

    assert "Os acontecimentos monitorados pela Campex aparecerão aqui." in route_block
    assert "eventos canônicos" not in route_block
    assert 'id="eventsPeriodFilter"' in script
    assert 'id="eventsStatusFilter"' in script
    assert 'id="eventsSeverityFilter"' in script
    assert 'id="eventsFamilyFilter"' in script
    assert 'id="eventsContextFilter"' in script
    assert "Identificador do evento" not in script
    assert "<dt>event_uuid</dt>" not in script


def test_events_v1_renders_operational_list_and_human_mappers() -> None:
    script = _workspace_script()
    start = script.index("function renderEventsList")
    end = script.index("function evidenceDetail")
    events_block = script[start:end]

    for expected in [
        "Veja ocorrências, evidências e o estado de cada evento registrado.",
        "Buscar ocorrências, ativos, áreas...",
        "Evento",
        "Prioridade",
        "Estado",
        "Quando",
        "Evidência",
        "Nenhuma ocorrência encontrada neste período.",
    ]:
        assert expected in events_block

    assert "function eventSeverityLabel" in script
    assert "function eventDateLabel" in script
    assert "Ativo/área" in script
    assert "machine_stoppage" in script
    assert "Parada operacional" in script
    assert "workstation_unattended" in script
    assert "Posto sem operador" in script
    assert "eventPhysicalStatusLabel" in script


def test_events_v1_drawer_prioritizes_evidence_and_separates_human_context() -> None:
    script = _workspace_script()
    start = script.index("function eventDetail")
    end = script.index("function evidenceDetail")
    detail_block = script[start:end]

    for expected in [
        "Evidência",
        "O que a Campex observou",
        "Contexto da operação",
        "Tratamento",
        "Causa confirmada",
        "Ação tomada",
        "Detalhes técnicos",
    ]:
        assert expected in detail_block

    assert "Nenhuma evidência visual disponível." in detail_block
    assert "technical_type" in detail_block
    assert "event_uuid" not in detail_block
