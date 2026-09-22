from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from pathlib import Path

from backend.security.dependencies import organization_id_provider
from backend.videos.service import VideoAnalysisService, VideoUploadError


router = APIRouter(prefix="/api/v1/videos", tags=["videos"])


def _service(request: Request) -> VideoAnalysisService:
    return VideoAnalysisService(
        request.app.state.settings,
        detector=getattr(request.app.state, "video_detector", None),
    )


@router.post("/analyze", status_code=status.HTTP_202_ACCEPTED)
def analyze_video(
    request: Request,
    file: UploadFile = File(...),
    organization_id: str = Depends(organization_id_provider),
) -> dict:
    try:
        return _service(request).enqueue_upload(file, organization_id)
    except VideoUploadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("")
def list_video_analyses(
    request: Request,
    organization_id: str = Depends(organization_id_provider),
) -> list[dict]:
    return _service(request).list(organization_id)


@router.get("/{analysis_id}/status")
def video_analysis_status(
    analysis_id: str,
    request: Request,
    organization_id: str = Depends(organization_id_provider),
) -> dict:
    item = _service(request).get(analysis_id, organization_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Video analysis not found.")
    return item


@router.get("/{analysis_id}/video")
def uploaded_video(
    analysis_id: str,
    request: Request,
    organization_id: str = Depends(organization_id_provider),
) -> FileResponse:
    item = _service(request).get(analysis_id, organization_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Video analysis not found.")
    return FileResponse(item["storage_path"], media_type="video/mp4", filename=item["original_filename"])


@router.get("/{analysis_id}/debug-video")
def debug_video(
    analysis_id: str,
    request: Request,
    organization_id: str = Depends(organization_id_provider),
) -> FileResponse:
    item = _service(request).get(analysis_id, organization_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Video analysis not found.")
    debug_path = item.get("debug_video_path")
    if not debug_path:
        raise HTTPException(status_code=404, detail="Debug video not available.")
    file_path = Path(debug_path).resolve()
    upload_root = Path(request.app.state.settings.video_upload_dir)
    if not upload_root.is_absolute():
        from backend.config import ROOT_DIR

        upload_root = ROOT_DIR / upload_root
    upload_root = upload_root.resolve()
    if upload_root not in file_path.parents or not file_path.exists():
        raise HTTPException(status_code=404, detail="Debug video not found.")
    return FileResponse(file_path, media_type="video/mp4", filename=file_path.name)
