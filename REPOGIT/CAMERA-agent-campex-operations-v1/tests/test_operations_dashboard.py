from __future__ import annotations

import tempfile
import unittest
import os
from pathlib import Path
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient

from app import api as api_module
from app.alerts import enqueue_event_alert
from app.api import api
from app.database import connect
from app.models import criar_alert_recipient, registrar_operational_sample
from app.operations_history import (
    OperationsRecorder,
    close_open_operational_event,
    current_status,
    insert_operational_event,
    list_operational_events,
    operations_summary,
    operations_timeline,
)


ROOT = Path(__file__).resolve().parents[1]


class OperationsDashboardTest(unittest.TestCase):
    def _db(self, temp_dir: str):
        db_path = Path(temp_dir) / "operations.sqlite3"
        connection = connect(db_path)
        api_module.init_db(connection)
        return connection, db_path

    def test_open_and_close_events_with_duration(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            connection, _ = self._db(temp_dir)
            insert_operational_event(connection, "s1", "cam1", "Extrusora", "machine_state", None, "ATIVA", "2026-07-20T10:00:00+00:00")
            closed = close_open_operational_event(connection, "s1", "machine_state", "2026-07-20T10:05:30+00:00")
            events = list_operational_events(connection)
            canonical_total = connection.execute("SELECT COUNT(*) AS total FROM eventos").fetchone()["total"]
            legacy_total = connection.execute("SELECT COUNT(*) AS total FROM operational_events").fetchone()["total"]
            outbox_total = connection.execute("SELECT COUNT(*) AS total FROM sync_outbox").fetchone()["total"]

        self.assertIsNotNone(closed)
        self.assertEqual(closed["duration_seconds"], 330.0)
        self.assertEqual(events[0]["ended_at"], "2026-07-20T10:05:30+00:00")
        self.assertEqual(canonical_total, 1)
        self.assertEqual(legacy_total, 0)
        self.assertEqual(outbox_total, 1)

    def test_canonical_event_update_evidence_alert_and_samples_remain_separate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            connection, db_path = self._db(temp_dir)
            event_id = insert_operational_event(
                connection,
                "s1",
                "cam1",
                "Extrusora",
                "machine_state",
                None,
                "PARADA",
                "2026-07-20T10:00:00+00:00",
                confidence=0.91,
                activity_score=2.5,
                people_count=1,
                snapshot_path="data/evidence/frame.jpg",
            )
            criar_alert_recipient(connection, "Operador", "ops@example.com", cliente_id="cli_operational_compat")
            connection.close()
            with patch("app.alerts.connect", lambda: connect(db_path)), patch.dict("os.environ", {"CAMPEX_EMAIL_MODE": "console"}):
                enqueue_event_alert(event_id)
            reopened = connect(db_path)
            event = reopened.execute("SELECT * FROM eventos WHERE id = ?", (event_id,)).fetchone()
            deliveries = reopened.execute("SELECT COUNT(*) AS total FROM alert_deliveries WHERE evento_id = ?", (event_id,)).fetchone()["total"]
            legacy_total = reopened.execute("SELECT COUNT(*) AS total FROM operational_events").fetchone()["total"]

        self.assertEqual(event["midia_path"], "data/evidence/frame.jpg")
        self.assertEqual(deliveries, 1)
        self.assertEqual(legacy_total, 0)

    def test_summary_counts_active_stopped_and_biggest_stop(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            connection, _ = self._db(temp_dir)
            insert_operational_event(connection, "s1", "cam1", "Extrusora", "machine_state", None, "ATIVA", "2026-07-20T08:00:00+00:00")
            close_open_operational_event(connection, "s1", "machine_state", "2026-07-20T10:00:00+00:00")
            insert_operational_event(connection, "s1", "cam1", "Extrusora", "machine_state", "ATIVA", "PARADA", "2026-07-20T10:00:00+00:00")
            close_open_operational_event(connection, "s1", "machine_state", "2026-07-20T10:30:00+00:00")
            insert_operational_event(connection, "s1", "cam1", "Extrusora", "machine_state", "PARADA", "ATIVA", "2026-07-20T10:30:00+00:00")
            close_open_operational_event(connection, "s1", "machine_state", "2026-07-20T12:00:00+00:00")
            summary = operations_summary(connection, "2026-07-20T08:00:00+00:00", "2026-07-20T12:00:00+00:00", "cam1", "Extrusora")

        self.assertEqual(summary["tempo_total_monitorado"], 14400.0)
        self.assertEqual(summary["tempo_maquina_ativa"], 12600.0)
        self.assertEqual(summary["tempo_maquina_parada"], 1800.0)
        self.assertEqual(summary["quantidade_paradas"], 1)
        self.assertEqual(summary["maior_parada"], 1800.0)

    def test_active_without_operator_and_camera_offline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            connection, _ = self._db(temp_dir)
            insert_operational_event(connection, "s1", "cam1", "Extrusora", "active_without_operator", None, "ATIVA_SEM_OPERADOR", "2026-07-20T09:00:00+00:00")
            close_open_operational_event(connection, "s1", "active_without_operator", "2026-07-20T09:20:00+00:00")
            sample_base = {
                "tenant_id": "cli",
                "unit_id": "uni",
                "camera_id": "cam1",
                "machine_id": None,
                "machine_state": None,
                "operator_present": None,
                "activity_score": None,
                "confidence": None,
                "capture_fps": 12.0,
                "inference_fps": 5.0,
                "frames_analyzed": 1,
            }
            registrar_operational_sample(connection, **sample_base, sample_uuid="sample_online", camera_online=True, sample_at="2026-07-20T09:00:00+00:00")
            registrar_operational_sample(connection, **sample_base, sample_uuid="sample_offline", camera_online=False, sample_at="2026-07-20T09:30:00+00:00")
            registrar_operational_sample(connection, **sample_base, sample_uuid="sample_back", camera_online=True, sample_at="2026-07-20T10:00:00+00:00")
            summary = operations_summary(connection, "2026-07-20T09:00:00+00:00", "2026-07-20T11:00:00+00:00", "cam1", "Extrusora")

        self.assertEqual(summary["tempo_ativa_sem_operador"], 1200.0)
        self.assertEqual(summary["disponibilidade_camera"], 75.0)

    def test_recorder_does_not_create_camera_status_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            connection, db_path = self._db(temp_dir)
            connection.close()
            with patch("app.operations_history.connect", lambda: connect(db_path)):
                recorder_a = OperationsRecorder("s1", "cam1")
                recorder_a.update_status("online", None)
                recorder_b = OperationsRecorder("s1", "cam1")
                recorder_b.update_status("online", None)
            reopened = connect(db_path)
            events = list_operational_events(reopened)

        self.assertEqual([event for event in events if event["event_type"] == "camera_status"], [])

    def test_camera_status_insert_is_ignored_by_compat_event_layer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            connection, _ = self._db(temp_dir)
            event_id = insert_operational_event(connection, "s1", "cam1", "Extrusora", "camera_status", None, "offline", "2026-07-20T10:00:00+00:00")
            events = list_operational_events(connection)
            canonical_total = connection.execute("SELECT COUNT(*) AS total FROM eventos WHERE tipo = 'camera_status'").fetchone()["total"]

        self.assertEqual(event_id, "")
        self.assertEqual(events, [])
        self.assertEqual(canonical_total, 0)

    def test_cleanup_removes_only_safe_legacy_camera_status_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            connection, _ = self._db(temp_dir)
            connection.execute("INSERT INTO clientes (id, nome, status) VALUES ('cli', 'Cliente', 'ativo')")
            connection.execute("INSERT INTO unidades (id, cliente_id, nome) VALUES ('uni', 'cli', 'Unidade')")
            connection.execute("INSERT INTO cameras (id, cliente_id, unidade_id, nome) VALUES ('cam1', 'cli', 'uni', 'Camera')")
            event_id = connection.execute(
                """
                INSERT INTO eventos (id, event_uuid, cliente_id, unidade_id, camera_id, tipo, inicio, status, metadata_json)
                VALUES ('legacy_cam', 'uuid_legacy_cam', 'cli', 'uni', 'cam1', 'camera_status', '2026-07-20T10:00:00+00:00', 'open', ?)
                RETURNING id
                """,
                ('{"domain":"operations_history_compat"}',),
            ).fetchone()["id"]
            connection.execute(
                """
                INSERT INTO eventos (id, event_uuid, cliente_id, unidade_id, camera_id, tipo, inicio, status, metadata_json, asset_id)
                VALUES ('protected_cam', 'uuid_protected_cam', 'cli', 'uni', 'cam1', 'camera_status', '2026-07-20T10:00:00+00:00', 'open', ?, 'asset1')
                """,
                ('{"domain":"operations_history_compat"}',),
            )
            api_module.init_db(connection)
            removed = connection.execute("SELECT * FROM eventos WHERE id = ?", (event_id,)).fetchone()
            protected = connection.execute("SELECT * FROM eventos WHERE id = 'protected_cam'").fetchone()

        self.assertIsNone(removed)
        self.assertIsNotNone(protected)

    def test_live_view_session_does_not_become_persistent_camera_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            connection, db_path = self._db(temp_dir)
            connection.close()
            with patch("app.operations_history.connect", lambda: connect(db_path)):
                recorder = OperationsRecorder("live_abc123", "live_abc123")
                recorder.update_status("online", None)
            reopened = connect(db_path)
            events = list_operational_events(reopened)

        self.assertEqual(events, [])

    def test_machine_not_configured_does_not_create_machine_or_camera_offline_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            connection, db_path = self._db(temp_dir)
            connection.close()
            ops = {
                "machine": None,
                "machine_state": "NAO_CONFIGURADA",
                "operator_present": False,
                "people_count": 2,
            }
            with patch("app.operations_history.connect", lambda: connect(db_path)):
                recorder = OperationsRecorder("s1", "cam1")
                recorder.update_status("online", ops)
            reopened = connect(db_path)
            events = list_operational_events(reopened)
            status = current_status(reopened, "cam1")

        self.assertEqual(events, [])
        self.assertEqual(status["machine_state"], "NAO_CONFIGURADA")
        self.assertEqual(status["camera_status"], "online")

    def test_timeline_keeps_camera_availability_out_of_operational_states(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            connection, _ = self._db(temp_dir)
            insert_operational_event(connection, "s1", "cam1", "Extrusora", "machine_state", None, "ATIVA", "2026-07-20T08:10:00+00:00")
            close_open_operational_event(connection, "s1", "machine_state", "2026-07-20T09:00:00+00:00")
            timeline = operations_timeline(connection, "2026-07-20T08:00:00+00:00", "2026-07-20T09:00:00+00:00", "cam1", "Extrusora")

        self.assertEqual(len(timeline), 1)
        self.assertEqual(timeline[0]["state"], "ATIVA")

    def test_period_crossing_midnight_is_clipped_correctly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            connection, _ = self._db(temp_dir)
            insert_operational_event(connection, "s1", "cam1", "Extrusora", "machine_state", None, "PARADA", "2026-07-20T23:50:00+00:00")
            close_open_operational_event(connection, "s1", "machine_state", "2026-07-21T00:10:00+00:00")
            summary = operations_summary(connection, "2026-07-21T00:00:00+00:00", "2026-07-21T01:00:00+00:00", "cam1", "Extrusora")

        self.assertEqual(summary["tempo_maquina_parada"], 600.0)

    def test_absence_of_data_returns_zeroes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            connection, _ = self._db(temp_dir)
            summary = operations_summary(connection, "2026-07-20T00:00:00+00:00", "2026-07-20T01:00:00+00:00")
            timeline = operations_timeline(connection, "2026-07-20T00:00:00+00:00", "2026-07-20T01:00:00+00:00")

        self.assertEqual(summary["tempo_maquina_ativa"], 0)
        self.assertEqual(summary["quantidade_paradas"], 0)
        self.assertEqual(timeline, [])

    def test_recorder_persists_after_reopening_database(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            connection, db_path = self._db(temp_dir)
            connection.close()
            frame = np.zeros((24, 24, 3), dtype=np.uint8)
            ops = {
                "machine": {"nome": "Extrusora"},
                "machine_state": "ATIVA",
                "operator_present": False,
                "calibration_status": "calibrada",
                "visual_confidence": 0.8,
                "machine_motion": 12.0,
                "people_count": 0,
            }
            with patch("app.operations_history.connect", lambda: connect(db_path)):
                recorder = OperationsRecorder("s1", "cam1", evidence_root=Path(temp_dir) / "snapshots")
                recorder.update_status("online", ops, frame)
                recorder.update_status("online", {**ops, "machine_state": "PARADA"}, frame)
            reopened = connect(db_path)
            events = list_operational_events(reopened)
            status = current_status(reopened, "cam1", "Extrusora")
            samples = reopened.execute("SELECT COUNT(*) AS total FROM operational_samples").fetchone()["total"]
            legacy_total = reopened.execute("SELECT COUNT(*) AS total FROM operational_events").fetchone()["total"]

        self.assertGreaterEqual(len(events), 4)
        self.assertEqual(status["machine_state"], "PARADA")
        self.assertGreaterEqual(samples, 2)
        self.assertEqual(legacy_total, 0)

    def test_operations_api_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            connection, db_path = self._db(temp_dir)
            insert_operational_event(connection, "s1", "cam1", "Extrusora", "machine_state", None, "ATIVA", "2026-07-20T08:00:00+00:00")
            close_open_operational_event(connection, "s1", "machine_state", "2026-07-20T09:00:00+00:00")
            connection.close()
            with patch("app.api.connect", lambda: connect(db_path)):
                client = TestClient(api)
                summary = client.get("/operations/summary?start=2026-07-20T08:00:00+00:00&end=2026-07-20T10:00:00+00:00")
                events = client.get("/operations/events?limit=10&offset=0")
                current = client.get("/operations/current-status")

        self.assertEqual(summary.status_code, 200)
        self.assertEqual(events.status_code, 200)
        self.assertEqual(current.status_code, 200)
        self.assertEqual(summary.json()["tempo_maquina_ativa"], 3600.0)
        self.assertEqual(len(events.json()["events"]), 1)

    def test_home_stage_rules_are_encoded_in_frontend(self) -> None:
        script = (ROOT / "frontend" / "operations-dashboard.js").read_text()

        self.assertIn('const stage = !cameras.length ? "empty" : hasHistory ? "active" : "partial"', script)
        self.assertIn('setVisible(homeOnboarding, empty)', script)
        self.assertIn('setVisible(homeNextAction, partial)', script)
        self.assertIn('setVisible(homeSummarySection, active)', script)
        self.assertIn('setVisible(homeLowerGrid, active)', script)
        self.assertIn('function isOperationalHomeEvent(event)', script)
        self.assertIn('type === "camera_status"', script)

    def test_dashboard_does_not_default_to_named_authenticated_user(self) -> None:
        html = (ROOT / "frontend" / "dashboard.html").read_text()

        self.assertNotIn("<strong>Felipe</strong>", html)
        self.assertNotIn("<span>Admin Campex</span>", html)
        self.assertIn("<strong>Campex</strong>", html)
        self.assertIn("<span>Piloto local</span>", html)


if __name__ == "__main__":
    unittest.main()
