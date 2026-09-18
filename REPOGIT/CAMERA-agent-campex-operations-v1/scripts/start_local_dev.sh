#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

HOST="${API_HOST:-127.0.0.1}"
PORT="${API_PORT:-8000}"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 nao encontrado. Instale Python 3 antes de iniciar a Campex."
  exit 1
fi

if python3 - <<PY
import socket
s = socket.socket()
try:
    s.bind(("$HOST", int("$PORT")))
except OSError:
    raise SystemExit(1)
finally:
    s.close()
PY
then
  :
else
  echo "A porta $PORT ja esta em uso em $HOST."
  echo "Feche o processo manualmente ou use outra porta: API_PORT=8001 ./scripts/start_local_dev.sh"
  exit 1
fi

mkdir -p data logs data/evidence

python3 - <<'PY'
from app.database import connect, init_db
with connect() as connection:
    init_db(connection)
print("Banco local inicializado.")
PY

echo "Campex disponivel em http://$HOST:$PORT"
echo "Diagnostico visual em http://$HOST:$PORT/local-diagnostics-view"
echo "Grade multi-camera em http://$HOST:$PORT/live-grid"

exec python3 -m app.main
