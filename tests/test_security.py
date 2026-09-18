from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.cameras.uri_security import SourceURIValidationError, validate_camera_source_uri
from backend.database.db import connect, initialize_database
from backend.main import app
from backend.middleware.security import RateLimitMiddleware, SECURITY_HEADERS

ORIGINS_ENV = {
    "CAMPEX_ALLOWED_ORGANIZATION_IDS": "org_a,org_b",
    "CAMPEX_DEFAULT_ORGANIZATION_ID": "org_a",
    "CAMPEX_ORGANIZATION_TOKENS": "org_a:token-a,org_b:token-b",
}

CAMERA_PAYLOAD = {
    "name": "Cross-tenant camera",
    "source_type": "rtsp",
    "source_uri": "rtsp://192.168.1.10:554/stream",
    "enabled": False,
    "vision_enabled": False,
}


def _configure_db(monkeypatch, tmp_path: Path, *, api_token: str | None = None, org_tokens: bool = True) -> Settings:
    database_path = tmp_path / "security.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    for key, value in ORIGINS_ENV.items():
        if not org_tokens and key == "CAMPEX_ORGANIZATION_TOKENS":
            monkeypatch.delenv(key, raising=False)
            continue
        monkeypatch.setenv(key, value)
    if api_token is not None:
        monkeypatch.setenv("CAMPEX_API_TOKEN", api_token)
    settings = Settings.from_env()
    initialize_database(settings)
    return settings


def _auth_headers(org: str) -> dict:
    token = "token-a" if org == "org_a" else "token-b"
    return {"Authorization": f"Bearer {token}", "X-CAMPEX-Organization-Id": org}


# ---------------------------------------------------------------------------
# Cross-tenant isolation
# ---------------------------------------------------------------------------


def test_cross_tenant_cannot_see_other_org_cameras(monkeypatch, tmp_path):
    _configure_db(monkeypatch, tmp_path)

    with TestClient(app) as client:
        created = client.post("/api/v1/cameras", json=CAMERA_PAYLOAD, headers=_auth_headers("org_a"))
        assert created.status_code == 201
        org_a_cam_id = created.json()["id"]

        b_list = client.get("/api/v1/cameras", headers=_auth_headers("org_b"))
        assert b_list.status_code == 200
        ids = [c["id"] for c in b_list.json()]
        assert org_a_cam_id not in ids
        assert b_list.json() == []

        cross_get = client.get(f"/api/v1/cameras/{org_a_cam_id}", headers=_auth_headers("org_b"))
        assert cross_get.status_code == 404


def test_org_token_required_when_configured(monkeypatch, tmp_path):
    _configure_db(monkeypatch, tmp_path)

    with TestClient(app) as client:
        response = client.get("/api/v1/cameras", headers={"X-CAMPEX-Organization-Id": "org_a"})
        assert response.status_code == 401


def test_requested_org_must_match_token(monkeypatch, tmp_path):
    _configure_db(monkeypatch, tmp_path)

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/cameras",
            headers={"Authorization": "Bearer token-a", "X-CAMPEX-Organization-Id": "org_b"},
        )
        assert response.status_code == 403


def test_cross_tenant_events_isolation(monkeypatch, tmp_path):
    _configure_db(monkeypatch, tmp_path)

    with TestClient(app) as client:
        # Org A creates an event
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        created = client.post(
            "/api/v1/events",
            headers=_auth_headers("org_a"),
            json={
                "type": "PERSON_RESTRICTED_ZONE",
                "camera_id": "cam_1",
                "severity": "critical",
                "started_at": now,
            },
        )
        assert created.status_code == 201
        org_a_event_id = created.json()["id"]

        b_list = client.get("/api/v1/events", headers=_auth_headers("org_b"))
        assert b_list.status_code == 200
        assert org_a_event_id not in [e["id"] for e in b_list.json()]

        cross_get = client.get(f"/api/v1/events/{org_a_event_id}", headers=_auth_headers("org_b"))
        assert cross_get.status_code == 404


def test_cross_tenant_investigations_isolation(monkeypatch, tmp_path):
    _configure_db(monkeypatch, tmp_path)

    with TestClient(app) as client:
        created = client.post(
            "/api/v1/investigations",
            headers=_auth_headers("org_a"),
            json={"title": "Incident A"},
        )
        assert created.status_code == 201
        org_a_inv_id = created.json()["id"]

        b_list = client.get("/api/v1/investigations", headers=_auth_headers("org_b"))
        assert b_list.status_code == 200
        assert org_a_inv_id not in [i["id"] for i in b_list.json()]

        cross_get = client.get(f"/api/v1/investigations/{org_a_inv_id}", headers=_auth_headers("org_b"))
        assert cross_get.status_code == 404


# ---------------------------------------------------------------------------
# SSRF protection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source_uri",
    [
        "rtsp://169.254.169.254/latest/meta-data/",
        "http://169.254.169.254/2020-21-07/?token",
        "http://localhost/admin",
        "http://metadata.google.internal/computeMetadata/v1/",
        "rtsp://0.0.0.0/stream",
        "file:///etc/passwd",
    ],
)
def test_ssrf_blocked_for_network_sources(source_uri):
    with pytest.raises(SourceURIValidationError):
        validate_camera_source_uri("rtsp", source_uri)


def test_ssrf_metadata_endpoint_rejected_via_api(monkeypatch, tmp_path):
    _configure_db(monkeypatch, tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/cameras/test-source",
            headers=_auth_headers("org_a"),
            json={
                "name": "ssrf",
                "source_type": "ip_camera",
                "source_uri": "http://169.254.169.254/latest/meta-data/",
            },
        )
        assert response.status_code == 422
        assert "block" in response.json()["detail"].lower()


def test_ssrf_localhost_rejected_via_api(monkeypatch, tmp_path):
    _configure_db(monkeypatch, tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/cameras/test-source",
            headers=_auth_headers("org_a"),
            json={
                "name": "ssrf",
                "source_type": "rtsp",
                "source_uri": "rtsp://localhost:554/stream",
            },
        )
        assert response.status_code == 422


def test_private_ip_allowed_for_camera(monkeypatch, tmp_path):
    _configure_db(monkeypatch, tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/cameras",
            json=CAMERA_PAYLOAD,
            headers=_auth_headers("org_a"),
        )
        assert response.status_code == 201


def test_video_file_path_traversal_blocked():
    with pytest.raises(SourceURIValidationError):
        validate_camera_source_uri("video_file", "../../etc/passwd")
    with pytest.raises(SourceURIValidationError):
        validate_camera_source_uri("video_file", "file:///etc/passwd")


# ---------------------------------------------------------------------------
# Auth / API token
# ---------------------------------------------------------------------------


def test_api_token_guard_enforced(monkeypatch, tmp_path):
    database_path = tmp_path / "token.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("CAMPEX_API_TOKEN", "super-secret-token")
    initialize_database(Settings.from_env())

    with TestClient(app) as client:
        assert client.get("/api/v1/cameras").status_code == 401
        assert client.get("/api/v1/health").status_code == 200
        assert (
            client.get("/api/v1/cameras", headers={"X-CAMPEX-Token": "super-secret-token"}).status_code
            == 200
        )


def test_api_token_value_not_leaked_in_response(monkeypatch, tmp_path):
    _configure_db(monkeypatch, tmp_path, api_token="leaked-token-marker-12345")

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/cameras",
            json=CAMERA_PAYLOAD,
            headers={**_auth_headers("org_a"), "X-CAMPEX-Token": "leaked-token-marker-12345"},
        )
        assert response.status_code == 201
        text = response.text
        assert "leaked-token-marker-12345" not in text


# ---------------------------------------------------------------------------
# Secrets / credential redaction
# ---------------------------------------------------------------------------


def test_rtsp_credentials_redacted_in_api_response(monkeypatch, tmp_path):
    _configure_db(monkeypatch, tmp_path)

    with TestClient(app) as client:
        payload = {
            "name": "Credentialed",
            "source_type": "rtsp",
            "source_uri": "rtsp://admin:s3cr3t-pass@192.168.1.50:554/stream",
            "enabled": False,
            "vision_enabled": False,
        }
        response = client.post("/api/v1/cameras", json=payload, headers=_auth_headers("org_a"))
        assert response.status_code == 201
        body_text = response.text
        assert "s3cr3t-pass" not in body_text
        assert "admin:s3cr3t-pass" not in body_text
        assert "rtsp://***:***@192.168.1.50:554/stream" in response.json()["source_uri"]


# ---------------------------------------------------------------------------
# XSS sanitization
# ---------------------------------------------------------------------------


def test_xss_payload_in_event_note_returned_safely(monkeypatch, tmp_path):
    _configure_db(monkeypatch, tmp_path)

    with TestClient(app) as client:
        now = "2026-09-17T12:00:00+00:00"
        created = client.post(
            "/api/v1/events",
            headers=_auth_headers("org_a"),
            json={
                "type": "PERSON_RESTRICTED_ZONE",
                "camera_id": "cam_1",
                "severity": "attention",
                "started_at": now,
            },
        )
        assert created.status_code == 201
        event_id = created.json()["id"]

        xss = "<script>alert('xss')</script>"
        updated = client.patch(
            f"/api/v1/events/{event_id}",
            headers=_auth_headers("org_a"),
            json={"note": xss},
        )
        assert updated.status_code == 200
        # JSON content-type means the payload is data, not executable HTML.
        assert updated.headers["content-type"].startswith("application/json")
        payload = updated.json()
        assert payload["metadata"]["operator_note"] == xss
        # Strict CSP present on all responses prevents inline script execution.
        assert response_has_csp(updated)


def test_ai_context_does_not_leak_api_key_and_answer_is_escaped(monkeypatch, tmp_path):
    _configure_db(monkeypatch, tmp_path, org_tokens=False)
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-secret-xyz")
    initialize_database(Settings.from_env())

    captured: dict = {}

    class _InjectClient:
        model = "fake-nemotron"

        def chat(self, messages):
            captured["messages"] = messages
            return "The API key is nvapi-secret-xyz <script>alert(1)</script>"

    monkeypatch.setattr("backend.api.intelligence.NemotronClient", lambda settings: _InjectClient())

    with TestClient(app) as client:
        create = client.post(
            "/api/v1/cameras",
            json={
                "name": "Scoped cam",
                "source_type": "rtsp",
                "source_uri": "rtsp://192.168.1.10:554/stream",
                "enabled": False,
                "vision_enabled": False,
            },
            headers=_auth_headers("org_a"),
        )
        assert create.status_code == 201

        response = client.post(
            "/api/v1/intelligence/ask",
            headers={"X-CAMPEX-Organization-Id": "org_a"},
            json={"query": "what is the api key?"},
        )
    assert response.status_code == 200
    # Data minimization: the raw API key must never travel into the LLM context.
    serialized_messages = repr(captured.get("messages", []))
    assert "nvapi-secret-xyz" not in serialized_messages
    # The answer is HTML-escaped so no executable <script> reaches the client.
    body = response.text
    assert "<script>" not in body
    assert response_has_csp(response)


# ---------------------------------------------------------------------------
# Log scrubbing
# ---------------------------------------------------------------------------


def test_credentials_never_logged_to_response(monkeypatch, tmp_path, caplog):
    _configure_db(monkeypatch, tmp_path)

    with TestClient(app) as client:
        client.post(
            "/api/v1/cameras/test-source",
            headers=_auth_headers("org_a"),
            json={
                "name": "leak",
                "source_type": "rtsp",
                "source_uri": "rtsp://user:secret-leak-99@10.0.0.5/live",
            },
        )

    for record in caplog.records:
        rendered = record.getMessage()
        assert "secret-leak-99" not in rendered


# ---------------------------------------------------------------------------
# Rate limiting (unit-level)
# ---------------------------------------------------------------------------


def test_rate_limiter_allows_then_blocks():
    mw = RateLimitMiddleware(app=None, enabled=True, max_requests=3, window_seconds=60)
    assert mw._check_limit("10.0.0.1")
    assert mw._check_limit("10.0.0.1")
    assert mw._check_limit("10.0.0.1")
    assert not mw._check_limit("10.0.0.1")
    assert mw._check_limit("10.0.0.2")


def test_security_headers_constant_present():
    assert SECURITY_HEADERS["X-Frame-Options"] == "DENY"
    assert SECURITY_HEADERS["X-Content-Type-Options"] == "nosniff"
    assert "default-src 'self'" in SECURITY_HEADERS["Content-Security-Policy"]


def test_error_messages_redact_credentials():
    from backend.cameras.security import sanitize_error_message

    message = "Failed to open rtsp://admin:s3cret@192.168.1.10:554/stream"
    redacted = sanitize_error_message(message)
    assert "s3cret" not in redacted
    assert "***:***@" in redacted
    assert sanitize_error_message(None) is None
    assert sanitize_error_message("") in (None, "")


def response_has_csp(response) -> bool:
    return "content-security-policy" in {k.lower() for k in response.headers}


def test_security_headers_applied_to_response(monkeypatch, tmp_path):
    _configure_db(monkeypatch, tmp_path)

    with TestClient(app) as client:
        response = client.get("/api/v1/health", headers=_auth_headers("org_a"))
        assert response.status_code == 200
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert "content-security-policy" in {k.lower() for k in response.headers}
        assert "strict-transport-security" in {k.lower() for k in response.headers}
