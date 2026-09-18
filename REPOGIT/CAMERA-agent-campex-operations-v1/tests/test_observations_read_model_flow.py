from __future__ import annotations

import json
import sqlite3
from datetime import timedelta

from app.database import init_db
from app.machine_monitoring import MachineMonitorConfig, MachineMonitorEngine
from app.models import registrar_operational_sample
from app.operational_read_model import ReadModelFilters, daily_report, operational_data, parse_datetime
from app.restricted_area import AreaPoint


def _connect(path):
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def _observation(observation_type: str, value: str) -> dict[str, object]:
    return {
        "observation_id": f"obs_{observation_type}",
        "observation_type": observation_type,
        "camera_id": "cam_a6",
        "cliente_id": "cli_a6",
        "unidade_id": "unit_a6",
        "timestamp": "2026-08-10T12:00:00+00:00",
        "value": value,
        "confidence": 0.88,
        "source": "runtime",
        "data_quality": "observed",
        "metadata": {},
    }


def test_read_model_keeps_active_present_when_inference_fps_is_missing_but_observations_are_valid(tmp_path) -> None:
    db_path = tmp_path / "read_model_observations.sqlite3"
    with _connect(db_path) as connection:
        init_db(connection)
        registrar_operational_sample(
            connection,
            sample_uuid="sample_valid_observations",
            tenant_id="cli_a6",
            unit_id="unit_a6",
            camera_id="cam_a6",
            machine_id="mach_a6",
            machine_state="ACTIVE",
            operator_present=True,
            activity_score=42.0,
            confidence=0.9,
            capture_fps=15.0,
            inference_fps=None,
            frames_analyzed=10,
            camera_online=True,
            sample_at="2026-08-10T12:00:00+00:00",
            metadata={
                "canonical_observations": [
                    _observation("machine_activity", "ACTIVE"),
                    _observation("person_presence", "PRESENT"),
                    _observation("zone_occupancy", "PRESENT"),
                ]
            },
        )

        data = operational_data(
            connection,
            ReadModelFilters(
                cliente_id="cli_a6",
                start=parse_datetime("2026-08-10T12:00:00+00:00"),
                end=parse_datetime("2026-08-10T12:00:20+00:00"),
            ),
        )

    assert data["machine_data"]["active_seconds"] == 20.0
    assert data["machine_data"]["unknown_seconds"] == 0.0
    assert data["human_operation_data"]["presence_seconds"] == 20.0
    assert data["human_operation_data"]["unknown_seconds"] == 0.0
    assert data["coverage"]["status"] == "GOOD"


def test_runtime_persisted_observation_is_recovered_by_read_model(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "runtime_observations.sqlite3"

    def isolated_connect(path=None):
        return _connect(db_path)

    monkeypatch.setattr("app.machine_monitoring.connect", isolated_connect)
    with _connect(db_path) as connection:
        init_db(connection)

    config = MachineMonitorConfig(
        id="mach_a6",
        client_id="cli_a6",
        unit_id="unit_a6",
        camera_id="cam_a6",
        nome="A6",
        machine_polygon=[AreaPoint(0.1, 0.1), AreaPoint(0.9, 0.1), AreaPoint(0.9, 0.9)],
        operator_polygon=[AreaPoint(0.1, 0.1), AreaPoint(0.9, 0.1), AreaPoint(0.9, 0.9)],
        ativo=True,
    )
    engine = MachineMonitorEngine(config)
    engine.state.state = "ACTIVE"
    engine.state.smoothed_motion = 45.0
    engine.state.raw_activity_score = 46.0
    engine.state.confidence = 0.91
    engine.state.operator_present = True
    engine.state.analysis_status = "ANALYZING"
    engine.state.signal_quality = "READY"
    engine.state.frames_analyzed = 12

    engine._persist_state(changed=True)

    with _connect(db_path) as connection:
        row = connection.execute("SELECT * FROM operational_samples WHERE machine_id = ?", ("mach_a6",)).fetchone()
        assert row is not None
        metadata = json.loads(row["metadata_json"])
        observations = metadata["canonical_observations"]
        types = {item["observation_type"] for item in observations}
        assert {"machine_activity", "person_presence", "zone_occupancy"}.issubset(types)

        sample_at = parse_datetime(row["sample_at"])
        data = operational_data(
            connection,
            ReadModelFilters(
                cliente_id="cli_a6",
                start=sample_at,
                end=sample_at + timedelta(seconds=20),
            ),
        )
        report = daily_report(
            connection,
            ReadModelFilters(
                cliente_id="cli_a6",
                start=sample_at,
                end=sample_at + timedelta(seconds=20),
            ),
        )

    assert data["machine_data"]["active_seconds"] == 20.0
    assert data["human_operation_data"]["presence_seconds"] == 20.0
    assert data["machine_data"]["traceability"]["observation_types"] == ["machine_activity"]
    assert report["summary"]["machines"]["active_seconds"] == 20.0
    assert report["summary"]["human_operation"]["presence_seconds"] == 20.0
