#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

export CAMPEX_EMAIL_MODE="${CAMPEX_EMAIL_MODE:-console}"
export CAMPEX_VISION_LAB_PORT="${CAMPEX_VISION_LAB_PORT:-8011}"

echo "Campex Local Vision Lab"
echo "URL: http://127.0.0.1:${CAMPEX_VISION_LAB_PORT}"
echo "SQLite isolado: ${CAMPEX_VISION_LAB_DB:-data/vision_lab.db}"
echo "Evidencias isoladas: ${CAMPEX_VISION_LAB_EVIDENCE:-data/vision_lab_evidence}"

python3 tools/vision_lab.py
