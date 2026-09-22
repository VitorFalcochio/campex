from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.database.db import connect, initialize_database
from backend.main import app
from backend.services.intelligence.context import build_intelligence_context
from backend.services.intelligence.exceptions import (
    IntelligenceInvalidResponseError,
    IntelligenceNotConfiguredError,
    IntelligenceProviderUnavailableError,
    IntelligenceRateLimitError,
    IntelligenceTimeoutError,
)
from backend.services.intelligence.models import (
    INSUFFICIENT_INFORMATION,
    IntelligenceRequest,
)
from backend.services.intelligence.service import CampexIntelligenceService


class FakeNemotronClient:
    model = "fake-nemotron"

    def __init__(self, answer: str = "Camera cam_a is ONLINE based on CAMPEX data.") -> None:
        self.answer = answer
        self.messages = []

    def chat(self, messages):
        self.messages = messages
        return self.answer


class TimeoutClient(FakeNemotronClient):
    def chat(self, messages):
        raise IntelligenceTimeoutError("timeout")


class UnavailableClient(FakeNemotronClient):
    def chat(self, messages):
        raise IntelligenceProviderUnavailableError("unavailable")


class EmptyClient(FakeNemotronClient):
    def chat(self, messages):
        return ""


class InvalidJsonClient(FakeNemotronClient):
    def chat(self, messages):
        return "CAMPEX - relatorio sem JSON"


class RateLimitClient(FakeNemotronClient):
    def chat(self, messages):
        raise IntelligenceRateLimitError("rate limit")


class NotConfiguredClient(FakeNemotronClient):
    def chat(self, messages):
        raise IntelligenceNotConfiguredError("NVIDIA_API_KEY is not configured.")


def test_service_answers_with_structured_context_only():
    client = FakeNemotronClient()
    service = CampexIntelligenceService(client)
    context = {
        "schema": "campex_intelligence_context.v1",
        "organization_id": "org_a",
        "source": {"events_seen": 1},
        "camera_status": {"total": 1, "online": 1},
        "assets": {"machines_total": 0},
    }

    response = service.ask(
        IntelligenceRequest(
            organization_id="org_a",
            query="What is online?",
            context=context,
        )
    )

    assert response.answer == "Camera cam_a is ONLINE based on CAMPEX data."
    assert response.organization_id == "org_a"
    assert response.model == "fake-nemotron"
    assert "Campex Intelligence" in client.messages[0]["content"]
    assert "Structured context JSON" in client.messages[1]["content"]


def test_service_returns_insufficient_information_for_empty_context():
    client = FakeNemotronClient()
    service = CampexIntelligenceService(client)
    response = service.ask(
        IntelligenceRequest(
            organization_id="org_empty",
            query="What happened?",
            context={
                "schema": "campex_intelligence_context.v1",
                "organization_id": "org_empty",
                "source": {"events_seen": 0},
                "camera_status": {"total": 0},
                "assets": {"machines_total": 0},
            },
        )
    )

    assert response.answer == INSUFFICIENT_INFORMATION
    assert client.messages == []


def test_service_surfaces_timeout_and_unavailable_errors():
    request = IntelligenceRequest(
        organization_id="org_a",
        query="summarize",
        context={
            "source": {"events_seen": 1},
            "camera_status": {"total": 1},
            "assets": {"machines_total": 0},
        },
    )

    with pytest.raises(IntelligenceTimeoutError):
        CampexIntelligenceService(TimeoutClient()).ask(request)
    with pytest.raises(IntelligenceProviderUnavailableError):
        CampexIntelligenceService(UnavailableClient()).ask(request)


def test_operational_report_success_returns_structured_payload():
    service = CampexIntelligenceService(
        FakeNemotronClient(
            '{"summary":"Foram detectados 30 tracks, com pico de 15 pessoas simultaneamente.",'
            '"sections":{"flow":"Entradas: 30; saidas: 30.","movement":"Movimento: 152.8 segundos."}}'
        )
    )

    report = service.generate_operational_report(
        organization_id="org_a",
        data=_palace_metrics(),
    ).as_dict()

    assert report["provider"] == "nvidia"
    assert report["model"] == "fake-nemotron"
    assert report["status"] == "success"
    assert report["fallback_used"] is False
    assert "30" in report["summary"]
    assert "15" in report["summary"]
    assert report["sections"]["movement"] == "Movimento: 152.8 segundos."


def test_operational_report_extracts_json_after_provider_preamble():
    service = CampexIntelligenceService(
        FakeNemotronClient(
            'Texto antes do JSON. {"summary":"Foram detectados 30 tracks.",'
            '"sections":{"flow":"Pico de 15 pessoas simultaneamente."}}'
        )
    )

    report = service.generate_operational_report(
        organization_id="org_a",
        data=_palace_metrics(),
    ).as_dict()

    assert report["provider"] == "nvidia"
    assert report["fallback_used"] is False
    assert report["summary"] == "Foram detectados 30 tracks."


@pytest.mark.parametrize(
    "client,reason",
    [
        (NotConfiguredClient(), "NVIDIA_API_KEY"),
        (TimeoutClient(), "timeout"),
        (RateLimitClient(), "rate limit"),
        (InvalidJsonClient(), "invalid JSON"),
        (EmptyClient(), "invalid JSON"),
    ],
)
def test_operational_report_falls_back_for_provider_failures(client, reason):
    report = CampexIntelligenceService(client).generate_operational_report(
        organization_id="org_a",
        data=_palace_metrics(),
    ).as_dict()

    assert report["provider"] == "fallback"
    assert report["status"] == "fallback"
    assert report["fallback_used"] is True
    assert "30 tracks" in report["summary"]
    assert "15 pessoas" in report["summary"]
    assert reason.lower().split()[0] in report["reason"].lower()


def test_operational_report_prompt_does_not_invite_hallucination():
    client = FakeNemotronClient(
        '{"summary":"Foram detectados 5 tracks, com pico de 3 pessoas simultaneamente.",'
        '"sections":{"flow":"Nao ha dados suficientes para determinar setor, causa ou produtividade."}}'
    )
    service = CampexIntelligenceService(client)

    report = service.generate_operational_report(
        organization_id="org_a",
        data={
            "metrics": {
                "people": {"detected": 5, "max_simultaneous": 3},
                "activity": {"stationary_events": 0},
            }
        },
    ).as_dict()

    serialized_messages = json.dumps(client.messages, ensure_ascii=False)
    assert "Nunca invente causas" in serialized_messages
    assert "Nao recalcule metricas" in serialized_messages
    forbidden = ["producao", "funcionarios", "maquina parada", "queda de produtividade"]
    assert all(term not in report["summary"].lower() for term in forbidden)


def test_nemotron_client_requires_api_key(tmp_path):
    from backend.integrations.nemotron import NemotronClient

    settings = _settings(tmp_path / "no-key.sqlite3")
    settings = Settings(**{**settings.__dict__, "nvidia_api_key": None})

    with pytest.raises(IntelligenceNotConfiguredError):
        NemotronClient(settings).chat([{"role": "user", "content": "status"}])


def test_context_builder_filters_by_organization(tmp_path):
    settings = _settings(tmp_path / "tenant.sqlite3")
    initialize_database(settings)
    _seed_camera(settings, "cam_a", "org_a", "ONLINE")
    _seed_camera(settings, "cam_b", "org_b", "OFFLINE")
    _seed_event(settings, "evt_a", "cam_a", "org_a")
    _seed_event(settings, "evt_b", "cam_b", "org_b")

    context = build_intelligence_context(settings, "org_a")

    assert context["organization_id"] == "org_a"
    assert context["camera_status"]["total"] == 1
    assert context["camera_status"]["cameras"][0]["id"] == "cam_a"
    assert context["events"]["total_in_context"] == 1
    assert context["events"]["recent"][0]["id"] == "evt_a"
    assert "cam_b" not in json.dumps(context)
    assert "evt_b" not in json.dumps(context)


def test_intelligence_endpoint_uses_header_tenant_and_hides_api_key(monkeypatch, tmp_path):
    database_path = tmp_path / "api-intelligence.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("NVIDIA_API_KEY", "secret-key-must-not-leak")
    monkeypatch.setenv("CAMPEX_ALLOWED_ORGANIZATION_IDS", "org_a,org_b")
    monkeypatch.setenv("CAMPEX_DEFAULT_ORGANIZATION_ID", "org_a")
    initialize_database(Settings.from_env())
    _seed_camera(Settings.from_env(), "cam_a", "org_a", "ONLINE")
    _seed_camera(Settings.from_env(), "cam_b", "org_b", "OFFLINE")

    class EndpointFakeClient(FakeNemotronClient):
        def __init__(self, settings):
            super().__init__("Only org_a context was used.")

    monkeypatch.setattr("backend.api.intelligence.NemotronClient", EndpointFakeClient)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/intelligence/ask",
            headers={"X-CAMPEX-Organization-Id": "org_a"},
            json={"query": "How are cameras?"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["organization_id"] == "org_a"
    assert payload["context_summary"]["cameras_total"] == 1
    assert "secret-key-must-not-leak" not in response.text
    assert "org_b" not in response.text


def test_intelligence_endpoint_rejects_unallowed_organization(monkeypatch, tmp_path):
    database_path = tmp_path / "api-intelligence-forbidden.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("CAMPEX_ALLOWED_ORGANIZATION_IDS", "org_a")
    initialize_database(Settings.from_env())

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/intelligence/ask",
            headers={"X-CAMPEX-Organization-Id": "org_b"},
            json={"query": "status"},
        )

    assert response.status_code == 403


def test_intelligence_endpoint_requires_organization_token_when_configured(monkeypatch, tmp_path):
    database_path = tmp_path / "api-intelligence-token-required.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("CAMPEX_ALLOWED_ORGANIZATION_IDS", "org_a,org_b")
    monkeypatch.setenv("CAMPEX_DEFAULT_ORGANIZATION_ID", "org_a")
    monkeypatch.setenv("CAMPEX_ORGANIZATION_TOKENS", "org_a:token-a,org_b:token-b")
    initialize_database(Settings.from_env())
    _seed_camera(Settings.from_env(), "cam_a", "org_a", "ONLINE")
    _seed_camera(Settings.from_env(), "cam_b", "org_b", "OFFLINE")

    class EndpointFakeClient(FakeNemotronClient):
        def __init__(self, settings):
            super().__init__("Token scoped context.")

    monkeypatch.setattr("backend.api.intelligence.NemotronClient", EndpointFakeClient)

    with TestClient(app) as client:
        missing = client.post(
            "/api/v1/intelligence/ask",
            headers={"X-CAMPEX-Organization-Id": "org_a"},
            json={"query": "status"},
        )
        mismatch = client.post(
            "/api/v1/intelligence/ask",
            headers={
                "X-CAMPEX-Organization-Id": "org_b",
                "Authorization": "Bearer token-a",
            },
            json={"query": "status"},
        )
        authorized = client.post(
            "/api/v1/intelligence/ask",
            headers={"Authorization": "Bearer token-a"},
            json={"query": "status"},
        )

    assert missing.status_code == 401
    assert mismatch.status_code == 403
    assert authorized.status_code == 200
    payload = authorized.json()
    assert payload["organization_id"] == "org_a"
    assert payload["context_summary"]["cameras_total"] == 1
    assert "org_b" not in authorized.text


def _settings(database_path):
    return Settings(
        environment="test",
        service_name="campex",
        version="0.1.0",
        log_level="INFO",
        database_url=f"sqlite:///{database_path}",
        frontend_origins=["*"],
        camera_reconnect_seconds=0.01,
        camera_stale_seconds=0.1,
        camera_offline_seconds=0.3,
        camera_read_failure_limit=1,
        camera_test_timeout_seconds=1,
        vision_enabled=True,
        vision_detector="rfdetr",
        vision_device="auto",
        vision_fps=5,
        vision_confidence=0.5,
        vision_video_loop=False,
        intelligence_allowed_organization_ids=["org_a", "org_b"],
        intelligence_default_organization_id="org_a",
        nvidia_api_key="test-key",
    )


def _palace_metrics():
    return {
        "metrics": {
            "people": {
                "detected": 30,
                "entries": 30,
                "exits": 30,
                "max_simultaneous": 15,
            },
            "summary": {
                "unique_people": 30,
                "max_simultaneous": 15,
                "total_events": 118,
            },
            "activity": {
                "moving_seconds": 152.8,
                "stationary_seconds": 0,
                "stationary_events": 0,
            },
            "zones": {},
        },
        "events": [
            {
                "event_type": "person_detected",
                "track_id": 1,
                "started_at": "2026-09-22T12:00:00+00:00",
            }
        ],
    }


def _seed_camera(settings, camera_id: str, organization_id: str, status: str) -> None:
    with connect(settings.sqlite_path) as connection:
        connection.execute(
            """
            INSERT INTO cameras (
                id, name, source_type, source_uri, enabled, vision_enabled,
                status, organization_id
            )
            VALUES (?, ?, 'video_file', 'fixture.mp4', 1, 1, ?, ?)
            """,
            (camera_id, f"Camera {camera_id}", status, organization_id),
        )
        connection.commit()


def _seed_event(settings, event_id: str, camera_id: str, organization_id: str) -> None:
    now = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc).isoformat()
    metadata = json.dumps({"facts": {"quality": {"is_reliable": True, "state": "RELIABLE"}}})
    with connect(settings.sqlite_path) as connection:
        connection.execute(
            """
            INSERT INTO events (
                id, type, camera_id, severity, status, confidence,
                started_at, ended_at, duration, metadata, organization_id
            )
            VALUES (?, 'MACHINE_WAITING', ?, 'attention', 'CLOSED', 0.9, ?, ?, 60, ?, ?)
            """,
            (event_id, camera_id, now, now, metadata, organization_id),
        )
        connection.commit()
