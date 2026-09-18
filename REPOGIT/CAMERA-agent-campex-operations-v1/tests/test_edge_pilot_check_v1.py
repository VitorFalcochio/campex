from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.database import connect, init_db
from app.edge_pilot_check import (
    ATTENTION,
    BLOCKED,
    NOT_CONFIGURED,
    PASS,
    format_edge_pilot_check,
    run_edge_pilot_check,
)
from app.models import criar_camera, criar_cliente, criar_machine_monitor, criar_unidade, registrar_edge_heartbeat
from edge_agent.sync_outbox import enqueue_sync_event


@dataclass(frozen=True)
class FakeCameraCheck:
    conexao_realizada: bool = True
    video_recebido: bool = True
    motivo_erro: str | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _healthy_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, monitor: bool = True) -> tuple[Path, str]:
    db_path = tmp_path / "edge.sqlite3"
    monkeypatch.setenv("CAMPEX_EDGE_ID", "edge_fabrica_01")
    monkeypatch.setenv("CAMPEX_CREDENTIAL_KEY", "valid-key-with-enough-length")
    with connect(db_path) as connection:
        init_db(connection)
        cliente_id = criar_cliente(connection, "Cliente")
        unidade_id = criar_unidade(connection, cliente_id, "Fabrica")
        camera_id = criar_camera(
            connection,
            unidade_id,
            "Camera Fabrica",
            cliente_id=cliente_id,
            edge_id="edge_fabrica_01",
            rtsp_host="10.0.0.10",
            rtsp_username="operador",
            rtsp_password="senha-super-secreta",
            status="online",
        )
        connection.execute(
            "UPDATE cameras SET ultimo_frame = ?, frames_processados = ? WHERE id = ?",
            (_now_iso(), 10, camera_id),
        )
        if monitor:
            criar_machine_monitor(
                connection,
                cliente_id,
                unidade_id,
                camera_id,
                "Máquina",
                [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.1}, {"x": 0.9, "y": 0.9}],
                [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.1}, {"x": 0.9, "y": 0.9}],
                ativo=True,
            )
        registrar_edge_heartbeat(
            connection,
            "edge_fabrica_01",
            heartbeat_at=_now_iso(),
            camera_online=True,
            last_frame_at=_now_iso(),
            capture_fps=15.0,
            inference_fps=4.0,
            frames_analyzed=10,
            outbox_pending=0,
            disk_free_bytes=10_000,
            disk_used_percent=10.0,
        )
    return db_path, camera_id


def _patch_happy_externals(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("app.edge_pilot_check.service_status", lambda: type("R", (), {"ok": True, "message": "state = running\npid = 123"})())
    monkeypatch.setattr("app.edge_pilot_check._http_json", lambda *_args, **_kwargs: (200, {"status": "ok"}, None))
    monkeypatch.setattr("app.edge_pilot_check.check_camera", lambda *_args, **_kwargs: FakeCameraCheck())
    monkeypatch.setattr("app.edge_pilot_check.EVIDENCE_DIR", tmp_path / "evidence")
    monkeypatch.setattr("app.edge_pilot_check._recent_fatal_logs", lambda *_args, **_kwargs: None)


def _status(report, label: str) -> str:
    return next(item.status for item in report.items if item.label == label)


def test_edge_pilot_check_healthy_edge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path, _camera_id = _healthy_db(tmp_path, monkeypatch)
    _patch_happy_externals(monkeypatch, tmp_path)

    report = run_edge_pilot_check(db_path=db_path)
    output = format_edge_pilot_check(report)

    assert report.result == "READY FOR PILOT"
    assert _status(report, "Configuração") == PASS
    assert _status(report, "Serviço") == PASS
    assert _status(report, "Banco") == PASS
    assert _status(report, "Câmera / RTSP") == PASS
    assert "senha-super-secreta" not in output
    assert "valid-key" not in output


def test_edge_pilot_check_blocks_when_camera_inaccessible(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path, _camera_id = _healthy_db(tmp_path, monkeypatch)
    _patch_happy_externals(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "app.edge_pilot_check.check_camera",
        lambda *_args, **_kwargs: FakeCameraCheck(False, False, "rtsp://user:secret@10.0.0.10/live falhou"),
    )

    report = run_edge_pilot_check(db_path=db_path)
    output = format_edge_pilot_check(report)

    assert report.result == "BLOCKED"
    assert _status(report, "Câmera / RTSP") == BLOCKED
    assert "A câmera não está acessível nesta rede." in output
    assert "secret" not in output
    assert "rtsp://user" not in output


def test_edge_pilot_check_blocks_invalid_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CAMPEX_EDGE_ID", raising=False)
    monkeypatch.setenv("CAMPEX_CREDENTIAL_KEY", "valid-key-with-enough-length")

    report = run_edge_pilot_check(db_path=tmp_path / "edge.sqlite3")

    assert report.result == "BLOCKED"
    assert _status(report, "Configuração") == BLOCKED


def test_edge_pilot_check_blocks_stopped_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path, _camera_id = _healthy_db(tmp_path, monkeypatch)
    _patch_happy_externals(monkeypatch, tmp_path)
    monkeypatch.setattr("app.edge_pilot_check.service_status", lambda: type("R", (), {"ok": True, "message": "Could not find service"})())

    report = run_edge_pilot_check(db_path=db_path)

    assert report.result == "BLOCKED"
    assert _status(report, "Serviço") == BLOCKED


def test_edge_pilot_check_blocks_unavailable_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path, _camera_id = _healthy_db(tmp_path, monkeypatch)
    _patch_happy_externals(monkeypatch, tmp_path)
    monkeypatch.setattr("app.edge_pilot_check.connect", lambda *_args, **_kwargs: (_ for _ in ()).throw(__import__("sqlite3").OperationalError("unable to open database file")))

    report = run_edge_pilot_check(db_path=db_path)

    assert report.result == "BLOCKED"
    assert _status(report, "Banco") == BLOCKED


def test_edge_pilot_check_blocks_without_recent_stream_frame(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path, camera_id = _healthy_db(tmp_path, monkeypatch)
    _patch_happy_externals(monkeypatch, tmp_path)
    with connect(db_path) as connection:
        connection.execute("UPDATE cameras SET ultimo_frame = NULL WHERE id = ?", (camera_id,))
        connection.commit()

    report = run_edge_pilot_check(db_path=db_path)

    assert report.result == "BLOCKED"
    assert _status(report, "Stream") == BLOCKED


def test_edge_pilot_check_blocks_without_inference_frame(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path, camera_id = _healthy_db(tmp_path, monkeypatch)
    _patch_happy_externals(monkeypatch, tmp_path)
    with connect(db_path) as connection:
        connection.execute("UPDATE cameras SET frames_processados = 0 WHERE id = ?", (camera_id,))
        connection.commit()

    report = run_edge_pilot_check(db_path=db_path)

    assert report.result == "BLOCKED"
    assert _status(report, "Inferência") == BLOCKED


def test_edge_pilot_check_allows_missing_machine_monitor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path, _camera_id = _healthy_db(tmp_path, monkeypatch, monitor=False)
    _patch_happy_externals(monkeypatch, tmp_path)

    report = run_edge_pilot_check(db_path=db_path)

    assert report.result == "READY WITH ATTENTION"
    assert _status(report, "Machine monitor") == NOT_CONFIGURED


def test_edge_pilot_check_marks_outbox_backlog_attention(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path, _camera_id = _healthy_db(tmp_path, monkeypatch)
    _patch_happy_externals(monkeypatch, tmp_path)
    with connect(db_path) as connection:
        for index in range(100):
            enqueue_sync_event(connection, f"event-{index}", "tenant", {"id": index}, edge_id="edge_fabrica_01")

    report = run_edge_pilot_check(db_path=db_path)

    assert report.result == "READY WITH ATTENTION"
    assert _status(report, "Outbox") == ATTENTION


def test_edge_pilot_check_does_not_leak_secrets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path, _camera_id = _healthy_db(tmp_path, monkeypatch)
    monkeypatch.setenv("CAMPEX_EDGE_SECRET", "edge-secret-value")
    _patch_happy_externals(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "app.edge_pilot_check.service_status",
        lambda: type("R", (), {"ok": False, "message": "CAMPEX_EDGE_SECRET=edge-secret-value rtsp://admin:camera-pass@10.0.0.10"})(),
    )

    output = format_edge_pilot_check(run_edge_pilot_check(db_path=db_path))

    assert "edge-secret-value" not in output
    assert "camera-pass" not in output
    assert "admin:camera-pass" not in output
