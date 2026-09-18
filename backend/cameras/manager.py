from __future__ import annotations

import logging
import base64
import threading
import time
from datetime import datetime
from typing import Any

import cv2

from backend.cameras.base import CameraConfig, CameraSource, FrameResult
from backend.cameras.factory import create_camera_source
from backend.cameras.frame_buffer import (
    LatestFrameBuffer,
    LatestFrameSnapshot,
    LatestFrameStats,
)
from backend.cameras.health import CameraHealth, CameraStatus, utc_now
from backend.cameras.models import Camera
from backend.cameras.repository import CameraRepository
from backend.config import Settings


logger = logging.getLogger("campex.cameras.manager")


class CameraWorker:
    def __init__(
        self,
        camera: Camera,
        settings: Settings,
        source: CameraSource | None = None,
    ) -> None:
        self.camera = camera
        self.settings = settings
        self.source = source or create_camera_source(
            CameraConfig(
                id=camera.id,
                source_type=camera.source_type,
                source_uri=camera.source_uri,
            ),
            settings=self.settings,
        )
        self._stop = threading.Event()
        self._frame_buffer = LatestFrameBuffer()
        self._thread = threading.Thread(
            target=self._run,
            name=f"campex-camera-{camera.id}",
            daemon=True,
        )
        self._last_reported_status: CameraStatus | None = None

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.source.close()
        if self._thread.is_alive():
            self._thread.join(timeout=2)
        if self._thread.is_alive():
            logger.warning(
                "Camera worker did not stop before timeout",
                extra={"camera_id": self.camera.id},
            )

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def health(self) -> CameraHealth:
        health = self.source.health()
        if health.last_successful_frame is None and health.status == CameraStatus.ONLINE:
            health.status = CameraStatus.DEGRADED
            health.connection_state = CameraStatus.DEGRADED.value
            health.last_error = "Connection is open, but no valid frame has been observed."
        if (
            health.status in {CameraStatus.ONLINE, CameraStatus.DEGRADED}
            and health.last_successful_frame is not None
            and (utc_now() - health.last_successful_frame).total_seconds()
            > self.settings.camera_stale_seconds
        ):
            stale_for = (utc_now() - health.last_successful_frame).total_seconds()
            if stale_for >= self.settings.camera_offline_seconds:
                health.status = CameraStatus.OFFLINE
                health.connection_state = CameraStatus.OFFLINE.value
                health.last_disconnected_at = health.last_disconnected_at or utc_now()
                health.last_error = "No valid frame received before offline timeout."
            else:
                health.status = CameraStatus.DEGRADED
                health.connection_state = CameraStatus.DEGRADED.value
                health.last_error = "No recent valid frame received."
        return health

    def latest_frame(self) -> tuple[Any | None, datetime | None]:
        return self._frame_buffer.latest()

    def frame_stats(self) -> LatestFrameStats:
        return self._frame_buffer.stats()

    def latest_snapshot(self) -> LatestFrameSnapshot:
        return self._frame_buffer.snapshot()

    def _run(self) -> None:
        consecutive_failures = 0
        try:
            while not self._stop.is_set():
                if self.source.health().status == CameraStatus.OFFLINE:
                    try:
                        if not self.source.connect():
                            self._stop.wait(self.settings.camera_reconnect_seconds)
                            continue
                    except Exception as exc:
                        health = self.source.health()
                        health.status = CameraStatus.OFFLINE
                        health.last_error = str(exc)
                        logger.exception(
                            "Camera connection failed unexpectedly",
                            extra={"camera_id": self.camera.id},
                        )
                        self._stop.wait(self.settings.camera_reconnect_seconds)
                        continue

                try:
                    result = self.source.read()
                except Exception as exc:
                    health = self.source.health()
                    health.last_error = str(exc)
                    result = FrameResult(success=False, error=str(exc))
                    logger.exception(
                        "Camera frame read failed unexpectedly",
                        extra={"camera_id": self.camera.id},
                    )

                if result.success:
                    self._frame_buffer.put(result.frame, utc_now())
                    consecutive_failures = 0
                    self._log_status_if_changed()
                    self._stop.wait(0.02)
                    continue

                consecutive_failures += 1
                health = self.source.health()
                health.consecutive_failures = consecutive_failures
                if consecutive_failures >= self.settings.camera_read_failure_limit:
                    health.status = CameraStatus.DEGRADED
                    health.connection_state = CameraStatus.DEGRADED.value
                    logger.warning(
                        "[camera:%s] frame_timeout",
                        self.camera.id,
                        extra={
                            "camera_id": self.camera.id,
                            "status": CameraStatus.DEGRADED.value,
                            "error": result.error,
                        },
                    )
                    try:
                        self.source.reconnect()
                    except Exception as exc:
                        health.status = CameraStatus.OFFLINE
                        health.connection_state = CameraStatus.OFFLINE.value
                        health.last_disconnected_at = utc_now()
                        health.last_error = str(exc)
                        logger.exception(
                            "Camera reconnect failed unexpectedly",
                            extra={"camera_id": self.camera.id},
                        )
                    consecutive_failures = 0
                    self._stop.wait(self.settings.camera_reconnect_seconds)
                else:
                    self._stop.wait(0.2)
        except Exception as exc:
            health = self.source.health()
            health.status = CameraStatus.OFFLINE
            health.last_error = str(exc)
            logger.exception("Camera worker failed", extra={"camera_id": self.camera.id})
        finally:
            self.source.close()

    def _log_status_if_changed(self) -> None:
        health = self.health()
        if health.status == self._last_reported_status:
            return
        self._last_reported_status = health.status
        logger.info(
            "[camera:%s] %s",
            self.camera.id,
            health.status.value.lower(),
            extra={"camera_id": self.camera.id, "status": health.status.value},
        )


class CameraManager:
    def __init__(self, settings: Settings, repository: CameraRepository) -> None:
        self.settings = settings
        self.repository = repository
        self._workers: dict[str, CameraWorker] = {}
        self._last_persisted_runtime: dict[str, tuple[float, tuple]] = {}
        self._lock = threading.Lock()

    def start_enabled_cameras(self) -> None:
        for camera in self.repository.list():
            if camera.enabled:
                self.start_camera(camera)

    def start_camera(self, camera: Camera) -> None:
        with self._lock:
            existing = self._workers.get(camera.id)
            if existing is not None and existing.is_alive():
                return
            if existing is not None:
                self._workers.pop(camera.id, None)
            worker = CameraWorker(camera, self.settings)
            self._workers[camera.id] = worker
            worker.start()

    def stop_camera(self, camera_id: str) -> None:
        with self._lock:
            worker = self._workers.pop(camera_id, None)
        if worker:
            worker.stop()

    def restart_camera(self, camera: Camera) -> None:
        self.stop_camera(camera.id)
        if camera.enabled:
            self.start_camera(camera)

    def health(self, camera: Camera) -> CameraHealth:
        with self._lock:
            worker = self._workers.get(camera.id)
        if worker:
            health = worker.health()
        else:
            health = CameraHealth(camera_id=camera.id, status=CameraStatus.OFFLINE)
        self._persist_health(camera.id, health, force=False)
        return health

    def camera_health(self, camera_id: str) -> CameraHealth:
        with self._lock:
            worker = self._workers.get(camera_id)
        if worker:
            health = worker.health()
        else:
            health = CameraHealth(camera_id=camera_id, status=CameraStatus.OFFLINE)
        self._persist_health(camera_id, health, force=False)
        return health

    def latest_frame(self, camera_id: str) -> tuple[Any | None, datetime | None]:
        with self._lock:
            worker = self._workers.get(camera_id)
        if worker is None:
            return None, None
        return worker.latest_frame()

    def frame_stats(self, camera_id: str) -> LatestFrameStats:
        with self._lock:
            worker = self._workers.get(camera_id)
        if worker is None:
            return LatestFrameStats(frames_received=0, frames_replaced=0)
        return worker.frame_stats()

    def latest_frame_snapshot(self, camera_id: str) -> LatestFrameSnapshot:
        with self._lock:
            worker = self._workers.get(camera_id)
        if worker is None:
            return LatestFrameSnapshot(
                frame=None,
                frame_at=None,
                frame_id=0,
                frames_received=0,
                frames_replaced=0,
            )
        return worker.latest_snapshot()

    def is_running(self, camera_id: str) -> bool:
        with self._lock:
            worker = self._workers.get(camera_id)
        return worker is not None and worker.is_alive()

    def shutdown(self) -> None:
        with self._lock:
            camera_ids = list(self._workers)
        for camera_id in camera_ids:
            self.stop_camera(camera_id)

    def _persist_health(
        self,
        camera_id: str,
        health: CameraHealth,
        *,
        force: bool = False,
    ) -> None:
        fingerprint = (
            health.status.value,
            health.connection_state,
            health.last_connected_at.isoformat() if health.last_connected_at else None,
            health.last_disconnected_at.isoformat() if health.last_disconnected_at else None,
            health.consecutive_failures,
        )
        now = time.monotonic()
        previous = self._last_persisted_runtime.get(camera_id)
        if not force and previous is not None:
            persisted_at, previous_fingerprint = previous
            if previous_fingerprint == fingerprint and now - persisted_at < 30:
                return
        try:
            self.repository.update_runtime_state(camera_id, health.as_dict())
            self._last_persisted_runtime[camera_id] = (now, fingerprint)
        except Exception:
            logger.debug(
                "Could not persist camera runtime state",
                extra={"camera_id": camera_id},
                exc_info=True,
            )


def test_camera_connection(camera: Camera, settings: Settings) -> dict:
    source = create_camera_source(
        CameraConfig(
            id=camera.id,
            source_type=camera.source_type,
            source_uri=camera.source_uri,
        ),
        settings=settings,
    )
    deadline = time.monotonic() + settings.camera_test_timeout_seconds
    try:
        if not source.connect():
            health = source.health()
            return {
                "success": False,
                "status": health.status.value,
                "error": health.last_error or "Source could not provide a valid frame.",
                "resolution": None,
            }

        while time.monotonic() < deadline:
            result = source.read()
            if result.success:
                health = source.health()
                resolution = (
                    health.resolution
                    and {
                        "width": health.resolution.width,
                        "height": health.resolution.height,
                    }
                )
                return {
                    "success": True,
                    "status": CameraStatus.ONLINE.value,
                    "error": None,
                    "resolution": resolution,
                    "preview_data_url": _frame_data_url(result.frame),
                }
            time.sleep(0.05)

        health = source.health()
        return {
            "success": False,
            "status": CameraStatus.OFFLINE.value,
            "error": health.last_error or "No valid frame received before timeout.",
            "resolution": None,
        }
    except Exception:
        logger.exception("Camera connection test failed", extra={"camera_id": camera.id})
        return {
            "success": False,
            "status": CameraStatus.OFFLINE.value,
            "error": "Connection test failed. See server logs for details.",
            "resolution": None,
        }
    finally:
        source.close()


def _frame_data_url(frame: Any) -> str | None:
    try:
        ok, encoded = cv2.imencode(".jpg", frame)
        if not ok:
            return None
        payload = base64.b64encode(encoded.tobytes()).decode("ascii")
        return f"data:image/jpeg;base64,{payload}"
    except Exception:
        return None
