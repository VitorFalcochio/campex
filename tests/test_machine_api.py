from fastapi.testclient import TestClient

from backend.config import Settings
from backend.database.db import initialize_database
from backend.main import app


def test_machine_crud(monkeypatch, tmp_path):
    database_path = tmp_path / "machines.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    initialize_database(Settings.from_env())

    with TestClient(app) as client:
        camera_response = client.post(
            "/api/v1/cameras",
            json={
                "name": "Linha 1",
                "source_type": "video_file",
                "source_uri": "palace.mp4",
                "enabled": False,
                "vision_enabled": False,
            },
        )
        camera_id = camera_response.json()["id"]

        create_response = client.post(
            "/api/v1/machines",
            json={
                "camera_id": camera_id,
                "name": "Prensa 01",
                "type": "fixed",
                "points": [[0.1, 0.1], [0.8, 0.1], [0.8, 0.8]],
                "requires_operator": True,
                "allow_idle": False,
                "min_person_distance": 0.12,
            },
        )
        machine = create_response.json()
        machine_id = machine["id"]

        list_response = client.get(f"/api/v1/machines?camera_id={camera_id}")
        patch_response = client.patch(
            f"/api/v1/machines/{machine_id}",
            json={"name": "Prensa 01A", "enabled": False},
        )
        delete_response = client.delete(f"/api/v1/machines/{machine_id}")
        after_delete = client.get(f"/api/v1/machines/{machine_id}")

    assert create_response.status_code == 201
    assert machine["name"] == "Prensa 01"
    assert machine["requires_operator"] is True
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1
    assert patch_response.status_code == 200
    assert patch_response.json()["name"] == "Prensa 01A"
    assert patch_response.json()["enabled"] is False
    assert delete_response.status_code == 204
    assert after_delete.status_code == 404


def test_machine_requires_existing_camera(monkeypatch, tmp_path):
    database_path = tmp_path / "machines-missing-camera.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    initialize_database(Settings.from_env())

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/machines",
            json={
                "camera_id": "cam_missing",
                "name": "Esteira A",
                "type": "conveyor",
                "points": [[0.1, 0.1], [0.8, 0.1], [0.8, 0.8]],
            },
        )

    assert response.status_code == 404
