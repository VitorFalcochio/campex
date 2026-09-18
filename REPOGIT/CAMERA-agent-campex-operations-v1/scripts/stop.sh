#!/usr/bin/env bash
set -euo pipefail
pkill -f "python3 -m app.main" || true
echo "Campex parada."
