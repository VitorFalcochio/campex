from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import api as api_module
from app.api import api
from app.auth import create_user
from app.database import connect, init_db
from app.models import (
    criar_alert_delivery,
    criar_alert_recipient,
    criar_area_monitorada,
    criar_camera,
    criar_cliente,
    criar_ocorrencia_area_restrita,
    criar_unidade,
)


class FakeStream:
    def __init__(self, camera_id: str):
        self.camera_id = camera_id
        self.started = False

    def start(self) -> None:
        self.started = True

    def frames(self):
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\nfake\r\n"

    def public_status(self) -> dict[str, object]:
        return {"camera_id": self.camera_id, "status": "online", "started": self.started}

    def set_analysis(self, enabled: bool) -> dict[str, object]:
        return {"camera_id": self.camera_id, "status": "online", "ai_status": "ativa" if enabled else "inativa"}


class FakeLiveStreams:
    def __init__(self):
        self.streams: dict[str, FakeStream] = {}
        self.stopped: list[str] = []

    def get_or_create(self, camera_id: str, _source: str) -> FakeStream:
        self.streams.setdefault(camera_id, FakeStream(camera_id))
        return self.streams[camera_id]

    def get(self, camera_id: str) -> FakeStream | None:
        return self.streams.get(camera_id)

    def stop(self, camera_id: str) -> bool:
        self.stopped.append(camera_id)
        return camera_id in self.streams


def _make_context(tmp_path: Path):
    db_path = tmp_path / "security-gate.sqlite3"
    root = tmp_path / "root"
    replay_dir = root / "data" / "replays"
    evidence_dir = root / "data" / "evidence" / "cam-a"
    replay_dir.mkdir(parents=True)
    evidence_dir.mkdir(parents=True)
    replay_file = replay_dir / "event-a.mp4"
    evidence_file = evidence_dir / "event-a.jpg"
    replay_file.write_bytes(b"mp4")
    evidence_file.write_bytes(b"\xff\xd8jpg\xff\xd9")

    def test_connect(_db_path=None):
        return connect(db_path)

    with test_connect() as connection:
        init_db(connection)
        cliente_a = criar_cliente(connection, "Cliente A")
        unidade_a = criar_unidade(connection, cliente_a, "Unidade A")
        camera_a = criar_camera(connection, unidade_a, "Camera A", cliente_id=cliente_a, config_ref="rtsp://user:secret@camera-a/stream", source_type="rtsp")
        area_a = criar_area_monitorada(connection, camera_a, "Area A", [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.1}, {"x": 0.9, "y": 0.9}])
        event_a = criar_ocorrencia_area_restrita(
            connection,
            cliente_a,
            unidade_a,
            camera_a,
            area_a,
            regra_id=None,
            inicio="2026-08-11T10:00:00+00:00",
            quantidade_inicial=1,
            quantidade_maxima=1,
            track_ids=[1],
            confianca=0.9,
            midia_path="data/evidence/cam-a/event-a.jpg",
            severidade="high",
        )
        connection.execute("UPDATE eventos SET replay_path = ? WHERE id = ?", ("data/replays/event-a.mp4", event_a))
        recipient_a = criar_alert_recipient(connection, "Pessoa A", "a@example.com", cliente_id=cliente_a)
        delivery_a = criar_alert_delivery(connection, recipient_a, evento_id=event_a, status="failed")

        cliente_b = criar_cliente(connection, "Cliente B")
        unidade_b = criar_unidade(connection, cliente_b, "Unidade B")
        camera_b = criar_camera(connection, unidade_b, "Camera B", cliente_id=cliente_b, config_ref="rtsp://user:secret@camera-b/stream", source_type="rtsp")

        create_user(connection, "a@example.com", "senha-segura", "admin_cliente", cliente_a, "Cliente A")
        create_user(connection, "b@example.com", "senha-segura", "admin_cliente", cliente_b, "Cliente B")
        connection.commit()

    return {
        "connect": test_connect,
        "root": root,
        "event_a": event_a,
        "delivery_a": delivery_a,
        "camera_a": camera_a,
        "camera_b": camera_b,
    }


def _login(client: TestClient, email: str) -> None:
    response = client.post("/auth/login", json={"email": email, "senha": "senha-segura"})
    assert response.status_code == 200


def test_event_replay_and_evidence_require_auth_and_tenant(tmp_path: Path) -> None:
    context = _make_context(tmp_path)
    with patch.object(api_module, "connect", context["connect"]), patch.object(api_module, "ROOT", context["root"]):
        anonymous = TestClient(api)
        assert anonymous.get(f"/eventos/{context['event_a']}").status_code == 401
        assert anonymous.patch(f"/eventos/{context['event_a']}", json={"duracao": 10}).status_code == 401
        assert anonymous.post(
            "/eventos",
            json={
                "cliente_id": "qualquer",
                "unidade_id": "qualquer",
                "camera_id": context["camera_a"],
                "tipo": "machine_stoppage",
            },
        ).status_code == 401
        assert anonymous.get(f"/eventos/{context['event_a']}/replay").status_code == 401
        assert anonymous.get(f"/eventos/{context['event_a']}/evidence").status_code == 401

        allowed = TestClient(api)
        _login(allowed, "a@example.com")
        assert allowed.get(f"/eventos/{context['event_a']}").status_code == 200
        assert allowed.patch(f"/eventos/{context['event_a']}", json={"duracao": 10}).status_code == 200
        assert allowed.post(
            "/eventos",
            json={
                "cliente_id": allowed.get(f"/eventos/{context['event_a']}").json()["cliente_id"],
                "unidade_id": allowed.get(f"/eventos/{context['event_a']}").json()["unidade_id"],
                "camera_id": context["camera_a"],
                "tipo": "machine_stoppage",
            },
        ).status_code == 200
        assert allowed.get(f"/eventos/{context['event_a']}/replay").status_code == 200
        assert allowed.get(f"/eventos/{context['event_a']}/evidence").status_code == 200

        blocked = TestClient(api)
        _login(blocked, "b@example.com")
        assert blocked.get(f"/eventos/{context['event_a']}").status_code == 403
        assert blocked.patch(f"/eventos/{context['event_a']}", json={"duracao": 20}).status_code == 403
        assert blocked.get(f"/eventos/{context['event_a']}/replay").status_code == 403
        assert blocked.get(f"/eventos/{context['event_a']}/evidence").status_code == 403


def test_alert_delivery_get_and_retry_require_auth_and_tenant(tmp_path: Path) -> None:
    context = _make_context(tmp_path)
    with (
        patch.object(api_module, "connect", context["connect"]),
        patch("app.alerts.connect", context["connect"]),
        patch("app.alerts.send_email_alert", return_value=None),
    ):
        anonymous = TestClient(api)
        assert anonymous.get(f"/alert-deliveries/{context['delivery_a']}").status_code == 401
        assert anonymous.post(f"/alert-deliveries/{context['delivery_a']}/retry").status_code == 401

        blocked = TestClient(api)
        _login(blocked, "b@example.com")
        assert blocked.get(f"/alert-deliveries/{context['delivery_a']}").status_code == 403
        assert blocked.post(f"/alert-deliveries/{context['delivery_a']}/retry").status_code == 403

        allowed = TestClient(api)
        _login(allowed, "a@example.com")
        assert allowed.get(f"/alert-deliveries/{context['delivery_a']}").status_code == 200
        retry = allowed.post(f"/alert-deliveries/{context['delivery_a']}/retry")
        assert retry.status_code == 200
        assert retry.json()["id"] == context["delivery_a"]


def test_camera_stream_start_and_stop_require_auth_and_tenant(tmp_path: Path) -> None:
    context = _make_context(tmp_path)
    fake_streams = FakeLiveStreams()
    with (
        patch.object(api_module, "connect", context["connect"]),
        patch.object(api_module, "live_streams", fake_streams),
        patch.object(api_module, "test_rtsp_connection", return_value={"compativel": True, "fps": 30}),
        patch.dict("os.environ", {"CAMPEX_VIDEO_SOURCE_MODE": "file", "CAMPEX_VIDEO_FILE": str(tmp_path / "video.mp4")}),
    ):
        (tmp_path / "video.mp4").write_bytes(b"fake")
        anonymous = TestClient(api)
        assert anonymous.post(f"/cameras/{context['camera_a']}/start").status_code == 401
        assert anonymous.post(f"/cameras/{context['camera_a']}/stop").status_code == 401
        assert anonymous.post(f"/cameras/{context['camera_a']}/test-connection").status_code == 401
        assert anonymous.get(f"/cameras/{context['camera_a']}/stream").status_code == 401
        assert anonymous.get(f"/cameras/{context['camera_a']}/status").status_code == 401
        assert anonymous.post(f"/cameras/{context['camera_a']}/analysis/start").status_code == 401
        assert anonymous.post(f"/cameras/{context['camera_a']}/analysis/stop").status_code == 401

        blocked = TestClient(api)
        _login(blocked, "b@example.com")
        assert blocked.post(f"/cameras/{context['camera_a']}/start").status_code == 403
        assert blocked.post(f"/cameras/{context['camera_a']}/stop").status_code == 403
        assert blocked.post(f"/cameras/{context['camera_a']}/test-connection").status_code == 403
        assert blocked.get(f"/cameras/{context['camera_a']}/stream").status_code == 403
        assert blocked.get(f"/cameras/{context['camera_a']}/status").status_code == 403
        assert blocked.post(f"/cameras/{context['camera_a']}/analysis/start").status_code == 403
        assert blocked.post(f"/cameras/{context['camera_a']}/analysis/stop").status_code == 403

        allowed = TestClient(api)
        _login(allowed, "a@example.com")
        assert allowed.post(f"/cameras/{context['camera_a']}/start").status_code == 200
        test_connection = allowed.post(f"/cameras/{context['camera_a']}/test-connection")
        assert test_connection.status_code == 200
        assert "secret" not in test_connection.text
        assert allowed.get(f"/cameras/{context['camera_a']}/status").status_code == 200
        assert allowed.post(f"/cameras/{context['camera_a']}/analysis/start").status_code == 200
        assert allowed.post(f"/cameras/{context['camera_a']}/analysis/stop").status_code == 200
        assert allowed.get(f"/cameras/{context['camera_a']}/stream").status_code == 200
        assert allowed.post(f"/cameras/{context['camera_a']}/stop").status_code == 200
        assert context["camera_a"] in fake_streams.streams
        assert context["camera_a"] in fake_streams.stopped
