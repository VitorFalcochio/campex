from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from shared.schemas import now_iso


def init_queue(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS event_queue (
            id TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            created_at TEXT NOT NULL,
            sent_at TEXT
        )
        """
    )
    connection.commit()


def enqueue_event(
    connection: sqlite3.Connection,
    payload: dict[str, Any],
    method: str = "POST",
    path: str = "/eventos",
) -> str:
    init_queue(connection)
    queue_id = f"queue_{uuid.uuid4().hex[:12]}"
    envelope = {
        "method": method,
        "path": path,
        "payload": payload,
    }
    connection.execute(
        """
        INSERT INTO event_queue (id, payload_json, created_at)
        VALUES (?, ?, ?)
        """,
        (queue_id, json.dumps(envelope), now_iso()),
    )
    connection.commit()
    return queue_id


def send_payload(
    api_url: str,
    payload: dict[str, Any],
    timeout: float = 5.0,
    method: str = "POST",
    path: str = "/eventos",
) -> None:
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        f"{api_url.rstrip('/')}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    with urlopen(request, timeout=timeout) as response:
        if response.status >= 400:
            raise URLError(f"HTTP {response.status}")


def flush_queue(connection: sqlite3.Connection, api_url: str, limit: int = 50) -> int:
    init_queue(connection)
    rows = connection.execute(
        """
        SELECT id, payload_json
        FROM event_queue
        WHERE status = 'pending'
        ORDER BY created_at
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    sent = 0
    for row in rows:
        envelope = json.loads(row["payload_json"])
        if "payload" in envelope:
            payload = envelope["payload"]
            method = envelope.get("method", "POST")
            path = envelope.get("path", "/eventos")
        else:
            payload = envelope
            method = "POST"
            path = "/eventos"
        try:
            send_payload(api_url, payload, method=method, path=path)
        except Exception as exc:
            connection.execute(
                """
                UPDATE event_queue
                SET attempts = attempts + 1, last_error = ?
                WHERE id = ?
                """,
                (str(exc), row["id"]),
            )
            connection.commit()
            continue
        connection.execute(
            "UPDATE event_queue SET status = 'sent', sent_at = ? WHERE id = ?",
            (now_iso(), row["id"]),
        )
        connection.commit()
        sent += 1
    return sent


def pending_count(connection: sqlite3.Connection) -> int:
    init_queue(connection)
    return int(connection.execute("SELECT COUNT(*) AS total FROM event_queue WHERE status = 'pending'").fetchone()["total"])


def run_sender_loop(db_path: Path, api_url: str, interval_seconds: float = 10.0) -> None:
    while True:
        with sqlite3.connect(db_path) as connection:
            connection.row_factory = sqlite3.Row
            flush_queue(connection, api_url)
        time.sleep(interval_seconds)
