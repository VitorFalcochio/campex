#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -f .env ]; then
  cp .env.example .env
  credential_key="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
)"
  python3 - "$credential_key" <<'PY'
from pathlib import Path
import sys
key = sys.argv[1]
path = Path(".env")
lines = []
for line in path.read_text(encoding="utf-8").splitlines():
    if line.startswith("CAMPEX_CREDENTIAL_KEY="):
        lines.append(f"CAMPEX_CREDENTIAL_KEY={key}")
    elif line.startswith("CAMPEX_SECRET_KEY="):
        lines.append(f"CAMPEX_SECRET_KEY={key}")
    else:
        lines.append(line)
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
  echo ".env criado a partir de .env.example com chave local gerada"
else
  echo ".env ja existe"
fi
