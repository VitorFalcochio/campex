from __future__ import annotations

import logging
from typing import Any

from backend.config import get_settings
from backend.integrations.nemotron import NemotronClient
from backend.services.intelligence.exceptions import IntelligenceError
from backend.services.intelligence.models import IntelligenceRequest
from backend.services.intelligence.service import CampexIntelligenceService


logger = logging.getLogger("campex.nemotron")


SYSTEM_GUIDANCE = """Voce e o analista operacional da CAMPEX.
Analise exclusivamente os dados fornecidos.
Nunca invente pessoas, horarios, eventos, causas ou numeros.
Diferencie observacao de interpretacao.
Nao afirme que uma pessoa estava trabalhando, improdutiva, distraida ou ociosa apenas porque permaneceu parada.
Use linguagem objetiva e empresarial.
Quando nao houver dados suficientes, diga explicitamente que nao ha dados suficientes."""




def analyze_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    return _ask("Analise os eventos operacionais CAMPEX fornecidos.", {"events": events})


def generate_operational_summary(metrics: dict[str, Any]) -> dict[str, Any]:
    return _ask("Gere um resumo operacional objetivo a partir das metricas.", {"metrics": metrics})


def analyze_anomalies(events: list[dict[str, Any]], metrics: dict[str, Any]) -> dict[str, Any]:
    return _ask(
        "Identifique apenas anomalias sustentadas pelos dados estruturados.",
        {"events": events, "metrics": metrics},
    )


def generate_daily_report(data: dict[str, Any]) -> dict[str, Any]:
    return _ask(
        "Gere um relatorio operacional CAMPEX com resumo, movimentacao, entradas, saidas, permanencia, tempo sem deslocamento, zonas, eventos relevantes e observacoes.",
        data,
    )


def generate_alert(event: dict[str, Any]) -> dict[str, Any]:
    return _ask("Gere um alerta operacional curto para este evento observado.", {"event": event})


def _ask(query: str, context: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    if not settings.nvidia_api_key or not settings.intelligence_enabled:
        return _fallback("Nemotron indisponivel ou NVIDIA_API_KEY ausente.")

    service = CampexIntelligenceService(NemotronClient(settings))
    try:
        response = service.ask(
            IntelligenceRequest(
                organization_id=settings.intelligence_default_organization_id,
                query=f"{SYSTEM_GUIDANCE}\n\n{query}",
                context=context,
            )
        )
    except IntelligenceError as exc:
        logger.warning("[CAMPEX][NEMOTRON] unavailable: %s", exc)
        return _fallback(str(exc))
    except Exception as exc:
        logger.exception("[CAMPEX][NEMOTRON] unexpected failure")
        return _fallback("Falha inesperada ao consultar o Nemotron.")

    return {
        "available": True,
        "summary": response.answer,
        "model": response.model,
        "limitations": response.limitations,
        "fallback": False,
    }


def _fallback(reason: str) -> dict[str, Any]:
    return {
        "available": False,
        "summary": "Analise operacional por IA indisponivel. O processamento de video continua ativo com eventos e metricas deterministicas.",
        "model": None,
        "limitations": [reason],
        "fallback": True,
    }
