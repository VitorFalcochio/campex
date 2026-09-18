from __future__ import annotations

import os
from pathlib import Path

from app.env import load_env_file

load_env_file()

ROOT = Path(__file__).resolve().parents[1]


def env(name: str, default: str) -> str:
    return os.getenv(name, default)


def path_env(name: str, default: Path) -> Path:
    value = os.getenv(name)
    return Path(value) if value else default


DATABASE_PATH = path_env("DATABASE_PATH", ROOT / "data" / "visual_ops_product.sqlite3")
EVIDENCE_DIR = path_env("CAMPEX_EVIDENCE_DIR", ROOT / "data" / "evidence")
API_HOST = env("API_HOST", "127.0.0.1") or "127.0.0.1"
API_PORT = int(env("API_PORT", "8000") or "8000")
LOG_DIR = ROOT / "logs"


def storage_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)
