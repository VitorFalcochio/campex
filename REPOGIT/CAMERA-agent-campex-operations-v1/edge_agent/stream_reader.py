from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

from edge_agent.camera_connector import CameraSource, UniversalCameraConnector


@dataclass(frozen=True)
class StreamConfig:
    camera_id: str
    source: str | int
    reconnect_seconds: float = 5.0


class StreamReader:
    def __init__(self, config: StreamConfig) -> None:
        self.config = config
        self.connector = UniversalCameraConnector(
            CameraSource(
                camera_id=config.camera_id,
                source=config.source,
                reconnect_seconds=config.reconnect_seconds,
            )
        )

    def open(self) -> bool:
        return self.connector.open()

    def close(self) -> None:
        self.connector.close()

    def frames(self) -> Iterator[object]:
        yield from self.connector.frames()
