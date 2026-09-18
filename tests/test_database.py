import sqlite3

from backend.config import Settings
from backend.database.db import database_is_initialized, initialize_database


def test_initialize_database_creates_sqlite_file(tmp_path):
    database_path = tmp_path / "campex_test.sqlite3"
    settings = Settings(
        environment="test",
        service_name="campex",
        version="0.1.0",
        log_level="INFO",
        database_url=f"sqlite:///{database_path}",
        frontend_origins=["http://127.0.0.1:5500"],
        camera_reconnect_seconds=0.1,
        camera_stale_seconds=1,
        camera_offline_seconds=3,
        camera_read_failure_limit=1,
        camera_test_timeout_seconds=1,
        vision_enabled=True,
        vision_detector="rfdetr",
        vision_device="auto",
        vision_fps=5,
        vision_confidence=0.5,
        vision_video_loop=False,
    )

    initialized_path = initialize_database(settings)

    assert initialized_path == database_path
    assert database_is_initialized(settings)

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT value FROM app_meta WHERE key = 'schema_version'"
        ).fetchone()

    camera_table = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'cameras'"
    ).fetchone()

    zones_table = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'zones'"
    ).fetchone()

    events_table = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'events'"
    ).fetchone()

    machines_table = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'machines'"
    ).fetchone()

    assert row == ("5",)
    assert camera_table == ("cameras",)
    assert zones_table == ("zones",)
    assert events_table == ("events",)
    assert machines_table == ("machines",)
