from __future__ import annotations

import json
import os
import queue
import smtplib
import ssl
import threading
import time
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from app.config import EVIDENCE_DIR, ROOT
from app.database import connect, init_db
from app.models import (
    alert_delivery_public_dict,
    criar_alert_delivery,
    listar_alert_deliveries,
    listar_recipients_para_evento,
    obter_alert_delivery,
    obter_alert_recipient,
    obter_evento,
    atualizar_alert_delivery_attempt,
)
from shared.schemas import now_iso


SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}
_subscribers: list[queue.Queue[dict[str, Any]]] = []
_subscribers_lock = threading.Lock()
_workers_lock = threading.Lock()
_active_workers: set[str] = set()


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def safe_error(exc: Exception) -> str:
    text = str(exc) or exc.__class__.__name__
    for secret_name in ("CAMPEX_SMTP_PASSWORD", "CAMPEX_SMTP_USERNAME"):
        secret = os.getenv(secret_name)
        if secret:
            text = text.replace(secret, "[oculto]")
    for marker in ("rtsp://", "rtsps://"):
        if marker in text.lower():
            return "Falha segura no envio. Detalhe sensivel ocultado."
    return text[:300]


def email_configuration_status() -> dict[str, Any]:
    mode = os.getenv("CAMPEX_EMAIL_MODE", "").strip().lower()
    if mode == "console":
        return {"status": "CONFIGURED", "mode": "console", "missing": []}
    if mode == "cloud":
        required = ["CAMPEX_CLOUD_URL", "CAMPEX_EDGE_ID", "CAMPEX_EDGE_SECRET"]
        missing = [name for name in required if not os.getenv(name)]
        return {
            "status": "CONFIGURED" if not missing else "NOT_CONFIGURED",
            "mode": "cloud",
            "missing": missing,
        }
    if mode == "smtp":
        required = ["CAMPEX_SMTP_HOST", "CAMPEX_SMTP_USERNAME", "CAMPEX_SMTP_PASSWORD"]
        missing = [name for name in required if not os.getenv(name)]
        return {
            "status": "CONFIGURED" if not missing else "NOT_CONFIGURED",
            "mode": "smtp",
            "missing": missing,
        }
    if not mode:
        return {"status": "NOT_CONFIGURED", "mode": "", "missing": ["CAMPEX_EMAIL_MODE"]}
    return {"status": "FAILED", "mode": mode, "missing": [], "error": "CAMPEX_EMAIL_MODE invalido."}


def subscribe() -> queue.Queue[dict[str, Any]]:
    subscriber: queue.Queue[dict[str, Any]] = queue.Queue()
    with _subscribers_lock:
        _subscribers.append(subscriber)
    return subscriber


def unsubscribe(subscriber: queue.Queue[dict[str, Any]]) -> None:
    with _subscribers_lock:
        if subscriber in _subscribers:
            _subscribers.remove(subscriber)


def publish_alert(payload: dict[str, Any]) -> None:
    with _subscribers_lock:
        subscribers = list(_subscribers)
    for subscriber in subscribers:
        try:
            subscriber.put_nowait(payload)
        except queue.Full:
            pass


def stream_events(tenant_id: str | None = None):
    subscriber = subscribe()
    try:
        yield "event: connected\ndata: {\"status\":\"ok\"}\n\n"
        while True:
            try:
                payload = subscriber.get(timeout=15)

                if tenant_id:
                    payload_tenant = payload.get("cliente_id") or payload.get("tenant_id")
                    if payload_tenant != tenant_id:
                        continue

                yield f"event: alert\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            except queue.Empty:
                yield "event: heartbeat\ndata: {}\n\n"
    finally:
        unsubscribe(subscriber)


def event_alert_payload(event: dict[str, Any], phase: str = "start") -> dict[str, Any]:
    title = event.get("tipo") or "Evento operacional"
    if event.get("tipo") == "restricted_area_occupied":
        title = "Pessoa em área restrita"
    elif event.get("tipo") == "workstation_unattended":
        title = "Operador fora da zona"
    elif event.get("tipo") == "active_without_operator":
        title = "Máquina ativa sem operador"
    elif event.get("tipo") == "machine_running_without_operator":
        title = "Máquina ativa sem operador"
    elif event.get("tipo") == "machine_stopped_with_operator":
        title = "Máquina parada com operador"
    elif event.get("tipo") == "machine_stoppage":
        title = "Parada de máquina"
    elif event.get("tipo") == "camera_offline":
        title = "Câmera offline"
    if phase == "normalization":
        title = f"Normalizado: {title}"
    return {
        "type": "incident_normalized" if phase == "normalization" else "incident_opened",
        "event_id": event["id"],
        "cliente_id": event.get("cliente_id"),
        "titulo": title,
        "camera_id": event.get("camera_id"),
        "area_id": event.get("area_id"),
        "unidade_id": event.get("unidade_id"),
        "horario": event.get("inicio"),
        "quantidade_pessoas": event.get("quantidade_inicial") or event.get("quantidade_atual") or 0,
        "evidence_url": f"/eventos/{event['id']}/evidence" if event.get("midia_path") else None,
        "status": event.get("status"),
    }


def severity_allowed(event_severity: str | None, recipient_min: str | None) -> bool:
    event_rank = SEVERITY_RANK.get((event_severity or "high").lower(), 3)
    min_rank = SEVERITY_RANK.get((recipient_min or "low").lower(), 1)
    return event_rank >= min_rank


def event_type_allowed(event_type: str | None, enabled_types: list[str] | None) -> bool:
    if not enabled_types:
        return True
    return str(event_type or "") in enabled_types


def alert_decision_payload(decision: dict[str, Any]) -> dict[str, Any]:
    return {
        "tenant_id": decision.get("tenant_id"),
        "type": "critical_alert_decision",
        "decision_id": decision["decision_id"],
        "incident_key": decision["incident_key"],
        "alert_type": decision.get("alert_type"),
        "severity": decision.get("severity"),
        "priority": decision.get("priority") or decision.get("severity"),
        "title": decision.get("title"),
        "summary": decision.get("summary"),
        "camera_id": decision.get("camera_id"),
        "asset_id": decision.get("asset_id"),
        "event_refs": decision.get("event_refs") or [],
        "anomaly_refs": decision.get("anomaly_refs") or [],
        "understanding_refs": decision.get("understanding_refs") or [],
        "evidence_refs": decision.get("evidence_refs") or [],
        "reason_codes": decision.get("reason_codes") or [],
        "cause_inferred": False,
        "created_at": decision.get("created_at") or now_iso(),
    }


def listar_recipients_para_decisao(connection, decision: dict[str, Any]) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT *
        FROM alert_recipients
        WHERE ativo = 1
          AND (cliente_id IS NULL OR cliente_id = ?)
          AND (camera_id IS NULL OR camera_id = ?)
        ORDER BY criado_em DESC
        """,
        (decision.get("tenant_id"), decision.get("camera_id")),
    ).fetchall()
    recipients = []
    for row in rows:
        recipient = dict(row)
        recipient["ativo"] = bool(recipient["ativo"])
        recipient["event_types"] = json.loads(recipient.get("event_types") or "[]")
        if not severity_allowed(decision.get("severity"), recipient.get("severidade_minima")):
            continue
        if not event_type_allowed(decision.get("alert_type"), recipient.get("event_types")):
            continue
        recipients.append(recipient)
    return recipients


def enqueue_alert_decision_delivery(decision_id: str, *, canal: str = "email") -> list[str]:
    with connect() as connection:
        init_db(connection)
        from app.operational_alerting import get_alert_decision

        decision = get_alert_decision(connection, decision_id)
        if decision is None or decision.get("decision") != "ALERT":
            return []
        return enqueue_alert_decisions_with_connection(connection, [decision], canal=canal)


def enqueue_alert_decisions(decisions: list[dict[str, Any]], *, canal: str = "email") -> list[str]:
    with connect() as connection:
        init_db(connection)
        return enqueue_alert_decisions_with_connection(connection, decisions, canal=canal)


def enqueue_alert_decisions_with_connection(connection, decisions: list[dict[str, Any]], *, canal: str = "email") -> list[str]:
    delivery_ids: list[str] = []
    for decision in decisions:
        if decision.get("decision") != "ALERT":
            continue
        recipients = listar_recipients_para_decisao(connection, decision)
        payload = alert_decision_payload(decision)
        created_for_decision = [
            criar_alert_delivery(
                connection,
                recipient["id"],
                evento_id=None,
                canal=canal,
                decision_id=decision["decision_id"],
                incident_key=decision["incident_key"],
                alert_type=decision.get("alert_type"),
                severity=decision.get("severity"),
                payload=payload,
            )
            for recipient in recipients
        ]
        if created_for_decision:
            publish_alert(payload)
        for delivery_id in created_for_decision:
            schedule_delivery(delivery_id)
        delivery_ids.extend(created_for_decision)
    return delivery_ids


def enqueue_event_alert(event_id: str, phase: str = "start") -> None:
    """Publish event realtime updates without emailing every raw event by default.

    Outbound operational email is owned by Alert Decisioning. The old direct
    event-email path can be re-enabled explicitly for legacy deployments with
    CAMPEX_DIRECT_EVENT_EMAILS=true.
    """
    direct_email = os.getenv("CAMPEX_DIRECT_EVENT_EMAILS", "false").strip().lower() == "true"
    canal = "email_normalizacao" if phase == "normalization" else "email"
    with connect() as connection:
        init_db(connection)
        event = obter_evento(connection, event_id)
        if event is None:
            return
        delivery_ids: list[str] = []
        if direct_email:
            recipients = [
                recipient
                for recipient in listar_recipients_para_evento(connection, event)
                if severity_allowed(event.get("severidade"), recipient.get("severidade_minima"))
                and event_type_allowed(event.get("tipo"), recipient.get("event_types"))
            ]
            delivery_ids = [
                criar_alert_delivery(connection, recipient["id"], evento_id=event_id, canal=canal)
                for recipient in recipients
            ]
    publish_alert(event_alert_payload(event, phase))
    for delivery_id in delivery_ids:
        schedule_delivery(delivery_id)


def schedule_delivery(delivery_id: str) -> None:
    with _workers_lock:
        if delivery_id in _active_workers:
            return
        _active_workers.add(delivery_id)
    thread = threading.Thread(target=_delivery_worker, args=(delivery_id,), name=f"alert-{delivery_id}", daemon=True)
    thread.start()


def _delivery_worker(delivery_id: str) -> None:
    try:
        max_attempts = env_int("CAMPEX_EMAIL_MAX_ATTEMPTS", 3)
        while True:
            try:
                with connect() as connection:
                    init_db(connection)
                    delivery = obter_alert_delivery(connection, delivery_id)
                    if delivery is None or delivery["status"] == "sent":
                        return
                    if int(delivery["attempts"] or 0) >= max_attempts:
                        return
                    recipient = obter_alert_recipient(connection, delivery["recipient_id"])
                    event = obter_evento(connection, delivery["evento_id"]) if delivery.get("evento_id") else None
            except Exception:
                return
            if recipient is None:
                _mark_delivery(delivery, "failed", "Destinatario nao encontrado.")
                return
            try:
                send_email_alert(recipient, event, bool(delivery.get("is_test")), decision_payload=delivery.get("payload") if delivery.get("decision_id") else None)
                _mark_delivery(delivery, "sent", None)
                return
            except Exception as exc:
                attempts = int(delivery["attempts"] or 0) + 1
                if attempts >= max_attempts:
                    _mark_delivery(delivery, "failed", safe_error(exc))
                    return
                delay = min(60, 2 ** attempts)
                _mark_delivery(delivery, "pending", safe_error(exc), next_delay_seconds=delay)
                time.sleep(delay)
    finally:
        with _workers_lock:
            _active_workers.discard(delivery_id)


def _mark_delivery(
    delivery: dict[str, Any],
    status: str,
    error: str | None,
    next_delay_seconds: int | None = None,
) -> None:
    attempts = int(delivery["attempts"] or 0) + 1
    now = now_iso()
    sent_at = now if status == "sent" else None
    next_attempt_at = None
    if next_delay_seconds is not None:
        next_attempt_at = str(time.time() + next_delay_seconds)
    with connect() as connection:
        init_db(connection)
        updated = atualizar_alert_delivery_attempt(
            connection,
            delivery["id"],
            status=status,
            attempts=attempts,
            last_attempt_at=now,
            next_attempt_at=next_attempt_at,
            sent_at=sent_at,
            erro=error,
        )
    if updated:
        publish_alert({"type": "delivery_updated", "delivery": alert_delivery_public_dict(updated)})


def send_email_alert(
    recipient: dict[str, Any],
    event: dict[str, Any] | None,
    is_test: bool = False,
    decision_payload: dict[str, Any] | None = None,
) -> None:
    config = email_configuration_status()
    if config["status"] != "CONFIGURED":
        if config["status"] == "NOT_CONFIGURED":
            raise RuntimeError(f"EMAIL_NOT_CONFIGURED: faltam {', '.join(config.get('missing') or [])}.")
        raise RuntimeError(str(config.get("error") or "CAMPEX_EMAIL_MODE invalido."))
    mode = str(config["mode"])
    if mode == "console":
        label = "decisao" if decision_payload else "teste" if is_test else "ocorrencia"
        print(f"Campex email console: alerta para {recipient['email']} ({label})")
        return
    message = build_email_message(recipient, event, is_test, decision_payload=decision_payload)
    host = os.getenv("CAMPEX_SMTP_HOST")
    port = env_int("CAMPEX_SMTP_PORT", 587)
    username = os.getenv("CAMPEX_SMTP_USERNAME")
    password = os.getenv("CAMPEX_SMTP_PASSWORD")
    use_tls = os.getenv("CAMPEX_SMTP_USE_TLS", "true").lower() == "true"
    if not host or not username or not password:
        raise RuntimeError("SMTP nao configurado.")
    if use_tls:
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(username, password)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            smtp.login(username, password)
            smtp.send_message(message)


def build_email_message(
    recipient: dict[str, Any],
    event: dict[str, Any] | None,
    is_test: bool = False,
    decision_payload: dict[str, Any] | None = None,
) -> EmailMessage:
    sender = os.getenv("CAMPEX_EMAIL_FROM", "campex@localhost")
    app_url = os.getenv("CAMPEX_APP_URL", "http://127.0.0.1:8000")
    if decision_payload:
        subject = f"[Campex] {decision_payload.get('title') or 'Alerta operacional crítico'}"
        lines = [
            str(decision_payload.get("title") or "Alerta operacional crítico"),
            str(decision_payload.get("summary") or "Decisão de alerta operacional."),
            f"Destinatario: {recipient['nome']}",
            f"Decision ID: {decision_payload.get('decision_id')}",
            f"Incident key: {decision_payload.get('incident_key')}",
            f"Tipo: {decision_payload.get('alert_type')}",
            f"Severidade: {decision_payload.get('severity')}",
            f"Camera: {decision_payload.get('camera_id')}",
            f"Ativo: {decision_payload.get('asset_id')}",
            f"Eventos: {', '.join(decision_payload.get('event_refs') or []) or 'nenhum'}",
            f"Evidencias: {len(decision_payload.get('evidence_refs') or [])}",
            f"Entendimentos visuais: {', '.join(decision_payload.get('understanding_refs') or []) or 'nenhum'}",
            "Causa inferida: não",
            f"Link: {app_url}/events",
        ]
        uncertainties = decision_payload.get("uncertainties") or []
        if uncertainties:
            lines.append("Incertezas: " + "; ".join(str(item) for item in uncertainties[:3]))
        message = EmailMessage()
        message["From"] = sender
        message["To"] = recipient["email"]
        message["Subject"] = subject
        message.set_content("\n".join(lines))
        return message
    event_id = event["id"] if event else "teste"
    event_title = event_alert_payload(event)["titulo"] if event else "Alerta de teste da Campex"
    subject = "[Campex] Alerta de teste" if is_test else f"[Campex] {event_title}"
    lines = [
        event_title,
        f"Destinatario: {recipient['nome']}",
        f"Evento: {event_id}",
    ]
    if event:
        lines.extend(
            [
                f"Camera: {event.get('camera_id')}",
                f"Area: {event.get('area_id')}",
                f"Unidade: {event.get('unidade_id')}",
                f"Tipo: {event.get('tipo')}",
                f"Severidade: {event.get('severidade')}",
                f"Status: {event.get('status')}",
                f"Horario: {event.get('inicio')}",
                f"Duracao: {event.get('duracao') if event.get('duracao') is not None else 'em andamento'}",
                f"Pessoas: {event.get('quantidade_maxima') or event.get('quantidade_inicial') or 0}",
                f"Link: {app_url}/#evento-{event_id}",
            ]
        )
    else:
        lines.append("Este alerta nao foi registrado como ocorrencia operacional real.")
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient["email"]
    message["Subject"] = subject
    message.set_content("\n".join(lines))
    if event and event.get("midia_path"):
        path = (ROOT / str(event["midia_path"])).resolve()
        evidence_root = EVIDENCE_DIR.resolve()
        if evidence_root in path.parents and path.exists():
            message.add_attachment(path.read_bytes(), maintype="image", subtype="jpeg", filename="evidencia.jpg")
    return message


def retry_delivery(delivery_id: str) -> dict[str, Any] | None:
    with connect() as connection:
        init_db(connection)
        delivery = obter_alert_delivery(connection, delivery_id)
        if delivery is None:
            return None
        connection.execute(
            "UPDATE alert_deliveries SET status = 'pending', attempts = 0, erro = NULL, next_attempt_at = NULL WHERE id = ?",
            (delivery_id,),
        )
        connection.commit()
        delivery = obter_alert_delivery(connection, delivery_id)
    schedule_delivery(delivery_id)
    return delivery


def send_test_alert(recipient_id: str) -> str | None:
    with connect() as connection:
        init_db(connection)
        recipient = obter_alert_recipient(connection, recipient_id)
        if recipient is None:
            return None
        delivery_id = criar_alert_delivery(connection, recipient_id, evento_id=None, canal="email", is_test=True)
    publish_alert(
        {
            "type": "test_alert",
            "cliente_id": recipient.get("cliente_id"),
            "titulo": "Alerta de teste",
            "recipient_id": recipient_id,
            "horario": now_iso(),
        }
    )
    schedule_delivery(delivery_id)
    return delivery_id


def resume_pending_deliveries() -> None:
    with connect() as connection:
        init_db(connection)
        pending = listar_alert_deliveries(connection, status="pending")
    for delivery in pending:
        schedule_delivery(delivery["id"])
