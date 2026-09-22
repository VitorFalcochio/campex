from __future__ import annotations

import logging
from typing import Any

from backend.config import get_settings
from backend.integrations.nemotron import NemotronClient
from backend.services.intelligence.exceptions import IntelligenceError
from backend.services.intelligence.service import (
    CampexIntelligenceService,
    build_deterministic_report,
    normalize_operational_context,
)


logger = logging.getLogger("campex.nemotron")


SYSTEM_GUIDANCE = """Voce e o analista operacional da CAMPEX.
Analise exclusivamente os dados fornecidos.
Nunca invente pessoas, horarios, eventos, causas ou numeros.
Diferencie observacao de interpretacao.
Nao afirme que uma pessoa estava trabalhando, improdutiva, distraida ou ociosa apenas porque permaneceu parada.
Use linguagem objetiva e empresarial.
Quando nao houver dados suficientes, diga explicitamente que nao ha dados suficientes."""




def analyze_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    return _report({"events": events})


def generate_operational_summary(metrics: dict[str, Any]) -> dict[str, Any]:
    return _report({"metrics": metrics})


def analyze_anomalies(events: list[dict[str, Any]], metrics: dict[str, Any]) -> dict[str, Any]:
    return _report({"events": events, "metrics": metrics})


def generate_daily_report(data: dict[str, Any]) -> dict[str, Any]:
    return _report(data)


def generate_alert(event: dict[str, Any]) -> dict[str, Any]:
    return _report({"events": [event]})


def _report(data: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    context = normalize_operational_context(settings.intelligence_default_organization_id, data)
    if not settings.nvidia_api_key or not settings.intelligence_enabled:
        return build_deterministic_report(
            context,
            "Nemotron indisponivel ou NVIDIA_API_KEY ausente.",
        ).as_dict()

    try:
        return CampexIntelligenceService(NemotronClient(settings)).generate_operational_report(
            organization_id=settings.intelligence_default_organization_id,
            data=data,
        ).as_dict()
    except IntelligenceError as exc:
        logger.warning("[CAMPEX][NEMOTRON] fallback activated: %s", exc)
        return build_deterministic_report(context, str(exc)).as_dict()

