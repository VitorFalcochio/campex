from __future__ import annotations

import unittest

import numpy as np

from app.live_view_ops import LiveViewOpsEngine, draw_live_view_overlay
from app.person_detection import Detection


class LiveViewOpsTest(unittest.TestCase):
    def test_machine_config_uses_normalized_points(self) -> None:
        engine = LiveViewOpsEngine()
        state = engine.configure_machine(
            "Extrusora",
            [
                {"x": -1, "y": 0.2},
                {"x": 0.8, "y": 0.2},
                {"x": 0.8, "y": 2},
                {"x": -1, "y": 2},
            ],
        )

        points = state["machine"]["machine_polygon"]
        self.assertEqual(points[0], {"x": 0.0, "y": 0.2})
        self.assertEqual(points[2], {"x": 0.8, "y": 1.0})
        self.assertEqual(state["machine_state"], "UNKNOWN")
        self.assertEqual(state["calibration_status"], "use_assisted_calibration_endpoint")

    def test_compatibility_engine_does_not_determine_operator_presence(self) -> None:
        engine = LiveViewOpsEngine()
        engine.set_ai(True)
        engine.configure_machine(
            "Extrusora",
            [
                {"x": 0.1, "y": 0.1},
                {"x": 0.9, "y": 0.1},
                {"x": 0.9, "y": 0.9},
                {"x": 0.1, "y": 0.9},
            ],
            operator_polygon=[
                {"x": 0.4, "y": 0.4},
                {"x": 0.8, "y": 0.4},
                {"x": 0.8, "y": 1.0},
                {"x": 0.4, "y": 1.0},
            ],
        )
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        engine.update(frame, [Detection(45, 20, 65, 95, 0.9, track_id=7)])

        state = engine.public_state()
        self.assertFalse(state["operator_present"])
        self.assertEqual(state["operator_people_count"], 0)
        self.assertIn("MachineMonitorEngine", state["relation"])

    def test_unconfigured_machine_is_not_camera_without_signal(self) -> None:
        engine = LiveViewOpsEngine()
        engine.set_ai(True)
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        engine.update(frame, [Detection(10, 10, 30, 80, 0.9, track_id=1)])

        state = engine.public_state()

        self.assertEqual(state["machine_state"], "NAO_CONFIGURADA")
        self.assertEqual(state["people_count"], 1)
        self.assertEqual(state["relation"], "Aguardando configuração persistente")

    def test_machine_state_changes_after_calibration(self) -> None:
        engine = LiveViewOpsEngine()
        engine.configure_machine(
            "Esteira",
            [
                {"x": 0.0, "y": 0.0},
                {"x": 1.0, "y": 0.0},
                {"x": 1.0, "y": 1.0},
                {"x": 0.0, "y": 1.0},
            ],
        )
        engine.calibrate_active(current_motion=20.0)
        state = engine.update(np.full((32, 32, 3), 255, dtype=np.uint8), [])
        self.assertEqual(state.shape, (32, 32, 3))
        self.assertEqual(engine.public_state()["machine_state"], "UNKNOWN")
        self.assertEqual(engine.public_state()["calibration_status"], "use_assisted_calibration_endpoint")

    def test_overlay_draws_without_credentials_or_crash(self) -> None:
        engine = LiveViewOpsEngine()
        engine.configure_machine(
            "Máquina",
            [
                {"x": 0.1, "y": 0.1},
                {"x": 0.9, "y": 0.1},
                {"x": 0.9, "y": 0.9},
                {"x": 0.1, "y": 0.9},
            ],
        )
        frame = np.zeros((80, 80, 3), dtype=np.uint8)
        annotated = draw_live_view_overlay(frame, engine.config, engine.state, [Detection(5, 5, 20, 30, 0.8, track_id=1)])
        self.assertEqual(annotated.shape, frame.shape)
        self.assertNotIn("senha", str(engine.public_state()).lower())


if __name__ == "__main__":
    unittest.main()
