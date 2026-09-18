from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from app.config import EVIDENCE_DIR, storage_path
from app.alerts import enqueue_event_alert
from app.database import connect, init_db
from app.models import (
    atualizar_ocorrencia_area,
    criar_ocorrencia_area_restrita,
    fechar_ocorrencia_area,
    obter_camera,
)
from app.person_detection import Detection
from app.restricted_area import AreaPresence, RestrictedArea
from shared.schemas import now_iso


def env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass
class ActiveIncident:
    event_id: str
    started_at_iso: str
    started_monotonic: float
    last_occupied_monotonic: float
    track_ids: set[int] = field(default_factory=set)
    max_people: int = 0
    current_people: int = 0
    confidence: float | None = None
    last_update_monotonic: float = 0.0


class IncidentManager:
    def __init__(
        self,
        camera_id: str,
        entry_delay_seconds: float | None = None,
        exit_grace_seconds: float | None = None,
        cooldown_seconds: float | None = None,
        severity: str | None = None,
        evidence_root: Path | None = None,
    ) -> None:
        self.camera_id = camera_id
        self.entry_delay_seconds = entry_delay_seconds if entry_delay_seconds is not None else env_float("CAMPEX_EVENT_ENTRY_DELAY_SECONDS", 1.0)
        self.exit_grace_seconds = exit_grace_seconds if exit_grace_seconds is not None else env_float("CAMPEX_EVENT_EXIT_GRACE_SECONDS", 2.0)
        self.cooldown_seconds = cooldown_seconds if cooldown_seconds is not None else env_float("CAMPEX_EVENT_COOLDOWN_SECONDS", 3.0)
        self.severity = severity or os.getenv("CAMPEX_EVENT_SEVERITY", "high")
        self.evidence_root = evidence_root or EVIDENCE_DIR
        self.active: ActiveIncident | None = None
        self._occupied_since: float | None = None
        self._cooldown_until = 0.0

    def update(
        self,
        area: RestrictedArea | None,
        presence: AreaPresence,
        detections: list[Detection],
        frame: np.ndarray,
    ) -> dict[str, object]:
        now = time.monotonic()
        if area is None or presence.area_id is None:
            self._close_if_needed(now, interrupted=True)
            self._occupied_since = None
            return self.public_state()

        occupied = presence.pessoas_dentro > 0
        if occupied:
            self._occupied_since = self._occupied_since or now
            if self.active is None and now >= self._cooldown_until and now - self._occupied_since >= self.entry_delay_seconds:
                self._open(area, presence, detections, frame, now)
            elif self.active is not None:
                self._update_open(presence, detections, now)
        else:
            self._occupied_since = None
            if self.active is not None and now - self.active.last_occupied_monotonic >= self.exit_grace_seconds:
                self._close_if_needed(now)
        return self.public_state()

    def _camera_context(self) -> tuple[str, str, str | None]:
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
            rule = connection.execute(
                """
                SELECT id
                FROM regras
                WHERE camera_id = ? AND ativo = 1 AND tipo_evento = 'restricted_area_occupied'
                ORDER BY criado_em DESC
                LIMIT 1
                """,
                (self.camera_id,),
            ).fetchone()
        if row is None:
            return "", "", None
        return str(row["cliente_id"] or ""), str(row["unidade_id"] or ""), str(rule["id"]) if rule else None

    def _confidence(self, detections: list[Detection], ids: list[int]) -> float | None:
        values = [d.confidence for d in detections if d.track_id in ids]
        return max(values) if values else None

    def _open(
        self,
        area: RestrictedArea,
        presence: AreaPresence,
        detections: list[Detection],
        frame: np.ndarray,
        now: float,
    ) -> None:
        ids = presence.ids_dentro or []
        started_iso = now_iso()
        confidence = self._confidence(detections, ids)
        evidence_path, evidence_error = self._save_evidence(frame, area, presence)
        cliente_id, unidade_id, regra_id = self._camera_context()
        try:
            with connect() as connection:
                init_db(connection)
                event_id = criar_ocorrencia_area_restrita(
                    connection,
                    cliente_id=cliente_id,
                    unidade_id=unidade_id,
                    camera_id=self.camera_id,
                    area_id=area.id,
                    regra_id=regra_id,
                    inicio=started_iso,
                    quantidade_inicial=presence.pessoas_dentro,
                    quantidade_maxima=presence.pessoas_dentro,
                    track_ids=ids,
                    confianca=confidence,
                    midia_path=evidence_path,
                    severidade=self.severity,
                    evidence_error=evidence_error,
                )
        except Exception:
            return
        self.active = ActiveIncident(
            event_id=event_id,
            started_at_iso=started_iso,
            started_monotonic=now,
            last_occupied_monotonic=now,
            track_ids=set(ids),
            max_people=presence.pessoas_dentro,
            current_people=presence.pessoas_dentro,
            confidence=confidence,
            last_update_monotonic=now,
        )
        enqueue_event_alert(event_id)

    def _update_open(self, presence: AreaPresence, detections: list[Detection], now: float) -> None:
        if self.active is None:
            return
        ids = presence.ids_dentro or []
        changed = presence.pessoas_dentro != self.active.current_people or bool(set(ids) - self.active.track_ids)
        self.active.track_ids.update(ids)
        self.active.current_people = presence.pessoas_dentro
        self.active.max_people = max(self.active.max_people, presence.pessoas_dentro)
        self.active.last_occupied_monotonic = now
        confidence = self._confidence(detections, ids)
        if confidence is not None:
            self.active.confidence = max(self.active.confidence or 0, confidence)
        if not changed and now - self.active.last_update_monotonic < 1.0:
            return
        try:
            with connect() as connection:
                init_db(connection)
                atualizar_ocorrencia_area(
                    connection,
                    self.active.event_id,
                    quantidade_atual=presence.pessoas_dentro,
                    quantidade_maxima=self.active.max_people,
                    track_ids=sorted(self.active.track_ids),
                    confianca=self.active.confidence,
                    ultimo_ocupado_em=now_iso(),
                )
            self.active.last_update_monotonic = now
        except Exception:
            pass

    def _close_if_needed(self, now: float, interrupted: bool = False) -> None:
        if self.active is None:
            return
        duration = max(0.0, now - self.active.started_monotonic)
        try:
            with connect() as connection:
                init_db(connection)
                fechar_ocorrencia_area(
                    connection,
                    self.active.event_id,
                    fim=now_iso(),
                    duracao=duration,
                    observacao="Encerrada por interrupcao da camera." if interrupted else None,
                )
        except Exception:
            pass
        self._cooldown_until = now + self.cooldown_seconds
        self.active = None

    def close_interrupted(self) -> None:
        self._close_if_needed(time.monotonic(), interrupted=True)

    def _save_evidence(self, frame: np.ndarray, area: RestrictedArea, presence: AreaPresence) -> tuple[str | None, str | None]:
        try:
            now = datetime.now(timezone.utc).astimezone()
            folder = self.evidence_root / self.camera_id / f"{now:%Y}" / f"{now:%m}" / f"{now:%d}"
            folder.mkdir(parents=True, exist_ok=True)
            filename = f"{now:%H%M%S}_{area.id}_{int(time.time() * 1000)}.jpg"
            path = folder / filename
            annotated = frame.copy()
            cv2.putText(annotated, f"Campex - Ocorrencia detectada", (16, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 4, cv2.LINE_AA)
            cv2.putText(annotated, f"Campex - Ocorrencia detectada", (16, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 0, 0), 2, cv2.LINE_AA)
            cv2.putText(annotated, f"{area.nome} | {presence.pessoas_dentro} pessoa(s) | {now:%Y-%m-%d %H:%M:%S}", (16, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2, cv2.LINE_AA)
            if not cv2.imwrite(str(path), annotated):
                return None, "Falha ao gravar imagem de evidencia."
            return storage_path(path), None
        except Exception as exc:
            return None, str(exc)

    def public_state(self) -> dict[str, object]:
        if self.active is None:
            return {
                "incident_active": False,
                "incident_id": None,
                "incident_started_at": None,
                "incident_duration": None,
                "incident_people": 0,
            }
        return {
            "incident_active": True,
            "incident_id": self.active.event_id,
            "incident_started_at": self.active.started_at_iso,
            "incident_duration": round(max(0.0, time.monotonic() - self.active.started_monotonic), 2),
            "incident_people": self.active.current_people,
        }
