from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
from fastapi.testclient import TestClient

from app import alerts
from app.machine_monitoring import MachineMonitorConfig, MachineMonitorEngine
from app.api import api
from app.database import connect, init_db
from app.models import (
    criar_alert_recipient,
    criar_area_monitorada,
    criar_camera,
    criar_cliente,
    criar_ocorrencia_area_restrita,
    criar_unidade,
    listar_alert_deliveries,
)
from app.restricted_area import AreaPoint
from manage import run_send_test_email


class AlertsStage6Test(unittest.TestCase):
    def make_context(self, temp_dir: str):
        db_path = Path(temp_dir) / "alerts.sqlite3"

        def test_connect(_db_path: object = None):
            return connect(db_path)

        connection = connect(db_path)
        init_db(connection)
        cliente_id = criar_cliente(connection, "Cliente")
        unidade_id = criar_unidade(connection, cliente_id, "Unidade")
        camera_id = criar_camera(connection, unidade_id, "Camera", cliente_id=cliente_id)
        area_id = criar_area_monitorada(
            connection,
            camera_id,
            "Restrita",
            [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.1}, {"x": 0.9, "y": 0.9}],
        )
        event_id = criar_ocorrencia_area_restrita(
            connection,
            cliente_id,
            unidade_id,
            camera_id,
            area_id,
            regra_id=None,
            inicio="2026-07-16T10:00:00",
            quantidade_inicial=1,
            quantidade_maxima=1,
            track_ids=[7],
            confianca=0.91,
            midia_path=None,
            severidade="high",
        )
        connection.close()
        return test_connect, camera_id, area_id, event_id

    def wait_for_deliveries(self, test_connect, expected: int = 1):
        for _ in range(30):
            with test_connect() as connection:
                rows = listar_alert_deliveries(connection)
            if len(rows) >= expected and all(row["status"] != "pending" for row in rows):
                return rows
            time.sleep(0.05)
        with test_connect() as connection:
            return listar_alert_deliveries(connection)

    def test_raw_event_does_not_email_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {"CAMPEX_EMAIL_MODE": "console", "CAMPEX_DIRECT_EVENT_EMAILS": "false"}):
            test_connect, camera_id, _area_id, event_id = self.make_context(temp_dir)
            with patch("app.alerts.connect", test_connect), patch("builtins.print"):
                with test_connect() as connection:
                    criar_alert_recipient(connection, "Operacao", "ops@example.com", camera_id=camera_id)
                alerts.enqueue_event_alert(event_id)
                time.sleep(0.05)
            with test_connect() as connection:
                deliveries = listar_alert_deliveries(connection)

        self.assertEqual(deliveries, [])

    def test_new_event_generates_one_alert_per_recipient_and_realtime_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {"CAMPEX_EMAIL_MODE": "console", "CAMPEX_DIRECT_EVENT_EMAILS": "true"}):
            test_connect, camera_id, area_id, event_id = self.make_context(temp_dir)
            with patch("app.alerts.connect", test_connect), patch("builtins.print"):
                with test_connect() as connection:
                    criar_alert_recipient(connection, "Ativo", "ativo@example.com", camera_id=camera_id, area_id=area_id)
                subscriber = alerts.subscribe()
                try:
                    alerts.enqueue_event_alert(event_id)
                    alerts.enqueue_event_alert(event_id)
                    payload = subscriber.get(timeout=1)
                    rows = self.wait_for_deliveries(test_connect)
                finally:
                    alerts.unsubscribe(subscriber)
        self.assertEqual(payload["type"], "incident_opened")
        self.assertEqual(payload["event_id"], event_id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "sent")

    def test_inactive_and_camera_area_filters_do_not_receive(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {"CAMPEX_EMAIL_MODE": "console", "CAMPEX_DIRECT_EVENT_EMAILS": "true"}):
            test_connect, camera_id, area_id, event_id = self.make_context(temp_dir)
            with patch("app.alerts.connect", test_connect), patch("builtins.print"):
                with test_connect() as connection:
                    cliente_id = criar_cliente(connection, "Outro Cliente")
                    unidade_id = criar_unidade(connection, cliente_id, "Outra Unidade")
                    other_camera_id = criar_camera(connection, unidade_id, "Outra Camera", cliente_id=cliente_id)
                    other_area_id = criar_area_monitorada(
                        connection,
                        camera_id,
                        "Outra Area",
                        [{"x": 0.1, "y": 0.1}, {"x": 0.2, "y": 0.1}, {"x": 0.2, "y": 0.2}],
                    )
                    criar_alert_recipient(connection, "Inativo", "inativo@example.com", ativo=False)
                    criar_alert_recipient(connection, "Outra camera", "outra@example.com", camera_id=other_camera_id)
                    criar_alert_recipient(connection, "Outra area", "area@example.com", area_id=other_area_id)
                    criar_alert_recipient(connection, "Geral", "geral@example.com")
                alerts.enqueue_event_alert(event_id)
                rows = self.wait_for_deliveries(test_connect)
        self.assertEqual(len(rows), 1)

    def test_console_mode_does_not_use_smtp(self) -> None:
        with patch.dict(os.environ, {"CAMPEX_EMAIL_MODE": "console", "CAMPEX_DIRECT_EVENT_EMAILS": "true"}), patch("smtplib.SMTP") as smtp, patch("builtins.print") as printer:
            alerts.send_email_alert({"nome": "Pessoa", "email": "pessoa@example.com"}, None, is_test=True)
        smtp.assert_not_called()
        printer.assert_called_once()

    def test_email_configuration_distinguishes_not_configured_failed_and_sent(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            status = alerts.email_configuration_status()
            self.assertEqual(status["status"], "NOT_CONFIGURED")
            self.assertIn("CAMPEX_EMAIL_MODE", status["missing"])
            with self.assertRaisesRegex(RuntimeError, "EMAIL_NOT_CONFIGURED"):
                alerts.send_email_alert({"nome": "Pessoa", "email": "pessoa@example.com"}, None, is_test=True)

        with patch.dict(os.environ, {"CAMPEX_EMAIL_MODE": "invalid"}, clear=True):
            status = alerts.email_configuration_status()
            self.assertEqual(status["status"], "FAILED")

        with patch.dict(os.environ, {"CAMPEX_EMAIL_MODE": "console"}, clear=True), patch("builtins.print"):
            status = alerts.email_configuration_status()
            self.assertEqual(status["status"], "CONFIGURED")
            alerts.send_email_alert({"nome": "Pessoa", "email": "pessoa@example.com"}, None, is_test=True)

    def test_smtp_mode_uses_safe_configuration(self) -> None:
        env = {
            "CAMPEX_EMAIL_MODE": "smtp",
            "CAMPEX_SMTP_HOST": "smtp.example.com",
            "CAMPEX_SMTP_PORT": "2525",
            "CAMPEX_SMTP_USERNAME": "user",
            "CAMPEX_SMTP_PASSWORD": "secret",
            "CAMPEX_EMAIL_FROM": "campex@example.com",
        }
        smtp_instance = MagicMock()
        smtp_instance.__enter__.return_value = smtp_instance
        with patch.dict(os.environ, env), patch("smtplib.SMTP", return_value=smtp_instance) as smtp:
            alerts.send_email_alert({"nome": "Pessoa", "email": "pessoa@example.com"}, None, is_test=True)
        smtp.assert_called_once_with("smtp.example.com", 2525, timeout=15)
        smtp_instance.login.assert_called_once_with("user", "secret")
        sent_message = smtp_instance.send_message.call_args.args[0]
        self.assertNotIn("rtsp://", sent_message.as_string().lower())
        self.assertNotIn("secret@", sent_message.as_string().lower())

    def test_failure_marks_delivery_failed_and_retry_can_succeed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {"CAMPEX_EMAIL_MAX_ATTEMPTS": "1"}):
            test_connect, _camera_id, _area_id, event_id = self.make_context(temp_dir)
            with patch("app.alerts.connect", test_connect):
                with test_connect() as connection:
                    recipient_id = criar_alert_recipient(connection, "Pessoa", "pessoa@example.com")
                    delivery_id = alerts.criar_alert_delivery(connection, recipient_id, evento_id=event_id)
                with patch("app.alerts.send_email_alert", side_effect=RuntimeError("falha segura")):
                    alerts.schedule_delivery(delivery_id)
                    rows = self.wait_for_deliveries(test_connect)
                self.assertEqual(rows[0]["status"], "failed")
                with patch("app.alerts.send_email_alert", return_value=None):
                    alerts.retry_delivery(delivery_id)
                    rows = self.wait_for_deliveries(test_connect)
        self.assertEqual(rows[0]["status"], "sent")

    def test_api_recipients_deliveries_test_alert_and_no_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {"CAMPEX_EMAIL_MODE": "console", "CAMPEX_DIRECT_EVENT_EMAILS": "true"}):
            test_connect, _camera_id, _area_id, _event_id = self.make_context(temp_dir)
            with patch("app.api.connect", test_connect), patch("app.alerts.connect", test_connect), patch("builtins.print"):
                client = TestClient(api)
                created = client.post("/alert-recipients", json={"nome": "Pessoa", "email": "pessoa@example.com"})
                recipient_id = created.json()["id"]
                listed = client.get("/alert-recipients")
                tested = client.post(f"/alert-recipients/{recipient_id}/test")
                deliveries = client.get("/alert-deliveries")
                detail = client.get(f"/alert-deliveries/{tested.json()['delivery_id']}")
        text = created.text + listed.text + tested.text + deliveries.text + detail.text
        self.assertEqual(created.status_code, 200)
        self.assertEqual(tested.status_code, 200)
        self.assertNotIn("rtsp://", text.lower())
        self.assertNotIn("senha", text.lower())

    def test_machine_stoppage_event_automatically_sends_real_email_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {"CAMPEX_EMAIL_MODE": "console", "CAMPEX_DIRECT_EVENT_EMAILS": "true"}):
            test_connect, camera_id, _area_id, _event_id = self.make_context(temp_dir)
            with patch("app.alerts.connect", test_connect), patch("app.machine_monitoring.connect", test_connect), patch("builtins.print") as printer:
                with test_connect() as connection:
                    criar_alert_recipient(
                        connection,
                        "Manutencao",
                        "manutencao@example.com",
                        camera_id=camera_id,
                        cliente_id=connection.execute("SELECT cliente_id FROM cameras WHERE id = ?", (camera_id,)).fetchone()["cliente_id"],
                        event_types=["machine_stoppage"],
                    )
                config = MachineMonitorConfig(
                    id="mach_test",
                    client_id="",
                    unit_id="",
                    camera_id=camera_id,
                    nome="Extrusora",
                    machine_polygon=[AreaPoint(0.1, 0.1), AreaPoint(0.9, 0.1), AreaPoint(0.9, 0.9)],
                    operator_polygon=[AreaPoint(0.0, 0.1), AreaPoint(0.05, 0.1), AreaPoint(0.05, 0.9)],
                    stop_seconds=0.1,
                    recovery_seconds=0.1,
                )
                with test_connect() as connection:
                    camera = connection.execute("SELECT cliente_id, unidade_id FROM cameras WHERE id = ?", (camera_id,)).fetchone()
                config.client_id = camera["cliente_id"]
                config.unit_id = camera["unidade_id"]
                engine = MachineMonitorEngine(config)
                frame = np.zeros((80, 120, 3), dtype=np.uint8)
                with patch("app.machine_monitoring.save_machine_evidence", return_value=(None, None)):
                    engine._open_event(time.monotonic(), frame)
                    engine._open_event(time.monotonic(), frame)
                rows = self.wait_for_deliveries(test_connect)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "sent")
        self.assertEqual(rows[0]["destinatario"], "manutencao@example.com")
        printer.assert_called()

    def test_event_type_filter_prevents_unrelated_real_email(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {"CAMPEX_EMAIL_MODE": "console", "CAMPEX_DIRECT_EVENT_EMAILS": "true"}):
            test_connect, camera_id, _area_id, _event_id = self.make_context(temp_dir)
            with patch("app.alerts.connect", test_connect), patch("app.machine_monitoring.connect", test_connect):
                with test_connect() as connection:
                    camera = connection.execute("SELECT cliente_id, unidade_id FROM cameras WHERE id = ?", (camera_id,)).fetchone()
                    criar_alert_recipient(
                        connection,
                        "Area",
                        "area@example.com",
                        camera_id=camera_id,
                        cliente_id=camera["cliente_id"],
                        event_types=["restricted_area_occupied"],
                    )
                config = MachineMonitorConfig(
                    id="mach_filter",
                    client_id=camera["cliente_id"],
                    unit_id=camera["unidade_id"],
                    camera_id=camera_id,
                    nome="Extrusora",
                    machine_polygon=[AreaPoint(0.1, 0.1), AreaPoint(0.9, 0.1), AreaPoint(0.9, 0.9)],
                    operator_polygon=[AreaPoint(0.0, 0.1), AreaPoint(0.05, 0.1), AreaPoint(0.05, 0.9)],
                )
                engine = MachineMonitorEngine(config)
                with patch("app.machine_monitoring.save_machine_evidence", return_value=(None, None)):
                    engine._open_event(time.monotonic(), np.zeros((80, 120, 3), dtype=np.uint8))
                time.sleep(0.1)
                with test_connect() as connection:
                    rows = listar_alert_deliveries(connection)
        self.assertEqual(rows, [])

    def test_manage_send_test_email_uses_alert_pipeline_without_operational_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {"CAMPEX_EMAIL_MODE": "console", "CAMPEX_DIRECT_EVENT_EMAILS": "true"}):
            db_path = Path(temp_dir) / "email.sqlite3"
            with patch("builtins.print"):
                exit_code = run_send_test_email(db_path, "destino@example.com", "Destino", timeout=2.0)
            with connect(db_path) as connection:
                deliveries = connection.execute("SELECT * FROM alert_deliveries").fetchall()
                events = connection.execute("SELECT COUNT(*) AS total FROM eventos").fetchone()["total"]
                recipients = connection.execute("SELECT * FROM alert_recipients WHERE email = ?", ("destino@example.com",)).fetchall()

        self.assertEqual(exit_code, 0)
        self.assertEqual(events, 0)
        self.assertEqual(len(recipients), 1)
        self.assertEqual(len(deliveries), 1)
        self.assertIsNone(deliveries[0]["evento_id"])
        self.assertEqual(deliveries[0]["status"], "sent")
        self.assertEqual(deliveries[0]["is_test"], 1)

    def test_smtp_error_scrubs_configured_credentials(self) -> None:
        with patch.dict(os.environ, {"CAMPEX_SMTP_USERNAME": "user@example.com", "CAMPEX_SMTP_PASSWORD": "super-secret"}):
            message = alerts.safe_error(RuntimeError("falha user@example.com super-secret"))
        self.assertNotIn("user@example.com", message)
        self.assertNotIn("super-secret", message)


if __name__ == "__main__":
    unittest.main()
