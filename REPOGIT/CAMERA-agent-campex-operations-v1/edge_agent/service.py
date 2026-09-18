from __future__ import annotations

import logging
import os
import re
import shutil
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.database import connect, init_db
from app.models import (
    atualizar_camera_operacao,
    listar_cameras_do_edge,
    registrar_edge_heartbeat,
    registrar_edge_metricas,
    ultima_metrica_edge,
    ultimo_edge_heartbeat,
)
from edge_agent.camera_connector import CameraSource, UniversalCameraConnector, safe_source_ref
from edge_agent.camera_connector import detect_source_type
from edge_agent.event_sender import flush_queue
from edge_agent.sync_outbox import pending_sync_count
from edge_agent.health import mark_edge_contact
from shared.schemas import now_iso

logger = logging.getLogger(__name__)


def sanitize_env_key(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "_", value).upper()


def resolve_camera_source(camera: dict[str, Any]) -> str | int | None:
    camera_id = str(camera["id"])
    env_name = f"CAMERA_SOURCE_{sanitize_env_key(camera_id)}"
    if os.getenv(env_name):
        return os.getenv(env_name)
    config_ref = camera.get("config_ref")
    if config_ref:
        if str(config_ref).startswith("env:"):
            return os.getenv(str(config_ref)[4:])
        return str(config_ref)
    return None


def resource_usage() -> tuple[float | None, float | None]:
    try:
        import psutil
    except Exception:
        return None, None
    process = psutil.Process(os.getpid())
    cpu = process.cpu_percent(interval=None)
    memory = process.memory_percent()
    return round(cpu, 2), round(memory, 2)


@dataclass
class CameraRuntime:
    camera: dict[str, Any]
    thread: threading.Thread | None = None
    stop_event: threading.Event | None = None
    restarts: int = 0
    last_error: str | None = None
    frames: int = 0


class EdgeCameraWorker:
    def __init__(self, db_path: Path, camera: dict[str, Any], stop_event: threading.Event) -> None:
        self.db_path = db_path
        self.camera = camera
        self.stop_event = stop_event
        self.frames_processed = 0

    def run(self) -> None:
        source = resolve_camera_source(self.camera)
        camera_id = str(self.camera["id"])
        if source is None:
            with connect(self.db_path) as connection:
                init_db(connection)
                atualizar_camera_operacao(connection, camera_id, "offline", ultimo_erro="Fonte da camera nao configurada.")
            return

        connector = UniversalCameraConnector(
            CameraSource(
                camera_id=camera_id,
                source=source,
                cliente_id=self.camera.get("cliente_id"),
                unidade_id=self.camera.get("unidade_id"),
                edge_id=self.camera.get("edge_id") or self.camera.get("dispositivo_id"),
                name=self.camera.get("nome"),
                reconnect_seconds=2.0,
            )
        )
        last_status = "offline"
        try:
            while not self.stop_event.is_set():
                if connector.capture is None or not connector.capture.isOpened():
                    if not connector.open():
                        last_status = "offline"
                        with connect(self.db_path) as connection:
                            init_db(connection)
                            atualizar_camera_operacao(
                                connection,
                                camera_id,
                                "offline",
                                ultimo_erro=connector.info.error or "Fonte indisponivel.",
                            )
                        self.stop_event.wait(2.0)
                        continue

                ok, frame = connector.capture.read() if connector.capture else (False, None)
                if ok and frame is not None:
                    reconnected = last_status != "online"
                    connector.info.status = "online"
                    connector.info.last_frame_at = now_iso()
                    connector.info.height, connector.info.width = frame.shape[:2]
                    connector.info.error = None
                    last_status = "online"
                    self.frames_processed += 1
                    with connect(self.db_path) as connection:
                        init_db(connection)
                        atualizar_camera_operacao(
                            connection,
                            camera_id,
                            "online",
                            ultimo_frame=connector.info.last_frame_at or now_iso(),
                            ultimo_erro=None,
                            reconectar=reconnected,
                            frames_increment=1,
                        )
                    continue

                if self.stop_event.is_set():
                    break
                connector.close()
                if detect_source_type(source).value == "file":
                    continue
                last_status = "offline"
                connector.info.status = "offline"
                connector.info.error = "Stream parou de entregar frames."
                with connect(self.db_path) as connection:
                    init_db(connection)
                    atualizar_camera_operacao(
                        connection,
                        camera_id,
                        "offline",
                        ultimo_erro=connector.info.error or "Stream encerrado.",
                    )
                self.stop_event.wait(2.0)
        finally:
            connector.stop()


class EdgeSupervisor:
    def __init__(
        self,
        edge_id: str,
        db_path: Path,
        api_url: str | None = None,
        heartbeat_seconds: float = 10.0,
        restart_delay_seconds: float = 3.0,
        max_restarts: int = 20,
    ) -> None:
        self.edge_id = edge_id
        self.db_path = db_path
        self.api_url = api_url
        self.heartbeat_seconds = heartbeat_seconds
        self.restart_delay_seconds = restart_delay_seconds
        self.max_restarts = max_restarts
        self.stop_event = threading.Event()
        self.started_at = time.monotonic()
        self.runtimes: dict[str, CameraRuntime] = {}

    def load_cameras(self) -> list[dict[str, Any]]:
        with connect(self.db_path) as connection:
            init_db(connection)
            return listar_cameras_do_edge(connection, self.edge_id)

    def start_camera(self, camera: dict[str, Any]) -> None:
        camera_id = str(camera["id"])
        camera_stop = threading.Event()
        worker = EdgeCameraWorker(self.db_path, camera, camera_stop)

        def target() -> None:
            try:
                worker.run()
            except Exception as exc:
                logger.exception("Camera %s encerrou com erro: %s", camera_id, exc)
                runtime = self.runtimes.get(camera_id)
                if runtime:
                    runtime.last_error = str(exc)
                with connect(self.db_path) as connection:
                    init_db(connection)
                    atualizar_camera_operacao(connection, camera_id, "offline", ultimo_erro=str(exc))

        thread = threading.Thread(target=target, name=f"camera-{camera_id}", daemon=True)
        self.runtimes[camera_id] = CameraRuntime(camera=camera, thread=thread, stop_event=camera_stop)
        thread.start()

    def ensure_workers(self) -> None:
        known = {camera["id"]: camera for camera in self.load_cameras()}
        for camera_id, camera in known.items():
            runtime = self.runtimes.get(camera_id)
            if runtime is None:
                self.start_camera(camera)
                continue
            if runtime.thread and runtime.thread.is_alive():
                continue
            if runtime.restarts >= self.max_restarts:
                logger.error("Camera %s excedeu limite de reinicios.", camera_id)
                continue
            runtime.restarts += 1
            time.sleep(self.restart_delay_seconds)
            self.start_camera(camera)

    def heartbeat(self) -> None:
        with connect(self.db_path) as connection:
            init_db(connection)
            mark_edge_contact(connection, self.edge_id, "online")
            cameras = listar_cameras_do_edge(connection, self.edge_id)
            active = sum(1 for camera in cameras if camera.get("status") == "online")
            frames = sum(int(camera.get("frames_processados") or 0) for camera in cameras)
            last_frame = max([str(camera.get("ultimo_frame") or "") for camera in cameras], default=None) or None
            capture_fps_values = [float(camera.get("fps") or 0) for camera in cameras if camera.get("fps") is not None]
            capture_fps = round(sum(capture_fps_values) / len(capture_fps_values), 2) if capture_fps_values else None
            sync_pending = pending_sync_count(connection)
            disk = shutil.disk_usage(self.db_path.parent if self.db_path.parent.exists() else Path("."))
            cpu, memory = resource_usage()
            registrar_edge_metricas(
                connection,
                self.edge_id,
                uptime_seconds=time.monotonic() - self.started_at,
                cpu_percent=cpu,
                memory_percent=memory,
                active_cameras=active,
                frames_processed=frames,
            )
            registrar_edge_heartbeat(
                connection,
                self.edge_id,
                heartbeat_at=now_iso(),
                camera_online=active > 0,
                last_frame_at=last_frame,
                capture_fps=capture_fps,
                inference_fps=None,
                frames_analyzed=frames,
                outbox_pending=sync_pending,
                disk_free_bytes=int(disk.free),
                disk_used_percent=round((disk.used / disk.total) * 100, 2) if disk.total else None,
            )
            if self.api_url:
                flush_queue(connection, self.api_url)

    def run_forever(self) -> None:
        logger.info("Edge %s iniciando.", self.edge_id)
        with connect(self.db_path) as connection:
            init_db(connection)
            mark_edge_contact(connection, self.edge_id, "online")

        try:
            while not self.stop_event.is_set():
                self.ensure_workers()
                self.heartbeat()
                self.stop_event.wait(self.heartbeat_seconds)
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        logger.info("Edge %s encerrando.", self.edge_id)
        self.stop_event.set()
        for runtime in self.runtimes.values():
            if runtime.stop_event:
                runtime.stop_event.set()
        for runtime in self.runtimes.values():
            if runtime.thread:
                runtime.thread.join(timeout=5.0)
        with connect(self.db_path) as connection:
            init_db(connection)
            mark_edge_contact(connection, self.edge_id, "offline")


def edge_status(edge_id: str, db_path: Path) -> dict[str, Any]:
    with connect(db_path) as connection:
        init_db(connection)
        device = connection.execute("SELECT * FROM dispositivos WHERE id = ?", (edge_id,)).fetchone()
        cameras = listar_cameras_do_edge(connection, edge_id)
        metric = ultima_metrica_edge(connection, edge_id)
        heartbeat = ultimo_edge_heartbeat(connection, edge_id)
        pending = pending_sync_count(connection)
    online = [camera for camera in cameras if camera.get("status") == "online"]
    offline = [camera for camera in cameras if camera.get("status") != "online"]
    return {
        "edge_id": edge_id,
        "edge_status": device["status"] if device else "nao_cadastrado",
        "ultimo_contato": device["ultimo_contato"] if device else None,
        "uptime_seconds": metric["uptime_seconds"] if metric else 0,
        "cpu_percent": metric["cpu_percent"] if metric else None,
        "memory_percent": metric["memory_percent"] if metric else None,
        "ultimo_heartbeat": heartbeat,
        "cameras": cameras,
        "cameras_total": len(cameras),
        "cameras_online": len(online),
        "cameras_offline": len(offline),
        "eventos_pendentes": pending,
    }
