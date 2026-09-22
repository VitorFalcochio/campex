from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


ALERT_TYPES = {
    "camera_offline",
    "camera_online",
    "zone_idle",
    "zone_activity_resumed",
    "crowding_started",
    "crowding_ended",
    "long_presence",
}

REPORT_FREQUENCIES = {"DAILY", "WEEKLY", "MONTHLY"}


@dataclass(frozen=True)
class NotificationPreference:
    id: str
    organization_id: str
    enabled: bool = True
    telegram_enabled: bool = False
    telegram_chat_id: str | None = None
    email_enabled: bool = False
    email_recipients: list[str] = field(default_factory=list)
    reports_enabled: bool = False
    report_frequency: str = "DAILY"
    report_time: str = "18:00"
    report_weekday: int = 4
    report_month_day: int = 0
    timezone: str = "America/Sao_Paulo"
    immediate_alerts_enabled: bool = True
    alert_types: list[str] = field(default_factory=lambda: sorted(ALERT_TYPES))

    def as_dict(self, *, telegram_configured: bool = False, email_configured: bool = False) -> dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "enabled": self.enabled,
            "telegram_enabled": self.telegram_enabled,
            "telegram_chat_id": self.telegram_chat_id,
            "telegram_configured": telegram_configured,
            "email_enabled": self.email_enabled,
            "email_recipients": self.email_recipients,
            "email_configured": email_configured,
            "reports_enabled": self.reports_enabled,
            "report_frequency": self.report_frequency,
            "report_time": self.report_time,
            "report_weekday": self.report_weekday,
            "report_month_day": self.report_month_day,
            "timezone": self.timezone,
            "immediate_alerts_enabled": self.immediate_alerts_enabled,
            "alert_types": self.alert_types,
        }


@dataclass(frozen=True)
class DeliveryResult:
    channel: str
    status: str
    delivery_id: str | None = None
    recipient: str | None = None
    message_id: str | None = None
    attempts: int = 0
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "status": self.status,
            "delivery_id": self.delivery_id,
            "recipient": self.recipient,
            "message_id": self.message_id,
            "attempts": self.attempts,
            "error": self.error,
        }
