from __future__ import annotations

import tempfile
import unittest
from unittest.mock import Mock, patch
from datetime import datetime, timezone
from pathlib import Path

from app.database import connect, init_db
from app.models import (
    criar_camera,
    criar_cliente,
    criar_unidade,
    registrar_evento,
)
from app.report_delivery import (
    build_report_for_tenant,
    get_report_schedule,
    send_report_email,
    upsert_report_schedule,
)


class ReportDeliveryV1Test(unittest.TestCase):
    def test_two_companies_keep_independent_report_schedules(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "reports.sqlite3"

            with connect(db_path) as connection:
                init_db(connection)

                company_a = criar_cliente(connection, "Empresa A")
                company_b = criar_cliente(connection, "Empresa B")

                upsert_report_schedule(
                    connection,
                    tenant_id=company_a,
                    enabled=True,
                    send_time="08:00",
                    timezone_name="America/Sao_Paulo",
                    channel="email",
                    email="diretor-a@empresa.com",
                )

                upsert_report_schedule(
                    connection,
                    tenant_id=company_b,
                    enabled=True,
                    send_time="11:55",
                    timezone_name="America/Sao_Paulo",
                    channel="email",
                    email="diretor-b@empresa.com",
                )

                schedule_a = get_report_schedule(connection, company_a)
                schedule_b = get_report_schedule(connection, company_b)

            self.assertEqual(schedule_a["send_time"], "08:00")
            self.assertEqual(schedule_a["email"], "diretor-a@empresa.com")

            self.assertEqual(schedule_b["send_time"], "11:55")
            self.assertEqual(schedule_b["email"], "diretor-b@empresa.com")

            self.assertNotEqual(schedule_a["tenant_id"], schedule_b["tenant_id"])

    def test_report_email_cloud_transport_uses_edge_credentials_and_delivery_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "reports.sqlite3"

            with connect(db_path) as connection:
                init_db(connection)
                company = criar_cliente(connection, "Empresa A")
                criar_unidade(connection, company, "Unidade A")

                report = build_report_for_tenant(
                    connection,
                    tenant_id=company,
                    end_at=datetime(2026, 9, 2, 8, 0, tzinfo=timezone.utc),
                )

            response = Mock()
            response.status_code = 200
            response.json.return_value = {
                "status": "sent",
                "delivery_id": "report-fixed-001",
            }

            with patch.dict(
                "os.environ",
                {
                    "CAMPEX_EMAIL_MODE": "cloud",
                    "CAMPEX_CLOUD_URL": "https://cloud.campex.test",
                    "CAMPEX_EDGE_ID": "edge-001",
                    "CAMPEX_EDGE_SECRET": "edge-secret-001",
                },
                clear=False,
            ):
                with patch(
                    "app.report_delivery.httpx.post",
                    return_value=response,
                ) as post_mock:
                    send_report_email(
                        report,
                        "gestor@empresa.com",
                        "Gestor",
                        delivery_id="report-fixed-001",
                    )

            post_mock.assert_called_once()
            args, kwargs = post_mock.call_args

            self.assertEqual(
                args[0],
                "https://cloud.campex.test/edge/report-delivery",
            )
            self.assertEqual(
                kwargs["headers"]["X-Edge-Id"],
                "edge-001",
            )
            self.assertEqual(
                kwargs["headers"]["X-Edge-Secret"],
                "edge-secret-001",
            )
            self.assertEqual(
                kwargs["json"]["delivery_id"],
                "report-fixed-001",
            )
            self.assertEqual(
                kwargs["json"]["cliente_id"],
                company,
            )
            self.assertEqual(
                kwargs["json"]["recipient"],
                "gestor@empresa.com",
            )

    def test_daily_report_never_mixes_company_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "reports.sqlite3"

            with connect(db_path) as connection:
                init_db(connection)

                company_a = criar_cliente(connection, "Empresa A")
                unit_a = criar_unidade(connection, company_a, "Unidade A")
                camera_a = criar_camera(
                    connection,
                    unit_a,
                    "Camera A",
                    cliente_id=company_a,
                )

                company_b = criar_cliente(connection, "Empresa B")
                unit_b = criar_unidade(connection, company_b, "Unidade B")
                camera_b = criar_camera(
                    connection,
                    unit_b,
                    "Camera B",
                    cliente_id=company_b,
                )

                registrar_evento(
                    connection,
                    company_a,
                    unit_a,
                    camera_a,
                    "machine_stoppage",
                    inicio="2026-08-19T12:00:00+00:00",
                    fim="2026-08-19T12:10:00+00:00",
                    duracao=600,
                )

                registrar_evento(
                    connection,
                    company_b,
                    unit_b,
                    camera_b,
                    "machine_stoppage",
                    inicio="2026-08-19T13:00:00+00:00",
                    fim="2026-08-19T13:20:00+00:00",
                    duracao=1200,
                )

                end_at = datetime(
                    2026, 8, 19, 18, 0, tzinfo=timezone.utc
                )

                report_a = build_report_for_tenant(
                    connection,
                    tenant_id=company_a,
                    end_at=end_at,
                )

                report_b = build_report_for_tenant(
                    connection,
                    tenant_id=company_b,
                    end_at=end_at,
                )

            events_a = report_a["report"]["main_events"]
            events_b = report_b["report"]["main_events"]

            self.assertEqual(report_a["tenant_id"], company_a)
            self.assertEqual(report_b["tenant_id"], company_b)

            self.assertTrue(events_a)
            self.assertTrue(events_b)

            self.assertTrue(
                all(
                    event["context"]["camera_id"] == camera_a
                    for event in events_a
                )
            )

            self.assertTrue(
                all(
                    event["context"]["camera_id"] == camera_b
                    for event in events_b
                )
            )

            self.assertNotIn(
                camera_b,
                [event["context"]["camera_id"] for event in events_a],
            )

            self.assertNotIn(
                camera_a,
                [event["context"]["camera_id"] for event in events_b],
            )


if __name__ == "__main__":
    unittest.main()
