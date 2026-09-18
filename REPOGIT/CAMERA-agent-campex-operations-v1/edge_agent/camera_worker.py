from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

from edge_agent.health import mark_camera_offline, mark_camera_online
from edge_agent.stream_reader import StreamConfig, StreamReader

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CameraWorkerConfig:
    camera_id: str
    source: str | int
    cliente_id: str | None = None
    unidade_id: str | None = None
    edge_id: str | None = None


class CameraWorker:
    def __init__(self, config: CameraWorkerConfig, db_path: str) -> None:
        self.config = config
        self.db_path = db_path

    def run_forever(self) -> None:
        reader = StreamReader(StreamConfig(camera_id=self.config.camera_id, source=self.config.source))
        while True:
            try:
                with sqlite3.connect(self.db_path) as connection:
                    connection.row_factory = sqlite3.Row
                    for _frame in reader.frames():
                        mark_camera_online(connection, self.config.camera_id)
                        # Detection stays in monitor_context.py today.
                        # This worker only prepares isolated live camera execution.
            except Exception as exc:
                logger.exception("Camera %s failed: %s", self.config.camera_id, exc)
                with sqlite3.connect(self.db_path) as connection:
                    connection.row_factory = sqlite3.Row
                    mark_camera_offline(connection, self.config.camera_id)
