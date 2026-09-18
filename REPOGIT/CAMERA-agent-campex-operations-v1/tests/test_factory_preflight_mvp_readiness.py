from __future__ import annotations

from pathlib import Path

import manage
from app.database import connect, init_db
from app.models import criar_camera, criar_cliente, criar_unidade


def test_factory_preflight_checks_mvp_pipeline_endpoints(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "preflight.sqlite3"
    with connect(db_path) as connection:
        init_db(connection)
        cliente_id = criar_cliente(connection, "Cliente")
        unidade_id = criar_unidade(connection, cliente_id, "Fabrica")
        camera_id = criar_camera(connection, unidade_id, "Camera A6", cliente_id=cliente_id)

    called_paths: list[str] = []

    def fake_http_json(url: str, timeout: float = 3.0, opener=None, method: str = "GET", payload: dict | None = None):
        called_paths.append(url)
        if url.endswith("/health"):
            return 200, {"status": "ok"}, None
        if url.endswith("/auth/login"):
            return 200, {"user": {"email": "preflight@example.com"}}, None
        if url.endswith("/auth/status"):
            return 200, {"authenticated": True}, None
        if f"/cameras/{camera_id}/status" in url:
            return 200, {
                "status": "online",
                "last_frame_at": "2999-01-01T00:00:00+00:00",
                "ai_status": "ativa",
                "analysis_fps": 5.0,
                "analysis_frames": 10 if len([item for item in called_paths if f"/cameras/{camera_id}/status" in item]) == 1 else 12,
            }, None
        pipeline_paths = {
            "/operations/timeline",
            "/operations/change-anomalies",
            "/operations/video-contexts",
            "/operations/video-understandings",
            "/operations/alert-decisions",
            "/operations/briefing",
            "/operations/impact",
        }
        if any(path in url for path in pipeline_paths):
            return 200, {"ok": True}, None
        return 404, None, "not found"

    monkeypatch.setattr(manage, "_http_json", fake_http_json)
    monkeypatch.setattr(manage, "_http_sse_connected", lambda *args, **kwargs: (True, "connected"))
    monkeypatch.setattr(manage.time, "sleep", lambda _seconds: None)
    monkeypatch.setenv("CAMPEX_PREFLIGHT_EMAIL", "preflight@example.com")
    monkeypatch.setenv("CAMPEX_PREFLIGHT_PASSWORD", "senha")
    monkeypatch.setenv("CAMPEX_EMAIL_MODE", "console")

    result = manage.run_factory_preflight(db_path, "http://127.0.0.1:8000", camera_id, timeout=1.0, min_free_gb=0.0)

    assert result == 1
    expected_paths = [
        "/operations/timeline",
        "/operations/change-anomalies",
        "/operations/video-contexts",
        "/operations/video-understandings",
        "/operations/alert-decisions",
        "/operations/briefing",
        "/operations/impact",
    ]
    for path in expected_paths:
        assert any(path in url for url in called_paths)
