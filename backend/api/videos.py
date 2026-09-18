from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse

from backend.security.dependencies import organization_id_provider
from backend.videos.service import VideoAnalysisService, VideoUploadError


router = APIRouter(prefix="/api/v1/videos", tags=["videos"])


def _service(request: Request) -> VideoAnalysisService:
    return VideoAnalysisService(request.app.state.settings)


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
