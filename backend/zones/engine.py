from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from backend.vision.models import TrackedObject
from backend.zones.models import Observation, Zone, ZonePoint

logger = logging.getLogger("campex.zones.engine")

DISAPPEARED_EXIT_FRAME_THRESHOLD = 3


def _point_in_polygon(
    x: float, y: float, polygon: list[ZonePoint]
) -> bool:
    """Ray-casting point-in-polygon test.

    Works on normalized coordinates (0.0–1.0) so it is resolution-independent.
    """
    n = len(polygon)
    if n < 3:
        return False
    inside = False
    previous = polygon[-1]
    for current in polygon:
        if _point_on_segment(x, y, previous, current):
            return True
        crosses = (current.y > y) != (previous.y > y)
        if crosses:
            intersection_x = (
                (previous.x - current.x)
                * (y - current.y)
                / (previous.y - current.y)
                + current.x
            )
            if x < intersection_x:
                inside = not inside
        previous = current
    return inside


def _point_on_segment(
    x: float,
    y: float,
    first: ZonePoint,
    second: ZonePoint,
    epsilon: float = 1e-9,
) -> bool:
    cross = (x - first.x) * (second.y - first.y) - (
        y - first.y
    ) * (second.x - first.x)
    if abs(cross) > epsilon:
        return False
    return (
        min(first.x, second.x) - epsilon <= x <= max(first.x, second.x) + epsilon
        and min(first.y, second.y) - epsilon
        <= y
        <= max(first.y, second.y) + epsilon
    )


def _bottom_center_normalized(
    bbox_x1: float,
    bbox_y1: float,
    bbox_x2: float,
    bbox_y2: float,
    frame_width: int,
    frame_height: int,
) -> tuple[float, float] | None:
    """Convert bottom-center of a bounding box to normalized (0–1) coordinates."""
    if frame_width <= 0 or frame_height <= 0:
        return None
    cx = ((bbox_x1 + bbox_x2) / 2.0) / frame_width
    cy = bbox_y2 / frame_height
    return (cx, cy)


@dataclass
class ZonePresence:
    """Snapshot of which zones a single track is inside."""

    track_id: int
    zone_ids: set[str]
    knowledge_state: str = "OBSERVED"


class SpatialEngine:
    """Spatial Engine — evaluates tracked objects against configured zones.

    Maintains per-camera zone membership state and emits structured Observations
    for zone entry, zone exit, and ongoing presence.

    Architecture:
        TrackedObjects
        → normalize bottom-center bbox point to (0–1)
        → point-in-polygon against each zone
        → diff against previous membership
        → emit Observations (entered / exited / presence)
    """

    def __init__(self) -> None:
        self._zones_by_camera: dict[str, list[Zone]] = {}
        # camera_id → {track_id → set(zone_id)}
        self._membership: dict[str, dict[int, set[str]]] = {}
        # camera_id → {track_id → last TrackedObject (for timestamp/confidence on exit)
        self._last_objects: dict[str, dict[int, TrackedObject]] = {}
        # camera_id → {track_id → consecutive frames absent while still considered present}
        self._missing_counts: dict[str, dict[int, int]] = {}

    def update_zones(self, camera_id: str, zones: list[Zone]) -> None:
        """Replace all zones for a camera and prune stale membership."""
        active_zones = [z for z in zones if z.enabled]
        self._zones_by_camera[camera_id] = active_zones

        # Prune membership for removed zones
        if camera_id in self._membership:
            valid_zone_ids = {z.id for z in active_zones}
            for track_id, zone_ids in self._membership[camera_id].items():
                zone_ids.intersection_update(valid_zone_ids)

    def get_zones(self, camera_id: str) -> list[Zone]:
        return list(self._zones_by_camera.get(camera_id, []))

    def evaluate(
        self,
        camera_id: str,
        objects: list[TrackedObject],
        frame_width: int,
        frame_height: int,
    ) -> tuple[list[Observation], list[ZonePresence]]:
        """Evaluate zone membership for tracked objects.

        Returns:
            Tuple of (observations, current_zone_presence) where observations
            include zone entry/exit events and current_zone_presence reflects
            which tracks are in which zones after evaluation.
        """
        zones = self._zones_by_camera.get(camera_id, [])
        observations: list[Observation] = []
        current_presence: dict[int, set[str]] = {
            track_id: set(zone_ids)
            for track_id, zone_ids in self._membership.get(camera_id, {}).items()
        }

        if not zones:
            return observations, []

        prev_membership = self._membership.get(camera_id, {})
        missing_counts = self._missing_counts.setdefault(camera_id, {})
        observed_track_ids: set[int] = set()

        # Process each tracked object
        for obj in objects:
            if obj.class_name.lower() != "person":
                continue
            observed_track_ids.add(obj.track_id)
            missing_counts.pop(obj.track_id, None)
            point = _bottom_center_normalized(
                obj.bounding_box.x1,
                obj.bounding_box.y1,
                obj.bounding_box.x2,
                obj.bounding_box.y2,
                frame_width,
                frame_height,
            )
            if point is None:
                continue

            px, py = point
            in_zones: set[str] = set()
            for zone in zones:
                if _point_in_polygon(px, py, zone.points):
                    in_zones.add(zone.id)

            if in_zones:
                current_presence[obj.track_id] = in_zones
            else:
                current_presence.pop(obj.track_id, None)

            prev_zones = prev_membership.get(obj.track_id, set())

            # Detect zone entries
            entered = in_zones - prev_zones
            for zone_id in entered:
                zone = next(z for z in zones if z.id == zone_id)
                observations.append(
                    Observation(
                        type="person_entered_zone",
                        camera_id=camera_id,
                        track_id=obj.track_id,
                        zone_id=zone_id,
                        state="present",
                        confidence=obj.confidence,
                        timestamp=obj.timestamp,
                    )
                )
                logger.debug(
                    "Person entered zone",
                    extra={
                        "camera_id": camera_id,
                        "track_id": obj.track_id,
                        "zone_id": zone_id,
                        "zone_name": zone.name,
                        "zone_type": zone.type,
                    },
                )

            # Detect zone exits
            exited = prev_zones - in_zones
            for zone_id in exited:
                zone = next(z for z in zones if z.id == zone_id)
                observations.append(
                    Observation(
                        type="person_exited_zone",
                        camera_id=camera_id,
                        track_id=obj.track_id,
                        zone_id=zone_id,
                        state="absent",
                        confidence=obj.confidence,
                        timestamp=obj.timestamp,
                    )
                )
                logger.debug(
                    "Person exited zone",
                    extra={
                        "camera_id": camera_id,
                        "track_id": obj.track_id,
                        "zone_id": zone_id,
                        "zone_name": zone.name,
                        "zone_type": zone.type,
                    },
                )

            # Emit presence observation if still inside a zone
            for zone_id in sorted(in_zones):
                observations.append(
                    Observation(
                        type="person_presence",
                        camera_id=camera_id,
                        track_id=obj.track_id,
                        zone_id=zone_id,
                        state="present",
                        confidence=obj.confidence,
                        timestamp=obj.timestamp,
                    )
                )

        # Detect tracks that disappeared (no longer visible this frame).
        # Short detector/tracker gaps are tolerated so a single missed frame
        # does not close and immediately recreate zone events.
        disappeared_tracks = set(prev_membership.keys()) - observed_track_ids
        prev_last_objects = self._last_objects.get(camera_id, {})
        for track_id in disappeared_tracks:
            missing_counts[track_id] = missing_counts.get(track_id, 0) + 1
            if missing_counts[track_id] < DISAPPEARED_EXIT_FRAME_THRESHOLD:
                continue
            prev_zones = prev_membership.get(track_id, set())
            last_obj = prev_last_objects.get(track_id)
            for zone_id in prev_zones:
                zone = next((z for z in zones if z.id == zone_id), None)
                if zone is None:
                    continue
                observations.append(
                    Observation(
                        type="person_exited_zone",
                        camera_id=camera_id,
                        track_id=track_id,
                        zone_id=zone_id,
                        state="absent",
                        confidence=last_obj.confidence if last_obj else 0.0,
                        timestamp=last_obj.timestamp if last_obj else datetime.now(timezone.utc),
                    )
                )
                logger.debug(
                    "Person exited zone (track disappeared)",
                    extra={
                        "camera_id": camera_id,
                        "track_id": track_id,
                        "zone_id": zone_id,
                        "zone_name": zone.name,
                        "zone_type": zone.type,
                    },
                )
            current_presence.pop(track_id, None)
            missing_counts.pop(track_id, None)

        # Update last-seen objects for visible tracks; prune disappeared tracks.
        updated_last_objects: dict[int, TrackedObject] = {}
        for obj in objects:
            if obj.class_name.lower() == "person":
                updated_last_objects[obj.track_id] = obj
        for track_id, last_obj in prev_last_objects.items():
            if track_id in current_presence and track_id not in updated_last_objects:
                updated_last_objects[track_id] = last_obj
        self._last_objects[camera_id] = updated_last_objects

        # Update membership state
        self._membership[camera_id] = current_presence
        presence_list = [
            ZonePresence(
                track_id=tid,
                zone_ids=zids,
                knowledge_state=(
                    "OBSERVED" if tid in observed_track_ids else "UNKNOWN"
                ),
            )
            for tid, zids in current_presence.items()
        ]
        return observations, presence_list

    def get_presence(self, camera_id: str) -> list[ZonePresence]:
        """Return current zone presence for all active tracks."""
        membership = self._membership.get(camera_id, {})
        return [
            ZonePresence(track_id=tid, zone_ids=set(zids))
            for tid, zids in membership.items()
        ]

    def reset(self, camera_id: str | None = None) -> None:
        if camera_id is None:
            self._membership.clear()
            self._last_objects.clear()
            self._missing_counts.clear()
        else:
            self._membership.pop(camera_id, None)
            self._last_objects.pop(camera_id, None)
            self._missing_counts.pop(camera_id, None)

    @staticmethod
    def point_in_polygon(x: float, y: float, points: list[ZonePoint]) -> bool:
        """Public static method for tests and external use."""
        return _point_in_polygon(x, y, points)
