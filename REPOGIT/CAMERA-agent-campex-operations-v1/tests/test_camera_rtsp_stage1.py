from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import api
from app.camera_rtsp import build_rtsp_url
from app.database import connect, init_db
from app.models import criar_camera, criar_cliente, criar_unidade, listar, obter_camera


class CameraRtspStage1Test(unittest.TestCase):
    def test_rtsp_create_schema_does_not_require_unidade_id(self) -> None:
        schema = api.openapi()["components"]["schemas"]["CameraRtspIn"]
        self.assertEqual(schema.get("required"), ["nome"])
        self.assertNotIn("unidade_id", schema.get("required", []))

    def test_build_rtsp_url_masks_credentials(self) -> None:
        connection = build_rtsp_url(
            host="192.168.1.50",
            port=554,
            path="live/channel1",
            username="admin",
            password="senha-secreta",
        )

        self.assertEqual(connection.url, "rtsp://admin:senha-secreta@192.168.1.50:554/live/channel1")
        self.assertEqual(connection.safe_url, "rtsp://***:***@192.168.1.50:554/live/channel1")
        self.assertNotIn("senha-secreta", connection.safe_url)

    def test_camera_credentials_stay_out_of_public_listing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "stage1.sqlite3"
            with connect(db_path) as connection:
                init_db(connection)
                cliente_id = criar_cliente(connection, "Cliente RTSP")
                unidade_id = criar_unidade(connection, cliente_id, "Unidade RTSP")
                rtsp = build_rtsp_url(
                    host="camera.local",
                    port=554,
                    path="/stream",
                    username="operador",
                    password="muito-secreta",
                )
                camera_id = criar_camera(
                    connection,
                    unidade_id,
                    "Camera RTSP",
                    config_ref=rtsp.url,
                    status="offline",
                    cliente_id=cliente_id,
                    source_type="rtsp",
                    secure_ref=rtsp.safe_url,
                    rtsp_host=rtsp.host,
                    rtsp_port=rtsp.port,
                    rtsp_path=rtsp.path,
                    rtsp_username=rtsp.username,
                    rtsp_password=rtsp.password,
                )
                private_camera = obter_camera(connection, camera_id, include_secret=True)
                public_camera = listar(connection, "cameras")[0]

        self.assertEqual(private_camera["rtsp_password"], "muito-secreta")
        self.assertNotIn("rtsp_password", public_camera)
        self.assertNotIn("rtsp_username", public_camera)
        self.assertNotIn("muito-secreta", str(public_camera))
        self.assertIn("***:***", public_camera["config_ref"])

    def test_post_camera_rtsp_derives_cliente_from_unidade(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "stage1_api.sqlite3"

            def test_connect(_db_path: object = None):
                return connect(db_path)

            with connect(db_path) as connection:
                init_db(connection)
                cliente_id = criar_cliente(connection, "Cliente")
                unidade_id = criar_unidade(connection, cliente_id, "Unidade")
            fake_test = {"compativel": True, "conexao_realizada": True, "video_recebido": True}
            with patch("app.api.connect", test_connect), patch("app.api.test_rtsp_connection", return_value=fake_test):
                response = TestClient(api).post(
                    "/cameras/rtsp",
                    json={
                        "nome": "Camera",
                        "unidade_id": unidade_id,
                        "host": "camera.local",
                        "usuario": "admin",
                        "senha": "segredo",
                        "caminho_rtsp": "/stream",
                    },
                )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["camera"]["cliente_id"], cliente_id)
        self.assertNotIn("segredo", response.text)

    def test_post_camera_rtsp_creates_default_cliente_unidade_without_internal_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "stage1_api_default.sqlite3"

            def test_connect(_db_path: object = None):
                return connect(db_path)

            with connect(db_path) as connection:
                init_db(connection)
            fake_test = {"compativel": True, "conexao_realizada": True, "video_recebido": True, "resolucao": "1280x720", "fps": 30}
            with patch("app.api.connect", test_connect), patch("app.api.test_rtsp_connection", return_value=fake_test):
                response = TestClient(api).post(
                    "/cameras/rtsp",
                    json={
                        "nome": "Extrusora Principal",
                        "host": "192.168.15.2",
                        "usuario": "admin",
                        "senha": "segredo",
                        "caminho_rtsp": "/stream",
                    },
                )
            payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["camera"]["cliente_id"])
        self.assertTrue(payload["camera"]["unidade_id"])
        self.assertEqual(payload["camera"]["resolucao"], "1280x720")
        self.assertEqual(payload["camera"]["fps"], 30)
        self.assertNotIn("segredo", response.text)

    def test_post_camera_rtsp_returns_400_for_invalid_unidade_or_cliente(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "stage1_api_invalid.sqlite3"

            def test_connect(_db_path: object = None):
                return connect(db_path)

            with connect(db_path) as connection:
                init_db(connection)
                cliente_a = criar_cliente(connection, "Cliente A")
                cliente_b = criar_cliente(connection, "Cliente B")
                unidade_id = criar_unidade(connection, cliente_a, "Unidade A")
            with patch("app.api.connect", test_connect), patch("app.api.test_rtsp_connection", return_value={"compativel": True}):
                client = TestClient(api)
                missing = client.post(
                    "/cameras/rtsp",
                    json={"nome": "Camera", "unidade_id": "uni_inexistente", "host": "camera.local"},
                )
                mismatch = client.post(
                    "/cameras/rtsp",
                    json={"nome": "Camera", "unidade_id": unidade_id, "cliente_id": cliente_b, "host": "camera.local"},
                )
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(mismatch.status_code, 400)
        self.assertIn("Unidade", missing.text)
        self.assertIn("não pertence", mismatch.text)


if __name__ == "__main__":
    unittest.main()
