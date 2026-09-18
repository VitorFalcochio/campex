from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.database import connect, init_db
from app.models import (
    atualizar_evento,
    criar_camera,
    criar_cliente,
    criar_regra,
    criar_unidade,
    listar,
    registrar_evento,
)
from app.reports import daily_report_data, save_daily_report
from edge_agent.event_sender import enqueue_event, flush_queue, init_queue, pending_count


class ProductMvpTest(unittest.TestCase):
    def test_database_customer_camera_event_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "mvp.sqlite3"
            with connect(db_path) as connection:
                init_db(connection)
                cliente_id = criar_cliente(connection, "Cliente Teste")
                unidade_id = criar_unidade(connection, cliente_id, "Unidade 1", "Sao Paulo")
                camera_id = criar_camera(connection, unidade_id, "Camera Linha 1")
                criar_regra(connection, camera_id, "machine_stopped", 60)
                registrar_evento(
                    connection,
                    cliente_id,
                    unidade_id,
                    camera_id,
                    "machine_stopped",
                    inicio="2026-07-15T07:00:00-03:00",
                    operador_presente=False,
                    confianca=0.7,
                )
                event_id = registrar_evento(
                    connection,
                    cliente_id,
                    unidade_id,
                    camera_id,
                    "machine_stopped",
                    inicio="2026-07-15T08:00:00-03:00",
                    fim="2026-07-15T08:10:00-03:00",
                    duracao=600,
                    operador_presente=False,
                    confianca=0.91,
                )
                atualizar_evento(
                    connection,
                    event_id,
                    fim="2026-07-15T08:10:00-03:00",
                    duracao=600,
                    operador_presente=False,
                    confianca=0.95,
                )

                cameras = listar(connection, "cameras")
                report = daily_report_data(connection, "2026-07-15")
                paths = save_daily_report(connection, Path(temp_dir), "2026-07-15")
                json_exists = paths["json"].exists()
                csv_exists = paths["csv"].exists()

        self.assertEqual(len(cameras), 1)
        self.assertEqual(report["quantidade_eventos"], 2)
        self.assertEqual(report["tempo_total_parado"], 600)
        self.assertEqual(report["tempo_parado_sem_operador"], 600)
        self.assertEqual(report["maior_parada"], 600)
        self.assertTrue(json_exists)
        self.assertTrue(csv_exists)

    def test_pending_event_queue_survives_when_api_is_offline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "queue.sqlite3"
            connection = sqlite3.connect(db_path)
            connection.row_factory = sqlite3.Row
            try:
                init_queue(connection)
                enqueue_event(connection, {"cliente_id": "cli_1", "tipo": "machine_stopped"})
                sent = flush_queue(connection, "http://127.0.0.1:9", limit=1)
                pending = pending_count(connection)
            finally:
                connection.close()

        self.assertEqual(sent, 0)
        self.assertEqual(pending, 1)


if __name__ == "__main__":
    unittest.main()
