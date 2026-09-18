from __future__ import annotations

from dataclasses import dataclass
from typing import Final


EVENT_FAMILY_INTERRUPTION: Final = "interruption"
EVENT_FAMILY_WAIT: Final = "wait"
EVENT_FAMILY_FLOW: Final = "flow"
EVENT_FAMILY_ABSENCE: Final = "absence"
EVENT_FAMILY_VISUAL: Final = "visual"
EVENT_FAMILY_UNKNOWN: Final = "unknown"

OFFICIAL_EVENT_FAMILIES: Final = {
    EVENT_FAMILY_INTERRUPTION,
    EVENT_FAMILY_WAIT,
    EVENT_FAMILY_FLOW,
    EVENT_FAMILY_ABSENCE,
    EVENT_FAMILY_VISUAL,
}


@dataclass(frozen=True)
class EventTaxonomy:
    event_family: str
    event_subtype: str | None = None


EVENT_TAXONOMY: Final[dict[str, EventTaxonomy]] = {
    "machine_stoppage": EventTaxonomy(EVENT_FAMILY_INTERRUPTION, "machine_stoppage"),
    "machine_stopped_with_operator": EventTaxonomy(EVENT_FAMILY_INTERRUPTION, "stopped_with_operator"),
    "repeated_microstops": EventTaxonomy(EVENT_FAMILY_INTERRUPTION, "microstops"),
    "machine_running_without_operator": EventTaxonomy(EVENT_FAMILY_ABSENCE, "running_without_operator"),
    "workstation_unattended": EventTaxonomy(EVENT_FAMILY_ABSENCE, "work_area_unattended"),
    "visual_occurrence": EventTaxonomy(EVENT_FAMILY_VISUAL, "visual_occurrence"),
}


def classify_event_type(event_type: str | None) -> EventTaxonomy:
    if not event_type:
        return EventTaxonomy(EVENT_FAMILY_UNKNOWN, None)
    return EVENT_TAXONOMY.get(str(event_type), EventTaxonomy(EVENT_FAMILY_UNKNOWN, None))


def known_event_types() -> list[str]:
    return sorted(EVENT_TAXONOMY)
