from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from app.config import DATABASE_PATH, EVIDENCE_DIR, LOG_DIR, ROOT
from app.database import connect, init_db
from app.edge_config import EdgeConfigError, validate_edge_config
from app.edge_service import install_service
from app.env import resolved_env_file


PASS = "PASS"
FAIL = "FAIL"
WARNING = "WARNING"


@dataclass(frozen=True)
class SetupCheck:
    label: str
    status: str
    detail: str = ""


@dataclass(frozen=True)
class SetupReport:
    checks: list[SetupCheck]

    @property
    def ok(self) -> bool:
        return all(item.status in {PASS, WARNING} for item in self.checks)

    @property
    def exit_code(self) -> int:
        return 0 if self.ok else 1


def _run(command: list[str], *, cwd: Path = ROOT) -> tuple[bool, str]:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    detail = (result.stdout or result.stderr or "").strip().splitlines()
    return result.returncode == 0, detail[-1] if detail else ""


def _venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run_setup(*, install_service_flag: bool = False, skip_pip: bool = False, venv: Path | None = None) -> SetupReport:
    checks: list[SetupCheck] = []
    venv_path = venv or ROOT / ".venv"

    def add(label: str, status: str, detail: str = "") -> None:
        checks.append(SetupCheck(label, status, detail))

    if sys.version_info < (3, 9):
        add("Python", FAIL, f"{sys.version.split()[0]} não suportado; use Python 3.9+")
    else:
        add("Python", PASS, sys.version.split()[0])

    if not venv_path.exists():
        ok, detail = _run([sys.executable, "-m", "venv", str(venv_path)])
        add("Virtualenv", PASS if ok else FAIL, str(venv_path) if ok else detail)
    else:
        add("Virtualenv", PASS, f"reutilizada em {venv_path}")

    python = _venv_python(venv_path)
    if not python.exists():
        add("Python da .venv", FAIL, str(python))
    else:
        add("Python da .venv", PASS, str(python))

    if skip_pip:
        add("Dependências Python", WARNING, "instalação pulada por opção")
    elif python.exists():
        ok_pip, detail_pip = _run([str(python), "-m", "pip", "install", "--upgrade", "pip"])
        ok_reqs, detail_reqs = _run([str(python), "-m", "pip", "install", "-r", "requirements.txt"]) if ok_pip else (False, detail_pip)
        add("Dependências Python", PASS if ok_pip and ok_reqs else FAIL, detail_reqs or detail_pip)

    ffmpeg = shutil.which("ffmpeg")
    add("FFmpeg", PASS if ffmpeg else WARNING, ffmpeg or "não encontrado no PATH")

    if python.exists():
        ok_cv, detail_cv = _run([str(python), "-c", "import cv2; print(cv2.__version__)"])
        add("OpenCV", PASS if ok_cv else FAIL, detail_cv or "import cv2 falhou")

    for path, label in [(DATABASE_PATH.parent, "Diretório do banco"), (EVIDENCE_DIR, "Diretório de evidências"), (LOG_DIR, "Diretório de logs")]:
        try:
            path.mkdir(parents=True, exist_ok=True)
            add(label, PASS, str(path))
        except OSError as exc:
            add(label, FAIL, str(exc))

    try:
        with connect(DATABASE_PATH) as connection:
            init_db(connection)
            connection.execute("SELECT 1").fetchone()
        add("Banco", PASS, str(DATABASE_PATH))
    except Exception as exc:
        add("Banco", FAIL, str(exc))

    env_file = resolved_env_file()
    add("Arquivo de ambiente", PASS if env_file.exists() else WARNING, str(env_file) if env_file.exists() else f"{env_file} ausente")

    try:
        validate_edge_config(db_path=DATABASE_PATH)
        add("Configuração Edge", PASS)
    except EdgeConfigError as exc:
        add("Configuração Edge", WARNING, str(exc))

    if install_service_flag:
        if platform.system() == "Darwin":
            result = install_service()
            add("Serviço macOS", PASS if result.ok else FAIL, result.message)
        else:
            add("Serviço do sistema", WARNING, f"instalação automática não suportada para {platform.system()}")

    return SetupReport(checks)


def format_setup(report: SetupReport) -> str:
    width = max([len(item.label) for item in report.checks] + [10])
    lines = ["CAMPEX EDGE SETUP RC1", ""]
    for item in report.checks:
        dots = "." * max(2, width + 3 - len(item.label))
        detail = f" ({item.detail})" if item.detail else ""
        lines.append(f"{item.label} {dots} {item.status}{detail}")
    lines.extend(["", f"RESULT: {'PASS' if report.ok else 'FAIL'}"])
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Instalação idempotente do Campex Edge RC1.")
    parser.add_argument("--install-service", action="store_true", help="Instala/configura serviço do SO quando suportado.")
    parser.add_argument("--skip-pip", action="store_true", help="Não instala dependências Python.")
    parser.add_argument("--venv", type=Path, default=ROOT / ".venv")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_setup(install_service_flag=args.install_service, skip_pip=args.skip_pip, venv=args.venv)
    print(format_setup(report))
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
