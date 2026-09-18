from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from backend.cameras.health import CameraHealth


@dataclass(frozen=True)
class CameraConfig:
    id: str
    source_type: str
    source_uri: str


@dataclass
class FrameResult:
    success: bool
    frame: Any | None = None
    error: str | None = None


class CameraSource(ABC):
    def __init__(self, config: CameraConfig) -> None:
        self.config = config

    @abstractmethod
    def connect(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def read(self) -> FrameResult:
        raise NotImplementedError

    @abstractmethod
    def reconnect(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def health(self) -> CameraHealth:
        raise NotImplementedError
