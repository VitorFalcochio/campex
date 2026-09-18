from __future__ import annotations

from fastapi import APIRouter

from backend.config import get_settings


router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    settings = get_settings()
    return {
        "status": "ok",
        "service": settings.service_name,
        "version": settings.version,
    }


@router.get("/settings/runtime")
def runtime_settings() -> dict:
    settings = get_settings()
    return {
        "environment": settings.environment,
        "service_name": settings.service_name,
        "version": settings.version,
        "log_level": settings.log_level,
        "database_url": settings.database_url,
        "frontend_origins": settings.frontend_origins,
        "camera": {
            "reconnect_seconds": settings.camera_reconnect_seconds,
            "stale_seconds": settings.camera_stale_seconds,
            "read_failure_limit": settings.camera_read_failure_limit,
            "test_timeout_seconds": settings.camera_test_timeout_seconds,
        },
        "vision": {
            "enabled": settings.vision_enabled,
            "detector": settings.vision_detector,
            "device": settings.vision_device,
            "fps": settings.vision_fps,
            "confidence": settings.vision_confidence,
            "video_loop": settings.vision_video_loop,
            "full_scan_seconds": settings.vision_full_scan_seconds,
            "tracker_lost_buffer": settings.vision_tracker_lost_buffer,
        },
        "video_analysis": {
            "upload_dir": settings.video_upload_dir,
            "max_upload_mb": settings.video_max_upload_mb,
            "analysis_fps": settings.video_analysis_fps,
            "temporary_retention_hours": settings.video_temporary_retention_hours,
        },
    }
