@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [CAMPEX] Criando ambiente virtual...
    py -3.12 -m venv .venv
    if errorlevel 1 (
        echo [CAMPEX] Nao foi possivel criar o ambiente com py -3.12.
        echo [CAMPEX] Tentando com python...
        python -m venv .venv
        if errorlevel 1 goto error
    )
)

echo [CAMPEX] Instalando/atualizando dependencias...
if not exist ".tmp\pip-temp" mkdir ".tmp\pip-temp"
set "TEMP=%CD%\.tmp\pip-temp"
set "TMP=%CD%\.tmp\pip-temp"
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto error
".venv\Scripts\python.exe" -m pip install --no-cache-dir fastapi==0.116.1 uvicorn==0.35.0 httpx==0.28.1 opencv-python-headless==4.12.0.88
if errorlevel 1 goto error
".venv\Scripts\python.exe" -m pip install --no-cache-dir rfdetr==1.10.1 supervision==0.30.2 trackers==2.6.0
if errorlevel 1 (
    echo [CAMPEX] Dependencias opcionais de IA nao foram instaladas.
    echo [CAMPEX] O backend vai iniciar; libere espaco em disco para usar RF-DETR completo.
)

echo [CAMPEX] Inicializando banco de dados...
".venv\Scripts\python.exe" scripts\init_db.py
if errorlevel 1 goto error

echo [CAMPEX] Iniciando backend em http://0.0.0.0:8000
".venv\Scripts\python.exe" -m uvicorn backend.main:app --reload --reload-dir backend --reload-dir scripts --host 0.0.0.0 --port 8000
goto end

:error
echo.
echo [CAMPEX] Falha ao iniciar o backend.
pause

:end
endlocal
