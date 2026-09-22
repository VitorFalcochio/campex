from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from fastapi.testclient import TestClient

from backend.vision.models import BoundingBox, Detection
from backend.main import app


class FakeDetector:
    name = "fake"
    device = "CPU"

    @property
    def is_loaded(self):
        return True

    def load(self):
        return None

    def detect(self, frame):
        return [
            Detection(
                class_name="person",
                confidence=0.91,
                bounding_box=BoundingBox(x1=20, y1=20, x2=70, y2=100),
            )
        ], 1.0


class FakeNemotronClient:
    model = "fake-nemotron"

    def __init__(self, settings):
        pass

    def chat(self, messages):
        return (
            '{"summary":"Foi observada uma pessoa no video analisado.",'
            '"sections":{"flow":"Foi observada uma pessoa no video analisado."}}'
        )


def test_video_analysis_upload_status_and_completion(monkeypatch, tmp_path):
    db_path = tmp_path / "video.sqlite3"
    upload_dir = tmp_path / "uploads"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("VIDEO_UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("VIDEO_ANALYSIS_FPS", "2")
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")
    monkeypatch.setattr("backend.videos.service.create_detector", lambda settings: FakeDetector())
    monkeypatch.setattr("backend.videos.service.NemotronClient", FakeNemotronClient)

    video_path = tmp_path / "sample.mp4"
    _write_video(video_path)

    with TestClient(app) as client:
        with video_path.open("rb") as handle:
            created = client.post(
                "/api/v1/videos/analyze",
                files={"file": ("sample.mp4", handle, "video/mp4")},
            )
        assert created.status_code == 202
        analysis_id = created.json()["analysis_id"]

        payload = _wait_completed(client, analysis_id)

    assert payload["status"] == "COMPLETED"
    assert payload["progress"] == 100
    assert payload["source"]["duration_seconds"] > 0
    assert payload["metrics"]["summary"]["unique_people"] >= 1
    assert payload["events"]
    assert payload["insight"]["summary"] == "Foi observada uma pessoa no video analisado."
    assert payload["insight"]["sections"]["flow"] == "Foi observada uma pessoa no video analisado."
    assert payload["ai"]["provider"] == "nvidia"
    assert payload["ai"]["fallback_used"] is False


def test_video_analysis_rejects_invalid_extension(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'invalid.sqlite3'}")
    monkeypatch.setenv("VIDEO_UPLOAD_DIR", str(tmp_path / "uploads"))

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/videos/analyze",
            files={"file": ("bad.txt", b"not video", "text/plain")},
        )

    assert response.status_code == 400
    assert "Only .mp4" in response.json()["detail"]


def _write_video(path: Path) -> None:
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        5.0,
        (120, 120),
    )
    for index in range(10):
        frame = np.zeros((120, 120, 3), dtype=np.uint8)
        cv2.rectangle(frame, (20 + index, 20), (70 + index, 100), (255, 255, 255), -1)
        writer.write(frame)
    writer.release()


def _wait_completed(client: TestClient, analysis_id: str) -> dict:
    import time

    for _ in range(50):
        response = client.get(f"/api/v1/videos/{analysis_id}/status")
        assert response.status_code == 200
        payload = response.json()
        if payload["status"] in {"COMPLETED", "FAILED"}:
            return payload
        time.sleep(0.1)
    raise AssertionError("video analysis did not finish")
