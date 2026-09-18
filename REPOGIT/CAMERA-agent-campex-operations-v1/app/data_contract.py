from __future__ import annotations

import json
import os
from typing import Any


CANONICAL_EVENT_VERSION = "campex_event_v1"


def canonical_event_from_row(row: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    raw_metadata = row.get("metadata_json") or row.get("metadata") or "{}"
    if isinstance(raw_metadata, dict):
        metadata = raw_metadata
    else:
        try:
            metadata = json.loads(str(raw_metadata))
        except json.JSONDecodeError:
            metadata = {}
    evidence_id = row.get("evidence_id")
    if not evidence_id and row.get("midia_path"):
        evidence_id = f"evidence:{row.get('id')}"
    return {
        "contract_version": CANONICAL_EVENT_VERSION,
        "event_id": row.get("event_uuid") or row.get("id"),
        "local_event_id": row.get("id"),
        "factory_id": row.get("cliente_id") or row.get("tenant_id"),
        "edge_id": row.get("edge_id") or os.getenv("CAMPEX_EDGE_ID"),
        "camera_id": row.get("camera_id"),
        "machine_id": row.get("machine_monitor_id") or row.get("machine_id"),
        "zone_id": row.get("area_id") or metadata.get("area_id"),
        "event_type": row.get("tipo") or row.get("event_type"),
        "started_at": row.get("inicio") or row.get("started_at"),
        "ended_at": row.get("fim") or row.get("ended_at"),
        "duration_seconds": row.get("duracao") if row.get("duracao") is not None else row.get("duration_seconds"),
        "machine_state": metadata.get("machine_state") or row.get("current_state"),
        "operator_present": row.get("operador_presente") if row.get("operador_presente") is not None else row.get("operator_present_start"),
        "confidence": row.get("confianca") if row.get("confianca") is not None else row.get("confidence"),
        "data_quality": metadata.get("data_quality", "unknown"),
        "severity": row.get("severidade") or row.get("severity"),
        "evidence_id": evidence_id,
        "rule_id": row.get("regra_id") or metadata.get("rule_id"),
        "rule_version": metadata.get("rule_version", "v1"),
        "created_at": row.get("criado_em") or row.get("created_at"),
        "updated_at": row.get("atualizado_em") or row.get("updated_at") or row.get("criado_em") or row.get("created_at"),
    }
