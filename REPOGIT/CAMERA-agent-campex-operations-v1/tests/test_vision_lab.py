from __future__ import annotations

import tempfile
import time
from pathlib import Path

import cv2
import numpy as np
from fastapi.testclient import TestClient
from unittest.mock import patch

from app.database import connect
from app.machine_monitoring import MachineMonitorEngine, config_from_dict
from app.models import listar_eventos_filtrados, listar_areas_camera, obter_machine_monitor
from app.person_detection import Detection
from tools.vision_lab import ActivityTelemetry, LAB_CAMERA_ID, create_lab_app, ensure_lab_database


def _poly(x1=0.1, y1=0.1, x2=0.9, y2=0.9):
    return [{"x": x1, "y": y1}, {"x": x2, "y": y1}, {"x": x2, "y": y2}, {"x": x1, "y": y2}]


def test_vision_lab_uses_isolated_sqlite_and_persists_zone():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "vision_lab.db"
        app = create_lab_app(start_worker=False, db_path=db_path)
        client = TestClient(app)

        response = client.post(
            "/zones",
            json={"name": "DEV Maquina", "area_type": "machine_region", "polygon": _poly()},
        )
        assert response.status_code == 200

        with connect(db_path) as connection:
            areas = listar_areas_camera(connection, LAB_CAMERA_ID)
        assert len(areas) == 1
        assert areas[0]["camera_id"] == LAB_CAMERA_ID
        assert db_path.exists()

        restarted = create_lab_app(start_worker=False, db_path=db_path)
        restarted_client = TestClient(restarted)
        status = restarted_client.get("/status").json()
        assert len(status["areas"]) == 1
        assert status["areas"][0]["nome"] == "DEV Maquina"


def test_vision_lab_rejects_invalid_polygon():
    with tempfile.TemporaryDirectory() as tmp:
        client = TestClient(create_lab_app(start_worker=False, db_path=Path(tmp) / "lab.db"))
        response = client.post(
            "/zones",
            json={"name": "Invalida", "area_type": "restricted_area", "polygon": [{"x": 0.1, "y": 0.1}]},
        )
        assert response.status_code == 400


def test_activity_score_is_available_with_machine_region_only():
    telemetry = ActivityTelemetry()
    polygon = _poly()
    frame_a = np.zeros((120, 160, 3), dtype=np.uint8)
    frame_b = frame_a.copy()
    cv2.rectangle(frame_b, (40, 40), (90, 90), (255, 255, 255), -1)

    telemetry.update(frame_a, polygon)
    telemetry.update(frame_b, polygon)
    snapshot = telemetry.snapshot()

    assert snapshot["raw_activity_score"] is not None
    assert snapshot["smoothed_activity_score"] is not None
    assert snapshot["changed_pixels"] > 0
    assert snapshot["roi_size"] == {"width": 128, "height": 96}
    assert snapshot["machine_region_found"] is True
    assert snapshot["previous_frame_available"] is True
    assert snapshot["analysis_status"] == "ANALYZING"
    assert snapshot["roi_width"] == 128
    assert snapshot["roi_height"] == 96
    assert snapshot["score_reason"] == "score calculado"


def test_activity_score_reports_waiting_for_machine_region():
    telemetry = ActivityTelemetry()
    frame = np.zeros((120, 160, 3), dtype=np.uint8)

    telemetry.update(frame, None)
    snapshot = telemetry.snapshot()

    assert snapshot["machine_region_found"] is False
    assert snapshot["analysis_status"] == "WAITING_FOR_MACHINE_REGION"
    assert snapshot["score_reason"] == "machine_region ausente"
    assert snapshot["frames_received"] == 1
    assert snapshot["frames_analyzed"] == 0


def test_vision_lab_test_alert_creates_delivery_without_operational_event(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setenv("CAMPEX_EMAIL_MODE", "console")
        monkeypatch.setenv("CAMPEX_VISION_LAB_RECIPIENT", "felipe@example.com")
        client = TestClient(create_lab_app(start_worker=False, db_path=Path(tmp) / "lab.db"))
        response = client.post("/alerts/test")

        assert response.status_code == 200
        body = response.json()
        assert body["delivery_id"].startswith("del_")
        assert body["recipient"] == "felipe@example.com"
        assert body["initial_status"] in {"pending", "sent", "failed"}

        delivery = client.get(f"/alerts/test/{body['delivery_id']}").json()
        assert delivery["recipient"] == "felipe@example.com"
        assert delivery["status"] in {"queued", "sent", "failed"}

        status = client.get("/status").json()
        assert status["last_alert"]["id"] == body["delivery_id"]
        assert status["events"] == []


def test_vision_lab_smtp_without_recipient_refuses_delivery(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setenv("CAMPEX_EMAIL_MODE", "smtp")
        monkeypatch.delenv("CAMPEX_VISION_LAB_RECIPIENT", raising=False)
        monkeypatch.delenv("CAMPEX_VISION_LAB_ALERT_EMAIL", raising=False)
        client = TestClient(create_lab_app(start_worker=False, db_path=Path(tmp) / "lab.db"))

        response = client.post("/alerts/test")

        assert response.status_code == 400
        assert "Configure o e-mail desta sessao" in response.json()["detail"]
        status = client.get("/status").json()
        assert status["last_alert"] is None


def test_vision_lab_email_session_config_is_memory_only_and_masks_password(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setenv("CAMPEX_EMAIL_MODE", "smtp")
        client = TestClient(create_lab_app(start_worker=False, db_path=Path(tmp) / "lab.db"))
        payload = {
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587,
            "smtp_user": "felipe@gmail.com",
            "smtp_password": "senha-de-app",
            "email_from": "felipe@gmail.com",
            "recipient": "destino@gmail.com",
            "use_tls": True,
        }

        response = client.post("/lab-email/session-config", json=payload)

        assert response.status_code == 200
        body = response.json()
        assert body["configured"] is True
        assert body["smtp_host"] == "smtp.gmail.com"
        assert body["smtp_user"] == "f***@gmail.com"
        assert body["recipient"] == "d***@gmail.com"
        assert "smtp_password" not in body
        assert "senha-de-app" not in response.text

        status = client.get("/lab-email/session-status").json()
        assert status["configured"] is True
        assert "smtp_password" not in status
        assert "senha-de-app" not in str(status)

        cleared = client.delete("/lab-email/session-config")
        assert cleared.status_code == 200
        assert client.get("/lab-email/session-status").json() == {"configured": False}


def test_vision_lab_email_session_rejects_invalid_payload(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setenv("CAMPEX_EMAIL_MODE", "smtp")
        client = TestClient(create_lab_app(start_worker=False, db_path=Path(tmp) / "lab.db"))
        response = client.post(
            "/lab-email/session-config",
            json={
                "smtp_host": "smtp.gmail.com",
                "smtp_port": 587,
                "smtp_user": "felipe@gmail.com",
                "smtp_password": "",
                "email_from": "felipe@gmail.com",
                "recipient": "destino@gmail.com",
                "use_tls": True,
            },
        )

        assert response.status_code == 400
        assert "Senha de app" in response.json()["detail"]


def test_vision_lab_updates_old_dev_recipient_from_environment(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "lab.db"
        monkeypatch.setenv("CAMPEX_EMAIL_MODE", "console")
        monkeypatch.setenv("CAMPEX_VISION_LAB_RECIPIENT", "novo@example.com")
        ensure_lab_database(db_path)
        with connect(db_path) as connection:
            connection.execute(
                """
                INSERT INTO alert_recipients (id, cliente_id, nome, email, event_types, ativo, severidade_minima)
                VALUES ('rec_old', 'dev_vision_lab_client', 'DEV Vision Lab Recipient', 'felipe.local@campex.dev', '[]', 1, 'low')
                """
            )
            connection.commit()

        client = TestClient(create_lab_app(start_worker=False, db_path=db_path))
        response = client.post("/alerts/test")

        assert response.status_code == 200
        assert response.json()["recipient"] == "novo@example.com"
        with connect(db_path) as connection:
            rows = connection.execute("SELECT email FROM alert_recipients WHERE cliente_id = 'dev_vision_lab_client'").fetchall()
        emails = [row["email"] for row in rows]
        assert "felipe.local@campex.dev" not in emails


def test_vision_lab_report_is_written():
    with tempfile.TemporaryDirectory() as tmp:
        client = TestClient(create_lab_app(start_worker=False, db_path=Path(tmp) / "lab.db"))
        response = client.post("/report")

        assert response.status_code == 200
        path = Path(response.json()["path"])
        assert path.exists()
        assert response.json()["report"]["database"].endswith("lab.db")


def test_vision_lab_machine_stoppage_creates_event_and_outbox_without_main_db():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "vision_lab.db"
        ensure_lab_database(db_path)
        with connect(db_path) as connection:
            connection.execute(
                """
                INSERT INTO monitored_areas (id, cliente_id, unidade_id, camera_id, nome, tipo, pontos_json, metadata_json, ativa)
                VALUES ('area_machine', 'dev_vision_lab_client', 'dev_vision_lab_unit', ?, 'Maquina', 'machine_region', ?, '{}', 1)
                """,
                (LAB_CAMERA_ID, '[{"x":0.1,"y":0.1},{"x":0.9,"y":0.1},{"x":0.9,"y":0.9},{"x":0.1,"y":0.9}]'),
            )
            connection.execute(
                """
                INSERT INTO monitored_areas (id, cliente_id, unidade_id, camera_id, nome, tipo, pontos_json, metadata_json, ativa)
                VALUES ('area_operator', 'dev_vision_lab_client', 'dev_vision_lab_unit', ?, 'Operador', 'workstation', ?, '{}', 1)
                """,
                (LAB_CAMERA_ID, '[{"x":0.1,"y":0.1},{"x":0.9,"y":0.1},{"x":0.9,"y":0.9},{"x":0.1,"y":0.9}]'),
            )
            connection.execute(
                """
                INSERT INTO machine_monitors (
                    id, client_id, unit_id, camera_id, nome, machine_polygon_json, operator_polygon_json,
                    stop_seconds, recovery_seconds, active_baseline, stopped_baseline,
                    active_noise, stopped_noise, motion_threshold
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0.05, 0.05, 20, 0, 1, 1, 10)
                """,
                (
                    "mach_lab",
                    "dev_vision_lab_client",
                    "dev_vision_lab_unit",
                    LAB_CAMERA_ID,
                    "Ventilador",
                    '[{"x":0.1,"y":0.1},{"x":0.9,"y":0.1},{"x":0.9,"y":0.9},{"x":0.1,"y":0.9}]',
                    '[{"x":0.1,"y":0.1},{"x":0.9,"y":0.1},{"x":0.9,"y":0.9},{"x":0.1,"y":0.9}]',
                ),
            )
            connection.commit()
            monitor = obter_machine_monitor(connection, "mach_lab")
            engine = MachineMonitorEngine(config_from_dict(monitor))
            engine.smoothing_seconds = 0.01
            engine.analysis_fps = 100

        blank = np.zeros((120, 160, 3), dtype=np.uint8)
        moving = blank.copy()
        cv2.rectangle(moving, (30, 30), (90, 90), (255, 255, 255), -1)
        moving_next = blank.copy()
        cv2.rectangle(moving_next, (45, 30), (105, 90), (255, 255, 255), -1)
        detection = Detection(20, 20, 80, 100, 0.9, "person", 1)

        with patch("app.machine_monitoring.connect", lambda: connect(db_path)):
            for frame in (blank, moving, moving_next, moving):
                engine.update(frame, [detection])
                time.sleep(0.03)
            for _ in range(4):
                engine.update(blank, [])
                time.sleep(0.06)

        with connect(db_path) as connection:
            events = listar_eventos_filtrados(connection, camera_id=LAB_CAMERA_ID, tipo="machine_stoppage")
            outbox_total = connection.execute("SELECT COUNT(*) AS total FROM sync_outbox").fetchone()["total"]

        assert len(events) == 1
        assert events[0]["event_uuid"]
        assert outbox_total == 1
