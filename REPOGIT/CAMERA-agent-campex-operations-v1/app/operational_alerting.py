from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.operational_read_model import ReadModelFilters, operational_change_anomalies, parse_datetime, to_iso
from app.operational_understanding import UnderstandingFilters, list_validated_understandings


ALERT_DECISIONS = {"ALERT", "SUPPRESS", "INSUFFICIENT_DATA"}
ALERT_SEVERITIES = {"low", "medium", "high", "critical"}
MATERIAL_ESCALATION_SECONDS = 1800.0
DEFAULT_COOLDOWN_SECONDS = 1800.0

ALERT_POLICY = {
    "exceptionally_long_stoppage": {
        "alert_type": "prolonged_stoppage",
        "base_severity": "high",
        "cooldown_seconds": DEFAULT_COOLDOWN_SECONDS,
        "material_escalation_seconds": MATERIAL_ESCALATION_SECONDS,
        "technical": False,
    },
    "recurrent_stoppages_short_window": {
        "alert_type": "recurrent_stoppages",
        "base_severity": "medium",
        "cooldown_seconds": DEFAULT_COOLDOWN_SECONDS,
        "technical": False,
    },
    "prolonged_operational_absence": {
        "alert_type": "prolonged_operational_absence",
        "base_severity": "medium",
        "cooldown_seconds": DEFAULT_COOLDOWN_SECONDS,
        "technical": False,
    },
    "prolonged_camera_offline": {
        "alert_type": "technical_camera_offline",
        "base_severity": "high",
        "cooldown_seconds": 3600.0,
        "technical": True,
    },
    "lighting_state_change": {
        "alert_type": "persistent_lighting_change",
        "base_severity": "low",
        "cooldown_seconds": 3600.0,
        "technical": False,
    },
    "critical_operational_activity_change": {
        "alert_type": "critical_operational_activity_change",
        "base_severity": "medium",
        "cooldown_seconds": DEFAULT_COOLDOWN_SECONDS,
        "technical": False,
    },
}


@dataclass(frozen=True)
class AlertDecisionFilters:
    tenant_id: str | None = None
    camera_id: str | None = None
    asset_id: str | None = None
    decision: str | None = None
    severity: str | None = None
    alert_type: str | None = None
    active: bool | None = None
    start: str | None = None
    end: str | None = None


def evaluate_alert_decisions(
    connection: sqlite3.Connection,
    filters: ReadModelFilters,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    change_payload = operational_change_anomalies(connection, filters, now=now)
    candidates = _decision_candidates(connection, filters, change_payload)
    decisions = [persist_alert_decision(connection, candidate, now=now) for candidate in candidates]
    return {
        "period": change_payload["period"],
        "filters": change_payload["filters"],
        "decisions": decisions,
        "count": len(decisions),
        "rules": [
            "critical_operational_alert_decisioning_v1",
            "incident_key_dedup_v1",
            "material_escalation_v1",
            "cooldown_suppression_v1",
            "validated_understanding_enrichment_v1",
        ],
        "delivery_performed": False,
        "cause_inferred": False,
    }


def persist_alert_decision(connection: sqlite3.Connection, record: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    existing_same = get_alert_decision_by_key(connection, record["decision_key"], tenant_id=record.get("tenant_id"))
    if existing_same:
        return existing_same
    previous = _latest_alert_for_incident(connection, record["incident_key"], tenant_id=record.get("tenant_id"))
    if record["decision"] == "ALERT" and previous and not _material_escalation(previous, record) and not _cooldown_elapsed(previous, now, float(record.get("cooldown_seconds") or DEFAULT_COOLDOWN_SECONDS)):
        record = dict(record)
        record["decision"] = "SUPPRESS"
        record["suppression"] = {
            "reason": "cooldown_active",
            "previous_decision_id": previous["decision_id"],
            "previous_severity": previous["severity"],
        }
        record["reason_codes"] = _dedupe_strings([*(record.get("reason_codes") or []), "suppressed_by_cooldown"])
        record["decision_key"] = _decision_key(record["incident_key"], record["alert_type"], record["decision"], record["severity"], record.get("suppression", {}).get("reason"))
    existing_suppressed = get_alert_decision_by_key(connection, record["decision_key"], tenant_id=record.get("tenant_id"))
    if existing_suppressed:
        return existing_suppressed
    connection.execute(
        """
        INSERT INTO operational_alert_decisions (
            decision_id, decision_key, incident_key, tenant_id, site_id, unit_id,
            area_context_id, process_id, asset_id, camera_id, alert_type, decision,
            severity, priority, title, summary, active, source_refs_json,
            event_refs_json, anomaly_refs_json, understanding_refs_json,
            evidence_refs_json, reason_codes_json, suppression_json, quality_json,
            visual_summary, visual_facts_json, uncertainties_json, cause_inferred
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record["decision_id"],
            record["decision_key"],
            record["incident_key"],
            record.get("tenant_id"),
            record.get("site_id"),
            record.get("unit_id"),
            record.get("area_context_id"),
            record.get("process_id"),
            record.get("asset_id"),
            record.get("camera_id"),
            record["alert_type"],
            record["decision"],
            record["severity"],
            record.get("priority"),
            record["title"],
            record["summary"],
            1 if record.get("active", True) else 0,
            json.dumps(record.get("source_refs") or [], ensure_ascii=False),
            json.dumps(record.get("event_refs") or [], ensure_ascii=False),
            json.dumps(record.get("anomaly_refs") or [], ensure_ascii=False),
            json.dumps(record.get("understanding_refs") or [], ensure_ascii=False),
            json.dumps(record.get("evidence_refs") or [], ensure_ascii=False),
            json.dumps(record.get("reason_codes") or [], ensure_ascii=False),
            json.dumps(record.get("suppression"), ensure_ascii=False) if record.get("suppression") else None,
            json.dumps(record.get("quality") or {}, ensure_ascii=False),
            record.get("visual_summary"),
            json.dumps(record.get("visual_facts") or [], ensure_ascii=False),
            json.dumps(record.get("uncertainties") or [], ensure_ascii=False),
            1 if record.get("cause_inferred") else 0,
        ),
    )
    connection.commit()
    return get_alert_decision_by_key(connection, record["decision_key"], tenant_id=record.get("tenant_id")) or record


def list_alert_decisions(connection: sqlite3.Connection, filters: AlertDecisionFilters | None = None) -> list[dict[str, Any]]:
    filters = filters or AlertDecisionFilters()
    clauses: list[str] = []
    values: list[Any] = []
    for column, value in (
        ("tenant_id", filters.tenant_id),
        ("camera_id", filters.camera_id),
        ("asset_id", filters.asset_id),
        ("decision", filters.decision),
        ("severity", filters.severity),
        ("alert_type", filters.alert_type),
    ):
        if value:
            clauses.append(f"{column} = ?")
            values.append(value)
    if filters.active is not None:
        clauses.append("active = ?")
        values.append(1 if filters.active else 0)
    if filters.start:
        clauses.append("created_at >= ?")
        values.append(filters.start)
    if filters.end:
        clauses.append("created_at <= ?")
        values.append(filters.end)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = connection.execute(f"SELECT * FROM operational_alert_decisions {where} ORDER BY created_at DESC, decision_id DESC", values).fetchall()
    return [_row_to_decision(row) for row in rows]


def get_alert_decision(connection: sqlite3.Connection, decision_id: str, *, tenant_id: str | None = None) -> dict[str, Any] | None:
    clauses = ["decision_id = ?"]
    values: list[Any] = [decision_id]
    if tenant_id:
        clauses.append("tenant_id = ?")
        values.append(tenant_id)
    row = connection.execute(f"SELECT * FROM operational_alert_decisions WHERE {' AND '.join(clauses)}", values).fetchone()
    return _row_to_decision(row) if row else None


def get_alert_decision_by_key(connection: sqlite3.Connection, decision_key: str, *, tenant_id: str | None = None) -> dict[str, Any] | None:
    clauses = ["decision_key = ?"]
    values: list[Any] = [decision_key]
    if tenant_id:
        clauses.append("tenant_id = ?")
        values.append(tenant_id)
    row = connection.execute(f"SELECT * FROM operational_alert_decisions WHERE {' AND '.join(clauses)}", values).fetchone()
    return _row_to_decision(row) if row else None


def _decision_candidates(connection: sqlite3.Connection, filters: ReadModelFilters, change_payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for anomaly in change_payload.get("anomalies") or []:
        candidate = _candidate_from_anomaly(connection, filters, anomaly)
        if candidate:
            candidates.append(candidate)
    for item in change_payload.get("operational_activity") or []:
        if item.get("new_state") in {"LOW_ACTIVITY", "NO_ACTIVITY"} and item.get("data_quality") != "insufficient_data":
            candidates.append(_candidate_from_activity(connection, filters, item))
    return candidates


def _candidate_from_anomaly(connection: sqlite3.Connection, filters: ReadModelFilters, anomaly: dict[str, Any]) -> dict[str, Any] | None:
    anomaly_type = str(anomaly.get("anomaly_type") or "")
    policy = ALERT_POLICY.get(anomaly_type)
    if not policy:
        return None
    context = anomaly.get("context") if isinstance(anomaly.get("context"), dict) else {}
    reason_codes = [f"rule:{anomaly_type}", "deterministic_policy_v1"]
    decision = "ALERT"
    quality = {"status": anomaly.get("data_quality") or "observed", "confidence": anomaly.get("confidence")}
    if anomaly.get("data_quality") in {"insufficient_data", "unknown"} and anomaly_type != "prolonged_camera_offline":
        decision = "INSUFFICIENT_DATA"
        reason_codes.append("insufficient_operational_data")
    if anomaly_type == "prolonged_camera_offline":
        reason_codes.extend(["technical_alert", "no_visual_inference_while_offline"])
    if anomaly.get("event_refs") and _all_events_resolved(connection, anomaly.get("event_refs") or []):
        decision = "SUPPRESS"
        reason_codes.append("event_already_resolved")
    severity = _severity_for_anomaly(anomaly, policy)
    incident_key = _incident_key(policy["alert_type"], context, anomaly.get("event_refs") or [], anomaly.get("timestamp"))
    enrichment = _validated_understanding_enrichment(connection, filters, context, anomaly.get("event_refs") or [])
    reason_codes.extend(enrichment["reason_codes"])
    if enrichment["rejected_seen"]:
        reason_codes.append("rejected_understanding_ignored")
    evidence_refs = _dedupe_jsonable([*(anomaly.get("evidence_refs") or []), *enrichment["evidence_refs"]])
    return _base_record(
        alert_type=policy["alert_type"],
        incident_key=incident_key,
        decision=decision,
        severity=severity,
        title=anomaly.get("title") or str(policy["alert_type"]),
        summary=anomaly.get("description") or "Situação operacional relevante detectada por regra determinística.",
        context=context,
        tenant_id=filters.cliente_id,
        source_refs=[{"type": "anomaly", "ref": anomaly_type, "timestamp": anomaly.get("timestamp")}],
        event_refs=anomaly.get("event_refs") or [],
        anomaly_refs=[anomaly_type],
        evidence_refs=evidence_refs,
        reason_codes=reason_codes,
        quality=quality,
        active=_incident_active(connection, anomaly.get("event_refs") or []),
        visual_summary=enrichment["visual_summary"],
        visual_facts=enrichment["visual_facts"],
        understanding_refs=enrichment["understanding_refs"],
        uncertainties=enrichment["uncertainties"],
    )


def _candidate_from_activity(connection: sqlite3.Connection, filters: ReadModelFilters, item: dict[str, Any]) -> dict[str, Any]:
    context = item.get("context") if isinstance(item.get("context"), dict) else {}
    alert_type = "critical_operational_activity_change"
    incident_key = _incident_key(alert_type, context, [], item.get("timestamp"))
    severity = "high" if item.get("new_state") == "NO_ACTIVITY" else "medium"
    return _base_record(
        alert_type=alert_type,
        incident_key=incident_key,
        decision="ALERT",
        severity=severity,
        title=item.get("title") or "Mudança crítica de atividade operacional.",
        summary=item.get("description") or "Atividade operacional agregada mudou de forma relevante.",
        context=context,
        tenant_id=filters.cliente_id,
        source_refs=[{"type": "operational_activity", "timestamp": item.get("timestamp"), "new_state": item.get("new_state")}],
        event_refs=[],
        anomaly_refs=[],
        evidence_refs=item.get("evidence_refs") or [],
        reason_codes=["rule:critical_operational_activity_change", "deterministic_policy_v1"],
        quality={"status": item.get("data_quality") or "observed", "confidence": item.get("confidence")},
        active=True,
    )


def _base_record(
    *,
    alert_type: str,
    incident_key: str,
    decision: str,
    severity: str,
    title: str,
    summary: str,
    context: dict[str, Any],
    tenant_id: str | None,
    source_refs: list[Any],
    event_refs: list[str],
    anomaly_refs: list[str],
    evidence_refs: list[Any],
    reason_codes: list[str],
    quality: dict[str, Any],
    active: bool,
    visual_summary: str | None = None,
    visual_facts: list[dict[str, Any]] | None = None,
    understanding_refs: list[str] | None = None,
    uncertainties: list[str] | None = None,
) -> dict[str, Any]:
    decision_key = _decision_key(incident_key, alert_type, decision, severity, None)
    return {
        "decision_id": "ald-" + hashlib.sha256(decision_key.encode("utf-8")).hexdigest()[:24],
        "decision_key": decision_key,
        "incident_key": incident_key,
        "tenant_id": tenant_id,
        "site_id": context.get("site_id"),
        "unit_id": context.get("unit_id"),
        "area_context_id": context.get("area_id") or context.get("area_context_id"),
        "process_id": context.get("process_id"),
        "asset_id": context.get("asset_id"),
        "camera_id": context.get("camera_id"),
        "alert_type": alert_type,
        "decision": decision,
        "severity": severity,
        "priority": severity,
        "title": str(title),
        "summary": str(summary),
        "active": active,
        "source_refs": source_refs,
        "event_refs": _dedupe_strings(event_refs),
        "anomaly_refs": _dedupe_strings(anomaly_refs),
        "understanding_refs": _dedupe_strings(understanding_refs or []),
        "evidence_refs": _dedupe_jsonable(evidence_refs),
        "reason_codes": _dedupe_strings(reason_codes),
        "suppression": None,
        "quality": quality,
        "visual_summary": visual_summary,
        "visual_facts": visual_facts or [],
        "uncertainties": _dedupe_strings(uncertainties or []),
        "cause_inferred": False,
    }


def _severity_for_anomaly(anomaly: dict[str, Any], policy: dict[str, Any]) -> str:
    anomaly_type = str(anomaly.get("anomaly_type") or "")
    observed = float(anomaly.get("observed_value") or 0)
    if anomaly_type == "exceptionally_long_stoppage" and observed >= 3600:
        return "critical"
    if anomaly_type == "prolonged_operational_absence" and observed >= 1800:
        return "high"
    if anomaly_type == "recurrent_stoppages_short_window" and observed >= 7:
        return "high"
    severity = str(anomaly.get("severity") or policy.get("base_severity") or "medium").lower()
    return severity if severity in ALERT_SEVERITIES else str(policy.get("base_severity") or "medium")


def _validated_understanding_enrichment(connection: sqlite3.Connection, filters: ReadModelFilters, context: dict[str, Any], event_refs: list[str]) -> dict[str, Any]:
    records = list_validated_understandings(
        connection,
        UnderstandingFilters(
            tenant_id=filters.cliente_id,
            camera_id=context.get("camera_id"),
            asset_id=context.get("asset_id"),
        ),
    )
    valid_records: list[dict[str, Any]] = []
    rejected_seen = False
    event_ref_set = set(str(ref) for ref in event_refs or [])
    for record in records:
        status = record.get("status")
        if status == "REJECTED":
            rejected_seen = True
            continue
        if status not in {"VALID", "PARTIAL"}:
            continue
        structured = record.get("structured_result") or {}
        trigger_ref = record.get("trigger_ref")
        result_refs = set(str(ref) for ref in structured.get("event_refs") or [])
        if event_ref_set and trigger_ref not in event_ref_set and not (result_refs & event_ref_set):
            continue
        valid_records.append(record)
    reason_codes = []
    if valid_records:
        reason_codes.append("validated_understanding_enriched")
    partial = [record for record in valid_records if record.get("status") == "PARTIAL"]
    if partial:
        reason_codes.append("partial_understanding_used_as_context_only")
    return {
        "understanding_refs": [record["understanding_id"] for record in valid_records],
        "visual_summary": valid_records[0].get("summary") if valid_records else None,
        "visual_facts": [
            fact
            for record in valid_records
            for fact in (record.get("structured_result") or {}).get("visual_facts", [])
        ][:8],
        "evidence_refs": [ref for record in valid_records for ref in record.get("evidence_refs") or []],
        "uncertainties": [uncertainty for record in valid_records for uncertainty in record.get("uncertainties") or []],
        "reason_codes": reason_codes,
        "rejected_seen": rejected_seen,
    }


def _incident_active(connection: sqlite3.Connection, event_refs: list[str]) -> bool:
    if not event_refs:
        return True
    placeholders = ",".join("?" for _ in event_refs)
    rows = connection.execute(f"SELECT status FROM eventos WHERE event_uuid IN ({placeholders})", event_refs).fetchall()
    if not rows:
        return True
    return any(str(row["status"] or "open").lower() == "open" for row in rows)


def _all_events_resolved(connection: sqlite3.Connection, event_refs: list[str]) -> bool:
    if not event_refs:
        return False
    placeholders = ",".join("?" for _ in event_refs)
    rows = connection.execute(
        f"SELECT workflow_status FROM eventos WHERE event_uuid IN ({placeholders})",
        event_refs,
    ).fetchall()
    return bool(rows) and all(str(row["workflow_status"] or "new").lower() == "resolved" for row in rows)


def _latest_alert_for_incident(connection: sqlite3.Connection, incident_key: str, *, tenant_id: str | None) -> dict[str, Any] | None:
    clauses = ["incident_key = ?", "decision = 'ALERT'"]
    values: list[Any] = [incident_key]
    if tenant_id:
        clauses.append("tenant_id = ?")
        values.append(tenant_id)
    row = connection.execute(
        f"SELECT * FROM operational_alert_decisions WHERE {' AND '.join(clauses)} ORDER BY created_at DESC LIMIT 1",
        values,
    ).fetchone()
    return _row_to_decision(row) if row else None


def _material_escalation(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    ranks = {"low": 1, "medium": 2, "high": 3, "critical": 4}
    return ranks.get(current.get("severity"), 0) > ranks.get(previous.get("severity"), 0)


def _cooldown_elapsed(previous: dict[str, Any], now: datetime, cooldown_seconds: float) -> bool:
    previous_at = parse_datetime(previous.get("created_at"), now)
    return (now - previous_at).total_seconds() >= cooldown_seconds


def _incident_key(alert_type: str, context: dict[str, Any], event_refs: list[str], timestamp: Any) -> str:
    if event_refs:
        identity = {"alert_type": alert_type, "event_refs": sorted(str(ref) for ref in event_refs)}
    else:
        identity = {
            "alert_type": alert_type,
            "asset_id": context.get("asset_id"),
            "camera_id": context.get("camera_id"),
            "timestamp": str(timestamp or "")[:16],
        }
    return "incident-" + hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:24]


def _decision_key(incident_key: str, alert_type: str, decision: str, severity: str, suppression_reason: str | None) -> str:
    payload = {
        "incident_key": incident_key,
        "alert_type": alert_type,
        "decision": decision,
        "severity": severity,
        "suppression_reason": suppression_reason,
    }
    return "decision-" + hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:24]


def _dedupe_strings(values: list[Any]) -> list[str]:
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


def _row_to_decision(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    data["active"] = bool(data.get("active"))
    data["cause_inferred"] = bool(data.get("cause_inferred"))
    for target, source, default in (
        ("source_refs", "source_refs_json", []),
        ("event_refs", "event_refs_json", []),
        ("anomaly_refs", "anomaly_refs_json", []),
        ("understanding_refs", "understanding_refs_json", []),
        ("evidence_refs", "evidence_refs_json", []),
        ("reason_codes", "reason_codes_json", []),
        ("quality", "quality_json", {}),
        ("visual_facts", "visual_facts_json", []),
        ("uncertainties", "uncertainties_json", []),
    ):
        data[target] = json.loads(data.pop(source) or json.dumps(default))
    suppression = data.pop("suppression_json", None)
    data["suppression"] = json.loads(suppression) if suppression else None
    return data
