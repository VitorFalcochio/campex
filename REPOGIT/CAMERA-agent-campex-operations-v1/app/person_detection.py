from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from math import hypot
from typing import Protocol

import cv2
import numpy as np


@dataclass
class Detection:
    x1: int
    y1: int
    x2: int
    y2: int
    confidence: float
    class_name: str = "person"
    track_id: int | None = None

    @property
    def center(self) -> tuple[int, int]:
        return (self.x1 + self.x2) // 2, (self.y1 + self.y2) // 2


@dataclass
class PersonTrackState:
    track_id: int
    first_seen_at: float
    last_seen_at: float
    last_bbox: tuple[int, int, int, int]
    last_confidence: float
    class_name: str = "person"
    zone_id: str | None = None
    consecutive_seen: int = 1
    consecutive_missed: int = 0
    total_seen: int = 1
    state: str = "PRESENT"
    temporal_confidence: float = 0.0
    last_update_at: float | None = None

    @property
    def center(self) -> tuple[int, int]:
        x1, y1, x2, y2 = self.last_bbox
        return (x1 + x2) // 2, (y1 + y2) // 2

    @property
    def duration_seen(self) -> float:
        return max(0.0, self.last_seen_at - self.first_seen_at)

    @property
    def seconds_since_last_seen(self) -> float:
        reference = self.last_update_at if self.last_update_at is not None else time.monotonic()
        return max(0.0, reference - self.last_seen_at)

    def to_detection(self) -> Detection:
        x1, y1, x2, y2 = self.last_bbox
        return Detection(
            x1=x1,
            y1=y1,
            x2=x2,
            y2=y2,
            confidence=self.temporal_confidence,
            class_name=self.class_name,
            track_id=self.track_id,
        )


class PersonDetector(Protocol):
    model_name: str

    def detect(self, frame: np.ndarray) -> list[Detection]: ...


YOLO_CLASS_IDS = {
    "person": 0,
    "bicycle": 1,
    "car": 2,
    "motorcycle": 3,
    "bus": 5,
    "truck": 7,
}

SUPPORTED_VEHICLE_CLASSES = {"bicycle", "car", "motorcycle", "bus", "truck"}
SPECIALIZED_MODEL_REQUIRED_CLASSES = {"forklift"}


def requested_classes() -> list[str]:
    raw = os.getenv("CAMPEX_YOLO_CLASSES", "person")
    classes = [item.strip().lower() for item in raw.split(",") if item.strip()]
    return [item for item in classes if item in YOLO_CLASS_IDS] or ["person"]


class YoloPersonDetector:
    def __init__(self, model_name: str, confidence: float) -> None:
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise RuntimeError("YOLO indisponível. Instale com: pip install -r requirements-yolo.txt") from exc
        self.model_name = model_name
        self.confidence = confidence
        self.imgsz = int(os.getenv("CAMPEX_YOLO_IMGSZ", "960"))
        self.class_names = requested_classes()
        self.class_ids = [YOLO_CLASS_IDS[name] for name in self.class_names]
        self.id_to_name = {YOLO_CLASS_IDS[name]: name for name in self.class_names}
        self.model = YOLO(model_name)

    def detect(self, frame: np.ndarray) -> list[Detection]:
        results = self.model.predict(source=frame, classes=self.class_ids, conf=self.confidence, imgsz=self.imgsz, verbose=False)
        detections: list[Detection] = []
        for result in results:
            if result.boxes is None:
                continue
            xyxy = result.boxes.xyxy.cpu().numpy()
            confidences = result.boxes.conf.cpu().numpy()
            classes = result.boxes.cls.cpu().numpy() if result.boxes.cls is not None else [0] * len(xyxy)
            for coords, confidence, class_id in zip(xyxy, confidences, classes):
                x1, y1, x2, y2 = map(int, coords)
                detections.append(
                    Detection(
                        x1=x1,
                        y1=y1,
                        x2=x2,
                        y2=y2,
                        confidence=float(confidence),
                        class_name=self.id_to_name.get(int(class_id), "object"),
                    )
                )
        return detections


class CentroidTracker:
    def __init__(
        self,
        max_distance: float = 80.0,
        max_missing: int = 10,
        grace_seconds: float | None = None,
        unknown_seconds: float | None = None,
    ) -> None:
        self.max_distance = max_distance
        self.max_missing = max_missing
        self.grace_seconds = grace_seconds if grace_seconds is not None else float(os.getenv("CAMPEX_TRACK_GRACE_SECONDS", "2.0"))
        self.unknown_seconds = unknown_seconds if unknown_seconds is not None else float(os.getenv("CAMPEX_TRACK_UNKNOWN_SECONDS", "5.0"))
        self._next_id = 1
        self._tracks: dict[int, tuple[int, int]] = {}
        self._missing: dict[int, int] = {}
        self._states: dict[int, PersonTrackState] = {}

    def update(self, detections: list[Detection], now: float | None = None) -> list[Detection]:
        now = time.monotonic() if now is None else now
        unmatched_tracks = set(self._tracks)
        for detection in detections:
            center = detection.center
            best_id = None
            best_distance = self.max_distance
            for track_id in list(unmatched_tracks):
                state = self._states.get(track_id)
                if state is not None and state.class_name != detection.class_name:
                    continue
                previous = self._tracks[track_id]
                distance = hypot(center[0] - previous[0], center[1] - previous[1])
                if distance < best_distance:
                    best_distance = distance
                    best_id = track_id
            if best_id is None:
                best_id = self._next_id
                self._next_id += 1
            else:
                unmatched_tracks.discard(best_id)
            detection.track_id = best_id
            self._tracks[best_id] = center
            self._missing[best_id] = 0
            state = self._states.get(best_id)
            bbox = (int(detection.x1), int(detection.y1), int(detection.x2), int(detection.y2))
            if state is None:
                state = PersonTrackState(
                    track_id=best_id,
                    first_seen_at=now,
                    last_seen_at=now,
                    last_bbox=bbox,
                    last_confidence=float(detection.confidence),
                    class_name=detection.class_name,
                    temporal_confidence=float(detection.confidence),
                    last_update_at=now,
                )
                self._states[best_id] = state
            else:
                state.last_seen_at = now
                state.last_bbox = bbox
                state.last_confidence = float(detection.confidence)
                state.class_name = detection.class_name
                state.consecutive_seen += 1
                state.consecutive_missed = 0
                state.total_seen += 1
                state.state = "PRESENT"
                state.temporal_confidence = float(detection.confidence)
                state.last_update_at = now

        for track_id in unmatched_tracks:
            self._missing[track_id] = self._missing.get(track_id, 0) + 1
            state = self._states.get(track_id)
            if state is not None:
                state.consecutive_missed += 1
                state.consecutive_seen = 0
                state.last_update_at = now
                age = state.seconds_since_last_seen
                if age <= self.grace_seconds:
                    state.state = "PRESENT"
                    state.temporal_confidence = self._decayed_confidence(state.last_confidence, age)
                else:
                    state.state = "UNKNOWN"
                    state.temporal_confidence = 0.0
            if self._missing[track_id] > self.max_missing and (state is None or state.seconds_since_last_seen > self.unknown_seconds):
                self._tracks.pop(track_id, None)
                self._missing.pop(track_id, None)
                self._states.pop(track_id, None)
        return detections

    def active_tracks(self) -> list[PersonTrackState]:
        return [state for state in self._states.values() if state.state == "PRESENT"]

    def track_states(self) -> list[PersonTrackState]:
        return list(self._states.values())

    def recent_detections(self, *, include_inferred: bool = True) -> list[Detection]:
        if not include_inferred:
            return [state.to_detection() for state in self._states.values() if state.consecutive_missed == 0 and state.state == "PRESENT"]
        return [state.to_detection() for state in self.active_tracks()]

    def reset(self) -> None:
        self._tracks.clear()
        self._missing.clear()
        self._states.clear()

    def _decayed_confidence(self, base: float, age: float) -> float:
        if self.grace_seconds <= 0:
            return 0.0
        factor = max(0.0, 1.0 - (age / self.grace_seconds) * 0.5)
        return round(max(0.0, min(1.0, base * factor)), 4)


class PersonAnalysisEngine:
    def __init__(
        self,
        model_name: str | None = None,
        confidence: float | None = None,
        analysis_fps: float | None = None,
        tracking_enabled: bool | None = None,
        detector: PersonDetector | None = None,
    ) -> None:
        self.model_name = model_name or os.getenv("CAMPEX_YOLO_MODEL", "yolo11n.pt")
        self.confidence = confidence if confidence is not None else float(os.getenv("CAMPEX_YOLO_CONFIDENCE", "0.35"))
        self.analysis_fps = analysis_fps if analysis_fps is not None else float(os.getenv("CAMPEX_ANALYSIS_FPS", "2"))
        tracking_env = os.getenv("CAMPEX_TRACKING_ENABLED", "true").lower()
        self.tracking_enabled = tracking_enabled if tracking_enabled is not None else tracking_env in {"1", "true", "sim", "yes"}
        self.detector = detector or get_yolo_detector(self.model_name, self.confidence)
        self.allowed_classes = set(getattr(self.detector, "class_names", requested_classes()))
        self.tracker = CentroidTracker()
        self.last_error: str | None = None
        self.last_track_states: list[PersonTrackState] = []

    def analyze(self, frame: np.ndarray) -> list[Detection]:
        detections = self.detector.detect(frame)
        detections = [detection for detection in detections if detection.class_name in self.allowed_classes]
        if self.tracking_enabled:
            detections = self.tracker.update(detections)
            self.last_track_states = self.tracker.track_states()
        else:
            self.last_track_states = []
        self.last_error = None
        return detections

    def recent_detections(self) -> list[Detection]:
        if not self.tracking_enabled:
            return []
        return self.tracker.recent_detections()

    def draw(self, frame: np.ndarray, detections: list[Detection]) -> np.ndarray:
        annotated = frame.copy()
        for detection in detections:
            cv2.rectangle(annotated, (detection.x1, detection.y1), (detection.x2, detection.y2), (0, 255, 0), 2)
            label_id = detection.track_id if detection.track_id is not None else "-"
            label = f"{detection.class_name} #{label_id} {detection.confidence:.2f}"
            cv2.putText(
                annotated,
                label,
                (detection.x1, max(20, detection.y1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (0, 255, 0),
                2,
                cv2.LINE_AA,
            )
        return annotated


_DETECTOR_LOCK = threading.Lock()
_DETECTORS: dict[tuple[str, float, int, tuple[str, ...]], YoloPersonDetector] = {}


def get_yolo_detector(model_name: str, confidence: float) -> YoloPersonDetector:
    imgsz = int(os.getenv("CAMPEX_YOLO_IMGSZ", "960"))
    key = (model_name, confidence, imgsz, tuple(requested_classes()))
    with _DETECTOR_LOCK:
        detector = _DETECTORS.get(key)
        if detector is None:
            detector = YoloPersonDetector(model_name, confidence)
            _DETECTORS[key] = detector
        return detector


def detector_cache_size() -> int:
    with _DETECTOR_LOCK:
        return len(_DETECTORS)
