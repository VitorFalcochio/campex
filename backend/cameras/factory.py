from __future__ import annotations

from backend.cameras.base import CameraConfig, CameraSource
from backend.cameras.opencv_source import (
    IPCameraSource,
    RTSPSource,
    VideoFileSource,
    WebcamSource,
)
from backend.config import Settings


def create_camera_source(config: CameraConfig, settings: Settings | None = None) -> CameraSource:
    if config.source_type == "webcam":
        return WebcamSource(config)
    if config.source_type == "video_file":
        loop = settings.vision_video_loop if settings is not None else False
        return VideoFileSource(config, loop=loop)
    if config.source_type == "rtsp":
        return RTSPSource(config)
    if config.source_type == "ip_camera":
        return IPCameraSource(config)
    raise ValueError(f"Unsupported camera source type: {config.source_type}")
