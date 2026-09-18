from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import httpx

from app.database import connect, init_db
from app.models import registrar_evento
from edge_agent.sync_outbox import flush_sync_outbox, pending_sync_count


ROOT = Path(__file__).resolve().parents[1]
EDGE_DB_PATH = Path(os.getenv("EDGE_DB_PATH", str(ROOT / "data" / "edge_cloud_validation.sqlite3")))
CLOUD_URL = os.getenv("CAMPEX_CLOUD_URL", "http://127.0.0.1:8010")
EDGE_ID = os.getenv("CAMPEX_EDGE_ID", "edge_dev_01")
EDGE_SECRET = os.getenv("CAMPEX_EDGE_SECRET", "secret-local-dev-com-mais-de-12")
TENANT_ID = os.getenv("CAMPEX_TENANT_ID", "cli_dev")
UNIDADE_ID = os.getenv("CAMPEX_UNIDADE_ID", "uni_dev")
CAMERA_ID = os.getenv("CAMPEX_CAMERA_ID", "cam_dev_01")


def ensure_edge_fixture(connection: sqlite3.Connection) -> None:
    connection.execute(
        "INSERT OR IGNORE INTO clientes (id, nome, status) VALUES (?, ?, 'ativo')",
        (TENANT_ID, os.getenv("CAMPEX_TENANT_NAME", "Cliente de validacao")),
    )
    connection.execute(
        "INSERT OR IGNORE INTO unidades (id, cliente_id, nome) VALUES (?, ?, ?)",
        (UNIDADE_ID, TENANT_ID, "Matriz"),
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO cameras (id, cliente_id, unidade_id, nome, status)
        VALUES (?, ?, ?, ?, 'online')
        """,
        (CAMERA_ID, TENANT_ID, UNIDADE_ID, "Camera teste Edge Cloud"),
    )
    connection.commit()


def register_edge() -> None:
    payload = {
        "id": EDGE_ID,
        "tenant_id": TENANT_ID,
        "cliente_id": TENANT_ID,
        "unidade_id": UNIDADE_ID,
        "nome": os.getenv("CAMPEX_EDGE_NAME", "Edge de validacao local"),
        "secret": EDGE_SECRET,
    }
    response = httpx.post(f"{CLOUD_URL.rstrip('/')}/admin/edge-devices", json=payload, timeout=10)
    if response.status_code not in {200, 409}:
        response.raise_for_status()


def main() -> int:
    register_edge()
    with connect(EDGE_DB_PATH) as connection:
        init_db(connection)
        ensure_edge_fixture(connection)
        before = pending_sync_count(connection)
        event_id = registrar_evento(
            connection,
            TENANT_ID,
            UNIDADE_ID,
            CAMERA_ID,
            "machine_stoppage",
            inicio="2026-07-28T08:00:00-03:00",
            fim="2026-07-28T08:05:00-03:00",
            duracao=300,
            operador_presente=False,
            confianca=0.91,
        )
        synced = flush_sync_outbox(connection, CLOUD_URL, EDGE_ID, EDGE_SECRET)
        after = pending_sync_count(connection)
    print(f"Evento local criado: {event_id}")
    print(f"Outbox pendente antes: {before}")
    print(f"Sincronizados agora: {synced}")
    print(f"Outbox pendente depois: {after}")
    print(f"Dashboard Cloud: {CLOUD_URL.rstrip('/')}/dashboard")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
