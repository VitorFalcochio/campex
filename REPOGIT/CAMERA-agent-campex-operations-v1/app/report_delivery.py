from __future__ import annotations

import os
import smtplib
import sqlite3
import ssl
import threading
import time
import uuid

import httpx
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from html import escape
from typing import Any
from zoneinfo import ZoneInfo

from app.alerts import email_configuration_status
from app.database import connect, init_db
from app.operational_read_model import ReadModelFilters, daily_report


DEFAULT_TIMEZONE = "America/Sao_Paulo"
_scheduler_thread: threading.Thread | None = None
_scheduler_stop = threading.Event()


def ensure_report_delivery_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS report_schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL UNIQUE,
            enabled INTEGER NOT NULL DEFAULT 1,
            send_time TEXT NOT NULL DEFAULT '08:00',
            timezone TEXT NOT NULL DEFAULT 'America/Sao_Paulo',
            channel TEXT NOT NULL DEFAULT 'email',
            email TEXT,
            recipient_name TEXT,
            whatsapp_number TEXT,
            last_sent_local_date TEXT,
            last_sent_at TEXT,
            last_status TEXT,
            last_error TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(report_schedules)").fetchall()
    }
    if "recipient_name" not in columns:
        connection.execute(
            "ALTER TABLE report_schedules ADD COLUMN recipient_name TEXT"
        )

    connection.commit()


def get_report_schedule(connection: sqlite3.Connection, tenant_id: str) -> dict[str, Any] | None:
    ensure_report_delivery_schema(connection)
    row = connection.execute(
        "SELECT * FROM report_schedules WHERE tenant_id = ?",
        (tenant_id,),
    ).fetchone()
    return dict(row) if row else None


def upsert_report_schedule(
    connection: sqlite3.Connection,
    *,
    tenant_id: str,
    enabled: bool,
    send_time: str,
    timezone_name: str = DEFAULT_TIMEZONE,
    channel: str = "email",
    email: str | None = None,
    recipient_name: str | None = None,
    whatsapp_number: str | None = None,
) -> dict[str, Any]:
    ensure_report_delivery_schema(connection)

    try:
        hour_text, minute_text = send_time.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise ValueError
    except Exception as exc:
        raise ValueError("Horário inválido. Use HH:MM.") from exc

    try:
        ZoneInfo(timezone_name)
    except Exception as exc:
        raise ValueError("Fuso horário inválido.") from exc

    channel = str(channel or "email").strip().lower()
    if channel not in {"email", "whatsapp", "both"}:
        raise ValueError("Canal inválido.")

    if channel in {"email", "both"} and not email:
        raise ValueError("Email é obrigatório para este canal.")

    connection.execute(
        """
        INSERT INTO report_schedules (
            tenant_id, enabled, send_time, timezone, channel,
            email, recipient_name, whatsapp_number, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(tenant_id) DO UPDATE SET
            enabled = excluded.enabled,
            send_time = excluded.send_time,
            timezone = excluded.timezone,
            channel = excluded.channel,
            email = excluded.email,
            recipient_name = excluded.recipient_name,
            whatsapp_number = excluded.whatsapp_number,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            tenant_id,
            int(enabled),
            send_time,
            timezone_name,
            channel,
            email,
            recipient_name,
            whatsapp_number,
        ),
    )
    connection.commit()
    return get_report_schedule(connection, tenant_id) or {}


def _tenant_name(connection: sqlite3.Connection, tenant_id: str) -> str:
    row = connection.execute(
        "SELECT nome FROM clientes WHERE id = ?",
        (tenant_id,),
    ).fetchone()
    return str(row["nome"]) if row and row["nome"] else "Operação"


def build_report_for_tenant(
    connection: sqlite3.Connection,
    *,
    tenant_id: str,
    end_at: datetime,
) -> dict[str, Any]:
    start_at = end_at - timedelta(hours=24)

    filters = ReadModelFilters(
        cliente_id=tenant_id,
        start=start_at.astimezone(timezone.utc),
        end=end_at.astimezone(timezone.utc),
    )

    report = daily_report(
        connection,
        filters,
        now=end_at.astimezone(timezone.utc),
    )

    return {
        "tenant_id": tenant_id,
        "tenant_name": _tenant_name(connection, tenant_id),
        "generated_at": end_at.isoformat(),
        "period": {
            "start": start_at.isoformat(),
            "end": end_at.isoformat(),
        },
        "report": report,
    }


def _seconds_label(value: Any) -> str:
    total = max(0, int(float(value or 0)))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}min"
    if minutes:
        return f"{minutes}min {seconds:02d}s"
    return f"{seconds}s"


def _report_event_label(event_type: Any) -> str:
    labels = {
        "machine_stoppage": "Parada observada",
        "machine_running_without_operator": "Operação sem operador",
        "active_without_operator": "Operação sem operador",
        "workstation_unattended": "Ausência de operador",
        "restricted_area_occupied": "Área restrita ocupada",
        "machine_stopped_with_operator": "Máquina parada com operador",
    }
    value = str(event_type or "").strip()
    return labels.get(value, value.replace("_", " ").strip().capitalize() or "Ocorrência operacional")


def _report_time_label(value: Any) -> str:
    if not value:
        return "Horário não informado"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.strftime("%H:%M")
    except Exception:
        return str(value)


def _report_date_label(value: Any) -> str:
    if not value:
        return datetime.now().strftime("%d/%m/%Y")
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.strftime("%d/%m/%Y")
    except Exception:
        return datetime.now().strftime("%d/%m/%Y")


def _report_email_html(
    lines: list[str],
    *,
    app_url: str,
    tenant_name: str,
    report_date: str,
) -> str:
    section_titles = {
        "RESUMO DO DIA",
        "PRINCIPAIS NÚMEROS",
        "O QUE MERECE ATENÇÃO",
        "PRINCIPAIS ACONTECIMENTOS",
        "LEITURA CAMPEX",
    }

    content: list[str] = []
    bullets: list[str] = []

    def flush_bullets() -> None:
        nonlocal bullets
        if not bullets:
            return

        items = "".join(
            f"""
            <div style="
                padding:12px 0;
                border-bottom:1px solid #e7e9ee;
                font-size:14px;
                line-height:1.55;
                color:#242830;
            ">
                {escape(item)}
            </div>
            """
            for item in bullets
        )

        content.append(
            f"""
            <div style="
                margin:8px 0 22px;
                padding:0 18px;
                border:1px solid #e7e9ee;
                border-radius:14px;
                background:#ffffff;
            ">
                {items}
            </div>
            """
        )
        bullets = []

    for index, raw_line in enumerate(lines):
        line = str(raw_line or "").strip()

        if not line:
            flush_bullets()
            continue

        if line.startswith("- "):
            bullets.append(line[2:])
            continue

        flush_bullets()

        if line in section_titles:
            content.append(
                f"""
                <div style="
                    margin:28px 0 10px;
                    font-size:11px;
                    line-height:1.4;
                    font-weight:700;
                    letter-spacing:1.2px;
                    color:#666d79;
                ">
                    {escape(line)}
                </div>
                """
            )
            continue

        if index == 0:
            content.append(
                f"""
                <h1 style="
                    margin:0 0 8px;
                    font-size:24px;
                    line-height:1.25;
                    font-weight:650;
                    color:#111318;
                ">
                    {escape(line)}
                </h1>
                """
            )
            continue

        if line.startswith("Segue a leitura da Campex"):
            content.append(
                f"""
                <p style="
                    margin:0 0 26px;
                    font-size:15px;
                    line-height:1.65;
                    color:#555c67;
                ">
                    {escape(line)}
                </p>
                """
            )
            continue

        if line.startswith("Ver eventos e evidências na Campex:"):
            content.append(
                f"""
                <div style="margin:30px 0 10px;">
                    <a
                        href="{escape(app_url)}/events"
                        style="
                            display:inline-block;
                            padding:13px 20px;
                            border-radius:10px;
                            background:#111318;
                            color:#ffffff;
                            text-decoration:none;
                            font-size:14px;
                            font-weight:650;
                        "
                    >
                        Ver eventos e evidências
                    </a>
                </div>
                """
            )
            continue

        if line == "Campex":
            continue

        if line.startswith("Inteligência operacional a partir"):
            continue

        content.append(
            f"""
            <p style="
                margin:0 0 12px;
                font-size:14px;
                line-height:1.65;
                color:#242830;
            ">
                {escape(line)}
            </p>
            """
        )

    flush_bullets()

    body = "".join(content)

    return f"""<!doctype html>
<html>
<body style="
    margin:0;
    padding:0;
    background:#f4f5f7;
    font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;
">
    <div style="
        display:none;
        max-height:0;
        overflow:hidden;
        opacity:0;
    ">
        Relatório operacional Campex — {escape(tenant_name)}
    </div>

    <table
        role="presentation"
        width="100%"
        cellspacing="0"
        cellpadding="0"
        border="0"
        style="background:#f4f5f7;"
    >
        <tr>
            <td align="center" style="padding:32px 16px;">
                <table
                    role="presentation"
                    width="100%"
                    cellspacing="0"
                    cellpadding="0"
                    border="0"
                    style="
                        max-width:660px;
                        background:#ffffff;
                        border:1px solid #e4e7eb;
                        border-radius:18px;
                        overflow:hidden;
                    "
                >
                    <tr>
                        <td style="
                            padding:22px 30px;
                            background:#111318;
                        ">
                            <table
                                role="presentation"
                                width="100%"
                                cellspacing="0"
                                cellpadding="0"
                                border="0"
                            >
                                <tr>
                                    <td style="
                                        font-size:19px;
                                        font-weight:750;
                                        letter-spacing:1.2px;
                                        color:#ffffff;
                                    ">
                                        CAMPEX
                                    </td>

                                    <td
                                        align="right"
                                        style="
                                            font-size:12px;
                                            color:#b8bdc7;
                                        "
                                    >
                                        {escape(report_date)}
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>

                    <tr>
                        <td style="padding:34px 30px 28px;">
                            {body}
                        </td>
                    </tr>

                    <tr>
                        <td style="
                            padding:22px 30px;
                            border-top:1px solid #e7e9ee;
                            background:#fafafa;
                        ">
                            <div style="
                                font-size:14px;
                                font-weight:700;
                                color:#111318;
                                margin-bottom:5px;
                            ">
                                Campex
                            </div>

                            <div style="
                                font-size:12px;
                                line-height:1.55;
                                color:#737985;
                            ">
                                Inteligência operacional a partir das câmeras que sua empresa já possui.
                            </div>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>"""


def build_report_email(
    payload: dict[str, Any],
    recipient: str,
    recipient_name: str | None = None,
) -> EmailMessage:
    report = payload["report"]
    summary = report.get("summary") or {}
    machines = summary.get("machines") or {}
    coverage = report.get("coverage") or {}

    raw_events = report.get("main_events") or []

    # Eventos internos ajudam a Campex a entender a operação,
    # mas não são acontecimentos que devem aparecer para o cliente.
    technical_event_types = {
        "calibration",
        "machine_state",
        "operator_presence",
    }

    events = [
        event
        for event in raw_events
        if str(event.get("tipo") or "") not in technical_event_types
    ]

    tenant_name = payload.get("tenant_name") or "Operação"
    period = payload.get("period") or {}

    coverage_status = str(coverage.get("status") or "").upper()
    valid_percent = float(coverage.get("valid_percent") or 0)
    coverage_sufficient = (
        coverage_status != "INSUFFICIENT"
        and valid_percent > 0
    )

    active_seconds = float(machines.get("active_seconds") or 0)
    stopped_seconds = float(machines.get("stopped_seconds") or 0)

    greeting_name = (recipient_name or "").strip()
    greeting = f"Olá, {greeting_name}." if greeting_name else "Olá."

    report_date = _report_date_label(period.get("end"))

    message = EmailMessage()
    message["From"] = os.getenv("CAMPEX_EMAIL_FROM", "campex@localhost")
    message["To"] = recipient
    message["Subject"] = f"Campex | Relatório Operacional — {report_date}"

    lines = [
        greeting,
        "",
        f"Segue a leitura da Campex sobre a operação da {tenant_name} nas últimas 24 horas.",
        "",
        "RESUMO DO DIA",
    ]

    # =========================================================
    # COBERTURA INSUFICIENTE
    # =========================================================
    if not coverage_sufficient:
        lines.extend([
            (
                "A Campex não teve cobertura operacional suficiente nas últimas "
                "24 horas para gerar indicadores confiáveis de atividade, parada "
                "ou presença de operador."
            ),
            "",
            "PRINCIPAIS NÚMEROS",
            "- Tempo monitorado: Não disponível",
            "- Tempo em operação: Não disponível",
            "- Tempo parado: Não disponível",
            "- Acontecimentos relevantes: Não disponível",
            "- Tempo sem operador: Não disponível",
            "",
            "O QUE MERECE ATENÇÃO",
            (
                f"- Cobertura operacional insuficiente: "
                f"{valid_percent:.0f}% de leitura válida no período."
            ),
            "",
            "PRINCIPAIS ACONTECIMENTOS",
            "- Sem base suficiente para consolidar acontecimentos do período.",
            "",
            "LEITURA CAMPEX",
            (
                "Não houve cobertura suficiente para produzir uma leitura "
                "operacional confiável neste período. A Campex não considera "
                "ausência de dados como evidência de atividade, parada ou "
                "ausência de operador."
            ),
        ])

    # =========================================================
    # COBERTURA SUFICIENTE
    # =========================================================
    else:
        absence_types = {
            "workstation_unattended",
            "machine_running_without_operator",
            "active_without_operator",
        }

        absence_events = [
            event
            for event in events
            if str(event.get("tipo") or "") in absence_types
        ]

        # Não soma durações para gerar "tempo sem operador" quando
        # existem eventos possivelmente sobrepostos.
        absence_seconds = None
        if len(absence_events) == 1:
            absence_seconds = float(
                absence_events[0].get("duration_seconds") or 0
            )

        event_counts: dict[str, int] = {}
        for event in events:
            event_type = str(event.get("tipo") or "operational_event")
            event_counts[event_type] = event_counts.get(event_type, 0) + 1

        repeated = sorted(
            (
                (event_type, count)
                for event_type, count in event_counts.items()
                if count >= 2
            ),
            key=lambda item: item[1],
            reverse=True,
        )

        event_count_label = (
            "1 acontecimento relevante"
            if len(events) == 1
            else f"{len(events)} acontecimentos relevantes"
        )

        lines.append(
            f"A Campex identificou {event_count_label} no período."
        )

        if stopped_seconds > 0:
            lines[-1] += (
                f" Foram observados {_seconds_label(stopped_seconds)} de parada."
            )

        if repeated:
            repeated_type, repeated_count = repeated[0]
            lines[-1] += (
                f" Houve recorrência de "
                f"{_report_event_label(repeated_type).lower()}, "
                f"com {repeated_count} ocorrências registradas."
            )

        lines.extend([
            "",
            "PRINCIPAIS NÚMEROS",
            (
                f"- Tempo monitorado: "
                f"{_seconds_label(86400 * valid_percent / 100)} "
                f"· {valid_percent:.0f}% do período"
            ),
            f"- Tempo em operação: {_seconds_label(active_seconds)}",
            f"- Tempo parado: {_seconds_label(stopped_seconds)}",
            f"- Acontecimentos relevantes: {len(events)}",
            (
                f"- Tempo sem operador: {_seconds_label(absence_seconds)}"
                if absence_seconds is not None
                else "- Tempo sem operador: Não consolidado"
            ),
            "",
            "O QUE MERECE ATENÇÃO",
        ])

        attention_lines: list[str] = []
        used_types: set[str] = set()

        if repeated:
            repeated_type, repeated_count = repeated[0]
            repeated_events = [
                event
                for event in events
                if str(event.get("tipo") or "") == repeated_type
            ]
            longest_repeated = max(
                repeated_events,
                key=lambda event: float(event.get("duration_seconds") or 0),
            )

            attention_lines.append(
                f"- {_report_event_label(repeated_type)} recorrente: "
                f"{repeated_count} ocorrências no período; "
                f"maior duração de "
                f"{_seconds_label(longest_repeated.get('duration_seconds'))}."
            )
            used_types.add(repeated_type)

        for event in events:
            event_type = str(event.get("tipo") or "")
            if event_type in used_types:
                continue

            attention_lines.append(
                f"- {_report_event_label(event_type)}: "
                f"{_seconds_label(event.get('duration_seconds'))} "
                f"às {_report_time_label(event.get('started_at'))}."
            )
            used_types.add(event_type)

            if len(attention_lines) >= 3:
                break

        if attention_lines:
            lines.extend(attention_lines)
        else:
            lines.append("- Nenhum ponto de atenção relevante identificado.")

        lines.extend([
            "",
            "PRINCIPAIS ACONTECIMENTOS",
        ])

        if events:
            for event in events[:5]:
                lines.append(
                    f"- {_report_time_label(event.get('started_at'))} — "
                    f"{_report_event_label(event.get('tipo'))} — "
                    f"{_seconds_label(event.get('duration_seconds'))}"
                )
        else:
            lines.append("- Nenhum acontecimento relevante registrado.")

        lines.extend([
            "",
            "LEITURA CAMPEX",
        ])

        if repeated:
            repeated_type, repeated_count = repeated[0]
            lines.append(
                f"A recorrência de "
                f"{_report_event_label(repeated_type).lower()} em "
                f"{repeated_count} momentos do período merece investigação "
                "operacional. A Campex não determina automaticamente a causa "
                "quando não existe evidência suficiente."
            )
        elif events:
            longest = max(
                events,
                key=lambda event: float(event.get("duration_seconds") or 0),
            )
            lines.append(
                f"O principal acontecimento do período foi "
                f"{_report_event_label(longest.get('tipo')).lower()}, "
                f"com duração de "
                f"{_seconds_label(longest.get('duration_seconds'))}. "
                "A Campex recomenda revisar a ocorrência e sua evidência antes "
                "de atribuir uma causa."
            )
        else:
            lines.append(
                "O período não apresentou acontecimentos relevantes "
                "suficientes para indicar um padrão operacional."
            )

    app_url = os.getenv(
        "CAMPEX_APP_URL",
        "http://127.0.0.1:8000",
    )

    lines.extend([
        "",
        f"Ver eventos e evidências na Campex: {app_url}/events",
        "",
        "Campex",
        "Inteligência operacional a partir das câmeras que sua empresa já possui.",
    ])

    plain_text = "\n".join(lines)
    message.set_content(plain_text)

    message.add_alternative(
        _report_email_html(
            lines,
            app_url=app_url,
            tenant_name=tenant_name,
            report_date=report_date,
        ),
        subtype="html",
    )

    return message


def send_report_email(
    payload: dict[str, Any],
    recipient: str,
    recipient_name: str | None = None,
    *,
    delivery_id: str | None = None,
) -> None:
    config = email_configuration_status()

    if config["status"] != "CONFIGURED":
        if config["status"] == "NOT_CONFIGURED":
            raise RuntimeError(
                f"EMAIL_NOT_CONFIGURED: faltam {', '.join(config.get('missing') or [])}."
            )
        raise RuntimeError(str(config.get("error") or "CAMPEX_EMAIL_MODE inválido."))

    if config["mode"] == "console":
        print(
            f"Campex relatório console: "
            f"{payload.get('tenant_name')} -> {recipient}"
        )
        return

    message = build_report_email(payload, recipient, recipient_name)

    if config["mode"] == "cloud":
        cloud_url = str(os.getenv("CAMPEX_CLOUD_URL") or "").rstrip("/")
        edge_id = str(os.getenv("CAMPEX_EDGE_ID") or "").strip()
        edge_secret = str(os.getenv("CAMPEX_EDGE_SECRET") or "").strip()

        plain_part = message.get_body(preferencelist=("plain",))
        html_part = message.get_body(preferencelist=("html",))

        text_body = plain_part.get_content() if plain_part else ""
        html_body = html_part.get_content() if html_part else text_body

        effective_delivery_id = (
            delivery_id
            or f"report-manual-{uuid.uuid4().hex}"
        )

        response = httpx.post(
            f"{cloud_url}/edge/report-delivery",
            json={
                "delivery_id": effective_delivery_id,
                "cliente_id": str(payload["tenant_id"]),
                "recipient": recipient,
                "subject": str(message["Subject"]),
                "text_body": text_body,
                "html_body": html_body,
            },
            headers={
                "X-Edge-Id": edge_id,
                "X-Edge-Secret": edge_secret,
            },
            timeout=15.0,
        )

        if response.status_code >= 400:
            try:
                detail = response.json().get("detail")
            except Exception:
                detail = response.text[:1000]
            raise RuntimeError(
                f"CLOUD_EMAIL_DELIVERY_FAILED: HTTP "
                f"{response.status_code}: {detail}"
            )

        return

    host = os.getenv("CAMPEX_SMTP_HOST")
    port = int(os.getenv("CAMPEX_SMTP_PORT", "587"))
    username = os.getenv("CAMPEX_SMTP_USERNAME")
    password = os.getenv("CAMPEX_SMTP_PASSWORD")
    use_tls = os.getenv("CAMPEX_SMTP_USE_TLS", "true").lower() == "true"

    if not host or not username or not password:
        raise RuntimeError("SMTP não configurado.")

    with smtplib.SMTP(host, port, timeout=15) as smtp:
        if use_tls:
            smtp.starttls(context=ssl.create_default_context())
        smtp.login(username, password)
        smtp.send_message(message)


def _schedule_is_due(schedule: dict[str, Any], now_utc: datetime) -> tuple[bool, datetime]:
    tz = ZoneInfo(str(schedule.get("timezone") or DEFAULT_TIMEZONE))
    local_now = now_utc.astimezone(tz)

    hour, minute = [int(part) for part in str(schedule["send_time"]).split(":", 1)]
    scheduled_local = local_now.replace(
        hour=hour,
        minute=minute,
        second=0,
        microsecond=0,
    )

    already_sent_today = (
        str(schedule.get("last_sent_local_date") or "")
        == local_now.date().isoformat()
    )

    return local_now >= scheduled_local and not already_sent_today, local_now


def send_due_reports_once(now_utc: datetime | None = None) -> list[dict[str, Any]]:
    now_utc = now_utc or datetime.now(timezone.utc)
    results: list[dict[str, Any]] = []

    with connect() as connection:
        init_db(connection)
        ensure_report_delivery_schema(connection)

        schedules = [
            dict(row)
            for row in connection.execute(
                """
                SELECT *
                FROM report_schedules
                WHERE enabled = 1
                ORDER BY tenant_id
                """
            ).fetchall()
        ]

        for schedule in schedules:
            due, local_now = _schedule_is_due(schedule, now_utc)
            if not due:
                continue

            tenant_id = str(schedule["tenant_id"])

            try:
                hour, minute = [
                    int(part)
                    for part in str(schedule["send_time"]).split(":", 1)
                ]
                scheduled_local = local_now.replace(
                    hour=hour,
                    minute=minute,
                    second=0,
                    microsecond=0,
                )

                payload = build_report_for_tenant(
                    connection,
                    tenant_id=tenant_id,
                    end_at=scheduled_local,
                )

                channel = str(schedule.get("channel") or "email")

                if channel in {"email", "both"}:
                    delivery_id = (
                        f"report-{tenant_id}-"
                        f"{scheduled_local.date().isoformat()}-"
                        f"{str(schedule['send_time']).replace(':', '')}-email"
                    )
                    send_report_email(
                        payload,
                        str(schedule["email"]),
                        schedule.get("recipient_name"),
                        delivery_id=delivery_id,
                    )

                if channel in {"whatsapp", "both"}:
                    raise RuntimeError(
                        "WHATSAPP_PROVIDER_NOT_CONFIGURED"
                    )

                connection.execute(
                    """
                    UPDATE report_schedules
                    SET
                        last_sent_local_date = ?,
                        last_sent_at = ?,
                        last_status = 'sent',
                        last_error = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE tenant_id = ?
                    """,
                    (
                        local_now.date().isoformat(),
                        now_utc.isoformat(),
                        tenant_id,
                    ),
                )
                connection.commit()

                results.append(
                    {
                        "tenant_id": tenant_id,
                        "status": "sent",
                    }
                )

            except Exception as exc:
                connection.execute(
                    """
                    UPDATE report_schedules
                    SET
                        last_status = 'failed',
                        last_error = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE tenant_id = ?
                    """,
                    (str(exc), tenant_id),
                )
                connection.commit()

                results.append(
                    {
                        "tenant_id": tenant_id,
                        "status": "failed",
                        "error": str(exc),
                    }
                )

    return results


def _scheduler_loop() -> None:
    while not _scheduler_stop.is_set():
        try:
            send_due_reports_once()
        except Exception:
            pass
        _scheduler_stop.wait(20.0)


def start_report_scheduler() -> None:
    global _scheduler_thread

    if _scheduler_thread and _scheduler_thread.is_alive():
        return

    _scheduler_stop.clear()
    _scheduler_thread = threading.Thread(
        target=_scheduler_loop,
        name="campex-report-scheduler",
        daemon=True,
    )
    _scheduler_thread.start()


def stop_report_scheduler() -> None:
    _scheduler_stop.set()
    thread = _scheduler_thread
    if thread:
        thread.join(timeout=3.0)
