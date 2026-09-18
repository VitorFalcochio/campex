from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient

from app.api import api
from app.database import connect, init_db
from app.models import (
    criar_alert_recipient,
    criar_area_monitorada,
    criar_camera,
    criar_cliente,
    criar_unidade,
    listar_regras,
    listar_alert_deliveries,
    listar_areas_camera,
    listar_eventos_filtrados,
    registrar_operational_sample,
)
from app.people_zones import EVENT_CATALOG_V1, PeopleZonesEngine
from app.person_detection import Detection
from shared.schemas import now_iso


class PeopleZonesV1Test(unittest.TestCase):
    def make_context(self, temp_dir: str):
        db_path = Path(temp_dir) / "people-zones.sqlite3"

        def test_connect():
            return connect(db_path)

        with test_connect() as connection:
            init_db(connection)
            cliente_id = criar_cliente(connection, "Cliente")
            unidade_id = criar_unidade(connection, cliente_id, "Unidade")
            camera_id = criar_camera(connection, unidade_id, "Camera", cliente_id=cliente_id)
            criar_alert_recipient(
                connection,
                "Responsavel",
                "ops@example.com",
                True,
                cliente_id=cliente_id,
                event_types=["workstation_unattended", "restricted_zone_occupied"],
            )
        return test_connect, camera_id

    def add_operational_context(
        self,
        connection,
        camera_id: str,
        *,
        machine_state: str = "ACTIVE",
        person_presence: str = "UNKNOWN",
        lighting_state: str | None = None,
        operational_activity: str | None = None,
        camera_online: bool = True,
        data_quality: str = "observed",
        machine_id: str | None = None,
    ) -> None:
        observations = [
            {
                "observation_type": "machine_activity",
                "camera_id": camera_id,
                "value": machine_state,
                "confidence": 0.9 if machine_state != "UNKNOWN" else 0.0,
                "data_quality": data_quality if machine_state != "UNKNOWN" else "insufficient_data",
            },
            {
                "observation_type": "person_presence",
                "camera_id": camera_id,
                "value": person_presence,
                "confidence": 0.8 if person_presence != "UNKNOWN" else 0.0,
                "data_quality": data_quality if person_presence != "UNKNOWN" else "insufficient_data",
            },
        ]
        if lighting_state:
            observations.append(
                {
                    "observation_type": "lighting_state",
                    "camera_id": camera_id,
                    "value": lighting_state,
                    "confidence": 0.9,
                    "data_quality": data_quality,
                }
            )
        if operational_activity:
            observations.append(
                {
                    "observation_type": "operational_activity",
                    "camera_id": camera_id,
                    "value": operational_activity,
                    "confidence": 0.85,
                    "data_quality": "inferred",
                }
            )
        registrar_operational_sample(
            connection,
            sample_uuid=f"sample-{time.monotonic_ns()}",
            tenant_id="tenant",
            unit_id="unit",
            camera_id=camera_id,
            machine_id=machine_id,
            machine_state=machine_state,
            operator_present=None,
            activity_score=42.0 if machine_state == "ACTIVE" else 0.0,
            confidence=0.9 if machine_state != "UNKNOWN" else 0.0,
            capture_fps=15.0 if camera_online else 0.0,
            inference_fps=5.0 if data_quality != "sensor_unavailable" else 0.0,
            frames_analyzed=10 if data_quality != "sensor_unavailable" else 0,
            camera_online=camera_online,
            sample_at=now_iso(),
            metadata={"canonical_observations": observations},
        )

    def test_catalog_has_people_and_zones_v1_events(self) -> None:
        self.assertEqual(
            EVENT_CATALOG_V1,
            {
                "restricted_zone_occupied",
                "workstation_unattended",
                "minimum_staff_not_met",
                "shift_start_incomplete",
                "excessive_zone_dwell",
                "after_hours_presence",
            },
        )

    def test_four_workstations_are_persisted_with_normalized_points(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            test_connect, camera_id = self.make_context(temp_dir)
            with test_connect() as connection:
                for index in range(4):
                    criar_area_monitorada(
                        connection,
                        camera_id,
                        f"Posto {index + 1}",
                        [{"x": 0.1, "y": 0.1}, {"x": 0.3, "y": 0.1}, {"x": 0.3, "y": 0.3}],
                        tipo="workstation",
                        absence_tolerance_seconds=0,
                        collaborator_name=f"Colaborador {index + 1}",
                    )
                areas = listar_areas_camera(connection, camera_id)

        self.assertEqual(len([area for area in areas if area["tipo"] == "workstation"]), 4)
        self.assertTrue(all(0 <= point["x"] <= 1 and 0 <= point["y"] <= 1 for area in areas for point in area["pontos"]))
        self.assertNotIn("rtsp://", str(areas))

    def test_workstation_unattended_is_context_only_and_does_not_create_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            test_connect, camera_id = self.make_context(temp_dir)
            evidence_root = Path(temp_dir) / "evidence"

            with test_connect() as connection:
                criar_area_monitorada(
                    connection,
                    camera_id,
                    "Posto 1",
                    [{"x": 0.2, "y": 0.2}, {"x": 0.8, "y": 0.2}, {"x": 0.8, "y": 0.8}, {"x": 0.2, "y": 0.8}],
                    tipo="workstation",
                    absence_tolerance_seconds=0,
                )
                self.add_operational_context(connection, camera_id, machine_state="ACTIVE")
                areas = listar_areas_camera(connection, camera_id)

            frame = np.zeros((100, 100, 3), dtype=np.uint8)
            engine = PeopleZonesEngine(camera_id, evidence_root=evidence_root)

            with patch("app.people_zones.connect", test_connect):
                engine.update(areas, [], frame)
                engine.update(areas, [], frame)

                with test_connect() as connection:
                    events = listar_eventos_filtrados(
                        connection,
                        tipo="workstation_unattended",
                    )

            self.assertEqual(events, [])

    def test_people_zones_page_and_summary_are_served(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            test_connect, camera_id = self.make_context(temp_dir)
            with test_connect() as connection:
                criar_area_monitorada(
                    connection,
                    camera_id,
                    "Posto 1",
                    [{"x": 0.1, "y": 0.1}, {"x": 0.4, "y": 0.1}, {"x": 0.4, "y": 0.4}],
                    tipo="workstation",
                )
            with patch("app.api.connect", test_connect):
                client = TestClient(api)
                logged_out = client.get("/people-zones", follow_redirects=False)
                with patch("app.api._request_has_valid_session", return_value=True):
                    page = client.get("/people-zones")
                summary = client.get("/people-zones/summary")

        self.assertEqual(logged_out.status_code, 303)
        self.assertTrue(logged_out.headers["location"].startswith("/login?next="))
        self.assertEqual(page.status_code, 200)
        self.assertIn("Pessoas e Zonas", page.text)
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(summary.json()["expected_staff"], 1)
        self.assertIn("workstation_unattended", summary.text)

    def test_local_diagnostics_does_not_expose_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            test_connect, _camera_id = self.make_context(temp_dir)
            with patch("app.api.connect", test_connect):
                client = TestClient(api)
                response = client.get("/local-diagnostics")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["sqlite"], "ok")
        self.assertIn("outbox_pendente", response.json())
        self.assertNotIn("rtsp://", response.text)
        self.assertNotIn("senha", response.text.lower())

    def test_local_diagnostics_view_is_served(self) -> None:
        client = TestClient(api)
        response = client.get("/local-diagnostics-view")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Diagnóstico", response.text)

    def test_api_persists_zone_with_tenant_unit_and_default_rule(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            test_connect, camera_id = self.make_context(temp_dir)
            with patch("app.api.connect", test_connect):
                client = TestClient(api)
                created = client.post(
                    f"/cameras/{camera_id}/areas",
                    json={
                        "nome": "Posto 4",
                        "tipo": "workstation",
                        "ativa": True,
                        "absence_tolerance_seconds": 10,
                        "pontos": [
                            {"x": 0.2, "y": 0.2},
                            {"x": 0.8, "y": 0.2},
                            {"x": 0.8, "y": 0.8},
                        ],
                    },
                )
                listed = client.get(f"/cameras/{camera_id}/areas")
            with test_connect() as connection:
                rules = listar_regras(connection, camera_id=camera_id)
                row = connection.execute("SELECT cliente_id, unidade_id FROM monitored_areas WHERE id = ?", (created.json()["id"],)).fetchone()

        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["tipo"], "workstation")
        self.assertEqual(created.json()["absence_tolerance_seconds"], 10)
        self.assertEqual(len(listed.json()), 1)
        self.assertTrue(row["cliente_id"])
        self.assertTrue(row["unidade_id"])
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["tipo_evento"], "workstation_unattended")
        self.assertEqual(rules[0]["regiao_id"], created.json()["id"])
        self.assertEqual(rules[0]["tempo_minimo"], 10)

    def test_operator_zone_uses_absence_tolerance_for_unattended_rule(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            test_connect, camera_id = self.make_context(temp_dir)
            with patch("app.api.connect", test_connect):
                client = TestClient(api)
                created = client.post(
                    f"/cameras/{camera_id}/areas",
                    json={
                        "nome": "Zona do operador",
                        "tipo": "operator_zone",
                        "ativa": True,
                        "absence_tolerance_seconds": 5,
                        "pontos": [
                            {"x": 0.2, "y": 0.2},
                            {"x": 0.8, "y": 0.2},
                            {"x": 0.8, "y": 0.8},
                        ],
                    },
                )
            with test_connect() as connection:
                rules = listar_regras(connection, camera_id=camera_id)

        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["tipo"], "operator_zone")
        self.assertEqual(created.json()["absence_tolerance_seconds"], 5)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["tipo_evento"], "workstation_unattended")
        self.assertEqual(rules[0]["tempo_minimo"], 5)

    def test_work_area_api_creates_unattended_rule_with_twenty_seconds(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            test_connect, camera_id = self.make_context(temp_dir)
            with patch("app.api.connect", test_connect):
                client = TestClient(api)
                created = client.post(
                    f"/cameras/{camera_id}/areas",
                    json={
                        "nome": "Área de corte A6",
                        "tipo": "work_area",
                        "ativa": True,
                        "absence_tolerance_seconds": 20,
                        "pontos": [
                            {"x": 0.2, "y": 0.2},
                            {"x": 0.8, "y": 0.2},
                            {"x": 0.8, "y": 0.8},
                        ],
                    },
                )
                listed = client.get(f"/cameras/{camera_id}/areas")
            with test_connect() as connection:
                rules = listar_regras(connection, camera_id=camera_id)

        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["nome"], "Área de corte A6")
        self.assertEqual(created.json()["tipo"], "work_area")
        self.assertEqual(created.json()["absence_tolerance_seconds"], 20)
        self.assertEqual(listed.json()[0]["id"], created.json()["id"])
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["tipo_evento"], "workstation_unattended")
        self.assertEqual(rules[0]["tempo_minimo"], 20)
        self.assertEqual(rules[0]["condicao"]["type"], "absence_in_zone")

    def test_work_area_presence_absence_generates_one_event_evidence_outbox_and_alert(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict("os.environ", {"CAMPEX_EMAIL_MODE": "console", "CAMPEX_ZONE_EXIT_GRACE_SECONDS": "0"}):
            test_connect, camera_id = self.make_context(temp_dir)
            evidence_root = Path(temp_dir) / "evidence"
            frame = np.zeros((100, 100, 3), dtype=np.uint8)
            inside = [Detection(30, 10, 50, 70, 0.92, track_id=5)]
            with test_connect() as connection:
                area_id = criar_area_monitorada(
                    connection,
                    camera_id,
                    "Área de corte A6",
                    [{"x": 0.2, "y": 0.2}, {"x": 0.8, "y": 0.2}, {"x": 0.8, "y": 0.8}, {"x": 0.2, "y": 0.8}],
                    tipo="work_area",
                    absence_tolerance_seconds=0.2,
                )
                self.add_operational_context(connection, camera_id, machine_state="ACTIVE")
                areas = listar_areas_camera(connection, camera_id)
            engine = PeopleZonesEngine(camera_id, evidence_root=evidence_root)
            with patch("app.people_zones.connect", test_connect), patch("app.alerts.connect", test_connect), patch("builtins.print"):
                engine.update(areas, inside, frame)
                with test_connect() as connection:
                    self.assertEqual(listar_eventos_filtrados(connection, tipo="workstation_unattended"), [])
                engine.update(areas, [], frame)
                time.sleep(0.05)
                engine.update(areas, [], frame)
                with test_connect() as connection:
                    self.assertEqual(listar_eventos_filtrados(connection, tipo="workstation_unattended"), [])
                time.sleep(0.22)
                engine.update(areas, [], frame)
                engine.update(areas, [], frame)
                engine.update(areas, inside, frame)
                engine.update(areas, inside, frame)
                with test_connect() as connection:
                    events = listar_eventos_filtrados(connection, tipo="workstation_unattended")
                    outbox_rows = connection.execute("SELECT * FROM sync_outbox WHERE event_uuid = ?", (events[0]["event_uuid"],)).fetchall()
                    deliveries = listar_alert_deliveries(connection)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["area_id"], area_id)
        self.assertEqual(events[0]["camera_id"], camera_id)
        self.assertEqual(events[0]["status"], "closed")
        self.assertIsNotNone(events[0]["fim"])
        self.assertGreater(float(events[0]["duracao"] or 0), 0)
        self.assertTrue(events[0]["midia_path"])
        self.assertEqual(len(outbox_rows), 1)
        self.assertEqual(len(deliveries), 0)  # delivery direto removido; Alert Decisioning é responsável pelo envio

    def test_brief_exit_from_zone_does_not_create_operational_absence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict("os.environ", {"CAMPEX_EMAIL_MODE": "console"}):
            test_connect, camera_id = self.make_context(temp_dir)
            frame = np.zeros((100, 100, 3), dtype=np.uint8)
            inside = [Detection(30, 10, 50, 70, 0.92, track_id=5)]
            with test_connect() as connection:
                criar_area_monitorada(
                    connection,
                    camera_id,
                    "Área de trabalho",
                    [{"x": 0.2, "y": 0.2}, {"x": 0.8, "y": 0.2}, {"x": 0.8, "y": 0.8}],
                    tipo="work_area",
                    absence_tolerance_seconds=5,
                )
                self.add_operational_context(connection, camera_id, machine_state="ACTIVE")
                areas = listar_areas_camera(connection, camera_id)
            engine = PeopleZonesEngine(camera_id, evidence_root=Path(temp_dir) / "evidence")
            with patch("app.people_zones.connect", test_connect), patch("app.alerts.connect", test_connect):
                engine.update(areas, inside, frame)
                engine.update(areas, [], frame)
                time.sleep(0.05)
                engine.update(areas, [], frame)
                engine.update(areas, inside, frame)
                with test_connect() as connection:
                    events = listar_eventos_filtrados(connection, tipo="workstation_unattended")
        self.assertEqual(events, [])

    def test_stopped_machine_lights_off_and_no_people_is_no_activity_not_absence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            test_connect, camera_id = self.make_context(temp_dir)
            frame = np.zeros((100, 100, 3), dtype=np.uint8)
            with test_connect() as connection:
                criar_area_monitorada(
                    connection,
                    camera_id,
                    "Área parada",
                    [{"x": 0.2, "y": 0.2}, {"x": 0.8, "y": 0.2}, {"x": 0.8, "y": 0.8}],
                    tipo="work_area",
                    absence_tolerance_seconds=0,
                )
                self.add_operational_context(
                    connection,
                    camera_id,
                    machine_state="STOPPED",
                    person_presence="UNKNOWN",
                    lighting_state="OFF",
                    operational_activity="NO_ACTIVITY",
                )
                areas = listar_areas_camera(connection, camera_id)
            engine = PeopleZonesEngine(camera_id, evidence_root=Path(temp_dir) / "evidence")
            with patch("app.people_zones.connect", test_connect):
                engine.update(areas, [], frame)
                engine.update(areas, [], frame)
                with test_connect() as connection:
                    events = listar_eventos_filtrados(connection, tipo="workstation_unattended")
        self.assertEqual(events, [])

    def test_active_machine_with_sustained_empty_area_creates_absence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict("os.environ", {"CAMPEX_EMAIL_MODE": "console"}):
            test_connect, camera_id = self.make_context(temp_dir)
            frame = np.zeros((100, 100, 3), dtype=np.uint8)
            with test_connect() as connection:
                criar_area_monitorada(
                    connection,
                    camera_id,
                    "Área ativa",
                    [{"x": 0.2, "y": 0.2}, {"x": 0.8, "y": 0.2}, {"x": 0.8, "y": 0.8}],
                    tipo="work_area",
                    absence_tolerance_seconds=0.1,
                )
                self.add_operational_context(connection, camera_id, machine_state="ACTIVE")
                areas = listar_areas_camera(connection, camera_id)
            engine = PeopleZonesEngine(camera_id, evidence_root=Path(temp_dir) / "evidence")
            with patch("app.people_zones.connect", test_connect), patch("app.alerts.connect", test_connect):
                engine.update(areas, [], frame)
                time.sleep(0.12)
                engine.update(areas, [], frame)
                with test_connect() as connection:
                    events = listar_eventos_filtrados(connection, tipo="workstation_unattended")
        self.assertEqual(len(events), 1)

    def test_normal_activity_from_other_context_does_not_require_operator_here(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            test_connect, camera_id = self.make_context(temp_dir)
            frame = np.zeros((100, 100, 3), dtype=np.uint8)
            with test_connect() as connection:
                criar_area_monitorada(
                    connection,
                    camera_id,
                    "Área A6",
                    [{"x": 0.2, "y": 0.2}, {"x": 0.8, "y": 0.2}, {"x": 0.8, "y": 0.8}],
                    tipo="work_area",
                    absence_tolerance_seconds=0,
                    machine_id="mach_a6",
                )
                self.add_operational_context(
                    connection,
                    camera_id,
                    machine_state="STOPPED",
                    operational_activity="NORMAL_ACTIVITY",
                    machine_id="mach_other",
                )
                areas = listar_areas_camera(connection, camera_id)
            engine = PeopleZonesEngine(camera_id, evidence_root=Path(temp_dir) / "evidence")
            with patch("app.people_zones.connect", test_connect):
                engine.update(areas, [], frame)
                engine.update(areas, [], frame)
                with test_connect() as connection:
                    events = listar_eventos_filtrados(connection, tipo="workstation_unattended")

        self.assertEqual(events, [])

    def test_active_machine_same_context_still_requires_presence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            test_connect, camera_id = self.make_context(temp_dir)
            frame = np.zeros((100, 100, 3), dtype=np.uint8)
            with test_connect() as connection:
                criar_area_monitorada(
                    connection,
                    camera_id,
                    "Área A6",
                    [{"x": 0.2, "y": 0.2}, {"x": 0.8, "y": 0.2}, {"x": 0.8, "y": 0.8}],
                    tipo="work_area",
                    absence_tolerance_seconds=0,
                    machine_id="mach_a6",
                )
                self.add_operational_context(connection, camera_id, machine_state="ACTIVE", machine_id="mach_a6")
                areas = listar_areas_camera(connection, camera_id)
            engine = PeopleZonesEngine(camera_id, evidence_root=Path(temp_dir) / "evidence")
            with patch("app.people_zones.connect", test_connect), patch("app.alerts.connect", test_connect):
                engine.update(areas, [], frame)
                engine.update(areas, [], frame)
                with test_connect() as connection:
                    events = listar_eventos_filtrados(connection, tipo="workstation_unattended")

        self.assertEqual(len(events), 1)

    def test_camera_offline_and_unknown_context_do_not_create_absence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            test_connect, camera_id = self.make_context(temp_dir)
            frame = np.zeros((100, 100, 3), dtype=np.uint8)
            with test_connect() as connection:
                criar_area_monitorada(
                    connection,
                    camera_id,
                    "Área sem dado",
                    [{"x": 0.2, "y": 0.2}, {"x": 0.8, "y": 0.2}, {"x": 0.8, "y": 0.8}],
                    tipo="work_area",
                    absence_tolerance_seconds=0,
                )
                self.add_operational_context(connection, camera_id, machine_state="ACTIVE", camera_online=False, data_quality="sensor_unavailable")
                areas = listar_areas_camera(connection, camera_id)
            engine = PeopleZonesEngine(camera_id, evidence_root=Path(temp_dir) / "evidence")
            with patch("app.people_zones.connect", test_connect):
                engine.update(areas, [], frame)
                with test_connect() as connection:
                    offline_events = listar_eventos_filtrados(connection, tipo="workstation_unattended")
                    self.add_operational_context(connection, camera_id, machine_state="UNKNOWN", data_quality="insufficient_data")
                engine.update(areas, [], frame)
                with test_connect() as connection:
                    unknown_events = listar_eventos_filtrados(connection, tipo="workstation_unattended")
        self.assertEqual(offline_events, [])
        self.assertEqual(unknown_events, [])

    def test_work_area_without_runtime_updates_does_not_create_empty_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            test_connect, camera_id = self.make_context(temp_dir)
            with test_connect() as connection:
                criar_area_monitorada(
                    connection,
                    camera_id,
                    "Área offline",
                    [{"x": 0.2, "y": 0.2}, {"x": 0.8, "y": 0.2}, {"x": 0.8, "y": 0.8}],
                    tipo="work_area",
                    absence_tolerance_seconds=0,
                )
                events = listar_eventos_filtrados(connection, tipo="workstation_unattended")

        self.assertEqual(events, [])

    def test_browser_zone_contract_post_201_sqlite_get_and_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "browser-contract.sqlite3"

            def test_connect():
                return connect(db_path)

            with test_connect() as connection:
                init_db(connection)
                cliente_id = criar_cliente(connection, "Cliente")
                unidade_id = criar_unidade(connection, cliente_id, "Unidade")
                camera_id = criar_camera(connection, unidade_id, "Camera", cliente_id=cliente_id)
            request_payload = {
                "camera_id": camera_id,
                "cliente_id": "ignorado_pelo_backend",
                "unidade_id": "ignorado_pelo_backend",
                "name": "Posto de Corte 1",
                "area_type": "workstation",
                "polygon": [
                    {"x": 0.20, "y": 0.20},
                    {"x": 0.80, "y": 0.20},
                    {"x": 0.80, "y": 0.80},
                    {"x": 0.20, "y": 0.80},
                ],
                "active": True,
            }
            with patch("app.api.connect", test_connect):
                client = TestClient(api)
                created = client.post(f"/cameras/{camera_id}/areas", json=request_payload)
                listed = client.get(f"/cameras/{camera_id}/areas")
                restarted_client = TestClient(api)
                listed_after_restart = restarted_client.get(f"/cameras/{camera_id}/areas")
            with test_connect() as connection:
                row = connection.execute(
                    "SELECT id, cliente_id, unidade_id, camera_id, nome, tipo, pontos_json, ativa FROM monitored_areas WHERE id = ?",
                    (created.json()["id"],),
                ).fetchone()

        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["nome"], "Posto de Corte 1")
        self.assertEqual(created.json()["tipo"], "workstation")
        self.assertEqual(row["camera_id"], camera_id)
        self.assertNotEqual(row["cliente_id"], "ignorado_pelo_backend")
        self.assertNotEqual(row["unidade_id"], "ignorado_pelo_backend")
        self.assertEqual(len(listed.json()), 1)
        self.assertEqual(listed.json()[0]["id"], created.json()["id"])
        self.assertEqual(listed_after_restart.json()[0]["id"], created.json()["id"])

    def test_zone_persists_after_test_app_restart_with_same_sqlite_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "restart.sqlite3"

            def test_connect():
                return connect(db_path)

            with test_connect() as connection:
                init_db(connection)
                cliente_id = criar_cliente(connection, "Cliente")
                unidade_id = criar_unidade(connection, cliente_id, "Unidade")
                camera_id = criar_camera(connection, unidade_id, "Camera", cliente_id=cliente_id)
            with patch("app.api.connect", test_connect):
                first_client = TestClient(api)
                created = first_client.post(
                    f"/cameras/{camera_id}/areas",
                    json={
                        "nome": "Posto persistente",
                        "tipo": "workstation",
                        "pontos": [{"x": 0.1, "y": 0.1}, {"x": 0.4, "y": 0.1}, {"x": 0.4, "y": 0.4}],
                    },
                )
                second_client = TestClient(api)
                listed = second_client.get(f"/cameras/{camera_id}/areas")

        self.assertEqual(created.status_code, 201)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()[0]["nome"], "Posto persistente")

    def test_dev_test_event_creates_evidence_alert_delivery_and_outbox(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict("os.environ", {"CAMPEX_ENABLE_TEST_EVENT": "true", "CAMPEX_ENV": "development", "CAMPEX_EMAIL_MODE": "console"}):
            test_connect, camera_id = self.make_context(temp_dir)
            with test_connect() as connection:
                area_id = criar_area_monitorada(
                    connection,
                    camera_id,
                    "Posto 1",
                    [{"x": 0.1, "y": 0.1}, {"x": 0.4, "y": 0.1}, {"x": 0.4, "y": 0.4}],
                    tipo="workstation",
                )
            with patch("app.api.connect", test_connect), patch("app.alerts.connect", test_connect), patch("builtins.print"):
                client = TestClient(api)
                response = client.post("/dev/test-event", json={"camera_id": camera_id, "area_id": area_id})
                time.sleep(0.2)
            with test_connect() as connection:
                event = listar_eventos_filtrados(connection, tipo="workstation_unattended")[0]
                outbox = connection.execute("SELECT * FROM sync_outbox WHERE event_uuid = ?", (event["event_uuid"],)).fetchone()
                deliveries = listar_alert_deliveries(connection)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(event["metadata"]["is_test"], True)
        self.assertTrue(event["midia_path"])
        self.assertIsNotNone(outbox)
        self.assertEqual(len(deliveries), 0)  # delivery direto removido; Alert Decisioning é responsável pelo envio

    def test_dev_test_event_is_hidden_without_flag(self) -> None:
        with patch.dict("os.environ", {"CAMPEX_ENABLE_TEST_EVENT": "false", "CAMPEX_ENV": "production"}):
            client = TestClient(api)
            response = client.post("/dev/test-event", json={})

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
