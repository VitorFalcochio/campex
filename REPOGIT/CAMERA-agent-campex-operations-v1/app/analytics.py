from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.models import new_id, row_to_dict
from shared.schemas import now_iso


DEFAULT_TIMEZONE = "America/Sao_Paulo"
STOP_EVENT_TYPES = {"machine_stoppage", "machine_stopped_with_operator", "repeated_microstops"}
RUNNING_WITHOUT_OPERATOR_TYPES = {"machine_running_without_operator", "workstation_unattended"}
OFFLINE_EVENT_TYPES = {"camera_offline", "camera_status_offline", "camera_status"}


def parse_dt(value: str | None, default: datetime | None = None) -> datetime:
    if not value:
        if default is None:
            return datetime.now(timezone.utc)
        return default
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def overlap_seconds(start: datetime, end: datetime, window_start: datetime, window_end: datetime) -> float:
    effective_start = max(start, window_start)
    effective_end = min(end, window_end)
    return max(0.0, (effective_end - effective_start).total_seconds())


def load_shift_config() -> list[dict[str, str]]:
    raw = os.getenv("CAMPEX_SHIFT_CONFIG_JSON")
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, list) and data:
                return data
        except json.JSONDecodeError:
            pass
    return [
        {"name": "turno_1", "start": "06:00", "end": "14:00"},
        {"name": "turno_2", "start": "14:00", "end": "22:00"},
        {"name": "turno_3", "start": "22:00", "end": "06:00"},
    ]


def list_events(
    connection,
    machine_id: str | None,
    start: datetime,
    end: datetime,
    camera_id: str | None = None,
    event_family: str | None = None,
    area_context_id: str | None = None,
    process_id: str | None = None,
    asset_id: str | None = None,
    confirmed_cause: str | None = None,
) -> list[dict[str, Any]]:
    clauses = ["inicio <= ?", "COALESCE(fim, ?) >= ?"]
    params: list[Any] = [iso(end), iso(end), iso(start)]
    if machine_id:
        clauses.append("machine_monitor_id = ?")
        params.append(machine_id)
    if camera_id:
        clauses.append("camera_id = ?")
        params.append(camera_id)
    if event_family:
        clauses.append("event_family = ?")
        params.append(event_family)
    if area_context_id:
        clauses.append("area_context_id = ?")
        params.append(area_context_id)
    if process_id:
        clauses.append("process_id = ?")
        params.append(process_id)
    if asset_id:
        clauses.append("asset_id = ?")
        params.append(asset_id)
    if confirmed_cause:
        clauses.append("COALESCE(confirmed_cause, cause_category) = ?")
        params.append(confirmed_cause)
    rows = connection.execute(
        f"""
        SELECT *
        FROM eventos
        WHERE {' AND '.join(clauses)}
        ORDER BY inicio ASC
        """,
        params,
    ).fetchall()
    return [row_to_dict(row) for row in rows]


def list_samples(connection, machine_id: str | None, start: datetime, end: datetime, camera_id: str | None = None) -> list[dict[str, Any]]:
    clauses = ["sample_at >= ?", "sample_at <= ?"]
    params: list[Any] = [iso(start), iso(end)]
    if machine_id:
        clauses.append("machine_id = ?")
        params.append(machine_id)
    if camera_id:
        clauses.append("camera_id = ?")
        params.append(camera_id)
    rows = connection.execute(
        f"""
        SELECT *
        FROM operational_samples
        WHERE {' AND '.join(clauses)}
        ORDER BY sample_at ASC
        """,
        params,
    ).fetchall()
    return [row_to_dict(row) for row in rows]


def compute_summary(
    connection,
    *,
    machine_id: str | None,
    start: datetime,
    end: datetime,
    camera_id: str | None = None,
    event_family: str | None = None,
    area_context_id: str | None = None,
    process_id: str | None = None,
    asset_id: str | None = None,
    confirmed_cause: str | None = None,
) -> dict[str, Any]:
    total = max(0.0, (end - start).total_seconds())
    events = list_events(
        connection,
        machine_id,
        start,
        end,
        camera_id,
        event_family=event_family,
        area_context_id=area_context_id,
        process_id=process_id,
        asset_id=asset_id,
        confirmed_cause=confirmed_cause,
    )
    samples = list_samples(connection, machine_id, start, end, camera_id)
    event_counts = Counter(event["tipo"] for event in events)
    family_counts = Counter((event.get("event_family") or "unknown") for event in events)

    stopped = 0.0
    running_without_operator = 0.0
    stopped_with_operator = 0.0
    offline = 0.0
    stop_durations: list[float] = []
    related_stop_ids: list[str] = []
    for event in events:
        event_start = parse_dt(event.get("inicio"), start)
        event_end = parse_dt(event.get("fim"), end) if event.get("fim") else end
        duration = overlap_seconds(event_start, event_end, start, end)
        event_type = str(event.get("tipo") or "")
        if event_type in STOP_EVENT_TYPES:
            stopped += duration
            stop_durations.append(duration)
            related_stop_ids.append(str(event["id"]))
        if event_type in RUNNING_WITHOUT_OPERATOR_TYPES:
            running_without_operator += duration
        if event_type == "machine_stopped_with_operator":
            stopped_with_operator += duration
        if event_type in OFFLINE_EVENT_TYPES and str(event.get("status") or "") != "open":
            offline += duration

    active_samples = [sample for sample in samples if sample.get("machine_state") == "ACTIVE"]
    stopped_samples = [sample for sample in samples if sample.get("machine_state") == "STOPPED"]
    offline_samples = [sample for sample in samples if sample.get("camera_online") == 0]
    monitored_from_samples = bool(samples)
    estimated_active = 0.0
    if monitored_from_samples and total > 0:
        estimated_active = total * (len(active_samples) / max(len(samples), 1))
        stopped = max(stopped, total * (len(stopped_samples) / max(len(samples), 1)))
        offline = max(offline, total * (len(offline_samples) / max(len(samples), 1)))

    reliable_coverage = 0.0
    if monitored_from_samples and total > 0:
        reliable_coverage = max(0.0, min(1.0, len(samples) * 10.0 / total))
    active_time = max(0.0, estimated_active if monitored_from_samples else 0.0)
    alerts = connection.execute(
        """
        SELECT status, COUNT(*) AS total
        FROM alert_deliveries
        WHERE criado_em >= ? AND criado_em <= ?
        GROUP BY status
        """,
        (iso(start), iso(end)),
    ).fetchall()
    alert_counts = {row["status"]: row["total"] for row in alerts}
    no_data_periods = data_quality(connection, machine_id=machine_id, start=start, end=end, camera_id=camera_id)["periods"]
    return {
        "machine_id": machine_id,
        "camera_id": camera_id,
        "start": iso(start),
        "end": iso(end),
        "total_monitored_seconds": round(total, 3),
        "reliable_monitored_seconds": round(total * reliable_coverage, 3),
        "active_seconds": round(active_time, 3),
        "stopped_seconds": round(stopped, 3),
        "availability_percent": round((active_time / total) * 100, 2) if total else None,
        "stoppage_count": len(stop_durations),
        "average_stoppage_seconds": round(sum(stop_durations) / len(stop_durations), 3) if stop_durations else 0,
        "max_stoppage_seconds": round(max(stop_durations), 3) if stop_durations else 0,
        "mean_time_between_stoppages_seconds": round(total / max(len(stop_durations), 1), 3) if stop_durations else None,
        "running_without_operator_seconds": round(running_without_operator, 3),
        "stopped_with_operator_seconds": round(stopped_with_operator, 3),
        "stopped_without_operator_seconds": round(max(0.0, stopped - stopped_with_operator), 3),
        "events_by_type": dict(event_counts),
        "events_by_family": dict(family_counts),
        "alerts": {
            "sent": int(alert_counts.get("sent", 0)),
            "pending": int(alert_counts.get("pending", 0)),
            "failed": int(alert_counts.get("failed", 0)),
        },
        "offline_or_no_data_periods": no_data_periods,
        "reliable_data_coverage_percent": round(reliable_coverage * 100, 2),
        "incomplete": bool(no_data_periods) or not samples,
        "sample_count": len(samples),
        "related_stop_event_ids": related_stop_ids,
    }


def timeline(
    connection,
    *,
    machine_id: str | None,
    start: datetime,
    end: datetime,
    camera_id: str | None = None,
    event_family: str | None = None,
) -> dict[str, Any]:
    events = list_events(connection, machine_id, start, end, camera_id, event_family=event_family)
    return {
        "start": iso(start),
        "end": iso(end),
        "segments": [
            {
                "event_id": event["id"],
                "type": event["tipo"],
                "event_family": event.get("event_family") or "unknown",
                "event_subtype": event.get("event_subtype"),
                "state": event.get("status"),
                "start": event["inicio"],
                "end": event.get("fim"),
                "duration_seconds": event.get("duracao"),
                "camera_id": event.get("camera_id"),
                "machine_id": event.get("machine_monitor_id"),
                "evidence": event.get("midia_path"),
            }
            for event in events
        ],
    }


def data_quality(connection, *, machine_id: str | None, start: datetime, end: datetime, camera_id: str | None = None) -> dict[str, Any]:
    samples = list_samples(connection, machine_id, start, end, camera_id)
    periods: list[dict[str, Any]] = []
    if not samples:
        periods.append({"type": "insufficient_data", "start": iso(start), "end": iso(end), "reason": "Nenhuma amostra operacional no período."})
    elif (parse_dt(samples[0]["sample_at"]) - start).total_seconds() > 120:
        first_at = parse_dt(samples[0]["sample_at"])
        periods.append({"type": "no_frames", "start": iso(start), "end": iso(first_at), "duration_seconds": (first_at - start).total_seconds()})
    for previous, current in zip(samples, samples[1:]):
        previous_at = parse_dt(previous["sample_at"])
        current_at = parse_dt(current["sample_at"])
        gap = (current_at - previous_at).total_seconds()
        if gap > 120:
            periods.append({"type": "no_frames", "start": iso(previous_at), "end": iso(current_at), "duration_seconds": gap})
    if samples:
        last_at = parse_dt(samples[-1]["sample_at"])
        tail_gap = (end - last_at).total_seconds()
        if tail_gap > 120:
            periods.append({"type": "no_frames", "start": iso(last_at), "end": iso(end), "duration_seconds": tail_gap})
    offline = [sample for sample in samples if sample.get("camera_online") == 0]
    if offline:
        periods.append({"type": "camera_offline_samples", "count": len(offline)})
    inactive = [sample for sample in samples if not sample.get("inference_fps")]
    if samples and len(inactive) == len(samples):
        periods.append({"type": "inference_inactive", "reason": "Nenhuma amostra com FPS de inferência informado."})
    return {"start": iso(start), "end": iso(end), "periods": periods, "sample_count": len(samples)}


def generate_insights(connection, *, machine_id: str | None, start: datetime, end: datetime, camera_id: str | None = None) -> list[dict[str, Any]]:
    summary = compute_summary(connection, machine_id=machine_id, start=start, end=end, camera_id=camera_id)
    insights: list[dict[str, Any]] = []
    created_at = now_iso()
    data_quality_label = "partial" if summary.get("incomplete") else "reliable"
    def insight_id(rule_id: str, period_start: str, period_end: str) -> str:
        return f"ins_{hashlib.sha1(f'{machine_id}:{rule_id}:{period_start}:{period_end}'.encode('utf-8')).hexdigest()[:16]}"

    if summary["stopped_seconds"] >= 60:
        minutes = round(summary["stopped_seconds"] / 60, 1)
        rule_id = "stopped_time_threshold_v1"
        insights.append({
            "insight_id": insight_id(rule_id, summary["start"], summary["end"]),
            "title": f"A máquina acumulou {minutes} minutos parada no período.",
            "description": "A soma das paradas consolidadas ultrapassou um minuto no período analisado.",
            "severity": "warning" if minutes < 30 else "critical",
            "period_start": summary["start"],
            "period_end": summary["end"],
            "metrics": {"stopped_seconds": summary["stopped_seconds"], "stoppage_count": summary["stoppage_count"]},
            "related_event_ids": summary["related_stop_event_ids"],
            "rule_id": rule_id,
            "rule_version": "v1",
            "data_quality": data_quality_label,
            "recommended_action": "Revisar as maiores paradas e registrar causa operacional.",
            "created_at": created_at,
        })
    if summary["running_without_operator_seconds"] >= 60:
        rule_id = "running_without_operator_v1"
        insights.append({
            "insight_id": insight_id(rule_id, summary["start"], summary["end"]),
            "title": "A máquina operou sem operador no período.",
            "description": "Eventos confirmados indicaram operação com ausência do operador na zona configurada.",
            "severity": "warning",
            "period_start": summary["start"],
            "period_end": summary["end"],
            "metrics": {"running_without_operator_seconds": summary["running_without_operator_seconds"]},
            "related_event_ids": [],
            "rule_id": rule_id,
            "rule_version": "v1",
            "data_quality": data_quality_label,
            "recommended_action": "Verificar cobertura da zona do operador e rotina de acompanhamento.",
            "created_at": created_at,
        })
    quality = data_quality(connection, machine_id=machine_id, start=start, end=end, camera_id=camera_id)
    if quality["periods"]:
        rule_id = "data_quality_gap_v1"
        insights.append({
            "insight_id": insight_id(rule_id, iso(start), iso(end)),
            "title": "Existem lacunas de dados no período.",
            "description": "Há trechos sem amostras, câmera offline ou inferência inativa; as métricas podem estar incompletas.",
            "severity": "info",
            "period_start": iso(start),
            "period_end": iso(end),
            "metrics": {"periods": quality["periods"]},
            "related_event_ids": [],
            "rule_id": rule_id,
            "rule_version": "v1",
            "data_quality": "partial",
            "recommended_action": "Validar câmera, IA e rede antes de usar o período como referência gerencial.",
            "created_at": created_at,
        })
    return insights


def confirmed_cause_summary(
    connection,
    *,
    start: datetime,
    end: datetime,
    machine_id: str | None = None,
    camera_id: str | None = None,
    event_family: str | None = None,
) -> list[dict[str, Any]]:
    clauses = ["inicio <= ?", "COALESCE(fim, ?) >= ?"]
    params: list[Any] = [iso(end), iso(end), iso(start)]
    if machine_id:
        clauses.append("machine_monitor_id = ?")
        params.append(machine_id)
    if camera_id:
        clauses.append("camera_id = ?")
        params.append(camera_id)
    if event_family:
        clauses.append("event_family = ?")
        params.append(event_family)
    rows = connection.execute(
        f"""
        SELECT COALESCE(confirmed_cause, cause_category, 'sem causa confirmada') AS confirmed_cause,
               COUNT(*) AS total_events,
               SUM(COALESCE(duracao, 0)) AS total_duration_seconds
        FROM eventos
        WHERE {' AND '.join(clauses)}
        GROUP BY COALESCE(confirmed_cause, cause_category, 'sem causa confirmada')
        ORDER BY total_events DESC
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def persist_aggregation(connection, table: str, machine_id: str, camera_id: str | None, start: datetime, end: datetime, timezone_name: str, metrics: dict[str, Any], shift_name: str | None = None) -> str:
    digest = hashlib.sha1(f"{table}:{machine_id}:{shift_name or ''}:{iso(start)}:{iso(end)}".encode("utf-8")).hexdigest()[:16]
    row_id = f"met_{digest}"
    if table == "shift_machine_metrics":
        connection.execute(
            """
            INSERT INTO shift_machine_metrics (
                id, machine_id, camera_id, shift_name, period_start, period_end, timezone, metrics_json, incomplete, recalculated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(machine_id, shift_name, period_start, period_end)
            DO UPDATE SET metrics_json = excluded.metrics_json, incomplete = excluded.incomplete, recalculated_at = excluded.recalculated_at
            """,
            (row_id, machine_id, camera_id, shift_name or "turno", iso(start), iso(end), timezone_name, json.dumps(metrics, ensure_ascii=False), int(bool(metrics.get("incomplete"))), now_iso()),
        )
    else:
        connection.execute(
            f"""
            INSERT INTO {table} (
                id, machine_id, camera_id, period_start, period_end, timezone, metrics_json, incomplete, recalculated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(machine_id, period_start, period_end)
            DO UPDATE SET metrics_json = excluded.metrics_json, incomplete = excluded.incomplete, recalculated_at = excluded.recalculated_at
            """,
            (row_id, machine_id, camera_id, iso(start), iso(end), timezone_name, json.dumps(metrics, ensure_ascii=False), int(bool(metrics.get("incomplete"))), now_iso()),
        )
    connection.commit()
    return row_id


def persist_insights(connection, machine_id: str | None, camera_id: str | None, insights: list[dict[str, Any]]) -> None:
    for insight in insights:
        digest = hashlib.sha1(f"{machine_id}:{insight['rule_id']}:{insight['period_start']}:{insight['period_end']}".encode("utf-8")).hexdigest()[:16]
        connection.execute(
            """
            INSERT INTO generated_insights (
                id, machine_id, camera_id, title, description, severity, period_start, period_end,
                metrics_json, related_event_ids_json, rule_id, recommended_action
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(machine_id, period_start, period_end, rule_id)
            DO UPDATE SET title = excluded.title, description = excluded.description,
                severity = excluded.severity, metrics_json = excluded.metrics_json,
                related_event_ids_json = excluded.related_event_ids_json,
                recommended_action = excluded.recommended_action
            """,
            (
                f"ins_{digest}",
                machine_id,
                camera_id,
                insight["title"],
                insight["description"],
                insight["severity"],
                insight["period_start"],
                insight["period_end"],
                json.dumps(insight["metrics"], ensure_ascii=False),
                json.dumps(insight["related_event_ids"], ensure_ascii=False),
                insight["rule_id"],
                insight["recommended_action"],
            ),
        )
    connection.commit()


def aggregate_period(
    connection,
    *,
    machine_id: str,
    start: datetime,
    end: datetime,
    aggregation: str,
    camera_id: str | None = None,
    timezone_name: str = DEFAULT_TIMEZONE,
    event_family: str | None = None,
) -> dict[str, Any]:
    metrics = compute_summary(connection, machine_id=machine_id, start=start, end=end, camera_id=camera_id, event_family=event_family)
    table = {"hour": "hourly_machine_metrics", "day": "daily_machine_metrics", "shift": "shift_machine_metrics"}.get(aggregation)
    if table:
        persist_aggregation(connection, table, machine_id, camera_id, start, end, timezone_name, metrics, shift_name="custom" if aggregation == "shift" else None)
    insights = generate_insights(connection, machine_id=machine_id, start=start, end=end, camera_id=camera_id)
    persist_insights(connection, machine_id, camera_id, insights)
    return metrics


def current_period_range(aggregation: str, timezone_name: str = DEFAULT_TIMEZONE) -> tuple[datetime, datetime]:
    tz = ZoneInfo(timezone_name)
    now = datetime.now(tz)
    if aggregation == "day":
        start = datetime.combine(now.date(), time.min, tz)
        return start.astimezone(timezone.utc), now.astimezone(timezone.utc)
    if aggregation == "week":
        start_date = now.date() - timedelta(days=now.weekday())
        start = datetime.combine(start_date, time.min, tz)
        return start.astimezone(timezone.utc), now.astimezone(timezone.utc)
    if aggregation == "shift":
        shifts = load_shift_config()
        for shift in shifts:
            start_t = time.fromisoformat(shift["start"])
            end_t = time.fromisoformat(shift["end"])
            start_dt = datetime.combine(now.date(), start_t, tz)
            end_dt = datetime.combine(now.date(), end_t, tz)
            if end_dt <= start_dt:
                end_dt += timedelta(days=1)
                if now < start_dt:
                    start_dt -= timedelta(days=1)
                    end_dt -= timedelta(days=1)
            if start_dt <= now <= end_dt:
                return start_dt.astimezone(timezone.utc), min(now, end_dt).astimezone(timezone.utc)
    start = now.replace(minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc), now.astimezone(timezone.utc)
