from __future__ import annotations

import argparse
import http.cookiejar
import json
import logging
import os
import signal
import shutil
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from datetime import datetime, timedelta, timezone

from app.database import connect, init_db
from app.config import API_PORT, DATABASE_PATH, EVIDENCE_DIR
import app.alerts as alerts_module
from app.auth import create_user, update_user_password
from app.edge_config import EdgeConfigError, edge_config_report, validate_edge_config
from app.edge_pilot_check import format_edge_pilot_check, run_edge_pilot_check
from app.edge_service import run_edge_service_command
from app.env import load_env_file
from app.models import (
    criar_camera,
    criar_alert_recipient,
    criar_cliente,
    criar_dispositivo,
    criar_regra,
    criar_unidade,
    listar,
    listar_areas_camera,
    listar_machine_monitors_camera,
    obter_alert_delivery,
    registrar_evento,
)
from app.reports import save_daily_report
from app.pilot import acceptance_checklist, create_backup, health_snapshot, prune_old_evidence, restore_backup
from app.machine_replay import run_machine_replay
from app.edge_runtime import run_production_edge
from edge_agent.camera_connector import detect_source_type, safe_source_ref
from edge_agent.camera_check import check_camera
from edge_agent.service import EdgeSupervisor, edge_status
from edge_agent.sync_outbox import flush_sync_outbox, pending_sync_count, run_sync_loop

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Comandos locais do MVP de produto.")
    parser.add_argument("--db", default=os.getenv("DATABASE_PATH") or str(DATABASE_PATH))
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init-db")

    user = subparsers.add_parser("create-user")
    user.add_argument("--email", required=True)
    user.add_argument("--senha", required=True)
    user.add_argument("--role", required=True, choices=["admin_campex", "admin_cliente", "operador", "visualizador"])
    user.add_argument("--cliente-id")

    reset = subparsers.add_parser("reset-password")
    reset.add_argument("--email", required=True)
    reset.add_argument("--nova-senha", required=True)

    cliente = subparsers.add_parser("add-cliente")
    cliente.add_argument("--nome", required=True)

    unidade = subparsers.add_parser("add-unidade")
    unidade.add_argument("--cliente-id", required=True)
    unidade.add_argument("--nome", required=True)
    unidade.add_argument("--localizacao")

    dispositivo = subparsers.add_parser("add-dispositivo")
    dispositivo.add_argument("--unidade-id", required=True)
    dispositivo.add_argument("--nome", required=True)

    camera = subparsers.add_parser("add-camera")
    camera.add_argument("--unidade-id", required=True)
    camera.add_argument("--nome", required=True)
    camera.add_argument("--cliente-id")
    camera.add_argument("--dispositivo-id")
    camera.add_argument("--edge-id")
    camera.add_argument("--config-ref")
    camera.add_argument("--source")

    regra = subparsers.add_parser("add-regra")
    regra.add_argument("--camera-id", required=True)
    regra.add_argument("--tipo-evento", required=True)
    regra.add_argument("--tempo-minimo", type=float, default=0)

    evento = subparsers.add_parser("add-evento")
    evento.add_argument("--cliente-id", required=True)
    evento.add_argument("--unidade-id", required=True)
    evento.add_argument("--camera-id", required=True)
    evento.add_argument("--tipo", required=True)
    evento.add_argument("--duracao", type=float)
    evento.add_argument("--operador-presente", choices=["sim", "nao"])
    evento.add_argument("--confianca", type=float)

    report = subparsers.add_parser("relatorio-diario")
    report.add_argument("--data")
    report.add_argument("--output-dir", default="reports")

    listing = subparsers.add_parser("list")
    listing.add_argument("table", choices=["clientes", "unidades", "dispositivos", "cameras", "regras", "eventos", "alertas"])

    camera_check = subparsers.add_parser("check-camera")
    camera_check.add_argument("--source", required=True)
    camera_check.add_argument("--timeout", type=float, default=5.0)

    run_edge = subparsers.add_parser("run-edge")
    run_edge.add_argument("--edge-id", required=True)
    run_edge.add_argument("--api-url", default=os.getenv("API_URL"))
    run_edge.add_argument("--heartbeat-seconds", type=float, default=10.0)

    run_edge_production = subparsers.add_parser("run-edge-production")
    run_edge_production.add_argument("--edge-id", default=os.getenv("CAMPEX_EDGE_ID"), required=False)
    run_edge_production.add_argument("--host", default=os.getenv("API_HOST") or "0.0.0.0")
    run_edge_production.add_argument("--port", type=int, default=int(os.getenv("API_PORT") or API_PORT or 8000))
    run_edge_production.add_argument("--heartbeat-seconds", type=float, default=float(os.getenv("CAMPEX_HEARTBEAT_SECONDS", "10")))
    run_edge_production.add_argument("--sync-seconds", type=float, default=float(os.getenv("CAMPEX_SYNC_SECONDS", "10")))
    run_edge_production.add_argument("--alert-decision-seconds", type=float, default=float(os.getenv("CAMPEX_ALERT_DECISION_SECONDS", "60")))

    status = subparsers.add_parser("edge-status")
    status.add_argument("--edge-id", required=True)

    backup = subparsers.add_parser("backup")
    backup.add_argument("--output-dir", default="backups")

    restore = subparsers.add_parser("restore")
    restore.add_argument("--archive", required=True)

    retention = subparsers.add_parser("prune-evidence")
    retention.add_argument("--days", type=int, required=True)
    retention.add_argument("--confirm", action="store_true")

    subparsers.add_parser("system-health")
    subparsers.add_parser("pilot-checklist")
    edge_config_check = subparsers.add_parser("edge-config-check")
    edge_config_check.add_argument("--edge-id", default=os.getenv("CAMPEX_EDGE_ID"))

    edge_pilot_check = subparsers.add_parser("edge-pilot-check")
    edge_pilot_check.add_argument("--api-url", default=os.getenv("CAMPEX_API_URL"))
    edge_pilot_check.add_argument("--camera-timeout", type=float, default=5.0)
    edge_pilot_check.add_argument("--http-timeout", type=float, default=2.0)

    edge_service = subparsers.add_parser("edge-service")
    edge_service.add_argument(
        "action",
        choices=["install", "uninstall", "start", "stop", "restart", "status", "logs"],
    )

    sync_cloud = subparsers.add_parser("sync-cloud")
    sync_cloud.add_argument("--cloud-url", default=os.getenv("CAMPEX_CLOUD_URL"))
    sync_cloud.add_argument("--edge-id", default=os.getenv("CAMPEX_EDGE_ID"))
    sync_cloud.add_argument("--edge-secret", default=os.getenv("CAMPEX_EDGE_SECRET"))
    sync_cloud.add_argument("--loop", action="store_true")
    sync_cloud.add_argument("--interval-seconds", type=float, default=10.0)

    replay = subparsers.add_parser("machine-replay")
    replay.add_argument("--video", required=True)
    replay.add_argument("--machine-config", required=True)
    replay.add_argument("--annotations", required=True)
    replay.add_argument("--output", default="reports/machine_replay_report.json")

    preflight = subparsers.add_parser("factory-preflight")
    preflight.add_argument("--api-url", default=os.getenv("CAMPEX_API_URL", "http://127.0.0.1:8000"))
    preflight.add_argument("--camera-id", default=os.getenv("CAMPEX_PREFLIGHT_CAMERA_ID"))
    preflight.add_argument("--timeout", type=float, default=3.0)
    preflight.add_argument("--min-free-gb", type=float, default=5.0)

    test_email = subparsers.add_parser("send-test-email")
    test_email.add_argument("--to", required=True)
    test_email.add_argument("--nome", default="Teste Campex")
    test_email.add_argument("--timeout", type=float, default=20.0)
    return parser


def _http_json(
    url: str,
    timeout: float = 3.0,
    opener: urllib.request.OpenerDirector | None = None,
    method: str = "GET",
    payload: dict | None = None,
) -> tuple[int, dict | list | None, str | None]:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    client = opener or urllib.request
    try:
        with client.open(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type:
                return response.status, json.loads(body), None
            return response.status, None, body[:200]
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = None
        return exc.code, payload, body[:200]
    except Exception as exc:
        return 0, None, str(exc)


def _http_sse_connected(
    url: str,
    timeout: float = 3.0,
    opener: urllib.request.OpenerDirector | None = None,
) -> tuple[bool, str]:
    request = urllib.request.Request(url, headers={"Accept": "text/event-stream"})
    client = opener or urllib.request
    try:
        with client.open(request, timeout=timeout) as response:
            chunk = response.readline().decode("utf-8", errors="replace").strip()
            return response.status == 200 and bool(chunk), chunk or "conectado"
    except Exception as exc:
        return False, str(exc)


def _print_check(status: str, label: str, detail: str) -> None:
    print(f"{status:<10} {label} - {detail}")


def _check_recent_frame(last_frame_at: object) -> bool:
    if not last_frame_at:
        return False
    try:
        from datetime import datetime, timezone

        parsed = datetime.fromisoformat(str(last_frame_at).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() <= 15
    except Exception:
        return False


def run_factory_preflight(db_path: Path, api_url: str, camera_id: str | None, timeout: float, min_free_gb: float) -> int:
    api_url = api_url.rstrip("/")
    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
    results: list[tuple[str, str, str]] = []

    def add(status: str, label: str, detail: str) -> None:
        results.append((status, label, detail))

    health_code, health, health_error = _http_json(f"{api_url}/health", timeout, opener)
    add("PASS" if health_code == 200 and isinstance(health, dict) and health.get("status") == "ok" else "FAIL", "API iniciada", f"{api_url}/health -> {health_code or health_error}")

    preflight_email = os.getenv("CAMPEX_PREFLIGHT_EMAIL")
    preflight_password = os.getenv("CAMPEX_PREFLIGHT_PASSWORD")
    login_detail = ""
    if preflight_email and preflight_password:
        login_code, login_payload, login_error = _http_json(
            f"{api_url}/auth/login",
            timeout,
            opener,
            method="POST",
            payload={"email": preflight_email, "senha": preflight_password},
        )
        if login_code == 200 and isinstance(login_payload, dict) and login_payload.get("user"):
            login_detail = f"login realizado como {login_payload['user'].get('email')}"
        else:
            login_detail = f"login falhou: {login_code or login_error}"
    elif preflight_email or preflight_password:
        login_detail = "CAMPEX_PREFLIGHT_EMAIL ou CAMPEX_PREFLIGHT_PASSWORD ausente"
    else:
        login_detail = "credenciais CAMPEX_PREFLIGHT_EMAIL/CAMPEX_PREFLIGHT_PASSWORD não informadas"

    auth_code, auth, auth_error = _http_json(f"{api_url}/auth/status", timeout, opener)
    if auth_code == 200 and isinstance(auth, dict):
        if auth.get("authenticated"):
            add("PASS", "login funcionando", login_detail or "sessão autenticada detectada")
        elif auth.get("bootstrap"):
            add("WARNING", "login funcionando", "API de auth respondeu, mas ainda não há usuário criado")
        elif preflight_email and preflight_password:
            add("FAIL", "login funcionando", login_detail)
        else:
            add("NOT TESTED", "login funcionando", login_detail)
    else:
        add("FAIL", "login funcionando", f"/auth/status não respondeu corretamente: {auth_code or auth_error}")

    try:
        with connect(db_path) as connection:
            init_db(connection)
            connection.execute("SELECT 1").fetchone()
            add("PASS", "banco acessível", str(db_path))
            cameras = listar(connection, "cameras")
            selected_camera = next((camera for camera in cameras if camera.get("id") == camera_id), None) if camera_id else (cameras[0] if cameras else None)
            if selected_camera:
                camera_id = str(selected_camera["id"])
                add("PASS", "câmera cadastrada", f"{selected_camera.get('nome')} ({camera_id})")
            else:
                add("FAIL", "câmera cadastrada", "nenhuma câmera encontrada no SQLite")
            areas = listar_areas_camera(connection, camera_id) if camera_id else []
            operator_zones = [area for area in areas if area.get("tipo") in {"operator_zone", "workstation"} and area.get("ativa")]
            machine_regions = [area for area in areas if area.get("tipo") == "machine_region" and area.get("ativa")]
            monitors = listar_machine_monitors_camera(connection, camera_id) if camera_id else []
            active_monitors = [monitor for monitor in monitors if monitor.get("ativo")]
            valid_calibrations = [
                monitor for monitor in active_monitors
                if monitor.get("active_baseline") is not None
                and monitor.get("stopped_baseline") is not None
                and monitor.get("calibration_result") == "READY"
            ]
            recipients = connection.execute("SELECT COUNT(*) AS total FROM alert_recipients WHERE ativo = 1").fetchone()["total"]
    except sqlite3.Error as exc:
        add("FAIL", "banco acessível", str(exc))
        selected_camera = None
        areas = []
        operator_zones = []
        machine_regions = []
        active_monitors = []
        valid_calibrations = []
        recipients = 0

    stream_status = None
    if camera_id:
        code, payload, error = _http_json(f"{api_url}/cameras/{camera_id}/status", timeout, opener)
        stream_status = payload if code == 200 and isinstance(payload, dict) else None
        if stream_status and stream_status.get("status") == "online":
            add("PASS", "câmera online", f"status online ({camera_id})")
        elif stream_status:
            add("FAIL", "câmera online", f"status {stream_status.get('status')}")
        else:
            add("FAIL", "câmera online", f"sem status via API: {code or error}")
    else:
        add("NOT TESTED", "câmera online", "sem camera_id para consultar")

    if stream_status and _check_recent_frame(stream_status.get("last_frame_at")):
        add("PASS", "stream recebendo frames", f"último frame: {stream_status.get('last_frame_at')}")
    elif stream_status and stream_status.get("fps"):
        add("WARNING", "stream recebendo frames", f"FPS informado {stream_status.get('fps')}, mas último frame recente não comprovado")
    elif camera_id:
        add("FAIL", "stream recebendo frames", "nenhum frame recente comprovado")
    else:
        add("NOT TESTED", "stream recebendo frames", "sem câmera alvo")

    ai_status = stream_status.get("ai_status") if stream_status else None
    if stream_status:
        add("PASS" if ai_status == "ativa" else "FAIL", "IA realmente iniciada", f"ai_status={ai_status or 'indisponível'}")
    else:
        add("NOT TESTED", "IA realmente iniciada", "sem status de stream")

    inference_fps = float((stream_status or {}).get("analysis_fps") or 0)
    if stream_status:
        add("PASS" if inference_fps > 0 else "FAIL", "FPS de inferência maior que zero", str(inference_fps))
    else:
        add("NOT TESTED", "FPS de inferência maior que zero", "sem status de stream")

    frames_before = int((stream_status or {}).get("analysis_frames") or (stream_status or {}).get("machine_frames_analyzed") or 0)
    time.sleep(min(2.0, max(0.5, timeout / 2)))
    frames_after = frames_before
    if camera_id:
        code, payload, _error = _http_json(f"{api_url}/cameras/{camera_id}/status", timeout, opener)
        if code == 200 and isinstance(payload, dict):
            frames_after = int(payload.get("analysis_frames") or payload.get("machine_frames_analyzed") or 0)
    if stream_status:
        add("PASS" if frames_after > frames_before else "FAIL", "frames analisados aumentando", f"{frames_before} -> {frames_after}")
    else:
        add("NOT TESTED", "frames analisados aumentando", "sem status de stream")

    add("PASS" if operator_zones else "FAIL", "zona do operador salva", f"{len(operator_zones)} zona(s)")
    add("PASS" if machine_regions else "FAIL", "região da máquina salva", f"{len(machine_regions)} região(ões)")
    add("PASS" if active_monitors else "FAIL", "monitor de máquina configurado", f"{len(active_monitors)} monitor(es) ativo(s)")
    add("PASS" if valid_calibrations else "FAIL", "calibração ativa/parada válida", f"{len(valid_calibrations)} monitor(es) READY")

    sse_ok, sse_detail = _http_sse_connected(f"{api_url}/events/stream", timeout, opener)
    add("PASS" if sse_ok else "FAIL", "SSE de eventos conectado", sse_detail)

    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(hours=2)
    pipeline_params = f"start={urllib.parse.quote(start_dt.isoformat())}&end={urllib.parse.quote(end_dt.isoformat())}"
    if camera_id:
        pipeline_params += f"&camera_id={urllib.parse.quote(camera_id)}"

    def add_pipeline_check(label: str, path: str, *, allow_empty: bool = True) -> None:
        code, payload, error = _http_json(f"{api_url}{path}?{pipeline_params}", timeout, opener)
        if code == 200 and isinstance(payload, dict):
            detail = "resposta estrutural válida"
            if not allow_empty:
                detail = "resposta estrutural válida; validação física ainda depende de dados reais"
            add("PASS", label, detail)
            return
        if code == 401:
            add("FAIL", label, "endpoint protegido sem sessão autenticada")
            return
        add("FAIL", label, f"{path} -> {code or error}")

    add_pipeline_check("Operational Timeline", "/operations/timeline")
    add_pipeline_check("Change & Anomaly", "/operations/change-anomalies")
    add_pipeline_check("Operational Video Context", "/operations/video-contexts")
    add_pipeline_check("Video Understanding config", "/operations/video-understandings")
    add_pipeline_check("Alert Decisioning", "/operations/alert-decisions")
    add_pipeline_check("Operational Shift Briefing", "/operations/briefing")
    add_pipeline_check("Operational & Financial Impact", "/operations/impact")

    evidence_dir = EVIDENCE_DIR
    try:
        evidence_dir.mkdir(parents=True, exist_ok=True)
        test_file = evidence_dir / ".preflight_write_test"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink()
        add("PASS", "pasta de evidências gravável", str(evidence_dir))
    except Exception as exc:
        add("FAIL", "pasta de evidências gravável", str(exc))

    email_mode = os.getenv("CAMPEX_EMAIL_MODE", "").strip().lower()
    if email_mode == "console":
        add("PASS", "modo de alertas configurado", "CAMPEX_EMAIL_MODE=console")
    elif email_mode == "smtp":
        smtp_ready = all(os.getenv(name) for name in ["CAMPEX_SMTP_HOST", "CAMPEX_SMTP_USERNAME", "CAMPEX_SMTP_PASSWORD"])
        add("PASS" if smtp_ready else "FAIL", "modo de alertas configurado", "SMTP configurado" if smtp_ready else "SMTP incompleto")
    else:
        add("WARNING" if recipients else "FAIL", "modo de alertas configurado", f"CAMPEX_EMAIL_MODE={email_mode or 'não definido'}; destinatários ativos={recipients}")

    usage = shutil.disk_usage(Path.cwd())
    free_gb = usage.free / (1024 ** 3)
    add("PASS" if free_gb >= min_free_gb else "FAIL", "espaço em disco suficiente", f"{free_gb:.2f} GB livres")

    print("Campex Factory Preflight")
    print(f"API: {api_url}")
    print(f"Banco: {db_path}")
    print(f"Câmera alvo: {camera_id or 'não selecionada'}")
    print("")
    for status, label, detail in results:
        _print_check(status, label, detail)
    print("")
    ready = all(status == "PASS" for status, _label, _detail in results)
    print("PRONTO PARA TESTE DE CAMPO" if ready else "NÃO PRONTO PARA TESTE DE CAMPO")
    return 0 if ready else 1


def _mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    if not domain:
        return email
    safe_local = f"{local[:1]}***" if local else "***"
    return f"{safe_local}@{domain}"


def run_send_test_email(db_path: Path, email: str, nome: str, timeout: float) -> int:
    email = email.strip().lower()
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        print("E-mail invalido.")
        return 2

    def command_connect(_db_path: object = None):
        return connect(db_path)

    original_alerts_connect = alerts_module.connect
    try:
        alerts_module.connect = command_connect
        with command_connect() as connection:
            init_db(connection)
            row = connection.execute("SELECT id FROM alert_recipients WHERE lower(email) = lower(?) LIMIT 1", (email,)).fetchone()
            if row:
                recipient_id = str(row["id"])
            else:
                recipient_id = criar_alert_recipient(connection, nome, email, ativo=False, event_types=[])

        delivery_id = alerts_module.send_test_alert(recipient_id)
        if not delivery_id:
            print("Nao foi possivel criar entrega de teste.")
            return 1

        deadline = time.time() + timeout
        delivery = None
        while time.time() < deadline:
            with command_connect() as connection:
                delivery = obter_alert_delivery(connection, delivery_id)
            if delivery and delivery["status"] != "pending":
                break
            time.sleep(0.2)

        with command_connect() as connection:
            delivery = obter_alert_delivery(connection, delivery_id)
        status = delivery["status"] if delivery else "unknown"
        print(f"delivery_id: {delivery_id}")
        print(f"destinatario: {_mask_email(email)}")
        print(f"modo: {os.getenv('CAMPEX_EMAIL_MODE', 'console').lower()}")
        print(f"status: {status}")
        if delivery and delivery.get("erro"):
            print(f"erro: {delivery['erro']}")
        if status == "sent":
            return 0
        if status == "pending":
            print("Entrega ainda pendente. Consulte alert_deliveries para acompanhar.")
            return 1
        return 1
    finally:
        alerts_module.connect = original_alerts_connect


def main() -> int:
    load_env_file()
    args = build_parser().parse_args()
    if args.command == "edge-config-check":
        try:
            print(edge_config_report(db_path=Path(args.db), edge_id=args.edge_id))
            return 0
        except EdgeConfigError as exc:
            print("Campex Edge configuration error:")
            print(str(exc))
            return 2
    if args.command == "edge-service":
        result = run_edge_service_command(args.action)
        print(result.message)
        return 0 if result.ok else 2
    if args.command == "edge-pilot-check":
        report = run_edge_pilot_check(
            db_path=Path(args.db),
            api_url=args.api_url,
            camera_timeout=args.camera_timeout,
            http_timeout=args.http_timeout,
        )
        print(format_edge_pilot_check(report))
        return report.exit_code
    if args.command == "factory-preflight":
        return run_factory_preflight(Path(args.db), args.api_url, args.camera_id, args.timeout, args.min_free_gb)
    if args.command == "send-test-email":
        return run_send_test_email(Path(args.db), args.to, args.nome, args.timeout)

    if args.command == "sync-cloud" and args.loop:
        if not args.cloud_url or not args.edge_id or not args.edge_secret:
            raise SystemExit("Configure CAMPEX_CLOUD_URL, CAMPEX_EDGE_ID e CAMPEX_EDGE_SECRET.")
        print(f"Sincronizando outbox com {args.cloud_url}. Pressione Ctrl+C para parar.")
        run_sync_loop(args.db, args.cloud_url, args.edge_id, args.edge_secret, args.interval_seconds)
        return 0

    with connect(args.db) as connection:
        init_db(connection)
        if args.command == "init-db":
            print(f"Banco local pronto: {args.db}")
        elif args.command == "create-user":
            print(create_user(connection, args.email, args.senha, args.role, args.cliente_id))
        elif args.command == "reset-password":
            print("senha atualizada" if update_user_password(connection, args.email, args.nova_senha) else "usuario nao encontrado")
        elif args.command == "add-cliente":
            print(criar_cliente(connection, args.nome))
        elif args.command == "add-unidade":
            print(criar_unidade(connection, args.cliente_id, args.nome, args.localizacao))
        elif args.command == "add-dispositivo":
            print(criar_dispositivo(connection, args.unidade_id, args.nome))
        elif args.command == "add-camera":
            source_type = detect_source_type(args.source).value if args.source else None
            secure_ref = safe_source_ref(args.source) if args.source else None
            config_ref = args.config_ref
            if args.source and source_type in {"file", "webcam"}:
                config_ref = args.source
            print(criar_camera(
                connection,
                args.unidade_id,
                args.nome,
                args.dispositivo_id,
                config_ref,
                cliente_id=args.cliente_id,
                edge_id=args.edge_id,
                source_type=source_type,
                secure_ref=secure_ref,
            ))
        elif args.command == "add-regra":
            print(criar_regra(connection, args.camera_id, args.tipo_evento, args.tempo_minimo))
        elif args.command == "add-evento":
            operador = None
            if args.operador_presente:
                operador = args.operador_presente == "sim"
            print(registrar_evento(
                connection,
                args.cliente_id,
                args.unidade_id,
                args.camera_id,
                args.tipo,
                duracao=args.duracao,
                operador_presente=operador,
                confianca=args.confianca,
            ))
        elif args.command == "relatorio-diario":
            paths = save_daily_report(connection, Path(args.output_dir), args.data)
            print(f"JSON: {paths['json']}")
            print(f"CSV: {paths['csv']}")
        elif args.command == "list":
            for row in listar(connection, args.table):
                print(row)
        elif args.command == "check-camera":
            result = check_camera(args.source, args.timeout)
            print(f"conexao_realizada: {'sim' if result.conexao_realizada else 'nao'}")
            print(f"video_recebido: {'sim' if result.video_recebido else 'nao'}")
            print(f"resolucao: {result.resolucao or 'indisponivel'}")
            print(f"fps: {result.fps if result.fps is not None else 'indisponivel'}")
            print(f"tipo_conexao: {result.tipo_conexao}")
            print(f"compativel: {'sim' if result.compativel else 'nao'}")
            print(f"referencia_segura: {result.referencia_segura}")
            if result.motivo_erro:
                print(f"motivo_erro: {result.motivo_erro}")
        elif args.command == "run-edge":
            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s %(levelname)s %(name)s: %(message)s",
            )
            supervisor = EdgeSupervisor(
                edge_id=args.edge_id,
                db_path=Path(args.db),
                api_url=args.api_url,
                heartbeat_seconds=args.heartbeat_seconds,
            )
            def stop_service(_signum: int, _frame: object) -> None:
                supervisor.shutdown()
                raise SystemExit(0)

            signal.signal(signal.SIGTERM, stop_service)
            signal.signal(signal.SIGINT, stop_service)
            try:
                supervisor.run_forever()
            except KeyboardInterrupt:
                print("\nEdge encerrado pelo usuario.")
                supervisor.shutdown()
        elif args.command == "run-edge-production":
            try:
                validate_edge_config(db_path=Path(args.db), edge_id=args.edge_id)
            except EdgeConfigError as exc:
                raise SystemExit(f"Campex Edge configuration error:\n{exc}") from exc
            logging.basicConfig(
                level=os.getenv("CAMPEX_LOG_LEVEL", "INFO"),
                format="%(asctime)s %(levelname)s %(name)s: %(message)s",
            )
            run_production_edge(
                edge_id=args.edge_id,
                db_path=Path(args.db),
                host=args.host,
                port=args.port,
                heartbeat_seconds=args.heartbeat_seconds,
                sync_seconds=args.sync_seconds,
                alert_decision_seconds=args.alert_decision_seconds,
            )
        elif args.command == "edge-status":
            status = edge_status(args.edge_id, Path(args.db))
            print(f"Edge: {args.edge_id}")
            print(f"Status: {status['edge_status']}")
            print(f"Ultimo contato: {status['ultimo_contato'] or 'indisponivel'}")
            print(f"Tempo ligado: {int(status['uptime_seconds'])} segundos")
            print(f"CPU: {status['cpu_percent'] if status['cpu_percent'] is not None else 'indisponivel'}")
            print(f"Memoria: {status['memory_percent'] if status['memory_percent'] is not None else 'indisponivel'}")
            print(f"Cameras cadastradas: {status['cameras_total']}")
            print(f"Cameras online: {status['cameras_online']}")
            print(f"Cameras offline: {status['cameras_offline']}")
            print(f"Eventos pendentes na fila: {status['eventos_pendentes']}")
            for camera in status["cameras"]:
                print(
                    "- "
                    f"{camera['nome']} ({camera['id']}): {camera['status']} | "
                    f"ultimo frame: {camera.get('ultimo_frame') or 'nunca'} | "
                    f"reconexoes: {camera.get('reconexoes') or 0} | "
                    f"erro: {camera.get('ultimo_erro') or 'nenhum'}"
                )
        elif args.command == "backup":
            print(create_backup(Path(args.output_dir), Path(args.db)))
        elif args.command == "restore":
            restore_backup(Path(args.archive))
            print("Backup restaurado.")
        elif args.command == "prune-evidence":
            removed = prune_old_evidence(args.days, args.confirm)
            print(f"Evidencias removidas: {len(removed)}")
        elif args.command == "system-health":
            print(health_snapshot(Path(args.db)))
        elif args.command == "pilot-checklist":
            print(acceptance_checklist(Path(args.db)))
        elif args.command == "sync-cloud":
            if not args.cloud_url or not args.edge_id or not args.edge_secret:
                raise SystemExit("Configure CAMPEX_CLOUD_URL, CAMPEX_EDGE_ID e CAMPEX_EDGE_SECRET.")
            before = pending_sync_count(connection)
            synced = flush_sync_outbox(connection, args.cloud_url, args.edge_id, args.edge_secret)
            after = pending_sync_count(connection)
            print(f"Pendentes antes: {before}")
            print(f"Sincronizados agora: {synced}")
            print(f"Pendentes depois: {after}")
        elif args.command == "machine-replay":
            report = run_machine_replay(args.video, args.machine_config, args.annotations, args.output)
            metrics = report["metrics"]
            print(f"Relatorio: {args.output}")
            print(f"Tempo correto por estado: {metrics['tempo_correto_percentual']}%")
            print(f"Transicoes anotadas: {metrics['transicoes_anotadas']}")
            print(f"Transicoes perdidas: {metrics['transicoes_perdidas']}")
            print(f"Confianca media: {metrics['confianca_media']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
