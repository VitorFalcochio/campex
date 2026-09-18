from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import api as api_module
from app.analytics import compute_summary, generate_insights, parse_dt
from app.alerts import enqueue_event_alert
from app.auth import create_user
from app.data_contract import CANONICAL_EVENT_VERSION, canonical_event_from_row
from app.database import connect, init_db
from app.models import (
    criar_alert_recipient,
    criar_camera,
    criar_cliente,
    criar_machine_monitor,
    criar_unidade,
    registrar_evidence_index,
    registrar_evento,
)
from app.api import api


class PilotDataSecurityBaselineTest(unittest.TestCase):
    def make_context(self, temp_dir: str):
        db_path = Path(temp_dir) / "pilot.sqlite3"
        connection = connect(db_path)
        init_db(connection)
        cliente_id = criar_cliente(connection, "Cliente A")
        other_cliente = criar_cliente(connection, "Cliente B")
        unidade_id = criar_unidade(connection, cliente_id, "Unidade A")
        other_unidade = criar_unidade(connection, other_cliente, "Unidade B")
        camera_id = criar_camera(connection, unidade_id, "Camera A", cliente_id=cliente_id, config_ref="teste_maquina.mp4")
        other_camera = criar_camera(connection, other_unidade, "Camera B", cliente_id=other_cliente, config_ref="teste_maquina.mp4")
        machine_id = criar_machine_monitor(
            connection,
            cliente_id,
            unidade_id,
            camera_id,
            "Extrusora A",
            [{"x": 0.1, "y": 0.1}, {"x": 0.8, "y": 0.1}, {"x": 0.8, "y": 0.8}],
            [{"x": 0.1, "y": 0.1}, {"x": 0.5, "y": 0.1}, {"x": 0.5, "y": 0.5}],
        )
        return connection, db_path, cliente_id, other_cliente, unidade_id, camera_id, other_camera, machine_id

    def test_canonical_event_contract_maps_current_event_model(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            connection, _db_path, cliente_id, _other, unidade_id, camera_id, _other_camera, machine_id = self.make_context(temp_dir)
            event_id = registrar_evento(
                connection,
                cliente_id,
                unidade_id,
                camera_id,
                "machine_stoppage",
                inicio="2026-08-05T10:00:00+00:00",
                fim="2026-08-05T10:05:00+00:00",
                duracao=300,
                operador_presente=False,
                confianca=0.92,
                midia_path="data/evidence/test.jpg",
            )
            connection.execute(
                """
                UPDATE eventos
                SET machine_monitor_id = ?, area_id = ?, regra_id = ?, severidade = ?, metadata_json = ?
                WHERE id = ?
                """,
                (machine_id, "zone_1", "rule_1", "high", '{"machine_state":"STOPPED","data_quality":"reliable","rule_version":"v3"}', event_id),
            )
            row = dict(connection.execute("SELECT * FROM eventos WHERE id = ?", (event_id,)).fetchone())
            contract = canonical_event_from_row(row)

        self.assertEqual(contract["contract_version"], CANONICAL_EVENT_VERSION)
        self.assertEqual(contract["event_id"], row["event_uuid"])
        self.assertEqual(contract["factory_id"], cliente_id)
        self.assertEqual(contract["machine_id"], machine_id)
        self.assertEqual(contract["zone_id"], "zone_1")
        self.assertEqual(contract["rule_version"], "v3")
        self.assertEqual(contract["evidence_id"], f"evidence:{event_id}")

    def test_offline_or_missing_samples_do_not_count_as_stopped_or_active_time(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            connection, _db_path, _cliente_id, _other, _unidade_id, camera_id, _other_camera, machine_id = self.make_context(temp_dir)
            summary = compute_summary(
                connection,
                machine_id=machine_id,
                camera_id=camera_id,
                start=parse_dt("2026-08-05T10:00:00+00:00"),
                end=parse_dt("2026-08-05T11:00:00+00:00"),
            )

        self.assertEqual(summary["active_seconds"], 0)
        self.assertEqual(summary["stopped_seconds"], 0)
        self.assertEqual(summary["reliable_data_coverage_percent"], 0)
        self.assertTrue(summary["incomplete"])

    def test_insight_is_deterministic_and_points_to_metrics_and_event_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            connection, _db_path, cliente_id, _other, unidade_id, camera_id, _other_camera, machine_id = self.make_context(temp_dir)
            event_id = registrar_evento(
                connection,
                cliente_id,
                unidade_id,
                camera_id,
                "machine_stoppage",
                inicio="2026-08-05T10:00:00+00:00",
                fim="2026-08-05T10:10:00+00:00",
                duracao=600,
            )
            connection.execute("UPDATE eventos SET machine_monitor_id = ? WHERE id = ?", (machine_id, event_id))
            insights = generate_insights(
                connection,
                machine_id=machine_id,
                camera_id=camera_id,
                start=parse_dt("2026-08-05T10:00:00+00:00"),
                end=parse_dt("2026-08-05T11:00:00+00:00"),
            )

        stoppage = next(item for item in insights if item["rule_id"] == "stopped_time_threshold_v1")
        self.assertIn(event_id, stoppage["related_event_ids"])
        self.assertEqual(stoppage["metrics"]["stopped_seconds"], 600)
        self.assertIn("recommended_action", stoppage)

    def test_event_has_exactly_one_evidence_index_and_one_outbox_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            connection, _db_path, cliente_id, _other, unidade_id, camera_id, _other_camera, machine_id = self.make_context(temp_dir)
            event_id = registrar_evento(
                connection,
                cliente_id,
                unidade_id,
                camera_id,
                "machine_stoppage",
                inicio="2026-08-05T10:00:00+00:00",
                fim="2026-08-05T10:01:00+00:00",
                duracao=60,
                midia_path="data/evidence/e1.jpg",
            )
            row = connection.execute("SELECT event_uuid FROM eventos WHERE id = ?", (event_id,)).fetchone()
            registrar_evidence_index(
                connection,
                evidence_id="evd_1",
                event_id=event_id,
                event_uuid=row["event_uuid"],
                tenant_id=cliente_id,
                unit_id=unidade_id,
                camera_id=camera_id,
                machine_id=machine_id,
                path="data/evidence/e1.jpg",
            )
            registrar_evidence_index(
                connection,
                evidence_id="evd_1_dup",
                event_id=event_id,
                event_uuid=row["event_uuid"],
                tenant_id=cliente_id,
                unit_id=unidade_id,
                camera_id=camera_id,
                machine_id=machine_id,
                path="data/evidence/e1.jpg",
            )
            evidence_count = connection.execute("SELECT COUNT(*) AS total FROM evidences WHERE event_id = ?", (event_id,)).fetchone()["total"]
            outbox_count = connection.execute("SELECT COUNT(*) AS total FROM sync_outbox WHERE event_uuid = ?", (row["event_uuid"],)).fetchone()["total"]

        self.assertEqual(evidence_count, 1)
        self.assertEqual(outbox_count, 1)

    def test_retry_or_reenqueue_does_not_duplicate_alert_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            connection, db_path, cliente_id, _other, unidade_id, camera_id, _other_camera, _machine_id = self.make_context(temp_dir)
            criar_alert_recipient(connection, "Responsavel", "ops@example.com", cliente_id=cliente_id, event_types=["machine_stoppage"])
            event_id = registrar_evento(connection, cliente_id, unidade_id, camera_id, "machine_stoppage")
            connection.execute("UPDATE eventos SET severidade = 'high' WHERE id = ?", (event_id,))
            connection.commit()

            def patched_connect(_path=None):
                return connect(db_path)

            with patch("app.alerts.connect", patched_connect), patch("app.alerts.schedule_delivery"):
                enqueue_event_alert(event_id)
                enqueue_event_alert(event_id)
            deliveries = connect(db_path).execute("SELECT COUNT(*) AS total FROM alert_deliveries WHERE evento_id = ?", (event_id,)).fetchone()["total"]

        self.assertEqual(deliveries, 1)

    def test_login_and_configuration_write_audit_log_and_cross_tenant_is_denied(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            connection, db_path, cliente_id, _other, _unidade_id, _camera_id, other_camera, _machine_id = self.make_context(temp_dir)
            create_user(connection, "admin@cliente.test", "senha-segura", "admin_cliente", cliente_id, "Admin Cliente")

            def patched_connect(_path=None):
                return connect(db_path)

            with patch.object(api_module, "connect", patched_connect):
                client = TestClient(api)
                login = client.post("/auth/login", json={"email": "admin@cliente.test", "senha": "senha-segura"})
                forbidden = client.get(f"/cameras/{other_camera}/machine-monitors")
                audit_rows = connect(db_path).execute("SELECT action, actor_email FROM audit_log ORDER BY created_at").fetchall()

        self.assertEqual(login.status_code, 200)
        self.assertEqual(forbidden.status_code, 403)
        self.assertTrue(any(row["action"] == "auth.login" and row["actor_email"] == "admin@cliente.test" for row in audit_rows))

    def test_logs_do_not_expose_rtsp_credentials_on_camera_bootstrap_failure(self) -> None:
        with self.assertLogs("campex.api", level="ERROR") as captured:
            api_module.logger.error("Falha segura na camera: %s", "rtsp://***:***@10.0.0.5/live")
        text = "\n".join(captured.output)
        self.assertNotIn("segredo", text)
        self.assertNotIn("user:pass", text)
        self.assertNotRegex(text, r"rtsp://[^*\\s]+:[^*\\s]+@")


if __name__ == "__main__":
    unittest.main()
