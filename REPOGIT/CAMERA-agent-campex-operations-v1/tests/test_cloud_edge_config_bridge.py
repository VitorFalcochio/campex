from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.auth import create_user
from app.database import connect as edge_connect, init_db
from app.edge_runtime import ProductionEdgeRuntime
from app.security import decrypt_secret
from cloud import database as cloud_database
from cloud import api as cloud_api_module
from cloud.security import hash_edge_secret
from edge_agent.sync_outbox import enqueue_sync_event, flush_sync_outbox
from shared.schemas import now_iso


EDGE_ID = "edge_config_a"
EDGE_SECRET = "edge-secret-config-123"


def _cloud_client(tmp_path: Path) -> TestClient:
    cloud_database.DATABASE_URL = ""
    cloud_database.SQLITE_CLOUD_PATH = tmp_path / "cloud.sqlite3"
    cloud_api_module.CLOUD_FRAME_DIR = tmp_path / "latest_frames"
    cloud_api_module.CLOUD_EVENT_EVIDENCE_DIR = tmp_path / "event_evidence"
    return TestClient(cloud_api_module.api)


def _login_admin(client: TestClient) -> None:
    with cloud_database.connect() as db:
        cloud_database.init_cloud_db(db)
        create_user(
            db,
            email="admin@campex.test",
            password="SenhaCampex123",
            role="admin_campex",
            nome="Admin",
        )
    response = client.post("/auth/login", json={"email": "admin@campex.test", "senha": "SenhaCampex123"})
    assert response.status_code == 200


def _tenant_with_edge(client: TestClient, edge_id: str = EDGE_ID, secret: str = EDGE_SECRET) -> tuple[str, str]:
    cliente = client.post("/clientes", json={"nome": "Cliente"})
    assert cliente.status_code == 200
    cliente_id = cliente.json()["id"]
    unidade = client.post("/unidades", json={"cliente_id": cliente_id, "nome": "Unidade"})
    assert unidade.status_code == 200
    unidade_id = unidade.json()["id"]
    edge = client.post(
        "/admin/edge-devices",
        json={
            "id": edge_id,
            "tenant_id": cliente_id,
            "cliente_id": cliente_id,
            "unidade_id": unidade_id,
            "nome": "Edge",
            "secret": secret,
        },
    )
    assert edge.status_code == 200
    return cliente_id, unidade_id


def test_edge_config_is_tenant_scoped_and_public_camera_does_not_leak_secret(tmp_path: Path) -> None:
    client = _cloud_client(tmp_path)
    _login_admin(client)
    cliente_id, unidade_id = _tenant_with_edge(client)
    other_cliente, other_unidade = _tenant_with_edge(client, "edge_other", "other-edge-secret-123")

    created = client.post(
        "/cameras/rtsp",
        json={
            "cliente_id": cliente_id,
            "unidade_id": unidade_id,
            "edge_id": EDGE_ID,
            "nome": "Camera A6",
            "rtsp_url": "rtsp://operator:super-secret@10.0.0.10:8554/live",
        },
    )
    assert created.status_code == 200
    public_camera = created.json()["camera"]
    assert "rtsp_username" not in public_camera
    assert "rtsp_password_encrypted" not in public_camera
    assert "super-secret" not in str(public_camera)

    other = client.post(
        "/cameras/rtsp",
        json={
            "cliente_id": other_cliente,
            "unidade_id": other_unidade,
            "edge_id": "edge_other",
            "nome": "Camera B",
            "rtsp_url": "rtsp://other:other-secret@10.0.0.20/live",
        },
    )
    assert other.status_code == 200

    config = client.get("/edge/config", headers={"X-Edge-Id": EDGE_ID, "X-Edge-Secret": EDGE_SECRET})
    assert config.status_code == 200
    cameras = config.json()["cameras"]
    assert [camera["nome"] for camera in cameras] == ["Camera A6"]
    assert cameras[0]["username"] == "operator"
    assert cameras[0]["password"] == "super-secret"
    assert "other-secret" not in str(config.json())

    wrong_edge = client.get("/edge/config", headers={"X-Edge-Id": EDGE_ID, "X-Edge-Secret": "wrong"})
    assert wrong_edge.status_code == 401


def test_edge_config_and_runtime_sync_include_areas_and_machine_monitors(tmp_path: Path) -> None:
    client = _cloud_client(tmp_path)
    _login_admin(client)
    cliente_id, unidade_id = _tenant_with_edge(client)
    camera = client.post(
        "/cameras/rtsp",
        json={
            "cliente_id": cliente_id,
            "unidade_id": unidade_id,
            "edge_id": EDGE_ID,
            "nome": "Camera A6",
            "host": "10.0.0.10",
        },
    ).json()["camera"]
    points = [{"x": 0.1, "y": 0.1}, {"x": 0.8, "y": 0.1}, {"x": 0.8, "y": 0.8}]
    area = client.post(
        f"/cameras/{camera['id']}/areas",
        json={"nome": "Região da máquina", "tipo": "machine_region", "pontos": points},
    ).json()
    monitor = client.post(
        f"/cameras/{camera['id']}/machine-monitors",
        json={
            "nome": "Monitor A6",
            "machine_polygon": points,
            "operator_polygon": points,
            "operation_polygon": points,
            "stop_seconds": 12,
            "operator_absence_seconds": 45,
            "stopped_with_operator_seconds": 90,
        },
    ).json()

    config = client.get("/edge/config", headers={"X-Edge-Id": EDGE_ID, "X-Edge-Secret": EDGE_SECRET}).json()
    assert config["areas"][0]["id"] == area["id"]
    assert config["areas"][0]["pontos"] == points
    assert config["machine_monitors"][0]["id"] == monitor["id"]
    assert config["machine_monitors"][0]["machine_polygon"] == points

    edge_db = tmp_path / "edge.sqlite3"
    with edge_connect(edge_db) as connection:
        init_db(connection)
    runtime = ProductionEdgeRuntime(edge_id=EDGE_ID, db_path=edge_db)
    runtime._fetch_cloud_edge_config = lambda _url, _secret: config  # type: ignore[method-assign]
    first = runtime.sync_cloud_edge_config("https://cloud.campex.test", EDGE_SECRET)
    second = runtime.sync_cloud_edge_config("https://cloud.campex.test", EDGE_SECRET)

    with edge_connect(edge_db) as connection:
        stored_area = connection.execute("SELECT * FROM monitored_areas WHERE id = ?", (area["id"],)).fetchone()
        stored_monitor = connection.execute("SELECT * FROM machine_monitors WHERE id = ?", (monitor["id"],)).fetchone()
        area_count = connection.execute("SELECT COUNT(*) AS total FROM monitored_areas WHERE id = ?", (area["id"],)).fetchone()["total"]
        monitor_count = connection.execute("SELECT COUNT(*) AS total FROM machine_monitors WHERE id = ?", (monitor["id"],)).fetchone()["total"]

    assert first["areas_upserted"] == 1
    assert first["monitors_upserted"] == 1
    assert second["areas_upserted"] == 1
    assert second["monitors_upserted"] == 1
    assert area_count == 1
    assert monitor_count == 1
    assert stored_area["camera_id"] == camera["id"]
    assert stored_area["pontos_json"] == json.dumps(points, ensure_ascii=False)
    assert stored_monitor["camera_id"] == camera["id"]
    assert stored_monitor["machine_polygon_json"] == json.dumps(points, ensure_ascii=False)
    assert stored_monitor["stop_seconds"] == 12


def test_cloud_live_view_configuration_persists_zones_and_monitor_from_cloud_routes(tmp_path: Path) -> None:
    client = _cloud_client(tmp_path)
    _login_admin(client)
    cliente_id, unidade_id = _tenant_with_edge(client)
    camera = client.post(
        "/cameras/rtsp",
        json={"cliente_id": cliente_id, "unidade_id": unidade_id, "edge_id": EDGE_ID, "nome": "Camera A6", "host": "10.0.0.10"},
    ).json()["camera"]
    machine_points = [{"x": 0.1, "y": 0.1}, {"x": 0.6, "y": 0.1}, {"x": 0.6, "y": 0.6}]
    operator_points = [{"x": 0.6, "y": 0.1}, {"x": 0.9, "y": 0.1}, {"x": 0.9, "y": 0.6}]

    machine_region = client.post(
        f"/cameras/{camera['id']}/areas",
        json={"nome": "Região da máquina", "tipo": "machine_region", "pontos": machine_points},
    )
    operator_zone = client.post(
        f"/cameras/{camera['id']}/areas",
        json={"nome": "Zona do operador", "tipo": "operator_zone", "pontos": operator_points},
    )
    assert machine_region.status_code == 200
    assert operator_zone.status_code == 200

    reloaded = client.get(f"/cameras/{camera['id']}/areas").json()
    assert {area["tipo"] for area in reloaded} == {"machine_region", "operator_zone"}

    deleted = client.delete(f"/areas/{operator_zone.json()['id']}")
    assert deleted.status_code == 200
    after_delete = client.get(f"/cameras/{camera['id']}/areas").json()
    assert [area["id"] for area in after_delete] == [machine_region.json()["id"]]

    monitor = client.post(
        f"/cameras/{camera['id']}/machine-monitors",
        json={
            "nome": "Monitor A6",
            "machine_polygon": machine_points,
            "operator_polygon": machine_points,
            "stop_seconds": 30,
        },
    )
    assert monitor.status_code == 200
    assert monitor.json()["machine_polygon"] == machine_points
    updated_monitor = client.post(
        f"/cameras/{camera['id']}/machine-monitors",
        json={
            "nome": "Monitor A6 ajustado",
            "machine_polygon": machine_points,
            "operator_polygon": machine_points,
            "stop_seconds": 45,
        },
    )
    assert updated_monitor.status_code == 200
    assert updated_monitor.json()["id"] == monitor.json()["id"]
    assert updated_monitor.json()["stop_seconds"] == 45
    assert client.get(f"/cameras/{camera['id']}/machine-monitors").json()[0]["id"] == monitor.json()["id"]


def test_edge_runtime_status_reaches_cloud_camera_status_and_stale_becomes_unknown(tmp_path: Path) -> None:
    client = _cloud_client(tmp_path)
    _login_admin(client)
    cliente_id, unidade_id = _tenant_with_edge(client)
    camera = client.post(
        "/cameras/rtsp",
        json={"cliente_id": cliente_id, "unidade_id": unidade_id, "edge_id": EDGE_ID, "nome": "Camera A6", "host": "10.0.0.10"},
    ).json()["camera"]

    active = client.post(
        "/edge/cameras/status",
        json={
            "cameras": [{
                "camera_id": camera["id"],
                "status": "online",
                "last_frame_at": now_iso(),
                "ai_status": "ativa",
                "people_count": 1,
                "machine_state": "ACTIVE",
                "machine_motion": 7.2,
                "machine_confidence": 0.91,
                "machine_reason": "motion_above_baseline",
                "machine_seconds_in_state": 18,
                "machine_analysis_status": "ready",
                "machine_monitor_id": "mon_a6",
            }]
        },
        headers={"X-Edge-Id": EDGE_ID, "X-Edge-Secret": EDGE_SECRET},
    )
    assert active.status_code == 200
    status = client.get(f"/cameras/{camera['id']}/status").json()
    assert status["runtime_source"] == "edge"
    assert status["machine_state"] == "ACTIVE"
    assert status["ai_status"] == "ativa"
    assert status["machine_monitor_id"] == "mon_a6"

    stopped = client.post(
        "/edge/cameras/status",
        json={"cameras": [{"camera_id": camera["id"], "status": "online", "machine_state": "STOPPED"}]},
        headers={"X-Edge-Id": EDGE_ID, "X-Edge-Secret": EDGE_SECRET},
    )
    assert stopped.status_code == 200
    assert client.get(f"/cameras/{camera['id']}/status").json()["machine_state"] == "STOPPED"

    with cloud_database.connect() as db:
        db.execute(
            "UPDATE cloud_cameras SET runtime_status_json = ? WHERE id = ?",
            (json.dumps({"camera_id": camera["id"], "machine_state": "ACTIVE", "received_at": "2000-01-01T00:00:00+00:00"}), camera["id"]),
        )
        db.commit()
    stale = client.get(f"/cameras/{camera['id']}/status").json()
    assert stale["machine_state"] == "UNKNOWN"
    assert stale["status"] == "offline"


def test_edge_uploads_latest_frame_and_cloud_user_reads_jpeg(tmp_path: Path) -> None:
    client = _cloud_client(tmp_path)
    _login_admin(client)
    cliente_id, unidade_id = _tenant_with_edge(client)
    created = client.post(
        "/cameras/rtsp",
        json={
            "cliente_id": cliente_id,
            "unidade_id": unidade_id,
            "edge_id": EDGE_ID,
            "nome": "Camera A6",
            "rtsp_url": "rtsp://operator:super-secret@10.0.0.10:8554/live",
        },
    )
    camera_id = created.json()["id"]

    first = client.post(
        f"/edge/cameras/{camera_id}/latest-frame",
        content=b"\xff\xd8first\xff\xd9",
        headers={"Content-Type": "image/jpeg", "X-Edge-Id": EDGE_ID, "X-Edge-Secret": EDGE_SECRET},
    )
    assert first.status_code == 200
    image = client.get(f"/cameras/{camera_id}/latest-frame")
    assert image.status_code == 200
    assert image.headers["content-type"].startswith("image/jpeg")
    assert image.headers["cache-control"] == "no-store"
    assert image.content == b"\xff\xd8first\xff\xd9"

    second = client.post(
        f"/edge/cameras/{camera_id}/latest-frame",
        content=b"\xff\xd8second\xff\xd9",
        headers={"Content-Type": "image/jpeg", "X-Edge-Id": EDGE_ID, "X-Edge-Secret": EDGE_SECRET},
    )
    assert second.status_code == 200
    assert client.get(f"/cameras/{camera_id}/latest-frame").content == b"\xff\xd8second\xff\xd9"
    assert client.get("/cameras/estado").json()[0]["ultimo_frame"]


def test_latest_frame_rejects_wrong_edge_and_other_tenant_reader(tmp_path: Path) -> None:
    client = _cloud_client(tmp_path)
    _login_admin(client)
    cliente_id, unidade_id = _tenant_with_edge(client)
    other_cliente, other_unidade = _tenant_with_edge(client, "edge_other", "other-edge-secret-123")
    created = client.post(
        "/cameras/rtsp",
        json={
            "cliente_id": cliente_id,
            "unidade_id": unidade_id,
            "edge_id": EDGE_ID,
            "nome": "Camera A6",
            "host": "10.0.0.10",
        },
    )
    camera_id = created.json()["id"]

    wrong_edge = client.post(
        f"/edge/cameras/{camera_id}/latest-frame",
        content=b"\xff\xd8bad\xff\xd9",
        headers={"Content-Type": "image/jpeg", "X-Edge-Id": "edge_other", "X-Edge-Secret": "other-edge-secret-123"},
    )
    assert wrong_edge.status_code == 403

    client.post(
        f"/edge/cameras/{camera_id}/latest-frame",
        content=b"\xff\xd8ok\xff\xd9",
        headers={"Content-Type": "image/jpeg", "X-Edge-Id": EDGE_ID, "X-Edge-Secret": EDGE_SECRET},
    )
    other_client = _cloud_client(tmp_path)
    with cloud_database.connect() as db:
        cloud_database.init_cloud_db(db)
        create_user(
            db,
            email="other@campex.test",
            password="SenhaCampex123",
            role="admin_cliente",
            nome="Other",
            cliente_id=other_cliente,
        )
    assert other_client.post("/auth/login", json={"email": "other@campex.test", "senha": "SenhaCampex123"}).status_code == 200
    assert other_client.get(f"/cameras/{camera_id}/latest-frame").status_code == 403


def test_edge_event_evidence_upload_makes_cloud_evidence_readable(tmp_path: Path) -> None:
    client = _cloud_client(tmp_path)
    _login_admin(client)
    cliente_id, unidade_id = _tenant_with_edge(client)
    camera = client.post(
        "/cameras/rtsp",
        json={"cliente_id": cliente_id, "unidade_id": unidade_id, "edge_id": EDGE_ID, "nome": "Camera A6", "host": "10.0.0.10"},
    ).json()["camera"]

    edge_db = tmp_path / "edge.sqlite3"
    evidence_path = tmp_path / "data" / "evidence" / "cam_a6" / "stop.jpg"
    evidence_path.parent.mkdir(parents=True)
    evidence_path.write_bytes(b"\xff\xd8event-evidence\xff\xd9")
    relative_evidence = evidence_path.relative_to(tmp_path).as_posix()
    event_uuid = "evt_evidence_bridge_001"
    payload = {
        "event_uuid": event_uuid,
        "tenant_id": cliente_id,
        "cliente_id": cliente_id,
        "unidade_id": unidade_id,
        "camera_id": camera["id"],
        "tipo": "machine_stoppage",
        "inicio": now_iso(),
        "fim": None,
        "duracao": None,
        "operador_presente": True,
        "confianca": 0.88,
        "midia_path": relative_evidence,
        "metadata": {"machine_monitor_id": "mon_a6"},
    }
    with edge_connect(edge_db) as connection:
        init_db(connection)
        enqueue_sync_event(connection, event_uuid=event_uuid, tenant_id=cliente_id, payload=payload, edge_id=EDGE_ID)

        def local_post(url: str, **kwargs):
            path = url.replace("https://cloud.campex.test", "")
            if path == "/edge/events":
                return client.post(path, json=kwargs.get("json"), headers=kwargs.get("headers"))
            if path == f"/edge/events/{event_uuid}/evidence":
                return client.post(path, content=kwargs.get("content"), headers=kwargs.get("headers"))
            raise AssertionError(url)

        with patch("edge_agent.sync_outbox.ROOT", tmp_path), patch("edge_agent.sync_outbox.httpx.post", side_effect=local_post):
            assert flush_sync_outbox(connection, "https://cloud.campex.test", EDGE_ID, EDGE_SECRET) == 1

    events = client.get("/eventos").json()
    assert events[0]["event_uuid"] == event_uuid
    image = client.get(f"/eventos/{event_uuid}/evidence")
    assert image.status_code == 200
    assert image.headers["content-type"].startswith("image/jpeg")
    assert image.content == b"\xff\xd8event-evidence\xff\xd9"


def test_edge_event_evidence_rejects_wrong_edge(tmp_path: Path) -> None:
    client = _cloud_client(tmp_path)
    _login_admin(client)
    cliente_id, unidade_id = _tenant_with_edge(client)
    camera = client.post(
        "/cameras/rtsp",
        json={"cliente_id": cliente_id, "unidade_id": unidade_id, "edge_id": EDGE_ID, "nome": "Camera A6", "host": "10.0.0.10"},
    ).json()["camera"]
    event_uuid = "evt_evidence_wrong_edge"
    received = client.post(
        "/edge/events",
        json={
            "event_uuid": event_uuid,
            "tenant_id": cliente_id,
            "cliente_id": cliente_id,
            "unidade_id": unidade_id,
            "camera_id": camera["id"],
            "tipo": "machine_stoppage",
            "inicio": now_iso(),
        },
        headers={"X-Edge-Id": EDGE_ID, "X-Edge-Secret": EDGE_SECRET},
    )
    assert received.status_code == 200
    assert client.post(
        f"/edge/events/{event_uuid}/evidence",
        content=b"\xff\xd8bad\xff\xd9",
        headers={"Content-Type": "image/jpeg", "X-Edge-Id": "edge_other", "X-Edge-Secret": "other-edge-secret-123"},
    ).status_code == 401


def test_frontend_cloud_viewer_uses_latest_frame_not_start_endpoint() -> None:
    source = Path("frontend/app.js").read_text()
    assert "function refreshCloudLatestFrame()" in source
    assert "latest-frame?t=" in source
    cloud_branch = source[source.index("if (isCloudFrontend())"):source.index("} else {", source.index("if (isCloudFrontend())"))]
    assert "refreshCloudLatestFrame();" in cloud_branch
    assert "/start" not in cloud_branch


def test_live_view_cloud_mode_uses_latest_frame_without_legacy_session_calls() -> None:
    source = Path("frontend/live-view.js").read_text()
    assert "function isCloudFrontend()" in source
    assert "/cameras/${encodeURIComponent(currentCameraId)}/latest-frame?t=" in source
    start_branch = source[source.index("if (isCloudFrontend())", source.index("async function startLiveView")):source.index("setStatus(\"conectando\", \"Abrindo transmissão...\");")]
    assert "/live-view/start" not in start_branch
    assert "/live-view/${sessionId}/stream" not in start_branch
    assert "/live-view/${sessionId}/ai/start" not in start_branch
    assert "sessionId = started.session_id" not in start_branch


def test_live_view_cloud_mode_keeps_configuration_controls_available() -> None:
    source = Path("frontend/live-view.js").read_text()
    controls = source[source.index("function configureCloudLiveViewControls()"):source.index("async function requestJson")]
    assert "configureRestrictedArea" not in controls
    assert "clearMachine" not in controls
    assert "if (!sessionId && !isCloudFrontend()) return;" in source
    assert "/areas/${zone.id}/${nextActive ? \"activate\" : \"deactivate\"}" in source
    assert "(machine && !isCloudFrontend()) ? `/machine-monitors/${machine.id}`" in source


def test_edge_runtime_syncs_cloud_camera_config_idempotently_and_deactivates_removed(tmp_path: Path) -> None:
    edge_db = tmp_path / "edge.sqlite3"
    with edge_connect(edge_db) as connection:
        init_db(connection)

    runtime = ProductionEdgeRuntime(edge_id=EDGE_ID, db_path=edge_db)
    payload = {
        "cameras": [
            {
                "id": "cam_cloud_a6",
                "cliente_id": "cli_cloud",
                "unidade_id": "uni_cloud",
                "edge_id": EDGE_ID,
                "nome": "Camera A6",
                "host": "10.0.0.10",
                "porta": 8554,
                "path": "/live",
                "username": "operator",
                "password": "super-secret",
                "secure_ref": "rtsp://***:***@10.0.0.10:8554/live",
                "ativa": True,
            }
        ]
    }
    runtime._fetch_cloud_edge_config = lambda _url, _secret: payload  # type: ignore[method-assign]

    first = runtime.sync_cloud_edge_config("https://cloud.campex.test", EDGE_SECRET)
    second = runtime.sync_cloud_edge_config("https://cloud.campex.test", EDGE_SECRET)

    with edge_connect(edge_db) as connection:
        row = connection.execute("SELECT * FROM cameras WHERE id = 'cam_cloud_a6'").fetchone()
        count = connection.execute("SELECT COUNT(*) AS total FROM cameras WHERE id = 'cam_cloud_a6'").fetchone()["total"]

    assert first["created"] == 1
    assert second["created"] == 0
    assert second["updated"] == 1
    assert count == 1
    assert row["nome"] == "Camera A6"
    assert row["rtsp_host"] == "10.0.0.10"
    assert row["rtsp_port"] == 8554
    assert row["rtsp_username"] == "operator"
    assert row["rtsp_password"] is None
    assert decrypt_secret(row["rtsp_password_encrypted"]) == "super-secret"
    assert row["ativa"] == 1

    payload["cameras"][0]["nome"] = "Camera A6 Atualizada"
    payload["cameras"][0]["host"] = "10.0.0.11"
    runtime.sync_cloud_edge_config("https://cloud.campex.test", EDGE_SECRET)
    with edge_connect(edge_db) as connection:
        updated = connection.execute("SELECT nome, rtsp_host FROM cameras WHERE id = 'cam_cloud_a6'").fetchone()
    assert updated["nome"] == "Camera A6 Atualizada"
    assert updated["rtsp_host"] == "10.0.0.11"

    payload["cameras"] = []
    deactivated = runtime.sync_cloud_edge_config("https://cloud.campex.test", EDGE_SECRET)
    with edge_connect(edge_db) as connection:
        inactive = connection.execute("SELECT ativa FROM cameras WHERE id = 'cam_cloud_a6'").fetchone()
    assert deactivated["deactivated"] == 1
    assert inactive["ativa"] == 0


def test_edge_runtime_uploads_latest_frame_from_existing_stream(tmp_path: Path) -> None:
    class OneShotEvent:
        def __init__(self) -> None:
            self.done = False

        def is_set(self) -> bool:
            return self.done

        def wait(self, _seconds: float) -> bool:
            self.done = True
            return True

    class FakeStream:
        def latest_jpeg(self) -> bytes:
            return b"\xff\xd8frame\xff\xd9"

    class FakeStreams:
        def statuses(self) -> list[dict[str, object]]:
            return [{"camera_id": "cam_a", "status": "online"}]

        def get(self, camera_id: str) -> FakeStream | None:
            return FakeStream() if camera_id == "cam_a" else None

    runtime = ProductionEdgeRuntime(edge_id=EDGE_ID, db_path=tmp_path / "edge.sqlite3", latest_frame_seconds=0.01)
    runtime.stop_event = OneShotEvent()  # type: ignore[assignment]
    uploads: list[tuple[str, str, bytes]] = []
    runtime._upload_latest_frame = lambda cloud_url, edge_secret, camera_id, jpeg: uploads.append((cloud_url, camera_id, jpeg))  # type: ignore[method-assign]

    with patch("app.edge_runtime.api_module.live_streams", FakeStreams()), patch.dict(
        "os.environ",
        {"CAMPEX_CLOUD_URL": "https://cloud.campex.test", "CAMPEX_EDGE_SECRET": EDGE_SECRET},
    ):
        runtime._run_latest_frame_upload()

    assert uploads == [("https://cloud.campex.test", "cam_a", b"\xff\xd8frame\xff\xd9")]
