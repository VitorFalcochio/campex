from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import api
from app.auth import create_user
from app.database import connect, init_db
from app.operational_read_model import ReadModelFilters, parse_datetime, video_contexts
from app.operational_understanding import (
    UnderstandingFilters,
    get_validated_understanding,
    list_validated_understandings,
    validate_normalize_and_persist_understanding,
)
from app.video_understanding import DeterministicFakeVideoUnderstandingProvider, VideoUnderstandingService, build_understanding_request
from tests.test_operational_read_model import add_event, add_sample, make_context


def _context_with_visual_evidence(*, partial: bool = False, open_event: bool = False):
    temp_dir, db_path, connection, cliente_id, site_id, area_id, process_id, asset_id, camera_id = make_context()
    start = parse_datetime("2026-08-07T08:00:00+00:00")
    end = parse_datetime("2026-08-07T09:00:00+00:00")
    add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T08:05:00+00:00", "ACTIVE", True)
    add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T08:10:00+00:00", "STOPPED", True)
    add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T08:20:00+00:00", "STOPPED", False)
    if not open_event:
        add_sample(connection, cliente_id, site_id, camera_id, asset_id, "2026-08-07T08:35:00+00:00", "ACTIVE", True)
    event_id = add_event(
        connection,
        cliente_id,
        site_id,
        camera_id,
        "machine_stoppage",
        start="2026-08-07T08:10:00+00:00",
        end=None if open_event else "2026-08-07T08:30:00+00:00",
        duration=None if open_event else 1200,
        event_uuid="evt-vou",
    )
    connection.execute("UPDATE eventos SET midia_path = ? WHERE id = ?", ("data/evidence/vou.jpg", event_id))
    connection.commit()
    payload = video_contexts(connection, ReadModelFilters(cliente_id=cliente_id, start=start, end=end), trigger_type="event_started", now=end)
    context = payload["contexts"][0]
    if partial:
        context["data_quality"]["status"] = "partial"
        context["phases"]["after"] = []
    return temp_dir, db_path, connection, cliente_id, site_id, area_id, process_id, asset_id, camera_id, context


def _result(request: dict, *, understanding_id: str = "vu-valid-1") -> dict:
    refs = [item["evidence_ref"] for item in request.get("evidence") or []]
    return {
        "understanding_id": understanding_id,
        "context_id": request["context_id"],
        "summary": "Cena industrial validada visualmente.",
        "visual_facts": [{"type": "machine_visible", "description": "Maquina visivel no frame.", "phase": "transition", "evidence_refs": refs[:1]}],
        "scene_changes": [{"description": "Mudanca visual sustentada por evidencias.", "phase": "transition", "evidence_refs": refs[:1]}],
        "observed_entities": [{"entity_type": "machine", "description": "Ativo operacional visivel.", "phase": "transition", "evidence_refs": refs[:1]}],
        "observed_actions": [],
        "uncertainties": [],
        "evidence_refs": refs + refs[:1],
        "model_metadata": {
            "provider": "fake",
            "model": "fake-video-understanding-v1",
            "schema_version": "video_understanding_v1",
            "prompt_version": "video_understanding_v1",
            "analyzed_at": "2026-08-07T08:30:00+00:00",
        },
        "cause_inferred": False,
    }


def _mark_complete(context: dict) -> dict:
    context["data_quality"]["status"] = "complete"
    context["data_quality"]["coverage_status"] = "complete"
    context["data_quality"]["gaps"] = []
    for phase in ("before", "transition", "during", "after"):
        items = context["phases"].setdefault(phase, [])
        if not items:
            items.append({"timestamp": context.get("start_ts"), "type": "synthetic_phase_marker", "evidence_refs": []})
        items[0]["evidence_refs"] = [{"path": f"data/evidence/{phase}.jpg"}]
    return context


def test_valid_result_is_persisted_as_valid_and_auditable() -> None:
    temp_dir, _db_path, connection, cliente_id, _site_id, _area_id, _process_id, asset_id, camera_id, context = _context_with_visual_evidence()
    with temp_dir, connection:
        context = _mark_complete(context)
        request = build_understanding_request(context, request_id="vur-valid")
        record = validate_normalize_and_persist_understanding(connection, video_context=context, request=request, result=_result(request))

    assert record["status"] == "VALID"
    assert record["quality"] == "complete"
    assert record["tenant_id"] == cliente_id
    assert record["camera_id"] == camera_id
    assert record["asset_id"] == asset_id
    assert record["request_id"] == "vur-valid"
    assert record["structured_result"]["cause_inferred"] is False
    assert len(record["evidence_refs"]) == len(set(record["evidence_refs"]))


def test_partial_context_and_timestamp_uncertainty_become_partial_without_changing_canonical_facts() -> None:
    temp_dir, _db_path, connection, cliente_id, *_rest, context = _context_with_visual_evidence(partial=True)
    with temp_dir, connection:
        before_events = connection.execute("SELECT COUNT(*) AS total FROM eventos").fetchone()["total"]
        before_samples = connection.execute("SELECT COUNT(*) AS total FROM operational_samples").fetchone()["total"]
        request = build_understanding_request(context, request_id="vur-partial")
        result = _result(request, understanding_id="vu-partial-1")
        result["uncertainties"] = ["Visual timestamp mismatch with evidence manifest."]
        record = validate_normalize_and_persist_understanding(connection, video_context=context, request=request, result=result)
        after_events = connection.execute("SELECT COUNT(*) AS total FROM eventos").fetchone()["total"]
        after_samples = connection.execute("SELECT COUNT(*) AS total FROM operational_samples").fetchone()["total"]

    assert record["status"] == "PARTIAL"
    assert "context_partial" in record["quality_reasons"]
    assert "missing_after_evidence" in record["quality_reasons"]
    assert "visual_timestamp_mismatch_reported" in record["quality_reasons"]
    assert before_events == after_events
    assert before_samples == after_samples


def test_rejected_results_are_not_marked_valid() -> None:
    temp_dir, _db_path, connection, _cliente_id, *_rest, context = _context_with_visual_evidence()
    with temp_dir, connection:
        request = build_understanding_request(context, request_id="vur-rejected")
        cause = _result(request, understanding_id="vu-rejected-cause")
        cause["cause_inferred"] = True
        invented = _result(request, understanding_id="vu-rejected-ref")
        invented["evidence_refs"] = ["invented-evidence"]
        mismatch = _result(request, understanding_id="vu-rejected-context")
        mismatch["context_id"] = "ctx-other"
        bad_schema = _result(request, understanding_id="vu-rejected-schema")
        bad_schema["model_metadata"]["schema_version"] = "old"
        records = [
            validate_normalize_and_persist_understanding(connection, video_context=context, request=request, result=item)
            for item in (cause, invented, mismatch, bad_schema)
        ]

    assert {record["status"] for record in records} == {"REJECTED"}
    assert "cause_inferred_not_allowed" in records[0]["validation_errors"]
    assert "unknown_evidence_ref" in records[1]["validation_errors"]
    assert "context_id_mismatch" in records[2]["validation_errors"]
    assert "schema_version_invalid" in records[3]["validation_errors"]


def test_potential_conflict_is_recorded_without_overwriting_winner() -> None:
    temp_dir, _db_path, connection, _cliente_id, *_rest, context = _context_with_visual_evidence()
    with temp_dir, connection:
        request = build_understanding_request(context, request_id="vur-conflict")
        result = _result(request, understanding_id="vu-conflict-1")
        result["visual_facts"][0]["description"] = "No person visible in the selected image."
        record = validate_normalize_and_persist_understanding(connection, video_context=context, request=request, result=result)

    assert record["conflicts"][0]["type"] == "potential_conflict"
    assert record["conflicts"][0]["canonical_fact"] == "person_presence=PRESENT"
    assert record["structured_result"]["visual_facts"][0]["description"] == "No person visible in the selected image."


def test_same_context_accepts_reanalysis_but_same_understanding_id_is_idempotent() -> None:
    temp_dir, _db_path, connection, _cliente_id, *_rest, context = _context_with_visual_evidence()
    with temp_dir, connection:
        request = build_understanding_request(context, request_id="vur-one")
        first = validate_normalize_and_persist_understanding(connection, video_context=context, request=request, result=_result(request, understanding_id="vu-same-1"))
        second = validate_normalize_and_persist_understanding(connection, video_context=context, request=request, result=_result(request, understanding_id="vu-same-1"))
        other_request = build_understanding_request(context, request_id="vur-two")
        third = validate_normalize_and_persist_understanding(connection, video_context=context, request=other_request, result=_result(other_request, understanding_id="vu-same-2"))
        records = list_validated_understandings(connection, UnderstandingFilters(context_id=context["context_id"]))

    assert first["understanding_id"] == second["understanding_id"]
    assert third["understanding_id"] != first["understanding_id"]
    assert len(records) == 2


def test_persisted_understanding_survives_reopen_and_filters_work() -> None:
    temp_dir, db_path, connection, cliente_id, _site_id, _area_id, _process_id, asset_id, camera_id, context = _context_with_visual_evidence()
    with temp_dir:
        context = _mark_complete(context)
        request = build_understanding_request(context, request_id="vur-persist")
        record = validate_normalize_and_persist_understanding(connection, video_context=context, request=request, result=_result(request, understanding_id="vu-persist-1"))
        connection.close()
        reopened = connect(db_path)
        init_db(reopened)
        try:
            loaded = get_validated_understanding(reopened, record["understanding_id"], tenant_id=cliente_id)
            filtered = list_validated_understandings(reopened, UnderstandingFilters(tenant_id=cliente_id, camera_id=camera_id, asset_id=asset_id, status="VALID"))
        finally:
            reopened.close()

    assert loaded is not None
    assert loaded["understanding_id"] == "vu-persist-1"
    assert filtered[0]["understanding_id"] == "vu-persist-1"


def test_video_understanding_post_persists_and_get_endpoints_return_records() -> None:
    temp_dir, db_path, connection, cliente_id, *_rest, context = _context_with_visual_evidence()
    with temp_dir:
        create_user(connection, "validated-vu@example.com", "senha", "admin_cliente", cliente_id)
        connection.close()

        def test_connect(_path=None):
            return connect(db_path)

        with patch("app.api.connect", test_connect), patch.dict("os.environ", {"CAMPEX_VIDEO_UNDERSTANDING_PROVIDER": "fake"}, clear=False):
            client = TestClient(api)
            client.post("/auth/login", json={"email": "validated-vu@example.com", "senha": "senha"})
            created = client.post(f"/operations/video-understanding/{context['context_id']}")
            listing = client.get("/operations/video-understandings", params={"context_id": context["context_id"]})
            detail = client.get(f"/operations/video-understandings/{created.json()['validated_understanding']['understanding_id']}")

    assert created.status_code == 200
    assert created.json()["validated_understanding"]["status"] in {"VALID", "PARTIAL"}
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert detail.status_code == 200
    assert detail.json()["context_id"] == context["context_id"]


def test_no_base64_api_key_or_raw_payload_is_persisted() -> None:
    temp_dir, _db_path, connection, _cliente_id, *_rest, context = _context_with_visual_evidence()
    with temp_dir, connection:
        request = build_understanding_request(context, request_id="vur-secret")
        result = _result(request, understanding_id="vu-secret-1")
        result["model_metadata"]["api_key"] = "sk-secret"
        result["model_metadata"]["raw_response"] = {"image_url": "data:image/png;base64,abc"}
        record = validate_normalize_and_persist_understanding(connection, video_context=context, request=request, result=result)
        raw = connection.execute("SELECT structured_result_json FROM video_understandings WHERE understanding_id = ?", (record["understanding_id"],)).fetchone()[0]

    assert "sk-secret" not in raw
    assert "data:image" not in raw
    assert "raw_response" not in raw
