from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.event_workflow import observed_context
from app.models import evento_public_dict, row_to_dict
from app.operational_read_model import ReadModelFilters, parse_datetime, to_iso, _coverage


DEFAULT_BEFORE_SECONDS = 300
DEFAULT_AFTER_SECONDS = 300
SENSITIVE_FRAGMENTS = ("password", "senha", "secret", "token", "rtsp", "credential", "api_key")


@dataclass(frozen=True)
class ContextWindow:
    before_seconds: int = DEFAULT_BEFORE_SECONDS
    after_seconds: int = DEFAULT_AFTER_SECONDS


class ContextPackNotFoundError(LookupError):
    pass


class ContextPackAccessError(PermissionError):
    pass


def build_context_pack(
    connection: sqlite3.Connection,
    event_uuid: str,
    *,
    tenant_id: str | None,
    window: ContextWindow | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    event = _get_event_by_uuid(connection, event_uuid)
    if event is None:
        raise ContextPackNotFoundError(event_uuid)
    if tenant_id and event.get("cliente_id") != tenant_id:
        raise ContextPackAccessError(event_uuid)
    window = window or ContextWindow()
    now = now or datetime.now(timezone.utc)
    opened_at = parse_datetime(event.get("inicio"), now)
    closed_at = parse_datetime(event.get("fim"), now) if event.get("fim") else None
    during_end = closed_at or now
    before_start = opened_at - timedelta(seconds=window.before_seconds)
    after_end = during_end + timedelta(seconds=window.after_seconds) if closed_at else during_end
    context_filters = ReadModelFilters(
        cliente_id=event.get("cliente_id"),
        site_id=event.get("site_id") or event.get("unidade_id"),
        area_context_id=event.get("area_context_id"),
        process_id=event.get("process_id"),
        asset_id=event.get("asset_id") or event.get("machine_monitor_id"),
        camera_id=event.get("camera_id"),
        start=before_start,
        end=after_end,
    )
    timeline = {
        "before": _samples(connection, event, before_start, opened_at),
        "during": _samples(connection, event, opened_at, during_end),
        "after": _samples(connection, event, during_end, after_end) if closed_at else [],
        "window": {
            "before_seconds": window.before_seconds,
            "after_seconds": window.after_seconds,
            "start": to_iso(before_start),
            "event_start": to_iso(opened_at),
            "event_end": to_iso(during_end),
            "end": to_iso(after_end),
        },
    }
    pack = {
        "context_pack_version": "context_engine_v1",
        "event": _event_summary(event),
        "operational_context": _operational_context(connection, event),
        "timeline": timeline,
        "observations": _observations_from_timeline(timeline),
        "history": _similar_history(connection, event),
        "human_confirmed": _human_confirmed(event),
        "operational_memory": _operational_memory(event),
        "evidence": _evidence(connection, event),
        "data_quality": _data_quality(connection, context_filters, timeline),
        "traceability": _traceability(event, timeline),
    }
    return _sanitize(pack)


def _get_event_by_uuid(connection: sqlite3.Connection, event_uuid: str) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT *
        FROM eventos
        WHERE event_uuid = ? OR id = ?
        LIMIT 1
        """,
        (event_uuid, event_uuid),
    ).fetchone()
    return evento_public_dict(row) if row else None


def _event_summary(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": event.get("id"),
        "event_uuid": event.get("event_uuid"),
        "event_type": event.get("tipo"),
        "event_family": event.get("event_family") or "unknown",
        "event_subtype": event.get("event_subtype"),
        "status": event.get("status"),
        "workflow_status": event.get("workflow_status") or "new",
        "opened_at": event.get("inicio"),
        "closed_at": event.get("fim"),
        "duration_seconds": event.get("duracao"),
        "confidence": event.get("confianca"),
        "severity": event.get("severidade"),
    }


def _operational_context(connection: sqlite3.Connection, event: dict[str, Any]) -> dict[str, Any]:
    return {
        "cliente": _lookup(connection, "clientes", event.get("cliente_id")),
        "unidade": _lookup(connection, "unidades", event.get("unidade_id")),
        "area": _lookup(connection, "operational_areas", event.get("area_context_id")),
        "process": _lookup(connection, "operational_processes", event.get("process_id")),
        "asset": _lookup(connection, "operational_assets", event.get("asset_id")),
        "camera": _lookup(connection, "cameras", event.get("camera_id"), allowed=("id", "nome", "status", "ativa", "unidade_id", "cliente_id", "area_context_id", "process_id", "asset_id")),
        "monitor": _lookup(connection, "machine_monitors", event.get("machine_monitor_id"), allowed=("id", "nome", "camera_id", "ativo", "current_state", "confidence", "calibration_status", "calibration_result")),
        "rule": _lookup(connection, "regras", event.get("regra_id"), allowed=("id", "nome", "tipo_evento", "severidade", "ativo")),
        "area_id": event.get("area_id"),
    }


def _lookup(connection: sqlite3.Connection, table: str, row_id: str | None, allowed: tuple[str, ...] | None = None) -> dict[str, Any] | None:
    if not row_id:
        return None
    try:
        row = connection.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    data = row_to_dict(row)
    if allowed:
        data = {key: data.get(key) for key in allowed if key in data}
    return data


def _samples(connection: sqlite3.Connection, event: dict[str, Any], start: datetime, end: datetime) -> list[dict[str, Any]]:
    if end <= start:
        return []
    clauses = ["sample_at >= ?", "sample_at <= ?", "tenant_id = ?"]
    params: list[Any] = [to_iso(start), to_iso(end), event.get("cliente_id")]
    for column, value in {
        "camera_id": event.get("camera_id"),
        "asset_id": event.get("asset_id") or event.get("machine_monitor_id"),
        "machine_id": event.get("machine_monitor_id"),
    }.items():
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)
    rows = connection.execute(
        f"""
        SELECT *
        FROM operational_samples
        WHERE {' AND '.join(clauses)}
        ORDER BY sample_at ASC, id ASC
        LIMIT 500
        """,
        params,
    ).fetchall()
    return [_sample_context(row_to_dict(row)) for row in rows]


def _sample_context(sample: dict[str, Any]) -> dict[str, Any]:
    metadata = _json(sample.pop("metadata_json", None))
    observations = metadata.get("canonical_observations") if isinstance(metadata.get("canonical_observations"), list) else []
    return {
        "sample_id": sample.get("id"),
        "sample_uuid": sample.get("sample_uuid"),
        "timestamp": sample.get("sample_at"),
        "source": "operational_samples",
        "camera_id": sample.get("camera_id"),
        "asset_id": sample.get("asset_id") or sample.get("machine_id"),
        "machine_id": sample.get("machine_id"),
        "machine_activity": {
            "state": sample.get("machine_state") or "UNKNOWN",
            "activity_score": sample.get("activity_score"),
            "confidence": sample.get("confidence"),
        },
        "person_presence": {
            "value": "UNKNOWN" if sample.get("operator_present") is None else "PRESENT" if int(sample.get("operator_present") or 0) else "ABSENT",
            "operator_present": None if sample.get("operator_present") is None else bool(sample.get("operator_present")),
            "people_count": metadata.get("people_count"),
        },
        "data_quality": {
            "camera_online": None if sample.get("camera_online") is None else bool(sample.get("camera_online")),
            "capture_fps": sample.get("capture_fps"),
            "inference_fps": sample.get("inference_fps"),
            "frames_analyzed": sample.get("frames_analyzed"),
            "analysis_status": metadata.get("analysis_status"),
            "signal_quality": metadata.get("signal_quality"),
        },
        "observations": observations,
    }


def _observations_from_timeline(timeline: dict[str, Any]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for section in ("before", "during", "after"):
        for sample in timeline[section]:
            machine = sample["machine_activity"]
            grouped.setdefault("machine_activity", []).append({"section": section, "sample_uuid": sample.get("sample_uuid"), "timestamp": sample.get("timestamp"), **machine})
            presence = sample["person_presence"]
            grouped.setdefault("person_presence", []).append({"section": section, "sample_uuid": sample.get("sample_uuid"), "timestamp": sample.get("timestamp"), **presence})
            for observation in sample.get("observations") or []:
                kind = observation.get("observation_type") or "unknown"
                grouped.setdefault(kind, []).append({"section": section, "sample_uuid": sample.get("sample_uuid"), "timestamp": sample.get("timestamp"), **observation})
    return grouped


def _similar_history(connection: sqlite3.Connection, event: dict[str, Any], limit: int = 5) -> dict[str, Any]:
    scopes = [
        ("same_asset", "asset_id", event.get("asset_id") or event.get("machine_monitor_id")),
        ("same_process", "process_id", event.get("process_id")),
        ("same_area", "area_context_id", event.get("area_context_id")),
    ]
    selected: list[dict[str, Any]] = []
    seen: set[str] = {str(event.get("event_uuid") or event.get("id"))}
    for scope, column, value in scopes:
        if not value:
            continue
        rows = connection.execute(
            f"""
            SELECT *
            FROM eventos
            WHERE cliente_id = ?
              AND tipo = ?
              AND {column} = ?
              AND COALESCE(event_uuid, id) != ?
            ORDER BY inicio DESC, criado_em DESC
            LIMIT ?
            """,
            (event.get("cliente_id"), event.get("tipo"), value, event.get("event_uuid") or event.get("id"), limit),
        ).fetchall()
        for row in rows:
            item = evento_public_dict(row)
            uuid = str(item.get("event_uuid") or item.get("id"))
            if uuid in seen:
                continue
            seen.add(uuid)
            selected.append(_history_item(item, scope))
            if len(selected) >= limit:
                break
        if len(selected) >= limit:
            break
    return {
        "strategy": ["same_asset_same_event_type", "same_process_same_event_type", "same_area_same_event_type"],
        "total_returned": len(selected),
        "events": selected,
    }


def _history_item(event: dict[str, Any], scope: str) -> dict[str, Any]:
    return {
        "scope": scope,
        "event_uuid": event.get("event_uuid"),
        "event_type": event.get("tipo"),
        "started_at": event.get("inicio"),
        "closed_at": event.get("fim"),
        "duration_seconds": event.get("duracao"),
        "status": event.get("status"),
        "confirmed_cause": event.get("confirmed_cause") or event.get("cause_category"),
        "confirmed_by": event.get("confirmed_by") or event.get("classified_by"),
        "confirmed_at": event.get("confirmed_at") or event.get("classified_at"),
        "action_taken": event.get("action_taken"),
        "action_at": event.get("action_at"),
        "recommendation_id": event.get("recommendation_id"),
        "recommendation_accepted": None if event.get("recommendation_accepted") is None else bool(event.get("recommendation_accepted")),
        "outcome_status": event.get("outcome_status"),
        "outcome_notes": event.get("outcome_notes"),
        "resolution_time_seconds": event.get("resolution_time_seconds"),
        "human_notes": event.get("human_notes") or event.get("observacao") or event.get("cause_notes"),
    }


def _human_confirmed(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "confirmed_cause": event.get("confirmed_cause") or event.get("cause_category"),
        "action_taken": event.get("action_taken"),
        "human_notes": event.get("human_notes") or event.get("observacao") or event.get("cause_notes"),
        "acknowledged_at": event.get("acknowledged_at"),
        "acknowledged_by": event.get("acknowledged_by"),
        "resolved_at": event.get("resolved_at"),
        "resolved_by": event.get("resolved_by"),
        "cause_is_human_confirmed_only": True,
    }


def _operational_memory(event: dict[str, Any]) -> dict[str, Any]:
    confirmed_cause = event.get("confirmed_cause") or event.get("cause_category")
    return {
        "event_uuid": event.get("event_uuid"),
        "human_confirmation": {
            "confirmed_cause": confirmed_cause,
            "confirmed_by": event.get("confirmed_by") or event.get("classified_by"),
            "confirmed_at": event.get("confirmed_at") or event.get("classified_at"),
        },
        "action": {
            "action_taken": event.get("action_taken"),
            "action_at": event.get("action_at"),
            "recommendation_id": event.get("recommendation_id"),
            "recommendation_accepted": None if event.get("recommendation_accepted") is None else bool(event.get("recommendation_accepted")),
        },
        "outcome": {
            "resolved": _resolved_bool(event.get("outcome_status")),
            "outcome_status": event.get("outcome_status"),
            "resolved_at": event.get("resolved_at"),
            "resolution_time_seconds": event.get("resolution_time_seconds"),
            "outcome_notes": event.get("outcome_notes"),
        },
        "human_notes": event.get("human_notes") or event.get("observacao") or event.get("cause_notes"),
        "cause_is_human_confirmed_only": True,
    }


def _resolved_bool(outcome_status: Any) -> bool | None:
    if outcome_status == "resolved":
        return True
    if outcome_status == "not_resolved":
        return False
    return None


def _evidence(connection: sqlite3.Connection, event: dict[str, Any]) -> dict[str, Any]:
    rows = connection.execute(
        """
        SELECT *
        FROM evidences
        WHERE tenant_id = ? AND (event_uuid = ? OR event_id = ?)
        ORDER BY created_at ASC, id ASC
        """,
        (event.get("cliente_id"), event.get("event_uuid"), event.get("id")),
    ).fetchall()
    items = []
    for row in rows:
        data = row_to_dict(row)
        items.append(
            {
                "evidence_id": data.get("id"),
                "event_uuid": data.get("event_uuid"),
                "path": data.get("path"),
                "media_type": data.get("media_type"),
                "size_bytes": data.get("size_bytes"),
                "metadata": _json(data.get("metadata_json")),
            }
        )
    if event.get("midia_path") and not items:
        items.append({"evidence_id": None, "event_uuid": event.get("event_uuid"), "path": event.get("midia_path"), "media_type": "image", "size_bytes": None, "metadata": {"source": "event_midia_path"}})
    return {"available": bool(items), "items": items}


def _data_quality(connection: sqlite3.Connection, filters: ReadModelFilters, timeline: dict[str, Any]) -> dict[str, Any]:
    coverage = _coverage(connection, filters)
    samples = [sample for section in ("before", "during", "after") for sample in timeline[section]]
    unknown_samples = [sample for sample in samples if sample["machine_activity"]["state"] in {None, "UNKNOWN"} or sample["person_presence"]["value"] == "UNKNOWN"]
    sensor_unavailable = [
        sample
        for sample in samples
        if sample["data_quality"].get("camera_online") is False or not sample["data_quality"].get("inference_fps")
    ]
    limitations = []
    if unknown_samples:
        limitations.append("UNKNOWN presente em amostras do contexto.")
    if sensor_unavailable:
        limitations.append("Sensor/câmera/inferência indisponível em parte da janela.")
    if any(sample["data_quality"].get("signal_quality") in {"INSUFFICIENT_VISUAL_SIGNAL", "CALIBRATION_REQUIRED", "INVALID_ROI"} for sample in samples):
        limitations.append("Qualidade/calibração visual limita conclusões.")
    return {
        "coverage": coverage,
        "unknown_sample_count": len(unknown_samples),
        "sensor_unavailable_sample_count": len(sensor_unavailable),
        "limitations": limitations,
        "causal_conclusion_allowed": False,
    }


def _traceability(event: dict[str, Any], timeline: dict[str, Any]) -> dict[str, Any]:
    sample_refs = [
        {"sample_id": sample.get("sample_id"), "sample_uuid": sample.get("sample_uuid"), "timestamp": sample.get("timestamp"), "section": section}
        for section in ("before", "during", "after")
        for sample in timeline[section]
    ]
    return {
        "event_uuid": event.get("event_uuid"),
        "event_id": event.get("id"),
        "sample_refs": sample_refs,
        "sources": ["eventos", "operational_samples", "evidences", "workflow_fields"],
    }


def _json(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        data = json.loads(str(raw))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            if any(fragment in str(key).lower() for fragment in SENSITIVE_FRAGMENTS):
                clean[key] = "[redacted]"
            else:
                clean[key] = _sanitize(item)
        return clean
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, str) and "rtsp://" in value.lower():
        return "[redacted]"
    return value
