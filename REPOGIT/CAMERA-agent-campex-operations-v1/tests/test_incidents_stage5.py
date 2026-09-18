from __future__ import annotations

import tempfile
import time
import unittest
import shutil
from pathlib import Path
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient

from app.api import api
from app.config import ROOT
from app.database import connect, init_db
from app.incidents import IncidentManager
from app.models import (
    criar_area_monitorada,
    criar_camera,
    criar_cliente,
    criar_unidade,
    listar_eventos_filtrados,
    obter_evento,
)
from app.person_detection import Detection
from app.restricted_area import AreaPresence, area_from_dict


class IncidentStage5Test(unittest.TestCase):
    def setUp(self) -> None:
        self.evidence_root = ROOT / "data" / "evidence" / "test_stage5"
        shutil.rmtree(self.evidence_root, ignore_errors=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.evidence_root, ignore_errors=True)

    def make_context(self, temp_dir: str):
        db_path = Path(temp_dir) / "incidents.sqlite3"

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
        area = area_from_dict({"id": area_id, "camera_id": camera_id, "nome": "Restrita", "pontos": [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.1}, {"x": 0.9, "y": 0.9}], "ativa": True})
        connection.close()
        return db_path, test_connect, camera_id, area

    def test_fast_occupancy_does_not_create_incident(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _db_path, test_connect, camera_id, area = self.make_context(temp_dir)
            manager = IncidentManager(camera_id, entry_delay_seconds=10, evidence_root=Path(temp_dir) / "evidence")
            frame = np.zeros((100, 100, 3), dtype=np.uint8)
            presence = AreaPresence(area.id, area.nome, "ocupada", 1, [1])
            with patch("app.incidents.connect", test_connect):
                manager.update(area, presence, [Detection(10, 10, 20, 20, 0.9, track_id=1)], frame)
                with test_connect() as connection:
                    events = listar_eventos_filtrados(connection, tipo="restricted_area_occupied")
        self.assertEqual(events, [])

    def test_confirmed_occupancy_creates_single_incident_and_updates_people(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _db_path, test_connect, camera_id, area = self.make_context(temp_dir)
            manager = IncidentManager(camera_id, entry_delay_seconds=0, exit_grace_seconds=10, evidence_root=self.evidence_root)
            frame = np.zeros((100, 100, 3), dtype=np.uint8)
            one = AreaPresence(area.id, area.nome, "ocupada", 1, [1])
            two = AreaPresence(area.id, area.nome, "ocupada", 2, [1, 2])
            with patch("app.incidents.connect", test_connect):
                manager.update(area, one, [Detection(10, 10, 20, 20, 0.7, track_id=1)], frame)
                manager.update(area, two, [Detection(10, 10, 20, 20, 0.7, track_id=1), Detection(30, 10, 40, 20, 0.95, track_id=2)], frame)
                with test_connect() as connection:
                    events = listar_eventos_filtrados(connection, tipo="restricted_area_occupied")
                    outbox = connection.execute("SELECT * FROM sync_outbox WHERE event_uuid = ?", (events[0]["event_uuid"],)).fetchone()
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0]["event_uuid"])
        self.assertEqual(events[0]["quantidade_maxima"], 2)
        self.assertEqual(set(events[0]["track_ids"]), {1, 2})
        self.assertEqual(events[0]["status"], "open")
        self.assertTrue(events[0]["midia_path"])
        self.assertIsNotNone(outbox)
        self.assertIn('"tipo": "restricted_area_occupied"', outbox["payload_json"])
        self.assertNotIn("rtsp://", str(events))

    def test_brief_exit_does_not_close_but_grace_exit_closes_and_cooldown_prevents_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _db_path, test_connect, camera_id, area = self.make_context(temp_dir)
            manager = IncidentManager(camera_id, entry_delay_seconds=0, exit_grace_seconds=0.2, cooldown_seconds=10, evidence_root=self.evidence_root)
            frame = np.zeros((100, 100, 3), dtype=np.uint8)
            occupied = AreaPresence(area.id, area.nome, "ocupada", 1, [1])
            free = AreaPresence(area.id, area.nome, "livre", 0, [])
            with patch("app.incidents.connect", test_connect):
                manager.update(area, occupied, [Detection(10, 10, 20, 20, 0.9, track_id=1)], frame)
                manager.update(area, free, [], frame)
                manager.update(area, occupied, [Detection(10, 10, 20, 20, 0.9, track_id=1)], frame)
                time.sleep(0.25)
                manager.update(area, free, [], frame)
                manager.update(area, occupied, [Detection(10, 10, 20, 20, 0.9, track_id=1)], frame)
                with test_connect() as connection:
                    events = listar_eventos_filtrados(connection, tipo="restricted_area_occupied")
                    outbox = connection.execute("SELECT * FROM sync_outbox WHERE event_uuid = ?", (events[0]["event_uuid"],)).fetchone()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["status"], "closed")
        self.assertIsNotNone(events[0]["fim"])
        self.assertIn('"status": "closed"', outbox["payload_json"])
        self.assertIn('"duracao":', outbox["payload_json"])

    def test_evidence_failure_does_not_prevent_incident(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            blocker = Path(temp_dir) / "not_a_dir"
            blocker.write_text("x")
            _db_path, test_connect, camera_id, area = self.make_context(temp_dir)
            manager = IncidentManager(camera_id, entry_delay_seconds=0, evidence_root=blocker)
            frame = np.zeros((100, 100, 3), dtype=np.uint8)
            with patch("app.incidents.connect", test_connect):
                manager.update(area, AreaPresence(area.id, area.nome, "ocupada", 1, [1]), [Detection(10, 10, 20, 20, 0.9, track_id=1)], frame)
                with test_connect() as connection:
                    events = listar_eventos_filtrados(connection, tipo="restricted_area_occupied")
        self.assertEqual(len(events), 1)
        self.assertIsNone(events[0]["midia_path"])
        self.assertTrue(events[0]["evidence_error"])

    def test_acknowledge_filters_and_evidence_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path, test_connect, camera_id, area = self.make_context(temp_dir)
            manager = IncidentManager(camera_id, entry_delay_seconds=0, evidence_root=self.evidence_root)
            frame = np.zeros((100, 100, 3), dtype=np.uint8)
            with patch("app.incidents.connect", test_connect):
                manager.update(area, AreaPresence(area.id, area.nome, "ocupada", 1, [1]), [Detection(10, 10, 20, 20, 0.9, track_id=1)], frame)
            with patch("app.api.connect", test_connect):
                client = TestClient(api)
                listed = client.get(f"/eventos?camera_id={camera_id}&area_id={area.id}&status=open&tipo=restricted_area_occupied")
                event_id = listed.json()[0]["id"]
                detail = client.get(f"/eventos/{event_id}")
                ack = client.patch(f"/eventos/{event_id}", json={"status": "acknowledged", "observacao": "ok", "acknowledged_by": "tester"})
                evidence = client.get(f"/eventos/{event_id}/evidence")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()), 1)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(ack.json()["status"], "open")
        self.assertEqual(ack.json()["workflow_status"], "acknowledged")
        self.assertEqual(evidence.status_code, 200)
        self.assertNotIn("secret", listed.text + detail.text + ack.text)


if __name__ == "__main__":
    unittest.main()
