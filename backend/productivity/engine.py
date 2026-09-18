from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import hypot
from typing import Any

from backend.vision.models import BoundingBox, TrackedObject


PERSON_CLASSES = {"person"}
PHONE_CLASSES = {"cell phone", "mobile phone", "phone", "smartphone"}
MACHINE_CLASSES = {
    "forklift",
    "truck",
    "car",
    "bus",
    "motorcycle",
    "bicycle",
    "train",
    "boat",
    "airplane",
    "tractor",
    "excavator",
    "crane",
    "loader",
    "bulldozer",
    "machine",
    "industrial machine",
}


@dataclass
class TrackState:
    center: tuple[float, float]
    first_seen: datetime
    last_seen: datetime
    still_since: datetime


@dataclass
class MachineState:
    state: str = "UNKNOWN"
    state_since: datetime | None = None
    evidence_since: datetime | None = None
    absence_since: datetime | None = None
    last_observed_at: datetime | None = None
    last_evidence: str | None = None


class ProductivityEngine:
    def __init__(
        self,
        idle_seconds: float = 30.0,
        still_distance_px: float = 18.0,
        machine_proximity_px: float = 140.0,
        machine_active_seconds: float = 3.0,
        machine_stopped_seconds: float = 20.0,
    ) -> None:
        self.idle_seconds = idle_seconds
        self.still_distance_px = still_distance_px
        self.machine_proximity_px = machine_proximity_px
        self.machine_active_seconds = machine_active_seconds
        self.machine_stopped_seconds = machine_stopped_seconds
        self._tracks: dict[tuple[str, int], TrackState] = {}
        self._machines: dict[str, MachineState] = {}

    def analyze(
        self,
        camera_id: str,
        objects: list[TrackedObject],
        timestamp: datetime,
        *,
        camera_status: str = "ONLINE",
        configured_assets: list[Any] | None = None,
        frame_width: int | None = None,
        frame_height: int | None = None,
    ) -> dict:
        people = [obj for obj in objects if classify_object(obj.class_name) == "person"]
        machine_like = [obj for obj in objects if classify_object(obj.class_name) == "machine"]
        phones = [obj for obj in objects if classify_object(obj.class_name) == "phone"]
        assets = configured_assets or []
        signals: list[dict] = []

        for person in people:
            state = self._update_track(camera_id, person, timestamp)
            idle_for = max(0.0, (timestamp - state.still_since).total_seconds())
            if idle_for >= self.idle_seconds:
                signals.append(
                    {
                        "type": "person_idle",
                        "severity": "attention",
                        "label": "Pessoa parada por tempo prolongado",
                        "track_id": person.track_id,
                        "duration_seconds": round(idle_for, 1),
                        "confidence": person.confidence,
                    }
                )

            if any(_boxes_near(person.bounding_box, phone.bounding_box, 80.0) for phone in phones):
                signals.append(
                    {
                        "type": "possible_phone_use",
                        "severity": "attention",
                        "label": "Possivel uso de celular",
                        "track_id": person.track_id,
                        "confidence": person.confidence,
                    }
                )

            near_machine = [
                machine
                for machine in machine_like
                if _boxes_near(person.bounding_box, machine.bounding_box, self.machine_proximity_px)
            ]
            if near_machine:
                signals.append(
                    {
                        "type": "person_near_machine_like_object",
                        "severity": "info",
                        "label": "Pessoa proxima de objeto reconhecido como maquina/veiculo",
                        "track_id": person.track_id,
                        "machine_track_id": near_machine[0].track_id,
                        "confidence": min(person.confidence, near_machine[0].confidence),
                    }
                )

        for machine in machine_like:
            state = self._update_track(camera_id, machine, timestamp)
            still_for = max(0.0, (timestamp - state.still_since).total_seconds())
            if still_for >= self.idle_seconds:
                signals.append(
                    {
                        "type": "machine_like_object_stationary",
                        "severity": "info",
                        "label": "Objeto tipo maquina/veiculo parado por tempo prolongado",
                        "track_id": machine.track_id,
                        "class_name": machine.class_name,
                        "duration_seconds": round(still_for, 1),
                        "confidence": machine.confidence,
                    }
                )

        active_people = max(0, len(people) - len([s for s in signals if s["type"] == "person_idle"]))
        asset_states = [
            self._update_asset_state(
                camera_id,
                asset,
                objects,
                timestamp,
                camera_status=camera_status,
                frame_width=frame_width,
                frame_height=frame_height,
            )
            for asset in assets
            if getattr(asset, "enabled", True)
        ]

        return {
            "camera_id": camera_id,
            "timestamp": timestamp.isoformat(),
            "score": None,
            "metric_label": "atividade observada",
            "counts": {
                "people": len(people),
                "active_people": active_people,
                "idle_people": len([s for s in signals if s["type"] == "person_idle"]),
                "machines": len(asset_states) if asset_states else len(machine_like),
                "detected_machine_like_objects": len(machine_like),
                "phones": len(phones),
            },
            "signals": signals,
            "machines": [
                machine.as_dict() | {"category": "detected_machine_like_object"}
                for machine in machine_like
            ],
            "assets": asset_states,
            "people": [person.as_dict() | {"category": "person"} for person in people],
            "limitations": [
                "Maquinas cadastradas sao avaliadas por ROI e evidencias temporais, nao pela classe generica do detector.",
                "Esta tela mostra atividade observada; produtividade real exige integracao com producao, metas ou contadores.",
            ],
        }

    def reset(self, camera_id: str | None = None) -> None:
        if camera_id is None:
            self._tracks.clear()
            self._machines.clear()
            return
        for key in list(self._tracks):
            if key[0] == camera_id:
                self._tracks.pop(key, None)
        for key in list(self._machines):
            if key.startswith(f"{camera_id}:"):
                self._machines.pop(key, None)

    def _update_track(self, camera_id: str, obj: TrackedObject, timestamp: datetime) -> TrackState:
        key = (camera_id, obj.track_id)
        center = _center(obj.bounding_box)
        previous = self._tracks.get(key)
        if previous is None:
            state = TrackState(center, timestamp, timestamp, timestamp)
            self._tracks[key] = state
            return state

        moved = hypot(center[0] - previous.center[0], center[1] - previous.center[1])
        still_since = previous.still_since if moved <= self.still_distance_px else timestamp
        state = TrackState(center, previous.first_seen, timestamp, still_since)
        self._tracks[key] = state
        return state

    def _update_asset_state(
        self,
        camera_id: str,
        asset: Any,
        objects: list[TrackedObject],
        timestamp: datetime,
        *,
        camera_status: str,
        frame_width: int | None,
        frame_height: int | None,
    ) -> dict:
        key = f"{camera_id}:{asset.id}"
        state = self._machines.setdefault(key, MachineState(state_since=timestamp))
        if camera_status == "OFFLINE":
            self._transition_machine(state, "UNKNOWN", timestamp, "camera_offline")
            return _asset_payload(asset, state, timestamp)

        evidence_objects = [
            obj
            for obj in objects
            if classify_object(obj.class_name) not in {"person", "phone"}
            and _object_inside_asset(obj, asset, frame_width, frame_height)
        ]
        if evidence_objects:
            state.last_observed_at = timestamp
            state.last_evidence = ",".join(sorted({obj.class_name for obj in evidence_objects}))
            state.absence_since = None
            state.evidence_since = state.evidence_since or timestamp
            if (timestamp - state.evidence_since).total_seconds() >= self.machine_active_seconds:
                self._transition_machine(state, "ACTIVE", timestamp, "activity_evidence")
        else:
            state.evidence_since = None
            state.absence_since = state.absence_since or timestamp
            if state.state == "ACTIVE":
                if (timestamp - state.absence_since).total_seconds() >= self.machine_stopped_seconds:
                    self._transition_machine(state, "STOPPED", timestamp, "absence_after_active")
            elif (timestamp - state.absence_since).total_seconds() >= self.machine_stopped_seconds:
                self._transition_machine(state, "STOPPED", timestamp, "consistent_absence")

        return _asset_payload(asset, state, timestamp)

    def _transition_machine(
        self,
        state: MachineState,
        new_state: str,
        timestamp: datetime,
        reason: str,
    ) -> None:
        if state.state == new_state:
            return
        state.state = new_state
        state.state_since = timestamp
        state.last_evidence = reason


def classify_object(class_name: str) -> str:
    normalized = class_name.strip().lower().replace("_", " ")
    if normalized in PERSON_CLASSES:
        return "person"
    if normalized in PHONE_CLASSES:
        return "phone"
    if normalized in MACHINE_CLASSES:
        return "machine"
    return "object"


def _center(box: BoundingBox) -> tuple[float, float]:
    return ((box.x1 + box.x2) / 2, (box.y1 + box.y2) / 2)


def _boxes_near(first: BoundingBox, second: BoundingBox, max_distance: float) -> bool:
    a = _center(first)
    b = _center(second)
    return hypot(a[0] - b[0], a[1] - b[1]) <= max_distance


def _object_inside_asset(
    obj: TrackedObject,
    asset: Any,
    frame_width: int | None,
    frame_height: int | None,
) -> bool:
    cx, cy = _center(obj.bounding_box)
    if frame_width and frame_height:
        cx /= frame_width
        cy /= frame_height
    return _point_in_polygon(cx, cy, getattr(asset, "points", []))


def _point_in_polygon(x: float, y: float, points: list[Any]) -> bool:
    if len(points) < 3:
        return False
    inside = False
    previous = points[-1]
    for current in points:
        previous_x, previous_y = float(previous.x), float(previous.y)
        current_x, current_y = float(current.x), float(current.y)
        crosses = (current_y > y) != (previous_y > y)
        if crosses:
            intersection_x = (
                (previous_x - current_x)
                * (y - current_y)
                / (previous_y - current_y)
                + current_x
            )
            if x < intersection_x:
                inside = not inside
        previous = current
    return inside


def _asset_payload(asset: Any, state: MachineState, timestamp: datetime) -> dict:
    state_since = state.state_since or timestamp
    return {
        "asset_id": asset.id,
        "machine_id": asset.id,
        "name": asset.name,
        "type": asset.type,
        "state": state.state,
        "state_since": state_since.isoformat(),
        "state_age_seconds": round(max(0.0, (timestamp - state_since).total_seconds()), 3),
        "last_observed_at": state.last_observed_at.isoformat() if state.last_observed_at else None,
        "last_evidence": state.last_evidence,
    }
