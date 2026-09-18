import time
from datetime import timedelta

from backend.cameras.base import FrameResult
from backend.cameras.health import CameraHealth, CameraStatus, utc_now
from backend.cameras.manager import CameraWorker
from backend.cameras.models import Camera
from tests.helpers import make_settings


class FailingSource:
    def __init__(self):
        self.closed = False
        self.reconnects = 0
        self._health = CameraHealth("cam_fail", CameraStatus.OFFLINE)

    def connect(self):
        self._health.status = CameraStatus.ONLINE
        return True

    def read(self):
        return FrameResult(success=False, error="synthetic frame failure")

    def reconnect(self):
        self.reconnects += 1
        self._health.reconnect_attempts += 1
        return False

    def close(self):
        self.closed = True
        self._health.status = CameraStatus.OFFLINE

    def health(self):
        return self._health


def test_camera_worker_reconnects_and_closes_on_failure(tmp_path):
    camera = Camera(
        id="cam_fail",
        name="Failing camera",
        area_id=None,
        source_type="video_file",
        source_uri="missing.mp4",
        enabled=True,
        vision_enabled=False,
        status="OFFLINE",
        created_at="2026-09-09 00:00:00",
        updated_at="2026-09-09 00:00:00",
    )
    source = FailingSource()
    worker = CameraWorker(camera, make_settings(tmp_path / "manager.sqlite3"), source)

    worker.start()
    deadline = time.monotonic() + 1
    while source.reconnects == 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    worker.stop()

    assert source.closed is True
    assert source.reconnects >= 1


def test_camera_worker_reports_online_when_recent_frame_exists(tmp_path):
    camera = Camera(
        id="cam_online",
        name="Online camera",
        area_id=None,
        source_type="video_file",
        source_uri="ok.mp4",
        enabled=True,
        vision_enabled=False,
        status="OFFLINE",
        created_at="2026-09-09 00:00:00",
        updated_at="2026-09-09 00:00:00",
    )
    source = FailingSource()
    source._health = CameraHealth(
        "cam_online",
        CameraStatus.ONLINE,
        last_successful_frame=utc_now(),
        last_connected_at=utc_now(),
        connection_state="ONLINE",
        frames_received=1,
    )
    worker = CameraWorker(camera, make_settings(tmp_path / "manager-online.sqlite3"), source)

    health = worker.health()

    assert health.status == CameraStatus.ONLINE
    assert health.last_successful_frame is not None


def test_camera_worker_degrades_and_then_offlines_when_frames_stall(tmp_path):
    camera = Camera(
        id="cam_stale",
        name="Stale camera",
        area_id=None,
        source_type="video_file",
        source_uri="stale.mp4",
        enabled=True,
        vision_enabled=False,
        status="OFFLINE",
        created_at="2026-09-09 00:00:00",
        updated_at="2026-09-09 00:00:00",
    )
    source = FailingSource()
    settings = make_settings(tmp_path / "manager-stale.sqlite3")
    source._health = CameraHealth(
        "cam_stale",
        CameraStatus.ONLINE,
        last_successful_frame=utc_now() - timedelta(seconds=settings.camera_stale_seconds + 0.01),
        last_connected_at=utc_now(),
        connection_state="ONLINE",
    )
    worker = CameraWorker(camera, settings, source)
    assert worker.health().status == CameraStatus.DEGRADED

    source._health.status = CameraStatus.ONLINE
    source._health.last_successful_frame = utc_now() - timedelta(seconds=settings.camera_offline_seconds + 0.01)
    assert worker.health().status == CameraStatus.OFFLINE
