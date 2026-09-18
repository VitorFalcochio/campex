from __future__ import annotations

import logging

import httpx

from backend.config import Settings
from backend.services.intelligence.exceptions import (
    IntelligenceInvalidResponseError,
    IntelligenceNotConfiguredError,
    IntelligenceProviderUnavailableError,
    IntelligenceRateLimitError,
    IntelligenceTimeoutError,
)


logger = logging.getLogger("campex.intelligence")


class NemotronClient:
    def __init__(self, settings: Settings) -> None:
        self.api_key = settings.nvidia_api_key
        self.base_url = settings.nemotron_base_url.rstrip("/")
        self.model = settings.nemotron_model
        self.timeout_seconds = settings.nemotron_timeout_seconds
        self.temperature = settings.nemotron_temperature
        self.top_p = settings.nemotron_top_p
        self.max_tokens = settings.nemotron_max_tokens

    def chat(self, messages: list[dict[str, str]]) -> str:
        if not self.api_key:
            raise IntelligenceNotConfiguredError("NVIDIA_API_KEY is not configured.")

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}/chat/completions"
        try:
            response = httpx.post(
                url,
                headers=headers,
                json=payload,
                timeout=self.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise IntelligenceTimeoutError("Nemotron request timed out.") from exc
        except httpx.HTTPError as exc:
            raise IntelligenceProviderUnavailableError("Nemotron request failed.") from exc

        if response.status_code == 429:
            raise IntelligenceRateLimitError("Nemotron rate limit reached.")
        if response.status_code >= 500:
            raise IntelligenceProviderUnavailableError("Nemotron service unavailable.")
        if response.status_code >= 400:
            raise IntelligenceProviderUnavailableError("Nemotron request rejected.")

        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise IntelligenceInvalidResponseError("Nemotron returned an invalid response.") from exc

        if not isinstance(content, str) or not content.strip():
            raise IntelligenceInvalidResponseError("Nemotron returned an empty response.")
        return content.strip()
