from __future__ import annotations

import sqlite3
from pathlib import Path

from backend.config import Settings


SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS app_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS cameras (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        area_id TEXT,
        source_type TEXT NOT NULL CHECK(source_type IN ('webcam', 'video_file', 'rtsp', 'ip_camera')),
        source_uri TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        vision_enabled INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'OFFLINE'
            CHECK(status IN ('CONNECTING', 'ONLINE', 'DEGRADED', 'OFFLINE')),
        last_frame_at TEXT,
        last_connected_at TEXT,
        last_disconnected_at TEXT,
        connection_state TEXT NOT NULL DEFAULT 'OFFLINE',
        consecutive_failures INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS zones (
        id TEXT PRIMARY KEY,
        camera_id TEXT NOT NULL,
        name TEXT NOT NULL,
        type TEXT NOT NULL CHECK(type IN ('monitored', 'restricted')),
        enabled INTEGER NOT NULL DEFAULT 1,
        points TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS events (
        id TEXT PRIMARY KEY,
        type TEXT NOT NULL,
        camera_id TEXT NOT NULL,
        zone_id TEXT,
        track_id INTEGER,
        severity TEXT NOT NULL CHECK(severity IN ('info', 'attention', 'critical')),
        status TEXT NOT NULL DEFAULT 'OPEN'
            CHECK(status IN ('OPEN', 'REVIEWED', 'CLOSED')),
        confidence REAL,
        started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        ended_at TEXT,
        duration REAL,
        metadata TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS investigations (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'OPEN'
            CHECK(status IN ('OPEN', 'REVIEWING', 'CLOSED')),
        event_id TEXT,
        notes TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS visual_rules (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        camera_id TEXT,
        zone_id TEXT,
        observation_type TEXT NOT NULL,
        zone_type TEXT,
        event_type TEXT NOT NULL,
        severity TEXT NOT NULL CHECK(severity IN ('info', 'attention', 'critical')),
        duration_threshold_seconds REAL NOT NULL DEFAULT 0,
        cooldown_seconds REAL NOT NULL DEFAULT 10,
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS machines (
        id TEXT PRIMARY KEY,
        camera_id TEXT NOT NULL,
        name TEXT NOT NULL,
        type TEXT NOT NULL CHECK(type IN ('fixed', 'mobile', 'vehicle', 'conveyor', 'robot', 'other')),
        enabled INTEGER NOT NULL DEFAULT 1,
        points TEXT NOT NULL,
        requires_operator INTEGER NOT NULL DEFAULT 1,
        allow_idle INTEGER NOT NULL DEFAULT 0,
        min_person_distance REAL NOT NULL DEFAULT 0.08,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS video_analyses (
        id TEXT PRIMARY KEY,
        organization_id TEXT NOT NULL,
        original_filename TEXT NOT NULL,
        stored_filename TEXT NOT NULL,
        storage_path TEXT NOT NULL,
        content_type TEXT,
        file_size INTEGER NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('QUEUED', 'PROCESSING', 'GENERATING_INSIGHTS', 'COMPLETED', 'FAILED')),
        progress INTEGER NOT NULL DEFAULT 0,
        error TEXT,
        source_json TEXT,
        metrics_json TEXT,
        events_json TEXT,
        tracks_json TEXT,
        detections_json TEXT,
        insight_json TEXT,
        debug_video_path TEXT,
        runtime_json TEXT,
        ai_json TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        completed_at TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_zones_camera ON zones(camera_id)",
    "CREATE INDEX IF NOT EXISTS idx_events_camera_started ON events(camera_id, started_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_events_zone_started ON events(zone_id, started_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_events_type_status ON events(type, status)",
    "CREATE INDEX IF NOT EXISTS idx_investigations_status ON investigations(status, updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_visual_rules_enabled ON visual_rules(enabled, updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_machines_camera ON machines(camera_id)",
    "CREATE INDEX IF NOT EXISTS idx_video_analyses_org_created ON video_analyses(organization_id, created_at DESC)",
)


CAMERAS_SCHEMA = SCHEMA_STATEMENTS[1]


def connect(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path, timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def initialize_database(settings: Settings) -> Path:
    database_path = settings.sqlite_path
    database_path.parent.mkdir(parents=True, exist_ok=True)

    with connect(database_path) as connection:
        for statement in SCHEMA_STATEMENTS:
            connection.execute(statement)
        _migrate_camera_source_types(connection)
        _migrate_camera_runtime_state(connection)
        _migrate_organization_scope(connection, settings.intelligence_default_organization_id)
        _migrate_video_analysis_debug_columns(connection)
        connection.execute(
            """
            INSERT INTO app_meta (key, value, updated_at)
            VALUES ('schema_version', '5', CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                value = '5',
                updated_at = CURRENT_TIMESTAMP
            """
        )
        connection.commit()

    return database_path


def _migrate_camera_source_types(connection: sqlite3.Connection) -> None:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'cameras'"
    ).fetchone()
    if row is None or "ip_camera" in (row["sql"] or ""):
        return

    connection.execute("ALTER TABLE cameras RENAME TO cameras_legacy")
    connection.execute(CAMERAS_SCHEMA)
    connection.execute(
        """
        INSERT INTO cameras (
            id, name, area_id, source_type, source_uri,
            enabled, vision_enabled, status, created_at, updated_at
        )
        SELECT
            id, name, area_id, source_type, source_uri,
            enabled, vision_enabled, status, created_at, updated_at
        FROM cameras_legacy
        """
    )
    connection.execute("DROP TABLE cameras_legacy")


def _migrate_camera_runtime_state(connection: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(cameras)").fetchall()
    }
    migrations = {
        "last_frame_at": "ALTER TABLE cameras ADD COLUMN last_frame_at TEXT",
        "last_connected_at": "ALTER TABLE cameras ADD COLUMN last_connected_at TEXT",
        "last_disconnected_at": "ALTER TABLE cameras ADD COLUMN last_disconnected_at TEXT",
        "connection_state": "ALTER TABLE cameras ADD COLUMN connection_state TEXT NOT NULL DEFAULT 'OFFLINE'",
        "consecutive_failures": "ALTER TABLE cameras ADD COLUMN consecutive_failures INTEGER NOT NULL DEFAULT 0",
    }
    for column, statement in migrations.items():
        if column not in columns:
            connection.execute(statement)


def _migrate_organization_scope(
    connection: sqlite3.Connection, default_organization_id: str
) -> None:
    scoped_tables = ("cameras", "zones", "events", "investigations", "visual_rules", "machines")
    for table in scoped_tables:
        columns = {
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if "organization_id" not in columns:
            safe_default = default_organization_id.replace("'", "''")
            connection.execute(
                f"ALTER TABLE {table} ADD COLUMN organization_id TEXT NOT NULL DEFAULT '{safe_default}'"
            )
        connection.execute(
            f"""
            UPDATE {table}
            SET organization_id = ?
            WHERE organization_id IS NULL OR organization_id = ''
            """,
            (default_organization_id,),
        )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_cameras_org_status ON cameras(organization_id, status)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_org_started ON events(organization_id, started_at DESC)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_machines_org_camera ON machines(organization_id, camera_id)"
    )


def _migrate_video_analysis_debug_columns(connection: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(video_analyses)").fetchall()
    }
    migrations = {
        "debug_video_path": "ALTER TABLE video_analyses ADD COLUMN debug_video_path TEXT",
        "runtime_json": "ALTER TABLE video_analyses ADD COLUMN runtime_json TEXT",
        "ai_json": "ALTER TABLE video_analyses ADD COLUMN ai_json TEXT",
    }
    for column, statement in migrations.items():
        if column not in columns:
            connection.execute(statement)


def database_is_initialized(settings: Settings) -> bool:
    database_path = settings.sqlite_path
    if not database_path.exists():
        return False

    with connect(database_path) as connection:
        result = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'app_meta'"
        ).fetchone()
        return result is not None
