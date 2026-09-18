from __future__ import annotations

import sqlite3

from app.models import atualizar_camera_status
from shared.schemas import now_iso


def mark_camera_online(connection: sqlite3.Connection, camera_id: str) -> None:
    atualizar_camera_status(connection, camera_id, "online", now_iso())


def mark_camera_offline(connection: sqlite3.Connection, camera_id: str) -> None:
    atualizar_camera_status(connection, camera_id, "offline")


def mark_edge_contact(connection: sqlite3.Connection, edge_id: str, status: str = "online") -> None:
    connection.execute(
        "UPDATE dispositivos SET status = ?, ultimo_contato = ? WHERE id = ?",
        (status, now_iso(), edge_id),
    )
    connection.commit()

