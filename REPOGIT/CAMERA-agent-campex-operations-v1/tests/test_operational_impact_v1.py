from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import api
from app.auth import create_user
from app.database import connect
from app.models import listar_alert_deliveries
from app.operational_context import criar_operational_asset
from app.operational_impact import (
    METHOD_DOWNTIME_COST_PER_HOUR,
    METHOD_PRODUCTION_RATE_CONTRIBUTION,
    calculate_operational_impact,
    upsert_asset_economic_config,
)
from app.operational_read_model import ReadModelFilters, parse_datetime
from tests.test_operational_read_model import START, END, NOW, add_event, add_sample, make_context


def test_downtime_total_two_stoppages_and_asset_impact() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, asset_id, camera_id = make_context()
    with temp_dir, connection:
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T08:10:00+00:00", end="2026-08-07T08:20:00+00:00", duration=600, event_uuid="evt-impact-1")
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T09:00:00+00:00", end="2026-08-07T09:05:00+00:00", duration=300, event_uuid="evt-impact-2")
        payload = calculate_operational_impact(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=END), now=NOW)

    assert payload["operational_impact"]["downtime_seconds"] == 900
    assert payload["operational_impact"]["stoppage_count"] == 2
    assert payload["assets"][0]["asset_id"] == asset_id
    assert payload["assets"][0]["operational_impact"]["longest_stoppage_seconds"] == 600
    assert payload["financial_impact"]["status"] == "NOT_AVAILABLE"
    assert payload["financial_impact"]["reason"] == "economic_parameters_not_configured"


def test_overlapping_events_are_not_double_counted() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, _asset_id, camera_id = make_context()
    with temp_dir, connection:
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T08:00:00+00:00", end="2026-08-07T08:20:00+00:00", duration=1200, event_uuid="evt-overlap-a")
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T08:10:00+00:00", end="2026-08-07T08:30:00+00:00", duration=1200, event_uuid="evt-overlap-b")
        payload = calculate_operational_impact(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=END), now=NOW)

    assert payload["operational_impact"]["downtime_seconds"] == 1800
    assert payload["operational_impact"]["stoppage_count"] == 2
    assert payload["assets"][0]["segments"][0]["event_uuids"] == ["evt-overlap-a", "evt-overlap-b"]


def test_unknown_samples_and_camera_offline_do_not_count_as_downtime() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, asset_id, camera_id = make_context()
    with temp_dir, connection:
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T08:00:00+00:00", "UNKNOWN", None, camera_online=False, inference_fps=0.0)
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T09:00:00+00:00", "UNKNOWN", None, camera_online=False, inference_fps=0.0)
        payload = calculate_operational_impact(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=END), now=NOW)

    assert payload["operational_impact"]["downtime_seconds"] == 0
    assert payload["quality"]["status"] == "PARTIAL"
    assert "unknown_period_present" in payload["quality"]["reasons"]
    assert payload["quality"]["camera_offline_is_not_counted_as_machine_stopped"] is True


def test_events_crossing_window_boundaries_are_cut_and_mark_quality_partial() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, _asset_id, camera_id = make_context()
    with temp_dir, connection:
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T07:50:00+00:00", end="2026-08-07T08:10:00+00:00", duration=1200, event_uuid="evt-before")
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T11:50:00+00:00", end="2026-08-07T12:10:00+00:00", duration=1200, event_uuid="evt-after")
        payload = calculate_operational_impact(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=END), now=NOW)

    assert payload["operational_impact"]["downtime_seconds"] == 1200
    assert payload["quality"]["status"] == "PARTIAL"
    assert "event_boundary_outside_window" in payload["quality"]["reasons"]


def test_open_event_is_counted_until_window_end_or_now_and_marked_ongoing() -> None:
    window_end = parse_datetime("2026-08-07T13:00:00+00:00")
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, _asset_id, camera_id = make_context()
    with temp_dir, connection:
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T11:30:00+00:00", event_uuid="evt-open-impact")
        payload = calculate_operational_impact(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=window_end), now=NOW)

    assert payload["operational_impact"]["downtime_seconds"] == 1800
    assert payload["assets"][0]["operational_impact"]["ongoing"] is True
    assert "event_open" in payload["quality"]["reasons"]


def test_financial_method_downtime_cost_per_hour_audits_inputs_and_currency() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, asset_id, camera_id = make_context()
    with temp_dir, connection:
        upsert_asset_economic_config(
            connection,
            asset_id,
            tenant_id=cliente_id,
            method=METHOD_DOWNTIME_COST_PER_HOUR,
            downtime_cost_per_hour=1500.0,
            currency="BRL",
        )
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T08:00:00+00:00", end="2026-08-07T08:30:00+00:00", duration=1800, event_uuid="evt-cost-hour")
        payload = calculate_operational_impact(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=END), now=NOW)

    assert payload["financial_impact"]["status"] == "AVAILABLE"
    assert payload["financial_impact"]["estimated_amount"] == 750.0
    assert payload["financial_impact"]["currency"] == "BRL"
    assert payload["assets"][0]["financial_impact"]["inputs"] == {"downtime_hours": 0.5, "downtime_cost_per_hour": 1500.0}
    assert payload["assets"][0]["financial_impact"]["formula"] == "downtime_hours × downtime_cost_per_hour"


def test_financial_method_production_rate_contribution() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, asset_id, camera_id = make_context()
    with temp_dir, connection:
        upsert_asset_economic_config(
            connection,
            asset_id,
            tenant_id=cliente_id,
            method=METHOD_PRODUCTION_RATE_CONTRIBUTION,
            production_rate_per_hour=120.0,
            contribution_value_per_unit=3.0,
            currency="BRL",
        )
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T08:00:00+00:00", end="2026-08-07T08:30:00+00:00", duration=1800, event_uuid="evt-cost-production")
        payload = calculate_operational_impact(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=END), now=NOW)

    assert payload["financial_impact"]["estimated_amount"] == 180.0
    assert payload["assets"][0]["financial_impact"]["inputs"]["production_rate_per_hour"] == 120.0
    assert payload["assets"][0]["financial_impact"]["terminology"] == "estimated_downtime_impact"


def test_tenant_and_asset_configs_are_isolated() -> None:
    temp_dir, _db_path, connection, cliente_id, site_id, area_id, process_id, asset_id, camera_id = make_context()
    with temp_dir, connection:
        other_asset = criar_operational_asset(connection, cliente_id=cliente_id, unidade_id=site_id, area_id=area_id, process_id=process_id, nome="A7")
        upsert_asset_economic_config(connection, other_asset, tenant_id=cliente_id, method=METHOD_DOWNTIME_COST_PER_HOUR, downtime_cost_per_hour=9999.0)
        upsert_asset_economic_config(connection, asset_id, tenant_id="tenant-invalido", method=METHOD_DOWNTIME_COST_PER_HOUR, downtime_cost_per_hour=1500.0)
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T08:00:00+00:00", end="2026-08-07T08:30:00+00:00", duration=1800, event_uuid="evt-isolated")
        payload = calculate_operational_impact(connection, ReadModelFilters(cliente_id=cliente_id, asset_id=asset_id, start=START, end=END), now=NOW)

    assert payload["assets"][0]["asset_id"] == asset_id
    assert payload["assets"][0]["financial_impact"]["status"] == "NOT_AVAILABLE"
    assert payload["financial_impact"]["status"] == "NOT_AVAILABLE"


def test_briefing_consumes_impact_without_ai_or_alert_side_effects() -> None:
    from app.operational_briefing import operational_shift_briefing

    temp_dir, _db_path, connection, cliente_id, site_id, _area_id, _process_id, asset_id, camera_id = make_context()
    with temp_dir, connection, patch("app.video_understanding.OpenAIVideoUnderstandingProvider.analyze") as openai:
        before_deliveries = len(listar_alert_deliveries(connection))
        upsert_asset_economic_config(connection, asset_id, tenant_id=cliente_id, method=METHOD_DOWNTIME_COST_PER_HOUR, downtime_cost_per_hour=1200.0)
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T08:00:00+00:00", end="2026-08-07T08:30:00+00:00", duration=1800, event_uuid="evt-briefing-impact")
        payload = operational_shift_briefing(connection, ReadModelFilters(cliente_id=cliente_id, start=START, end=END), now=NOW)
        after_deliveries = len(listar_alert_deliveries(connection))

    assert payload["impact"]["operational_impact"]["downtime_seconds"] == 1800
    assert payload["impact"]["financial_impact"]["estimated_amount"] == 600.0
    assert payload["financial_impact_calculated"] is True
    assert before_deliveries == after_deliveries
    openai.assert_not_called()


def test_impact_endpoint_and_economic_config_endpoint_are_authenticated_and_tenant_scoped() -> None:
    temp_dir, db_path, connection, cliente_id, site_id, _area_id, _process_id, asset_id, camera_id = make_context()
    with temp_dir:
        create_user(connection, "impact@example.com", "senha", "admin_cliente", cliente_id)
        add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T08:00:00+00:00", end="2026-08-07T08:30:00+00:00", duration=1800, event_uuid="evt-api-impact")
        connection.close()

        def test_connect(_path=None):
            return connect(db_path)

        with patch("app.api.connect", test_connect):
            client = TestClient(api)
            assert client.get("/operations/impact", params={"start": START.isoformat(), "end": END.isoformat()}).status_code == 401
            client.post("/auth/login", json={"email": "impact@example.com", "senha": "senha"})
            config_response = client.put(
                f"/operations/assets/{asset_id}/economic-config",
                json={"method": METHOD_DOWNTIME_COST_PER_HOUR, "downtime_cost_per_hour": 1000, "currency": "BRL"},
            )
            response = client.get("/operations/impact", params={"start": START.isoformat(), "end": END.isoformat(), "camera_id": camera_id})

    assert config_response.status_code == 200
    assert config_response.json()["downtime_cost_per_hour"] == 1000
    assert response.status_code == 200
    assert response.json()["financial_impact"]["estimated_amount"] == 500.0
