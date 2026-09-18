from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import sys

import numpy as np

from backend.vision.models import BoundingBox, Detection, TrackedObject


class ObjectTracker(ABC):
    name = "abstract"

    def __init__(self) -> None:
        if self.__class__ is object:
            raise TypeError("ObjectTracker cannot initialize a plain object.")

    @abstractmethod
    def update(
        self, camera_id: str, detections: list[Detection], timestamp: datetime
    ) -> list[TrackedObject]:
        raise NotImplementedError


@dataclass
class _Track:
    track_id: int
    class_name: str
    bounding_box: BoundingBox
    confidence: float
    hits: int = 1
    missed: int = 0


class ByteTrackTracker(ObjectTracker):
    name = "ByteTrack"

    def __init__(
        self,
        iou_threshold: float = 0.25,
        max_missed: int = 10,
        minimum_consecutive_frames: int = 1,
    ) -> None:
        self.iou_threshold = iou_threshold
        self.max_missed = max_missed
        self.minimum_consecutive_frames = minimum_consecutive_frames
        self._next_id = 1
        self._tracks: dict[int, _Track] = {}

    def update(
        self, camera_id: str, detections: list[Detection], timestamp: datetime
    ) -> list[TrackedObject]:
        assigned_tracks: set[int] = set()
        objects: list[TrackedObject] = []

        for detection in detections:
            best_track_id: int | None = None
            best_score = 0.0
            for track_id, track in self._tracks.items():
                if track_id in assigned_tracks or track.class_name != detection.class_name:
                    continue
                score = _iou(track.bounding_box, detection.bounding_box)
                if score > best_score:
                    best_score = score
                    best_track_id = track_id

            if best_track_id is None or best_score < self.iou_threshold:
                best_track_id = self._next_id
                self._next_id += 1
                hits = 1
            else:
                hits = self._tracks[best_track_id].hits + 1

            self._tracks[best_track_id] = _Track(
                track_id=best_track_id,
                class_name=detection.class_name,
                bounding_box=detection.bounding_box,
                confidence=detection.confidence,
                hits=hits,
                missed=0,
            )
            assigned_tracks.add(best_track_id)
            if hits > self.minimum_consecutive_frames:
                objects.append(
                    TrackedObject(
                        track_id=best_track_id,
                        camera_id=camera_id,
                        class_name=detection.class_name,
                        confidence=detection.confidence,
                        bounding_box=detection.bounding_box,
                        timestamp=timestamp,
                    )
                )

        for track_id in list(self._tracks):
            if track_id in assigned_tracks:
                continue
            self._tracks[track_id].missed += 1
            if self._tracks[track_id].missed >= self.max_missed:
                del self._tracks[track_id]

        return objects


def _iou(first: BoundingBox, second: BoundingBox) -> float:
    x1 = max(first.x1, second.x1)
    y1 = max(first.y1, second.y1)
    x2 = min(first.x2, second.x2)
    y2 = min(first.y2, second.y2)
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if intersection == 0:
        return 0.0

    first_area = max(0.0, first.x2 - first.x1) * max(0.0, first.y2 - first.y1)
    second_area = max(0.0, second.x2 - second.x1) * max(0.0, second.y2 - second.y1)
    union = first_area + second_area - intersection
    return intersection / union if union else 0.0


class ByteTrackAdapter(ObjectTracker):
    """Adapter that wraps ByteTrack implementations behind CAMPEX's interface.

    Preferred backends:
    1. ``trackers.ByteTrackTracker`` package, when installed.
    2. FoundationVision ByteTrack source under ``REPOGIT/ByteTrack-main``.
    3. Local IoU tracker fallback, so vision stays available without optional deps.
    """

    def __init__(
        self,
        lost_track_buffer: int = 30,
        frame_rate: float = 30.0,
        track_activation_threshold: float = 0.7,
        minimum_consecutive_frames: int = 2,
        minimum_iou_threshold: float = 0.1,
        high_conf_det_threshold: float = 0.6,
    ) -> None:
        self._kwargs = dict(
            lost_track_buffer=lost_track_buffer,
            frame_rate=frame_rate,
            track_activation_threshold=track_activation_threshold,
            minimum_consecutive_frames=minimum_consecutive_frames,
            minimum_iou_threshold=minimum_iou_threshold,
            high_conf_det_threshold=high_conf_det_threshold,
        )
        self._sv: Any | None = None
        self._trackers_module: Any | None = None
        self._foundation_cls: Any | None = None
        self._fallback: ByteTrackTracker | None = None
        try:
            import supervision as sv
            import trackers

            self._sv = sv
            self._trackers_module = trackers
        except ImportError:
            self._foundation_cls = _load_foundation_bytetrack()
            if self._foundation_cls is None:
                self._fallback = ByteTrackTracker(
                    iou_threshold=minimum_iou_threshold,
                    max_missed=lost_track_buffer,
                    minimum_consecutive_frames=minimum_consecutive_frames,
                )
        self._trackers: dict[str, Any] = {}
        self._class_offsets: dict[str, int] = {}
        self._next_offset = 0

    @property
    def name(self) -> str:
        return "ByteTrack" if self.using_external_tracker else "IoU fallback"

    @property
    def backend(self) -> str:
        if self._trackers_module is not None:
            return "trackers.ByteTrackTracker"
        if self._foundation_cls is not None:
            return "REPOGIT.FoundationVision.BYTETracker"
        return "campex.local.ByteTrackTracker"

    @property
    def state(self) -> str:
        return "ACTIVE" if self.using_external_tracker else "DEGRADED"

    @property
    def tracker_type(self) -> str:
        return "bytetrack" if self.using_external_tracker else "iou_fallback"

    @property
    def using_external_tracker(self) -> bool:
        return self._fallback is None

    def _get_tracker(self, class_name: str) -> tuple[Any, int]:
        tracker = self._trackers.get(class_name)
        if tracker is None:
            if self._trackers_module is None and self._foundation_cls is None:
                raise RuntimeError("External ByteTrack package is not available.")
            if self._trackers_module is not None:
                tracker = self._trackers_module.ByteTrackTracker(**self._kwargs)
            else:
                tracker = self._foundation_cls(
                    SimpleNamespace(
                        track_thresh=self._kwargs["track_activation_threshold"],
                        track_buffer=self._kwargs["lost_track_buffer"],
                        match_thresh=max(
                            0.1,
                            1.0 - self._kwargs["minimum_iou_threshold"],
                        ),
                        mot20=False,
                    ),
                    frame_rate=self._kwargs["frame_rate"],
                )
            self._trackers[class_name] = tracker
            self._class_offsets[class_name] = self._next_offset
            self._next_offset += 1000
        return tracker, self._class_offsets[class_name]

    def update(
        self, camera_id: str, detections: list[Detection], timestamp: datetime
    ) -> list[TrackedObject]:
        if self._fallback is not None:
            return self._fallback.update(camera_id, detections, timestamp)

        if not detections:
            if self._foundation_cls is not None:
                empty = np.empty((0, 5), dtype=np.float32)
                for tracker in self._trackers.values():
                    tracker.update(empty, img_info=(1, 1), img_size=(1, 1))
                return []
            if self._sv is not None:
                for tracker in self._trackers.values():
                    tracker.update(self._sv.Detections.empty(), timestamp=None)
            return []

        by_class: dict[str, list[Detection]] = {}
        for detection in detections:
            by_class.setdefault(detection.class_name, []).append(detection)

        objects: list[TrackedObject] = []
        for class_name, class_detections in by_class.items():
            tracker, offset = self._get_tracker(class_name)
            if self._trackers_module is not None:
                sv_detections = self._to_sv_detections(class_detections)
                tracked = tracker.update(sv_detections, timestamp=None)
                objects.extend(
                    self._from_sv_detections(
                        tracked, class_name, camera_id, timestamp, offset
                    )
                )
            else:
                tracked = tracker.update(
                    self._to_foundation_detections(class_detections),
                    img_info=(1, 1),
                    img_size=(1, 1),
                )
                objects.extend(
                    self._from_foundation_tracks(
                        tracked, class_name, camera_id, timestamp, offset
                    )
                )

        missing_classes = set(self._trackers) - set(by_class)
        if self._sv is not None and self._trackers_module is not None:
            for class_name in missing_classes:
                self._trackers[class_name].update(
                    self._sv.Detections.empty(), timestamp=None
                )
        elif self._foundation_cls is not None:
            empty = np.empty((0, 5), dtype=np.float32)
            for class_name in missing_classes:
                self._trackers[class_name].update(empty, img_info=(1, 1), img_size=(1, 1))

        return objects

    def reset(self) -> None:
        if self._fallback is not None:
            self._fallback = ByteTrackTracker(
                iou_threshold=self._fallback.iou_threshold,
                max_missed=self._fallback.max_missed,
                minimum_consecutive_frames=self._fallback.minimum_consecutive_frames,
            )
            return
        for tracker in self._trackers.values():
            if hasattr(tracker, "reset"):
                tracker.reset()
        self._trackers.clear()
        self._class_offsets.clear()
        self._next_offset = 0

    def _to_sv_detections(self, detections: list[Detection]) -> Any:
        if self._sv is None:
            raise RuntimeError("supervision is not available.")
        xyxy = np.array([d.bounding_box.as_list() for d in detections], dtype=np.float32)
        confidence = np.array([d.confidence for d in detections], dtype=np.float32)
        class_id = np.zeros(len(detections), dtype=np.int64)
        class_name_array = np.array([d.class_name for d in detections], dtype=object)
        return self._sv.Detections(
            xyxy=xyxy,
            confidence=confidence,
            class_id=class_id,
            data={"class_name": class_name_array},
        )

    @staticmethod
    def _to_foundation_detections(detections: list[Detection]) -> np.ndarray:
        rows = [
            [
                detection.bounding_box.x1,
                detection.bounding_box.y1,
                detection.bounding_box.x2,
                detection.bounding_box.y2,
                detection.confidence,
            ]
            for detection in detections
        ]
        return np.asarray(rows, dtype=np.float32)

    @staticmethod
    def _from_foundation_tracks(
        tracks: list[Any],
        class_name: str,
        camera_id: str,
        timestamp: datetime,
        id_offset: int = 0,
    ) -> list[TrackedObject]:
        objects: list[TrackedObject] = []
        for track in tracks:
            x1, y1, x2, y2 = [float(value) for value in list(track.tlbr)[:4]]
            objects.append(
                TrackedObject(
                    track_id=int(track.track_id) + id_offset,
                    camera_id=camera_id,
                    class_name=class_name,
                    confidence=float(getattr(track, "score", 0.0)),
                    bounding_box=BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2),
                    timestamp=timestamp,
                )
            )
        return objects

    @staticmethod
    def _from_sv_detections(
        tracked: Any,
        class_name: str,
        camera_id: str,
        timestamp: datetime,
        id_offset: int = 0,
    ) -> list[TrackedObject]:
        objects: list[TrackedObject] = []
        if len(tracked) == 0:
            return objects
        for i in range(len(tracked.xyxy)):
            track_id = int(tracked.tracker_id[i]) if tracked.tracker_id is not None else -1
            # ByteTrack returns track_id == -1 for unconfirmed tracks (first
            # detection of an object). Only return confirmed tracks with IDs >= 0.
            if track_id < 0:
                continue
            # Apply per-class offset to ensure global uniqueness of track IDs.
            track_id += id_offset
            confidence = float(tracked.confidence[i]) if tracked.confidence is not None else 0.0
            bbox = BoundingBox(
                x1=float(tracked.xyxy[i][0]),
                y1=float(tracked.xyxy[i][1]),
                x2=float(tracked.xyxy[i][2]),
                y2=float(tracked.xyxy[i][3]),
            )
            objects.append(
                TrackedObject(
                    track_id=track_id,
                    camera_id=camera_id,
                    class_name=class_name,
                    confidence=confidence,
                    bounding_box=bbox,
                    timestamp=timestamp,
                )
            )
        return objects


def _load_foundation_bytetrack() -> Any | None:
    repo_root = Path(__file__).resolve().parents[2]
    source_root = repo_root / "REPOGIT" / "ByteTrack-main"
    if not source_root.exists():
        return None

    source_root_text = str(source_root)
    if source_root_text not in sys.path:
        sys.path.insert(0, source_root_text)

    try:
        from yolox.tracker.byte_tracker import BYTETracker
    except Exception:
        return None
    return BYTETracker
