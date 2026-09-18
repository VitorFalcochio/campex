from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from urllib.parse import urlsplit

import cv2

from backend.cameras.base import CameraConfig, CameraSource, FrameResult
from backend.cameras.health import CameraHealth, CameraStatus, Resolution, utc_now
from backend.cameras.security import sanitize_source_uri


logger = logging.getLogger("campex.cameras")


class OpenCVCameraSource(CameraSource):
    def __init__(
        self,
        config: CameraConfig,
        capture_target: int | str,
        *,
        prefer_ffmpeg: bool = False,
    ) -> None:
        super().__init__(config)
        self.capture_target = capture_target
        self.prefer_ffmpeg = prefer_ffmpeg
        self.capture: cv2.VideoCapture | None = None
        self._health = CameraHealth(
            camera_id=config.id,
            status=CameraStatus.OFFLINE,
        )
        self._first_frame_logged = False

    def connect(self) -> bool:
        self.close()
        self._health.status = CameraStatus.CONNECTING
        self._health.connection_state = CameraStatus.CONNECTING.value
        safe_uri = sanitize_source_uri(str(self.config.source_uri))
        logger.info(
            "[camera:%s] reconnect_attempt=%s",
            self.config.id,
            self._health.reconnect_attempts,
            extra={"camera_id": self.config.id, "source_uri": safe_uri},
        )

        self._prepare_backend()
        capture = self._open_capture()
        self._configure_capture(capture)
        self.capture = capture

        if not capture.isOpened():
            self._health.status = CameraStatus.OFFLINE
            self._health.connection_state = CameraStatus.OFFLINE.value
            self._health.last_disconnected_at = utc_now()
            self._health.last_error = "Capture could not be opened."
            logger.warning(
                "[camera:%s] offline",
                self.config.id,
                extra={"camera_id": self.config.id, "source_uri": safe_uri},
            )
            return False

        frame_result = self.read()
        if not frame_result.success:
            self._health.status = CameraStatus.OFFLINE
            self._health.connection_state = CameraStatus.OFFLINE.value
            self._health.last_disconnected_at = utc_now()
            self._health.last_error = frame_result.error or "No valid frame received."
            logger.warning(
                "[camera:%s] frame_timeout",
                self.config.id,
                extra={"camera_id": self.config.id, "source_uri": safe_uri},
            )
            return False

        self._health.status = CameraStatus.ONLINE
        self._health.connection_state = CameraStatus.ONLINE.value
        self._health.last_connected_at = utc_now()
        self._health.last_error = None
        logger.info(
            "[camera:%s] connected",
            self.config.id,
            extra={"camera_id": self.config.id, "source_uri": safe_uri},
        )
        return True

    def read(self) -> FrameResult:
        if self.capture is None or not self.capture.isOpened():
            self._health.status = CameraStatus.OFFLINE
            self._health.connection_state = CameraStatus.OFFLINE.value
            self._health.last_disconnected_at = utc_now()
            self._health.last_error = "Capture is not open."
            return FrameResult(success=False, error=self._health.last_error)

        success, frame = self.capture.read()
        if not success or frame is None or getattr(frame, "size", 0) == 0:
            self._health.consecutive_failures += 1
            self._health.last_error = "No valid frame received."
            return FrameResult(success=False, error=self._health.last_error)

        height, width = frame.shape[:2]
        self._health.last_successful_frame = utc_now()
        self._health.resolution = Resolution(width=int(width), height=int(height))
        self._health.frames_received += 1
        fps = float(self.capture.get(cv2.CAP_PROP_FPS) or 0)
        self._health.approximate_fps = fps if fps > 0 else None
        self._health.status = CameraStatus.ONLINE
        self._health.connection_state = CameraStatus.ONLINE.value
        self._health.consecutive_failures = 0
        self._health.last_error = None
        if not self._first_frame_logged:
            logger.info(
                "[camera:%s] first_frame_received",
                self.config.id,
                extra={"camera_id": self.config.id},
            )
            self._first_frame_logged = True
        return FrameResult(success=True, frame=frame)

    def reconnect(self) -> bool:
        self._health.reconnect_attempts += 1
        logger.info(
            "[camera:%s] reconnect_attempt=%s",
            self.config.id,
            self._health.reconnect_attempts,
            extra={"camera_id": self.config.id},
        )
        self.close()
        time.sleep(0.05)
        return self.connect()

    def close(self) -> None:
        if self.capture is not None:
            self.capture.release()
            self.capture = None
        if self._health.status != CameraStatus.OFFLINE:
            self._health.status = CameraStatus.OFFLINE
            self._health.connection_state = CameraStatus.OFFLINE.value
            self._health.last_disconnected_at = utc_now()
            logger.info("[camera:%s] offline", self.config.id, extra={"camera_id": self.config.id})

    def health(self) -> CameraHealth:
        return self._health

    def _configure_capture(self, capture: cv2.VideoCapture) -> None:
        try:
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            capture.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 3000)
            capture.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 3000)
        except Exception:
            logger.debug("OpenCV timeout properties are not available.")

    def _open_capture(self) -> cv2.VideoCapture:
        if self.prefer_ffmpeg and isinstance(self.capture_target, str):
            return cv2.VideoCapture(self.capture_target, cv2.CAP_FFMPEG)
        return cv2.VideoCapture(self.capture_target)

    def _prepare_backend(self) -> None:
        if not self.prefer_ffmpeg:
            return
        # Prefer TCP for RTSP because packet loss over UDP tends to break
        # detection/tracking more often than a small latency increase.
        os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")


class WebcamSource(OpenCVCameraSource):
    def __init__(self, config: CameraConfig) -> None:
        try:
            capture_target: int | str = int(config.source_uri)
        except ValueError:
            capture_target = config.source_uri
        super().__init__(config, capture_target)


class VideoFileSource(OpenCVCameraSource):
    def __init__(self, config: CameraConfig, loop: bool = False) -> None:
        super().__init__(config, str(Path(config.source_uri)))
        self._loop = loop

    def read(self) -> FrameResult:
        result = super().read()
        if result.success:
            return result

        if self.capture is not None and self.capture.isOpened():
            self._health.status = CameraStatus.OFFLINE
            self._health.last_error = "End of video or no valid frame received."
            if self._loop:
                logger.debug(
                    "Looping video file", extra={"camera_id": self.config.id}
                )
                self._health.status = CameraStatus.CONNECTING
                self._health.last_error = None
                if self.capture is not None:
                    self.capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                loop_result = super().read()
                if loop_result.success:
                    self._health.status = CameraStatus.ONLINE
                    return loop_result
            return FrameResult(success=False, error=self._health.last_error)

        return result


class RTSPSource(OpenCVCameraSource):
    def __init__(self, config: CameraConfig) -> None:
        super().__init__(config, config.source_uri, prefer_ffmpeg=True)


class IPCameraSource(OpenCVCameraSource):
    def __init__(self, config: CameraConfig) -> None:
        super().__init__(config, config.source_uri, prefer_ffmpeg=True)

    def connect(self) -> bool:
        parsed = urlsplit(self.config.source_uri)
        if parsed.scheme.lower() not in {"http", "https", "rtsp"}:
            self._health.status = CameraStatus.OFFLINE
            self._health.last_error = (
                "IP camera source must start with http://, https:// or rtsp://."
            )
            return False
        return super().connect()
