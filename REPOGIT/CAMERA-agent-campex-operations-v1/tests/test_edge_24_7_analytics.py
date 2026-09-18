from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import app.alerts as alerts_module
import app.pilot as pilot_module
from app import edge_runtime as edge_runtime_module
from app import api as api_module
from app.analytics import aggregate_period, compute_summary, data_quality, generate_insights, parse_dt
from app.api import api
from app.auth import create_user
from app.database import connect, init_db
from app.models import (
    atualizar_camera_operacao,
    atualizar_machine_monitor,
    criar_camera,
    criar_cliente,
    criar_machine_monitor,
    criar_unidade,
    registrar_edge_heartbeat,
    registrar_evento,
    registrar_operational_sample,
)
from shared.schemas import now_iso


class FakeStream:
    def __init__(self, camera_id: str, source: str) -> None:
        self.camera_id = camera_id
        self.source = source
        self.started = False
        self.start_count = 0
        self.analysis_enabled = False

    def start(self) -> None:
        self.started = True
        self.start_count += 1

    def set_analysis(self, enabled: bool):
        self.analysis_enabled = enabled
        return self.public_status()

    def public_status(self) -> dict[str, object]:
        return {
            "camera_id": self.camera_id,
            "status": "online" if self.started else "offline",
            "last_frame_at": now_iso() if self.started else None,
            "analysis_fps": 3.0 if self.analysis_enabled else 0.0,
            "analysis_frames": 4 if self.analysis_enabled else 0,
            "last_analysis_at": now_iso() if self.analysis_enabled else None,
            "machine_monitor_id": "mach_loaded" if self.analysis_enabled else None,
        }


class FakeLiveStreams:
    def __init__(self, fail_camera_id: str | None = None) -> None:
        self.fail_camera_id = fail_camera_id
        self.streams: dict[str, FakeStream] = {}

    def get_or_create(self, camera_id: str, source: str) -> FakeStream:
        if camera_id == self.fail_camera_id:
            raise RuntimeError("camera inválida")
        stream = self.streams.get(camera_id)
        if stream is None:
            stream = FakeStream(camera_id, source)
            self.streams[camera_id] = stream
        return stream

    def statuses(self) -> list[dict[str, object]]:
        return [stream.public_status() for stream in self.streams.values()]

    def get(self, camera_id: str) -> FakeStream | None:
        return self.streams.get(camera_id)

    def stop(self, camera_id: str) -> bool:
        return self.streams.pop(camera_id, None) is not None

    def stop_all(self) -> None:
        self.streams.clear()


class Edge24x7AnalyticsTest(unittest.TestCase):
    def make_db(self, temp_dir: str):
        db_path = Path(temp_dir) / "edge24.sqlite3"
        connection = connect(db_path)
        init_db(connection)
        cliente_id = criar_cliente(connection, "Cliente Teste")
        unidade_id = criar_unidade(connection, cliente_id, "Unidade Teste")
        camera_id = criar_camera(connection, unidade_id, "Camera Teste", cliente_id=cliente_id, edge_id="edge_test")
        machine_id = criar_machine_monitor(
            connection,
            client_id=cliente_id,
            unit_id=unidade_id,
            camera_id=camera_id,
            nome="Extrusora Teste",
            machine_polygon=[{"x": 0.1, "y": 0.1}, {"x": 0.8, "y": 0.1}, {"x": 0.8, "y": 0.8}],
            operator_polygon=[{"x": 0.1, "y": 0.1}, {"x": 0.5, "y": 0.1}, {"x": 0.5, "y": 0.5}],
        )
        return connection, db_path, cliente_id, unidade_id, camera_id, machine_id

    def test_edge_heartbeat_is_persisted_and_exposed_in_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            connection, db_path, _cliente_id, _unidade_id, _camera_id, _machine_id = self.make_db(temp_dir)
            registrar_edge_heartbeat(
                connection,
                "edge_test",
                heartbeat_at=now_iso(),
                camera_online=True,
                last_frame_at="2026-08-05T10:00:00+00:00",
                capture_fps=15.0,
                inference_fps=4.0,
                frames_analyzed=40,
                outbox_pending=2,
                disk_free_bytes=123456,
                disk_used_percent=42.0,
            )

            def patched_connect(_path=None):
                return connect(db_path)

            with patch.object(api_module, "connect", patched_connect):
                client = TestClient(api)
                response = client.get("/edge/status?edge_id=edge_test")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["heartbeat"]["edge_id"], "edge_test")
        self.assertEqual(response.json()["heartbeat"]["frames_analyzed"], 40)

    def test_analytics_counts_event_once_and_persists_idempotent_hourly_aggregation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            connection, _db_path, cliente_id, unidade_id, camera_id, machine_id = self.make_db(temp_dir)
            event_id = registrar_evento(
                connection,
                cliente_id,
                unidade_id,
                camera_id,
                "machine_stoppage",
                inicio="2026-08-05T10:10:00+00:00",
                fim="2026-08-05T10:20:00+00:00",
                duracao=600,
            )
            connection.execute("UPDATE eventos SET machine_monitor_id = ? WHERE id = ?", (machine_id, event_id))
            connection.commit()
            start = parse_dt("2026-08-05T10:00:00+00:00")
            end = parse_dt("2026-08-05T11:00:00+00:00")

            first = aggregate_period(connection, machine_id=machine_id, camera_id=camera_id, start=start, end=end, aggregation="hour")
            second = aggregate_period(connection, machine_id=machine_id, camera_id=camera_id, start=start, end=end, aggregation="hour")
            rows = connection.execute("SELECT COUNT(*) AS total FROM hourly_machine_metrics").fetchone()["total"]

        self.assertEqual(first["stoppage_count"], 1)
        self.assertEqual(first["stopped_seconds"], 600)
        self.assertEqual(second["stoppage_count"], 1)
        self.assertEqual(rows, 1)

    def test_data_quality_reports_missing_samples_and_insights_are_traceable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            connection, _db_path, cliente_id, unidade_id, camera_id, machine_id = self.make_db(temp_dir)
            event_id = registrar_evento(
                connection,
                cliente_id,
                unidade_id,
                camera_id,
                "machine_running_without_operator",
                inicio="2026-08-05T12:00:00+00:00",
                fim="2026-08-05T12:03:00+00:00",
                duracao=180,
            )
            connection.execute("UPDATE eventos SET machine_monitor_id = ? WHERE id = ?", (machine_id, event_id))
            registrar_operational_sample(
                connection,
                sample_uuid="sample-1",
                tenant_id=cliente_id,
                unit_id=unidade_id,
                camera_id=camera_id,
                machine_id=machine_id,
                machine_state="ACTIVE",
                operator_present=False,
                activity_score=12.0,
                confidence=0.8,
                capture_fps=15.0,
                inference_fps=5.0,
                frames_analyzed=10,
                camera_online=True,
                sample_at="2026-08-05T12:00:00+00:00",
            )
            start = parse_dt("2026-08-05T12:00:00+00:00")
            end = parse_dt("2026-08-05T13:00:00+00:00")
            summary = compute_summary(connection, machine_id=machine_id, camera_id=camera_id, start=start, end=end)
            quality = data_quality(connection, machine_id=machine_id, camera_id=camera_id, start=start, end=end)
            insights = generate_insights(connection, machine_id=machine_id, camera_id=camera_id, start=start, end=end)

        self.assertEqual(summary["running_without_operator_seconds"], 180)
        self.assertTrue(quality["periods"])
        self.assertTrue(any(item["rule_id"] == "running_without_operator_v1" for item in insights))

    def test_production_bootstrap_starts_active_configured_camera_and_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            connection, db_path, _cliente_id, _unidade_id, camera_id, _machine_id = self.make_db(temp_dir)
            connection.execute("UPDATE cameras SET config_ref = ? WHERE id = ?", ("teste_maquina.mp4", camera_id))
            connection.commit()
            fake_streams = FakeLiveStreams()

            def patched_connect(_path=None):
                return connect(db_path)

            with patch.object(api_module, "connect", patched_connect), patch.object(pilot_module, "connect", patched_connect), patch.object(api_module, "live_streams", fake_streams):
                result = api_module.bootstrap_production_streams()

        self.assertEqual(len(result["started"]), 1)
        self.assertTrue(fake_streams.streams[camera_id].started)
        self.assertTrue(fake_streams.streams[camera_id].analysis_enabled)

    def test_invalid_camera_does_not_abort_production_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            connection, db_path, cliente_id, unidade_id, camera_id, _machine_id = self.make_db(temp_dir)
            bad_camera_id = criar_camera(connection, unidade_id, "Camera Ruim", cliente_id=cliente_id, config_ref="bad.mp4")
            connection.execute("UPDATE cameras SET config_ref = ? WHERE id = ?", ("teste_maquina.mp4", camera_id))
            connection.commit()
            fake_streams = FakeLiveStreams(fail_camera_id=bad_camera_id)

            def patched_connect(_path=None):
                return connect(db_path)

            with patch.object(api_module, "connect", patched_connect), patch.object(pilot_module, "connect", patched_connect), patch.object(api_module, "live_streams", fake_streams):
                result = api_module.bootstrap_production_streams()

        self.assertEqual(len(result["started"]), 1)
        self.assertEqual(len(result["failed"]), 1)
        self.assertIn(camera_id, fake_streams.streams)

    def test_production_bootstrap_restarts_existing_stream_after_failure_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            connection, db_path, _cliente_id, _unidade_id, camera_id, _machine_id = self.make_db(temp_dir)
            connection.execute("UPDATE cameras SET config_ref = ? WHERE id = ?", ("teste_maquina.mp4", camera_id))
            connection.commit()
            fake_streams = FakeLiveStreams()

            def patched_connect(_path=None):
                return connect(db_path)

            with patch.object(api_module, "connect", patched_connect), patch.object(api_module, "live_streams", fake_streams):
                api_module.bootstrap_production_streams()
                fake_streams.streams[camera_id].started = False
                api_module.bootstrap_production_streams()

        self.assertEqual(len(fake_streams.streams), 1)
        self.assertEqual(fake_streams.streams[camera_id].start_count, 2)
        self.assertTrue(fake_streams.streams[camera_id].analysis_enabled)

    def test_production_bootstrap_stops_deactivated_camera_stream(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            connection, db_path, _cliente_id, _unidade_id, camera_id, _machine_id = self.make_db(temp_dir)
            connection.execute("UPDATE cameras SET config_ref = ?, ativa = 0 WHERE id = ?", ("teste_maquina.mp4", camera_id))
            connection.commit()
            fake_streams = FakeLiveStreams()
            fake_streams.streams[camera_id] = FakeStream(camera_id, "teste_maquina.mp4")
            fake_streams.streams[camera_id].start()

            def patched_connect(_path=None):
                return connect(db_path)

            with patch.object(api_module, "connect", patched_connect), patch.object(api_module, "live_streams", fake_streams):
                result = api_module.bootstrap_production_streams()

        self.assertEqual(result["started"], [])
        self.assertNotIn(camera_id, fake_streams.streams)

    def test_production_runtime_binds_api_and_alerts_to_requested_database(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_db = Path(temp_dir) / "runtime.sqlite3"
            other_db = Path(temp_dir) / "other.sqlite3"
            with connect(runtime_db) as connection:
                init_db(connection)
                cliente_id = criar_cliente(connection, "Cliente Runtime")
                criar_unidade(connection, cliente_id, "Unidade Runtime")
            with connect(other_db) as connection:
                init_db(connection)

            runtime = edge_runtime_module.ProductionEdgeRuntime(edge_id="edge_test", db_path=runtime_db)
            original_api_connect = api_module.connect
            original_alerts_connect = alerts_module.connect
            original_pilot_connect = pilot_module.connect
            try:
                runtime._bind_runtime_database()
                with api_module.connect() as connection:
                    runtime_clients = connection.execute("SELECT COUNT(*) AS total FROM clientes").fetchone()["total"]
                with alerts_module.connect() as connection:
                    alert_clients = connection.execute("SELECT COUNT(*) AS total FROM clientes").fetchone()["total"]
                with pilot_module.connect() as connection:
                    pilot_clients = connection.execute("SELECT COUNT(*) AS total FROM clientes").fetchone()["total"]
                with connect(other_db) as connection:
                    other_clients = connection.execute("SELECT COUNT(*) AS total FROM clientes").fetchone()["total"]
            finally:
                api_module.connect = original_api_connect
                alerts_module.connect = original_alerts_connect
                pilot_module.connect = original_pilot_connect

        self.assertEqual(runtime_clients, 1)
        self.assertEqual(alert_clients, 1)
        self.assertEqual(pilot_clients, 1)
        self.assertEqual(other_clients, 0)

    def test_production_runtime_starts_api_camera_outbox_alert_and_heartbeat_workers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = edge_runtime_module.ProductionEdgeRuntime(
                edge_id="edge_test",
                db_path=Path(temp_dir) / "runtime.sqlite3",
                heartbeat_seconds=0.1,
                sync_seconds=0.1,
            )
            started_jobs: list[str] = []

            class ImmediateThread:
                def __init__(self, target, name, daemon):
                    self.target = target
                    self.name = name
                    self.daemon = daemon
                    started_jobs.append(name)

                def start(self):
                    return None

                def join(self, timeout=None):
                    return None

            original_api_connect = api_module.connect
            original_alerts_connect = alerts_module.connect
            original_pilot_connect = pilot_module.connect
            try:
                with patch.object(edge_runtime_module.threading, "Thread", ImmediateThread), patch.object(alerts_module, "resume_pending_deliveries"):
                    runtime.start()
                    runtime.shutdown()
            finally:
                api_module.connect = original_api_connect
                alerts_module.connect = original_alerts_connect
                pilot_module.connect = original_pilot_connect

        self.assertEqual(
            started_jobs,
            [
                "campex-api",
                "campex-camera-runtime",
                "campex-outbox-sync",
                "campex-alert-decisioning",
                "campex-alert-delivery-resume",
            ],
        )

    def test_ready_ignores_old_database_online_status_without_runtime_stream(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            connection, db_path, _cliente_id, _unidade_id, camera_id, _machine_id = self.make_db(temp_dir)
            atualizar_camera_operacao(connection, camera_id, "online", ultimo_frame="2026-08-05T10:00:00+00:00")

            def patched_connect(_path=None):
                return connect(db_path)

            with patch.object(api_module, "connect", patched_connect), patch.object(api_module, "live_streams", FakeLiveStreams()):
                response = TestClient(api).get("/ready")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "not_ready")
        self.assertEqual(response.json()["camera_stream"], "not_ready")

    def test_ready_requires_recent_frame_inference_and_loaded_monitor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            connection, db_path, _cliente_id, _unidade_id, camera_id, machine_id = self.make_db(temp_dir)
            atualizar_machine_monitor(
                connection,
                machine_id,
                active_baseline=20,
                stopped_baseline=2,
                calibration_result="READY",
            )
            fake_streams = FakeLiveStreams()
            stream = fake_streams.get_or_create(camera_id, "teste_maquina.mp4")
            stream.start()
            stream.set_analysis(True)
            original_public_status = stream.public_status

            def public_status_with_monitor():
                data = original_public_status()
                data["machine_monitor_id"] = machine_id
                return data

            stream.public_status = public_status_with_monitor

            def patched_connect(_path=None):
                return connect(db_path)

            with patch.object(api_module, "connect", patched_connect), patch.object(pilot_module, "connect", patched_connect), patch.object(api_module, "live_streams", fake_streams):
                response = TestClient(api).get("/ready")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ready")
        self.assertEqual(response.json()["camera_stream"], "ready")
        self.assertEqual(response.json()["inference"], "ready")
        self.assertEqual(response.json()["machine_monitor_loaded"], "ready")

    def test_health_and_checklist_use_runtime_frames_not_stale_camera_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            connection, db_path, cliente_id, _unidade_id, camera_id, _machine_id = self.make_db(temp_dir)
            create_user(connection, "admin@runtime.test", "senha-segura", "admin_cliente", cliente_id=cliente_id, nome="Admin")
            atualizar_camera_operacao(connection, camera_id, "offline", ultimo_frame=None)
            connection.execute("UPDATE cameras SET analysis_enabled = 0 WHERE id = ?", (camera_id,))
            connection.commit()
            fake_streams = FakeLiveStreams()
            stream = fake_streams.get_or_create(camera_id, "teste_maquina.mp4")
            stream.start()
            stream.set_analysis(True)

            def patched_connect(_path=None):
                return connect(db_path)

            with patch.object(api_module, "connect", patched_connect), patch.object(pilot_module, "connect", patched_connect), patch.object(api_module, "live_streams", fake_streams):
                client = TestClient(api)
                login = client.post("/auth/login", json={"email": "admin@runtime.test", "senha": "senha-segura"})
                self.assertEqual(login.status_code, 200)
                health = client.get("/system/health")
                checklist = client.get("/pilot/checklist")
                cameras = client.get("/cameras/estado")

        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["cameras_online"], 1)
        self.assertEqual(health.json()["cameras_offline"], 0)
        self.assertEqual(health.json()["ai_active"], 1)
        self.assertTrue(health.json()["ultimo_frame"])
        self.assertTrue(checklist.json()["checks"]["camera_conectada"])
        self.assertTrue(checklist.json()["checks"]["ia_ativa"])
        camera = next(item for item in cameras.json() if item["id"] == camera_id)
        self.assertEqual(camera["effective_status"], "online")
        self.assertTrue(camera["runtime"]["camera_online"])
        self.assertTrue(camera["runtime"]["inference_active"])

    def test_health_does_not_mark_online_without_recent_runtime_frame(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            connection, db_path, cliente_id, _unidade_id, camera_id, _machine_id = self.make_db(temp_dir)
            create_user(connection, "admin@stale.test", "senha-segura", "admin_cliente", cliente_id=cliente_id, nome="Admin")
            atualizar_camera_operacao(connection, camera_id, "online", ultimo_frame="2026-08-05T10:00:00+00:00")
            fake_streams = FakeLiveStreams()
            stream = fake_streams.get_or_create(camera_id, "teste_maquina.mp4")
            stream.start()
            original_public_status = stream.public_status

            def stale_public_status():
                data = original_public_status()
                data["last_frame_at"] = None
                data["last_analysis_at"] = None
                data["analysis_fps"] = 0
                data["analysis_frames"] = 0
                return data

            stream.public_status = stale_public_status

            def patched_connect(_path=None):
                return connect(db_path)

            with patch.object(api_module, "connect", patched_connect), patch.object(pilot_module, "connect", patched_connect), patch.object(api_module, "live_streams", fake_streams):
                client = TestClient(api)
                self.assertEqual(client.post("/auth/login", json={"email": "admin@stale.test", "senha": "senha-segura"}).status_code, 200)
                health = client.get("/system/health")
                ready = client.get("/ready")

        self.assertEqual(health.json()["cameras_online"], 0)
        self.assertEqual(health.json()["cameras_offline"], 1)
        self.assertEqual(health.json()["ai_active"], 0)
        self.assertEqual(ready.json()["camera_stream"], "not_ready")


if __name__ == "__main__":
    unittest.main()
