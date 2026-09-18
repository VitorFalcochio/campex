from __future__ import annotations

from uuid import uuid4

from backend.config import Settings
from backend.database.db import connect
from backend.events.models import EventRule


DEFAULT_RULE_DATA = [
    ("restricted_zone_entry", "person_entered_zone", "restricted", "PERSON_RESTRICTED_ZONE", "critical", 0.0, 10.0),
    ("restricted_zone_exit", "person_exited_zone", "restricted", "PERSON_RESTRICTED_ZONE", "critical", 0.0, 10.0),
    ("restricted_zone_dwell", "person_presence", "restricted", "PERSON_RESTRICTED_ZONE_DWELL", "critical", 5.0, 60.0),
    ("monitored_zone_entry", "person_entered_zone", "monitored", "PERSON_MONITORED_ZONE", "attention", 0.0, 30.0),
    ("monitored_zone_exit", "person_exited_zone", "monitored", "PERSON_MONITORED_ZONE", "attention", 0.0, 30.0),
]


class RuleRepository:
    def __init__(self, settings: Settings) -> None:
        self.database_path = settings.sqlite_path

    def ensure_defaults(self) -> None:
        with connect(self.database_path) as connection:
            count = connection.execute("SELECT COUNT(*) FROM visual_rules").fetchone()[0]
            if count:
                return
            for name, observation, zone_type, event_type, severity, duration, cooldown in DEFAULT_RULE_DATA:
                connection.execute(
                    """
                    INSERT INTO visual_rules (
                        id, name, observation_type, zone_type, event_type,
                        severity, duration_threshold_seconds, cooldown_seconds, enabled
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        f"rule_{uuid4().hex[:12]}",
                        name,
                        observation,
                        zone_type,
                        event_type,
                        severity,
                        duration,
                        cooldown,
                    ),
                )
            connection.commit()

    def list(self, enabled_only: bool = False, organization_id: str | None = None) -> list[EventRule]:
        self.ensure_defaults()
        where = "WHERE enabled = 1" if enabled_only else "WHERE 1=1"
        conditions = [where]
        params: list = []
        if organization_id is not None:
            conditions.append("organization_id = ?")
            params.append(organization_id)
        where_clause = " AND ".join(conditions)
        with connect(self.database_path) as connection:
            rows = connection.execute(
                f"SELECT * FROM visual_rules {where_clause} ORDER BY created_at ASC",
                params,
            ).fetchall()
        return [_row_to_rule(row) for row in rows]

    def list_dicts(self, organization_id: str | None = None) -> list[dict]:
        self.ensure_defaults()
        if organization_id is not None:
            query = "SELECT * FROM visual_rules WHERE organization_id = ? ORDER BY created_at ASC"
            params: list = [organization_id]
        else:
            query = "SELECT * FROM visual_rules ORDER BY created_at ASC"
            params = []
        with connect(self.database_path) as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) | {"enabled": bool(row["enabled"])} for row in rows]

    def create(self, payload: dict, organization_id: str | None = None) -> dict:
        rule_id = f"rule_{uuid4().hex[:12]}"
        columns = [
            "id", "name", "camera_id", "zone_id", "observation_type", "zone_type",
            "event_type", "severity", "duration_threshold_seconds",
            "cooldown_seconds", "enabled",
        ]
        values: list = [
            rule_id,
            payload["name"],
            payload.get("camera_id") or None,
            payload.get("zone_id") or None,
            payload["observation_type"],
            payload.get("zone_type") or None,
            payload["event_type"],
            payload["severity"],
            float(payload.get("duration_threshold_seconds") or 0),
            float(payload.get("cooldown_seconds") or 10),
            int(payload.get("enabled", True)),
        ]
        if organization_id is not None:
            columns.append("organization_id")
            values.append(organization_id)
        with connect(self.database_path) as connection:
            connection.execute(
                f"""
                INSERT INTO visual_rules ({", ".join(columns)})
                VALUES ({", ".join(["?"] * len(values))})
                """,
                values,
            )
            connection.commit()
        return self.get(rule_id)

    def get(self, rule_id: str, organization_id: str | None = None) -> dict:
        with connect(self.database_path) as connection:
            if organization_id is not None:
                row = connection.execute(
                    "SELECT * FROM visual_rules WHERE id = ? AND organization_id = ?",
                    (rule_id, organization_id),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT * FROM visual_rules WHERE id = ?", (rule_id,)
                ).fetchone()
        if row is None:
            raise KeyError(rule_id)
        return dict(row) | {"enabled": bool(row["enabled"])}

    def update(self, rule_id: str, updates: dict, organization_id: str | None = None) -> dict:
        allowed = {
            "name", "camera_id", "zone_id", "observation_type", "zone_type",
            "event_type", "severity", "duration_threshold_seconds",
            "cooldown_seconds", "enabled",
        }
        fields = [key for key in updates if key in allowed]
        if not fields:
            return self.get(rule_id, organization_id=organization_id)
        values = [int(updates[key]) if key == "enabled" else updates[key] for key in fields]
        assignments = ", ".join(f"{key} = ?" for key in fields)
        with connect(self.database_path) as connection:
            cursor = connection.execute(
                f"UPDATE visual_rules SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (*values, rule_id),
            )
            connection.commit()
        if cursor.rowcount == 0:
            raise KeyError(rule_id)
        return self.get(rule_id, organization_id=organization_id)

    def delete(self, rule_id: str, organization_id: str | None = None) -> bool:
        with connect(self.database_path) as connection:
            if organization_id is not None:
                cursor = connection.execute(
                    "DELETE FROM visual_rules WHERE id = ? AND organization_id = ?",
                    (rule_id, organization_id),
                )
            else:
                cursor = connection.execute("DELETE FROM visual_rules WHERE id = ?", (rule_id,))
            connection.commit()
            return cursor.rowcount > 0


def _row_to_rule(row) -> EventRule:
    return EventRule(
        id=row["id"],
        name=row["name"],
        camera_id=row["camera_id"],
        zone_id=row["zone_id"],
        observation_type=row["observation_type"],
        zone_type=row["zone_type"],
        event_type=row["event_type"],
        severity=row["severity"],
        duration_threshold_seconds=float(row["duration_threshold_seconds"] or 0),
        cooldown_seconds=float(row["cooldown_seconds"] or 10),
        enabled=bool(row["enabled"]),
    )
