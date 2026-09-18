from __future__ import annotations

import os
import platform
import plistlib
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from app.config import API_PORT, ROOT
from app.edge_config import EdgeConfigError, validate_edge_config


LABEL = "com.campex.edge"
TEMPLATE_PATH = ROOT / "deployment" / f"{LABEL}.plist"
LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
PLIST_PATH = LAUNCH_AGENTS_DIR / f"{LABEL}.plist"
LAUNCHER_PATH = ROOT / "deployment" / "run-campex-edge.sh"
STDOUT_LOG = ROOT / "logs" / "edge.stdout.log"
STDERR_LOG = ROOT / "logs" / "edge.stderr.log"

WINDOWS_TASK_NAME = "Campex Edge"
WINDOWS_LAUNCHER_PATH = ROOT / "deployment" / "run_campex_edge_windows.py"


@dataclass(frozen=True)
class EdgeServiceResult:
    ok: bool
    message: str


def render_plist(root: Path = ROOT) -> str:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    return template.replace("__CAMPEX_ROOT__", str(root))


def validate_plist(text: str) -> dict:
    return plistlib.loads(text.encode("utf-8"))


def _run_launchctl(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["launchctl", *args],
        text=True,
        capture_output=True,
        check=False,
    )


def _wait_for_api_health(timeout_seconds: float = 15.0, interval_seconds: float = 0.5) -> tuple[bool, str]:
    deadline = time.monotonic() + timeout_seconds
    url = f"http://127.0.0.1:{API_PORT}/health"
    last_error = "API ainda não respondeu."
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=min(interval_seconds, 1.0)) as response:
                if response.status == 200:
                    return True, f"API pronta em {url}"
                last_error = f"HTTP {response.status}"
        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code}"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(interval_seconds)
    return False, f"timeout aguardando /health em {url}: {last_error}"



def _is_windows() -> bool:
    return platform.system().lower() == "windows"


def _windows_pythonw() -> Path:
    executable = Path(sys.executable)
    candidate = executable.with_name("pythonw.exe")
    return candidate if candidate.exists() else executable


def _windows_task_command() -> str:
    pythonw = _windows_pythonw()
    return f'"{pythonw}" "{WINDOWS_LAUNCHER_PATH}"'


def _run_schtasks(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["schtasks", *args],
        text=True,
        capture_output=True,
        check=False,
    )


def _run_powershell(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def _install_windows_service() -> EdgeServiceResult:
    try:
        validate_edge_config()
    except EdgeConfigError as exc:
        return EdgeServiceResult(False, f"Campex Edge configuration error:\n{exc}")

    if not WINDOWS_LAUNCHER_PATH.exists():
        return EdgeServiceResult(
            False,
            f"Launcher Windows não encontrado: {WINDOWS_LAUNCHER_PATH}",
        )

    (ROOT / "logs").mkdir(parents=True, exist_ok=True)

    result = _run_schtasks([
        "/Create",
        "/TN", WINDOWS_TASK_NAME,
        "/SC", "ONSTART",
        "/RU", "SYSTEM",
        "/RL", "HIGHEST",
        "/TR", _windows_task_command(),
        "/F",
    ])

    if result.returncode != 0:
        return EdgeServiceResult(
            False,
            result.stderr.strip()
            or result.stdout.strip()
            or "Falha ao instalar tarefa Campex Edge.",
        )

    settings = _run_powershell(
        "$settings = New-ScheduledTaskSettingsSet "
        "-RestartCount 999 "
        "-RestartInterval (New-TimeSpan -Minutes 1) "
        "-StartWhenAvailable "
        "-ExecutionTimeLimit ([TimeSpan]::Zero) "
        "-MultipleInstances IgnoreNew; "
        "Set-ScheduledTask -TaskName 'Campex Edge' "
        "-Settings $settings | Out-Null"
    )

    if settings.returncode != 0:
        return EdgeServiceResult(
            False,
            settings.stderr.strip()
            or settings.stdout.strip()
            or "Falha ao configurar recuperacao automatica do Campex Edge.",
        )

    return EdgeServiceResult(
        True,
        "Campex Edge instalado no Windows Task Scheduler.",
    )


def _start_windows_service() -> EdgeServiceResult:
    query = _run_schtasks(["/Query", "/TN", WINDOWS_TASK_NAME])
    if query.returncode != 0:
        installed = _install_windows_service()
        if not installed.ok:
            return installed

    result = _run_schtasks(["/Run", "/TN", WINDOWS_TASK_NAME])
    if result.returncode != 0:
        return EdgeServiceResult(
            False,
            result.stderr.strip()
            or result.stdout.strip()
            or "Falha ao iniciar Campex Edge.",
        )

    api_ready, api_detail = _wait_for_api_health(timeout_seconds=25.0)
    if not api_ready:
        return EdgeServiceResult(
            False,
            f"Tarefa iniciada, mas API não ficou pronta: {api_detail}",
        )

    return EdgeServiceResult(
        True,
        f"Campex Edge iniciado em segundo plano. {api_detail}.",
    )


def _stop_windows_service() -> EdgeServiceResult:
    result = _run_schtasks(["/End", "/TN", WINDOWS_TASK_NAME])
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().lower()
        if "cannot find" not in detail and "não" not in detail:
            return EdgeServiceResult(
                False,
                result.stderr.strip()
                or result.stdout.strip()
                or "Falha ao parar Campex Edge.",
            )
    return EdgeServiceResult(True, "Campex Edge parado.")


def _uninstall_windows_service() -> EdgeServiceResult:
    _stop_windows_service()
    result = _run_schtasks([
        "/Delete",
        "/TN", WINDOWS_TASK_NAME,
        "/F",
    ])
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().lower()
        if "cannot find" not in detail and "não" not in detail:
            return EdgeServiceResult(
                False,
                result.stderr.strip()
                or result.stdout.strip()
                or "Falha ao remover Campex Edge.",
            )
    return EdgeServiceResult(True, "Campex Edge removido do Windows.")


def _status_windows_service() -> EdgeServiceResult:
    result = _run_schtasks([
        "/Query",
        "/TN", WINDOWS_TASK_NAME,
        "/FO", "LIST",
        "/V",
    ])
    if result.returncode != 0:
        return EdgeServiceResult(
            True,
            result.stderr.strip()
            or result.stdout.strip()
            or "Campex Edge não instalado.",
        )
    return EdgeServiceResult(True, result.stdout.strip())


def _ensure_service_files() -> None:
    if not LAUNCHER_PATH.exists():
        raise RuntimeError(f"Launcher não encontrado: {LAUNCHER_PATH}")
    LAUNCHER_PATH.chmod(LAUNCHER_PATH.stat().st_mode | 0o111)
    (ROOT / "logs").mkdir(parents=True, exist_ok=True)
    LAUNCH_AGENTS_DIR.mkdir(parents=True, exist_ok=True)


def install_service() -> EdgeServiceResult:
    if _is_windows():
        return _install_windows_service()

    try:
        validate_edge_config()
    except EdgeConfigError as exc:
        return EdgeServiceResult(False, f"Campex Edge configuration error:\n{exc}")
    _ensure_service_files()
    text = render_plist()
    validate_plist(text)
    PLIST_PATH.write_text(text, encoding="utf-8")
    try:
        PLIST_PATH.chmod(0o644)
    except OSError:
        pass
    return EdgeServiceResult(True, f"Serviço instalado em {PLIST_PATH}")


def uninstall_service() -> EdgeServiceResult:
    if _is_windows():
        return _uninstall_windows_service()

    stop_service()
    if PLIST_PATH.exists():
        PLIST_PATH.unlink()
    return EdgeServiceResult(True, f"Serviço removido de {PLIST_PATH}")


def start_service() -> EdgeServiceResult:
    if _is_windows():
        return _start_windows_service()

    if not PLIST_PATH.exists():
        install = install_service()
        if not install.ok:
            return install
    user_domain = f"gui/{os.getuid()}"
    bootstrap = _run_launchctl(["bootstrap", user_domain, str(PLIST_PATH)])
    if bootstrap.returncode not in {0, 5}:
        return EdgeServiceResult(False, bootstrap.stderr.strip() or bootstrap.stdout.strip() or "Falha ao carregar serviço.")
    kickstart = _run_launchctl(["kickstart", "-k", f"{user_domain}/{LABEL}"])
    if kickstart.returncode != 0:
        return EdgeServiceResult(False, kickstart.stderr.strip() or kickstart.stdout.strip() or "Falha ao iniciar serviço.")
    api_ready, api_detail = _wait_for_api_health()
    if not api_ready:
        return EdgeServiceResult(False, f"Serviço carregado, mas API não ficou pronta: {api_detail}")
    return EdgeServiceResult(True, f"Serviço Campex Edge iniciado. {api_detail}.")


def stop_service() -> EdgeServiceResult:
    if _is_windows():
        return _stop_windows_service()

    user_domain = f"gui/{os.getuid()}"
    result = _run_launchctl(["bootout", user_domain, str(PLIST_PATH)])
    if result.returncode not in {0, 36, 113}:
        return EdgeServiceResult(False, result.stderr.strip() or result.stdout.strip() or "Falha ao parar serviço.")
    return EdgeServiceResult(True, "Serviço Campex Edge parado.")


def restart_service() -> EdgeServiceResult:
    stopped = stop_service()
    if not stopped.ok:
        return stopped
    return start_service()


def service_status() -> EdgeServiceResult:
    if _is_windows():
        return _status_windows_service()

    user_domain = f"gui/{os.getuid()}"
    result = _run_launchctl(["print", f"{user_domain}/{LABEL}"])
    if result.returncode == 0:
        return EdgeServiceResult(True, result.stdout.strip() or "Serviço carregado.")
    detail = result.stderr.strip() or result.stdout.strip() or "Serviço não carregado."
    return EdgeServiceResult(True, detail)


def service_logs(lines: int = 80) -> EdgeServiceResult:
    paths = [STDOUT_LOG, STDERR_LOG]
    output: list[str] = []
    for path in paths:
        output.append(f"== {path} ==")
        if path.exists():
            tail = shutil.which("tail")
            if tail:
                result = subprocess.run([tail, "-n", str(lines), str(path)], text=True, capture_output=True, check=False)
                output.append(result.stdout.rstrip())
            else:
                output.extend(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
        else:
            output.append("Log ainda não existe.")
    return EdgeServiceResult(True, "\n".join(output))


def run_edge_service_command(action: str) -> EdgeServiceResult:
    actions = {
        "install": install_service,
        "uninstall": uninstall_service,
        "start": start_service,
        "stop": stop_service,
        "restart": restart_service,
        "status": service_status,
        "logs": service_logs,
    }
    return actions[action]()
