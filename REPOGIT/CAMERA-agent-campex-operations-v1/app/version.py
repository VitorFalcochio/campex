from __future__ import annotations

import os
from pathlib import Path


DEFAULT_VERSION = "0.1.0-rc1"
VERSION_FILE = Path(__file__).resolve().parents[1] / ".campex_version"


def current_version(root: Path | None = None) -> str:
    explicit = os.getenv("CAMPEX_VERSION", "").strip()
    if explicit:
        return explicit
    path = (root or VERSION_FILE.parent) / ".campex_version"
    try:
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    except OSError:
        pass
    return DEFAULT_VERSION
