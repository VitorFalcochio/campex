from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from backend.cameras.repository import CameraRepository
from backend.config import get_settings
from backend.security import OrganizationScope, get_organization_scope
from backend.zones.models import ZonePoint
from backend.zones.repository import ZoneRepository

logger = logging.getLogger("campex.api.zones")
router = APIRouter(prefix="/api/v1/zones", tags=["zones"])


class ZoneCreate(BaseModel):
    camera_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    type: str = Field(pattern="^(monitored|restricted)$")
    enabled: bool = True
    points: list[list[float]] = Field(min_length=3)

    model_config = {"extra": "forbid"}


class ZoneUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    type: str | None = Field(default=None, pattern="^(monitored|restricted)$")
    enabled: bool | None = None
    points: list[list[float]] | None = None

    model_config = {"extra": "forbid"}


def get_zone_repository() -> ZoneRepository:
    return ZoneRepository.for_settings(get_settings())


def get_camera_repository() -> CameraRepository:
    return CameraRepository(get_settings())


def _validate_zone_points(points: list[list[float]]) -> list[ZonePoint]:
    zone_points: list[ZonePoint] = []
    for pt in points:
        if len(pt) != 2:
            raise HTTPException(status_code=400, detail="Each point must have 2 coordinates.")
        x, y = float(pt[0]), float(pt[1])
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            raise HTTPException(
                status_code=400,
                detail="Zone coordinates must be normalized (0.0–1.0).",
            )
        zone_points.append(ZonePoint(x=x, y=y))
    if len(zone_points) < 3:
        raise HTTPException(status_code=400, detail="Zone polygon must have at least 3 points.")
    return zone_points


@router.get("")
def list_zones(
    camera_id: str | None = None,
    scope: OrganizationScope = Depends(get_organization_scope),
    repository: ZoneRepository = Depends(get_zone_repository),
) -> list[dict]:
    return [
        zone.as_dict()
        for zone in repository.list(camera_id, scope.organization_id)
    ]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_zone(
    payload: ZoneCreate,
    scope: OrganizationScope = Depends(get_organization_scope),
    repository: ZoneRepository = Depends(get_zone_repository),
    camera_repo: CameraRepository = Depends(get_camera_repository),
) -> dict:
    camera = camera_repo.get(payload.camera_id, scope.organization_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found.")

    points = _validate_zone_points(payload.points)
    zone = repository.create(
        camera_id=payload.camera_id,
        name=payload.name,
        zone_type=payload.type,
        points=points,
        enabled=payload.enabled,
        organization_id=scope.organization_id,
    )
    logger.info(
        "Zone created",
        extra={"zone_id": zone.id, "camera_id": zone.camera_id, "zone_type": zone.type},
    )
    return zone.as_dict()


@router.get("/{zone_id}")
def get_zone(
    zone_id: str,
    scope: OrganizationScope = Depends(get_organization_scope),
    repository: ZoneRepository = Depends(get_zone_repository),
) -> dict:
    zone = repository.get(zone_id, scope.organization_id)
    if zone is None:
        raise HTTPException(status_code=404, detail="Zone not found.")
    return zone.as_dict()


@router.patch("/{zone_id}")
def update_zone(
    zone_id: str,
    payload: ZoneUpdate,
    scope: OrganizationScope = Depends(get_organization_scope),
    repository: ZoneRepository = Depends(get_zone_repository),
) -> dict:
    existing = repository.get(zone_id, scope.organization_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Zone not found.")

    updates = payload.model_dump(exclude_unset=True)
    if "points" in updates:
        updates["points"] = _validate_zone_points(updates["points"])

    zone = repository.update(zone_id, updates, scope.organization_id)
    if zone is None:
        raise HTTPException(status_code=404, detail="Zone not found.")
    return zone.as_dict()


@router.delete(
    "/{zone_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_zone(
    zone_id: str,
    scope: OrganizationScope = Depends(get_organization_scope),
    repository: ZoneRepository = Depends(get_zone_repository),
):
    zone = repository.get(zone_id, scope.organization_id)
    if zone is None:
        raise HTTPException(status_code=404, detail="Zone not found.")
    repository.delete(zone_id, scope.organization_id)
    logger.info(
        "Zone deleted",
        extra={"zone_id": zone_id, "camera_id": zone.camera_id},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
