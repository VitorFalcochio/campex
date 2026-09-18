from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def add_tenant(connection: sqlite3.Connection, name: str, document: str | None = None) -> str:
    tenant_id = new_id("tenant")
    connection.execute(
        "INSERT INTO tenants (tenant_id, name, document) VALUES (?, ?, ?)",
        (tenant_id, name, document),
    )
    connection.commit()
    return tenant_id


def add_site(connection: sqlite3.Connection, tenant_id: str, name: str, location: str | None = None) -> str:
    site_id = new_id("site")
    connection.execute(
        "INSERT INTO sites (site_id, tenant_id, name, location) VALUES (?, ?, ?, ?)",
        (site_id, tenant_id, name, location),
    )
    connection.commit()
    return site_id


def add_camera(
    connection: sqlite3.Connection,
    tenant_id: str,
    site_id: str,
    name: str,
    source_type: str = "future_live",
    source_ref: str | None = None,
    notes: str | None = None,
) -> str:
    camera_id = new_id("camera")
    connection.execute(
        """
        INSERT INTO cameras (
            camera_id, tenant_id, site_id, name, source_type, source_ref, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (camera_id, tenant_id, site_id, name, source_type, source_ref, notes),
    )
    connection.commit()
    return camera_id


def add_rule(
    connection: sqlite3.Connection,
    tenant_id: str,
    site_id: str,
    name: str,
    rule_type: str,
    camera_id: str | None = None,
    parameters: dict[str, Any] | None = None,
) -> str:
    rule_id = new_id("rule")
    connection.execute(
        """
        INSERT INTO rules (
            rule_id, tenant_id, site_id, camera_id, name, rule_type, parameters_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (rule_id, tenant_id, site_id, camera_id, name, rule_type, json.dumps(parameters or {})),
    )
    connection.commit()
    return rule_id


def add_event(
    connection: sqlite3.Connection,
    tenant_id: str,
    site_id: str,
    camera_id: str,
    rule_id: str,
    event_type: str,
    started_at: str | None = None,
    ended_at: str | None = None,
    duration_seconds: float | None = None,
    severity: str = "info",
    payload: dict[str, Any] | None = None,
) -> str:
    event_id = new_id("event")
    connection.execute(
        """
        INSERT INTO events (
            event_id, tenant_id, site_id, camera_id, rule_id, event_type,
            started_at, ended_at, duration_seconds, severity, payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            tenant_id,
            site_id,
            camera_id,
            rule_id,
            event_type,
            started_at or now_iso(),
            ended_at,
            duration_seconds,
            severity,
            json.dumps(payload or {}),
        ),
    )
    connection.commit()
    return event_id


def add_alert(
    connection: sqlite3.Connection,
    tenant_id: str,
    site_id: str,
    camera_id: str,
    rule_id: str,
    title: str,
    message: str,
    event_id: str | None = None,
) -> str:
    alert_id = new_id("alert")
    connection.execute(
        """
        INSERT INTO alerts (
            alert_id, tenant_id, site_id, camera_id, rule_id, event_id, title, message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (alert_id, tenant_id, site_id, camera_id, rule_id, event_id, title, message),
    )
    connection.commit()
    return alert_id


def list_table(connection: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    allowed = {"tenants", "sites", "cameras", "rules", "events", "alerts"}
    if table not in allowed:
        raise ValueError(f"Tabela inválida: {table}")
    return list(connection.execute(f"SELECT * FROM {table} ORDER BY created_at DESC"))

