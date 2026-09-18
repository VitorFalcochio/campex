from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable
from backend.events.models import Event, EventRule
from backend.events.repository import EventRepository
from backend.zones.models import Observation, Zone

logger = logging.getLogger("campex.events.engine")


@dataclass
class ActiveEvent:
    """Tracks an ongoing event to prevent duplicate creation."""

    event: Event
    event_key: str  # camera_id:track_id:zone_id:event_type
    started_at: datetime


class EventEngine:
    """Event Engine V1 — generates structured events from observations.

    Architecture:
        Observations (person_entered_zone, person_exited_zone, person_presence)
        → Rule evaluation
        → Deduplication (one event per camera:track:zone:event_type)
        → Event persistence
    """

    DEFAULT_RULES: list[EventRule] = [
        EventRule(
            name="restricted_zone_entry",
            observation_type="person_entered_zone",
            zone_type="restricted",
            event_type="PERSON_RESTRICTED_ZONE",
            severity="critical",
        ),
        EventRule(
            name="restricted_zone_exit",
            observation_type="person_exited_zone",
            zone_type="restricted",
            event_type="PERSON_RESTRICTED_ZONE",  # Same event type as entry
            severity="critical",
        ),
        EventRule(
            name="restricted_zone_dwell",
            observation_type="person_presence",
            zone_type="restricted",
            event_type="PERSON_RESTRICTED_ZONE_DWELL",
            severity="critical",
            duration_threshold_seconds=5.0,
        ),
        EventRule(
            name="monitored_zone_entry",
            observation_type="person_entered_zone",
            zone_type="monitored",
            event_type="PERSON_MONITORED_ZONE",
            severity="attention",
        ),
        EventRule(
            name="monitored_zone_exit",
            observation_type="person_exited_zone",
            zone_type="monitored",
            event_type="PERSON_MONITORED_ZONE",
            severity="attention",
        ),
    ]

    def __init__(
        self,
        event_repo: EventRepository,
        rules: list[EventRule] | None = None,
        rules_provider: Callable[[], list[EventRule]] | None = None,
    ) -> None:
        self._event_repo = event_repo
        self._rules_provider = rules_provider
        self._rules = rules or list(self.DEFAULT_RULES)
        # Build mapping from (zone_type, obs_type) to base event type for dwell
        self._dwell_base_types: dict[tuple[str, str], str] = {}
        self._rebuild_dwell_base_types()

        # camera_id:track_id:zone_id:base_event_type -> ActiveEvent
        self._active_events: dict[str, ActiveEvent] = {}
        self._dwell_timers: dict[str, datetime] = {}
        self._cooldowns: dict[str, datetime] = {}
        self._lock = threading.RLock()

    def _rebuild_dwell_base_types(self) -> None:
        self._dwell_base_types.clear()
        for rule in self._rules:
            if rule.duration_threshold_seconds > 0:
                # This is a dwell rule; find the corresponding entry rule
                for r in self._rules:
                    if (r.zone_type == rule.zone_type
                        and r.observation_type == "person_entered_zone"
                        and not r.duration_threshold_seconds):
                        self._dwell_base_types[(rule.zone_type, rule.observation_type)] = r.event_type
                        break

    def process(
        self,
        camera_id: str,
        observations: list[Observation],
        zones: list[Zone] | None = None,
    ) -> list[Event]:
        with self._lock:
            return self._process(camera_id, observations, zones)

    def _process(
        self,
        camera_id: str,
        observations: list[Observation],
        zones: list[Zone] | None = None,
    ) -> list[Event]:
        """Process observations and generate/update events."""
        created_or_updated: list[Event] = []
        if self._rules_provider is not None:
            self._rules = self._rules_provider()
            self._rebuild_dwell_base_types()
        zone_by_id = {z.id: z for z in zones} if zones else {}

        for obs in observations:
            if obs.zone_id and zones:
                zone = zone_by_id.get(obs.zone_id)
            else:
                zone = None

            zone_type = zone.type if zone else None

            for rule in self._rules:
                if not rule.matches(obs.type, zone_type, camera_id, obs.zone_id):
                    continue

                # Determine base event type for this rule
                if rule.duration_threshold_seconds > 0:
                    # Dwell rule - use base type from entry rule
                    base_type = self._dwell_base_types.get((zone_type, obs.type))
                    if not base_type:
                        base_type = rule.event_type
                else:
                    base_type = rule.event_type

                event_key = self._make_key(
                    camera_id, obs.track_id, obs.zone_id, base_type
                )

                if obs.type == "person_entered_zone":
                    event = self._handle_zone_entry(
                        event_key,
                        camera_id,
                        obs,
                        rule,
                        zone,
                    )
                    if event:
                        created_or_updated.append(event)

                elif obs.type == "person_exited_zone":
                    events = self._handle_zone_exit(
                        event_key,
                        camera_id,
                        obs,
                        rule,
                    )
                    created_or_updated.extend(events)

                elif obs.type == "person_presence" and rule.duration_threshold_seconds > 0:
                    event = self._handle_dwell(
                        event_key,
                        camera_id,
                        obs,
                        rule,
                        zone,
                    )
                    if event:
                        created_or_updated.append(event)

        return created_or_updated

    def _make_key(
        self,
        camera_id: str,
        track_id: int | None,
        zone_id: str | None,
        event_type: str,
    ) -> str:
        return f"{camera_id}:{track_id or 0}:{zone_id or 'none'}:{event_type}"

    def _make_cooldown_key(
        self,
        camera_id: str,
        zone_id: str | None,
        event_type: str,
    ) -> str:
        return f"{camera_id}:{zone_id or 'none'}:{event_type}"

    def _handle_zone_entry(
        self,
        event_key: str,
        camera_id: str,
        obs: Observation,
        rule: EventRule,
        zone: Zone | None,
    ) -> Event | None:
        if event_key in self._active_events:
            # Event already exists for this track/zone/type
            return None
        cooldown_key = self._make_cooldown_key(camera_id, obs.zone_id, rule.event_type)
        cooldown_until = self._cooldowns.get(cooldown_key)
        if cooldown_until and obs.timestamp < cooldown_until:
            return None

        event = self._event_repo.create(
            event_type=rule.event_type,
            camera_id=camera_id,
            zone_id=obs.zone_id,
            track_id=obs.track_id,
            severity=rule.severity,
            confidence=obs.confidence,
            metadata={
                "zone_name": zone.name if zone else None,
                "zone_type": zone.type if zone else None,
                "track_class": obs.track_id is not None and "person",
            },
            started_at=obs.timestamp.isoformat(),
        )

        active = ActiveEvent(
            event=event,
            event_key=event_key,
            started_at=obs.timestamp,
        )
        self._active_events[event_key] = active
        # Start dwell timer for this track+zone (base key)
        self._dwell_timers[event_key] = obs.timestamp

        logger.info(
            "Event created",
            extra={
                "event_id": event.id,
                "event_type": event.type,
                "camera_id": camera_id,
                "track_id": obs.track_id,
                "zone_id": obs.zone_id,
                "severity": event.severity,
            },
        )
        return event

    def _handle_zone_exit(
        self,
        event_key: str,
        camera_id: str,
        obs: Observation,
        rule: EventRule,
    ) -> list[Event]:
        active = self._active_events.pop(event_key, None)
        if not active:
            return []

        # Stop dwell timer
        self._dwell_timers.pop(event_key, None)

        ended_at = obs.timestamp.isoformat()
        duration = max(0.0, (obs.timestamp - active.started_at).total_seconds())

        event = self._event_repo.close(
            active.event.id,
            ended_at=ended_at,
            duration=duration,
        )
        cooldown_key = self._make_cooldown_key(camera_id, obs.zone_id, active.event.type)
        self._cooldowns[cooldown_key] = obs.timestamp + timedelta(
            seconds=max(0.0, rule.cooldown_seconds)
        )

        closed_events = [event] if event is not None else []

        dwell_key = f"{event_key}:dwell"
        dwell_active = self._active_events.pop(dwell_key, None)
        if dwell_active is not None:
            dwell_duration = max(
                0.0, (obs.timestamp - dwell_active.started_at).total_seconds()
            )
            dwell_event = self._event_repo.close(
                dwell_active.event.id,
                ended_at=ended_at,
                duration=dwell_duration,
            )
            if dwell_event is not None:
                closed_events.append(dwell_event)

        logger.info(
            "Event closed",
            extra={
                "event_id": event.id if event else None,
                "camera_id": camera_id,
                "track_id": obs.track_id,
                "zone_id": obs.zone_id,
                "duration": round(duration, 2),
            },
        )
        return closed_events

    def _handle_dwell(
        self,
        event_key: str,
        camera_id: str,
        obs: Observation,
        rule: EventRule,
        zone: Zone | None,
    ) -> Event | None:
        """Handle dwell time for restricted zone presence."""
        started = self._dwell_timers.get(event_key)
        if started is None:
            return None

        elapsed = max(0.0, (obs.timestamp - started).total_seconds())
        if elapsed >= rule.duration_threshold_seconds:
            # Dwell threshold reached — create dwell event if not exists
            # Use a separate key for dwell events to avoid conflict with entry event
            dwell_key = f"{event_key}:dwell"
            if dwell_key not in self._active_events:
                event = self._event_repo.create(
                    event_type=rule.event_type,
                    camera_id=camera_id,
                    zone_id=obs.zone_id,
                    track_id=obs.track_id,
                    severity=rule.severity,
                    confidence=obs.confidence,
                    metadata={
                        "zone_name": zone.name if zone else None,
                        "zone_type": zone.type if zone else None,
                        "dwell_seconds": round(elapsed, 1),
                    },
                    started_at=started.isoformat(),
                )
                active = ActiveEvent(
                    event=event,
                    event_key=dwell_key,
                    started_at=started,
                )
                self._active_events[dwell_key] = active

                logger.info(
                    "Dwell event created",
                    extra={
                        "event_id": event.id,
                        "camera_id": camera_id,
                        "track_id": obs.track_id,
                        "zone_id": obs.zone_id,
                        "dwell_seconds": round(elapsed, 1),
                    },
                )
                return event

        return None

    def mark_camera_unknown(self, camera_id: str, reason: str) -> None:
        """Stop in-memory continuity without fabricating a physical zone exit."""
        with self._lock:
            keys = [
                key for key in self._active_events if key.startswith(f"{camera_id}:")
            ]
            observed_at = datetime.now(timezone.utc).isoformat()
            for key in keys:
                active = self._active_events.pop(key)
                self._event_repo.update_status(
                    active.event.id,
                    active.event.status,
                    metadata_update={
                        "knowledge_state": "UNKNOWN",
                        "uncertainty_reason": reason,
                        "last_observed_at": observed_at,
                    },
                )
                self._dwell_timers.pop(key.removesuffix(":dwell"), None)

    def close_camera_events(self, camera_id: str) -> None:
        self.mark_camera_unknown(camera_id, "camera_observation_unavailable")

    def get_active_events(self, camera_id: str | None = None) -> list[ActiveEvent]:
        with self._lock:
            if camera_id:
                return [
                    event
                    for key, event in self._active_events.items()
                    if key.startswith(f"{camera_id}:")
                ]
            return list(self._active_events.values())

    def attach_evidence(self, event_id: str, metadata: dict) -> Event | None:
        with self._lock:
            event = self._event_repo.get(event_id)
            if event is None:
                return None
            updated = self._event_repo.update_status(
                event_id,
                event.status,
                metadata_update=metadata,
            )
            if updated is None:
                return None
            for active in self._active_events.values():
                if active.event.id == event_id:
                    active.event = updated
            return updated
