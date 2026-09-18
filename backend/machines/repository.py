from __future__ import annotations

import json
import logging
from pathlib import Path
from uuid import uuid4

from backend.config import Settings
from backend.database.db import connect
from backend.machines.models import Machine
from backend.zones.models import ZonePoint


logger = logging.getLogger("campex.machines.repository")
MACHINE_TYPES = {"fixed", "mobile", "vehicle", "conveyor", "robot", "other"}


class MachineRepository:
    def __init__(self, settings: Settings) -> None:
        self.database_path = settings.sqlite_path

    def list(self, camera_id: str | None = None, organization_id: str | None = None) -> list[Machine]:
        with connect(self._db_path) as connection:
            if organization_id is not None and camera_id is not None:
                rows = connection.execute(
                    "SELECT * FROM machines WHERE organization_id = ? AND camera_id = ? ORDER BY created_at ASC",
                    (organization_id, camera_id),
                ).fetchall()
            elif organization_id is not None:
                rows = connection.execute(
                    "SELECT * FROM machines WHERE organization_id = ? ORDER BY created_at ASC",
                    (organization_id,),
                ).fetchall()
            elif camera_id:
                rows = connection.execute(
                    "SELECT * FROM machines WHERE camera_id = ? ORDER BY created_at ASC",
                    (camera_id,),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM machines ORDER BY created_at ASC"
                ).fetchall()
        machines: list[Machine] = []
        for row in rows:
            try:
                machines.append(_row_to_machine(row))
            except (json.JSONDecodeError, TypeError, ValueError, KeyError, IndexError):
                logger.exception("Ignoring malformed machine record", extra={"machine_id": row["id"]})
        return machines

    def get(self, machine_id: str, organization_id: str | None = None) -> Machine | None:
        with connect(self._db_path) as connection:
            if organization_id is not None:
                row = connection.execute(
                    "SELECT * FROM machines WHERE id = ? AND organization_id = ?",
                    (machine_id, organization_id),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT * FROM machines WHERE id = ?", (machine_id,)
                ).fetchone()
        if row is None:
            return None
        return _row_to_machine(row)

    def create(
        self,
        *,
        camera_id: str,
        name: str,
        machine_type: str,
        points: list[ZonePoint],
        enabled: bool = True,
        requires_operator: bool = True,
        allow_idle: bool = False,
        min_person_distance: float = 0.08,
        organization_id: str | None = None,
    ) -> Machine:
        _validate_machine_type(machine_type)
        _validate_points(points)
        machine_id = f"mach_{uuid4().hex[:12]}"
        points_json = json.dumps([point.as_list() for point in points])
        columns = [
            "id", "camera_id", "name", "type", "enabled", "points",
            "requires_operator", "allow_idle", "min_person_distance",
        ]
        values: list = [
            machine_id, camera_id, name, machine_type, int(enabled), points_json,
            int(requires_operator), int(allow_idle), float(min_person_distance),
        ]
        if organization_id is not None:
            columns.append("organization_id")
            values.append(organization_id)
        with connect(self._db_path) as connection:
            connection.execute(
                f"""
                INSERT INTO machines ({", ".join(columns)})
                VALUES ({", ".join(["?"] * len(values))})
                """,
                values,
            )
            connection.commit()
        return self.get(machine_id, organization_id=organization_id)  # type: ignore[return-value]

    def update(self, machine_id: str, updates: dict, organization_id: str | None = None) -> Machine | None:
        allowed = {
            "name",
            "type",
            "enabled",
            "points",
            "requires_operator",
            "allow_idle",
            "min_person_distance",
        }
        fields = [key for key in updates if key in allowed]
        if not fields:
            return self.get(machine_id)

        values: list = []
        for field_name in fields:
            value = updates[field_name]
            if field_name in {"enabled", "requires_operator", "allow_idle"}:
                values.append(int(value))
            elif field_name == "points":
                _validate_points(value)
                values.append(json.dumps([_point_as_list(point) for point in value]))
            elif field_name == "type":
                _validate_machine_type(value)
                values.append(value)
            elif field_name == "min_person_distance":
                values.append(float(value))
            else:
                values.append(value)

        assignments = ", ".join(f"{field} = ?" for field in fields)
        with connect(self._db_path) as connection:
            connection.execute(
                f"UPDATE machines SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (*values, machine_id),
            )
            connection.commit()
        return self.get(machine_id, organization_id=organization_id)  # type: ignore[return-value]

    def delete(self, machine_id: str, organization_id: str | None = None) -> bool:
        with connect(self._db_path) as connection:
            if organization_id is not None:
                cursor = connection.execute(
                    "DELETE FROM machines WHERE id = ? AND organization_id = ?",
                    (machine_id, organization_id),
                )
            else:
                cursor = connection.execute("DELETE FROM machines WHERE id = ?", (machine_id,))
            connection.commit()
            return cursor.rowcount > 0

    @property
    def _db_path(self) -> Path:
        return self.database_path


def _validate_machine_type(machine_type: str) -> None:
    if machine_type not in MACHINE_TYPES:
        raise ValueError(f"Machine type must be one of: {', '.join(sorted(MACHINE_TYPES))}.")


def _validate_points(points: list) -> None:
    if len(points) < 3:
        raise ValueError("Machine polygon must have at least 3 points.")
    for point in points:
        x, y = _point_xy(point)
        if not 0.0 <= float(x) <= 1.0 or not 0.0 <= float(y) <= 1.0:
            raise ValueError("Machine coordinates must be normalized between 0 and 1.")


def _point_xy(point) -> tuple[float, float]:
    if isinstance(point, ZonePoint):
        return point.x, point.y
    if isinstance(point, (list, tuple)) and len(point) == 2:
        return float(point[0]), float(point[1])
    raise ValueError("Invalid points format.")


def _point_as_list(point) -> list[float]:
    x, y = _point_xy(point)
    return [round(float(x), 6), round(float(y), 6)]


def _row_to_machine(row) -> Machine:
    points_data = json.loads(row["points"])
    points = [ZonePoint(x=float(point[0]), y=float(point[1])) for point in points_data]
    _validate_points(points)
    return Machine(
        id=row["id"],
        camera_id=row["camera_id"],
        name=row["name"],
        type=row["type"],
        enabled=bool(row["enabled"]),
        points=points,
        requires_operator=bool(row["requires_operator"]),
        allow_idle=bool(row["allow_idle"]),
        min_person_distance=float(row["min_person_distance"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
