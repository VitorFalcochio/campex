from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.operations.intelligence import build_operational_intelligence


def _event(
    event_id: str,
    started_at: datetime,
    duration_seconds: float,
    *,
    machine_id: str = "station_4",
    machine_name: str = "Estacao 4",
    activity_label: str = "Espera",
    hourly_rate: float | None = None,
    currency: str = "BRL",
) -> dict:
    ended_at = started_at + timedelta(seconds=duration_seconds)
    metadata = {
        "facts": {
            "person": {"track_id": int(event_id.split("_")[-1])},
            "machine_area": {
                "camera_id": "cam_1",
                "site_id": "plant_1",
                "site_name": "Plant 1",
                "line_id": "line_a",
                "line_name": "Line A",
                "zone_id": machine_id,
                "machine_id": machine_id,
                "machine_name": machine_name,
            },
            "activity": {
                "type": "WAITING",
                "label": activity_label,
                "is_stop": True,
            },
            "timing": {
                "started_at": started_at.isoformat(),
                "ended_at": ended_at.isoformat(),
                "duration_seconds": duration_seconds,
            },
            "evidence": {"paths": [f"storage/evidence/{event_id}.jpg"]},
            "context": {"before": {"queue": 3}, "after": {"queue": 1}, "currency": currency},
            "quality": {"is_reliable": True, "state": "RELIABLE"},
        }
    }
    if hourly_rate is not None:
        metadata["impact_hourly_rate"] = hourly_rate
        metadata["currency"] = currency
    return {
        "id": event_id,
        "type": "MACHINE_WAITING",
        "camera_id": "cam_1",
        "zone_id": machine_id,
        "track_id": int(event_id.split("_")[-1]),
        "severity": "attention",
        "status": "CLOSED",
        "confidence": 0.9,
        "started_at": started_at.isoformat(),
        "ended_at": ended_at.isoformat(),
        "duration": duration_seconds,
        "metadata": metadata,
    }


def test_operational_intelligence_groups_recurrence_and_duration():
    now = datetime(2026, 9, 14, 18, 0, tzinfo=timezone.utc)
    events = [
        _event(f"evt_{index}", now - timedelta(hours=1, minutes=index), 600)
        for index in range(1, 13)
    ]

    payload = build_operational_intelligence(events, now=now)

    assert payload["source"]["closed_reliable_events"] == 12
    group = payload["event_groups"][0]
    assert group["frequency"] == 12
    assert group["operational_category"] == "waiting"
    assert group["site_id"] == "plant_1"
    assert group["line_id"] == "line_a"
    assert group["total_duration_seconds"] == 7200
    assert group["total_duration_label"] == "2h"


def test_operational_intelligence_triages_noise_and_escalates_recurrence():
    now = datetime(2026, 9, 14, 18, 0, tzinfo=timezone.utc)
    noisy = [_event("evt_1", now - timedelta(minutes=20), 120)]
    recurring = [
        _event(f"evt_{index}", now - timedelta(minutes=index), 120)
        for index in range(2, 11)
    ]

    payload = build_operational_intelligence(
        noisy
        + [
            {
                **event,
                "zone_id": "station_5",
                "metadata": {
                    **event["metadata"],
                    "facts": {
                        **event["metadata"]["facts"],
                        "machine_area": {
                            **event["metadata"]["facts"]["machine_area"],
                            "machine_id": "station_5",
                            "machine_name": "Estacao 5",
                        },
                    },
                },
            }
            for event in recurring
        ],
        now=now,
    )

    decisions = {item["group"]["location_label"]: item["decision"] for item in payload["triage"]}
    assert decisions["Estacao 4"] == "IGNORE"
    assert decisions["Estacao 5"] == "INVESTIGATE"
    assert payload["investigations"][0]["frequency"] == 9
    assert payload["investigations"][0]["operational_category"] == "waiting"


def test_operational_intelligence_builds_finding_comparison_and_impact():
    now = datetime(2026, 9, 14, 18, 0, tzinfo=timezone.utc)
    today = [_event(f"evt_{index}", now - timedelta(hours=2, minutes=index), 600, hourly_rate=200, currency="USD") for index in range(1, 8)]
    yesterday = [_event(f"evt_{index}", now - timedelta(days=1, minutes=index), 300, hourly_rate=200, currency="USD") for index in range(8, 10)]

    payload = build_operational_intelligence(today + yesterday, now=now)

    finding = payload["findings"][0]["statement"]
    assert "Estacao 4 - Espera acumulou 70 minutos hoje" in finding
    assert payload["comparisons"]["today_vs_yesterday"]["direction"] == "up"
    assert payload["comparisons"]["today_vs_yesterday"]["duration_delta_percent"] == 600.0
    assert payload["impacts"][0]["estimated_lost_capacity_hours"] == 1.167
    assert payload["impacts"][0]["estimated_cost"] == 233.33
    assert payload["impacts"][0]["currency"] == "USD"
    assert payload["impacts"][0]["estimated_cost_brl"] is None


def test_operational_intelligence_compares_current_day_to_recent_normal():
    now = datetime(2026, 9, 14, 18, 0, tzinfo=timezone.utc)
    today = [_event(f"evt_{index}", now - timedelta(hours=1, minutes=index), 600) for index in range(1, 5)]
    normal_days = [
        _event(f"evt_{index}", now - timedelta(days=day, hours=2), 300)
        for index, day in enumerate(range(1, 4), start=5)
    ]

    payload = build_operational_intelligence(today + normal_days, now=now)
    normal = payload["comparisons"]["normal_vs_current"]

    assert normal["state"] == "ABOVE_NORMAL"
    assert normal["baseline"]["sample_days"] == 3
    assert normal["baseline"]["total_duration_seconds"] == 300
    assert normal["comparison"]["duration_delta_percent"] == 700.0
