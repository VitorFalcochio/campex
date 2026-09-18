from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend.config import get_settings
from backend.config import ROOT_DIR
from backend.events.models import Event
from backend.events.repository import EventRepository
from backend.security import OrganizationScope, get_organization_scope

logger = logging.getLogger("campex.api.events")
router = APIRouter(prefix="/api/v1/events", tags=["events"])

EventSeverity = Literal["info", "attention", "critical"]
EventStatus = Literal["OPEN", "REVIEWED", "CLOSED"]


class EventUpdate(BaseModel):
    status: EventStatus | None = None
    note: str | None = None


class EventCreate(BaseModel):
    type: str = Field(min_length=1, max_length=120)
    camera_id: str = Field(min_length=1, max_length=80)
    zone_id: str | None = Field(default=None, max_length=80)
    track_id: int | None = None
    severity: EventSeverity = "info"
    confidence: float | None = Field(default=None, ge=0, le=1)
    started_at: datetime
    ended_at: datetime | None = None
    duration: float | None = Field(default=None, ge=0)
    metadata: dict = Field(default_factory=dict)
    facts: dict = Field(default_factory=dict)


def get_event_repo() -> EventRepository:
    return EventRepository.for_settings(get_settings())


@router.get("")
def list_events(
    status: EventStatus | None = Query(None),
    camera_id: str | None = Query(None),
    event_type: str | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    scope: OrganizationScope = Depends(get_organization_scope),
    repo: EventRepository = Depends(get_event_repo),
) -> list[dict]:
    return [
        event.as_dict()
        for event in repo.list(
            status=status,
            camera_id=camera_id,
            event_type=event_type,
            limit=limit,
            organization_id=scope.organization_id,
        )
    ]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_event(
    payload: EventCreate,
    scope: OrganizationScope = Depends(get_organization_scope),
    repo: EventRepository = Depends(get_event_repo),
) -> dict:
    if payload.ended_at and payload.ended_at < payload.started_at:
        raise HTTPException(status_code=422, detail="ended_at must be after started_at.")

    metadata = dict(payload.metadata)
    if payload.facts:
        metadata["facts"] = payload.facts

    event_status: EventStatus = "CLOSED" if payload.ended_at else "OPEN"
    event = repo.create(
        event_type=payload.type,
        camera_id=payload.camera_id,
        zone_id=payload.zone_id,
        track_id=payload.track_id,
        severity=payload.severity,
        status=event_status,
        confidence=payload.confidence,
        metadata=metadata,
        started_at=payload.started_at.isoformat(),
        ended_at=payload.ended_at.isoformat() if payload.ended_at else None,
        duration=payload.duration,
        organization_id=scope.organization_id,
    )
    quality = event.facts.get("quality", {})
    if event.status == "CLOSED" and not quality.get("is_reliable"):
        repo.delete(event.id)
        missing = quality.get("missing_required", [])
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Closed events must include person, machine/area, activity, duration, evidence, and before/after context.",
                "missing_required": missing,
            },
        )
    return event.as_dict()


@router.get("/{event_id}")
def get_event(
    event_id: str,
    scope: OrganizationScope = Depends(get_organization_scope),
    repo: EventRepository = Depends(get_event_repo),
) -> dict:
    event = repo.get(event_id, scope.organization_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found.")
    return event.as_dict()


@router.get("/{event_id}/evidence")
def get_event_evidence(
    event_id: str,
    variant: Literal["overlay", "snapshot", "metadata"] = Query("overlay"),
    scope: OrganizationScope = Depends(get_organization_scope),
    repo: EventRepository = Depends(get_event_repo),
):
    event = repo.get(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found.")

    key = {
        "overlay": "overlay_path",
        "snapshot": "snapshot_path",
        "metadata": "evidence_metadata_path",
    }[variant]
    relative_path = event.metadata.get(key)
    if not relative_path:
        raise HTTPException(status_code=404, detail="Evidence not found.")

    file_path = (ROOT_DIR / Path(relative_path)).resolve()
    evidence_root = (ROOT_DIR / "storage" / "evidence").resolve()
    if evidence_root not in file_path.parents:
        raise HTTPException(status_code=400, detail="Invalid evidence path.")
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Evidence file not found.")

    if variant == "metadata":
        return FileResponse(file_path, media_type="application/json")
    return FileResponse(file_path, media_type="image/jpeg")


@router.patch("/{event_id}")
def update_event(
    event_id: str,
    payload: EventUpdate,
    scope: OrganizationScope = Depends(get_organization_scope),
    repo: EventRepository = Depends(get_event_repo),
) -> dict:
    event = repo.get(event_id, scope.organization_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found.")

    updates = payload.model_dump(exclude_unset=True)
    if "status" in updates:
        if updates["status"] == "REVIEWED":
            event = repo.mark_reviewed(event_id)
        elif updates["status"] == "CLOSED":
            event = repo.close(
                event_id,
                ended_at=datetime.now().isoformat(),
                duration=None,
            )
        else:
            event = repo.update_status(event_id, updates["status"])

    if updates.get("note"):
        event = repo.update_status(event_id, event.status, metadata_update={"operator_note": updates["note"]})

    if event is None:
        raise HTTPException(status_code=404, detail="Event not found.")
    return event.as_dict()


@router.delete(
    "/{event_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_event(
    event_id: str,
    scope: OrganizationScope = Depends(get_organization_scope),
    repo: EventRepository = Depends(get_event_repo),
):
    event = repo.get(event_id, scope.organization_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found.")
    repo.delete(event_id, scope.organization_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
