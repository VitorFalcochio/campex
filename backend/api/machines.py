from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from backend.cameras.repository import CameraRepository
from backend.config import get_settings
from backend.machines.repository import MACHINE_TYPES, MachineRepository
from backend.security import OrganizationScope, get_organization_scope
from backend.zones.models import ZonePoint


logger = logging.getLogger("campex.api.machines")
router = APIRouter(prefix="/api/v1/machines", tags=["machines"])


class MachineCreate(BaseModel):
    camera_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    type: str = Field(pattern="^(fixed|mobile|vehicle|conveyor|robot|other)$")
    enabled: bool = True
    points: list[list[float]] = Field(min_length=3)
    requires_operator: bool = True
    allow_idle: bool = False
    min_person_distance: float = Field(default=0.08, ge=0, le=1)

    model_config = {"extra": "forbid"}


class MachineUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    type: str | None = Field(default=None, pattern="^(fixed|mobile|vehicle|conveyor|robot|other)$")
    enabled: bool | None = None
    points: list[list[float]] | None = None
    requires_operator: bool | None = None
    allow_idle: bool | None = None
    min_person_distance: float | None = Field(default=None, ge=0, le=1)

    model_config = {"extra": "forbid"}


def get_machine_repository() -> MachineRepository:
    return MachineRepository(get_settings())


def get_camera_repository() -> CameraRepository:
    return CameraRepository(get_settings())


def _validate_points(points: list[list[float]]) -> list[ZonePoint]:
    output: list[ZonePoint] = []
    for point in points:
        if len(point) != 2:
            raise HTTPException(status_code=400, detail="Each point must have 2 coordinates.")
        x, y = float(point[0]), float(point[1])
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            raise HTTPException(status_code=400, detail="Machine coordinates must be normalized.")
        output.append(ZonePoint(x=x, y=y))
    if len(output) < 3:
        raise HTTPException(status_code=400, detail="Machine polygon must have at least 3 points.")
    return output


@router.get("")
def list_machines(
    camera_id: str | None = None,
    scope: OrganizationScope = Depends(get_organization_scope),
    repository: MachineRepository = Depends(get_machine_repository),
) -> list[dict]:
    return [machine.as_dict() for machine in repository.list(camera_id, scope.organization_id)]


@router.get("/types")
def machine_types() -> dict:
    return {"types": sorted(MACHINE_TYPES)}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_machine(
    payload: MachineCreate,
    scope: OrganizationScope = Depends(get_organization_scope),
    repository: MachineRepository = Depends(get_machine_repository),
    camera_repo: CameraRepository = Depends(get_camera_repository),
) -> dict:
    camera = camera_repo.get(payload.camera_id, scope.organization_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found.")
    machine = repository.create(
        camera_id=payload.camera_id,
        name=payload.name,
        machine_type=payload.type,
        points=_validate_points(payload.points),
        enabled=payload.enabled,
        requires_operator=payload.requires_operator,
        allow_idle=payload.allow_idle,
        min_person_distance=payload.min_person_distance,
        organization_id=scope.organization_id,
    )
    logger.info("Machine created", extra={"machine_id": machine.id, "camera_id": machine.camera_id})
    return machine.as_dict()


@router.get("/{machine_id}")
def get_machine(
    machine_id: str,
    scope: OrganizationScope = Depends(get_organization_scope),
    repository: MachineRepository = Depends(get_machine_repository),
) -> dict:
    machine = repository.get(machine_id, scope.organization_id)
    if machine is None:
        raise HTTPException(status_code=404, detail="Machine not found.")
    return machine.as_dict()


@router.patch("/{machine_id}")
def update_machine(
    machine_id: str,
    payload: MachineUpdate,
    scope: OrganizationScope = Depends(get_organization_scope),
    repository: MachineRepository = Depends(get_machine_repository),
) -> dict:
    machine = repository.get(machine_id, scope.organization_id)
    if machine is None:
        raise HTTPException(status_code=404, detail="Machine not found.")
    updates = payload.model_dump(exclude_unset=True)
    if "points" in updates:
        updates["points"] = _validate_points(updates["points"])
    updated = repository.update(machine_id, updates, scope.organization_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="Machine not found.")
    return updated.as_dict()


@router.delete("/{machine_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_machine(
    machine_id: str,
    scope: OrganizationScope = Depends(get_organization_scope),
    repository: MachineRepository = Depends(get_machine_repository),
):
    machine = repository.get(machine_id, scope.organization_id)
    if machine is None:
        raise HTTPException(status_code=404, detail="Machine not found.")
    repository.delete(machine_id, scope.organization_id)
    logger.info("Machine deleted", extra={"machine_id": machine_id, "camera_id": machine.camera_id})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
