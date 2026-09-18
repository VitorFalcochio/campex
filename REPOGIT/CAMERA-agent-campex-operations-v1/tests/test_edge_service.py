from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import cv2
import numpy as np

from app.database import connect, init_db
from app.models import criar_camera, criar_cliente, criar_dispositivo, criar_unidade
from edge_agent.event_sender import enqueue_event, pending_count
from edge_agent.service import EdgeSupervisor, edge_status


def make_video(path: Path, color: int = 255) -> None:
    out = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (80, 60))
    for _ in range(12):
        frame = np.full((60, 80, 3), color, dtype=np.uint8)
        out.write(frame)
    out.release()


class EventHandler(BaseHTTPRequestHandler):
    received = 0

    def do_POST(self) -> None:
        _ = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        EventHandler.received += 1
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"id": "evt_test"}).encode("utf-8"))

    def log_message(self, _format: str, *args: object) -> None:
        return


class EdgeServiceTest(unittest.TestCase):
    def test_edge_runs_two_cameras_and_isolates_failed_camera(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "edge.sqlite3"
            video_a = root / "a.mp4"
            video_b = root / "b.mp4"
            make_video(video_a, 100)
            make_video(video_b, 200)
            with connect(db_path) as connection:
                init_db(connection)
                cliente_id = criar_cliente(connection, "Cliente")
                unidade_id = criar_unidade(connection, cliente_id, "Unidade")
                edge_id = criar_dispositivo(connection, unidade_id, "Edge 1")
                criar_camera(
                    connection,
                    unidade_id,
                    "Camera A",
                    dispositivo_id=edge_id,
                    config_ref=str(video_a),
                    cliente_id=cliente_id,
                    edge_id=edge_id,
                    source_type="file",
                )
                criar_camera(
                    connection,
                    unidade_id,
                    "Camera B",
                    dispositivo_id=edge_id,
                    config_ref=str(video_b),
                    cliente_id=cliente_id,
                    edge_id=edge_id,
                    source_type="file",
                )
                criar_camera(
                    connection,
                    unidade_id,
                    "Camera Com Falha",
                    dispositivo_id=edge_id,
                    config_ref=str(root / "nao_existe.mp4"),
                    cliente_id=cliente_id,
                    edge_id=edge_id,
                    source_type="file",
                )

            supervisor = EdgeSupervisor(edge_id=edge_id, db_path=db_path, heartbeat_seconds=0.2)
            thread = threading.Thread(target=supervisor.run_forever)
            thread.start()
            time.sleep(1.2)
            supervisor.shutdown()
            thread.join(timeout=5)

            status = edge_status(edge_id, db_path)
            frames = {camera["nome"]: int(camera.get("frames_processados") or 0) for camera in status["cameras"]}
            failed = [camera for camera in status["cameras"] if camera["nome"] == "Camera Com Falha"][0]

        self.assertGreater(frames["Camera A"], 0)
        self.assertGreater(frames["Camera B"], 0)
        self.assertEqual(failed["status"], "offline")
        self.assertEqual(status["cameras_total"], 3)

    def test_pending_queue_is_sent_when_api_returns(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "queue.sqlite3"
            with sqlite3.connect(db_path) as connection:
                connection.row_factory = sqlite3.Row
                enqueue_event(connection, {"cliente_id": "cli", "unidade_id": "uni", "camera_id": "cam", "tipo": "test"})
                self.assertEqual(pending_count(connection), 1)

            EventHandler.received = 0
            server = HTTPServer(("127.0.0.1", 0), EventHandler)
            port = server.server_port
            server_thread = threading.Thread(target=server.serve_forever)
            server_thread.start()
            try:
                supervisor = EdgeSupervisor(
                    edge_id="edge_queue",
                    db_path=db_path,
                    api_url=f"http://127.0.0.1:{port}",
                    heartbeat_seconds=0.2,
                )
                thread = threading.Thread(target=supervisor.run_forever)
                thread.start()
                time.sleep(0.5)
                supervisor.shutdown()
                thread.join(timeout=5)
            finally:
                server.shutdown()
                server_thread.join(timeout=5)
                server.server_close()

            with sqlite3.connect(db_path) as connection:
                connection.row_factory = sqlite3.Row
                remaining = pending_count(connection)

        self.assertEqual(remaining, 0)
        self.assertEqual(EventHandler.received, 1)


if __name__ == "__main__":
    unittest.main()
