from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Camera:
    id: str
    name: str
    area_id: str | None
    source_type: str
    source_uri: str
    enabled: bool
    vision_enabled: bool
    status: str
    created_at: str
    updated_at: str
