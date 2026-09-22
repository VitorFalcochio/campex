from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status

from backend.cameras.repository import CameraRepository
from backend.events.repository import EventRepository
from backend.security import OrganizationScope, get_organization_scope
from backend.videos.service import VideoAnalysisService, VideoUploadError


router = APIRouter(prefix="/api/v1/analysis", tags=["analysis"])


def _video_service(request: Request) -> VideoAnalysisService:
    return VideoAnalysisService(
        request.app.state.settings,
        detector=getattr(request.app.state, "video_detector", None),
    )


@router.get("/status")
def analysis_status(
    request: Request,
    scope: OrganizationScope = Depends(get_organization_scope),
) -> dict[str, Any]:
    videos = _video_service(request).list(scope.organization_id)
    cameras = CameraRepository(request.app.state.settings).list(scope.organization_id)
    vision = []
    for camera in cameras:
        try:
            vision.append(request.app.state.vision_engine.status(camera.id))
        except Exception:
            vision.append({"camera_id": camera.id, "status": "ERROR"})
    return {
        "status": "PROCESSING" if any(v.get("status") in {"PROCESSING", "GENERATING_INSIGHTS"} for v in videos) else "IDLE",
        "videos": videos,
        "cameras": vision,
    }


@router.post("/video", status_code=status.HTTP_202_ACCEPTED)
def upload_video_for_analysis(
    request: Request,
    file: UploadFile = File(...),
    scope: OrganizationScope = Depends(get_organization_scope),
) -> dict:
    try:
        return _video_service(request).enqueue_upload(
            file, scope.organization_id
        )
    except VideoUploadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/start/{camera_id}")
def start_camera_analysis(
    camera_id: str,
    request: Request,
    scope: OrganizationScope = Depends(get_organization_scope),
) -> dict:
    camera = CameraRepository(request.app.state.settings).get(camera_id, scope.organization_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found.")
    if not request.app.state.camera_manager.is_running(camera_id):
        request.app.state.camera_manager.start_camera(camera)
    return request.app.state.vision_engine.start_session(camera_id)


@router.post("/stop/{camera_id}")
def stop_camera_analysis(
    camera_id: str,
    request: Request,
    scope: OrganizationScope = Depends(get_organization_scope),
) -> dict:
    camera = CameraRepository(request.app.state.settings).get(camera_id, scope.organization_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found.")
    return request.app.state.vision_engine.stop_session(camera_id)


@router.get("/events")
def analysis_events(
    request: Request,
    camera_id: str | None = Query(None),
    event_type: str | None = Query(None),
    zone: str | None = Query(None),
    start: datetime | None = Query(None),
    end: datetime | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    scope: OrganizationScope = Depends(get_organization_scope),
) -> list[dict]:
    del request
    events = EventRepository.for_settings(request.app.state.settings).list(
        camera_id=camera_id,
        event_type=event_type,
        limit=limit,
        organization_id=scope.organization_id,
    )
    output = []
    for event in events:
        started = _parse_datetime(event.started_at)
        if start and started and started < start:
            continue
        if end and started and started > end:
            continue
        if zone and zone not in {event.zone_id, event.metadata.get("zone_name")}:
            continue
        output.append(event.as_dict())
    return output


@router.get("/metrics/{camera_id}")
def analysis_metrics(
    camera_id: str,
    request: Request,
    scope: OrganizationScope = Depends(get_organization_scope),
) -> dict[str, Any]:
    camera = CameraRepository(request.app.state.settings).get(camera_id, scope.organization_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found.")
    events = EventRepository.for_settings(request.app.state.settings).list(
        camera_id=camera_id,
        limit=1000,
        organization_id=scope.organization_id,
    )
    return _aggregate_events(camera_id, [event.as_dict() for event in events])


@router.get("/report/{camera_id}")
def analysis_report(
    camera_id: str,
    request: Request,
    scope: OrganizationScope = Depends(get_organization_scope),
) -> dict[str, Any]:
    metrics = analysis_metrics(camera_id, request, scope)
    latest_video = next(
        (
            item for item in _video_service(request).list(scope.organization_id)
            if item.get("metrics")
        ),
        None,
    )
    insight = latest_video.get("insight") if latest_video else None
    return {
        "title": "CAMPEX - Relatorio Operacional",
        "camera_id": camera_id,
        "metrics": metrics,
        "nemotron": insight or {
            "summary": "Relatorio deterministico gerado a partir dos eventos persistidos. Nemotron nao possui analise recente para esta camera.",
            "limitations": ["Sem analise Nemotron validada para este periodo."],
        },
    }


@router.get("/sessions")
def analysis_sessions(
    request: Request,
    scope: OrganizationScope = Depends(get_organization_scope),
) -> list[dict]:
    return _video_service(request).list(scope.organization_id)


@router.get("/sessions/{analysis_id}")
def analysis_session_detail(
    analysis_id: str,
    request: Request,
    scope: OrganizationScope = Depends(get_organization_scope),
) -> dict:
    item = _video_service(request).get(
        analysis_id,
        scope.organization_id,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Analysis session not found.")
    return item


def _aggregate_events(camera_id: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "camera_id": camera_id,
        "people_detected": sum(1 for event in events if event["type"] == "person_detected"),
        "entries": sum(1 for event in events if event["type"] in {"person_entered", "zone_entered"}),
        "exits": sum(1 for event in events if event["type"] in {"person_exited", "zone_exited"}),
        "stationary_events": sum(1 for event in events if event["type"] == "person_stationary"),
        "stationary_total_seconds": round(
            sum(event.get("duration") or 0 for event in events if event["type"] == "person_stationary"),
            3,
        ),
        "long_presence_events": sum(1 for event in events if event["type"] == "long_presence"),
        "crowding_events": sum(1 for event in events if event["type"] == "crowding_started"),
        "events_total": len(events),
        "timeline": events[:200],
    }


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
