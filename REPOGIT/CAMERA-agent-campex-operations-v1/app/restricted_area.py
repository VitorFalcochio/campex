from __future__ import annotations

import time
from dataclasses import dataclass

import cv2
import numpy as np

from app.person_detection import Detection


@dataclass(frozen=True)
class AreaPoint:
    x: float
    y: float


@dataclass(frozen=True)
class RestrictedArea:
    id: str
    camera_id: str
    nome: str
    pontos: list[AreaPoint]
    ativa: bool = True


@dataclass
class AreaPresence:
    area_id: str | None = None
    area_nome: str | None = None
    estado: str = "livre"
    pessoas_dentro: int = 0
    ids_dentro: list[int] | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "area_id": self.area_id,
            "area_nome": self.area_nome,
            "estado": self.estado,
            "pessoas_dentro": self.pessoas_dentro,
            "ids_dentro": self.ids_dentro or [],
        }


class AreaPresenceTracker:
    def __init__(self, enter_frames: int = 2, exit_frames: int = 3, exit_grace_seconds: float = 2.0) -> None:
        self.enter_frames = enter_frames
        self.exit_frames = exit_frames
        self.exit_grace_seconds = exit_grace_seconds
        self._inside_counts: dict[int, int] = {}
        self._outside_counts: dict[int, int] = {}
        self._last_inside_at: dict[int, float] = {}
        self._stable_inside: set[int] = set()

    def update(self, raw_inside_ids: set[int], visible_ids: set[int], now: float | None = None) -> set[int]:
        now = time.monotonic() if now is None else now
        for track_id in visible_ids:
            if track_id in raw_inside_ids:
                self._inside_counts[track_id] = self._inside_counts.get(track_id, 0) + 1
                self._outside_counts[track_id] = 0
                self._last_inside_at[track_id] = now
                if self._inside_counts[track_id] >= self.enter_frames:
                    self._stable_inside.add(track_id)
            else:
                self._outside_counts[track_id] = self._outside_counts.get(track_id, 0) + 1
                self._inside_counts[track_id] = 0
                if self._outside_counts[track_id] >= self.exit_frames and now - self._last_inside_at.get(track_id, 0.0) > self.exit_grace_seconds:
                    self._stable_inside.discard(track_id)

        missing = set(self._inside_counts) - visible_ids
        for track_id in missing:
            self._outside_counts[track_id] = self._outside_counts.get(track_id, 0) + 1
            if self._outside_counts[track_id] >= self.exit_frames and now - self._last_inside_at.get(track_id, 0.0) > self.exit_grace_seconds:
                self._stable_inside.discard(track_id)
                self._inside_counts.pop(track_id, None)
                self._outside_counts.pop(track_id, None)
                self._last_inside_at.pop(track_id, None)
        return set(self._stable_inside)


def normalize_points(points: list[dict[str, float]]) -> list[dict[str, float]]:
    normalized: list[dict[str, float]] = []
    for point in points:
        x = min(1.0, max(0.0, float(point["x"])))
        y = min(1.0, max(0.0, float(point["y"])))
        normalized.append({"x": x, "y": y})
    if len(normalized) < 3:
        raise ValueError("A area precisa de pelo menos 3 pontos.")
    return normalized


def area_from_dict(payload: dict[str, object]) -> RestrictedArea:
    return RestrictedArea(
        id=str(payload["id"]),
        camera_id=str(payload["camera_id"]),
        nome=str(payload["nome"]),
        pontos=[AreaPoint(float(point["x"]), float(point["y"])) for point in payload["pontos"]],  # type: ignore[index]
        ativa=bool(payload.get("ativa", True)),
    )


def point_in_polygon(point: tuple[float, float], polygon: list[AreaPoint]) -> bool:
    x, y = point
    inside = False
    j = len(polygon) - 1
    for i, current in enumerate(polygon):
        previous = polygon[j]
        intersects = ((current.y > y) != (previous.y > y)) and (
            x < (previous.x - current.x) * (y - current.y) / ((previous.y - current.y) or 1e-9) + current.x
        )
        if intersects:
            inside = not inside
        j = i
    return inside


def foot_point_normalized(detection: Detection, width: int, height: int) -> tuple[float, float]:
    x = ((detection.x1 + detection.x2) / 2.0) / max(1, width)
    y = float(detection.y2) / max(1, height)
    return min(1.0, max(0.0, x)), min(1.0, max(0.0, y))


def evaluate_area(
    area: RestrictedArea | None,
    detections: list[Detection],
    width: int,
    height: int,
    tracker: AreaPresenceTracker,
) -> tuple[AreaPresence, set[int]]:
    if area is None or not area.ativa:
        return AreaPresence(), set()
    raw_inside: set[int] = set()
    visible: set[int] = set()
    for detection in detections:
        if detection.class_name != "person":
            continue
        if detection.track_id is None:
            continue
        visible.add(detection.track_id)
        if point_in_polygon(foot_point_normalized(detection, width, height), area.pontos):
            raw_inside.add(detection.track_id)
    stable_inside = tracker.update(raw_inside, visible)
    return (
        AreaPresence(
            area_id=area.id,
            area_nome=area.nome,
            estado="ocupada" if stable_inside else "livre",
            pessoas_dentro=len(stable_inside),
            ids_dentro=sorted(stable_inside),
        ),
        stable_inside,
    )


def draw_area_overlay(
    frame: np.ndarray,
    area: RestrictedArea | None,
    presence: AreaPresence,
    inside_ids: set[int],
    detections: list[Detection],
) -> np.ndarray:
    annotated = frame.copy()
    height, width = annotated.shape[:2]
    if area is not None and area.ativa:
        pts = np.array(
            [[int(point.x * width), int(point.y * height)] for point in area.pontos],
            dtype=np.int32,
        )
        color = (0, 0, 255) if presence.estado == "ocupada" else (0, 180, 0)
        cv2.polylines(annotated, [pts], isClosed=True, color=color, thickness=3)
        label = f"{area.nome}: {'Ocupada' if presence.estado == 'ocupada' else 'Livre'}"
        x, y = pts[0]
        cv2.putText(annotated, label, (x, max(24, y - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2, cv2.LINE_AA)

    for detection in detections:
        inside = detection.track_id in inside_ids if detection.track_id is not None else False
        color = (0, 0, 255) if inside else (0, 255, 0)
        cv2.rectangle(annotated, (detection.x1, detection.y1), (detection.x2, detection.y2), color, 2)
        label_id = detection.track_id if detection.track_id is not None else "-"
        label = f"person #{label_id} {detection.confidence:.2f}"
        cv2.putText(
            annotated,
            label,
            (detection.x1, max(20, detection.y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            2,
            cv2.LINE_AA,
        )
    return annotated
