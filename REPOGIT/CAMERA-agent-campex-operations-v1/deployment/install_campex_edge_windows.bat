@echo off
cd /d "%~dp0\.."

if not exist ".venv\Scripts\python.exe" (
    echo [ERRO] Ambiente Campex nao encontrado.
    pause
    exit /b 1
)

echo Instalando Campex Edge...
".venv\Scripts\python.exe" manage.py edge-service install
if errorlevel 1 (
    echo.
    echo [ERRO] Nao foi possivel instalar o Campex Edge.
    pause
    exit /b 1
)

echo Iniciando Campex Edge em segundo plano...
".venv\Scripts\python.exe" manage.py edge-service start
if errorlevel 1 (
    echo.
    echo [ERRO] Campex Edge foi instalado, mas nao iniciou corretamente.
    pause
    exit /b 1
)

echo.
echo Campex instalado e funcionando.

powershell -NoProfile -Command "$desktop=[Environment]::GetFolderPath('Desktop'); $p=Join-Path $desktop 'Campex.url'; Set-Content -Path $p -Value '[InternetShortcut]`r`nURL=http://127.0.0.1:8000/'"

echo Atalho Campex criado na Area de Trabalho.
start "" "http://127.0.0.1:8000/settings/cameras"

timeout /t 3 /nobreak >nul
exit /b 0
