from __future__ import annotations

import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class LatestFrameSnapshot:
    frame: Any | None
    frame_at: datetime | None
    frame_id: int
    frames_received: int
    frames_replaced: int


@dataclass(frozen=True)
class LatestFrameStats:
    frames_received: int
    frames_replaced: int

    def as_dict(self) -> dict:
        return asdict(self)


class LatestFrameBuffer:
    """Single-slot frame buffer: new frames replace stale frames."""

    def __init__(self) -> None:
        self._frame: Any | None = None
        self._frame_at: datetime | None = None
        self._frames_received = 0
        self._frames_replaced = 0
        self._lock = threading.Lock()

    def put(self, frame: Any, frame_at: datetime) -> None:
        frame_copy = frame.copy() if hasattr(frame, "copy") else frame
        with self._lock:
            if self._frame is not None:
                self._frames_replaced += 1
            self._frame = frame_copy
            self._frame_at = frame_at
            self._frames_received += 1

    def latest(self) -> tuple[Any | None, datetime | None]:
        with self._lock:
            frame = self._frame.copy() if hasattr(self._frame, "copy") else self._frame
            return frame, self._frame_at

    def snapshot(self) -> LatestFrameSnapshot:
        with self._lock:
            frame = self._frame.copy() if hasattr(self._frame, "copy") else self._frame
            return LatestFrameSnapshot(
                frame=frame,
                frame_at=self._frame_at,
                frame_id=self._frames_received,
                frames_received=self._frames_received,
                frames_replaced=self._frames_replaced,
            )

    def stats(self) -> LatestFrameStats:
        with self._lock:
            return LatestFrameStats(
                frames_received=self._frames_received,
                frames_replaced=self._frames_replaced,
            )
