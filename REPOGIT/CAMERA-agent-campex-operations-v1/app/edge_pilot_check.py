from __future__ import annotations

import os
import re
import sqlite3
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.camera_rtsp import build_rtsp_url
from app.config import API_PORT, DATABASE_PATH, EVIDENCE_DIR, ROOT
from app.database import connect, init_db
from app.edge_config import EdgeConfigError, validate_edge_config
from app.edge_service import service_status
from app.models import listar_machine_monitors_ativos_camera, obter_camera, ultimo_edge_heartbeat
from app.security import mask_sensitive_error
from edge_agent.camera_check import check_camera
from edge_agent.sync_outbox import pending_sync_count


PASS = "PASS"
ATTENTION = "ATTENTION"
BLOCKED = "BLOCKED"
NOT_CONFIGURED = "NOT CONFIGURED"

RECENT_SECONDS = 90
OUTBOX_ATTENTION_THRESHOLD = 100
FATAL_LOG_PATTERNS = (
    "traceback",
    "fatal",
    "campex edge configuration error",
    "credential key",
    "credencial criptografada invalida",
)
SECRET_NAMES = ("CAMPEX_CREDENTIAL_KEY", "CAMPEX_EDGE_SECRET")


@dataclass(frozen=True)
class PilotCheckItem:
    label: str
    status: str
    detail: str = ""
    core: bool = True


@dataclass(frozen=True)
class PilotCheckReport:
    items: list[PilotCheckItem]
    result: str
    reason: str | None = None
    action: str | None = None

    @property
    def exit_code(self) -> int:
        return 2 if self.result == "BLOCKED" else 0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _recent(value: object, max_age_seconds: int = RECENT_SECONDS) -> bool:
    parsed = _parse_dt(value)
    return bool(parsed and (_now() - parsed).total_seconds() <= max_age_seconds)


def _safe(text: object) -> str:
    value = str(text or "")
    for name in SECRET_NAMES:
        secret = os.getenv(name)
        if secret:
            value = value.replace(secret, "***")
    value = re.sub(r"(rts?p://)([^/@\s:]+):([^/@\s]+)@", r"\1***:***@", value, flags=re.IGNORECASE)
    return mask_sensitive_error(value) or ""


def _http_json(url: str, timeout: float) -> tuple[int, Any | None, str | None]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            if "application/json" not in response.headers.get("content-type", ""):
                return response.status, None, body[:160]
            import json

            return response.status, json.loads(body), None
    except urllib.error.HTTPError as exc:
        return exc.code, None, _safe(exc.reason)
    except Exception as exc:
        return 0, None, _safe(exc)


def _service_running() -> tuple[bool, str]:
    result = service_status()
    message = result.message.lower()
    if not result.ok:
        return False, result.message
    if "could not find service" in message or "não carregado" in message or "not loaded" in message:
        return False, result.message
    if "state = running" in message or "pid =" in message or "serviço carregado" in message:
        return True, "serviço carregado"
    return False, result.message


def _camera_source(camera: dict[str, Any]) -> str | None:
    config_ref = str(camera.get("config_ref") or "").strip()
    if config_ref:
        return config_ref
    if camera.get("rtsp_host"):
        return build_rtsp_url(
            host=camera.get("rtsp_host"),
            port=camera.get("rtsp_port") or 554,
            path=camera.get("rtsp_path"),
            username=camera.get("rtsp_username"),
            password=camera.get("rtsp_password"),
        ).url
    return None


def _active_camera(connection: sqlite3.Connection, edge_id: str | None) -> dict[str, Any] | None:
    values: list[Any] = []
    edge_clause = ""
    if edge_id:
        edge_clause = "AND (edge_id = ? OR dispositivo_id = ? OR edge_id IS NULL)"
        values.extend([edge_id, edge_id])
    row = connection.execute(
        f"""
        SELECT id
        FROM cameras
        WHERE ativa = 1
          AND status != 'inativa'
          {edge_clause}
        ORDER BY nome
        LIMIT 1
        """,
        values,
    ).fetchone()
    if row is None:
        return None
    return obter_camera(connection, row["id"], include_secret=True)


def _stream_status(connection: sqlite3.Connection, camera_id: str, health: dict[str, Any] | None) -> dict[str, Any]:
    streams = (((health or {}).get("workers") or {}).get("streams") or []) if isinstance(health, dict) else []
    for stream in streams:
        if str(stream.get("camera_id")) == str(camera_id):
            return dict(stream)
    row = connection.execute("SELECT ultimo_frame, status, frames_processados, ultimo_erro FROM cameras WHERE id = ?", (camera_id,)).fetchone()
    if row is None:
        return {}
    return {
        "camera_id": camera_id,
        "status": row["status"],
        "last_frame_at": row["ultimo_frame"],
        "analysis_frames": row["frames_processados"],
        "error": row["ultimo_erro"],
    }


def _recent_fatal_logs(log_dir: Path = ROOT / "logs", max_lines: int = 120) -> str | None:
    for path in [log_dir / "edge.stderr.log", log_dir / "edge.stdout.log"]:
        if not path.exists():
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-max_lines:]
        except OSError:
            continue
        for line in reversed(lines):
            lowered = line.lower()
            if any(pattern in lowered for pattern in FATAL_LOG_PATTERNS):
                return _safe(line)[:160]
    return None


def run_edge_pilot_check(
    *,
    db_path: Path | None = None,
    api_url: str | None = None,
    camera_timeout: float = 5.0,
    http_timeout: float = 2.0,
) -> PilotCheckReport:
    items: list[PilotCheckItem] = []
    database_path = Path(db_path or DATABASE_PATH)
    edge_id = os.getenv("CAMPEX_EDGE_ID")

    def add(label: str, status: str, detail: str = "", *, core: bool = True) -> None:
        items.append(PilotCheckItem(label=label, status=status, detail=_safe(detail), core=core))

    try:
        config = validate_edge_config(db_path=database_path, edge_id=edge_id)
        edge_id = config.edge_id
        add("Configuração", PASS)
    except EdgeConfigError as exc:
        add("Configuração", BLOCKED, str(exc))
        return _finalize(items, "Configuração inválida.", "Abra o arquivo de ambiente canônico e corrija a configuração do Edge.")

    running, service_detail = _service_running()
    add("Serviço", PASS if running else BLOCKED, "" if running else "serviço local não está rodando")

    health_url = (api_url or f"http://127.0.0.1:{API_PORT}").rstrip("/") + "/health"
    health_code, health_payload, health_error = _http_json(health_url, http_timeout)
    add("/health", PASS if health_code == 200 else BLOCKED, "" if health_code == 200 else (health_error or "API local não respondeu"))

    connection: sqlite3.Connection | None = None
    camera: dict[str, Any] | None = None
    stream: dict[str, Any] = {}
    try:
        connection = connect(database_path)
        init_db(connection)
        connection.execute("SELECT 1").fetchone()
        add("Banco", PASS)

        camera = _active_camera(connection, edge_id)
        if camera is None:
            add("Câmera cadastrada", BLOCKED, "nenhuma câmera ativa cadastrada")
        else:
            add("Câmera cadastrada", PASS)
            try:
                source = _camera_source(camera)
                if not source:
                    add("Credencial da câmera", BLOCKED, "câmera sem fonte de vídeo")
                    add("Câmera / RTSP", BLOCKED, "câmera sem fonte de vídeo")
                else:
                    add("Credencial da câmera", PASS)
                    rtsp_result = check_camera(source, timeout_seconds=camera_timeout)
                    if rtsp_result.conexao_realizada and rtsp_result.video_recebido:
                        add("Câmera / RTSP", PASS)
                    else:
                        add("Câmera / RTSP", BLOCKED, rtsp_result.motivo_erro or "câmera inacessível nesta rede")
            except Exception as exc:
                add("Credencial da câmera", BLOCKED, str(exc))
                add("Câmera / RTSP", BLOCKED, "câmera inacessível nesta rede")

            stream = _stream_status(connection, str(camera["id"]), health_payload if isinstance(health_payload, dict) else None)
            stream_recent = _recent(stream.get("last_frame_at")) and str(stream.get("status") or "").lower() in {"online", "conectado"}
            add("Stream", PASS if stream_recent else BLOCKED, "" if stream_recent else "sem frame recente")

            inference_recent = _recent(stream.get("last_analysis_at")) or int(stream.get("analysis_frames") or stream.get("machine_frames_analyzed") or 0) > 0
            add("Inferência", PASS if inference_recent else BLOCKED, "" if inference_recent else "sem frame processado recente")

            monitors = listar_machine_monitors_ativos_camera(connection, str(camera["id"]))
            add("Machine monitor", PASS if monitors else NOT_CONFIGURED, "" if monitors else "não configurado", core=False)

        heartbeat = ultimo_edge_heartbeat(connection, edge_id)
        heartbeat_ok = bool(heartbeat and _recent(heartbeat.get("heartbeat_at")))
        add("Heartbeat", PASS if heartbeat_ok else BLOCKED, "" if heartbeat_ok else "sem heartbeat recente")

        try:
            EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
            test_file = EVIDENCE_DIR / ".edge_pilot_check"
            test_file.write_text("ok", encoding="utf-8")
            test_file.unlink(missing_ok=True)
            add("Evidências", PASS)
        except OSError as exc:
            add("Evidências", BLOCKED, str(exc))

        outbox = pending_sync_count(connection)
        if outbox >= OUTBOX_ATTENTION_THRESHOLD:
            add("Outbox", ATTENTION, f"{outbox} pendentes", core=False)
        else:
            add("Outbox", PASS, f"{outbox} pendentes", core=False)
    except sqlite3.Error as exc:
        add("Banco", BLOCKED, str(exc))
    finally:
        if connection is not None:
            connection.close()

    fatal_log = _recent_fatal_logs()
    add("Logs recentes", BLOCKED if fatal_log else PASS, fatal_log or "", core=True)
    return _finalize(items, _blocked_reason(items), _suggested_action(items))


def _blocked_reason(items: list[PilotCheckItem]) -> str | None:
    for item in items:
        if item.core and item.status == BLOCKED:
            if item.label == "Câmera / RTSP":
                return "A câmera não está acessível nesta rede."
            if item.label == "Stream":
                return "O stream ainda não recebeu frame recente."
            if item.label == "Inferência":
                return "A inferência ainda não processou frame recente."
            if item.label == "Serviço":
                return "O serviço local do Campex Edge não está rodando."
            if item.label == "Banco":
                return "O banco local não abriu corretamente."
            return item.detail or f"{item.label} bloqueado."
    return None


def _suggested_action(items: list[PilotCheckItem]) -> str | None:
    labels = {item.label: item for item in items if item.status == BLOCKED}
    if "Câmera / RTSP" in labels:
        return "Verifique se o Mac está conectado à rede da fábrica e se a câmera está ligada."
    if "Serviço" in labels:
        return "Rode python manage.py edge-service start."
    if "Banco" in labels:
        return "Confira DATABASE_PATH no arquivo de ambiente canônico."
    if "Configuração" in labels:
        return "Corrija CAMPEX_EDGE_ID, DATABASE_PATH e CAMPEX_CREDENTIAL_KEY."
    return None


def _finalize(items: list[PilotCheckItem], reason: str | None, action: str | None) -> PilotCheckReport:
    core_blocked = any(item.core and item.status == BLOCKED for item in items)
    attention = any(item.status == ATTENTION or (not item.core and item.status == NOT_CONFIGURED) for item in items)
    if core_blocked:
        result = "BLOCKED"
    elif attention:
        result = "READY WITH ATTENTION"
    else:
        result = "READY FOR PILOT"
    return PilotCheckReport(items=items, result=result, reason=reason if core_blocked else None, action=action if core_blocked else None)


def format_edge_pilot_check(report: PilotCheckReport) -> str:
    width = max([len(item.label) for item in report.items] + [10])
    lines = ["CAMPEX EDGE — PILOT CHECK", ""]
    for item in report.items:
        dots = "." * max(1, 22 - len(item.label))
        detail = f" — {item.detail}" if item.detail else ""
        lines.append(f"{item.label} {dots} {item.status}{detail}")
    lines.extend(["", f"RESULTADO: {report.result}"])
    if report.reason:
        lines.extend(["Motivo:", report.reason])
    if report.action:
        lines.extend(["Ação sugerida:", report.action])
    return "\n".join(lines)
