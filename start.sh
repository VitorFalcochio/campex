#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

python_is_compatible() {
    "$1" - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
}

find_python() {
    for candidate in python3.12 python3.11 python3.10 python3 "$HOME/.local/bin/python3.12"; do
        if command -v "$candidate" >/dev/null 2>&1 && python_is_compatible "$candidate"; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done

    if [ -x "$HOME/.local/bin/uv" ] && "$HOME/.local/bin/uv" python find 3.12 >/dev/null 2>&1; then
        "$HOME/.local/bin/uv" python find 3.12
        return 0
    fi

    return 1
}

if [ -x ".venv/bin/python" ] && ! python_is_compatible ".venv/bin/python"; then
    echo "[CAMPEX] Ambiente virtual usa Python antigo: $(.venv/bin/python -V 2>&1)."
    echo "[CAMPEX] Removendo .venv para recriar com Python 3.10+..."
    rm -rf .venv
fi

if [ ! -x ".venv/bin/python" ]; then
    if ! PYTHON_BIN="$(find_python)"; then
        echo "[CAMPEX] Python 3.10+ nao encontrado."
        echo "[CAMPEX] Instale o Python 3.12 e rode novamente."
        echo
        echo "[CAMPEX] Opcao 1: instalador oficial em https://www.python.org/downloads/macos/"
        echo
        echo "[CAMPEX] Opcao 2: Homebrew."
        echo "         Se o comando brew nao existir, instale o Homebrew primeiro:"
        echo '         /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
        echo
        echo "         Depois instale o Python:"
        echo "         brew install python@3.12"
        echo
        echo "[CAMPEX] Por fim:"
        echo "         ./start.sh"
        exit 1
    fi

    echo "[CAMPEX] Criando ambiente virtual com $("$PYTHON_BIN" -V 2>&1)..."
    "$PYTHON_BIN" -m venv .venv || {
        echo "[CAMPEX] Nao foi possivel criar o ambiente com $PYTHON_BIN."
        exit 1
    }
fi

echo "[CAMPEX] Instalando/atualizando dependencias..."
".venv/bin/python" -m pip install --upgrade pip
".venv/bin/python" -m pip install -r requirements.txt

echo "[CAMPEX] Inicializando banco de dados..."
".venv/bin/python" scripts/init_db.py

FRONTEND_PORT="${CAMPEX_FRONTEND_PORT:-5174}"
BACKEND_PORT="${CAMPEX_BACKEND_PORT:-8000}"

cleanup() {
    if [ -n "${FRONTEND_PID:-}" ]; then
        kill "$FRONTEND_PID" >/dev/null 2>&1 || true
    fi
}
trap cleanup EXIT INT TERM

echo "[CAMPEX] Iniciando frontend em http://127.0.0.1:${FRONTEND_PORT}"
".venv/bin/python" -m http.server "$FRONTEND_PORT" --directory frontend >/tmp/campex-frontend.log 2>&1 &
FRONTEND_PID="$!"

echo "[CAMPEX] Iniciando backend em http://0.0.0.0:${BACKEND_PORT}"
echo "[CAMPEX] Abra: http://127.0.0.1:${FRONTEND_PORT}"
".venv/bin/python" -m uvicorn backend.main:app \
    --reload \
    --reload-dir backend \
    --reload-dir scripts \
    --host 0.0.0.0 \
    --port "$BACKEND_PORT"
