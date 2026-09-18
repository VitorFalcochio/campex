from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

import manage
from app.database import connect, init_db
from app.edge_config import EdgeConfigError, edge_config_report, validate_edge_config
from app.env import load_env_file
from app.models import criar_camera, criar_cliente, criar_unidade


def test_explicit_env_file_loads_before_database_path_resolution(tmp_path: Path) -> None:
    db_path = tmp_path / "persistent" / "edge.sqlite3"
    env_file = tmp_path / "edge.env"
    env_file.write_text(
        "\n".join(
            [
                "CAMPEX_EDGE_ID=edge_explicit",
                f"DATABASE_PATH={db_path}",
                "CAMPEX_CREDENTIAL_KEY=explicit-key-with-enough-length",
            ]
        ),
        encoding="utf-8",
    )
    code = (
        "from app.config import DATABASE_PATH; "
        "from app.env import resolved_env_file; "
        "print(resolved_env_file()); print(DATABASE_PATH)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        env={**{key: value for key, value in os.environ.items() if key != "DATABASE_PATH"}, "CAMPEX_ENV_FILE": str(env_file)},
        text=True,
        capture_output=True,
        check=True,
    )

    lines = result.stdout.strip().splitlines()
    assert lines == [str(env_file.resolve()), str(db_path)]


def test_system_environment_has_precedence_over_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = tmp_path / "edge.env"
    env_file.write_text(
        "DATABASE_PATH=from-file.sqlite3\nCAMPEX_EDGE_ID=edge_file\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DATABASE_PATH", "from-system.sqlite3")
    monkeypatch.delenv("CAMPEX_EDGE_ID", raising=False)

    load_env_file(env_file)

    assert os.environ["DATABASE_PATH"] == "from-system.sqlite3"
    assert os.environ["CAMPEX_EDGE_ID"] == "edge_file"


def test_edge_config_check_detects_wrong_credential_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "edge.sqlite3"
    monkeypatch.setenv("CAMPEX_CREDENTIAL_KEY", "correct-key-with-enough-length")
    with connect(db_path) as connection:
        init_db(connection)
        cliente_id = criar_cliente(connection, "Cliente")
        unidade_id = criar_unidade(connection, cliente_id, "Fabrica")
        criar_camera(
            connection,
            unidade_id,
            "FL Plasticos",
            cliente_id=cliente_id,
            rtsp_host="10.0.0.10",
            rtsp_username="operador",
            rtsp_password="senha-super-secreta",
        )

    monkeypatch.setenv("CAMPEX_CREDENTIAL_KEY", "wrong-key-with-enough-length")
    monkeypatch.setenv("CAMPEX_EDGE_ID", "edge_fabrica_01")

    with pytest.raises(EdgeConfigError) as exc:
        validate_edge_config(db_path=db_path)

    message = str(exc.value)
    assert "CAMPEX_CREDENTIAL_KEY não consegue abrir" in message
    assert "FL Plasticos" in message
    assert "senha-super-secreta" not in message
    assert "wrong-key" not in message


def test_edge_config_check_accepts_correct_credential_key_and_does_not_leak_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "edge.sqlite3"
    secret_key = "correct-key-with-enough-length"
    monkeypatch.setenv("CAMPEX_CREDENTIAL_KEY", secret_key)
    monkeypatch.setenv("CAMPEX_EDGE_ID", "edge_fabrica_01")
    with connect(db_path) as connection:
        init_db(connection)
        cliente_id = criar_cliente(connection, "Cliente")
        unidade_id = criar_unidade(connection, cliente_id, "Fabrica")
        criar_camera(
            connection,
            unidade_id,
            "Camera OK",
            cliente_id=cliente_id,
            rtsp_host="10.0.0.10",
            rtsp_username="operador",
            rtsp_password="senha-super-secreta",
        )

    report = edge_config_report(db_path=db_path)

    assert "Campex Edge Config" in report
    assert "Database: OK" in report
    assert "Credential key: configured" in report
    assert "Camera credentials: OK (1 checked)" in report
    assert secret_key not in report
    assert "senha-super-secreta" not in report


def test_run_edge_production_fails_early_with_invalid_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CAMPEX_EDGE_ID", raising=False)
    env_file = tmp_path / "edge.env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("CAMPEX_ENV_FILE", str(env_file))
    monkeypatch.setenv("CAMPEX_CREDENTIAL_KEY", "valid-key-with-enough-length")
    monkeypatch.setattr(sys, "argv", ["manage.py", "--db", str(tmp_path / "edge.sqlite3"), "run-edge-production"])
    with patch.object(manage, "run_production_edge") as runner:
        with pytest.raises(SystemExit) as exc:
            manage.main()

    assert "Campex Edge configuration error" in str(exc.value)
    runner.assert_not_called()


def test_run_edge_production_valid_config_reaches_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CAMPEX_EDGE_ID", "edge_fabrica_01")
    monkeypatch.setenv("CAMPEX_CREDENTIAL_KEY", "valid-key-with-enough-length")
    monkeypatch.setattr(sys, "argv", ["manage.py", "--db", str(tmp_path / "edge.sqlite3"), "run-edge-production"])
    with patch.object(manage, "run_production_edge") as runner:
        assert manage.main() == 0

    runner.assert_called_once()
