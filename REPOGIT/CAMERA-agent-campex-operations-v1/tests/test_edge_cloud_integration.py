from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import hashlib
import httpx
from fastapi.testclient import TestClient

from app.auth import create_user
from app.database import connect as edge_connect
from app.database import init_db
from app.models import criar_camera, criar_cliente, criar_unidade, registrar_evento
from app.edge_runtime import ProductionEdgeRuntime
import deployment.run_campex_edge_windows as edge_windows
from cloud import database as cloud_database
from cloud.api import api as cloud_api
from edge_agent.sync_outbox import flush_sync_outbox, pending_sync_count


EDGE_ID = "edge_fl_plasticos_01"
EDGE_SECRET = "secret-local-com-mais-de-12"


class EdgeCloudIntegrationTest(unittest.TestCase):
    def make_cloud_client(self, temp_dir: str) -> TestClient:
        cloud_database.DATABASE_URL = ""
        cloud_database.SQLITE_CLOUD_PATH = Path(temp_dir) / "cloud.sqlite3"
        client = TestClient(cloud_api)

        with cloud_database.connect() as db:
            cloud_database.init_cloud_db(db)
            create_user(
                db,
                email="admin@campex.test",
                password="SenhaCampex123",
                role="admin_campex",
                nome="Admin Campex",
            )

        response = client.post(
            "/auth/login",
            json={
                "email": "admin@campex.test",
                "senha": "SenhaCampex123",
            },
        )
        assert response.status_code == 200

        return client

    def register_edge(self, client: TestClient, tenant_id: str = "cli_fl", unidade_id: str = "uni_fl") -> None:
        response = client.post(
            "/admin/edge-devices",
            json={
                "id": EDGE_ID,
                "tenant_id": tenant_id,
                "cliente_id": tenant_id,
                "unidade_id": unidade_id,
                "nome": "Edge FL Plasticos",
                "secret": EDGE_SECRET,
            },
        )
        self.assertEqual(response.status_code, 200)

    def sample_event(self, tenant_id: str = "cli_fl", unidade_id: str = "uni_fl") -> dict:
        return {
            "event_uuid": "evt-uuid-001",
            "tenant_id": tenant_id,
            "cliente_id": tenant_id,
            "unidade_id": unidade_id,
            "camera_id": "cam_01",
            "tipo": "machine_stoppage",
            "inicio": "2026-07-28T08:00:00-03:00",
            "fim": "2026-07-28T08:05:00-03:00",
            "duracao": 300,
            "operador_presente": False,
            "confianca": 0.91,
            "metadata": {"machine_name": "Extrusora principal"},
        }

    def test_cloud_receives_new_event_and_lists_for_dashboard(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = self.make_cloud_client(temp_dir)
            health = client.get("/health")
            dashboard = client.get("/dashboard")
            self.register_edge(client)
            response = client.post(
                "/edge/events",
                json=self.sample_event(),
                headers={"X-Edge-Id": EDGE_ID, "X-Edge-Secret": EDGE_SECRET, "Idempotency-Key": "evt-uuid-001"},
            )
            events = client.get("/eventos").json()
            operations = client.get("/operations/events").json()
            cameras = client.get("/cameras/estado").json()

        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "ok")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn('id="workspaceTitle"', dashboard.text)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "received")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_uuid"], "evt-uuid-001")
        self.assertEqual(len(operations["events"]), 1)
        self.assertEqual(operations["events"][0]["event_uuid"], "evt-uuid-001")
        self.assertEqual(cameras[0]["camera_id"], "cam_01")

    def test_duplicate_event_uuid_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = self.make_cloud_client(temp_dir)
            self.register_edge(client)
            headers = {"X-Edge-Id": EDGE_ID, "X-Edge-Secret": EDGE_SECRET, "Idempotency-Key": "evt-uuid-001"}
            first = client.post("/edge/events", json=self.sample_event(), headers=headers)
            updated_payload = {**self.sample_event(), "fim": "2026-07-28T08:07:00-03:00", "duracao": 420, "status": "closed", "severidade": "high"}
            second = client.post("/edge/events", json=updated_payload, headers=headers)
            events = client.get("/eventos").json()

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["status"], "duplicate_updated")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["duracao"], 420)
        self.assertEqual(events[0]["status"], "closed")
        self.assertEqual(events[0]["severidade"], "high")

    def test_invalid_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = self.make_cloud_client(temp_dir)
            self.register_edge(client)
            response = client.post(
                "/edge/events",
                json=self.sample_event(),
                headers={"X-Edge-Id": EDGE_ID, "X-Edge-Secret": "senha-errada"},
            )

        self.assertEqual(response.status_code, 401)

    def test_revoked_device_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = self.make_cloud_client(temp_dir)
            self.register_edge(client)
            with cloud_database.connect() as db:
                db.execute("UPDATE edge_devices SET status = 'revoked', revoked_at = ? WHERE id = ?", ("2026-07-28T09:00:00-03:00", EDGE_ID))
                db.commit()
            response = client.post(
                "/edge/events",
                json=self.sample_event(),
                headers={"X-Edge-Id": EDGE_ID, "X-Edge-Secret": EDGE_SECRET},
            )

        self.assertEqual(response.status_code, 403)

    def test_other_tenant_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = self.make_cloud_client(temp_dir)
            self.register_edge(client, tenant_id="cli_fl", unidade_id="uni_fl")
            response = client.post(
                "/edge/events",
                json=self.sample_event(tenant_id="cli_outro", unidade_id="uni_fl"),
                headers={"X-Edge-Id": EDGE_ID, "X-Edge-Secret": EDGE_SECRET},
            )

        self.assertEqual(response.status_code, 403)

    def test_edge_outbox_survives_failure_and_syncs_later(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "edge.sqlite3"
            with edge_connect(db_path) as connection:
                init_db(connection)
                cliente_id = criar_cliente(connection, "FL Plasticos")
                unidade_id = criar_unidade(connection, cliente_id, "Unidade")
                camera_id = criar_camera(connection, unidade_id, "Camera", cliente_id=cliente_id)
                registrar_evento(connection, cliente_id, unidade_id, camera_id, "machine_stoppage", event_uuid="evt-sync-001")
                self.assertEqual(pending_sync_count(connection), 1)
                with patch("edge_agent.sync_outbox.httpx.post", side_effect=httpx.ConnectError("offline")):
                    self.assertEqual(flush_sync_outbox(connection, "https://cloud.campex.test", EDGE_ID, EDGE_SECRET), 0)
                failed = connection.execute("SELECT status, attempts FROM sync_outbox WHERE event_uuid = ?", ("evt-sync-001",)).fetchone()

            reopened = sqlite3.connect(db_path)
            reopened.row_factory = sqlite3.Row
            try:
                reopened.execute("UPDATE sync_outbox SET next_attempt_at = NULL WHERE event_uuid = ?", ("evt-sync-001",))
                reopened.commit()

                class FakeResponse:
                    def raise_for_status(self) -> None:
                        return None

                with patch("edge_agent.sync_outbox.httpx.post", return_value=FakeResponse()) as poster:
                    synced = flush_sync_outbox(reopened, "https://cloud.campex.test", EDGE_ID, EDGE_SECRET)
                row = reopened.execute("SELECT status FROM sync_outbox WHERE event_uuid = ?", ("evt-sync-001",)).fetchone()
            finally:
                reopened.close()

        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["attempts"], 1)
        self.assertEqual(synced, 1)
        self.assertEqual(row["status"], "synced")
        poster.assert_called_once()

    def test_sync_failures_keep_outbox_for_retry_without_leaking_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "edge.sqlite3"
            cloud_url = "https://cloud.campex.test"
            edge_secret = "secret-local-com-mais-de-12"
            with edge_connect(db_path) as connection:
                init_db(connection)
                cliente_id = criar_cliente(connection, "FL Plasticos")
                unidade_id = criar_unidade(connection, cliente_id, "Unidade")
                camera_id = criar_camera(connection, unidade_id, "Camera", cliente_id=cliente_id)
                registrar_evento(connection, cliente_id, unidade_id, camera_id, "machine_stoppage", event_uuid="evt-sync-secret")

                with patch("edge_agent.sync_outbox.httpx.post", side_effect=httpx.ConnectError(f"offline {cloud_url} {edge_secret}")):
                    synced = flush_sync_outbox(connection, cloud_url, EDGE_ID, edge_secret)
                row = connection.execute("SELECT status, attempts, last_error FROM sync_outbox WHERE event_uuid = ?", ("evt-sync-secret",)).fetchone()

        self.assertEqual(synced, 0)
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["attempts"], 1)
        self.assertNotIn(edge_secret, row["last_error"])
        self.assertNotIn(cloud_url, row["last_error"])

    def test_timeout_and_http_5xx_keep_outbox_pending_for_later_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "edge.sqlite3"
            with edge_connect(db_path) as connection:
                init_db(connection)
                cliente_id = criar_cliente(connection, "FL Plasticos")
                unidade_id = criar_unidade(connection, cliente_id, "Unidade")
                camera_id = criar_camera(connection, unidade_id, "Camera", cliente_id=cliente_id)
                registrar_evento(connection, cliente_id, unidade_id, camera_id, "machine_stoppage", event_uuid="evt-timeout")
                registrar_evento(connection, cliente_id, unidade_id, camera_id, "machine_stoppage", event_uuid="evt-5xx")

                with patch("edge_agent.sync_outbox.httpx.post", side_effect=httpx.TimeoutException("timeout")):
                    self.assertEqual(flush_sync_outbox(connection, "https://cloud.campex.test", EDGE_ID, EDGE_SECRET, limit=1), 0)
                connection.execute("UPDATE sync_outbox SET next_attempt_at = '2999-01-01T00:00:00+00:00' WHERE event_uuid = ?", ("evt-timeout",))
                connection.commit()

                request = httpx.Request("POST", "https://cloud.campex.test/edge/events")
                response = httpx.Response(503, request=request, text="temporarily unavailable")
                with patch("edge_agent.sync_outbox.httpx.post", return_value=response):
                    self.assertEqual(flush_sync_outbox(connection, "https://cloud.campex.test", EDGE_ID, EDGE_SECRET, limit=1), 0)

                statuses = {
                    row["event_uuid"]: row["status"]
                    for row in connection.execute("SELECT event_uuid, status FROM sync_outbox WHERE event_uuid IN (?, ?)", ("evt-timeout", "evt-5xx")).fetchall()
                }

        self.assertEqual(statuses["evt-timeout"], "failed")
        self.assertEqual(statuses["evt-5xx"], "failed")

    def test_lost_ack_retry_is_idempotent_in_cloud_and_drains_outbox(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = self.make_cloud_client(temp_dir)
            db_path = Path(temp_dir) / "edge.sqlite3"
            with edge_connect(db_path) as connection:
                init_db(connection)
                cliente_id = criar_cliente(connection, "FL Plasticos")
                unidade_id = criar_unidade(connection, cliente_id, "Unidade")
                camera_id = criar_camera(connection, unidade_id, "Camera", cliente_id=cliente_id)
                self.register_edge(client, tenant_id=cliente_id, unidade_id=unidade_id)
                registrar_evento(connection, cliente_id, unidade_id, camera_id, "machine_stoppage", event_uuid="evt-lost-ack")
                payload = connection.execute("SELECT payload_json FROM sync_outbox WHERE event_uuid = ?", ("evt-lost-ack",)).fetchone()["payload_json"]

                accepted = client.post(
                    "/edge/events",
                    json=__import__("json").loads(payload),
                    headers={"X-Edge-Id": EDGE_ID, "X-Edge-Secret": EDGE_SECRET, "Idempotency-Key": "evt-lost-ack"},
                )
                self.assertEqual(accepted.status_code, 200)
                self.assertEqual(pending_sync_count(connection), 1)

                def local_post(url, json=None, headers=None, timeout=None):
                    return httpx.Response(
                        200,
                        json=client.post("/edge/events", json=json, headers=headers).json(),
                        request=httpx.Request("POST", url),
                    )

                with patch("edge_agent.sync_outbox.httpx.post", side_effect=local_post):
                    synced = flush_sync_outbox(connection, "https://cloud.campex.test", EDGE_ID, EDGE_SECRET)
                row = connection.execute("SELECT status FROM sync_outbox WHERE event_uuid = ?", ("evt-lost-ack",)).fetchone()
                events = client.get("/eventos").json()

        self.assertEqual(synced, 1)
        self.assertEqual(row["status"], "synced")
        self.assertEqual(len([item for item in events if item["event_uuid"] == "evt-lost-ack"]), 1)

    def test_invalid_cloud_secret_keeps_outbox_unsynced(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = self.make_cloud_client(temp_dir)
            self.register_edge(client)
            db_path = Path(temp_dir) / "edge.sqlite3"
            with edge_connect(db_path) as connection:
                init_db(connection)
                cliente_id = criar_cliente(connection, "FL Plasticos")
                unidade_id = criar_unidade(connection, cliente_id, "Unidade")
                camera_id = criar_camera(connection, unidade_id, "Camera", cliente_id=cliente_id)
                registrar_evento(connection, cliente_id, unidade_id, camera_id, "machine_stoppage", event_uuid="evt-invalid-secret")

                def local_post(url, json=None, headers=None, timeout=None):
                    return httpx.Response(
                        401,
                        json=client.post("/edge/events", json=json, headers=headers).json(),
                        request=httpx.Request("POST", url),
                    )

                with patch("edge_agent.sync_outbox.httpx.post", side_effect=local_post):
                    synced = flush_sync_outbox(connection, "https://cloud.campex.test", EDGE_ID, "wrong-secret")
                row = connection.execute("SELECT status, attempts FROM sync_outbox WHERE event_uuid = ?", ("evt-invalid-secret",)).fetchone()

        self.assertEqual(synced, 0)
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["attempts"], 1)

    def test_report_delivery_is_authenticated_persisted_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = self.make_cloud_client(temp_dir)
            with cloud_database.connect() as db:
                cloud_database.init_cloud_db(db)
                from cloud.security import hash_edge_secret
                db.execute(
                    """
                    INSERT INTO edge_devices (
                        id, tenant_id, cliente_id, unidade_id,
                        nome, secret_hash, status
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 'active')
                    """,
                    (
                        EDGE_ID,
                        "cli_fl",
                        "cli_fl",
                        "uni_fl",
                        "Edge FL Plasticos",
                        hash_edge_secret(EDGE_SECRET),
                    ),
                )
                db.commit()

            payload = {
                "delivery_id": "report-2026-09-02-cli-fl",
                "cliente_id": "cli_fl",
                "recipient": "gestor@example.com",
                "subject": "Campex | Relatório Operacional — 02/09/2026",
                "text_body": "Resumo operacional Campex.",
                "html_body": "<html><body>Resumo operacional Campex.</body></html>",
            }
            headers = {
                "X-Edge-Id": EDGE_ID,
                "X-Edge-Secret": EDGE_SECRET,
            }

            with patch(
                "cloud.api._send_cloud_report_email",
                return_value="provider-msg-001",
            ) as send_mock:
                first = client.post(
                    "/edge/report-delivery",
                    json=payload,
                    headers=headers,
                )
                second = client.post(
                    "/edge/report-delivery",
                    json=payload,
                    headers=headers,
                )

                conflict = client.post(
                    "/edge/report-delivery",
                    json={**payload, "subject": "Outro relatório"},
                    headers=headers,
                )

            with cloud_database.connect() as db:
                row = db.fetchone(
                    "SELECT * FROM report_deliveries WHERE id = ?",
                    (payload["delivery_id"],),
                )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["status"], "sent")
        self.assertFalse(first.json()["idempotent"])

        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["status"], "sent")
        self.assertTrue(second.json()["idempotent"])

        self.assertEqual(conflict.status_code, 409)

        self.assertEqual(send_mock.call_count, 1)
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "sent")
        self.assertEqual(row["attempts"], 1)
        self.assertEqual(row["provider_message_id"], "provider-msg-001")

    def test_postgresql_url_detection(self) -> None:
        self.assertTrue(cloud_database.is_postgres_url("postgresql://user:pass@host/db"))
        self.assertTrue(cloud_database.is_postgres_url("postgres://user:pass@host/db"))
        self.assertFalse(cloud_database.is_postgres_url("sqlite:///local.db"))

    def test_edge_update_check_no_approved_or_same_version_has_no_download(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = self.make_cloud_client(temp_dir)
            self.register_edge(client)
            no_update = client.post(
                "/edge/update/check",
                json={"current_version": "0.1.0-rc1"},
                headers={"X-Edge-Id": EDGE_ID, "X-Edge-Secret": EDGE_SECRET},
            )
            package = Path(temp_dir) / "edge.zip"
            package.write_bytes(b"zip")
            sha = hashlib.sha256(package.read_bytes()).hexdigest()
            with cloud_database.connect() as db:
                db.execute(
                    "INSERT INTO edge_update_releases (version, sha256, size_bytes, package_path, approved) VALUES (?, ?, ?, ?, 1)",
                    ("0.1.0-rc1", sha, package.stat().st_size, str(package)),
                )
                db.commit()
            same = client.post(
                "/edge/update/check",
                json={"current_version": "0.1.0-rc1"},
                headers={"X-Edge-Id": EDGE_ID, "X-Edge-Secret": EDGE_SECRET},
            )

        self.assertEqual(no_update.status_code, 200)
        self.assertFalse(no_update.json()["download_available"])
        self.assertEqual(same.status_code, 200)
        self.assertFalse(same.json()["download_available"])

    def test_edge_update_check_and_package_are_authenticated_and_hash_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = self.make_cloud_client(temp_dir)
            self.register_edge(client)
            package = Path(temp_dir) / "edge.zip"
            package.write_bytes(b"approved package")
            sha = hashlib.sha256(package.read_bytes()).hexdigest()
            with cloud_database.connect() as db:
                db.execute(
                    "INSERT INTO edge_update_releases (version, sha256, size_bytes, package_path, approved) VALUES (?, ?, ?, ?, 1)",
                    ("0.1.1-rc1", sha, package.stat().st_size, str(package)),
                )
                db.commit()
            denied = client.post(
                "/edge/update/check",
                json={"current_version": "0.1.0-rc1"},
                headers={"X-Edge-Id": EDGE_ID, "X-Edge-Secret": "wrong"},
            )
            check = client.post(
                "/edge/update/check",
                json={"current_version": "0.1.0-rc1"},
                headers={"X-Edge-Id": EDGE_ID, "X-Edge-Secret": EDGE_SECRET},
            )
            download = client.get(
                "/edge/update/package?version=0.1.1-rc1",
                headers={"X-Edge-Id": EDGE_ID, "X-Edge-Secret": EDGE_SECRET},
            )

        self.assertEqual(denied.status_code, 401)
        self.assertEqual(check.status_code, 200)
        self.assertTrue(check.json()["download_available"])
        self.assertEqual(check.json()["sha256"], sha)
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.content, b"approved package")

    def test_edge_runtime_stages_approved_update_and_hash_mismatch_never_marks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "data" / "edge.sqlite3"
            db_path.parent.mkdir()
            runtime = ProductionEdgeRuntime(edge_id=EDGE_ID, db_path=db_path)
            package_bytes = b"valid package"
            digest = hashlib.sha256(package_bytes).hexdigest()
            calls = []

            class FakeResponse:
                status = 200

                def __init__(self, data: bytes) -> None:
                    self.data = data
                    self.offset = 0

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

                def read(self, size: int = -1) -> bytes:
                    if size == -1:
                        return self.data
                    if self.offset >= len(self.data):
                        return b""
                    chunk = self.data[self.offset:self.offset + size]
                    self.offset += len(chunk)
                    return chunk

            def fake_urlopen(request, timeout):
                calls.append(request.full_url)
                if request.full_url.endswith("/edge/update/check"):
                    return FakeResponse(json.dumps({
                        "download_available": True,
                        "version": "0.1.1-rc1",
                        "sha256": digest,
                        "size": len(package_bytes),
                    }).encode("utf-8"))
                return FakeResponse(package_bytes)

            with patch("app.edge_runtime.urllib.request.urlopen", side_effect=fake_urlopen), patch.dict("os.environ", {}, clear=False):
                result = runtime.check_for_cloud_update("https://cloud.campex.test", EDGE_SECRET)
            marker = Path(temp_dir) / ".campex_update" / "pending_update.json"

            bad_runtime = ProductionEdgeRuntime(edge_id=EDGE_ID, db_path=Path(temp_dir) / "bad" / "edge.sqlite3")
            bad_runtime.db_path.parent.mkdir()

            def bad_urlopen(request, timeout):
                if request.full_url.endswith("/edge/update/check"):
                    return FakeResponse(json.dumps({
                        "download_available": True,
                        "version": "0.1.2-rc1",
                        "sha256": "0" * 64,
                        "size": len(package_bytes),
                    }).encode("utf-8"))
                return FakeResponse(package_bytes)

            with patch("app.edge_runtime.urllib.request.urlopen", side_effect=bad_urlopen):
                with self.assertRaises(RuntimeError):
                    bad_runtime.check_for_cloud_update("https://cloud.campex.test", EDGE_SECRET)

            self.assertEqual(result["update_status"], "STAGED")
            self.assertTrue(marker.exists())
            self.assertTrue(runtime.stop_event.is_set())
            self.assertEqual(json.loads(marker.read_text())["target_version"], "0.1.1-rc1")
            self.assertFalse((Path(temp_dir) / "bad" / ".campex_update" / "pending_update.json").exists())

    def test_update_check_failure_does_not_stop_heartbeat_or_outbox_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = ProductionEdgeRuntime(edge_id=EDGE_ID, db_path=Path(temp_dir) / "data" / "edge.sqlite3")
            runtime.db_path.parent.mkdir()
            calls = []

            def wait_once(_seconds):
                runtime.stop_event.set()
                return False

            with patch.dict("os.environ", {"CAMPEX_CLOUD_URL": "https://cloud.campex.test", "CAMPEX_EDGE_SECRET": EDGE_SECRET}), \
                 patch.object(runtime, "_send_cloud_heartbeat", side_effect=lambda *_args: calls.append("heartbeat")), \
                 patch.object(runtime, "check_for_cloud_update", side_effect=RuntimeError("https://secret/update failed")), \
                 patch.object(runtime, "sync_cloud_edge_config", side_effect=lambda *_args: calls.append("config")), \
                 patch.object(runtime, "_send_cloud_camera_statuses", side_effect=lambda *_args: calls.append("status")), \
                 patch("app.edge_runtime.flush_sync_outbox", side_effect=lambda *_args, **_kwargs: calls.append("outbox")), \
                 patch.object(runtime.stop_event, "wait", side_effect=wait_once):
                runtime._run_outbox_sync()

        self.assertIn("heartbeat", calls)
        self.assertIn("config", calls)
        self.assertIn("outbox", calls)
        self.assertEqual(runtime._last_update_error, "RuntimeError")

    def test_windows_supervisor_applies_update_preserving_env_data_and_records_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "Edge"
            root.mkdir()
            (root / "app").mkdir()
            (root / "app" / "old.py").write_text("old", encoding="utf-8")
            (root / ".env").write_text("CAMPEX_EDGE_SECRET=keep\n", encoding="utf-8")
            (root / "data").mkdir()
            (root / "data" / "edge.sqlite3").write_text("db", encoding="utf-8")
            package = Path(temp_dir) / "update.zip"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("app/new.py", "new")
                archive.writestr(".env", "bad")
                archive.writestr("data/edge.sqlite3", "bad")
            sha = hashlib.sha256(package.read_bytes()).hexdigest()
            update_dir = root / ".campex_update"
            update_dir.mkdir()
            marker = update_dir / "pending_update.json"
            marker.write_text(json.dumps({
                "current_version": "0.1.0-rc1",
                "target_version": "0.1.1-rc1",
                "staged_package": str(package),
                "expected_sha256": sha,
            }), encoding="utf-8")

            with patch.object(edge_windows, "ROOT", root), patch.object(edge_windows, "UPDATE_DIR", update_dir), patch.object(edge_windows, "UPDATE_MARKER", marker), patch.object(edge_windows, "VERSION_FILE", root / ".campex_version"):
                edge_windows.apply_pending_update()

            self.assertFalse(marker.exists())
            self.assertEqual((root / ".env").read_text(encoding="utf-8"), "CAMPEX_EDGE_SECRET=keep\n")
            self.assertEqual((root / "data" / "edge.sqlite3").read_text(encoding="utf-8"), "db")
            self.assertEqual((root / "app" / "new.py").read_text(encoding="utf-8"), "new")
            self.assertEqual((root / ".campex_version").read_text(encoding="utf-8").strip(), "0.1.1-rc1")
            self.assertTrue((update_dir / "backup_previous" / "app" / "old.py").exists())
            self.assertTrue((update_dir / "backup_previous" / edge_windows.BACKUP_READY_FILE).exists())
            metadata = json.loads((update_dir / "backup_previous" / edge_windows.BACKUP_READY_FILE).read_text(encoding="utf-8"))
            self.assertEqual(metadata["source_version"], "0.1.0-rc1")
            self.assertEqual(metadata["target_version"], "0.1.1-rc1")
            self.assertFalse((update_dir / "backup_building").exists())

    def test_windows_supervisor_rolls_back_when_apply_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "Edge"
            root.mkdir()
            (root / "app").mkdir()
            (root / "app" / "old.py").write_text("old", encoding="utf-8")
            package = Path(temp_dir) / "update.zip"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("app/new.py", "new")
            sha = hashlib.sha256(package.read_bytes()).hexdigest()
            update_dir = root / ".campex_update"
            update_dir.mkdir()
            marker = update_dir / "pending_update.json"
            marker.write_text(json.dumps({
                "current_version": "0.1.0-rc1",
                "target_version": "0.1.1-rc1",
                "staged_package": str(package),
                "expected_sha256": sha,
            }), encoding="utf-8")

            with patch.object(edge_windows, "ROOT", root), patch.object(edge_windows, "UPDATE_DIR", update_dir), patch.object(edge_windows, "UPDATE_MARKER", marker), patch.object(edge_windows, "VERSION_FILE", root / ".campex_version"), patch.object(edge_windows, "_extract_package", side_effect=RuntimeError("boom")):
                edge_windows.apply_pending_update()

            payload = json.loads(marker.read_text(encoding="utf-8"))

            self.assertEqual((root / "app" / "old.py").read_text(encoding="utf-8"), "old")
            self.assertFalse((root / "app" / "new.py").exists())
            self.assertEqual(payload["update_status"], "FAILED")
            self.assertTrue((update_dir / "backup_previous" / "app" / "old.py").exists())
            self.assertTrue((update_dir / "backup_previous" / edge_windows.BACKUP_READY_FILE).exists())

    def test_windows_supervisor_failed_marker_does_not_reapply(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "Edge"
            root.mkdir()
            (root / "app").mkdir()
            (root / "app" / "old.py").write_text("old", encoding="utf-8")
            package = Path(temp_dir) / "update.zip"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("app/new.py", "new")
            sha = hashlib.sha256(package.read_bytes()).hexdigest()
            update_dir = root / ".campex_update"
            update_dir.mkdir()
            marker = update_dir / "pending_update.json"
            marker.write_text(json.dumps({
                "update_status": "FAILED",
                "target_version": "0.1.1-rc1",
                "staged_package": str(package),
                "expected_sha256": sha,
            }), encoding="utf-8")

            with patch.object(edge_windows, "ROOT", root), patch.object(edge_windows, "UPDATE_DIR", update_dir), patch.object(edge_windows, "UPDATE_MARKER", marker), patch.object(edge_windows, "VERSION_FILE", root / ".campex_version"):
                edge_windows.apply_pending_update()

            payload = json.loads(marker.read_text(encoding="utf-8"))
            self.assertEqual((root / "app" / "old.py").read_text(encoding="utf-8"), "old")
            self.assertFalse((root / "app" / "new.py").exists())
            self.assertEqual(payload["update_status"], "FAILED")

    def test_windows_supervisor_applying_marker_restores_backup_and_marks_failed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "Edge"
            root.mkdir()
            (root / "app").mkdir()
            (root / "app" / "old.py").write_text("partial-new", encoding="utf-8")
            update_dir = root / ".campex_update"
            backup = update_dir / "backup_previous"
            (backup / "app").mkdir(parents=True)
            (backup / "app" / "old.py").write_text("old", encoding="utf-8")
            (backup / edge_windows.BACKUP_READY_FILE).write_text("ready", encoding="utf-8")
            building = update_dir / "backup_building"
            (building / "app").mkdir(parents=True)
            (building / "app" / "old.py").write_text("bad-building", encoding="utf-8")
            marker = update_dir / "pending_update.json"
            marker.write_text(json.dumps({
                "update_status": "APPLYING",
                "current_version": "0.1.0-rc1",
                "target_version": "0.1.1-rc1",
                "staged_package": str(Path(temp_dir) / "update.zip"),
                "expected_sha256": "0" * 64,
            }), encoding="utf-8")
            (backup / edge_windows.BACKUP_READY_FILE).write_text(json.dumps({
                "source_version": "0.1.0-rc1",
                "target_version": "0.1.1-rc1",
            }), encoding="utf-8")

            with patch.object(edge_windows, "ROOT", root), patch.object(edge_windows, "UPDATE_DIR", update_dir), patch.object(edge_windows, "UPDATE_MARKER", marker), patch.object(edge_windows, "VERSION_FILE", root / ".campex_version"):
                edge_windows.apply_pending_update()

            payload = json.loads(marker.read_text(encoding="utf-8"))
            self.assertEqual((root / "app" / "old.py").read_text(encoding="utf-8"), "old")
            self.assertEqual((backup / "app" / "old.py").read_text(encoding="utf-8"), "old")
            self.assertTrue(building.exists())
            self.assertEqual(payload["update_status"], "FAILED")
            self.assertEqual(payload["last_update_error"], "update_interrupted")

    def test_windows_supervisor_pending_update_reuses_matching_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "Edge"
            root.mkdir()
            (root / "app").mkdir()
            (root / "app" / "old.py").write_text("partial-new", encoding="utf-8")
            package = Path(temp_dir) / "update.zip"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("app/new.py", "new")
            sha = hashlib.sha256(package.read_bytes()).hexdigest()
            update_dir = root / ".campex_update"
            backup = update_dir / "backup_previous"
            (backup / "app").mkdir(parents=True)
            (backup / "app" / "old.py").write_text("original-backup", encoding="utf-8")
            (backup / edge_windows.BACKUP_READY_FILE).write_text(json.dumps({
                "source_version": "0.1.0-rc1",
                "target_version": "0.1.1-rc1",
            }), encoding="utf-8")
            marker = update_dir / "pending_update.json"
            marker.write_text(json.dumps({
                "update_status": "PENDING",
                "current_version": "0.1.0-rc1",
                "target_version": "0.1.1-rc1",
                "staged_package": str(package),
                "expected_sha256": sha,
            }), encoding="utf-8")

            with patch.object(edge_windows, "ROOT", root), patch.object(edge_windows, "UPDATE_DIR", update_dir), patch.object(edge_windows, "UPDATE_MARKER", marker), patch.object(edge_windows, "VERSION_FILE", root / ".campex_version"):
                edge_windows.apply_pending_update()

            self.assertEqual((backup / "app" / "old.py").read_text(encoding="utf-8"), "original-backup")
            self.assertFalse(marker.exists())

    def test_windows_supervisor_pending_update_replaces_previous_cycle_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "Edge"
            root.mkdir()
            (root / "app").mkdir()
            (root / "app" / "current.py").write_text("v2", encoding="utf-8")
            package = Path(temp_dir) / "update.zip"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("app/current.py", "v3")
            sha = hashlib.sha256(package.read_bytes()).hexdigest()
            update_dir = root / ".campex_update"
            backup = update_dir / "backup_previous"
            (backup / "app").mkdir(parents=True)
            (backup / "app" / "current.py").write_text("v1", encoding="utf-8")
            (backup / edge_windows.BACKUP_READY_FILE).write_text(json.dumps({
                "source_version": "v1",
                "target_version": "v2",
            }), encoding="utf-8")
            marker = update_dir / "pending_update.json"
            marker.write_text(json.dumps({
                "update_status": "PENDING",
                "current_version": "v2",
                "target_version": "v3",
                "staged_package": str(package),
                "expected_sha256": sha,
            }), encoding="utf-8")

            with patch.object(edge_windows, "ROOT", root), patch.object(edge_windows, "UPDATE_DIR", update_dir), patch.object(edge_windows, "UPDATE_MARKER", marker), patch.object(edge_windows, "VERSION_FILE", root / ".campex_version"):
                edge_windows.apply_pending_update()

            metadata = json.loads((backup / edge_windows.BACKUP_READY_FILE).read_text(encoding="utf-8"))
            self.assertEqual((backup / "app" / "current.py").read_text(encoding="utf-8"), "v2")
            self.assertEqual(metadata["source_version"], "v2")
            self.assertEqual(metadata["target_version"], "v3")

    def test_windows_supervisor_backup_build_failure_leaves_marker_pending_and_no_valid_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "Edge"
            root.mkdir()
            (root / "app").mkdir()
            (root / "app" / "old.py").write_text("old", encoding="utf-8")
            package = Path(temp_dir) / "update.zip"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("app/new.py", "new")
            sha = hashlib.sha256(package.read_bytes()).hexdigest()
            update_dir = root / ".campex_update"
            update_dir.mkdir()
            marker = update_dir / "pending_update.json"
            marker.write_text(json.dumps({
                "update_status": "PENDING",
                "current_version": "0.1.0-rc1",
                "target_version": "0.1.1-rc1",
                "staged_package": str(package),
                "expected_sha256": sha,
            }), encoding="utf-8")

            def fail_backup(_target, _marker):
                building = update_dir / "backup_building"
                (building / "app").mkdir(parents=True)
                (building / "app" / "old.py").write_text("partial", encoding="utf-8")
                raise RuntimeError("copy failed")

            with patch.object(edge_windows, "ROOT", root), patch.object(edge_windows, "UPDATE_DIR", update_dir), patch.object(edge_windows, "UPDATE_MARKER", marker), patch.object(edge_windows, "VERSION_FILE", root / ".campex_version"), patch.object(edge_windows, "_ensure_current_code_backup", side_effect=fail_backup):
                edge_windows.apply_pending_update()

            payload = json.loads(marker.read_text(encoding="utf-8"))
            self.assertEqual(payload["update_status"], "PENDING")
            self.assertFalse((update_dir / "backup_previous").exists())
            self.assertTrue((update_dir / "backup_building").exists())

    def test_windows_supervisor_pending_after_incomplete_backup_discards_and_retries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "Edge"
            root.mkdir()
            (root / "app").mkdir()
            (root / "app" / "old.py").write_text("old", encoding="utf-8")
            package = Path(temp_dir) / "update.zip"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("app/new.py", "new")
            sha = hashlib.sha256(package.read_bytes()).hexdigest()
            update_dir = root / ".campex_update"
            building = update_dir / "backup_building"
            (building / "app").mkdir(parents=True)
            (building / "app" / "old.py").write_text("partial", encoding="utf-8")
            marker = update_dir / "pending_update.json"
            marker.write_text(json.dumps({
                "update_status": "PENDING",
                "current_version": "0.1.0-rc1",
                "target_version": "0.1.1-rc1",
                "staged_package": str(package),
                "expected_sha256": sha,
            }), encoding="utf-8")

            with patch.object(edge_windows, "ROOT", root), patch.object(edge_windows, "UPDATE_DIR", update_dir), patch.object(edge_windows, "UPDATE_MARKER", marker), patch.object(edge_windows, "VERSION_FILE", root / ".campex_version"):
                edge_windows.apply_pending_update()

            backup = update_dir / "backup_previous"
            self.assertFalse(building.exists())
            self.assertTrue((backup / edge_windows.BACKUP_READY_FILE).exists())
            self.assertEqual((backup / "app" / "old.py").read_text(encoding="utf-8"), "old")
            self.assertFalse(marker.exists())

    def test_windows_supervisor_applying_ignores_incomplete_backup_building(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "Edge"
            root.mkdir()
            (root / "app").mkdir()
            (root / "app" / "old.py").write_text("partial-new", encoding="utf-8")
            update_dir = root / ".campex_update"
            building = update_dir / "backup_building"
            (building / "app").mkdir(parents=True)
            (building / "app" / "old.py").write_text("building-should-not-restore", encoding="utf-8")
            marker = update_dir / "pending_update.json"
            marker.write_text(json.dumps({
                "update_status": "APPLYING",
                "current_version": "0.1.0-rc1",
                "target_version": "0.1.1-rc1",
                "staged_package": str(Path(temp_dir) / "update.zip"),
                "expected_sha256": "0" * 64,
            }), encoding="utf-8")

            with patch.object(edge_windows, "ROOT", root), patch.object(edge_windows, "UPDATE_DIR", update_dir), patch.object(edge_windows, "UPDATE_MARKER", marker), patch.object(edge_windows, "VERSION_FILE", root / ".campex_version"):
                edge_windows.apply_pending_update()

            payload = json.loads(marker.read_text(encoding="utf-8"))
            self.assertEqual((root / "app" / "old.py").read_text(encoding="utf-8"), "partial-new")
            self.assertEqual(payload["update_status"], "FAILED")
            self.assertEqual(payload["last_update_error"], "update_interrupted")

    def test_windows_supervisor_sequential_updates_roll_back_to_immediate_previous_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "Edge"
            root.mkdir()
            (root / "app").mkdir()
            (root / "app" / "version.py").write_text("v1", encoding="utf-8")
            update_dir = root / ".campex_update"
            update_dir.mkdir()
            marker = update_dir / "pending_update.json"
            package_v2 = Path(temp_dir) / "v2.zip"
            with zipfile.ZipFile(package_v2, "w") as archive:
                archive.writestr("app/version.py", "v2")
            marker.write_text(json.dumps({
                "update_status": "PENDING",
                "current_version": "v1",
                "target_version": "v2",
                "staged_package": str(package_v2),
                "expected_sha256": hashlib.sha256(package_v2.read_bytes()).hexdigest(),
            }), encoding="utf-8")

            with patch.object(edge_windows, "ROOT", root), patch.object(edge_windows, "UPDATE_DIR", update_dir), patch.object(edge_windows, "UPDATE_MARKER", marker), patch.object(edge_windows, "VERSION_FILE", root / ".campex_version"):
                edge_windows.apply_pending_update()

            self.assertEqual((root / "app" / "version.py").read_text(encoding="utf-8"), "v2")
            package_v3 = Path(temp_dir) / "v3.zip"
            with zipfile.ZipFile(package_v3, "w") as archive:
                archive.writestr("app/version.py", "v3")
            marker.write_text(json.dumps({
                "update_status": "PENDING",
                "current_version": "v2",
                "target_version": "v3",
                "staged_package": str(package_v3),
                "expected_sha256": hashlib.sha256(package_v3.read_bytes()).hexdigest(),
            }), encoding="utf-8")

            with patch.object(edge_windows, "ROOT", root), patch.object(edge_windows, "UPDATE_DIR", update_dir), patch.object(edge_windows, "UPDATE_MARKER", marker), patch.object(edge_windows, "VERSION_FILE", root / ".campex_version"), patch.object(edge_windows, "_extract_package", side_effect=RuntimeError("boom")):
                edge_windows.apply_pending_update()

            payload = json.loads(marker.read_text(encoding="utf-8"))
            metadata = json.loads((update_dir / "backup_previous" / edge_windows.BACKUP_READY_FILE).read_text(encoding="utf-8"))

            self.assertEqual((root / "app" / "version.py").read_text(encoding="utf-8"), "v2")
            self.assertEqual(metadata["source_version"], "v2")
            self.assertEqual(metadata["target_version"], "v3")
            self.assertEqual(payload["update_status"], "FAILED")

    def test_edge_heartbeat_accepts_legacy_payload_without_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = self.make_cloud_client(temp_dir)
            self.register_edge(client)
            response = client.post(
                "/edge/heartbeat",
                json={},
                headers={"X-Edge-Id": EDGE_ID, "X-Edge-Secret": EDGE_SECRET},
            )
            diagnostics = client.get(f"/edges/{EDGE_ID}/diagnostics")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["diagnostics"], "not_provided")
        self.assertEqual(diagnostics.status_code, 200)
        self.assertEqual(diagnostics.json()["edge_id"], EDGE_ID)
        self.assertIsNone(diagnostics.json()["diagnostics"])

    def test_edge_heartbeat_persists_latest_diagnostics_snapshot_without_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = self.make_cloud_client(temp_dir)
            self.register_edge(client)
            first = {
                "diagnostics": {
                    "generated_at": "2026-09-03T10:00:00+00:00",
                    "edge": {
                        "version": "rc1",
                        "process_uptime_seconds": 12.5,
                        "python_version": "3.11.9",
                        "platform": "Windows",
                        "local_api_healthy": True,
                        "last_local_health_check_at": "2026-09-03T10:00:00+00:00",
                    },
                    "cameras": {
                        "total": 1,
                        "online": 1,
                        "offline": 0,
                        "items": [{
                            "camera_id": "cam_01",
                            "status": "online",
                            "last_frame_at": "2026-09-03T10:00:00+00:00",
                            "reconnect_attempts": 0,
                            "analysis_status": "ANALYZING",
                            "analysis_error": "rtsp://user:password@10.0.0.10/live",
                        }],
                    },
                    "machines": {
                        "total": 1,
                        "items": [{
                            "monitor_id": "mon_01",
                            "camera_id": "cam_01",
                            "machine_state": "STOPPED",
                            "analysis_status": "ANALYZING",
                            "signal_quality": 0.87,
                            "calibration_result": "PASS",
                            "frames_analyzed": 42,
                            "confidence": 0.91,
                            "reason": "motion below baseline",
                        }],
                    },
                    "edge_secret": "should-not-persist",
                }
            }
            second = {
                "diagnostics": {
                    **first["diagnostics"],
                    "generated_at": "2026-09-03T10:01:00+00:00",
                    "cameras": {**first["diagnostics"]["cameras"], "online": 0, "offline": 1},
                }
            }
            self.assertEqual(client.post("/edge/heartbeat", json=first, headers={"X-Edge-Id": EDGE_ID, "X-Edge-Secret": EDGE_SECRET}).status_code, 200)
            self.assertEqual(client.post("/edge/heartbeat", json=second, headers={"X-Edge-Id": EDGE_ID, "X-Edge-Secret": EDGE_SECRET}).status_code, 200)
            payload = client.get(f"/edges/{EDGE_ID}/diagnostics").json()
            with cloud_database.connect() as db:
                row = db.fetchone("SELECT last_diagnostics_json FROM edge_devices WHERE id = ?", (EDGE_ID,))

        self.assertEqual(payload["generated_at"], "2026-09-03T10:01:00+00:00")
        self.assertIsNotNone(payload["received_at"])
        self.assertEqual(payload["diagnostics"]["cameras"]["online"], 0)
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("should-not-persist", serialized)
        self.assertNotIn("rtsp://user:password", serialized)
        self.assertIn("[redacted]", serialized)
        self.assertIn("received_at", row["last_diagnostics_json"])

    def test_edge_diagnostics_auth_and_tenant_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = self.make_cloud_client(temp_dir)
            self.register_edge(client, tenant_id="cli_fl", unidade_id="uni_fl")
            client.post(
                "/edge/heartbeat",
                json={"diagnostics": {"generated_at": "2026-09-03T10:00:00+00:00", "edge": {}, "cameras": {}, "machines": {}}},
                headers={"X-Edge-Id": EDGE_ID, "X-Edge-Secret": EDGE_SECRET},
            )
            self.assertEqual(
                client.post("/edge/heartbeat", json={}, headers={"X-Edge-Id": EDGE_ID, "X-Edge-Secret": "wrong"}).status_code,
                401,
            )
            with cloud_database.connect() as db:
                cloud_database.init_cloud_db(db)
                create_user(
                    db,
                    email="tenant@campex.test",
                    password="SenhaCampex123",
                    role="admin_cliente",
                    nome="Tenant",
                    cliente_id="cli_other",
                )
            other = TestClient(cloud_api)
            self.assertEqual(other.post("/auth/login", json={"email": "tenant@campex.test", "senha": "SenhaCampex123"}).status_code, 200)
            forbidden = other.get(f"/edges/{EDGE_ID}/diagnostics")

        self.assertEqual(forbidden.status_code, 403)

    def test_edge_diagnostics_offline_is_not_reported_healthy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = self.make_cloud_client(temp_dir)
            self.register_edge(client)
            with cloud_database.connect() as db:
                db.execute(
                    "UPDATE edge_devices SET last_seen_at = ?, last_diagnostics_json = ? WHERE id = ?",
                    (
                        "2026-09-03T10:00:00+00:00",
                        json.dumps({
                            "received_at": "2026-09-03T10:00:00+00:00",
                            "diagnostics": {"generated_at": "2026-09-03T10:00:00+00:00", "edge": {}, "cameras": {}, "machines": {}},
                        }),
                        EDGE_ID,
                    ),
                )
                db.commit()
            payload = client.get(f"/edges/{EDGE_ID}/diagnostics").json()

        self.assertFalse(payload["online"])
        self.assertEqual(payload["status"], "offline")
        self.assertTrue(payload["stale"])

    def test_edge_diagnostics_old_generated_at_is_stale_even_when_received_now(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = self.make_cloud_client(temp_dir)
            self.register_edge(client)
            old_generated_at = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
            response = client.post(
                "/edge/heartbeat",
                json={"diagnostics": {"generated_at": old_generated_at, "edge": {}, "cameras": {}, "machines": {}}},
                headers={"X-Edge-Id": EDGE_ID, "X-Edge-Secret": EDGE_SECRET},
            )
            payload = client.get(f"/edges/{EDGE_ID}/diagnostics").json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["online"])
        self.assertTrue(payload["stale"])

    def test_edge_diagnostics_recent_online_snapshot_is_not_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = self.make_cloud_client(temp_dir)
            self.register_edge(client)
            generated_at = datetime.now(timezone.utc).isoformat()
            response = client.post(
                "/edge/heartbeat",
                json={"diagnostics": {"generated_at": generated_at, "edge": {}, "cameras": {}, "machines": {}}},
                headers={"X-Edge-Id": EDGE_ID, "X-Edge-Secret": EDGE_SECRET},
            )
            payload = client.get(f"/edges/{EDGE_ID}/diagnostics").json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["online"])
        self.assertFalse(payload["stale"])

    def test_runtime_collects_partial_diagnostics_and_heartbeat_continues_when_collection_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = ProductionEdgeRuntime(edge_id=EDGE_ID, db_path=Path(temp_dir) / "edge.sqlite3")
            with patch("app.edge_runtime.api_module.live_streams.statuses", return_value=[
                {
                    "camera_id": "cam_01",
                    "status": "online",
                    "last_frame_at": "2026-09-03T10:00:00+00:00",
                    "analysis_error": "failed with rtsp://user:password@10.0.0.10/live and token=abc",
                    "machine_monitor_id": "mon_01",
                    "machine_state": "ACTIVE",
                    "machine_analysis_status": "ANALYZING",
                    "machine_frames_analyzed": 10,
                    "machine_confidence": 0.88,
                    "machine_reason": "secret leaked in local reason",
                }
            ]), patch.object(runtime, "_check_local_api_health", return_value=None), patch("app.edge_runtime.db_connect", side_effect=RuntimeError("credential .env rtsp://secret")):
                diagnostics = runtime._collect_cloud_diagnostics()

            calls = []

            class FakeResponse:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

            def fake_urlopen(request, timeout):
                calls.append(json.loads(request.data.decode("utf-8")))
                return FakeResponse()

            with patch.object(runtime, "_collect_cloud_diagnostics", side_effect=RuntimeError("partial failure")), patch("app.edge_runtime.urllib.request.urlopen", side_effect=fake_urlopen):
                runtime._send_cloud_heartbeat("https://cloud.campex.test", EDGE_SECRET)

        self.assertEqual(diagnostics["cameras"]["online"], 1)
        serialized = json.dumps(diagnostics, ensure_ascii=False)
        self.assertNotIn("rtsp://user:password", serialized)
        self.assertNotIn("token=abc", serialized)
        self.assertNotIn("credential .env", serialized)
        self.assertIn("diagnostic_redacted", serialized)
        self.assertIn("monitor_query_failed", serialized)
        self.assertEqual(diagnostics["machines"]["items"][0]["machine_state"], "ACTIVE")
        self.assertEqual(calls, [{}])


if __name__ == "__main__":
    unittest.main()
