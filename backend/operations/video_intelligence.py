from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from backend.config import Settings
from backend.vision.models import TrackedObject
from backend.zones.engine import SpatialEngine
from backend.zones.models import Zone


MOVING = "MOVING"
STATIONARY = "STATIONARY"
UNKNOWN = "UNKNOWN"


@dataclass
class TrackRuntime:
    track_id: int
    first_seen: datetime
    last_seen: datetime
    confidence: float
    zone_id: str | None = None
    movement_state: str = UNKNOWN
    stationary_since: datetime | None = None
    moving_seconds: float = 0.0
    stationary_seconds: float = 0.0
    positions: deque[tuple[datetime, float, float]] = field(default_factory=lambda: deque(maxlen=30))
    open_stationary_event_id: str | None = None
    long_presence_emitted: bool = False
    entered_counted: bool = False
    exited_counted: bool = False
    last_line_event_at: datetime | None = None
    potential_stationary_since: datetime | None = None
    stationary_accounted_until: datetime | None = None


class CampexOperationalEngine:
    """Transforms tracked people into CAMPEX operational facts.

    The engine receives computer-vision output only. It does not inspect frames,
    classify productivity, identify people, or infer intent.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        camera_id: str,
        zones: list[Zone] | None = None,
        frame_width: int = 1,
        frame_height: int = 1,
    ) -> None:
        self.settings = settings
        self.camera_id = camera_id
        self.frame_width = max(1, frame_width)
        self.frame_height = max(1, frame_height)
        self.zones = [zone for zone in zones or [] if zone.enabled]
        self.spatial = SpatialEngine()
        self.spatial.update_zones(camera_id, self.zones)
        self.tracks: dict[int, TrackRuntime] = {}
        self.events: list[dict[str, Any]] = []
        self.timeline: list[dict[str, Any]] = []
        self.people_visible = 0
        self.max_simultaneous = 0
        self.entries = 0
        self.exits = 0
        self._previous_visible: set[int] = set()
        self._zone_counts: dict[str, int] = defaultdict(int)
        self._zone_peak: dict[str, int] = defaultdict(int)
        self._zone_entries: dict[str, int] = defaultdict(int)
        self._zone_exits: dict[str, int] = defaultdict(int)
        self._zone_stays: dict[str, list[float]] = defaultdict(list)
        self._zone_membership_started: dict[tuple[int, str], datetime] = {}
        self._zone_last_activity: dict[str, datetime] = {}
        self._zone_idle_event: dict[str, str] = {}
        self._crowding_event: dict[str, str] = {}
        self._crowding_peak: dict[str, int] = defaultdict(int)

    def process(self, objects: list[TrackedObject], timestamp: datetime) -> None:
        people = [obj for obj in objects if obj.class_name.lower() == "person"]
        visible_ids = {obj.track_id for obj in people}
        self.people_visible = len(visible_ids)
        self.max_simultaneous = max(self.max_simultaneous, self.people_visible)

        for obj in people:
            self._process_track(obj, timestamp)

        for track_id in sorted(self._previous_visible - visible_ids):
            self._close_track_visibility(track_id, timestamp)
        self._previous_visible = visible_ids

        self._process_zones(people, timestamp)
        self._update_zone_aggregate_events(timestamp)

    def close(self, timestamp: datetime) -> None:
        for track_id in list(self._previous_visible):
            self._close_track_visibility(track_id, timestamp)
        for event_id in list(self._zone_idle_event.values()):
            self._close_event(event_id, timestamp)
        for event_id in list(self._crowding_event.values()):
            self._close_event(event_id, timestamp)
        self._previous_visible.clear()

    def as_result(self, source: dict[str, Any] | None = None) -> dict[str, Any]:
        tracks = [self._track_as_dict(track) for track in self.tracks.values()]
        metrics = self.metrics(source or {})
        return {
            "events": self.events,
            "tracks": tracks,
            "metrics": metrics,
            "timeline": self.timeline,
            "operational_context": {
                "schema": "campex_video_operational_context.v2",
                "camera_id": self.camera_id,
                "source": source or {},
                "metrics": metrics,
                "people": metrics["people"],
                "activity": metrics["activity"],
                "zones": metrics["zones"],
                "important_events": self.events[:200],
                "timeline": self.timeline[:200],
            },
        }

    def metrics(self, source: dict[str, Any]) -> dict[str, Any]:
        stationary_events = [
            event for event in self.events if event["event_type"] == "person_stationary"
        ]
        long_presence_events = [
            event for event in self.events if event["event_type"] == "long_presence"
        ]
        crowding_events = [
            event for event in self.events if event["event_type"] == "crowding_started"
        ]
        zone_metrics: dict[str, Any] = {}
        for zone in self.zones:
            stays = self._zone_stays.get(zone.id, [])
            zone_metrics[zone.id] = {
                "name": zone.name,
                "entries": self._zone_entries.get(zone.id, 0),
                "exits": self._zone_exits.get(zone.id, 0),
                "people_in_zone": self._zone_counts.get(zone.id, 0),
                "max_people": self._zone_peak.get(zone.id, 0),
                "average_stay_seconds": round(sum(stays) / max(1, len(stays)), 3),
                "stationary_seconds": round(
                    sum(
                        track.stationary_seconds
                        for track in self.tracks.values()
                        if track.zone_id == zone.id
                    ),
                    3,
                ),
                "idle_open": zone.id in self._zone_idle_event,
                "crowding_open": zone.id in self._crowding_event,
            }
        return {
            "source": source,
            "people": {
                "detected": len(self.tracks),
                "entries": self.entries,
                "exits": self.exits,
                "current_count": max(0, self.entries - self.exits),
                "people_visible": self.people_visible,
                "max_simultaneous": self.max_simultaneous,
            },
            "summary": {
                "unique_people": len(self.tracks),
                "total_events": len(self.events),
                "max_simultaneous": self.max_simultaneous,
            },
            "activity": {
                "stationary_events": len(stationary_events),
                "stationary_seconds": round(
                    sum(track.stationary_seconds for track in self.tracks.values()), 3
                ),
                "moving_seconds": round(
                    sum(track.moving_seconds for track in self.tracks.values()), 3
                ),
                "long_presence_events": len(long_presence_events),
                "crowding_events": len(crowding_events),
            },
            "movement": {
                "moving_total_seconds": round(
                    sum(track.moving_seconds for track in self.tracks.values()), 3
                ),
                "stationary_total_seconds": round(
                    sum(track.stationary_seconds for track in self.tracks.values()), 3
                ),
            },
            "zones": zone_metrics,
            "timeline": self.timeline[:200],
        }

    def _process_track(self, obj: TrackedObject, timestamp: datetime) -> None:
        cx, cy = _normalized_centroid(obj, self.frame_width, self.frame_height)
        track = self.tracks.get(obj.track_id)
        if track is None:
            track = TrackRuntime(
                track_id=obj.track_id,
                first_seen=timestamp,
                last_seen=timestamp,
                confidence=obj.confidence,
            )
            self.tracks[obj.track_id] = track
            self.entries += 1
            self._create_event(
                "person_detected",
                timestamp,
                track_id=obj.track_id,
                confidence=obj.confidence,
                metadata={"bbox": obj.bounding_box.as_list()},
            )
            self._create_event(
                "person_entered",
                timestamp,
                track_id=obj.track_id,
                confidence=obj.confidence,
            )

        elapsed = max(0.0, (timestamp - track.last_seen).total_seconds())
        track.confidence = max(track.confidence, obj.confidence)
        if track.positions:
            state = self._movement_state(track, cx, cy, timestamp)
            if state == MOVING:
                track.moving_seconds += elapsed
            elif state == STATIONARY and track.movement_state == STATIONARY:
                track.stationary_seconds += elapsed
                track.stationary_accounted_until = timestamp
            self._transition_movement(track, state, timestamp, obj.confidence)
        track.positions.append((timestamp, cx, cy))
        track.last_seen = timestamp
        self._maybe_long_presence(track, timestamp, obj.confidence)

    def debug_tracks(
        self, objects: list[TrackedObject], timestamp: datetime
    ) -> list[dict[str, Any]]:
        debug: list[dict[str, Any]] = []
        for obj in objects:
            if obj.class_name.lower() != "person":
                continue
            track = self.tracks.get(obj.track_id)
            if track is None:
                continue
            state = track.movement_state
            seconds = 0.0
            if state == STATIONARY and track.stationary_since is not None:
                seconds = max(0.0, (timestamp - track.stationary_since).total_seconds())
            elif state == UNKNOWN:
                potential_since = self._stationary_candidate_started(track)
                if potential_since is not None:
                    seconds = max(0.0, (timestamp - potential_since).total_seconds())
                    if seconds > 0:
                        state = "POTENTIAL_STATIONARY"
            debug.append(
                {
                    "track_id": obj.track_id,
                    "bbox": obj.bounding_box.as_list(),
                    "confidence": obj.confidence,
                    "zone": self._zone_name(track.zone_id),
                    "movement_state": state,
                    "state_seconds": round(seconds, 3),
                    "trajectory": [
                        {
                            "x": round(x * self.frame_width, 2),
                            "y": round(y * self.frame_height, 2),
                        }
                        for _, x, y in list(track.positions)[-20:]
                    ],
                }
            )
        return debug

    def _movement_state(
        self, track: TrackRuntime, cx: float, cy: float, timestamp: datetime
    ) -> str:
        window_start = timestamp.timestamp() - self.settings.stationary_threshold_seconds
        candidates = [item for item in track.positions if item[0].timestamp() >= window_start]
        if not candidates:
            return UNKNOWN
        max_distance = max(
            ((cx - px) ** 2 + (cy - py) ** 2) ** 0.5
            for _, px, py in candidates
        )
        if max_distance <= self.settings.movement_threshold:
            elapsed = (timestamp - candidates[0][0]).total_seconds()
            track.potential_stationary_since = candidates[0][0]
            return STATIONARY if elapsed >= self.settings.stationary_threshold_seconds else UNKNOWN
        track.potential_stationary_since = None
        return MOVING

    def _transition_movement(
        self, track: TrackRuntime, next_state: str, timestamp: datetime, confidence: float
    ) -> None:
        if next_state == UNKNOWN or next_state == track.movement_state:
            return
        previous = track.movement_state
        track.movement_state = next_state
        if next_state == STATIONARY:
            track.stationary_since = track.potential_stationary_since or timestamp
            if track.stationary_accounted_until is None:
                track.stationary_seconds += max(
                    0.0,
                    (timestamp - track.stationary_since).total_seconds(),
                )
            track.stationary_accounted_until = timestamp
            event = self._create_event(
                "person_stationary",
                track.stationary_since,
                track_id=track.track_id,
                zone=track.zone_id,
                confidence=confidence,
                metadata={"previous_state": previous},
            )
            track.open_stationary_event_id = event["id"]
        elif next_state == MOVING:
            track.potential_stationary_since = None
            if track.open_stationary_event_id:
                if track.stationary_accounted_until is not None:
                    track.stationary_seconds += max(
                        0.0,
                        (timestamp - track.stationary_accounted_until).total_seconds(),
                    )
                track.stationary_accounted_until = None
                self._close_event(track.open_stationary_event_id, timestamp)
                track.open_stationary_event_id = None
            self._create_event(
                "person_moving",
                timestamp,
                track_id=track.track_id,
                zone=track.zone_id,
                confidence=confidence,
                metadata={"previous_state": previous},
            )

    def _stationary_candidate_started(self, track: TrackRuntime) -> datetime | None:
        return track.potential_stationary_since

    def _maybe_long_presence(
        self, track: TrackRuntime, timestamp: datetime, confidence: float
    ) -> None:
        if track.long_presence_emitted:
            return
        duration = (timestamp - track.first_seen).total_seconds()
        if duration >= self.settings.long_presence_threshold_seconds:
            self._create_event(
                "long_presence",
                track.first_seen,
                ended_at=timestamp,
                duration_seconds=duration,
                track_id=track.track_id,
                zone=track.zone_id,
                confidence=confidence,
            )
            track.long_presence_emitted = True

    def _close_track_visibility(self, track_id: int, timestamp: datetime) -> None:
        track = self.tracks.get(track_id)
        if track is None or track.exited_counted:
            return
        if track.open_stationary_event_id:
            self._close_event(track.open_stationary_event_id, timestamp)
            track.open_stationary_event_id = None
        track.exited_counted = True
        self.exits += 1
        self._create_event(
            "person_exited",
            timestamp,
            track_id=track_id,
            zone=track.zone_id,
            confidence=track.confidence,
        )

    def _process_zones(self, people: list[TrackedObject], timestamp: datetime) -> None:
        if not self.zones:
            return
        observations, presence = self.spatial.evaluate(
            self.camera_id, people, self.frame_width, self.frame_height
        )
        zone_counts = defaultdict(int)
        for item in presence:
            for zone_id in item.zone_ids:
                zone_counts[zone_id] += 1
        self._zone_counts = zone_counts
        for zone_id, count in zone_counts.items():
            self._zone_peak[zone_id] = max(self._zone_peak[zone_id], count)

        for obs in observations:
            track = self.tracks.get(obs.track_id or -1)
            zone_name = self._zone_name(obs.zone_id)
            if obs.type == "person_entered_zone":
                self._zone_entries[obs.zone_id or ""] += 1
                self._zone_membership_started[(obs.track_id or 0, obs.zone_id or "")] = obs.timestamp
                if track:
                    track.zone_id = obs.zone_id
                self._create_event(
                    "zone_entered",
                    obs.timestamp,
                    track_id=obs.track_id,
                    zone=zone_name,
                    confidence=obs.confidence,
                )
            elif obs.type == "person_exited_zone":
                self._zone_exits[obs.zone_id or ""] += 1
                started = self._zone_membership_started.pop(
                    (obs.track_id or 0, obs.zone_id or ""), None
                )
                if started:
                    self._zone_stays[obs.zone_id or ""].append(
                        max(0.0, (obs.timestamp - started).total_seconds())
                    )
                if track and track.zone_id == obs.zone_id:
                    track.zone_id = None
                self._create_event(
                    "zone_exited",
                    obs.timestamp,
                    track_id=obs.track_id,
                    zone=zone_name,
                    confidence=obs.confidence,
                )
            elif obs.type == "person_presence" and track:
                if track.movement_state == MOVING:
                    self._zone_last_activity[obs.zone_id or ""] = obs.timestamp

        for zone in self.zones:
            self._zone_last_activity.setdefault(zone.id, timestamp)

    def _update_zone_aggregate_events(self, timestamp: datetime) -> None:
        for zone in self.zones:
            count = self._zone_counts.get(zone.id, 0)
            if count > self.settings.crowding_threshold and zone.id not in self._crowding_event:
                event = self._create_event(
                    "crowding_started",
                    timestamp,
                    zone=zone.name,
                    metadata={"people_in_zone": count, "threshold": self.settings.crowding_threshold},
                )
                self._crowding_event[zone.id] = event["id"]
                self._crowding_peak[zone.id] = count
            elif zone.id in self._crowding_event:
                self._crowding_peak[zone.id] = max(self._crowding_peak[zone.id], count)
                if count <= self.settings.crowding_threshold:
                    self._close_event(
                        self._crowding_event.pop(zone.id),
                        timestamp,
                        metadata={"peak_people": self._crowding_peak[zone.id]},
                    )

            last_activity = self._zone_last_activity.get(zone.id)
            if last_activity is None:
                continue
            idle_seconds = (timestamp - last_activity).total_seconds()
            if idle_seconds >= self.settings.zone_idle_threshold_seconds and zone.id not in self._zone_idle_event:
                event = self._create_event(
                    "zone_idle",
                    last_activity,
                    zone=zone.name,
                    metadata={"idle_threshold_seconds": self.settings.zone_idle_threshold_seconds},
                )
                self._zone_idle_event[zone.id] = event["id"]
            elif zone.id in self._zone_idle_event and count > 0:
                self._close_event(self._zone_idle_event.pop(zone.id), timestamp)
                self._create_event("zone_activity_resumed", timestamp, zone=zone.name)

    def _create_event(
        self,
        event_type: str,
        started_at: datetime,
        *,
        ended_at: datetime | None = None,
        duration_seconds: float | None = None,
        track_id: int | None = None,
        zone: str | None = None,
        confidence: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if duration_seconds is None and ended_at is not None:
            duration_seconds = max(0.0, (ended_at - started_at).total_seconds())
        event = {
            "id": f"evt_{uuid4().hex[:12]}",
            "event_type": event_type,
            "camera_id": self.camera_id,
            "track_id": track_id,
            "zone": zone,
            "started_at": started_at.isoformat(),
            "ended_at": ended_at.isoformat() if ended_at else None,
            "duration_seconds": round(duration_seconds, 3) if duration_seconds is not None else None,
            "confidence": confidence,
            "metadata": metadata or {},
        }
        self.events.append(event)
        self.timeline.append(
            {
                "timestamp": event["started_at"],
                "event_type": event_type,
                "track_id": track_id,
                "zone": zone,
                "description": _describe_event(event_type, track_id, zone),
            }
        )
        return event

    def _close_event(
        self,
        event_id: str,
        ended_at: datetime,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        for event in self.events:
            if event["id"] != event_id:
                continue
            event["ended_at"] = ended_at.isoformat()
            started = datetime.fromisoformat(event["started_at"])
            event["duration_seconds"] = round(
                max(0.0, (ended_at - started).total_seconds()), 3
            )
            if metadata:
                event["metadata"].update(metadata)
            return

    def _zone_name(self, zone_id: str | None) -> str | None:
        if zone_id is None:
            return None
        for zone in self.zones:
            if zone.id == zone_id:
                return zone.name
        return zone_id

    @staticmethod
    def _track_as_dict(track: TrackRuntime) -> dict[str, Any]:
        total = max(0.001, (track.last_seen - track.first_seen).total_seconds())
        return {
            "track_id": track.track_id,
            "class": "person",
            "first_seen": track.first_seen.isoformat(),
            "last_seen": track.last_seen.isoformat(),
            "total_visible_seconds": round(total, 3),
            "confidence": track.confidence,
            "zone": track.zone_id,
            "movement_state": track.movement_state,
            "moving_seconds": round(track.moving_seconds, 3),
            "stationary_seconds": round(track.stationary_seconds, 3),
            "moving_percent": round((track.moving_seconds / total) * 100, 2),
            "stationary_percent": round((track.stationary_seconds / total) * 100, 2),
            "positions": [
                {"timestamp": ts.isoformat(), "x": round(x, 6), "y": round(y, 6)}
                for ts, x, y in list(track.positions)
            ],
        }


def _normalized_centroid(
    obj: TrackedObject, frame_width: int, frame_height: int
) -> tuple[float, float]:
    bbox = obj.bounding_box
    return (
        ((bbox.x1 + bbox.x2) / 2.0) / max(1, frame_width),
        ((bbox.y1 + bbox.y2) / 2.0) / max(1, frame_height),
    )


def _describe_event(event_type: str, track_id: int | None, zone: str | None) -> str:
    person = f"Pessoa #{track_id}" if track_id is not None else "Zona"
    labels = {
        "person_detected": "detectada",
        "person_entered": "entrou",
        "person_exited": "saiu",
        "person_stationary": "iniciou periodo sem deslocamento significativo",
        "person_moving": "retomou movimento",
        "zone_entered": f"entrou na zona {zone}",
        "zone_exited": f"saiu da zona {zone}",
        "long_presence": "atingiu permanencia longa",
        "zone_idle": f"ficou sem atividade observavel em {zone}",
        "zone_activity_resumed": f"teve atividade retomada em {zone}",
        "crowding_started": f"ultrapassou limite de pessoas em {zone}",
        "crowding_ended": f"normalizou aglomeracao em {zone}",
    }
    return f"{person} {labels.get(event_type, event_type)}"
