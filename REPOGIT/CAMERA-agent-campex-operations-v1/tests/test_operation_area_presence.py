from __future__ import annotations

import numpy as np

from app.database import init_db
from app.machine_monitoring import MachineMonitorConfig, MachineMonitorEngine
from app.models import criar_machine_monitor, obter_machine_monitor
from app.person_detection import CentroidTracker, Detection
from app.restricted_area import AreaPoint


def _polygon(x1: float, y1: float, x2: float, y2: float) -> list[AreaPoint]:
    return [
        AreaPoint(x1, y1),
        AreaPoint(x2, y1),
        AreaPoint(x2, y2),
        AreaPoint(x1, y2),
    ]


def _engine(*, presence_scope: str = "OPERATOR_ZONE", operation_polygon: list[AreaPoint] | None = None) -> MachineMonitorEngine:
    config = MachineMonitorConfig(
        id="mach_a6",
        client_id="cli_dev",
        unit_id="unit_dev",
        camera_id="cam_a6",
        nome="A6",
        machine_polygon=_polygon(0.1, 0.1, 0.9, 0.9),
        operator_polygon=_polygon(0.1, 0.1, 0.3, 0.4),
        operation_polygon=operation_polygon,
        presence_scope=presence_scope,
    )
    return MachineMonitorEngine(config)


def _frame() -> np.ndarray:
    return np.zeros((100, 100, 3), dtype=np.uint8)


def _person_with_foot_at(x: float, y: float, *, track_id: int = 1, confidence: float = 0.82) -> Detection:
    foot_x = int(x * 100)
    foot_y = int(y * 100)
    return Detection(
        x1=max(0, foot_x - 5),
        y1=max(0, foot_y - 20),
        x2=min(99, foot_x + 5),
        y2=min(99, foot_y),
        confidence=confidence,
        class_name="person",
        track_id=track_id,
    )


def test_person_in_operation_area_is_present_even_outside_operator_zone() -> None:
    engine = _engine(
        presence_scope="OPERATION_AREA",
        operation_polygon=_polygon(0.1, 0.1, 0.9, 0.9),
    )

    engine._update_operator(_frame(), [_person_with_foot_at(0.7, 0.7)], dt=1.0)

    assert engine.state.operator_present is True
    assert engine.state.max_people == 1
    assert engine.state.track_ids == {1}


def test_default_operator_zone_compatibility_keeps_narrow_presence_scope() -> None:
    engine = _engine(operation_polygon=_polygon(0.1, 0.1, 0.9, 0.9))

    engine._update_operator(_frame(), [_person_with_foot_at(0.7, 0.7)], dt=1.0)

    assert engine.state.operator_present is False


def test_short_yolo_loss_remains_present_when_tracker_keeps_recent_person_in_operation_area() -> None:
    tracker = CentroidTracker(grace_seconds=2.0, unknown_seconds=5.0)
    tracker.update([_person_with_foot_at(0.7, 0.7)], now=100.0)
    tracker.update([], now=101.0)
    engine = _engine(
        presence_scope="OPERATION_AREA",
        operation_polygon=_polygon(0.1, 0.1, 0.9, 0.9),
    )

    engine._update_operator(_frame(), tracker.recent_detections(), dt=1.0)

    assert engine.state.operator_present is True
    assert engine.state.track_ids == {1}


def test_person_outside_whole_operation_area_is_absent_for_monitor() -> None:
    engine = _engine(
        presence_scope="OPERATION_AREA",
        operation_polygon=_polygon(0.1, 0.1, 0.6, 0.6),
    )

    engine._update_operator(_frame(), [_person_with_foot_at(0.8, 0.8)], dt=1.0)

    assert engine.state.operator_present is False


def test_invalid_presence_scope_falls_back_to_operator_zone() -> None:
    engine = _engine(
        presence_scope="warehouse",
        operation_polygon=_polygon(0.1, 0.1, 0.9, 0.9),
    )

    engine._update_operator(_frame(), [_person_with_foot_at(0.7, 0.7)], dt=1.0)

    assert engine.state.operator_present is False


def test_machine_monitor_persists_operation_area_presence_scope(tmp_path) -> None:
    import sqlite3

    db_path = tmp_path / "presence_scope.sqlite3"
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        init_db(connection)
        monitor_id = criar_machine_monitor(
            connection=connection,
            client_id="cli_dev",
            unit_id="unit_dev",
            camera_id="cam_a6",
            nome="A6",
            machine_polygon=[{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.1}, {"x": 0.9, "y": 0.9}],
            operator_polygon=[{"x": 0.1, "y": 0.1}, {"x": 0.3, "y": 0.1}, {"x": 0.3, "y": 0.4}],
            operation_polygon=[{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.1}, {"x": 0.9, "y": 0.9}],
            presence_scope="OPERATION_AREA",
        )

        monitor = obter_machine_monitor(connection, monitor_id)

        assert monitor is not None
        assert monitor["presence_scope"] == "OPERATION_AREA"
        assert monitor["operation_polygon"] == [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.1}, {"x": 0.9, "y": 0.9}]
    finally:
        connection.close()
