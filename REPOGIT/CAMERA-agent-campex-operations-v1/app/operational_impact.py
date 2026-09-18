from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from app.event_taxonomy import EVENT_FAMILY_INTERRUPTION
from app.models import row_to_dict
from app.operational_read_model import ReadModelFilters, list_events, operational_data, parse_datetime, to_iso


IMPACT_VERSION = "operational_financial_impact_v1"
METHOD_DOWNTIME_COST_PER_HOUR = "downtime_cost_per_hour"
METHOD_PRODUCTION_RATE_CONTRIBUTION = "production_rate_per_hour_x_contribution_value_per_unit"
SUPPORTED_METHODS = {METHOD_DOWNTIME_COST_PER_HOUR, METHOD_PRODUCTION_RATE_CONTRIBUTION}


def get_asset_economic_config(connection: sqlite3.Connection, asset_id: str, *, tenant_id: str | None = None) -> dict[str, Any] | None:
    clauses = ["id = ?"]
    params: list[Any] = [asset_id]
    if tenant_id:
        clauses.append("cliente_id = ?")
        params.append(tenant_id)
    row = connection.execute(
        f"""
        SELECT id, cliente_id, unidade_id, economic_method, downtime_cost_per_hour,
               production_rate_per_hour, contribution_value_per_unit, economic_currency,
               economic_effective_from, atualizado_em
        FROM operational_assets
        WHERE {' AND '.join(clauses)}
        """,
        params,
    ).fetchone()
    if row is None:
        return None
    data = row_to_dict(row)
    return {
        "asset_id": data["id"],
        "tenant_id": data["cliente_id"],
        "site_id": data["unidade_id"],
        "method": data.get("economic_method"),
        "downtime_cost_per_hour": data.get("downtime_cost_per_hour"),
        "production_rate_per_hour": data.get("production_rate_per_hour"),
        "contribution_value_per_unit": data.get("contribution_value_per_unit"),
        "currency": data.get("economic_currency"),
        "effective_from": data.get("economic_effective_from"),
        "updated_at": data.get("atualizado_em"),
    }


def upsert_asset_economic_config(
    connection: sqlite3.Connection,
    asset_id: str,
    *,
    tenant_id: str | None,
    method: str | None,
    currency: str | None = "BRL",
    downtime_cost_per_hour: float | None = None,
    production_rate_per_hour: float | None = None,
    contribution_value_per_unit: float | None = None,
    effective_from: datetime | None = None,
) -> dict[str, Any] | None:
    if method is not None and method not in SUPPORTED_METHODS:
        raise ValueError("Método econômico não suportado.")
    if currency is not None and not str(currency).strip():
        raise ValueError("Moeda precisa ser informada quando houver configuração econômica.")
    existing = get_asset_economic_config(connection, asset_id, tenant_id=tenant_id)
    if existing is None:
        return None
    _validate_config(
        method=method,
        downtime_cost_per_hour=downtime_cost_per_hour,
        production_rate_per_hour=production_rate_per_hour,
        contribution_value_per_unit=contribution_value_per_unit,
    )
    connection.execute(
        """
        UPDATE operational_assets
        SET economic_method = ?,
            downtime_cost_per_hour = ?,
            production_rate_per_hour = ?,
            contribution_value_per_unit = ?,
            economic_currency = ?,
            economic_effective_from = ?,
            atualizado_em = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            method,
            downtime_cost_per_hour,
            production_rate_per_hour,
            contribution_value_per_unit,
            currency,
            to_iso(effective_from) if effective_from else None,
            asset_id,
        ),
    )
    connection.commit()
    return get_asset_economic_config(connection, asset_id, tenant_id=tenant_id)


def calculate_operational_impact(connection: sqlite3.Connection, filters: ReadModelFilters, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    if not filters.start or not filters.end:
        raise ValueError("Impacto operacional requer início e fim.")
    data = operational_data(connection, filters, now=now)
    events = list_events(connection, filters, now=now)
    stoppages = _stoppage_events(events)
    merged_by_asset = _merged_stoppage_segments_by_asset(stoppages, filters.start, filters.end, now)
    asset_impacts = [_asset_impact(connection, asset_id, segments, stoppages, filters, now) for asset_id, segments in merged_by_asset.items()]
    asset_impacts.sort(key=lambda item: (-item["operational_impact"]["downtime_seconds"], item["asset_id"]))

    downtime_seconds = sum(item["operational_impact"]["downtime_seconds"] for item in asset_impacts)
    financial = _aggregate_financial(asset_impacts)
    quality = _quality(data, stoppages, filters.start, filters.end, now)
    event_uuids = _dedupe([_event_uuid(event) for event in stoppages])
    return {
        "impact_id": _impact_id(filters),
        "impact_version": IMPACT_VERSION,
        "start_ts": to_iso(filters.start),
        "end_ts": to_iso(filters.end),
        "operational_impact": {
            "downtime_seconds": round(downtime_seconds, 3),
            "downtime_minutes": round(downtime_seconds / 60.0, 3),
            "downtime_hours": round(downtime_seconds / 3600.0, 6),
            "stoppage_count": len(event_uuids),
            "repeated_stoppages": max(0, len(event_uuids) - len(asset_impacts)),
            "affected_assets": len([item for item in asset_impacts if item["asset_id"] != "unassigned"]),
            "observed_low_activity_minutes": _low_activity_minutes(data),
            "operational_absence_minutes": round(float(data["human_operation_data"].get("absence_total_seconds") or 0) / 60.0, 3),
            "camera_unobserved_minutes": round(float(data["data_quality"].get("unknown_seconds") or 0) / 60.0, 3),
            "lost_observation_time_minutes": round(float(data["data_quality"].get("unknown_seconds") or 0) / 60.0, 3),
            "incident_count": len(event_uuids),
        },
        "assets": asset_impacts,
        "financial_impact": financial,
        "quality": quality,
        "source_refs": {
            "event_uuids": event_uuids,
            "sample_count": data["data_quality"].get("sample_count") or 0,
            "config_refs": [item["financial_impact"].get("config_ref") for item in asset_impacts if item["financial_impact"].get("config_ref")],
        },
        "generated_at": to_iso(now),
        "no_openai_call": True,
        "no_alerts_created": True,
    }


def _validate_config(
    *,
    method: str | None,
    downtime_cost_per_hour: float | None,
    production_rate_per_hour: float | None,
    contribution_value_per_unit: float | None,
) -> None:
    values = [downtime_cost_per_hour, production_rate_per_hour, contribution_value_per_unit]
    if any(value is not None and float(value) < 0 for value in values):
        raise ValueError("Parâmetros econômicos não podem ser negativos.")
    if method == METHOD_DOWNTIME_COST_PER_HOUR and downtime_cost_per_hour is None:
        raise ValueError("downtime_cost_per_hour é obrigatório para este método.")
    if method == METHOD_PRODUCTION_RATE_CONTRIBUTION and (production_rate_per_hour is None or contribution_value_per_unit is None):
        raise ValueError("production_rate_per_hour e contribution_value_per_unit são obrigatórios para este método.")


def _stoppage_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        event
        for event in events
        if event.get("tipo") == "machine_stoppage" and (event.get("event_family") or EVENT_FAMILY_INTERRUPTION) == EVENT_FAMILY_INTERRUPTION
    ]


def _merged_stoppage_segments_by_asset(
    events: list[dict[str, Any]],
    start: datetime,
    end: datetime,
    now: datetime,
) -> dict[str, list[tuple[datetime, datetime, list[str]]]]:
    raw: dict[str, list[tuple[datetime, datetime, str]]] = {}
    for event in events:
        event_start = parse_datetime(event.get("inicio"), start)
        event_end = parse_datetime(event.get("fim"), now) if event.get("fim") else min(now, end)
        effective_start = max(start, event_start)
        effective_end = min(end, event_end)
        if effective_end <= effective_start:
            continue
        asset_id = str(event.get("asset_id") or "unassigned")
        raw.setdefault(asset_id, []).append((effective_start, effective_end, _event_uuid(event)))

    merged: dict[str, list[tuple[datetime, datetime, list[str]]]] = {}
    for asset_id, segments in raw.items():
        ordered = sorted(segments, key=lambda item: item[0])
        for segment_start, segment_end, event_uuid in ordered:
            asset_segments = merged.setdefault(asset_id, [])
            if not asset_segments or segment_start > asset_segments[-1][1]:
                asset_segments.append((segment_start, segment_end, [event_uuid]))
            else:
                previous_start, previous_end, refs = asset_segments[-1]
                refs.append(event_uuid)
                asset_segments[-1] = (previous_start, max(previous_end, segment_end), _dedupe(refs))
    return merged


def _asset_impact(
    connection: sqlite3.Connection,
    asset_id: str,
    segments: list[tuple[datetime, datetime, list[str]]],
    events: list[dict[str, Any]],
    filters: ReadModelFilters,
    now: datetime,
) -> dict[str, Any]:
    downtime_seconds = sum((end - start).total_seconds() for start, end, _refs in segments)
    asset_events = [event for event in events if str(event.get("asset_id") or "unassigned") == asset_id]
    event_uuids = _dedupe([_event_uuid(event) for event in asset_events])
    ongoing = any(not event.get("fim") for event in asset_events)
    boundary_cut = any(
        parse_datetime(event.get("inicio"), filters.start) < filters.start
        or (parse_datetime(event.get("fim"), now) if event.get("fim") else min(now, filters.end)) > filters.end
        for event in asset_events
    )
    financial = _financial_for_asset(connection, asset_id, downtime_seconds, filters.cliente_id)
    return {
        "asset_id": asset_id,
        "operational_impact": {
            "downtime_seconds": round(downtime_seconds, 3),
            "downtime_minutes": round(downtime_seconds / 60.0, 3),
            "downtime_hours": round(downtime_seconds / 3600.0, 6),
            "stoppage_count": len(event_uuids),
            "longest_stoppage_seconds": round(max(((end - start).total_seconds() for start, end, _refs in segments), default=0.0), 3),
            "ongoing": ongoing,
        },
        "financial_impact": financial,
        "quality": {
            "status": "PARTIAL" if ongoing or boundary_cut else "COMPLETE",
            "reasons": [reason for reason, enabled in {"event_open": ongoing, "event_boundary_outside_window": boundary_cut}.items() if enabled],
        },
        "source_refs": {"event_uuids": event_uuids},
        "segments": [
            {"start": to_iso(start), "end": to_iso(end), "duration_seconds": round((end - start).total_seconds(), 3), "event_uuids": refs}
            for start, end, refs in segments
        ],
    }


def _financial_for_asset(connection: sqlite3.Connection, asset_id: str, downtime_seconds: float, tenant_id: str | None) -> dict[str, Any]:
    if asset_id == "unassigned":
        return {"status": "NOT_AVAILABLE", "reason": "asset_not_available"}
    config = get_asset_economic_config(connection, asset_id, tenant_id=tenant_id)
    if not config or not config.get("method"):
        return {"status": "NOT_AVAILABLE", "reason": "economic_parameters_not_configured"}
    method = config["method"]
    currency = config.get("currency") or "BRL"
    downtime_hours = downtime_seconds / 3600.0
    if method == METHOD_DOWNTIME_COST_PER_HOUR and config.get("downtime_cost_per_hour") is not None:
        rate = float(config["downtime_cost_per_hour"])
        amount = downtime_hours * rate
        inputs = {"downtime_hours": round(downtime_hours, 6), "downtime_cost_per_hour": rate}
        formula = "downtime_hours × downtime_cost_per_hour"
    elif method == METHOD_PRODUCTION_RATE_CONTRIBUTION and config.get("production_rate_per_hour") is not None and config.get("contribution_value_per_unit") is not None:
        production_rate = float(config["production_rate_per_hour"])
        contribution = float(config["contribution_value_per_unit"])
        amount = downtime_hours * production_rate * contribution
        inputs = {
            "downtime_hours": round(downtime_hours, 6),
            "production_rate_per_hour": production_rate,
            "contribution_value_per_unit": contribution,
        }
        formula = "downtime_hours × production_rate_per_hour × contribution_value_per_unit"
    else:
        return {"status": "NOT_AVAILABLE", "reason": "economic_parameters_incomplete", "method": method}
    return {
        "status": "AVAILABLE",
        "estimated_amount": round(amount, 2),
        "currency": currency,
        "method": method,
        "inputs": inputs,
        "formula": formula,
        "config_ref": f"operational_assets:{asset_id}:economic_config",
        "effective_from": config.get("effective_from"),
        "updated_at": config.get("updated_at"),
        "terminology": "estimated_downtime_impact",
    }


def _aggregate_financial(asset_impacts: list[dict[str, Any]]) -> dict[str, Any]:
    available = [item["financial_impact"] for item in asset_impacts if item["financial_impact"].get("status") == "AVAILABLE"]
    if not asset_impacts:
        return {"status": "NOT_AVAILABLE", "reason": "no_downtime_incidents"}
    if not available:
        return {"status": "NOT_AVAILABLE", "reason": "economic_parameters_not_configured"}
    currencies = {item["currency"] for item in available}
    status = "AVAILABLE" if len(available) == len(asset_impacts) and len(currencies) == 1 else "PARTIAL"
    return {
        "status": status,
        "estimated_amount": round(sum(float(item["estimated_amount"]) for item in available), 2),
        "currency": sorted(currencies)[0] if len(currencies) == 1 else None,
        "method": "asset_configured_methods",
        "inputs": {"asset_count": len(asset_impacts), "assets_with_financial_config": len(available)},
        "formula": "sum(asset_estimated_downtime_impact)",
        "asset_impacts": available,
    }


def _quality(data: dict[str, Any], stoppages: list[dict[str, Any]], start: datetime, end: datetime, now: datetime) -> dict[str, Any]:
    reasons: list[str] = []
    coverage = data.get("coverage") or {}
    if coverage.get("status") in {"partial", "unknown"}:
        reasons.append("partial_observation" if coverage.get("status") == "partial" else "unknown_period_present")
    if data.get("data_quality", {}).get("unknown_seconds"):
        reasons.append("unknown_period_present")
    for event in stoppages:
        event_start = parse_datetime(event.get("inicio"), start)
        event_end = parse_datetime(event.get("fim"), now) if event.get("fim") else min(now, end)
        if not event.get("fim"):
            reasons.append("event_open")
        if event_start < start or event_end > end:
            reasons.append("event_boundary_outside_window")
    return {
        "status": "PARTIAL" if reasons else "COMPLETE",
        "reasons": _dedupe(reasons),
        "coverage": coverage,
        "unknown_is_not_counted_as_downtime": True,
        "camera_offline_is_not_counted_as_machine_stopped": True,
    }


def _low_activity_minutes(data: dict[str, Any]) -> float:
    return 0.0


def _impact_id(filters: ReadModelFilters) -> str:
    payload = {
        "tenant_id": filters.cliente_id,
        "site_id": filters.site_id,
        "area_context_id": filters.area_context_id,
        "process_id": filters.process_id,
        "asset_id": filters.asset_id,
        "camera_id": filters.camera_id,
        "start": to_iso(filters.start) if filters.start else None,
        "end": to_iso(filters.end) if filters.end else None,
        "version": IMPACT_VERSION,
    }
    return "imp-" + hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:24]


def _event_uuid(event: dict[str, Any]) -> str:
    return str(event.get("event_uuid") or event.get("id"))


def _dedupe(values: list[Any]) -> list[Any]:
    seen: set[Any] = set()
    result: list[Any] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
