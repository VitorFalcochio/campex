from __future__ import annotations

import logging
import threading
import time
import os
from collections import deque
import queue
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable

import cv2
import numpy as np

from app.config import EVIDENCE_DIR, ROOT, storage_path
from app.database import connect, init_db
from edge_agent.camera_connector import CameraSource, UniversalCameraConnector, now_iso
from app.person_detection import Detection, PersonAnalysisEngine
from app.incidents import IncidentManager
from app.people_zones import PeopleZonesEngine
from app.machine_monitoring import MachineMonitorEngine, config_from_dict, draw_machine_overlay, machine_activity_score, machine_calibration_separation
from app.models import atualizar_machine_monitor, listar_areas_ativas_camera, listar_machine_monitors_ativos_camera, new_id, registrar_evidence_index, registrar_machine_calibration
from app.operations_history import OperationsRecorder
from app.observation_engine import ObservationEngine
from app.operational_rule_runtime import OperationalRuleRuntime, facts_from_stream
from app.security import mask_sensitive_error
from app.restricted_area import (
    AreaPresence,
    AreaPresenceTracker,
    RestrictedArea,
    area_from_dict,
    draw_area_overlay,
    evaluate_area,
)


logger = logging.getLogger("campex.live_stream")


@dataclass
class LiveStreamStatus:
    camera_id: str
    status: str = "offline"
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    last_frame_at: str | None = None
    error: str | None = None
    viewers: int = 0
    reconnect_attempts: int = 0
    ai_status: str = "inativa"
    ai_model: str | None = None
    analysis_fps: float | None = None
    analysis_frames: int = 0
    people_count: int = 0
    last_analysis_at: str | None = None
    analysis_error: str | None = None
    area_id: str | None = None
    area_nome: str | None = None
    area_estado: str = "livre"
    pessoas_na_area: int = 0
    ids_na_area: list[int] | None = None
    incident_active: bool = False
    incident_id: str | None = None
    incident_started_at: str | None = None
    incident_duration: float | None = None
    incident_people: int = 0
    machine_state: str = "unavailable"
    machine_motion: float | None = None
    machine_threshold: float | None = None
    machine_operator_present: bool | None = None
    machine_event_id: str | None = None
    machine_monitor_id: str | None = None
    machine_monitor_error: str | None = None
    machine_confidence: float | None = None
    machine_reason: str | None = None
    machine_seconds_in_state: float | None = None
    machine_analysis_status: str | None = None
    machine_analysis_error: str | None = None
    machine_raw_activity_score: float | None = None
    machine_frames_analyzed: int = 0
    machine_roi_width: int = 0
    machine_roi_height: int = 0
    zones: list[dict[str, object]] | None = None
    active_zone_events: list[dict[str, object]] | None = None
    observation: dict[str, object] | None = None
    calibration: dict[str, object] | None = None

    def to_public_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["ids_na_area"] = self.ids_na_area or []
        data["zones"] = self.zones or []
        data["active_zone_events"] = self.active_zone_events or []
        data["observation"] = self.observation or {}
        data["calibration"] = self.calibration or {}
        return data


class LiveCameraStream:
    def __init__(
        self,
        camera_id: str,
        source: str,
        connector_factory: Callable[[CameraSource], UniversalCameraConnector] | None = None,
    ) -> None:
        self.camera_id = camera_id
        self.source = source
        self.connector_factory = connector_factory or (lambda camera: UniversalCameraConnector(camera))
        self.status = LiveStreamStatus(camera_id=camera_id, status="offline")
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_jpeg: bytes | None = None
        self._analysis_enabled = False
        self._analysis_engine: PersonAnalysisEngine | None = None
        self._last_detections: list[Detection] = []
        self._last_temporal_detections: list[Detection] = []
        self._last_analysis_seconds = 0.0
        self._analysis_frames = 0
        self._analysis_started = time.monotonic()
        self._last_non_machine_sample_seconds = 0.0
        self._non_machine_sample_interval_seconds = 30.0
        self._analysis_worker_stop = threading.Event()
        self._analysis_worker_thread: threading.Thread | None = None
        self._analysis_frame_lock = threading.Lock()
        self._analysis_frame = None
        self._last_raw_frame = None

        # Rolling visual evidence buffer.
        # Keeps a small compressed history in memory so future visual events
        # can recover what happened before a trigger without recording video 24/7.
        self._evidence_sample_interval_seconds = 2.0
        self._evidence_buffer_seconds = 30.0
        self._last_evidence_sample_seconds = 0.0
        self._evidence_buffer_lock = threading.Lock()
        self._evidence_buffer = deque(maxlen=18)
        self._visual_candidates: dict[str, dict[str, Any]] = {}
        self._visual_understanding_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=32)
        self._visual_understanding_worker_thread: threading.Thread | None = None
        self._visual_understanding_worker_stop = threading.Event()
        self._visual_understanding_processed: set[str] = set()
        self._last_visual_understanding_error: str | None = None

        self._area_presence_tracker = AreaPresenceTracker()
        self._active_area: RestrictedArea | None = None
        self._active_areas: list[dict[str, object]] = []
        self._last_area_load_seconds = 0.0
        self._incident_manager = IncidentManager(camera_id)
        self._people_zones = PeopleZonesEngine(camera_id)
        self._machine_engines: dict[str, MachineMonitorEngine] = {}
        self._last_machine_load_seconds = 0.0
        self._last_machine_load_error: str | None = None
        self.live_view_ops = None
        self._operations_recorder = OperationsRecorder(camera_id, camera_id)
        self._rule_runtime = OperationalRuleRuntime(camera_id)
        self._observation_engine = ObservationEngine(camera_id)
        self._calibration_lock = threading.Lock()
        self._calibration: dict[str, Any] | None = None

    def _buffer_evidence_frame(self, frame: np.ndarray) -> None:
        now = time.monotonic()
        if now - self._last_evidence_sample_seconds < self._evidence_sample_interval_seconds:
            return

        encoded, jpeg = cv2.imencode(
            ".jpg",
            frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), 82],
        )
        if not encoded:
            return

        sample = {
            "captured_at": now_iso(),
            "monotonic": now,
            "jpeg": jpeg.tobytes(),
        }

        cutoff = now - self._evidence_buffer_seconds
        with self._evidence_buffer_lock:
            self._evidence_buffer.append(sample)
            while self._evidence_buffer and self._evidence_buffer[0]["monotonic"] < cutoff:
                self._evidence_buffer.popleft()

        self._update_visual_candidates(sample)
        self._last_evidence_sample_seconds = now

    def recent_evidence_frames(self, seconds: float = 30.0) -> list[dict[str, object]]:
        cutoff = time.monotonic() - max(0.0, float(seconds))
        with self._evidence_buffer_lock:
            return [
                {
                    "captured_at": sample["captured_at"],
                    "jpeg": sample["jpeg"],
                }
                for sample in self._evidence_buffer
                if sample["monotonic"] >= cutoff
            ]

    def latest_jpeg(self) -> bytes | None:
        with self._lock:
            return bytes(self._last_jpeg) if self._last_jpeg else None

    def start_visual_candidate(
        self,
        candidate_type: str,
        *,
        context: dict[str, Any] | None = None,
        before_seconds: float = 12.0,
        after_seconds: float = 12.0,
    ) -> str:
        candidate_id = new_id("vcan")
        now = time.monotonic()
        cutoff = now - max(0.0, before_seconds)

        with self._evidence_buffer_lock:
            before = [
                dict(sample)
                for sample in self._evidence_buffer
                if sample["monotonic"] >= cutoff
            ]

        self._visual_candidates[candidate_id] = {
            "candidate_id": candidate_id,
            "candidate_type": candidate_type,
            "context": context or {},
            "triggered_at": now_iso(),
            "trigger_monotonic": now,
            "after_seconds": max(0.0, after_seconds),
            "before": before,
            "after": [],
        }
        return candidate_id

    def _update_visual_candidates(self, sample: dict[str, object]) -> None:
        completed: list[str] = []

        for candidate_id, candidate in list(self._visual_candidates.items()):
            trigger_monotonic = float(candidate["trigger_monotonic"])
            sample_monotonic = float(sample["monotonic"])

            if sample_monotonic >= trigger_monotonic:
                candidate["after"].append(dict(sample))

            if sample_monotonic >= trigger_monotonic + float(candidate["after_seconds"]):
                completed.append(candidate_id)

        for candidate_id in completed:
            candidate = self._visual_candidates.pop(candidate_id, None)
            if candidate:
                self._persist_visual_evidence_bundle(candidate)

    def _persist_visual_evidence_bundle(self, candidate: dict[str, Any]) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc).astimezone()
        folder = EVIDENCE_DIR / self.camera_id / f"{now:%Y}" / f"{now:%m}" / f"{now:%d}"
        folder.mkdir(parents=True, exist_ok=True)

        before = candidate.get("before") or []
        after = candidate.get("after") or []

        selected: list[tuple[str, dict[str, Any]]] = []

        if before:
            selected.extend(("before", sample) for sample in before[-3:])

        if after:
            selected.append(("transition", after[0]))
            selected.extend(("after", sample) for sample in after[1:4])

        refs: list[dict[str, Any]] = []

        with connect() as connection:
            init_db(connection)

            for index, (phase, sample) in enumerate(selected):
                evidence_id = new_id("evd")
                filename = f"{now:%H%M%S}_{candidate['candidate_id']}_{phase}_{index}.jpg"
                path = folder / filename
                path.write_bytes(sample["jpeg"])

                try:
                    relative_path = storage_path(path)
                except ValueError:
                    relative_path = str(path)

                metadata = {
                    "source": "visual_candidate",
                    "candidate_id": candidate["candidate_id"],
                    "candidate_type": candidate["candidate_type"],
                    "phase": phase,
                    "captured_at": sample.get("captured_at"),
                    "triggered_at": candidate.get("triggered_at"),
                    "context": candidate.get("context") or {},
                }

                registrar_evidence_index(
                    connection,
                    evidence_id=evidence_id,
                    event_id=None,
                    event_uuid=None,
                    tenant_id=(candidate.get("context") or {}).get("tenant_id"),
                    unit_id=(candidate.get("context") or {}).get("unit_id"),
                    camera_id=self.camera_id,
                    machine_id=(candidate.get("context") or {}).get("machine_id"),
                    path=relative_path,
                    media_type="image",
                    size_bytes=path.stat().st_size,
                    metadata=metadata,
                )

                refs.append({
                    "evidence_id": evidence_id,
                    "path": relative_path,
                    "type": "image",
                    "phase": phase,
                    "captured_at": sample.get("captured_at"),
                })

        self._enqueue_visual_understanding(candidate)
        return refs

    def _ensure_visual_understanding_worker(self) -> None:
        thread = self._visual_understanding_worker_thread
        if thread and thread.is_alive():
            return

        self._visual_understanding_worker_stop.clear()
        self._visual_understanding_worker_thread = threading.Thread(
            target=self._visual_understanding_worker_loop,
            name=f"visual-understanding-{self.camera_id}",
            daemon=True,
        )
        self._visual_understanding_worker_thread.start()

    def _enqueue_visual_understanding(self, candidate: dict[str, Any]) -> None:
        import os

        auto_enabled = (
            os.getenv("CAMPEX_VISUAL_UNDERSTANDING_AUTO_ENABLED", "")
            .strip()
            .lower()
            in {"1", "true", "yes", "on"}
        )
        provider = (
            os.getenv("CAMPEX_VIDEO_UNDERSTANDING_PROVIDER")
            or os.getenv("VIDEO_UNDERSTANDING_PROVIDER")
            or ""
        ).strip().lower()

        if not auto_enabled or provider not in {"fake", "stub", "openai"}:
            return

        candidate_id = str(candidate.get("candidate_id") or "")
        if not candidate_id or candidate_id in self._visual_understanding_processed:
            return

        job = {
            "candidate_id": candidate_id,
            "candidate_type": candidate.get("candidate_type"),
            "triggered_at": candidate.get("triggered_at"),
            "context": dict(candidate.get("context") or {}),
        }

        self._ensure_visual_understanding_worker()

        try:
            self._visual_understanding_queue.put_nowait(job)
        except queue.Full:
            self._last_visual_understanding_error = "visual_understanding_queue_full"

    def _visual_understanding_worker_loop(self) -> None:
        from app.operational_read_model import ReadModelFilters, _context_id_for_trigger
        from app.video_understanding import VideoUnderstandingService

        while not self._visual_understanding_worker_stop.is_set():
            try:
                job = self._visual_understanding_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            try:
                context = dict(job.get("context") or {})
                context.setdefault("camera_id", self.camera_id)

                trigger = {
                    "type": f"visual_candidate_{job.get('candidate_type') or 'scene_change'}",
                    "ref": job["candidate_id"],
                    "timestamp": job.get("triggered_at"),
                    "context": context,
                    "source": "visual_evidence_bundle",
                }

                context_id = _context_id_for_trigger(trigger)

                filters = ReadModelFilters(
                    cliente_id=context.get("tenant_id"),
                    site_id=context.get("unit_id"),
                    camera_id=context.get("camera_id") or self.camera_id,
                )

                with connect() as connection:
                    init_db(connection)
                    VideoUnderstandingService().analyze_context(
                        connection,
                        filters,
                        context_id,
                    )

                self._visual_understanding_processed.add(job["candidate_id"])
                self._last_visual_understanding_error = None

            except Exception as exc:
                self._last_visual_understanding_error = str(exc)

            finally:
                self._visual_understanding_queue.task_done()

    def _evaluate_rules(
        self,
        frame=None,
        area_presence: AreaPresence | None = None,
        machine_state: str | None = None,
        machine_motion: float | None = None,
        operator_present: bool | None = None,
        operator_people_count: int | None = None,
        confidence: float | None = None,
        force: bool = False,
    ) -> None:
        with self._lock:
            status = self.status.status
            fps = self.status.fps
            detections = list(self._last_detections)
        facts = facts_from_stream(
            self.camera_id,
            status,
            detections=detections,
            area_presence=area_presence,
            machine_state=machine_state,
            machine_motion=machine_motion,
            operator_present=operator_present,
            operator_people_count=operator_people_count,
            fps=fps,
            confidence=confidence,
        )
        self._rule_runtime.evaluate(facts, frame=frame, force=force)

    def enable_live_view_ops(self):
        """Compatibility shim.

        Live View no longer owns an operational runtime. Frames and decisions
        flow through MachineMonitorEngine, ObservationEngine and PeopleZonesEngine.
        """
        return None

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self.status.status = "conectando"
            self._thread = threading.Thread(target=self._run, name=f"live-{self.camera_id}", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread:
            thread.join(timeout=5.0)
        for engine in list(self._machine_engines.values()):
            engine.close_interrupted()
        self._incident_manager.close_interrupted()
        self._people_zones.close_interrupted()
        self._rule_runtime.camera_status("offline", self._last_raw_frame)
        with self._lock:
            self.status.status = "offline"
            self.status.viewers = 0
            self.status.ai_status = "inativa"

    def set_analysis(self, enabled: bool) -> dict[str, object]:
        with self._lock:
            self._analysis_enabled = enabled
            if not enabled:
                self._analysis_worker_stop.set()
                self._last_detections = []
                self.status.ai_status = "inativa"
                self.status.people_count = 0
                self.status.analysis_error = None
                return self.status.to_public_dict()
            self.status.ai_status = "carregando"
            self._ensure_analysis_worker()
        return self.public_status()

    def _ensure_analysis_worker(self) -> None:
        if self._analysis_worker_thread and self._analysis_worker_thread.is_alive():
            return
        self._analysis_worker_stop.clear()
        self._analysis_worker_thread = threading.Thread(
            target=self._analysis_worker,
            name=f"analysis-{self.camera_id}",
            daemon=True,
        )
        self._analysis_worker_thread.start()

    def _analysis_worker(self) -> None:
        while not self._analysis_worker_stop.is_set():
            engine = self._ensure_analysis_engine()
            if engine is None:
                self._analysis_worker_stop.wait(1.0)
                continue
            with self._analysis_frame_lock:
                frame = self._analysis_frame.copy() if self._analysis_frame is not None else None
                self._analysis_frame = None
            if frame is None:
                self._analysis_worker_stop.wait(0.05)
                continue
            try:
                detections = engine.analyze(frame)
                now = time.monotonic()
                self._analysis_frames += 1
                elapsed = max(0.001, now - self._analysis_started)
                with self._lock:
                    self._last_detections = detections
                    self.status.ai_status = "ativa"
                    self.status.ai_model = engine.model_name
                    self.status.analysis_fps = round(self._analysis_frames / elapsed, 2)
                    self.status.analysis_frames = self._analysis_frames
                    self.status.people_count = len([d for d in detections if d.class_name == "person"])
                    self.status.last_analysis_at = now_iso()
                    self.status.analysis_error = None
            except Exception as exc:
                with self._lock:
                    self.status.ai_status = "indisponivel"
                    self.status.analysis_error = str(exc)

    def _submit_analysis_frame(self, frame, analysis_fps: float) -> None:
        now = time.monotonic()
        interval = 1.0 / max(0.1, analysis_fps)
        if now - self._last_analysis_seconds < interval:
            return
        self._last_analysis_seconds = now
        with self._analysis_frame_lock:
            self._analysis_frame = frame.copy()

    def _ensure_analysis_engine(self) -> PersonAnalysisEngine | None:
        if self._analysis_engine is not None:
            return self._analysis_engine
        try:
            self._analysis_engine = PersonAnalysisEngine()
            with self._lock:
                self.status.ai_model = self._analysis_engine.model_name
                self.status.ai_status = "ativa"
                self.status.analysis_error = None
            return self._analysis_engine
        except Exception as exc:
            with self._lock:
                self.status.ai_status = "indisponivel"
                self.status.analysis_error = str(exc)
            return None

    def start_machine_calibration(self, monitor: dict[str, Any], region: list[dict[str, float]], phase: str, duration_seconds: float = 30.0) -> dict[str, object]:
        if phase not in {"active", "stopped"}:
            raise ValueError("Fase de calibracao invalida.")
        with self._calibration_lock:
            if self._calibration and self._calibration.get("status") == "running":
                raise RuntimeError("Ja existe uma calibracao em andamento nesta camera.")
            started = now_iso()
            self._calibration = {
                "status": "running",
                "phase": phase,
                "machine_id": monitor["id"],
                "camera_id": self.camera_id,
                "duration_seconds": max(0.01, float(duration_seconds)),
                "started_at": started,
                "started_monotonic": time.monotonic(),
                "samples": [],
                "invalid_frames": 0,
                "region": region,
                "previous_gray": None,
                "algorithm_version": "frame-diff-roi-temporal-v1",
                "result": None,
                "error": None,
            }
        return self.calibration_status()

    def calibration_status(self) -> dict[str, object]:
        with self._calibration_lock:
            if not self._calibration:
                return {"status": "idle"}
            data = {key: value for key, value in self._calibration.items() if key not in {"previous_gray", "samples"}}
            samples = list(self._calibration.get("samples") or [])
        elapsed = max(0.0, time.monotonic() - float(data.get("started_monotonic") or time.monotonic()))
        duration = float(data.get("duration_seconds") or 1.0)
        data["progress"] = min(100, round((elapsed / duration) * 100, 1)) if data.get("status") == "running" else 100
        data["samples_count"] = len(samples)
        data["last_sample"] = samples[-1] if samples else None
        data.pop("started_monotonic", None)
        return data

    def machine_diagnostics(self, monitor_id: str) -> dict[str, object] | None:
        with self._lock:
            is_online = self.status.status == "online"
            engine = self._machine_engines.get(monitor_id)
        if not is_online or engine is None:
            return None
        state = engine.state
        config = engine.config
        now = time.monotonic()
        state_since = state.state_since
        seconds_in_state = round(max(0.0, now - float(state_since)), 3) if state_since is not None else None
        smoothed = state.smoothed_motion
        if smoothed is None:
            smoothed = state.window_median
        return {
            "runtime_diagnostics": {
                "machine_state": state.state,
                "raw_activity_score": state.raw_activity_score,
                "smoothed_activity_score": round(float(smoothed), 3) if smoothed is not None else None,
                "threshold": round(float(state.threshold), 3),
                "confidence": state.confidence,
                "reason": state.reason,
                "signal_quality": state.signal_quality,
                "analysis_status": state.analysis_status,
                "analysis_error": state.analysis_error,
                "seconds_in_state": seconds_in_state,
                "frames_analyzed": state.frames_analyzed,
                "roi_width": state.roi_width,
                "roi_height": state.roi_height,
                "window_samples": state.window_samples,
                "window_mean": state.window_mean,
                "window_median": state.window_median,
                "window_std": state.window_std,
            },
            "calibration": {
                "active_baseline": config.active_baseline,
                "stopped_baseline": config.stopped_baseline,
                "active_noise": config.active_noise,
                "stopped_noise": config.stopped_noise,
                "separation_score": config.separation_score,
                "threshold": config.motion_threshold,
                "calibration_result": config.calibration_result,
            },
        }

    def _update_calibration(self, frame) -> None:
        with self._calibration_lock:
            session = self._calibration
            if not session or session.get("status") != "running":
                return
            elapsed = time.monotonic() - float(session["started_monotonic"])
            duration = float(session["duration_seconds"])
            if elapsed >= duration:
                session["status"] = "finishing"
                snapshot = dict(session)
            else:
                snapshot = None
                try:
                    score, previous = calibration_activity_score(frame, session["region"], session.get("previous_gray"))
                    session["previous_gray"] = previous
                    if score is None:
                        session["invalid_frames"] += 1
                    else:
                        session["samples"].append(round(float(score), 4))
                except Exception as exc:
                    session["invalid_frames"] += 1
                    session["error"] = str(exc)
                return
        self._finish_calibration(snapshot)

    def _finish_calibration(self, session: dict[str, Any]) -> None:
        samples = list(session.get("samples") or [])
        finished = now_iso()
        if not samples:
            result = {
                "status": "failed",
                "phase": session["phase"],
                "error": "Nenhuma amostra valida foi capturada.",
                "samples_count": 0,
                "finished_at": finished,
            }
            with self._calibration_lock:
                self._calibration = {**session, **result}
            return
        stats = calibration_stats(samples)
        phase = str(session["phase"])
        monitor_id = str(session["machine_id"])
        algorithm = str(session["algorithm_version"])
        region = list(session.get("region") or [])
        try:
            with connect() as connection:
                init_db(connection)
                registrar_machine_calibration(
                    connection,
                    machine_id=monitor_id,
                    camera_id=self.camera_id,
                    phase=phase,
                    samples=samples,
                    stats=stats,
                    algorithm_version=algorithm,
                    region=region,
                    started_at=str(session["started_at"]),
                    finished_at=finished,
                )
                monitor = next((item for item in listar_machine_monitors_ativos_camera(connection, self.camera_id) if item["id"] == monitor_id), None)
                active_calibration = stats if phase == "active" else (monitor or {}).get("active_calibration")
                stopped_calibration = stats if phase == "stopped" else (monitor or {}).get("stopped_calibration")
                separation = calibration_separation(active_calibration, stopped_calibration)
                atualizar_machine_monitor(
                    connection,
                    monitor_id,
                    motion_threshold=separation.get("threshold"),
                    calibration_status="calibrated" if separation["result"] == "READY" else "calibration_needs_review",
                    running_motion=active_calibration.get("median") if active_calibration else None,
                    stopped_motion=stopped_calibration.get("median") if stopped_calibration else None,
                    active_baseline=active_calibration.get("median") if active_calibration else None,
                    stopped_baseline=stopped_calibration.get("median") if stopped_calibration else None,
                    active_noise=active_calibration.get("std") if active_calibration else None,
                    stopped_noise=stopped_calibration.get("std") if stopped_calibration else None,
                    active_calibration=active_calibration if phase == "active" else None,
                    stopped_calibration=stopped_calibration if phase == "stopped" else None,
                    separation_score=separation.get("score"),
                    calibration_result=separation["result"],
                    calibration_algorithm_version="frame-diff-roi-temporal-v1",
                )
                previous_engine = self._machine_engines.pop(monitor_id, None)
                if previous_engine is not None:
                    previous_engine.close_interrupted()
        except Exception as exc:
            with self._calibration_lock:
                self._calibration = {**session, "status": "failed", "error": str(exc), "samples_count": len(samples), "finished_at": finished}
            return
        with self._calibration_lock:
            self._calibration = {
                "status": "completed",
                "phase": phase,
                "machine_id": monitor_id,
                "camera_id": self.camera_id,
                "samples_count": len(samples),
                "invalid_frames": int(session.get("invalid_frames") or 0),
                "stats": stats,
                "separation": separation,
                "started_at": session["started_at"],
                "finished_at": finished,
                "algorithm_version": algorithm,
            }
        with self._lock:
            self.status.calibration = self.calibration_status()

    def _load_active_areas(self) -> list[dict[str, object]]:
        now = time.monotonic()
        if now - self._last_area_load_seconds < 2.0:
            return self._active_areas
        self._last_area_load_seconds = now
        try:
            with connect() as connection:
                init_db(connection)
                areas = listar_areas_ativas_camera(connection, self.camera_id)
            self._active_areas = areas
            self._active_area = area_from_dict(areas[0]) if areas else None
        except Exception:
            self._active_areas = []
            self._active_area = None
        return self._active_areas

    def _load_machine_engines(self) -> list[MachineMonitorEngine]:
        now = time.monotonic()
        if now - self._last_machine_load_seconds < 2.0:
            return list(self._machine_engines.values())
        self._last_machine_load_seconds = now
        try:
            with connect() as connection:
                init_db(connection)
                monitors = listar_machine_monitors_ativos_camera(connection, self.camera_id)
            active_ids = {monitor["id"] for monitor in monitors}
            for stale_id in set(self._machine_engines) - active_ids:
                stale_engine = self._machine_engines.pop(stale_id, None)
                if stale_engine is not None:
                    stale_engine.close_interrupted()
            for monitor in monitors:
                if monitor["id"] not in self._machine_engines:
                    self._machine_engines[monitor["id"]] = MachineMonitorEngine(config_from_dict(monitor))
                setattr(self._machine_engines[monitor["id"]], "_monitor_public", monitor)
            self._last_machine_load_error = None
            with self._lock:
                self.status.machine_monitor_error = None
        except Exception as exc:
            error = mask_sensitive_error(str(exc)) or type(exc).__name__
            if error != self._last_machine_load_error:
                logger.warning("Falha ao carregar machine monitor da câmera %s: %s", self.camera_id, error)
                self._last_machine_load_error = error
            with self._lock:
                self.status.machine_monitor_error = error
            return list(self._machine_engines.values())
        return list(self._machine_engines.values())

    def _maybe_analyze(self, frame):
        with self._lock:
            enabled = self._analysis_enabled
        areas = self._load_active_areas()
        area = area_from_dict(areas[0]) if areas else None
        if not enabled:
            presence = AreaPresence(
                area_id=area.id if area else None,
                area_nome=area.nome if area else None,
            )
            with self._lock:
                self.status.area_id = presence.area_id
                self.status.area_nome = presence.area_nome
                self.status.area_estado = presence.estado
                self.status.pessoas_na_area = presence.pessoas_dentro
                self.status.ids_na_area = presence.ids_dentro or []
                self.status.zones = []
                self.status.active_zone_events = []
            output = draw_area_overlay(frame, area, presence, set(), [])
            output = self._update_machines(output, self._load_machine_engines(), presence)
            self._evaluate_rules(output, area_presence=presence)
            return output
        engine = self._ensure_analysis_engine()
        if engine is None:
            return frame
        now = time.monotonic()
        interval = 1.0 / max(0.1, engine.analysis_fps)
        if now - self._last_analysis_seconds >= interval:
            try:
                detections = engine.analyze(frame)
                self._last_detections = detections
                self._last_temporal_detections = engine.recent_detections() or detections
                self._last_analysis_seconds = now
                self._analysis_frames += 1
                elapsed = max(0.001, now - self._analysis_started)
                with self._lock:
                    self.status.ai_status = "ativa"
                    self.status.ai_model = engine.model_name
                    self.status.analysis_fps = round(self._analysis_frames / elapsed, 2)
                    self.status.analysis_frames = self._analysis_frames
                    self.status.people_count = len([d for d in detections if d.class_name == "person"])
                    self.status.last_analysis_at = now_iso()
                    self.status.analysis_error = None
            except Exception as exc:
                with self._lock:
                    self.status.ai_status = "indisponivel"
                    self.status.analysis_error = str(exc)
                return frame
        height, width = frame.shape[:2]
        temporal_detections = self._last_temporal_detections or self._last_detections
        presence, inside_ids = evaluate_area(area, temporal_detections, width, height, self._area_presence_tracker)
        with self._lock:
            self.status.people_count = len([d for d in temporal_detections if d.class_name == "person"])
            self.status.area_id = presence.area_id
            self.status.area_nome = presence.area_nome
            self.status.area_estado = presence.estado
            self.status.pessoas_na_area = presence.pessoas_dentro
            self.status.ids_na_area = presence.ids_dentro or []
        machine_engines = self._load_machine_engines()
        if areas:
            output, people_zones = self._people_zones.update(areas, temporal_detections, frame)
            output = self._update_machines(output, machine_engines, presence, people_zones.get("zones") or [])
            with self._lock:
                self.status.zones = people_zones.get("zones") or []
                self.status.active_zone_events = people_zones.get("active_events") or []
                first_active = (people_zones.get("active_events") or [None])[0]
                self.status.incident_active = bool(first_active)
                self.status.incident_id = first_active.get("event_id") if first_active else None
                self.status.incident_started_at = first_active.get("started_at_iso") if first_active else None
                self.status.incident_people = int(first_active.get("current_people") or 0) if first_active else 0
            self._evaluate_rules(output, area_presence=presence)
            return output
        self._people_zones.update([], temporal_detections, frame)
        output = engine.draw(frame, temporal_detections)
        output = self._update_machines(output, machine_engines, presence)
        self._evaluate_rules(output, area_presence=presence)
        return output

    def _record_non_machine_operational_sample_if_due(self) -> None:
        if self._machine_engines:
            return
        now = time.monotonic()
        if now - self._last_non_machine_sample_seconds < self._non_machine_sample_interval_seconds:
            return
        self._last_non_machine_sample_seconds = now
        self._operations_recorder.update_status("online", self._official_ops_state())

    def _official_ops_state(self) -> dict[str, object]:
        with self._lock:
            status = self.status.to_public_dict()
        machine = None
        calibration = status.get("calibration") or {}
        for engine in self._machine_engines.values():
            machine = {
                "id": engine.config.id,
                "nome": engine.config.nome,
                "threshold": engine.config.motion_threshold,
                "active_baseline": engine.config.active_baseline,
                "stopped_baseline": engine.config.stopped_baseline,
            }
            break
        state = status.get("machine_state")
        if state == "ACTIVE":
            machine_state = "ATIVA"
        elif state == "STOPPED":
            machine_state = "PARADA"
        elif state == "UNKNOWN":
            machine_state = "UNKNOWN"
        else:
            machine_state = "NAO_CONFIGURADA"
        return {
            "machine": machine,
            "machine_state": machine_state,
            "machine_motion": status.get("machine_motion"),
            "machine_threshold": status.get("machine_threshold"),
            "machine_reason": status.get("machine_reason"),
            "machine_seconds_in_state": status.get("machine_seconds_in_state"),
            "analysis_status": status.get("machine_analysis_status"),
            "analysis_error": status.get("machine_analysis_error"),
            "raw_activity_score": status.get("machine_raw_activity_score"),
            "smoothed_activity_score": status.get("machine_motion"),
            "capture_fps": status.get("fps"),
            "inference_fps": status.get("analysis_fps"),
            "frames_analyzed": status.get("analysis_frames"),
            "roi": {
                "width": status.get("machine_roi_width"),
                "height": status.get("machine_roi_height"),
            },
            "operator_present": status.get("machine_operator_present"),
            "operator_people_count": 1 if status.get("machine_operator_present") else 0,
            "people_count": int(status.get("people_count") or 0),
            "visual_confidence": status.get("machine_confidence") or (status.get("observation") or {}).get("machine_confidence") or 0,
            "calibration_status": calibration.get("calibration_result") or calibration.get("status") or "não calibrada",
            "baselines": {
                "active": calibration.get("active_baseline"),
                "stopped": calibration.get("stopped_baseline"),
            },
            "separation_score": calibration.get("separation_score"),
            "event_id": status.get("machine_event_id"),
        }

    def _update_machines(self, frame, machine_engines: list[MachineMonitorEngine], area_presence: AreaPresence | None = None, zone_states: list[dict[str, object]] | None = None):
        output = frame
        zone_states = list(zone_states or [])
        for engine in machine_engines:
            try:
                previous_machine_state = self.status.machine_state
                state = engine.update(output, self._last_temporal_detections or self._last_detections)
                output = draw_machine_overlay(output, engine.config, state)
                machine_state = "ACTIVE" if state.state == "ACTIVE" else "STOPPED" if state.state == "STOPPED" else "UNKNOWN"

                if (
                    previous_machine_state in {"ACTIVE", "STOPPED"}
                    and state.state in {"ACTIVE", "STOPPED"}
                    and previous_machine_state != state.state
                ):
                    self.start_visual_candidate(
                        "machine_state_change",
                        context={
                            "tenant_id": engine.config.client_id,
                            "unit_id": engine.config.unit_id,
                            "camera_id": self.camera_id,
                            "machine_id": engine.config.id,
                            "previous_state": previous_machine_state,
                            "new_state": state.state,
                        },
                        before_seconds=12.0,
                        after_seconds=12.0,
                    )
                if area_presence and not zone_states:
                    zone_states.append({**area_presence.to_dict(), "tipo": "restricted_zone"})
                monitor_public = getattr(engine, "_monitor_public", {}) or {}
                observation = self._observation_engine.build(
                    machine_id=engine.config.id,
                    machine_state=machine_state,
                    machine_activity_score=state.smoothed_motion,
                    machine_confidence=state.confidence,
                    operator_present=state.operator_present,
                    zone_states=zone_states or [],
                    cliente_id=engine.config.client_id,
                    unidade_id=engine.config.unit_id,
                    area_id=monitor_public.get("area_context_id"),
                    process_id=monitor_public.get("process_id"),
                    asset_id=monitor_public.get("asset_id"),
                    camera_online=self.status.status == "online",
                    inference_available=self.status.ai_status == "ativa",
                    operator_absence_tolerance_seconds=engine.config.operator_absence_seconds,
                    detections=self._last_temporal_detections or self._last_detections,
                    frame_width=output.shape[1],
                    frame_height=output.shape[0],
                )
                with self._lock:
                    self.status.machine_state = state.state
                    self.status.machine_motion = round(state.smoothed_motion, 3)
                    self.status.machine_threshold = round(state.threshold, 3)
                    self.status.machine_operator_present = state.operator_present
                    self.status.machine_event_id = state.event_id
                    self.status.machine_monitor_id = engine.config.id
                    self.status.machine_confidence = state.confidence
                    self.status.machine_reason = state.reason
                    self.status.machine_analysis_status = state.analysis_status
                    self.status.machine_analysis_error = state.analysis_error
                    self.status.machine_raw_activity_score = state.raw_activity_score
                    self.status.machine_frames_analyzed = state.frames_analyzed
                    self.status.machine_roi_width = state.roi_width
                    self.status.machine_roi_height = state.roi_height
                    self.status.observation = observation
                    self.status.machine_seconds_in_state = observation.get("seconds_in_machine_state")
                    self.status.calibration = {
                        "machine_monitor_id": engine.config.id,
                        "active_baseline": engine.config.active_baseline,
                        "stopped_baseline": engine.config.stopped_baseline,
                        "motion_threshold": engine.config.motion_threshold,
                        "separation_score": monitor_public.get("separation_score"),
                        "calibration_result": monitor_public.get("calibration_result") or monitor_public.get("calibration_status"),
                    }
                self._operations_recorder.update_status("online", self._official_ops_state(), output)
                self._evaluate_rules(
                    output,
                    area_presence=area_presence,
                    machine_state="ATIVA" if state.state == "ACTIVE" else "PARADA" if state.state == "STOPPED" else "UNKNOWN",
                    machine_motion=state.smoothed_motion,
                    operator_present=state.operator_present,
                    operator_people_count=1 if state.operator_present else 0,
                    confidence=state.confidence,
                )
            except Exception as exc:
                with self._lock:
                    self.status.machine_state = "unavailable"
                    self.status.analysis_error = str(exc)
        return output

    def _invalidate_operational_state_for_offline(self) -> None:
        """Camera loss means UNKNOWN, never operator absence."""
        for engine in list(self._machine_engines.values()):
            try:
                engine.close_interrupted()
            except Exception:
                pass

        try:
            self._incident_manager.close_interrupted()
        except Exception:
            pass

        try:
            self._people_zones.close_interrupted()
        except Exception:
            pass

        with self._lock:
            self.status.machine_state = "unavailable"
            self.status.machine_operator_present = None
            self.status.machine_event_id = None
            self.status.machine_seconds_in_state = None
            self.status.active_zone_events = []
            self.status.incident_active = False
            self.status.incident_id = None
            self.status.incident_started_at = None
            self.status.incident_duration = None
            self.status.incident_people = 0
            self.status.observation = {}

    def _run(self) -> None:
        self._analysis_worker_stop.clear()
        reconnect_delay = 1.0
        connector = self.connector_factory(
            CameraSource(camera_id=self.camera_id, source=self.source, reconnect_seconds=1.0)
        )
        try:
            while not self._stop_event.is_set():
                with self._lock:
                    self.status.status = "conectando" if self.status.reconnect_attempts == 0 else "reconectando"
                if not connector.open():
                    with self._lock:
                        self.status.status = "reconectando"
                        self.status.error = connector.info.error
                    self.status.reconnect_attempts += 1
                    self._invalidate_operational_state_for_offline()
                    self._operations_recorder.update_status("offline", self._official_ops_state())
                    self._rule_runtime.camera_status("offline", self._last_raw_frame)
                    self._stop_event.wait(reconnect_delay)
                    reconnect_delay = min(10.0, reconnect_delay * 1.5)
                    continue

                reconnect_delay = 1.0
                with self._lock:
                    self.status.status = "online"
                    self.status.error = None
                    self.status.width = connector.info.width
                    self.status.height = connector.info.height
                    self.status.fps = connector.info.fps
                # A amostra operacional online é registrada após o primeiro frame/análise,
                # evitando marcar a inferência como indisponível durante o instante de conexão.
                self._rule_runtime.camera_status("online")

                frame_count = 0
                fps_started = time.monotonic()
                while not self._stop_event.is_set():
                    ok, frame = connector.capture.read() if connector.capture else (False, None)
                    if not ok or frame is None:
                        connector.close()
                        with self._lock:
                            self.status.status = "reconectando"
                            self.status.error = "Stream parou de entregar frames."
                            self.status.reconnect_attempts += 1
                        self._invalidate_operational_state_for_offline()
                        self._operations_recorder.update_status("offline", self._official_ops_state())
                        self._rule_runtime.camera_status("offline", self._last_raw_frame)
                        break

                    self._last_raw_frame = frame.copy()
                    self._buffer_evidence_frame(frame)
                    self._update_calibration(frame)
                    output_frame = self._maybe_analyze(frame)
                    self._record_non_machine_operational_sample_if_due()
                    encoded, jpeg = cv2.imencode(".jpg", output_frame)
                    if not encoded:
                        continue
                    frame_count += 1
                    elapsed = max(0.001, time.monotonic() - fps_started)
                    height, width = frame.shape[:2]
                    with self._lock:
                        self._last_jpeg = jpeg.tobytes()
                        self.status.status = "online"
                        self.status.width = width
                        self.status.height = height
                        self.status.fps = round(frame_count / elapsed, 2)
                        self.status.last_frame_at = now_iso()
                        self.status.error = None
        finally:
            self._analysis_worker_stop.set()
            analysis_thread = self._analysis_worker_thread
            if analysis_thread:
                analysis_thread.join(timeout=3.0)
            connector.stop()
            self._incident_manager.close_interrupted()
            self._people_zones.close_interrupted()
            with self._lock:
                if self.status.status != "offline":
                    self.status.status = "offline"

    def frames(self):
        self.start()
        with self._lock:
            self.status.viewers += 1
        try:
            while not self._stop_event.is_set():
                with self._lock:
                    jpeg = self._last_jpeg
                    status = self.status.status
                if jpeg is None:
                    if status in {"offline", "erro"}:
                        break
                    time.sleep(0.2)
                    continue
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
                )
                time.sleep(0.03)
        finally:
            with self._lock:
                self.status.viewers = max(0, self.status.viewers - 1)

    def public_status(self) -> dict[str, object]:
        with self._lock:
            data = self.status.to_public_dict()
            if data.get("status") in {"conectando", "reconectando"} and self._last_jpeg is not None:
                last_frame_at = str(data.get("last_frame_at") or "")
                try:
                    parsed = datetime.fromisoformat(last_frame_at.replace("Z", "+00:00"))
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=timezone.utc)
                    is_recent = (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() <= 5
                except ValueError:
                    is_recent = False
                if is_recent:
                    data["status"] = "online"
                    data["error"] = None
            data["calibration"] = self.calibration_status()
            return data


def calibration_activity_score(frame, polygon: list[dict[str, float]], previous_gray):
    score, current_gray, _diagnostics = machine_activity_score(frame, polygon, previous_gray)
    return score, current_gray


def calibration_stats(samples: list[float]) -> dict[str, object]:
    array = np.array(samples, dtype=float)
    return {
        "samples_count": int(array.size),
        "mean": round(float(np.mean(array)), 4),
        "median": round(float(np.median(array)), 4),
        "std": round(float(np.std(array)), 4),
        "min": round(float(np.min(array)), 4),
        "max": round(float(np.max(array)), 4),
        "p10": round(float(np.percentile(array, 10)), 4),
        "p25": round(float(np.percentile(array, 25)), 4),
        "p75": round(float(np.percentile(array, 75)), 4),
        "p90": round(float(np.percentile(array, 90)), 4),
        "p95": round(float(np.percentile(array, 95)), 4),
    }


def calibration_separation(active: dict[str, object] | None, stopped: dict[str, object] | None) -> dict[str, object]:
    result = machine_calibration_separation(active, stopped)
    if result["result"] == "CALIBRATION_REQUIRED":
        return result
    return result


class LiveStreamManager:
    def __init__(
        self,
        connector_factory: Callable[[CameraSource], UniversalCameraConnector] | None = None,
    ) -> None:
        self.connector_factory = connector_factory
        self._lock = threading.Lock()
        self._streams: dict[str, LiveCameraStream] = {}

    def get_or_create(self, camera_id: str, source: str) -> LiveCameraStream:
        with self._lock:
            stream = self._streams.get(camera_id)
            if stream is None:
                stream = LiveCameraStream(camera_id, source, self.connector_factory)
                self._streams[camera_id] = stream
            return stream

    def get(self, camera_id: str) -> LiveCameraStream | None:
        with self._lock:
            return self._streams.get(camera_id)

    def statuses(self) -> list[dict[str, object]]:
        with self._lock:
            streams = list(self._streams.values())
        return [stream.public_status() for stream in streams]

    def stop(self, camera_id: str) -> bool:
        with self._lock:
            stream = self._streams.pop(camera_id, None)
        if stream is None:
            return False
        stream.stop()
        return True

    def stop_all(self) -> None:
        with self._lock:
            streams = list(self._streams.values())
            self._streams.clear()
        for stream in streams:
            stream.stop()
