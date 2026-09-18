from __future__ import annotations

import os

from app.config import DATABASE_PATH
from edge_agent.service import EdgeSupervisor


def main() -> None:
    edge_id = os.getenv("EDGE_ID")
    if not edge_id:
        print("Defina EDGE_ID no ambiente.")
        return
    supervisor = EdgeSupervisor(
        edge_id=edge_id,
        db_path=DATABASE_PATH,
        api_url=os.getenv("API_URL"),
    )
    supervisor.run_forever()


if __name__ == "__main__":
    main()
