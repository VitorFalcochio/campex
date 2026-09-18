from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import patch

import app.database as database_module
from app.database import connect, init_db


def test_init_db_runs_schema_only_once_per_database_file(tmp_path: Path) -> None:
    db_path = tmp_path / "edge.sqlite3"

    with patch.object(database_module, "_initialize_schema", wraps=database_module._initialize_schema) as initialize:
        with connect(db_path) as connection:
            init_db(connection)
        with connect(db_path) as connection:
            init_db(connection)

    assert initialize.call_count == 1


def test_edge_sqlite_allows_concurrent_short_writes(tmp_path: Path) -> None:
    db_path = tmp_path / "edge.sqlite3"
    with connect(db_path) as connection:
        init_db(connection)

    errors: list[str] = []

    def writer(worker_id: int) -> None:
        for attempt in range(25):
            try:
                with connect(db_path) as connection:
                    init_db(connection)
                    connection.execute(
                        """
                        INSERT INTO installation_state(key, value)
                        VALUES (?, ?)
                        ON CONFLICT(key) DO UPDATE SET value = excluded.value
                        """,
                        (f"worker_{worker_id}", str(attempt)),
                    )
                    connection.commit()
            except Exception as exc:  # pragma: no cover - assertion records any runtime failure
                errors.append(str(exc))

    threads = [threading.Thread(target=writer, args=(worker_id,)) for worker_id in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert all(not thread.is_alive() for thread in threads)
    assert errors == []

    with connect(db_path) as connection:
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]

    assert str(journal_mode).lower() == "wal"
    assert int(busy_timeout) == 30000
