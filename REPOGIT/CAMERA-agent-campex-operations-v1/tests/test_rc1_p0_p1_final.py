from __future__ import annotations

import os
import tarfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient

import manage
from app import api as api_module
from app.api import api
from app.auth import create_user
from app.database import connect, init_db
from app.machine_monitoring import MachineMonitorConfig, MachineMonitorEngine
from app.models import criar_camera, criar_cliente, criar_unidade, listar_eventos_filtrados
from app.pilot import create_backup
from app.security import require_configured_credential_key


class FakeStream:
    def __init__(self, camera_id: str):
        self.camera_id = camera_id

    def start(self) -> None:
        return None

    def frames(self):
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\nfake\r\n"

    def public_status(self) -> dict[str, object]:
        return {"camera_id": self.camera_id, "status": "online", "fps": 30}


class FakeLiveStreams:
    def __init__(self):
        self.streams: dict[str, FakeStream] = {}

    def get_or_create(self, camera_id: str, _source: str) -> FakeStream:
        self.streams.setdefault(camera_id, FakeStream(camera_id))
        return self.streams[camera_id]

    def get(self, camera_id: str) -> FakeStream | None:
        return self.streams.get(camera_id)

    def stop(self, camera_id: str) -> bool:
        return self.streams.pop(camera_id, None) is not None


def _login(client: TestClient, email: str = "a@example.com") -> None:
    response = client.post("/auth/login", json={"email": email, "senha": "senha-segura"})
    assert response.status_code == 200


def _tenant_db(tmp_path: Path):
    db_path = tmp_path / "rc1.sqlite3"

    def test_connect(_path=None):
        return connect(db_path)

    with test_connect() as connection:
        init_db(connection)
        cliente_a = criar_cliente(connection, "Cliente A")
        unidade_a = criar_unidade(connection, cliente_a, "Unidade A")
        camera_a = criar_camera(connection, unidade_a, "Camera A", cliente_id=cliente_a, config_ref="rtsp://user:secret@camera-a/stream", source_type="rtsp")
        connection.execute(
            "UPDATE cameras SET rtsp_host = ?, rtsp_path = ?, rtsp_port = ? WHERE id = ?",
            ("camera-a", "/stream", 554, camera_a),
        )
        connection.commit()
        cliente_b = criar_cliente(connection, "Cliente B")
        unidade_b = criar_unidade(connection, cliente_b, "Unidade B")
        create_user(connection, "a@example.com", "senha-segura", "admin_cliente", cliente_a, "Admin A")
        create_user(connection, "b@example.com", "senha-segura", "admin_cliente", cliente_b, "Admin B")
    return test_connect, cliente_a, unidade_a, camera_a, cliente_b, unidade_b


def test_sensitive_camera_creation_and_live_view_are_authenticated_and_tenant_scoped(tmp_path: Path) -> None:
    test_connect, cliente_a, unidade_a, camera_a, _cliente_b, unidade_b = _tenant_db(tmp_path)
    with (
        patch.object(api_module, "connect", test_connect),
        patch.object(api_module, "live_streams", FakeLiveStreams()),
        patch.object(api_module, "test_rtsp_connection", return_value={"compativel": True}),
    ):
        anonymous = TestClient(api)
        assert anonymous.post("/cameras", json={"unidade_id": unidade_a, "nome": "Sem login"}).status_code == 401
        assert anonymous.post("/cameras/rtsp", json={"nome": "Sem login", "rtsp_url": "rtsp://user:secret@host/stream"}).status_code == 401
        assert anonymous.post("/cameras/test-connection", json={"rtsp_url": "rtsp://user:secret@host/stream"}).status_code == 401
        assert anonymous.post("/live-view/start", json={"camera_id": camera_a, "nome": "A"}).status_code == 401

        blocked = TestClient(api)
        _login(blocked, "b@example.com")
        assert blocked.post("/cameras", json={"unidade_id": unidade_b, "nome": "Camera B"}).status_code == 200
        assert blocked.post("/live-view/start", json={"camera_id": camera_a, "nome": "A"}).status_code == 403

        allowed = TestClient(api)
        _login(allowed)
        assert allowed.post("/cameras", json={"unidade_id": unidade_a, "nome": "Camera A2"}).status_code == 200
        raw_test = allowed.post("/cameras/test-connection", json={"rtsp_url": "rtsp://user:secret@host/stream"})
        assert raw_test.status_code == 200
        assert "secret" not in raw_test.text
        live = allowed.post("/live-view/start", json={"camera_id": camera_a, "nome": "A"})
        assert live.status_code == 200
        session_id = live.json()["session_id"]
        assert anonymous.get(f"/live-view/{session_id}/status").status_code == 401
        assert blocked.get(f"/live-view/{session_id}/stream").status_code == 403
        assert allowed.get(f"/live-view/{session_id}/status").status_code == 200


def test_encryption_key_has_no_known_production_fallback(monkeypatch) -> None:
    monkeypatch.delenv("CAMPEX_CREDENTIAL_KEY", raising=False)
    monkeypatch.delenv("CAMPEX_SECRET_KEY", raising=False)
    monkeypatch.setenv("CAMPEX_ENV", "production")
    try:
        require_configured_credential_key()
    except RuntimeError as exc:
        assert "CAMPEX_CREDENTIAL_KEY" in str(exc)
    else:
        raise AssertionError("production accepted missing credential key")

    monkeypatch.setenv("CAMPEX_CREDENTIAL_KEY", "troque-antes-do-piloto")
    try:
        require_configured_credential_key()
    except RuntimeError:
        pass
    else:
        raise AssertionError("production accepted placeholder credential key")


def test_manage_loads_dotenv_before_parser_defaults(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("CAMPEX_EDGE_ID=edge_dotenv\nDATABASE_PATH=data/from_dotenv.sqlite3\nAPI_PORT=8012\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CAMPEX_ENV_FILE", str(env_file))
    monkeypatch.delenv("CAMPEX_EDGE_ID", raising=False)
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    monkeypatch.delenv("API_PORT", raising=False)

    manage.load_env_file()
    parser = manage.build_parser()
    args = parser.parse_args(["run-edge-production"])

    assert args.edge_id == "edge_dotenv"
    assert args.db == "data/from_dotenv.sqlite3"
    assert args.port == 8012


def test_backup_excludes_env_file(tmp_path: Path) -> None:
    db_path = tmp_path / "visual_ops_product.sqlite3"
    with connect(db_path) as connection:
        init_db(connection)
    (tmp_path / ".env").write_text("CAMPEX_SMTP_PASSWORD=segredo\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text("CAMPEX_EMAIL_MODE=console\n", encoding="utf-8")
    with patch("app.pilot.ROOT", tmp_path), patch("app.pilot.DATABASE_PATH", db_path):
        archive = create_backup(tmp_path / "backups", db_path)

    with tarfile.open(archive, "r:gz") as tar:
        names = tar.getnames()
    assert ".env" not in names
    assert ".env.example" in names
    assert "data/visual_ops_product.sqlite3" in names


def test_docker_healthcheck_uses_health_not_ready() -> None:
    assert "http://127.0.0.1:8000/health" in Path("Dockerfile").read_text(encoding="utf-8")
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    assert "http://127.0.0.1:8000/health" in compose
    assert "http://127.0.0.1:8000/ready" not in compose


def test_machine_evidence_is_indexed_after_canonical_event(tmp_path: Path) -> None:
    db_path = tmp_path / "evidence.sqlite3"

    def test_connect(_path=None):
        return connect(db_path)

    with test_connect() as connection:
        init_db(connection)
        cliente_id = criar_cliente(connection, "Cliente")
        unidade_id = criar_unidade(connection, cliente_id, "Unidade")
        camera_id = criar_camera(connection, unidade_id, "Camera", cliente_id=cliente_id)
    config = MachineMonitorConfig(
        id="mach_rc1",
        client_id=cliente_id,
        unit_id=unidade_id,
        camera_id=camera_id,
        nome="A6",
        machine_polygon=[{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.1}, {"x": 0.9, "y": 0.9}],
        operator_polygon=[{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.1}, {"x": 0.9, "y": 0.9}],
        stop_seconds=0,
        recovery_seconds=0,
        active_baseline=20,
        stopped_baseline=1,
        motion_threshold=10,
    )
    engine = MachineMonitorEngine(config)
    frame = np.zeros((120, 120, 3), dtype=np.uint8)
    evidence_file = tmp_path / "data" / "evidence" / "machine.jpg"
    evidence_file.parent.mkdir(parents=True)
    evidence_file.write_bytes(b"\xff\xd8rc1\xff\xd9")
    with (
        patch("app.machine_monitoring.connect", test_connect),
        patch("app.machine_monitoring.save_machine_evidence", return_value=("data/evidence/machine.jpg", None)),
        patch("app.alerts.connect", test_connect),
        patch("app.alerts.send_email_alert", return_value=None),
    ):
        engine.state.state = "ACTIVE"
        engine.state.state_since = 0
        engine.state.smoothed_motion = 1
        engine.state.threshold = 10
        engine.state.confidence = 0.9
        engine._open_event(1, frame, "machine_stoppage")

    with test_connect() as connection:
        event = listar_eventos_filtrados(connection, tipo="machine_stoppage")[0]
        evidence = connection.execute("SELECT * FROM evidences WHERE event_id = ?", (event["id"],)).fetchone()
    assert event["midia_path"]
    assert evidence is not None
    assert evidence["event_uuid"] == event["event_uuid"]
