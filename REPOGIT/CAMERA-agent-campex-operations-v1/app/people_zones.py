from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.alerts import enqueue_event_alert
from app.config import EVIDENCE_DIR, ROOT, storage_path
from app.database import connect, init_db
from app.models import (
    atualizar_ocorrencia_area,
    criar_ocorrencia_zona,
    fechar_ocorrencia_area,
    listar_regras,
    new_id,
    obter_evento,
    registrar_evidence_index,
)
from app.person_detection import Detection
from app.restricted_area import AreaPresence, AreaPresenceTracker, area_from_dict, draw_area_overlay, evaluate_area
from shared.schemas import now_iso


ZONE_TYPES = {
    "workstation",
    "restricted_area",
    "restricted_zone",
    "operator_zone",
    "work_area",
    "dwell_area",
    "authorized_area",
}

EVENT_CATALOG_V1 = {
    "restricted_zone_occupied",
    "workstation_unattended",
    "minimum_staff_not_met",
    "shift_start_incomplete",
    "excessive_zone_dwell",
    "after_hours_presence",
}


@dataclass
class OpenZoneEvent:
    event_id: str
    event_type: str
    area_id: str
    area_nome: str
    started_at_iso: str
    started_monotonic: float
    last_true_monotonic: float
    track_ids: set[int] = field(default_factory=set)
    current_people: int = 0
    max_people: int = 0
    confidence: float | None = None
    last_update_monotonic: float = 0.0


@dataclass
class ZoneRuleConfig:
    event_type: str
    min_seconds: float
    severity: str
    cooldown_seconds: float
    rule_id: str | None


@dataclass
class OperationalAbsenceContext:
    presence_required: bool
    data_quality_sufficient: bool
    reason: str
    facts: list[str] = field(default_factory=list)


class PeopleZonesEngine:
    def __init__(self, camera_id: str, evidence_root: Path | None = None) -> None:
        self.camera_id = camera_id
        self.evidence_root = evidence_root or EVIDENCE_DIR
        self._trackers: dict[str, AreaPresenceTracker] = {}
        self._true_since: dict[tuple[str, str], float] = {}
        self._cooldown_until: dict[tuple[str, str], float] = {}
        self._open: dict[tuple[str, str], OpenZoneEvent] = {}

    def update(
        self,
        areas: list[dict[str, Any]],
        detections: list[Detection],
        frame: np.ndarray,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        output = frame
        height, width = frame.shape[:2]
        states: list[dict[str, Any]] = []
        rules = self._rules_by_area()
        for area_payload in areas:
            if not area_payload.get("ativa", True):
                continue
            area = area_from_dict(area_payload)
            tracker = self._trackers.setdefault(area.id, AreaPresenceTracker())
            presence, inside_ids = evaluate_area(area, detections, width, height, tracker)
            zone_type = str(area_payload.get("tipo") or "restricted_area")
            output = draw_area_overlay(output, area, presence, inside_ids, detections)
            state = self._evaluate_zone(area_payload, presence, detections, output, rules.get(area.id, []))
            states.append({**presence.to_dict(), "tipo": zone_type, **state})
        self._close_missing_areas({str(area.get("id")) for area in areas if area.get("ativa", True)})
        return output, {"zones": states, "active_events": [event.__dict__ for event in self._open.values()]}

    def _rules_by_area(self) -> dict[str, list[dict[str, Any]]]:
        try:
            with connect() as connection:
                init_db(connection)
                rules = listar_regras(connection, camera_id=self.camera_id)
        except Exception:
            return {}
        by_area: dict[str, list[dict[str, Any]]] = {}
        for rule in rules:
            if not rule.get("ativo", True):
                continue
            area_id = rule.get("regiao_id")
            if area_id:
                by_area.setdefault(str(area_id), []).append(rule)
        return by_area

    def _camera_context(self) -> tuple[str, str]:
        with connect() as connection:
            init_db(connection)
            row = connection.execute(
                """
                SELECT c.unidade_id, COALESCE(c.cliente_id, u.cliente_id) AS cliente_id
                FROM cameras c
                JOIN unidades u ON u.id = c.unidade_id
                WHERE c.id = ?
                """,
                (self.camera_id,),
            ).fetchone()
        if row is None:
            return "", ""
        return str(row["cliente_id"] or ""), str(row["unidade_id"] or "")

    def _rule_config(self, area: dict[str, Any], event_type: str, rules: list[dict[str, Any]]) -> ZoneRuleConfig:
        matching = next((rule for rule in rules if rule.get("tipo_evento") == event_type), None)
        metadata = area.get("metadata") or {}
        if matching:
            return ZoneRuleConfig(
                event_type=event_type,
                min_seconds=float(matching.get("tempo_minimo") or 0),
                severity=str(matching.get("severidade") or "medium"),
                cooldown_seconds=float(matching.get("cooldown_seconds") or 60),
                rule_id=str(matching["id"]),
            )
        if event_type == "workstation_unattended":
            minimum = self._first_configured(
                area.get("absence_tolerance_seconds"),
                metadata.get("absence_tolerance_seconds"),
                os.getenv("CAMPEX_WORKSTATION_ABSENCE_SECONDS", "30"),
            )
            severity = "medium"
        elif event_type == "excessive_zone_dwell":
            minimum = self._first_configured(
                area.get("dwell_limit_seconds"),
                metadata.get("dwell_limit_seconds"),
                os.getenv("CAMPEX_ZONE_DWELL_SECONDS", "300"),
            )
            severity = "medium"
        else:
            minimum = self._first_configured(metadata.get("minimum_seconds"), os.getenv("CAMPEX_ZONE_EVENT_SECONDS", "5"))
            severity = "high" if event_type in {"restricted_zone_occupied", "after_hours_presence"} else "medium"
        return ZoneRuleConfig(event_type, float(minimum), severity, float(os.getenv("CAMPEX_ZONE_COOLDOWN_SECONDS", "60")), None)

    def _first_configured(self, *values: Any) -> Any:
        for value in values:
            if value is not None and value != "":
                return value
        return 0

    def _evaluate_zone(
        self,
        area: dict[str, Any],
        presence: AreaPresence,
        detections: list[Detection],
        frame: np.ndarray,
        rules: list[dict[str, Any]],
    ) -> dict[str, Any]:
        zone_type = str(area.get("tipo") or "restricted_area")
        candidates: list[tuple[str, bool]] = []
        occupied = presence.pessoas_dentro > 0
        if zone_type in {"restricted_area", "restricted_zone"}:
            candidates.append(("restricted_zone_occupied", occupied))
        if zone_type in {"workstation", "operator_zone", "work_area"}:
            # Operator zones provide presence context only in V1.
            # Absence alone must never become a client-facing event.
            pass
        if zone_type == "dwell_area":
            candidates.append(("excessive_zone_dwell", occupied))
        if zone_type == "authorized_area":
            candidates.append(("after_hours_presence", occupied and not self._inside_authorized_window(area)))

        result: dict[str, Any] = {"event_active": False, "event_type": None, "event_id": None}
        for event_type, condition in candidates:
            config = self._rule_config(area, event_type, rules)
            event_state = self._apply_condition(area, presence, detections, frame, config, condition)
            if event_state.get("event_active"):
                result = event_state
        return result

    def _workstation_unattended_condition(self, area: dict[str, Any], presence: AreaPresence, occupied: bool) -> bool:
        if occupied:
            return False
        context = self._absence_context(area, presence)
        area["_absence_context"] = {
            "presence_required": context.presence_required,
            "data_quality_sufficient": context.data_quality_sufficient,
            "reason": context.reason,
            "facts": context.facts,
        }
        return context.presence_required and context.data_quality_sufficient

    def _absence_context(self, area: dict[str, Any], presence: AreaPresence) -> OperationalAbsenceContext:
        sample = self._latest_operational_sample(area)
        if sample is None:
            return OperationalAbsenceContext(False, False, "sem amostra operacional recente para exigir presença")
        if int(sample.get("camera_online") or 0) != 1:
            return OperationalAbsenceContext(False, False, "câmera offline não prova ausência operacional", ["camera_online=false"])
        metadata = sample.get("metadata") or {}
        observations = metadata.get("canonical_observations")
        if not isinstance(observations, list):
            observations = []
        states = self._observation_states(observations)
        machine = states.get("machine_activity") or self._sample_machine_state(sample)
        person = states.get("person_presence")
        lighting = states.get("lighting_state")
        activity = states.get("operational_activity")
        zone = states.get("zone_occupancy") or ("EMPTY" if presence.pessoas_dentro <= 0 else "OCCUPIED")
        context_matches = self._context_matches(area, sample)
        facts = [
            fact
            for fact in (
                f"machine_activity={machine}" if machine else None,
                f"person_presence={person}" if person else None,
                f"lighting_state={lighting}" if lighting else None,
                f"operational_activity={activity}" if activity else None,
                f"zone_occupancy={zone}" if zone else None,
                "context_match=true" if context_matches else "context_match=false",
            )
            if fact
        ]
        if not context_matches:
            return OperationalAbsenceContext(False, False, "amostra operacional não pertence ao ativo/área monitorada", facts)
        invalid_quality = any(
            str(observation.get("data_quality") or "").lower() in {"sensor_unavailable", "insufficient_data"}
            and str(observation.get("value") or "").upper() == "UNKNOWN"
            for observation in observations
            if isinstance(observation, dict) and observation.get("observation_type") == "machine_activity"
        )
        if invalid_quality:
            return OperationalAbsenceContext(False, False, "dados operacionais insuficientes; UNKNOWN não vira ausência", facts)
        if activity == "NO_ACTIVITY":
            return OperationalAbsenceContext(False, True, "operação sem atividade observada; não exigir operador", facts)
        if machine == "STOPPED" and lighting == "OFF" and person in {None, "ABSENT", "UNKNOWN"}:
            return OperationalAbsenceContext(False, True, "máquina parada e luz apagada indicam operação inativa", facts)
        if machine == "ACTIVE" or activity == "NORMAL_ACTIVITY":
            return OperationalAbsenceContext(True, True, "contexto operacional ativo exige presença", facts)
        if machine in {"UNKNOWN", None}:
            return OperationalAbsenceContext(False, False, "estado da máquina desconhecido; ausência não pode ser inferida", facts)
        return OperationalAbsenceContext(False, True, "contexto operacional não exige presença neste momento", facts)

    def _latest_operational_sample(self, area: dict[str, Any]) -> dict[str, Any] | None:
        max_age = float(os.getenv("CAMPEX_OPERATIONAL_ABSENCE_CONTEXT_MAX_AGE_SECONDS", "30"))
        try:
            with connect() as connection:
                init_db(connection)
                row = connection.execute(
                    """
                    SELECT *
                    FROM operational_samples
                    WHERE camera_id = ?
                    ORDER BY sample_at DESC, id DESC
                    LIMIT 1
                    """,
                    (self.camera_id,),
                ).fetchone()
        except Exception:
            return None
        if row is None:
            return None
        sample = dict(row)
        raw = sample.get("metadata_json")
        try:
            sample["metadata"] = json.loads(raw or "{}")
        except json.JSONDecodeError:
            sample["metadata"] = {}
        sample_at = self._parse_sample_time(sample.get("sample_at"))
        if sample_at is not None:
            age = max(0.0, (datetime.now(timezone.utc) - sample_at).total_seconds())
            if age > max_age:
                return None
        return sample

    def _parse_sample_time(self, value: Any) -> datetime | None:
        if not value:
            return None
        try:
            text = str(value).replace("Z", "+00:00")
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            return None

    def _observation_states(self, observations: list[Any]) -> dict[str, str]:
        states: dict[str, str] = {}
        for observation in observations:
            if not isinstance(observation, dict):
                continue
            kind = str(observation.get("observation_type") or "")
            if kind not in {"machine_activity", "person_presence", "lighting_state", "operational_activity", "zone_occupancy"}:
                continue
            value = str(observation.get("value") or "UNKNOWN").upper()
            states[kind] = value
        return states

    def _sample_machine_state(self, sample: dict[str, Any]) -> str | None:
        value = sample.get("machine_state")
        if value is None:
            return None
        normalized = str(value or "UNKNOWN").upper()
        return normalized if normalized in {"ACTIVE", "STOPPED", "UNKNOWN"} else None

    def _context_matches(self, area: dict[str, Any], sample: dict[str, Any]) -> bool:
        comparable = (
            ("machine_id", "machine_id"),
            ("asset_id", "asset_id"),
            ("process_id", "process_id"),
            ("area_context_id", "area_context_id"),
        )
        expected = [(area_key, sample_key) for area_key, sample_key in comparable if area.get(area_key)]
        if not expected:
            return True
        return any(str(area.get(area_key)) == str(sample.get(sample_key)) for area_key, sample_key in expected if sample.get(sample_key))

    def _apply_condition(
        self,
        area: dict[str, Any],
        presence: AreaPresence,
        detections: list[Detection],
        frame: np.ndarray,
        config: ZoneRuleConfig,
        condition: bool,
    ) -> dict[str, Any]:
        key = (str(area["id"]), config.event_type)
        now = time.monotonic()
        active = self._open.get(key)
        if condition:
            self._true_since[key] = self._true_since.get(key) or now
            if active:
                active.last_true_monotonic = now
                self._update_open(active, presence, detections, now)
            elif now >= self._cooldown_until.get(key, 0.0) and now - self._true_since[key] >= config.min_seconds:
                self._open_event(area, presence, detections, frame, config, now)
        else:
            self._true_since.pop(key, None)
            if active and now - active.last_true_monotonic >= float(os.getenv("CAMPEX_ZONE_EXIT_GRACE_SECONDS", "2")):
                self._close_event(key, now)
        active = self._open.get(key)
        return {
            "event_active": bool(active),
            "event_type": active.event_type if active else config.event_type,
            "event_id": active.event_id if active else None,
            "condition_seconds": round(max(0.0, now - self._true_since.get(key, now)), 2) if condition else 0,
        }

    def _open_event(
        self,
        area: dict[str, Any],
        presence: AreaPresence,
        detections: list[Detection],
        frame: np.ndarray,
        config: ZoneRuleConfig,
        now: float,
    ) -> None:
        ids = presence.ids_dentro or []
        confidence = self._confidence(detections, ids)
        evidence_path, evidence_error = self._save_evidence(frame, area, presence, config.event_type)
        cliente_id, unidade_id = self._camera_context()
        started = now_iso()
        metadata = {
            "zone_name": area.get("nome"),
            "zone_type": area.get("tipo"),
            "people_count": presence.pessoas_dentro,
            "collaborator_name": area.get("collaborator_name"),
            "operational_absence_context": area.get("_absence_context"),
            "observation_provenance": {
                "domain": "vision_v1",
                "runtime": "PeopleZonesEngine",
                "event_type": config.event_type,
                "source_observations": ["zone_occupancy", "person_presence"],
                "condition_started_monotonic": round(float(self._true_since.get((str(area["id"]), config.event_type), now)), 6),
                "event_opened_monotonic": round(float(now), 6),
                "zone_id": str(area["id"]),
                "zone_type": area.get("tipo"),
                "people_count": presence.pessoas_dentro,
                "track_ids": ids,
                "confidence": confidence,
            },
        }
        try:
            with connect() as connection:
                init_db(connection)
                event_id = criar_ocorrencia_zona(
                    connection,
                    cliente_id=cliente_id,
                    unidade_id=unidade_id,
                    camera_id=self.camera_id,
                    area_id=str(area["id"]),
                    regra_id=config.rule_id,
                    tipo=config.event_type,
                    inicio=started,
                    quantidade_inicial=presence.pessoas_dentro,
                    quantidade_maxima=presence.pessoas_dentro,
                    track_ids=ids,
                    confianca=confidence,
                    midia_path=evidence_path,
                    severidade=config.severity,
                    metadata=metadata,
                    evidence_error=evidence_error,
                )
                if evidence_path:
                    event = obter_evento(connection, event_id)
                    registrar_evidence_index(
                        connection,
                        evidence_id=new_id("evd"),
                        event_id=event_id,
                        event_uuid=event.get("event_uuid") if event else None,
                        tenant_id=cliente_id,
                        unit_id=unidade_id,
                        camera_id=self.camera_id,
                        machine_id=area.get("machine_id"),
                        path=evidence_path,
                        media_type="image",
                        size_bytes=(ROOT / evidence_path).stat().st_size if (ROOT / evidence_path).exists() else None,
                        metadata={"source": "people_zones", "area_id": str(area["id"]), "event_type": config.event_type},
                    )
        except Exception:
            return
        self._open[(str(area["id"]), config.event_type)] = OpenZoneEvent(
            event_id=event_id,
            event_type=config.event_type,
            area_id=str(area["id"]),
            area_nome=str(area.get("nome") or ""),
            started_at_iso=started,
            started_monotonic=now,
            last_true_monotonic=now,
            track_ids=set(ids),
            current_people=presence.pessoas_dentro,
            max_people=presence.pessoas_dentro,
            confidence=confidence,
            last_update_monotonic=now,
        )
        try:
            enqueue_event_alert(event_id)
        except Exception:
            pass

    def _update_open(self, active: OpenZoneEvent, presence: AreaPresence, detections: list[Detection], now: float) -> None:
        ids = presence.ids_dentro or []
        active.track_ids.update(ids)
        active.current_people = presence.pessoas_dentro
        active.max_people = max(active.max_people, presence.pessoas_dentro)
        confidence = self._confidence(detections, ids)
        if confidence is not None:
            active.confidence = max(active.confidence or 0, confidence)
        if now - active.last_update_monotonic < 1.0:
            return
        try:
            with connect() as connection:
                init_db(connection)
                atualizar_ocorrencia_area(
                    connection,
                    active.event_id,
                    quantidade_atual=presence.pessoas_dentro,
                    quantidade_maxima=active.max_people,
                    track_ids=sorted(active.track_ids),
                    confianca=active.confidence,
                    ultimo_ocupado_em=now_iso(),
                )
            active.last_update_monotonic = now
        except Exception:
            pass

    def _close_event(self, key: tuple[str, str], now: float) -> None:
        active = self._open.pop(key, None)
        if not active:
            return
        duration = max(0.0, now - active.started_monotonic)
        try:
            with connect() as connection:
                init_db(connection)
                fechar_ocorrencia_area(connection, active.event_id, fim=now_iso(), duracao=duration)
        except Exception:
            pass
        self._cooldown_until[key] = now + self._rule_config({"id": key[0], "metadata": {}}, key[1], []).cooldown_seconds

    def _close_missing_areas(self, active_area_ids: set[str]) -> None:
        now = time.monotonic()
        for key in list(self._open):
            if key[0] not in active_area_ids:
                self._close_event(key, now)

    def close_interrupted(self) -> None:
        now = time.monotonic()
        for key in list(self._open):
            self._close_event(key, now)

    def _save_evidence(self, frame: np.ndarray, area: dict[str, Any], presence: AreaPresence, event_type: str) -> tuple[str | None, str | None]:
        try:
            now = datetime.now(timezone.utc).astimezone()
            folder = self.evidence_root / self.camera_id / f"{now:%Y}" / f"{now:%m}" / f"{now:%d}"
            folder.mkdir(parents=True, exist_ok=True)
            filename = f"{now:%H%M%S}_{event_type}_{area['id']}_{int(time.time() * 1000)}.jpg"
            path = folder / filename
            annotated = frame.copy()
            cv2.putText(annotated, f"Campex - {event_type}", (16, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 4, cv2.LINE_AA)
            cv2.putText(annotated, f"Campex - {event_type}", (16, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2, cv2.LINE_AA)
            cv2.putText(annotated, f"{area.get('nome')} | {presence.pessoas_dentro} pessoa(s)", (16, 56), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2, cv2.LINE_AA)
            if not cv2.imwrite(str(path), annotated):
                return None, "Falha ao gravar imagem de evidencia."
            try:
                return storage_path(path), None
            except ValueError:
                return str(path), None
        except Exception as exc:
            return None, str(exc)

    def _confidence(self, detections: list[Detection], ids: list[int]) -> float | None:
        values = [d.confidence for d in detections if d.track_id in ids]
        return max(values) if values else None

    def _inside_authorized_window(self, area: dict[str, Any]) -> bool:
        metadata = area.get("metadata") or {}
        start = area.get("expected_start") or metadata.get("authorized_start")
        end = area.get("expected_end") or metadata.get("authorized_end")
        if not start or not end:
            return True
        now_text = datetime.now().strftime("%H:%M")
        return str(start) <= now_text <= str(end) if str(start) <= str(end) else now_text >= str(start) or now_text <= str(end)
