from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.events.taxonomy import classify_operational_category, get_category_config


MIN_EVENT_DURATION_SECONDS = 0.0


@dataclass(frozen=True)
class TimeWindow:
    name: str
    start: datetime
    end: datetime


def build_operational_intelligence(
    events: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    reference = _ensure_aware(now or datetime.now(timezone.utc))
    normalized_events = [_normalize_event(event) for event in events]
    reliable_events = [
        event
        for event in normalized_events
        if event["status"] == "CLOSED"
        and event["duration_seconds"] is not None
        and event["quality"].get("is_reliable") is True
    ]
    today_start = reference.replace(hour=0, minute=0, second=0, microsecond=0)
    today_events = [
        event
        for event in reliable_events
        if event["started_dt"] is not None and today_start <= event["started_dt"] <= reference
    ]
    groups = _group_events(today_events)
    groups.sort(key=lambda item: (item["total_duration_seconds"], item["frequency"]), reverse=True)

    triage = [_triage_group(group) for group in groups]
    attention_items = [item for item in triage if item["decision"] == "INVESTIGATE"]
    investigations = [_build_investigation(item["group"]) for item in attention_items]
    findings = [_build_finding(investigation) for investigation in investigations]
    comparisons = _build_comparisons(reliable_events, reference)
    impacts = [_build_impact(group) for group in groups if group["total_duration_seconds"] > 0]

    return {
        "source": {
            "events_seen": len(events),
            "closed_reliable_events": len(reliable_events),
            "incomplete_or_open_events": len(events) - len(reliable_events),
        },
        "event_groups": groups,
        "triage": triage,
        "investigations": investigations,
        "findings": findings,
        "comparisons": comparisons,
        "impacts": impacts,
    }


def _normalize_event(event: dict[str, Any]) -> dict[str, Any]:
    metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
    facts = metadata.get("facts") if isinstance(metadata.get("facts"), dict) else {}
    timing = facts.get("timing") if isinstance(facts.get("timing"), dict) else {}
    machine_area = facts.get("machine_area") if isinstance(facts.get("machine_area"), dict) else {}
    activity = facts.get("activity") if isinstance(facts.get("activity"), dict) else {}
    evidence = facts.get("evidence") if isinstance(facts.get("evidence"), dict) else {}
    context = facts.get("context") if isinstance(facts.get("context"), dict) else {}
    quality = facts.get("quality") if isinstance(facts.get("quality"), dict) else {}

    duration = event.get("duration")
    if duration is None:
        duration = timing.get("duration_seconds")

    started_at = _parse_datetime(event.get("started_at") or timing.get("started_at"))
    ended_at = _parse_datetime(event.get("ended_at") or timing.get("ended_at"))
    location_id = (
        machine_area.get("station_id")
        or machine_area.get("machine_id")
        or machine_area.get("area_id")
        or machine_area.get("zone_id")
        or event.get("zone_id")
        or event.get("camera_id")
        or "unknown"
    )
    location_label = (
        machine_area.get("station_name")
        or machine_area.get("machine_name")
        or machine_area.get("zone_name")
        or machine_area.get("area_id")
        or event.get("zone_id")
        or event.get("camera_id")
        or "local desconhecido"
    )
    activity_label = activity.get("label") or activity.get("type") or event.get("type")
    category = classify_operational_category(
        event_type=str(event.get("type") or ""),
        activity_type=activity.get("type"),
        activity_label=activity_label,
        metadata=metadata,
    )

    return {
        **event,
        "metadata": metadata,
        "facts": facts,
        "quality": quality,
        "duration_seconds": float(duration) if duration is not None else None,
        "started_dt": started_at,
        "ended_dt": ended_at,
        "group_key": "|".join(
            [
                str(event.get("type") or "unknown"),
                category,
                str(location_id),
                str(activity.get("type") or event.get("type") or "unknown"),
            ]
        ),
        "location_id": location_id,
        "location_label": location_label,
        "site_id": machine_area.get("site_id"),
        "site_name": machine_area.get("site_name"),
        "line_id": machine_area.get("line_id"),
        "line_name": machine_area.get("line_name"),
        "activity_label": activity_label,
        "operational_category": category,
        "evidence_paths": evidence.get("paths") if isinstance(evidence.get("paths"), list) else [],
        "context_before": context.get("before"),
        "context_after": context.get("after"),
    }


def _group_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        by_key.setdefault(event["group_key"], []).append(event)

    groups = []
    for key, items in by_key.items():
        items.sort(key=lambda event: event["started_dt"] or datetime.min.replace(tzinfo=timezone.utc))
        durations = [event["duration_seconds"] or 0.0 for event in items]
        first = items[0]
        started_values = [event["started_dt"] for event in items if event["started_dt"] is not None]
        ended_values = [event["ended_dt"] for event in items if event["ended_dt"] is not None]
        total_duration = sum(durations)
        evidence_paths = []
        for event in items:
            evidence_paths.extend(event["evidence_paths"])
        hourly_rate = _first_number(
            event["metadata"].get("impact_hourly_rate_brl")
            or event["metadata"].get("lost_capacity_hourly_rate_brl")
            or event["metadata"].get("impact_hourly_rate")
            or event["metadata"].get("lost_capacity_hourly_rate")
            for event in items
        )
        currency = next(
            (
                event["metadata"].get("currency")
                or event["facts"].get("context", {}).get("currency")
                for event in items
                if event["metadata"].get("currency") or event["facts"].get("context", {}).get("currency")
            ),
            None,
        )

        groups.append(
            {
                "key": key,
                "type": first.get("type"),
                "operational_category": first["operational_category"],
                "location_id": first["location_id"],
                "location_label": first["location_label"],
                "site_id": first["site_id"],
                "site_name": first["site_name"],
                "line_id": first["line_id"],
                "line_name": first["line_name"],
                "activity_label": first["activity_label"],
                "frequency": len(items),
                "total_duration_seconds": round(total_duration, 3),
                "total_duration_label": _format_duration(total_duration),
                "average_duration_seconds": round(total_duration / len(items), 3) if items else 0,
                "first_started_at": min(started_values).isoformat() if started_values else None,
                "last_ended_at": max(ended_values).isoformat() if ended_values else None,
                "severity": _highest_severity(item.get("severity") for item in items),
                "event_ids": [event["id"] for event in items if event.get("id")],
                "evidence_paths": evidence_paths[:12],
                "sample_context": {
                    "before": next((event["context_before"] for event in items if event["context_before"]), None),
                    "after": next((event["context_after"] for event in items if event["context_after"]), None),
                },
                "impact_hourly_rate_brl": hourly_rate,
                "impact_hourly_rate": hourly_rate,
                "currency": currency or "BRL",
            }
        )
    return groups


def _triage_group(group: dict[str, Any]) -> dict[str, Any]:
    reasons = []
    category_config = get_category_config(group["operational_category"])
    if group["frequency"] >= category_config.attention_threshold_count:
        reasons.append(f"{group['frequency']} ocorrencias semelhantes")
    if group["total_duration_seconds"] >= category_config.attention_threshold_seconds:
        reasons.append(f"{group['total_duration_label']} acumulados")
    if group["severity"] == "critical":
        reasons.append("severidade critica")

    decision = "INVESTIGATE" if reasons else "IGNORE"
    if decision == "IGNORE":
        reasons.append("ocorrencia isolada ou impacto baixo")

    return {
        "decision": decision,
        "priority": _priority(group, decision),
        "reasons": reasons,
        "category": category_config.as_dict(),
        "group": group,
    }


def _build_investigation(group: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": f"{group['location_label']} - {group['activity_label']}",
        "what_happened": group["activity_label"],
        "operational_category": group["operational_category"],
        "site_id": group["site_id"],
        "site_name": group["site_name"],
        "line_id": group["line_id"],
        "line_name": group["line_name"],
        "started_at": group["first_started_at"],
        "last_seen_at": group["last_ended_at"],
        "total_duration_seconds": group["total_duration_seconds"],
        "total_duration_label": group["total_duration_label"],
        "frequency": group["frequency"],
        "context": group["sample_context"],
        "evidence_paths": group["evidence_paths"],
        "event_ids": group["event_ids"],
        "severity": group["severity"],
    }


def _build_finding(investigation: dict[str, Any]) -> dict[str, Any]:
    minutes = round(investigation["total_duration_seconds"] / 60)
    text = (
        f"{investigation['title']} acumulou {minutes} minutos hoje, "
        f"em {investigation['frequency']} ocorrencias semelhantes."
    )
    return {
        "title": investigation["title"],
        "statement": text,
        "severity": investigation["severity"],
        "operational_category": investigation["operational_category"],
        "event_ids": investigation["event_ids"],
    }


def _build_comparisons(events: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)
    week_start = today_start - timedelta(days=today_start.weekday())
    previous_week_start = week_start - timedelta(days=7)
    windows = {
        "today": TimeWindow("today", today_start, now),
        "yesterday": TimeWindow("yesterday", yesterday_start, today_start),
        "this_week": TimeWindow("this_week", week_start, now),
        "previous_week": TimeWindow("previous_week", previous_week_start, week_start),
    }
    totals = {name: _window_totals(events, window) for name, window in windows.items()}
    return {
        "totals": totals,
        "today_vs_yesterday": _compare_totals(totals["today"], totals["yesterday"]),
        "this_week_vs_previous_week": _compare_totals(totals["this_week"], totals["previous_week"]),
        "normal_vs_current": _build_recent_normal(events, now),
    }


def _build_impact(group: dict[str, Any]) -> dict[str, Any]:
    lost_hours = group["total_duration_seconds"] / 3600
    hourly_rate = group.get("impact_hourly_rate_brl")
    currency = group.get("currency") or "BRL"
    cost = round(lost_hours * hourly_rate, 2) if hourly_rate is not None else None
    return {
        "group_key": group["key"],
        "location_label": group["location_label"],
        "lost_time_seconds": group["total_duration_seconds"],
        "lost_time_label": group["total_duration_label"],
        "estimated_lost_capacity_hours": round(lost_hours, 3),
        "estimated_cost": cost,
        "estimated_cost_brl": cost if currency == "BRL" else None,
        "currency": currency,
        "estimate_status": "COSTED" if cost is not None else "TIME_ONLY",
    }


def _window_totals(events: list[dict[str, Any]], window: TimeWindow) -> dict[str, Any]:
    selected = [
        event
        for event in events
        if event["started_dt"] is not None and window.start <= event["started_dt"] < window.end
    ]
    duration = sum(event["duration_seconds"] or 0 for event in selected)
    return {
        "event_count": len(selected),
        "total_duration_seconds": round(duration, 3),
        "total_duration_label": _format_duration(duration),
    }


def _compare_totals(current: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    current_duration = current["total_duration_seconds"]
    baseline_duration = baseline["total_duration_seconds"]
    delta = current_duration - baseline_duration
    if baseline_duration > 0:
        percent = round((delta / baseline_duration) * 100, 1)
    else:
        percent = None
    return {
        "duration_delta_seconds": round(delta, 3),
        "duration_delta_label": _format_duration(abs(delta)),
        "duration_delta_percent": percent,
        "direction": "up" if delta > 0 else "down" if delta < 0 else "flat",
    }


def _build_recent_normal(events: list[dict[str, Any]], now: datetime, days: int = 7) -> dict[str, Any]:
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    current = _window_totals(events, TimeWindow("today", today_start, now))
    daily_totals = []
    for offset in range(1, days + 1):
        end = today_start - timedelta(days=offset - 1)
        start = end - timedelta(days=1)
        total = _window_totals(events, TimeWindow(f"d-{offset}", start, end))
        if total["event_count"] > 0:
            daily_totals.append(total)

    average_duration = (
        sum(item["total_duration_seconds"] for item in daily_totals) / len(daily_totals)
        if daily_totals
        else 0
    )
    baseline = {
        "event_count": round(sum(item["event_count"] for item in daily_totals) / len(daily_totals), 3)
        if daily_totals
        else 0,
        "total_duration_seconds": round(average_duration, 3),
        "total_duration_label": _format_duration(average_duration),
        "sample_days": len(daily_totals),
    }
    comparison = _compare_totals(current, baseline)
    return {
        "current": current,
        "baseline": baseline,
        "comparison": comparison,
        "state": "NO_BASELINE" if not daily_totals else "ABOVE_NORMAL" if comparison["direction"] == "up" else "NORMAL_OR_BELOW",
    }


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return _ensure_aware(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _format_duration(seconds: float) -> str:
    total_minutes = round(max(0, seconds) / 60)
    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return f"{hours}h{minutes:02d}"
    if hours:
        return f"{hours}h"
    return f"{minutes}min"


def _highest_severity(values) -> str:
    order = {"info": 0, "attention": 1, "critical": 2}
    return max((value or "info" for value in values), key=lambda value: order.get(value, 0))


def _priority(group: dict[str, Any], decision: str) -> str:
    if decision == "IGNORE":
        return "low"
    if group["severity"] == "critical" or group["total_duration_seconds"] >= 3600:
        return "high"
    return "medium"


def _first_number(values) -> float | None:
    for value in values:
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None
