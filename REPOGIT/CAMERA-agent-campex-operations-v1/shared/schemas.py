from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


@dataclass(frozen=True)
class EventPayload:
    cliente_id: str
    unidade_id: str
    camera_id: str
    tipo: str
    inicio: str
    fim: str | None = None
    duracao: float | None = None
    operador_presente: bool | None = None
    confianca: float | None = None
    midia_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CameraHealth:
    camera_id: str
    status: str
    ultimo_frame: str | None = None
    mensagem: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

