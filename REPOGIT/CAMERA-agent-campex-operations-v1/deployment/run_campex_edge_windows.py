from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs"
STDOUT_LOG = LOG_DIR / "edge.stdout.log"
STDERR_LOG = LOG_DIR / "edge.stderr.log"
UPDATE_DIR = ROOT / ".campex_update"
UPDATE_MARKER = UPDATE_DIR / "pending_update.json"
VERSION_FILE = ROOT / ".campex_version"
PROTECTED_NAMES = {".env", "data", "logs", ".runtime", ".venv", ".campex_update"}
BACKUP_READY_FILE = "_backup_complete.json"


def _write_marker(marker: dict, status: str, error: str | None = None) -> None:
    marker["update_status"] = status
    marker["last_update_error"] = error
    UPDATE_MARKER.parent.mkdir(parents=True, exist_ok=True)
    UPDATE_MARKER.write_text(json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8")


def _safe_update_error(exc: Exception) -> str:
    text = str(exc)
    blocked = ("http://", "https://", "rtsp://", "password", "senha", "secret", "token", "credential", "api_key", ".env")
    if any(item in text.lower() for item in blocked):
        return exc.__class__.__name__
    return text[:240] or exc.__class__.__name__


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _backup_is_complete(target: Path) -> bool:
    return target.exists() and (target / BACKUP_READY_FILE).is_file()


def _backup_metadata(target: Path) -> dict:
    if not _backup_is_complete(target):
        return {}
    try:
        data = json.loads((target / BACKUP_READY_FILE).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _backup_matches_marker(target: Path, marker: dict) -> bool:
    metadata = _backup_metadata(target)
    return (
        bool(metadata)
        and str(metadata.get("source_version") or "") == str(marker.get("current_version") or "")
        and str(metadata.get("target_version") or "") == str(marker.get("target_version") or "")
    )


def _ensure_current_code_backup(target: Path, marker: dict) -> None:
    if _backup_matches_marker(target, marker):
        return
    building = UPDATE_DIR / "backup_building"
    if building.exists():
        shutil.rmtree(building)
    building.mkdir(parents=True, exist_ok=True)
    for item in ROOT.iterdir():
        if item.name in PROTECTED_NAMES:
            continue
        destination = building / item.name
        if item.is_dir():
            shutil.copytree(item, destination, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
        else:
            shutil.copy2(item, destination)
    (building / BACKUP_READY_FILE).write_text(
        json.dumps(
            {
                "created_at": time.time(),
                "source_version": str(marker.get("current_version") or ""),
                "target_version": str(marker.get("target_version") or ""),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    if target.exists():
        shutil.rmtree(target)
    building.replace(target)


def _restore_backup(backup: Path) -> None:
    for item in list(ROOT.iterdir()):
        if item.name in PROTECTED_NAMES:
            continue
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()
    for item in backup.iterdir():
        destination = ROOT / item.name
        if item.is_dir():
            shutil.copytree(item, destination)
        else:
            shutil.copy2(item, destination)


def _extract_package(package: Path) -> None:
    with zipfile.ZipFile(package) as archive:
        for member in archive.infolist():
            target = ROOT / member.filename
            resolved = target.resolve()
            if ROOT.resolve() not in resolved.parents and resolved != ROOT.resolve():
                raise RuntimeError("update_package_invalid_path")
            first = Path(member.filename).parts[0] if Path(member.filename).parts else ""
            if first in PROTECTED_NAMES:
                continue
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as destination:
                shutil.copyfileobj(source, destination)


def apply_pending_update() -> None:
    if not UPDATE_MARKER.exists():
        return
    try:
        marker = json.loads(UPDATE_MARKER.read_text(encoding="utf-8"))
        status = str(marker.get("update_status") or "PENDING").upper()
        backup = UPDATE_DIR / "backup_previous"
        if status == "FAILED":
            return
        if status == "APPLYING":
            if _backup_matches_marker(backup, marker):
                _restore_backup(backup)
            _write_marker(marker, "FAILED", "update_interrupted")
            return
        package = Path(str(marker.get("staged_package") or ""))
        expected_sha = str(marker.get("expected_sha256") or "").lower()
        target_version = str(marker.get("target_version") or "").strip()
        if not package.exists() or not expected_sha or _sha256(package).lower() != expected_sha:
            raise RuntimeError("staged_update_invalid")
        try:
            _ensure_current_code_backup(backup, marker)
        except Exception as exc:
            _write_marker(marker, "PENDING", _safe_update_error(exc))
            return
        _write_marker(marker, "APPLYING")
        try:
            _extract_package(package)
            if target_version:
                VERSION_FILE.write_text(target_version + "\n", encoding="utf-8")
            package.unlink(missing_ok=True)
            UPDATE_MARKER.unlink(missing_ok=True)
        except Exception:
            _restore_backup(backup)
            raise
    except Exception as exc:
        try:
            marker = json.loads(UPDATE_MARKER.read_text(encoding="utf-8")) if UPDATE_MARKER.exists() else {}
            _write_marker(marker, "FAILED", _safe_update_error(exc))
        except Exception:
            pass


def main() -> None:
    os.chdir(ROOT)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    python = Path(sys.executable)
    python_console = python.with_name("python.exe")
    if python_console.exists():
        python = python_console

    command = [
        str(python),
        str(ROOT / "manage.py"),
        "run-edge-production",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
    ]

    while True:
        try:
            with STDOUT_LOG.open("a", encoding="utf-8") as stdout, \
                 STDERR_LOG.open("a", encoding="utf-8") as stderr:
                process = subprocess.run(
                    command,
                    cwd=ROOT,
                    stdout=stdout,
                    stderr=stderr,
                    check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                stderr.write(
                    f"\nCampex Edge encerrou com código "
                    f"{process.returncode}; reiniciando em 5s.\n"
                )
                stderr.flush()
            apply_pending_update()
        except Exception:
            with STDERR_LOG.open("a", encoding="utf-8") as stderr:
                traceback.print_exc(file=stderr)

        time.sleep(5)


if __name__ == "__main__":
    main()
