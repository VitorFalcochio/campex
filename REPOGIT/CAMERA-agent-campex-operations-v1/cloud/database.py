from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.config import ROOT


DATABASE_URL = os.getenv("DATABASE_URL", "")
SQLITE_CLOUD_PATH = Path(os.getenv("CLOUD_SQLITE_PATH", str(ROOT / "data" / "campex_cloud.sqlite3")))


def is_postgres_url(url: str | None = None) -> bool:
    value = url if url is not None else DATABASE_URL
    return value.startswith("postgres://") or value.startswith("postgresql://")


@contextmanager
def connect():
    if is_postgres_url():
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("psycopg precisa estar instalado para usar PostgreSQL.") from exc
        with psycopg.connect(DATABASE_URL, row_factory=dict_row) as connection:
            yield PostgresConnection(connection)
        return
    SQLITE_CLOUD_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(SQLITE_CLOUD_PATH) as connection:
        connection.row_factory = sqlite3.Row
        yield SQLiteConnection(connection)


class SQLiteConnection:
    param = "?"

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def execute(self, sql: str, values: tuple = ()):
        return self.connection.execute(sql, values)

    def fetchone(self, sql: str, values: tuple = ()):
        row = self.connection.execute(sql, values).fetchone()
        return dict(row) if row else None

    def fetchall(self, sql: str, values: tuple = ()):
        return [dict(row) for row in self.connection.execute(sql, values).fetchall()]

    def commit(self) -> None:
        self.connection.commit()


class PostgresConnection:
    param = "%s"

    def __init__(self, connection) -> None:
        self.connection = connection

    def _sql(self, sql: str) -> str:
        return sql.replace("?", "%s")

    def execute(self, sql: str, values: tuple = ()):
        return self.connection.execute(self._sql(sql), values)

    def fetchone(self, sql: str, values: tuple = ()):
        cursor = self.connection.execute(self._sql(sql), values)
        return cursor.fetchone()

    def fetchall(self, sql: str, values: tuple = ()):
        cursor = self.connection.execute(self._sql(sql), values)
        return list(cursor.fetchall())

    def commit(self) -> None:
        self.connection.commit()


def init_cloud_db(db=None) -> None:
    if db is None:
        with connect() as connection:
            init_cloud_db(connection)
        return
    if isinstance(db, PostgresConnection):
        _init_postgres(db)
    else:
        _init_sqlite(db)
    db.commit()


def _init_sqlite(db: SQLiteConnection) -> None:
    db.connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            cliente_id TEXT,
            nome TEXT,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            ativo INTEGER NOT NULL DEFAULT 1,
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS user_sessions (
            token_hash TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS clientes (
            id TEXT PRIMARY KEY,
            nome TEXT NOT NULL,
            documento TEXT,
            status TEXT NOT NULL DEFAULT 'ativo',
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS unidades (
            id TEXT PRIMARY KEY,
            cliente_id TEXT NOT NULL,
            nome TEXT NOT NULL,
            localizacao TEXT,
            timezone TEXT NOT NULL DEFAULT 'America/Sao_Paulo',
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS edge_devices (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            cliente_id TEXT NOT NULL,
            unidade_id TEXT NOT NULL,
            nome TEXT NOT NULL,
            secret_hash TEXT NOT NULL,
            edge_secret_encrypted TEXT,
            credential_key_encrypted TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            revoked_at TEXT,
            last_seen_at TEXT,
            last_diagnostics_json TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS edge_update_releases (
            version TEXT PRIMARY KEY,
            sha256 TEXT NOT NULL,
            size_bytes INTEGER,
            package_path TEXT NOT NULL,
            approved INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS edge_events (
            id TEXT PRIMARY KEY,
            event_uuid TEXT NOT NULL UNIQUE,
            tenant_id TEXT NOT NULL,
            cliente_id TEXT NOT NULL,
            unidade_id TEXT NOT NULL,
            edge_id TEXT NOT NULL,
            camera_id TEXT NOT NULL,
            tipo TEXT NOT NULL,
            inicio TEXT,
            fim TEXT,
            duracao REAL,
            operador_presente INTEGER,
            confianca REAL,
            severidade TEXT,
            status TEXT,
            midia_path TEXT,
            payload_json TEXT NOT NULL,
            received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS report_deliveries (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            cliente_id TEXT NOT NULL,
            unidade_id TEXT NOT NULL,
            edge_id TEXT NOT NULL,
            recipient TEXT NOT NULL,
            subject TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            provider_message_id TEXT,
            last_error TEXT,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            sent_at TEXT
        );

        CREATE TABLE IF NOT EXISTS cloud_cameras (
            id TEXT PRIMARY KEY,
            cliente_id TEXT NOT NULL,
            unidade_id TEXT NOT NULL,
            edge_id TEXT,
            nome TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'configured',
            ativa INTEGER NOT NULL DEFAULT 1,
            source_type TEXT NOT NULL DEFAULT 'rtsp',
            secure_ref TEXT,
            rtsp_host TEXT,
            rtsp_port INTEGER,
            rtsp_path TEXT,
            rtsp_username TEXT,
            rtsp_password_encrypted TEXT,
            resolucao TEXT,
            fps REAL,
            ultimo_frame TEXT,
            runtime_status_json TEXT,
            area_context_id TEXT,
            process_id TEXT,
            asset_id TEXT,
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS operational_areas (
            id TEXT PRIMARY KEY,
            cliente_id TEXT NOT NULL,
            unidade_id TEXT NOT NULL,
            nome TEXT NOT NULL,
            tipo TEXT NOT NULL DEFAULT 'area',
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS operational_processes (
            id TEXT PRIMARY KEY,
            cliente_id TEXT NOT NULL,
            unidade_id TEXT NOT NULL,
            area_id TEXT NOT NULL,
            nome TEXT NOT NULL,
            tipo TEXT NOT NULL DEFAULT 'processo',
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS operational_assets (
            id TEXT PRIMARY KEY,
            cliente_id TEXT NOT NULL,
            unidade_id TEXT NOT NULL,
            area_id TEXT NOT NULL,
            process_id TEXT NOT NULL,
            nome TEXT NOT NULL,
            tipo TEXT NOT NULL DEFAULT 'ativo',
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS cloud_monitored_areas (
            id TEXT PRIMARY KEY,
            cliente_id TEXT NOT NULL,
            camera_id TEXT NOT NULL,
            nome TEXT NOT NULL,
            tipo TEXT NOT NULL,
            pontos_json TEXT NOT NULL,
            ativa INTEGER NOT NULL DEFAULT 1,
            machine_id TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS cloud_machine_monitors (
            id TEXT PRIMARY KEY,
            client_id TEXT NOT NULL,
            unit_id TEXT NOT NULL,
            camera_id TEXT NOT NULL,
            nome TEXT NOT NULL,
            machine_polygon_json TEXT NOT NULL DEFAULT '[]',
            operator_polygon_json TEXT NOT NULL DEFAULT '[]',
            operation_polygon_json TEXT,
            ativo INTEGER NOT NULL DEFAULT 1,
            current_state TEXT NOT NULL DEFAULT 'UNKNOWN',
            current_motion REAL,
            motion_sensitivity REAL,
            motion_threshold REAL,
            stop_seconds REAL DEFAULT 30,
            operator_absence_seconds REAL DEFAULT 300,
            stopped_with_operator_seconds REAL DEFAULT 120,
            calibration_status TEXT NOT NULL DEFAULT 'pending',
            calibration_result TEXT,
            separation_score REAL,
            area_context_id TEXT,
            process_id TEXT,
            asset_id TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    _ensure_sqlite_column(db, "edge_devices", "last_seen_at", "TEXT")
    _ensure_sqlite_column(db, "edge_devices", "last_diagnostics_json", "TEXT")
    _ensure_sqlite_column(db, "edge_devices", "edge_secret_encrypted", "TEXT")
    _ensure_sqlite_column(db, "edge_devices", "credential_key_encrypted", "TEXT")
    _ensure_sqlite_column(db, "edge_events", "severidade", "TEXT")
    _ensure_sqlite_column(db, "edge_events", "status", "TEXT")
    _ensure_sqlite_column(db, "cloud_cameras", "rtsp_username", "TEXT")
    _ensure_sqlite_column(db, "cloud_cameras", "rtsp_password_encrypted", "TEXT")
    _ensure_sqlite_column(db, "cloud_cameras", "runtime_status_json", "TEXT")


def _init_postgres(db: PostgresConnection) -> None:
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            cliente_id TEXT,
            nome TEXT,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            ativo INTEGER NOT NULL DEFAULT 1,
            criado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
            atualizado_em TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS user_sessions (
            token_hash TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS clientes (
            id TEXT PRIMARY KEY,
            nome TEXT NOT NULL,
            documento TEXT,
            status TEXT NOT NULL DEFAULT 'ativo',
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS unidades (
            id TEXT PRIMARY KEY,
            cliente_id TEXT NOT NULL,
            nome TEXT NOT NULL,
            localizacao TEXT,
            timezone TEXT NOT NULL DEFAULT 'America/Sao_Paulo',
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS edge_devices (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            cliente_id TEXT NOT NULL,
            unidade_id TEXT NOT NULL,
            nome TEXT NOT NULL,
            secret_hash TEXT NOT NULL,
            edge_secret_encrypted TEXT,
            credential_key_encrypted TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            revoked_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS edge_events (
            id TEXT PRIMARY KEY,
            event_uuid TEXT NOT NULL UNIQUE,
            tenant_id TEXT NOT NULL,
            cliente_id TEXT NOT NULL,
            unidade_id TEXT NOT NULL,
            edge_id TEXT NOT NULL REFERENCES edge_devices(id),
            camera_id TEXT NOT NULL,
            tipo TEXT NOT NULL,
            inicio TIMESTAMPTZ,
            fim TIMESTAMPTZ,
            duracao DOUBLE PRECISION,
            operador_presente BOOLEAN,
            confianca DOUBLE PRECISION,
            severidade TEXT,
            status TEXT,
            midia_path TEXT,
            payload_json TEXT NOT NULL,
            received_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS edge_update_releases (
            version TEXT PRIMARY KEY,
            sha256 TEXT NOT NULL,
            size_bytes BIGINT,
            package_path TEXT NOT NULL,
            approved BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS report_deliveries (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            cliente_id TEXT NOT NULL,
            unidade_id TEXT NOT NULL,
            edge_id TEXT NOT NULL REFERENCES edge_devices(id),
            recipient TEXT NOT NULL,
            subject TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            provider_message_id TEXT,
            last_error TEXT,
            payload_json TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            sent_at TIMESTAMPTZ
        )
        """
    )
    db.execute("ALTER TABLE edge_devices ADD COLUMN IF NOT EXISTS last_seen_at TEXT")
    db.execute("ALTER TABLE edge_devices ADD COLUMN IF NOT EXISTS last_diagnostics_json TEXT")
    db.execute("ALTER TABLE edge_devices ADD COLUMN IF NOT EXISTS edge_secret_encrypted TEXT")
    db.execute("ALTER TABLE edge_devices ADD COLUMN IF NOT EXISTS credential_key_encrypted TEXT")
    db.execute("ALTER TABLE edge_events ADD COLUMN IF NOT EXISTS severidade TEXT")
    db.execute("ALTER TABLE edge_events ADD COLUMN IF NOT EXISTS status TEXT")
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS cloud_cameras (
            id TEXT PRIMARY KEY,
            cliente_id TEXT NOT NULL,
            unidade_id TEXT NOT NULL,
            edge_id TEXT,
            nome TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'configured',
            ativa INTEGER NOT NULL DEFAULT 1,
            source_type TEXT NOT NULL DEFAULT 'rtsp',
            secure_ref TEXT,
            rtsp_host TEXT,
            rtsp_port INTEGER,
            rtsp_path TEXT,
            rtsp_username TEXT,
            rtsp_password_encrypted TEXT,
            resolucao TEXT,
            fps DOUBLE PRECISION,
            ultimo_frame TIMESTAMPTZ,
            runtime_status_json TEXT,
            area_context_id TEXT,
            process_id TEXT,
            asset_id TEXT,
            criado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
            atualizado_em TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    db.execute("ALTER TABLE cloud_cameras ADD COLUMN IF NOT EXISTS rtsp_username TEXT")
    db.execute("ALTER TABLE cloud_cameras ADD COLUMN IF NOT EXISTS rtsp_password_encrypted TEXT")
    db.execute("ALTER TABLE cloud_cameras ADD COLUMN IF NOT EXISTS runtime_status_json TEXT")
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS operational_areas (
            id TEXT PRIMARY KEY,
            cliente_id TEXT NOT NULL,
            unidade_id TEXT NOT NULL,
            nome TEXT NOT NULL,
            tipo TEXT NOT NULL DEFAULT 'area',
            criado_em TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS operational_processes (
            id TEXT PRIMARY KEY,
            cliente_id TEXT NOT NULL,
            unidade_id TEXT NOT NULL,
            area_id TEXT NOT NULL,
            nome TEXT NOT NULL,
            tipo TEXT NOT NULL DEFAULT 'processo',
            criado_em TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS operational_assets (
            id TEXT PRIMARY KEY,
            cliente_id TEXT NOT NULL,
            unidade_id TEXT NOT NULL,
            area_id TEXT NOT NULL,
            process_id TEXT NOT NULL,
            nome TEXT NOT NULL,
            tipo TEXT NOT NULL DEFAULT 'ativo',
            criado_em TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS cloud_monitored_areas (
            id TEXT PRIMARY KEY,
            cliente_id TEXT NOT NULL,
            camera_id TEXT NOT NULL,
            nome TEXT NOT NULL,
            tipo TEXT NOT NULL,
            pontos_json TEXT NOT NULL,
            ativa INTEGER NOT NULL DEFAULT 1,
            machine_id TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS cloud_machine_monitors (
            id TEXT PRIMARY KEY,
            client_id TEXT NOT NULL,
            unit_id TEXT NOT NULL,
            camera_id TEXT NOT NULL,
            nome TEXT NOT NULL,
            machine_polygon_json TEXT NOT NULL DEFAULT '[]',
            operator_polygon_json TEXT NOT NULL DEFAULT '[]',
            operation_polygon_json TEXT,
            ativo INTEGER NOT NULL DEFAULT 1,
            current_state TEXT NOT NULL DEFAULT 'UNKNOWN',
            current_motion DOUBLE PRECISION,
            motion_sensitivity DOUBLE PRECISION,
            motion_threshold DOUBLE PRECISION,
            stop_seconds DOUBLE PRECISION DEFAULT 30,
            operator_absence_seconds DOUBLE PRECISION DEFAULT 300,
            stopped_with_operator_seconds DOUBLE PRECISION DEFAULT 120,
            calibration_status TEXT NOT NULL DEFAULT 'pending',
            calibration_result TEXT,
            separation_score DOUBLE PRECISION,
            area_context_id TEXT,
            process_id TEXT,
            asset_id TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def _ensure_sqlite_column(db: SQLiteConnection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in db.connection.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        db.connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
