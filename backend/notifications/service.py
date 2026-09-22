from __future__ import annotations

import html
import logging
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from backend.config import Settings
from backend.integrations.email import EmailClient
from backend.integrations.telegram import TelegramClient
from backend.notifications.models import ALERT_TYPES, DeliveryResult, NotificationPreference
from backend.notifications.repository import NotificationRepository
from backend.videos.repository import VideoAnalysisRepository


logger = logging.getLogger("campex.notifications")
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class NotificationService:
    def __init__(
        self,
        settings: Settings,
        *,
        repository: NotificationRepository | None = None,
        telegram_client: TelegramClient | None = None,
        email_client: EmailClient | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository or NotificationRepository(settings)
        self.telegram = telegram_client or TelegramClient(settings)
        self.email = email_client or EmailClient(settings)
        self.videos = VideoAnalysisRepository(settings)

    def get_preferences(self, organization_id: str) -> dict[str, Any]:
        pref = self.repository.get_or_create_preference(organization_id)
        return pref.as_dict(
            telegram_configured=self.telegram.configured,
            email_configured=self.email.configured,
        )

    def update_preferences(self, organization_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        recipients = [item.strip() for item in payload.get("email_recipients", []) if str(item).strip()]
        invalid = [item for item in recipients if not EMAIL_RE.match(item)]
        if invalid:
            raise ValueError("Invalid email recipient.")
        alert_types = payload.get("alert_types") or sorted(ALERT_TYPES)
        unsupported = [item for item in alert_types if item not in ALERT_TYPES]
        if unsupported:
            raise ValueError("Unsupported alert type.")
        payload = {**payload, "organization_id": organization_id, "email_recipients": recipients, "alert_types": alert_types}
        pref = self.repository.save_preference(payload)
        return pref.as_dict(
            telegram_configured=self.telegram.configured,
            email_configured=self.email.configured,
        )

    def test_telegram(self, organization_id: str) -> dict[str, Any]:
        pref = self.repository.get_or_create_preference(organization_id)
        chat_ids = _telegram_recipients(pref)
        if not chat_ids:
            raise ValueError("Telegram chat_id is required.")
        message = f"CAMPEX\n\nIntegracao com Telegram configurada com sucesso.\n\nHorario:\n{_local_now(pref.timezone)}"
        return {
            "status": "completed",
            "telegram": [
                self._send_telegram(
                    organization_id=organization_id,
                    delivery_type="TEST",
                    reference_id=f"telegram-test-{int(time.time())}",
                    recipient=chat_id,
                    message=message,
                ).as_dict()
                for chat_id in chat_ids
            ],
        }

    def test_email(self, organization_id: str) -> dict[str, Any]:
        pref = self.repository.get_or_create_preference(organization_id)
        if not pref.email_recipients:
            raise ValueError("At least one email recipient is required.")
        return self._send_email(
            organization_id=organization_id,
            delivery_type="TEST",
            reference_id=f"email-test-{int(time.time())}",
            recipients=pref.email_recipients,
            subject="CAMPEX | Teste de integracao",
            text="CAMPEX\n\nIntegracao de e-mail configurada com sucesso.",
            html="<h1>CAMPEX</h1><p>Integracao de e-mail configurada com sucesso.</p>",
        ).as_dict()

    def send_report_now(self, organization_id: str) -> dict[str, Any]:
        logger.info("[CAMPEX][NOTIFICATION] report requested")
        pref = self.repository.get_or_create_preference(organization_id)
        analysis = _latest_completed_analysis(self.videos, organization_id)
        if analysis is None:
            raise ValueError("No completed CAMPEX report is available.")
        reference_id = f"manual-report:{analysis['id']}"
        subject = _report_subject(analysis, pref)
        text = _format_report_text(analysis, pref)
        html_body = _format_report_html(analysis, pref)
        results: dict[str, Any] = {}
        if not pref.enabled:
            return {"status": "skipped", "reason": "notifications disabled", "channels": results}
        if pref.telegram_enabled:
            telegram_results = [
                self._send_telegram(
                    organization_id=organization_id,
                    delivery_type="REPORT",
                    reference_id=reference_id,
                    recipient=chat_id,
                    message=text,
                ).as_dict()
                for chat_id in _telegram_recipients(pref)
            ]
            if telegram_results:
                results["telegram"] = telegram_results
        if pref.email_enabled and pref.email_recipients:
            results["email"] = self._send_email(
                organization_id=organization_id,
                delivery_type="REPORT",
                reference_id=reference_id,
                recipients=pref.email_recipients,
                subject=subject,
                text=text,
                html=html_body,
            ).as_dict()
        return {"status": "completed", "channels": results, "reference_id": reference_id}

    def send_alert(self, organization_id: str, event: dict[str, Any]) -> dict[str, Any]:
        pref = self.repository.get_or_create_preference(organization_id)
        event_type = str(event.get("event_type") or event.get("type") or "")
        if event_type not in ALERT_TYPES or event_type not in pref.alert_types:
            return {"status": "skipped", "reason": "alert type disabled"}
        if not (pref.enabled and pref.immediate_alerts_enabled):
            return {"status": "skipped", "reason": "alerts disabled"}
        reference_id = f"alert:{event_type}:{event.get('id') or event.get('started_at') or int(time.time())}"
        message = _format_alert_text(event, pref)
        results: dict[str, Any] = {}
        if pref.telegram_enabled:
            telegram_results = [
                self._send_telegram(
                    organization_id=organization_id,
                    delivery_type="ALERT",
                    reference_id=reference_id,
                    recipient=chat_id,
                    message=message,
                ).as_dict()
                for chat_id in _telegram_recipients(pref)
            ]
            if telegram_results:
                results["telegram"] = telegram_results
        if pref.email_enabled and pref.email_recipients:
            results["email"] = self._send_email(
                organization_id=organization_id,
                delivery_type="ALERT",
                reference_id=reference_id,
                recipients=pref.email_recipients,
                subject="CAMPEX | Alerta Operacional",
                text=message,
                html=f"<pre>{html.escape(message)}</pre>",
            ).as_dict()
        return {"status": "completed", "channels": results, "reference_id": reference_id}

    def deliveries(self, organization_id: str) -> list[dict[str, Any]]:
        return self.repository.list_deliveries(organization_id)

    def _send_telegram(
        self,
        *,
        organization_id: str,
        delivery_type: str,
        reference_id: str,
        recipient: str,
        message: str,
    ) -> DeliveryResult:
        delivery_id, created = self.repository.create_delivery(
            organization_id=organization_id,
            channel="telegram",
            delivery_type=delivery_type,
            reference_id=reference_id,
            recipient=recipient,
        )
        if not created:
            return DeliveryResult("telegram", "skipped", delivery_id, recipient, error="duplicate")
        return self._attempt_delivery(
            delivery_id=delivery_id,
            channel="telegram",
            recipient=recipient,
            send=lambda: self.telegram.send_message(recipient, message),
        )

    def _send_email(
        self,
        *,
        organization_id: str,
        delivery_type: str,
        reference_id: str,
        recipients: list[str],
        subject: str,
        text: str,
        html: str | None,
    ) -> DeliveryResult:
        recipient_key = ",".join(sorted(recipients))
        delivery_id, created = self.repository.create_delivery(
            organization_id=organization_id,
            channel="email",
            delivery_type=delivery_type,
            reference_id=reference_id,
            recipient=recipient_key,
        )
        if not created:
            return DeliveryResult("email", "skipped", delivery_id, recipient_key, error="duplicate")
        return self._attempt_delivery(
            delivery_id=delivery_id,
            channel="email",
            recipient=recipient_key,
            send=lambda: self.email.send_email(
                recipients=recipients,
                subject=subject,
                text=text,
                html=html,
            ),
        )

    def _attempt_delivery(self, *, delivery_id: str, channel: str, recipient: str, send) -> DeliveryResult:
        last_error: str | None = None
        for attempt in range(1, 4):
            try:
                result = send()
                self.repository.update_delivery(
                    delivery_id,
                    status="sent",
                    attempts=attempt,
                    metadata={k: v for k, v in result.items() if k != "recipients"},
                )
                return DeliveryResult(
                    channel=channel,
                    status="sent",
                    delivery_id=delivery_id,
                    recipient=recipient,
                    message_id=result.get("message_id"),
                    attempts=attempt,
                )
            except Exception as exc:  # notification failures must never escape the service
                last_error = str(exc)
                if attempt < 3:
                    time.sleep(0.1 * attempt)
        self.repository.update_delivery(delivery_id, status="failed", attempts=3, error=last_error)
        return DeliveryResult(channel, "failed", delivery_id, recipient, attempts=3, error=last_error)


class NotificationScheduler:
    def __init__(self, service: NotificationService, interval_seconds: float = 60.0) -> None:
        self.service = service
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="campex-notification-scheduler", daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            # The persisted preferences survive restarts. Scheduled dispatch can be
            # expanded here without coupling notifications to vision processing.
            continue


def _latest_completed_analysis(repository: VideoAnalysisRepository, organization_id: str) -> dict[str, Any] | None:
    for item in repository.list(organization_id, limit=10):
        if item.get("status") == "COMPLETED" and item.get("metrics"):
            return item
    return None


def _telegram_recipients(pref: NotificationPreference) -> list[str]:
    raw = pref.telegram_chat_id or ""
    return [item.strip() for item in raw.split(",") if item.strip()]


def _report_subject(analysis: dict[str, Any], pref: NotificationPreference) -> str:
    name = (analysis.get("source") or {}).get("name") or analysis.get("original_filename") or "CAMPEX"
    return f"CAMPEX | Relatorio Operacional | {name} | {_local_date(pref.timezone)}"


def _format_report_text(analysis: dict[str, Any], pref: NotificationPreference) -> str:
    source = analysis.get("source") or {}
    metrics = analysis.get("metrics") or {}
    people = metrics.get("people") or {}
    activity = metrics.get("activity") or {}
    insight = analysis.get("insight") or {}
    return "\n".join(
        [
            "CAMPEX - Relatorio Operacional",
            "",
            f"Camera: {source.get('name') or analysis.get('original_filename') or 'CAMPEX'}",
            f"Periodo: {_local_date(pref.timezone)}",
            "",
            "Fluxo",
            f"Pessoas detectadas: {people.get('detected', '-')}",
            f"Entradas: {people.get('entries', '-')}",
            f"Saidas: {people.get('exits', '-')}",
            f"Pico simultaneo: {people.get('max_simultaneous', '-')}",
            "",
            "Atividade",
            f"Movimentacao detectada: {_seconds(activity.get('moving_seconds'))}",
            f"Tempo sem deslocamento: {_seconds(activity.get('stationary_seconds'))}",
            f"Eventos sem deslocamento: {activity.get('stationary_events', 0)}",
            "",
            "Analise CAMPEX",
            str(insight.get("summary") or "Relatorio deterministico CAMPEX disponivel."),
            "",
            "Gerado pela CAMPEX.",
        ]
    )


def _format_report_html(analysis: dict[str, Any], pref: NotificationPreference) -> str:
    text = _format_report_text(analysis, pref)
    return f"<html><body><pre>{html.escape(text)}</pre></body></html>"


def _format_alert_text(event: dict[str, Any], pref: NotificationPreference) -> str:
    event_type = str(event.get("event_type") or event.get("type") or "alerta")
    labels = {
        "camera_offline": "Camera desconectada.",
        "camera_online": "Camera conectada.",
        "zone_idle": "Nenhuma movimentacao detectavel no periodo configurado.",
        "zone_activity_resumed": "Movimentacao detectavel retomada.",
        "crowding_started": "Aglomeracao acima do limite configurado.",
        "crowding_ended": "Aglomeracao normalizada.",
        "long_presence": "Permanencia prolongada observada.",
    }
    return "\n".join(
        [
            "CAMPEX - Alerta Operacional",
            "",
            f"Camera: {event.get('camera_id', '-')}",
            labels.get(event_type, event_type),
            "",
            f"Horario: {_local_now(pref.timezone)}",
        ]
    )


def _local_now(timezone_name: str) -> str:
    try:
        zone = ZoneInfo(timezone_name)
    except Exception:
        zone = timezone.utc
    return datetime.now(zone).strftime("%Y-%m-%d %H:%M")


def _local_date(timezone_name: str) -> str:
    try:
        zone = ZoneInfo(timezone_name)
    except Exception:
        zone = timezone.utc
    return datetime.now(zone).strftime("%Y-%m-%d")


def _seconds(value: Any) -> str:
    try:
        seconds = float(value or 0)
    except (TypeError, ValueError):
        seconds = 0.0
    if seconds >= 60:
        minutes = int(seconds // 60)
        rest = int(seconds % 60)
        return f"{minutes}m{rest:02d}s"
    return f"{seconds:g}s"
