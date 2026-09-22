from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.notifications.service import NotificationService
from backend.security.dependencies import organization_id_provider


router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


class PreferencePayload(BaseModel):
    enabled: bool = True
    telegram_enabled: bool = False
    telegram_chat_id: str | None = None
    email_enabled: bool = False
    email_recipients: list[str] = Field(default_factory=list)
    reports_enabled: bool = False
    report_frequency: str = "DAILY"
    report_time: str = "18:00"
    report_weekday: int = 4
    report_month_day: int = 0
    timezone: str = "America/Sao_Paulo"
    immediate_alerts_enabled: bool = True
    alert_types: list[str] = Field(default_factory=list)


def _service(request: Request) -> NotificationService:
    return NotificationService(request.app.state.settings)


@router.get("/preferences")
def get_preferences(
    request: Request,
    organization_id: str = Depends(organization_id_provider),
) -> dict[str, Any]:
    return _service(request).get_preferences(organization_id)


@router.put("/preferences")
def update_preferences(
    payload: PreferencePayload,
    request: Request,
    organization_id: str = Depends(organization_id_provider),
) -> dict[str, Any]:
    try:
        return _service(request).update_preferences(organization_id, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/test/telegram")
def test_telegram(
    request: Request,
    organization_id: str = Depends(organization_id_provider),
) -> dict[str, Any]:
    try:
        return _service(request).test_telegram(organization_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/test/email")
def test_email(
    request: Request,
    organization_id: str = Depends(organization_id_provider),
) -> dict[str, Any]:
    try:
        return _service(request).test_email(organization_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/send-report")
def send_report(
    request: Request,
    organization_id: str = Depends(organization_id_provider),
) -> dict[str, Any]:
    try:
        return _service(request).send_report_now(organization_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/deliveries")
def deliveries(
    request: Request,
    organization_id: str = Depends(organization_id_provider),
) -> list[dict[str, Any]]:
    return _service(request).deliveries(organization_id)
