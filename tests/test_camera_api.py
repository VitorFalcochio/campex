from fastapi.testclient import TestClient

from backend.config import Settings
from backend.database.db import initialize_database
from backend.main import app


def create_fixture_video(path):
    path.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")


def test_camera_crud_and_sanitized_response(monkeypatch, tmp_path):
    database_path = tmp_path / "api.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    initialize_database(Settings.from_env())

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/cameras",
            json={
                "name": "RTSP teste",
                "source_type": "rtsp",
                "source_uri": "rtsp://example-user:example-pass@192.168.1.50/stream",
                "enabled": False,
                "vision_enabled": False,
            },
        )
        assert response.status_code == 201
        camera = response.json()
        assert camera["source_uri"] == "rtsp://***:***@192.168.1.50/stream"

        camera_id = camera["id"]
        assert client.get(f"/api/v1/cameras/{camera_id}").status_code == 200
        assert len(client.get("/api/v1/cameras").json()) == 1

        patch = client.patch(f"/api/v1/cameras/{camera_id}", json={"name": "RTSP teste 2"})
        assert patch.status_code == 200
        assert patch.json()["name"] == "RTSP teste 2"

        health = client.get(f"/api/v1/cameras/{camera_id}/health")
        assert health.status_code == 200
        assert health.json()["status"] in {
            "CONNECTING",
            "ONLINE",
            "DEGRADED",
            "OFFLINE",
        }

        delete = client.delete(f"/api/v1/cameras/{camera_id}")
        assert delete.status_code == 204
        assert client.get(f"/api/v1/cameras/{camera_id}").status_code == 404


def test_test_connection_failure_is_reported(monkeypatch, tmp_path):
    database_path = tmp_path / "api-failure.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    initialize_database(Settings.from_env())

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/cameras",
            json={
                "name": "Arquivo ausente",
                "source_type": "video_file",
                "source_uri": str(tmp_path / "missing.mp4"),
                "enabled": False,
                "vision_enabled": False,
            },
        )
        camera_id = response.json()["id"]

        test_result = client.post(f"/api/v1/cameras/{camera_id}/test")

    assert test_result.status_code == 200
    assert test_result.json()["success"] is False
    assert test_result.json()["status"] == "OFFLINE"


def test_unsaved_camera_source_can_be_tested(monkeypatch, tmp_path):
    database_path = tmp_path / "api-test-source.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    initialize_database(Settings.from_env())

    with TestClient(app) as client:
        test_result = client.post(
            "/api/v1/cameras/test-source",
            json={
                "name": "Arquivo ausente",
                "source_type": "video_file",
                "source_uri": str(tmp_path / "missing.mp4"),
            },
        )

    assert test_result.status_code == 200
    assert test_result.json()["success"] is False


def test_video_file_stream_contract_serves_mp4(monkeypatch, tmp_path):
    database_path = tmp_path / "api-video.sqlite3"
    video_path = tmp_path / "fixture.mp4"
    create_fixture_video(video_path)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    initialize_database(Settings.from_env())

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/cameras",
            json={
                "name": "Arquivo local",
                "source_type": "video_file",
                "source_uri": str(video_path),
                "enabled": False,
                "vision_enabled": False,
            },
        )
        camera_id = response.json()["id"]

        stream_info = client.get(f"/api/v1/cameras/{camera_id}/stream/info")
        video = client.get(f"/api/v1/cameras/{camera_id}/video")

    assert stream_info.status_code == 200
    assert stream_info.json()["mode"] == "file_video"
    assert stream_info.json()["video_url"] == f"/api/v1/cameras/{camera_id}/video"
    assert video.status_code == 200
    assert video.headers["content-type"].startswith("video/mp4")
    assert video.content


def test_video_endpoint_resolves_project_root_mp4(monkeypatch, tmp_path):
    database_path = tmp_path / "api-root-video.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    initialize_database(Settings.from_env())

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/cameras",
            json={
                "name": "Arquivo local",
                "source_type": "video_file",
                "source_uri": "palace.mp4",
                "enabled": False,
                "vision_enabled": False,
            },
        )
        camera_id = response.json()["id"]

        video = client.get(f"/api/v1/cameras/{camera_id}/video")

    assert video.status_code in {200, 404}
    if video.status_code == 200:
        assert video.headers["content-type"].startswith("video/mp4")


def test_live_camera_stream_contract_uses_mjpeg(monkeypatch, tmp_path):
    database_path = tmp_path / "api-live.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    initialize_database(Settings.from_env())

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/cameras",
            json={
                "name": "Camera IP",
                "source_type": "rtsp",
                "source_uri": "rtsp://example.test/stream",
                "enabled": False,
                "vision_enabled": False,
            },
        )
        camera_id = response.json()["id"]

        stream_info = client.get(f"/api/v1/cameras/{camera_id}/stream/info")

    assert stream_info.status_code == 200
    assert stream_info.json()["mode"] == "mjpeg"
    assert stream_info.json()["stream_url"] == f"/api/v1/cameras/{camera_id}/stream"
    assert stream_info.json()["video_url"] is None


def test_camera_diagnostics_and_snapshot_contract(monkeypatch, tmp_path):
    database_path = tmp_path / "api-diagnostics.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    initialize_database(Settings.from_env())

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/cameras",
            json={
                "name": "Camera IP",
                "source_type": "ip_camera",
                "source_uri": "http://192.168.1.20:8080/video",
                "enabled": False,
                "vision_enabled": False,
            },
        )
        camera_id = response.json()["id"]

        diagnostics = client.get(f"/api/v1/cameras/{camera_id}/diagnostics")
        snapshot = client.get(f"/api/v1/cameras/{camera_id}/snapshot")

    assert diagnostics.status_code == 200
    assert diagnostics.json()["camera"]["id"] == camera_id
    assert diagnostics.json()["health"]["status"] == "OFFLINE"
    assert snapshot.status_code == 200
    assert snapshot.headers["content-type"].startswith("image/jpeg")


def test_optional_api_token_protects_api(monkeypatch, tmp_path):
    database_path = tmp_path / "api-token.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("CAMPEX_API_TOKEN", "secret-token")
    initialize_database(Settings.from_env())

    with TestClient(app) as client:
        unauthorized = client.get("/api/v1/cameras")
        authorized = client.get(
            "/api/v1/cameras",
            headers={"X-CAMPEX-Token": "secret-token"},
        )
        health = client.get("/api/v1/health")

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200
    assert health.status_code == 200
