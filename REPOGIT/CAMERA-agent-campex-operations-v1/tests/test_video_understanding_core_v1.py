from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest

from app.api import api
from app.auth import create_user
from app.database import connect
from app.operational_read_model import ReadModelFilters, parse_datetime, video_contexts
from app.video_understanding import (
    DeterministicFakeVideoUnderstandingProvider,
    EvidenceSelectionConfig,
    VideoUnderstandingError,
    VideoUnderstandingProviderError,
    VideoUnderstandingProviderUnavailable,
    VideoUnderstandingService,
    build_understanding_request,
    select_evidence,
    validate_understanding_result,
)
from tests.test_operational_read_model import add_event, add_sample, make_context


def _make_context_with_evidence():
    temp_dir, db_path, connection, cliente_id, site_id, area_id, process_id, asset_id, camera_id = make_context()
    start = parse_datetime("2026-08-07T08:00:00+00:00")
    end = parse_datetime("2026-08-07T09:00:00+00:00")
    add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T08:05:00+00:00", "ACTIVE", True)
    add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T08:10:00+00:00", "STOPPED", True)
    add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T08:20:00+00:00", "STOPPED", False)
    add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T08:35:00+00:00", "ACTIVE", True)
    event_id = add_event(connection, cliente_id, site_id, camera_id, "machine_stoppage", start="2026-08-07T08:10:00+00:00", end="2026-08-07T08:30:00+00:00", duration=1200, event_uuid="evt-vu")
    connection.execute("UPDATE eventos SET midia_path = ? WHERE id = ?", ("data/evidence/vu.jpg", event_id))
    connection.commit()
    payload = video_contexts(connection, ReadModelFilters(cliente_id=cliente_id, start=start, end=end), trigger_type="event_started", now=end)
    context = payload["contexts"][0]
    return temp_dir, db_path, connection, cliente_id, site_id, area_id, process_id, asset_id, camera_id, context


def test_valid_context_id_generates_understanding_request_with_constraints_and_versions() -> None:
    temp_dir, _db_path, connection, cliente_id, *_rest, context = _make_context_with_evidence()
    with temp_dir, connection:
        request = build_understanding_request(context, request_id="req-test")

    assert request["request_id"] == "req-test"
    assert request["context_id"] == context["context_id"]
    assert request["request_id"] != request["context_id"]
    assert request["schema_version"] == "video_understanding_v1"
    assert request["constraints"] == {
        "infer_cause": False,
        "infer_intent": False,
        "assign_responsibility": False,
        "identify_people": False,
        "replace_canonical_facts": False,
    }
    assert request["operational_context"]["known_facts"]


def test_evidence_selection_preserves_phases_dedupes_and_respects_limits() -> None:
    video_context = {
        "phases": {
            "before": [
                {"timestamp": "t1", "type": "camera_status", "evidence_refs": [{"path": "a.jpg"}, {"path": "a.jpg"}]},
                {"timestamp": "t2", "type": "machine_activity", "evidence_refs": [{"path": "b.jpg"}]},
            ],
            "transition": [{"timestamp": "t3", "type": "event_started", "evidence_refs": [{"path": "c.jpg"}]}],
            "during": [{"timestamp": "t4", "type": "person_presence", "evidence_refs": [{"path": "d.jpg"}]}],
            "after": [{"timestamp": "t5", "type": "event_closed", "evidence_refs": [{"path": "e.jpg"}]}],
        }
    }
    selected = select_evidence(video_context, EvidenceSelectionConfig(max_total_evidence=3, max_evidence_per_phase=1))

    assert [item["media_path"] for item in selected] == ["a.jpg", "c.jpg", "d.jpg"]
    assert [item["phase"] for item in selected] == ["before", "transition", "during"]


def test_context_without_evidence_and_partial_context_generate_valid_request() -> None:
    temp_dir, _db_path, connection, cliente_id, *_rest, context = _make_context_with_evidence()
    with temp_dir, connection:
        context["evidence_refs"] = []
        for phase_items in context["phases"].values():
            for item in phase_items:
                item["evidence_refs"] = []
        context["data_quality"]["status"] = "partial"
        request = build_understanding_request(context)
        result = DeterministicFakeVideoUnderstandingProvider().analyze(request)
        validated = validate_understanding_result(result, request)

    assert request["evidence"] == []
    assert "Nenhuma evidencia visual" in validated["uncertainties"][0]
    assert validated["cause_inferred"] is False


def test_fake_provider_receives_request_and_returns_structured_result() -> None:
    temp_dir, _db_path, connection, cliente_id, *_rest, context = _make_context_with_evidence()
    provider = DeterministicFakeVideoUnderstandingProvider()
    with temp_dir, connection:
        result = VideoUnderstandingService(provider=provider).analyze_context(connection, ReadModelFilters(cliente_id=cliente_id), context["context_id"])

    assert provider.calls[0] == result["request"]
    assert result["status"] == "ok"
    assert result["result"]["context_id"] == context["context_id"]
    assert result["result"]["understanding_id"] != context["context_id"]
    assert result["result"]["understanding_id"] != result["request"]["request_id"]
    assert result["result"]["model_metadata"]["schema_version"] == "video_understanding_v1"


def test_invalid_context_provider_unavailable_and_provider_error_are_controlled() -> None:
    temp_dir, _db_path, connection, cliente_id, *_rest, _context = _make_context_with_evidence()
    with temp_dir, connection:
        with pytest.raises(VideoUnderstandingError) as missing:
            VideoUnderstandingService(provider=DeterministicFakeVideoUnderstandingProvider()).analyze_context(connection, ReadModelFilters(cliente_id=cliente_id), "ctx-missing")
        with pytest.raises(VideoUnderstandingProviderUnavailable):
            VideoUnderstandingService().analyze_context(connection, ReadModelFilters(cliente_id=cliente_id), _context["context_id"])

    assert missing.value.code == "VIDEO_CONTEXT_NOT_FOUND"


class BadProvider:
    def analyze(self, request):
        return {"context_id": request["context_id"]}


def test_invalid_provider_output_is_rejected_and_canonical_data_is_not_modified() -> None:
    temp_dir, _db_path, connection, cliente_id, *_rest, context = _make_context_with_evidence()
    with temp_dir, connection:
        before_events = connection.execute("SELECT COUNT(*) AS total FROM eventos").fetchone()["total"]
        before_samples = connection.execute("SELECT COUNT(*) AS total FROM operational_samples").fetchone()["total"]
        response = VideoUnderstandingService(provider=BadProvider()).analyze_context(connection, ReadModelFilters(cliente_id=cliente_id), context["context_id"])
        after_events = connection.execute("SELECT COUNT(*) AS total FROM eventos").fetchone()["total"]
        after_samples = connection.execute("SELECT COUNT(*) AS total FROM operational_samples").fetchone()["total"]

    assert response["validated_understanding"]["status"] == "REJECTED"
    assert before_events == after_events
    assert before_samples == after_samples


def test_video_understanding_endpoint_uses_fake_provider_when_configured_and_no_external_api() -> None:
    temp_dir, db_path, connection, cliente_id, *_rest, context = _make_context_with_evidence()
    with temp_dir:
        create_user(connection, "vu@example.com", "senha", "admin_cliente", cliente_id)
        connection.close()

        def test_connect(_path=None):
            return connect(db_path)

        with patch("app.api.connect", test_connect), patch.dict("os.environ", {"CAMPEX_VIDEO_UNDERSTANDING_PROVIDER": "fake"}, clear=False):
            client = TestClient(api)
            client.post("/auth/login", json={"email": "vu@example.com", "senha": "senha"})
            response = client.post(f"/operations/video-understanding/{context['context_id']}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["model_metadata"]["provider"] == "fake"
    assert payload["result"]["cause_inferred"] is False


def test_video_understanding_endpoint_without_provider_fails_explicitly() -> None:
    temp_dir, db_path, connection, cliente_id, *_rest, context = _make_context_with_evidence()
    with temp_dir:
        create_user(connection, "vu-none@example.com", "senha", "admin_cliente", cliente_id)
        connection.close()

        def test_connect(_path=None):
            return connect(db_path)

        with patch("app.api.connect", test_connect), patch.dict("os.environ", {"CAMPEX_VIDEO_UNDERSTANDING_PROVIDER": ""}, clear=False):
            client = TestClient(api)
            client.post("/auth/login", json={"email": "vu-none@example.com", "senha": "senha"})
            response = client.post(f"/operations/video-understanding/{context['context_id']}")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "VIDEO_UNDERSTANDING_PROVIDER_NOT_CONFIGURED"
