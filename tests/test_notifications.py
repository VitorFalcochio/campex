from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.config import Settings
from backend.database.db import connect, initialize_database
from backend.main import app
from backend.notifications.service import NotificationService


class FakeTelegram:
    configured = True

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.sent = []

    def send_message(self, chat_id, message):
        if self.fail:
            raise RuntimeError("telegram timeout")
        self.sent.append((chat_id, message))
        return {"status": "sent", "message_id": "42"}

    def test_connection(self):
        return {"status": "ok"}


class FakeEmail:
    configured = True

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.sent = []

    def send_email(self, *, recipients, subject, text, html=None):
        if self.fail:
            raise RuntimeError("smtp authentication failed")
        self.sent.append((recipients, subject, text, html))
        return {"status": "sent", "recipients": recipients}

    def test_connection(self):
        return {"status": "ok"}


def test_notification_preferences_api(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)

    with TestClient(app) as client:
        payload = client.get("/api/v1/notifications/preferences").json()
        assert payload["telegram_configured"] is False

        updated = client.put(
            "/api/v1/notifications/preferences",
            json={
                "telegram_enabled": True,
                "telegram_chat_id": "123",
                "email_enabled": True,
                "email_recipients": ["gestor@example.com"],
                "reports_enabled": True,
                "report_frequency": "DAILY",
                "report_time": "18:00",
                "timezone": "America/Sao_Paulo",
                "immediate_alerts_enabled": True,
                "alert_types": ["camera_offline"],
            },
        )

    assert updated.status_code == 200
    body = updated.json()
    assert body["telegram_chat_id"] == "123"
    assert body["email_recipients"] == ["gestor@example.com"]


def test_notification_service_two_channels_and_idempotency(tmp_path):
    settings = _settings(tmp_path / "notifications.sqlite3")
    initialize_database(settings)
    _seed_completed_video(settings)
    telegram = FakeTelegram()
    email = FakeEmail()
    service = NotificationService(settings, telegram_client=telegram, email_client=email)
    service.update_preferences(
        "default",
        {
            "telegram_enabled": True,
            "telegram_chat_id": "chat-1",
            "email_enabled": True,
            "email_recipients": ["gestor@example.com"],
            "reports_enabled": True,
            "alert_types": ["camera_offline"],
        },
    )

    first = service.send_report_now("default")
    second = service.send_report_now("default")

    assert first["channels"]["telegram"][0]["status"] == "sent"
    assert first["channels"]["email"]["status"] == "sent"
    assert second["channels"]["telegram"][0]["status"] == "skipped"
    assert second["channels"]["email"]["status"] == "skipped"
    assert len(telegram.sent) == 1
    assert len(email.sent) == 1


def test_notification_service_channel_failures_are_isolated(tmp_path):
    settings = _settings(tmp_path / "notification-failures.sqlite3")
    initialize_database(settings)
    _seed_completed_video(settings)
    service = NotificationService(
        settings,
        telegram_client=FakeTelegram(fail=True),
        email_client=FakeEmail(),
    )
    service.update_preferences(
        "default",
        {
            "telegram_enabled": True,
            "telegram_chat_id": "chat-1",
            "email_enabled": True,
            "email_recipients": ["gestor@example.com"],
            "reports_enabled": True,
        },
    )

    result = service.send_report_now("default")

    assert result["channels"]["telegram"][0]["status"] == "failed"
    assert result["channels"]["telegram"][0]["attempts"] == 3
    assert result["channels"]["email"]["status"] == "sent"


def test_alert_cooldown_idempotency(tmp_path):
    settings = _settings(tmp_path / "notification-alerts.sqlite3")
    initialize_database(settings)
    telegram = FakeTelegram()
    service = NotificationService(settings, telegram_client=telegram, email_client=FakeEmail())
    service.update_preferences(
        "default",
        {
            "telegram_enabled": True,
            "telegram_chat_id": "chat-1",
            "immediate_alerts_enabled": True,
            "alert_types": ["camera_offline"],
        },
    )
    event = {"id": "evt_1", "event_type": "camera_offline", "camera_id": "cam_1"}

    first = service.send_alert("default", event)
    second = service.send_alert("default", event)

    assert first["channels"]["telegram"][0]["status"] == "sent"
    assert second["channels"]["telegram"][0]["status"] == "skipped"
    assert len(telegram.sent) == 1


def test_telegram_multiple_recipients(tmp_path):
    settings = _settings(tmp_path / "notification-multiple-telegram.sqlite3")
    initialize_database(settings)
    telegram = FakeTelegram()
    service = NotificationService(settings, telegram_client=telegram, email_client=FakeEmail())
    service.update_preferences(
        "default",
        {
            "telegram_enabled": True,
            "telegram_chat_id": "chat-1, chat-2",
            "immediate_alerts_enabled": True,
            "alert_types": ["camera_offline"],
        },
    )

    result = service.send_alert(
        "default",
        {"id": "evt_multi", "event_type": "camera_offline", "camera_id": "cam_1"},
    )

    assert [item["status"] for item in result["channels"]["telegram"]] == ["sent", "sent"]
    assert [item[0] for item in telegram.sent] == ["chat-1", "chat-2"]


def test_preferences_disabled_skip_notifications(tmp_path):
    settings = _settings(tmp_path / "notification-disabled.sqlite3")
    initialize_database(settings)
    _seed_completed_video(settings)
    service = NotificationService(settings, telegram_client=FakeTelegram(), email_client=FakeEmail())
    service.update_preferences(
        "default",
        {"enabled": False, "telegram_enabled": True, "telegram_chat_id": "chat-1"},
    )

    result = service.send_report_now("default")

    assert result["status"] == "skipped"


def _configure(monkeypatch, tmp_path: Path) -> Settings:
    settings = _settings(tmp_path / "notifications-api.sqlite3")
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    initialize_database(Settings.from_env())
    return settings


def _settings(database_path: Path) -> Settings:
    return Settings(
        environment="test",
        service_name="campex",
        version="0.1.0",
        log_level="INFO",
        database_url=f"sqlite:///{database_path}",
        frontend_origins=["*"],
        camera_reconnect_seconds=5,
        camera_stale_seconds=10,
        camera_offline_seconds=30,
        camera_read_failure_limit=3,
        camera_test_timeout_seconds=5,
        vision_enabled=True,
        vision_detector="yolo",
        vision_model="yolo11n.pt",
        vision_device="auto",
        vision_fps=5,
        vision_confidence=0.35,
        vision_video_loop=False,
    )


def _seed_completed_video(settings: Settings) -> None:
    metrics = {
        "people": {"detected": 30, "entries": 30, "exits": 30, "max_simultaneous": 15},
        "activity": {"moving_seconds": 152.8, "stationary_seconds": 0, "stationary_events": 0},
        "summary": {"unique_people": 30, "total_events": 118, "max_simultaneous": 15},
    }
    insight = {"summary": "Relatorio operacional validado pelo Nemotron.", "sections": {"flow": "30 entradas."}}
    with connect(settings.sqlite_path) as connection:
        connection.execute(
            """
            INSERT INTO video_analyses (
                id, organization_id, original_filename, stored_filename, storage_path,
                content_type, file_size, status, progress, source_json, metrics_json,
                events_json, tracks_json, detections_json, insight_json
            )
            VALUES (
                'analysis_1', 'default', 'palace.mp4', 'palace.mp4', 'palace.mp4',
                'video/mp4', 1, 'COMPLETED', 100, ?, ?, '[]', '[]', '[]', ?
            )
            """,
            (
                json.dumps({"name": "palace.mp4"}),
                json.dumps(metrics),
                json.dumps(insight),
            ),
        )
        connection.commit()
