from __future__ import annotations

import re
import tempfile
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.auth import create_user
from app.config import ROOT
from cloud import database as cloud_database
from cloud.api import api as cloud_api
from cloud.edge_installer import build_windows_installer_cmd, create_windows_edge_package


def make_client(temp_dir: str) -> TestClient:
    cloud_database.DATABASE_URL = ""
    cloud_database.SQLITE_CLOUD_PATH = Path(temp_dir) / "cloud-installer.sqlite3"
    return TestClient(cloud_api)


def bootstrap_account(client: TestClient) -> tuple[str, str]:
    with cloud_database.connect() as db:
        cloud_database.init_cloud_db(db)

        create_user(
            db,
            email="felipe@campex.test",
            password="SenhaCampex123",
            role="admin_campex",
            nome="Felipe",
        )

    login = client.post(
        "/auth/login",
        json={
            "email": "felipe@campex.test",
            "senha": "SenhaCampex123",
        },
    )
    assert login.status_code == 200

    cliente = client.post(
        "/clientes",
        json={
            "nome": "Cliente Piloto",
            "status": "ativo",
        },
    )
    assert cliente.status_code == 200
    cliente_id = cliente.json()["id"]

    unidade = client.post(
        "/unidades",
        json={
            "cliente_id": cliente_id,
            "nome": "Producao",
            "localizacao": "Sao Jose do Rio Preto",
            "timezone": "America/Sao_Paulo",
        },
    )
    assert unidade.status_code == 200
    unidade_id = unidade.json()["id"]

    return cliente_id, unidade_id


def extract_variable(script: str, name: str) -> str:
    match = re.search(
        rf'^set "{re.escape(name)}=([^"]*)"$',
        script,
        flags=re.MULTILINE,
    )
    assert match is not None
    return match.group(1)


def test_installer_creates_offline_edge_then_heartbeat_makes_it_online() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        client = make_client(temp_dir)
        cliente_id, unidade_id = bootstrap_account(client)

        download = client.get(
            "/edge-installer/windows",
            params={"unidade_id": unidade_id},
        )

        assert download.status_code == 200
        assert "Instalar-Campex.cmd" in download.headers.get(
            "content-disposition",
            "",
        )

        cmd_text = download.text
        installer = cmd_text

        edge_id = extract_variable(installer, "CAMPEX_EDGE_ID")
        edge_secret = extract_variable(installer, "CAMPEX_EDGE_SECRET")
        cloud_url = extract_variable(installer, "CAMPEX_CLOUD_URL")

        assert edge_id.startswith("edge_")
        assert len(edge_secret) >= 12
        assert cloud_url.startswith("http://testserver")
        assert "/edge-package/windows" in installer
        assert "Start-Process -FilePath '%~f0' -Verb RunAs" in installer
        assert "manage.py edge-config-check" in installer
        assert "manage.py edge-service install" in installer
        assert "manage.py edge-service start" in installer
        assert "/edge/runtime-check" in installer
        assert '"%CAMPEX_CLOUD_URL%/edge/heartbeat"' not in installer
        assert "EncodedCommand" not in installer

        with cloud_database.connect() as db:
            cloud_database.init_cloud_db(db)
            edge = db.fetchone(
                "SELECT * FROM edge_devices WHERE id = ?",
                (edge_id,),
            )

        assert edge is not None
        assert edge["cliente_id"] == cliente_id
        assert edge["tenant_id"] == cliente_id
        assert edge["unidade_id"] == unidade_id
        assert edge["last_seen_at"] is None

        before = client.get("/edge-devices")
        assert before.status_code == 200

        edge_before = next(
            item for item in before.json()
            if item["id"] == edge_id
        )
        assert edge_before["online"] is False
        assert edge_before["connection_status"] == "offline"

        heartbeat = client.post(
            "/edge/heartbeat",
            headers={
                "X-Edge-Id": edge_id,
                "X-Edge-Secret": edge_secret,
            },
        )

        assert heartbeat.status_code == 200
        assert heartbeat.json()["status"] == "online"

        after = client.get("/edge-devices")
        assert after.status_code == 200

        edge_after = next(
            item for item in after.json()
            if item["id"] == edge_id
        )
        assert edge_after["online"] is True
        assert edge_after["connection_status"] == "online"
        assert edge_after["last_seen_at"] is not None


def test_repeated_installer_download_reuses_edge_identity_and_credential_key() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        client = make_client(temp_dir)
        _, unidade_id = bootstrap_account(client)

        first = client.get("/edge-installer/windows", params={"unidade_id": unidade_id})
        second = client.get("/edge-installer/windows", params={"unidade_id": unidade_id})

        assert first.status_code == 200
        assert second.status_code == 200
        assert extract_variable(first.text, "CAMPEX_EDGE_ID") == extract_variable(second.text, "CAMPEX_EDGE_ID")
        assert extract_variable(first.text, "CAMPEX_EDGE_SECRET") == extract_variable(second.text, "CAMPEX_EDGE_SECRET")
        assert extract_variable(first.text, "CAMPEX_CREDENTIAL_KEY") == extract_variable(second.text, "CAMPEX_CREDENTIAL_KEY")

        with cloud_database.connect() as db:
            cloud_database.init_cloud_db(db)
            total = db.fetchone("SELECT COUNT(*) AS total FROM edge_devices WHERE unidade_id = ?", (unidade_id,))
            edge = db.fetchone("SELECT * FROM edge_devices WHERE unidade_id = ?", (unidade_id,))

        assert total["total"] == 1
        assert edge["edge_secret_encrypted"]
        assert edge["credential_key_encrypted"]
        assert "edge_secret_encrypted" not in client.get("/edge-devices").text
        assert "credential_key_encrypted" not in client.get("/edge-devices").text


def test_installer_rotates_unused_edge_when_credentials_are_unrecoverable() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        client = make_client(temp_dir)
        cliente_id, unidade_id = bootstrap_account(client)

        with cloud_database.connect() as db:
            cloud_database.init_cloud_db(db)
            db.execute(
                """
                INSERT INTO edge_devices (
                    id, tenant_id, cliente_id, unidade_id, nome,
                    secret_hash, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                ("edge_legacy", cliente_id, cliente_id, unidade_id, "Edge legado", "hash-only"),
            )
            db.commit()

        response = client.get(
            "/edge-installer/windows",
            params={"unidade_id": unidade_id},
        )

        assert response.status_code == 200

        with cloud_database.connect() as db:
            rows = db.fetchall(
                """
                SELECT id, status, revoked_at
                FROM edge_devices
                WHERE unidade_id = ?
                ORDER BY created_at
                """,
                (unidade_id,),
            )

        assert len(rows) == 2
        legacy = next(row for row in rows if row["id"] == "edge_legacy")
        assert legacy["status"] == "revoked"
        assert legacy["revoked_at"] is not None

        active = [row for row in rows if row["status"] == "active"]
        assert len(active) == 1
        assert active[0]["id"] != "edge_legacy"


def test_installer_refuses_rotation_when_existing_edge_was_already_used() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        client = make_client(temp_dir)
        cliente_id, unidade_id = bootstrap_account(client)

        with cloud_database.connect() as db:
            cloud_database.init_cloud_db(db)
            db.execute(
                """
                INSERT INTO edge_devices (
                    id, tenant_id, cliente_id, unidade_id, nome,
                    secret_hash, status, created_at, updated_at, last_seen_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 'active',
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                ("edge_used", cliente_id, cliente_id, unidade_id, "Edge usado", "hash-only"),
            )
            db.commit()

        response = client.get(
            "/edge-installer/windows",
            params={"unidade_id": unidade_id},
        )

        assert response.status_code == 409

        with cloud_database.connect() as db:
            rows = db.fetchall(
                "SELECT id, status FROM edge_devices WHERE unidade_id = ?",
                (unidade_id,),
            )

        assert len(rows) == 1
        assert rows[0]["id"] == "edge_used"
        assert rows[0]["status"] == "active"

def test_installer_requests_admin_elevation_at_top() -> None:
    installer = build_windows_installer_cmd(
        cloud_url="https://cloud.campex.test",
        edge_id="edge_elev",
        edge_secret="edge-secret-elev",
        credential_key="credential-key-elev",
    )
    assert "Start-Process -FilePath '%~f0' -Verb RunAs" in installer
    elev_index = installer.index("Start-Process -FilePath '%~f0' -Verb RunAs")
    schtasks_index = installer.index("schtasks /Create")
    assert elev_index < schtasks_index


def test_installer_preserves_existing_env_and_data_on_reinstall() -> None:
    installer = build_windows_installer_cmd(
        cloud_url="https://cloud.campex.test",
        edge_id="edge_existing",
        edge_secret="edge-secret-existing",
        credential_key="credential-key-existing",
    )

    assert 'set "ENV_FILE=%INSTALL_ROOT%\\.env"' in installer
    assert 'if not exist "%ENV_FILE%"' in installer
    assert "Arquivo .env existente preservado." in installer
    assert "Preservando identidade, credenciais e dados locais." in installer
    assert "run_campex_edge_windows.py" in installer
    assert "Stop-Process -Id $_.ProcessId -Force" in installer


def test_installer_blocks_existing_env_from_different_edge_identity() -> None:
    installer = build_windows_installer_cmd(
        cloud_url="https://cloud.campex.test",
        edge_id="edge_new",
        edge_secret="edge-secret-new",
        credential_key="credential-key-new",
    )

    assert 'set "EXISTING_EDGE_ID="' in installer
    assert 'if /I "%%A"=="CAMPEX_EDGE_ID" set "EXISTING_EDGE_ID=%%B"' in installer
    assert "setlocal EnableDelayedExpansion" in installer
    assert 'if /I not "!EXISTING_EDGE_ID!"=="%CAMPEX_EDGE_ID%"' in installer
    assert "Este computador ja esta vinculado a outro Edge Campex." in installer
    assert "A Campex nao substituiu a identidade existente" in installer


def test_edge_package_excludes_env_data_tests_and_tmp_secret() -> None:
    zip_path = create_windows_edge_package(ROOT)
    try:
        with zipfile.ZipFile(zip_path) as package:
            names = package.namelist()
    finally:
        Path(zip_path).unlink(missing_ok=True)

    assert ".env" not in names
    assert not any(name.startswith("data/") for name in names)
    assert not any(name.startswith("tests/") for name in names)
    assert "tmp/cloud_edge_secret.txt" not in names
