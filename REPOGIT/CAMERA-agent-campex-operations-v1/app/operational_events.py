from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from app.models import (
    atualizar_evento,
    atualizar_outbox_evento,
    obter_camera,
    obter_evento,
    registrar_evento,
)
from shared.schemas import now_iso


COMPAT_CLIENT_ID = "cli_operational_compat"
COMPAT_UNIT_ID = "uni_operational_compat"


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _ensure_compat_context(connection: sqlite3.Connection, camera_id: str) -> tuple[str, str, str]:
    connection.execute(
        """
        INSERT OR IGNORE INTO clientes (id, nome, status)
        VALUES (?, ?, 'ativo')
        """,
        (COMPAT_CLIENT_ID, "Operação local"),
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO unidades (id, cliente_id, nome)
        VALUES (?, ?, ?)
        """,
        (COMPAT_UNIT_ID, COMPAT_CLIENT_ID, "Unidade local"),
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO cameras (id, cliente_id, unidade_id, nome, status, ativa)
        VALUES (?, ?, ?, ?, 'nao_conectada', 1)
        """,
        (camera_id, COMPAT_CLIENT_ID, COMPAT_UNIT_ID, camera_id),
    )
    return COMPAT_CLIENT_ID, COMPAT_UNIT_ID, camera_id


def resolve_event_context(connection: sqlite3.Connection, camera_id: str | None, session_id: str) -> tuple[str, str, str, str | None]:
    persistent_camera_id = camera_id if camera_id and not camera_id.startswith("live_") else None
    if persistent_camera_id:
        camera = obter_camera(connection, persistent_camera_id)
        if camera:
            return str(camera.get("cliente_id") or COMPAT_CLIENT_ID), str(camera["unidade_id"]), persistent_camera_id, None
        return (*_ensure_compat_context(connection, persistent_camera_id), None)
    compat_camera_id = f"compat_{session_id}"
    client_id, unit_id, canonical_camera_id = _ensure_compat_context(connection, compat_camera_id)
    return client_id, unit_id, canonical_camera_id, camera_id


def _metadata(
    *,
    session_id: str,
    machine_name: str | None,
    event_type: str,
    previous_state: str | None,
    new_state: str,
    activity_score: float | None,
    people_count: int,
    snapshot_path: str | None,
    source_camera_id: str | None = None,
) -> dict[str, Any]:
    return {
        "domain": "operations_history_compat",
        "session_id": session_id,
        "machine_name": machine_name,
        "event_type": event_type,
        "previous_state": previous_state,
        "new_state": new_state,
        "activity_score": activity_score,
        "people_count": int(people_count or 0),
        "snapshot_path": snapshot_path,
        "source_camera_id": source_camera_id,
    }


def _write_metadata(connection: sqlite3.Connection, event_id: str, metadata: dict[str, Any]) -> None:
    connection.execute(
        "UPDATE eventos SET metadata_json = ?, atualizado_em = CURRENT_TIMESTAMP WHERE id = ?",
        (json.dumps(metadata, ensure_ascii=False), event_id),
    )
    connection.commit()
    atualizar_outbox_evento(connection, event_id)


def open_event(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    camera_id: str | None,
    machine_name: str | None,
    event_type: str,
    previous_state: str | None,
    new_state: str,
    started_at: str,
    confidence: float | None = None,
    activity_score: float | None = None,
    people_count: int = 0,
    snapshot_path: str | None = None,
    severity: str = "medium",
) -> str:
    if event_type == "camera_status":
        return ""
    existing = _find_open_event(connection, session_id, event_type, new_state)
    if existing:
        return str(existing["id"])
    client_id, unit_id, canonical_camera_id, source_camera_id = resolve_event_context(connection, camera_id, session_id)
    event_id = registrar_evento(
        connection,
        client_id,
        unit_id,
        canonical_camera_id,
        event_type,
        inicio=started_at,
        operador_presente=None,
        confianca=confidence,
        midia_path=snapshot_path,
    )
    metadata = _metadata(
        session_id=session_id,
        machine_name=machine_name,
        event_type=event_type,
        previous_state=previous_state,
        new_state=new_state,
        activity_score=activity_score,
        people_count=people_count,
        snapshot_path=snapshot_path,
        source_camera_id=source_camera_id,
    )
    connection.execute(
        """
        UPDATE eventos
        SET status = 'open',
            severidade = ?,
            quantidade_inicial = ?,
            quantidade_atual = ?,
            metadata_json = ?,
            atualizado_em = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (severity, int(people_count or 0), int(people_count or 0), json.dumps(metadata, ensure_ascii=False), event_id),
    )
    connection.commit()
    atualizar_outbox_evento(connection, event_id)
    return event_id


def update_event(connection: sqlite3.Connection, event_id: str, **metadata_updates: Any) -> dict[str, Any] | None:
    event = obter_evento(connection, event_id)
    if event is None:
        return None
    metadata = dict(event.get("metadata") or {})
    metadata.update({key: value for key, value in metadata_updates.items() if value is not None})
    _write_metadata(connection, event_id, metadata)
    return obter_evento(connection, event_id)


def close_event(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    event_type: str,
    ended_at: str,
) -> dict[str, Any] | None:
    row = _find_open_event(connection, session_id, event_type)
    if row is None:
        return None
    started = parse_iso(row["inicio"])
    ended = parse_iso(ended_at)
    duration = max(0.0, (ended - started).total_seconds()) if started and ended else None
    atualizar_evento(connection, row["id"], fim=ended_at, duracao=duration)
    connection.execute(
        "UPDATE eventos SET status = 'closed', atualizado_em = CURRENT_TIMESTAMP WHERE id = ?",
        (row["id"],),
    )
    connection.commit()
    atualizar_outbox_evento(connection, row["id"])
    event = obter_evento(connection, row["id"])
    if event is None:
        return None
    return to_legacy_operational_event(event)


def _find_open_event(
    connection: sqlite3.Connection,
    session_id: str,
    event_type: str,
    new_state: str | None = None,
) -> sqlite3.Row | None:
    clauses = ["status = 'open'", "tipo = ?", "json_extract(metadata_json, '$.session_id') = ?"]
    values: list[Any] = [event_type, session_id]
    if new_state is not None:
        clauses.append("json_extract(metadata_json, '$.new_state') = ?")
        values.append(new_state)
    return connection.execute(
        f"""
        SELECT *
        FROM eventos
        WHERE {' AND '.join(clauses)}
        ORDER BY inicio DESC, criado_em DESC, rowid DESC
        LIMIT 1
        """,
        values,
    ).fetchone()


def to_legacy_operational_event(event: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(event.get("metadata") or {})
    camera_id = metadata.get("source_camera_id") if metadata.get("source_camera_id") else event.get("camera_id")
    if str(camera_id or "").startswith("compat_live_"):
        camera_id = None
    return {
        "id": event["id"],
        "event_uuid": event.get("event_uuid"),
        "session_id": metadata.get("session_id") or event.get("camera_id"),
        "camera_id": camera_id,
        "machine_id": event.get("machine_monitor_id"),
        "machine_name": metadata.get("machine_name"),
        "event_type": metadata.get("event_type") or event.get("tipo"),
        "previous_state": metadata.get("previous_state"),
        "new_state": metadata.get("new_state") or event.get("status"),
        "started_at": event.get("inicio"),
        "ended_at": event.get("fim"),
        "duration_seconds": event.get("duracao"),
        "confidence": event.get("confianca"),
        "activity_score": metadata.get("activity_score") or event.get("motion_level"),
        "people_count": metadata.get("people_count") or event.get("quantidade_atual") or event.get("quantidade_inicial") or 0,
        "snapshot_path": metadata.get("snapshot_path") or event.get("midia_path"),
        "tenant_id": event.get("cliente_id"),
        "unit_id": event.get("unidade_id"),
        "status": event.get("status"),
        "severity": event.get("severidade"),
        "metadata": metadata,
        "created_at": event.get("criado_em"),
    }


def list_events(
    connection: sqlite3.Connection,
    *,
    start: str | None = None,
    end: str | None = None,
    camera_id: str | None = None,
    machine_name: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    values: list[Any] = []
    if start:
        clauses.append("COALESCE(fim, ?) >= ?")
        values.extend([now_iso(), start])
    if end:
        clauses.append("inicio <= ?")
        values.append(end)
    if camera_id:
        clauses.append("(camera_id = ? OR json_extract(metadata_json, '$.source_camera_id') = ?)")
        values.extend([camera_id, camera_id])
    if machine_name:
        clauses.append("json_extract(metadata_json, '$.machine_name') = ?")
        values.append(machine_name)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = connection.execute(
        f"""
        SELECT *
        FROM eventos
        {where}
        ORDER BY inicio DESC, criado_em DESC, rowid DESC
        LIMIT ? OFFSET ?
        """,
        [*values, max(1, min(limit, 200)), max(0, offset)],
    ).fetchall()
    from app.models import evento_public_dict

    return [to_legacy_operational_event(evento_public_dict(row)) for row in rows]
