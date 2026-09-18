from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Protocol


class AIProviderError(RuntimeError):
    code = "AI_UNAVAILABLE"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code


class AIProviderNotConfigured(AIProviderError):
    code = "AI_NOT_CONFIGURED"


class AIProviderInvalidOutput(AIProviderError):
    code = "AI_INVALID_OUTPUT"


class AIProviderTimeout(AIProviderError):
    code = "AI_UNAVAILABLE"


class StructuredAIProvider(Protocol):
    def structured_response(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        schema: dict[str, Any],
        model: str,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        ...


@dataclass
class OpenAIResponsesProvider:
    api_key: str | None = None

    def __post_init__(self) -> None:
        self.api_key = self.api_key or os.getenv("OPENAI_API_KEY")

    def structured_response(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        schema: dict[str, Any],
        model: str,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise AIProviderNotConfigured("OPENAI_API_KEY nao configurada.")
        try:
            from openai import APITimeoutError, OpenAI
        except ImportError as exc:  # pragma: no cover - depends on deployment env
            raise AIProviderNotConfigured("SDK oficial da OpenAI nao instalado.") from exc

        client = OpenAI(api_key=self.api_key, timeout=timeout_seconds)
        try:
            response = client.responses.create(
                model=model,
                store=False,
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "campex_reasoning_result",
                        "schema": schema,
                        "strict": True,
                    }
                },
            )
        except APITimeoutError as exc:  # pragma: no cover - mocked in tests
            raise AIProviderTimeout("OpenAI timeout ao gerar reasoning.") from exc
        except Exception as exc:  # pragma: no cover - mocked in tests
            raise AIProviderError("Falha ao chamar provider de IA.") from exc

        raw_output = getattr(response, "output_text", None)
        if not raw_output:
            try:
                raw_output = response.output[0].content[0].text
            except Exception as exc:  # pragma: no cover - SDK shape fallback
                raise AIProviderInvalidOutput("Provider retornou resposta vazia.") from exc
        try:
            parsed = json.loads(raw_output)
        except json.JSONDecodeError as exc:
            raise AIProviderInvalidOutput("Provider retornou JSON invalido.") from exc
        if not isinstance(parsed, dict):
            raise AIProviderInvalidOutput("Provider retornou objeto invalido.")
        return parsed
