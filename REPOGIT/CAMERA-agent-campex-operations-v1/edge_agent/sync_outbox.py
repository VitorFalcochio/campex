from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from app.config import ROOT
from app.security import mask_sensitive_error
from shared.schemas import now_iso


OUTBOX_STATUSES = {"pending", "sending", "synced", "failed"}


def new_event_uuid() -> str:
    return str(uuid.uuid4())


def init_sync_outbox(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS sync_outbox (
            id TEXT PRIMARY KEY,
            event_uuid TEXT NOT NULL UNIQUE,
            edge_id TEXT,
            tenant_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            next_attempt_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            synced_at TEXT
        )
        """
    )
    connection.commit()


def enqueue_sync_event(
    connection: sqlite3.Connection,
    event_uuid: str,
    tenant_id: str,
    payload: dict[str, Any],
    edge_id: str | None = None,
) -> str:
    init_sync_outbox(connection)
    outbox_id = f"sync_{uuid.uuid4().hex[:12]}"
    connection.execute(
        """
        INSERT OR IGNORE INTO sync_outbox (
            id, event_uuid, edge_id, tenant_id, payload_json, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
        """,
        (outbox_id, event_uuid, edge_id or os.getenv("CAMPEX_EDGE_ID"), tenant_id, json.dumps(payload), now_iso(), now_iso()),
    )
    connection.commit()
    row = connection.execute("SELECT id FROM sync_outbox WHERE event_uuid = ?", (event_uuid,)).fetchone()
    return row["id"] if row else outbox_id


def refresh_sync_event(
    connection: sqlite3.Connection,
    event_uuid: str,
    payload: dict[str, Any],
    tenant_id: str,
    edge_id: str | None = None,
) -> None:
    init_sync_outbox(connection)
    encoded = json.dumps(payload)
    now = now_iso()
    row = connection.execute(
        "SELECT status FROM sync_outbox WHERE event_uuid = ?",
        (event_uuid,),
    ).fetchone()
    if row is None:
        enqueue_sync_event(connection, event_uuid, tenant_id, payload, edge_id=edge_id)
        return
    next_status = "pending" if row["status"] == "synced" else row["status"]
    connection.execute(
        """
        UPDATE sync_outbox
        SET payload_json = ?,
            edge_id = COALESCE(?, edge_id),
            tenant_id = ?,
            status = ?,
            next_attempt_at = NULL,
            updated_at = ?
        WHERE event_uuid = ?
        """,
        (encoded, edge_id or os.getenv("CAMPEX_EDGE_ID"), tenant_id, next_status, now, event_uuid),
    )
    connection.commit()


def pending_sync_count(connection: sqlite3.Connection) -> int:
    init_sync_outbox(connection)
    return int(
        connection.execute(
            "SELECT COUNT(*) AS total FROM sync_outbox WHERE status IN ('pending', 'failed')"
        ).fetchone()["total"]
    )


def _next_attempt(attempts: int) -> str:
    delay = min(3600, 2 ** min(max(attempts, 0), 8))
    return (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()


def _safe_sync_error(exc: Exception, *, cloud_url: str, edge_secret: str) -> str:
    text = str(exc)
    if cloud_url:
        text = text.replace(cloud_url, "<cloud_url>")
    if edge_secret:
        text = text.replace(edge_secret, "***")
    return str(mask_sensitive_error(text) or "Erro de sincronizacao ocultado.")[:500]


def _event_evidence_file(payload: dict[str, Any]) -> Path | None:
    midia_path = str(payload.get("midia_path") or "").strip()
    if not midia_path:
        return None
    candidate = Path(midia_path)
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    try:
        resolved = candidate.resolve()
        root = ROOT.resolve()
    except Exception:
        return None
    if root not in resolved.parents and resolved != root:
        return None
    if not resolved.exists() or not resolved.is_file():
        return None
    return resolved


def _upload_event_evidence(
    *,
    cloud_url: str,
    edge_id: str,
    edge_secret: str,
    event_uuid: str,
    evidence_path: Path,
    timeout: float,
) -> None:
    with evidence_path.open("rb") as file_obj:
        response = httpx.post(
            f"{cloud_url.rstrip('/')}/edge/events/{event_uuid}/evidence",
            content=file_obj.read(),
            headers={
                "Content-Type": "image/jpeg",
                "X-Edge-Id": edge_id,
                "X-Edge-Secret": edge_secret,
            },
            timeout=timeout,
        )
    response.raise_for_status()


def flush_sync_outbox(
    connection: sqlite3.Connection,
    cloud_url: str,
    edge_id: str,
    edge_secret: str,
    limit: int = 50,
    timeout: float = 8.0,
) -> int:
    init_sync_outbox(connection)
    rows = connection.execute(
        """
        SELECT *
        FROM sync_outbox
        WHERE status IN ('pending', 'failed')
          AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
        ORDER BY created_at
        LIMIT ?
        """,
        (now_iso(), limit),
    ).fetchall()
    synced = 0
    for row in rows:
        connection.execute(
            "UPDATE sync_outbox SET status = 'sending', updated_at = ? WHERE id = ?",
            (now_iso(), row["id"]),
        )
        connection.commit()
        try:
            payload = json.loads(row["payload_json"])
            response = httpx.post(
                f"{cloud_url.rstrip('/')}/edge/events",
                json=payload,
                headers={
                    "X-Edge-Id": edge_id,
                    "X-Edge-Secret": edge_secret,
                    "Idempotency-Key": row["event_uuid"],
                },
                timeout=timeout,
            )
            response.raise_for_status()
            evidence_path = _event_evidence_file(payload)
            if evidence_path is not None:
                _upload_event_evidence(
                    cloud_url=cloud_url,
                    edge_id=edge_id,
                    edge_secret=edge_secret,
                    event_uuid=row["event_uuid"],
                    evidence_path=evidence_path,
                    timeout=timeout,
                )
        except Exception as exc:
            attempts = int(row["attempts"] or 0) + 1
            connection.execute(
                """
                UPDATE sync_outbox
                SET status = 'failed',
                    attempts = ?,
                    last_error = ?,
                    next_attempt_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (attempts, _safe_sync_error(exc, cloud_url=cloud_url, edge_secret=edge_secret), _next_attempt(attempts), now_iso(), row["id"]),
            )
            connection.commit()
            continue
        connection.execute(
            """
            UPDATE sync_outbox
            SET status = 'synced',
                synced_at = ?,
                updated_at = ?,
                last_error = NULL
            WHERE id = ?
            """,
            (now_iso(), now_iso(), row["id"]),
        )
        connection.commit()
        synced += 1
    return synced


def run_sync_loop(db_path: str, cloud_url: str, edge_id: str, edge_secret: str, interval_seconds: float = 10.0) -> None:
    while True:
        with sqlite3.connect(db_path) as connection:
            connection.row_factory = sqlite3.Row
            flush_sync_outbox(connection, cloud_url, edge_id, edge_secret)
        time.sleep(interval_seconds)
