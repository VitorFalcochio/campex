from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class AnalysisStatus(str, Enum):
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    GENERATING_INSIGHTS = "GENERATING_INSIGHTS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class VideoMetadata:
    source_type: str
    name: str
    fps: float
    width: int
    height: int
    frame_count: int
    duration_seconds: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": self.source_type,
            "name": self.name,
            "fps": self.fps,
            "width": self.width,
            "height": self.height,
            "frame_count": self.frame_count,
            "duration_seconds": self.duration_seconds,
        }


@dataclass
class AnalysisJob:
    analysis_id: str
    organization_id: str
    original_filename: str
    stored_filename: str
    storage_path: Path
    content_type: str | None
    file_size: int
    status: AnalysisStatus = AnalysisStatus.QUEUED
    progress: int = 0
    error: str | None = None
    source: dict[str, Any] | None = None
    metrics: dict[str, Any] | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    tracks: list[dict[str, Any]] = field(default_factory=list)
    detections: list[dict[str, Any]] = field(default_factory=list)
    insight: dict[str, Any] | None = None
