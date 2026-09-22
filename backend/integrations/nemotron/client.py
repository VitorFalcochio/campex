from __future__ import annotations

import logging
import time

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

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
        self.max_retries = 2

    def chat(self, messages: list[dict[str, str]]) -> str:
        if not self.api_key:
            raise IntelligenceNotConfiguredError("NVIDIA_API_KEY is not configured.")

        client = OpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=self.timeout_seconds,
        )
        logger.info("[CAMPEX][NEMOTRON] request started")
        completion = None
        for attempt in range(self.max_retries + 1):
            try:
                completion = client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                    top_p=self.top_p,
                    max_tokens=self.max_tokens,
                    stream=False,
                    extra_body={
                        "chat_template_kwargs": {"enable_thinking": False},
                        "reasoning_budget": 0,
                    },
                )
            except APITimeoutError as exc:
                if attempt >= self.max_retries:
                    raise IntelligenceTimeoutError("Nemotron request timed out.") from exc
                logger.warning("[CAMPEX][NEMOTRON] fallback activated: timeout")
                time.sleep(0.5 * (attempt + 1))
                continue
            except APIStatusError as exc:
                status_code = exc.status_code
                if status_code in {429, 500, 502, 503, 504} and attempt < self.max_retries:
                    logger.warning(
                        "[CAMPEX][NEMOTRON] transient response; retrying",
                        extra={"status_code": status_code, "attempt": attempt + 1},
                    )
                    time.sleep(0.5 * (attempt + 1))
                    continue
                if status_code == 429:
                    raise IntelligenceRateLimitError("Nemotron rate limit reached.") from exc
                if status_code >= 500:
                    raise IntelligenceProviderUnavailableError("Nemotron service unavailable.") from exc
                raise IntelligenceProviderUnavailableError("Nemotron request rejected.") from exc
            except APIConnectionError as exc:
                if attempt >= self.max_retries:
                    raise IntelligenceProviderUnavailableError("Nemotron request failed.") from exc
                logger.warning("[CAMPEX][NEMOTRON] transient connection error; retrying")
                time.sleep(0.5 * (attempt + 1))
                continue
            break

        if completion is None:
            raise IntelligenceProviderUnavailableError("Nemotron request failed.")

        try:
            content = completion.choices[0].message.content
        except (AttributeError, IndexError, TypeError) as exc:
            raise IntelligenceInvalidResponseError("Nemotron returned an invalid response.") from exc

        if not isinstance(content, str) or not content.strip():
            raise IntelligenceInvalidResponseError("Nemotron returned an empty response.")
        logger.info("[CAMPEX][NEMOTRON] response received")
        return content.strip()
