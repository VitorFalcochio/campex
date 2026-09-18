from __future__ import annotations

import os

import uvicorn

from cloud.api import api


def main() -> None:
    host = os.getenv("CLOUD_HOST", "0.0.0.0")
    port = int(os.getenv("PORT", os.getenv("CLOUD_PORT", "8000")))
    print(f"Campex Cloud disponível em http://{host}:{port}")
    uvicorn.run(api, host=host, port=port)


if __name__ == "__main__":
    main()
