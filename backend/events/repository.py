from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from uuid import uuid4

from backend.config import Settings
from backend.database.db import connect
from backend.events.models import Event, normalize_event_metadata


logger = logging.getLogger("campex.events.repository")


class EventRepository:
    def __init__(self, settings: Settings) -> None:
        self.database_path = settings.sqlite_path

    @classmethod
    def for_settings(cls, settings: Settings) -> "EventRepository":
        return cls(settings)

    def list(
        self,
        status: str | None = None,
        camera_id: str | None = None,
        event_type: str | None = None,
        limit: int = 200,
        organization_id: str | None = None,
    ) -> list[Event]:
        conditions: list[str] = []
        params: list = []
        if organization_id is not None:
            conditions.append("organization_id = ?")
            params.append(organization_id)
        if status:
            conditions.append("status = ?")
            params.append(status)
        if camera_id:
            conditions.append("camera_id = ?")
            params.append(camera_id)
        if event_type:
            conditions.append("type = ?")
            params.append(event_type)

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
        query = (
            f"SELECT * FROM events {where_clause} "
            f"ORDER BY started_at DESC LIMIT ?"
        )
        params.append(limit)

        with connect(self.database_path) as connection:
            rows = connection.execute(query, params).fetchall()
        events: list[Event] = []
        for row in rows:
            try:
                events.append(_row_to_event(row))
            except (json.JSONDecodeError, TypeError, ValueError):
                logger.exception(
                    "Ignoring malformed event record",
                    extra={"event_id": row["id"]},
                )
        return events

    def get(self, event_id: str, organization_id: str | None = None) -> Event | None:
        with connect(self.database_path) as connection:
            if organization_id is not None:
                row = connection.execute(
                    "SELECT * FROM events WHERE id = ? AND organization_id = ?",
                    (event_id, organization_id),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT * FROM events WHERE id = ?", (event_id,)
                ).fetchone()
        if row is None:
            return None
        try:
            return _row_to_event(row)
        except (json.JSONDecodeError, TypeError, ValueError):
            logger.exception(
                "Malformed event record",
                extra={"event_id": event_id},
            )
            return None

    def create(
        self,
        *,
        event_type: str,
        camera_id: str,
        zone_id: str | None = None,
        track_id: int | None = None,
        severity: str = "info",
        status: str = "OPEN",
        confidence: float | None = None,
        metadata: dict | None = None,
        started_at: str | None = None,
        ended_at: str | None = None,
        duration: float | None = None,
        organization_id: str | None = None,
    ) -> Event:
        event_id = f"evt_{uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()
        event_started_at = started_at or now
        event_status = "CLOSED" if ended_at is not None and status == "OPEN" else status
        event_duration = duration
        if event_duration is None and ended_at is not None:
            event_duration = _duration_seconds(event_started_at, ended_at)
        normalized_metadata = normalize_event_metadata(
            event_type=event_type,
            camera_id=camera_id,
            zone_id=zone_id,
            track_id=track_id,
            started_at=event_started_at,
            ended_at=ended_at,
            duration=event_duration,
            metadata=metadata,
        )

        columns = [
            "id", "type", "camera_id", "zone_id", "track_id", "severity",
            "status", "confidence", "started_at", "ended_at", "duration",
            "metadata", "created_at", "updated_at",
        ]
        placeholders = [
            "?", "?", "?", "?", "?", "?",
            "?", "?", "?", "?", "?",
            "?", "?", "?",
        ]
        params: list = [
            event_id, event_type, camera_id, zone_id, track_id,
            severity, event_status, confidence, event_started_at,
            ended_at, event_duration, json.dumps(normalized_metadata), now, now,
        ]
        if organization_id is not None:
            columns.append("organization_id")
            placeholders.append("?")
            params.append(organization_id)
        with connect(self.database_path) as connection:
            connection.execute(
                f"""
                INSERT INTO events ({", ".join(columns)})
                VALUES ({", ".join(placeholders)})
                """,
                params,
            )
            connection.commit()
        return self.get(event_id, organization_id=organization_id)  # type: ignore[return-value]

    def update_status(
        self,
        event_id: str,
        status: str,
        ended_at: str | None = None,
        duration: float | None = None,
        metadata_update: dict | None = None,
    ) -> Event | None:
        fields = ["status = ?"]
        values: list = [status]
        if ended_at:
            fields.append("ended_at = ?")
            values.append(ended_at)
            if duration is None:
                existing = self.get(event_id)
                if existing is not None:
                    duration = _duration_seconds(existing.started_at, ended_at)
        if duration is not None:
            fields.append("duration = ?")
            values.append(duration)
        if metadata_update or ended_at or duration is not None:
            with connect(self.database_path) as connection:
                existing = connection.execute(
                    "SELECT * FROM events WHERE id = ?", (event_id,)
                ).fetchone()
                if existing:
                    current_meta = json.loads(existing["metadata"]) if existing["metadata"] else {}
                    current_meta.update(metadata_update or {})
                    next_ended_at = ended_at or existing["ended_at"]
                    next_duration = duration if duration is not None else existing["duration"]
                    current_meta = normalize_event_metadata(
                        event_type=existing["type"],
                        camera_id=existing["camera_id"],
                        zone_id=existing["zone_id"],
                        track_id=existing["track_id"],
                        started_at=existing["started_at"],
                        ended_at=next_ended_at,
                        duration=next_duration,
                        metadata=current_meta,
                    )
                    fields.append("metadata = ?")
                    values.append(json.dumps(current_meta))

        fields.append("updated_at = CURRENT_TIMESTAMP")
        # event_id is the WHERE parameter, not part of SET values

        with connect(self.database_path) as connection:
            connection.execute(
                f"UPDATE events SET {', '.join(fields)} WHERE id = ?",
                (*values, event_id),
            )
            connection.commit()
        return self.get(event_id)

    def close(
        self,
        event_id: str,
        ended_at: str | None = None,
        duration: float | None = None,
    ) -> Event | None:
        return self.update_status(event_id, "CLOSED", ended_at, duration)

    def mark_reviewed(self, event_id: str) -> Event | None:
        return self.update_status(event_id, "REVIEWED")

    def delete(self, event_id: str, organization_id: str | None = None) -> bool:
        with connect(self.database_path) as connection:
            if organization_id is not None:
                cursor = connection.execute(
                    "DELETE FROM events WHERE id = ? AND organization_id = ?",
                    (event_id, organization_id),
                )
            else:
                cursor = connection.execute("DELETE FROM events WHERE id = ?", (event_id,))
            connection.commit()
            return cursor.rowcount > 0


def _row_to_event(row) -> Event:
    metadata = json.loads(row["metadata"]) if row["metadata"] else {}
    if not isinstance(metadata, dict):
        raise ValueError("Event metadata must be a JSON object.")
    metadata = normalize_event_metadata(
        event_type=row["type"],
        camera_id=row["camera_id"],
        zone_id=row["zone_id"],
        track_id=row["track_id"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        duration=row["duration"],
        metadata=metadata,
    )
    return Event(
        id=row["id"],
        type=row["type"],
        camera_id=row["camera_id"],
        zone_id=row["zone_id"],
        track_id=row["track_id"],
        severity=row["severity"],
        status=row["status"],
        confidence=row["confidence"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        duration=row["duration"],
        metadata=metadata,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _duration_seconds(started_at: str, ended_at: str) -> float | None:
    try:
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        ended = datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0.0, (ended - started).total_seconds())
