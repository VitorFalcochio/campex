from __future__ import annotations

import tempfile
import time as real_time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from app.database import connect, init_db
from app.machine_monitoring import MachineMonitorConfig, MachineMonitorEngine, machine_activity_score
from app.models import (
    criar_alert_recipient,
    criar_camera,
    criar_cliente,
    criar_machine_monitor,
    criar_unidade,
)
from app.restricted_area import AreaPoint


class P0VerticalSliceTest(unittest.TestCase):
    def test_machine_stoppage_full_chain_with_synthetic_frames(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "p0.sqlite3"
            evidence_root = Path(temp_dir)

            def test_connect():
                return connect(db_path)

            with test_connect() as connection:
                init_db(connection)
                cliente_id = criar_cliente(connection, "Cliente P0")
                unidade_id = criar_unidade(connection, cliente_id, "Unidade P0")
                camera_id = criar_camera(connection, unidade_id, "Camera P0", cliente_id=cliente_id)
                monitor_id = criar_machine_monitor(
                    connection,
                    cliente_id,
                    unidade_id,
                    camera_id,
                    "Extrusora P0",
                    [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.1}, {"x": 0.9, "y": 0.9}, {"x": 0.1, "y": 0.9}],
                    [{"x": 0.0, "y": 0.1}, {"x": 0.05, "y": 0.1}, {"x": 0.05, "y": 0.9}, {"x": 0.0, "y": 0.9}],
                    stop_seconds=0.25,
                    recovery_seconds=0.25,
                    operator_absence_seconds=9999.0,
                    stopped_with_operator_seconds=9999.0,
                    microstop_limit=9999,
                )
                criar_alert_recipient(
                    connection,
                    "Console P0",
                    "p0-console@campex.dev",
                    cliente_id=cliente_id,
                    event_types=["machine_stoppage"],
                    severidade_minima="low",
                )

            polygon = [AreaPoint(0.1, 0.1), AreaPoint(0.9, 0.1), AreaPoint(0.9, 0.9), AreaPoint(0.1, 0.9)]
            black = np.zeros((80, 120, 3), dtype=np.uint8)
            white = np.full((80, 120, 3), 255, dtype=np.uint8)

            active_samples = self._scores([black, white, black, white], polygon)
            stopped_samples = self._scores([black, black, black, black], polygon)
            self.assertGreater(min(active_samples), 100.0)
            self.assertEqual(max(stopped_samples), 0.0)

            config = MachineMonitorConfig(
                id=monitor_id,
                client_id=cliente_id,
                unit_id=unidade_id,
                camera_id=camera_id,
                nome="Extrusora P0",
                machine_polygon=polygon,
                operator_polygon=[AreaPoint(0.0, 0.1), AreaPoint(0.05, 0.1), AreaPoint(0.05, 0.9), AreaPoint(0.0, 0.9)],
                stop_seconds=0.25,
                recovery_seconds=0.25,
                operator_absence_seconds=9999.0,
                stopped_with_operator_seconds=9999.0,
                microstop_limit=9999,
            )
            engine = MachineMonitorEngine(config)
            engine.analysis_fps = 1000.0
            engine.smoothing_seconds = 0.01
            engine.state.last_update = 0.0
            engine._last_analysis = -1.0
            current = [0.0]
            states: list[str] = []

            def set_time(value: float) -> None:
                current[0] = value

            with (
                patch("app.machine_monitoring.connect", test_connect),
                patch("app.alerts.connect", test_connect),
                patch("app.machine_monitoring.ROOT", evidence_root),
                patch("app.machine_monitoring.time.monotonic", lambda: current[0]),
                patch.dict("os.environ", {"CAMPEX_EMAIL_MODE": "console", "CAMPEX_EMAIL_MAX_ATTEMPTS": "1"}),
            ):
                engine.calibrate_active(active_samples)
                engine.calibrate_stopped(stopped_samples)
                for timestamp, frame in [
                    (0.0, black),
                    (0.1, white),
                    (0.4, black),
                    (0.5, black),
                    (0.9, black),
                    (1.1, black),
                    (1.2, white),
                    (1.5, black),
                ]:
                    set_time(timestamp)
                    states.append(engine.update(frame, []).state)
                real_time.sleep(0.2)

            with test_connect() as connection:
                events = connection.execute("SELECT * FROM eventos WHERE tipo = 'machine_stoppage'").fetchall()
                outbox = connection.execute("SELECT * FROM sync_outbox").fetchall()
                deliveries = connection.execute("SELECT * FROM alert_deliveries").fetchall()

        self.assertIn("ACTIVE", states)
        self.assertIn("STOPPED", states)
        self.assertEqual(states[-1], "ACTIVE")
        self.assertEqual(engine.state.analysis_status, "ANALYZING")
        self.assertGreater(engine.state.frames_analyzed, 0)
        self.assertGreater(engine.state.roi_width, 0)
        self.assertGreater(engine.state.roi_height, 0)
        self.assertIsNotNone(engine.state.raw_activity_score)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["status"], "closed")
        self.assertGreaterEqual(float(events[0]["duracao"]), 0.5)
        self.assertLess(float(events[0]["duracao"]), 1.0)
        self.assertTrue(events[0]["midia_path"])
        self.assertEqual(len(outbox), 1)
        self.assertEqual(outbox[0]["status"], "pending")
        # Short raw stoppages stay in the event stream/outbox; decisioning decides whether to alert.
        self.assertEqual(len(deliveries), 0)

    def _scores(self, frames: list[np.ndarray], polygon: list[AreaPoint]) -> list[float]:
        previous = None
        scores: list[float] = []
        for frame in frames:
            score, previous, diagnostics = machine_activity_score(frame, polygon, previous)
            if diagnostics["analysis_status"] == "ANALYZING" and score is not None:
                scores.append(float(score))
        return scores


if __name__ == "__main__":
    unittest.main()
