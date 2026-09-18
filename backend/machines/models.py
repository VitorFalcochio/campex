from __future__ import annotations

from dataclasses import dataclass

from backend.zones.models import ZonePoint


@dataclass(frozen=True)
class Machine:
    id: str
    camera_id: str
    name: str
    type: str
    enabled: bool
    points: list[ZonePoint]
    requires_operator: bool
    allow_idle: bool
    min_person_distance: float
    created_at: str
    updated_at: str

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "camera_id": self.camera_id,
            "name": self.name,
            "type": self.type,
            "enabled": self.enabled,
            "points": [point.as_list() for point in self.points],
            "requires_operator": self.requires_operator,
            "allow_idle": self.allow_idle,
            "min_person_distance": self.min_person_distance,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
