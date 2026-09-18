from fastapi.testclient import TestClient

from backend.main import app


def test_health_endpoint_returns_foundation_status():
    client = TestClient(app)

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "campex",
        "version": "0.1.0",
    }
