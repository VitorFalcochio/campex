from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.config import get_settings
from backend.database.db import initialize_database


def main() -> None:
    settings = get_settings()
    database_path = initialize_database(settings)
    print(f"CAMPEX database initialized: {database_path}")


if __name__ == "__main__":
    main()
