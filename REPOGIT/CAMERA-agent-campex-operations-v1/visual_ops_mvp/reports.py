from __future__ import annotations

import sqlite3
from datetime import date


def daily_report(connection: sqlite3.Connection, report_date: str | None = None) -> str:
    day = report_date or date.today().isoformat()
    rows = connection.execute(
        """
        SELECT
            t.name AS tenant_name,
            s.name AS site_name,
            c.name AS camera_name,
            r.name AS rule_name,
            COUNT(e.event_id) AS event_count,
            COALESCE(SUM(e.duration_seconds), 0) AS total_seconds,
            SUM(CASE WHEN e.severity IN ('warning', 'critical') THEN 1 ELSE 0 END) AS important_events
        FROM events e
        JOIN tenants t ON t.tenant_id = e.tenant_id
        JOIN sites s ON s.site_id = e.site_id
        JOIN cameras c ON c.camera_id = e.camera_id
        JOIN rules r ON r.rule_id = e.rule_id
        WHERE substr(e.started_at, 1, 10) = ?
        GROUP BY t.name, s.name, c.name, r.name
        ORDER BY t.name, s.name, c.name, r.name
        """,
        (day,),
    ).fetchall()
    open_alerts = connection.execute(
        """
        SELECT COUNT(*) AS total
        FROM alerts
        WHERE status = 'open' AND substr(created_at, 1, 10) = ?
        """,
        (day,),
    ).fetchone()["total"]

    lines = [
        f"Relatório diário - {day}",
        "",
        f"Alertas abertos no dia: {open_alerts}",
        "",
        "Eventos por cliente / unidade / câmera / regra:",
    ]
    if not rows:
        lines.append("- Nenhum evento registrado neste dia.")
        return "\n".join(lines)

    for row in rows:
        minutes = float(row["total_seconds"]) / 60.0
        lines.append(
            "- "
            f"{row['tenant_name']} | {row['site_name']} | {row['camera_name']} | "
            f"{row['rule_name']}: {row['event_count']} evento(s), "
            f"{minutes:.1f} min, {row['important_events']} importante(s)"
        )
    return "\n".join(lines)

