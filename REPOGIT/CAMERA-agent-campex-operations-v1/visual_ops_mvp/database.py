from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = ROOT / "data" / "visual_ops_mvp.sqlite3"


def connect(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS tenants (
            tenant_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            document TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS sites (
            site_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            name TEXT NOT NULL,
            location TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (tenant_id) REFERENCES tenants (tenant_id)
        );

        CREATE TABLE IF NOT EXISTS cameras (
            camera_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            site_id TEXT NOT NULL,
            name TEXT NOT NULL,
            source_type TEXT NOT NULL DEFAULT 'future_live',
            source_ref TEXT,
            connection_status TEXT NOT NULL DEFAULT 'not_connected',
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (tenant_id) REFERENCES tenants (tenant_id),
            FOREIGN KEY (site_id) REFERENCES sites (site_id)
        );

        CREATE TABLE IF NOT EXISTS rules (
            rule_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            site_id TEXT NOT NULL,
            camera_id TEXT,
            name TEXT NOT NULL,
            rule_type TEXT NOT NULL,
            parameters_json TEXT NOT NULL DEFAULT '{}',
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (tenant_id) REFERENCES tenants (tenant_id),
            FOREIGN KEY (site_id) REFERENCES sites (site_id),
            FOREIGN KEY (camera_id) REFERENCES cameras (camera_id)
        );

        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            site_id TEXT NOT NULL,
            camera_id TEXT NOT NULL,
            rule_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            duration_seconds REAL,
            severity TEXT NOT NULL DEFAULT 'info',
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (tenant_id) REFERENCES tenants (tenant_id),
            FOREIGN KEY (site_id) REFERENCES sites (site_id),
            FOREIGN KEY (camera_id) REFERENCES cameras (camera_id),
            FOREIGN KEY (rule_id) REFERENCES rules (rule_id)
        );

        CREATE TABLE IF NOT EXISTS alerts (
            alert_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            site_id TEXT NOT NULL,
            camera_id TEXT NOT NULL,
            rule_id TEXT NOT NULL,
            event_id TEXT,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            resolved_at TEXT,
            FOREIGN KEY (tenant_id) REFERENCES tenants (tenant_id),
            FOREIGN KEY (site_id) REFERENCES sites (site_id),
            FOREIGN KEY (camera_id) REFERENCES cameras (camera_id),
            FOREIGN KEY (rule_id) REFERENCES rules (rule_id),
            FOREIGN KEY (event_id) REFERENCES events (event_id)
        );
        """
    )
    connection.commit()

