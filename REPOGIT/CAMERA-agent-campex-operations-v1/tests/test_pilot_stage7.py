from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import api
from app.auth import authenticate, create_user
from app.database import connect, init_db
from app.models import criar_camera, criar_cliente, criar_unidade, obter_camera
from app.pilot import acceptance_checklist, create_backup, health_snapshot, restore_backup
from app.security import decrypt_secret, encrypt_secret, hash_password, verify_password


class PilotStage7Test(unittest.TestCase):
    def make_db(self, temp_dir: str):
        db_path = Path(temp_dir) / "pilot.sqlite3"

        def test_connect(_db_path: object = None):
            return connect(db_path)

        with connect(db_path) as connection:
            init_db(connection)
        return db_path, test_connect

    def test_password_hash_and_authentication(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _db_path, test_connect = self.make_db(temp_dir)
            with test_connect() as connection:
                user_id = create_user(connection, "admin@example.com", "senha-forte", "admin_campex")
                user = authenticate(connection, "admin@example.com", "senha-forte")
        self.assertTrue(user_id.startswith("usr_"))
        self.assertEqual(user["email"], "admin@example.com")
        self.assertTrue(verify_password("senha-forte", hash_password("senha-forte")))

    def test_camera_password_is_encrypted_at_rest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict("os.environ", {"CAMPEX_SECRET_KEY": "test-key"}):
            _db_path, test_connect = self.make_db(temp_dir)
            with test_connect() as connection:
                cliente_id = criar_cliente(connection, "Cliente")
                unidade_id = criar_unidade(connection, cliente_id, "Unidade")
                camera_id = criar_camera(
                    connection,
                    unidade_id,
                    "Camera",
                    cliente_id=cliente_id,
                    rtsp_host="10.0.0.10",
                    rtsp_username="admin",
                    rtsp_password="segredo",
                )
                raw = connection.execute("SELECT rtsp_password, rtsp_password_encrypted FROM cameras WHERE id = ?", (camera_id,)).fetchone()
                private_camera = obter_camera(connection, camera_id, include_secret=True)
        self.assertIsNone(raw["rtsp_password"])
        self.assertNotIn("segredo", raw["rtsp_password_encrypted"])
        self.assertEqual(private_camera["rtsp_password"], "segredo")

    def test_api_login_isolation_and_hidden_camera_details(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _db_path, test_connect = self.make_db(temp_dir)
            with test_connect() as connection:
                cliente_a = criar_cliente(connection, "A")
                unidade_a = criar_unidade(connection, cliente_a, "UA")
                criar_camera(connection, unidade_a, "Camera A", cliente_id=cliente_a, rtsp_host="10.0.0.1")
                cliente_b = criar_cliente(connection, "B")
                unidade_b = criar_unidade(connection, cliente_b, "UB")
                criar_camera(connection, unidade_b, "Camera B", cliente_id=cliente_b, rtsp_host="10.0.0.2")
                create_user(connection, "op@example.com", "senha", "operador", cliente_a)
            with patch("app.api.connect", test_connect):
                client = TestClient(api)
                login = client.post("/auth/login", json={"email": "op@example.com", "senha": "senha"})
                cameras = client.get("/cameras/estado")
        self.assertEqual(login.status_code, 200)
        self.assertEqual(len(cameras.json()), 1)
        self.assertEqual(cameras.json()[0]["nome"], "Camera A")
        self.assertNotIn("rtsp_host", cameras.text)

    def test_encrypt_decrypt_roundtrip(self) -> None:
        with patch.dict("os.environ", {"CAMPEX_SECRET_KEY": "roundtrip"}):
            encrypted = encrypt_secret("valor-secreto")
            self.assertNotIn("valor-secreto", encrypted)
            self.assertEqual(decrypt_secret(encrypted), "valor-secreto")

    def test_backup_restore_health_and_checklist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path, test_connect = self.make_db(temp_dir)
            with test_connect() as connection:
                cliente_id = criar_cliente(connection, "Cliente")
                create_user(connection, "admin@example.com", "senha", "admin_cliente", cliente_id)
            backup = create_backup(Path(temp_dir) / "backups", db_path)
            restored_root = Path(temp_dir) / "restore"
            restored_root.mkdir()
            restore_backup(backup, restored_root)
            health = health_snapshot(db_path)
            checklist = acceptance_checklist(db_path)
            self.assertTrue((restored_root / "data" / "visual_ops_product.sqlite3").exists())
            self.assertEqual(health["database"], "online")
            self.assertTrue(checklist["checks"]["login"])


if __name__ == "__main__":
    unittest.main()
