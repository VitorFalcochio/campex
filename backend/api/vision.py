from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import cv2
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse

from backend.cameras.manager import CameraManager
from backend.cameras.repository import CameraRepository
from backend.config import ROOT_DIR, get_settings
from backend.security import OrganizationScope, get_organization_scope
from backend.vision.engine import VisionEngine
from backend.vision.overlay import OverlayRenderer


router = APIRouter(prefix="/api/v1/cameras", tags=["vision"])
overlay_renderer = OverlayRenderer()
logger = logging.getLogger("campex.api.vision")


def get_repository() -> CameraRepository:
    return CameraRepository(get_settings())


def get_camera_manager(request: Request) -> CameraManager:
    return request.app.state.camera_manager


def get_vision_engine(request: Request) -> VisionEngine:
    return request.app.state.vision_engine


def ensure_camera(camera_id: str, repository: CameraRepository, scope: OrganizationScope) -> Camera:
    camera = repository.get(camera_id, scope.organization_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found.")
    return camera


@router.post("/{camera_id}/vision/start")
def start_vision(
    camera_id: str,
    scope: OrganizationScope = Depends(get_organization_scope),
    repository: CameraRepository = Depends(get_repository),
    manager: CameraManager = Depends(get_camera_manager),
    engine: VisionEngine = Depends(get_vision_engine),
) -> dict:
    camera = ensure_camera(camera_id, repository, scope)
    if not manager.is_running(camera_id):
        manager.start_camera(camera)
    return engine.start_session(camera_id)


@router.post("/{camera_id}/vision/restart")
def restart_vision(
    camera_id: str,
    scope: OrganizationScope = Depends(get_organization_scope),
    repository: CameraRepository = Depends(get_repository),
    manager: CameraManager = Depends(get_camera_manager),
    engine: VisionEngine = Depends(get_vision_engine),
) -> dict:
    camera = ensure_camera(camera_id, repository, scope)
    manager.restart_camera(camera)
    return engine.restart_session(camera_id)


@router.post("/{camera_id}/vision/stop")
def stop_vision(
    camera_id: str,
    scope: OrganizationScope = Depends(get_organization_scope),
    repository: CameraRepository = Depends(get_repository),
    engine: VisionEngine = Depends(get_vision_engine),
) -> dict:
    ensure_camera(camera_id, repository, scope)
    return engine.stop_session(camera_id)


@router.post("/{camera_id}/mapping/start")
def start_mapping(
    camera_id: str,
    scope: OrganizationScope = Depends(get_organization_scope),
    repository: CameraRepository = Depends(get_repository),
    manager: CameraManager = Depends(get_camera_manager),
    engine: VisionEngine = Depends(get_vision_engine),
) -> dict:
    camera = ensure_camera(camera_id, repository, scope)
    if not manager.is_running(camera_id):
        manager.start_camera(camera)
    return engine.start_mapping(camera_id)


@router.post("/{camera_id}/mapping/stop")
def stop_mapping(
    camera_id: str,
    scope: OrganizationScope = Depends(get_organization_scope),
    repository: CameraRepository = Depends(get_repository),
    engine: VisionEngine = Depends(get_vision_engine),
) -> dict:
    ensure_camera(camera_id, repository, scope)
    return engine.stop_mapping(camera_id)


@router.get("/{camera_id}/vision/status")
def vision_status(
    camera_id: str,
    scope: OrganizationScope = Depends(get_organization_scope),
    repository: CameraRepository = Depends(get_repository),
    engine: VisionEngine = Depends(get_vision_engine),
) -> dict:
    ensure_camera(camera_id, repository, scope)
    return engine.status(camera_id)


@router.get("/{camera_id}/vision/objects")
def vision_objects(
    camera_id: str,
    scope: OrganizationScope = Depends(get_organization_scope),
    repository: CameraRepository = Depends(get_repository),
    engine: VisionEngine = Depends(get_vision_engine),
) -> list[dict]:
    ensure_camera(camera_id, repository, scope)
    return [tracked.as_dict() for tracked in engine.objects(camera_id)]


@router.get("/{camera_id}/mapping/poses")
def mapping_poses(
    camera_id: str,
    scope: OrganizationScope = Depends(get_organization_scope),
    repository: CameraRepository = Depends(get_repository),
    engine: VisionEngine = Depends(get_vision_engine),
) -> list[dict]:
    ensure_camera(camera_id, repository, scope)
    return [pose.as_dict() for pose in engine.poses(camera_id)]


@router.get("/{camera_id}/vision/events")
def vision_events(
    camera_id: str,
    scope: OrganizationScope = Depends(get_organization_scope),
    repository: CameraRepository = Depends(get_repository),
    engine: VisionEngine = Depends(get_vision_engine),
) -> list[dict]:
    ensure_camera(camera_id, repository, scope)
    return [e.as_dict() for e in engine.events(camera_id)]


@router.get("/{camera_id}/productivity")
def camera_productivity(
    camera_id: str,
    scope: OrganizationScope = Depends(get_organization_scope),
    repository: CameraRepository = Depends(get_repository),
    engine: VisionEngine = Depends(get_vision_engine),
) -> dict:
    ensure_camera(camera_id, repository, scope)
    return engine.productivity(camera_id)


@router.get("/{camera_id}/stream/info")
def stream_info(
    camera_id: str,
    scope: OrganizationScope = Depends(get_organization_scope),
    repository: CameraRepository = Depends(get_repository),
) -> dict:
    camera = ensure_camera(camera_id, repository, scope)
    mode = "file_video" if camera.source_type == "video_file" else "mjpeg"
    return {
        "camera_id": camera.id,
        "source_type": camera.source_type,
        "mode": mode,
        "stream_url": f"/api/v1/cameras/{camera.id}/stream",
        "video_url": f"/api/v1/cameras/{camera.id}/video" if mode == "file_video" else None,
    }


@router.get("/{camera_id}/diagnostics")
def camera_diagnostics(
    camera_id: str,
    scope: OrganizationScope = Depends(get_organization_scope),
    repository: CameraRepository = Depends(get_repository),
    manager: CameraManager = Depends(get_camera_manager),
    engine: VisionEngine = Depends(get_vision_engine),
) -> dict:
    camera = ensure_camera(camera_id, repository, scope)
    health = manager.health(camera).as_dict()
    frame_stats = manager.frame_stats(camera_id)
    vision = engine.status(camera_id)
    return {
        "camera": {
            "id": camera.id,
            "name": camera.name,
            "source_type": camera.source_type,
            "enabled": camera.enabled,
            "vision_enabled": camera.vision_enabled,
        },
        "health": health,
        "frames": {
            "received": frame_stats.frames_received,
            "replaced": frame_stats.frames_replaced,
        },
        "vision": vision,
        "notes": [
            "ONLINE indica frames recentes no buffer.",
            "DEGRADED indica falhas de leitura ou frame antigo.",
            "OFFLINE indica fonte parada, inacessível ou ainda sem conexão.",
        ],
    }


@router.get("/{camera_id}/video")
def camera_video(
    camera_id: str,
    scope: OrganizationScope = Depends(get_organization_scope),
    repository: CameraRepository = Depends(get_repository),
) -> FileResponse:
    camera = ensure_camera(camera_id, repository, scope)
    if camera.source_type != "video_file":
        raise HTTPException(status_code=404, detail="Video playback is available only for video_file sources.")

    video_path = resolve_video_path(camera.source_uri)
    if not video_path.exists() or not video_path.is_file():
        raise HTTPException(status_code=404, detail="Video file not found.")

    return FileResponse(
        video_path,
        media_type="video/mp4",
        filename=video_path.name,
    )


@router.get("/{camera_id}/snapshot")
def camera_snapshot(
    camera_id: str,
    scope: OrganizationScope = Depends(get_organization_scope),
    repository: CameraRepository = Depends(get_repository),
    manager: CameraManager = Depends(get_camera_manager),
    engine: VisionEngine = Depends(get_vision_engine),
) -> Response:
    ensure_camera(camera_id, repository, scope)
    frame, _ = manager.latest_frame(camera_id)
    if frame is None:
        frame = _blank_frame("Sem preview disponivel")
    else:
        objects = engine.objects(camera_id)
        poses = engine.poses(camera_id)
        if objects or poses:
            try:
                frame = overlay_renderer.render(frame, objects, poses)
            except Exception:
                logger.exception(
                    "[CAMPEX][VISION] Snapshot overlay rendering failed",
                    extra={"camera_id": camera_id},
                )
    ok, encoded = cv2.imencode(".jpg", frame)
    if not ok:
        raise HTTPException(status_code=503, detail="Snapshot encoding failed.")
    return Response(content=encoded.tobytes(), media_type="image/jpeg")


def prepare_stream_frame(frame):
    settings = get_settings()
    height, width = frame.shape[:2]
    if width > settings.stream_max_width:
        scale = settings.stream_max_width / width
        frame = cv2.resize(
            frame,
            (settings.stream_max_width, max(1, int(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
    return frame


def encode_stream_frame(frame) -> bytes | None:
    settings = get_settings()
    frame = prepare_stream_frame(frame)
    ok, encoded = cv2.imencode(
        ".jpg",
        frame,
        [int(cv2.IMWRITE_JPEG_QUALITY), settings.stream_jpeg_quality],
    )
    return encoded.tobytes() if ok else None


def resolve_video_path(source_uri: str) -> Path:
    raw_path = Path(source_uri).expanduser()
    if any(part == ".." for part in raw_path.parts):
        return ROOT_DIR / ".denied-video-source"
    candidates = [raw_path]

    if not raw_path.is_absolute():
        candidates.append(ROOT_DIR / raw_path)

    candidates.append(ROOT_DIR / raw_path.name)

    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.exists() and resolved.is_file():
            return resolved

    return raw_path


@router.get("/{camera_id}/stream")
async def camera_stream(
    request: Request,
    camera_id: str,
    scope: OrganizationScope = Depends(get_organization_scope),
    repository: CameraRepository = Depends(get_repository),
    manager: CameraManager = Depends(get_camera_manager),
    engine: VisionEngine = Depends(get_vision_engine),
) -> StreamingResponse:
    ensure_camera(camera_id, repository, scope)

    async def generate():
        settings = get_settings()
        frame_delay = 1 / settings.stream_fps
        while True:
            if await request.is_disconnected():
                break
            try:
                frame, _ = manager.latest_frame(camera_id)
                if frame is None:
                    frame = _blank_frame("Aguardando frame da camera")
                objects = engine.objects(camera_id)
                poses = engine.poses(camera_id)
                if objects or poses:
                    try:
                        frame = overlay_renderer.render(frame, objects, poses)
                    except Exception:
                        logger.exception(
                            "[CAMPEX][VISION] Overlay rendering failed",
                            extra={"camera_id": camera_id},
                        )
                encoded = encode_stream_frame(frame)
                if encoded is not None:
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n"
                        + encoded
                        + b"\r\n"
                    )
            except Exception:
                logger.exception(
                    "[CAMPEX][VISION] MJPEG stream frame generation failed",
                    extra={"camera_id": camera_id},
                )
                blank = _blank_frame("Erro no stream")
                encoded = encode_stream_frame(blank)
                if encoded is not None:
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n"
                        + encoded
                        + b"\r\n"
                    )
            await asyncio.sleep(frame_delay)

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store"},
    )


def _blank_frame(message: str):
    import numpy as np

    frame = np.zeros((480, 854, 3), dtype=np.uint8)
    cv2.putText(
        frame,
        message,
        (32, 240),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (220, 220, 220),
        2,
        cv2.LINE_AA,
    )
    return frame
