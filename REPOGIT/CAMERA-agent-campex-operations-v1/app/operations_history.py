from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.config import ROOT
from app.database import connect, init_db
from app.operational_events import close_event as close_canonical_event
from app.operational_events import list_events as list_canonical_events
from app.operational_events import open_event as open_canonical_event
from app.operational_events import resolve_event_context
from app.models import registrar_operational_sample
from edge_agent.sync_outbox import new_event_uuid
from shared.schemas import now_iso

LOGGER = logging.getLogger(__name__)

SNAPSHOT_EVENT_STATES = {
    ("machine_state", "PARADA"),
    ("machine_state", "ATIVA"),
    ("operator_presence", "PRESENTE"),
}


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    if len(normalized) >= 6 and normalized[-6] == " " and normalized[-3] == ":":
        normalized = f"{normalized[:-6]}+{normalized[-5:]}"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso_at(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def row_to_event(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    return data


def init_operations_db(connection: sqlite3.Connection) -> None:
    init_db(connection)


def insert_operational_event(
    connection: sqlite3.Connection,
    session_id: str,
    camera_id: str | None,
    machine_name: str | None,
    event_type: str,
    previous_state: str | None,
    new_state: str,
    started_at: str,
    confidence: float | None = None,
    activity_score: float | None = None,
    people_count: int = 0,
    snapshot_path: str | None = None,
) -> str:
    return open_canonical_event(
        connection,
        session_id=session_id,
        camera_id=camera_id,
        machine_name=machine_name,
        event_type=event_type,
        previous_state=previous_state,
        new_state=new_state,
        started_at=started_at,
        confidence=confidence,
        activity_score=activity_score,
        people_count=people_count,
        snapshot_path=snapshot_path,
    )


def close_open_operational_event(
    connection: sqlite3.Connection,
    session_id: str,
    event_type: str,
    ended_at: str,
) -> dict[str, Any] | None:
    return close_canonical_event(connection, session_id=session_id, event_type=event_type, ended_at=ended_at)


def list_operational_events(
    connection: sqlite3.Connection,
    start: str | None = None,
    end: str | None = None,
    camera_id: str | None = None,
    machine_name: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    return list_canonical_events(
        connection,
        start=start,
        end=end,
        camera_id=camera_id,
        machine_name=machine_name,
        limit=limit,
        offset=offset,
    )


@dataclass
class OperationalSnapshot:
    session_id: str
    camera_id: str
    machine_name: str | None
    machine_state: str
    operator_state: str
    camera_status: str
    calibration_status: str
    confidence: float | None
    activity_score: float | None
    people_count: int


class OperationsRecorder:
    def __init__(self, session_id: str, camera_id: str | None = None, evidence_root: Path | None = None) -> None:
        self.session_id = session_id
        self.camera_id = self._persistent_camera_id(camera_id)
        self.evidence_root = evidence_root or (ROOT / "data" / "operations_snapshots")
        self._states: dict[str, str] = {}

    @staticmethod
    def _persistent_camera_id(camera_id: str | None) -> str | None:
        if not camera_id or camera_id.startswith("live_"):
            return None
        return camera_id

    def update_status(
        self,
        camera_status: str,
        ops_state: dict[str, Any] | None,
        frame: np.ndarray | None = None,
    ) -> None:
        machine = (ops_state or {}).get("machine") if ops_state else None
        operator_present = (ops_state or {}).get("operator_present")
        operator_state = (
            "PRESENTE"
            if operator_present is True
            else "AUSENTE"
            if operator_present is False
            else "DESCONHECIDO"
        )
        snapshot = OperationalSnapshot(
            session_id=self.session_id,
            camera_id=self.camera_id or self.session_id,
            machine_name=machine.get("nome") if machine else None,
            machine_state=str((ops_state or {}).get("machine_state") or "NAO_CONFIGURADA"),
            operator_state=operator_state,
            camera_status="online" if camera_status == "online" else "offline",
            calibration_status=str((ops_state or {}).get("calibration_status") or "não calibrada"),
            confidence=(ops_state or {}).get("visual_confidence"),
            activity_score=(ops_state or {}).get("machine_motion"),
            people_count=int((ops_state or {}).get("people_count") or 0),
        )
        self._record_sample(snapshot, camera_status, ops_state)
        if machine:
            self._transition("machine_state", snapshot.machine_state, snapshot, frame)
            self._transition("operator_presence", snapshot.operator_state, snapshot, frame)
            self._transition("calibration", snapshot.calibration_status, snapshot, frame)
            relation_state = "ATIVA_SEM_OPERADOR" if snapshot.machine_state == "ATIVA" and snapshot.operator_state == "AUSENTE" else "NORMAL"
            self._transition("active_without_operator", relation_state, snapshot, frame)

    def _record_sample(self, snapshot: OperationalSnapshot, camera_status: str, ops_state: dict[str, Any] | None) -> None:
        if not ops_state:
            return
        try:
            with connect() as connection:
                init_operations_db(connection)
                client_id, unit_id, canonical_camera_id, _source_camera_id = resolve_event_context(connection, self.camera_id, self.session_id)
                machine = ops_state.get("machine") if ops_state else None
                sample_machine_state = {
                    "ATIVA": "ACTIVE",
                    "PARADA": "STOPPED",
                    "ACTIVE": "ACTIVE",
                    "STOPPED": "STOPPED",
                    "UNKNOWN": "UNKNOWN",
                }.get(snapshot.machine_state)
                sample_operator_present = (
                    True
                    if snapshot.operator_state == "PRESENTE"
                    else False
                    if snapshot.operator_state == "AUSENTE"
                    else None
                )
                registrar_operational_sample(
                    connection,
                    sample_uuid=new_event_uuid(),
                    tenant_id=client_id,
                    unit_id=unit_id,
                    camera_id=canonical_camera_id,
                    machine_id=str(machine.get("id")) if isinstance(machine, dict) and machine.get("id") else None,
                    machine_state=sample_machine_state,
                    operator_present=sample_operator_present,
                    activity_score=snapshot.activity_score,
                    confidence=snapshot.confidence,
                    capture_fps=(ops_state or {}).get("capture_fps"),
                    inference_fps=(ops_state or {}).get("inference_fps"),
                    frames_analyzed=int((ops_state or {}).get("frames_analyzed") or 0),
                    camera_online=camera_status == "online",
                    sample_at=now_iso(),
                    metadata={"people_count": snapshot.people_count, "session_id": self.session_id},
                )
        except Exception:
            LOGGER.exception("Falha ao registrar amostra operacional.")

    def _transition(
        self,
        event_type: str,
        new_state: str,
        snapshot: OperationalSnapshot,
        frame: np.ndarray | None,
    ) -> None:
        previous = self._states.get(event_type)
        if previous is None:
            previous = self._latest_state(event_type)
            if previous is not None:
                self._states[event_type] = previous
        if previous == new_state:
            return
        now = now_iso()
        snapshot_path = self._save_snapshot(event_type, new_state, frame) if self._should_snapshot(event_type, new_state, previous) else None
        try:
            with connect() as connection:
                init_operations_db(connection)
                if self._is_redundant_open_event(connection, event_type, new_state):
                    self._states[event_type] = new_state
                    return
                close_open_operational_event(connection, self.session_id, event_type, now)
                insert_operational_event(
                    connection,
                    self.session_id,
                    self.camera_id,
                    snapshot.machine_name,
                    event_type,
                    previous,
                    new_state,
                    now,
                    confidence=snapshot.confidence,
                    activity_score=snapshot.activity_score,
                    people_count=snapshot.people_count,
                    snapshot_path=snapshot_path,
                )
            self._states[event_type] = new_state
        except Exception:
            LOGGER.exception("Falha ao persistir evento operacional.")

    def _is_redundant_open_event(self, connection: sqlite3.Connection, event_type: str, new_state: str) -> bool:
        row = connection.execute(
            """
            SELECT json_extract(metadata_json, '$.new_state') AS new_state
            FROM eventos
            WHERE status = 'open'
              AND tipo = ?
              AND json_extract(metadata_json, '$.session_id') = ?
            ORDER BY inicio DESC, criado_em DESC, rowid DESC
            LIMIT 1
            """,
            (event_type, self.session_id),
        ).fetchone()
        return bool(row and row["new_state"] == new_state)

    def _latest_state(self, event_type: str) -> str | None:
        try:
            with connect() as connection:
                init_operations_db(connection)
                row = connection.execute(
                    """
                    SELECT json_extract(metadata_json, '$.new_state') AS new_state
                    FROM eventos
                    WHERE tipo = ?
                      AND json_extract(metadata_json, '$.session_id') = ?
                    ORDER BY inicio DESC, criado_em DESC, rowid DESC
                    LIMIT 1
                    """,
                    (event_type, self.session_id),
                ).fetchone()
                return str(row["new_state"]) if row else None
        except Exception:
            LOGGER.exception("Falha ao recuperar ultimo estado operacional.")
            return None

    def _should_snapshot(self, event_type: str, new_state: str, previous: str | None) -> bool:
        if (event_type, new_state) in SNAPSHOT_EVENT_STATES:
            return True
        return event_type == "active_without_operator" and new_state == "ATIVA_SEM_OPERADOR"

    def _save_snapshot(self, event_type: str, new_state: str, frame: np.ndarray | None) -> str | None:
        if frame is None:
            return None
        try:
            now = datetime.now(timezone.utc).astimezone()
            folder = self.evidence_root / (self.camera_id or self.session_id) / f"{now:%Y}" / f"{now:%m}" / f"{now:%d}"
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{now:%H%M%S}_{event_type}_{new_state}_{uuid.uuid4().hex[:6]}.jpg"
            if not cv2.imwrite(str(path), frame):
                return None
            try:
                return str(path.relative_to(ROOT))
            except ValueError:
                return str(path)
        except Exception:
            LOGGER.exception("Falha ao salvar snapshot operacional.")
            return None


def _overlap_seconds(event: dict[str, Any], start: datetime, end: datetime, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    event_start = parse_iso(event.get("started_at"))
    event_end = parse_iso(event.get("ended_at")) or now
    if event_start is None:
        return 0.0
    left = max(event_start, start)
    right = min(event_end, end)
    return max(0.0, (right - left).total_seconds())


def operations_summary(
    connection: sqlite3.Connection,
    start: str | None,
    end: str | None,
    camera_id: str | None = None,
    machine_name: str | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    end_dt = parse_iso(end) or now
    start_dt = parse_iso(start) or (end_dt - timedelta(days=1))
    events = list_operational_events(connection, iso_at(start_dt), iso_at(end_dt), camera_id, machine_name, limit=200, offset=0)
    events = events + _older_open_events(connection, start_dt, camera_id, machine_name)

    total_monitored = max(0.0, (end_dt - start_dt).total_seconds())
    active = sum(_overlap_seconds(e, start_dt, end_dt, now) for e in events if e["event_type"] == "machine_state" and e["new_state"] == "ATIVA")
    stopped_events = [e for e in events if e["event_type"] == "machine_state" and e["new_state"] == "PARADA"]
    stopped = sum(_overlap_seconds(e, start_dt, end_dt, now) for e in stopped_events)
    active_without_operator = sum(_overlap_seconds(e, start_dt, end_dt, now) for e in events if e["event_type"] == "active_without_operator" and e["new_state"] == "ATIVA_SEM_OPERADOR")
    offline = _offline_seconds_from_samples(connection, start_dt, end_dt, camera_id)
    stop_durations = [_overlap_seconds(e, start_dt, end_dt, now) for e in stopped_events]
    operator_absences = [e for e in events if e["event_type"] == "operator_presence" and e["new_state"] == "AUSENTE"]
    current = current_status(connection, camera_id, machine_name)
    return {
        "period": {"start": iso_at(start_dt), "end": iso_at(end_dt)},
        "tempo_total_monitorado": round(total_monitored, 2),
        "tempo_maquina_ativa": round(active, 2),
        "tempo_maquina_parada": round(stopped, 2),
        "percentual_atividade_estimada": round((active / total_monitored) * 100, 2) if total_monitored else 0,
        "quantidade_paradas": len(stopped_events),
        "duracao_media_paradas": round(sum(stop_durations) / len(stop_durations), 2) if stop_durations else 0,
        "maior_parada": round(max(stop_durations, default=0), 2),
        "tempo_ativa_sem_operador": round(active_without_operator, 2),
        "quantidade_ausencias_operador": len(operator_absences),
        "disponibilidade_camera": round(((total_monitored - offline) / total_monitored) * 100, 2) if total_monitored else 0,
        "situacao_atual_maquina": current.get("machine_state", "NAO_CONFIGURADA"),
        "situacao_atual_operador": current.get("operator_state", "AUSENTE"),
    }


def _older_open_events(
    connection: sqlite3.Connection,
    start_dt: datetime,
    camera_id: str | None,
    machine_name: str | None,
) -> list[dict[str, Any]]:
    return [
        event
        for event in list_operational_events(connection, None, iso_at(start_dt), camera_id, machine_name, limit=200, offset=0)
        if event.get("ended_at") is None and parse_iso(event.get("started_at")) and parse_iso(event.get("started_at")) < start_dt
    ]


def current_status(connection: sqlite3.Connection, camera_id: str | None = None, machine_name: str | None = None) -> dict[str, Any]:
    status: dict[str, Any] = {
        "machine_state": "NAO_CONFIGURADA",
        "operator_state": "AUSENTE",
        "camera_status": "desconhecida",
        "people_count": 0,
        "machine_name": machine_name,
        "last_update": None,
    }
    mapping = {
        "machine_state": "machine_state",
        "operator_presence": "operator_state",
    }
    events = list_operational_events(connection, camera_id=camera_id, machine_name=machine_name, limit=200, offset=0)
    for event_type, key in mapping.items():
        event = next((item for item in events if item.get("event_type") == event_type), None)
        if event:
            status[key] = event["new_state"]
            status["people_count"] = max(int(status["people_count"]), int(event.get("people_count") or 0))
            status["machine_name"] = event.get("machine_name") or status["machine_name"]
            status["last_update"] = event.get("started_at")
    sample = _latest_camera_sample(connection, camera_id)
    if sample:
        status["camera_status"] = "online" if sample.get("camera_online") else "offline"
        status["last_update"] = sample.get("sample_at") or status["last_update"]
    return status


def _latest_camera_sample(connection: sqlite3.Connection, camera_id: str | None) -> dict[str, Any] | None:
    clauses = []
    params: list[Any] = []
    if camera_id:
        clauses.append("camera_id = ?")
        params.append(camera_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    row = connection.execute(
        f"""
        SELECT sample_at, camera_online, inference_fps
        FROM operational_samples
        {where}
        ORDER BY sample_at DESC
        LIMIT 1
        """,
        params,
    ).fetchone()
    return dict(row) if row else None


def _offline_seconds_from_samples(connection: sqlite3.Connection, start_dt: datetime, end_dt: datetime, camera_id: str | None) -> float:
    clauses = ["sample_at >= ?", "sample_at <= ?"]
    params: list[Any] = [iso_at(start_dt), iso_at(end_dt)]
    if camera_id:
        clauses.append("camera_id = ?")
        params.append(camera_id)
    rows = connection.execute(
        f"""
        SELECT sample_at, camera_online
        FROM operational_samples
        WHERE {' AND '.join(clauses)}
        ORDER BY sample_at ASC
        """,
        params,
    ).fetchall()
    samples = [dict(row) for row in rows]
    if len(samples) < 2:
        return 0.0
    offline = 0.0
    for previous, current in zip(samples, samples[1:]):
        previous_at = parse_iso(previous.get("sample_at"))
        current_at = parse_iso(current.get("sample_at"))
        if previous_at and current_at and not previous.get("camera_online"):
            offline += max(0.0, (current_at - previous_at).total_seconds())
    return offline


def operations_timeline(
    connection: sqlite3.Connection,
    start: str | None,
    end: str | None,
    camera_id: str | None = None,
    machine_name: str | None = None,
) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    end_dt = parse_iso(end) or now
    start_dt = parse_iso(start) or (end_dt - timedelta(days=1))
    events = list_operational_events(connection, iso_at(start_dt), iso_at(end_dt), camera_id, machine_name, limit=200, offset=0)
    items = []
    for event in sorted(events, key=lambda item: item["started_at"]):
        if event["event_type"] == "machine_state" and event["new_state"] not in {"ATIVA", "PARADA", "CALIBRANDO", "SEM SINAL"}:
            continue
        if event["event_type"] == "active_without_operator" and event["new_state"] != "ATIVA_SEM_OPERADOR":
            continue
        if event["event_type"] not in {"machine_state", "active_without_operator", "calibration"}:
            continue
        state = "CALIBRANDO" if event["event_type"] == "calibration" else event["new_state"]
        items.append({
            "event_type": event["event_type"],
            "state": state,
            "start": max(parse_iso(event["started_at"]) or start_dt, start_dt).isoformat(),
            "end": min(parse_iso(event["ended_at"]) or now, end_dt).isoformat(),
            "duration_seconds": round(_overlap_seconds(event, start_dt, end_dt, now), 2),
            "machine_name": event.get("machine_name"),
        })
    return items


def prune_operation_snapshots(days: int | None = None) -> list[Path]:
    retention_days = days if days is not None else int(os.getenv("CAMPEX_OPERATION_SNAPSHOT_RETENTION_DAYS", "30"))
    root = ROOT / "data" / "operations_snapshots"
    if not root.exists():
        return []
    cutoff = datetime.now(timezone.utc).timestamp() - (retention_days * 86400)
    removed: list[Path] = []
    for path in root.rglob("*.jpg"):
        if path.stat().st_mtime < cutoff:
            path.unlink()
            removed.append(path)
    return removed
