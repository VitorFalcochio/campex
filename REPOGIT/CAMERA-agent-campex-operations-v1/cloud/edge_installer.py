from __future__ import annotations

import os
import tempfile
import zipfile
from pathlib import Path


def build_windows_installer_cmd(
    *,
    cloud_url: str,
    edge_id: str,
    edge_secret: str,
    credential_key: str,
) -> str:
    cmd = r"""@echo off
setlocal
title Campex Edge

net session >nul 2>nul
if %errorlevel% neq 0 (
    echo.
    echo =========================================
    echo   Solicitando privilegios de administrador
    echo =========================================
    echo.
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

set "CAMPEX_CLOUD_URL=__CLOUD_URL__"
set "CAMPEX_EDGE_ID=__EDGE_ID__"
set "CAMPEX_EDGE_SECRET=__EDGE_SECRET__"
set "CAMPEX_CREDENTIAL_KEY=__CREDENTIAL_KEY__"

set "INSTALL_ROOT=%LOCALAPPDATA%\Campex\Edge"
set "PYTHON_ROOT=%INSTALL_ROOT%\.runtime\python"
set "PYTHON_EXE=%PYTHON_ROOT%\python.exe"
set "VENV_PYTHON=%INSTALL_ROOT%\.venv\Scripts\python.exe"
set "VENV_PYTHONW=%INSTALL_ROOT%\.venv\Scripts\pythonw.exe"
set "PACKAGE_ZIP=%TEMP%\campex-edge-package.zip"
set "PYTHON_INSTALLER=%TEMP%\campex-python-installer.exe"
set "STARTUP_FILE=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\CampexEdge.cmd"
set "ENV_FILE=%INSTALL_ROOT%\.env"

echo.
echo =========================================
echo            Instalando Campex
echo =========================================
echo.

if not exist "%INSTALL_ROOT%" mkdir "%INSTALL_ROOT%"
if not exist "%PYTHON_ROOT%" mkdir "%PYTHON_ROOT%"

if exist "%ENV_FILE%" (
    echo Instalacao existente detectada. Preservando identidade, credenciais e dados locais.
)

echo [1/6] Baixando Campex Edge...

curl.exe -fL ^
  -H "X-Edge-Id: %CAMPEX_EDGE_ID%" ^
  -H "X-Edge-Secret: %CAMPEX_EDGE_SECRET%" ^
  "%CAMPEX_CLOUD_URL%/edge-package/windows" ^
  -o "%PACKAGE_ZIP%"

if errorlevel 1 goto :error

echo [2/6] Preparando arquivos...

tar.exe -xf "%PACKAGE_ZIP%" -C "%INSTALL_ROOT%"

if errorlevel 1 goto :error

if not exist "%PYTHON_EXE%" (
    echo [3/6] Preparando runtime Campex...

    curl.exe -fL ^
      "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe" ^
      -o "%PYTHON_INSTALLER%"

    if errorlevel 1 goto :error

    "%PYTHON_INSTALLER%" /quiet ^
      InstallAllUsers=0 ^
      PrependPath=0 ^
      Include_launcher=0 ^
      Include_test=0 ^
      Shortcuts=0 ^
      AssociateFiles=0 ^
      TargetDir="%PYTHON_ROOT%"

    if errorlevel 1 goto :error
) else (
    echo [3/6] Runtime Campex ja preparado.
)

if not exist "%VENV_PYTHON%" (
    echo [4/6] Criando ambiente Campex...
    "%PYTHON_EXE%" -m venv "%INSTALL_ROOT%\.venv"
    if errorlevel 1 goto :error
) else (
    echo [4/6] Ambiente Campex ja preparado.
)

echo [5/6] Instalando componentes...

"%VENV_PYTHON%" -m pip install ^
  --disable-pip-version-check ^
  --no-input ^
  -r "%INSTALL_ROOT%\requirements.txt"

if errorlevel 1 goto :error

if not exist "%ENV_FILE%" (
    > "%ENV_FILE%" (
        echo CAMPEX_CLOUD_URL=%CAMPEX_CLOUD_URL%
        echo CAMPEX_EDGE_ID=%CAMPEX_EDGE_ID%
        echo CAMPEX_EDGE_SECRET=%CAMPEX_EDGE_SECRET%
        echo CAMPEX_CREDENTIAL_KEY=%CAMPEX_CREDENTIAL_KEY%
        echo CAMPEX_EMAIL_MODE=cloud
    )
) else (
    echo [5/6] Arquivo .env existente preservado.
)

echo [6/6] Validando e iniciando Campex Edge...

pushd "%INSTALL_ROOT%"
"%VENV_PYTHON%" manage.py edge-config-check
if errorlevel 1 (
    popd
    goto :error
)
popd

powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*run_campex_edge_windows.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1

timeout /t 2 /nobreak >nul

rem Inicia o Edge diretamente para a sessao atual.
start "" /D "%INSTALL_ROOT%" "%VENV_PYTHONW%" "%INSTALL_ROOT%\deployment\run_campex_edge_windows.py"

echo Aguardando o Campex Edge iniciar...

for /L %%I in (1,1,30) do (
    curl.exe -fsS "http://127.0.0.1:8000/health" >nul 2>&1
    if not errorlevel 1 goto :edge_ready
    timeout /t 1 /nobreak >nul
)

echo O Campex Edge nao iniciou dentro do tempo esperado.
goto :error

:edge_ready

rem Registra a tarefa de boot para proximos reinicios.
schtasks /Create /TN "Campex Edge" /SC ONSTART /RU SYSTEM /RL HIGHEST /TR ""%VENV_PYTHONW%" "%INSTALL_ROOT%\deployment\run_campex_edge_windows.py"" /F
if errorlevel 1 (
    echo Nao foi possivel instalar o Campex Edge no Windows para inicializacao automatica.
    goto :error
)

rem Remove mecanismo legado da pasta Startup, se existir.
if exist "%STARTUP_FILE%" del /f /q "%STARTUP_FILE%" >nul 2>&1

curl.exe -fsS ^
  -X POST ^
  -H "Content-Type: application/json" ^
  -H "X-Edge-Id: %CAMPEX_EDGE_ID%" ^
  -H "X-Edge-Secret: %CAMPEX_EDGE_SECRET%" ^
  -d "{}" ^
  "%CAMPEX_CLOUD_URL%/edge/heartbeat" ^
  >nul

if errorlevel 1 (
    echo O Edge iniciou, mas nao conseguiu conectar ao Campex Cloud.
    goto :error
)

> "%USERPROFILE%\Desktop\Campex.url" (
    echo [InternetShortcut]
    echo URL=%CAMPEX_CLOUD_URL%
)

del "%PACKAGE_ZIP%" >nul 2>&1
del "%PYTHON_INSTALLER%" >nul 2>&1

echo.
echo =========================================
echo       Campex instalada com sucesso
echo =========================================
echo.
echo O Campex Edge esta rodando em segundo plano.
echo Voce pode fechar esta janela.
echo.

start "" "%CAMPEX_CLOUD_URL%/edges"
pause
exit /b 0

:error
echo.

if exist "%INSTALL_ROOT%\logs\edge.stderr.log" (
    echo Ultimo diagnostico automatico:
    echo -----------------------------------------
    type "%INSTALL_ROOT%\logs\edge.stderr.log"
    echo -----------------------------------------
)

echo =========================================
echo A instalacao da Campex nao foi concluida.
echo =========================================
echo.
echo Nao desative o Windows Defender.
echo Deixe esta janela aberta e informe a etapa acima.
echo.
pause
exit /b 1
"""

    return (
        cmd.replace("__CLOUD_URL__", cloud_url)
        .replace("__EDGE_ID__", edge_id)
        .replace("__EDGE_SECRET__", edge_secret)
        .replace("__CREDENTIAL_KEY__", credential_key)
    )


def create_windows_edge_package(project_root: Path) -> str:
    excluded_dirs = {
        ".git",
        ".venv",
        "__pycache__",
        ".pytest_cache",
        "data",
        "logs",
        "tmp",
        "tests",
    }

    excluded_files = {
        ".env",
        ".DS_Store",
    }

    fd, zip_path = tempfile.mkstemp(
        prefix="campex-edge-",
        suffix=".zip",
    )
    os.close(fd)

    with zipfile.ZipFile(
        zip_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        for path in project_root.rglob("*"):
            relative = path.relative_to(project_root)

            if any(part in excluded_dirs for part in relative.parts):
                continue

            if path.name in excluded_files or path.is_dir():
                continue

            archive.write(path, arcname=str(relative))

    return zip_path
