from __future__ import annotations

import argparse
from pathlib import Path

from visual_ops_mvp.database import DEFAULT_DB_PATH, connect, init_db
from visual_ops_mvp.reports import daily_report
from visual_ops_mvp.repository import (
    add_alert,
    add_camera,
    add_event,
    add_rule,
    add_site,
    add_tenant,
    list_table,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MVP local de cadastros e eventos.")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Caminho do banco SQLite local.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="Cria ou atualiza o banco local.")

    tenant = subparsers.add_parser("add-tenant", help="Cadastra um cliente.")
    tenant.add_argument("--name", required=True)
    tenant.add_argument("--document")

    site = subparsers.add_parser("add-site", help="Cadastra uma unidade.")
    site.add_argument("--tenant-id", required=True)
    site.add_argument("--name", required=True)
    site.add_argument("--location")

    camera = subparsers.add_parser("add-camera", help="Cadastra uma câmera sem conectá-la.")
    camera.add_argument("--tenant-id", required=True)
    camera.add_argument("--site-id", required=True)
    camera.add_argument("--name", required=True)
    camera.add_argument("--source-type", default="future_live")
    camera.add_argument("--source-ref")
    camera.add_argument("--notes")

    rule = subparsers.add_parser("add-rule", help="Cadastra uma regra monitorada.")
    rule.add_argument("--tenant-id", required=True)
    rule.add_argument("--site-id", required=True)
    rule.add_argument("--camera-id")
    rule.add_argument("--name", required=True)
    rule.add_argument("--rule-type", required=True)

    event = subparsers.add_parser("add-event", help="Registra um evento.")
    event.add_argument("--tenant-id", required=True)
    event.add_argument("--site-id", required=True)
    event.add_argument("--camera-id", required=True)
    event.add_argument("--rule-id", required=True)
    event.add_argument("--event-type", required=True)
    event.add_argument("--started-at")
    event.add_argument("--ended-at")
    event.add_argument("--duration-seconds", type=float)
    event.add_argument("--severity", default="info", choices=["info", "warning", "critical"])

    alert = subparsers.add_parser("add-alert", help="Registra um alerta.")
    alert.add_argument("--tenant-id", required=True)
    alert.add_argument("--site-id", required=True)
    alert.add_argument("--camera-id", required=True)
    alert.add_argument("--rule-id", required=True)
    alert.add_argument("--event-id")
    alert.add_argument("--title", required=True)
    alert.add_argument("--message", required=True)

    listing = subparsers.add_parser("list", help="Lista registros.")
    listing.add_argument("table", choices=["tenants", "sites", "cameras", "rules", "events", "alerts"])

    report = subparsers.add_parser("daily-report", help="Gera relatório diário em texto.")
    report.add_argument("--date", help="Data no formato AAAA-MM-DD. Padrão: hoje.")

    return parser


def main() -> int:
    args = build_parser().parse_args()
    db_path = Path(args.db)
    with connect(db_path) as connection:
        init_db(connection)

        if args.command == "init-db":
            print(f"Banco local pronto: {db_path}")
        elif args.command == "add-tenant":
            print(add_tenant(connection, args.name, args.document))
        elif args.command == "add-site":
            print(add_site(connection, args.tenant_id, args.name, args.location))
        elif args.command == "add-camera":
            print(add_camera(
                connection,
                args.tenant_id,
                args.site_id,
                args.name,
                args.source_type,
                args.source_ref,
                args.notes,
            ))
        elif args.command == "add-rule":
            print(add_rule(connection, args.tenant_id, args.site_id, args.name, args.rule_type, args.camera_id))
        elif args.command == "add-event":
            print(add_event(
                connection,
                args.tenant_id,
                args.site_id,
                args.camera_id,
                args.rule_id,
                args.event_type,
                args.started_at,
                args.ended_at,
                args.duration_seconds,
                args.severity,
            ))
        elif args.command == "add-alert":
            print(add_alert(
                connection,
                args.tenant_id,
                args.site_id,
                args.camera_id,
                args.rule_id,
                args.title,
                args.message,
                args.event_id,
            ))
        elif args.command == "list":
            for row in list_table(connection, args.table):
                print(dict(row))
        elif args.command == "daily-report":
            print(daily_report(connection, args.date))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
