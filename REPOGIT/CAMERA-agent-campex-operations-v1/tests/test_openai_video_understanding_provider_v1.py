from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.video_understanding import (
    DEFAULT_OPENAI_VIDEO_UNDERSTANDING_MODEL,
    OpenAIVideoUnderstandingProvider,
    VideoUnderstandingMediaError,
    VideoUnderstandingProviderError,
    VideoUnderstandingProviderUnavailable,
    build_understanding_request,
    validate_understanding_result,
)


class FakeResponse:
    id = "resp_fake_123"
    usage = {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30}

    def __init__(self, payload: dict):
        self.output_text = json.dumps(payload)


class FakeResponses:
    def __init__(self, payload: dict | None = None, error: Exception | None = None):
        self.payload = payload
        self.error = error
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return FakeResponse(self.payload or {})


class FakeClient:
    def __init__(self, payload: dict | None = None, error: Exception | None = None):
        self.responses = FakeResponses(payload=payload, error=error)


def _image(path: Path) -> str:
    path.write_bytes(b"\x89PNG\r\n\x1a\n")
    return str(path)


def _request(tmp_path: Path) -> dict:
    context = {
        "context_id": "ctx-openai",
        "asset_id": "asset-a6",
        "camera_id": "cam-a6",
        "trigger": {"type": "event_started", "ref": "evt-a6", "timestamp": "2026-08-07T08:10:00+00:00"},
        "start_ts": "2026-08-07T08:05:00+00:00",
        "end_ts": "2026-08-07T08:20:00+00:00",
        "data_quality": {"status": "complete"},
        "phases": {
            "before": [{"timestamp": "2026-08-07T08:05:00+00:00", "type": "machine_activity", "evidence_refs": [{"path": _image(tmp_path / "before.png")}]}],
            "transition": [{"timestamp": "2026-08-07T08:10:00+00:00", "type": "event_started", "evidence_refs": [{"path": _image(tmp_path / "transition.png")}]}],
            "during": [{"timestamp": "2026-08-07T08:15:00+00:00", "type": "person_presence", "evidence_refs": [{"path": _image(tmp_path / "during.png")}]}],
        },
        "observations": [
            {"timestamp": "2026-08-07T08:10:00+00:00", "type": "machine_activity", "description": "machine_activity mudou de ACTIVE para STOPPED.", "new_state": "STOPPED"}
        ],
    }
    return build_understanding_request(context, request_id="vur-openai-test")


def _valid_result(request: dict) -> dict:
    refs = [item["evidence_ref"] for item in request["evidence"]]
    return {
        "understanding_id": "vu-openai-test",
        "context_id": request["context_id"],
        "summary": "Pessoa visivel na fase de transicao.",
        "visual_facts": [{"type": "person_visible", "description": "Uma pessoa aparece na imagem.", "phase": "transition", "evidence_refs": [refs[1]]}],
        "scene_changes": [{"description": "A cena muda entre before e transition.", "phase": "transition", "evidence_refs": refs[:2]}],
        "observed_entities": [{"entity_type": "person", "description": "Pessoa generica visivel.", "phase": "transition", "evidence_refs": [refs[1]]}],
        "observed_actions": [{"action_type": "movement", "description": "Ha movimentacao visual.", "phase": "during", "evidence_refs": [refs[2]]}],
        "uncertainties": ["Nao determinar causa visualmente."],
        "evidence_refs": refs,
        "model_metadata": {"provider": "openai", "model": "test-model", "schema_version": "video_understanding_v1", "prompt_version": "video_understanding_v1", "analyzed_at": "2026-08-07T08:20:00+00:00"},
        "cause_inferred": False,
    }


def test_openai_provider_builds_multimodal_structured_request_with_phases_known_facts_and_constraints(tmp_path: Path) -> None:
    request = _request(tmp_path)
    client = FakeClient(payload=_valid_result(request))
    result = OpenAIVideoUnderstandingProvider(api_key="test-key", model="test-model", image_detail="high", client=client).analyze(request)
    call = client.responses.calls[0]
    user_content = call["input"][1]["content"]
    manifest = json.loads(user_content[0]["text"])

    assert call["model"] == "test-model"
    assert call["store"] is False
    assert call["text"]["format"]["type"] == "json_schema"
    assert call["text"]["format"]["strict"] is True
    assert call["text"]["format"]["schema"]["additionalProperties"] is False
    assert manifest["schema_version"] == "video_understanding_v1"
    assert manifest["operational_context"]["known_facts"][0]["new_state"] == "STOPPED"
    assert manifest["constraints"]["infer_cause"] is False
    assert [item["phase"] for item in manifest["evidence_manifest"]] == ["before", "transition", "during"]
    image_items = [item for item in user_content if item["type"] == "input_image"]
    assert len(image_items) == 3
    assert all(item["detail"] == "high" for item in image_items)
    assert all(str(item["image_url"]).startswith("data:image/png;base64,") for item in image_items)
    assert result["model_metadata"]["provider"] == "openai"
    assert result["model_metadata"]["usage"]["total_tokens"] == 30


def test_openai_provider_uses_environment_model_default_and_validates_image_detail(monkeypatch, tmp_path: Path) -> None:
    request = _request(tmp_path)
    monkeypatch.setenv("OPENAI_VIDEO_UNDERSTANDING_MODEL", "custom-model")
    provider = OpenAIVideoUnderstandingProvider(api_key="test-key", client=FakeClient(payload=_valid_result(request)))
    assert provider.model == "custom-model"
    monkeypatch.delenv("OPENAI_VIDEO_UNDERSTANDING_MODEL", raising=False)
    provider = OpenAIVideoUnderstandingProvider(api_key="test-key", client=FakeClient(payload=_valid_result(request)))
    assert provider.model == DEFAULT_OPENAI_VIDEO_UNDERSTANDING_MODEL
    monkeypatch.setenv("OPENAI_VIDEO_UNDERSTANDING_IMAGE_DETAIL", "medium")
    with pytest.raises(VideoUnderstandingProviderError):
        OpenAIVideoUnderstandingProvider(api_key="test-key")


def test_openai_provider_rejects_invented_evidence_ref_and_cause_inference(tmp_path: Path) -> None:
    request = _request(tmp_path)
    invalid_ref = _valid_result(request)
    invalid_ref["visual_facts"][0]["evidence_refs"] = ["invented.jpg"]
    with pytest.raises(VideoUnderstandingProviderError):
        validate_understanding_result(invalid_ref, request)
    invalid_cause = _valid_result(request)
    invalid_cause["cause_inferred"] = True
    with pytest.raises(VideoUnderstandingProviderError):
        validate_understanding_result(invalid_cause, request)


def test_openai_provider_media_errors_are_controlled(tmp_path: Path) -> None:
    request = _request(tmp_path)
    request["evidence"][0]["media_path"] = str(tmp_path / "missing.png")
    with pytest.raises(VideoUnderstandingMediaError) as missing:
        OpenAIVideoUnderstandingProvider(api_key="test-key", client=FakeClient(payload=_valid_result(request))).analyze(request)
    assert missing.value.code == "VIDEO_UNDERSTANDING_MEDIA_NOT_FOUND"
    bad = tmp_path / "bad.txt"
    bad.write_text("not image")
    request["evidence"][0]["media_path"] = str(bad)
    with pytest.raises(VideoUnderstandingMediaError) as unsupported:
        OpenAIVideoUnderstandingProvider(api_key="test-key", client=FakeClient(payload=_valid_result(request))).analyze(request)
    assert unsupported.value.code == "VIDEO_UNDERSTANDING_MEDIA_UNSUPPORTED"


def test_openai_provider_requires_api_key_without_injected_client(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(VideoUnderstandingProviderUnavailable):
        OpenAIVideoUnderstandingProvider().analyze({"evidence": []})


class FakeTimeout(Exception):
    pass


class FakeRateLimit(Exception):
    pass


class FakeServerError(Exception):
    status_code = 503


def test_openai_provider_maps_timeout_rate_limit_5xx_and_invalid_json(tmp_path: Path) -> None:
    request = _request(tmp_path)
    for error, code in (
        (TimeoutError("timeout"), "VIDEO_UNDERSTANDING_TIMEOUT"),
        (Exception("rate limit 429"), "VIDEO_UNDERSTANDING_RATE_LIMIT"),
        (FakeServerError("server"), "VIDEO_UNDERSTANDING_PROVIDER_5XX"),
    ):
        with pytest.raises(VideoUnderstandingProviderError) as exc:
            OpenAIVideoUnderstandingProvider(api_key="test-key", client=FakeClient(error=error)).analyze(request)
        assert exc.value.code == code
    client = FakeClient()
    client.responses.create = lambda **kwargs: type("Resp", (), {"output_text": "not-json"})()
    with pytest.raises(VideoUnderstandingProviderError) as invalid:
        OpenAIVideoUnderstandingProvider(api_key="test-key", client=client).analyze(request)
    assert invalid.value.code == "VIDEO_UNDERSTANDING_INVALID_OUTPUT"
