from __future__ import annotations

import os
import shutil
import sqlite3
import tarfile
import time
from pathlib import Path
from typing import Any
from datetime import datetime, timezone

from app.config import DATABASE_PATH, EVIDENCE_DIR, ROOT
from app.database import connect, init_db
from app.models import get_installation_state, listar, listar_alert_deliveries, listar_eventos_filtrados, listar_technical_notices


def _recent_iso(value: object, max_age_seconds: float = 15.0) -> bool:
    if not value:
        return False
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() <= max_age_seconds
    except Exception:
        return False


def _runtime_by_camera(runtime_statuses: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    return {str(item.get("camera_id")): item for item in (runtime_statuses or []) if item.get("camera_id")}


def _stream_online(stream: dict[str, Any] | None) -> bool:
    return bool(stream and stream.get("status") == "online" and _recent_iso(stream.get("last_frame_at")))


def _stream_inference_active(stream: dict[str, Any] | None) -> bool:
    if not stream or not _recent_iso(stream.get("last_analysis_at")):
        return False
    return bool(
        stream.get("ai_status") == "ativa"
        or float(stream.get("analysis_fps") or 0) > 0
        or int(stream.get("analysis_frames") or stream.get("machine_frames_analyzed") or 0) > 0
    )


def health_snapshot(db_path: Path | None = None, runtime_statuses: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    path = db_path or DATABASE_PATH
    disk = shutil.disk_usage(ROOT)
    runtime = _runtime_by_camera(runtime_statuses)
    data: dict[str, Any] = {
        "api": "online",
        "database": "unknown",
        "disk_free_gb": round(disk.free / (1024 ** 3), 2),
        "cameras_online": 0,
        "cameras_offline": 0,
        "ai_active": 0,
        "ai_inactive": 0,
        "ultimo_frame": None,
        "ultimo_evento": None,
        "ultimo_email": None,
        "erros_recentes": [],
    }
    try:
        with connect(path) as connection:
            init_db(connection)
            connection.execute("SELECT 1").fetchone()
            data["database"] = "online"
            cameras = listar(connection, "cameras")
            if runtime_statuses is not None:
                active_cameras = [c for c in cameras if c.get("ativa", True)]
                data["cameras_online"] = len([c for c in active_cameras if _stream_online(runtime.get(str(c.get("id"))))])
                data["cameras_offline"] = len(active_cameras) - data["cameras_online"]
                data["ai_active"] = len([c for c in active_cameras if _stream_inference_active(runtime.get(str(c.get("id"))))])
                data["ai_inactive"] = len(active_cameras) - data["ai_active"]
                frames = [stream.get("last_frame_at") for stream in runtime.values() if _stream_online(stream)]
            else:
                data["cameras_online"] = len([c for c in cameras if c.get("status") == "online"])
                data["cameras_offline"] = len([c for c in cameras if c.get("status") != "online"])
                data["ai_active"] = len([c for c in cameras if c.get("analysis_enabled")])
                data["ai_inactive"] = len(cameras) - data["ai_active"]
                frames = [c.get("ultimo_frame") for c in cameras if c.get("ultimo_frame")]
            data["ultimo_frame"] = max(frames) if frames else None
            eventos = listar_eventos_filtrados(connection)
            data["ultimo_evento"] = eventos[0]["inicio"] if eventos else None
            deliveries = listar_alert_deliveries(connection, status="sent")
            data["ultimo_email"] = deliveries[0]["sent_at"] if deliveries else None
            data["erros_recentes"] = [n.get("erro") for n in listar_technical_notices(connection)[:5] if n.get("erro")]
    except sqlite3.Error as exc:
        data["database"] = "erro"
        data["erros_recentes"].append(str(exc)[:200])
    return data


def acceptance_checklist(db_path: Path | None = None, runtime_statuses: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    path = db_path or DATABASE_PATH
    runtime = _runtime_by_camera(runtime_statuses)
    with connect(path) as connection:
        init_db(connection)
        state = get_installation_state(connection)
        cameras = listar(connection, "cameras")
        active_cameras = [c for c in cameras if c.get("ativa", True)]
        runtime_camera_online = any(_stream_online(runtime.get(str(c.get("id")))) for c in active_cameras) if runtime_statuses is not None else None
        runtime_inference_active = any(_stream_inference_active(runtime.get(str(c.get("id")))) for c in active_cameras) if runtime_statuses is not None else None
        events = listar_eventos_filtrados(connection)
        deliveries = listar_alert_deliveries(connection)
        checks = {
            "login": bool(connection.execute("SELECT COUNT(*) AS total FROM users").fetchone()["total"]),
            "isolamento_clientes": bool(connection.execute("SELECT COUNT(*) AS total FROM clientes").fetchone()["total"]),
            "camera_conectada": runtime_camera_online if runtime_camera_online is not None else any(c.get("status") == "online" for c in cameras),
            "transmissao_ao_vivo": bool(cameras),
            "ia_ativa": runtime_inference_active if runtime_inference_active is not None else any(c.get("analysis_enabled") for c in cameras) or state.get("ia_ativa") == "ok",
            "area_criada": bool(connection.execute("SELECT COUNT(*) AS total FROM monitored_areas").fetchone()["total"]),
            "ocorrencia_automatica": bool(events),
            "evidencia_salva": any(e.get("midia_path") for e in events),
            "alerta_no_painel": bool(deliveries) or state.get("alerta_no_painel") == "ok",
            "email_de_teste": any(d.get("is_test") for d in deliveries),
            "recuperacao_reinicio": state.get("recuperacao_reinicio") == "ok",
        }
    return {"checks": checks, "pendentes": [key for key, ok in checks.items() if not ok]}


def create_backup(output_dir: Path, db_path: Path | None = None) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    archive = output_dir / f"campex_backup_{stamp}.tar.gz"
    db = db_path or DATABASE_PATH
    with tarfile.open(archive, "w:gz") as tar:
        if db.exists():
            tar.add(db, arcname="data/visual_ops_product.sqlite3")
        for name in (".env.example",):
            path = ROOT / name
            if path.exists():
                tar.add(path, arcname=name)
    return archive


def restore_backup(archive: Path, target_root: Path | None = None) -> None:
    root = target_root or ROOT
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            if member.name.startswith("/") or ".." in Path(member.name).parts:
                raise ValueError("Backup contem caminho inseguro.")
        tar.extractall(root)


def prune_old_evidence(days: int, confirm: bool = False) -> list[Path]:
    if not confirm:
        raise ValueError("Confirme explicitamente para apagar evidencias antigas.")
    cutoff = time.time() - (days * 86400)
    evidence_root = EVIDENCE_DIR
    removed: list[Path] = []
    if not evidence_root.exists():
        return removed
    for path in evidence_root.rglob("*.jpg"):
        if path.stat().st_mtime < cutoff:
            path.unlink()
            removed.append(path)
    return removed
