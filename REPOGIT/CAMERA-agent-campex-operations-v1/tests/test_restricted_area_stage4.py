from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import api
from app.database import connect, init_db
from app.models import criar_camera, criar_cliente, criar_unidade, listar_areas_camera
from app.restricted_area import (
    AreaPresenceTracker,
    Detection,
    area_from_dict,
    evaluate_area,
    normalize_points,
    point_in_polygon,
)


class RestrictedAreaStage4Test(unittest.TestCase):
    def test_area_saved_with_normalized_coordinates_and_no_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "areas.sqlite3"
            with connect(db_path) as connection:
                init_db(connection)
                cliente_id = criar_cliente(connection, "Cliente")
                unidade_id = criar_unidade(connection, cliente_id, "Unidade")
                camera_id = criar_camera(
                    connection,
                    unidade_id,
                    "Camera",
                    config_ref="rtsp://user:secret@camera/stream",
                    secure_ref="rtsp://***:***@camera/stream",
                    rtsp_username="user",
                    rtsp_password="secret",
                )
                from app.models import criar_area_monitorada

                points = normalize_points([
                    {"x": 0.1, "y": 0.1},
                    {"x": 0.9, "y": 0.1},
                    {"x": 0.9, "y": 0.9},
                ])
                criar_area_monitorada(connection, camera_id, "Restrita", points)
                areas = listar_areas_camera(connection, camera_id)

        self.assertEqual(len(areas), 1)
        self.assertTrue(all(0 <= point["x"] <= 1 and 0 <= point["y"] <= 1 for point in areas[0]["pontos"]))
        self.assertNotIn("secret", str(areas))

    def test_person_inside_and_outside_area(self) -> None:
        area = area_from_dict({
            "id": "area_1",
            "camera_id": "cam",
            "nome": "Restrita",
            "pontos": [{"x": 0.2, "y": 0.2}, {"x": 0.8, "y": 0.2}, {"x": 0.8, "y": 0.8}, {"x": 0.2, "y": 0.8}],
            "ativa": True,
        })
        inside = Detection(40, 20, 60, 70, 0.9, track_id=1)
        outside = Detection(5, 5, 20, 20, 0.9, track_id=2)
        tracker = AreaPresenceTracker(enter_frames=1, exit_frames=1)
        presence, ids = evaluate_area(area, [inside, outside], 100, 100, tracker)

        self.assertEqual(presence.pessoas_dentro, 1)
        self.assertEqual(ids, {1})
        self.assertTrue(point_in_polygon((0.5, 0.7), area.pontos))
        self.assertFalse(point_in_polygon((0.1, 0.2), area.pontos))

    def test_border_debounce_reduces_oscillation(self) -> None:
        area = area_from_dict({
            "id": "area_1",
            "camera_id": "cam",
            "nome": "Restrita",
            "pontos": [{"x": 0.4, "y": 0.4}, {"x": 0.8, "y": 0.4}, {"x": 0.8, "y": 0.8}, {"x": 0.4, "y": 0.8}],
            "ativa": True,
        })
        tracker = AreaPresenceTracker(enter_frames=2, exit_frames=2)
        inside = Detection(45, 45, 55, 60, 0.9, track_id=1)
        outside = Detection(20, 20, 30, 30, 0.9, track_id=1)

        first, _ = evaluate_area(area, [inside], 100, 100, tracker)
        second, _ = evaluate_area(area, [inside], 100, 100, tracker)
        third, _ = evaluate_area(area, [outside], 100, 100, tracker)

        self.assertEqual(first.estado, "livre")
        self.assertEqual(second.estado, "ocupada")
        self.assertEqual(third.estado, "ocupada")

    def test_resolution_change_keeps_area_position(self) -> None:
        area = area_from_dict({
            "id": "area_1",
            "camera_id": "cam",
            "nome": "Restrita",
            "pontos": [{"x": 0.25, "y": 0.25}, {"x": 0.75, "y": 0.25}, {"x": 0.75, "y": 0.75}, {"x": 0.25, "y": 0.75}],
            "ativa": True,
        })
        tracker_a = AreaPresenceTracker(enter_frames=1, exit_frames=1)
        tracker_b = AreaPresenceTracker(enter_frames=1, exit_frames=1)
        detection_small = Detection(40, 20, 60, 70, 0.9, track_id=1)
        detection_large = Detection(80, 40, 120, 140, 0.9, track_id=1)

        small, _ = evaluate_area(area, [detection_small], 100, 100, tracker_a)
        large, _ = evaluate_area(area, [detection_large], 200, 200, tracker_b)

        self.assertEqual(small.estado, "ocupada")
        self.assertEqual(large.estado, "ocupada")

    def test_area_activate_deactivate_and_delete(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "areas.sqlite3"
            with connect(db_path) as connection:
                init_db(connection)
                cliente_id = criar_cliente(connection, "Cliente")
                unidade_id = criar_unidade(connection, cliente_id, "Unidade")
                camera_id = criar_camera(connection, unidade_id, "Camera")
                from app.models import atualizar_area_monitorada, criar_area_monitorada, excluir_area_monitorada

                area_id = criar_area_monitorada(
                    connection,
                    camera_id,
                    "Restrita",
                    [{"x": 0.1, "y": 0.1}, {"x": 0.8, "y": 0.1}, {"x": 0.8, "y": 0.8}],
                )
                inactive = atualizar_area_monitorada(connection, area_id, ativa=False)
                active = atualizar_area_monitorada(connection, area_id, ativa=True)
                deleted = excluir_area_monitorada(connection, area_id)

        self.assertFalse(inactive["ativa"])
        self.assertTrue(active["ativa"])
        self.assertTrue(deleted)

    def test_area_api_endpoints_do_not_expose_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "api_areas.sqlite3"

            def test_connect(_db_path: object = None):
                return connect(db_path)

            with patch("app.api.connect", test_connect):
                with connect(db_path) as connection:
                    init_db(connection)
                    cliente_id = criar_cliente(connection, "Cliente")
                    unidade_id = criar_unidade(connection, cliente_id, "Unidade")
                    camera_id = criar_camera(
                        connection,
                        unidade_id,
                        "Camera",
                        config_ref="rtsp://user:secret@camera/stream",
                        rtsp_username="user",
                        rtsp_password="secret",
                    )
                client = TestClient(api)
                created = client.post(
                    f"/cameras/{camera_id}/areas",
                    json={
                        "nome": "Restrita",
                        "tipo": "restricted_area",
                        "pontos": [
                            {"x": 0.1, "y": 0.1},
                            {"x": 0.8, "y": 0.1},
                            {"x": 0.8, "y": 0.8},
                        ],
                    },
                )
                area_id = created.json()["id"]
                listed = client.get(f"/cameras/{camera_id}/areas")
                deactivated = client.post(f"/areas/{area_id}/deactivate")
                activated = client.post(f"/areas/{area_id}/activate")
                deleted = client.delete(f"/areas/{area_id}")

        self.assertEqual(created.status_code, 201)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(deactivated.status_code, 200)
        self.assertFalse(deactivated.json()["ativa"])
        self.assertTrue(activated.json()["ativa"])
        self.assertTrue(deleted.json()["deleted"])
        self.assertNotIn("secret", created.text + listed.text + deactivated.text + activated.text + deleted.text)


if __name__ == "__main__":
    unittest.main()
