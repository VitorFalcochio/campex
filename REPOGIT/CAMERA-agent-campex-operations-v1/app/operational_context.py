from __future__ import annotations

import sqlite3
import uuid
from typing import Any


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def row_to_dict(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    return dict(row)


def criar_operational_area(
    connection: sqlite3.Connection,
    *,
    cliente_id: str,
    unidade_id: str,
    nome: str,
    tipo: str = "production_area",
) -> str:
    area_id = new_id("oparea")
    connection.execute(
        """
        INSERT INTO operational_areas (id, cliente_id, unidade_id, nome, tipo)
        VALUES (?, ?, ?, ?, ?)
        """,
        (area_id, cliente_id, unidade_id, nome, tipo),
    )
    connection.commit()
    return area_id


def criar_operational_process(
    connection: sqlite3.Connection,
    *,
    cliente_id: str,
    unidade_id: str,
    nome: str,
    area_id: str | None = None,
    tipo: str = "station",
) -> str:
    process_id = new_id("opproc")
    connection.execute(
        """
        INSERT INTO operational_processes (id, cliente_id, unidade_id, area_id, nome, tipo)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (process_id, cliente_id, unidade_id, area_id, nome, tipo),
    )
    connection.commit()
    return process_id


def criar_operational_asset(
    connection: sqlite3.Connection,
    *,
    cliente_id: str,
    unidade_id: str,
    nome: str,
    area_id: str | None = None,
    process_id: str | None = None,
    tipo: str = "machine",
) -> str:
    asset_id = new_id("opasset")
    connection.execute(
        """
        INSERT INTO operational_assets (id, cliente_id, unidade_id, area_id, process_id, nome, tipo)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (asset_id, cliente_id, unidade_id, area_id, process_id, nome, tipo),
    )
    connection.commit()
    return asset_id


def resolve_context(
    connection: sqlite3.Connection,
    *,
    camera_id: str | None = None,
    area_id: str | None = None,
    machine_monitor_id: str | None = None,
    fallback_cliente_id: str | None = None,
    fallback_unidade_id: str | None = None,
) -> dict[str, Any]:
    context = {
        "cliente_id": fallback_cliente_id,
        "unidade_id": fallback_unidade_id,
        "site_id": fallback_unidade_id,
        "area_context_id": None,
        "process_id": None,
        "asset_id": None,
        "camera_id": camera_id,
        "machine_monitor_id": machine_monitor_id,
        "zone_id": area_id,
    }
    if camera_id:
        row = connection.execute("SELECT * FROM cameras WHERE id = ?", (camera_id,)).fetchone()
        if row:
            camera = row_to_dict(row)
            context.update(
                {
                    "cliente_id": camera.get("cliente_id") or context["cliente_id"],
                    "unidade_id": camera.get("unidade_id") or context["unidade_id"],
                    "site_id": camera.get("site_id") or camera.get("unidade_id") or context["site_id"],
                    "area_context_id": camera.get("area_context_id") or context["area_context_id"],
                    "process_id": camera.get("process_id") or context["process_id"],
                    "asset_id": camera.get("asset_id") or context["asset_id"],
                }
            )
    if area_id:
        row = connection.execute("SELECT * FROM monitored_areas WHERE id = ?", (area_id,)).fetchone()
        if row:
            area = row_to_dict(row)
            context.update(
                {
                    "cliente_id": area.get("cliente_id") or context["cliente_id"],
                    "unidade_id": area.get("unidade_id") or context["unidade_id"],
                    "site_id": area.get("site_id") or area.get("unidade_id") or context["site_id"],
                    "area_context_id": area.get("area_context_id") or context["area_context_id"],
                    "process_id": area.get("process_id") or context["process_id"],
                    "asset_id": area.get("asset_id") or area.get("machine_id") or context["asset_id"],
                }
            )
            if not context["machine_monitor_id"] and area.get("machine_id"):
                context["machine_monitor_id"] = area.get("machine_id")
    if machine_monitor_id or context.get("machine_monitor_id"):
        monitor_id = machine_monitor_id or context.get("machine_monitor_id")
        row = connection.execute("SELECT * FROM machine_monitors WHERE id = ?", (monitor_id,)).fetchone()
        if row:
            monitor = row_to_dict(row)
            context.update(
                {
                    "cliente_id": monitor.get("client_id") or context["cliente_id"],
                    "unidade_id": monitor.get("unit_id") or context["unidade_id"],
                    "site_id": monitor.get("site_id") or monitor.get("unit_id") or context["site_id"],
                    "area_context_id": monitor.get("area_context_id") or context["area_context_id"],
                    "process_id": monitor.get("process_id") or context["process_id"],
                    "asset_id": monitor.get("asset_id") or monitor.get("id") or context["asset_id"],
                    "machine_monitor_id": monitor.get("id"),
                }
            )
    context["site_id"] = context.get("site_id") or context.get("unidade_id")
    return context


def apply_context_to_camera(
    connection: sqlite3.Connection,
    camera_id: str,
    *,
    area_context_id: str | None = None,
    process_id: str | None = None,
    asset_id: str | None = None,
) -> dict[str, Any]:
    context = resolve_context(connection, camera_id=camera_id)
    connection.execute(
        """
        UPDATE cameras
        SET site_id = ?,
            area_context_id = COALESCE(?, area_context_id),
            process_id = COALESCE(?, process_id),
            asset_id = COALESCE(?, asset_id)
        WHERE id = ?
        """,
        (context["site_id"], area_context_id, process_id, asset_id, camera_id),
    )
    connection.commit()
    return resolve_context(connection, camera_id=camera_id)


def apply_context_to_event(
    connection: sqlite3.Connection,
    event_id: str,
    *,
    camera_id: str | None = None,
    area_id: str | None = None,
    machine_monitor_id: str | None = None,
) -> dict[str, Any]:
    if not any([camera_id, area_id, machine_monitor_id]):
        row = connection.execute("SELECT camera_id, area_id, machine_monitor_id, cliente_id, unidade_id FROM eventos WHERE id = ?", (event_id,)).fetchone()
        if row:
            camera_id = row["camera_id"]
            area_id = row["area_id"]
            machine_monitor_id = row["machine_monitor_id"]
    context = resolve_context(connection, camera_id=camera_id, area_id=area_id, machine_monitor_id=machine_monitor_id)
    connection.execute(
        """
        UPDATE eventos
        SET site_id = COALESCE(?, site_id),
            area_context_id = COALESCE(?, area_context_id),
            process_id = COALESCE(?, process_id),
            asset_id = COALESCE(?, asset_id),
            machine_monitor_id = COALESCE(?, machine_monitor_id)
        WHERE id = ?
        """,
        (
            context.get("site_id"),
            context.get("area_context_id"),
            context.get("process_id"),
            context.get("asset_id"),
            context.get("machine_monitor_id"),
            event_id,
        ),
    )
    connection.commit()
    return context
