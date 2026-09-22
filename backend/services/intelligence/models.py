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


@dataclass(frozen=True)
class OperationalReportResult:
    provider: str
    model: str | None
    status: str
    fallback_used: bool
    summary: str
    sections: dict[str, str]
    reason: str | None = None
    latency_ms: float | None = None
    raw_text: str | None = None

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "provider": self.provider,
            "model": self.model,
            "status": self.status,
            "fallback_used": self.fallback_used,
            "summary": self.summary,
            "sections": self.sections,
        }
        if self.reason:
            data["reason"] = self.reason
        if self.latency_ms is not None:
            data["latency_ms"] = self.latency_ms
        if self.raw_text:
            data["raw_text"] = self.raw_text
        return data


class ChatMessageClient(Protocol):
    model: str

    def chat(self, messages: list[dict[str, str]]) -> str:
        ...
