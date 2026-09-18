from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class ZonePoint:
    """A single normalized point [x, y] where 0.0–1.0 maps to the frame."""

    x: float
    y: float

    def as_list(self) -> list[float]:
        return [round(self.x, 6), round(self.y, 6)]


@dataclass(frozen=True)
class Zone:
    id: str
    camera_id: str
    name: str
    type: str  # "monitored" or "restricted"
    enabled: bool
    points: list[ZonePoint]
    created_at: str
    updated_at: str

    def as_dict(self) -> dict:
        data = {
            "id": self.id,
            "camera_id": self.camera_id,
            "name": self.name,
            "type": self.type,
            "enabled": self.enabled,
            "points": [p.as_list() for p in self.points],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        return data


@dataclass(frozen=True)
class Observation:
    """A structured interpretation of detection/tracking data for a zone.

    Observations are the bridge between raw tracking and rule/event evaluation.
    """

    type: str  # "person_presence", "person_entered_zone", "person_exited_zone"
    camera_id: str
    track_id: int | None
    zone_id: str | None
    state: str  # "present", "absent"
    confidence: float
    timestamp: datetime
    knowledge_state: str = "OBSERVED"

    def as_dict(self) -> dict:
        return {
            "type": self.type,
            "camera_id": self.camera_id,
            "track_id": self.track_id,
            "zone_id": self.zone_id,
            "state": self.state,
            "confidence": self.confidence,
            "timestamp": self.timestamp.isoformat(),
            "knowledge_state": self.knowledge_state,
        }
