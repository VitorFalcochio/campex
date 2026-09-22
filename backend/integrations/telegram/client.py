from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from backend.config import Settings


logger = logging.getLogger("campex.telegram")


class TelegramError(RuntimeError):
    pass


class TelegramClient:
    def __init__(self, settings: Settings, timeout_seconds: float = 10.0) -> None:
        self.token = settings.telegram_bot_token
        self.timeout_seconds = timeout_seconds
        self.base_url = f"https://api.telegram.org/bot{self.token}" if self.token else ""

    @property
    def configured(self) -> bool:
        return bool(self.token)

    def test_connection(self) -> dict[str, Any]:
        if not self.token:
            raise TelegramError("TELEGRAM_BOT_TOKEN is not configured.")
        started = time.perf_counter()
        response = httpx.get(f"{self.base_url}/getMe", timeout=self.timeout_seconds)
        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        data = _telegram_json(response)
        return {"status": "ok", "latency_ms": latency_ms, "bot": data.get("result", {}).get("username")}

    def send_message(self, chat_id: str, message: str) -> dict[str, Any]:
        if not self.token:
            raise TelegramError("TELEGRAM_BOT_TOKEN is not configured.")
        if not chat_id:
            raise TelegramError("Telegram chat_id is required.")
        logger.info("[CAMPEX][TELEGRAM] sending report")
        started = time.perf_counter()
        try:
            response = httpx.post(
                f"{self.base_url}/sendMessage",
                json={"chat_id": chat_id, "text": message, "disable_web_page_preview": True},
                timeout=self.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise TelegramError("Telegram request timed out.") from exc
        except httpx.HTTPError as exc:
            raise TelegramError("Telegram request failed.") from exc
        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        data = _telegram_json(response)
        result = data.get("result") or {}
        logger.info("[CAMPEX][TELEGRAM] sent")
        return {
            "status": "sent",
            "message_id": str(result.get("message_id")) if result.get("message_id") is not None else None,
            "latency_ms": latency_ms,
        }


def _telegram_json(response: httpx.Response) -> dict[str, Any]:
    if response.status_code == 429:
        raise TelegramError("Telegram rate limit reached.")
    if response.status_code in {401, 403}:
        raise TelegramError("Telegram token or chat is not authorized.")
    if response.status_code == 400:
        raise TelegramError("Telegram chat is invalid or unavailable.")
    if response.status_code >= 400:
        raise TelegramError("Telegram service unavailable.")
    try:
        data = response.json()
    except ValueError as exc:
        raise TelegramError("Telegram returned invalid JSON.") from exc
    if not data.get("ok"):
        raise TelegramError("Telegram rejected the request.")
    return data
