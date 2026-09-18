from __future__ import annotations

import hashlib
import base64
import json
import mimetypes
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from app.operational_understanding import validate_normalize_and_persist_understanding
from app.operational_read_model import ReadModelFilters, video_context_by_id


VIDEO_UNDERSTANDING_SCHEMA_VERSION = "video_understanding_v1"
VIDEO_UNDERSTANDING_PROMPT_VERSION = "video_understanding_v1"
DEFAULT_OPENAI_VIDEO_UNDERSTANDING_MODEL = "gpt-5.6-terra"
DEFAULT_OPENAI_IMAGE_DETAIL = "high"
DEFAULT_MAX_TOTAL_EVIDENCE = 8
DEFAULT_MAX_EVIDENCE_PER_PHASE = 2
PHASE_ORDER = ("before", "transition", "during", "after")
SUPPORTED_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}

VIDEO_UNDERSTANDING_SYSTEM_PROMPT = """You are Campex's operational visual understanding adapter.

Analyze only the supplied Operational Video Context and selected evidence images.

Rules:
- Describe only what is visually supported by the provided images.
- Keep canonical known facts separate from visual facts.
- Never replace machine_state, person_presence, events, timeline, or anomalies supplied by Campex.
- Never infer cause, intent, blame, responsibility, mechanical diagnosis, employee identity, emotion, or productivity.
- Correlation is not cause.
- If evidence is insufficient, partially occluded, missing for a phase, or visually ambiguous, say so as uncertainty.
- Absence of evidence is not evidence of absence.
- Every visual fact, scene change, and observed action based on images must cite evidence_refs from the request.
- Return only the structured schema.
"""

VIDEO_UNDERSTANDING_RESULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "understanding_id",
        "context_id",
        "summary",
        "visual_facts",
        "scene_changes",
        "observed_entities",
        "observed_actions",
        "uncertainties",
        "evidence_refs",
        "model_metadata",
        "cause_inferred",
    ],
    "properties": {
        "understanding_id": {"type": "string"},
        "context_id": {"type": "string"},
        "summary": {"type": "string"},
        "visual_facts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["type", "description", "phase", "evidence_refs"],
                "properties": {
                    "type": {"type": "string"},
                    "description": {"type": "string"},
                    "phase": {"type": "string", "enum": ["before", "transition", "during", "after", "unknown"]},
                    "evidence_refs": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "scene_changes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["description", "phase", "evidence_refs"],
                "properties": {
                    "description": {"type": "string"},
                    "phase": {"type": "string", "enum": ["before", "transition", "during", "after", "unknown"]},
                    "evidence_refs": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "observed_entities": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["entity_type", "description", "phase", "evidence_refs"],
                "properties": {
                    "entity_type": {"type": "string"},
                    "description": {"type": "string"},
                    "phase": {"type": "string", "enum": ["before", "transition", "during", "after", "unknown"]},
                    "evidence_refs": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "observed_actions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["action_type", "description", "phase", "evidence_refs"],
                "properties": {
                    "action_type": {"type": "string"},
                    "description": {"type": "string"},
                    "phase": {"type": "string", "enum": ["before", "transition", "during", "after", "unknown"]},
                    "evidence_refs": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "uncertainties": {"type": "array", "items": {"type": "string"}},
        "evidence_refs": {"type": "array", "items": {"type": "string"}},
        "model_metadata": {
            "type": "object",
            "additionalProperties": False,
            "required": ["provider", "model", "schema_version", "prompt_version", "analyzed_at"],
            "properties": {
                "provider": {"type": "string"},
                "model": {"type": "string"},
                "schema_version": {"type": "string"},
                "prompt_version": {"type": "string"},
                "analyzed_at": {"type": "string"},
            },
        },
        "cause_inferred": {"type": "boolean"},
    },
}


class VideoUnderstandingError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class VideoUnderstandingProviderUnavailable(VideoUnderstandingError):
    def __init__(self) -> None:
        super().__init__("VIDEO_UNDERSTANDING_PROVIDER_NOT_CONFIGURED", "Provider de Video Understanding nao configurado.")


class VideoUnderstandingProviderError(VideoUnderstandingError):
    pass


class VideoUnderstandingMediaError(VideoUnderstandingError):
    pass


class VideoUnderstandingProvider(Protocol):
    def analyze(self, request: dict[str, Any]) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class EvidenceSelectionConfig:
    max_total_evidence: int = DEFAULT_MAX_TOTAL_EVIDENCE
    max_evidence_per_phase: int = DEFAULT_MAX_EVIDENCE_PER_PHASE


class DeterministicFakeVideoUnderstandingProvider:
    provider_name = "fake"
    model_name = "fake-video-understanding-v1"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def analyze(self, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(request)
        evidence_refs = [item["evidence_ref"] for item in request.get("evidence") or []]
        visual_facts = [
            {
                "type": "evidence_available",
                "description": f"Evidencia visual selecionada para a fase {item['phase']}.",
                "phase": item["phase"],
                "evidence_refs": [item["evidence_ref"]],
            }
            for item in request.get("evidence") or []
        ]
        if not visual_facts:
            visual_facts = []
        phases = sorted({item["phase"] for item in request.get("evidence") or []})
        return {
            "understanding_id": "vu-" + hashlib.sha256(request["request_id"].encode("utf-8")).hexdigest()[:24],
            "context_id": request["context_id"],
            "summary": "Resultado fake deterministico para validar o contrato de Video Understanding.",
            "visual_facts": visual_facts,
            "scene_changes": [
                {
                    "description": fact.get("description"),
                    "phase": fact.get("phase"),
                    "evidence_refs": fact.get("evidence_refs"),
                }
                for fact in visual_facts
            ],
            "observed_entities": [],
            "observed_actions": [],
            "uncertainties": [] if evidence_refs else ["Nenhuma evidencia visual selecionada para este contexto."],
            "evidence_refs": evidence_refs,
            "model_metadata": {
                "provider": self.provider_name,
                "model": self.model_name,
                "schema_version": VIDEO_UNDERSTANDING_SCHEMA_VERSION,
                "analyzed_at": _now_iso(),
            },
            "cause_inferred": False,
        }


@dataclass
class OpenAIVideoUnderstandingProvider:
    api_key: str | None = None
    model: str | None = None
    image_detail: str | None = None
    timeout_seconds: float = 45.0
    client: Any | None = None

    def __post_init__(self) -> None:
        self.api_key = self.api_key or os.getenv("OPENAI_API_KEY")
        self.model = self.model or os.getenv("OPENAI_VIDEO_UNDERSTANDING_MODEL") or DEFAULT_OPENAI_VIDEO_UNDERSTANDING_MODEL
        self.image_detail = self.image_detail or os.getenv("OPENAI_VIDEO_UNDERSTANDING_IMAGE_DETAIL") or DEFAULT_OPENAI_IMAGE_DETAIL
        if self.image_detail not in {"low", "high", "auto"}:
            raise VideoUnderstandingProviderError("VIDEO_UNDERSTANDING_INVALID_IMAGE_DETAIL", "OPENAI_VIDEO_UNDERSTANDING_IMAGE_DETAIL invalido.")

    def _client(self) -> Any:
        if self.client is not None:
            return self.client
        if not self.api_key:
            raise VideoUnderstandingProviderUnavailable()
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise VideoUnderstandingProviderUnavailable() from exc
        return OpenAI(api_key=self.api_key, timeout=self.timeout_seconds)

    def analyze(self, request: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key and self.client is None:
            raise VideoUnderstandingProviderUnavailable()
        started = time.monotonic()
        input_payload = _provider_request_payload(request, self.image_detail or DEFAULT_OPENAI_IMAGE_DETAIL)
        try:
            response = self._client().responses.create(
                model=self.model,
                store=False,
                input=input_payload,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "campex_video_understanding_result",
                        "schema": VIDEO_UNDERSTANDING_RESULT_SCHEMA,
                        "strict": True,
                    }
                },
            )
        except VideoUnderstandingError:
            raise
        except Exception as exc:
            raise _map_openai_error(exc) from exc
        raw_output = _extract_response_text(response)
        try:
            result = json.loads(raw_output)
        except json.JSONDecodeError as exc:
            raise VideoUnderstandingProviderError("VIDEO_UNDERSTANDING_INVALID_OUTPUT", "Provider retornou JSON invalido.") from exc
        if not isinstance(result, dict):
            raise VideoUnderstandingProviderError("VIDEO_UNDERSTANDING_INVALID_OUTPUT", "Provider retornou objeto invalido.")
        metadata = result.setdefault("model_metadata", {})
        metadata.update(
            {
                "provider": "openai",
                "model": self.model,
                "schema_version": VIDEO_UNDERSTANDING_SCHEMA_VERSION,
                "prompt_version": VIDEO_UNDERSTANDING_PROMPT_VERSION,
                "analyzed_at": metadata.get("analyzed_at") or _now_iso(),
                "duration_ms": round((time.monotonic() - started) * 1000, 3),
                "provider_request_id": getattr(response, "id", None),
                "usage": _usage_metadata(response),
            }
        )
        return result


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_request_id() -> str:
    return "vur-" + uuid.uuid4().hex


def _evidence_key(ref: dict[str, Any]) -> str:
    return str(ref.get("path") or ref.get("evidence_ref") or ref)


def _extract_response_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if output_text:
        return str(output_text)
    try:
        return str(response.output[0].content[0].text)
    except Exception as exc:
        raise VideoUnderstandingProviderError("VIDEO_UNDERSTANDING_EMPTY_RESPONSE", "Provider retornou resposta vazia.") from exc


def _usage_metadata(response: Any) -> dict[str, Any]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    if isinstance(usage, dict):
        return {key: usage.get(key) for key in ("input_tokens", "output_tokens", "total_tokens") if usage.get(key) is not None}
    return {
        key: getattr(usage, key, None)
        for key in ("input_tokens", "output_tokens", "total_tokens")
        if getattr(usage, key, None) is not None
    }


def _media_path(path: str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    return candidate


def _image_data_url(media_path: str) -> tuple[str, str]:
    path = _media_path(media_path)
    if not path.exists() or not path.is_file():
        raise VideoUnderstandingMediaError("VIDEO_UNDERSTANDING_MEDIA_NOT_FOUND", "Evidencia visual nao encontrada.")
    mime_type = mimetypes.guess_type(str(path))[0]
    if mime_type not in SUPPORTED_IMAGE_MIME_TYPES:
        raise VideoUnderstandingMediaError("VIDEO_UNDERSTANDING_MEDIA_UNSUPPORTED", "Formato de evidencia visual nao suportado.")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}", mime_type


def _provider_request_payload(request: dict[str, Any], image_detail: str) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [
        {
            "type": "input_text",
            "text": json.dumps(
                {
                    "schema_version": request["schema_version"],
                    "context_id": request["context_id"],
                    "operational_context": request["operational_context"],
                    "constraints": request["constraints"],
                    "evidence_manifest": [
                        {
                            "evidence_ref": item["evidence_ref"],
                            "phase": item["phase"],
                            "timestamp": item["timestamp"],
                            "source_fact_type": item["source_fact_type"],
                        }
                        for item in request.get("evidence") or []
                    ],
                    "instruction": "Use evidence_ref values exactly as supplied. Do not invent cause or responsibility.",
                },
                ensure_ascii=False,
            ),
        }
    ]
    for item in request.get("evidence") or []:
        data_url, mime_type = _image_data_url(str(item.get("media_path") or ""))
        content.append(
            {
                "type": "input_text",
                "text": f"EVIDENCE_REF={item['evidence_ref']} PHASE={item['phase']} TIMESTAMP={item.get('timestamp')} MIME={mime_type}",
            }
        )
        content.append({"type": "input_image", "image_url": data_url, "detail": image_detail})
    return [{"role": "system", "content": VIDEO_UNDERSTANDING_SYSTEM_PROMPT}, {"role": "user", "content": content}]


def _map_openai_error(exc: Exception) -> VideoUnderstandingProviderError:
    name = exc.__class__.__name__.lower()
    message = str(exc).lower()
    if "timeout" in name or "timeout" in message:
        return VideoUnderstandingProviderError("VIDEO_UNDERSTANDING_TIMEOUT", "Timeout ao chamar provider multimodal.")
    if "authentication" in name or "unauthorized" in message or "api key" in message:
        return VideoUnderstandingProviderError("VIDEO_UNDERSTANDING_AUTH_ERROR", "Autenticacao do provider multimodal falhou.")
    if "ratelimit" in name or "rate limit" in message or "429" in message:
        return VideoUnderstandingProviderError("VIDEO_UNDERSTANDING_RATE_LIMIT", "Rate limit do provider multimodal.")
    status_code = getattr(exc, "status_code", None)
    if status_code and 400 <= int(status_code) < 500:
        return VideoUnderstandingProviderError("VIDEO_UNDERSTANDING_PROVIDER_4XX", "Provider multimodal recusou a requisicao.")
    if status_code and int(status_code) >= 500:
        return VideoUnderstandingProviderError("VIDEO_UNDERSTANDING_PROVIDER_5XX", "Provider multimodal indisponivel.")
    if "server" in name or "5" in message:
        return VideoUnderstandingProviderError("VIDEO_UNDERSTANDING_PROVIDER_5XX", "Provider multimodal indisponivel.")
    return VideoUnderstandingProviderError("VIDEO_UNDERSTANDING_PROVIDER_ERROR", "Falha controlada no provider multimodal.")


def select_evidence(video_context: dict[str, Any], config: EvidenceSelectionConfig | None = None) -> list[dict[str, Any]]:
    config = config or EvidenceSelectionConfig()
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    phases = video_context.get("phases") if isinstance(video_context.get("phases"), dict) else {}
    for phase in PHASE_ORDER:
        phase_items = phases.get(phase) or []
        phase_count = 0
        for fact in phase_items:
            for ref in fact.get("evidence_refs") or []:
                key = _evidence_key(ref)
                if key in seen or not key:
                    continue
                if phase_count >= config.max_evidence_per_phase or len(selected) >= config.max_total_evidence:
                    break
                seen.add(key)
                phase_count += 1
                selected.append(
                    {
                        "evidence_ref": key,
                        "phase": phase,
                        "timestamp": fact.get("timestamp"),
                        "media_path": ref.get("path") if isinstance(ref, dict) else key,
                        "source_fact_type": fact.get("type"),
                    }
                )
            if phase_count >= config.max_evidence_per_phase or len(selected) >= config.max_total_evidence:
                break
        if len(selected) >= config.max_total_evidence:
            break
    return selected


def build_understanding_request(
    video_context: dict[str, Any],
    *,
    evidence_config: EvidenceSelectionConfig | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    selected_evidence = select_evidence(video_context, evidence_config)
    known_facts = []
    for observation in video_context.get("observations") or []:
        known_facts.append(
            {
                "timestamp": observation.get("timestamp"),
                "type": observation.get("type"),
                "description": observation.get("description"),
                "previous_state": observation.get("previous_state"),
                "new_state": observation.get("new_state"),
                "data_quality": observation.get("data_quality"),
                "confidence": observation.get("confidence"),
                "event_uuid": observation.get("event_uuid"),
            }
        )
    return {
        "request_id": request_id or _new_request_id(),
        "context_id": video_context["context_id"],
        "schema_version": VIDEO_UNDERSTANDING_SCHEMA_VERSION,
        "operational_context": {
            "asset_id": video_context.get("asset_id"),
            "camera_id": video_context.get("camera_id"),
            "trigger": video_context.get("trigger"),
            "start_ts": video_context.get("start_ts"),
            "end_ts": video_context.get("end_ts"),
            "known_facts": known_facts,
            "data_quality": video_context.get("data_quality"),
        },
        "evidence": selected_evidence,
        "constraints": {
            "infer_cause": False,
            "infer_intent": False,
            "assign_responsibility": False,
            "identify_people": False,
            "replace_canonical_facts": False,
        },
    }


def validate_understanding_result(result: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise VideoUnderstandingProviderError("VIDEO_UNDERSTANDING_INVALID_OUTPUT", "Resultado deve ser um objeto.")
    required = {
        "understanding_id",
        "context_id",
        "summary",
        "visual_facts",
        "scene_changes",
        "observed_entities",
        "observed_actions",
        "uncertainties",
        "evidence_refs",
        "model_metadata",
        "cause_inferred",
    }
    missing = required - set(result)
    if missing:
        raise VideoUnderstandingProviderError("VIDEO_UNDERSTANDING_INVALID_OUTPUT", f"Resultado sem campos obrigatorios: {sorted(missing)}")
    if result["context_id"] != request["context_id"]:
        raise VideoUnderstandingProviderError("VIDEO_UNDERSTANDING_INVALID_OUTPUT", "context_id do resultado nao corresponde ao request.")
    if result["understanding_id"] in {request["context_id"], request["request_id"]}:
        raise VideoUnderstandingProviderError("VIDEO_UNDERSTANDING_INVALID_OUTPUT", "understanding_id deve ser distinto de context_id e request_id.")
    if result.get("cause_inferred") is not False:
        raise VideoUnderstandingProviderError("VIDEO_UNDERSTANDING_INVALID_OUTPUT", "Video Understanding nao pode inferir causa.")
    for field in ("visual_facts", "scene_changes", "observed_entities", "observed_actions", "uncertainties", "evidence_refs"):
        if not isinstance(result.get(field), list):
            raise VideoUnderstandingProviderError("VIDEO_UNDERSTANDING_INVALID_OUTPUT", f"{field} invalido.")
    request_evidence = {item["evidence_ref"] for item in request.get("evidence") or []}
    grounded_fields = ("visual_facts", "scene_changes", "observed_entities", "observed_actions")
    for field in grounded_fields:
        for fact in result.get(field) or []:
            if not isinstance(fact, dict):
                raise VideoUnderstandingProviderError("VIDEO_UNDERSTANDING_INVALID_OUTPUT", f"{field} invalido.")
            refs = fact.get("evidence_refs")
            if not isinstance(refs, list) or not refs:
                raise VideoUnderstandingProviderError("VIDEO_UNDERSTANDING_INVALID_OUTPUT", f"{field} sem evidence_refs.")
            if not set(refs).issubset(request_evidence):
                raise VideoUnderstandingProviderError("VIDEO_UNDERSTANDING_INVALID_OUTPUT", f"{field} referencia evidencia fora do request.")
    for ref in result.get("evidence_refs") or []:
        if ref not in request_evidence:
            raise VideoUnderstandingProviderError("VIDEO_UNDERSTANDING_INVALID_OUTPUT", "Resultado referencia evidencia fora do request.")
    for fact in result.get("visual_facts") or []:
        if not isinstance(fact, dict):
            raise VideoUnderstandingProviderError("VIDEO_UNDERSTANDING_INVALID_OUTPUT", "visual_fact invalido.")
        refs = fact.get("evidence_refs")
        if refs and not set(refs).issubset(request_evidence):
            raise VideoUnderstandingProviderError("VIDEO_UNDERSTANDING_INVALID_OUTPUT", "visual_fact referencia evidencia fora do request.")
    metadata = result.get("model_metadata")
    if not isinstance(metadata, dict) or metadata.get("schema_version") != VIDEO_UNDERSTANDING_SCHEMA_VERSION:
        raise VideoUnderstandingProviderError("VIDEO_UNDERSTANDING_INVALID_OUTPUT", "model_metadata/schema_version invalido.")
    return result


def provider_from_environment() -> VideoUnderstandingProvider:
    provider_name = (os.getenv("CAMPEX_VIDEO_UNDERSTANDING_PROVIDER") or os.getenv("VIDEO_UNDERSTANDING_PROVIDER") or "").strip().lower()
    if provider_name in {"fake", "stub"}:
        return DeterministicFakeVideoUnderstandingProvider()
    if provider_name == "openai":
        return OpenAIVideoUnderstandingProvider()
    raise VideoUnderstandingProviderUnavailable()


@dataclass
class VideoUnderstandingService:
    provider: VideoUnderstandingProvider | None = None
    evidence_config: EvidenceSelectionConfig = field(default_factory=EvidenceSelectionConfig)

    def analyze_context(
        self,
        connection: Any,
        filters: ReadModelFilters,
        context_id: str,
    ) -> dict[str, Any]:
        video_context = video_context_by_id(connection, filters, context_id)
        if video_context is None:
            raise VideoUnderstandingError("VIDEO_CONTEXT_NOT_FOUND", "Contexto de video nao encontrado.")
        request = build_understanding_request(video_context, evidence_config=self.evidence_config)
        provider = self.provider or provider_from_environment()
        try:
            result = provider.analyze(request)
        except VideoUnderstandingError:
            raise
        except Exception as exc:
            raise VideoUnderstandingProviderError("VIDEO_UNDERSTANDING_PROVIDER_ERROR", "Falha controlada no provider de Video Understanding.") from exc
        validated = validate_normalize_and_persist_understanding(
            connection,
            video_context=video_context,
            request=request,
            result=result,
        )
        return {
            "status": "ok",
            "request": request,
            "result": validated["structured_result"],
            "validated_understanding": validated,
            "video_context": video_context,
        }
