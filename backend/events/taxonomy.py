from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OperationalCategory:
    id: str
    label: str
    description: str
    default_severity: str
    attention_threshold_count: int
    attention_threshold_seconds: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "default_severity": self.default_severity,
            "attention_threshold_count": self.attention_threshold_count,
            "attention_threshold_seconds": self.attention_threshold_seconds,
        }


OPERATIONAL_CATEGORIES: dict[str, OperationalCategory] = {
    "waiting": OperationalCategory(
        id="waiting",
        label="Waiting",
        description="Person, station, material, or machine is waiting for the next operational step.",
        default_severity="attention",
        attention_threshold_count=3,
        attention_threshold_seconds=30 * 60,
    ),
    "idle": OperationalCategory(
        id="idle",
        label="Idle",
        description="Person or machine is present but inactive longer than expected.",
        default_severity="attention",
        attention_threshold_count=3,
        attention_threshold_seconds=20 * 60,
    ),
    "blocked": OperationalCategory(
        id="blocked",
        label="Blocked",
        description="Work cannot continue because access, flow, machine, or material is blocked.",
        default_severity="attention",
        attention_threshold_count=2,
        attention_threshold_seconds=10 * 60,
    ),
    "unsafe_presence": OperationalCategory(
        id="unsafe_presence",
        label="Unsafe presence",
        description="Person entered or remained in an unsafe or restricted area.",
        default_severity="critical",
        attention_threshold_count=1,
        attention_threshold_seconds=0,
    ),
    "missing_operator": OperationalCategory(
        id="missing_operator",
        label="Missing operator",
        description="A machine, line, or station needs an operator and no person is present.",
        default_severity="attention",
        attention_threshold_count=2,
        attention_threshold_seconds=10 * 60,
    ),
    "manual_rework": OperationalCategory(
        id="manual_rework",
        label="Manual rework",
        description="Manual correction or repeated handling suggests rework.",
        default_severity="attention",
        attention_threshold_count=2,
        attention_threshold_seconds=15 * 60,
    ),
    "queue_growth": OperationalCategory(
        id="queue_growth",
        label="Queue growth",
        description="Queue or accumulation is growing around a station or process.",
        default_severity="attention",
        attention_threshold_count=2,
        attention_threshold_seconds=10 * 60,
    ),
    "machine_starved": OperationalCategory(
        id="machine_starved",
        label="Machine starved",
        description="Machine is ready but lacks material, input, or upstream supply.",
        default_severity="attention",
        attention_threshold_count=2,
        attention_threshold_seconds=15 * 60,
    ),
    "machine_blocked": OperationalCategory(
        id="machine_blocked",
        label="Machine blocked",
        description="Machine cannot output or continue because downstream flow is blocked.",
        default_severity="attention",
        attention_threshold_count=2,
        attention_threshold_seconds=15 * 60,
    ),
    "other": OperationalCategory(
        id="other",
        label="Other",
        description="Operational event that has not been mapped to a standard category yet.",
        default_severity="info",
        attention_threshold_count=3,
        attention_threshold_seconds=30 * 60,
    ),
}


EVENT_TYPE_CATEGORY_MAP = {
    "PERSON_RESTRICTED_ZONE": "unsafe_presence",
    "PERSON_RESTRICTED_ZONE_DWELL": "unsafe_presence",
    "PERSON_MONITORED_ZONE": "other",
    "MACHINE_WAITING": "waiting",
    "WAITING_AT_STATION": "waiting",
    "PERSON_IDLE": "idle",
    "MACHINE_IDLE": "idle",
    "MACHINE_STATIONARY": "idle",
    "MACHINE_BLOCKED": "machine_blocked",
    "MACHINE_STARVED": "machine_starved",
    "MISSING_OPERATOR": "missing_operator",
    "MANUAL_REWORK": "manual_rework",
    "QUEUE_GROWTH": "queue_growth",
}


KEYWORD_CATEGORY_MAP = (
    ("unsafe_presence", ("restricted", "unsafe", "danger", "risco", "restrita")),
    ("waiting", ("waiting", "wait", "espera", "aguardando")),
    ("idle", ("idle", "stationary", "parada", "ocioso", "inativo")),
    ("machine_blocked", ("blocked", "bloqueada", "bloqueado", "travada", "travado")),
    ("machine_starved", ("starved", "sem material", "falta material", "abastecimento")),
    ("missing_operator", ("missing operator", "sem operador", "operador ausente")),
    ("manual_rework", ("rework", "retrabalho", "correcao", "correção")),
    ("queue_growth", ("queue", "fila", "acumulo", "acúmulo")),
)


def list_operational_categories() -> list[dict[str, Any]]:
    return [category.as_dict() for category in OPERATIONAL_CATEGORIES.values()]


def normalize_category(category_id: Any) -> str:
    if not isinstance(category_id, str):
        return "other"
    normalized = category_id.strip().lower().replace("-", "_").replace(" ", "_")
    return normalized if normalized in OPERATIONAL_CATEGORIES else "other"


def classify_operational_category(
    *,
    event_type: str,
    activity_type: Any = None,
    activity_label: Any = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    metadata = metadata or {}
    explicit = (
        metadata.get("operational_category")
        or metadata.get("category")
        or metadata.get("activity_category")
    )
    if explicit:
        return normalize_category(explicit)

    mapped = EVENT_TYPE_CATEGORY_MAP.get(str(event_type).upper())
    if mapped:
        return mapped

    text = f"{event_type or ''} {activity_type or ''} {activity_label or ''}".lower()
    for category_id, keywords in KEYWORD_CATEGORY_MAP:
        if any(keyword in text for keyword in keywords):
            return category_id
    return "other"


def get_category_config(category_id: str) -> OperationalCategory:
    return OPERATIONAL_CATEGORIES.get(normalize_category(category_id), OPERATIONAL_CATEGORIES["other"])
