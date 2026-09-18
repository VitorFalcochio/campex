from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Iterator, Union
from urllib.parse import urlsplit, urlunsplit

import cv2


class SourceType(str, Enum):
    FILE = "file"
    WEBCAM = "webcam"
    RTSP = "rtsp"
    ONVIF = "onvif"
    UNKNOWN = "unknown"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def detect_source_type(source: str | int) -> SourceType:
    if isinstance(source, int):
        return SourceType.WEBCAM
    value = str(source).strip()
    if value.isdigit():
        return SourceType.WEBCAM
    lowered = value.lower()
    if lowered.startswith(("rtsp://", "rtsps://")):
        return SourceType.RTSP
    if lowered.startswith("onvif://"):
        return SourceType.ONVIF
    if lowered.endswith((".mp4", ".mov", ".avi", ".mkv", ".m4v")):
        return SourceType.FILE
    return SourceType.UNKNOWN


def normalize_source(source: str | int) -> str | int:
    if isinstance(source, int):
        return source
    value = str(source).strip()
    return int(value) if value.isdigit() else value


def safe_source_ref(source: str | int) -> str:
    if isinstance(source, int):
        return str(source)
    value = str(source)
    parsed = urlsplit(value)
    if parsed.scheme and parsed.netloc:
        hostname = parsed.hostname or ""
        port = f":{parsed.port}" if parsed.port else ""
        netloc = f"***:***@{hostname}{port}" if parsed.username or parsed.password else parsed.netloc
        return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))
    return value


@dataclass
class FrameInfo:
    camera_id: str
    status: str = "offline"
    last_frame_at: str | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    error: str | None = None


@dataclass(frozen=True)
class CameraSource:
    camera_id: str
    source: str | int
    cliente_id: str | None = None
    unidade_id: str | None = None
    edge_id: str | None = None
    name: str | None = None
    reconnect_seconds: float = 5.0

    @property
    def source_type(self) -> SourceType:
        return detect_source_type(self.source)

    @property
    def safe_ref(self) -> str:
        return safe_source_ref(self.source)


CaptureFactory = Callable[[Union[str, int]], cv2.VideoCapture]


def default_capture_factory(source: str | int) -> cv2.VideoCapture:
    if isinstance(source, str) and source.lower().startswith(("rtsp://", "rtsps://")):
        os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|stimeout;5000000")
        return cv2.VideoCapture(source, cv2.CAP_FFMPEG)
    return cv2.VideoCapture(source)


class UniversalCameraConnector:
    def __init__(
        self,
        camera: CameraSource,
        capture_factory: CaptureFactory = default_capture_factory,
    ) -> None:
        self.camera = camera
        self.capture_factory = capture_factory
        self.capture: cv2.VideoCapture | None = None
        self.info = FrameInfo(camera_id=camera.camera_id)
        self._stopped = False

    def open(self) -> bool:
        self.close()
        source = normalize_source(self.camera.source)
        self.capture = self.capture_factory(source)
        if not self.capture or not self.capture.isOpened():
            self.info.status = "offline"
            self.info.error = "Nao foi possivel abrir a fonte de video."
            return False
        self.info.status = "online"
        self.info.error = None
        self.info.width = int(self.capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0) or None
        self.info.height = int(self.capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0) or None
        fps = float(self.capture.get(cv2.CAP_PROP_FPS) or 0.0)
        self.info.fps = round(fps, 2) if fps > 0 else None
        return True

    def close(self) -> None:
        if self.capture is not None:
            self.capture.release()
        self.capture = None

    def stop(self) -> None:
        self._stopped = True
        self.close()

    def frames(self) -> Iterator[object]:
        while not self._stopped:
            if self.capture is None or not self.capture.isOpened():
                if not self.open():
                    time.sleep(self.camera.reconnect_seconds)
                    continue
            ok, frame = self.capture.read()
            if ok and frame is not None:
                self.info.status = "online"
                self.info.last_frame_at = now_iso()
                self.info.height, self.info.width = frame.shape[:2]
                self.info.error = None
                yield frame
                continue
            self.info.status = "offline"
            self.info.error = "Stream parou de entregar frames."
            self.close()
            time.sleep(self.camera.reconnect_seconds)
