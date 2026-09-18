from __future__ import annotations

import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESOLVED_ENV_KEY = "CAMPEX_RESOLVED_ENV_FILE"


def resolve_env_file() -> Path:
    explicit = os.getenv("CAMPEX_ENV_FILE")
    if explicit:
        return Path(explicit).expanduser().resolve()
    return ROOT / ".env"


def load_env_file(path: str | Path | None = None, *, override: bool = False) -> Path:
    env_path = Path(path).expanduser().resolve() if path else resolve_env_file()
    os.environ[RESOLVED_ENV_KEY] = str(env_path)
    if not env_path.exists():
        return env_path
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            continue
        if override or key not in os.environ:
            os.environ[key] = value
    return env_path


def resolved_env_file() -> Path:
    return Path(os.getenv(RESOLVED_ENV_KEY) or resolve_env_file())
