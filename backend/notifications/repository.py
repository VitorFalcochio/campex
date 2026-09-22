from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from backend.config import Settings
from backend.database.db import connect
from backend.notifications.models import ALERT_TYPES, NotificationPreference


class NotificationRepository:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def get_or_create_preference(self, organization_id: str) -> NotificationPreference:
        existing = self.get_preference(organization_id)
        if existing:
            return existing
        preference = NotificationPreference(
            id=f"pref_{uuid4().hex[:12]}",
            organization_id=organization_id,
        )
        self.save_preference(preference.as_dict())
        return self.get_preference(organization_id) or preference

    def get_preference(self, organization_id: str) -> NotificationPreference | None:
        with connect(self.settings.sqlite_path) as connection:
            row = connection.execute(
                "SELECT * FROM notification_preferences WHERE organization_id = ?",
                (organization_id,),
            ).fetchone()
        return _preference_from_row(row) if row else None

    def save_preference(self, payload: dict[str, Any]) -> NotificationPreference:
        organization_id = payload["organization_id"]
        existing = self.get_preference(organization_id)
        preference_id = existing.id if existing else payload.get("id") or f"pref_{uuid4().hex[:12]}"
        email_recipients = payload.get("email_recipients") or []
        alert_types = payload.get("alert_types") or sorted(ALERT_TYPES)
        values = {
            "id": preference_id,
            "organization_id": organization_id,
            "enabled": bool(payload.get("enabled", True)),
            "telegram_enabled": bool(payload.get("telegram_enabled", False)),
            "telegram_chat_id": payload.get("telegram_chat_id") or None,
            "email_enabled": bool(payload.get("email_enabled", False)),
            "email_recipients": json.dumps(email_recipients, ensure_ascii=False),
            "reports_enabled": bool(payload.get("reports_enabled", False)),
            "report_frequency": payload.get("report_frequency", "DAILY"),
            "report_time": payload.get("report_time", "18:00"),
            "report_weekday": int(payload.get("report_weekday", 4)),
            "report_month_day": int(payload.get("report_month_day", 0)),
            "timezone": payload.get("timezone", "America/Sao_Paulo"),
            "immediate_alerts_enabled": bool(payload.get("immediate_alerts_enabled", True)),
            "alert_types": json.dumps(alert_types, ensure_ascii=False),
        }
        with connect(self.settings.sqlite_path) as connection:
            connection.execute(
                """
                INSERT INTO notification_preferences (
                    id, organization_id, enabled, telegram_enabled, telegram_chat_id,
                    email_enabled, email_recipients, reports_enabled, report_frequency,
                    report_time, report_weekday, report_month_day, timezone,
                    immediate_alerts_enabled, alert_types
                )
                VALUES (
                    :id, :organization_id, :enabled, :telegram_enabled, :telegram_chat_id,
                    :email_enabled, :email_recipients, :reports_enabled, :report_frequency,
                    :report_time, :report_weekday, :report_month_day, :timezone,
                    :immediate_alerts_enabled, :alert_types
                )
                ON CONFLICT(organization_id) DO UPDATE SET
                    enabled = excluded.enabled,
                    telegram_enabled = excluded.telegram_enabled,
                    telegram_chat_id = excluded.telegram_chat_id,
                    email_enabled = excluded.email_enabled,
                    email_recipients = excluded.email_recipients,
                    reports_enabled = excluded.reports_enabled,
                    report_frequency = excluded.report_frequency,
                    report_time = excluded.report_time,
                    report_weekday = excluded.report_weekday,
                    report_month_day = excluded.report_month_day,
                    timezone = excluded.timezone,
                    immediate_alerts_enabled = excluded.immediate_alerts_enabled,
                    alert_types = excluded.alert_types,
                    updated_at = CURRENT_TIMESTAMP
                """,
                values,
            )
            connection.commit()
        return self.get_preference(organization_id)  # type: ignore[return-value]

    def create_delivery(
        self,
        *,
        organization_id: str,
        channel: str,
        delivery_type: str,
        reference_id: str,
        recipient: str,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[str, bool]:
        delivery_id = f"del_{uuid4().hex[:12]}"
        with connect(self.settings.sqlite_path) as connection:
            existing = connection.execute(
                """
                SELECT id FROM notification_deliveries
                WHERE organization_id = ? AND channel = ? AND type = ?
                  AND reference_id = ? AND recipient = ?
                """,
                (organization_id, channel, delivery_type, reference_id, recipient),
            ).fetchone()
            if existing:
                return existing["id"], False
            connection.execute(
                """
                INSERT INTO notification_deliveries (
                    id, organization_id, channel, type, reference_id, recipient,
                    status, attempts, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, ?)
                """,
                (
                    delivery_id,
                    organization_id,
                    channel,
                    delivery_type,
                    reference_id,
                    recipient,
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
            connection.commit()
        return delivery_id, True

    def update_delivery(
        self,
        delivery_id: str,
        *,
        status: str,
        attempts: int,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        sent_at = _now() if status == "sent" else None
        with connect(self.settings.sqlite_path) as connection:
            connection.execute(
                """
                UPDATE notification_deliveries
                SET status = ?, attempts = ?, error = ?, sent_at = COALESCE(?, sent_at),
                    metadata = COALESCE(?, metadata), updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    status,
                    attempts,
                    error,
                    sent_at,
                    json.dumps(metadata, ensure_ascii=False) if metadata is not None else None,
                    delivery_id,
                ),
            )
            connection.commit()

    def list_deliveries(self, organization_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with connect(self.settings.sqlite_path) as connection:
            rows = connection.execute(
                """
                SELECT * FROM notification_deliveries
                WHERE organization_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (organization_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]


def _preference_from_row(row) -> NotificationPreference:
    return NotificationPreference(
        id=row["id"],
        organization_id=row["organization_id"],
        enabled=bool(row["enabled"]),
        telegram_enabled=bool(row["telegram_enabled"]),
        telegram_chat_id=row["telegram_chat_id"],
        email_enabled=bool(row["email_enabled"]),
        email_recipients=_decode_list(row["email_recipients"]),
        reports_enabled=bool(row["reports_enabled"]),
        report_frequency=row["report_frequency"],
        report_time=row["report_time"],
        report_weekday=int(row["report_weekday"]),
        report_month_day=int(row["report_month_day"]),
        timezone=row["timezone"],
        immediate_alerts_enabled=bool(row["immediate_alerts_enabled"]),
        alert_types=_decode_list(row["alert_types"]) or sorted(ALERT_TYPES),
    )


def _decode_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in decoded if str(item).strip()]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
