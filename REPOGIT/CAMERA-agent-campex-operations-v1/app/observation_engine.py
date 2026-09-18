from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from shared.schemas import now_iso

OBSERVATION_TYPES = {
    "machine_activity",
    "person_track",
    "person_presence",
    "zone_occupancy",
    "lighting_state",
    "operational_activity",
    "phone_candidate",
    "vehicle_presence",
    "person_vehicle_proximity",
}

DATA_QUALITY_VALUES = {
    "observed",
    "inferred",
    "insufficient_data",
    "sensor_unavailable",
}

SECRET_KEY_FRAGMENTS = (
    "authorization",
    "credential",
    "password",
    "rtsp",
    "secret",
    "senha",
    "token",
)

SUPPORTED_VEHICLE_CLASSES = {"bicycle", "car", "motorcycle", "bus", "truck"}
SPECIALIZED_MODEL_REQUIRED_CLASSES = {"forklift"}


@dataclass(frozen=True)
class Observation:
    observation_type: str
    camera_id: str
    value: str
    confidence: float
    source: str
    data_quality: str
    timestamp: datetime | str | None = None
    observation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    cliente_id: str | None = None
    unidade_id: str | None = None
    area_id: str | None = None
    process_id: str | None = None
    asset_id: str | None = None
    machine_id: str | None = None
    zone_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.observation_type not in OBSERVATION_TYPES:
            raise ValueError(f"invalid observation_type: {self.observation_type}")
        if self.data_quality not in DATA_QUALITY_VALUES:
            raise ValueError(f"invalid data_quality: {self.data_quality}")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        object.__setattr__(self, "timestamp", _coerce_timestamp(self.timestamp))
        object.__setattr__(self, "confidence", round(float(self.confidence), 4))
        object.__setattr__(self, "metadata", sanitize_metadata(self.metadata or {}))

    def to_dict(self) -> dict[str, Any]:
        timestamp = self.timestamp
        return {
            "observation_id": self.observation_id,
            "observation_type": self.observation_type,
            "camera_id": self.camera_id,
            "cliente_id": self.cliente_id,
            "unidade_id": self.unidade_id,
            "area_id": self.area_id,
            "process_id": self.process_id,
            "asset_id": self.asset_id,
            "machine_id": self.machine_id,
            "zone_id": self.zone_id,
            "timestamp": timestamp.isoformat() if isinstance(timestamp, datetime) else timestamp,
            "value": self.value,
            "confidence": self.confidence,
            "source": self.source,
            "data_quality": self.data_quality,
            "metadata": self.metadata,
        }


@dataclass
class HumanPresenceState:
    zone_id: str
    state: str = "UNKNOWN"
    last_presence_at: float | None = None
    absence_started_at: float | None = None
    current_state_since: float = field(default_factory=time.monotonic)
    seconds_present: float = 0.0
    seconds_absent: float = 0.0
    transitions: int = 0
    confidence: float = 0.0
    valid_tracks_count: int = 0

    def set_state(self, state: str, now: float, confidence: float) -> None:
        if state != self.state:
            self.state = state
            self.current_state_since = now
            self.transitions += 1
        self.confidence = round(float(confidence), 4)

    def seconds_in_state(self, now: float) -> float:
        return max(0.0, now - self.current_state_since)


class HumanPresenceTemporalTracker:
    def __init__(self, grace_seconds: float = 2.0, absence_tolerance_seconds: float = 5.0) -> None:
        self.grace_seconds = grace_seconds
        self.absence_tolerance_seconds = absence_tolerance_seconds
        self._states: dict[str, HumanPresenceState] = {}
        self._last_update_at: float | None = None

    def update(
        self,
        *,
        zone_id: str,
        valid_tracks_count: int,
        camera_online: bool,
        inference_available: bool,
        zone_configured: bool,
        presence_required: bool = True,
        track_confidence: float | None = None,
        now: float | None = None,
        absence_tolerance_seconds: float | None = None,
    ) -> HumanPresenceState:
        now = time.monotonic() if now is None else now
        tolerance = self.absence_tolerance_seconds if absence_tolerance_seconds is None else float(absence_tolerance_seconds)
        state = self._states.setdefault(zone_id, HumanPresenceState(zone_id=zone_id, current_state_since=now))
        dt = 0.0 if self._last_update_at is None else max(0.0, now - self._last_update_at)
        self._last_update_at = now
        if state.state == "PRESENT":
            state.seconds_present += dt
        elif state.state == "ABSENT":
            state.seconds_absent += dt

        state.valid_tracks_count = int(valid_tracks_count)
        if not camera_online or not inference_available or not zone_configured:
            state.set_state("UNKNOWN", now, 0.0)
            return state

        if valid_tracks_count > 0:
            state.last_presence_at = now
            state.absence_started_at = None
            confidence = 0.85 if track_confidence is None else min(1.0, max(0.0, float(track_confidence)))
            state.set_state("PRESENT", now, confidence)
            return state

        if not presence_required:
            state.absence_started_at = None
            state.set_state("UNKNOWN", now, 0.0)
            return state

        if state.last_presence_at is not None and now - state.last_presence_at <= self.grace_seconds:
            age = now - state.last_presence_at
            confidence = max(0.0, state.confidence * (1.0 - min(1.0, age / max(self.grace_seconds, 1e-9)) * 0.5))
            state.set_state("PRESENT", now, confidence)
            return state

        if state.absence_started_at is None:
            state.absence_started_at = now
        if now - state.absence_started_at >= tolerance:
            state.set_state("ABSENT", now, 0.75)
        else:
            state.set_state("UNKNOWN", now, 0.0)
        return state

    def reset(self) -> None:
        self._states.clear()
        self._last_update_at = None


@dataclass
class SafetyZoneState:
    zone_id: str
    people_inside: set[int] = field(default_factory=set)
    vehicles_inside: set[int] = field(default_factory=set)
    vehicle_classes: dict[int, str] = field(default_factory=dict)
    entered_at: dict[str, float] = field(default_factory=dict)
    last_seen_at: dict[str, float] = field(default_factory=dict)


@dataclass
class ProximityState:
    key: tuple[int, int]
    person_track_id: int
    vehicle_track_id: int
    vehicle_class: str
    first_near_at: float
    last_near_at: float
    seconds_persistent: float = 0.0
    confidence: float = 0.0
    state: str = "UNKNOWN"


class SafetyTemporalTracker:
    def __init__(self, grace_seconds: float = 2.0, proximity_min_seconds: float = 1.0) -> None:
        self.grace_seconds = grace_seconds
        self.proximity_min_seconds = proximity_min_seconds
        self._zones: dict[str, SafetyZoneState] = {}
        self._proximity: dict[tuple[int, int], ProximityState] = {}

    def zone_update(
        self,
        *,
        zone_id: str,
        people_ids: set[int],
        vehicle_ids: set[int],
        vehicle_classes: dict[int, str],
        now: float | None = None,
    ) -> SafetyZoneState:
        now = time.monotonic() if now is None else now
        state = self._zones.setdefault(zone_id, SafetyZoneState(zone_id=zone_id))
        for prefix, ids in (("person", people_ids), ("vehicle", vehicle_ids)):
            for track_id in ids:
                key = f"{prefix}:{track_id}"
                state.entered_at.setdefault(key, now)
                state.last_seen_at[key] = now
        for key, seen_at in list(state.last_seen_at.items()):
            if now - seen_at > self.grace_seconds:
                state.last_seen_at.pop(key, None)
                state.entered_at.pop(key, None)
        state.people_inside = {int(key.split(":", 1)[1]) for key in state.last_seen_at if key.startswith("person:")}
        state.vehicles_inside = {int(key.split(":", 1)[1]) for key in state.last_seen_at if key.startswith("vehicle:")}
        state.vehicle_classes = {track_id: vehicle_classes.get(track_id, "vehicle") for track_id in state.vehicles_inside}
        return state

    def proximity_update(
        self,
        *,
        person_track_id: int,
        vehicle_track_id: int,
        vehicle_class: str,
        near: bool,
        distance_metric: float | None,
        confidence: float,
        now: float | None = None,
    ) -> ProximityState:
        now = time.monotonic() if now is None else now
        key = (person_track_id, vehicle_track_id)
        state = self._proximity.get(key)
        if near:
            if state is None:
                state = ProximityState(
                    key=key,
                    person_track_id=person_track_id,
                    vehicle_track_id=vehicle_track_id,
                    vehicle_class=vehicle_class,
                    first_near_at=now,
                    last_near_at=now,
                )
                self._proximity[key] = state
            state.last_near_at = now
            state.seconds_persistent = max(0.0, now - state.first_near_at)
            state.confidence = round(min(0.95, max(0.0, confidence)), 4)
            state.state = "NEAR" if state.seconds_persistent >= self.proximity_min_seconds else "CANDIDATE"
            return state
        if state is None:
            return ProximityState(key=key, person_track_id=person_track_id, vehicle_track_id=vehicle_track_id, vehicle_class=vehicle_class, first_near_at=now, last_near_at=now)
        if now - state.last_near_at <= self.grace_seconds:
            state.state = "CANDIDATE"
            state.confidence = round(max(0.0, state.confidence * 0.7), 4)
            return state
        state.state = "UNKNOWN"
        state.confidence = 0.0
        state.seconds_persistent = 0.0
        state.first_near_at = now
        return state

    def reset(self) -> None:
        self._zones.clear()
        self._proximity.clear()


@dataclass
class LightingState:
    state: str = "UNKNOWN"
    pending_state: str | None = None
    pending_count: int = 0
    brightness: float | None = None
    confidence: float = 0.0
    data_quality: str = "insufficient_data"


class LightingStateDetector:
    def __init__(
        self,
        *,
        off_threshold: float = 35.0,
        on_threshold: float = 55.0,
        min_persistent_frames: int = 3,
    ) -> None:
        self.off_threshold = float(off_threshold)
        self.on_threshold = float(on_threshold)
        self.min_persistent_frames = max(1, int(min_persistent_frames))
        self._state = LightingState()

    def update(
        self,
        frame: Any,
        *,
        camera_online: bool = True,
        inference_available: bool = True,
    ) -> LightingState:
        if not camera_online:
            self._state = LightingState(state="UNKNOWN", data_quality="sensor_unavailable")
            return self._state
        brightness = _mean_brightness(frame)
        if brightness is None or not inference_available:
            self._state = LightingState(
                state="UNKNOWN",
                brightness=brightness,
                confidence=0.0,
                data_quality="insufficient_data",
            )
            return self._state
        if brightness <= self.off_threshold:
            candidate = "OFF"
        elif brightness >= self.on_threshold:
            candidate = "ON"
        else:
            candidate = "UNKNOWN"
        if candidate == "UNKNOWN":
            self._state = LightingState(
                state="UNKNOWN",
                brightness=brightness,
                confidence=0.25,
                data_quality="insufficient_data",
            )
            return self._state
        if candidate == self._state.state:
            self._state.pending_state = None
            self._state.pending_count = 0
        elif candidate == self._state.pending_state:
            self._state.pending_count += 1
        else:
            self._state.pending_state = candidate
            self._state.pending_count = 1
        if self._state.state == "UNKNOWN" or self._state.pending_count >= self.min_persistent_frames:
            self._state.state = candidate
            self._state.pending_state = None
            self._state.pending_count = 0
        distance = abs(brightness - (self.off_threshold if self._state.state == "OFF" else self.on_threshold))
        confidence = min(0.95, max(0.5, distance / 80.0))
        self._state.brightness = round(float(brightness), 3)
        self._state.confidence = round(confidence, 4)
        self._state.data_quality = "observed"
        return self._state

    def reset(self) -> None:
        self._state = LightingState()


def _mean_brightness(frame: Any) -> float | None:
    if frame is None:
        return None
    try:
        import numpy as np

        array = np.asarray(frame)
        if array.size == 0:
            return None
        if array.ndim == 3:
            array = array[..., :3].mean(axis=2)
        return float(array.mean())
    except Exception:
        return None


def _coerce_timestamp(value: datetime | str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        parsed = value
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def sanitize_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if any(fragment in key_text.lower() for fragment in SECRET_KEY_FRAGMENTS):
                sanitized[key_text] = "[redacted]"
            else:
                sanitized[key_text] = sanitize_metadata(item)
        return sanitized
    if isinstance(value, list):
        return [sanitize_metadata(item) for item in value]
    if isinstance(value, str) and "rtsp://" in value.lower():
        return "[redacted]"
    return value


def machine_activity_observation(
    *,
    camera_id: str,
    machine_id: str | None,
    state: str,
    activity_score: float | None,
    confidence: float | None,
    source: str = "machine_monitor",
    data_quality: str | None = None,
    cliente_id: str | None = None,
    unidade_id: str | None = None,
    area_id: str | None = None,
    process_id: str | None = None,
    asset_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    timestamp: datetime | str | None = None,
) -> Observation:
    value = state if state in {"ACTIVE", "STOPPED"} else "UNKNOWN"
    quality = data_quality or ("observed" if value != "UNKNOWN" else "insufficient_data")
    return Observation(
        observation_type="machine_activity",
        camera_id=camera_id,
        cliente_id=cliente_id,
        unidade_id=unidade_id,
        area_id=area_id,
        process_id=process_id,
        asset_id=asset_id,
        machine_id=machine_id,
        timestamp=timestamp,
        value=value,
        confidence=0.0 if confidence is None else confidence,
        source=source,
        data_quality=quality,
        metadata={**(metadata or {}), "activity_score": activity_score},
    )


def person_presence_observation(
    *,
    camera_id: str,
    detections: list[Any] | None = None,
    people_count: int | None = None,
    inference_available: bool = True,
    absence_confirmed: bool = False,
    confidence: float | None = None,
    source: str = "person_detector",
    cliente_id: str | None = None,
    unidade_id: str | None = None,
    area_id: str | None = None,
    process_id: str | None = None,
    asset_id: str | None = None,
    zone_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    timestamp: datetime | str | None = None,
) -> Observation:
    detections = detections or []
    count = int(people_count if people_count is not None else len(detections))
    if not inference_available:
        value = "UNKNOWN"
        quality = "sensor_unavailable"
    elif count > 0:
        value = "PRESENT"
        quality = "observed"
    elif absence_confirmed:
        value = "ABSENT"
        quality = "inferred"
    else:
        value = "UNKNOWN"
        quality = "insufficient_data"
    resolved_confidence = confidence if confidence is not None else _max_detection_confidence(detections)
    return Observation(
        observation_type="person_presence",
        camera_id=camera_id,
        cliente_id=cliente_id,
        unidade_id=unidade_id,
        area_id=area_id,
        process_id=process_id,
        asset_id=asset_id,
        zone_id=zone_id,
        timestamp=timestamp,
        value=value,
        confidence=resolved_confidence if value != "UNKNOWN" else 0.0,
        source=source,
        data_quality=quality,
        metadata={**(metadata or {}), "people_count": count, "track_ids": _track_ids(detections)},
    )


def person_track_observation(
    *,
    camera_id: str,
    track: Any,
    source: str = "centroid_tracker",
    cliente_id: str | None = None,
    unidade_id: str | None = None,
    area_id: str | None = None,
    process_id: str | None = None,
    asset_id: str | None = None,
    zone_id: str | None = None,
    timestamp: datetime | str | None = None,
) -> Observation:
    state = str(getattr(track, "state", "UNKNOWN") or "UNKNOWN")
    confidence = float(getattr(track, "temporal_confidence", 0.0) or 0.0)
    data_quality = "observed" if state == "PRESENT" and getattr(track, "seconds_since_last_seen", 999.0) <= 0.05 else "inferred" if state == "PRESENT" else "insufficient_data"
    return Observation(
        observation_type="person_track",
        camera_id=camera_id,
        cliente_id=cliente_id,
        unidade_id=unidade_id,
        area_id=area_id,
        process_id=process_id,
        asset_id=asset_id,
        zone_id=zone_id,
        timestamp=timestamp,
        value=state if state in {"PRESENT", "UNKNOWN"} else "UNKNOWN",
        confidence=confidence,
        source=source,
        data_quality=data_quality,
        metadata={
            "track_id": getattr(track, "track_id", None),
            "bbox": getattr(track, "last_bbox", None),
            "detector_confidence": getattr(track, "last_confidence", None),
            "duration_seen": round(float(getattr(track, "duration_seen", 0.0) or 0.0), 3),
            "seconds_since_last_seen": round(float(getattr(track, "seconds_since_last_seen", 0.0) or 0.0), 3),
            "consecutive_seen": getattr(track, "consecutive_seen", 0),
            "consecutive_missed": getattr(track, "consecutive_missed", 0),
        },
    )


def zone_occupancy_observation(
    *,
    camera_id: str,
    zone_id: str | None,
    zone_type: str | None,
    people_count: int | None,
    inference_available: bool = True,
    confidence: float | None = None,
    source: str = "people_zones",
    cliente_id: str | None = None,
    unidade_id: str | None = None,
    area_id: str | None = None,
    process_id: str | None = None,
    asset_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    timestamp: datetime | str | None = None,
) -> Observation:
    count = int(people_count or 0)
    metadata = metadata or {}
    vehicle_count = int(metadata.get("vehicle_count") or 0)
    if not inference_available:
        value = "UNKNOWN"
        quality = "sensor_unavailable"
        resolved_confidence = 0.0
    else:
        value = "OCCUPIED" if count > 0 or vehicle_count > 0 else "EMPTY"
        quality = "observed"
        resolved_confidence = 1.0 if confidence is None else confidence
    return Observation(
        observation_type="zone_occupancy",
        camera_id=camera_id,
        cliente_id=cliente_id,
        unidade_id=unidade_id,
        area_id=area_id,
        process_id=process_id,
        asset_id=asset_id,
        zone_id=zone_id,
        timestamp=timestamp,
        value=value,
        confidence=resolved_confidence,
        source=source,
        data_quality=quality,
        metadata={**metadata, "zone_type": zone_type, "people_count": count, "vehicle_count": vehicle_count},
    )


def lighting_state_observation(
    *,
    camera_id: str,
    state: str,
    brightness: float | None,
    confidence: float,
    data_quality: str = "observed",
    source: str = "lighting_state_detector",
    cliente_id: str | None = None,
    unidade_id: str | None = None,
    area_id: str | None = None,
    process_id: str | None = None,
    asset_id: str | None = None,
    timestamp: datetime | str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Observation:
    value = state if state in {"ON", "OFF"} else "UNKNOWN"
    quality = data_quality if value != "UNKNOWN" else data_quality if data_quality == "sensor_unavailable" else "insufficient_data"
    return Observation(
        observation_type="lighting_state",
        camera_id=camera_id,
        cliente_id=cliente_id,
        unidade_id=unidade_id,
        area_id=area_id,
        process_id=process_id,
        asset_id=asset_id,
        timestamp=timestamp,
        value=value,
        confidence=confidence,
        source=source,
        data_quality=quality,
        metadata={**(metadata or {}), "brightness": brightness},
    )


def operational_activity_observation(
    *,
    camera_id: str,
    state: str,
    facts: list[str],
    confidence: float,
    data_quality: str = "inferred",
    source: str = "operational_read_model",
    cliente_id: str | None = None,
    unidade_id: str | None = None,
    area_id: str | None = None,
    process_id: str | None = None,
    asset_id: str | None = None,
    timestamp: datetime | str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Observation:
    value = state if state in {"NORMAL_ACTIVITY", "LOW_ACTIVITY", "NO_ACTIVITY"} else "UNKNOWN"
    return Observation(
        observation_type="operational_activity",
        camera_id=camera_id,
        cliente_id=cliente_id,
        unidade_id=unidade_id,
        area_id=area_id,
        process_id=process_id,
        asset_id=asset_id,
        timestamp=timestamp,
        value=value,
        confidence=confidence if value != "UNKNOWN" else 0.0,
        source=source,
        data_quality=data_quality if value != "UNKNOWN" else "insufficient_data",
        metadata={**(metadata or {}), "facts": facts},
    )


def phone_candidate_observation(**kwargs: Any) -> Observation:
    candidate = bool(kwargs.pop("candidate", False))
    return Observation(
        observation_type="phone_candidate",
        value=kwargs.pop("value", "CANDIDATE" if candidate else "UNKNOWN"),
        confidence=kwargs.pop("confidence", 0.0),
        source=kwargs.pop("source", "detector"),
        data_quality=kwargs.pop("data_quality", "observed" if candidate else "insufficient_data"),
        metadata={**(kwargs.pop("metadata", {}) or {}), "candidate": candidate},
        **kwargs,
    )


def vehicle_presence_observation(**kwargs: Any) -> Observation:
    detections = kwargs.pop("detections", None) or []
    count = int(kwargs.pop("vehicle_count", len(detections)) or 0)
    classes = sorted({str(getattr(detection, "class_name", "")) for detection in detections if getattr(detection, "class_name", None)})
    track_ids = _track_ids(detections)
    bboxes = [_bbox(detection) for detection in detections]
    data_quality = kwargs.pop("data_quality", "observed" if count > 0 else "insufficient_data")
    return Observation(
        observation_type="vehicle_presence",
        value="PRESENT" if count > 0 else "UNKNOWN",
        data_quality=data_quality,
        confidence=kwargs.pop("confidence", _max_detection_confidence(detections) if count > 0 else 0.0),
        source=kwargs.pop("source", "vehicle_detector"),
        metadata={
            **(kwargs.pop("metadata", {}) or {}),
            "vehicle_count": count,
            "vehicle_classes": classes,
            "track_ids": track_ids,
            "bboxes": bboxes,
            "forklift_detection": "SPECIALIZED_MODEL_REQUIRED",
        },
        **kwargs,
    )


def person_vehicle_proximity_observation(**kwargs: Any) -> Observation:
    near = bool(kwargs.pop("near", False))
    return Observation(
        observation_type="person_vehicle_proximity",
        value=kwargs.pop("value", "NEAR" if near else "UNKNOWN"),
        confidence=kwargs.pop("confidence", 0.0),
        source=kwargs.pop("source", "proximity_engine"),
        data_quality=kwargs.pop("data_quality", "observed" if near else "insufficient_data"),
        metadata={**(kwargs.pop("metadata", {}) or {}), "near": near},
        **kwargs,
    )


def safety_observations_from_detections(
    *,
    camera_id: str,
    detections: list[Any],
    tracker: SafetyTemporalTracker,
    frame_width: int,
    frame_height: int,
    zones: list[dict[str, Any]] | None = None,
    camera_online: bool = True,
    inference_available: bool = True,
    cliente_id: str | None = None,
    unidade_id: str | None = None,
    area_id: str | None = None,
    process_id: str | None = None,
    asset_id: str | None = None,
    timestamp: datetime | str | None = None,
    proximity_threshold: float = 0.18,
    now: float | None = None,
) -> list[dict[str, Any]]:
    if not camera_online or not inference_available:
        return [
            vehicle_presence_observation(
                camera_id=camera_id,
                vehicle_count=0,
                confidence=0.0,
                data_quality="sensor_unavailable",
                source="safety_observation",
                cliente_id=cliente_id,
                unidade_id=unidade_id,
                area_id=area_id,
                process_id=process_id,
                asset_id=asset_id,
                timestamp=timestamp,
            ).to_dict(),
            person_vehicle_proximity_observation(
                camera_id=camera_id,
                near=False,
                value="UNKNOWN",
                confidence=0.0,
                data_quality="sensor_unavailable",
                source="safety_observation",
                cliente_id=cliente_id,
                unidade_id=unidade_id,
                area_id=area_id,
                process_id=process_id,
                asset_id=asset_id,
                timestamp=timestamp,
            ).to_dict(),
        ]

    people = [detection for detection in detections if getattr(detection, "class_name", None) == "person" and getattr(detection, "track_id", None) is not None]
    vehicles = [detection for detection in detections if getattr(detection, "class_name", None) in SUPPORTED_VEHICLE_CLASSES and getattr(detection, "track_id", None) is not None]
    observations = [
        vehicle_presence_observation(
            camera_id=camera_id,
            detections=vehicles,
            source="safety_observation",
            cliente_id=cliente_id,
            unidade_id=unidade_id,
            area_id=area_id,
            process_id=process_id,
            asset_id=asset_id,
            timestamp=timestamp,
        ).to_dict()
    ]

    for zone in zones or []:
        zone_id = str(zone.get("id") or zone.get("area_id") or "zone")
        polygon = zone.get("pontos") or zone.get("polygon") or []
        people_ids = {int(d.track_id) for d in people if _detection_in_polygon(d, polygon, frame_width, frame_height)}
        vehicle_ids = {int(d.track_id) for d in vehicles if _detection_in_polygon(d, polygon, frame_width, frame_height)}
        vehicle_classes = {int(d.track_id): str(d.class_name) for d in vehicles if d.track_id is not None}
        zone_state = tracker.zone_update(
            zone_id=zone_id,
            people_ids=people_ids,
            vehicle_ids=vehicle_ids,
            vehicle_classes=vehicle_classes,
            now=now,
        )
        observations.append(
            zone_occupancy_observation(
                camera_id=camera_id,
                zone_id=zone_id,
                zone_type=str(zone.get("tipo") or zone.get("area_type") or "zone"),
                people_count=len(zone_state.people_inside),
                confidence=0.85 if zone_state.people_inside or zone_state.vehicles_inside else 0.7,
                source="safety_observation",
                cliente_id=cliente_id,
                unidade_id=unidade_id,
                area_id=area_id,
                process_id=process_id,
                asset_id=asset_id,
                timestamp=timestamp,
                metadata={
                    "people_track_ids": sorted(zone_state.people_inside),
                    "vehicle_track_ids": sorted(zone_state.vehicles_inside),
                    "vehicle_classes": zone_state.vehicle_classes,
                    "vehicle_count": len(zone_state.vehicles_inside),
                },
            ).to_dict()
        )

    for person in people:
        for vehicle in vehicles:
            distance = normalized_bbox_distance(person, vehicle, frame_width, frame_height)
            overlap = bbox_overlap_ratio(person, vehicle)
            near = overlap > 0 or distance <= proximity_threshold
            pair_confidence = min(0.95, (_safe_confidence(person) + _safe_confidence(vehicle)) / 2.0)
            proximity = tracker.proximity_update(
                person_track_id=int(person.track_id),
                vehicle_track_id=int(vehicle.track_id),
                vehicle_class=str(vehicle.class_name),
                near=near,
                distance_metric=distance,
                confidence=pair_confidence,
                now=now,
            )
            observations.append(
                person_vehicle_proximity_observation(
                    camera_id=camera_id,
                    near=proximity.state == "NEAR",
                    value=proximity.state if proximity.state in {"NEAR", "CANDIDATE"} else "UNKNOWN",
                    confidence=proximity.confidence,
                    data_quality="observed" if proximity.state == "NEAR" else "inferred" if proximity.state == "CANDIDATE" else "insufficient_data",
                    source="safety_observation",
                    cliente_id=cliente_id,
                    unidade_id=unidade_id,
                    area_id=area_id,
                    process_id=process_id,
                    asset_id=asset_id,
                    timestamp=timestamp,
                    metadata={
                        "person_track_id": proximity.person_track_id,
                        "vehicle_track_id": proximity.vehicle_track_id,
                        "vehicle_class": proximity.vehicle_class,
                        "distance_metric": round(distance, 4),
                        "distance_metric_type": "normalized_bbox_gap",
                        "overlap_ratio": round(overlap, 4),
                        "seconds_persistent": round(proximity.seconds_persistent, 3),
                        "forklift_detection": "SPECIALIZED_MODEL_REQUIRED",
                    },
                ).to_dict()
            )
    return observations


def _max_detection_confidence(detections: list[Any]) -> float:
    values = []
    for detection in detections:
        value = getattr(detection, "confidence", None)
        if value is None and isinstance(detection, dict):
            value = detection.get("confidence")
        if value is not None:
            values.append(float(value))
    return max(values) if values else 0.0


def _track_ids(detections: list[Any]) -> list[Any]:
    ids = []
    for detection in detections:
        value = getattr(detection, "track_id", None)
        if value is None and isinstance(detection, dict):
            value = detection.get("track_id")
        if value is not None:
            ids.append(value)
    return ids


def _bbox(detection: Any) -> list[int]:
    return [int(getattr(detection, "x1", 0)), int(getattr(detection, "y1", 0)), int(getattr(detection, "x2", 0)), int(getattr(detection, "y2", 0))]


def _safe_confidence(detection: Any) -> float:
    return min(1.0, max(0.0, float(getattr(detection, "confidence", 0.0) or 0.0)))


def normalized_bbox_distance(a: Any, b: Any, width: int, height: int) -> float:
    ax1, ay1, ax2, ay2 = _bbox(a)
    bx1, by1, bx2, by2 = _bbox(b)
    gap_x = max(0, max(bx1 - ax2, ax1 - bx2))
    gap_y = max(0, max(by1 - ay2, ay1 - by2))
    diagonal = max(1.0, (float(width) ** 2 + float(height) ** 2) ** 0.5)
    return ((gap_x ** 2 + gap_y ** 2) ** 0.5) / diagonal


def bbox_overlap_ratio(a: Any, b: Any) -> float:
    ax1, ay1, ax2, ay2 = _bbox(a)
    bx1, by1, bx2, by2 = _bbox(b)
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    if inter <= 0:
        return 0.0
    area_a = max(1, (ax2 - ax1) * (ay2 - ay1))
    area_b = max(1, (bx2 - bx1) * (by2 - by1))
    return inter / float(min(area_a, area_b))


def _detection_in_polygon(detection: Any, polygon: list[dict[str, float]], width: int, height: int) -> bool:
    if len(polygon) < 3:
        return False
    x = ((float(getattr(detection, "x1", 0)) + float(getattr(detection, "x2", 0))) / 2.0) / max(1, width)
    y = float(getattr(detection, "y2", 0)) / max(1, height)
    inside = False
    j = len(polygon) - 1
    for i, current in enumerate(polygon):
        previous = polygon[j]
        cy = float(current["y"])
        py = float(previous["y"])
        cx = float(current["x"])
        px = float(previous["x"])
        intersects = ((cy > y) != (py > y)) and (x < (px - cx) * (y - cy) / ((py - cy) or 1e-9) + cx)
        if intersects:
            inside = not inside
        j = i
    return inside


@dataclass
class MachineObservationTracker:
    state_since: float = field(default_factory=time.monotonic)
    last_state: str = "UNKNOWN"

    def duration(self, state: str, now: float) -> float:
        if state != self.last_state:
            self.last_state = state
            self.state_since = now
        return max(0.0, now - self.state_since)


class ObservationEngine:
    def __init__(self, camera_id: str) -> None:
        self.camera_id = camera_id
        self._trackers: dict[str, MachineObservationTracker] = {}
        self._human_presence = HumanPresenceTemporalTracker()
        self._safety = SafetyTemporalTracker()

    def build(
        self,
        *,
        machine_id: str | None,
        machine_state: str,
        machine_activity_score: float | None,
        machine_confidence: float | None,
        operator_present: bool,
        zone_states: list[dict[str, Any]] | None = None,
        cliente_id: str | None = None,
        unidade_id: str | None = None,
        area_id: str | None = None,
        process_id: str | None = None,
        asset_id: str | None = None,
        camera_online: bool = True,
        inference_available: bool = True,
        operator_absence_tolerance_seconds: float | None = None,
        detections: list[Any] | None = None,
        frame_width: int | None = None,
        frame_height: int | None = None,
    ) -> dict[str, Any]:
        now = time.monotonic()
        machine_key = machine_id or self.camera_id
        tracker = self._trackers.setdefault(machine_key, MachineObservationTracker())
        counts = self._zone_counts(zone_states or [])
        operator_zone_id = self._operator_zone_id(zone_states or [])
        human_state = self._human_presence.update(
            zone_id=operator_zone_id,
            valid_tracks_count=counts["operator_zone"] if zone_states else (1 if operator_present else 0),
            camera_online=camera_online,
            inference_available=inference_available,
            zone_configured=bool(zone_states) or operator_present,
            presence_required=str(machine_state or "UNKNOWN").upper() == "ACTIVE",
            track_confidence=machine_confidence,
            absence_tolerance_seconds=operator_absence_tolerance_seconds,
        )
        canonical_observations = [
            machine_activity_observation(
                camera_id=self.camera_id,
                machine_id=machine_id,
                state=machine_state,
                activity_score=machine_activity_score,
                confidence=machine_confidence,
                cliente_id=cliente_id,
                unidade_id=unidade_id,
                area_id=area_id,
                process_id=process_id,
                asset_id=asset_id,
            ).to_dict(),
            person_presence_observation(
                camera_id=self.camera_id,
                people_count=human_state.valid_tracks_count,
                absence_confirmed=human_state.state == "ABSENT",
                inference_available=camera_online and inference_available,
                confidence=human_state.confidence,
                cliente_id=cliente_id,
                unidade_id=unidade_id,
                area_id=area_id,
                process_id=process_id,
                asset_id=asset_id,
                zone_id=operator_zone_id,
                metadata={
                    "source_field": "operator_zone_temporal_presence",
                    "seconds_in_state": round(human_state.seconds_in_state(now), 3),
                    "last_presence_at_monotonic": human_state.last_presence_at,
                    "absence_started_at_monotonic": human_state.absence_started_at,
                    "seconds_present": round(human_state.seconds_present, 3),
                    "seconds_absent": round(human_state.seconds_absent, 3),
                    "transitions": human_state.transitions,
                    "valid_tracks_count": human_state.valid_tracks_count,
                    "presence_required": str(machine_state or "UNKNOWN").upper() == "ACTIVE",
                },
            ).to_dict(),
        ]
        for zone in zone_states or []:
            zone_type = normalize_zone_type(str(zone.get("tipo") or ""))
            canonical_observations.append(
                zone_occupancy_observation(
                    camera_id=self.camera_id,
                    zone_id=str(zone.get("id") or zone.get("area_id") or zone_type),
                    zone_type=zone_type,
                    people_count=int(zone.get("pessoas_dentro") or 0),
                    confidence=machine_confidence,
                    cliente_id=cliente_id,
                    unidade_id=unidade_id,
                    area_id=area_id,
                    process_id=process_id,
                    asset_id=asset_id,
                    metadata={"raw_zone_type": zone.get("tipo")},
                ).to_dict()
            )
        if detections is not None and frame_width and frame_height:
            canonical_observations.extend(
                safety_observations_from_detections(
                    camera_id=self.camera_id,
                    detections=detections,
                    tracker=self._safety,
                    frame_width=frame_width,
                    frame_height=frame_height,
                    zones=zone_states or [],
                    camera_online=camera_online,
                    inference_available=inference_available,
                    cliente_id=cliente_id,
                    unidade_id=unidade_id,
                    area_id=area_id,
                    process_id=process_id,
                    asset_id=asset_id,
                )
            )
        return {
            "timestamp": now_iso(),
            "camera_id": self.camera_id,
            "machine_id": machine_id,
            "machine_state": machine_state if machine_state in {"ACTIVE", "STOPPED", "UNKNOWN"} else "UNKNOWN",
            "machine_activity_score": round(float(machine_activity_score or 0.0), 3),
            "machine_confidence": round(float(machine_confidence or 0.0), 3),
            "operator_present": bool(operator_present),
            "people_in_operator_zone": counts["operator_zone"],
            "people_in_restricted_zone": counts["restricted_zone"],
            "people_in_work_area": counts["work_area"],
            "seconds_in_machine_state": round(tracker.duration(machine_state, now), 2),
            "observations": canonical_observations,
        }

    def _zone_counts(self, zone_states: list[dict[str, Any]]) -> dict[str, int]:
        counts = {"operator_zone": 0, "restricted_zone": 0, "work_area": 0}
        for zone in zone_states:
            zone_type = normalize_zone_type(str(zone.get("tipo") or ""))
            if zone_type in counts:
                counts[zone_type] += int(zone.get("pessoas_dentro") or 0)
        return counts

    def _operator_zone_id(self, zone_states: list[dict[str, Any]]) -> str:
        for zone in zone_states:
            zone_type = normalize_zone_type(str(zone.get("tipo") or ""))
            if zone_type == "operator_zone":
                return str(zone.get("id") or zone.get("area_id") or "operator_zone")
        return "operator_zone"


def normalize_zone_type(zone_type: str) -> str:
    aliases = {
        "restricted_area": "restricted_zone",
        "workstation": "operator_zone",
        "dwell_area": "work_area",
    }
    return aliases.get(zone_type, zone_type)
