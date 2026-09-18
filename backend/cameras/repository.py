from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from backend.cameras.models import Camera
from backend.config import Settings
from backend.database.db import connect


def _row_to_camera(row) -> Camera:
    return Camera(
        id=row["id"],
        name=row["name"],
        area_id=row["area_id"],
        source_type=row["source_type"],
        source_uri=row["source_uri"],
        enabled=bool(row["enabled"]),
        vision_enabled=bool(row["vision_enabled"]),
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class CameraRepository:
    def __init__(self, settings: Settings) -> None:
        self.database_path: Path = settings.sqlite_path

    def list(self, organization_id: str | None = None) -> list[Camera]:
        with connect(self.database_path) as connection:
            if organization_id is not None:
                rows = connection.execute(
                    "SELECT * FROM cameras WHERE organization_id = ? ORDER BY created_at DESC",
                    (organization_id,),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM cameras ORDER BY created_at DESC"
                ).fetchall()
        return [_row_to_camera(row) for row in rows]

    def get(self, camera_id: str, organization_id: str | None = None) -> Camera | None:
        with connect(self.database_path) as connection:
            if organization_id is not None:
                row = connection.execute(
                    "SELECT * FROM cameras WHERE id = ? AND organization_id = ?",
                    (camera_id, organization_id),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT * FROM cameras WHERE id = ?", (camera_id,)
                ).fetchone()
        return _row_to_camera(row) if row else None

    def create(
        self,
        *,
        name: str,
        area_id: str | None,
        source_type: str,
        source_uri: str,
        enabled: bool,
        vision_enabled: bool,
        organization_id: str | None = None,
    ) -> Camera:
        camera_id = f"cam_{uuid4().hex[:12]}"
        columns = [
            "id", "name", "area_id", "source_type", "source_uri",
            "enabled", "vision_enabled", "status",
        ]
        placeholders = [
            "?", "?", "?", "?", "?",
            "?", "?", "'OFFLINE'",
        ]
        params: list = [
            camera_id, name, area_id, source_type, source_uri,
            int(enabled), int(vision_enabled),
        ]
        if organization_id is not None:
            columns.append("organization_id")
            placeholders.append("?")
            params.append(organization_id)
        with connect(self.database_path) as connection:
            connection.execute(
                f"""
                INSERT INTO cameras ({", ".join(columns)})
                VALUES ({", ".join(placeholders)})
                """,
                params,
            )
            connection.commit()
        camera = self.get(camera_id, organization_id=organization_id)
        if camera is None:
            raise RuntimeError("Camera was not persisted.")
        return camera

    def update(self, camera_id: str, updates: dict) -> Camera | None:
        allowed = {
            "name",
            "area_id",
            "source_type",
            "source_uri",
            "enabled",
            "vision_enabled",
            "status",
        }
        fields = [key for key in updates if key in allowed]
        if not fields:
            return self.get(camera_id)

        values = [
            int(updates[field])
            if field in {"enabled", "vision_enabled"}
            else updates[field]
            for field in fields
        ]
        assignments = ", ".join(f"{field} = ?" for field in fields)
        with connect(self.database_path) as connection:
            connection.execute(
                f"""
                UPDATE cameras
                SET {assignments}, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (*values, camera_id),
            )
            connection.commit()
        return self.get(camera_id)

    def update_runtime_state(self, camera_id: str, health: dict) -> None:
        with connect(self.database_path) as connection:
            connection.execute(
                """
                UPDATE cameras
                SET
                    status = ?,
                    last_frame_at = ?,
                    last_connected_at = ?,
                    last_disconnected_at = ?,
                    connection_state = ?,
                    consecutive_failures = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    health.get("status", "OFFLINE"),
                    health.get("last_frame_at"),
                    health.get("last_connected_at"),
                    health.get("last_disconnected_at"),
                    health.get("connection_state", health.get("status", "OFFLINE")),
                    int(health.get("consecutive_failures") or 0),
                    camera_id,
                ),
            )
            connection.commit()

    def delete(self, camera_id: str, organization_id: str | None = None) -> bool:
        with connect(self.database_path) as connection:
            if organization_id is not None:
                cursor = connection.execute(
                    "DELETE FROM cameras WHERE id = ? AND organization_id = ?",
                    (camera_id, organization_id),
                )
            else:
                cursor = connection.execute("DELETE FROM cameras WHERE id = ?", (camera_id,))
            connection.commit()
            return cursor.rowcount > 0
