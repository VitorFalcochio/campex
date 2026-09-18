from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from app.database import connect, init_db
from app.live_stream import LiveCameraStream, calibration_separation, calibration_stats
from app.machine_monitoring import MachineMonitorConfig, MachineMonitorEngine, baseline_stats
from app.models import criar_area_monitorada, criar_camera, criar_cliente, criar_machine_monitor, criar_unidade, obter_machine_monitor
from app.models import criar_alert_recipient, fechar_eventos_machine_interrompidos, listar_alert_deliveries
from app.machine_replay import evaluate_state_samples
from app.observation_engine import ObservationEngine
from app.person_detection import Detection
from app.restricted_area import AreaPoint


class MachineOperatorIntelligenceV1Test(unittest.TestCase):
    def make_context(self, temp_dir: str):
        db_path = Path(temp_dir) / "machine-v1.sqlite3"

        def test_connect():
            return connect(db_path)

        with test_connect() as connection:
            init_db(connection)
            cliente_id = criar_cliente(connection, "Cliente")
            unidade_id = criar_unidade(connection, cliente_id, "Unidade")
            camera_id = criar_camera(connection, unidade_id, "Camera", cliente_id=cliente_id)
            monitor_id = criar_machine_monitor(
                connection,
                cliente_id,
                unidade_id,
                camera_id,
                "Extrusora",
                [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.1}, {"x": 0.9, "y": 0.9}],
                [{"x": 0.0, "y": 0.1}, {"x": 0.2, "y": 0.1}, {"x": 0.2, "y": 0.9}],
                stop_seconds=0.1,
                recovery_seconds=0.1,
                operator_absence_seconds=0.1,
                stopped_with_operator_seconds=0.1,
                loss_model="loss_per_minute",
                loss_per_minute=120.0,
            )
        return test_connect, cliente_id, unidade_id, camera_id, monitor_id

    def make_engine(self, cliente_id: str, unidade_id: str, camera_id: str, monitor_id: str) -> MachineMonitorEngine:
        config = MachineMonitorConfig(
            id=monitor_id,
            client_id=cliente_id,
            unit_id=unidade_id,
            camera_id=camera_id,
            nome="Extrusora",
            machine_polygon=[AreaPoint(0.1, 0.1), AreaPoint(0.9, 0.1), AreaPoint(0.9, 0.9)],
            operator_polygon=[AreaPoint(0.0, 0.1), AreaPoint(0.2, 0.1), AreaPoint(0.2, 0.9)],
            stop_seconds=0.1,
            recovery_seconds=0.1,
            operator_absence_seconds=0.1,
            stopped_with_operator_seconds=0.1,
            active_baseline=30.0,
            stopped_baseline=2.0,
            active_noise=1.0,
            stopped_noise=0.5,
            loss_model="loss_per_minute",
            loss_per_minute=120.0,
        )
        return MachineMonitorEngine(config)

    def wait_for_deliveries(self, test_connect, expected: int = 1):
        for _ in range(30):
            with test_connect() as connection:
                rows = listar_alert_deliveries(connection)
            if len(rows) >= expected and all(row["status"] != "pending" for row in rows):
                return rows
            time.sleep(0.05)
        with test_connect() as connection:
            return listar_alert_deliveries(connection)

    def test_baseline_stats_are_measurable(self) -> None:
        baseline, noise = baseline_stats([10, 12, 14])

        self.assertEqual(baseline, 12.0)
        self.assertGreater(noise, 0)

    def test_default_operator_presence_grace_is_conservative_for_factory_flow(self) -> None:
        config = MachineMonitorConfig(
            id="mon_1",
            client_id="tenant",
            unit_id="unit",
            camera_id="cam_1",
            nome="A6",
            machine_polygon=[AreaPoint(0.1, 0.1), AreaPoint(0.9, 0.1), AreaPoint(0.9, 0.9)],
            operator_polygon=[AreaPoint(0.0, 0.0), AreaPoint(0.2, 0.0), AreaPoint(0.2, 1.0)],
        )

        self.assertEqual(config.operator_presence_grace_seconds, 45.0)

    def test_evidence_window_keeps_only_recent_compressed_frames(self) -> None:
        stream = LiveCameraStream("cam_evidence", "fake.mp4")
        frame = np.zeros((60, 80, 3), dtype=np.uint8)

        with patch(
            "app.live_stream.time.monotonic",
            side_effect=[100.0, 101.0, 102.1, 133.0, 133.0],
        ), patch(
            "app.live_stream.now_iso",
            side_effect=[
                "2026-08-19T10:00:00+00:00",
                "2026-08-19T10:00:02+00:00",
                "2026-08-19T10:00:33+00:00",
            ],
        ):
            stream._buffer_evidence_frame(frame)
            stream._buffer_evidence_frame(frame)
            stream._buffer_evidence_frame(frame)
            stream._buffer_evidence_frame(frame)
            recent = stream.recent_evidence_frames(30)

        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0]["captured_at"], "2026-08-19T10:00:33+00:00")
        self.assertIsInstance(recent[0]["jpeg"], bytes)
        self.assertGreater(len(recent[0]["jpeg"]), 0)

    def test_visual_candidate_persists_before_transition_after_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            test_connect, _cliente_id, _unidade_id, camera_id, _monitor_id = self.make_context(temp_dir)
            stream = LiveCameraStream(camera_id, "fake.mp4")

            frame = np.zeros((60, 80, 3), dtype=np.uint8)
            encoded, jpeg = __import__("cv2").imencode(".jpg", frame)
            self.assertTrue(encoded)
            jpeg_bytes = jpeg.tobytes()

            stream._evidence_buffer.extend([
                {"captured_at": "2026-08-19T10:00:00+00:00", "monotonic": 90.0, "jpeg": jpeg_bytes},
                {"captured_at": "2026-08-19T10:00:05+00:00", "monotonic": 95.0, "jpeg": jpeg_bytes},
            ])

            evidence_root = Path(temp_dir)

            with patch("app.live_stream.EVIDENCE_DIR", evidence_root), patch("app.live_stream.connect", test_connect), patch("app.live_stream.time.monotonic", return_value=100.0):
                candidate_id = stream.start_visual_candidate(
                    "scene_change",
                    context={"camera_id": camera_id},
                    before_seconds=12.0,
                    after_seconds=5.0,
                )

                stream._update_visual_candidates({
                    "captured_at": "2026-08-19T10:00:01+00:00",
                    "monotonic": 101.0,
                    "jpeg": jpeg_bytes,
                })
                stream._update_visual_candidates({
                    "captured_at": "2026-08-19T10:00:03+00:00",
                    "monotonic": 103.0,
                    "jpeg": jpeg_bytes,
                })
                stream._update_visual_candidates({
                    "captured_at": "2026-08-19T10:00:06+00:00",
                    "monotonic": 106.0,
                    "jpeg": jpeg_bytes,
                })

            with test_connect() as connection:
                rows = connection.execute(
                    "SELECT path, metadata_json FROM evidences WHERE camera_id = ? ORDER BY created_at, id",
                    (camera_id,),
                ).fetchall()

            self.assertNotIn(candidate_id, stream._visual_candidates)
            self.assertGreaterEqual(len(rows), 4)

            metadata = [__import__("json").loads(row["metadata_json"]) for row in rows]
            phases = {item.get("phase") for item in metadata}

            self.assertIn("before", phases)
            self.assertIn("transition", phases)
            self.assertIn("after", phases)
            self.assertTrue(all(item.get("candidate_id") == candidate_id for item in metadata))

            for row in rows:
                self.assertTrue((evidence_root / row["path"]).exists())

    def test_visual_candidate_rebuilds_as_official_video_context(self) -> None:
        from datetime import datetime, timezone

        from app.models import new_id, registrar_evidence_index
        from app.operational_read_model import (
            ReadModelFilters,
            _context_id_for_trigger,
            video_context_by_id,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            test_connect, cliente_id, unidade_id, camera_id, _monitor_id = self.make_context(temp_dir)

            candidate_id = new_id("vcan")
            triggered_at = "2026-08-19T14:00:10+00:00"
            context = {"camera_id": camera_id}

            samples = [
                ("before", "2026-08-19T14:00:05+00:00"),
                ("transition", "2026-08-19T14:00:10+00:00"),
                ("after", "2026-08-19T14:00:15+00:00"),
            ]

            with test_connect() as connection:
                for phase, captured_at in samples:
                    registrar_evidence_index(
                        connection,
                        evidence_id=new_id("evd"),
                        event_id=None,
                        event_uuid=None,
                        tenant_id=cliente_id,
                        unit_id=unidade_id,
                        camera_id=camera_id,
                        machine_id=None,
                        path=f"data/evidence/{camera_id}/{phase}.jpg",
                        media_type="image",
                        size_bytes=123,
                        metadata={
                            "source": "visual_candidate",
                            "candidate_id": candidate_id,
                            "candidate_type": "scene_change",
                            "phase": phase,
                            "captured_at": captured_at,
                            "triggered_at": triggered_at,
                            "context": context,
                        },
                    )

                trigger = {
                    "type": "visual_candidate_scene_change",
                    "ref": candidate_id,
                    "timestamp": triggered_at,
                    "context": context,
                    "source": "visual_evidence_bundle",
                }
                context_id = _context_id_for_trigger(trigger)

                filters = ReadModelFilters(
                    cliente_id=cliente_id,
                    site_id=unidade_id,
                    camera_id=camera_id,
                    start=datetime(2026, 8, 19, 13, 59, tzinfo=timezone.utc),
                    end=datetime(2026, 8, 19, 14, 1, tzinfo=timezone.utc),
                )

                video_context = video_context_by_id(
                    connection,
                    filters,
                    context_id,
                )

            self.assertIsNotNone(video_context)
            self.assertEqual(video_context["context_id"], context_id)
            self.assertEqual(video_context["camera_id"], camera_id)
            self.assertEqual(video_context["trigger"]["ref"], candidate_id)

            self.assertIn("before", video_context["phases"])
            self.assertIn("transition", video_context["phases"])
            self.assertIn("after", video_context["phases"])

            self.assertEqual(len(video_context["evidence_refs"]), 3)
            self.assertTrue(video_context["data_quality"]["evidence_available"])

    def test_machine_state_change_starts_visual_candidate(self) -> None:
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as temp_dir:
            _test_connect, cliente_id, unidade_id, camera_id, monitor_id = self.make_context(temp_dir)

            stream = LiveCameraStream(camera_id, "fake.mp4")
            engine = self.make_engine(cliente_id, unidade_id, camera_id, monitor_id)
            stream.status.machine_state = "ACTIVE"

            state = SimpleNamespace(
                state="STOPPED",
                smoothed_motion=2.0,
                threshold=15.0,
                operator_present=False,
                event_id=None,
                confidence=0.9,
                reason="motion_below_threshold",
                analysis_status="ok",
                analysis_error=None,
                raw_activity_score=2.0,
                frames_analyzed=10,
                roi_width=100,
                roi_height=100,
            )

            frame = np.zeros((100, 100, 3), dtype=np.uint8)

            with patch.object(engine, "update", return_value=state), \
                 patch("app.live_stream.draw_machine_overlay", side_effect=lambda frame, config, state: frame), \
                 patch.object(stream._observation_engine, "build", return_value={"seconds_in_machine_state": 0}), \
                 patch.object(stream._operations_recorder, "update_status"), \
                 patch.object(stream, "_evaluate_rules"), \
                 patch.object(stream, "start_visual_candidate") as start_candidate:

                stream._update_machines(frame, [engine])

            start_candidate.assert_called_once()
            args, kwargs = start_candidate.call_args

            self.assertEqual(args[0], "machine_state_change")
            self.assertEqual(kwargs["context"]["camera_id"], camera_id)
            self.assertEqual(kwargs["context"]["machine_id"], monitor_id)
            self.assertEqual(kwargs["context"]["previous_state"], "ACTIVE")
            self.assertEqual(kwargs["context"]["new_state"], "STOPPED")

    def test_visual_candidate_runs_automatic_understanding_worker(self) -> None:
        stream = LiveCameraStream("cam_auto_understanding", "fake.mp4")

        candidate = {
            "candidate_id": "vcan_auto_1",
            "candidate_type": "machine_state_change",
            "triggered_at": "2026-08-19T15:00:00+00:00",
            "context": {
                "tenant_id": "tenant_1",
                "unit_id": "unit_1",
                "camera_id": "cam_auto_understanding",
                "machine_id": "machine_1",
                "previous_state": "ACTIVE",
                "new_state": "STOPPED",
            },
        }

        with patch.dict(
            "os.environ",
            {
                "CAMPEX_VISUAL_UNDERSTANDING_AUTO_ENABLED": "true",
                "CAMPEX_VIDEO_UNDERSTANDING_PROVIDER": "fake",
            },
        ), patch(
            "app.video_understanding.VideoUnderstandingService.analyze_context",
            return_value={"status": "ok"},
        ) as analyze_context:
            stream._enqueue_visual_understanding(candidate)
            stream._visual_understanding_queue.join()

        stream._visual_understanding_worker_stop.set()
        thread = stream._visual_understanding_worker_thread
        if thread:
            thread.join(timeout=2.0)

        analyze_context.assert_called_once()
        self.assertIn(
            candidate["candidate_id"],
            stream._visual_understanding_processed,
        )
        self.assertIsNone(stream._last_visual_understanding_error)

    def test_validated_understanding_materializes_visual_occurrence_once(self) -> None:
        from app.models import new_id, registrar_evidence_index
        from app.operational_understanding import _materialize_visual_occurrence

        with tempfile.TemporaryDirectory() as temp_dir:
            test_connect, cliente_id, unidade_id, camera_id, _monitor_id = self.make_context(temp_dir)

            candidate_id = new_id("vcan")

            with test_connect() as connection:
                for phase in ("before", "transition", "after"):
                    registrar_evidence_index(
                        connection,
                        evidence_id=new_id("evd"),
                        event_id=None,
                        event_uuid=None,
                        tenant_id=cliente_id,
                        unit_id=unidade_id,
                        camera_id=camera_id,
                        machine_id=None,
                        path=f"data/evidence/{camera_id}/{candidate_id}_{phase}.jpg",
                        media_type="image",
                        size_bytes=123,
                        metadata={
                            "source": "visual_candidate",
                            "candidate_id": candidate_id,
                            "candidate_type": "scene_change",
                            "phase": phase,
                        },
                    )

                video_context = {
                    "trigger": {
                        "type": "visual_candidate_scene_change",
                        "ref": candidate_id,
                        "timestamp": "2026-08-19T16:00:00+00:00",
                        "context": {"camera_id": camera_id},
                    }
                }

                understanding = {
                    "status": "VALID",
                    "tenant_id": cliente_id,
                    "unit_id": unidade_id,
                    "camera_id": camera_id,
                    "trigger_ref": candidate_id,
                }

                first_event_id = _materialize_visual_occurrence(
                    connection,
                    video_context=video_context,
                    understanding=understanding,
                )
                second_event_id = _materialize_visual_occurrence(
                    connection,
                    video_context=video_context,
                    understanding=understanding,
                )

                events = connection.execute(
                    """
                    SELECT id, event_uuid, tipo, event_family, event_subtype
                    FROM eventos
                    WHERE event_uuid = ?
                    """,
                    (f"visual:{candidate_id}",),
                ).fetchall()

                evidences = connection.execute(
                    """
                    SELECT event_id, event_uuid
                    FROM evidences
                    WHERE camera_id = ?
                      AND metadata_json LIKE ?
                    """,
                    (camera_id, f"%{candidate_id}%"),
                ).fetchall()

            self.assertIsNotNone(first_event_id)
            self.assertEqual(first_event_id, second_event_id)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["tipo"], "visual_occurrence")
            self.assertEqual(events[0]["event_family"], "visual")
            self.assertEqual(events[0]["event_subtype"], "visual_occurrence")

            self.assertEqual(len(evidences), 3)
            self.assertTrue(all(row["event_id"] == first_event_id for row in evidences))
            self.assertTrue(all(row["event_uuid"] == f"visual:{candidate_id}" for row in evidences))

    def test_assisted_calibration_collects_frame_samples_and_persists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            test_connect, _cliente_id, _unidade_id, camera_id, monitor_id = self.make_context(temp_dir)
            with test_connect() as connection:
                criar_area_monitorada(
                    connection,
                    camera_id,
                    "Região da máquina",
                    [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 0.0}, {"x": 1.0, "y": 1.0}],
                    tipo="machine_region",
                    machine_id=monitor_id,
                )
                monitor = obter_machine_monitor(connection, monitor_id)
            stream = LiveCameraStream(camera_id, "fake.mp4")
            frame_a = np.zeros((60, 80, 3), dtype=np.uint8)
            frame_b = np.full((60, 80, 3), 255, dtype=np.uint8)

            with patch("app.live_stream.connect", test_connect):
                stream.start_machine_calibration(monitor, monitor["machine_polygon"], "active", duration_seconds=0.05)
                stream._update_calibration(frame_a)
                stream._update_calibration(frame_b)
                stream._update_calibration(frame_a)
                time.sleep(0.06)
                stream._update_calibration(frame_b)
            with test_connect() as connection:
                rows = connection.execute("SELECT phase, samples_json, stats_json FROM machine_calibrations WHERE machine_id = ?", (monitor_id,)).fetchall()
                updated = obter_machine_monitor(connection, monitor_id)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["phase"], "active")
        self.assertGreater(updated["active_calibration"]["samples_count"], 0)
        self.assertEqual(updated["calibration_algorithm_version"], "frame-diff-roi-temporal-v1")

    def test_live_people_count_uses_temporal_detection_consistent_with_overlay(self) -> None:
        stream = LiveCameraStream("cam_temporal", "fake.mp4")
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        temporal_person = Detection(10, 10, 30, 80, 0.9, track_id=7)

        class FakeEngine:
            analysis_fps = 5.0
            model_name = "fake"

            def analyze(self, _frame):
                return []

            def recent_detections(self):
                return [temporal_person]

            def draw(self, output, _detections):
                return output

        stream._analysis_enabled = True
        stream._last_analysis_seconds = 0
        stream._ensure_analysis_engine = lambda: FakeEngine()
        stream._load_active_areas = lambda: []
        stream._load_machine_engines = lambda: []

        stream._maybe_analyze(frame)

        self.assertEqual(stream.public_status()["people_count"], 1)

    def test_calibration_separation_ready_and_invalid(self) -> None:
        active = calibration_stats([30, 32, 31, 33, 29])
        stopped = calibration_stats([1, 2, 1, 3, 2])

        ready = calibration_separation(active, stopped)
        invalid = calibration_separation(stopped, active)

        self.assertEqual(ready["result"], "READY")
        self.assertGreater(ready["score"], 3)
        self.assertEqual(invalid["result"], "INVALID")

    def test_official_state_uses_baseline_hysteresis(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _connect, cliente_id, unidade_id, camera_id, monitor_id = self.make_context(temp_dir)
            engine = self.make_engine(cliente_id, unidade_id, camera_id, monitor_id)

        engine.state.smoothed_motion = 32.0
        active, active_confidence, _reason = engine._classify_state()
        engine.state.smoothed_motion = 1.0
        stopped, stopped_confidence, reason = engine._classify_state()

        self.assertEqual(active, "ACTIVE")
        self.assertEqual(stopped, "STOPPED")
        self.assertGreater(active_confidence, 0.5)
        self.assertGreater(stopped_confidence, 0.5)
        self.assertIn("atividade visual", reason)

    def test_stop_event_is_unique_closes_and_enters_outbox_with_estimated_loss(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            test_connect, cliente_id, unidade_id, camera_id, monitor_id = self.make_context(temp_dir)
            engine = self.make_engine(cliente_id, unidade_id, camera_id, monitor_id)
            frame = np.zeros((80, 120, 3), dtype=np.uint8)
            now = time.monotonic()
            with patch("app.machine_monitoring.connect", test_connect), patch("app.alerts.connect", test_connect), patch("app.machine_monitoring.save_machine_evidence", return_value=("data/evidence/test.jpg", None)):
                engine.state.state = "STOPPED"
                engine.state.state_since = now - 120.0
                engine.state.confidence = 0.9
                engine.state.reason = "atividade visual abaixo do baseline por 120 segundos"
                engine._evaluate_official_events(now, frame)
                engine._evaluate_official_events(now + 1, frame)
                engine.state.state = "ACTIVE"
                engine._evaluate_official_events(now + 120, frame)
            with test_connect() as connection:
                events = connection.execute("SELECT tipo, status, duracao, midia_path, metadata_json FROM eventos").fetchall()
                outbox = connection.execute("SELECT COUNT(*) AS total FROM sync_outbox").fetchone()["total"]

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["tipo"], "machine_stoppage")
        self.assertEqual(events[0]["status"], "closed")
        self.assertGreaterEqual(events[0]["duracao"], 100)
        self.assertEqual(events[0]["midia_path"], "data/evidence/test.jpg")
        self.assertIn("Impacto operacional estimado", events[0]["metadata_json"])
        self.assertEqual(outbox, 1)

    def test_runtime_restart_closes_orphan_machine_event_without_inflating_duration(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            test_connect, cliente_id, unidade_id, camera_id, monitor_id = self.make_context(temp_dir)
            engine = self.make_engine(cliente_id, unidade_id, camera_id, monitor_id)
            frame = np.zeros((80, 120, 3), dtype=np.uint8)
            now = time.monotonic()
            with patch("app.machine_monitoring.connect", test_connect), patch("app.alerts.connect", test_connect), patch("app.machine_monitoring.save_machine_evidence", return_value=(None, None)):
                engine.state.state = "STOPPED"
                engine.state.state_since = now - 12.0
                engine.state.confidence = 0.9
                engine._open_event(now, frame, "machine_stoppage")
                engine._update_event_type("machine_stoppage", now + 12.0)
            with test_connect() as connection:
                before = connection.execute("SELECT id, status, duracao FROM eventos WHERE tipo = 'machine_stoppage'").fetchone()
                self.assertEqual(before["status"], "open")
                stored_duration = float(before["duracao"] or 0)
                closed = fechar_eventos_machine_interrompidos(connection)
                after = connection.execute("SELECT status, duracao, fim FROM eventos WHERE id = ?", (before["id"],)).fetchone()

        self.assertIn(before["id"], closed)
        self.assertEqual(after["status"], "closed")
        self.assertIsNotNone(after["fim"] )
        self.assertAlmostEqual(float(after["duracao"] or 0), stored_duration, delta=0.01)

    def test_close_interrupted_closes_in_memory_machine_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            test_connect, cliente_id, unidade_id, camera_id, monitor_id = self.make_context(temp_dir)
            engine = self.make_engine(cliente_id, unidade_id, camera_id, monitor_id)
            frame = np.zeros((80, 120, 3), dtype=np.uint8)
            now = time.monotonic()
            with patch("app.machine_monitoring.connect", test_connect), patch("app.alerts.connect", test_connect), patch("app.machine_monitoring.save_machine_evidence", return_value=(None, None)):
                engine.state.state = "STOPPED"
                engine.state.state_since = now - 5.0
                engine.state.confidence = 0.9
                engine._open_event(now, frame, "machine_stoppage")
                engine.close_interrupted()
            with test_connect() as connection:
                row = connection.execute("SELECT status FROM eventos WHERE tipo = 'machine_stoppage'").fetchone()

        self.assertEqual(row["status"], "closed")

    def test_machine_stoppage_duration_uses_condition_start_not_new_state_start(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            test_connect, cliente_id, unidade_id, camera_id, monitor_id = self.make_context(temp_dir)
            engine = self.make_engine(cliente_id, unidade_id, camera_id, monitor_id)
            frame = np.zeros((80, 120, 3), dtype=np.uint8)
            stopped_started = 1000.0
            opened_at = 1002.0
            closed_at = 1012.5
            with patch("app.machine_monitoring.connect", test_connect), patch("app.alerts.connect", test_connect), patch("app.machine_monitoring.save_machine_evidence", return_value=(None, None)):
                engine.state.state = "STOPPED"
                engine.state.state_since = stopped_started
                engine.state.confidence = 0.9
                engine._open_event(opened_at, frame, "machine_stoppage")
                engine.state.state = "ACTIVE"
                engine.state.state_since = closed_at
                engine._close_event_type("machine_stoppage", closed_at)
            with test_connect() as connection:
                event = connection.execute("SELECT duracao FROM eventos WHERE tipo = 'machine_stoppage'").fetchone()

        self.assertIsNotNone(event)
        self.assertAlmostEqual(event["duracao"], 12.5, delta=0.2)

    def test_active_without_operator_uses_single_open_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            test_connect, cliente_id, unidade_id, camera_id, monitor_id = self.make_context(temp_dir)
            engine = self.make_engine(cliente_id, unidade_id, camera_id, monitor_id)
            frame = np.zeros((80, 120, 3), dtype=np.uint8)
            now = time.monotonic()
            with patch("app.machine_monitoring.connect", test_connect), patch("app.alerts.connect", test_connect), patch("app.machine_monitoring.save_machine_evidence", return_value=(None, None)):
                engine.state.state = "ACTIVE"
                engine.state.state_since = now - 30.0
                engine.state.operator_present = False
                engine.state.operator_absence_confirmed = True
                engine._evaluate_official_events(now, frame)
                engine._evaluate_official_events(now + 0.2, frame)
                engine._evaluate_official_events(now + 0.4, frame)
                engine.state.operator_present = True
                engine._evaluate_official_events(now + 2.0, frame)
            with test_connect() as connection:
                rows = connection.execute("SELECT tipo, status FROM eventos WHERE tipo = 'machine_running_without_operator'").fetchall()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "closed")

    def test_active_with_operator_is_normal_without_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            test_connect, cliente_id, unidade_id, camera_id, monitor_id = self.make_context(temp_dir)
            engine = self.make_engine(cliente_id, unidade_id, camera_id, monitor_id)
            frame = np.zeros((80, 120, 3), dtype=np.uint8)
            now = time.monotonic()
            with patch("app.machine_monitoring.connect", test_connect), patch("app.alerts.connect", test_connect), patch("app.machine_monitoring.save_machine_evidence", return_value=(None, None)):
                engine.state.state = "ACTIVE"
                engine.state.state_since = now - 10.0
                engine.state.operator_present = True
                engine._evaluate_official_events(now, frame)
                engine._evaluate_official_events(now + 6.0, frame)
            with test_connect() as connection:
                events = connection.execute("SELECT COUNT(*) AS total FROM eventos").fetchone()["total"]
                outbox = connection.execute("SELECT COUNT(*) AS total FROM sync_outbox").fetchone()["total"]

        self.assertEqual(events, 0)
        self.assertEqual(outbox, 0)

    def test_short_detector_loss_keeps_operator_present_during_grace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _test_connect, cliente_id, unidade_id, camera_id, monitor_id = self.make_context(temp_dir)
            engine = self.make_engine(cliente_id, unidade_id, camera_id, monitor_id)
            engine.config.operator_presence_grace_seconds = 10.0
            engine.config.operator_polygon = [
                AreaPoint(0.0, 0.0),
                AreaPoint(0.25, 0.0),
                AreaPoint(0.25, 1.0),
                AreaPoint(0.0, 1.0),
            ]
            frame = np.zeros((100, 100, 3), dtype=np.uint8)
            detection = Detection(5, 20, 15, 70, 0.91, track_id=7)

            engine._update_operator(frame, [detection], dt=0.1, now=100.0)
            engine._update_operator(frame, [], dt=1.0, now=105.0)

        self.assertTrue(engine.state.operator_present)
        self.assertFalse(engine.state.raw_operator_present)
        self.assertIn("graça temporal", engine.state.operator_presence_reason)

    def test_operation_area_presence_survives_leaving_small_operator_zone(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _test_connect, cliente_id, unidade_id, camera_id, monitor_id = self.make_context(temp_dir)
            engine = self.make_engine(cliente_id, unidade_id, camera_id, monitor_id)
            engine.config.presence_scope = "OPERATION_AREA"
            engine.config.operation_polygon = [
                AreaPoint(0.0, 0.0),
                AreaPoint(1.0, 0.0),
                AreaPoint(1.0, 1.0),
                AreaPoint(0.0, 1.0),
            ]
            frame = np.zeros((100, 100, 3), dtype=np.uint8)
            outside_operator_zone_inside_operation = Detection(65, 20, 75, 70, 0.88, track_id=8)

            engine._update_operator(frame, [outside_operator_zone_inside_operation], dt=0.1, now=100.0)

        self.assertTrue(engine.state.operator_present)
        self.assertTrue(engine.state.raw_operator_present)

    def test_active_machine_sustained_absence_opens_event_after_grace_and_tolerance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            test_connect, cliente_id, unidade_id, camera_id, monitor_id = self.make_context(temp_dir)
            engine = self.make_engine(cliente_id, unidade_id, camera_id, monitor_id)
            engine.config.operator_presence_grace_seconds = 1.0
            frame = np.zeros((80, 120, 3), dtype=np.uint8)
            now = time.monotonic()
            with patch("app.machine_monitoring.connect", test_connect), patch("app.alerts.connect", test_connect), patch("app.machine_monitoring.save_machine_evidence", return_value=(None, None)):
                engine.state.state = "ACTIVE"
                engine.state.state_since = now - 30.0
                engine.state.confidence = 0.9
                engine.state.last_operator_seen_at = now - 2.0
                engine.state.operator_present = False
                engine.state.operator_absence_confirmed = True
                engine._evaluate_official_events(now, frame)
                engine._evaluate_official_events(now + 0.2, frame)
            with test_connect() as connection:
                rows = connection.execute("SELECT tipo, status FROM eventos WHERE tipo = 'machine_running_without_operator'").fetchall()

        self.assertEqual(len(rows), 1)

    def test_absence_is_unknown_during_initial_presence_warmup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _test_connect, cliente_id, unidade_id, camera_id, monitor_id = self.make_context(temp_dir)
            engine = self.make_engine(cliente_id, unidade_id, camera_id, monitor_id)
            engine.config.operator_presence_grace_seconds = 10.0
            frame = np.zeros((100, 100, 3), dtype=np.uint8)

            engine._update_operator(frame, [], dt=0.1, now=100.0)
            engine._update_operator(frame, [], dt=1.0, now=105.0)

        self.assertFalse(engine.state.operator_present)
        self.assertFalse(engine.state.operator_absence_confirmed)
        self.assertIn("presença ainda desconhecida", engine.state.operator_presence_reason)

    def test_machine_absence_event_requires_confirmed_absence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            test_connect, cliente_id, unidade_id, camera_id, monitor_id = self.make_context(temp_dir)
            engine = self.make_engine(cliente_id, unidade_id, camera_id, monitor_id)
            frame = np.zeros((80, 120, 3), dtype=np.uint8)
            now = time.monotonic()
            with patch("app.machine_monitoring.connect", test_connect), patch("app.alerts.connect", test_connect), patch("app.machine_monitoring.save_machine_evidence", return_value=(None, None)):
                engine.state.state = "ACTIVE"
                engine.state.state_since = now - 30.0
                engine.state.operator_present = False
                engine.state.operator_absence_confirmed = False
                engine._evaluate_official_events(now, frame)
                engine._evaluate_official_events(now + 10.0, frame)
            with test_connect() as connection:
                total = connection.execute("SELECT COUNT(*) AS total FROM eventos WHERE tipo = 'machine_running_without_operator'").fetchone()["total"]

        self.assertEqual(total, 0)

    def test_running_without_operator_event_evidence_outbox_and_alert(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict("os.environ", {"CAMPEX_EMAIL_MODE": "console", "CAMPEX_DIRECT_EVENT_EMAILS": "true"}):
            test_connect, cliente_id, unidade_id, camera_id, monitor_id = self.make_context(temp_dir)
            engine = self.make_engine(cliente_id, unidade_id, camera_id, monitor_id)
            frame = np.zeros((80, 120, 3), dtype=np.uint8)
            now = time.monotonic()
            with patch("app.machine_monitoring.connect", test_connect), patch("app.alerts.connect", test_connect), patch("app.machine_monitoring.save_machine_evidence", return_value=("data/evidence/running_without_operator.jpg", None)), patch("builtins.print"):
                with test_connect() as connection:
                    criar_alert_recipient(connection, "Operacao", "operacao@example.com", camera_id=camera_id, cliente_id=cliente_id, event_types=["machine_running_without_operator"])
                engine.state.state = "ACTIVE"
                engine.state.state_since = now - 20.0
                engine.state.operator_present = False
                engine.state.operator_absence_confirmed = True
                engine._evaluate_official_events(now, frame)
                engine._evaluate_official_events(now + 0.2, frame)
                engine.state.operator_present = True
                engine._evaluate_official_events(now + 1.0, frame)
                deliveries = self.wait_for_deliveries(test_connect)
            with test_connect() as connection:
                events = connection.execute("SELECT tipo, status, duracao, midia_path, operator_present_start FROM eventos WHERE tipo = 'machine_running_without_operator'").fetchall()
                outbox = connection.execute("SELECT COUNT(*) AS total FROM sync_outbox").fetchone()["total"]

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["tipo"], "machine_running_without_operator")
        self.assertEqual(events[0]["status"], "closed")
        self.assertGreaterEqual(events[0]["duracao"], 0.1)
        self.assertEqual(events[0]["midia_path"], "data/evidence/running_without_operator.jpg")
        self.assertEqual(events[0]["operator_present_start"], 0)
        self.assertGreaterEqual(outbox, 1)
        self.assertGreaterEqual(len(deliveries), 1)
        self.assertTrue(all(delivery["status"] == "sent" for delivery in deliveries))

    def test_stopped_with_operator_event_evidence_outbox_and_alert(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict("os.environ", {"CAMPEX_EMAIL_MODE": "console", "CAMPEX_DIRECT_EVENT_EMAILS": "true"}):
            test_connect, cliente_id, unidade_id, camera_id, monitor_id = self.make_context(temp_dir)
            engine = self.make_engine(cliente_id, unidade_id, camera_id, monitor_id)
            frame = np.zeros((80, 120, 3), dtype=np.uint8)
            now = time.monotonic()
            with patch("app.machine_monitoring.connect", test_connect), patch("app.alerts.connect", test_connect), patch("app.machine_monitoring.save_machine_evidence", return_value=("data/evidence/stopped_with_operator.jpg", None)), patch("builtins.print"):
                with test_connect() as connection:
                    criar_alert_recipient(connection, "Manutencao", "manutencao@example.com", camera_id=camera_id, cliente_id=cliente_id, event_types=["machine_stopped_with_operator"])
                engine.state.state = "STOPPED"
                engine.state.state_since = now - 20.0
                engine.state.operator_present = True
                engine._evaluate_official_events(now, frame)
                engine._evaluate_official_events(now + 0.2, frame)
                engine.state.state = "ACTIVE"
                engine._evaluate_official_events(now + 1.0, frame)
                deliveries = self.wait_for_deliveries(test_connect)
            with test_connect() as connection:
                events = connection.execute("SELECT tipo, status, duracao, midia_path, operator_present_start FROM eventos WHERE tipo = 'machine_stopped_with_operator'").fetchall()
                outbox = connection.execute("SELECT COUNT(*) AS total FROM sync_outbox").fetchone()["total"]

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["tipo"], "machine_stopped_with_operator")
        self.assertEqual(events[0]["status"], "closed")
        self.assertGreaterEqual(events[0]["duracao"], 0.1)
        self.assertEqual(events[0]["midia_path"], "data/evidence/stopped_with_operator.jpg")
        self.assertEqual(events[0]["operator_present_start"], 1)
        self.assertGreaterEqual(outbox, 1)
        self.assertGreaterEqual(len(deliveries), 1)
        self.assertTrue(all(delivery["status"] == "sent" for delivery in deliveries))

    def test_replay_metrics_compare_annotations_and_detected_states(self) -> None:
        metrics = evaluate_state_samples(
            [
                {"start": 0, "end": 10, "machine_state": "ACTIVE", "operator_present": True},
                {"start": 10, "end": 20, "machine_state": "STOPPED", "operator_present": True},
            ],
            [
                {"second": 1, "machine_state": "ACTIVE", "confidence": 0.8},
                {"second": 11, "machine_state": "STOPPED", "confidence": 0.9},
                {"second": 12, "machine_state": "ACTIVE", "confidence": 0.7},
            ],
        )

        self.assertEqual(metrics["samples"], 3)
        self.assertEqual(metrics["tempo_correto_percentual"], 66.67)
        self.assertEqual(metrics["transicoes_anotadas"], 1)
        self.assertGreater(metrics["confianca_media"], 0)

    def test_observation_engine_builds_central_frame_observation(self) -> None:
        engine = ObservationEngine("cam_1")

        observation = engine.build(
            machine_id="mach_1",
            machine_state="ACTIVE",
            machine_activity_score=28.5,
            machine_confidence=0.87,
            operator_present=True,
            zone_states=[
                {"tipo": "operator_zone", "pessoas_dentro": 1},
                {"tipo": "restricted_zone", "pessoas_dentro": 0},
                {"tipo": "work_area", "pessoas_dentro": 2},
            ],
        )

        self.assertEqual(observation["camera_id"], "cam_1")
        self.assertEqual(observation["machine_id"], "mach_1")
        self.assertEqual(observation["machine_state"], "ACTIVE")
        self.assertEqual(observation["people_in_operator_zone"], 1)
        self.assertEqual(observation["people_in_restricted_zone"], 0)
        self.assertEqual(observation["people_in_work_area"], 2)
        self.assertIn("seconds_in_machine_state", observation)


if __name__ == "__main__":
    unittest.main()
