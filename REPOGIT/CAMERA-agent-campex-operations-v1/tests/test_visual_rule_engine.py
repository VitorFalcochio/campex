import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import app.alerts as alerts_module
import app.api as api_module
from app.database import connect, init_db
from app.models import criar_alert_recipient, criar_camera, criar_cliente, criar_regra, criar_unidade, listar_alert_deliveries
from app.operational_rule_runtime import OperationalRuleRuntime, facts_from_stream
from app.person_detection import Detection
from app.visual_rule_engine import evaluate_condition


class VisualRuleEngineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "campex.sqlite"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def connection(self) -> sqlite3.Connection:
        return connect(self.db_path)

    def seed_camera(self) -> tuple[str, str, str]:
        with self.connection() as connection:
            init_db(connection)
            cliente_id = criar_cliente(connection, "FL Plásticos")
            unidade_id = criar_unidade(connection, cliente_id, "Unidade principal")
            camera_id = criar_camera(connection, unidade_id, "Câmera 01", cliente_id=cliente_id, source_type="rtsp")
            criar_alert_recipient(
                connection,
                "Supervisor",
                "supervisor@example.com",
                cliente_id=cliente_id,
                event_types=[],
            )
        return cliente_id, unidade_id, camera_id

    def test_primitives_evaluate_composed_machine_without_operator(self) -> None:
        condition = {
            "type": "all",
            "conditions": [
                {"type": "machine_state", "state": "ATIVA"},
                {"type": "absence_in_zone", "zone_id": "operator", "max_count": 0},
            ],
        }
        matched, detail = evaluate_condition(condition, {"machine_state": "ATIVA", "zone_counts": {"operator": 0}})
        self.assertTrue(matched)
        self.assertEqual(len(detail["children"]), 2)

    def test_rule_simulation_opens_one_event_closes_and_avoids_duplicates(self) -> None:
        _cliente_id, _unidade_id, camera_id = self.seed_camera()
        client = TestClient(api_module.api)
        with patch("app.api.connect", self.connection), patch("app.alerts.connect", self.connection), patch("builtins.print"):
            created = client.post(
                "/visual-rules",
                json={
                    "nome": "Máquina ativa sem operador",
                    "camera_id": camera_id,
                    "tipo_evento": "active_without_operator",
                    "tempo_minimo": 2,
                    "cooldown_seconds": 30,
                    "debounce_seconds": 0,
                    "hysteresis_seconds": 0,
                    "condicao": {
                        "type": "all",
                        "conditions": [
                            {"type": "machine_state", "state": "ATIVA"},
                            {"type": "absence_in_zone", "zone_id": "operator", "max_count": 0},
                        ],
                    },
                },
            )
            self.assertEqual(created.status_code, 200, created.text)
            rule_id = created.json()["id"]
            first = client.post(
                f"/visual-rules/{rule_id}/simulate",
                json={"facts": {"machine_state": "ATIVA", "zone_counts": {"operator": 0}}, "at": "2026-07-24T10:00:00+00:00"},
            )
            self.assertEqual(first.json()["action"], "unchanged")
            opened = client.post(
                f"/visual-rules/{rule_id}/simulate",
                json={"facts": {"machine_state": "ATIVA", "zone_counts": {"operator": 0}}, "at": "2026-07-24T10:00:03+00:00"},
            )
            self.assertEqual(opened.json()["action"], "opened")
            event_id = opened.json()["event_id"]
            duplicate = client.post(
                f"/visual-rules/{rule_id}/simulate",
                json={"facts": {"machine_state": "ATIVA", "zone_counts": {"operator": 0}}, "at": "2026-07-24T10:00:04+00:00"},
            )
            self.assertEqual(duplicate.json()["event_id"], event_id)
            self.assertEqual(duplicate.json()["action"], "unchanged")
            closed = client.post(
                f"/visual-rules/{rule_id}/simulate",
                json={"facts": {"machine_state": "ATIVA", "zone_counts": {"operator": 1}}, "at": "2026-07-24T10:01:03+00:00"},
            )
            self.assertEqual(closed.json()["action"], "closed")

            with self.connection() as connection:
                init_db(connection)
                events = connection.execute("SELECT * FROM eventos WHERE regra_id = ?", (rule_id,)).fetchall()
                outbox = connection.execute("SELECT * FROM sync_outbox WHERE event_uuid = ?", (events[0]["event_uuid"],)).fetchone()
                deliveries = listar_alert_deliveries(connection)
            self.assertEqual(len(events), 1)
            self.assertTrue(events[0]["event_uuid"])
            self.assertEqual(events[0]["status"], "closed")
            self.assertEqual(events[0]["duracao"], 60)
            self.assertIsNotNone(outbox)
            self.assertEqual(outbox["status"], "pending")
            self.assertIn('"status": "closed"', outbox["payload_json"])
            self.assertIn('"duracao": 60', outbox["payload_json"])
            self.assertIn('"severidade": "medium"', outbox["payload_json"])
            self.assertEqual(len(deliveries), 1)

    def test_normalization_alert_registers_second_delivery_without_duplicate_start(self) -> None:
        _cliente_id, _unidade_id, camera_id = self.seed_camera()
        client = TestClient(api_module.api)
        with patch("app.api.connect", self.connection), patch("app.alerts.connect", self.connection), patch("builtins.print"):
            created = client.post(
                "/visual-rules",
                json={
                    "nome": "Câmera offline",
                    "camera_id": camera_id,
                    "tipo_evento": "camera_offline",
                    "tempo_minimo": 0,
                    "cooldown_seconds": 0,
                    "debounce_seconds": 0,
                    "hysteresis_seconds": 0,
                    "alerta_normalizacao": True,
                    "condicao": {"type": "camera_status", "status": "offline"},
                },
            )
            rule_id = created.json()["id"]
            client.post(f"/visual-rules/{rule_id}/simulate", json={"facts": {"camera_status": "offline"}, "at": "2026-07-24T11:00:00+00:00"})
            client.post(f"/visual-rules/{rule_id}/simulate", json={"facts": {"camera_status": "offline"}, "at": "2026-07-24T11:00:01+00:00"})
            client.post(f"/visual-rules/{rule_id}/simulate", json={"facts": {"camera_status": "online"}, "at": "2026-07-24T11:01:00+00:00"})
            with self.connection() as connection:
                init_db(connection)
                deliveries = listar_alert_deliveries(connection)
            self.assertEqual(len(deliveries), 2)
            self.assertEqual({delivery["canal"] for delivery in deliveries}, {"email", "email_normalizacao"})

    def test_camera_offline_rule_uses_camera_status_primitive(self) -> None:
        _cliente_id, _unidade_id, camera_id = self.seed_camera()
        client = TestClient(api_module.api)
        with patch("app.api.connect", self.connection), patch("app.alerts.connect", self.connection), patch("builtins.print"):
            created = client.post(
                "/visual-rules",
                json={
                    "nome": "Câmera offline",
                    "camera_id": camera_id,
                    "tipo_evento": "camera_offline",
                    "tempo_minimo": 0,
                    "cooldown_seconds": 0,
                    "debounce_seconds": 0,
                    "condicao": {"type": "camera_status", "status": "offline"},
                },
            )
            result = client.post(
                f"/visual-rules/{created.json()['id']}/simulate",
                json={"facts": {"camera_status": "offline"}, "at": "2026-07-24T11:00:00+00:00"},
            )
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()["action"], "opened")

    def test_runtime_camera_status_does_not_create_operational_event(self) -> None:
        _cliente_id, _unidade_id, camera_id = self.seed_camera()
        with self.connection() as connection:
            init_db(connection)
            rule = criar_regra(
                connection,
                nome="Câmera offline técnica",
                camera_id=camera_id,
                tipo_evento="camera_offline",
                tempo_minimo=0,
                cooldown_seconds=0,
                debounce_seconds=0,
                condicao={"type": "camera_status", "status": "offline"},
            )
        runtime = OperationalRuleRuntime(camera_id)
        with patch("app.operational_rule_runtime.connect", self.connection):
            results = runtime.camera_status("offline")
        with self.connection() as connection:
            init_db(connection)
            total = connection.execute("SELECT COUNT(*) AS total FROM eventos WHERE tipo IN ('camera_status', 'camera_offline')").fetchone()["total"]

        self.assertTrue(rule)
        self.assertEqual(results, [])
        self.assertEqual(total, 0)

    def test_default_rules_endpoint_creates_pilot_rules_once(self) -> None:
        _cliente_id, _unidade_id, camera_id = self.seed_camera()
        client = TestClient(api_module.api)
        with patch("app.api.connect", self.connection):
            first = client.post(f"/cameras/{camera_id}/visual-rules/defaults", json={"zone_id": "area_1"})
            second = client.post(f"/cameras/{camera_id}/visual-rules/defaults", json={"zone_id": "area_1"})
        self.assertEqual(first.status_code, 200, first.text)
        self.assertGreaterEqual(first.json()["total"], 6)
        self.assertEqual(second.json()["total"], 0)

    def test_runtime_builds_facts_for_people_zone_machine_and_vehicle(self) -> None:
        facts = facts_from_stream(
            "cam1",
            "online",
            detections=[
                Detection(0, 0, 10, 10, 0.9, class_name="person", track_id=1),
                Detection(20, 0, 40, 20, 0.8, class_name="truck", track_id=2),
            ],
            machine_state="ATIVA",
            machine_motion=0.2,
            operator_present=False,
            operator_people_count=0,
            fps=30,
        )
        self.assertEqual(facts["people_count"], 1)
        self.assertEqual(facts["vehicle_count"], 1)
        matched, _detail = evaluate_condition({"type": "vehicle_stopped", "min_count": 1, "max_motion": 1}, facts)
        self.assertTrue(matched)

    def test_runtime_evaluates_active_rules_without_camera(self) -> None:
        _cliente_id, _unidade_id, camera_id = self.seed_camera()
        client = TestClient(api_module.api)
        with patch("app.api.connect", self.connection), patch("app.alerts.connect", self.connection), patch("app.operational_rule_runtime.connect", self.connection), patch("builtins.print"):
            created = client.post(
                "/visual-rules",
                json={
                    "nome": "Pessoa em área restrita",
                    "camera_id": camera_id,
                    "tipo_evento": "restricted_area_occupied",
                    "tempo_minimo": 0,
                    "cooldown_seconds": 0,
                    "debounce_seconds": 0,
                    "condicao": {"type": "presence_in_zone", "zone_id": "restricted_area", "min_count": 1},
                },
            )
            self.assertEqual(created.status_code, 200)
            runtime = OperationalRuleRuntime(camera_id, evaluation_interval_seconds=0)
            results = runtime.evaluate({"camera_status": "online", "people_count": 1, "zone_counts": {"restricted_area": 1}}, force=True)
            self.assertEqual(results[0]["action"], "opened")


if __name__ == "__main__":
    unittest.main()
