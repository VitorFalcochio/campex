from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import cv2

from backend.config import Settings
from backend.vision.detector import VisionDetector
from backend.vision.models import TrackedObject
from backend.vision.tracker import ByteTrackTracker, ObjectTracker
from backend.videos.models import VideoMetadata


class InvalidVideoError(ValueError):
    pass


class FileVideoSource:
    def __init__(self, path: Path, name: str) -> None:
        self.path = path
        self.name = name
        self.capture: cv2.VideoCapture | None = None
        self.metadata: VideoMetadata | None = None

    def open(self) -> VideoMetadata:
        self.capture = cv2.VideoCapture(str(self.path))
        if not self.capture.isOpened():
            raise InvalidVideoError("Video file could not be opened.")
        fps = float(self.capture.get(cv2.CAP_PROP_FPS) or 0)
        width = int(self.capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(self.capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        frame_count = int(self.capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if width <= 0 or height <= 0 or frame_count <= 0:
            raise InvalidVideoError("Video metadata is invalid or incomplete.")
        effective_fps = fps if fps > 0 else 30.0
        duration = frame_count / effective_fps if effective_fps else 0.0
        self.metadata = VideoMetadata("video_file", self.name, effective_fps, width, height, frame_count, duration)
        return self.metadata

    def frames(self, sample_fps: float):
        if self.capture is None or self.metadata is None:
            self.open()
        assert self.capture is not None
        assert self.metadata is not None
        step = max(1, int(round(self.metadata.fps / sample_fps)))
        frame_index = 0
        while True:
            ok, frame = self.capture.read()
            if not ok or frame is None:
                break
            if frame_index % step == 0:
                timestamp = frame_index / self.metadata.fps
                yield frame_index, timestamp, frame
            frame_index += 1

    def close(self) -> None:
        if self.capture is not None:
            self.capture.release()
            self.capture = None


class VideoAnalysisPipeline:
    def __init__(
        self,
        settings: Settings,
        detector: VisionDetector,
        tracker: ObjectTracker | None = None,
    ) -> None:
        self.settings = settings
        self.detector = detector
        self.tracker = tracker or ByteTrackTracker(
            iou_threshold=0.1,
            max_missed=settings.vision_tracker_lost_buffer,
            minimum_consecutive_frames=1,
        )

    def analyze(self, path: Path, original_name: str, progress_callback=None) -> dict[str, Any]:
        source = FileVideoSource(path, original_name)
        detections_out: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []
        tracks: dict[int, dict[str, Any]] = {}
        last_positions: dict[int, tuple[float, float, float]] = {}
        active_track_ids: set[int] = set()
        started_at = datetime.now(timezone.utc)

        try:
            metadata = source.open()
            if progress_callback:
                progress_callback(5, source=metadata.as_dict())
            for frame_index, timestamp_seconds, frame in source.frames(self.settings.video_analysis_fps):
                detections, _ = self.detector.detect(frame)
                timestamp_dt = started_at + timedelta(seconds=timestamp_seconds)
                objects = self.tracker.update("uploaded_video", detections, timestamp_dt)
                for detection in detections:
                    detections_out.append(
                        {
                            "class": detection.class_name,
                            "confidence": detection.confidence,
                            "bbox": detection.bounding_box.as_list(),
                            "timestamp": round(timestamp_seconds, 3),
                        }
                    )
                _update_tracks(tracks, events, last_positions, active_track_ids, objects, timestamp_seconds)
                if metadata.frame_count:
                    progress = min(90, 5 + int((frame_index / metadata.frame_count) * 85))
                    if progress_callback:
                        progress_callback(progress)
            _close_open_tracks(tracks, events, active_track_ids, metadata.duration_seconds)
            metrics = _build_metrics(metadata, tracks, events, detections_out)
            return {
                "source": metadata.as_dict(),
                "detections": detections_out[-500:],
                "tracks": list(tracks.values()),
                "events": events,
                "metrics": metrics,
                "operational_context": {
                    "schema": "campex_video_operational_context.v1",
                    "source": metadata.as_dict(),
                    "metrics": metrics,
                    "summary": metrics["summary"],
                    "movement": metrics["movement"],
                    "timeline": events[:200],
                },
            }
        finally:
            source.close()


def _update_tracks(
    tracks: dict[int, dict[str, Any]],
    events: list[dict[str, Any]],
    last_positions: dict[int, tuple[float, float, float]],
    active_track_ids: set[int],
    objects: list[TrackedObject],
    timestamp: float,
) -> None:
    seen_now = set()
    for obj in objects:
        seen_now.add(obj.track_id)
        bbox = obj.bounding_box.as_list()
        cx = (bbox[0] + bbox[2]) / 2
        cy = (bbox[1] + bbox[3]) / 2
        track = tracks.get(obj.track_id)
        if track is None:
            track = {
                "track_id": obj.track_id,
                "class": obj.class_name,
                "first_timestamp": round(timestamp, 3),
                "last_timestamp": round(timestamp, 3),
                "duration_seconds": 0.0,
                "confidence": obj.confidence,
                "positions": [],
                "state": "active",
            }
            tracks[obj.track_id] = track
            active_track_ids.add(obj.track_id)
            events.append(_event("PERSON_ENTERED" if obj.class_name == "person" else "OBJECT_ENTERED", obj.track_id, timestamp))
        previous = last_positions.get(obj.track_id)
        if previous:
            px, py, previous_ts = previous
            distance = ((cx - px) ** 2 + (cy - py) ** 2) ** 0.5
            elapsed = max(0.001, timestamp - previous_ts)
            moving = distance / elapsed > 8.0
            if moving and track.get("movement_state") != "moving":
                events.append(_event("PERSON_STARTED_MOVING", obj.track_id, timestamp))
                track["movement_state"] = "moving"
            elif not moving and track.get("movement_state") == "moving":
                events.append(_event("PERSON_STOPPED", obj.track_id, timestamp))
                track["movement_state"] = "stopped"
        last_positions[obj.track_id] = (cx, cy, timestamp)
        track["last_timestamp"] = round(timestamp, 3)
        track["duration_seconds"] = round(timestamp - track["first_timestamp"], 3)
        track["confidence"] = max(track["confidence"], obj.confidence)
        if len(track["positions"]) < 25:
            track["positions"].append({"timestamp": round(timestamp, 3), "bbox": bbox})

    disappeared = active_track_ids - seen_now
    for track_id in list(disappeared):
        track = tracks.get(track_id)
        if track and track["state"] == "active":
            track["state"] = "inactive"
            events.append(_event("PERSON_LEFT" if track["class"] == "person" else "OBJECT_LEFT", track_id, timestamp))
        active_track_ids.discard(track_id)


def _close_open_tracks(tracks: dict[int, dict[str, Any]], events: list[dict[str, Any]], active_track_ids: set[int], timestamp: float) -> None:
    for track_id in list(active_track_ids):
        track = tracks.get(track_id)
        if track:
            track["state"] = "inactive"
            events.append(_event("PERSON_LEFT" if track["class"] == "person" else "OBJECT_LEFT", track_id, timestamp))
    events.append({"event_type": "VIDEO_FINISHED", "timestamp": round(timestamp, 3), "metadata": {}})


def _build_metrics(metadata: VideoMetadata, tracks: dict[int, dict[str, Any]], events: list[dict[str, Any]], detections: list[dict[str, Any]]) -> dict[str, Any]:
    by_class = defaultdict(int)
    for track in tracks.values():
        by_class[track["class"]] += 1
    return {
        "source": metadata.as_dict(),
        "summary": {
            "unique_people": by_class.get("person", 0),
            "unique_objects": len(tracks),
            "total_detections": len(detections),
            "total_events": len(events),
        },
        "movement": {
            "moving_events": sum(1 for event in events if event["event_type"].endswith("STARTED_MOVING")),
            "stopped_events": sum(1 for event in events if event["event_type"].endswith("STOPPED")),
            "average_track_duration_seconds": round(
                sum(track["duration_seconds"] for track in tracks.values()) / max(1, len(tracks)),
                3,
            ),
        },
        "zones": {},
        "timeline": events[:200],
    }


def _event(event_type: str, track_id: int, timestamp: float) -> dict[str, Any]:
    return {
        "event_type": event_type,
        "track_id": track_id,
        "timestamp": round(timestamp, 3),
        "metadata": {},
    }
