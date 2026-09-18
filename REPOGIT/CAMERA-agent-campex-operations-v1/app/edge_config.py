from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.config import DATABASE_PATH, EVIDENCE_DIR
from app.database import connect, init_db
from app.env import resolved_env_file
from app.models import obter_camera
from app.security import require_configured_credential_key


class EdgeConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class EdgeConfigCheck:
    env_file: Path
    edge_id: str
    database_path: Path
    evidence_dir: Path
    database_ok: bool
    credential_key_configured: bool
    camera_credentials_ok: bool
    cameras_checked: int


def _configured_edge_id(edge_id: str | None = None) -> str:
    return str(edge_id or os.getenv("CAMPEX_EDGE_ID") or "").strip()


def validate_edge_config(*, db_path: Path | None = None, edge_id: str | None = None) -> EdgeConfigCheck:
    env_file = resolved_env_file()
    database_path = Path(db_path or DATABASE_PATH)
    evidence_dir = EVIDENCE_DIR
    resolved_edge_id = _configured_edge_id(edge_id)

    try:
        database_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise EdgeConfigError(f"Não foi possível criar o diretório do banco: {database_path.parent}") from exc

    try:
        evidence_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise EdgeConfigError(f"Não foi possível criar o diretório de evidências: {evidence_dir}") from exc

    if not resolved_edge_id:
        raise EdgeConfigError("CAMPEX_EDGE_ID não configurado. Defina o Edge ID no arquivo de ambiente canônico.")

    try:
        require_configured_credential_key()
    except RuntimeError as exc:
        raise EdgeConfigError(str(exc)) from exc

    cameras_checked = 0
    try:
        with connect(database_path) as connection:
            init_db(connection)
            rows = connection.execute(
                """
                SELECT id, nome
                FROM cameras
                WHERE ativa = 1
                  AND rtsp_password_encrypted IS NOT NULL
                  AND rtsp_password_encrypted != ''
                  AND (
                    config_ref IS NOT NULL
                    OR rtsp_host IS NOT NULL
                    OR secure_ref IS NOT NULL
                  )
                ORDER BY nome
                """
            ).fetchall()
            for row in rows:
                cameras_checked += 1
                try:
                    obter_camera(connection, row["id"], include_secret=True)
                except Exception as exc:
                    camera_name = row["nome"] or row["id"]
                    raise EdgeConfigError(
                        "CAMPEX_CREDENTIAL_KEY não consegue abrir a credencial salva "
                        f"da câmera \"{camera_name}\". Confirme que este Edge está usando "
                        "o arquivo de ambiente correto."
                    ) from exc
    except EdgeConfigError:
        raise
    except sqlite3.Error as exc:
        raise EdgeConfigError(f"Banco local não abriu corretamente: {database_path}") from exc

    return EdgeConfigCheck(
        env_file=env_file,
        edge_id=resolved_edge_id,
        database_path=database_path,
        evidence_dir=evidence_dir,
        database_ok=True,
        credential_key_configured=True,
        camera_credentials_ok=True,
        cameras_checked=cameras_checked,
    )


def edge_config_report(*, db_path: Path | None = None, edge_id: str | None = None) -> str:
    check = validate_edge_config(db_path=db_path, edge_id=edge_id)
    return "\n".join(
        [
            "Campex Edge Config",
            f"Environment: {check.env_file}",
            f"Edge ID: {check.edge_id}",
            f"Database: {check.database_path}",
            "Database: OK",
            "Credential key: configured",
            f"Camera credentials: OK ({check.cameras_checked} checked)",
            f"Evidence directory: OK ({check.evidence_dir})",
        ]
    )
