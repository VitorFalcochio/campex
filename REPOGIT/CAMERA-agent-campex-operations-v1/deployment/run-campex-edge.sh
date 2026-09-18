#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${ROOT}/.venv/bin/python"
LOG_DIR="${ROOT}/logs"

mkdir -p "${LOG_DIR}"

if [ ! -x "${PYTHON}" ]; then
  echo "Campex Edge configuration error:" >&2
  echo "Python da .venv não encontrado em ${PYTHON}. Rode a instalação antes de iniciar o serviço." >&2
  exit 2
fi

cd "${ROOT}"

"${PYTHON}" manage.py edge-config-check

exec "${PYTHON}" manage.py run-edge-production
