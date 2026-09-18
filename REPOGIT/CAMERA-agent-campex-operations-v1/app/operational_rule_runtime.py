from __future__ import annotations

import time
from collections import Counter
from typing import Any

import numpy as np

from app.database import connect, init_db
from app.models import listar_regras
from app.person_detection import Detection
from app.restricted_area import AreaPresence
from app.visual_rule_engine import evaluate_rule
from shared.schemas import now_iso


VEHICLE_CLASSES = {"car", "truck", "bus", "motorcycle", "vehicle"}


def facts_from_stream(
    camera_id: str,
    camera_status: str,
    detections: list[Detection] | None = None,
    area_presence: AreaPresence | None = None,
    machine_state: str | None = None,
    machine_motion: float | None = None,
    operator_present: bool | None = None,
    operator_people_count: int | None = None,
    fps: float | None = None,
    confidence: float | None = None,
) -> dict[str, Any]:
    detections = detections or []
    class_counts = Counter(detection.class_name for detection in detections)
    people_count = int(class_counts.get("person", len([d for d in detections if d.class_name == "person"])))
    zone_counts: dict[str, int] = {}
    zone_ids: dict[str, list[int]] = {}
    if area_presence and area_presence.area_id:
        zone_counts[area_presence.area_id] = int(area_presence.pessoas_dentro or 0)
        zone_counts["restricted_area"] = int(area_presence.pessoas_dentro or 0)
        zone_ids[area_presence.area_id] = list(area_presence.ids_dentro or [])
    if operator_people_count is not None:
        zone_counts["operator"] = int(operator_people_count)
    elif operator_present is not None:
        zone_counts["operator"] = 1 if operator_present else 0
    return {
        "camera_id": camera_id,
        "camera_status": "online" if camera_status == "online" else "offline",
        "people_count": people_count,
        "class_counts": dict(class_counts),
        "vehicle_count": sum(class_counts.get(name, 0) for name in VEHICLE_CLASSES),
        "zone_counts": zone_counts,
        "zone_track_ids": zone_ids,
        "machine_state": machine_state,
        "operator_present": operator_present,
        "operator_people_count": operator_people_count,
        "motion_score": machine_motion,
        "activity_score": machine_motion,
        "fps": fps,
        "confidence": confidence if confidence is not None else max([d.confidence for d in detections], default=None),
    }


class OperationalRuleRuntime:
    def __init__(self, camera_id: str, evaluation_interval_seconds: float = 1.0) -> None:
        self.camera_id = camera_id
        self.evaluation_interval_seconds = evaluation_interval_seconds
        self._last_rule_load = 0.0
        self._last_evaluation = 0.0
        self._rules: list[dict[str, Any]] = []

    def _load_rules(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        if self._rules and now - self._last_rule_load < 2.0:
            return self._rules
        self._last_rule_load = now
        try:
            with connect() as connection:
                init_db(connection)
                self._rules = [rule for rule in listar_regras(connection, camera_id=self.camera_id) if rule.get("ativo")]
        except Exception:
            self._rules = []
        return self._rules

    def evaluate(self, facts: dict[str, Any], frame: np.ndarray | None = None, force: bool = False) -> list[dict[str, Any]]:
        now = time.monotonic()
        if not force and now - self._last_evaluation < self.evaluation_interval_seconds:
            return []
        self._last_evaluation = now
        results: list[dict[str, Any]] = []
        rules = self._load_rules()
        if not rules:
            return results
        at = now_iso()
        with connect() as connection:
            init_db(connection)
            for rule in rules:
                try:
                    results.append(evaluate_rule(connection, rule["id"], facts, frame=frame, at=at))
                except Exception as exc:
                    results.append({"rule_id": rule.get("id"), "matched": False, "action": "error", "error": str(exc)[:200]})
        return results

    def camera_status(self, status: str, frame: np.ndarray | None = None) -> list[dict[str, Any]]:
        # Camera availability is technical telemetry, not a canonical operational event.
        # Readiness/coverage consume camera status through samples, health and stream status.
        return []
