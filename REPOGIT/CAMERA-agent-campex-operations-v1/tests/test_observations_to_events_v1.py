from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from app.database import connect, init_db
from app.machine_monitoring import MachineMonitorConfig, MachineMonitorEngine
from app.models import (
    criar_alert_recipient,
    criar_area_monitorada,
    criar_camera,
    criar_cliente,
    criar_machine_monitor,
    criar_unidade,
    listar_alert_deliveries,
    listar_areas_camera,
    listar_eventos_filtrados,
    registrar_operational_sample,
)
from app.people_zones import PeopleZonesEngine
from app.person_detection import Detection
from app.restricted_area import AreaPoint
from shared.schemas import now_iso


class ObservationsToEventsV1Test(unittest.TestCase):
    def _context(self, temp_dir: str):
        db_path = Path(temp_dir) / "observations-events.sqlite3"

        def test_connect():
            return connect(db_path)

        with test_connect() as connection:
            init_db(connection)
            cliente_id = criar_cliente(connection, "Tenant Etapa 6")
            unidade_id = criar_unidade(connection, cliente_id, "Unidade Etapa 6")
            camera_id = criar_camera(connection, unidade_id, "Camera Etapa 6", cliente_id=cliente_id)
            monitor_id = criar_machine_monitor(
                connection,
                cliente_id,
                unidade_id,
                camera_id,
                "A6",
                [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.1}, {"x": 0.9, "y": 0.9}],
                [{"x": 0.0, "y": 0.1}, {"x": 0.2, "y": 0.1}, {"x": 0.2, "y": 0.9}],
                stop_seconds=0.2,
                recovery_seconds=0.2,
                operator_absence_seconds=0.2,
                stopped_with_operator_seconds=0.2,
                microstop_limit=999,
            )
        return test_connect, cliente_id, unidade_id, camera_id, monitor_id

    def _engine(self, cliente_id: str, unidade_id: str, camera_id: str, monitor_id: str) -> MachineMonitorEngine:
        config = MachineMonitorConfig(
            id=monitor_id,
            client_id=cliente_id,
            unit_id=unidade_id,
            camera_id=camera_id,
            nome="A6",
            machine_polygon=[AreaPoint(0.1, 0.1), AreaPoint(0.9, 0.1), AreaPoint(0.9, 0.9)],
            operator_polygon=[AreaPoint(0.0, 0.1), AreaPoint(0.2, 0.1), AreaPoint(0.2, 0.9)],
            stop_seconds=0.2,
            recovery_seconds=0.2,
            operator_absence_seconds=0.2,
            stopped_with_operator_seconds=0.2,
            microstop_limit=999,
            active_baseline=30.0,
            stopped_baseline=2.0,
            active_noise=0.2,
            stopped_noise=0.2,
        )
        return MachineMonitorEngine(config)

    def _wait_for_deliveries(self, test_connect, expected: int = 1) -> list[dict]:
        for _ in range(30):
            with test_connect() as connection:
                rows = listar_alert_deliveries(connection)
            if len(rows) >= expected and all(row["status"] != "pending" for row in rows):
                return rows
            time.sleep(0.05)
        with test_connect() as connection:
            return listar_alert_deliveries(connection)

    def _add_active_operational_context(self, connection, camera_id: str) -> None:
        registrar_operational_sample(
            connection,
            sample_uuid=f"sample-{time.monotonic_ns()}",
            tenant_id="tenant",
            unit_id="unit",
            camera_id=camera_id,
            machine_id=None,
            machine_state="ACTIVE",
            operator_present=None,
            activity_score=42.0,
            confidence=0.9,
            capture_fps=15.0,
            inference_fps=5.0,
            frames_analyzed=10,
            camera_online=True,
            sample_at=now_iso(),
            metadata={
                "canonical_observations": [
                    {
                        "observation_type": "machine_activity",
                        "camera_id": camera_id,
                        "value": "ACTIVE",
                        "confidence": 0.9,
                        "data_quality": "observed",
                    },
                    {
                        "observation_type": "person_presence",
                        "camera_id": camera_id,
                        "value": "UNKNOWN",
                        "confidence": 0.0,
                        "data_quality": "insufficient_data",
                    },
                ]
            },
        )

    def test_machine_stoppage_vertical_chain_from_temporal_observation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict("os.environ", {"CAMPEX_EMAIL_MODE": "console", "CAMPEX_ZONE_EVENT_SECONDS": "0"}):
            test_connect, cliente_id, unidade_id, camera_id, monitor_id = self._context(temp_dir)
            engine = self._engine(cliente_id, unidade_id, camera_id, monitor_id)
            frame = np.zeros((80, 120, 3), dtype=np.uint8)
            with patch("app.machine_monitoring.connect", test_connect), patch("app.alerts.connect", test_connect), patch("app.machine_monitoring.save_machine_evidence", return_value=("data/evidence/a6-stop.jpg", None)), patch("builtins.print"):
                with test_connect() as connection:
                    criar_alert_recipient(connection, "Operacao", "ops@example.com", cliente_id=cliente_id, camera_id=camera_id, event_types=["machine_stoppage"])
                engine.state.state = "ACTIVE"
                engine._evaluate_official_events(100.0, frame)
                engine.state.state = "STOPPED"
                engine.state.state_since = 101.0
                engine.state.confidence = 0.92
                engine.state.analysis_status = "ANALYZING"
                engine._evaluate_official_events(101.0, frame)
                engine._evaluate_official_events(101.5, frame)
                engine._evaluate_official_events(102.0, frame)
                engine.state.state = "ACTIVE"
                engine._evaluate_official_events(104.0, frame)
                deliveries = self._wait_for_deliveries(test_connect)
            with test_connect() as connection:
                events = listar_eventos_filtrados(connection, tipo="machine_stoppage")
                outbox_rows = connection.execute("SELECT * FROM sync_outbox WHERE event_uuid = ?", (events[0]["event_uuid"],)).fetchall()
                evidence_rows = connection.execute("SELECT * FROM evidences WHERE event_id = ?", (events[0]["id"],)).fetchall()

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["status"], "closed")
        self.assertGreaterEqual(float(events[0]["duracao"]), 2.5)
        self.assertEqual(events[0]["midia_path"], "data/evidence/a6-stop.jpg")
        self.assertEqual(len(outbox_rows), 1)
        self.assertEqual(len(evidence_rows), 1)
        # Raw machine events no longer email by default; Alert Decisioning owns outbound alerts.
        self.assertEqual(deliveries, [])
        provenance = events[0]["metadata"]["observation_provenance"]
        self.assertEqual(provenance["runtime"], "MachineMonitorEngine")
        self.assertIn("machine_activity", provenance["source_observations"])

    def test_unknown_and_unready_machine_observations_do_not_open_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            test_connect, cliente_id, unidade_id, camera_id, monitor_id = self._context(temp_dir)
            engine = self._engine(cliente_id, unidade_id, camera_id, monitor_id)
            engine.config.active_baseline = None
            engine.config.stopped_baseline = None
            engine.config.calibration_result = "CALIBRATION_REQUIRED"
            frame = np.zeros((80, 120, 3), dtype=np.uint8)
            with patch("app.machine_monitoring.connect", test_connect), patch("app.alerts.connect", test_connect):
                engine.state.state = "UNKNOWN"
                engine._evaluate_official_events(10.0, frame)
                engine.state.state = "STOPPED"
                engine.state.confidence = 0.95
                engine._evaluate_official_events(20.0, frame)
            with test_connect() as connection:
                total = connection.execute("SELECT COUNT(*) AS total FROM eventos").fetchone()["total"]

        self.assertEqual(total, 0)

    def test_frame_isolated_repetition_does_not_duplicate_open_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            test_connect, cliente_id, unidade_id, camera_id, monitor_id = self._context(temp_dir)
            engine = self._engine(cliente_id, unidade_id, camera_id, monitor_id)
            frame = np.zeros((80, 120, 3), dtype=np.uint8)
            with patch("app.machine_monitoring.connect", test_connect), patch("app.alerts.connect", test_connect), patch("app.machine_monitoring.save_machine_evidence", return_value=(None, None)):
                engine.state.state = "STOPPED"
                engine.state.state_since = 100.0
                engine.state.confidence = 0.9
                for now in [100.0, 100.05, 100.1, 100.15]:
                    engine._evaluate_official_events(now, frame)
                engine._evaluate_official_events(100.5, frame)
                engine._evaluate_official_events(101.0, frame)
            with test_connect() as connection:
                rows = connection.execute("SELECT * FROM eventos WHERE tipo = 'machine_stoppage'").fetchall()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "open")

    def test_running_without_operator_requires_temporal_absence_and_closes_on_return(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            test_connect, cliente_id, unidade_id, camera_id, monitor_id = self._context(temp_dir)
            engine = self._engine(cliente_id, unidade_id, camera_id, monitor_id)
            frame = np.zeros((80, 120, 3), dtype=np.uint8)
            with patch("app.machine_monitoring.connect", test_connect), patch("app.alerts.connect", test_connect), patch("app.machine_monitoring.save_machine_evidence", return_value=(None, None)):
                engine.state.state = "ACTIVE"
                engine.state.confidence = 0.9
                engine.state.operator_present = True
                engine._evaluate_official_events(10.0, frame)
                engine.state.operator_present = False
                engine.state.operator_absence_confirmed = False
                engine._evaluate_official_events(11.0, frame)
                engine.state.operator_present = True
                engine.state.operator_absence_confirmed = False
                engine._evaluate_official_events(11.1, frame)
                engine.state.operator_present = False
                engine.state.operator_absence_confirmed = True
                engine._evaluate_official_events(12.0, frame)
                engine._evaluate_official_events(12.3, frame)
                engine.state.operator_present = True
                engine.state.operator_absence_confirmed = False
                engine._evaluate_official_events(13.0, frame)
            with test_connect() as connection:
                rows = listar_eventos_filtrados(connection, tipo="machine_running_without_operator")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "closed")
        self.assertGreaterEqual(float(rows[0]["duracao"]), 0.9)
        self.assertIn("person_presence", rows[0]["metadata"]["observation_provenance"]["source_observations"])

    def test_stopped_with_operator_uses_observation_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            test_connect, cliente_id, unidade_id, camera_id, monitor_id = self._context(temp_dir)
            engine = self._engine(cliente_id, unidade_id, camera_id, monitor_id)
            frame = np.zeros((80, 120, 3), dtype=np.uint8)
            with patch("app.machine_monitoring.connect", test_connect), patch("app.alerts.connect", test_connect), patch("app.machine_monitoring.save_machine_evidence", return_value=(None, None)):
                engine.state.state = "STOPPED"
                engine.state.state_since = 40.0
                engine.state.confidence = 0.88
                engine.state.operator_present = True
                engine._evaluate_official_events(40.0, frame)
                engine._evaluate_official_events(40.3, frame)
            with test_connect() as connection:
                rows = listar_eventos_filtrados(connection, tipo="machine_stopped_with_operator")

        self.assertEqual(len(rows), 1)
        provenance = rows[0]["metadata"]["observation_provenance"]
        self.assertEqual(provenance["event_type"], "machine_stopped_with_operator")
        self.assertIn("zone_occupancy", provenance["source_observations"])

    def test_workstation_unattended_and_restricted_zone_are_temporal_zone_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict("os.environ", {"CAMPEX_EMAIL_MODE": "console", "CAMPEX_ZONE_EVENT_SECONDS": "0"}):
            test_connect, _cliente_id, _unidade_id, camera_id, _monitor_id = self._context(temp_dir)
            evidence_root = Path(temp_dir) / "evidence"
            frame = np.zeros((100, 100, 3), dtype=np.uint8)
            with test_connect() as connection:
                work_id = criar_area_monitorada(
                    connection,
                    camera_id,
                    "Posto A6",
                    [{"x": 0.2, "y": 0.2}, {"x": 0.8, "y": 0.2}, {"x": 0.8, "y": 0.8}, {"x": 0.2, "y": 0.8}],
                    tipo="work_area",
                    absence_tolerance_seconds=0,
                )
                restricted_id = criar_area_monitorada(
                    connection,
                    camera_id,
                    "Restrita A6",
                    [{"x": 0.2, "y": 0.2}, {"x": 0.8, "y": 0.2}, {"x": 0.8, "y": 0.8}, {"x": 0.2, "y": 0.8}],
                    tipo="restricted_zone",
                )
                self._add_active_operational_context(connection, camera_id)
                areas = listar_areas_camera(connection, camera_id)
            engine = PeopleZonesEngine(camera_id, evidence_root=evidence_root)
            inside = [Detection(35, 10, 50, 70, 0.9, track_id=9)]
            with patch("app.people_zones.connect", test_connect), patch("app.alerts.connect", test_connect):
                engine.update(areas, inside, frame)
                engine.update(areas, inside, frame)
                engine.update(areas, [], frame)
                engine.update(areas, [], frame)
            with test_connect() as connection:
                unattended = listar_eventos_filtrados(connection, area_id=work_id, tipo="workstation_unattended")
                restricted = listar_eventos_filtrados(connection, area_id=restricted_id, tipo="restricted_zone_occupied")

        self.assertEqual(len(unattended), 1)
        self.assertEqual(len(restricted), 1)
        self.assertIn("zone_occupancy", unattended[0]["metadata"]["observation_provenance"]["source_observations"])
        self.assertIn("zone_occupancy", restricted[0]["metadata"]["observation_provenance"]["source_observations"])

    def test_evidence_failure_preserves_event_and_alert_failure_does_not_abort(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            test_connect, cliente_id, unidade_id, camera_id, monitor_id = self._context(temp_dir)
            engine = self._engine(cliente_id, unidade_id, camera_id, monitor_id)
            frame = np.zeros((80, 120, 3), dtype=np.uint8)
            with patch("app.machine_monitoring.connect", test_connect), patch("app.machine_monitoring.save_machine_evidence", return_value=(None, "disk full")), patch("app.machine_monitoring.enqueue_event_alert", side_effect=RuntimeError("smtp down")):
                engine.state.state = "STOPPED"
                engine.state.state_since = 100.0
                engine.state.confidence = 0.9
                engine._evaluate_official_events(100.5, frame)
            with test_connect() as connection:
                rows = listar_eventos_filtrados(connection, tipo="machine_stoppage")
                outbox = connection.execute("SELECT COUNT(*) AS total FROM sync_outbox").fetchone()["total"]

        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["midia_path"])
        self.assertGreaterEqual(outbox, 1)

    def test_restart_does_not_duplicate_open_event_for_same_monitor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            test_connect, cliente_id, unidade_id, camera_id, monitor_id = self._context(temp_dir)
            frame = np.zeros((80, 120, 3), dtype=np.uint8)
            first = self._engine(cliente_id, unidade_id, camera_id, monitor_id)
            restarted = self._engine(cliente_id, unidade_id, camera_id, monitor_id)
            with patch("app.machine_monitoring.connect", test_connect), patch("app.alerts.connect", test_connect), patch("app.machine_monitoring.save_machine_evidence", return_value=(None, None)):
                first.state.state = "STOPPED"
                first.state.state_since = 100.0
                first.state.confidence = 0.9
                first._evaluate_official_events(100.5, frame)
                restarted.state.state = "STOPPED"
                restarted.state.state_since = 101.0
                restarted.state.confidence = 0.9
                restarted._evaluate_official_events(101.5, frame)
            with test_connect() as connection:
                rows = listar_eventos_filtrados(connection, tipo="machine_stoppage")

        self.assertEqual(len(rows), 1)

    def test_two_tenants_never_share_event_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            test_connect, cliente_a, unidade_a, camera_a, monitor_a = self._context(temp_dir)
            with test_connect() as connection:
                cliente_b = criar_cliente(connection, "Tenant B")
                unidade_b = criar_unidade(connection, cliente_b, "Unidade B")
                camera_b = criar_camera(connection, unidade_b, "Camera B", cliente_id=cliente_b)
                monitor_b = criar_machine_monitor(
                    connection,
                    cliente_b,
                    unidade_b,
                    camera_b,
                    "B6",
                    [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.1}, {"x": 0.9, "y": 0.9}],
                    [{"x": 0.0, "y": 0.1}, {"x": 0.2, "y": 0.1}, {"x": 0.2, "y": 0.9}],
                    stop_seconds=0.2,
                    recovery_seconds=0.2,
                    operator_absence_seconds=0.2,
                    stopped_with_operator_seconds=0.2,
                )
            frame = np.zeros((80, 120, 3), dtype=np.uint8)
            engine_a = self._engine(cliente_a, unidade_a, camera_a, monitor_a)
            engine_b = self._engine(cliente_b, unidade_b, camera_b, monitor_b)
            with patch("app.machine_monitoring.connect", test_connect), patch("app.alerts.connect", test_connect), patch("app.machine_monitoring.save_machine_evidence", return_value=(None, None)):
                engine_a.state.state = "STOPPED"
                engine_a.state.state_since = 100.0
                engine_a.state.confidence = 0.9
                engine_a._evaluate_official_events(100.5, frame)
            with test_connect() as connection:
                total_a = connection.execute("SELECT COUNT(*) AS total FROM eventos WHERE cliente_id = ?", (cliente_a,)).fetchone()["total"]
                total_b = connection.execute("SELECT COUNT(*) AS total FROM eventos WHERE cliente_id = ?", (cliente_b,)).fetchone()["total"]

        self.assertEqual(total_a, 1)
        self.assertEqual(total_b, 0)
        self.assertEqual(engine_b.state.active_events, {})


if __name__ == "__main__":
    unittest.main()
