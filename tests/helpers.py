from __future__ import annotations

from pathlib import Path

from backend.config import Settings


def make_settings(database_path: Path) -> Settings:
    return Settings(
        environment="test",
        service_name="campex",
        version="0.1.0",
        log_level="INFO",
        database_url=f"sqlite:///{database_path}",
        frontend_origins=["http://127.0.0.1:5500"],
        camera_reconnect_seconds=0.01,
        camera_stale_seconds=0.1,
        camera_offline_seconds=0.3,
        camera_read_failure_limit=1,
        camera_test_timeout_seconds=1,
        vision_enabled=True,
        vision_detector="rfdetr",
        vision_device="auto",
        vision_fps=5,
        vision_confidence=0.5,
        vision_video_loop=False,
    )
