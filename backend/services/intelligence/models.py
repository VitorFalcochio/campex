from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


INSUFFICIENT_INFORMATION = "There is insufficient information."


@dataclass(frozen=True)
class IntelligenceRequest:
    organization_id: str
    query: str
    context: dict[str, Any]


@dataclass(frozen=True)
class IntelligenceResponse:
    answer: str
    organization_id: str
    model: str | None
    context_summary: dict[str, Any]
    limitations: list[str]


class ChatMessageClient(Protocol):
    model: str

    def chat(self, messages: list[dict[str, str]]) -> str:
        ...
