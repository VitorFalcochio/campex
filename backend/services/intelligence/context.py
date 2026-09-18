from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from backend.config import Settings
from backend.database.db import connect
from backend.operations import build_operational_intelligence


def build_intelligence_context(
    settings: Settings,
    organization_id: str,
    *,
    limit_events: int = 100,
) -> dict[str, Any]:
    with connect(settings.sqlite_path) as connection:
        cameras = [
            dict(row)
            for row in connection.execute(
                """
                SELECT id, name, area_id, enabled, vision_enabled, status,
                       last_frame_at, last_connected_at, last_disconnected_at
                FROM cameras
                WHERE organization_id = ?
                ORDER BY name
                """,
                (organization_id,),
            ).fetchall()
        ]
        machines = [
            dict(row)
            for row in connection.execute(
                """
                SELECT id, camera_id, name, type, enabled, requires_operator, allow_idle
                FROM machines
                WHERE organization_id = ?
                ORDER BY name
                """,
                (organization_id,),
            ).fetchall()
        ]
        raw_events = [
            _event_row(row)
            for row in connection.execute(
                """
                SELECT id, type, camera_id, zone_id, severity, status, confidence,
                       started_at, ended_at, duration, metadata
                FROM events
                WHERE organization_id = ?
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (organization_id, limit_events),
            ).fetchall()
        ]

    event_type_counts: dict[str, int] = {}
    open_events = 0
    critical_events = 0
    for event in raw_events:
        event_type_counts[event["type"]] = event_type_counts.get(event["type"], 0) + 1
        if event["status"] == "OPEN":
            open_events += 1
        if event["severity"] == "critical":
            critical_events += 1

    intelligence = build_operational_intelligence(raw_events)
    return {
        "schema": "campex_intelligence_context.v1",
        "organization_id": organization_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "database": "campex",
            "events_limit": limit_events,
            "events_seen": len(raw_events),
        },
        "camera_status": {
            "total": len(cameras),
            "online": sum(1 for camera in cameras if camera["status"] == "ONLINE"),
            "offline": sum(1 for camera in cameras if camera["status"] == "OFFLINE"),
            "degraded": sum(1 for camera in cameras if camera["status"] == "DEGRADED"),
            "cameras": cameras[:50],
        },
        "assets": {
            "machines_total": len(machines),
            "machines": machines[:50],
        },
        "events": {
            "total_in_context": len(raw_events),
            "open": open_events,
            "critical": critical_events,
            "by_type": [
                {"type": event_type, "count": count}
                for event_type, count in sorted(
                    event_type_counts.items(), key=lambda item: item[1], reverse=True
                )
            ],
            "recent": [_lean_event(event) for event in raw_events[:20]],
        },
        "operational_intelligence": {
            "source": intelligence["source"],
            "findings": intelligence["findings"][:10],
            "triage": [
                {
                    "decision": item["decision"],
                    "priority": item["priority"],
                    "reasons": item["reasons"],
                    "group": {
                        key: item["group"].get(key)
                        for key in (
                            "type",
                            "operational_category",
                            "location_label",
                            "frequency",
                            "total_duration_label",
                            "severity",
                            "event_ids",
                        )
                    },
                }
                for item in intelligence["triage"][:10]
            ],
            "comparisons": intelligence["comparisons"],
            "impacts": intelligence["impacts"][:10],
        },
    }


def summarize_context(context: dict[str, Any]) -> dict[str, Any]:
    camera_status = context.get("camera_status", {})
    events = context.get("events", {})
    source = context.get("source", {})
    return {
        "schema": context.get("schema"),
        "events_seen": source.get("events_seen", 0),
        "cameras_total": camera_status.get("total", 0),
        "cameras_online": camera_status.get("online", 0),
        "events_open": events.get("open", 0),
        "events_critical": events.get("critical", 0),
    }


def _event_row(row) -> dict[str, Any]:
    item = dict(row)
    raw_metadata = item.get("metadata")
    if not raw_metadata:
        item["metadata"] = {}
        return item
    try:
        parsed = json.loads(raw_metadata)
    except json.JSONDecodeError:
        parsed = {}
    item["metadata"] = parsed if isinstance(parsed, dict) else {}
    return item


def _lean_event(event: dict[str, Any]) -> dict[str, Any]:
    metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
    facts = metadata.get("facts") if isinstance(metadata.get("facts"), dict) else {}
    quality = facts.get("quality") if isinstance(facts.get("quality"), dict) else {}
    activity = facts.get("activity") if isinstance(facts.get("activity"), dict) else {}
    machine_area = facts.get("machine_area") if isinstance(facts.get("machine_area"), dict) else {}
    return {
        "id": event.get("id"),
        "type": event.get("type"),
        "camera_id": event.get("camera_id"),
        "zone_id": event.get("zone_id"),
        "severity": event.get("severity"),
        "status": event.get("status"),
        "confidence": event.get("confidence"),
        "started_at": event.get("started_at"),
        "ended_at": event.get("ended_at"),
        "duration": event.get("duration"),
        "activity": {
            "type": activity.get("type"),
            "label": activity.get("label"),
        },
        "location": {
            "site_id": machine_area.get("site_id"),
            "line_id": machine_area.get("line_id"),
            "machine_id": machine_area.get("machine_id"),
            "machine_name": machine_area.get("machine_name"),
        },
        "quality": {
            "is_reliable": quality.get("is_reliable"),
            "state": quality.get("state"),
        },
    }
