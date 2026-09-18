from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime


@dataclass(frozen=True)
class BoundingBox:
    x1: float
    y1: float
    x2: float
    y2: float

    def as_list(self) -> list[float]:
        return [self.x1, self.y1, self.x2, self.y2]


@dataclass(frozen=True)
class Detection:
    class_name: str
    confidence: float
    bounding_box: BoundingBox

    def as_dict(self) -> dict:
        data = asdict(self)
        data["bounding_box"] = self.bounding_box.as_list()
        return data


@dataclass(frozen=True)
class TrackedObject:
    track_id: int
    camera_id: str
    class_name: str
    confidence: float
    bounding_box: BoundingBox
    timestamp: datetime

    def as_dict(self) -> dict:
        return {
            "track_id": self.track_id,
            "camera_id": self.camera_id,
            "class_name": self.class_name,
            "confidence": self.confidence,
            "bounding_box": self.bounding_box.as_list(),
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass(frozen=True)
class PoseKeypoint:
    name: str
    x: float
    y: float
    confidence: float

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class PoseEstimate:
    pose_id: int
    camera_id: str
    confidence: float
    bounding_box: BoundingBox
    keypoints: list[PoseKeypoint]
    timestamp: datetime

    def as_dict(self) -> dict:
        return {
            "pose_id": self.pose_id,
            "camera_id": self.camera_id,
            "confidence": self.confidence,
            "bounding_box": self.bounding_box.as_list(),
            "keypoints": [keypoint.as_dict() for keypoint in self.keypoints],
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass(frozen=True)
class VisionMetrics:
    camera_fps: float
    vision_fps: float
    inference_ms: float | None
    objects_detected: int
    device: str
    detector: str
    tracker: str
    uptime: float
    frames_received: int = 0
    frames_processed: int = 0
    frames_dropped: int = 0
    frame_age_ms: float | None = None
    motion_processing_ms: float | None = None
    tracking_ms: float | None = None
    spatial_processing_ms: float | None = None
    motion_triggered_inferences: int = 0
    periodic_inferences: int = 0
    skipped_inferences: int = 0
    tracker_backend: str | None = None
    tracker_state: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)
