from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import api
from app.auth import create_user
from app.database import connect, init_db
from app.models import criar_camera, criar_cliente, criar_unidade, listar_alert_deliveries


class PilotFinalPersistentConfigTest(unittest.TestCase):
    def make_db(self, temp_dir: str):
        db_path = Path(temp_dir) / "pilot_final.sqlite3"

        def test_connect(_db_path: object = None):
            return connect(db_path)

        with connect(db_path) as connection:
            init_db(connection)
        return db_path, test_connect

    def wait_delivery(self, test_connect):
        for _ in range(30):
            with test_connect() as connection:
                rows = listar_alert_deliveries(connection)
            if rows and all(row["status"] != "pending" for row in rows):
                return rows
            time.sleep(0.05)
        with test_connect() as connection:
            return listar_alert_deliveries(connection)

    def test_full_pilot_registration_persists_after_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {"CAMPEX_EMAIL_MODE": "console"}):
            db_path, test_connect = self.make_db(temp_dir)
            with patch("app.api.connect", test_connect), patch("app.alerts.connect", test_connect), patch("builtins.print"):
                client = TestClient(api)
                cliente = client.post("/clientes", json={"nome": "FL Plásticos", "documento": "dev"}).json()
                user = client.post(
                    "/auth/users",
                    json={
                        "cliente_id": cliente["id"],
                        "nome": "Felipe",
                        "email": "felipe@flplasticos.com",
                        "senha": "senha-forte",
                        "role": "admin_cliente",
                    },
                )
                self.assertEqual(user.status_code, 200)
                login = client.post("/auth/login", json={"email": "felipe@flplasticos.com", "senha": "senha-forte"})
                unidade = client.post(
                    "/unidades",
                    json={"nome": "Fábrica principal", "localizacao": "São Paulo", "timezone": "America/Sao_Paulo"},
                ).json()
                camera = client.post(
                    "/cameras",
                    json={"nome": "Extrusora câmera", "unidade_id": unidade["id"], "source_type": "rtsp", "status": "offline"},
                ).json()
                maquina = client.post(
                    f"/cameras/{camera['id']}/machine-monitors",
                    json={
                        "nome": "Extrusora principal",
                        "machine_polygon": [{"x": 0.2, "y": 0.2}, {"x": 0.8, "y": 0.2}, {"x": 0.8, "y": 0.8}],
                        "operator_polygon": [{"x": 0.0, "y": 0.2}, {"x": 0.1, "y": 0.2}, {"x": 0.1, "y": 0.8}],
                    },
                )
                recipient = client.post(
                    "/alert-recipients",
                    json={"nome": "Supervisor", "email": "supervisor@flplasticos.com", "event_types": ["machine_stoppage"]},
                ).json()
                tested = client.post(f"/alert-recipients/{recipient['id']}/test")
                deliveries = self.wait_delivery(test_connect)
            self.assertEqual(login.status_code, 200)
            self.assertEqual(maquina.status_code, 200)
            self.assertEqual(tested.status_code, 200)
            self.assertEqual(deliveries[0]["destinatario"], "supervisor@flplasticos.com")

            with connect(db_path) as reopened:
                init_db(reopened)
                counts = {
                    "clientes": reopened.execute("SELECT COUNT(*) AS total FROM clientes").fetchone()["total"],
                    "unidades": reopened.execute("SELECT COUNT(*) AS total FROM unidades").fetchone()["total"],
                    "cameras": reopened.execute("SELECT COUNT(*) AS total FROM cameras").fetchone()["total"],
                    "machines": reopened.execute("SELECT COUNT(*) AS total FROM machine_monitors").fetchone()["total"],
                    "recipients": reopened.execute("SELECT COUNT(*) AS total FROM alert_recipients").fetchone()["total"],
                }
        self.assertEqual(counts, {"clientes": 1, "unidades": 1, "cameras": 1, "machines": 1, "recipients": 1})

    def test_user_cannot_access_other_client_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _db_path, test_connect = self.make_db(temp_dir)
            with test_connect() as connection:
                cliente_a = criar_cliente(connection, "Cliente A")
                unidade_a = criar_unidade(connection, cliente_a, "Unidade A")
                camera_a = criar_camera(connection, unidade_a, "Camera A", cliente_id=cliente_a)
                cliente_b = criar_cliente(connection, "Cliente B")
                unidade_b = criar_unidade(connection, cliente_b, "Unidade B")
                camera_b = criar_camera(connection, unidade_b, "Camera B", cliente_id=cliente_b)
                create_user(connection, "admin-a@example.com", "senha", "admin_cliente", cliente_a, "Admin A")
            with patch("app.api.connect", test_connect):
                client = TestClient(api)
                client.post("/auth/login", json={"email": "admin-a@example.com", "senha": "senha"})
                cameras = client.get("/cameras/estado").json()
                blocked = client.get(f"/cameras/{camera_b}/areas")
                allowed = client.get(f"/cameras/{camera_a}/areas")
        self.assertEqual([camera["nome"] for camera in cameras], ["Camera A"])
        self.assertEqual(blocked.status_code, 403)
        self.assertEqual(allowed.status_code, 200)


if __name__ == "__main__":
    unittest.main()
