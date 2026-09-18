from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from app.operational_alerting import AlertDecisionFilters, list_alert_decisions
from app.operational_impact import calculate_operational_impact
from app.operational_read_model import (
    ReadModelFilters,
    list_events,
    operational_change_anomalies,
    operational_data,
    parse_datetime,
    period_summary,
    to_iso,
)
from app.operational_understanding import UnderstandingFilters, list_validated_understandings


BRIEFING_VERSION = "operational_shift_briefing_v1"
SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def operational_shift_briefing(connection: sqlite3.Connection, filters: ReadModelFilters, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    if not filters.start or not filters.end:
        raise ValueError("Briefing operacional requer início e fim.")
    summary = period_summary(connection, filters, now=now)
    data = operational_data(connection, filters, now=now)
    change_payload = operational_change_anomalies(connection, filters, now=now)
    events = list_events(connection, filters, now=now)
    decisions = list_alert_decisions(
        connection,
        AlertDecisionFilters(
            tenant_id=filters.cliente_id,
            camera_id=filters.camera_id,
            asset_id=filters.asset_id,
        ),
    )
    understandings = list_validated_understandings(
        connection,
        UnderstandingFilters(
            tenant_id=filters.cliente_id,
            camera_id=filters.camera_id,
            asset_id=filters.asset_id,
        ),
    )
    valid_understandings = [item for item in understandings if item.get("status") in {"VALID", "PARTIAL"}]
    incidents = _critical_incidents(decisions, valid_understandings)
    impact = calculate_operational_impact(connection, filters, now=now)
    metrics = _metrics(summary, data, change_payload, decisions, incidents)
    data_quality = _data_quality(summary, data, change_payload)
    overall_status = _overall_status(metrics, incidents, data_quality)
    highlights = _highlights(metrics, data, change_payload, incidents)
    assets = _asset_summary(connection, events, decisions, change_payload)
    return {
        "briefing_id": _briefing_id(filters),
        "briefing_version": BRIEFING_VERSION,
        "start_ts": to_iso(filters.start),
        "end_ts": to_iso(filters.end),
        "overall_status": overall_status,
        "headline": _headline(overall_status, metrics, incidents, data_quality),
        "metrics": metrics,
        "highlights": highlights,
        "critical_incidents": incidents,
        "assets": assets,
        "operational_activity": _operational_activity(change_payload),
        "impact": _briefing_impact(impact),
        "data_quality": data_quality,
        "source_refs": {
            "event_uuids": summary.get("event_uuids") or [],
            "alert_decision_ids": [item["decision_id"] for item in decisions],
            "anomaly_refs": [item["anomaly_type"] for item in change_payload.get("anomalies") or []],
            "understanding_ids": [item["understanding_id"] for item in valid_understandings],
        },
        "generated_at": to_iso(now),
        "cause_inferred": False,
        "financial_impact_calculated": impact.get("financial_impact", {}).get("status") in {"AVAILABLE", "PARTIAL"},
    }


def _briefing_id(filters: ReadModelFilters) -> str:
    payload = {
        "tenant_id": filters.cliente_id,
        "site_id": filters.site_id,
        "area_context_id": filters.area_context_id,
        "process_id": filters.process_id,
        "asset_id": filters.asset_id,
        "camera_id": filters.camera_id,
        "start": to_iso(filters.start) if filters.start else None,
        "end": to_iso(filters.end) if filters.end else None,
        "version": BRIEFING_VERSION,
    }
    return "brf-" + hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:24]


def _briefing_impact(impact: dict[str, Any]) -> dict[str, Any]:
    return {
        "impact_id": impact.get("impact_id"),
        "operational_impact": impact.get("operational_impact"),
        "financial_impact": impact.get("financial_impact"),
        "quality": impact.get("quality"),
        "source_refs": impact.get("source_refs"),
    }


def _metrics(
    summary: dict[str, Any],
    data: dict[str, Any],
    change_payload: dict[str, Any],
    decisions: list[dict[str, Any]],
    incidents: list[dict[str, Any]],
) -> dict[str, Any]:
    machine = data["machine_data"]
    anomalies = change_payload.get("anomalies") or []
    alert_decisions = [item for item in decisions if item.get("decision") == "ALERT"]
    severity_counts: dict[str, int] = {}
    for item in alert_decisions:
        severity_counts[str(item.get("severity") or "medium")] = severity_counts.get(str(item.get("severity") or "medium"), 0) + 1
    offline = [item for item in anomalies if item.get("anomaly_type") == "prolonged_camera_offline"]
    recurrent = [item for item in anomalies if item.get("anomaly_type") == "recurrent_stoppages_short_window"]
    return {
        "period_seconds": _period_seconds(summary),
        "observed_seconds": machine.get("observed_total_seconds") or 0,
        "unknown_seconds": data.get("data_quality", {}).get("unknown_seconds") or 0,
        "coverage_status": (summary.get("coverage") or {}).get("status"),
        "relevant_events": summary.get("total_events") or 0,
        "anomalies": len(anomalies),
        "alert_decisions": len(alert_decisions),
        "alert_decisions_by_severity": severity_counts,
        "unique_incidents": len(incidents),
        "affected_assets": len({item.get("asset_id") for item in incidents if item.get("asset_id")}),
        "offline_cameras": len({(item.get("context") or {}).get("camera_id") for item in offline if (item.get("context") or {}).get("camera_id")}),
        "stoppage_count": machine.get("stoppage_count") or 0,
        "stoppage_total_seconds": machine.get("stoppage_total_seconds") or 0,
        "longest_stoppage_seconds": machine.get("max_stoppage_seconds") or 0,
        "recurrence_count": len(recurrent),
        "operational_absence_seconds": data.get("human_operation_data", {}).get("absence_total_seconds") or 0,
        "lighting_changes": len([item for item in anomalies if item.get("anomaly_type") == "lighting_state_change"]),
        "critical_activity_changes": len([item for item in decisions if item.get("alert_type") == "critical_operational_activity_change"]),
    }


def _period_seconds(summary: dict[str, Any]) -> float:
    period = summary.get("period") or {}
    start = parse_datetime(period.get("start")) if period.get("start") else None
    end = parse_datetime(period.get("end")) if period.get("end") else None
    if not start or not end:
        return 0.0
    return max(0.0, (end - start).total_seconds())


def _overall_status(metrics: dict[str, Any], incidents: list[dict[str, Any]], data_quality: dict[str, Any]) -> str:
    only_technical = bool(incidents) and all(item.get("alert_type") == "technical_camera_offline" for item in incidents)
    poor_coverage = data_quality.get("coverage_status") == "unknown" or data_quality.get("coverage_ratio") is not None and data_quality["coverage_ratio"] < 0.35
    if poor_coverage and (not incidents or only_technical):
        return "UNKNOWN"
    if any(item.get("max_severity") == "critical" for item in incidents):
        return "CRITICAL"
    if incidents or metrics.get("anomalies") or metrics.get("alert_decisions_by_severity", {}).get("high"):
        return "ATTENTION"
    return "NORMAL"


def _headline(overall_status: str, metrics: dict[str, Any], incidents: list[dict[str, Any]], data_quality: dict[str, Any]) -> str:
    if overall_status == "UNKNOWN":
        return "Não há cobertura suficiente para avaliar a operação com segurança neste período."
    if overall_status == "CRITICAL":
        critical = [item for item in incidents if item.get("max_severity") == "critical"]
        return f"{len(critical)} incidente(s) crítico(s) no período; revisar evidências e eventos relacionados."
    if incidents:
        top = incidents[0]
        asset = top.get("asset_label") or top.get("asset_id") or top.get("camera_id") or "operação"
        return f"{len(incidents)} incidente(s) relevante(s) no período; {asset} concentrou o principal alerta."
    if metrics.get("relevant_events"):
        return f"{metrics['relevant_events']} evento(s) registrado(s), sem incidentes críticos de alerta."
    if data_quality.get("coverage_status") == "partial":
        return "Operação sem incidentes relevantes, com cobertura parcial dos dados."
    return "Operação estável no período, sem incidentes críticos."


def _highlights(
    metrics: dict[str, Any],
    data: dict[str, Any],
    change_payload: dict[str, Any],
    incidents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    highlights: list[dict[str, Any]] = []
    if metrics.get("stoppage_count"):
        highlights.append(
            _highlight(
                "stoppages",
                f"{metrics['stoppage_count']} parada(s) no período.",
                {"stoppage_count": metrics["stoppage_count"], "total_seconds": metrics["stoppage_total_seconds"]},
                data["machine_data"].get("traceability", {}).get("event_uuids", []),
            )
        )
    if metrics.get("longest_stoppage_seconds"):
        longest = max(data["machine_data"].get("critical_times") or [], key=lambda item: float(item.get("duration_seconds") or 0), default={})
        highlights.append(
            _highlight(
                "longest_stoppage",
                f"A maior parada durou {_seconds_label(metrics['longest_stoppage_seconds'])}.",
                {"duration_seconds": metrics["longest_stoppage_seconds"]},
                [longest.get("event_uuid")] if longest.get("event_uuid") else [],
            )
        )
    for incident in incidents[:3]:
        highlights.append(
            {
                "type": "critical_incident",
                "text": f"{incident['title']} ({incident['max_severity']}).",
                "metrics": {"alert_type": incident["alert_type"], "decisions": len(incident["alert_decision_refs"])},
                "source_refs": {
                    "event_uuids": incident["event_refs"],
                    "alert_decision_ids": incident["alert_decision_refs"],
                    "evidence_refs": incident["evidence_refs"],
                    "understanding_refs": incident["understanding_refs"],
                },
                "cause_inferred": False,
            }
        )
    offline = [item for item in change_payload.get("anomalies") or [] if item.get("anomaly_type") == "prolonged_camera_offline"]
    for item in offline[:2]:
        highlights.append(
            _highlight(
                "camera_offline",
                item.get("title") or "Câmera offline no período.",
                {"duration_seconds": item.get("observed_value")},
                item.get("event_refs") or [],
                anomaly_refs=[item.get("anomaly_type")],
            )
        )
    return highlights[:8]


def _highlight(kind: str, text: str, metrics: dict[str, Any], event_uuids: list[Any], anomaly_refs: list[Any] | None = None) -> dict[str, Any]:
    return {
        "type": kind,
        "text": text,
        "metrics": metrics,
        "source_refs": {
            "event_uuids": [str(item) for item in event_uuids if item],
            "anomaly_refs": [str(item) for item in anomaly_refs or [] if item],
        },
        "cause_inferred": False,
    }


def _critical_incidents(decisions: list[dict[str, Any]], understandings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for decision in decisions:
        if decision.get("decision") != "ALERT":
            continue
        key = decision["incident_key"]
        item = grouped.setdefault(
            key,
            {
                "incident_key": key,
                "alert_type": decision.get("alert_type"),
                "asset_id": decision.get("asset_id"),
                "asset_label": decision.get("asset_id"),
                "camera_id": decision.get("camera_id"),
                "max_severity": decision.get("severity") or "medium",
                "start_ts": decision.get("created_at"),
                "end_ts": None,
                "active": bool(decision.get("active")),
                "alert_decision_refs": [],
                "event_refs": [],
                "anomaly_refs": [],
                "evidence_refs": [],
                "understanding_refs": [],
                "summary": decision.get("summary"),
                "title": decision.get("title"),
                "visual_context": [],
                "uncertainties": [],
                "cause_inferred": False,
            },
        )
        if SEVERITY_RANK.get(str(decision.get("severity")), 0) > SEVERITY_RANK.get(item["max_severity"], 0):
            item["max_severity"] = decision.get("severity")
        item["active"] = item["active"] or bool(decision.get("active"))
        item["alert_decision_refs"].append(decision["decision_id"])
        item["event_refs"].extend(decision.get("event_refs") or [])
        item["anomaly_refs"].extend(decision.get("anomaly_refs") or [])
        item["evidence_refs"].extend(decision.get("evidence_refs") or [])
        item["understanding_refs"].extend(decision.get("understanding_refs") or [])
        if decision.get("visual_summary"):
            item["visual_context"].append(decision["visual_summary"])
        item["uncertainties"].extend(decision.get("uncertainties") or [])
    by_id = {item["understanding_id"]: item for item in understandings if item.get("status") in {"VALID", "PARTIAL"}}
    for item in grouped.values():
        item["alert_decision_refs"] = _dedupe(item["alert_decision_refs"])
        item["event_refs"] = _dedupe(item["event_refs"])
        item["anomaly_refs"] = _dedupe(item["anomaly_refs"])
        item["evidence_refs"] = _dedupe_jsonable(item["evidence_refs"])
        item["understanding_refs"] = _dedupe(item["understanding_refs"])
        item["visual_context"].extend(
            by_id[understanding_id].get("summary")
            for understanding_id in item["understanding_refs"]
            if understanding_id in by_id and by_id[understanding_id].get("summary")
        )
        item["uncertainties"].extend(
            uncertainty
            for understanding_id in item["understanding_refs"]
            if understanding_id in by_id
            for uncertainty in by_id[understanding_id].get("uncertainties") or []
        )
        item["visual_context"] = _dedupe(item["visual_context"])
        item["uncertainties"] = _dedupe(item["uncertainties"])
    return sorted(grouped.values(), key=lambda item: (-SEVERITY_RANK.get(item["max_severity"], 0), item["incident_key"]))


def _asset_summary(
    connection: sqlite3.Connection,
    events: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    change_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for event in events:
        asset_id = event.get("asset_id")
        if not asset_id:
            continue
        item = grouped.setdefault(asset_id, _asset_item(connection, asset_id))
        if event.get("tipo") == "machine_stoppage":
            item["stoppage_count"] += 1
            item["stopped_seconds"] += float(event.get("read_duration_seconds") or 0)
            item["longest_stoppage_seconds"] = max(item["longest_stoppage_seconds"], float(event.get("read_duration_seconds") or 0))
            item["event_refs"].append(str(event.get("event_uuid") or event.get("id")))
    for decision in decisions:
        asset_id = decision.get("asset_id")
        if not asset_id:
            continue
        item = grouped.setdefault(asset_id, _asset_item(connection, asset_id))
        if decision.get("decision") == "ALERT":
            item["alerts"] += 1
            item["alert_decision_refs"].append(decision["decision_id"])
    for anomaly in change_payload.get("anomalies") or []:
        context = anomaly.get("context") or {}
        asset_id = context.get("asset_id")
        if not asset_id:
            continue
        item = grouped.setdefault(asset_id, _asset_item(connection, asset_id))
        item["anomalies"] += 1
        item["main_changes"].append(anomaly.get("anomaly_type"))
    for item in grouped.values():
        item["stopped_seconds"] = round(item["stopped_seconds"], 3)
        item["longest_stoppage_seconds"] = round(item["longest_stoppage_seconds"], 3)
        item["event_refs"] = _dedupe(item["event_refs"])
        item["alert_decision_refs"] = _dedupe(item["alert_decision_refs"])
        item["main_changes"] = _dedupe(item["main_changes"])
    return sorted(grouped.values(), key=lambda item: (-item["stopped_seconds"], -item["alerts"], item["asset_label"]))


def _asset_item(connection: sqlite3.Connection, asset_id: str) -> dict[str, Any]:
    row = connection.execute("SELECT nome FROM operational_assets WHERE id = ?", (asset_id,)).fetchone()
    return {
        "asset_id": asset_id,
        "asset_label": row["nome"] if row else asset_id,
        "observed_status": "observed",
        "stopped_seconds": 0.0,
        "stoppage_count": 0,
        "longest_stoppage_seconds": 0.0,
        "alerts": 0,
        "anomalies": 0,
        "main_changes": [],
        "event_refs": [],
        "alert_decision_refs": [],
    }


def _operational_activity(change_payload: dict[str, Any]) -> dict[str, Any]:
    items = change_payload.get("operational_activity") or []
    counts: dict[str, int] = {}
    refs: list[dict[str, Any]] = []
    for item in items:
        state = str(item.get("new_state") or "UNKNOWN")
        counts[state] = counts.get(state, 0) + 1
        refs.append({"timestamp": item.get("timestamp"), "state": state, "confidence": item.get("confidence")})
    return {"states": counts, "changes": refs, "source": "operational_change_anomalies"}


def _data_quality(summary: dict[str, Any], data: dict[str, Any], change_payload: dict[str, Any]) -> dict[str, Any]:
    coverage = summary.get("coverage") or {}
    period_seconds = _period_seconds(summary)
    unknown_seconds = float(data.get("data_quality", {}).get("unknown_seconds") or 0)
    observed_seconds = float(data.get("machine_data", {}).get("observed_total_seconds") or 0)
    offline = [item for item in change_payload.get("anomalies") or [] if item.get("anomaly_type") == "prolonged_camera_offline"]
    coverage_ratio = None
    if period_seconds:
        coverage_ratio = round(max(0.0, min(1.0, (period_seconds - unknown_seconds) / period_seconds)), 4)
    return {
        "coverage_status": coverage.get("status") or data.get("coverage", {}).get("status"),
        "coverage_ratio": coverage_ratio,
        "observed_seconds": round(observed_seconds, 3),
        "unknown_seconds": round(unknown_seconds, 3),
        "sample_count": coverage.get("sample_count") or data.get("data_quality", {}).get("sample_count") or 0,
        "gaps": coverage.get("gaps") or [],
        "offline_cameras": _dedupe([(item.get("context") or {}).get("camera_id") for item in offline if (item.get("context") or {}).get("camera_id")]),
        "limitations": _quality_limitations(coverage, unknown_seconds, offline),
        "unknown_is_not_interpreted_as_normal": True,
    }


def _quality_limitations(coverage: dict[str, Any], unknown_seconds: float, offline: list[dict[str, Any]]) -> list[str]:
    limitations: list[str] = []
    if coverage.get("status") in {"unknown", "partial"}:
        limitations.append(f"coverage_{coverage.get('status')}")
    if unknown_seconds > 0:
        limitations.append("unknown_time_present")
    if offline:
        limitations.append("camera_offline_periods_present")
    return _dedupe(limitations)


def _seconds_label(value: float | int | None) -> str:
    total = max(0, int(round(float(value or 0))))
    minutes = total // 60
    seconds = total % 60
    if minutes >= 60:
        return f"{minutes // 60}h {minutes % 60:02d}m"
    if minutes:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"


def _dedupe(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _dedupe_jsonable(values: list[Any]) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for value in values:
        key = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result
