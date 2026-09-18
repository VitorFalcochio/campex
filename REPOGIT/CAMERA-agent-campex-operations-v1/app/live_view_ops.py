from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

from app.person_detection import Detection
from app.restricted_area import AreaPoint, foot_point_normalized, normalize_points, point_in_polygon


@dataclass
class LiveViewMachineConfig:
    nome: str = "Máquina"
    tipo: str | None = None
    machine_polygon: list[AreaPoint] = field(default_factory=list)
    operator_polygon: list[AreaPoint] = field(default_factory=list)
    threshold: float | None = None
    calibrated: bool = False


@dataclass
class LiveViewOpsState:
    ai_enabled: bool = False
    ai_status: str = "inativa"
    people_count: int = 0
    inference_fps: float = 0.0
    last_error: str | None = None
    machine_state: str = "NAO_CONFIGURADA"
    machine_motion: float = 0.0
    machine_threshold: float | None = None
    operator_present: bool = False
    operator_people_count: int = 0
    relation: str = "Aguardando configuração"
    visual_confidence: float = 0.0
    calibration_status: str = "não calibrada"


class LiveViewOpsEngine:
    """Compatibility renderer for older imports.

    Operational decisions moved to MachineMonitorEngine, ObservationEngine and
    PeopleZonesEngine. This class intentionally keeps only lightweight display
    state so legacy callers can draw overlays without creating a second runtime.
    """

    def __init__(self) -> None:
        self.config: LiveViewMachineConfig | None = None
        self.state = LiveViewOpsState()
        self._last_inference_tick = time.monotonic()
        self._inference_frames = 0

    def set_ai(self, enabled: bool) -> dict[str, Any]:
        self.state.ai_enabled = enabled
        self.state.ai_status = "ativa" if enabled else "inativa"
        if not enabled:
            self.state.people_count = 0
            self.state.inference_fps = 0.0
        return self.public_state()

    def configure_machine(
        self,
        nome: str,
        machine_polygon: list[dict[str, float]],
        operator_polygon: list[dict[str, float]] | None = None,
        tipo: str | None = None,
    ) -> dict[str, Any]:
        machine_points = [AreaPoint(float(p["x"]), float(p["y"])) for p in normalize_points(machine_polygon)]
        operator_source = operator_polygon or expanded_polygon(machine_polygon, margin=0.08)
        operator_points = [AreaPoint(float(p["x"]), float(p["y"])) for p in normalize_points(operator_source)]
        self.config = LiveViewMachineConfig(nome=nome, tipo=tipo, machine_polygon=machine_points, operator_polygon=operator_points)
        self.state.machine_state = "UNKNOWN"
        self.state.relation = "Runtime oficial aguardando MachineMonitorEngine"
        self.state.calibration_status = "use_assisted_calibration_endpoint"
        return self.public_state()

    def load_machine_config(self, monitor: dict[str, Any]) -> dict[str, Any]:
        machine_points = [AreaPoint(float(p["x"]), float(p["y"])) for p in normalize_points(monitor.get("machine_polygon") or [])]
        operator_points = [AreaPoint(float(p["x"]), float(p["y"])) for p in normalize_points(monitor.get("operator_polygon") or [])]
        self.config = LiveViewMachineConfig(
            nome=str(monitor.get("nome") or "Máquina"),
            tipo=monitor.get("tipo"),
            machine_polygon=machine_points,
            operator_polygon=operator_points,
            threshold=monitor.get("motion_threshold"),
            calibrated=monitor.get("calibration_status") == "calibrated" or monitor.get("motion_threshold") is not None,
        )
        self.state.machine_threshold = self.config.threshold
        self.state.calibration_status = "use_assisted_calibration_endpoint"
        self.state.machine_state = "UNKNOWN"
        self.state.relation = "Runtime oficial aguardando MachineMonitorEngine"
        return self.public_state()

    def configure_operator_zone(self, operator_polygon: list[dict[str, float]]) -> dict[str, Any]:
        if self.config is None:
            raise ValueError("Configure a máquina antes da zona do operador.")
        self.config.operator_polygon = [AreaPoint(float(p["x"]), float(p["y"])) for p in normalize_points(operator_polygon)]
        return self.public_state()

    def clear(self) -> dict[str, Any]:
        self.config = None
        self.state = LiveViewOpsState(ai_enabled=self.state.ai_enabled, ai_status=self.state.ai_status)
        return self.public_state()

    def calibrate_active(self, current_motion: float | None = None) -> dict[str, Any]:
        if self.config is None:
            raise ValueError("Configure uma máquina antes de calibrar.")
        self.state.calibration_status = "use_assisted_calibration_endpoint"
        self.state.relation = "Use o endpoint assistido de MachineMonitorEngine"
        return self.public_state()

    def update(self, frame: np.ndarray, detections: list[Detection]) -> np.ndarray:
        if self.state.ai_enabled:
            self._inference_frames += 1
            elapsed = max(0.001, time.monotonic() - self._last_inference_tick)
            self.state.inference_fps = round(self._inference_frames / elapsed, 2)
        self.state.people_count = len([detection for detection in detections if detection.class_name == "person"])
        if self.config is None:
            self.state.machine_state = "NAO_CONFIGURADA"
            self.state.relation = "Aguardando configuração persistente"
        else:
            self.state.machine_state = "UNKNOWN"
            self.state.operator_present = False
            self.state.operator_people_count = 0
            self.state.visual_confidence = 0.0
            self.state.relation = "Runtime oficial aguardando MachineMonitorEngine"
        return draw_live_view_overlay(frame, self.config, self.state, detections)

    def public_state(self) -> dict[str, Any]:
        return {
            **self.state.__dict__,
            "machine": machine_to_dict(self.config),
        }


def motion_inside_polygon(frame: np.ndarray, polygon: list[AreaPoint], previous_gray: np.ndarray | None) -> float:
    gray = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    if previous_gray is None:
        return 0.0
    mask = polygon_mask(gray.shape, polygon)
    diff = cv2.absdiff(gray, previous_gray)
    values = diff[mask > 0]
    return float(np.mean(values)) if values.size else 0.0


def polygon_mask(shape: tuple[int, int], polygon: list[AreaPoint]) -> np.ndarray:
    height, width = shape
    mask = np.zeros((height, width), dtype=np.uint8)
    points = np.array([[int(point.x * width), int(point.y * height)] for point in polygon], dtype=np.int32)
    cv2.fillPoly(mask, [points], 255)
    return mask


def expanded_polygon(points: list[dict[str, float]], margin: float) -> list[dict[str, float]]:
    xs = [float(p["x"]) for p in points]
    ys = [float(p["y"]) for p in points]
    return [
        {"x": max(0.0, min(xs) - margin), "y": max(0.0, min(ys) - margin)},
        {"x": min(1.0, max(xs) + margin), "y": max(0.0, min(ys) - margin)},
        {"x": min(1.0, max(xs) + margin), "y": min(1.0, max(ys) + margin)},
        {"x": max(0.0, min(xs) - margin), "y": min(1.0, max(ys) + margin)},
    ]


def draw_live_view_overlay(
    frame: np.ndarray,
    config: LiveViewMachineConfig | None,
    state: LiveViewOpsState,
    detections: list[Detection],
) -> np.ndarray:
    annotated = frame.copy()
    height, width = annotated.shape[:2]
    for detection in detections:
        cv2.rectangle(annotated, (detection.x1, detection.y1), (detection.x2, detection.y2), (0, 255, 0), 2)
        label = f"{detection.class_name} {detection.confidence:.2f}"
        cv2.putText(annotated, label, (detection.x1, max(18, detection.y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2, cv2.LINE_AA)
    if config is not None:
        draw_polygon(annotated, config.machine_polygon, (255, 180, 0))
        draw_polygon(annotated, config.operator_polygon, (0, 220, 255))
        label = f"{config.nome}: Estado estimado: {state.machine_state}"
        cv2.putText(annotated, label, (16, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 4, cv2.LINE_AA)
        cv2.putText(annotated, label, (16, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 0), 2, cv2.LINE_AA)
    return annotated


def draw_polygon(frame: np.ndarray, polygon: list[AreaPoint], color: tuple[int, int, int]) -> None:
    if len(polygon) < 3:
        return
    height, width = frame.shape[:2]
    points = np.array([[int(point.x * width), int(point.y * height)] for point in polygon], dtype=np.int32)
    cv2.polylines(frame, [points], True, color, 3)


def machine_to_dict(config: LiveViewMachineConfig | None) -> dict[str, Any] | None:
    if config is None:
        return None
    return {
        "nome": config.nome,
        "tipo": config.tipo,
        "machine_polygon": [{"x": p.x, "y": p.y} for p in config.machine_polygon],
        "operator_polygon": [{"x": p.x, "y": p.y} for p in config.operator_polygon],
        "threshold": config.threshold,
        "calibrated": config.calibrated,
    }
