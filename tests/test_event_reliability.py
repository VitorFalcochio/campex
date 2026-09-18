from datetime import datetime, timedelta, timezone
import sys
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.config import Settings
from backend.database.db import initialize_database
from backend.events.repository import EventRepository
from tests.helpers import make_settings


class _DummyCapture:
    def __init__(self, *args, **kwargs):
        pass

    def isOpened(self):
        return False

    def read(self):
        return False, None

    def release(self):
        pass

    def set(self, *args, **kwargs):
        return True

    def get(self, *args, **kwargs):
        return 0


def _app_without_real_cv2():
    sys.modules.setdefault(
        "cv2",
        SimpleNamespace(
            VideoCapture=_DummyCapture,
            CAP_FFMPEG=0,
            CAP_PROP_BUFFERSIZE=0,
            CAP_PROP_OPEN_TIMEOUT_MSEC=0,
            CAP_PROP_READ_TIMEOUT_MSEC=0,
            CAP_PROP_POS_FRAMES=0,
            CAP_PROP_FPS=0,
            FONT_HERSHEY_SIMPLEX=0,
            LINE_AA=0,
            rectangle=lambda *args, **kwargs: None,
            putText=lambda *args, **kwargs: None,
            line=lambda *args, **kwargs: None,
            circle=lambda *args, **kwargs: None,
            imwrite=lambda *args, **kwargs: True,
        ),
    )
    from backend.main import app

    return app


def test_event_repository_normalizes_reliability_facts(tmp_path):
    database_path = tmp_path / "events-reliability.sqlite3"
    settings = make_settings(database_path)
    initialize_database(settings)
    repo = EventRepository(settings)
    started_at = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc).isoformat()
    ended_at = datetime(2026, 9, 14, 12, 7, tzinfo=timezone.utc).isoformat()

    event = repo.create(
        event_type="WAITING_AT_STATION",
        camera_id="cam_1",
        zone_id="station_4",
        track_id=42,
        severity="attention",
        started_at=started_at,
        ended_at=ended_at,
        metadata={
            "area_id": "linha_a",
            "site_id": "plant_br_sp",
            "site_name": "Planta Sao Paulo",
            "line_id": "line_a",
            "machine_id": "machine_4",
            "machine_name": "Estacao 4",
            "station_id": "station_4",
            "activity_label": "Espera na Estacao 4",
            "snapshot_path": "storage/evidence/evt/frame.jpg",
            "context_before": {"queue": 3},
            "context_after": {"queue": 1},
            "shift_id": "shift_1",
            "timezone": "America/Sao_Paulo",
            "currency": "BRL",
        },
    )

    payload = event.as_dict()
    facts = payload["facts"]

    assert event.status == "CLOSED"
    assert event.duration == 420
    assert facts["person"]["track_id"] == 42
    assert facts["machine_area"]["site_id"] == "plant_br_sp"
    assert facts["machine_area"]["line_id"] == "line_a"
    assert facts["machine_area"]["station_id"] == "station_4"
    assert facts["machine_area"]["machine_id"] == "machine_4"
    assert facts["activity"]["category"] == "waiting"
    assert facts["activity"]["is_stop"] is True
    assert facts["timing"]["duration_seconds"] == 420
    assert facts["evidence"]["paths"] == ["storage/evidence/evt/frame.jpg"]
    assert facts["context"]["before"] == {"queue": 3}
    assert facts["context"]["shift_id"] == "shift_1"
    assert facts["context"]["currency"] == "BRL"
    assert facts["quality"]["has_person"] is True
    assert facts["quality"]["has_evidence"] is True
    assert facts["quality"]["is_reliable"] is True
    assert facts["quality"]["state"] == "RELIABLE"
    assert facts["quality"]["missing_required"] == []


def test_event_repository_marks_incomplete_reliability_facts(tmp_path):
    database_path = tmp_path / "events-incomplete-reliability.sqlite3"
    settings = make_settings(database_path)
    initialize_database(settings)
    repo = EventRepository(settings)
    started_at = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc).isoformat()

    event = repo.create(
        event_type="WAITING_AT_STATION",
        camera_id="cam_1",
        zone_id="station_4",
        track_id=42,
        severity="attention",
        started_at=started_at,
    )

    quality = event.as_dict()["facts"]["quality"]

    assert quality["state"] == "INCOMPLETE"
    assert quality["is_reliable"] is False
    assert quality["missing_required"] == ["duration", "evidence", "context"]


def test_event_api_ingests_reliable_event(monkeypatch, tmp_path):
    database_path = tmp_path / "events-api.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    initialize_database(Settings.from_env())
    started_at = datetime(2026, 9, 14, 13, 0, tzinfo=timezone.utc)
    ended_at = started_at + timedelta(minutes=3)

    with TestClient(_app_without_real_cv2()) as client:
        response = client.post(
            "/api/v1/events",
            json={
                "type": "MACHINE_WAITING",
                "camera_id": "cam_1",
                "zone_id": "station_4",
                "track_id": 7,
                "severity": "attention",
                "started_at": started_at.isoformat(),
                "ended_at": ended_at.isoformat(),
                "metadata": {
                    "area_id": "producao",
                    "machine_name": "Estacao 4",
                    "context_before": {"operator_nearby": False},
                    "context_after": {"operator_nearby": True},
                    "overlay_path": "storage/evidence/evt/overlay.jpg",
                },
            },
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "CLOSED"
    assert payload["duration"] == 180
    assert payload["facts"]["person"]["person_id"] == "track:7"
    assert payload["facts"]["activity"]["category"] == "waiting"
    assert payload["facts"]["machine_area"]["area_id"] == "producao"
    assert payload["facts"]["context"]["after"] == {"operator_nearby": True}


def test_event_api_rejects_inverted_time(monkeypatch, tmp_path):
    database_path = tmp_path / "events-api-invalid.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    initialize_database(Settings.from_env())
    started_at = datetime(2026, 9, 14, 13, 0, tzinfo=timezone.utc)
    ended_at = started_at - timedelta(seconds=1)

    with TestClient(_app_without_real_cv2()) as client:
        response = client.post(
            "/api/v1/events",
            json={
                "type": "MACHINE_WAITING",
                "camera_id": "cam_1",
                "started_at": started_at.isoformat(),
                "ended_at": ended_at.isoformat(),
            },
        )

    assert response.status_code == 422


def test_event_api_rejects_closed_event_without_reliable_facts(monkeypatch, tmp_path):
    database_path = tmp_path / "events-api-unreliable.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    initialize_database(Settings.from_env())
    started_at = datetime(2026, 9, 14, 13, 0, tzinfo=timezone.utc)
    ended_at = started_at + timedelta(minutes=2)

    with TestClient(_app_without_real_cv2()) as client:
        response = client.post(
            "/api/v1/events",
            json={
                "type": "MACHINE_WAITING",
                "camera_id": "cam_1",
                "zone_id": "station_4",
                "track_id": 7,
                "started_at": started_at.isoformat(),
                "ended_at": ended_at.isoformat(),
                "metadata": {
                    "machine_name": "Estacao 4",
                    "overlay_path": "storage/evidence/evt/overlay.jpg",
                },
            },
        )

    assert response.status_code == 422
    assert response.json()["detail"]["missing_required"] == ["context"]
