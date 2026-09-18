from __future__ import annotations

import json
import shutil
import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.config import get_settings
from backend.config import ROOT_DIR
from backend.database.db import connect
from backend.events.taxonomy import list_operational_categories
from backend.events.rules_repository import RuleRepository
from backend.cameras.repository import CameraRepository
from backend.machines.repository import MachineRepository
from backend.operations import build_operational_intelligence
from backend.security import OrganizationScope, get_organization_scope
from backend.zones.repository import ZoneRepository
from backend.zones.models import ZonePoint
from backend.vision.engine import VisionEngine


router = APIRouter(prefix="/api/v1", tags=["operations"])

DEFAULT_OPERATION_RULES = [
    {
        "name": "restricted_zone_entry",
        "observation_type": "person_entered_zone",
        "zone_type": "restricted",
        "event_type": "PERSON_RESTRICTED_ZONE",
        "severity": "critical",
        "duration_threshold_seconds": 0.0,
        "enabled": True,
    },
    {
        "name": "restricted_zone_exit",
        "observation_type": "person_exited_zone",
        "zone_type": "restricted",
        "event_type": "PERSON_RESTRICTED_ZONE",
        "severity": "critical",
        "duration_threshold_seconds": 0.0,
        "enabled": True,
    },
    {
        "name": "restricted_zone_dwell",
        "observation_type": "person_presence",
        "zone_type": "restricted",
        "event_type": "PERSON_RESTRICTED_ZONE_DWELL",
        "severity": "critical",
        "duration_threshold_seconds": 5.0,
        "enabled": True,
    },
    {
        "name": "monitored_zone_entry",
        "observation_type": "person_entered_zone",
        "zone_type": "monitored",
        "event_type": "PERSON_MONITORED_ZONE",
        "severity": "attention",
        "duration_threshold_seconds": 0.0,
        "enabled": True,
    },
    {
        "name": "monitored_zone_exit",
        "observation_type": "person_exited_zone",
        "zone_type": "monitored",
        "event_type": "PERSON_MONITORED_ZONE",
        "severity": "attention",
        "duration_threshold_seconds": 0.0,
        "enabled": True,
    },
]


class InvestigationCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    status: str = Field(default="OPEN", pattern="^(OPEN|REVIEWING|CLOSED)$")
    event_id: str | None = Field(default=None, max_length=80)
    notes: str = ""


class InvestigationUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    status: str | None = Field(default=None, pattern="^(OPEN|REVIEWING|CLOSED)$")
    event_id: str | None = Field(default=None, max_length=80)
    notes: str | None = None


class RulePayload(BaseModel):
    name: str = Field(min_length=1, max_length=140)
    camera_id: str | None = None
    zone_id: str | None = None
    observation_type: str = Field(pattern="^(person_entered_zone|person_exited_zone|person_presence)$")
    zone_type: str | None = Field(default=None, pattern="^(monitored|restricted)$")
    event_type: str = Field(min_length=1, max_length=120)
    severity: str = Field(pattern="^(info|attention|critical)$")
    duration_threshold_seconds: float = Field(default=0, ge=0)
    cooldown_seconds: float = Field(default=10, ge=0)
    enabled: bool = True


class RuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=140)
    camera_id: str | None = None
    zone_id: str | None = None
    observation_type: str | None = Field(default=None, pattern="^(person_entered_zone|person_exited_zone|person_presence)$")
    zone_type: str | None = Field(default=None, pattern="^(monitored|restricted)$")
    event_type: str | None = Field(default=None, min_length=1, max_length=120)
    severity: str | None = Field(default=None, pattern="^(info|attention|critical)$")
    duration_threshold_seconds: float | None = Field(default=None, ge=0)
    cooldown_seconds: float | None = Field(default=None, ge=0)
    enabled: bool | None = None


class RetentionPayload(BaseModel):
    days: int = Field(default=7, ge=0, le=365)


def _settings():
    return get_settings()


def _rule_repo() -> RuleRepository:
    return RuleRepository(_settings())


def _json(value: str | None) -> dict:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _event_row(row) -> dict:
    item = dict(row)
    item["metadata"] = _json(item.get("metadata"))
    return item


def _investigation_row(row) -> dict:
    return dict(row)


def _operations_summary_payload(request: Request | None = None, organization_id: str | None = None) -> dict:
    settings = _settings()
    manager = getattr(request.app.state, "camera_manager", None) if request else None
    with connect(settings.sqlite_path) as connection:
        if organization_id is not None:
            cameras = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM cameras WHERE organization_id = ? ORDER BY created_at DESC",
                    (organization_id,),
                ).fetchall()
            ]
            zones = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM zones WHERE organization_id = ? ORDER BY created_at ASC",
                    (organization_id,),
                ).fetchall()
            ]
            events = [
                _event_row(row)
                for row in connection.execute(
                    "SELECT * FROM events WHERE organization_id = ? ORDER BY started_at DESC LIMIT 500",
                    (organization_id,),
                ).fetchall()
            ]
            investigations = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM investigations WHERE organization_id = ? ORDER BY updated_at DESC LIMIT 100",
                    (organization_id,),
                ).fetchall()
            ]
        else:
            cameras = [dict(row) for row in connection.execute("SELECT * FROM cameras").fetchall()]
            zones = [dict(row) for row in connection.execute("SELECT * FROM zones").fetchall()]
            events = [
                _event_row(row)
                for row in connection.execute(
                    "SELECT * FROM events ORDER BY started_at DESC LIMIT 500"
                ).fetchall()
            ]
            investigations = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM investigations ORDER BY updated_at DESC LIMIT 100"
                ).fetchall()
            ]

    if manager is not None:
        camera_repo = CameraRepository(settings)
        runtime_health = {
            camera.id: manager.health(camera).as_dict()
            for camera in camera_repo.list()
        }
        for camera in cameras:
            health = runtime_health.get(camera["id"])
            if health:
                camera["status"] = health["status"]
                camera["health"] = health

    open_events = [event for event in events if event["status"] == "OPEN"]
    critical_events = [event for event in events if event["severity"] == "critical"]
    active_cameras = [camera for camera in cameras if camera["enabled"] and camera["status"] == "ONLINE"]
    online_cameras = [camera for camera in cameras if camera["status"] == "ONLINE"]
    camera_by_area: dict[str, int] = {}
    for camera in cameras:
        area = camera.get("area_id") or "sem_area"
        camera_by_area[area] = camera_by_area.get(area, 0) + 1

    event_by_type: dict[str, int] = {}
    for event in events:
        event_by_type[event["type"]] = event_by_type.get(event["type"], 0) + 1

    intelligence = build_operational_intelligence(events)

    return {
        "kpis": {
            "cameras_total": len(cameras),
            "cameras_online": len(online_cameras),
            "cameras_active": len(active_cameras),
            "zones_total": len(zones),
            "events_total": len(events),
            "events_open": len(open_events),
            "events_critical": len(critical_events),
            "investigations_open": len([item for item in investigations if item["status"] != "CLOSED"]),
        },
        "intelligence": intelligence,
        "areas": [
            {"area_id": area_id, "camera_count": count}
            for area_id, count in sorted(camera_by_area.items(), key=lambda item: item[0])
        ],
        "event_types": [
            {"type": event_type, "count": count}
            for event_type, count in sorted(event_by_type.items(), key=lambda item: item[1], reverse=True)
        ],
        "recent_events": events[:10],
        "recent_investigations": investigations[:10],
    }


@router.get("/operations/summary")
def operations_summary(
    request: Request,
    scope: OrganizationScope = Depends(get_organization_scope),
) -> dict:
    return _operations_summary_payload(request, scope.organization_id)


@router.get("/operations/diagnostics")
def local_diagnostics(
    request: Request,
    scope: OrganizationScope = Depends(get_organization_scope),
) -> dict:
    settings = _settings()
    usage = shutil.disk_usage(settings.sqlite_path.parent)
    evidence_root = ROOT_DIR / "storage" / "evidence"
    evidence_bytes = sum(path.stat().st_size for path in evidence_root.rglob("*") if path.is_file()) if evidence_root.exists() else 0
    with connect(settings.sqlite_path) as connection:
        cameras_online = connection.execute(
            "SELECT COUNT(*) FROM cameras WHERE organization_id = ? AND status = 'ONLINE'",
            (scope.organization_id,),
        ).fetchone()[0]
        ia_ativa = connection.execute(
            "SELECT COUNT(*) FROM cameras WHERE organization_id = ? AND vision_enabled = 1",
            (scope.organization_id,),
        ).fetchone()[0]
        zonas_ativas = connection.execute(
            "SELECT COUNT(*) FROM zones WHERE organization_id = ? AND enabled = 1",
            (scope.organization_id,),
        ).fetchone()[0]
        eventos_abertos = connection.execute(
            "SELECT COUNT(*) FROM events WHERE organization_id = ? AND status = 'OPEN'",
            (scope.organization_id,),
        ).fetchone()[0]
        investigacoes_abertas = connection.execute(
            "SELECT COUNT(*) FROM investigations WHERE organization_id = ? AND status != 'CLOSED'",
            (scope.organization_id,),
        ).fetchone()[0]
        regras_ativas = connection.execute(
            "SELECT COUNT(*) FROM visual_rules WHERE organization_id = ? AND enabled = 1",
            (scope.organization_id,),
        ).fetchone()[0]
        ultima_entrega = connection.execute(
            "SELECT * FROM events WHERE organization_id = ? ORDER BY updated_at DESC LIMIT 1",
            (scope.organization_id,),
        ).fetchone()

    manager = getattr(request.app.state, "camera_manager", None)
    camera_repo = CameraRepository(settings)
    cameras_online = sum(
        1
        for camera in camera_repo.list(scope.organization_id)
        if manager is not None and manager.health(camera).status.value == "ONLINE"
    ) if manager is not None else cameras_online

    return {
        "sqlite": settings.sqlite_path.exists(),
        "database_path": None,
        "cameras_online": cameras_online,
        "ia_ativa": ia_ativa,
        "zonas_ativas": zonas_ativas,
        "regras_ativas": regras_ativas,
        "eventos_abertos": eventos_abertos,
        "investigacoes_abertas": investigacoes_abertas,
        "outbox_pendente": 0,
        "email_mode": "local",
        "disco_livre_percentual": round((usage.free / usage.total) * 100, 1),
        "evidence_bytes": evidence_bytes,
        "evidence_mb": round(evidence_bytes / 1024 / 1024, 2),
        "ultima_entrega": _event_row(ultima_entrega) if ultima_entrega else None,
    }


@router.get("/operations/productivity")
def productivity_summary(
    request: Request,
    scope: OrganizationScope = Depends(get_organization_scope),
) -> dict:
    settings = _settings()
    camera_repo = CameraRepository(settings)
    machine_repo = MachineRepository(settings)
    vision: VisionEngine = request.app.state.vision_engine
    cameras = camera_repo.list(scope.organization_id)
    mapped_machines = machine_repo.list(None, scope.organization_id)
    mapped_by_camera: dict[str, list[dict]] = {}
    for machine in mapped_machines:
        mapped_by_camera.setdefault(machine.camera_id, []).append(machine.as_dict())
    snapshots = [vision.productivity(camera.id) for camera in cameras]
    total_people = sum(item.get("counts", {}).get("people", 0) for item in snapshots)
    total_machines = sum(item.get("counts", {}).get("machines", 0) for item in snapshots)
    total_signals = sum(len(item.get("signals", [])) for item in snapshots)
    return {
        "score": None,
        "metric_label": "atividade observada",
        "counts": {
            "cameras": len(cameras),
            "people": total_people,
            "machines": total_machines,
            "signals": total_signals,
        },
        "cameras": [
            {
                "camera_id": camera.id,
                "camera_name": camera.name,
                "enabled": camera.enabled,
                "vision_enabled": camera.vision_enabled,
                "mapped_machines": _merge_machine_states(
                    mapped_by_camera.get(camera.id, []),
                    snapshot.get("assets", []),
                ),
                **snapshot,
            }
            for camera, snapshot in zip(cameras, snapshots)
        ],
        "mapped_machines_total": len(mapped_machines),
        "machine_classes": [
            "forklift", "truck", "car", "bus", "motorcycle", "tractor",
            "excavator", "crane", "machine", "industrial machine",
        ],
        "behavior_signals": [
            "person_idle",
            "possible_phone_use",
            "person_near_machine",
            "machine_stationary",
        ],
    }


@router.get("/operations/evidence")
def list_evidence(
    limit: int = Query(100, ge=1, le=500),
    scope: OrganizationScope = Depends(get_organization_scope),
) -> list[dict]:
    settings = _settings()
    with connect(settings.sqlite_path) as connection:
        rows = connection.execute(
            """
            SELECT * FROM events
            WHERE organization_id = ?
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (scope.organization_id, limit),
        ).fetchall()

    evidence: list[dict] = []
    for row in rows:
        event = _event_row(row)
        metadata = event["metadata"]
        media_path = (
            metadata.get("overlay_path")
            or metadata.get("media_path")
            or metadata.get("snapshot_path")
            or metadata.get("evidence_path")
        )
        if not media_path:
            continue
        evidence.append(
            {
                "id": event["id"],
                "event_id": event["id"],
                "type": event["type"],
                "camera_id": event["camera_id"],
                "zone_id": event["zone_id"],
                "severity": event["severity"],
                "status": event["status"],
                "started_at": event["started_at"],
                "media_path": media_path,
                "metadata": metadata,
            }
        )
    return evidence


@router.post("/operations/evidence/cleanup")
def cleanup_evidence(payload: RetentionPayload) -> dict:
    root = ROOT_DIR / "storage" / "evidence"
    if not root.exists():
        return {"deleted_files": 0, "deleted_bytes": 0}
    cutoff = datetime.now(timezone.utc) - timedelta(days=payload.days)
    deleted_files = 0
    deleted_bytes = 0
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_file():
            modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            if payload.days == 0 or modified < cutoff:
                deleted_bytes += path.stat().st_size
                path.unlink()
                deleted_files += 1
        elif path.is_dir():
            try:
                path.rmdir()
            except OSError:
                pass
    return {"deleted_files": deleted_files, "deleted_bytes": deleted_bytes}


@router.post("/operations/demo/setup")
def setup_demo(
    request: Request,
    scope: OrganizationScope = Depends(get_organization_scope),
) -> dict:
    settings = _settings()
    camera_repo = CameraRepository(settings)
    zone_repo = ZoneRepository.for_settings(settings)
    manager = request.app.state.camera_manager
    vision = request.app.state.vision_engine
    source = "palace.mp4"
    existing = next(
        (
            cam
            for cam in camera_repo.list(scope.organization_id)
            if cam.source_type == "video_file" and cam.source_uri == source
        ),
        None,
    )
    if existing is None:
        camera = camera_repo.create(
            name="Demo palace.mp4",
            area_id="demo",
            source_type="video_file",
            source_uri=source,
            enabled=True,
            vision_enabled=True,
            organization_id=scope.organization_id,
        )
    else:
        camera = camera_repo.update(existing.id, {"enabled": True, "vision_enabled": True}) or existing
    manager.restart_camera(camera)
    zones = zone_repo.list(camera.id, scope.organization_id)
    if not zones:
        zone_repo.create(
            camera_id=camera.id,
            name="Zona restrita demo",
            zone_type="restricted",
            points=[
                ZonePoint(0.18, 0.18),
                ZonePoint(0.82, 0.18),
                ZonePoint(0.82, 0.92),
                ZonePoint(0.18, 0.92),
            ],
            enabled=True,
            organization_id=scope.organization_id,
        )
    status_payload = vision.start_session(camera.id)
    saved = camera_repo.get(camera.id, scope.organization_id)
    return {
        "camera": {
            "id": saved.id,
            "name": saved.name,
            "source_type": saved.source_type,
            "source_uri": saved.source_uri,
            "enabled": saved.enabled,
            "vision_enabled": saved.vision_enabled,
            "status": saved.status,
        } if saved else {"id": camera.id},
        "vision": status_payload,
    }


@router.get("/operations/stream")
def operations_stream(
    scope: OrganizationScope = Depends(get_organization_scope),
):
    organization_id = scope.organization_id

    async def stream():
        while True:
            payload = _operations_summary_payload(None, organization_id)
            yield f"event: summary\ndata: {json.dumps(payload)}\n\n"

            await asyncio.sleep(3)
    return StreamingResponse(stream(), media_type="text/event-stream")


@router.get("/operations/rules")
def list_rules(
    scope: OrganizationScope = Depends(get_organization_scope),
) -> list[dict]:
    return _rule_repo().list_dicts(scope.organization_id)


@router.get("/operations/taxonomy")
def operational_taxonomy() -> dict:
    return {
        "categories": list_operational_categories(),
        "metadata_field": "operational_category",
    }


def _merge_machine_states(machines: list[dict], states: list[dict]) -> list[dict]:
    state_by_id = {
        state.get("asset_id") or state.get("machine_id"): state
        for state in states
    }
    return [
        machine | state_by_id.get(machine.get("id"), {"state": "UNKNOWN"})
        for machine in machines
    ]


@router.post("/operations/rules", status_code=status.HTTP_201_CREATED)
def create_rule(
    payload: RulePayload,
    scope: OrganizationScope = Depends(get_organization_scope),
) -> dict:
    return _rule_repo().create(payload.model_dump(), scope.organization_id)


@router.patch("/operations/rules/{rule_id}")
def update_rule(
    rule_id: str,
    payload: RuleUpdate,
    scope: OrganizationScope = Depends(get_organization_scope),
) -> dict:
    try:
        return _rule_repo().update(rule_id, payload.model_dump(exclude_unset=True), scope.organization_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Rule not found.")


@router.delete("/operations/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_rule(
    rule_id: str,
    scope: OrganizationScope = Depends(get_organization_scope),
):
    if not _rule_repo().delete(rule_id, scope.organization_id):
        raise HTTPException(status_code=404, detail="Rule not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/operations/rules/simulate")
def simulate_rule(
    payload: dict,
    scope: OrganizationScope = Depends(get_organization_scope),
) -> dict:
    observation = payload.get("observation_type") or payload.get("observation")
    zone_type = payload.get("zone_type")
    matches = [
        rule
        for rule in _rule_repo().list_dicts(scope.organization_id)
        if rule["enabled"] and rule["observation_type"] == observation and (rule["zone_type"] is None or rule["zone_type"] == zone_type)
    ]
    return {
        "matched": bool(matches),
        "rules": [
            {
                "name": rule["name"],
                "event_type": rule["event_type"],
                "severity": rule["severity"],
                "duration_threshold_seconds": rule["duration_threshold_seconds"],
            }
            for rule in matches
        ],
    }


@router.get("/investigations")
def list_investigations(
    status_filter: str | None = Query(None, alias="status"),
    scope: OrganizationScope = Depends(get_organization_scope),
) -> list[dict]:
    settings = _settings()
    where = "WHERE organization_id = ?"
    params: list[str] = [scope.organization_id]
    if status_filter:
        where += " AND status = ?"
        params.append(status_filter)
    with connect(settings.sqlite_path) as connection:
        rows = connection.execute(
            f"SELECT * FROM investigations {where} ORDER BY updated_at DESC",
            params,
        ).fetchall()
    return [_investigation_row(row) for row in rows]


@router.post("/investigations", status_code=status.HTTP_201_CREATED)
def create_investigation(
    payload: InvestigationCreate,
    scope: OrganizationScope = Depends(get_organization_scope),
) -> dict:
    settings = _settings()
    investigation_id = f"inv_{uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    with connect(settings.sqlite_path) as connection:
        connection.execute(
            """
            INSERT INTO investigations (id, title, status, event_id, notes, organization_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                investigation_id,
                payload.title,
                payload.status,
                payload.event_id,
                payload.notes,
                scope.organization_id,
                now,
                now,
            ),
        )
        connection.commit()
    return _get_investigation(investigation_id, scope.organization_id)


@router.get("/investigations/{investigation_id}")
def get_investigation(
    investigation_id: str,
    scope: OrganizationScope = Depends(get_organization_scope),
) -> dict:
    return _get_investigation(investigation_id, scope.organization_id)


def _get_investigation(investigation_id: str, organization_id: str) -> dict:
    settings = _settings()
    with connect(settings.sqlite_path) as connection:
        row = connection.execute(
            "SELECT * FROM investigations WHERE id = ? AND organization_id = ?",
            (investigation_id, organization_id),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Investigation not found.")
    return _investigation_row(row)


@router.patch("/investigations/{investigation_id}")
def update_investigation(
    investigation_id: str,
    payload: InvestigationUpdate,
    scope: OrganizationScope = Depends(get_organization_scope),
) -> dict:
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return _get_investigation(investigation_id, scope.organization_id)

    fields = [f"{key} = ?" for key in updates]
    values = list(updates.values())
    settings = _settings()
    with connect(settings.sqlite_path) as connection:
        cursor = connection.execute(
            f"""
            UPDATE investigations
            SET {', '.join(fields)}, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND organization_id = ?
            """,
            (*values, investigation_id, scope.organization_id),
        )
        connection.commit()
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Investigation not found.")
    return _get_investigation(investigation_id, scope.organization_id)


@router.delete(
    "/investigations/{investigation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_investigation(
    investigation_id: str,
    scope: OrganizationScope = Depends(get_organization_scope),
):
    settings = _settings()
    with connect(settings.sqlite_path) as connection:
        cursor = connection.execute(
            "DELETE FROM investigations WHERE id = ? AND organization_id = ?",
            (investigation_id, scope.organization_id),
        )
        connection.commit()
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Investigation not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
