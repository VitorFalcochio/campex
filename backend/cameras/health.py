from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from backend.cameras.security import sanitize_error_message


class CameraStatus(StrEnum):
    CONNECTING = "CONNECTING"
    ONLINE = "ONLINE"
    DEGRADED = "DEGRADED"
    OFFLINE = "OFFLINE"


@dataclass
class Resolution:
    width: int
    height: int


@dataclass
class CameraHealth:
    camera_id: str
    status: CameraStatus
    last_successful_frame: datetime | None = None
    last_connected_at: datetime | None = None
    last_disconnected_at: datetime | None = None
    connection_state: str = "OFFLINE"
    last_error: str | None = None
    resolution: Resolution | None = None
    approximate_fps: float | None = None
    reconnect_attempts: int = 0
    frames_received: int = 0
    consecutive_failures: int = 0

    def as_dict(self) -> dict:
        return {
            "camera_id": self.camera_id,
            "status": self.status.value,
            "connection_state": self.connection_state,
            "last_frame_at": (
                self.last_successful_frame.isoformat()
                if self.last_successful_frame
                else None
            ),
            "last_successful_frame": (
                self.last_successful_frame.isoformat()
                if self.last_successful_frame
                else None
            ),
            "last_connected_at": (
                self.last_connected_at.isoformat()
                if self.last_connected_at
                else None
            ),
            "last_disconnected_at": (
                self.last_disconnected_at.isoformat()
                if self.last_disconnected_at
                else None
            ),
            "last_error": sanitize_error_message(self.last_error),
            "resolution": (
                {
                    "width": self.resolution.width,
                    "height": self.resolution.height,
                }
                if self.resolution
                else None
            ),
            "approximate_fps": self.approximate_fps,
            "reconnect_attempts": self.reconnect_attempts,
            "frames_received": self.frames_received,
            "consecutive_failures": self.consecutive_failures,
        }


def utc_now() -> datetime:
    return datetime.now(UTC)
