from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import cv2

from backend.config import Settings
from backend.operations.video_intelligence import CampexOperationalEngine
from backend.vision.detector import VisionDetector
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

    def analyze(
        self,
        path: Path,
        original_name: str,
        progress_callback=None,
        debug_output_path: Path | None = None,
    ) -> dict[str, Any]:
        source = FileVideoSource(path, original_name)
        detections_out: list[dict[str, Any]] = []
        started_at = datetime.now(timezone.utc)
        debug_writer: cv2.VideoWriter | None = None
        debug_video_path: Path | None = None

        try:
            metadata = source.open()
            if debug_output_path is not None:
                debug_output_path.parent.mkdir(parents=True, exist_ok=True)
                debug_writer = cv2.VideoWriter(
                    str(debug_output_path),
                    cv2.VideoWriter_fourcc(*"mp4v"),
                    max(1.0, float(self.settings.video_analysis_fps)),
                    (metadata.width, metadata.height),
                )
                if debug_writer.isOpened():
                    debug_video_path = debug_output_path
                else:
                    debug_writer.release()
                    debug_writer = None
            operational = CampexOperationalEngine(
                self.settings,
                camera_id="uploaded_video",
                zones=[],
                frame_width=metadata.width,
                frame_height=metadata.height,
            )
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
                operational.process(objects, timestamp_dt)
                if debug_writer is not None:
                    debug_frame = _draw_debug_frame(
                        frame,
                        operational.debug_tracks(objects, timestamp_dt),
                        {
                            "title": "CAMPEX VISION DEBUG",
                            "video_time": timestamp_seconds,
                            "duration": metadata.duration_seconds,
                            "fps_original": metadata.fps,
                            "fps_analysis": self.settings.video_analysis_fps,
                            "visible": operational.people_visible,
                            "tracks_active": len(objects),
                            "moving": sum(
                                1
                                for item in operational.debug_tracks(objects, timestamp_dt)
                                if item["movement_state"] == "MOVING"
                            ),
                            "stationary": sum(
                                1
                                for item in operational.debug_tracks(objects, timestamp_dt)
                                if item["movement_state"] == "STATIONARY"
                            ),
                            "events": len(operational.events),
                            "detector": self.detector.name,
                            "model": getattr(self.detector, "model_name", None) or "-",
                            "device": self.detector.device.lower(),
                            "fallback": getattr(self.detector, "fallback_used", False),
                            "tracker": self.tracker.name,
                        },
                    )
                    debug_writer.write(debug_frame)
                if metadata.frame_count:
                    progress = min(90, 5 + int((frame_index / metadata.frame_count) * 85))
                    if progress_callback:
                        progress_callback(progress)
            operational.close(started_at + timedelta(seconds=metadata.duration_seconds))
            result = operational.as_result(metadata.as_dict())
            metrics = result["metrics"]
            metrics.setdefault("summary", {})
            metrics["summary"]["total_detections"] = len(detections_out)
            metrics["summary"]["unique_objects"] = metrics["summary"].get("unique_people", 0)
            runtime = {
                "detector": self.detector.name,
                "model": getattr(self.detector, "model_name", None),
                "device": self.detector.device.lower(),
                "fallback": bool(getattr(self.detector, "fallback_used", False)),
                "reason": getattr(self.detector, "fallback_reason", None),
                "tracker": self.tracker.name,
                "analysis_fps": self.settings.video_analysis_fps,
                "original_fps": metadata.fps,
                "input_resolution": getattr(self.detector, "input_resolution", None),
                "debug_overlay": debug_video_path is not None,
            }
            return {
                "source": metadata.as_dict(),
                "detections": detections_out[-500:],
                "tracks": result["tracks"],
                "events": result["events"],
                "timeline": result["timeline"],
                "metrics": metrics,
                "runtime": runtime,
                "debug_video_path": str(debug_video_path) if debug_video_path else None,
                "operational_context": result["operational_context"],
            }
        finally:
            if debug_writer is not None:
                debug_writer.release()
            source.close()


def _draw_debug_frame(frame, tracks: list[dict[str, Any]], panel: dict[str, Any]):
    output = frame.copy()
    for item in tracks:
        x1, y1, x2, y2 = [int(value) for value in item["bbox"]]
        state = item["movement_state"]
        color = (0, 220, 80)
        if state == "STATIONARY":
            color = (0, 190, 255)
        elif state == "POTENTIAL_STATIONARY":
            color = (0, 230, 230)
        elif state == "UNKNOWN":
            color = (180, 180, 180)
        cv2.rectangle(output, (x1, y1), (x2, y2), color, 2)
        label_state = state
        if state in {"STATIONARY", "POTENTIAL_STATIONARY"}:
            label_state = f"{state} {_format_mmss(item['state_seconds'])}"
        label = (
            f"PERSON #{item['track_id']} | {label_state} | "
            f"{item['confidence'] * 100:.0f}%"
        )
        zone = item.get("zone")
        if zone:
            label = f"{label} | ZONE: {zone}"
        _draw_label(output, label, x1, max(18, y1 - 8), color)
        trajectory = item.get("trajectory") or []
        for first, second in zip(trajectory, trajectory[1:]):
            cv2.line(
                output,
                (int(first["x"]), int(first["y"])),
                (int(second["x"]), int(second["y"])),
                color,
                2,
                cv2.LINE_AA,
            )
        if trajectory:
            last = trajectory[-1]
            cv2.circle(output, (int(last["x"]), int(last["y"])), 4, color, -1)
    _draw_panel(output, panel)
    return output


def _draw_label(frame, text: str, x: int, y: int, color) -> None:
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 0.55
    thickness = 1
    (width, height), _ = cv2.getTextSize(text, font, scale, thickness)
    cv2.rectangle(
        frame,
        (x, max(0, y - height - 8)),
        (min(frame.shape[1] - 1, x + width + 10), y + 4),
        (0, 0, 0),
        -1,
    )
    cv2.putText(frame, text, (x + 5, y - 3), font, scale, color, thickness, cv2.LINE_AA)


def _draw_panel(frame, panel: dict[str, Any]) -> None:
    rows = [
        panel["title"],
        f"Video: {_format_mmss(panel['video_time'])} / {_format_mmss(panel['duration'])}",
        f"FPS original: {panel['fps_original']:.2f}",
        f"FPS analise: {panel['fps_analysis']:.2f}",
        f"Visible: {panel['visible']} | Tracks ativos: {panel['tracks_active']}",
        f"Moving: {panel['moving']} | Stationary: {panel['stationary']}",
        f"Eventos: {panel['events']}",
        f"Detector: {panel['detector']}",
        f"Model: {panel.get('model') or '-'}",
        f"Device: {panel['device']} | Fallback: {str(panel['fallback']).lower()}",
        f"Tracker: {panel['tracker']}",
    ]
    x, y = 16, 24
    width = 430
    height = 26 + len(rows) * 22
    overlay = frame.copy()
    cv2.rectangle(overlay, (8, 8), (8 + width, 8 + height), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.68, frame, 0.32, 0, frame)
    for index, row in enumerate(rows):
        color = (255, 255, 255) if index else (0, 255, 180)
        cv2.putText(
            frame,
            row,
            (x, y + index * 22),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            1,
            cv2.LINE_AA,
        )


def _format_mmss(seconds: float) -> str:
    total = max(0, int(seconds))
    return f"{total // 60:02d}:{total % 60:02d}"
