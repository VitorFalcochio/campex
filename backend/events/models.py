from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.events.taxonomy import classify_operational_category


@dataclass
class Event:
    """A structured operational event generated from observations.

    Events represent meaningful operational situations (e.g., a person
    entered a restricted zone) and feed the operator interface.
    """

    id: str
    type: str
    camera_id: str
    zone_id: str | None
    track_id: int | None
    severity: str  # "info", "attention", "critical"
    status: str  # "OPEN", "REVIEWED", "CLOSED"
    confidence: float | None
    started_at: str
    ended_at: str | None
    duration: float | None
    metadata: dict[str, Any]
    created_at: str
    updated_at: str

    @property
    def facts(self) -> dict[str, Any]:
        facts = self.metadata.get("facts")
        return facts if isinstance(facts, dict) else {}

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "camera_id": self.camera_id,
            "zone_id": self.zone_id,
            "track_id": self.track_id,
            "severity": self.severity,
            "status": self.status,
            "confidence": self.confidence,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration": self.duration,
            "facts": self.facts,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def build_event_facts(
    *,
    event_type: str,
    camera_id: str,
    zone_id: str | None,
    track_id: int | None,
    started_at: str,
    ended_at: str | None,
    duration: float | None,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """Normalize the minimum operational truth a manager can trust."""

    existing = metadata.get("facts")
    facts = existing.copy() if isinstance(existing, dict) else {}
    evidence_paths = [
        metadata[key]
        for key in (
            "overlay_path",
            "snapshot_path",
            "evidence_metadata_path",
            "media_path",
            "evidence_path",
        )
        if metadata.get(key)
    ]
    activity_type = metadata.get("activity_type") or metadata.get("activity") or event_type
    activity_label = metadata.get("activity_label") or metadata.get("label") or event_type
    operational_category = classify_operational_category(
        event_type=event_type,
        activity_type=activity_type,
        activity_label=activity_label,
        metadata=metadata,
    )
    zone_name = metadata.get("zone_name")
    zone_type = metadata.get("zone_type")

    facts.setdefault(
        "person",
        {
            "track_id": track_id,
            "person_id": metadata.get("person_id") or (f"track:{track_id}" if track_id is not None else None),
        },
    )
    facts.setdefault(
        "machine_area",
        {
            "camera_id": camera_id,
            "site_id": metadata.get("site_id"),
            "site_name": metadata.get("site_name"),
            "area_id": metadata.get("area_id"),
            "line_id": metadata.get("line_id"),
            "line_name": metadata.get("line_name"),
            "zone_id": zone_id,
            "zone_name": zone_name,
            "zone_type": zone_type,
            "machine_id": metadata.get("machine_id"),
            "machine_name": metadata.get("machine_name"),
            "station_id": metadata.get("station_id"),
            "station_name": metadata.get("station_name"),
        },
    )
    facts.setdefault(
        "activity",
        {
            "type": activity_type,
            "label": activity_label,
            "category": operational_category,
            "is_stop": _looks_like_stop(activity_type, activity_label),
        },
    )
    facts.setdefault(
        "timing",
        {
            "started_at": started_at,
            "ended_at": ended_at,
            "duration_seconds": duration,
        },
    )
    facts.setdefault(
        "evidence",
        {
            "paths": evidence_paths,
            "snapshot_path": metadata.get("snapshot_path"),
            "overlay_path": metadata.get("overlay_path"),
            "metadata_path": metadata.get("evidence_metadata_path"),
        },
    )
    facts.setdefault(
        "context",
        {
            "before": metadata.get("context_before"),
            "after": metadata.get("context_after"),
            "knowledge_state": metadata.get("knowledge_state", "OBSERVED"),
            "shift_id": metadata.get("shift_id"),
            "shift_name": metadata.get("shift_name"),
            "timezone": metadata.get("timezone"),
            "currency": metadata.get("currency"),
        },
    )

    quality = evaluate_event_reliability(facts)
    facts["quality"] = quality
    return facts


def evaluate_event_reliability(facts: dict[str, Any]) -> dict[str, Any]:
    """Describe whether an event has enough operational truth to be trusted."""

    timing = facts.get("timing", {})
    evidence = _as_dict(facts.get("evidence"))
    context = _as_dict(facts.get("context"))
    machine_area = _as_dict(facts.get("machine_area"))
    person = _as_dict(facts.get("person"))
    activity = _as_dict(facts.get("activity"))

    checks = {
        "has_person": bool(_has_value(person.get("person_id")) or person.get("track_id") is not None),
        "has_machine_or_area": bool(
            _has_value(machine_area.get("machine_id"))
            or _has_value(machine_area.get("area_id"))
            or _has_value(machine_area.get("zone_id"))
            or _has_value(machine_area.get("camera_id"))
        ),
        "has_activity": _has_value(activity.get("type")),
        "has_timing": _has_value(timing.get("started_at")),
        "has_duration": timing.get("duration_seconds") is not None,
        "has_evidence": _has_value(evidence.get("paths")),
        "has_context": bool(
            _has_value(context.get("before"))
            and _has_value(context.get("after"))
        ),
    }
    required_checks = {
        "person": checks["has_person"],
        "machine_area": checks["has_machine_or_area"],
        "activity": checks["has_activity"],
        "timing": checks["has_timing"],
        "duration": checks["has_duration"],
        "evidence": checks["has_evidence"],
        "context": checks["has_context"],
    }
    missing_required = [
        field for field, present in required_checks.items() if not present
    ]
    return {
        **checks,
        "missing_required": missing_required,
        "is_reliable": not missing_required,
        "state": "RELIABLE" if not missing_required else "INCOMPLETE",
    }


def normalize_event_metadata(
    *,
    event_type: str,
    camera_id: str,
    zone_id: str | None,
    track_id: int | None,
    started_at: str,
    ended_at: str | None,
    duration: float | None,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    normalized = dict(metadata or {})
    normalized["facts"] = build_event_facts(
        event_type=event_type,
        camera_id=camera_id,
        zone_id=zone_id,
        track_id=track_id,
        started_at=started_at,
        ended_at=ended_at,
        duration=duration,
        metadata=normalized,
    )
    return normalized


def _looks_like_stop(activity_type: Any, activity_label: Any) -> bool:
    text = f"{activity_type or ''} {activity_label or ''}".lower()
    markers = ("stop", "stoppage", "idle", "waiting", "stationary", "parada", "espera")
    return any(marker in text for marker in markers)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


@dataclass(frozen=True)
class EventRule:
    """A simple rule that maps an observation type + zone type to an event type.

    Rules evaluate deterministic conditions — no AI reasoning needed.
    """

    name: str
    observation_type: str  # e.g., "person_entered_zone"
    zone_type: str | None  # e.g., "restricted", or None for any
    event_type: str  # e.g., "person_restricted_zone"
    severity: str  # "info", "attention", "critical"
    duration_threshold_seconds: float = 0.0  # 0 = immediate
    cooldown_seconds: float = 10.0
    id: str | None = None
    camera_id: str | None = None
    zone_id: str | None = None
    enabled: bool = True

    def matches(
        self,
        observation_type: str,
        zone_type: str | None,
        camera_id: str | None = None,
        zone_id: str | None = None,
    ) -> bool:
        if not self.enabled:
            return False
        if self.observation_type != observation_type:
            return False
        if self.zone_type is not None and self.zone_type != zone_type:
            return False
        if self.camera_id is not None and self.camera_id != camera_id:
            return False
        if self.zone_id is not None and self.zone_id != zone_id:
            return False
        return True
