from __future__ import annotations

import json
import logging
from pathlib import Path
from uuid import uuid4

from backend.config import Settings
from backend.database.db import connect
from backend.zones.models import Zone, ZonePoint


logger = logging.getLogger("campex.zones.repository")


class ZoneRepository:
    def __init__(self, settings: Settings | None = None) -> None:
        self.database_path = settings.sqlite_path if settings else None

    @classmethod
    def for_settings(cls, settings: Settings) -> "ZoneRepository":
        return cls(settings)

    def list(self, camera_id: str | None = None, organization_id: str | None = None) -> list[Zone]:
        with connect(self._db_path) as connection:
            if organization_id is not None and camera_id is not None:
                rows = connection.execute(
                    "SELECT * FROM zones WHERE organization_id = ? AND camera_id = ? ORDER BY created_at ASC",
                    (organization_id, camera_id),
                ).fetchall()
            elif organization_id is not None:
                rows = connection.execute(
                    "SELECT * FROM zones WHERE organization_id = ? ORDER BY created_at ASC",
                    (organization_id,),
                ).fetchall()
            elif camera_id:
                rows = connection.execute(
                    "SELECT * FROM zones WHERE camera_id = ? ORDER BY created_at ASC",
                    (camera_id,),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM zones ORDER BY created_at ASC"
                ).fetchall()
        zones: list[Zone] = []
        for row in rows:
            try:
                zones.append(_row_to_zone(row))
            except (json.JSONDecodeError, TypeError, ValueError, KeyError, IndexError):
                logger.exception(
                    "Ignoring malformed zone record",
                    extra={"zone_id": row["id"]},
                )
        return zones

    def get(self, zone_id: str, organization_id: str | None = None) -> Zone | None:
        with connect(self._db_path) as connection:
            if organization_id is not None:
                row = connection.execute(
                    "SELECT * FROM zones WHERE id = ? AND organization_id = ?",
                    (zone_id, organization_id),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT * FROM zones WHERE id = ?", (zone_id,)
                ).fetchone()
        if row is None:
            return None
        try:
            return _row_to_zone(row)
        except (json.JSONDecodeError, TypeError, ValueError, KeyError, IndexError):
            logger.exception(
                "Malformed zone record",
                extra={"zone_id": zone_id},
            )
            return None

    def create(
        self,
        *,
        camera_id: str,
        name: str,
        zone_type: str,
        points: list[ZonePoint],
        enabled: bool = True,
        organization_id: str | None = None,
    ) -> Zone:
        if zone_type not in ("monitored", "restricted"):
            raise ValueError("Zone type must be 'monitored' or 'restricted'.")
        _validate_points(points)

        zone_id = f"zone_{uuid4().hex[:12]}"
        points_json = json.dumps([p.as_list() for p in points])

        columns = ["id", "camera_id", "name", "type", "enabled", "points"]
        values: list = [zone_id, camera_id, name, zone_type, int(enabled), points_json]
        if organization_id is not None:
            columns.append("organization_id")
            values.append(organization_id)
        with connect(self._db_path) as connection:
            connection.execute(
                f"""
                INSERT INTO zones ({", ".join(columns)})
                VALUES ({", ".join(["?"] * len(values))})
                """,
                values,
            )
            connection.commit()
        return self.get(zone_id, organization_id=organization_id)  # type: ignore[return-value]

    def update(self, zone_id: str, updates: dict, organization_id: str | None = None) -> Zone | None:
        allowed = {"name", "type", "enabled", "points"}
        fields = [key for key in updates if key in allowed]
        if not fields:
            return self.get(zone_id)

        values: list = []
        for field_name in fields:
            if field_name == "enabled":
                values.append(int(updates[field_name]))
            elif field_name == "points":
                points = updates[field_name]
                _validate_points(points)
                if isinstance(points[0], ZonePoint):
                    values.append(json.dumps([p.as_list() for p in points]))
                elif isinstance(points[0], (list, tuple)):
                    values.append(
                        json.dumps(
                            [
                                [round(p[0], 6), round(p[1], 6)]
                                for p in points
                            ]
                        )
                    )
                else:
                    raise ValueError("Invalid points format.")
            elif field_name == "type":
                if updates[field_name] not in ("monitored", "restricted"):
                    raise ValueError(
                        "Zone type must be 'monitored' or 'restricted'."
                    )
                values.append(updates[field_name])
            else:
                values.append(updates[field_name])

        assignments = ", ".join(f"{f} = ?" for f in fields)
        with connect(self._db_path) as connection:
            connection.execute(
                f"UPDATE zones SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (*values, zone_id),
            )
            connection.commit()
        return self.get(zone_id, organization_id=organization_id)  # type: ignore[return-value]

    def delete(self, zone_id: str, organization_id: str | None = None) -> bool:
        with connect(self._db_path) as connection:
            if organization_id is not None:
                cursor = connection.execute(
                    "DELETE FROM zones WHERE id = ? AND organization_id = ?",
                    (zone_id, organization_id),
                )
            else:
                cursor = connection.execute("DELETE FROM zones WHERE id = ?", (zone_id,))
            connection.commit()
            return cursor.rowcount > 0

    @property
    def _db_path(self) -> Path:
        """Resolve database path from settings."""
        if self.database_path is None:
            raise RuntimeError("ZoneRepository requires database settings.")
        return self.database_path


def _validate_points(points: list) -> None:
    if len(points) < 3:
        raise ValueError("Zone polygon must have at least 3 points.")
    for point in points:
        if isinstance(point, ZonePoint):
            x, y = point.x, point.y
        elif isinstance(point, (list, tuple)) and len(point) == 2:
            x, y = point
        else:
            raise ValueError("Invalid points format.")
        if not 0.0 <= float(x) <= 1.0 or not 0.0 <= float(y) <= 1.0:
            raise ValueError("Zone coordinates must be normalized between 0 and 1.")


def _row_to_zone(row) -> Zone:
    points_data = json.loads(row["points"])
    points = [ZonePoint(x=float(p[0]), y=float(p[1])) for p in points_data]
    _validate_points(points)
    return Zone(
        id=row["id"],
        camera_id=row["camera_id"],
        name=row["name"],
        type=row["type"],
        enabled=bool(row["enabled"]),
        points=points,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
