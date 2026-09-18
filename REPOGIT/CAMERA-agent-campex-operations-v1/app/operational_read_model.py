from __future__ import annotations

import sqlite3
import json
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.event_taxonomy import EVENT_FAMILY_ABSENCE, EVENT_FAMILY_FLOW, EVENT_FAMILY_INTERRUPTION, EVENT_FAMILY_UNKNOWN, EVENT_FAMILY_WAIT, OFFICIAL_EVENT_FAMILIES
from app.models import row_to_dict


LOSS_FAMILIES = {EVENT_FAMILY_INTERRUPTION, EVENT_FAMILY_WAIT, EVENT_FAMILY_ABSENCE}
FAMILY_LABELS = {
    EVENT_FAMILY_INTERRUPTION: "interrupções",
    EVENT_FAMILY_WAIT: "esperas",
    EVENT_FAMILY_FLOW: "fluxo/movimentação",
    EVENT_FAMILY_ABSENCE: "ausências",
}


@dataclass(frozen=True)
class ReadModelFilters:
    cliente_id: str | None = None
    site_id: str | None = None
    area_context_id: str | None = None
    process_id: str | None = None
    asset_id: str | None = None
    camera_id: str | None = None
    event_family: str | None = None
    tipo: str | None = None
    workflow_status: str | None = None
    start: datetime | None = None
    end: datetime | None = None


def parse_datetime(value: str | None, default: datetime | None = None) -> datetime:
    if not value:
        if default is not None:
            return default
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def to_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def period_bounds(period: str = "day", start: str | None = None, end: str | None = None, now: datetime | None = None) -> tuple[datetime, datetime]:
    reference = now or datetime.now(timezone.utc)
    if start or end:
        return parse_datetime(start, reference - timedelta(days=1)), parse_datetime(end, reference)
    period = period or "day"
    if period == "turno":
        return reference - timedelta(hours=8), reference
    if period == "week":
        return reference - timedelta(days=7), reference
    if period == "month":
        return reference - timedelta(days=30), reference
    if period == "custom":
        return reference - timedelta(days=1), reference
    return reference - timedelta(days=1), reference


def previous_period(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    delta = end - start
    return start - delta, start


def _overlap_seconds(event: dict[str, Any], start: datetime, end: datetime, now: datetime) -> float:
    event_start = parse_datetime(event.get("inicio"), start)
    raw_end = event.get("fim")
    event_end = parse_datetime(raw_end, now) if raw_end else now
    effective_start = max(start, event_start)
    effective_end = min(end, event_end)
    return max(0.0, (effective_end - effective_start).total_seconds())


def _event_uuid(event: dict[str, Any]) -> str:
    return str(event.get("event_uuid") or event.get("id"))


def _family_label(family: str | None) -> str:
    return FAMILY_LABELS.get(str(family or ""), "eventos classificados")


def _seconds_label(value: float | int | None) -> str:
    total = max(0, int(round(float(value or 0))))
    hours = total // 3600
    minutes = (total % 3600) // 60
    seconds = total % 60
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"


def _official_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [event for event in events if (event.get("event_family") or EVENT_FAMILY_UNKNOWN) in OFFICIAL_EVENT_FAMILIES]


def _build_event_query(filters: ReadModelFilters) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if filters.start and filters.end:
        clauses.append("inicio <= ?")
        params.append(to_iso(filters.end))
        clauses.append("COALESCE(fim, ?) >= ?")
        params.extend([to_iso(filters.end), to_iso(filters.start)])
    column_filters = {
        "cliente_id": filters.cliente_id,
        "site_id": filters.site_id,
        "area_context_id": filters.area_context_id,
        "process_id": filters.process_id,
        "asset_id": filters.asset_id,
        "camera_id": filters.camera_id,
        "event_family": filters.event_family,
        "tipo": filters.tipo,
        "workflow_status": filters.workflow_status,
    }
    for column, value in column_filters.items():
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, params


def list_events(connection: sqlite3.Connection, filters: ReadModelFilters, *, now: datetime | None = None) -> list[dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    where, params = _build_event_query(filters)
    rows = connection.execute(
        f"""
        SELECT *
        FROM eventos
        {where}
        ORDER BY inicio ASC, criado_em ASC
        """,
        params,
    ).fetchall()
    events = [row_to_dict(row) for row in rows]
    for event in events:
        if filters.start and filters.end:
            event["read_duration_seconds"] = _overlap_seconds(event, filters.start, filters.end, now)
        elif event.get("fim"):
            event["read_duration_seconds"] = float(event.get("duracao") or 0)
        else:
            event["read_duration_seconds"] = _overlap_seconds(event, parse_datetime(event.get("inicio"), now), now, now)
        event["event_family"] = event.get("event_family") or EVENT_FAMILY_UNKNOWN
    return events


def _group_events(events: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for event in events:
        label = str(event.get(key) or "não informado")
        item = grouped.setdefault(label, {"key": label, "total_events": 0, "total_duration_seconds": 0.0, "event_uuids": []})
        item["total_events"] += 1
        item["total_duration_seconds"] += float(event.get("read_duration_seconds") or 0)
        item["event_uuids"].append(_event_uuid(event))
    return sorted(grouped.values(), key=lambda item: (-item["total_duration_seconds"], -item["total_events"], item["key"]))


def _coverage(connection: sqlite3.Connection, filters: ReadModelFilters) -> dict[str, Any]:
    if not filters.start or not filters.end:
        return {"status": "unknown", "reason": "Período não informado para cobertura."}
    clauses = ["datetime(sample_at) >= datetime(?)", "datetime(sample_at) <= datetime(?)"]
    params: list[Any] = [to_iso(filters.start), to_iso(filters.end)]
    for column, value in {
        "unit_id": filters.site_id,
        "area_context_id": filters.area_context_id,
        "process_id": filters.process_id,
        "asset_id": filters.asset_id,
        "camera_id": filters.camera_id,
    }.items():
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)
    rows = connection.execute(
        f"""
        SELECT sample_at, camera_online, inference_fps, metadata_json
        FROM operational_samples
        WHERE {' AND '.join(clauses)}
        ORDER BY sample_at ASC
        """,
        params,
    ).fetchall()
    samples = [row_to_dict(row) for row in rows]
    if not samples:
        return {
            "status": "unknown",
            "requested_start": to_iso(filters.start),
            "requested_end": to_iso(filters.end),
            "reason": "Sem amostras operacionais suficientes para estimar cobertura.",
            "sample_count": 0,
            "gaps": [],
        }
    gaps: list[dict[str, Any]] = []
    previous = parse_datetime(samples[0]["sample_at"])
    if (previous - filters.start).total_seconds() > 120:
        gaps.append({"type": "no_samples", "start": to_iso(filters.start), "end": to_iso(previous)})
    for sample in samples[1:]:
        current = parse_datetime(sample["sample_at"])
        if (current - previous).total_seconds() > 120:
            gaps.append({"type": "no_samples", "start": to_iso(previous), "end": to_iso(current)})
        previous = current
    if (filters.end - previous).total_seconds() > 120:
        gaps.append({"type": "no_samples", "start": to_iso(previous), "end": to_iso(filters.end)})
    offline_count = sum(1 for sample in samples if sample.get("camera_online") == 0)
    for sample in samples:
        try:
            sample["metadata"] = json.loads(sample.get("metadata_json") or "{}")
        except json.JSONDecodeError:
            sample["metadata"] = {}
    inactive_count = sum(1 for sample in samples if not _sample_has_inference_signal(sample))
    return {
        "status": "partial" if gaps or offline_count or inactive_count else "observed",
        "requested_start": to_iso(filters.start),
        "requested_end": to_iso(filters.end),
        "covered_start": samples[0]["sample_at"],
        "covered_end": samples[-1]["sample_at"],
        "sample_count": len(samples),
        "offline_samples": offline_count,
        "inference_inactive_samples": inactive_count,
        "gaps": gaps,
    }


def _list_samples(connection: sqlite3.Connection, filters: ReadModelFilters) -> list[dict[str, Any]]:
    if not filters.start or not filters.end:
        return []
    clauses = ["datetime(sample_at) >= datetime(?)", "datetime(sample_at) <= datetime(?)"]
    params: list[Any] = [to_iso(filters.start), to_iso(filters.end)]
    for column, value in {
        "tenant_id": filters.cliente_id,
        "site_id": filters.site_id,
        "area_context_id": filters.area_context_id,
        "process_id": filters.process_id,
        "asset_id": filters.asset_id,
        "camera_id": filters.camera_id,
        "machine_id": filters.asset_id,
    }.items():
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)
    rows = connection.execute(
        f"""
        SELECT *
        FROM operational_samples
        WHERE {' AND '.join(clauses)}
        ORDER BY sample_at ASC, id ASC
        """,
        params,
    ).fetchall()
    samples = [row_to_dict(row) for row in rows]
    for sample in samples:
        raw = sample.get("metadata_json")
        try:
            sample["metadata"] = json.loads(raw or "{}")
        except json.JSONDecodeError:
            sample["metadata"] = {}
    return samples


def _sample_has_valid_observation(sample: dict[str, Any]) -> bool:
    metadata = sample.get("metadata") or {}
    observations = metadata.get("canonical_observations")
    if not isinstance(observations, list):
        return False
    for observation in observations:
        if not isinstance(observation, dict):
            continue
        if observation.get("observation_type") not in {"machine_activity", "person_presence", "zone_occupancy"}:
            continue
        if observation.get("data_quality") not in {"observed", "inferred"}:
            continue
        if str(observation.get("value") or "UNKNOWN").upper() == "UNKNOWN":
            continue
        return True
    return False


def _sample_has_inference_signal(sample: dict[str, Any]) -> bool:
    fps = sample.get("inference_fps")
    if fps is None:
        return _sample_has_valid_observation(sample)
    try:
        return float(fps) > 0
    except (TypeError, ValueError):
        return False


def _sample_has_machine_signal(sample: dict[str, Any]) -> bool:
    metadata = sample.get("metadata") or {}
    observations = metadata.get("canonical_observations")

    if isinstance(observations, list):
        for observation in observations:
            if not isinstance(observation, dict):
                continue
            if observation.get("observation_type") != "machine_activity":
                continue
            if observation.get("data_quality") not in {"observed", "inferred"}:
                continue
            if str(observation.get("value") or "UNKNOWN").upper() not in {"ACTIVE", "STOPPED"}:
                continue
            return True

    # Compatibilidade com samples legados que ainda não carregavam
    # machine_activity canônica.
    return _sample_has_inference_signal(sample)


def _context_names(connection: sqlite3.Connection, ids: set[str]) -> dict[str, str]:
    if not ids:
        return {}
    lookups = [
        ("unidades", "nome"),
        ("operational_areas", "nome"),
        ("operational_processes", "nome"),
        ("operational_assets", "nome"),
        ("cameras", "nome"),
        ("machine_monitors", "nome"),
        ("areas_monitoradas", "nome"),
    ]
    names: dict[str, str] = {}
    for table, column in lookups:
        try:
            placeholders = ",".join("?" for _ in ids)
            rows = connection.execute(f"SELECT id, {column} AS name FROM {table} WHERE id IN ({placeholders})", tuple(ids)).fetchall()
        except sqlite3.Error:
            continue
        for row in rows:
            names[str(row["id"])] = str(row["name"])
    return names


def _timeline_context(source: dict[str, Any], names: dict[str, str]) -> dict[str, Any]:
    unit_id = source.get("unit_id") or source.get("unidade_id") or source.get("site_id")
    area_id = source.get("area_context_id")
    process_id = source.get("process_id")
    asset_id = source.get("asset_id")
    camera_id = source.get("camera_id")
    machine_id = source.get("machine_id") or source.get("machine_monitor_id")
    zone_id = source.get("zone_id") or source.get("area_id")
    return {
        "site_id": source.get("site_id") or unit_id,
        "unit_id": unit_id,
        "area_id": area_id,
        "process_id": process_id,
        "asset_id": asset_id,
        "camera_id": camera_id,
        "machine_id": machine_id,
        "zone_id": zone_id,
        "site_name": names.get(str(source.get("site_id") or unit_id)) if (source.get("site_id") or unit_id) else None,
        "unit_name": names.get(str(unit_id)) if unit_id else None,
        "area_name": names.get(str(area_id)) if area_id else None,
        "process_name": names.get(str(process_id)) if process_id else None,
        "asset_name": names.get(str(asset_id)) if asset_id else None,
        "camera_name": names.get(str(camera_id)) if camera_id else None,
        "machine_name": names.get(str(machine_id)) if machine_id else None,
        "zone_name": names.get(str(zone_id)) if zone_id else None,
    }


def _timeline_context_label(context: dict[str, Any]) -> str:
    return (
        context.get("asset_name")
        or context.get("machine_name")
        or context.get("process_name")
        or context.get("area_name")
        or context.get("camera_name")
        or context.get("asset_id")
        or context.get("machine_id")
        or context.get("camera_id")
        or "Operação"
    )


def _data_quality_from_sample(sample: dict[str, Any], observation: dict[str, Any] | None = None) -> str:
    if observation and observation.get("data_quality"):
        return str(observation["data_quality"])
    if sample.get("camera_online") == 0:
        return "camera_offline"
    if not _sample_has_inference_signal(sample):
        return "inference_unavailable"
    return "observed"


def _add_timeline_transition(
    items: list[dict[str, Any]],
    open_segments: dict[tuple[Any, ...], dict[str, Any]],
    *,
    key: tuple[Any, ...],
    timestamp: datetime,
    item_type: str,
    context: dict[str, Any],
    previous_state: str | None,
    new_state: str,
    confidence: float | None,
    data_quality: str,
    evidence_refs: list[dict[str, Any]] | None = None,
    event_uuid: str | None = None,
) -> None:
    previous_item = open_segments.get(key)
    if previous_item:
        previous_time = parse_datetime(previous_item["timestamp"])
        previous_item["duration_seconds"] = max(0.0, (timestamp - previous_time).total_seconds())
    label = _timeline_context_label(context)
    title_state = new_state.replace("_", " ")
    item = {
        "timestamp": to_iso(timestamp),
        "type": item_type,
        "context": context,
        "title": f"{label} -> {title_state}",
        "description": f"{item_type} mudou de {previous_state or 'sem estado anterior'} para {new_state}.",
        "previous_state": previous_state,
        "new_state": new_state,
        "duration_seconds": None,
        "confidence": confidence,
        "data_quality": data_quality,
        "event_uuid": event_uuid,
        "evidence_refs": evidence_refs or [],
    }
    items.append(item)
    open_segments[key] = item


def _state_from_observations(sample: dict[str, Any], observation_type: str) -> list[dict[str, Any]]:
    metadata = sample.get("metadata") or {}
    observations = metadata.get("canonical_observations")
    if not isinstance(observations, list):
        return []
    return [
        observation
        for observation in observations
        if isinstance(observation, dict) and observation.get("observation_type") == observation_type
    ]


def _derive_operational_activity(machine_state: str | None, presence_state: str | None, lighting_state: str | None, zone_state: str | None) -> tuple[str, list[str], float, str]:
    facts: list[str] = []
    machine = str(machine_state or "UNKNOWN").upper()
    presence = str(presence_state or "UNKNOWN").upper()
    lighting = str(lighting_state or "UNKNOWN").upper()
    zone = str(zone_state or "UNKNOWN").upper()
    if machine != "UNKNOWN":
        facts.append(f"machine_activity={machine}")
    if presence != "UNKNOWN":
        facts.append(f"person_presence={presence}")
    if lighting != "UNKNOWN":
        facts.append(f"lighting_state={lighting}")
    if zone != "UNKNOWN":
        facts.append(f"zone_occupancy={zone}")
    if not facts:
        return "UNKNOWN", [], 0.0, "insufficient_data"
    if machine == "ACTIVE" and presence == "PRESENT":
        return "NORMAL_ACTIVITY", facts, 0.85, "inferred"
    if machine == "STOPPED" and presence == "ABSENT" and lighting == "OFF":
        return "NO_ACTIVITY", facts, 0.85, "inferred"
    if machine == "STOPPED" and presence in {"ABSENT", "UNKNOWN"}:
        return "LOW_ACTIVITY", facts, 0.75, "inferred"
    if presence == "ABSENT" and lighting == "OFF":
        return "LOW_ACTIVITY", facts, 0.7, "inferred"
    if zone == "EMPTY" and machine != "ACTIVE":
        return "LOW_ACTIVITY", facts, 0.65, "inferred"
    return "NORMAL_ACTIVITY", facts, 0.65, "inferred"


def _coverage_from_sample_seconds(known_seconds: float, total_seconds: float, sample_count: int, unknown_seconds: float) -> dict[str, Any]:
    if total_seconds <= 0:
        return {"status": "INSUFFICIENT", "valid_percent": 0.0, "unknown_percent": 100.0, "sample_count": sample_count}
    valid_percent = round((known_seconds / total_seconds) * 100, 2)
    unknown_percent = round((unknown_seconds / total_seconds) * 100, 2)
    if sample_count == 0 or valid_percent < 50:
        status = "INSUFFICIENT"
    elif valid_percent < 90:
        status = "PARTIAL"
    else:
        status = "GOOD"
    return {
        "status": status,
        "valid_percent": valid_percent,
        "unknown_percent": unknown_percent,
        "sample_count": sample_count,
    }


def _sample_rollup(samples: list[dict[str, Any]], start: datetime, end: datetime) -> dict[str, Any]:
    total_seconds = max(0.0, (end - start).total_seconds())
    machine = {"ACTIVE": 0.0, "STOPPED": 0.0, "UNKNOWN": 0.0}
    human = {"PRESENT": 0.0, "ABSENT": 0.0, "UNKNOWN": 0.0}
    if not samples:
        machine["UNKNOWN"] = total_seconds
        human["UNKNOWN"] = total_seconds
        coverage = _coverage_from_sample_seconds(0.0, total_seconds, 0, total_seconds)
        return {"machine": machine, "human": human, "coverage": coverage}
    first_at = parse_datetime(samples[0]["sample_at"], start)
    if first_at > start:
        gap = min(total_seconds, (first_at - start).total_seconds())
        machine["UNKNOWN"] += gap
        human["UNKNOWN"] += gap
    for index, sample in enumerate(samples):
        current_at = parse_datetime(sample["sample_at"], start)
        next_at = parse_datetime(samples[index + 1]["sample_at"], end) if index + 1 < len(samples) else end
        segment_seconds = _overlap_seconds({"inicio": to_iso(current_at), "fim": to_iso(next_at)}, start, end, end)
        if segment_seconds <= 0:
            continue
        camera_online = sample.get("camera_online") == 1
        machine_sensor_ok = camera_online and _sample_has_machine_signal(sample)
        human_sensor_ok = camera_online and _sample_has_inference_signal(sample)

        state = str(sample.get("machine_state") or "UNKNOWN").upper()
        if not machine_sensor_ok or state not in {"ACTIVE", "STOPPED"}:
            machine["UNKNOWN"] += segment_seconds
        else:
            machine[state] += segment_seconds

        operator_value = sample.get("operator_present")
        if not human_sensor_ok or operator_value is None:
            human["UNKNOWN"] += segment_seconds
        elif int(operator_value) == 1:
            human["PRESENT"] += segment_seconds
        else:
            human["ABSENT"] += segment_seconds
    known_seconds = machine["ACTIVE"] + machine["STOPPED"]
    coverage = _coverage_from_sample_seconds(known_seconds, total_seconds, len(samples), machine["UNKNOWN"])
    return {"machine": machine, "human": human, "coverage": coverage}


def operational_timeline(connection: sqlite3.Connection, filters: ReadModelFilters, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    if not filters.start or not filters.end:
        raise ValueError("Timeline operacional requer início e fim.")
    samples = _list_samples(connection, filters)
    events = list_events(connection, filters, now=now)
    ids: set[str] = set()
    for sample in samples:
        for key in ("site_id", "unit_id", "area_context_id", "process_id", "asset_id", "camera_id", "machine_id"):
            if sample.get(key):
                ids.add(str(sample[key]))
        for observation_type in ("machine_activity", "person_presence", "zone_occupancy", "lighting_state"):
            for observation in _state_from_observations(sample, observation_type):
                for key in ("site_id", "unit_id", "area_context_id", "process_id", "asset_id", "camera_id", "machine_id", "zone_id"):
                    if observation.get(key):
                        ids.add(str(observation[key]))
                metadata = observation.get("metadata") if isinstance(observation.get("metadata"), dict) else {}
                if metadata.get("zone_id"):
                    ids.add(str(metadata["zone_id"]))
    for event in events:
        for key in ("site_id", "unidade_id", "area_context_id", "process_id", "asset_id", "camera_id", "machine_monitor_id", "area_id"):
            if event.get(key):
                ids.add(str(event[key]))
    names = _context_names(connection, ids)

    items: list[dict[str, Any]] = []
    open_segments: dict[tuple[Any, ...], dict[str, Any]] = {}
    last_states: dict[tuple[Any, ...], str] = {}

    def emit_sample_state(
        sample: dict[str, Any],
        *,
        item_type: str,
        state: str | None,
        key_parts: tuple[Any, ...],
        observation: dict[str, Any] | None = None,
    ) -> None:
        if state is None:
            return
        normalized = str(state or "UNKNOWN").upper()
        timestamp = parse_datetime(sample.get("sample_at"), filters.start)
        context_source = {**sample}
        if observation:
            context_source.update({key: value for key, value in observation.items() if key in {"site_id", "unit_id", "area_context_id", "process_id", "asset_id", "camera_id", "machine_id", "zone_id"}})
            metadata = observation.get("metadata") if isinstance(observation.get("metadata"), dict) else {}
            if metadata.get("zone_id") and not context_source.get("zone_id"):
                context_source["zone_id"] = metadata["zone_id"]
        context = _timeline_context(context_source, names)
        key = (item_type, *key_parts)
        previous = last_states.get(key)
        if previous == normalized:
            return
        last_states[key] = normalized
        confidence = observation.get("confidence") if observation else sample.get("confidence")
        _add_timeline_transition(
            items,
            open_segments,
            key=key,
            timestamp=timestamp,
            item_type=item_type,
            context=context,
            previous_state=previous,
            new_state=normalized,
            confidence=confidence,
            data_quality=_data_quality_from_sample(sample, observation),
        )

    for sample in samples:
        sample_machine_state: str | None = None
        sample_presence_state: str | None = None
        sample_zone_state: str | None = None
        sample_lighting_state: str | None = None
        machine_observations = _state_from_observations(sample, "machine_activity")
        if machine_observations:
            for observation in machine_observations:
                machine_key = observation.get("machine_id") or sample.get("machine_id") or observation.get("asset_id") or sample.get("asset_id") or sample.get("camera_id")
                sample_machine_state = str(observation.get("value") or "UNKNOWN").upper()
                emit_sample_state(sample, item_type="machine_activity", state=observation.get("value"), key_parts=(machine_key,), observation=observation)
        else:
            machine_key = sample.get("machine_id") or sample.get("asset_id") or sample.get("camera_id")
            sample_machine_state = str(sample.get("machine_state") or "UNKNOWN").upper()
            emit_sample_state(sample, item_type="machine_activity", state=sample.get("machine_state") or "UNKNOWN", key_parts=(machine_key,))

        presence_observations = _state_from_observations(sample, "person_presence")
        if presence_observations:
            for observation in presence_observations:
                presence_key = observation.get("zone_id") or observation.get("machine_id") or sample.get("machine_id") or sample.get("asset_id") or sample.get("camera_id")
                sample_presence_state = str(observation.get("value") or "UNKNOWN").upper()
                emit_sample_state(sample, item_type="person_presence", state=observation.get("value"), key_parts=(presence_key,), observation=observation)
        else:
            if sample.get("operator_present") is None:
                presence_state = "UNKNOWN"
            else:
                presence_state = "PRESENT" if int(sample.get("operator_present") or 0) == 1 else "ABSENT"
            presence_key = sample.get("machine_id") or sample.get("asset_id") or sample.get("camera_id")
            sample_presence_state = presence_state
            emit_sample_state(sample, item_type="person_presence", state=presence_state, key_parts=(presence_key,))

        for observation in _state_from_observations(sample, "zone_occupancy"):
            metadata = observation.get("metadata") if isinstance(observation.get("metadata"), dict) else {}
            zone_key = observation.get("zone_id") or metadata.get("zone_id") or sample.get("camera_id")
            sample_zone_state = str(observation.get("value") or "UNKNOWN").upper()
            emit_sample_state(sample, item_type="zone_occupancy", state=observation.get("value"), key_parts=(zone_key,), observation=observation)

        for observation in _state_from_observations(sample, "lighting_state"):
            lighting_key = observation.get("asset_id") or sample.get("asset_id") or observation.get("camera_id") or sample.get("camera_id")
            sample_lighting_state = str(observation.get("value") or "UNKNOWN").upper()
            emit_sample_state(sample, item_type="lighting_state", state=observation.get("value"), key_parts=(lighting_key,), observation=observation)

        activity_state, facts, activity_confidence, activity_quality = _derive_operational_activity(
            sample_machine_state,
            sample_presence_state,
            sample_lighting_state,
            sample_zone_state,
        )
        activity_key = sample.get("asset_id") or sample.get("machine_id") or sample.get("camera_id")
        activity_observation = {
            "value": activity_state,
            "confidence": activity_confidence,
            "data_quality": activity_quality,
            "metadata": {"facts": facts},
        }
        emit_sample_state(sample, item_type="operational_activity", state=activity_state, key_parts=(activity_key,), observation=activity_observation)

        camera_key = sample.get("camera_id")
        camera_state = "UNKNOWN" if sample.get("camera_online") is None else "ONLINE" if int(sample.get("camera_online") or 0) == 1 else "OFFLINE"
        emit_sample_state(sample, item_type="camera_status", state=camera_state, key_parts=(camera_key,))

    for event in events:
        context = _timeline_context(event, names)
        evidence_refs = [{"type": "image", "path": event["midia_path"]}] if event.get("midia_path") else []
        started_at = parse_datetime(event.get("inicio"), filters.start)
        event_uuid = _event_uuid(event)
        items.append(
            {
                "timestamp": to_iso(started_at),
                "type": "event_started",
                "context": context,
                "title": f"{_timeline_context_label(context)} -> evento iniciado",
                "description": f"Evento {event.get('tipo')} iniciado.",
                "previous_state": None,
                "new_state": "OPEN",
                "duration_seconds": float(event.get("read_duration_seconds") or 0) if event.get("fim") else None,
                "confidence": event.get("confianca"),
                "data_quality": (event.get("data_quality") or "observed") if "data_quality" in event else "observed",
                "event_uuid": event_uuid,
                "evidence_refs": evidence_refs,
            }
        )
        if event.get("fim"):
            ended_at = parse_datetime(event.get("fim"), filters.end)
            items.append(
                {
                    "timestamp": to_iso(ended_at),
                    "type": "event_closed",
                    "context": context,
                    "title": f"{_timeline_context_label(context)} -> evento encerrado",
                    "description": f"Evento {event.get('tipo')} encerrado.",
                    "previous_state": "OPEN",
                    "new_state": "CLOSED",
                    "duration_seconds": float(event.get("duracao") or event.get("read_duration_seconds") or 0),
                    "confidence": event.get("confianca"),
                    "data_quality": (event.get("data_quality") or "observed") if "data_quality" in event else "observed",
                    "event_uuid": event_uuid,
                    "evidence_refs": evidence_refs,
                }
            )

    for item in open_segments.values():
        if item.get("duration_seconds") is None:
            item_time = parse_datetime(item["timestamp"], filters.start)
            item["duration_seconds"] = max(0.0, (min(filters.end, now) - item_time).total_seconds())

    items.sort(key=lambda item: (item["timestamp"], item["type"], item.get("event_uuid") or ""))
    coverage = _coverage(connection, filters)
    return {
        "period": {"start": to_iso(filters.start), "end": to_iso(filters.end)},
        "filters": {key: value for key, value in filters.__dict__.items() if value is not None and key not in {"start", "end"}},
        "items": items,
        "count": len(items),
        "coverage": coverage,
        "sources": ["operational_samples", "eventos"],
        "future_observation_types": ["material_flow"],
    }


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return float((ordered[mid - 1] + ordered[mid]) / 2)


def _historical_event_durations(connection: sqlite3.Connection, filters: ReadModelFilters, tipo: str, *, before: datetime) -> list[float]:
    clauses = ["tipo = ?", "fim IS NOT NULL", "inicio < ?"]
    params: list[Any] = [tipo, to_iso(before)]
    for column, value in {
        "cliente_id": filters.cliente_id,
        "site_id": filters.site_id,
        "area_context_id": filters.area_context_id,
        "process_id": filters.process_id,
        "asset_id": filters.asset_id,
        "camera_id": filters.camera_id,
    }.items():
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)
    rows = connection.execute(
        f"""
        SELECT duracao
        FROM eventos
        WHERE {' AND '.join(clauses)}
        ORDER BY inicio DESC
        LIMIT 100
        """,
        params,
    ).fetchall()
    return [float(row["duracao"] or 0) for row in rows if float(row["duracao"] or 0) > 0]


def _timeline_event_refs(item: dict[str, Any]) -> list[str]:
    return [str(item["event_uuid"])] if item.get("event_uuid") else []


def _anomaly_item(
    *,
    anomaly_type: str,
    severity: str,
    observed_value: float,
    expected_value: float | None,
    timestamp: str,
    context: dict[str, Any],
    title: str,
    description: str,
    event_refs: list[str] | None = None,
    evidence_refs: list[dict[str, Any]] | None = None,
    confidence: float = 0.75,
    data_quality: str = "observed",
) -> dict[str, Any]:
    return {
        "anomaly_type": anomaly_type,
        "severity": severity,
        "observed_value": observed_value,
        "expected_value": expected_value,
        "timestamp": timestamp,
        "context": context,
        "title": title,
        "description": description,
        "event_refs": event_refs or [],
        "evidence_refs": evidence_refs or [],
        "confidence": round(float(confidence), 4),
        "data_quality": data_quality,
    }


def operational_change_anomalies(connection: sqlite3.Connection, filters: ReadModelFilters, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    timeline_payload = operational_timeline(connection, filters, now=now)
    items = timeline_payload["items"]
    changes = [
        item
        for item in items
        if item["type"] in {
            "machine_activity",
            "person_presence",
            "zone_occupancy",
            "camera_status",
            "lighting_state",
            "operational_activity",
            "event_started",
            "event_closed",
        }
    ]
    anomalies: list[dict[str, Any]] = []
    if not filters.start or not filters.end:
        raise ValueError("Anomalias operacionais requerem início e fim.")

    stoppage_events = [
        item
        for item in items
        if item["type"] == "event_closed" and item.get("event_uuid") and "machine_stoppage" in str(item.get("description") or "")
    ]
    historical_stop_durations = _historical_event_durations(connection, filters, "machine_stoppage", before=filters.start)
    reference_stop = _median(historical_stop_durations)
    for item in stoppage_events:
        duration = float(item.get("duration_seconds") or 0)
        threshold = max(900.0, (reference_stop or 0) * 2.0)
        if duration > threshold:
            anomalies.append(
                _anomaly_item(
                    anomaly_type="exceptionally_long_stoppage",
                    severity="high" if duration >= 1800 else "medium",
                    observed_value=duration,
                    expected_value=reference_stop,
                    timestamp=item["timestamp"],
                    context=item["context"],
                    title=f"{_timeline_context_label(item['context'])} está parada por tempo acima do padrão.",
                    description="Parada encerrada com duração acima da referência histórica disponível.",
                    event_refs=_timeline_event_refs(item),
                    evidence_refs=item.get("evidence_refs"),
                    confidence=0.85 if reference_stop else 0.65,
                    data_quality=item.get("data_quality") or "observed",
                )
            )

    started_stoppages = [
        item for item in items if item["type"] == "event_started" and "machine_stoppage" in str(item.get("description") or "")
    ]
    for index, item in enumerate(started_stoppages):
        window_start = parse_datetime(item["timestamp"])
        window_end = window_start + timedelta(minutes=40)
        window = [candidate for candidate in started_stoppages[index:] if parse_datetime(candidate["timestamp"]) <= window_end and candidate["context"].get("asset_id") == item["context"].get("asset_id")]
        if len(window) >= 5:
            anomalies.append(
                _anomaly_item(
                    anomaly_type="recurrent_stoppages_short_window",
                    severity="medium",
                    observed_value=float(len(window)),
                    expected_value=4.0,
                    timestamp=item["timestamp"],
                    context=item["context"],
                    title=f"{len(window)} paradas em 40 minutos.",
                    description="Foram identificadas paradas recorrentes em uma janela curta no mesmo ativo.",
                    event_refs=[uuid for window_item in window for uuid in _timeline_event_refs(window_item)],
                    confidence=0.8,
                )
            )
            break

    for item in items:
        duration = float(item.get("duration_seconds") or 0)
        if item["type"] == "person_presence" and item.get("new_state") == "ABSENT" and duration >= 900:
            anomalies.append(
                _anomaly_item(
                    anomaly_type="prolonged_operational_absence",
                    severity="medium",
                    observed_value=duration,
                    expected_value=900.0,
                    timestamp=item["timestamp"],
                    context=item["context"],
                    title=f"Operação sem presença por {_seconds_label(duration)}.",
                    description="Ausência operacional permaneceu acima do limite determinístico.",
                    confidence=item.get("confidence") or 0.75,
                    data_quality=item.get("data_quality") or "observed",
                )
            )
        if item.get("new_state") == "UNKNOWN" and duration >= 600:
            anomalies.append(
                _anomaly_item(
                    anomaly_type="excessive_unknown_period",
                    severity="medium",
                    observed_value=duration,
                    expected_value=600.0,
                    timestamp=item["timestamp"],
                    context=item["context"],
                    title=f"Período sem dado confiável por {_seconds_label(duration)}.",
                    description="A Campex preservou UNKNOWN em vez de interpretar ausência de dados como estado operacional.",
                    confidence=0.9,
                    data_quality=item.get("data_quality") or "insufficient_data",
                )
            )
        if item["type"] == "camera_status" and item.get("new_state") == "OFFLINE" and duration >= 300:
            anomalies.append(
                _anomaly_item(
                    anomaly_type="prolonged_camera_offline",
                    severity="high",
                    observed_value=duration,
                    expected_value=300.0,
                    timestamp=item["timestamp"],
                    context=item["context"],
                    title=f"Câmera offline por {_seconds_label(duration)}.",
                    description="Perda técnica prolongada; isso afeta cobertura, não vira evento operacional automaticamente.",
                    confidence=0.9,
                    data_quality="sensor_unavailable",
                )
            )
        if item["type"] == "lighting_state" and item.get("previous_state") in {"ON", "OFF"} and item.get("new_state") in {"ON", "OFF"}:
            anomalies.append(
                _anomaly_item(
                    anomaly_type="lighting_state_change",
                    severity="info",
                    observed_value=1.0,
                    expected_value=None,
                    timestamp=item["timestamp"],
                    context=item["context"],
                    title=f"Iluminação mudou de {item.get('previous_state')} para {item.get('new_state')}.",
                    description="Mudança persistente de iluminação registrada pela observação visual.",
                    confidence=item.get("confidence") or 0.7,
                    data_quality=item.get("data_quality") or "observed",
                )
            )

    operational_activity = [item for item in items if item["type"] == "operational_activity"]
    return {
        "period": timeline_payload["period"],
        "filters": timeline_payload["filters"],
        "changes": changes,
        "anomalies": anomalies,
        "operational_activity": operational_activity,
        "coverage": timeline_payload["coverage"],
        "sources": timeline_payload["sources"],
        "rules": [
            "state_transition_change_detection_v1",
            "long_stoppage_vs_history_v1",
            "recurrent_stoppages_40m_v1",
            "prolonged_absence_v1",
            "unknown_and_offline_duration_v1",
            "lighting_transition_v1",
            "operational_activity_facts_v1",
        ],
        "no_cause_inferred": True,
    }


VIDEO_CONTEXT_DEFAULT_BEFORE_SECONDS = 300
VIDEO_CONTEXT_DEFAULT_AFTER_SECONDS = 300


def _context_id_for_trigger(trigger: dict[str, Any]) -> str:
    payload = json.dumps(
        {
            "type": trigger.get("type"),
            "ref": trigger.get("ref"),
            "timestamp": trigger.get("timestamp"),
            "context": trigger.get("context"),
        },
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return "ctx-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _dedupe_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for ref in refs:
        key = json.dumps(ref, sort_keys=True, ensure_ascii=False)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(ref)
    return deduped


def _trigger_from_change(item: dict[str, Any]) -> dict[str, Any]:
    trigger_type = str(item.get("type") or "state_change")
    if trigger_type == "event_started":
        trigger_type = "event_started"
    elif trigger_type == "event_closed":
        trigger_type = "event_closed"
    else:
        trigger_type = f"{trigger_type}_change"
    return {
        "type": trigger_type,
        "ref": item.get("event_uuid") or f"{item.get('type')}:{item.get('timestamp')}:{item.get('new_state')}",
        "timestamp": item.get("timestamp"),
        "context": item.get("context") or {},
        "source": "operational_timeline",
        "item": item,
    }


def _trigger_from_anomaly(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": item.get("anomaly_type"),
        "ref": (item.get("event_refs") or [None])[0] or f"{item.get('anomaly_type')}:{item.get('timestamp')}",
        "timestamp": item.get("timestamp"),
        "context": item.get("context") or {},
        "source": "operational_change_anomalies",
        "item": item,
    }


def _trigger_time_bounds(trigger: dict[str, Any], timeline_items: list[dict[str, Any]], filters: ReadModelFilters, now: datetime) -> tuple[datetime, datetime | None]:
    trigger_ts = parse_datetime(trigger.get("timestamp"), filters.start or now)
    ref = trigger.get("ref")
    if ref:
        starts = [item for item in timeline_items if item.get("event_uuid") == ref and item.get("type") == "event_started"]
        closes = [item for item in timeline_items if item.get("event_uuid") == ref and item.get("type") == "event_closed"]
        if starts:
            trigger_ts = parse_datetime(starts[0]["timestamp"], trigger_ts)
        if closes:
            return trigger_ts, parse_datetime(closes[0]["timestamp"], now)
    return trigger_ts, None


def _phase_for_item(item_ts: datetime, trigger_start: datetime, trigger_end: datetime | None) -> str:
    transition_end = trigger_start + timedelta(seconds=1)
    if item_ts < trigger_start:
        return "before"
    if item_ts <= transition_end:
        return "transition"
    if trigger_end is None or item_ts <= trigger_end:
        return "during"
    return "after"


def _context_quality(coverage: dict[str, Any], phases: dict[str, list[dict[str, Any]]], evidence_refs: list[dict[str, Any]]) -> dict[str, Any]:
    gaps = coverage.get("gaps") or []
    has_unknown = any(item.get("new_state") == "UNKNOWN" or item.get("data_quality") in {"unknown", "insufficient_data", "sensor_unavailable"} for phase in phases.values() for item in phase)
    missing = [name for name in ("before", "transition", "during", "after") if not phases.get(name)]
    if gaps or has_unknown or missing:
        status = "partial"
    else:
        status = "complete"
    return {
        "status": status,
        "coverage_status": coverage.get("status"),
        "gaps": gaps,
        "has_unknown": has_unknown,
        "evidence_available": bool(evidence_refs),
        "missing_phases": missing,
        "sample_count": coverage.get("sample_count"),
    }


def build_video_context(
    connection: sqlite3.Connection,
    filters: ReadModelFilters,
    trigger: dict[str, Any],
    *,
    before_seconds: int = VIDEO_CONTEXT_DEFAULT_BEFORE_SECONDS,
    after_seconds: int = VIDEO_CONTEXT_DEFAULT_AFTER_SECONDS,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    if not filters.start or not filters.end:
        raise ValueError("Video context requer início e fim.")
    change_payload = operational_change_anomalies(connection, filters, now=now)
    timeline_items = change_payload["changes"]
    trigger_start, trigger_end = _trigger_time_bounds(trigger, timeline_items, filters, now)
    window_start = max(filters.start, trigger_start - timedelta(seconds=before_seconds))
    effective_end = trigger_end or trigger_start
    window_end = min(filters.end, effective_end + timedelta(seconds=after_seconds))
    phases: dict[str, list[dict[str, Any]]] = {"before": [], "transition": [], "during": [], "after": []}
    observations: list[dict[str, Any]] = []
    evidence_refs: list[dict[str, Any]] = []
    event_refs: set[str] = set()
    for item in timeline_items:
        item_ts = parse_datetime(item.get("timestamp"), filters.start)
        if item_ts < window_start or item_ts > window_end:
            continue
        phase = _phase_for_item(item_ts, trigger_start, trigger_end)
        duration = item.get("duration_seconds")
        if duration is not None:
            duration = min(float(duration), max(0.0, (window_end - item_ts).total_seconds()))
        fact = {
            "timestamp": item.get("timestamp"),
            "type": item.get("type"),
            "title": item.get("title"),
            "description": item.get("description"),
            "previous_state": item.get("previous_state"),
            "new_state": item.get("new_state"),
            "duration_seconds": duration,
            "confidence": item.get("confidence"),
            "data_quality": item.get("data_quality"),
            "event_uuid": item.get("event_uuid"),
            "evidence_refs": item.get("evidence_refs") or [],
        }
        phases[phase].append(fact)
        observations.append(fact)
        if item.get("event_uuid"):
            event_refs.add(str(item["event_uuid"]))
        evidence_refs.extend(item.get("evidence_refs") or [])
    anomalies = []
    for anomaly in change_payload["anomalies"]:
        item_ts = parse_datetime(anomaly.get("timestamp"), filters.start)
        if window_start <= item_ts <= window_end:
            anomalies.append(anomaly)
            event_refs.update(str(ref) for ref in anomaly.get("event_refs") or [])
            evidence_refs.extend(anomaly.get("evidence_refs") or [])
    events = [item for item in timeline_items if item.get("event_uuid") in event_refs and item.get("type") in {"event_started", "event_closed"}]
    context_trigger = {key: value for key, value in trigger.items() if key != "item"}
    context_id = _context_id_for_trigger(context_trigger)
    deduped_evidence = _dedupe_refs(evidence_refs)
    quality = _context_quality(change_payload["coverage"], phases, deduped_evidence)
    return {
        "context_id": context_id,
        "camera_id": (trigger.get("context") or {}).get("camera_id"),
        "asset_id": (trigger.get("context") or {}).get("asset_id"),
        "start_ts": to_iso(window_start),
        "end_ts": to_iso(window_end),
        "trigger": context_trigger,
        "phases": {key: value for key, value in phases.items() if value},
        "observations": observations,
        "events": events,
        "anomalies": anomalies,
        "evidence_refs": deduped_evidence,
        "data_quality": quality,
        "cause_inferred": False,
        "window": {
            "before_seconds": before_seconds,
            "after_seconds": after_seconds,
            "trigger_start": to_iso(trigger_start),
            "trigger_end": to_iso(trigger_end) if trigger_end else None,
        },
    }


def video_contexts(
    connection: sqlite3.Connection,
    filters: ReadModelFilters,
    *,
    trigger_type: str | None = None,
    context_id: str | None = None,
    before_seconds: int = VIDEO_CONTEXT_DEFAULT_BEFORE_SECONDS,
    after_seconds: int = VIDEO_CONTEXT_DEFAULT_AFTER_SECONDS,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    change_payload = operational_change_anomalies(connection, filters, now=now)
    triggers = [_trigger_from_change(item) for item in change_payload["changes"]]
    triggers.extend(_trigger_from_anomaly(item) for item in change_payload["anomalies"])
    deduped: dict[str, dict[str, Any]] = {}
    for trigger in triggers:
        context_trigger = {key: value for key, value in trigger.items() if key != "item"}
        cid = _context_id_for_trigger(context_trigger)
        if trigger_type and trigger.get("type") != trigger_type:
            continue
        if context_id and cid != context_id:
            continue
        deduped.setdefault(cid, trigger)
    contexts = [
        build_video_context(
            connection,
            filters,
            trigger,
            before_seconds=before_seconds,
            after_seconds=after_seconds,
            now=now,
        )
        for trigger in deduped.values()
    ]
    contexts.sort(key=lambda item: (item["start_ts"], item["context_id"]))
    return {
        "period": change_payload["period"],
        "filters": change_payload["filters"],
        "contexts": contexts,
        "count": len(contexts),
        "cause_inferred": False,
        "sources": ["operational_timeline", "operational_samples", "eventos", "change_anomalies"],
    }


def _source_bounds_for_video_context(connection: sqlite3.Connection, filters: ReadModelFilters) -> tuple[datetime, datetime] | None:
    sample_clauses: list[str] = []
    sample_params: list[Any] = []
    event_clauses: list[str] = []
    event_params: list[Any] = []
    for sample_column, event_column, value in (
        ("tenant_id", "cliente_id", filters.cliente_id),
        ("site_id", "site_id", filters.site_id),
        ("area_context_id", "area_context_id", filters.area_context_id),
        ("process_id", "process_id", filters.process_id),
        ("asset_id", "asset_id", filters.asset_id),
        ("camera_id", "camera_id", filters.camera_id),
    ):
        if value:
            sample_clauses.append(f"{sample_column} = ?")
            sample_params.append(value)
            event_clauses.append(f"{event_column} = ?")
            event_params.append(value)
    sample_where = f"WHERE {' AND '.join(sample_clauses)}" if sample_clauses else ""
    event_where = f"WHERE {' AND '.join(event_clauses)}" if event_clauses else ""
    sample_row = connection.execute(
        f"SELECT MIN(sample_at) AS min_ts, MAX(sample_at) AS max_ts FROM operational_samples {sample_where}",
        sample_params,
    ).fetchone()
    event_row = connection.execute(
        f"SELECT MIN(inicio) AS min_ts, MAX(COALESCE(fim, inicio)) AS max_ts FROM eventos {event_where}",
        event_params,
    ).fetchone()
    timestamps = [
        value
        for row in (sample_row, event_row)
        if row
        for value in (row["min_ts"], row["max_ts"])
        if value
    ]
    if not timestamps:
        return None
    parsed = [parse_datetime(str(value)) for value in timestamps]
    return min(parsed), max(parsed)


def _visual_candidate_context_by_id(
    connection: sqlite3.Connection,
    filters: ReadModelFilters,
    context_id: str,
) -> dict[str, Any] | None:
    clauses = ["metadata_json LIKE ?"]
    params: list[Any] = ["%visual_candidate%"]

    for column, value in (
        ("tenant_id", filters.cliente_id),
        ("unit_id", filters.site_id),
        ("camera_id", filters.camera_id),
    ):
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)

    rows = connection.execute(
        f"""
        SELECT
            id,
            tenant_id,
            unit_id,
            camera_id,
            machine_id,
            path,
            media_type,
            size_bytes,
            created_at,
            metadata_json
        FROM evidences
        WHERE {' AND '.join(clauses)}
        ORDER BY created_at, id
        """,
        params,
    ).fetchall()

    grouped: dict[str, list[dict[str, Any]]] = {}

    for row in rows:
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            continue

        if metadata.get("source") != "visual_candidate":
            continue

        candidate_id = metadata.get("candidate_id")
        if not candidate_id:
            continue

        captured_at = metadata.get("captured_at") or row["created_at"]

        if filters.start and parse_datetime(captured_at) < filters.start:
            continue
        if filters.end and parse_datetime(captured_at) > filters.end:
            continue

        grouped.setdefault(str(candidate_id), []).append(
            {
                "row": row,
                "metadata": metadata,
                "captured_at": captured_at,
            }
        )

    for candidate_id, items in grouped.items():
        first = items[0]
        first_row = first["row"]
        first_metadata = first["metadata"]

        candidate_type = str(first_metadata.get("candidate_type") or "scene_change")
        triggered_at = first_metadata.get("triggered_at") or first["captured_at"]

        candidate_context = dict(first_metadata.get("context") or {})
        candidate_context.setdefault("camera_id", first_row["camera_id"])

        if first_row["machine_id"]:
            candidate_context.setdefault("asset_id", first_row["machine_id"])

        trigger = {
            "type": f"visual_candidate_{candidate_type}",
            "ref": candidate_id,
            "timestamp": triggered_at,
            "context": candidate_context,
            "source": "visual_evidence_bundle",
        }

        candidate_context_id = _context_id_for_trigger(trigger)
        if candidate_context_id != context_id:
            continue

        phases: dict[str, list[dict[str, Any]]] = {
            "before": [],
            "transition": [],
            "during": [],
            "after": [],
        }
        observations: list[dict[str, Any]] = []
        evidence_refs: list[dict[str, Any]] = []
        timestamps: list[datetime] = []

        for item in items:
            row = item["row"]
            metadata = item["metadata"]
            phase = str(metadata.get("phase") or "during")

            if phase not in phases:
                phase = "during"

            captured_at = item["captured_at"]
            timestamps.append(parse_datetime(captured_at))

            evidence_ref = {
                "evidence_id": row["id"],
                "path": row["path"],
                "media_type": row["media_type"],
                "size_bytes": row["size_bytes"],
            }

            fact = {
                "timestamp": captured_at,
                "type": "visual_evidence",
                "title": "Evidência visual",
                "description": f"Evidência visual do candidato {candidate_type}.",
                "previous_state": None,
                "new_state": None,
                "duration_seconds": None,
                "confidence": None,
                "data_quality": "observed",
                "event_uuid": None,
                "evidence_refs": [evidence_ref],
            }

            phases[phase].append(fact)
            observations.append(fact)
            evidence_refs.append(evidence_ref)

        if not timestamps:
            continue

        trigger_ts = parse_datetime(triggered_at)
        start_ts = min(timestamps)
        end_ts = max(timestamps)

        present_phases = {
            phase: facts
            for phase, facts in phases.items()
            if facts
        }

        required_phases = {"before", "transition", "after"}
        missing_phases = sorted(required_phases - set(present_phases))

        return {
            "context_id": candidate_context_id,
            "camera_id": candidate_context.get("camera_id"),
            "asset_id": candidate_context.get("asset_id"),
            "start_ts": to_iso(start_ts),
            "end_ts": to_iso(end_ts),
            "trigger": trigger,
            "phases": present_phases,
            "observations": observations,
            "events": [],
            "anomalies": [],
            "evidence_refs": _dedupe_refs(evidence_refs),
            "data_quality": {
                "status": "complete" if not missing_phases else "partial",
                "coverage_status": "visual_evidence_bundle",
                "gaps": [],
                "has_unknown": False,
                "evidence_available": bool(evidence_refs),
                "missing_phases": missing_phases,
                "sample_count": len(observations),
            },
            "cause_inferred": False,
            "window": {
                "before_seconds": max(0.0, (trigger_ts - start_ts).total_seconds()),
                "after_seconds": max(0.0, (end_ts - trigger_ts).total_seconds()),
                "trigger_start": to_iso(trigger_ts),
                "trigger_end": None,
            },
        }

    return None


def video_context_by_id(
    connection: sqlite3.Connection,
    filters: ReadModelFilters,
    context_id: str,
    *,
    before_seconds: int = VIDEO_CONTEXT_DEFAULT_BEFORE_SECONDS,
    after_seconds: int = VIDEO_CONTEXT_DEFAULT_AFTER_SECONDS,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    now = now or datetime.now(timezone.utc)
    if filters.start and filters.end:
        payload = video_contexts(
            connection,
            filters,
            context_id=context_id,
            before_seconds=before_seconds,
            after_seconds=after_seconds,
            now=now,
        )
        if payload["contexts"]:
            return payload["contexts"][0]
        return _visual_candidate_context_by_id(connection, filters, context_id)

    bounds = _source_bounds_for_video_context(connection, filters)
    if bounds is None:
        return _visual_candidate_context_by_id(connection, filters, context_id)
    source_start, source_end = bounds
    search_filters = ReadModelFilters(
        cliente_id=filters.cliente_id,
        site_id=filters.site_id,
        area_context_id=filters.area_context_id,
        process_id=filters.process_id,
        asset_id=filters.asset_id,
        camera_id=filters.camera_id,
        event_family=filters.event_family,
        tipo=filters.tipo,
        workflow_status=filters.workflow_status,
        start=source_start - timedelta(seconds=before_seconds),
        end=source_end + timedelta(seconds=after_seconds),
    )
    payload = video_contexts(
        connection,
        search_filters,
        context_id=context_id,
        before_seconds=before_seconds,
        after_seconds=after_seconds,
        now=now,
    )
    if payload["contexts"]:
        return payload["contexts"][0]
    return _visual_candidate_context_by_id(connection, filters, context_id)


def operational_data(connection: sqlite3.Connection, filters: ReadModelFilters, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    if not filters.start or not filters.end:
        raise ValueError("Dados operacionais requerem início e fim.")
    events = list_events(connection, filters, now=now)
    samples = _list_samples(connection, filters)
    rollup = _sample_rollup(samples, filters.start, filters.end)
    classified_events = _official_events(events)
    stoppages = [event for event in classified_events if event.get("tipo") == "machine_stoppage"]
    absences = [event for event in classified_events if event.get("tipo") in {"workstation_unattended", "machine_running_without_operator"}]
    zone_events = [event for event in events if event.get("area_id") or event.get("tipo") in {"restricted_zone_occupied", "restricted_area_occupied", "excessive_zone_dwell"}]
    proximity_observations = []
    for sample in samples:
        metadata = sample.get("metadata") or {}
        for observation in metadata.get("canonical_observations", []) if isinstance(metadata.get("canonical_observations"), list) else []:
            if observation.get("observation_type") == "person_vehicle_proximity":
                proximity_observations.append(observation)
    stopped_total = sum(float(event.get("read_duration_seconds") or 0) for event in stoppages)
    absence_total = sum(float(event.get("read_duration_seconds") or 0) for event in absences)
    return {
        "period": {"start": to_iso(filters.start), "end": to_iso(filters.end)},
        "filters": {key: value for key, value in filters.__dict__.items() if value is not None and key not in {"start", "end"}},
        "coverage": rollup["coverage"],
        "machine_data": {
            "observed_total_seconds": round(sum(rollup["machine"].values()), 3),
            "active_seconds": round(rollup["machine"]["ACTIVE"], 3),
            "stopped_seconds": round(rollup["machine"]["STOPPED"], 3),
            "unknown_seconds": round(rollup["machine"]["UNKNOWN"], 3),
            "visual_availability_percent": round((rollup["machine"]["ACTIVE"] / max(1.0, rollup["machine"]["ACTIVE"] + rollup["machine"]["STOPPED"])) * 100, 2) if (rollup["machine"]["ACTIVE"] + rollup["machine"]["STOPPED"]) else None,
            "stoppage_count": len(stoppages),
            "stoppage_total_seconds": round(stopped_total, 3),
            "average_stoppage_seconds": round(stopped_total / len(stoppages), 3) if stoppages else 0,
            "max_stoppage_seconds": round(max((float(event.get("read_duration_seconds") or 0) for event in stoppages), default=0), 3),
            "critical_times": [{"started_at": event.get("inicio"), "duration_seconds": event.get("read_duration_seconds"), "event_uuid": _event_uuid(event)} for event in stoppages],
            "traceability": {"event_uuids": [_event_uuid(event) for event in stoppages], "observation_types": ["machine_activity"]},
        },
        "human_operation_data": {
            "presence_seconds": round(rollup["human"]["PRESENT"], 3),
            "absence_seconds": round(rollup["human"]["ABSENT"], 3),
            "unknown_seconds": round(rollup["human"]["UNKNOWN"], 3),
            "absence_count": len(absences),
            "absence_total_seconds": round(absence_total, 3),
            "absence_periods": [{"started_at": event.get("inicio"), "ended_at": event.get("fim"), "duration_seconds": event.get("read_duration_seconds"), "event_uuid": _event_uuid(event)} for event in absences],
            "traceability": {"event_uuids": [_event_uuid(event) for event in absences], "observation_types": ["person_presence", "zone_occupancy"]},
        },
        "zone_safety_data": {
            "occupancy_event_count": len(zone_events),
            "occupancy_total_seconds": round(sum(float(event.get("read_duration_seconds") or 0) for event in zone_events), 3),
            "occupancies": [{"event_uuid": _event_uuid(event), "tipo": event.get("tipo"), "area_id": event.get("area_id"), "duration_seconds": event.get("read_duration_seconds"), "evidence": event.get("midia_path")} for event in zone_events],
            "person_vehicle_proximity": {
                "observations_count": len(proximity_observations),
                "near_count": sum(1 for item in proximity_observations if item.get("value") == "NEAR"),
                "candidate_count": sum(1 for item in proximity_observations if item.get("value") == "CANDIDATE"),
                "vehicle_classes": sorted({str((item.get("metadata") or {}).get("vehicle_class")) for item in proximity_observations if (item.get("metadata") or {}).get("vehicle_class")}),
                "status": "OBSERVATION_SUPPORTED_EVENT_NOT_YET_DEFINED",
            },
            "traceability": {"event_uuids": [_event_uuid(event) for event in zone_events], "observation_types": ["zone_occupancy", "person_vehicle_proximity"]},
        },
        "data_quality": {
            "unknown_seconds": round(rollup["machine"]["UNKNOWN"], 3),
            "unknown_is_not_counted_as_active_or_stopped": True,
            "sample_count": len(samples),
        },
    }


def daily_report(connection: sqlite3.Connection, filters: ReadModelFilters, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    data = operational_data(connection, filters, now=now)
    summary = period_summary(connection, filters, now=now)
    intel = intelligence(connection, filters, now=now)
    events = list_events(connection, filters, now=now)
    main_events = sorted(events, key=lambda event: float(event.get("read_duration_seconds") or 0), reverse=True)[:10]
    return {
        "report_type": "daily_operational_report_v1",
        "period": data["period"],
        "coverage": data["coverage"],
        "summary": {
            "machines": data["machine_data"],
            "human_operation": data["human_operation_data"],
            "zones_safety": data["zone_safety_data"],
        },
        "main_events": [
            {
                "event_uuid": _event_uuid(event),
                "tipo": event.get("tipo"),
                "event_family": event.get("event_family") or EVENT_FAMILY_UNKNOWN,
                "started_at": event.get("inicio"),
                "ended_at": event.get("fim"),
                "duration_seconds": event.get("read_duration_seconds"),
                "context": {
                    "site_id": event.get("site_id"),
                    "area_id": event.get("area_context_id") or event.get("area_id"),
                    "process_id": event.get("process_id"),
                    "asset_id": event.get("asset_id") or event.get("machine_monitor_id"),
                    "camera_id": event.get("camera_id"),
                },
                "evidence": event.get("midia_path"),
            }
            for event in main_events
        ],
        "intelligence": {
            "briefing": intel["briefing"],
            "attention": intel["attention"],
            "patterns": intel["patterns"],
            "confirmed_causes": intel["confirmed_causes"],
        },
        "traceability": {
            "event_uuids": summary["event_uuids"],
            "why": "Cada métrica referencia events/event_uuids e observation_types usados no cálculo.",
        },
    }


def current_operation(connection: sqlite3.Connection, filters: ReadModelFilters | None = None, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    filters = filters or ReadModelFilters()
    current_filters = ReadModelFilters(**{**filters.__dict__, "start": None, "end": None})
    where, params = _build_event_query(current_filters)
    open_clause = "status = 'open'"
    where = f"{where} AND {open_clause}" if where else f"WHERE {open_clause}"
    rows = connection.execute(
        f"""
        SELECT *
        FROM eventos
        {where}
        ORDER BY inicio ASC, criado_em ASC
        """,
        params,
    ).fetchall()
    events = [row_to_dict(row) for row in rows]
    for event in events:
        event["event_family"] = event.get("event_family") or EVENT_FAMILY_UNKNOWN
        event["current_duration_seconds"] = _overlap_seconds(event, parse_datetime(event.get("inicio"), now), now, now)
        event["event_uuid"] = _event_uuid(event)
    return {"as_of": to_iso(now), "open_events": events, "total_open_events": len(events)}


def period_summary(connection: sqlite3.Connection, filters: ReadModelFilters, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    events = list_events(connection, filters, now=now)
    total_duration = sum(float(event.get("read_duration_seconds") or 0) for event in events)
    unresolved = [event for event in events if (event.get("workflow_status") or "new") == "new"]
    causes = _group_events(events, "confirmed_cause")
    for cause in causes:
        if cause["key"] == "não informado":
            cause["key"] = "causa não informada"
    return {
        "period": {"start": to_iso(filters.start) if filters.start else None, "end": to_iso(filters.end) if filters.end else None},
        "filters": {key: value for key, value in filters.__dict__.items() if value is not None and key not in {"start", "end"}},
        "total_events": len(events),
        "total_duration_seconds": round(total_duration, 3),
        "average_duration_seconds": round(total_duration / len(events), 3) if events else 0,
        "events_by_family": _group_events(events, "event_family"),
        "duration_by_family": _group_events(events, "event_family"),
        "events_by_area": _group_events(events, "area_context_id"),
        "events_by_process": _group_events(events, "process_id"),
        "events_by_asset": _group_events(events, "asset_id"),
        "events_pending_human_analysis": {"total": len(unresolved), "event_uuids": [_event_uuid(event) for event in unresolved]},
        "confirmed_causes": causes,
        "actions_taken": _group_events([event for event in events if event.get("action_taken")], "action_taken"),
        "event_uuids": [_event_uuid(event) for event in events],
        "coverage": _coverage(connection, filters),
    }


def losses(connection: sqlite3.Connection, filters: ReadModelFilters, *, now: datetime | None = None) -> dict[str, Any]:
    events = [event for event in list_events(connection, filters, now=now) if (event.get("event_family") or EVENT_FAMILY_UNKNOWN) in LOSS_FAMILIES]
    return {
        "period": {"start": to_iso(filters.start) if filters.start else None, "end": to_iso(filters.end) if filters.end else None},
        "loss_families": sorted(LOSS_FAMILIES),
        "by_asset": _group_events(events, "asset_id"),
        "by_process": _group_events(events, "process_id"),
        "by_area": _group_events(events, "area_context_id"),
        "by_family": _group_events(events, "event_family"),
        "excluded_unknown_or_non_loss_event_uuids": [
            _event_uuid(event)
            for event in list_events(connection, filters, now=now)
            if (event.get("event_family") or EVENT_FAMILY_UNKNOWN) not in LOSS_FAMILIES
        ],
    }


def _comparison_metric(current: dict[str, Any], previous: dict[str, Any], key: str) -> dict[str, Any]:
    current_value = float(current.get(key) or 0)
    previous_value = float(previous.get(key) or 0)
    diff = current_value - previous_value
    percent = None if previous_value == 0 else round((diff / previous_value) * 100, 3)
    return {"current": current_value, "previous": previous_value, "absolute_difference": round(diff, 3), "percent_change": percent}


def comparison(connection: sqlite3.Connection, filters: ReadModelFilters, *, now: datetime | None = None) -> dict[str, Any]:
    if not filters.start or not filters.end:
        raise ValueError("Comparação requer início e fim.")
    previous_start, previous_end = previous_period(filters.start, filters.end)
    current_summary = period_summary(connection, filters, now=now)
    previous_filters = ReadModelFilters(**{**filters.__dict__, "start": previous_start, "end": previous_end})
    previous_summary = period_summary(connection, previous_filters, now=now)
    return {
        "current_period": current_summary["period"],
        "previous_period": previous_summary["period"],
        "metrics": {
            "total_events": _comparison_metric(current_summary, previous_summary, "total_events"),
            "total_duration_seconds": _comparison_metric(current_summary, previous_summary, "total_duration_seconds"),
            "average_duration_seconds": _comparison_metric(current_summary, previous_summary, "average_duration_seconds"),
        },
        "current_event_uuids": current_summary["event_uuids"],
        "previous_event_uuids": previous_summary["event_uuids"],
    }


def _insight(
    *,
    insight_id: str,
    statement: str,
    number: str,
    why: str,
    event_uuids: list[str],
    severity: str = "info",
    rule_id: str,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "insight_id": insight_id,
        "statement": statement,
        "number": number,
        "why": why,
        "severity": severity,
        "event_uuids": event_uuids,
        "rule_id": rule_id,
        "rule_version": "intelligence_v0",
        "metrics_used": metrics or {},
        "recommended_action": "Investigar os eventos relacionados e confirmar causa ou ação quando necessário.",
    }


def _top(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    return items[0] if items else None


def _current_previous_text(metric: dict[str, Any]) -> str:
    if metric.get("percent_change") is None:
        return "sem base anterior suficiente"
    sign = "+" if float(metric["percent_change"]) > 0 else ""
    return f"{sign}{metric['percent_change']}% vs período anterior"


def _metric_from_values(current_value: float, previous_value: float) -> dict[str, Any]:
    diff = current_value - previous_value
    percent = None if previous_value == 0 else round((diff / previous_value) * 100, 3)
    return {"current": round(current_value, 3), "previous": round(previous_value, 3), "absolute_difference": round(diff, 3), "percent_change": percent}


def _hour_bucket(event: dict[str, Any]) -> str | None:
    value = event.get("inicio")
    if not value:
        return None
    hour = parse_datetime(value).hour
    return f"{hour:02d}h-{(hour + 1) % 24:02d}h"


def _events_with_operator_absence(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    related: list[dict[str, Any]] = []
    for event in events:
        observed = event.get("observed_context") or event.get("metadata") or ""
        text = str(observed).lower()
        if "operator_absent" in text or "operador ausente" in text or event.get("operator_present") == 0:
            related.append(event)
    return related


def intelligence(connection: sqlite3.Connection, filters: ReadModelFilters, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    events = list_events(connection, filters, now=now)
    classified_events = _official_events(events)
    summary = period_summary(connection, filters, now=now)
    loss_summary = losses(connection, filters, now=now)
    comparison_payload = comparison(connection, filters, now=now) if filters.start and filters.end else None
    official_comparison = None
    previous_classified_events: list[dict[str, Any]] = []
    if filters.start and filters.end:
        previous_start, previous_end = previous_period(filters.start, filters.end)
        previous_filters = ReadModelFilters(**{**filters.__dict__, "start": previous_start, "end": previous_end})
        previous_classified_events = _official_events(list_events(connection, previous_filters, now=now))
        current_duration = sum(float(event.get("read_duration_seconds") or 0) for event in classified_events)
        previous_duration = sum(float(event.get("read_duration_seconds") or 0) for event in previous_classified_events)
        current_avg = current_duration / len(classified_events) if classified_events else 0
        previous_avg = previous_duration / len(previous_classified_events) if previous_classified_events else 0
        official_comparison = {
            "metrics": {
                "total_events": _metric_from_values(float(len(classified_events)), float(len(previous_classified_events))),
                "total_duration_seconds": _metric_from_values(current_duration, previous_duration),
                "average_duration_seconds": _metric_from_values(current_avg, previous_avg),
            },
            "current_event_uuids": [_event_uuid(event) for event in classified_events],
            "previous_event_uuids": [_event_uuid(event) for event in previous_classified_events],
        }
    unknown_events = [event for event in events if (event.get("event_family") or EVENT_FAMILY_UNKNOWN) not in OFFICIAL_EVENT_FAMILIES]

    insights: list[dict[str, Any]] = []
    patterns: list[dict[str, Any]] = []
    briefing: list[str] = []

    if not classified_events:
        briefing.append("Ainda não existem eventos operacionais classificados suficientes neste período.")
    else:
        top_family = _top([item for item in summary["events_by_family"] if item["key"] in OFFICIAL_EVENT_FAMILIES])
        top_asset = _top([item for item in loss_summary["by_asset"] if item["key"] != "não informado"])
        if top_family:
            briefing.append(f"{_family_label(top_family['key']).capitalize()} somaram {_seconds_label(top_family['total_duration_seconds'])} no período.")
            insights.append(
                _insight(
                    insight_id=f"family_concentration:{top_family['key']}",
                    statement=f"{_family_label(top_family['key']).capitalize()} concentraram a maior duração classificada do período.",
                    number=_seconds_label(top_family["total_duration_seconds"]),
                    why=f"{top_family['total_events']} evento(s) classificados como {_family_label(top_family['key'])}.",
                    event_uuids=top_family["event_uuids"],
                    rule_id="top_family_duration",
                    metrics={"event_family": top_family["key"], "duration_seconds": top_family["total_duration_seconds"], "events": top_family["total_events"]},
                )
            )
        if top_asset and float(top_asset.get("total_duration_seconds") or 0) > 0:
            total_loss_duration = sum(float(item.get("total_duration_seconds") or 0) for item in loss_summary["by_family"])
            share = round((float(top_asset["total_duration_seconds"]) / total_loss_duration) * 100, 1) if total_loss_duration else 0
            briefing.append(f"{top_asset['key']} concentrou {share}% do tempo classificado como perda operacional.")
            insights.append(
                _insight(
                    insight_id=f"asset_loss_concentration:{top_asset['key']}",
                    statement=f"{top_asset['key']} concentrou {share}% das perdas monitoradas.",
                    number=_seconds_label(top_asset["total_duration_seconds"]),
                    why=f"{top_asset['total_events']} evento(s) em famílias classificadas como perda operacional.",
                    event_uuids=top_asset["event_uuids"],
                    severity="warning" if share >= 40 else "info",
                    rule_id="top_asset_loss_share",
                    metrics={"asset_id": top_asset["key"], "share_percent": share, "duration_seconds": top_asset["total_duration_seconds"]},
                )
            )

        if official_comparison:
            duration_metric = official_comparison["metrics"]["total_duration_seconds"]
            if duration_metric["percent_change"] is not None and abs(float(duration_metric["percent_change"])) >= 10:
                direction = "aumentou" if float(duration_metric["absolute_difference"]) > 0 else "reduziu"
                insights.append(
                    _insight(
                        insight_id="period_duration_change",
                        statement=f"A duração total dos eventos {direction} no período.",
                        number=_current_previous_text(duration_metric),
                        why=f"{_seconds_label(duration_metric['current'])} no período atual contra {_seconds_label(duration_metric['previous'])} no período anterior.",
                        event_uuids=official_comparison["current_event_uuids"],
                        severity="warning" if float(duration_metric["absolute_difference"]) > 0 else "info",
                        rule_id="period_over_period_duration",
                        metrics=duration_metric,
                    )
                )

        by_asset = [item for item in summary["events_by_asset"] if item["key"] != "não informado"]
        repeated_asset = next((item for item in by_asset if int(item["total_events"]) >= 3), None)
        if repeated_asset:
            patterns.append(
                _insight(
                    insight_id=f"asset_recurrence:{repeated_asset['key']}",
                    statement=f"{repeated_asset['total_events']} ocorrências foram registradas no ativo {repeated_asset['key']}.",
                    number=f"{repeated_asset['total_events']} eventos",
                    why="A recorrência é matemática: mesmo ativo com três ou mais eventos classificados no período.",
                    event_uuids=repeated_asset["event_uuids"],
                    rule_id="asset_recurrence_count",
                    metrics={"asset_id": repeated_asset["key"], "events": repeated_asset["total_events"]},
                )
            )

        by_hour: dict[str, dict[str, Any]] = {}
        for event in classified_events:
            bucket = _hour_bucket(event)
            if not bucket:
                continue
            item = by_hour.setdefault(bucket, {"key": bucket, "total_events": 0, "event_uuids": []})
            item["total_events"] += 1
            item["event_uuids"].append(_event_uuid(event))
        top_hour = sorted(by_hour.values(), key=lambda item: (-item["total_events"], item["key"]))[:1]
        if top_hour and top_hour[0]["total_events"] >= 2:
            item = top_hour[0]
            patterns.append(
                _insight(
                    insight_id=f"hour_concentration:{item['key']}",
                    statement=f"{item['total_events']} eventos classificados ocorreram entre {item['key']}.",
                    number=f"{item['total_events']} eventos",
                    why="A concentração temporal foi identificada por contagem de eventos no mesmo intervalo de uma hora.",
                    event_uuids=item["event_uuids"],
                    rule_id="hourly_event_concentration",
                    metrics={"hour_bucket": item["key"], "events": item["total_events"]},
                )
            )

        absence_related = _events_with_operator_absence(classified_events)
        interruption_events = [event for event in classified_events if event.get("event_family") == EVENT_FAMILY_INTERRUPTION]
        if interruption_events and absence_related:
            patterns.append(
                _insight(
                    insight_id="interruption_with_observed_absence",
                    statement=f"Em {len(absence_related)} de {len(interruption_events)} interrupções havia ausência observada no contexto.",
                    number=f"{len(absence_related)}/{len(interruption_events)}",
                    why="A Campex relata apenas a simultaneidade observada; isso não é causa confirmada.",
                    event_uuids=[_event_uuid(event) for event in absence_related],
                    rule_id="observed_absence_overlap",
                    metrics={"interruption_events": len(interruption_events), "events_with_observed_absence": len(absence_related)},
                )
            )

    family_groups = {item["key"]: item for item in summary["events_by_family"] if item["key"] in OFFICIAL_EVENT_FAMILIES}
    kpis = [
        {"key": "interruption_duration", "label": "Duração de interrupções", "value_seconds": float(family_groups.get(EVENT_FAMILY_INTERRUPTION, {}).get("total_duration_seconds") or 0), "event_uuids": family_groups.get(EVENT_FAMILY_INTERRUPTION, {}).get("event_uuids", [])},
        {"key": "interruption_frequency", "label": "Frequência de interrupções", "value": int(family_groups.get(EVENT_FAMILY_INTERRUPTION, {}).get("total_events") or 0), "event_uuids": family_groups.get(EVENT_FAMILY_INTERRUPTION, {}).get("event_uuids", [])},
        {"key": "average_duration", "label": "Duração média", "value_seconds": (sum(float(event.get("read_duration_seconds") or 0) for event in classified_events) / len(classified_events)) if classified_events else 0, "event_uuids": [_event_uuid(event) for event in classified_events]},
        {"key": "wait_duration", "label": "Espera", "value_seconds": float(family_groups.get(EVENT_FAMILY_WAIT, {}).get("total_duration_seconds") or 0), "event_uuids": family_groups.get(EVENT_FAMILY_WAIT, {}).get("event_uuids", [])},
        {"key": "absence_duration", "label": "Ausência", "value_seconds": float(family_groups.get(EVENT_FAMILY_ABSENCE, {}).get("total_duration_seconds") or 0), "event_uuids": family_groups.get(EVENT_FAMILY_ABSENCE, {}).get("event_uuids", [])},
        {"key": "recurrence", "label": "Recorrência", "value": max((int(item["total_events"]) for item in summary["events_by_asset"]), default=0), "event_uuids": (_top(summary["events_by_asset"]) or {}).get("event_uuids", [])},
    ]

    causes = _group_events(classified_events, "confirmed_cause")
    for cause in causes:
        if cause["key"] == "não informado":
            cause["key"] = "causa não informada"
    return {
        "period": summary["period"],
        "filters": summary["filters"],
        "coverage": summary["coverage"],
        "briefing": briefing,
        "attention": insights[:5],
        "patterns": patterns[:5],
        "kpis": kpis,
        "confirmed_causes": causes,
        "comparison": official_comparison or comparison_payload,
        "traceability": {"event_uuids": [_event_uuid(event) for event in classified_events]},
        "data_quality": {
            "classified_events": len(classified_events),
            "unknown_events": len(unknown_events),
            "unknown_event_uuids": [_event_uuid(event) for event in unknown_events],
        },
    }
