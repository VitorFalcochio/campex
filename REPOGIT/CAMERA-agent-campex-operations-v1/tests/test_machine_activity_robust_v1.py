from __future__ import annotations

import numpy as np

from app.machine_monitoring import (
    MachineMonitorConfig,
    MachineMonitorEngine,
    baseline_stats,
    machine_activity_score,
    machine_calibration_separation,
)
from app.observation_engine import machine_activity_observation
from app.restricted_area import AreaPoint


def config(
    *,
    active: float | None = 30.0,
    stopped: float | None = 2.0,
    active_noise: float | None = 1.0,
    stopped_noise: float | None = 0.5,
) -> MachineMonitorConfig:
    return MachineMonitorConfig(
        id="mach_a6",
        client_id="cli_1",
        unit_id="unit_1",
        camera_id="cam_a6",
        nome="A6",
        machine_polygon=[AreaPoint(0.1, 0.1), AreaPoint(0.9, 0.1), AreaPoint(0.9, 0.9), AreaPoint(0.1, 0.9)],
        operator_polygon=[AreaPoint(0.0, 0.1), AreaPoint(0.05, 0.1), AreaPoint(0.05, 0.9), AreaPoint(0.0, 0.9)],
        stop_seconds=0.2,
        recovery_seconds=0.2,
        active_baseline=active,
        stopped_baseline=stopped,
        active_noise=active_noise,
        stopped_noise=stopped_noise,
    )


def classify_after_samples(engine: MachineMonitorEngine, values: list[float], start: float = 100.0) -> tuple[str, float, str]:
    engine.state.analysis_status = "ANALYZING"
    for index, value in enumerate(values):
        engine._record_activity_sample(start + index * 0.5, value)
    engine.state.smoothed_motion = float(values[-1])
    return engine._classify_state()


def test_active_calibration_uses_robust_baseline() -> None:
    baseline, noise = baseline_stats([28, 30, 31, 32, 200])

    assert baseline == 31.0
    assert noise > 0


def test_stopped_calibration_uses_multiple_samples() -> None:
    baseline, noise = baseline_stats([1.0, 1.2, 0.9, 1.1, 1.0])

    assert baseline == 1.0
    assert noise >= 0


def test_separable_calibration_marks_monitor_ready() -> None:
    active = {"median": 31, "mean": 31, "std": 1, "p10": 29, "p90": 33}
    stopped = {"median": 2, "mean": 2, "std": 0.5, "p10": 1, "p90": 3}

    separation = machine_calibration_separation(active, stopped)

    assert separation["result"] == "READY"
    assert separation["score"] > 3
    assert separation["threshold"] == 16.5


def test_close_active_and_stopped_signal_is_unknown() -> None:
    active = {"median": 5.28, "mean": 5.28, "std": 0.6, "p10": 4.8, "p90": 5.8}
    stopped = {"median": 5.26, "mean": 5.26, "std": 0.6, "p10": 4.7, "p90": 5.9}
    separation = machine_calibration_separation(active, stopped)
    engine = MachineMonitorEngine(config(active=5.28, stopped=5.26, active_noise=0.6, stopped_noise=0.6))

    state, confidence, reason = classify_after_samples(engine, [5.2, 5.3, 5.25])

    assert separation["result"] == "INSUFFICIENT_VISUAL_SIGNAL"
    assert state == "UNKNOWN"
    assert confidence == 0.0
    assert "separação visual suficiente" in reason


def test_invalid_roi_produces_unknown_not_stopped() -> None:
    engine = MachineMonitorEngine(config())
    engine.state.analysis_status = "INVALID_ROI"
    state, confidence, reason = engine._classify_state()

    assert state == "UNKNOWN"
    assert confidence == 0.0
    assert "região" in reason


def test_explicit_calibration_required_produces_unknown() -> None:
    engine = MachineMonitorEngine(config(active=None, stopped=None))
    engine.config.calibration_result = "CALIBRATION_REQUIRED"
    engine.state.analysis_status = "ANALYZING"
    engine.state.smoothed_motion = 50.0

    state, confidence, reason = engine._classify_state()

    assert state == "UNKNOWN"
    assert confidence == 0.0
    assert "calibração" in reason


def test_hysteresis_avoids_flapping_near_threshold() -> None:
    engine = MachineMonitorEngine(config())
    engine.state.state = "ACTIVE"
    state, confidence, reason = classify_after_samples(engine, [16.4, 16.6, 16.5])

    assert state == "ACTIVE"
    assert confidence == 0.55
    assert "histerese" in reason


def test_short_activity_drop_does_not_create_false_stopped() -> None:
    engine = MachineMonitorEngine(config())
    engine.state.state = "ACTIVE"
    engine._evaluate_official_events = lambda _now, _frame: None  # type: ignore[method-assign]
    engine._persist_state = lambda **_kwargs: None  # type: ignore[method-assign]
    engine.state.analysis_status = "ANALYZING"
    engine.state.smoothed_motion = 2.0
    engine._record_activity_sample(100.0, 31.0)
    engine._record_activity_sample(100.5, 2.0)

    engine._classify_and_transition(100.5, np.zeros((8, 8, 3), dtype=np.uint8))

    assert engine.state.state == "ACTIVE"
    assert engine.state.candidate_state == "STOPPED"


def test_short_activity_spike_does_not_create_false_active() -> None:
    engine = MachineMonitorEngine(config())
    engine.state.state = "STOPPED"
    engine._evaluate_official_events = lambda _now, _frame: None  # type: ignore[method-assign]
    engine._persist_state = lambda **_kwargs: None  # type: ignore[method-assign]
    engine.state.analysis_status = "ANALYZING"
    engine.state.smoothed_motion = 31.0
    engine._record_activity_sample(100.0, 2.0)
    engine._record_activity_sample(100.5, 31.0)

    engine._classify_and_transition(100.5, np.zeros((8, 8, 3), dtype=np.uint8))

    assert engine.state.state == "STOPPED"
    assert engine.state.candidate_state == "ACTIVE"


def test_camera_frame_unavailable_is_unknown() -> None:
    score, _previous, diagnostics = machine_activity_score(None, config().machine_polygon, None)  # type: ignore[arg-type]
    engine = MachineMonitorEngine(config())
    engine.state.analysis_status = diagnostics["analysis_status"]

    state, confidence, reason = engine._classify_state()

    assert score is None
    assert state == "UNKNOWN"
    assert confidence == 0.0
    assert "sensor" in reason


def test_restart_recovers_calibration_but_starts_unknown_until_window_fills() -> None:
    restarted = MachineMonitorEngine(config())
    restarted.state.analysis_status = "ANALYZING"
    restarted._record_activity_sample(100.0, 31.0)

    state, confidence, reason = restarted._classify_state()

    assert restarted.config.active_baseline == 30.0
    assert restarted.config.stopped_baseline == 2.0
    assert restarted.state.state == "UNKNOWN"
    assert state == "UNKNOWN"
    assert confidence == 0.0
    assert "amostras temporais insuficientes" in reason


def test_machine_activity_canonical_observation_contains_robust_metadata() -> None:
    observation = machine_activity_observation(
        camera_id="cam_a6",
        machine_id="mach_a6",
        state="ACTIVE",
        activity_score=29.5,
        confidence=0.82,
        cliente_id="cli_1",
        unidade_id="unit_1",
        metadata={
            "baseline_active": 30,
            "baseline_stopped": 2,
            "separability": 12.0,
            "samples_count": 4,
            "seconds_in_state": 8.5,
            "calibration_status": "READY",
        },
    ).to_dict()

    assert observation["observation_type"] == "machine_activity"
    assert observation["value"] == "ACTIVE"
    assert observation["data_quality"] == "observed"
    assert observation["metadata"]["separability"] == 12.0
    assert observation["metadata"]["samples_count"] == 4


def test_no_event_is_created_by_classification_alone() -> None:
    engine = MachineMonitorEngine(config())
    classify_after_samples(engine, [31, 30, 29])

    assert engine.state.active_events == {}

def test_localized_machine_motion_is_distinguishable_from_stopped() -> None:
    polygon = [
        AreaPoint(0.1, 0.1),
        AreaPoint(0.9, 0.1),
        AreaPoint(0.9, 0.9),
        AreaPoint(0.1, 0.9),
    ]

    base = np.zeros((120, 160, 3), dtype=np.uint8)

    active_a = base.copy()
    active_b = base.copy()

    # Movimento localizado: representa correia, fio, rolo, eixo,
    # peça ou outro componente que ocupa apenas parte da máquina.
    active_a[45:75, 65:69] = 255
    active_b[45:75, 79:83] = 255

    previous = None
    active_scores = []
    for frame in [active_a, active_b, active_a, active_b]:
        score, previous, diagnostics = machine_activity_score(frame, polygon, previous)
        if diagnostics["analysis_status"] == "ANALYZING" and score is not None:
            active_scores.append(score)

    previous = None
    stopped_scores = []
    for frame in [active_a, active_a, active_a, active_a]:
        score, previous, diagnostics = machine_activity_score(frame, polygon, previous)
        if diagnostics["analysis_status"] == "ANALYZING" and score is not None:
            stopped_scores.append(score)

    assert active_scores
    assert stopped_scores
    assert min(active_scores) > max(stopped_scores) + 1.0
