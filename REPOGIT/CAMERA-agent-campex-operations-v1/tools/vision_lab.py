from __future__ import annotations

import json
import os
import re
import smtplib
import ssl
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.alerts as alerts
import app.machine_monitoring as machine_monitoring
import app.people_zones as people_zones
from app.database import connect, init_db
from app.machine_monitoring import MachineMonitorEngine, config_from_dict
from app.models import (
    atualizar_alert_delivery_attempt,
    atualizar_machine_monitor,
    criar_alert_delivery,
    criar_alert_recipient,
    criar_area_monitorada,
    criar_camera,
    criar_cliente,
    criar_dispositivo,
    criar_machine_monitor,
    criar_unidade,
    listar_alert_deliveries,
    listar_alert_recipients,
    listar_areas_camera,
    listar_eventos_filtrados,
    listar_machine_monitors_camera,
    obter_machine_monitor,
    registrar_machine_calibration,
    obter_alert_delivery,
)
from app.observation_engine import ObservationEngine
from app.people_zones import PeopleZonesEngine
from app.person_detection import PersonAnalysisEngine
from app.restricted_area import AreaPoint
from edge_agent.sync_outbox import pending_sync_count
from shared.schemas import now_iso


LAB_DB_PATH = Path(os.getenv("CAMPEX_VISION_LAB_DB", str(ROOT / "data" / "vision_lab.db")))
LAB_EVIDENCE_ROOT = Path(os.getenv("CAMPEX_VISION_LAB_EVIDENCE", str(ROOT / "data" / "vision_lab_evidence")))
LAB_HOST = os.getenv("CAMPEX_VISION_LAB_HOST", "127.0.0.1")
LAB_PORT = int(os.getenv("CAMPEX_VISION_LAB_PORT", "8011"))
LAB_CLIENT_ID = "dev_vision_lab_client"
LAB_UNIT_ID = "dev_vision_lab_unit"
LAB_EDGE_ID = "dev_vision_lab_edge"
LAB_CAMERA_ID = "dev_vision_lab_webcam"
LAB_MACHINE_NAME = "DEV Ventilador de teste"
LAB_RECIPIENT_NAME = "DEV Vision Lab Recipient"
ALGORITHM_VERSION = "vision_lab_activity_v1"


def lab_connect(db_path: str | Path = LAB_DB_PATH):
    return connect(db_path)


def configure_lab_environment(db_path: str | Path = LAB_DB_PATH) -> None:
    os.environ.setdefault("CAMPEX_ENV", "development")
    os.environ.setdefault("CAMPEX_EDGE_ID", LAB_EDGE_ID)
    os.environ.setdefault("CAMPEX_EMAIL_MODE", "console")
    os.environ.setdefault("CAMPEX_MACHINE_ANALYSIS_FPS", "5")
    os.environ.setdefault("CAMPEX_MACHINE_STOP_SECONDS", "2")
    os.environ.setdefault("CAMPEX_MACHINE_RECOVERY_SECONDS", "1")
    os.environ.setdefault("CAMPEX_OPERATOR_ABSENCE_SECONDS", "2")
    os.environ.setdefault("CAMPEX_ZONE_EVENT_SECONDS", "2")
    os.environ.setdefault("CAMPEX_WORKSTATION_ABSENCE_SECONDS", "2")
    os.environ.setdefault("CAMPEX_ZONE_COOLDOWN_SECONDS", "3")
    os.environ.setdefault("CAMPEX_ZONE_EXIT_GRACE_SECONDS", "1")
    os.environ.setdefault("CAMPEX_YOLO_CLASSES", "person")
    if os.getenv("CAMPEX_SMTP_USER") and not os.getenv("CAMPEX_SMTP_USERNAME"):
        os.environ["CAMPEX_SMTP_USERNAME"] = os.getenv("CAMPEX_SMTP_USER", "")
    alerts.connect = lambda: connect(db_path)
    machine_monitoring.connect = lambda: connect(db_path)
    machine_monitoring.enqueue_event_alert = alerts.enqueue_event_alert
    machine_monitoring.save_machine_evidence = save_lab_machine_evidence
    people_zones.connect = lambda: connect(db_path)
    people_zones.enqueue_event_alert = alerts.enqueue_event_alert


def save_lab_machine_evidence(frame: np.ndarray, config, state) -> tuple[str | None, str | None]:
    try:
        now = datetime.now(timezone.utc).astimezone()
        folder = LAB_EVIDENCE_ROOT / config.camera_id / f"{now:%Y}" / f"{now:%m}" / f"{now:%d}"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{now:%H%M%S}_{config.id}_machine.jpg"
        annotated = machine_monitoring.draw_machine_overlay(frame, config, state)
        if not cv2.imwrite(str(path), annotated):
            return None, "Falha ao gravar evidencia isolada do Vision Lab."
        return str(path), None
    except Exception as exc:
        return None, str(exc)[:300]


def ensure_lab_database(db_path: str | Path = LAB_DB_PATH) -> dict[str, str]:
    configure_lab_environment(db_path)
    recipient_email = current_lab_recipient_email()
    with connect(db_path) as connection:
        init_db(connection)
        if not connection.execute("SELECT 1 FROM clientes WHERE id = ?", (LAB_CLIENT_ID,)).fetchone():
            connection.execute(
                "INSERT INTO clientes (id, nome, documento, status) VALUES (?, ?, ?, ?)",
                (LAB_CLIENT_ID, "DEV Vision Lab", "DEV", "ativo"),
            )
        if not connection.execute("SELECT 1 FROM unidades WHERE id = ?", (LAB_UNIT_ID,)).fetchone():
            connection.execute(
                "INSERT INTO unidades (id, cliente_id, nome, localizacao, timezone) VALUES (?, ?, ?, ?, ?)",
                (LAB_UNIT_ID, LAB_CLIENT_ID, "DEV Bancada local", "Mac local", "America/Sao_Paulo"),
            )
        if not connection.execute("SELECT 1 FROM dispositivos WHERE id = ?", (LAB_EDGE_ID,)).fetchone():
            connection.execute(
                "INSERT INTO dispositivos (id, unidade_id, nome, status, ultimo_contato) VALUES (?, ?, ?, ?, ?)",
                (LAB_EDGE_ID, LAB_UNIT_ID, "DEV Vision Lab Edge", "online", now_iso()),
            )
        if not connection.execute("SELECT 1 FROM cameras WHERE id = ?", (LAB_CAMERA_ID,)).fetchone():
            connection.execute(
                """
                INSERT INTO cameras (
                    id, cliente_id, unidade_id, dispositivo_id, edge_id, nome, status,
                    source_type, secure_ref, canal, ativa
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    LAB_CAMERA_ID,
                    LAB_CLIENT_ID,
                    LAB_UNIT_ID,
                    LAB_EDGE_ID,
                    LAB_EDGE_ID,
                    "DEV Webcam local",
                    "offline",
                    "webcam",
                    "webcam://0",
                    "0",
                    1,
                ),
            )
        if recipient_email:
            connection.execute(
                """
                UPDATE alert_recipients
                SET nome = ?,
                    email = ?,
                    ativo = 1,
                    atualizado_em = CURRENT_TIMESTAMP
                WHERE cliente_id = ?
                  AND (email = 'felipe.local@campex.dev' OR nome = ?)
                  AND email != ?
                """,
                (LAB_RECIPIENT_NAME, recipient_email, LAB_CLIENT_ID, LAB_RECIPIENT_NAME, recipient_email),
            )
        else:
            connection.execute(
                """
                UPDATE alert_recipients
                SET ativo = 0,
                    atualizado_em = CURRENT_TIMESTAMP
                WHERE cliente_id = ?
                  AND (email = 'felipe.local@campex.dev' OR nome = ?)
                """,
                (LAB_CLIENT_ID, LAB_RECIPIENT_NAME),
            )
        existing_recipient = connection.execute(
            "SELECT id FROM alert_recipients WHERE cliente_id = ? AND nome = ?",
            (LAB_CLIENT_ID, LAB_RECIPIENT_NAME),
        ).fetchone()
        if recipient_email and existing_recipient:
            connection.execute(
                """
                UPDATE alert_recipients
                SET email = ?,
                    event_types = ?,
                    ativo = 1,
                    severidade_minima = 'low',
                    atualizado_em = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    recipient_email,
                    json.dumps(
                        [
                            "machine_stoppage",
                            "workstation_unattended",
                            "restricted_zone_occupied",
                            "machine_running_without_operator",
                        ]
                    ),
                    existing_recipient["id"],
                ),
            )
        elif recipient_email:
            criar_alert_recipient(
                connection,
                nome=LAB_RECIPIENT_NAME,
                email=recipient_email,
                cliente_id=LAB_CLIENT_ID,
                event_types=[
                    "machine_stoppage",
                    "workstation_unattended",
                    "restricted_zone_occupied",
                    "machine_running_without_operator",
                ],
                severidade_minima="low",
            )
        connection.commit()
    return {"client_id": LAB_CLIENT_ID, "unit_id": LAB_UNIT_ID, "edge_id": LAB_EDGE_ID, "camera_id": LAB_CAMERA_ID}


def current_lab_recipient_email() -> str | None:
    value = os.getenv("CAMPEX_VISION_LAB_RECIPIENT") or os.getenv("CAMPEX_VISION_LAB_ALERT_EMAIL")
    value = (value or "").strip()
    if value:
        return value
    if os.getenv("CAMPEX_EMAIL_MODE", "console").lower() == "smtp":
        return None
    return "vision-lab-console@campex.dev"


def require_lab_recipient_email() -> str:
    email = current_lab_recipient_email()
    if email:
        return email
    raise HTTPException(
        status_code=400,
        detail="CAMPEX_VISION_LAB_RECIPIENT precisa estar configurado para testar alertas em modo SMTP.",
    )


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_email(value: str, field_name: str) -> str:
    value = (value or "").strip()
    if not EMAIL_RE.match(value):
        raise HTTPException(status_code=400, detail=f"{field_name} invalido.")
    return value


def mask_email(value: str | None) -> str | None:
    if not value:
        return None
    name, _, domain = value.partition("@")
    if not domain:
        return "***"
    prefix = name[:1] or "*"
    return f"{prefix}***@{domain}"


def safe_delivery_error(exc: Exception) -> str:
    text = str(exc) or exc.__class__.__name__
    password = os.getenv("CAMPEX_SMTP_PASSWORD", "")
    if password:
        text = text.replace(password, "***")
    return text[:300]


def require_local_request(request: Request) -> None:
    host = request.client.host if request.client else ""
    if host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(status_code=403, detail="Configuracao de e-mail permitida somente em 127.0.0.1.")


class PointPayload(BaseModel):
    x: float
    y: float


class ZonePayload(BaseModel):
    name: str
    area_type: str
    polygon: list[PointPayload]


class ThresholdPayload(BaseModel):
    stop_seconds: Optional[float] = None
    recovery_seconds: Optional[float] = None
    operator_absence_seconds: Optional[float] = None


class LabEmailSessionPayload(BaseModel):
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    email_from: str
    recipient: str
    use_tls: bool = True


@dataclass
class LabEmailSessionConfig:
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    email_from: str
    recipient: str
    use_tls: bool = True

    def public(self) -> dict[str, Any]:
        return {
            "configured": True,
            "smtp_host": self.smtp_host,
            "smtp_port": self.smtp_port,
            "smtp_user": mask_email(self.smtp_user),
            "email_from": mask_email(self.email_from),
            "recipient": mask_email(self.recipient),
            "use_tls": self.use_tls,
        }


@dataclass
class ActivityTelemetry:
    previous_gray: np.ndarray | None = None
    previous_polygon_signature: str | None = None
    raw_score: float | None = None
    smoothed_score: float | None = None
    changed_pixel_ratio: float | None = None
    changed_pixels: int = 0
    roi_size: tuple[int, int] | None = None
    roi_bounds: tuple[int, int, int, int] | None = None
    frame_size: tuple[int, int] | None = None
    frames_received: int = 0
    frames_analyzed: int = 0
    first_frame_monotonic: float = field(default_factory=time.monotonic)
    last_frame_monotonic: float | None = None
    last_analysis_monotonic: float | None = None
    last_frame_timestamp: str | None = None
    status: str = "FRAME_STALE"
    reason: str = "stream sem frames"
    error: str | None = None
    debug_log: list[dict[str, Any]] = field(default_factory=list)

    def update(self, frame: np.ndarray, polygon: list[dict[str, float]] | None) -> None:
        self.frames_received += 1
        self.last_frame_monotonic = time.monotonic()
        self.last_frame_timestamp = now_iso()
        height, width = frame.shape[:2]
        self.frame_size = (width, height)
        if not polygon:
            self._set_unavailable("WAITING_FOR_MACHINE_REGION", "machine_region ausente")
            return
        try:
            polygon_signature = json.dumps(polygon, sort_keys=True)
            if polygon_signature != self.previous_polygon_signature:
                self.previous_gray = None
                self.previous_polygon_signature = polygon_signature
                self.smoothed_score = None
            points = [(int(float(p["x"]) * width), int(float(p["y"]) * height)) for p in polygon]
            xs = [point[0] for point in points]
            ys = [point[1] for point in points]
            x1, x2 = max(0, min(xs)), min(width, max(xs))
            y1, y2 = max(0, min(ys)), min(height, max(ys))
            roi_w, roi_h = x2 - x1, y2 - y1
            self.roi_size = (roi_w, roi_h)
            self.roi_bounds = (x1, y1, x2, y2)
            if roi_w < 5 or roi_h < 5:
                self._set_unavailable("INVALID_ROI", f"ROI invalida: {roi_w}x{roi_h}")
                return
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            mask = machine_monitoring.polygon_mask(gray.shape, [AreaPoint(float(p["x"]), float(p["y"])) for p in polygon])
            gray = cv2.GaussianBlur(gray, (5, 5), 0)
            if self.previous_gray is None:
                self.previous_gray = gray
                self._set_unavailable("WAITING_FOR_PREVIOUS_FRAME", "primeiro frame de referencia armazenado")
                return
            diff = cv2.absdiff(gray, self.previous_gray)
            self.previous_gray = gray
            values = diff[mask > 0]
            if values.size == 0:
                self._set_unavailable("INVALID_ROI", "ROI sem pixels validos")
                return
            self.raw_score = round(float(np.mean(values)), 3)
            self.changed_pixels = int(np.count_nonzero(values > 12))
            self.changed_pixel_ratio = round(self.changed_pixels / float(values.size), 5)
            alpha = 0.35
            self.smoothed_score = self.raw_score if self.smoothed_score is None else round((alpha * self.raw_score) + ((1 - alpha) * self.smoothed_score), 3)
            self.frames_analyzed += 1
            self.last_analysis_monotonic = time.monotonic()
            self.status = "ANALYZING"
            self.reason = "score calculado"
            self.error = None
            self._log(
                {
                    "status": self.status,
                    "frame": {"width": width, "height": height},
                    "normalized_polygon": polygon,
                    "pixel_bounds": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
                    "roi": {"width": roi_w, "height": roi_h},
                    "changed_pixels": self.changed_pixels,
                    "raw_activity_score": self.raw_score,
                    "smoothed_activity_score": self.smoothed_score,
                }
            )
        except Exception as exc:
            self.error = str(exc)[:200]
            self.status = "ANALYSIS_ERROR"
            self.reason = "erro no recorte"
            self._log({"status": self.status, "error": self.error})

    def _set_unavailable(self, status: str, reason: str) -> None:
        self.status = status
        self.reason = reason
        self.raw_score = None
        self.changed_pixel_ratio = None
        self.changed_pixels = 0
        self._log({"status": status, "reason": reason})

    def _log(self, payload: dict[str, Any]) -> None:
        entry = {"at": now_iso(), "frames_received": self.frames_received, "frames_analyzed": self.frames_analyzed, **payload}
        self.debug_log.append(entry)
        self.debug_log = self.debug_log[-20:]
        if os.getenv("CAMPEX_VISION_LAB_DEBUG", "").lower() in {"1", "true", "sim", "yes"}:
            print(f"[vision-lab/activity] {json.dumps(entry, ensure_ascii=False)}")

    def snapshot(self) -> dict[str, Any]:
        now = time.monotonic()
        elapsed = max(0.001, now - self.first_frame_monotonic)
        return {
            "raw_activity_score": self.raw_score,
            "smoothed_activity_score": self.smoothed_score,
            "changed_pixel_ratio": self.changed_pixel_ratio,
            "changed_pixels": self.changed_pixels,
            "machine_region_found": self.status != "WAITING_FOR_MACHINE_REGION",
            "previous_frame_available": self.previous_gray is not None,
            "frame_size": {"width": self.frame_size[0], "height": self.frame_size[1]} if self.frame_size else None,
            "roi_size": {"width": self.roi_size[0], "height": self.roi_size[1]} if self.roi_size else None,
            "roi_width": self.roi_size[0] if self.roi_size else None,
            "roi_height": self.roi_size[1] if self.roi_size else None,
            "roi_bounds": {"x1": self.roi_bounds[0], "y1": self.roi_bounds[1], "x2": self.roi_bounds[2], "y2": self.roi_bounds[3]} if self.roi_bounds else None,
            "frames_received": self.frames_received,
            "frames_analyzed": self.frames_analyzed,
            "camera_fps": round(self.frames_received / elapsed, 2),
            "analysis_fps": round(self.frames_analyzed / elapsed, 2),
            "last_frame_at": self.last_frame_timestamp,
            "last_frame_age_seconds": round(now - self.last_frame_monotonic, 2) if self.last_frame_monotonic else None,
            "last_analyzer_error": self.error,
            "analysis_error": self.error,
            "analysis_status": self.status,
            "score_reason": self.reason,
            "debug_log": self.debug_log,
        }


@dataclass
class SeparationRun:
    phase: str
    started_monotonic: float
    duration_seconds: float = 10.0
    moving_samples: list[float] = field(default_factory=list)
    stopped_samples: list[float] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None

    @property
    def progress(self) -> int:
        elapsed = time.monotonic() - self.started_monotonic
        total = self.duration_seconds * 2
        return int(min(100, max(0, elapsed / total * 100)))


@dataclass
class CalibrationRun:
    phase: str
    started_at: str
    started_monotonic: float
    duration_seconds: float = 30.0
    samples: list[float] = field(default_factory=list)
    finished: bool = False
    error: str | None = None

    @property
    def progress(self) -> int:
        elapsed = time.monotonic() - self.started_monotonic
        return int(min(100, max(0, (elapsed / self.duration_seconds) * 100)))


class VisionLabRuntime:
    def __init__(self, db_path: str | Path = LAB_DB_PATH, evidence_root: str | Path = LAB_EVIDENCE_ROOT) -> None:
        self.db_path = Path(db_path)
        self.evidence_root = Path(evidence_root)
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.capture: cv2.VideoCapture | None = None
        self.worker: threading.Thread | None = None
        self.frame: np.ndarray | None = None
        self.annotated: np.ndarray | None = None
        self.jpeg: bytes | None = None
        self.status: dict[str, Any] = {
            "camera": "offline",
            "activity_score": None,
            "machine_state": "UNKNOWN",
            "machine_confidence": 0,
            "operator_present": False,
            "people_count": 0,
            "people_in_operator_zone": 0,
            "people_in_restricted_zone": 0,
            "open_event": None,
            "last_alert": None,
            "last_evidence": None,
            "last_error": None,
        }
        self.telemetry = ActivityTelemetry()
        self.separation: SeparationRun | None = None
        self.validation_transitions: list[dict[str, Any]] = []
        self.detector: PersonAnalysisEngine | None = None
        self.person_error: str | None = None
        self.zone_engine = PeopleZonesEngine(LAB_CAMERA_ID, evidence_root=self.evidence_root)
        self.observation_engine = ObservationEngine(LAB_CAMERA_ID)
        self.machine_engine: MachineMonitorEngine | None = None
        self.machine_id: str | None = None
        self.calibration: CalibrationRun | None = None
        self.email_config: LabEmailSessionConfig | None = None

    def start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        self.stop_event.clear()
        self.worker = threading.Thread(target=self._run, name="campex-vision-lab", daemon=True)
        self.worker.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.worker:
            self.worker.join(timeout=3)
        if self.capture:
            self.capture.release()
        self.zone_engine.close_interrupted()

    def _open_camera(self) -> cv2.VideoCapture | None:
        source = int(os.getenv("CAMPEX_VISION_LAB_WEBCAM_INDEX", "0"))
        capture = cv2.VideoCapture(source)
        if not capture.isOpened():
            return None
        return capture

    def _run(self) -> None:
        last_detection = 0.0
        detections = []
        while not self.stop_event.is_set():
            if self.capture is None or not self.capture.isOpened():
                self.capture = self._open_camera()
                if self.capture is None:
                    self._set_status(camera="offline", last_error="Webcam indisponivel.")
                    time.sleep(1)
                    continue
            ok, frame = self.capture.read()
            if not ok or frame is None:
                self._set_status(camera="offline", last_error="Frame nao recebido da webcam.")
                self.capture.release()
                self.capture = None
                time.sleep(0.5)
                continue
            self._set_status(camera="online", last_error=None)
            self.telemetry.update(frame, self._machine_region_polygon())
            self._collect_separation_sample()
            now = time.monotonic()
            try:
                if self.detector is None:
                    self.detector = PersonAnalysisEngine()
                if now - last_detection >= 1.0 / max(0.1, self.detector.analysis_fps):
                    detections = self.detector.analyze(frame)
                    last_detection = now
            except Exception as exc:
                self.person_error = str(exc)[:200]
                detections = []
            areas = self._areas()
            annotated = frame.copy()
            zone_state: dict[str, Any] = {"zones": [], "active_events": []}
            try:
                annotated, zone_state = self.zone_engine.update(areas, detections, annotated)
            except Exception as exc:
                self._set_status(last_error=f"Erro nas zonas: {str(exc)[:160]}")
            machine_state = self._update_machine(frame, detections)
            observation = self.observation_engine.build(
                machine_id=self.machine_id,
                machine_state=machine_state.get("state", "UNKNOWN"),
                machine_activity_score=machine_state.get("motion"),
                machine_confidence=machine_state.get("confidence"),
                operator_present=machine_state.get("operator_present", False),
                zone_states=zone_state.get("zones", []),
            )
            self._draw_lab_overlay(annotated, observation, areas)
            ok, encoded = cv2.imencode(".jpg", annotated)
            with self.lock:
                self.frame = frame.copy()
                self.annotated = annotated
                if ok:
                    self.jpeg = encoded.tobytes()
                self.status.update(
                    {
                        "activity_score": machine_state.get("motion"),
                        "machine_state": machine_state.get("state", "UNKNOWN"),
                        "machine_confidence": machine_state.get("confidence", 0),
                        "operator_present": bool(observation["operator_present"]),
                        "people_count": len(detections),
                        "people_in_operator_zone": observation["people_in_operator_zone"],
                        "people_in_restricted_zone": observation["people_in_restricted_zone"],
                        "active_zone_events": zone_state.get("active_events", []),
                    }
                )
            time.sleep(0.005)

    def _update_machine(self, frame: np.ndarray, detections) -> dict[str, Any]:
        engine = self._machine_engine()
        if engine is None:
            self._update_calibration_without_engine()
            return {
                "state": "UNKNOWN",
                "motion": self.telemetry.smoothed_score,
                "confidence": 0,
                "operator_present": False,
                "reason": self.telemetry.reason,
            }
        state = engine.update(frame, detections)
        self._collect_calibration(engine, frame)
        self._track_transition(state.state, state.confidence, state.reason)
        return {
            "state": state.state,
            "motion": state.smoothed_motion,
            "confidence": state.confidence,
            "operator_present": state.operator_present,
            "reason": state.reason,
        }

    def _collect_calibration(self, engine: MachineMonitorEngine, frame: np.ndarray) -> None:
        run = self.calibration
        if run is None or run.finished:
            return
        try:
            sample = self.telemetry.raw_score
            if sample is None:
                sample = engine._motion(frame)
            if sample is not None:
                run.samples.append(float(sample))
        except Exception as exc:
            run.error = str(exc)[:200]
        if time.monotonic() - run.started_monotonic >= run.duration_seconds:
            self._finish_calibration(engine, run)

    def _update_calibration_without_engine(self) -> None:
        run = self.calibration
        if run and not run.finished:
            run.error = "Crie machine_region e operator_zone antes de calibrar."
            run.finished = True

    def _finish_calibration(self, engine: MachineMonitorEngine, run: CalibrationRun) -> None:
        run.finished = True
        stats = calibration_stats(run.samples)
        if run.phase == "active":
            result = engine.calibrate_active(run.samples)
            active_json = {"samples": run.samples, "stats": stats, "result": result}
            stopped_json = None
        else:
            result = engine.calibrate_stopped(run.samples)
            active_json = None
            stopped_json = {"samples": run.samples, "stats": stats, "result": result}
        monitor = self._monitor()
        if monitor:
            separation = calibration_separation(
                engine.config.active_baseline,
                engine.config.stopped_baseline,
                engine.config.active_noise,
                engine.config.stopped_noise,
            )
            with connect(self.db_path) as connection:
                init_db(connection)
                registrar_machine_calibration(
                    connection,
                    machine_id=monitor["id"],
                    camera_id=LAB_CAMERA_ID,
                    phase=run.phase,
                    samples=run.samples,
                    stats=stats,
                    baseline=engine.config.active_baseline if run.phase == "active" else engine.config.stopped_baseline,
                    algorithm_version=ALGORITHM_VERSION,
                    region=monitor["machine_polygon"],
                    started_at=run.started_at,
                    finished_at=now_iso(),
                )
                atualizar_machine_monitor(
                    connection,
                    monitor["id"],
                    motion_threshold=engine.config.motion_threshold,
                    calibration_status=separation["result"],
                    running_motion=engine.config.active_baseline,
                    stopped_motion=engine.config.stopped_baseline,
                    active_baseline=engine.config.active_baseline,
                    stopped_baseline=engine.config.stopped_baseline,
                    active_noise=engine.config.active_noise,
                    stopped_noise=engine.config.stopped_noise,
                    active_calibration=active_json,
                    stopped_calibration=stopped_json,
                    separation_score=separation["score"],
                    calibration_result=separation["result"],
                    calibration_algorithm_version=ALGORITHM_VERSION,
                )
        self.machine_engine = None

    def start_separation_test(self, duration_seconds: float = 10.0) -> dict[str, Any]:
        if not self._machine_region_polygon():
            raise RuntimeError("Crie machine_region antes de testar separacao visual.")
        self.separation = SeparationRun(phase="moving", started_monotonic=time.monotonic(), duration_seconds=duration_seconds)
        return self.separation_status()

    def _collect_separation_sample(self) -> None:
        run = self.separation
        score = self.telemetry.raw_score
        if run is None or run.result or score is None:
            return
        elapsed = time.monotonic() - run.started_monotonic
        if elapsed <= run.duration_seconds:
            run.phase = "moving"
            run.moving_samples.append(score)
        elif elapsed <= run.duration_seconds * 2:
            run.phase = "stopped"
            run.stopped_samples.append(score)
        else:
            moving = calibration_stats(run.moving_samples)
            stopped = calibration_stats(run.stopped_samples)
            difference = abs(float(moving.get("mean") or 0) - float(stopped.get("mean") or 0))
            noise = max(float(moving.get("std") or 0), float(stopped.get("std") or 0), 1.0)
            score_value = round(difference / noise, 3)
            overlap = round(max(0.0, 1.0 - min(1.0, score_value / 3.0)), 3)
            run.result = {
                "moving": moving,
                "stopped": stopped,
                "absolute_difference": round(difference, 3),
                "separation_score": score_value,
                "estimated_overlap": overlap,
                "status": "PASS" if score_value >= 2 and difference >= 2 else "FAIL",
            }

    def separation_status(self) -> dict[str, Any]:
        run = self.separation
        if run is None:
            return {"running": False, "phase": None, "progress": 0, "result": None, "error": None}
        return {
            "running": run.result is None and run.error is None,
            "phase": run.phase,
            "progress": run.progress,
            "moving_samples": len(run.moving_samples),
            "stopped_samples": len(run.stopped_samples),
            "result": run.result,
            "error": run.error,
        }

    def start_calibration(self, phase: str, duration_seconds: float = 30.0) -> dict[str, Any]:
        if phase not in {"active", "stopped"}:
            raise ValueError("Fase invalida.")
        if self.calibration and not self.calibration.finished:
            raise RuntimeError("Ja existe uma calibracao em andamento.")
        if self._machine_engine() is None:
            raise RuntimeError("Crie machine_region e operator_zone antes de calibrar.")
        self.calibration = CalibrationRun(phase=phase, started_at=now_iso(), started_monotonic=time.monotonic(), duration_seconds=duration_seconds)
        return self.calibration_status()

    def calibration_status(self) -> dict[str, Any]:
        run = self.calibration
        monitor = self._monitor()
        return {
            "running": bool(run and not run.finished),
            "phase": run.phase if run else None,
            "progress": run.progress if run else 0,
            "samples": len(run.samples) if run else 0,
            "error": run.error if run else None,
            "active_baseline": monitor.get("active_baseline") if monitor else None,
            "stopped_baseline": monitor.get("stopped_baseline") if monitor else None,
            "separation_score": monitor.get("separation_score") if monitor else None,
            "calibration_result": monitor.get("calibration_result") if monitor else "INVALID",
        }

    def _machine_engine(self) -> MachineMonitorEngine | None:
        monitor = self._ensure_machine_monitor()
        if monitor is None:
            self.machine_engine = None
            self.machine_id = None
            return None
        if self.machine_engine is None or self.machine_id != monitor["id"]:
            self.machine_id = monitor["id"]
            self.machine_engine = MachineMonitorEngine(config_from_dict(monitor))
        return self.machine_engine

    def _ensure_machine_monitor(self) -> dict[str, Any] | None:
        machine = self._area_by_type("machine_region")
        operator = self._area_by_type("workstation") or self._area_by_type("operator_zone")
        if machine is None or operator is None:
            return self._monitor()
        monitor = self._monitor()
        if monitor is None:
            with connect(self.db_path) as connection:
                init_db(connection)
                monitor_id = criar_machine_monitor(
                    connection,
                    client_id=LAB_CLIENT_ID,
                    unit_id=LAB_UNIT_ID,
                    camera_id=LAB_CAMERA_ID,
                    nome=LAB_MACHINE_NAME,
                    machine_polygon=machine["pontos"],
                    operator_polygon=operator["pontos"],
                    stop_seconds=float(os.getenv("CAMPEX_MACHINE_STOP_SECONDS", "2")),
                    recovery_seconds=float(os.getenv("CAMPEX_MACHINE_RECOVERY_SECONDS", "1")),
                    operator_absence_seconds=float(os.getenv("CAMPEX_OPERATOR_ABSENCE_SECONDS", "2")),
                    replay_pre_seconds=3,
                    replay_post_seconds=2,
                )
                monitor = obter_machine_monitor(connection, monitor_id)
        elif monitor["machine_polygon"] != machine["pontos"] or monitor["operator_polygon"] != operator["pontos"]:
            with connect(self.db_path) as connection:
                init_db(connection)
                monitor = atualizar_machine_monitor(
                    connection,
                    monitor["id"],
                    machine_polygon=machine["pontos"],
                    operator_polygon=operator["pontos"],
                )
        return monitor

    def _monitor(self) -> dict[str, Any] | None:
        with connect(self.db_path) as connection:
            init_db(connection)
            rows = listar_machine_monitors_camera(connection, LAB_CAMERA_ID)
            return rows[0] if rows else None

    def _area_by_type(self, area_type: str) -> dict[str, Any] | None:
        for area in self._areas():
            if area.get("tipo") == area_type:
                return area
        return None

    def _areas(self) -> list[dict[str, Any]]:
        with connect(self.db_path) as connection:
            init_db(connection)
            return listar_areas_camera(connection, LAB_CAMERA_ID)

    def _machine_region_polygon(self) -> list[dict[str, float]] | None:
        area = self._area_by_type("machine_region")
        return area.get("pontos") if area else None

    def _track_transition(self, state: str, confidence: float, reason: str) -> None:
        last = self.validation_transitions[-1]["state"] if self.validation_transitions else None
        if state != last:
            self.validation_transitions.append({"at": now_iso(), "state": state, "confidence": confidence, "reason": reason})

    def _set_status(self, **values: Any) -> None:
        with self.lock:
            self.status.update(values)

    def _draw_lab_overlay(self, frame: np.ndarray, observation: dict[str, Any], areas: list[dict[str, Any]]) -> None:
        label = f"{observation['machine_state']} | score {observation['machine_activity_score']} | operador {'presente' if observation['operator_present'] else 'ausente'}"
        cv2.putText(frame, label, (14, frame.shape[0] - 18), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (255, 255, 255), 4, cv2.LINE_AA)
        cv2.putText(frame, label, (14, frame.shape[0] - 18), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (0, 0, 0), 2, cv2.LINE_AA)

    def snapshot_status(self) -> dict[str, Any]:
        with self.lock:
            status = dict(self.status)
        with connect(self.db_path) as connection:
            init_db(connection)
            status["areas"] = listar_areas_camera(connection, LAB_CAMERA_ID)
            machine_region = next((area for area in status["areas"] if area.get("tipo") == "machine_region"), None)
            status["lab_ids"] = {
                "client_id": LAB_CLIENT_ID,
                "unit_id": LAB_UNIT_ID,
                "edge_id": LAB_EDGE_ID,
                "camera_id": LAB_CAMERA_ID,
                "machine_region_id": machine_region.get("id") if machine_region else None,
                "machine_region_camera_id": machine_region.get("camera_id") if machine_region else None,
                "machine_region_client_id": machine_region.get("cliente_id") if machine_region else None,
                "machine_region_unit_id": machine_region.get("unidade_id") if machine_region else None,
            }
            status["events"] = listar_eventos_filtrados(connection, camera_id=LAB_CAMERA_ID)[:10]
            status["open_event"] = next((event for event in status["events"] if event.get("status") == "open"), None)
            deliveries = listar_alert_deliveries(connection)
            status["last_alert"] = deliveries[0] if deliveries else None
            status["outbox_pending"] = pending_sync_count(connection)
            status["outbox_total"] = connection.execute("SELECT COUNT(*) AS total FROM sync_outbox").fetchone()["total"]
        status["calibration"] = self.calibration_status()
        status["telemetry"] = self.telemetry.snapshot()
        status["separation_test"] = self.separation_status()
        status["transitions"] = self.validation_transitions[-20:]
        evidence_files = sorted(self.evidence_root.rglob("*.jpg"), key=lambda path: path.stat().st_mtime, reverse=True) if self.evidence_root.exists() else []
        status["last_evidence"] = str(evidence_files[0]) if evidence_files else None
        return status

    def validation_report(self) -> dict[str, Any]:
        status = self.snapshot_status()
        report = {
            "generated_at": now_iso(),
            "source": "webcam",
            "camera_id": LAB_CAMERA_ID,
            "database": str(self.db_path),
            "evidence_root": str(self.evidence_root),
            "roi": self._machine_region_polygon(),
            "telemetry": status["telemetry"],
            "active_baseline": status["calibration"].get("active_baseline"),
            "stopped_baseline": status["calibration"].get("stopped_baseline"),
            "separation_score": status["calibration"].get("separation_score"),
            "calibration_result": status["calibration"].get("calibration_result"),
            "separation_test": status["separation_test"],
            "states_detected": sorted({item["state"] for item in self.validation_transitions}),
            "transitions": self.validation_transitions,
            "events": status["events"],
            "event_count": len(status["events"]),
            "last_evidence": status["last_evidence"],
            "outbox_pending": status["outbox_pending"],
            "outbox_total": status["outbox_total"],
            "last_delivery": status["last_alert"],
            "validated": {
                "movimento_detectado": status["telemetry"].get("raw_activity_score") is not None,
                "calibracao_concluida": status["calibration"].get("calibration_result") in {"READY", "WEAK_SEPARATION"},
                "active_detectado": "ACTIVE" in {item["state"] for item in self.validation_transitions},
                "stopped_detectado": "STOPPED" in {item["state"] for item in self.validation_transitions},
                "evento_aberto_ou_registrado": bool(status["events"]),
                "evidencia_salva": bool(status["last_evidence"]),
                "banco_registrado": self.db_path.exists(),
                "outbox_registrada": status["outbox_total"] > 0,
                "email_entregue": bool(status["last_alert"] and status["last_alert"].get("status") == "sent"),
                "evento_encerrado": any(event.get("status") == "closed" for event in status["events"]),
            },
            "pending": [
                "RTSP industrial",
                "iluminacao industrial",
                "maquina industrial",
                "teste prolongado",
                "piloto externo",
            ],
            "errors": [value for value in [status.get("last_error"), status["telemetry"].get("last_analyzer_error")] if value],
        }
        report_path = ROOT / "reports" / "vision_lab_validation.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"path": str(report_path), "report": report}

    def set_email_session(self, payload: LabEmailSessionPayload) -> dict[str, Any]:
        host = payload.smtp_host.strip()
        if not host:
            raise HTTPException(status_code=400, detail="SMTP host e obrigatorio.")
        if payload.smtp_port <= 0 or payload.smtp_port > 65535:
            raise HTTPException(status_code=400, detail="SMTP port invalido.")
        password = payload.smtp_password or ""
        if not password.strip():
            raise HTTPException(status_code=400, detail="Senha de app e obrigatoria.")
        config = LabEmailSessionConfig(
            smtp_host=host,
            smtp_port=int(payload.smtp_port),
            smtp_user=validate_email(payload.smtp_user, "E-mail remetente"),
            smtp_password=password,
            email_from=validate_email(payload.email_from, "E-mail remetente"),
            recipient=validate_email(payload.recipient, "E-mail destinatario"),
            use_tls=bool(payload.use_tls),
        )
        self.email_config = config
        self._ensure_email_recipient(config.recipient)
        return config.public()

    def clear_email_session(self) -> dict[str, Any]:
        self.email_config = None
        return {"configured": False}

    def email_session_status(self) -> dict[str, Any]:
        if self.email_config is None:
            return {"configured": False}
        return self.email_config.public()

    def _ensure_email_recipient(self, email: str) -> dict[str, Any]:
        with connect(self.db_path) as connection:
            init_db(connection)
            connection.execute(
                """
                UPDATE alert_recipients
                SET nome = ?,
                    email = ?,
                    ativo = 1,
                    atualizado_em = CURRENT_TIMESTAMP
                WHERE cliente_id = ?
                  AND nome = ?
                """,
                (LAB_RECIPIENT_NAME, email, LAB_CLIENT_ID, LAB_RECIPIENT_NAME),
            )
            row = connection.execute(
                "SELECT * FROM alert_recipients WHERE cliente_id = ? AND nome = ?",
                (LAB_CLIENT_ID, LAB_RECIPIENT_NAME),
            ).fetchone()
            if row is None:
                criar_alert_recipient(
                    connection,
                    nome=LAB_RECIPIENT_NAME,
                    email=email,
                    cliente_id=LAB_CLIENT_ID,
                    event_types=["machine_stoppage"],
                    severidade_minima="low",
                )
            connection.commit()
            recipients = listar_alert_recipients(connection)
            recipient = next(item for item in recipients if item.get("cliente_id") == LAB_CLIENT_ID and item.get("nome") == LAB_RECIPIENT_NAME)
            return recipient

    def create_test_delivery(self) -> dict[str, Any]:
        config = self.email_config
        if config is None:
            if os.getenv("CAMPEX_EMAIL_MODE", "console").lower() == "smtp":
                raise HTTPException(status_code=400, detail="Configure o e-mail desta sessao antes de testar SMTP.")
            email = require_lab_recipient_email()
            config = LabEmailSessionConfig("console", 0, email, "", email, email, True)
        recipient = self._ensure_email_recipient(config.recipient)
        with connect(self.db_path) as connection:
            init_db(connection)
            delivery_id = criar_alert_delivery(connection, recipient["id"], evento_id=None, canal="email", is_test=True)
            delivery = obter_alert_delivery(connection, delivery_id)
        thread = threading.Thread(target=self._send_session_delivery, args=(delivery_id,), name=f"vision-lab-email-{delivery_id}", daemon=True)
        thread.start()
        return {
            "delivery_id": delivery_id,
            "recipient": config.recipient,
            "initial_status": delivery.get("status") if delivery else "pending",
            "mode": "smtp" if self.email_config else os.getenv("CAMPEX_EMAIL_MODE", "console"),
        }

    def _send_session_delivery(self, delivery_id: str) -> None:
        config = self.email_config
        now = now_iso()
        try:
            if config is None:
                with connect(self.db_path) as connection:
                    init_db(connection)
                    atualizar_alert_delivery_attempt(connection, delivery_id, status="sent", attempts=1, last_attempt_at=now, sent_at=now, erro=None)
                return
            message = EmailMessage()
            message["From"] = config.email_from
            message["To"] = config.recipient
            message["Subject"] = "[Campex] Teste SMTP do Vision Lab"
            message.set_content(
                "\n".join(
                    [
                        "Campex — Ambiente de Validação",
                        "Teste SMTP do Campex Local Vision Lab.",
                        f"Delivery: {delivery_id}",
                        f"Horario: {now}",
                    ]
                )
            )
            with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=15) as smtp:
                if config.use_tls:
                    smtp.starttls(context=ssl.create_default_context())
                smtp.login(config.smtp_user, config.smtp_password)
                smtp.send_message(message)
            with connect(self.db_path) as connection:
                init_db(connection)
                atualizar_alert_delivery_attempt(connection, delivery_id, status="sent", attempts=1, last_attempt_at=now_iso(), sent_at=now_iso(), erro=None)
        except Exception as exc:
            error = safe_delivery_error(exc)
            if config is not None and config.smtp_password:
                error = error.replace(config.smtp_password, "***")
            with connect(self.db_path) as connection:
                init_db(connection)
                atualizar_alert_delivery_attempt(connection, delivery_id, status="failed", attempts=1, last_attempt_at=now_iso(), erro=error)


def calibration_stats(samples: list[float]) -> dict[str, Any]:
    if not samples:
        return {"count": 0}
    array = np.array(samples, dtype=float)
    return {
        "count": int(array.size),
        "mean": round(float(np.mean(array)), 3),
        "median": round(float(np.median(array)), 3),
        "std": round(float(np.std(array)), 3),
        "min": round(float(np.min(array)), 3),
        "max": round(float(np.max(array)), 3),
        "p10": round(float(np.percentile(array, 10)), 3),
        "p90": round(float(np.percentile(array, 90)), 3),
    }


def calibration_separation(active: float | None, stopped: float | None, active_noise: float | None, stopped_noise: float | None) -> dict[str, Any]:
    if active is None or stopped is None:
        return {"score": None, "result": "INVALID"}
    distance = abs(float(active) - float(stopped))
    noise = max(float(active_noise or 0), float(stopped_noise or 0), 1.0)
    score = round(distance / noise, 3)
    if score >= 3 and distance >= 2:
        result = "READY"
    elif score >= 1.5:
        result = "WEAK_SEPARATION"
    else:
        result = "INVALID"
    return {"score": score, "result": result}


def validate_polygon(points: list[PointPayload]) -> list[dict[str, float]]:
    if len(points) < 3:
        raise HTTPException(status_code=400, detail="A zona precisa de pelo menos 3 pontos.")
    payload = []
    for point in points:
        if point.x < 0 or point.x > 1 or point.y < 0 or point.y > 1:
            raise HTTPException(status_code=400, detail="Coordenadas devem estar entre 0 e 1.")
        payload.append({"x": float(point.x), "y": float(point.y)})
    return payload


def create_lab_app(start_worker: bool = True, db_path: str | Path = LAB_DB_PATH) -> FastAPI:
    ensure_lab_database(db_path)
    runtime = VisionLabRuntime(db_path=db_path)
    app = FastAPI(title="Campex Local Vision Lab")
    app.state.runtime = runtime

    @app.on_event("startup")
    def _startup() -> None:
        if start_worker:
            runtime.start()

    @app.on_event("shutdown")
    def _shutdown() -> None:
        runtime.stop()

    @app.get("/", response_class=HTMLResponse)
    def home() -> str:
        return LAB_HTML

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "lab": "Campex Local Vision Lab", "db": str(Path(db_path)), "camera_id": LAB_CAMERA_ID}

    @app.get("/stream")
    def stream() -> StreamingResponse:
        def frames():
            while True:
                with runtime.lock:
                    jpeg = runtime.jpeg
                if jpeg:
                    yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
                time.sleep(0.05)
        return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame")

    @app.get("/status")
    def status() -> dict[str, Any]:
        return runtime.snapshot_status()

    @app.post("/lab-email/session-config")
    def set_lab_email_session(payload: LabEmailSessionPayload, request: Request) -> dict[str, Any]:
        require_local_request(request)
        return runtime.set_email_session(payload)

    @app.get("/lab-email/session-status")
    def lab_email_session_status(request: Request) -> dict[str, Any]:
        require_local_request(request)
        return runtime.email_session_status()

    @app.delete("/lab-email/session-config")
    def clear_lab_email_session(request: Request) -> dict[str, Any]:
        require_local_request(request)
        return runtime.clear_email_session()

    @app.post("/zones")
    def save_zone(payload: ZonePayload) -> dict[str, Any]:
        if payload.area_type not in {"workstation", "restricted_area", "dwell_area", "machine_region", "operator_zone"}:
            raise HTTPException(status_code=400, detail="Tipo de zona invalido para o Vision Lab.")
        points = validate_polygon(payload.polygon)
        metadata = {"vision_lab": True, "minimum_seconds": float(os.getenv("CAMPEX_ZONE_EVENT_SECONDS", "2"))}
        absence = float(os.getenv("CAMPEX_WORKSTATION_ABSENCE_SECONDS", "2")) if payload.area_type in {"workstation", "operator_zone"} else None
        with connect(db_path) as connection:
            init_db(connection)
            area_id = criar_area_monitorada(
                connection,
                camera_id=LAB_CAMERA_ID,
                nome=payload.name,
                pontos=points,
                tipo=payload.area_type,
                ativa=True,
                metadata=metadata,
                absence_tolerance_seconds=absence,
            )
            area = next(item for item in listar_areas_camera(connection, LAB_CAMERA_ID) if item["id"] == area_id)
        runtime.machine_engine = None
        return {"status": "created", "area": area}

    @app.delete("/zones")
    def clear_zones() -> dict[str, Any]:
        with connect(db_path) as connection:
            init_db(connection)
            connection.execute("DELETE FROM monitored_areas WHERE camera_id = ?", (LAB_CAMERA_ID,))
            connection.execute("DELETE FROM machine_monitors WHERE camera_id = ?", (LAB_CAMERA_ID,))
            connection.commit()
        runtime.machine_engine = None
        runtime.machine_id = None
        return {"status": "cleared"}

    @app.post("/calibration/{phase}/start")
    def start_calibration(phase: str) -> dict[str, Any]:
        try:
            duration = float(os.getenv("CAMPEX_VISION_LAB_CALIBRATION_SECONDS", "30"))
            return runtime.start_calibration(phase, duration_seconds=duration)
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/separation-test/start")
    def start_separation_test() -> dict[str, Any]:
        try:
            duration = float(os.getenv("CAMPEX_VISION_LAB_SEPARATION_SECONDS", "10"))
            return runtime.start_separation_test(duration_seconds=duration)
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/alerts/test")
    def send_lab_test_alert(request: Request) -> dict[str, Any]:
        require_local_request(request)
        return runtime.create_test_delivery()

    @app.get("/alerts/test/{delivery_id}")
    def get_lab_test_alert(delivery_id: str) -> dict[str, Any]:
        with connect(db_path) as connection:
            init_db(connection)
            delivery = obter_alert_delivery(connection, delivery_id)
        if delivery is None:
            raise HTTPException(status_code=404, detail="Entrega nao encontrada.")
        status = str(delivery.get("status") or "queued")
        normalized = "queued" if status == "pending" else status
        return {
            "delivery_id": delivery["id"],
            "recipient": delivery.get("destinatario"),
            "status": normalized,
            "attempts": delivery.get("attempts"),
            "error": delivery.get("erro"),
            "sent_at": delivery.get("sent_at"),
            "mode": os.getenv("CAMPEX_EMAIL_MODE", "console"),
        }

    @app.post("/report")
    def create_report() -> dict[str, Any]:
        return runtime.validation_report()

    @app.post("/thresholds")
    def update_thresholds(payload: ThresholdPayload) -> dict[str, Any]:
        with connect(db_path) as connection:
            init_db(connection)
            monitor = runtime._monitor()
            if monitor is None:
                raise HTTPException(status_code=400, detail="Crie machine_region e operator_zone primeiro.")
            atualizar_machine_monitor(
                connection,
                monitor["id"],
                stop_seconds=payload.stop_seconds,
                recovery_seconds=payload.recovery_seconds,
                operator_absence_seconds=payload.operator_absence_seconds,
            )
        runtime.machine_engine = None
        return {"status": "updated"}

    return app


LAB_HTML = """
<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Campex Local Vision Lab</title>
  <style>
    body { margin: 0; font-family: Inter, Arial, sans-serif; background: #10131a; color: #f4f7fb; }
    header { padding: 16px 20px; border-bottom: 1px solid #293142; display:flex; justify-content:space-between; gap:16px; align-items:center; }
    main { display:grid; grid-template-columns: minmax(480px, 1.6fr) minmax(320px, .9fr); gap:16px; padding:16px; }
    .panel { background:#171d29; border:1px solid #293142; border-radius:10px; padding:14px; }
    .video-wrap { position:relative; background:#05070b; border-radius:10px; overflow:hidden; min-height:360px; }
    #video { display:block; width:100%; height:auto; }
    #overlay { position:absolute; inset:0; width:100%; height:100%; cursor:crosshair; }
    button, select, input { border-radius:8px; border:1px solid #344058; padding:9px 11px; background:#202838; color:#f4f7fb; }
    button.primary { background:#0a68ff; border-color:#0a68ff; }
    button.active { outline:2px solid #61a5ff; }
    button:disabled { opacity:.45; cursor:not-allowed; }
    .row { display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin:8px 0; }
    .grid { display:grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap:10px; }
    .metric { background:#111722; border:1px solid #283247; padding:10px; border-radius:8px; }
    .metric span { display:block; color:#93a0b7; font-size:12px; }
    .metric strong { font-size:20px; }
    .email-grid { display:grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap:8px; }
    .email-grid label { display:flex; flex-direction:column; gap:5px; color:#93a0b7; font-size:12px; }
    .email-grid input { width:100%; box-sizing:border-box; }
    pre { white-space:pre-wrap; word-break:break-word; color:#b6c1d6; }
    .hint { color:#9ea9bc; font-size:13px; }
    .ok { color:#63d489; } .warn { color:#ffd166; } .bad { color:#ff6b6b; }
  </style>
</head>
<body>
  <header>
    <div>
      <strong>Campex Local Vision Lab</strong>
      <div class="hint">Laboratorio isolado: webcam -> engine -> eventos -> alerta console -> SQLite/outbox</div>
    </div>
    <div class="hint">http://127.0.0.1:8011</div>
  </header>
  <main>
    <section class="panel">
      <div class="video-wrap">
        <img id="video" src="/stream" alt="Video da webcam do Vision Lab" />
        <canvas id="overlay"></canvas>
      </div>
      <div class="row">
        <select id="zoneType">
          <option value="machine_region">machine_region</option>
          <option value="workstation">operator_zone / workstation</option>
          <option value="restricted_area">restricted_zone</option>
        </select>
        <input id="zoneName" placeholder="Nome da zona" />
        <button id="drawBtn" class="primary">Desenhar zona</button>
        <button id="undoBtn">Desfazer ponto</button>
        <button id="saveBtn">Salvar</button>
        <button id="cancelBtn">Cancelar</button>
        <button id="clearBtn">Limpar zonas</button>
      </div>
      <p id="message" class="hint">Clique em Desenhar zona, marque pelo menos 3 pontos sobre o video e salve.</p>
    </section>
    <aside class="panel">
      <div class="row">
        <button id="sepTest">Testar separação visual</button>
        <button id="calActive" class="primary">Calibrar ativa</button>
        <button id="calStopped">Calibrar parada</button>
        <button id="testEmail">Enviar e-mail de teste</button>
        <button id="makeReport">Gerar relatório</button>
      </div>
      <section class="panel" style="margin: 10px 0; padding: 12px;">
        <h3>CONFIGURAÇÃO DE E-MAIL — AMBIENTE DE TESTE</h3>
        <p class="hint">Somente ambiente local de desenvolvimento. Use uma senha de app, não a senha normal do Gmail. A senha fica apenas em memória enquanto este servidor estiver rodando.</p>
        <div class="email-grid">
          <label>E-mail remetente <input id="emailFrom" type="email" placeholder="voce@gmail.com" autocomplete="off" /></label>
          <label>Senha de app <input id="smtpPassword" type="password" autocomplete="new-password" /></label>
          <label>E-mail destinatário <input id="emailRecipient" type="email" placeholder="destino@gmail.com" autocomplete="off" /></label>
          <label>SMTP host <input id="smtpHost" value="smtp.gmail.com" autocomplete="off" /></label>
          <label>SMTP port <input id="smtpPort" type="number" value="587" /></label>
          <label><span>TLS</span><span><input id="smtpTls" type="checkbox" checked /> ativado</span></label>
        </div>
        <div class="row">
          <button id="togglePassword">Mostrar/ocultar senha</button>
          <button id="useEmailSession" class="primary">Usar nesta sessão</button>
          <button id="clearEmailSession">Limpar configuração</button>
        </div>
        <p id="emailStatus" class="hint">E-mail de teste ainda não configurado nesta sessão.</p>
      </section>
      <div class="grid">
        <div class="metric"><span>Camera</span><strong id="camera">offline</strong></div>
        <div class="metric"><span>Maquina</span><strong id="machine">UNKNOWN</strong></div>
        <div class="metric"><span>raw_activity_score</span><strong id="rawScore">aguardando</strong></div>
        <div class="metric"><span>smoothed_activity_score</span><strong id="score">aguardando</strong></div>
        <div class="metric"><span>changed_pixel_ratio</span><strong id="changedRatio">aguardando</strong></div>
        <div class="metric"><span>pixels alterados</span><strong id="changedPixels">0</strong></div>
        <div class="metric"><span>ROI</span><strong id="roiSize">-</strong></div>
        <div class="metric"><span>Frames recebidos</span><strong id="framesReceived">0</strong></div>
        <div class="metric"><span>Frames analisados</span><strong id="framesAnalyzed">0</strong></div>
        <div class="metric"><span>machine_region_found</span><strong id="regionFound">false</strong></div>
        <div class="metric"><span>previous_frame_available</span><strong id="previousFrame">false</strong></div>
        <div class="metric"><span>analysis_status</span><strong id="analysisStatus">FRAME_STALE</strong></div>
        <div class="metric"><span>ROI pixels</span><strong id="roiBounds">-</strong></div>
        <div class="metric"><span>FPS webcam/análise</span><strong id="fps">-</strong></div>
        <div class="metric"><span>Idade último frame</span><strong id="frameAge">-</strong></div>
        <div class="metric"><span>Motivo do score</span><strong id="scoreReason">stream sem frames</strong></div>
        <div class="metric"><span>Confianca</span><strong id="confidence">-</strong></div>
        <div class="metric"><span>Operador</span><strong id="operator">ausente</strong></div>
        <div class="metric"><span>Pessoas</span><strong id="people">0</strong></div>
        <div class="metric"><span>Na zona operador</span><strong id="opZone">0</strong></div>
        <div class="metric"><span>Na restrita</span><strong id="resZone">0</strong></div>
        <div class="metric"><span>Calibracao</span><strong id="calProgress">0%</strong></div>
        <div class="metric"><span>Amostras</span><strong id="samples">0</strong></div>
        <div class="metric"><span>Baseline ativa</span><strong id="activeBase">-</strong></div>
        <div class="metric"><span>Baseline parada</span><strong id="stoppedBase">-</strong></div>
        <div class="metric"><span>Separation</span><strong id="separation">-</strong></div>
        <div class="metric"><span>Pré-teste</span><strong id="sepStatus">não iniciado</strong></div>
        <div class="metric"><span>Outbox</span><strong id="outbox">0</strong></div>
      </div>
      <h3>Estado</h3>
      <pre id="details">{}</pre>
    </aside>
  </main>
  <script>
    const $ = (id) => document.getElementById(id);
    const video = document.getElementById('video');
    const canvas = document.getElementById('overlay');
    const ctx = canvas.getContext('2d');
    let drawing = false;
    let points = [];
    let savedAreas = [];

    function resizeCanvas() {
      const rect = video.getBoundingClientRect();
      canvas.width = rect.width;
      canvas.height = rect.height;
      drawOverlay();
    }
    window.addEventListener('resize', resizeCanvas);
    video.addEventListener('load', resizeCanvas);

    function drawOverlay() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      savedAreas.forEach(area => drawPoly(area.pontos || area.polygon || [], '#5da2ff', area.nome || area.name));
      drawPoly(points, '#ffd166', 'desenho');
    }
    function drawPoly(poly, color, label) {
      if (!poly.length) return;
      ctx.strokeStyle = color;
      ctx.fillStyle = color;
      ctx.lineWidth = 2;
      ctx.beginPath();
      poly.forEach((p, i) => {
        const x = p.x * canvas.width, y = p.y * canvas.height;
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        ctx.fillRect(x - 3, y - 3, 6, 6);
      });
      if (poly.length >= 3) ctx.closePath();
      ctx.stroke();
      if (label) ctx.fillText(label, poly[0].x * canvas.width + 6, poly[0].y * canvas.height - 6);
    }
    canvas.addEventListener('click', ev => {
      if (!drawing) return;
      const rect = canvas.getBoundingClientRect();
      points.push({ x: (ev.clientX - rect.left) / rect.width, y: (ev.clientY - rect.top) / rect.height });
      drawOverlay();
    });
    document.getElementById('drawBtn').onclick = () => {
      drawing = true; points = [];
      document.getElementById('drawBtn').classList.add('active');
      $('message').textContent = 'Modo desenho ativo. Clique no video para marcar pontos.';
    };
    document.getElementById('undoBtn').onclick = () => { points.pop(); drawOverlay(); };
    document.getElementById('cancelBtn').onclick = () => { drawing = false; points = []; drawOverlay(); $('drawBtn').classList.remove('active'); };
    document.getElementById('saveBtn').onclick = async () => {
      if (points.length < 3) { $('message').textContent = 'Marque pelo menos 3 pontos.'; return; }
      const payload = { name: $('zoneName').value || $('zoneType').value, area_type: $('zoneType').value, polygon: points };
      const res = await fetch('/zones', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) { $('message').textContent = `Erro ${res.status}: ${body.detail || 'falha ao salvar'}`; return; }
      $('message').textContent = `Zona salva: ${body.area.id}`;
      drawing = false; points = []; $('drawBtn').classList.remove('active');
      await refresh();
    };
    document.getElementById('clearBtn').onclick = async () => {
      if (!confirm('Limpar somente zonas e monitor do Vision Lab?')) return;
      await fetch('/zones', { method:'DELETE' }); await refresh();
    };
    document.getElementById('calActive').onclick = () => fetch('/calibration/active/start', {method:'POST'}).then(showResponse);
    document.getElementById('calStopped').onclick = () => fetch('/calibration/stopped/start', {method:'POST'}).then(showResponse);
    document.getElementById('sepTest').onclick = () => fetch('/separation-test/start', {method:'POST'}).then(showResponse);
    document.getElementById('togglePassword').onclick = () => {
      $('smtpPassword').type = $('smtpPassword').type === 'password' ? 'text' : 'password';
    };
    document.getElementById('useEmailSession').onclick = async () => {
      const payload = {
        smtp_host: $('smtpHost').value,
        smtp_port: Number($('smtpPort').value),
        smtp_user: $('emailFrom').value,
        smtp_password: $('smtpPassword').value,
        email_from: $('emailFrom').value,
        recipient: $('emailRecipient').value,
        use_tls: $('smtpTls').checked
      };
      const res = await fetch('/lab-email/session-config', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        $('emailStatus').textContent = `Erro ${res.status}: ${body.detail || 'falha ao configurar e-mail'}`;
        return;
      }
      $('emailStatus').textContent = `Configuração ativa: ${body.smtp_user} -> ${body.recipient}`;
    };
    document.getElementById('clearEmailSession').onclick = async () => {
      await fetch('/lab-email/session-config', { method:'DELETE' });
      $('smtpPassword').value = '';
      $('emailStatus').textContent = 'Configuração limpa da memória desta sessão.';
    };
    document.getElementById('testEmail').onclick = async () => {
      const res = await fetch('/alerts/test', {method:'POST'});
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        $('emailStatus').textContent = `Erro ${res.status}: ${body.detail || 'falha no teste de alerta'}`;
        return;
      }
      $('emailStatus').textContent = `Entrega ${body.delivery_id} para ${body.recipient}: ${body.initial_status}`;
      pollDelivery(body.delivery_id);
    };
    document.getElementById('makeReport').onclick = () => fetch('/report', {method:'POST'}).then(showResponse);
    async function showResponse(res) {
      const body = await res.json().catch(() => ({}));
      $('message').textContent = res.ok ? 'Comando executado.' : `Erro ${res.status}: ${body.detail || 'falha'}`;
    }
    async function pollDelivery(deliveryId) {
      for (let i = 0; i < 12; i++) {
        await new Promise(resolve => setTimeout(resolve, 1000));
        const res = await fetch(`/alerts/test/${deliveryId}`);
        const body = await res.json().catch(() => ({}));
        if (!res.ok) {
          $('emailStatus').textContent = `Entrega ${deliveryId}: erro ao consultar status`;
          return;
        }
        const suffix = body.error ? ` | erro: ${body.error}` : '';
        $('emailStatus').textContent = `Entrega ${body.delivery_id} para ${body.recipient}: ${body.status}${suffix}`;
        if (body.status === 'sent' || body.status === 'failed') return;
      }
    }
    async function refreshEmailSession() {
      const res = await fetch('/lab-email/session-status');
      const body = await res.json().catch(() => ({}));
      if (body.configured) {
        $('emailStatus').textContent = `Configuração em memória: ${body.smtp_user} -> ${body.recipient}`;
      }
    }
    async function refresh() {
      const data = await fetch('/status').then(r => r.json());
      savedAreas = data.areas || [];
      $('camera').textContent = data.camera;
      $('camera').className = data.camera === 'online' ? 'ok' : 'bad';
      $('machine').textContent = data.machine_state || 'UNKNOWN';
      const t = data.telemetry || {};
      $('rawScore').textContent = t.raw_activity_score == null ? 'indisponível' : Number(t.raw_activity_score).toFixed(3);
      $('score').textContent = t.smoothed_activity_score == null ? 'indisponível' : Number(t.smoothed_activity_score).toFixed(3);
      $('changedRatio').textContent = t.changed_pixel_ratio == null ? 'indisponível' : Number(t.changed_pixel_ratio).toFixed(5);
      $('changedPixels').textContent = t.changed_pixels || 0;
      $('roiSize').textContent = t.roi_size ? `${t.roi_size.width}x${t.roi_size.height}` : 'sem ROI';
      $('framesReceived').textContent = t.frames_received || 0;
      $('framesAnalyzed').textContent = t.frames_analyzed || 0;
      $('regionFound').textContent = String(Boolean(t.machine_region_found));
      $('previousFrame').textContent = String(Boolean(t.previous_frame_available));
      $('analysisStatus').textContent = t.analysis_status || 'FRAME_STALE';
      $('roiBounds').textContent = t.roi_bounds ? `${t.roi_bounds.x1},${t.roi_bounds.y1} -> ${t.roi_bounds.x2},${t.roi_bounds.y2}` : '-';
      $('fps').textContent = `${t.camera_fps || 0}/${t.analysis_fps || 0}`;
      $('frameAge').textContent = t.last_frame_age_seconds == null ? '-' : `${t.last_frame_age_seconds}s`;
      $('scoreReason').textContent = t.score_reason || 'sem diagnóstico';
      $('confidence').textContent = data.machine_confidence == null ? '-' : Number(data.machine_confidence).toFixed(2);
      $('operator').textContent = data.operator_present ? 'presente' : 'ausente';
      $('people').textContent = data.people_count || 0;
      $('opZone').textContent = data.people_in_operator_zone || 0;
      $('resZone').textContent = data.people_in_restricted_zone || 0;
      $('calProgress').textContent = `${data.calibration?.progress || 0}%`;
      $('samples').textContent = data.calibration?.samples || 0;
      $('activeBase').textContent = data.calibration?.active_baseline ?? '-';
      $('stoppedBase').textContent = data.calibration?.stopped_baseline ?? '-';
      $('separation').textContent = data.calibration?.separation_score ?? '-';
      $('sepStatus').textContent = data.separation_test?.result?.status || (data.separation_test?.running ? `${data.separation_test.phase} ${data.separation_test.progress}%` : 'não iniciado');
      $('outbox').textContent = `${data.outbox_pending || 0}/${data.outbox_total || 0}`;
      $('details').textContent = JSON.stringify({
        lab_ids: data.lab_ids,
        telemetry: data.telemetry,
        separation_test: data.separation_test,
        calibration: data.calibration,
        open_event: data.open_event,
        last_alert: data.last_alert,
        last_evidence: data.last_evidence,
        active_zone_events: data.active_zone_events,
        last_error: data.last_error
      }, null, 2);
      drawOverlay();
    }
    setInterval(refresh, 1000);
    refreshEmailSession();
    refresh();
  </script>
</body>
</html>
"""


api = create_lab_app(start_worker=True)


def main() -> None:
    ensure_lab_database()
    print("Campex Local Vision Lab disponivel em http://127.0.0.1:8011")
    print(f"SQLite isolado: {LAB_DB_PATH}")
    print(f"Evidencias isoladas: {LAB_EVIDENCE_ROOT}")
    uvicorn.run("tools.vision_lab:api", host=LAB_HOST, port=LAB_PORT, reload=False)


if __name__ == "__main__":
    main()
