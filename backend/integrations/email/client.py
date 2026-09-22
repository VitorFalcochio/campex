from __future__ import annotations

import logging
import smtplib
import socket
import time
from email.message import EmailMessage
from typing import Any

from backend.config import Settings


logger = logging.getLogger("campex.email")


class EmailError(RuntimeError):
    pass


class EmailClient:
    def __init__(self, settings: Settings, timeout_seconds: float = 10.0) -> None:
        self.host = settings.smtp_host
        self.port = settings.smtp_port
        self.username = settings.smtp_username
        self.password = settings.smtp_password
        self.from_email = settings.smtp_from_email
        self.from_name = settings.smtp_from_name
        self.use_tls = settings.smtp_use_tls
        self.timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self.host and self.port and self.from_email)

    def test_connection(self) -> dict[str, Any]:
        if not self.configured:
            raise EmailError("SMTP is not configured.")
        started = time.perf_counter()
        with self._connect() as smtp:
            smtp.noop()
        return {"status": "ok", "latency_ms": round((time.perf_counter() - started) * 1000, 3)}

    def send_email(
        self,
        *,
        recipients: list[str],
        subject: str,
        text: str,
        html: str | None = None,
    ) -> dict[str, Any]:
        if not self.configured:
            raise EmailError("SMTP is not configured.")
        clean_recipients = [item.strip() for item in recipients if item.strip()]
        if not clean_recipients:
            raise EmailError("At least one email recipient is required.")
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = f"{self.from_name} <{self.from_email}>"
        message["To"] = ", ".join(clean_recipients)
        message.set_content(text)
        if html:
            message.add_alternative(html, subtype="html")

        logger.info("[CAMPEX][EMAIL] sending report")
        started = time.perf_counter()
        try:
            with self._connect() as smtp:
                smtp.send_message(message)
        except smtplib.SMTPAuthenticationError as exc:
            raise EmailError("SMTP authentication failed.") from exc
        except (smtplib.SMTPException, OSError, socket.timeout) as exc:
            raise EmailError("SMTP send failed.") from exc
        logger.info("[CAMPEX][EMAIL] sent")
        return {
            "status": "sent",
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            "recipients": clean_recipients,
        }

    def _connect(self):
        if self.use_tls:
            smtp = smtplib.SMTP(self.host, self.port, timeout=self.timeout_seconds)
            smtp.starttls()
        else:
            smtp = smtplib.SMTP(self.host, self.port, timeout=self.timeout_seconds)
        if self.username:
            smtp.login(self.username, self.password or "")
        return smtp
