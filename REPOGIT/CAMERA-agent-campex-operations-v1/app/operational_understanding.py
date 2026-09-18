from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any


SUPPORTED_VIDEO_UNDERSTANDING_SCHEMA_VERSION = "video_understanding_v1"
VALIDATED_UNDERSTANDING_STATUSES = {"VALID", "PARTIAL", "REJECTED"}
VALIDATED_UNDERSTANDING_QUALITIES = {"complete", "partial", "rejected"}


@dataclass(frozen=True)
class UnderstandingFilters:
    tenant_id: str | None = None
    context_id: str | None = None
    camera_id: str | None = None
    asset_id: str | None = None
    status: str | None = None
    provider: str | None = None
    model: str | None = None
    start: str | None = None
    end: str | None = None



def _materialize_visual_occurrence(
    connection: sqlite3.Connection,
    *,
    video_context: dict[str, Any],
    understanding: dict[str, Any],
) -> str | None:
    if understanding.get("status") not in {"VALID", "PARTIAL"}:
        return None

    trigger = video_context.get("trigger") if isinstance(video_context.get("trigger"), dict) else {}
    trigger_type = str(trigger.get("type") or "")

    if not trigger_type.startswith("visual_candidate_"):
        return None

    trigger_ref = str(trigger.get("ref") or understanding.get("trigger_ref") or "")
    if not trigger_ref:
        return None

    cliente_id = understanding.get("tenant_id")
    unidade_id = understanding.get("unit_id") or understanding.get("site_id")
    camera_id = understanding.get("camera_id")

    if not cliente_id or not unidade_id or not camera_id:
        return None

    event_uuid = f"visual:{trigger_ref}"

    existing = connection.execute(
        "SELECT id FROM eventos WHERE event_uuid = ? LIMIT 1",
        (event_uuid,),
    ).fetchone()

    if existing:
        return str(existing["id"])

    evidence_rows = connection.execute(
        """
        SELECT id, path, metadata_json
        FROM evidences
        WHERE camera_id = ?
        ORDER BY created_at, id
        """,
        (camera_id,),
    ).fetchall()

    candidate_evidences: list[sqlite3.Row] = []

    for row in evidence_rows:
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            continue

        if (
            metadata.get("source") == "visual_candidate"
            and str(metadata.get("candidate_id") or "") == trigger_ref
        ):
            candidate_evidences.append(row)

    midia_path = candidate_evidences[0]["path"] if candidate_evidences else None

    from app.models import registrar_evento

    event_id = registrar_evento(
        connection,
        cliente_id=str(cliente_id),
        unidade_id=str(unidade_id),
        camera_id=str(camera_id),
        tipo="visual_occurrence",
        inicio=trigger.get("timestamp"),
        fim=None,
        duracao=None,
        operador_presente=None,
        confianca=None,
        midia_path=midia_path,
        event_uuid=event_uuid,
    )

    for row in candidate_evidences:
        connection.execute(
            """
            UPDATE evidences
            SET event_id = ?, event_uuid = ?
            WHERE id = ?
            """,
            (event_id, event_uuid, row["id"]),
        )

    connection.commit()
    return event_id


def validate_normalize_and_persist_understanding(
    connection: sqlite3.Connection,
    *,
    video_context: dict[str, Any],
    request: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    normalized, validation_errors = validate_and_normalize_understanding(video_context=video_context, request=request, result=result)
    record = _record_from_parts(video_context=video_context, request=request, normalized=normalized, validation_errors=validation_errors)
    _resolve_record_scope(connection, record)
    persisted = persist_validated_understanding(connection, record)
    materialized_event_id = _materialize_visual_occurrence(
        connection,
        video_context=video_context,
        understanding=persisted,
    )
    if materialized_event_id:
        persisted["materialized_event_id"] = materialized_event_id
    return persisted


def validate_and_normalize_understanding(
    *,
    video_context: dict[str, Any],
    request: dict[str, Any],
    result: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    validation_errors: list[str] = []
    if not isinstance(result, dict):
        result = {}
        validation_errors.append("result_not_object")
    context_id = str(result.get("context_id") or "")
    if not context_id or context_id != video_context.get("context_id") or context_id != request.get("context_id"):
        validation_errors.append("context_id_mismatch")
    metadata = result.get("model_metadata") if isinstance(result.get("model_metadata"), dict) else {}
    if metadata.get("schema_version") != SUPPORTED_VIDEO_UNDERSTANDING_SCHEMA_VERSION:
        validation_errors.append("schema_version_invalid")
    if not metadata.get("provider") or not metadata.get("model"):
        validation_errors.append("provider_model_missing")
    if result.get("cause_inferred") is not False:
        validation_errors.append("cause_inferred_not_allowed")
    required_arrays = ("visual_facts", "scene_changes", "observed_entities", "observed_actions", "uncertainties", "evidence_refs")
    for field in required_arrays:
        if not isinstance(result.get(field), list):
            validation_errors.append(f"{field}_invalid")
    allowed_refs = {str(item.get("evidence_ref")) for item in request.get("evidence") or [] if item.get("evidence_ref")}
    evidence_refs = _dedupe_strings(result.get("evidence_refs") if isinstance(result.get("evidence_refs"), list) else [])
    unknown_refs = sorted(ref for ref in evidence_refs if ref not in allowed_refs)
    if unknown_refs:
        validation_errors.append("unknown_evidence_ref")
    normalized_result = dict(result)
    normalized_result["evidence_refs"] = [ref for ref in evidence_refs if ref in allowed_refs]
    normalized_result["uncertainties"] = _dedupe_strings(result.get("uncertainties") if isinstance(result.get("uncertainties"), list) else [])
    for field in ("visual_facts", "scene_changes", "observed_entities", "observed_actions"):
        normalized_result[field] = _normalize_grounded_items(result.get(field), allowed_refs, validation_errors, field)
    normalized_result["model_metadata"] = {
        key: value
        for key, value in metadata.items()
        if key not in {"api_key", "authorization", "headers", "raw_response", "base64"}
    }
    return _strip_sensitive_recursive(normalized_result), sorted(set(validation_errors))


def persist_validated_understanding(connection: sqlite3.Connection, record: dict[str, Any]) -> dict[str, Any]:
    existing = get_validated_understanding(connection, record["understanding_id"], tenant_id=record.get("tenant_id"))
    if existing:
        return existing
    connection.execute(
        """
        INSERT INTO video_understandings (
            understanding_id, request_id, context_id, tenant_id, site_id, unit_id,
            area_context_id, process_id, asset_id, camera_id, trigger_type,
            trigger_ref, provider, model, schema_version, prompt_version, status,
            quality, summary, structured_result_json, evidence_refs_json,
            uncertainties_json, conflicts_json, quality_reasons_json,
            validation_errors_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record["understanding_id"],
            record["request_id"],
            record["context_id"],
            record.get("tenant_id"),
            record.get("site_id"),
            record.get("unit_id"),
            record.get("area_context_id"),
            record.get("process_id"),
            record.get("asset_id"),
            record.get("camera_id"),
            record.get("trigger_type"),
            record.get("trigger_ref"),
            record.get("provider"),
            record.get("model"),
            record["schema_version"],
            record.get("prompt_version"),
            record["status"],
            record["quality"],
            record.get("summary"),
            json.dumps(record.get("structured_result") or {}, ensure_ascii=False),
            json.dumps(record.get("evidence_refs") or [], ensure_ascii=False),
            json.dumps(record.get("uncertainties") or [], ensure_ascii=False),
            json.dumps(record.get("conflicts") or [], ensure_ascii=False),
            json.dumps(record.get("quality_reasons") or [], ensure_ascii=False),
            json.dumps(record.get("validation_errors") or [], ensure_ascii=False),
        ),
    )
    connection.commit()
    return get_validated_understanding(connection, record["understanding_id"], tenant_id=record.get("tenant_id")) or record


def list_validated_understandings(connection: sqlite3.Connection, filters: UnderstandingFilters | None = None) -> list[dict[str, Any]]:
    filters = filters or UnderstandingFilters()
    clauses: list[str] = []
    values: list[Any] = []
    for column, value in (
        ("tenant_id", filters.tenant_id),
        ("context_id", filters.context_id),
        ("camera_id", filters.camera_id),
        ("asset_id", filters.asset_id),
        ("status", filters.status),
        ("provider", filters.provider),
        ("model", filters.model),
    ):
        if value:
            clauses.append(f"{column} = ?")
            values.append(value)
    if filters.start:
        clauses.append("created_at >= ?")
        values.append(filters.start)
    if filters.end:
        clauses.append("created_at <= ?")
        values.append(filters.end)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = connection.execute(f"SELECT * FROM video_understandings {where} ORDER BY created_at DESC, understanding_id DESC", values).fetchall()
    return [_row_to_record(row) for row in rows]


def get_validated_understanding(connection: sqlite3.Connection, understanding_id: str, *, tenant_id: str | None = None) -> dict[str, Any] | None:
    clauses = ["understanding_id = ?"]
    values: list[Any] = [understanding_id]
    if tenant_id:
        clauses.append("tenant_id = ?")
        values.append(tenant_id)
    row = connection.execute(f"SELECT * FROM video_understandings WHERE {' AND '.join(clauses)}", values).fetchone()
    return _row_to_record(row) if row else None


def _record_from_parts(
    *,
    video_context: dict[str, Any],
    request: dict[str, Any],
    normalized: dict[str, Any],
    validation_errors: list[str],
) -> dict[str, Any]:
    metadata = normalized.get("model_metadata") if isinstance(normalized.get("model_metadata"), dict) else {}
    trigger = video_context.get("trigger") if isinstance(video_context.get("trigger"), dict) else {}
    trigger_context = trigger.get("context") if isinstance(trigger.get("context"), dict) else {}
    quality_reasons = _quality_reasons(video_context, normalized, validation_errors)
    conflicts = _potential_conflicts(video_context, normalized)
    status = _status(validation_errors, quality_reasons)
    return {
        "understanding_id": str(normalized.get("understanding_id") or ""),
        "request_id": str(request.get("request_id") or ""),
        "context_id": str(video_context.get("context_id") or request.get("context_id") or normalized.get("context_id") or ""),
        "tenant_id": video_context.get("tenant_id") or video_context.get("cliente_id"),
        "site_id": video_context.get("site_id") or trigger_context.get("site_id"),
        "unit_id": video_context.get("unit_id") or video_context.get("unidade_id") or trigger_context.get("unit_id"),
        "area_context_id": video_context.get("area_context_id") or trigger_context.get("area_id"),
        "process_id": video_context.get("process_id") or trigger_context.get("process_id"),
        "asset_id": video_context.get("asset_id") or trigger_context.get("asset_id"),
        "camera_id": video_context.get("camera_id") or trigger_context.get("camera_id"),
        "trigger_type": trigger.get("type"),
        "trigger_ref": trigger.get("ref"),
        "provider": metadata.get("provider"),
        "model": metadata.get("model"),
        "schema_version": metadata.get("schema_version") or request.get("schema_version") or SUPPORTED_VIDEO_UNDERSTANDING_SCHEMA_VERSION,
        "prompt_version": metadata.get("prompt_version"),
        "status": status,
        "quality": "rejected" if status == "REJECTED" else "partial" if status == "PARTIAL" else "complete",
        "summary": _clean_string(normalized.get("summary")),
        "structured_result": normalized,
        "evidence_refs": normalized.get("evidence_refs") or [],
        "uncertainties": normalized.get("uncertainties") or [],
        "conflicts": conflicts,
        "quality_reasons": quality_reasons,
        "validation_errors": validation_errors,
    }


def _resolve_record_scope(connection: sqlite3.Connection, record: dict[str, Any]) -> None:
    camera_id = record.get("camera_id")
    if not camera_id:
        return
    row = connection.execute(
        """
        SELECT cliente_id, unidade_id, site_id, area_context_id, process_id, asset_id
        FROM cameras
        WHERE id = ?
        """,
        (camera_id,),
    ).fetchone()
    if not row:
        return
    record["tenant_id"] = record.get("tenant_id") or row["cliente_id"]
    record["unit_id"] = record.get("unit_id") or row["unidade_id"]
    record["site_id"] = record.get("site_id") or row["site_id"] or row["unidade_id"]
    record["area_context_id"] = record.get("area_context_id") or row["area_context_id"]
    record["process_id"] = record.get("process_id") or row["process_id"]
    record["asset_id"] = record.get("asset_id") or row["asset_id"]


def _status(validation_errors: list[str], quality_reasons: list[str]) -> str:
    if validation_errors:
        return "REJECTED"
    if quality_reasons:
        return "PARTIAL"
    return "VALID"


def _quality_reasons(video_context: dict[str, Any], normalized: dict[str, Any], validation_errors: list[str]) -> list[str]:
    reasons: list[str] = []
    if validation_errors:
        reasons.append("validation_errors")
    data_quality = video_context.get("data_quality") if isinstance(video_context.get("data_quality"), dict) else {}
    if str(data_quality.get("status") or "").lower() in {"partial", "unknown", "insufficient"}:
        reasons.append("context_partial")
    phases = video_context.get("phases") if isinstance(video_context.get("phases"), dict) else {}
    for phase in ("before", "transition", "during", "after"):
        if not _phase_has_evidence(phases.get(phase)):
            reasons.append(f"missing_{phase}_evidence")
    uncertainties = " ".join(str(item).lower() for item in normalized.get("uncertainties") or [])
    if "timestamp" in uncertainties and any(term in uncertainties for term in ("mismatch", "diverg", "differ", "inconsist", "ordem", "order")):
        reasons.append("visual_timestamp_mismatch_reported")
    if "offline" in uncertainties:
        reasons.append("camera_offline_reported")
    return sorted(set(reasons))


def _phase_has_evidence(phase_items: Any) -> bool:
    if not isinstance(phase_items, list):
        return False
    for item in phase_items:
        if isinstance(item, dict) and item.get("evidence_refs"):
            return True
    return False


def _potential_conflicts(video_context: dict[str, Any], normalized: dict[str, Any]) -> list[dict[str, Any]]:
    canonical_person_present = any(
        str(obs.get("type")) == "person_presence" and str(obs.get("new_state") or "").upper() in {"PRESENT", "TRUE", "1"}
        for obs in video_context.get("observations") or []
        if isinstance(obs, dict)
    )
    if not canonical_person_present:
        return []
    visual_text = " ".join(
        str(item.get("description") or "").lower()
        for field in ("visual_facts", "observed_entities", "observed_actions")
        for item in normalized.get(field) or []
        if isinstance(item, dict)
    )
    if any(fragment in visual_text for fragment in ("no person visible", "nenhuma pessoa", "sem pessoa", "person not visible")):
        refs = _dedupe_strings(
            ref
            for field in ("visual_facts", "observed_entities", "observed_actions")
            for item in normalized.get(field) or []
            if isinstance(item, dict)
            for ref in item.get("evidence_refs") or []
        )
        return [
            {
                "type": "potential_conflict",
                "canonical_fact": "person_presence=PRESENT",
                "visual_understanding": "person_not_visible_or_absent",
                "reason": "canonical_and_visual_sources_can_differ_due_to_occlusion_or_timing",
                "evidence_refs": refs,
            }
        ]
    return []


def _normalize_grounded_items(items: Any, allowed_refs: set[str], validation_errors: list[str], field: str) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    if not isinstance(items, list):
        return normalized
    for item in items:
        if not isinstance(item, dict):
            validation_errors.append(f"{field}_item_invalid")
            continue
        refs = _dedupe_strings(item.get("evidence_refs") if isinstance(item.get("evidence_refs"), list) else [])
        if not refs:
            validation_errors.append(f"{field}_missing_evidence_refs")
        if not set(refs).issubset(allowed_refs):
            validation_errors.append("unknown_evidence_ref")
        cleaned = {key: value for key, value in item.items() if key != "evidence_refs"}
        cleaned["evidence_refs"] = [ref for ref in refs if ref in allowed_refs]
        normalized.append(_strip_sensitive_recursive(cleaned))
    return normalized


def _dedupe_strings(values: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values or []:
        text = _clean_string(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _clean_string(value: Any) -> str:
    return str(value or "").strip()


def _strip_sensitive_recursive(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(secret in lowered for secret in ("api_key", "authorization", "password", "token", "base64", "image_url", "raw_request", "raw_response")):
                continue
            cleaned[key] = _strip_sensitive_recursive(item)
        return cleaned
    if isinstance(value, list):
        return [_strip_sensitive_recursive(item) for item in value]
    if isinstance(value, str) and ("data:image/" in value or "sk-" in value):
        return "[redacted]"
    return value


def _row_to_record(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    data["structured_result"] = json.loads(data.pop("structured_result_json") or "{}")
    data["evidence_refs"] = json.loads(data.pop("evidence_refs_json") or "[]")
    data["uncertainties"] = json.loads(data.pop("uncertainties_json") or "[]")
    data["conflicts"] = json.loads(data.pop("conflicts_json") or "[]")
    data["quality_reasons"] = json.loads(data.pop("quality_reasons_json") or "[]")
    data["validation_errors"] = json.loads(data.pop("validation_errors_json", None) or "[]")
    return data
