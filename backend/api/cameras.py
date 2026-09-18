from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from backend.cameras.manager import CameraManager, test_camera_connection
from backend.cameras.models import Camera
from backend.cameras.repository import CameraRepository
from backend.cameras.security import sanitize_source_uri
from backend.cameras.uri_security import SourceURIValidationError, validate_camera_source_uri
from backend.config import get_settings
from backend.security import OrganizationScope, get_organization_scope


logger = logging.getLogger("campex.api.cameras")
router = APIRouter(prefix="/api/v1/cameras", tags=["cameras"])

SourceType = Literal["webcam", "video_file", "rtsp", "ip_camera"]


class CameraCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    area_id: str | None = Field(default=None, max_length=80)
    source_type: SourceType
    source_uri: str = Field(min_length=1, max_length=1000)
    enabled: bool = True
    vision_enabled: bool = False


class CameraUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    area_id: str | None = Field(default=None, max_length=80)
    source_type: SourceType | None = None
    source_uri: str | None = Field(default=None, min_length=1, max_length=1000)
    enabled: bool | None = None
    vision_enabled: bool | None = None


class CameraTestPayload(BaseModel):
    name: str = Field(default="Teste de câmera", min_length=1, max_length=120)
    area_id: str | None = Field(default=None, max_length=80)
    source_type: SourceType
    source_uri: str = Field(min_length=1, max_length=1000)
    enabled: bool = False
    vision_enabled: bool = False


def serialize_camera(camera, health: dict | None = None) -> dict:
    runtime_status = (health or {}).get("status") or camera.status
    return {
        "id": camera.id,
        "name": camera.name,
        "area_id": camera.area_id,
        "source_type": camera.source_type,
        "source_uri": sanitize_source_uri(camera.source_uri),
        "enabled": camera.enabled,
        "vision_enabled": camera.vision_enabled,
        "status": runtime_status,
        "health": health,
        "created_at": camera.created_at,
        "updated_at": camera.updated_at,
    }


def get_repository() -> CameraRepository:
    return CameraRepository(get_settings())


def get_camera_manager(request: Request) -> CameraManager:
    return request.app.state.camera_manager


@router.get("")
def list_cameras(
    scope: OrganizationScope = Depends(get_organization_scope),
    repository: CameraRepository = Depends(get_repository),
    manager: CameraManager = Depends(get_camera_manager),
) -> list[dict]:
    return [
        serialize_camera(camera, manager.health(camera).as_dict())
        for camera in repository.list(scope.organization_id)
    ]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_camera(
    payload: CameraCreate,
    scope: OrganizationScope = Depends(get_organization_scope),
    repository: CameraRepository = Depends(get_repository),
    manager: CameraManager = Depends(get_camera_manager),
) -> dict:
    try:
        validate_camera_source_uri(payload.source_type, payload.source_uri)
    except SourceURIValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    camera = repository.create(
        **payload.model_dump(), organization_id=scope.organization_id
    )
    logger.info(
        "Camera registered",
        extra={"camera_id": camera.id, "source_type": camera.source_type},
    )
    if camera.enabled:
        manager.start_camera(camera)
    return serialize_camera(camera, manager.health(camera).as_dict())


@router.post("/test-source")
def test_camera_source(
    payload: CameraTestPayload,
    scope: OrganizationScope = Depends(get_organization_scope),
) -> dict:
    try:
        validate_camera_source_uri(payload.source_type, payload.source_uri)
    except SourceURIValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    camera = Camera(
        id="cam_test_source",
        name=payload.name,
        area_id=payload.area_id,
        source_type=payload.source_type,
        source_uri=payload.source_uri,
        enabled=payload.enabled,
        vision_enabled=payload.vision_enabled,
        status="OFFLINE",
        created_at="",
        updated_at="",
    )
    return test_camera_connection(camera, get_settings())


@router.get("/{camera_id}")
def get_camera(
    camera_id: str,
    scope: OrganizationScope = Depends(get_organization_scope),
    repository: CameraRepository = Depends(get_repository),
    manager: CameraManager = Depends(get_camera_manager),
) -> dict:
    camera = repository.get(camera_id, scope.organization_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found.")
    return serialize_camera(camera, manager.health(camera).as_dict())


@router.patch("/{camera_id}")
def update_camera(
    camera_id: str,
    payload: CameraUpdate,
    scope: OrganizationScope = Depends(get_organization_scope),
    repository: CameraRepository = Depends(get_repository),
    manager: CameraManager = Depends(get_camera_manager),
) -> dict:
    existing = repository.get(camera_id, scope.organization_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Camera not found.")

    updates = payload.model_dump(exclude_unset=True)
    if "source_uri" in updates or "source_type" in updates:
        resolved_type = updates.get("source_type", existing.source_type)
        try:
            validate_camera_source_uri(resolved_type, updates["source_uri"])
        except SourceURIValidationError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    camera = repository.update(camera_id, updates)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found.")

    manager.restart_camera(camera)
    return serialize_camera(camera, manager.health(camera).as_dict())


@router.delete(
    "/{camera_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_camera(
    camera_id: str,
    scope: OrganizationScope = Depends(get_organization_scope),
    repository: CameraRepository = Depends(get_repository),
    manager: CameraManager = Depends(get_camera_manager),
):
    manager.stop_camera(camera_id)
    deleted = repository.delete(camera_id, scope.organization_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Camera not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{camera_id}/test")
def test_camera(
    camera_id: str,
    scope: OrganizationScope = Depends(get_organization_scope),
    repository: CameraRepository = Depends(get_repository),
) -> dict:
    camera = repository.get(camera_id, scope.organization_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found.")
    return test_camera_connection(camera, get_settings())


@router.get("/{camera_id}/health")
def get_camera_health(
    camera_id: str,
    scope: OrganizationScope = Depends(get_organization_scope),
    repository: CameraRepository = Depends(get_repository),
    manager: CameraManager = Depends(get_camera_manager),
) -> dict:
    camera = repository.get(camera_id, scope.organization_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found.")
    return manager.health(camera).as_dict()
