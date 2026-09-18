from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.config import DATABASE_PATH


PROTECTED_TABLES = (
    "cameras",
    "eventos",
    "machine_monitors",
    "operational_areas",
    "operational_processes",
    "operational_assets",
    "monitored_areas",
    "sync_outbox",
    "alert_deliveries",
    "users",
)


def _persistent_db_counts() -> dict[str, int]:
    path = Path(DATABASE_PATH)
    if not path.exists():
        return {}
    connection = sqlite3.connect(path)
    try:
        counts: dict[str, int] = {}
        for table in PROTECTED_TABLES:
            try:
                counts[table] = int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            except sqlite3.Error:
                counts[table] = -1
        try:
            counts["operational_samples_test_compat"] = int(
                connection.execute(
                    "SELECT COUNT(*) FROM operational_samples WHERE tenant_id = 'cli_operational_compat'"
                ).fetchone()[0]
            )
        except sqlite3.Error:
            counts["operational_samples_test_compat"] = -1
        return counts
    finally:
        connection.close()


@pytest.fixture(autouse=True)
def protect_operational_database() -> None:
    before = _persistent_db_counts()
    yield
    after = _persistent_db_counts()
    assert after == before, (
        "Teste alterou o banco operacional persistente. "
        "Use tmp_path, tempfile ou patch do connect() para SQLite isolado. "
        f"Antes={before}; Depois={after}"
    )
