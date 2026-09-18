from __future__ import annotations

from typing import Any, Optional
import hashlib
import time
import os
import psutil
import secrets
from pathlib import Path
import logging
from datetime import datetime, timezone
from urllib.parse import quote, urlencode

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import httpx

from app.camera_rtsp import build_rtsp_url, test_rtsp_connection
from app.alerts import email_configuration_status, enqueue_alert_decisions_with_connection, enqueue_event_alert, resume_pending_deliveries, retry_delivery, send_test_alert, stream_events
from app.analytics import aggregate_period, compute_summary, current_period_range, data_quality, generate_insights, parse_dt, timeline
from app.auth import ADMIN_ROLES, authenticate, create_session, create_user, delete_session, find_active_user_by_email, get_request_user, require_role, require_user, tenant_filter, update_user_password, users_exist
from app.config import EVIDENCE_DIR, ROOT, storage_path
from app.database import connect, init_db
from app.event_workflow import acknowledge_event, event_detail, resolve_event, update_human_context, update_operational_memory
from app.context_engine import ContextPackAccessError, ContextPackNotFoundError, build_context_pack
from app.intelligence_reasoning import ReasoningEngine, ReasoningError, reasoning_error_response
from app.live_stream import LiveStreamManager, calibration_separation
from app.recommendation_engine import RecommendationEngine, RecommendationError, recommendation_error_response
from app.operational_read_model import (
    ReadModelFilters,
    comparison as read_model_comparison,
    current_operation as read_model_current,
    daily_report as read_model_daily_report,
    intelligence as read_model_intelligence,
    losses as read_model_losses,
    operational_change_anomalies as read_model_change_anomalies,
    operational_data as read_model_operational_data,
    operational_timeline as read_model_timeline,
    parse_datetime as read_model_parse_datetime,
    period_bounds as read_model_period_bounds,
    period_summary as read_model_summary,
    video_context_by_id as read_model_video_context_by_id,
    video_contexts as read_model_video_contexts,
)
from app.operational_context import (
    apply_context_to_camera,
    criar_operational_area,
    criar_operational_asset,
    criar_operational_process,
    resolve_context,
)
from app.operational_alerting import (
    AlertDecisionFilters,
    evaluate_alert_decisions,
    get_alert_decision,
    list_alert_decisions,
)
from app.operational_briefing import operational_shift_briefing
from app.operational_impact import (
    calculate_operational_impact,
    get_asset_economic_config,
    upsert_asset_economic_config,
)
from app.operational_understanding import (
    UnderstandingFilters,
    get_validated_understanding,
    list_validated_understandings,
)
from app.models import (
    atualizar_evento,
    atualizar_area_monitorada,
    atualizar_alert_recipient,
    atualizar_machine_monitor,
    atualizar_camera_video_info,
    alterar_senha_camera,
    classificar_evento,
    criar_camera,
    criar_alert_recipient,
    criar_cliente,
    criar_dispositivo,
    criar_area_monitorada,
    criar_ocorrencia_zona,
    criar_machine_monitor,
    criar_regra,
    criar_unidade,
    excluir_area_monitorada,
    excluir_alert_recipient,
    excluir_machine_monitor,
    listar,
    listar_alert_deliveries,
    listar_alert_recipients,
    listar_areas_camera,
    listar_eventos_filtrados,
    listar_machine_monitors_camera,
    listar_regras,
    listar_por_cliente,
    obter_alert_delivery,
    obter_alert_recipient,
    obter_camera,
    obter_evento,
    obter_machine_monitor,
    obter_regra,
    reconhecer_ocorrencia,
    registrar_evento,
    registrar_audit_log,
    atualizar_regra,
    ultimo_edge_heartbeat,
    new_id,
)
from app.pilot import acceptance_checklist, health_snapshot
from app.security import hash_password
from app.machine_monitoring import baseline_stats, calibrate_threshold
from app.operations_history import (
    current_status,
    list_operational_events,
    operations_summary,
    operations_timeline,
)
from app.reports import daily_report_data
from app.report_delivery import (
    build_report_for_tenant,
    ensure_report_delivery_schema,
    get_report_schedule,
    send_due_reports_once,
    send_report_email,
    start_report_scheduler,
    stop_report_scheduler,
    upsert_report_schedule,
)
from app.restricted_area import normalize_points
from app.visual_rule_engine import condition_templates, default_rule_payloads, evaluate_rule
from app.video_understanding import VideoUnderstandingError, VideoUnderstandingService
from shared.schemas import now_iso

api = FastAPI(title="Visual Operations Internal API")
logger = logging.getLogger("campex.api")
FRONTEND_DIR = ROOT / "frontend"
live_streams = LiveStreamManager()
live_view_sessions: dict[str, dict[str, Any]] = {}
GOOGLE_OAUTH_STATE_COOKIE = "campex_google_oauth_state"
GOOGLE_OAUTH_NEXT_COOKIE = "campex_google_oauth_next"
GOOGLE_AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

if FRONTEND_DIR.exists():
    api.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


def _link_machine_monitor_areas(connection, camera_id: str, monitor_id: str) -> dict[str, str | None]:
    linked: dict[str, str | None] = {"machine_region_id": None, "operator_zone_id": None, "operation_area_id": None}
    areas = listar_areas_camera(connection, camera_id)
    for area in areas:
        if not area.get("ativa"):
            continue
        area_type = area.get("tipo")
        if area_type == "machine_region" and linked["machine_region_id"] is None:
            atualizar_area_monitorada(connection, area["id"], machine_id=monitor_id)
            linked["machine_region_id"] = area["id"]
        if area_type in {"operator_zone", "workstation"} and linked["operator_zone_id"] is None:
            atualizar_area_monitorada(connection, area["id"], machine_id=monitor_id)
            atualizar_machine_monitor(connection, monitor_id, operator_polygon=area["pontos"])
            linked["operator_zone_id"] = area["id"]
        if area_type == "work_area" and linked["operation_area_id"] is None:
            atualizar_area_monitorada(connection, area["id"], machine_id=monitor_id)
            atualizar_machine_monitor(connection, monitor_id, operation_polygon=area["pontos"], presence_scope="OPERATION_AREA")
            linked["operation_area_id"] = area["id"]
    return linked


class ClienteIn(BaseModel):
    nome: str
    documento: Optional[str] = None
    status: str = "ativo"


class ClienteUpdateIn(BaseModel):
    nome: Optional[str] = None
    documento: Optional[str] = None
    status: Optional[str] = None


class UnidadeIn(BaseModel):
    cliente_id: Optional[str] = None
    nome: str
    localizacao: Optional[str] = None
    timezone: str = "America/Sao_Paulo"


class DispositivoIn(BaseModel):
    unidade_id: str
    nome: str
    status: str = "offline"


class CameraIn(BaseModel):
    cliente_id: Optional[str] = None
    unidade_id: Optional[str] = None
    dispositivo_id: Optional[str] = None
    edge_id: Optional[str] = None
    nome: str
    config_ref: Optional[str] = None
    source_type: Optional[str] = None
    secure_ref: Optional[str] = None
    status: str = "nao_conectada"


class CameraRtspIn(BaseModel):
    nome: str
    unidade_id: Optional[str] = None
    cliente_id: Optional[str] = None
    dispositivo_id: Optional[str] = None
    edge_id: Optional[str] = None
    host: Optional[str] = None
    porta_rtsp: int = 554
    usuario: Optional[str] = None
    senha: Optional[str] = None
    caminho_rtsp: Optional[str] = None
    rtsp_url: Optional[str] = None
    testar_conexao: bool = True
    canal: Optional[str] = None
    ativa: bool = True


class CameraPatchIn(BaseModel):
    ativa: Optional[bool] = None
    nome: Optional[str] = None


class CameraRtspTestIn(BaseModel):
    host: Optional[str] = None
    porta_rtsp: int = 554
    usuario: Optional[str] = None
    senha: Optional[str] = None
    caminho_rtsp: Optional[str] = None
    rtsp_url: Optional[str] = None
    timeout_seconds: float = 5.0


class LiveViewStartIn(CameraRtspTestIn):
    nome: str = "Live View"
    camera_id: Optional[str] = None


class RegraIn(BaseModel):
    camera_id: str
    tipo_evento: str
    tempo_minimo: float = 0
    ativo: bool = True
    nome: Optional[str] = None
    cliente_id: Optional[str] = None
    unidade_id: Optional[str] = None
    entidade: Optional[str] = None
    regiao_id: Optional[str] = None
    condicao: dict[str, Any] = {}
    severidade: str = "medium"
    cooldown_seconds: float = 60
    destinatarios: list[str] = []
    alerta_inicio: bool = True
    alerta_normalizacao: bool = False
    debounce_seconds: float = 1
    hysteresis_seconds: float = 1
    metadata: dict[str, Any] = {}


class RegraPatchIn(BaseModel):
    nome: Optional[str] = None
    tipo_evento: Optional[str] = None
    tempo_minimo: Optional[float] = None
    ativo: Optional[bool] = None
    entidade: Optional[str] = None
    regiao_id: Optional[str] = None
    condicao: Optional[dict[str, Any]] = None
    severidade: Optional[str] = None
    cooldown_seconds: Optional[float] = None
    destinatarios: Optional[list[str]] = None
    alerta_inicio: Optional[bool] = None
    alerta_normalizacao: Optional[bool] = None
    debounce_seconds: Optional[float] = None
    hysteresis_seconds: Optional[float] = None
    metadata: Optional[dict[str, Any]] = None


class VisualRuleSimulationIn(BaseModel):
    facts: dict[str, Any]
    at: Optional[str] = None


class VisualRuleDefaultsIn(BaseModel):
    zone_id: Optional[str] = None


class DevTestEventIn(BaseModel):
    camera_id: Optional[str] = None
    area_id: Optional[str] = None
    event_type: str = "workstation_unattended"


class EventoIn(BaseModel):
    cliente_id: str
    unidade_id: str
    camera_id: str
    tipo: str
    inicio: Optional[str] = None
    fim: Optional[str] = None
    duracao: Optional[float] = None
    operador_presente: Optional[bool] = None
    confianca: Optional[float] = None
    midia_path: Optional[str] = None


class EventoUpdateIn(BaseModel):
    fim: Optional[str] = None
    duracao: Optional[float] = None
    operador_presente: Optional[bool] = None
    confianca: Optional[float] = None
    midia_path: Optional[str] = None
    status: Optional[str] = None
    observacao: Optional[str] = None
    acknowledged_by: Optional[str] = None


class AreaPointIn(BaseModel):
    x: float
    y: float


class AreaIn(BaseModel):
    camera_id: Optional[str] = None
    cliente_id: Optional[str] = None
    unidade_id: Optional[str] = None
    machine_id: Optional[str] = None
    nome: Optional[str] = None
    name: Optional[str] = None
    pontos: Optional[list[AreaPointIn]] = None
    polygon: Optional[list[AreaPointIn]] = None
    tipo: Optional[str] = None
    area_type: Optional[str] = None
    ativa: Optional[bool] = None
    active: Optional[bool] = None
    collaborator_name: Optional[str] = None
    expected_start: Optional[str] = None
    expected_end: Optional[str] = None
    absence_tolerance_seconds: Optional[float] = None
    dwell_limit_seconds: Optional[float] = None
    expected_min_people: Optional[int] = None
    metadata: Optional[dict[str, Any]] = None

    def resolved_name(self) -> str:
        value = self.name or self.nome
        if not value:
            raise ValueError("Nome da zona obrigatorio.")
        return value

    def resolved_type(self) -> str:
        return self.area_type or self.tipo or "restricted_area"

    def resolved_points(self) -> list[AreaPointIn]:
        points = self.polygon or self.pontos
        if points is None:
            raise ValueError("Poligono da zona obrigatorio.")
        return points

    def resolved_active(self) -> bool:
        if self.active is not None:
            return self.active
        if self.ativa is not None:
            return self.ativa
        return True


class AreaPatchIn(BaseModel):
    machine_id: Optional[str] = None
    nome: Optional[str] = None
    tipo: Optional[str] = None
    pontos: Optional[list[AreaPointIn]] = None
    ativa: Optional[bool] = None
    collaborator_name: Optional[str] = None
    expected_start: Optional[str] = None
    expected_end: Optional[str] = None
    absence_tolerance_seconds: Optional[float] = None
    dwell_limit_seconds: Optional[float] = None
    expected_min_people: Optional[int] = None
    metadata: Optional[dict[str, Any]] = None


class AlertRecipientIn(BaseModel):
    nome: str
    email: str
    ativo: bool = True
    cliente_id: Optional[str] = None
    camera_id: Optional[str] = None
    area_id: Optional[str] = None
    severidade_minima: str = "low"
    event_types: list[str] = []


class AlertRecipientPatchIn(BaseModel):
    nome: Optional[str] = None
    email: Optional[str] = None
    ativo: Optional[bool] = None
    camera_id: Optional[str] = None
    area_id: Optional[str] = None
    severidade_minima: Optional[str] = None
    event_types: Optional[list[str]] = None


class LoginIn(BaseModel):
    email: str
    senha: str


class SignupIn(BaseModel):
    nome: str
    email: str
    senha: str
    empresa_nome: str


class UserIn(BaseModel):
    nome: Optional[str] = None
    email: str
    senha: str
    role: str
    cliente_id: Optional[str] = None


class ResetPasswordIn(BaseModel):
    email: str
    nova_senha: str


class FirstRunIn(BaseModel):
    admin_nome: str
    admin_email: str
    admin_senha: str
    empresa_nome: str
    empresa_documento: Optional[str] = None
    unidade_nome: str
    unidade_localizacao: Optional[str] = None
    timezone: str = "America/Sao_Paulo"


class CameraPasswordIn(BaseModel):
    senha: str


class MachineMonitorIn(BaseModel):
    nome: str
    machine_polygon: list[AreaPointIn]
    operator_polygon: list[AreaPointIn]
    operation_polygon: Optional[list[AreaPointIn]] = None
    presence_scope: str = "OPERATOR_ZONE"
    ativo: bool = True
    motion_sensitivity: float = 25.0
    stop_seconds: float = 10.0
    recovery_seconds: float = 3.0
    replay_pre_seconds: float = 60.0
    replay_post_seconds: float = 30.0
    operator_absence_seconds: float = 30.0
    stopped_with_operator_seconds: float = 120.0
    microstop_window_seconds: float = 3600.0
    microstop_limit: int = 5
    loss_model: Optional[str] = None
    loss_per_minute: Optional[float] = None
    units_per_minute: Optional[float] = None
    margin_per_unit: Optional[float] = None
    indicator_polygon: Optional[list[AreaPointIn]] = None


class MachineMonitorPatchIn(BaseModel):
    nome: Optional[str] = None
    machine_polygon: Optional[list[AreaPointIn]] = None
    operator_polygon: Optional[list[AreaPointIn]] = None
    operation_polygon: Optional[list[AreaPointIn]] = None
    presence_scope: Optional[str] = None
    ativo: Optional[bool] = None
    motion_sensitivity: Optional[float] = None
    motion_threshold: Optional[float] = None
    stop_seconds: Optional[float] = None
    recovery_seconds: Optional[float] = None
    operator_absence_seconds: Optional[float] = None
    stopped_with_operator_seconds: Optional[float] = None
    microstop_window_seconds: Optional[float] = None
    microstop_limit: Optional[int] = None
    loss_model: Optional[str] = None
    loss_per_minute: Optional[float] = None
    units_per_minute: Optional[float] = None
    margin_per_unit: Optional[float] = None
    indicator_polygon: Optional[list[AreaPointIn]] = None


class MachineCalibrationIn(BaseModel):
    running_motion: Optional[float] = None
    stopped_motion: Optional[float] = None
    samples: Optional[list[float]] = None
    duration_seconds: float = 20.0


class AssetEconomicConfigIn(BaseModel):
    method: Optional[str] = None
    downtime_cost_per_hour: Optional[float] = None
    production_rate_per_hour: Optional[float] = None
    contribution_value_per_unit: Optional[float] = None
    currency: str = "BRL"
    effective_from: Optional[str] = None


class SetupAreaIn(BaseModel):
    cliente_id: Optional[str] = None
    unidade_id: str
    nome: str
    tipo: str = "production_area"


class SetupProcessIn(BaseModel):
    cliente_id: Optional[str] = None
    unidade_id: str
    area_id: Optional[str] = None
    nome: str
    tipo: str = "station"


class SetupAssetIn(BaseModel):
    cliente_id: Optional[str] = None
    unidade_id: str
    area_id: Optional[str] = None
    process_id: Optional[str] = None
    nome: str
    tipo: str = "machine"


class SetupCameraContextIn(BaseModel):
    area_context_id: Optional[str] = None
    process_id: Optional[str] = None
    asset_id: Optional[str] = None


class AssistedMachineCalibrationIn(BaseModel):
    duration_seconds: float = 30.0


class EventCauseIn(BaseModel):
    cause_category: str
    cause_notes: Optional[str] = None
    classified_by: Optional[str] = None


class EventHumanContextIn(BaseModel):
    confirmed_cause: Optional[str] = None
    action_taken: Optional[str] = None
    human_notes: Optional[str] = None


class EventResolveIn(BaseModel):
    confirmed_cause: Optional[str] = None
    action_taken: Optional[str] = None
    human_notes: Optional[str] = None


class EventOperationalMemoryIn(BaseModel):
    confirmed_cause: Optional[str] = None
    action_taken: Optional[str] = None
    recommendation_id: Optional[str] = None
    recommendation_accepted: Optional[bool] = None
    outcome_status: Optional[str] = None
    outcome_notes: Optional[str] = None
    human_notes: Optional[str] = None


class LiveViewMachineIn(BaseModel):
    nome: str
    tipo: Optional[str] = None
    machine_polygon: list[AreaPointIn]
    operator_polygon: Optional[list[AreaPointIn]] = None


class LiveViewOperatorZoneIn(BaseModel):
    operator_polygon: list[AreaPointIn]


def resolve_unidade_cliente(connection, unidade_id: str, cliente_id: str | None) -> str:
    unidade = connection.execute("SELECT id, cliente_id FROM unidades WHERE id = ?", (unidade_id,)).fetchone()
    if unidade is None:
        raise HTTPException(status_code=400, detail="Unidade não encontrada. Cadastre ou informe um unidade_id válido.")
    real_cliente_id = str(unidade["cliente_id"])
    if cliente_id and cliente_id != real_cliente_id:
        raise HTTPException(status_code=400, detail="Cliente informado não pertence à unidade selecionada.")
    return real_cliente_id


def default_cliente_unidade(connection, cliente_id: str | None = None, unidade_id: str | None = None) -> tuple[str, str]:
    if unidade_id:
        resolved_cliente_id = resolve_unidade_cliente(connection, unidade_id, cliente_id)
        return resolved_cliente_id, unidade_id

    if cliente_id:
        cliente = connection.execute("SELECT id FROM clientes WHERE id = ?", (cliente_id,)).fetchone()
        if cliente is None:
            raise HTTPException(status_code=400, detail="Cliente não encontrado.")
    else:
        cliente = connection.execute("SELECT id FROM clientes ORDER BY criado_em ASC LIMIT 1").fetchone()
        if cliente is None:
            cliente_id = criar_cliente(connection, "Cliente padrão")
        else:
            cliente_id = str(cliente["id"])

    unidade = connection.execute(
        "SELECT id FROM unidades WHERE cliente_id = ? ORDER BY criado_em ASC LIMIT 1",
        (cliente_id,),
    ).fetchone()
    if unidade is None:
        unidade_id = criar_unidade(connection, str(cliente_id), "Unidade padrão")
    else:
        unidade_id = str(unidade["id"])
    return str(cliente_id), unidade_id


def require_same_tenant(user: dict[str, Any], cliente_id: str | None, message: str = "Registro de outro cliente.") -> None:
    tenant = tenant_filter(user)
    if tenant and cliente_id != tenant:
        raise HTTPException(status_code=403, detail=message)


def effective_cliente_id(user: dict[str, Any], requested: str | None = None) -> str | None:
    return requested if user["role"] == "admin_campex" else user.get("cliente_id")


def require_camera_access(connection, user: dict[str, Any], camera_id: str | None) -> None:
    if not camera_id:
        return
    camera = obter_camera(connection, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera nao encontrada.")
    require_same_tenant(user, camera.get("cliente_id"), "Camera de outro cliente.")


def require_event_access(connection, user: dict[str, Any], evento_id: str) -> dict[str, Any]:
    event = obter_evento(connection, evento_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Evento nao encontrado.")
    require_same_tenant(user, event.get("cliente_id"), "Evento de outro cliente.")
    return event


def require_alert_delivery_access(connection, user: dict[str, Any], delivery_id: str) -> dict[str, Any]:
    delivery = obter_alert_delivery(connection, delivery_id)
    if delivery is None:
        raise HTTPException(status_code=404, detail="Entrega nao encontrada.")
    event_id = delivery.get("evento_id")
    if event_id:
        require_event_access(connection, user, str(event_id))
        return delivery
    recipient_id = delivery.get("recipient_id")
    if recipient_id:
        recipient = obter_alert_recipient(connection, str(recipient_id))
        if recipient is None:
            raise HTTPException(status_code=404, detail="Responsavel nao encontrado.")
        require_same_tenant(user, recipient.get("cliente_id"), "Entrega de outro cliente.")
    return delivery


def require_area_access(connection, user: dict[str, Any], area_id: str) -> dict[str, Any]:
    row = connection.execute("SELECT * FROM monitored_areas WHERE id = ?", (area_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Area nao encontrada.")
    area = dict(row)
    require_camera_access(connection, user, area.get("camera_id"))
    return area


def require_live_view_session_access(connection, request: Request, session_id: str) -> dict[str, Any]:
    session = live_view_sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Live View não encontrada.")
    user = require_user(request, connection)
    camera_id = session.get("camera_id")
    if camera_id:
        require_camera_access(connection, user, str(camera_id))
    session_tenant = session.get("cliente_id")
    if session_tenant:
        require_same_tenant(user, str(session_tenant), "Live View de outro cliente.")
    return session


@api.on_event("startup")
def startup() -> None:
    with connect() as connection:
        init_db(connection)
        ensure_report_delivery_schema(connection)
    resume_pending_deliveries()
    start_report_scheduler()


@api.on_event("shutdown")
def shutdown() -> None:
    stop_report_scheduler()
    live_streams.stop_all()


@api.get("/")
def index() -> RedirectResponse:
    return RedirectResponse(url="/operations-view", status_code=307)


@api.get("/home")
def home_page() -> RedirectResponse:
    return RedirectResponse(url="/operations-view", status_code=307)


@api.get("/dashboard")
def dashboard_page() -> RedirectResponse:
    return RedirectResponse(url="/operations-view", status_code=307)


INTERNAL_ROUTE_FILES = {
    "/overview": "dashboard.html",
    "/operations-view": "workspace.html",
    "/cameras": "workspace.html",
    "/events": "workspace.html",
    "/alerts": "workspace.html",
    "/evidence": "workspace.html",
    "/rules": "workspace.html",
    "/reports": "workspace.html",
    "/insights": "workspace.html",
    "/history": "workspace.html",
    "/integrations": "workspace.html",
    "/users": "workspace.html",
    "/settings": "workspace.html",
    "/settings/cameras": "index.html",
    "/settings/notifications": "workspace.html",
    "/settings/account": "workspace.html",
    "/help": "workspace.html",
}


@api.get("/login", include_in_schema=False)
def login_page() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "login.html")


@api.get("/login/", include_in_schema=False)
def login_page_slash() -> FileResponse:
    return login_page()


FRONTEND_404_PREFIXES = {"settings"}
API_404_PREFIXES = {
    "alert-deliveries",
    "alert-recipients",
    "api",
    "assets",
    "auth",
    "cameras",
    "clientes",
    "dispositivos",
    "eventos",
    "events",
    "health",
    "live-grid",
    "live-view",
    "people-zones",
    "operations",
    "relatorios",
    "static",
    "unidades",
}


def _request_has_valid_session(request: Request) -> bool:
    with connect() as connection:
        init_db(connection)
        return get_request_user(request, connection) is not None


def _login_redirect_for(request: Request) -> RedirectResponse:
    next_path = request.url.path
    if request.url.query:
        next_path = f"{next_path}?{request.url.query}"
    return RedirectResponse(url=f"/login?next={quote(next_path, safe='')}", status_code=303)


def _protected_frontend_response(request: Request, filename: str):
    if not _request_has_valid_session(request):
        return _login_redirect_for(request)
    return FileResponse(FRONTEND_DIR / filename)


def serve_internal_route(request: Request):
    filename = INTERNAL_ROUTE_FILES.get(request.url.path)
    if filename is None:
        raise HTTPException(status_code=404, detail="Página não encontrada.")
    return _protected_frontend_response(request, filename)


for internal_route in INTERNAL_ROUTE_FILES:
    api.add_api_route(
        internal_route,
        serve_internal_route,
        methods=["GET"],
        include_in_schema=False,
        name=f"internal_{internal_route.strip('/').replace('/', '_') or 'home'}",
    )


def serve_internal_not_found(request: Request) -> FileResponse:
    path = request.url.path.strip("/")
    first_segment = path.split("/", 1)[0]
    if "." in path or first_segment in API_404_PREFIXES:
        raise HTTPException(status_code=404, detail="Not Found")
    if "/" in path and first_segment not in FRONTEND_404_PREFIXES:
        raise HTTPException(status_code=404, detail="Not Found")
    return FileResponse(FRONTEND_DIR / "workspace.html", status_code=404)


@api.get("/live-view")
def live_view_page(request: Request):
    return _protected_frontend_response(request, "live-view.html")


@api.get("/live-view/")
def live_view_page_slash(request: Request):
    return live_view_page(request)


@api.get("/live-grid")
def live_grid_page(request: Request):
    return _protected_frontend_response(request, "live-grid.html")


@api.get("/live-grid/")
def live_grid_page_slash(request: Request):
    return live_grid_page(request)


@api.get("/people-zones")
def people_zones_page(request: Request):
    return _protected_frontend_response(request, "people-zones.html")


@api.get("/people-zones/")
def people_zones_page_slash(request: Request):
    return people_zones_page(request)


@api.get("/local-diagnostics-view")
def local_diagnostics_view_page() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "local-diagnostics.html")


@api.get("/local-diagnostics-view/")
def local_diagnostics_view_page_slash() -> FileResponse:
    return local_diagnostics_view_page()


@api.get("/operations-dashboard")
def operations_dashboard_page() -> RedirectResponse:
    return RedirectResponse(url="/operations-view", status_code=307)


@api.get("/dashboard.html")
def dashboard_html_page() -> RedirectResponse:
    return RedirectResponse(url="/dashboard", status_code=307)


@api.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _recent_iso(value: object, max_age_seconds: float = 15.0) -> bool:
    if not value:
        return False
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() <= max_age_seconds
    except Exception:
        return False


@api.get("/ready")
def ready() -> dict[str, object]:
    streams = live_streams.statuses()
    with connect() as connection:
        init_db(connection)
        cameras_total = connection.execute("SELECT COUNT(*) AS total FROM cameras WHERE ativa = 1").fetchone()["total"]
        monitors_ready = connection.execute(
            "SELECT COUNT(*) AS total FROM machine_monitors WHERE ativo = 1 AND calibration_result = 'READY'"
        ).fetchone()["total"]
        outbox_pending = connection.execute(
            "SELECT COUNT(*) AS total FROM sync_outbox WHERE status IN ('pending', 'failed')"
        ).fetchone()["total"]
    stream_online = any(stream.get("status") == "online" and _recent_iso(stream.get("last_frame_at")) for stream in streams)
    inference_ready = any(
        (float(stream.get("analysis_fps") or 0) > 0 or int(stream.get("analysis_frames") or 0) > 0)
        and _recent_iso(stream.get("last_analysis_at"))
        for stream in streams
    )
    monitor_loaded = any(stream.get("machine_monitor_id") for stream in streams)
    database_ready = True
    ready_state = database_ready and cameras_total > 0 and stream_online and inference_ready and monitors_ready > 0 and monitor_loaded
    return {
        "status": "ready" if ready_state else "not_ready",
        "database": "ready" if database_ready else "not_ready",
        "cameras_registered": cameras_total,
        "camera_stream": "ready" if stream_online else "not_ready",
        "inference": "ready" if inference_ready else "not_ready",
        "machine_monitors_ready": monitors_ready,
        "machine_monitor_loaded": "ready" if monitor_loaded else "not_ready",
        "workers": {
            "live_streams": len(streams),
            "outbox_pending": outbox_pending,
        },
    }


@api.get("/edge/status")
def get_edge_runtime_status(
    request: Request,
    edge_id: Optional[str] = None,
) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_role(user, {"admin_campex"})

    disk = psutil.disk_usage(str(ROOT))
    streams = live_streams.statuses()
    with connect() as connection:
        init_db(connection)
        heartbeat = ultimo_edge_heartbeat(connection, edge_id)
        outbox_pending = connection.execute(
            "SELECT COUNT(*) AS total FROM sync_outbox WHERE status IN ('pending', 'failed')"
        ).fetchone()["total"]
        last_event = connection.execute("SELECT * FROM eventos ORDER BY criado_em DESC LIMIT 1").fetchone()
        cameras = connection.execute("SELECT id, nome, status, ultimo_frame, fps, frames_processados, ultimo_erro FROM cameras ORDER BY nome").fetchall()
    stream_by_camera = {stream["camera_id"]: stream for stream in streams}
    return {
        "edge_id": edge_id or os.getenv("CAMPEX_EDGE_ID"),
        "heartbeat": heartbeat,
        "cameras": [
            {**_camera_with_runtime_status(dict(camera), stream_by_camera.get(camera["id"])), "stream": stream_by_camera.get(camera["id"])}
            for camera in cameras
        ],
        "last_event": dict(last_event) if last_event else None,
        "outbox_pending": outbox_pending,
        "disk": {
            "free_bytes": disk.free,
            "used_percent": disk.percent,
        },
    }


@api.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "campex-logo-oficial.png", media_type="image/png")


@api.get("/users")
def get_users(request: Request) -> list[dict[str, Any]]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_role(user, ADMIN_ROLES)

        tenant = tenant_filter(user)

        if tenant:
            rows = connection.execute(
                "SELECT id, cliente_id, nome, email, role, ativo FROM users WHERE cliente_id = ? ORDER BY nome, email",
                (tenant,),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT id, cliente_id, nome, email, role, ativo FROM users ORDER BY nome, email"
            ).fetchall()

        return [dict(row) for row in rows]


@api.post("/users", status_code=status.HTTP_201_CREATED)
def post_user(payload: UserIn, request: Request) -> dict[str, Any]:
    if len(payload.senha) < 8:
        raise HTTPException(
            status_code=400,
            detail="A senha deve ter pelo menos 8 caracteres.",
        )

    allowed_customer_roles = {"admin_cliente", "operador", "visualizador"}
    if payload.role not in allowed_customer_roles:
        raise HTTPException(
            status_code=400,
            detail="Função de usuário inválida.",
        )

    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_role(user, ADMIN_ROLES)

        if user["role"] == "admin_campex":
            cliente_id = payload.cliente_id
            if not cliente_id:
                raise HTTPException(
                    status_code=400,
                    detail="Empresa é obrigatória para criar o usuário.",
                )

            cliente = connection.execute(
                "SELECT id FROM clientes WHERE id = ?",
                (cliente_id,),
            ).fetchone()
            if cliente is None:
                raise HTTPException(
                    status_code=404,
                    detail="Empresa não encontrada.",
                )
        else:
            cliente_id = user.get("cliente_id")
            if payload.cliente_id and payload.cliente_id != cliente_id:
                raise HTTPException(
                    status_code=403,
                    detail="Não é permitido criar usuário para outra empresa.",
                )

            if payload.role == "admin_cliente":
                raise HTTPException(
                    status_code=403,
                    detail="Administrador do cliente não pode criar outro administrador.",
                )

        existing = connection.execute(
            "SELECT id FROM users WHERE email = ?",
            (payload.email.lower().strip(),),
        ).fetchone()
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail="Já existe usuário com este e-mail.",
            )

        user_id = create_user(
            connection,
            payload.email,
            payload.senha,
            payload.role,
            cliente_id=cliente_id,
            nome=payload.nome,
        )

        created = connection.execute(
            """
            SELECT id, cliente_id, nome, email, role, ativo
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        ).fetchone()

        registrar_audit_log(
            connection,
            action="user.create",
            actor=user,
            entity_type="user",
            entity_id=user_id,
            tenant_id=cliente_id,
            metadata={"role": payload.role},
        )

        return dict(created)


@api.post("/auth/login")
def post_login(payload: LoginIn, response: Response) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        user = authenticate(connection, payload.email, payload.senha)
        if user is None:
            raise HTTPException(status_code=401, detail="E-mail ou senha invalidos.")
        token = create_session(connection, user["id"])
        registrar_audit_log(connection, action="auth.login", actor=user, entity_type="user", entity_id=user["id"], tenant_id=user.get("cliente_id"))
    response.set_cookie("campex_session", token, httponly=True, samesite="lax")
    return {"user": user}


@api.post("/auth/signup", status_code=status.HTTP_201_CREATED)
def post_signup(payload: SignupIn, response: Response) -> dict[str, object]:
    if os.getenv("CAMPEX_ENABLE_PUBLIC_SIGNUP", "").strip().lower() not in {"1", "true", "yes", "on"}:
        raise HTTPException(status_code=403, detail="Cadastro público desativado. Solicite uma demonstração com a Campex.")

    nome = payload.nome.strip()
    email = payload.email.lower().strip()
    empresa_nome = payload.empresa_nome.strip()
    if not nome:
        raise HTTPException(status_code=400, detail="Nome é obrigatório.")
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="E-mail válido é obrigatório.")
    if len(payload.senha) < 8:
        raise HTTPException(status_code=400, detail="A senha deve ter pelo menos 8 caracteres.")
    if not empresa_nome:
        raise HTTPException(status_code=400, detail="Nome da empresa é obrigatório.")

    with connect() as connection:
        init_db(connection)
        existing = connection.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if existing is not None:
            raise HTTPException(status_code=409, detail="Já existe usuário com este e-mail.")

        cliente_id = criar_cliente(connection, empresa_nome)
        unidade_id = criar_unidade(connection, cliente_id, "Unidade principal")
        user_id = create_user(connection, email, payload.senha, "admin_cliente", cliente_id=cliente_id, nome=nome)
        token = create_session(connection, user_id)
        user = find_active_user_by_email(connection, email)
        registrar_audit_log(
            connection,
            action="auth.signup",
            actor=user,
            entity_type="cliente",
            entity_id=cliente_id,
            tenant_id=cliente_id,
            metadata={"unidade_id": unidade_id, "role": "admin_cliente"},
        )

    response.set_cookie("campex_session", token, httponly=True, samesite="lax")
    return {
        "cliente_id": cliente_id,
        "unidade_id": unidade_id,
        "user": user,
        "next": "/operations-view?view=home",
    }


def _safe_oauth_next(value: str | None) -> str:
    if not value:
        return "/operations-view?view=home"
    text = value.strip()
    if not text.startswith("/") or text.startswith("//") or "\r" in text or "\n" in text:
        return "/operations-view?view=home"
    return text


def _oauth_redirect_with_error(error: str) -> RedirectResponse:
    return RedirectResponse(url=f"/login?oauth_error={error}", status_code=303)


def _google_redirect_uri() -> str:
    base_url = (os.getenv("CAMPEX_PUBLIC_BASE_URL") or "http://127.0.0.1:8000").rstrip("/")
    return f"{base_url}/auth/oauth/google/callback"


@api.get("/auth/oauth/google/start")
def google_oauth_start(next: Optional[str] = None) -> RedirectResponse:
    client_id = os.getenv("CAMPEX_GOOGLE_CLIENT_ID")
    client_secret = os.getenv("CAMPEX_GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        return _oauth_redirect_with_error("google_failed")
    state = secrets.token_urlsafe(32)
    safe_next = _safe_oauth_next(next)
    params = {
        "client_id": client_id,
        "redirect_uri": _google_redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    response = RedirectResponse(url=f"{GOOGLE_AUTHORIZATION_URL}?{urlencode(params)}", status_code=303)
    response.set_cookie(GOOGLE_OAUTH_STATE_COOKIE, state, httponly=True, samesite="lax", max_age=600)
    response.set_cookie(GOOGLE_OAUTH_NEXT_COOKIE, safe_next, httponly=True, samesite="lax", max_age=600)
    return response


@api.get("/auth/oauth/google/callback")
def google_oauth_callback(request: Request, response: Response, code: Optional[str] = None, state: Optional[str] = None) -> RedirectResponse:
    expected_state = request.cookies.get(GOOGLE_OAUTH_STATE_COOKIE)
    next_url = _safe_oauth_next(request.cookies.get(GOOGLE_OAUTH_NEXT_COOKIE))
    if not code or not state or not expected_state or not secrets.compare_digest(state, expected_state):
        redirect = _oauth_redirect_with_error("invalid_state")
        redirect.delete_cookie(GOOGLE_OAUTH_STATE_COOKIE)
        redirect.delete_cookie(GOOGLE_OAUTH_NEXT_COOKIE)
        return redirect

    client_id = os.getenv("CAMPEX_GOOGLE_CLIENT_ID")
    client_secret = os.getenv("CAMPEX_GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        redirect = _oauth_redirect_with_error("google_failed")
        redirect.delete_cookie(GOOGLE_OAUTH_STATE_COOKIE)
        redirect.delete_cookie(GOOGLE_OAUTH_NEXT_COOKIE)
        return redirect

    try:
        token_response = httpx.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": _google_redirect_uri(),
                "grant_type": "authorization_code",
            },
            headers={"Accept": "application/json"},
            timeout=10.0,
        )
        token_response.raise_for_status()
        access_token = token_response.json().get("access_token")
        if not access_token:
            raise ValueError("missing access token")
        userinfo_response = httpx.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            timeout=10.0,
        )
        userinfo_response.raise_for_status()
        identity = userinfo_response.json()
    except Exception:
        redirect = _oauth_redirect_with_error("google_failed")
        redirect.delete_cookie(GOOGLE_OAUTH_STATE_COOKIE)
        redirect.delete_cookie(GOOGLE_OAUTH_NEXT_COOKIE)
        return redirect

    email = str(identity.get("email") or "").lower().strip()
    email_verified = identity.get("email_verified") is True or str(identity.get("email_verified")).lower() == "true"
    if not email or not email_verified:
        redirect = _oauth_redirect_with_error("google_failed")
        redirect.delete_cookie(GOOGLE_OAUTH_STATE_COOKIE)
        redirect.delete_cookie(GOOGLE_OAUTH_NEXT_COOKIE)
        return redirect

    with connect() as connection:
        init_db(connection)
        user = find_active_user_by_email(connection, email)
        if user is None:
            redirect = _oauth_redirect_with_error("access_not_provisioned")
            redirect.delete_cookie(GOOGLE_OAUTH_STATE_COOKIE)
            redirect.delete_cookie(GOOGLE_OAUTH_NEXT_COOKIE)
            return redirect
        token = create_session(connection, user["id"])
        registrar_audit_log(connection, action="auth.oauth.google.login", actor=user, entity_type="user", entity_id=user["id"], tenant_id=user.get("cliente_id"))

    redirect = RedirectResponse(url=next_url, status_code=303)
    redirect.set_cookie("campex_session", token, httponly=True, samesite="lax")
    redirect.delete_cookie(GOOGLE_OAUTH_STATE_COOKIE)
    redirect.delete_cookie(GOOGLE_OAUTH_NEXT_COOKIE)
    return redirect


@api.post("/auth/logout")
def post_logout(request: Request, response: Response) -> dict[str, object]:
    token = request.cookies.get("campex_session")
    if token:
        with connect() as connection:
            init_db(connection)
            delete_session(connection, token)
    response.delete_cookie("campex_session")
    return {"ok": True}


@api.get("/auth/me")
def get_me(request: Request) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
    return {"user": user}


@api.get("/auth/status")
def get_auth_status(request: Request) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        user = get_request_user(request, connection)
        has_users = users_exist(connection)
    if user is not None:
        return {"authenticated": True, "bootstrap": False, "user": user}
    return {"authenticated": False, "bootstrap": not has_users, "user": None}


@api.get("/first-run/status")
def get_first_run_status() -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        locked = users_exist(connection)
    return {
        "available": not locked,
        "locked": locked,
        "message": "First Run disponível." if not locked else "First Run bloqueado: já existe usuário administrador.",
    }


@api.post("/first-run/complete", status_code=status.HTTP_201_CREATED)
def post_first_run_complete(payload: FirstRunIn, response: Response) -> dict[str, object]:
    if len(payload.admin_senha) < 8:
        raise HTTPException(status_code=400, detail="A senha do primeiro administrador deve ter pelo menos 8 caracteres.")
    with connect() as connection:
        init_db(connection)
        if users_exist(connection):
            raise HTTPException(status_code=403, detail="First Run bloqueado: já existe usuário cadastrado.")
        try:
            connection.execute("BEGIN")
            cliente_id = new_id("cli")
            unidade_id = new_id("uni")
            user_id = new_id("usr")
            connection.execute(
                "INSERT INTO clientes (id, nome, documento, status) VALUES (?, ?, ?, 'ativo')",
                (cliente_id, payload.empresa_nome, payload.empresa_documento),
            )
            connection.execute(
                "INSERT INTO unidades (id, cliente_id, nome, localizacao, timezone) VALUES (?, ?, ?, ?, ?)",
                (unidade_id, cliente_id, payload.unidade_nome, payload.unidade_localizacao, payload.timezone),
            )
            connection.execute(
                """
                INSERT INTO users (id, cliente_id, nome, email, password_hash, role)
                VALUES (?, ?, ?, ?, ?, 'admin_campex')
                """,
                (
                    user_id,
                    cliente_id,
                    payload.admin_nome,
                    payload.admin_email.lower().strip(),
                    hash_password(payload.admin_senha),
                ),
            )
            connection.commit()
            token = create_session(connection, user_id)
            user = authenticate(connection, payload.admin_email, payload.admin_senha)
            registrar_audit_log(
                connection,
                action="install.first_run.complete",
                actor=user,
                entity_type="cliente",
                entity_id=cliente_id,
                tenant_id=cliente_id,
                metadata={"unidade_id": unidade_id},
            )
        except Exception:
            connection.rollback()
            raise
    response.set_cookie("campex_session", token, httponly=True, samesite="lax")
    return {
        "cliente_id": cliente_id,
        "unidade_id": unidade_id,
        "user": user,
        "next": "/settings/cameras",
    }


@api.post("/auth/users")
def post_user(payload: UserIn, request: Request) -> dict[str, str]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_role(user, ADMIN_ROLES)
        cliente_id = payload.cliente_id if user["role"] == "admin_campex" else user.get("cliente_id")
        return {"id": create_user(connection, payload.email, payload.senha, payload.role, cliente_id, payload.nome)}


@api.post("/auth/reset-password")
def post_reset_password(payload: ResetPasswordIn, request: Request) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_role(user, ADMIN_ROLES)
        return {"updated": update_user_password(connection, payload.email, payload.nova_senha)}


@api.get("/system/health")
def get_system_health(request: Request) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        require_user(request, connection)
    return health_snapshot(runtime_statuses=live_streams.statuses())


@api.get("/pilot/checklist")
def get_pilot_checklist(request: Request) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        require_user(request, connection)
    return acceptance_checklist(runtime_statuses=live_streams.statuses())


@api.get("/clientes")
def get_clientes(request: Request) -> list[dict[str, Any]]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        return listar_por_cliente(connection, "clientes", tenant_filter(user))


@api.post("/clientes")
def post_cliente(payload: ClienteIn, request: Request) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_role(user, ADMIN_ROLES)
        if user["role"] != "admin_campex" and user.get("cliente_id"):
            raise HTTPException(status_code=403, detail="Somente admin Campex cria novos clientes.")
        cliente_id = criar_cliente(connection, payload.nome, payload.status, payload.documento)
        return listar_por_cliente(connection, "clientes", cliente_id)[0]


@api.patch("/clientes/{cliente_id}")
def patch_cliente(cliente_id: str, payload: ClienteUpdateIn, request: Request) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_role(user, ADMIN_ROLES)
        require_same_tenant(user, cliente_id, "Empresa de outro cliente.")

        current = connection.execute("SELECT * FROM clientes WHERE id = ?", (cliente_id,)).fetchone()
        if current is None:
            raise HTTPException(status_code=404, detail="Empresa não encontrada.")

        nome = payload.nome.strip() if payload.nome is not None else current["nome"]
        documento = payload.documento if payload.documento is not None else current["documento"]
        status_value = payload.status.strip() if payload.status is not None else current["status"]
        if not nome:
            raise HTTPException(status_code=400, detail="Nome da organização é obrigatório.")
        if not status_value:
            raise HTTPException(status_code=400, detail="Status da organização é obrigatório.")

        connection.execute(
            "UPDATE clientes SET nome = ?, documento = ?, status = ? WHERE id = ?",
            (nome, documento, status_value, cliente_id),
        )
        registrar_audit_log(
            connection,
            action="cliente.update",
            actor=user,
            entity_type="cliente",
            entity_id=cliente_id,
            tenant_id=cliente_id,
            metadata={"fields": [field for field in ("nome", "documento", "status") if getattr(payload, field) is not None]},
        )
        return listar_por_cliente(connection, "clientes", cliente_id)[0]


@api.post("/unidades")
def post_unidade(payload: UnidadeIn, request: Request) -> dict[str, str]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_role(user, ADMIN_ROLES)
        cliente_id = effective_cliente_id(user, payload.cliente_id)
        if cliente_id is None:
            raise HTTPException(status_code=400, detail="Informe o cliente da unidade.")
        return {"id": criar_unidade(connection, cliente_id, payload.nome, payload.localizacao, payload.timezone)}


@api.get("/unidades")
def get_unidades(request: Request, cliente_id: Optional[str] = None) -> list[dict[str, Any]]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        effective = effective_cliente_id(user, cliente_id)
        return listar_por_cliente(connection, "unidades", effective)


SETUP_CAPABILITIES = [
    {
        "id": "interruption",
        "label": "Paradas/Interrupções",
        "supported": True,
        "description": "Monitora paradas de máquina a partir da região calibrada.",
    },
    {
        "id": "absence",
        "label": "Ausência",
        "supported": True,
        "description": "Monitora ausência de operador em zona configurada.",
    },
    {
        "id": "wait",
        "label": "Espera",
        "supported": False,
        "description": "Em desenvolvimento para o piloto.",
    },
    {
        "id": "flow",
        "label": "Movimentação/Fluxo",
        "supported": False,
        "description": "Em desenvolvimento para o piloto.",
    },
]


def _setup_rows(connection, table: str, tenant: str | None) -> list[dict[str, Any]]:
    if tenant:
        rows = connection.execute(f"SELECT * FROM {table} WHERE cliente_id = ? ORDER BY criado_em DESC", (tenant,)).fetchall()
    else:
        rows = connection.execute(f"SELECT * FROM {table} ORDER BY criado_em DESC").fetchall()
    return [dict(row) for row in rows]


def _find_setup_record(connection, table: str, **filters: str | None) -> dict[str, Any] | None:
    clauses = []
    values: list[str] = []
    for key, value in filters.items():
        if value is None:
            clauses.append(f"{key} IS NULL")
        else:
            clauses.append(f"{key} = ?")
            values.append(value)
    row = connection.execute(
        f"SELECT * FROM {table} WHERE {' AND '.join(clauses)} ORDER BY criado_em ASC LIMIT 1",
        tuple(values),
    ).fetchone()
    return dict(row) if row else None


def _setup_asset_status(asset: dict[str, Any], cameras: list[dict[str, Any]], areas: list[dict[str, Any]], monitors: list[dict[str, Any]]) -> dict[str, Any]:
    asset_id = asset["id"]
    linked_cameras = [camera for camera in cameras if camera.get("asset_id") == asset_id]
    linked_camera_ids = {camera["id"] for camera in linked_cameras}
    linked_monitors = [
        monitor
        for monitor in monitors
        if monitor.get("asset_id") == asset_id or monitor.get("camera_id") in linked_camera_ids
    ]
    linked_monitor_ids = {monitor["id"] for monitor in linked_monitors}
    machine_regions = [
        area
        for area in areas
        if area.get("tipo") == "machine_region"
        and (area.get("asset_id") == asset_id or area.get("machine_id") in linked_monitor_ids or area.get("camera_id") in linked_camera_ids)
        and area.get("ativa")
    ]
    operator_zones = [
        area
        for area in areas
        if area.get("tipo") in {"operator_zone", "workstation", "work_area"}
        and (area.get("asset_id") == asset_id or area.get("machine_id") in linked_monitor_ids or area.get("camera_id") in linked_camera_ids)
        and area.get("ativa")
    ]
    active_monitor = next((monitor for monitor in linked_monitors if monitor.get("ativo")), None)
    missing = []
    if not linked_cameras:
        missing.append("associar uma câmera")
    if not machine_regions:
        missing.append("desenhar região da máquina")
    if not operator_zones:
        missing.append("desenhar zona do operador")
    if not active_monitor:
        missing.append("ativar monitor do ativo")
    return {
        "asset_id": asset_id,
        "asset_name": asset.get("nome"),
        "ready": not missing,
        "status": "Pronto para monitorar" if not missing else "Configuração incompleta",
        "missing": missing,
        "camera_ids": [camera["id"] for camera in linked_cameras],
        "monitor_ids": [monitor["id"] for monitor in linked_monitors],
        "machine_region_ids": [area["id"] for area in machine_regions],
        "operator_zone_ids": [area["id"] for area in operator_zones],
    }


def _has_operational_context(item: dict[str, Any] | None) -> bool:
    if not item:
        return False
    return bool(item.get("site_id") or item.get("unit_id") or item.get("unidade_id")) and bool(
        item.get("area_context_id") and item.get("process_id") and item.get("asset_id")
    )


def _camera_context_ready(camera: dict[str, Any], monitors: list[dict[str, Any]]) -> bool:
    if _has_operational_context(camera):
        return True
    return any(_has_operational_context(monitor) for monitor in monitors if monitor.get("camera_id") == camera.get("id"))


def _check_item(status_value: str, label: str, detail: str) -> dict[str, str]:
    return {"status": status_value, "label": label, "detail": detail}


def _setup_installation_readiness(
    *,
    clientes: list[dict[str, Any]],
    unidades: list[dict[str, Any]],
    areas: list[dict[str, Any]],
    processes: list[dict[str, Any]],
    assets: list[dict[str, Any]],
    cameras: list[dict[str, Any]],
    monitored_areas: list[dict[str, Any]],
    monitors: list[dict[str, Any]],
) -> dict[str, Any]:
    stream_by_camera = {stream.get("camera_id"): stream for stream in live_streams.statuses()}
    active_cameras = [camera for camera in cameras if camera.get("ativa", True)]
    online_streams = [
        stream for stream in stream_by_camera.values()
        if stream.get("status") == "online" and _recent_iso(stream.get("last_frame_at"))
    ]
    inference_streams = [
        stream for stream in stream_by_camera.values()
        if (float(stream.get("analysis_fps") or 0) > 0 or int(stream.get("analysis_frames") or 0) > 0)
        and _recent_iso(stream.get("last_analysis_at"))
    ]
    machine_regions = [area for area in monitored_areas if area.get("ativa") and area.get("tipo") == "machine_region"]
    operator_zones = [
        area for area in monitored_areas
        if area.get("ativa") and area.get("tipo") in {"operator_zone", "workstation", "work_area"}
    ]
    active_monitors = [monitor for monitor in monitors if monitor.get("ativo")]
    ready_monitors = [monitor for monitor in active_monitors if monitor.get("calibration_result") == "READY"]
    context_ready_cameras = [camera for camera in active_cameras if _camera_context_ready(camera, monitors)]
    email_config = email_configuration_status()
    with connect() as connection:
        init_db(connection)
        recipients = connection.execute("SELECT COUNT(*) AS total FROM alert_recipients WHERE ativo = 1").fetchone()["total"]
        outbox_pending = connection.execute("SELECT COUNT(*) AS total FROM sync_outbox WHERE status IN ('pending', 'failed')").fetchone()["total"]
        heartbeat = ultimo_edge_heartbeat(connection, os.getenv("CAMPEX_EDGE_ID"))
    checks = [
        _check_item("PASS" if clientes else "FAIL", "Empresa", f"{len(clientes)} empresa(s) cadastrada(s)"),
        _check_item("PASS" if unidades else "FAIL", "Unidade", f"{len(unidades)} unidade(s) cadastrada(s)"),
        _check_item(
            "PASS" if areas and processes and assets and context_ready_cameras else "FAIL",
            "Contexto operacional",
            f"áreas={len(areas)}, processos={len(processes)}, ativos={len(assets)}, câmeras_contextualizadas={len(context_ready_cameras)}",
        ),
        _check_item("PASS" if cameras else "FAIL", "Câmera cadastrada", f"{len(cameras)} câmera(s)"),
        _check_item(
            "PASS" if online_streams else "PENDING",
            "Câmera online",
            "frame recente comprovado" if online_streams else "Pendente: câmera precisa estar online",
        ),
        _check_item("PASS" if machine_regions else "FAIL", "Machine region", f"{len(machine_regions)} região(ões)"),
        _check_item("PASS" if operator_zones else "FAIL", "Operator zone", f"{len(operator_zones)} zona(s)"),
        _check_item("PASS" if active_monitors else "FAIL", "Monitor", f"{len(active_monitors)} monitor(es) ativo(s)"),
        _check_item(
            "PASS" if ready_monitors else "PENDING",
            "Calibração",
            "monitor READY" if ready_monitors else "Pendente: câmera precisa estar online para calibrar",
        ),
        _check_item(
            "PASS" if recipients and email_config["status"] == "CONFIGURED" else "FAIL",
            "Alertas",
            f"destinatários={recipients}, modo={email_config.get('mode') or 'não configurado'}, status={email_config['status']}",
        ),
        _check_item("PASS" if heartbeat else "PENDING", "Edge", "heartbeat recebido" if heartbeat else "Edge ainda não registrou heartbeat"),
        _check_item(
            "PASS" if inference_streams else "PENDING",
            "Inference",
            "inferência ativa com frame recente" if inference_streams else "Pendente: stream e análise precisam estar ativos",
        ),
    ]
    return {
        "checks": checks,
        "ready": all(item["status"] == "PASS" for item in checks),
        "summary": {
            "active_cameras": len(active_cameras),
            "online_streams": len(online_streams),
            "inference_streams": len(inference_streams),
            "ready_monitors": len(ready_monitors),
            "outbox_pending": outbox_pending,
        },
    }


@api.get("/setup/operation")
def get_setup_operation(request: Request) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        tenant = tenant_filter(user)
        clientes = listar_por_cliente(connection, "clientes", tenant)
        unidades = listar_por_cliente(connection, "unidades", tenant)
        areas = _setup_rows(connection, "operational_areas", tenant)
        processes = _setup_rows(connection, "operational_processes", tenant)
        assets = _setup_rows(connection, "operational_assets", tenant)
        cameras = listar_por_cliente(connection, "cameras", tenant)
        monitored_areas: list[dict[str, Any]] = []
        monitors: list[dict[str, Any]] = []
        for camera in cameras:
            monitored_areas.extend(listar_areas_camera(connection, camera["id"]))
            monitors.extend(listar_machine_monitors_camera(connection, camera["id"]))
        return {
            "clientes": clientes,
            "unidades": unidades,
            "areas": areas,
            "processes": processes,
            "assets": assets,
            "cameras": cameras,
            "monitored_areas": monitored_areas,
            "machine_monitors": monitors,
            "capabilities": SETUP_CAPABILITIES,
            "asset_status": [_setup_asset_status(asset, cameras, monitored_areas, monitors) for asset in assets],
            "readiness": _setup_installation_readiness(
                clientes=clientes,
                unidades=unidades,
                areas=areas,
                processes=processes,
                assets=assets,
                cameras=cameras,
                monitored_areas=monitored_areas,
                monitors=monitors,
            ),
        }


@api.get("/setup/readiness")
def get_setup_readiness(request: Request) -> dict[str, Any]:
    payload = get_setup_operation(request)
    return payload["readiness"]


@api.post("/setup/areas", status_code=status.HTTP_201_CREATED)
def post_setup_area(payload: SetupAreaIn, request: Request) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_role(user, ADMIN_ROLES)
        cliente_id = effective_cliente_id(user, payload.cliente_id)
        if cliente_id is None:
            unit = connection.execute("SELECT cliente_id FROM unidades WHERE id = ?", (payload.unidade_id,)).fetchone()
            cliente_id = unit["cliente_id"] if unit else None
        if cliente_id is None:
            raise HTTPException(status_code=400, detail="Unidade invalida para criar area.")
        existing = _find_setup_record(
            connection,
            "operational_areas",
            cliente_id=cliente_id,
            unidade_id=payload.unidade_id,
            nome=payload.nome,
            tipo=payload.tipo,
        )
        if existing:
            existing["created"] = False
            return existing
        area_id = criar_operational_area(connection, cliente_id=cliente_id, unidade_id=payload.unidade_id, nome=payload.nome, tipo=payload.tipo)
        created = _find_setup_record(connection, "operational_areas", id=area_id)
        if created is None:
            raise HTTPException(status_code=500, detail="Area operacional nao foi persistida.")
        created["created"] = True
        return created


@api.post("/setup/processes", status_code=status.HTTP_201_CREATED)
def post_setup_process(payload: SetupProcessIn, request: Request) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_role(user, ADMIN_ROLES)
        cliente_id = effective_cliente_id(user, payload.cliente_id)
        if cliente_id is None:
            unit = connection.execute("SELECT cliente_id FROM unidades WHERE id = ?", (payload.unidade_id,)).fetchone()
            cliente_id = unit["cliente_id"] if unit else None
        if cliente_id is None:
            raise HTTPException(status_code=400, detail="Unidade invalida para criar processo.")
        existing = _find_setup_record(
            connection,
            "operational_processes",
            cliente_id=cliente_id,
            unidade_id=payload.unidade_id,
            area_id=payload.area_id,
            nome=payload.nome,
            tipo=payload.tipo,
        )
        if existing:
            existing["created"] = False
            return existing
        process_id = criar_operational_process(
            connection,
            cliente_id=cliente_id,
            unidade_id=payload.unidade_id,
            area_id=payload.area_id,
            nome=payload.nome,
            tipo=payload.tipo,
        )
        created = _find_setup_record(connection, "operational_processes", id=process_id)
        if created is None:
            raise HTTPException(status_code=500, detail="Processo operacional nao foi persistido.")
        created["created"] = True
        return created


@api.post("/setup/assets", status_code=status.HTTP_201_CREATED)
def post_setup_asset(payload: SetupAssetIn, request: Request) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_role(user, ADMIN_ROLES)
        cliente_id = effective_cliente_id(user, payload.cliente_id)
        if cliente_id is None:
            unit = connection.execute("SELECT cliente_id FROM unidades WHERE id = ?", (payload.unidade_id,)).fetchone()
            cliente_id = unit["cliente_id"] if unit else None
        if cliente_id is None:
            raise HTTPException(status_code=400, detail="Unidade invalida para criar ativo.")
        existing = _find_setup_record(
            connection,
            "operational_assets",
            cliente_id=cliente_id,
            unidade_id=payload.unidade_id,
            area_id=payload.area_id,
            process_id=payload.process_id,
            nome=payload.nome,
            tipo=payload.tipo,
        )
        if existing:
            existing["created"] = False
            return existing
        asset_id = criar_operational_asset(
            connection,
            cliente_id=cliente_id,
            unidade_id=payload.unidade_id,
            area_id=payload.area_id,
            process_id=payload.process_id,
            nome=payload.nome,
            tipo=payload.tipo,
        )
        created = _find_setup_record(connection, "operational_assets", id=asset_id)
        if created is None:
            raise HTTPException(status_code=500, detail="Ativo operacional nao foi persistido.")
        created["created"] = True
        return created


@api.post("/setup/cameras/{camera_id}/context")
def post_setup_camera_context(camera_id: str, payload: SetupCameraContextIn, request: Request) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_role(user, ADMIN_ROLES)
        camera = obter_camera(connection, camera_id)
        if camera is None:
            raise HTTPException(status_code=404, detail="Camera nao encontrada.")
        if tenant_filter(user) and camera.get("cliente_id") != tenant_filter(user):
            raise HTTPException(status_code=403, detail="Camera de outro cliente.")
        context = apply_context_to_camera(
            connection,
            camera_id,
            area_context_id=payload.area_context_id,
            process_id=payload.process_id,
            asset_id=payload.asset_id,
        )
        monitors = listar_machine_monitors_camera(connection, camera_id)
        for monitor in monitors:
            atualizar_machine_monitor(
                connection,
                monitor["id"],
                area_context_id=payload.area_context_id,
                process_id=payload.process_id,
                asset_id=payload.asset_id,
            )
        return {"camera_id": camera_id, "context": context}


@api.get("/auth/users")
def get_users(request: Request) -> list[dict[str, Any]]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_role(user, ADMIN_ROLES)
        tenant = tenant_filter(user)
        if tenant:
            rows = connection.execute("SELECT id, cliente_id, nome, email, role, ativo, criado_em FROM users WHERE cliente_id = ? ORDER BY criado_em DESC", (tenant,)).fetchall()
        else:
            rows = connection.execute("SELECT id, cliente_id, nome, email, role, ativo, criado_em FROM users ORDER BY criado_em DESC").fetchall()
        return [dict(row) for row in rows]


@api.post("/dispositivos")
def post_dispositivo(payload: DispositivoIn, request: Request) -> dict[str, str]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_role(user, ADMIN_ROLES)
        cliente_id = resolve_unidade_cliente(connection, payload.unidade_id)
        require_same_tenant(user, cliente_id, "Unidade de outro cliente.")
        return {"id": criar_dispositivo(connection, payload.unidade_id, payload.nome, payload.status)}


@api.post("/cameras")
def post_camera(payload: CameraIn, request: Request) -> dict[str, str]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_role(user, ADMIN_ROLES)
        cliente_hint = payload.cliente_id if user["role"] == "admin_campex" else user.get("cliente_id")
        cliente_id, unidade_id = default_cliente_unidade(connection, cliente_hint, payload.unidade_id)
        return {"id": criar_camera(
            connection,
            unidade_id,
            payload.nome,
            payload.dispositivo_id,
            payload.config_ref,
            payload.status,
            cliente_id,
            payload.edge_id,
            payload.source_type,
            payload.secure_ref,
        )}


@api.post("/cameras/rtsp")
def post_camera_rtsp(payload: CameraRtspIn, request: Request) -> dict[str, object]:
    try:
        rtsp = build_rtsp_url(
            host=payload.host,
            port=payload.porta_rtsp,
            path=payload.caminho_rtsp,
            username=payload.usuario,
            password=payload.senha,
            full_url=payload.rtsp_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    test_result = None
    status = "nao_testada"
    if payload.testar_conexao:
        test_result = test_rtsp_connection(rtsp)
        status = "online" if test_result["compativel"] else "offline"
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_role(user, ADMIN_ROLES)
        cliente_hint = payload.cliente_id
        if user and user["role"] != "admin_campex":
            cliente_hint = user.get("cliente_id")
        cliente_id, unidade_id = default_cliente_unidade(connection, cliente_hint, payload.unidade_id)
        camera_id = criar_camera(
            connection,
            unidade_id,
            payload.nome,
            payload.dispositivo_id,
            rtsp.safe_url,
            status=status,
            cliente_id=cliente_id,
            edge_id=payload.edge_id,
            source_type="rtsp",
            secure_ref=rtsp.safe_url,
            rtsp_host=rtsp.host,
            rtsp_port=rtsp.port,
            rtsp_path=rtsp.path,
            rtsp_username=rtsp.username,
            rtsp_password=rtsp.password,
            canal=payload.canal,
            ativa=payload.ativa,
        )
        if test_result:
            atualizar_camera_video_info(
                connection,
                camera_id,
                resolucao=str(test_result.get("resolucao")) if test_result.get("resolucao") else None,
                fps=float(test_result["fps"]) if test_result.get("fps") is not None else None,
            )
        registrar_audit_log(
            connection,
            action="config.camera.create_rtsp",
            actor=user,
            entity_type="camera",
            entity_id=camera_id,
            tenant_id=cliente_id,
            metadata={"source_type": "rtsp", "connection_tested": bool(test_result)},
        )
        camera = obter_camera(connection, camera_id)
    return {"id": camera_id, "camera": camera, "teste": test_result}


@api.patch("/cameras/{camera_id}")
def patch_camera(camera_id: str, payload: CameraPatchIn, request: Request) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_role(user, ADMIN_ROLES)
        camera = obter_camera(connection, camera_id)
        if camera is None:
            raise HTTPException(status_code=404, detail="Camera nao encontrada.")
        if tenant_filter(user) and camera.get("cliente_id") != tenant_filter(user):
            raise HTTPException(status_code=403, detail="Camera de outro cliente.")
        updates = []
        values: list[Any] = []
        if payload.nome is not None:
            updates.append("nome = ?")
            values.append(payload.nome)
        if payload.ativa is not None:
            updates.append("ativa = ?")
            values.append(1 if payload.ativa else 0)
        if updates:
            values.append(camera_id)
            connection.execute(f"UPDATE cameras SET {', '.join(updates)} WHERE id = ?", tuple(values))
            registrar_audit_log(
                connection,
                action="config.camera.update",
                actor=user,
                entity_type="camera",
                entity_id=camera_id,
                tenant_id=camera.get("cliente_id"),
                metadata={"ativa": payload.ativa} if payload.ativa is not None else {},
            )
        updated_camera = obter_camera(connection, camera_id) or camera
        if "ativa" in updated_camera:
            updated_camera["ativa"] = bool(updated_camera["ativa"])
        return updated_camera


@api.post("/cameras/test-connection")
def post_camera_test_connection(payload: CameraRtspTestIn, request: Request) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        require_user(request, connection)
    try:
        rtsp = build_rtsp_url(
            host=payload.host,
            port=payload.porta_rtsp,
            path=payload.caminho_rtsp,
            username=payload.usuario,
            password=payload.senha,
            full_url=payload.rtsp_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return test_rtsp_connection(rtsp, timeout_seconds=payload.timeout_seconds)


@api.post("/live-view/start")
def post_live_view_start(payload: LiveViewStartIn, request: Request) -> dict[str, object]:
    camera_id = payload.camera_id
    camera_name = payload.nome
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        user_tenant = tenant_filter(user)
    if camera_id and not payload.rtsp_url and not payload.host:
        with connect() as connection:
            init_db(connection)
            require_camera_access(connection, user, camera_id)
            camera = obter_camera(connection, camera_id, include_secret=True)
        if camera is None:
            raise HTTPException(status_code=404, detail="Câmera não encontrada.")
        camera_name = str(camera.get("nome") or payload.nome)
        try:
            rtsp = build_rtsp_url(
                host=camera.get("rtsp_host"),
                port=int(camera.get("rtsp_port") or 554),
                path=camera.get("rtsp_path"),
                username=camera.get("rtsp_username"),
                password=camera.get("rtsp_password"),
                full_url=None,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    else:
        try:
            rtsp = build_rtsp_url(
                host=payload.host,
                port=payload.porta_rtsp,
                path=payload.caminho_rtsp,
                username=payload.usuario,
                password=payload.senha,
                full_url=payload.rtsp_url,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    session_id = "live_" + hashlib.sha256(f"{camera_id or camera_name}|{rtsp.safe_url}".encode()).hexdigest()[:16]
    live_view_sessions[session_id] = {
        "nome": camera_name,
        "source": rtsp.url,
        "safe_url": rtsp.safe_url,
        "camera_id": camera_id,
        "cliente_id": camera.get("cliente_id") if camera_id and "camera" in locals() else user_tenant,
        "user_id": user.get("id"),
        "stream_id": camera_id or session_id,
        "created_at": time.time(),
    }
    stream_id = str(camera_id or session_id)
    stream = live_streams.get_or_create(stream_id, rtsp.url)
    stream.start()
    status = stream.public_status()
    return {
        "session_id": session_id,
        "stream_id": stream_id,
        "nome": camera_name,
        "status": status,
    }


def live_view_stream_id(session_id: str) -> str:
    session = live_view_sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Live View não encontrada.")
    return str(session.get("stream_id") or session.get("camera_id") or session_id)


@api.get("/live-view/{session_id}/status")
def get_live_view_status(session_id: str, request: Request) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        session = require_live_view_session_access(connection, request, session_id)
    stream = live_streams.get(live_view_stream_id(session_id))
    status = stream.public_status() if stream else {"status": "offline", "width": None, "height": None, "fps": None}
    ops = live_view_official_ops(session, stream)
    context = None
    if session.get("camera_id"):
        with connect() as connection:
            init_db(connection)
            camera = obter_camera(connection, str(session["camera_id"]))
            if camera:
                context = _live_context(connection, camera, status)
    return {"session_id": session_id, "nome": session["nome"], **status, "ops": ops, "context": context}


@api.get("/live-view/{session_id}/stream")
def get_live_view_stream(session_id: str, request: Request) -> StreamingResponse:
    with connect() as connection:
        init_db(connection)
        session = require_live_view_session_access(connection, request, session_id)
    stream = live_streams.get_or_create(live_view_stream_id(session_id), str(session["source"]))
    stream.start()
    return StreamingResponse(stream.frames(), media_type="multipart/x-mixed-replace; boundary=frame")


def live_view_stream_for(session_id: str):
    session = live_view_sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Live View não encontrada.")
    stream = live_streams.get_or_create(live_view_stream_id(session_id), str(session["source"]))
    return session, stream


def live_view_official_ops(session: dict[str, object] | None, stream) -> dict[str, object]:
    camera_id = session.get("camera_id") if session else None
    monitor = None
    if camera_id:
        with connect() as connection:
            init_db(connection)
            monitors = listar_machine_monitors_camera(connection, str(camera_id))
            monitor = monitors[0] if monitors else None
    status = stream.public_status() if stream else {}
    observation = status.get("observation") or {}
    machine_state = status.get("machine_state")
    if machine_state == "ACTIVE":
        compat_state = "ATIVA"
    elif machine_state == "STOPPED":
        compat_state = "PARADA"
    elif machine_state == "UNKNOWN":
        compat_state = "UNKNOWN"
    else:
        compat_state = "NAO_CONFIGURADA"
    return {
        "ai_enabled": (status.get("ai_status") or "") in {"ativa", "carregando"},
        "ai_status": status.get("ai_status", "inativa"),
        "people_count": status.get("people_count", 0),
        "machine_state": compat_state,
        "machine_motion": status.get("machine_motion"),
        "machine_threshold": status.get("machine_threshold"),
        "machine_reason": status.get("machine_reason"),
        "machine_seconds_in_state": status.get("machine_seconds_in_state"),
        "analysis_status": status.get("machine_analysis_status"),
        "analysis_error": status.get("machine_analysis_error"),
        "inference_frames": status.get("analysis_frames"),
        "raw_activity_score": status.get("machine_raw_activity_score"),
        "smoothed_activity_score": status.get("machine_motion"),
        "frames_analyzed": status.get("machine_frames_analyzed"),
        "roi": {
            "width": status.get("machine_roi_width"),
            "height": status.get("machine_roi_height"),
        },
        "operator_present": status.get("machine_operator_present"),
        "operator_people_count": 1 if status.get("machine_operator_present") else 0,
        "zones": status.get("zones") or [],
        "active_zone_events": status.get("active_zone_events") or [],
        "visual_confidence": status.get("machine_confidence") or observation.get("machine_confidence") or 0,
        "calibration_status": (status.get("calibration") or {}).get("calibration_result") or (monitor or {}).get("calibration_result") or "não calibrada",
        "baselines": {
            "active": (status.get("calibration") or {}).get("active_baseline") or (monitor or {}).get("active_baseline"),
            "stopped": (status.get("calibration") or {}).get("stopped_baseline") or (monitor or {}).get("stopped_baseline"),
        },
        "separation_score": (status.get("calibration") or {}).get("separation_score") or (monitor or {}).get("separation_score"),
        "machine": {
            "id": monitor.get("id"),
            "nome": monitor.get("nome"),
            "machine_polygon": monitor.get("machine_polygon"),
            "operator_polygon": monitor.get("operator_polygon"),
            "threshold": monitor.get("motion_threshold"),
            "calibrated": monitor.get("calibration_result") == "READY",
        } if monitor else None,
        "event_id": status.get("machine_event_id"),
        "observation": observation,
    }


OFFICIAL_LIVE_FAMILIES = {"interruption", "wait", "flow", "absence"}


def _lookup_name(connection, table: str, item_id: object | None) -> str | None:
    if not item_id:
        return None
    if table not in {"unidades", "operational_areas", "operational_processes", "operational_assets"}:
        return None
    row = connection.execute(f"SELECT nome FROM {table} WHERE id = ?", (str(item_id),)).fetchone()
    return str(row["nome"]) if row and row["nome"] else None


def _public_live_event(event: dict[str, Any] | None) -> dict[str, Any] | None:
    if not event:
        return None
    started_at = event.get("inicio")
    duration = event.get("duracao")
    if event.get("status") == "open" and started_at:
        try:
            duration = max(0, round((datetime.now(timezone.utc) - read_model_parse_datetime(str(started_at))).total_seconds()))
        except Exception:
            duration = event.get("duracao")
    return {
        "id": event.get("id"),
        "event_uuid": event.get("event_uuid"),
        "tipo": event.get("tipo"),
        "event_family": event.get("event_family"),
        "event_subtype": event.get("event_subtype"),
        "status": event.get("status"),
        "workflow_status": event.get("workflow_status") or "new",
        "started_at": started_at,
        "ended_at": event.get("fim"),
        "duration_seconds": duration,
        "severity": event.get("severidade"),
        "evidence_available": bool(event.get("midia_path")),
    }


def _live_context(connection, camera: dict[str, Any], status_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    camera_id = str(camera.get("id"))
    monitor = None
    monitors = listar_machine_monitors_camera(connection, camera_id)
    if monitors:
        monitor = monitors[0]
    context = resolve_context(connection, camera_id=camera_id, machine_monitor_id=monitor.get("id") if monitor else None)
    area_name = _lookup_name(connection, "operational_areas", context.get("area_context_id"))
    process_name = _lookup_name(connection, "operational_processes", context.get("process_id"))
    asset_name = _lookup_name(connection, "operational_assets", context.get("asset_id"))
    site_name = _lookup_name(connection, "unidades", context.get("site_id") or context.get("unidade_id"))
    if not asset_name and monitor:
        asset_name = str(monitor.get("nome") or "")
    primary = asset_name or process_name or area_name or str(camera.get("nome") or camera_id)
    path = " → ".join([part for part in [area_name, process_name] if part]) or site_name or "Contexto não informado"
    events = [
        event
        for event in listar_eventos_filtrados(connection, camera_id=camera_id, status="open")
        if (event.get("event_family") or "unknown") in OFFICIAL_LIVE_FAMILIES and event.get("tipo") != "camera_status"
    ]
    current_event = events[0] if events else None
    status_payload = status_payload or {}
    ops_state = status_payload.get("machine_state") or status_payload.get("observation", {}).get("machine_state")
    if current_event:
        operational_status = "evento_aberto"
    elif status_payload.get("status") != "online":
        operational_status = "sem_frame_recente" if camera.get("ultimo_frame") else "offline"
    elif status_payload.get("ai_status") in {"indisponivel", "erro"}:
        operational_status = "inferencia_indisponivel"
    elif ops_state in {"STOPPED", "PARADA"}:
        operational_status = "parada"
    elif ops_state in {"ACTIVE", "ATIVA"}:
        operational_status = "ativa"
    elif status_payload.get("status") == "online":
        operational_status = "sem_evento"
    else:
        operational_status = "cobertura_parcial"
    return {
        "site_id": context.get("site_id") or context.get("unidade_id"),
        "site_name": site_name,
        "area_id": context.get("area_context_id"),
        "area_name": area_name,
        "process_id": context.get("process_id"),
        "process_name": process_name,
        "asset_id": context.get("asset_id"),
        "asset_name": asset_name,
        "camera_id": camera_id,
        "camera_name": camera.get("nome"),
        "primary_label": primary,
        "path_label": path,
        "machine_monitor_id": monitor.get("id") if monitor else context.get("machine_monitor_id"),
        "operational_status": operational_status,
        "current_event": _public_live_event(current_event),
    }


def _live_status_for_camera(connection, camera: dict[str, Any]) -> dict[str, Any]:
    camera_id = str(camera.get("id"))
    stream = live_streams.get(camera_id)
    if stream is None:
        status_payload = {
            "camera_id": camera_id,
            "status": "offline",
            "width": None,
            "height": None,
            "fps": None,
            "last_frame_at": camera.get("ultimo_frame"),
            "error": None,
            "viewers": 0,
            "reconnect_attempts": camera.get("reconexoes") or 0,
        }
    else:
        status_payload = stream.public_status()
    return {**status_payload, "context": _live_context(connection, camera, status_payload)}


def _camera_with_runtime_status(camera: dict[str, Any], stream: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(camera)
    runtime_online = bool(stream and stream.get("status") == "online" and _recent_iso(stream.get("last_frame_at")))
    inference_active = bool(
        stream
        and _recent_iso(stream.get("last_analysis_at"))
        and (
            stream.get("ai_status") == "ativa"
            or float(stream.get("analysis_fps") or 0) > 0
            or int(stream.get("analysis_frames") or stream.get("machine_frames_analyzed") or 0) > 0
        )
    )
    if stream:
        payload["runtime"] = {
            "camera_online": runtime_online,
            "stream_running": stream.get("status") == "online",
            "last_frame_at": stream.get("last_frame_at"),
            "inference_active": inference_active,
            "inference_fps": stream.get("analysis_fps"),
            "last_inference_at": stream.get("last_analysis_at"),
            "frames_analyzed": stream.get("analysis_frames") or stream.get("machine_frames_analyzed") or 0,
            "status": "online" if runtime_online else str(stream.get("status") or "offline"),
        }
        payload["effective_status"] = "online" if runtime_online else str(stream.get("status") or "offline")
        payload["ultimo_frame"] = stream.get("last_frame_at") or payload.get("ultimo_frame")
        payload["analysis_enabled"] = inference_active
    else:
        payload["runtime"] = {
            "camera_online": False,
            "stream_running": False,
            "last_frame_at": None,
            "inference_active": False,
            "inference_fps": 0,
            "last_inference_at": None,
            "frames_analyzed": 0,
            "status": "offline",
        }
        payload["effective_status"] = "offline"
        payload["analysis_enabled"] = False
    return payload


def expanded_live_view_polygon(points: list[dict[str, float]], margin: float = 0.08) -> list[dict[str, float]]:
    normalized = normalize_points(points)
    xs = [float(point["x"]) for point in normalized]
    ys = [float(point["y"]) for point in normalized]
    return [
        {"x": max(0.0, min(xs) - margin), "y": max(0.0, min(ys) - margin)},
        {"x": min(1.0, max(xs) + margin), "y": max(0.0, min(ys) - margin)},
        {"x": min(1.0, max(xs) + margin), "y": min(1.0, max(ys) + margin)},
        {"x": max(0.0, min(xs) - margin), "y": min(1.0, max(ys) + margin)},
    ]


def persist_live_view_machine_config(session_id: str, machine: dict[str, object], nome: str | None = None) -> dict[str, object] | None:
    session = live_view_sessions.get(session_id)
    camera_id = session.get("camera_id") if session else None
    if not camera_id:
        return None
    with connect() as connection:
        init_db(connection)
        camera = obter_camera(connection, str(camera_id))
        if camera is None:
            return None
        monitors = listar_machine_monitors_camera(connection, str(camera_id))
        if monitors:
            return atualizar_machine_monitor(
                connection,
                monitors[0]["id"],
                nome=nome or machine["nome"],
                machine_polygon=machine["machine_polygon"],
                operator_polygon=machine["operator_polygon"],
                motion_threshold=machine.get("threshold"),
            )
        monitor_id = criar_machine_monitor(
            connection,
            str(camera.get("cliente_id") or ""),
            str(camera.get("unidade_id")),
            str(camera_id),
            nome or machine["nome"],
            machine["machine_polygon"],
            machine["operator_polygon"],
            True,
        )
        return obter_machine_monitor(connection, monitor_id)


@api.post("/live-view/{session_id}/ai/start")
def post_live_view_ai_start(session_id: str, request: Request) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        require_live_view_session_access(connection, request, session_id)
    session, stream = live_view_stream_for(session_id)
    stream.set_analysis(True)
    return {"ai_enabled": True, **live_view_official_ops(session, stream)}


@api.post("/live-view/{session_id}/ai/stop")
def post_live_view_ai_stop(session_id: str, request: Request) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        require_live_view_session_access(connection, request, session_id)
    session, stream = live_view_stream_for(session_id)
    stream.set_analysis(False)
    return {"ai_enabled": False, **live_view_official_ops(session, stream)}


@api.post("/live-view/{session_id}/machine")
def post_live_view_machine(session_id: str, payload: LiveViewMachineIn, request: Request) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        require_live_view_session_access(connection, request, session_id)
    session, stream = live_view_stream_for(session_id)
    machine_polygon = normalize_points([point.model_dump() for point in payload.machine_polygon])
    operator_polygon = normalize_points([point.model_dump() for point in payload.operator_polygon]) if payload.operator_polygon else expanded_live_view_polygon(machine_polygon)
    machine = {
        "nome": payload.nome,
        "machine_polygon": machine_polygon,
        "operator_polygon": operator_polygon,
        "threshold": None,
    }
    monitor = persist_live_view_machine_config(session_id, machine, payload.nome)
    stream._machine_engines.pop(monitor["id"], None) if monitor else None
    state = live_view_official_ops(session, stream)
    state["machine"] = {
        "id": monitor.get("id") if monitor else None,
        "nome": payload.nome,
        "machine_polygon": machine_polygon,
        "operator_polygon": operator_polygon,
        "threshold": monitor.get("motion_threshold") if monitor else None,
        "calibrated": False,
    }
    state["machine_state"] = "UNKNOWN" if monitor else "NAO_CONFIGURADA"
    return state


@api.post("/live-view/{session_id}/operator-zone")
def post_live_view_operator_zone(session_id: str, payload: LiveViewOperatorZoneIn, request: Request) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        require_live_view_session_access(connection, request, session_id)
    session, stream = live_view_stream_for(session_id)
    camera_id = session.get("camera_id") if session else None
    if not camera_id:
        raise HTTPException(status_code=400, detail="Zona do operador exige câmera persistente.")
    operator_polygon = normalize_points([point.model_dump() for point in payload.operator_polygon])
    with connect() as connection:
        init_db(connection)
        monitors = listar_machine_monitors_camera(connection, str(camera_id))
        if not monitors:
            raise HTTPException(status_code=400, detail="Configure a máquina antes da zona do operador.")
        monitor = atualizar_machine_monitor(connection, monitors[0]["id"], operator_polygon=operator_polygon)
    stream._machine_engines.pop(monitor["id"], None) if monitor else None
    return live_view_official_ops(session, stream)


@api.post("/live-view/{session_id}/machine/calibrate-active")
def post_live_view_machine_calibrate_active(session_id: str, request: Request) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        require_live_view_session_access(connection, request, session_id)
    session, stream = live_view_stream_for(session_id)
    state = live_view_official_ops(session, stream)
    state["calibration_status"] = "use_assisted_calibration_endpoint"
    state["message"] = "Use POST /machine-monitors/{id}/calibration/active/start para calibração assistida real."
    return state


@api.delete("/live-view/{session_id}/machine")
def delete_live_view_machine(session_id: str, request: Request) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        session = require_live_view_session_access(connection, request, session_id)
    camera_id = session.get("camera_id") if session else None
    if camera_id:
        with connect() as connection:
            init_db(connection)
            for monitor in listar_machine_monitors_camera(connection, str(camera_id)):
                excluir_machine_monitor(connection, monitor["id"])
    stream = live_streams.get(live_view_stream_id(session_id))
    if stream:
        stream._machine_engines.clear()
    return {"machine": None, "machine_state": "NAO_CONFIGURADA", "calibration_status": "não calibrada"}


@api.post("/live-view/{session_id}/stop")
def post_live_view_stop(session_id: str, request: Request) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        require_live_view_session_access(connection, request, session_id)
    session = live_view_sessions.pop(session_id, None)
    stream_id = str(session.get("stream_id") or session_id) if session else session_id
    stopped = False if session and session.get("camera_id") else live_streams.stop(stream_id)
    return {"session_id": session_id, "status": "offline", "stopped": stopped}


@api.post("/cameras/{camera_id}/test-connection")
def post_existing_camera_test_connection(camera_id: str, request: Request) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        require_camera_access(connection, require_user(request, connection), camera_id)
        camera = obter_camera(connection, camera_id, include_secret=True)
    if camera is None:
        return {"compativel": False, "motivo_erro": "Camera nao encontrada."}
    source = camera.get("config_ref")
    if not source:
        return {"compativel": False, "motivo_erro": "Camera sem fonte configurada."}
    rtsp = build_rtsp_url(full_url=str(source))
    return test_rtsp_connection(rtsp)


@api.post("/cameras/{camera_id}/password")
def post_camera_password(camera_id: str, payload: CameraPasswordIn, request: Request) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_role(user, ADMIN_ROLES)
        camera = obter_camera(connection, camera_id)
        if camera is None:
            raise HTTPException(status_code=404, detail="Camera nao encontrada.")
        if tenant_filter(user) and camera.get("cliente_id") != tenant_filter(user):
            raise HTTPException(status_code=403, detail="Camera de outro cliente.")
        return {"updated": alterar_senha_camera(connection, camera_id, payload.senha)}


def load_camera_source(camera_id: str) -> tuple[dict[str, Any], str]:
    with connect() as connection:
        init_db(connection)
        camera = obter_camera(connection, camera_id, include_secret=True)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera nao encontrada.")
    if os.getenv("CAMPEX_VIDEO_SOURCE_MODE", "").strip().lower() == "file":
        video_file = os.getenv("CAMPEX_VIDEO_FILE", "").strip()
        if not video_file:
            raise HTTPException(status_code=400, detail="CAMPEX_VIDEO_SOURCE_MODE=file exige CAMPEX_VIDEO_FILE.")
        if not Path(video_file).exists():
            raise HTTPException(status_code=400, detail="Arquivo de video de teste nao encontrado.")
        return camera, video_file
    source = camera.get("config_ref")
    if camera.get("rtsp_host"):
        source = build_rtsp_url(
            host=str(camera.get("rtsp_host")),
            port=int(camera.get("rtsp_port") or 554),
            path=camera.get("rtsp_path"),
            username=camera.get("rtsp_username"),
            password=camera.get("rtsp_password"),
        ).url
    if not source:
        raise HTTPException(status_code=400, detail="Camera sem fonte configurada.")
    return camera, str(source)


def start_camera_runtime(camera_id: str, enable_analysis: bool = True) -> dict[str, object]:
    _camera, source = load_camera_source(camera_id)
    stream = live_streams.get_or_create(camera_id, source)
    stream.start()
    if enable_analysis:
        stream.set_analysis(True)
    return stream.public_status()


def bootstrap_production_streams() -> dict[str, object]:
    started: list[dict[str, object]] = []
    failed: list[dict[str, object]] = []
    with connect() as connection:
        init_db(connection)
        rows = connection.execute(
            """
            SELECT id, nome
            FROM cameras
            WHERE ativa = 1
              AND (
                config_ref IS NOT NULL
                OR rtsp_host IS NOT NULL
                OR secure_ref IS NOT NULL
              )
            ORDER BY nome
            """
        ).fetchall()
        inactive_rows = connection.execute("SELECT id, nome FROM cameras WHERE ativa = 0").fetchall()
    for row in inactive_rows:
        camera_id = str(row["id"])
        current_stream = live_streams.get(camera_id) if hasattr(live_streams, "get") else None
        if current_stream:
            live_streams.stop(camera_id)
            logger.info("Bootstrap Edge: câmera desativada parada (%s).", camera_id)
    for row in rows:
        camera_id = str(row["id"])
        try:
            status_payload = start_camera_runtime(camera_id, enable_analysis=True)
            started.append({"camera_id": camera_id, "nome": row["nome"], "status": status_payload.get("status")})
            logger.info("Bootstrap Edge: câmera %s iniciada (%s).", row["nome"], camera_id)
        except Exception as exc:
            failed.append({"camera_id": camera_id, "nome": row["nome"], "error": str(exc)})
            logger.error("Bootstrap Edge: falha ao iniciar câmera %s (%s): %s", row["nome"], camera_id, exc)
    return {"started": started, "failed": failed}


@api.post("/cameras/{camera_id}/start")
def post_camera_start(camera_id: str, request: Request) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        require_camera_access(connection, require_user(request, connection), camera_id)
    return start_camera_runtime(camera_id, enable_analysis=False)


@api.post("/cameras/{camera_id}/stop")
def post_camera_stop(camera_id: str, request: Request) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        require_camera_access(connection, require_user(request, connection), camera_id)
    stopped = live_streams.stop(camera_id)
    return {"camera_id": camera_id, "status": "offline", "stopped": stopped}


@api.get("/cameras/{camera_id}/stream")
def get_camera_stream(camera_id: str, request: Request) -> StreamingResponse:
    with connect() as connection:
        init_db(connection)
        require_camera_access(connection, require_user(request, connection), camera_id)
    _camera, source = load_camera_source(camera_id)
    stream = live_streams.get_or_create(camera_id, source)
    stream.start()
    return StreamingResponse(
        stream.frames(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@api.get("/cameras/{camera_id}/status")
def get_camera_live_status(camera_id: str, request: Request) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_camera_access(connection, user, camera_id)
        camera = obter_camera(connection, camera_id)
        if camera is None:
            raise HTTPException(status_code=404, detail="Camera nao encontrada.")
        return _live_status_for_camera(connection, camera)


@api.get("/live/overview")
def get_live_overview(request: Request) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        cameras = listar(connection, "cameras")
        if user and tenant_filter(user):
            cameras = [camera for camera in cameras if camera.get("cliente_id") == tenant_filter(user)]
        items = [{"camera": camera, "status": _live_status_for_camera(connection, camera)} for camera in cameras]
    streams = live_streams.statuses()
    return {
        "cameras": items,
        "resources": {
            "active_streams": len(streams),
            "cpu_percent": psutil.cpu_percent(interval=None),
            "memory_percent": psutil.virtual_memory().percent,
        },
    }


@api.get("/live-streams/status")
def get_live_streams_status(request: Request) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        require_user(request, connection)
    streams = live_streams.statuses()
    return {
        "active_streams": len(streams),
        "streams": streams,
        "cpu_percent": psutil.cpu_percent(interval=None),
        "memory_percent": psutil.virtual_memory().percent,
    }


@api.get("/people-zones/summary")
def get_people_zones_summary(request: Request, camera_id: Optional[str] = None) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        cameras = listar(connection, "cameras")
        if tenant_filter(user):
            cameras = [camera for camera in cameras if camera.get("cliente_id") == tenant_filter(user)]
        if camera_id:
            require_camera_access(connection, user, camera_id)
            cameras = [camera for camera in cameras if camera["id"] == camera_id]
        camera_ids = {camera["id"] for camera in cameras}
        zones = []
        events = []
        for current_camera_id in camera_ids:
            zones.extend(listar_areas_camera(connection, current_camera_id))
            events.extend(listar_eventos_filtrados(connection, camera_id=current_camera_id))
    live = {status["camera_id"]: status for status in live_streams.statuses()}
    workstation_zones = [zone for zone in zones if zone.get("tipo") == "workstation"]
    zone_states = []
    for zone in zones:
        status = live.get(zone["camera_id"], {})
        current = next((item for item in status.get("zones", []) if item.get("area_id") == zone["id"]), {})
        zone_events = [event for event in events if event.get("area_id") == zone["id"]]
        unattended = [event for event in zone_events if event.get("tipo") == "workstation_unattended"]
        unattended_seconds = sum(float(event.get("duracao") or 0) for event in unattended if event.get("duracao") is not None)
        active_unattended = next((event for event in unattended if event.get("status") == "open"), None)
        zone_states.append({
            "id": zone["id"],
            "camera_id": zone["camera_id"],
            "nome": zone["nome"],
            "tipo": zone["tipo"],
            "ativa": zone["ativa"],
            "ocupacao_atual": current.get("pessoas_dentro", 0),
            "estado": current.get("estado", "sem_dados"),
            "evento_ativo": current.get("event_active", False),
            "evento_id": current.get("event_id"),
            "colaborador_turno": zone.get("collaborator_name"),
            "tolerancia_ausencia": zone.get("absence_tolerance_seconds"),
            "ausencias": len(unattended),
            "tempo_total_desocupado": unattended_seconds,
            "inicio_desocupacao": active_unattended.get("inicio") if active_unattended else None,
        })
    people_visible = sum(int(status.get("people_count") or 0) for status in live.values())
    return {
        "catalog": [
            "restricted_zone_occupied",
            "workstation_unattended",
            "minimum_staff_not_met",
            "shift_start_incomplete",
            "excessive_zone_dwell",
            "after_hours_presence",
        ],
        "cameras": cameras,
        "zones": zone_states,
        "workstations": [zone for zone in zone_states if zone["tipo"] == "workstation"],
        "expected_staff": len([zone for zone in workstation_zones if zone.get("ativa")]),
        "identified_people": people_visible,
        "active_events": [event for event in events if event.get("status") == "open"],
        "events": events[:100],
    }


@api.get("/local-diagnostics")
def get_local_diagnostics(request: Request) -> dict[str, object]:
    disk = psutil.disk_usage(str(ROOT))
    with connect() as connection:
        init_db(connection)
        require_user(request, connection)
        zones = connection.execute("SELECT COUNT(*) AS total FROM monitored_areas WHERE ativa = 1").fetchone()["total"]
        rules = connection.execute("SELECT COUNT(*) AS total FROM regras WHERE ativo = 1").fetchone()["total"]
        open_events = connection.execute("SELECT COUNT(*) AS total FROM eventos WHERE status = 'open'").fetchone()["total"]
        outbox = connection.execute("SELECT COUNT(*) AS total FROM sync_outbox WHERE status IN ('pending', 'failed')").fetchone()["total"]
        last_delivery = connection.execute("SELECT status, last_attempt_at, sent_at, erro FROM alert_deliveries ORDER BY criado_em DESC LIMIT 1").fetchone()
    streams = live_streams.statuses()
    online_streams = [stream for stream in streams if stream.get("status") == "online" and _recent_iso(stream.get("last_frame_at"))]
    inference_streams = [
        stream for stream in streams
        if _recent_iso(stream.get("last_analysis_at"))
        and (
            stream.get("ai_status") == "ativa"
            or float(stream.get("analysis_fps") or 0) > 0
            or int(stream.get("analysis_frames") or stream.get("machine_frames_analyzed") or 0) > 0
        )
    ]
    return {
        "sqlite": "ok",
        "cameras_online": len(online_streams),
        "ultimo_frame": max([str(stream.get("last_frame_at") or "") for stream in online_streams], default=None),
        "ia_ativa": len(inference_streams),
        "zonas_ativas": zones,
        "regras_ativas": rules,
        "eventos_abertos": open_events,
        "outbox_pendente": outbox,
        "email_mode": email_configuration_status(),
        "ultima_entrega": dict(last_delivery) if last_delivery else None,
        "disco_livre_percentual": round(100 - disk.percent, 2),
    }


def test_events_enabled() -> bool:
    return os.getenv("CAMPEX_ENABLE_TEST_EVENT", "").lower() in {"1", "true", "sim", "yes"} and os.getenv("CAMPEX_ENV", "development").lower() != "production"


def create_test_evidence(camera_id: str, area_id: str, event_type: str) -> str:
    import cv2
    import numpy as np

    folder = EVIDENCE_DIR / "test" / camera_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{int(time.time() * 1000)}_{event_type}_{area_id}.jpg"
    image = np.zeros((360, 640, 3), dtype=np.uint8)
    cv2.putText(image, "Campex - evidencia de teste", (24, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(image, event_type, (24, 105), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (80, 170, 255), 2, cv2.LINE_AA)
    if not cv2.imwrite(str(path), image):
        raise HTTPException(status_code=500, detail="Nao foi possivel salvar evidencia de teste.")
    return storage_path(path)


@api.post("/dev/test-event")
def post_dev_test_event(payload: DevTestEventIn, request: Request) -> dict[str, object]:
    if not test_events_enabled():
        raise HTTPException(status_code=404, detail="Ocorrencia de teste indisponivel neste ambiente.")
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        camera = obter_camera(connection, payload.camera_id) if payload.camera_id else None
        if camera is None:
            cameras = listar(connection, "cameras")
            camera = cameras[0] if cameras else None
        if camera is None:
            raise HTTPException(status_code=400, detail="Cadastre uma camera antes de gerar ocorrencia de teste.")
        require_camera_access(connection, user, camera["id"])
        areas = listar_areas_camera(connection, camera["id"])
        area = next((item for item in areas if item["id"] == payload.area_id), None) if payload.area_id else (areas[0] if areas else None)
        if area is None:
            raise HTTPException(status_code=400, detail="Cadastre uma zona antes de gerar ocorrencia de teste.")
        rules = listar_regras(connection, camera_id=camera["id"])
        rule = next((item for item in rules if item.get("regiao_id") == area["id"] and item.get("tipo_evento") == payload.event_type), None)
        evidence_path = create_test_evidence(camera["id"], area["id"], payload.event_type)
        event_id = criar_ocorrencia_zona(
            connection,
            cliente_id=str(area.get("cliente_id") or camera.get("cliente_id") or ""),
            unidade_id=str(area.get("unidade_id") or camera.get("unidade_id") or ""),
            camera_id=camera["id"],
            area_id=area["id"],
            regra_id=rule["id"] if rule else None,
            tipo=payload.event_type,
            inicio=now_iso(),
            quantidade_inicial=0,
            quantidade_maxima=0,
            track_ids=[],
            confianca=1.0,
            midia_path=evidence_path,
            severidade=str(rule.get("severidade") if rule else "high"),
            metadata={"is_test": True, "source": "dev_test_event", "zone_name": area["nome"], "zone_type": area["tipo"]},
        )
    enqueue_event_alert(event_id)
    return {"event_id": event_id, "status": "created", "is_test": True, "evidence_path": evidence_path}


@api.post("/cameras/{camera_id}/analysis/start")
def post_camera_analysis_start(camera_id: str, request: Request) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        require_camera_access(connection, require_user(request, connection), camera_id)
    start_camera_runtime(camera_id, enable_analysis=True)
    stream = live_streams.get(camera_id)
    return stream.public_status() if stream else {"camera_id": camera_id, "status": "offline"}


@api.post("/cameras/{camera_id}/analysis/stop")
def post_camera_analysis_stop(camera_id: str, request: Request) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        require_camera_access(connection, require_user(request, connection), camera_id)
    stream = live_streams.get(camera_id)
    if stream is None:
        return {
            "camera_id": camera_id,
            "status": "offline",
            "ai_status": "inativa",
            "people_count": 0,
        }
    return stream.set_analysis(False)


@api.get("/cameras/{camera_id}/areas")
def get_camera_areas(camera_id: str, request: Request) -> list[dict[str, Any]]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        camera = obter_camera(connection, camera_id)
        if camera is None:
            raise HTTPException(status_code=404, detail="Camera nao encontrada.")
        if tenant_filter(user) and camera.get("cliente_id") != tenant_filter(user):
            raise HTTPException(status_code=403, detail="Camera de outro cliente.")
        return listar_areas_camera(connection, camera_id)


@api.post("/cameras/{camera_id}/areas", status_code=status.HTTP_201_CREATED)
def post_camera_area(camera_id: str, payload: AreaIn, request: Request) -> dict[str, Any]:
    try:
        zone_name = payload.resolved_name()
        zone_type = payload.resolved_type()
        zone_active = payload.resolved_active()
        points = normalize_points([point.model_dump() for point in payload.resolved_points()])
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    allowed_types = {"workstation", "restricted_area", "dwell_area", "machine_region", "operator_zone", "restricted_zone", "work_area"}
    if zone_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Tipo de zona invalido para People & Zones V1.")
    try:
        with connect() as connection:
            init_db(connection)
            user = require_user(request, connection)
            require_camera_access(connection, user, camera_id)
            camera = obter_camera(connection, camera_id)
            if camera is None:
                raise HTTPException(status_code=404, detail="Camera nao encontrada.")
            area_id = criar_area_monitorada(
                connection,
                camera_id,
                zone_name,
                points,
                zone_type,
                zone_active,
                metadata=payload.metadata,
                collaborator_name=payload.collaborator_name,
                expected_start=payload.expected_start,
                expected_end=payload.expected_end,
                absence_tolerance_seconds=payload.absence_tolerance_seconds,
                dwell_limit_seconds=payload.dwell_limit_seconds,
                expected_min_people=payload.expected_min_people,
                machine_id=payload.machine_id,
            )
            event_by_type = {
                "restricted_area": "restricted_zone_occupied",
                "restricted_zone": "restricted_zone_occupied",
                "workstation": "workstation_unattended",
                "operator_zone": "workstation_unattended",
                "work_area": "workstation_unattended",
                "dwell_area": "excessive_zone_dwell",
            }
            event_type = event_by_type.get(zone_type)
            if event_type:
                minimum_seconds = (
                    payload.absence_tolerance_seconds
                    if zone_type in {"workstation", "operator_zone", "work_area"}
                    else payload.dwell_limit_seconds
                    if zone_type == "dwell_area"
                    else (payload.metadata or {}).get("minimum_seconds", 5)
                )
                criar_regra(
                    connection,
                    camera_id,
                    event_type,
                    tempo_minimo=float(minimum_seconds or 0),
                    ativo=zone_active,
                    nome=f"{zone_name} · {event_type}",
                    cliente_id=str(camera.get("cliente_id") or ""),
                    unidade_id=str(camera.get("unidade_id") or ""),
                    entidade="person",
                    regiao_id=area_id,
                    condicao={"type": "absence_in_zone" if event_type == "workstation_unattended" else "presence_in_zone", "zone_id": area_id},
                    severidade=(payload.metadata or {}).get("severidade", "high" if event_type == "restricted_zone_occupied" else "medium"),
                    cooldown_seconds=float((payload.metadata or {}).get("cooldown_seconds", 60)),
                    alerta_inicio=True,
                    alerta_normalizacao=True,
                )
            areas = listar_areas_camera(connection, camera_id)
        return next(area for area in areas if area["id"] == area_id)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Falha ao persistir zona para camera %s", camera_id)
        raise HTTPException(status_code=500, detail="Nao foi possivel salvar a zona. A configuracao nao foi alterada.") from exc


@api.patch("/areas/{area_id}")
def patch_area(area_id: str, payload: AreaPatchIn, request: Request) -> dict[str, Any]:
    points = None
    if payload.pontos is not None:
        try:
            points = normalize_points([point.model_dump() for point in payload.pontos])
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    with connect() as connection:
        init_db(connection)
        require_area_access(connection, require_user(request, connection), area_id)
        area = atualizar_area_monitorada(
            connection,
            area_id,
            payload.nome,
            points,
            tipo=payload.tipo,
            ativa=payload.ativa,
            metadata=payload.metadata,
            collaborator_name=payload.collaborator_name,
            expected_start=payload.expected_start,
            expected_end=payload.expected_end,
            absence_tolerance_seconds=payload.absence_tolerance_seconds,
            dwell_limit_seconds=payload.dwell_limit_seconds,
            expected_min_people=payload.expected_min_people,
            machine_id=payload.machine_id,
        )
    if area is None:
        raise HTTPException(status_code=404, detail="Area nao encontrada.")
    return area


@api.delete("/areas/{area_id}")
def delete_area(area_id: str, request: Request) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        require_area_access(connection, require_user(request, connection), area_id)
        deleted = excluir_area_monitorada(connection, area_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Area nao encontrada.")
    return {"id": area_id, "deleted": True}


@api.post("/areas/{area_id}/activate")
def post_area_activate(area_id: str, request: Request) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        require_area_access(connection, require_user(request, connection), area_id)
        area = atualizar_area_monitorada(connection, area_id, ativa=True)
    if area is None:
        raise HTTPException(status_code=404, detail="Area nao encontrada.")
    return area


@api.post("/areas/{area_id}/deactivate")
def post_area_deactivate(area_id: str, request: Request) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        require_area_access(connection, require_user(request, connection), area_id)
        area = atualizar_area_monitorada(connection, area_id, ativa=False)
    if area is None:
        raise HTTPException(status_code=404, detail="Area nao encontrada.")
    return area


@api.get("/cameras/{camera_id}/machine-monitors")
def get_machine_monitors(camera_id: str, request: Request) -> list[dict[str, Any]]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        camera = obter_camera(connection, camera_id)
        if camera is None:
            raise HTTPException(status_code=404, detail="Camera nao encontrada.")
        if tenant_filter(user) and camera.get("cliente_id") != tenant_filter(user):
            raise HTTPException(status_code=403, detail="Camera de outro cliente.")
        return listar_machine_monitors_camera(connection, camera_id)


@api.post("/cameras/{camera_id}/machine-monitors")
def post_machine_monitor(camera_id: str, payload: MachineMonitorIn, request: Request) -> dict[str, Any]:
    machine_points = normalize_points([point.model_dump() for point in payload.machine_polygon])
    operator_points = normalize_points([point.model_dump() for point in payload.operator_polygon])
    operation_points = normalize_points([point.model_dump() for point in payload.operation_polygon]) if payload.operation_polygon else None
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        camera = obter_camera(connection, camera_id)
        if camera is None:
            raise HTTPException(status_code=404, detail="Camera nao encontrada.")
        if tenant_filter(user) and camera.get("cliente_id") != tenant_filter(user):
            raise HTTPException(status_code=403, detail="Camera de outro cliente.")
        client_id = str(camera.get("cliente_id") or tenant_filter(user) or "")
        unit_id = str(camera.get("unidade_id"))
        existing_monitors = listar_machine_monitors_camera(connection, camera_id)
        existing = next((item for item in existing_monitors if item.get("ativo")), None) or (existing_monitors[0] if existing_monitors else None)
        indicator_points = normalize_points([point.model_dump() for point in payload.indicator_polygon]) if payload.indicator_polygon else None
        if existing:
            monitor_id = existing["id"]
            atualizar_machine_monitor(
                connection,
                monitor_id,
                nome=payload.nome,
                machine_polygon=machine_points,
                operator_polygon=operator_points,
                operation_polygon=operation_points,
                presence_scope=payload.presence_scope,
                ativo=payload.ativo,
                motion_sensitivity=payload.motion_sensitivity,
                stop_seconds=payload.stop_seconds,
                recovery_seconds=payload.recovery_seconds,
                operator_absence_seconds=payload.operator_absence_seconds,
                stopped_with_operator_seconds=payload.stopped_with_operator_seconds,
                microstop_window_seconds=payload.microstop_window_seconds,
                microstop_limit=payload.microstop_limit,
                loss_model=payload.loss_model,
                loss_per_minute=payload.loss_per_minute,
                units_per_minute=payload.units_per_minute,
                margin_per_unit=payload.margin_per_unit,
                indicator_polygon=indicator_points,
            )
            audit_action = "config.machine_monitor.update"
        else:
            monitor_id = criar_machine_monitor(
                connection=connection,
                client_id=client_id,
                unit_id=unit_id,
                camera_id=camera_id,
                nome=payload.nome,
                machine_polygon=machine_points,
                operator_polygon=operator_points,
                ativo=payload.ativo,
                motion_sensitivity=payload.motion_sensitivity,
                stop_seconds=payload.stop_seconds,
                recovery_seconds=payload.recovery_seconds,
                replay_pre_seconds=payload.replay_pre_seconds,
                replay_post_seconds=payload.replay_post_seconds,
                operator_absence_seconds=payload.operator_absence_seconds,
                stopped_with_operator_seconds=payload.stopped_with_operator_seconds,
                microstop_window_seconds=payload.microstop_window_seconds,
                microstop_limit=payload.microstop_limit,
                loss_model=payload.loss_model,
                loss_per_minute=payload.loss_per_minute,
                units_per_minute=payload.units_per_minute,
                margin_per_unit=payload.margin_per_unit,
                indicator_polygon=indicator_points,
                operation_polygon=operation_points,
                presence_scope=payload.presence_scope,
            )
            audit_action = "config.machine_monitor.create"
        linked_areas = _link_machine_monitor_areas(connection, camera_id, monitor_id)
        registrar_audit_log(
            connection,
            action=audit_action,
            actor=user,
            entity_type="machine_monitor",
            entity_id=monitor_id,
            tenant_id=client_id,
            metadata={"camera_id": camera_id, **linked_areas},
        )
        result = obter_machine_monitor(connection, monitor_id)
        if result is None:
            raise HTTPException(status_code=500, detail="Monitor nao foi persistido.")
        result.update(linked_areas)
        return result


@api.patch("/machine-monitors/{monitor_id}")
def patch_machine_monitor(monitor_id: str, payload: MachineMonitorPatchIn, request: Request) -> dict[str, Any]:
    machine_points = normalize_points([point.model_dump() for point in payload.machine_polygon]) if payload.machine_polygon else None
    operator_points = normalize_points([point.model_dump() for point in payload.operator_polygon]) if payload.operator_polygon else None
    operation_points = normalize_points([point.model_dump() for point in payload.operation_polygon]) if payload.operation_polygon else None
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        monitor = obter_machine_monitor(connection, monitor_id)
        if monitor is None:
            raise HTTPException(status_code=404, detail="Monitor nao encontrado.")
        if tenant_filter(user) and monitor.get("client_id") != tenant_filter(user):
            raise HTTPException(status_code=403, detail="Monitor de outro cliente.")
        updated = atualizar_machine_monitor(
            connection,
            monitor_id,
            nome=payload.nome,
            machine_polygon=machine_points,
            operator_polygon=operator_points,
            operation_polygon=operation_points,
            presence_scope=payload.presence_scope,
            ativo=payload.ativo,
            motion_sensitivity=payload.motion_sensitivity,
            motion_threshold=payload.motion_threshold,
            stop_seconds=payload.stop_seconds,
            recovery_seconds=payload.recovery_seconds,
            operator_absence_seconds=payload.operator_absence_seconds,
            stopped_with_operator_seconds=payload.stopped_with_operator_seconds,
            microstop_window_seconds=payload.microstop_window_seconds,
            microstop_limit=payload.microstop_limit,
            loss_model=payload.loss_model,
            loss_per_minute=payload.loss_per_minute,
            units_per_minute=payload.units_per_minute,
            margin_per_unit=payload.margin_per_unit,
            indicator_polygon=normalize_points([point.model_dump() for point in payload.indicator_polygon]) if payload.indicator_polygon else None,
        )
        linked_areas = _link_machine_monitor_areas(connection, monitor.get("camera_id"), monitor_id)
        registrar_audit_log(
            connection,
            action="config.machine_monitor.update",
            actor=user,
            entity_type="machine_monitor",
            entity_id=monitor_id,
            tenant_id=monitor.get("client_id"),
            metadata={"camera_id": monitor.get("camera_id"), **linked_areas},
        )
    if updated is not None:
        updated.update(linked_areas)
    return updated


@api.delete("/machine-monitors/{monitor_id}")
def delete_machine_monitor(monitor_id: str, request: Request) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        monitor = obter_machine_monitor(connection, monitor_id)
        if monitor is None:
            raise HTTPException(status_code=404, detail="Monitor nao encontrado.")
        if tenant_filter(user) and monitor.get("client_id") != tenant_filter(user):
            raise HTTPException(status_code=403, detail="Monitor de outro cliente.")
        deleted = excluir_machine_monitor(connection, monitor_id)
        if deleted:
            registrar_audit_log(
                connection,
                action="config.machine_monitor.delete",
                actor=user,
                entity_type="machine_monitor",
                entity_id=monitor_id,
                tenant_id=monitor.get("client_id"),
                metadata={"camera_id": monitor.get("camera_id")},
            )
        return {"id": monitor_id, "deleted": deleted}


@api.post("/machine-monitors/{monitor_id}/activate")
def post_machine_monitor_activate(monitor_id: str, request: Request) -> dict[str, Any]:
    return patch_machine_monitor(monitor_id, MachineMonitorPatchIn(ativo=True), request)


@api.post("/machine-monitors/{monitor_id}/deactivate")
def post_machine_monitor_deactivate(monitor_id: str, request: Request) -> dict[str, Any]:
    return patch_machine_monitor(monitor_id, MachineMonitorPatchIn(ativo=False), request)


@api.post("/machine-monitors/{monitor_id}/calibrate")
def post_machine_monitor_calibrate(monitor_id: str, payload: MachineCalibrationIn, request: Request) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        monitor = obter_machine_monitor(connection, monitor_id)
        if monitor is None:
            raise HTTPException(status_code=404, detail="Monitor nao encontrado.")
        if tenant_filter(user) and monitor.get("client_id") != tenant_filter(user):
            raise HTTPException(status_code=403, detail="Monitor de outro cliente.")
        running = payload.running_motion if payload.running_motion is not None else monitor.get("running_motion")
        stopped = payload.stopped_motion if payload.stopped_motion is not None else monitor.get("stopped_motion")
        threshold = calibrate_threshold(running or monitor["motion_sensitivity"] * 2, stopped or monitor["motion_sensitivity"] * 0.3)
        return atualizar_machine_monitor(
            connection,
            monitor_id,
            motion_threshold=threshold,
            calibration_status="calibrated",
            running_motion=running,
            stopped_motion=stopped,
        )


@api.post("/machine-monitors/{monitor_id}/calibrate-active")
def post_machine_monitor_calibrate_active(monitor_id: str, payload: MachineCalibrationIn, request: Request) -> dict[str, Any]:
    return calibrate_machine_monitor_phase(monitor_id, payload, request, "active")


@api.post("/machine-monitors/{monitor_id}/calibrate-stopped")
def post_machine_monitor_calibrate_stopped(monitor_id: str, payload: MachineCalibrationIn, request: Request) -> dict[str, Any]:
    return calibrate_machine_monitor_phase(monitor_id, payload, request, "stopped")


@api.post("/machine-monitors/{monitor_id}/calibration/active/start")
def post_machine_monitor_assisted_active_start(monitor_id: str, payload: AssistedMachineCalibrationIn, request: Request) -> dict[str, object]:
    return start_assisted_machine_calibration(monitor_id, payload, request, "active")


@api.post("/machine-monitors/{monitor_id}/calibration/stopped/start")
def post_machine_monitor_assisted_stopped_start(monitor_id: str, payload: AssistedMachineCalibrationIn, request: Request) -> dict[str, object]:
    return start_assisted_machine_calibration(monitor_id, payload, request, "stopped")


def _build_calibration_readiness(
    monitor: dict[str, Any],
    separation: dict[str, object] | None,
    engine_cal: dict[str, object] | None,
) -> dict[str, object]:
    if engine_cal:
        active_baseline = engine_cal.get("active_baseline")
        stopped_baseline = engine_cal.get("stopped_baseline")
        active_noise = engine_cal.get("active_noise")
        stopped_noise = engine_cal.get("stopped_noise")
        separation_score = engine_cal.get("separation_score")
        threshold = engine_cal.get("threshold")
        result = engine_cal.get("calibration_result")
    else:
        active_baseline = monitor.get("active_baseline")
        stopped_baseline = monitor.get("stopped_baseline")
        active_noise = monitor.get("active_noise")
        stopped_noise = monitor.get("stopped_noise")
        separation_score = monitor.get("separation_score")
        threshold = monitor.get("motion_threshold")
        result = monitor.get("calibration_result")

    ready = (
        result == "READY"
        and active_baseline is not None
        and stopped_baseline is not None
    )
    reason = (separation or {}).get("message")
    return {
        "ready": ready,
        "result": result,
        "active_baseline": active_baseline,
        "stopped_baseline": stopped_baseline,
        "active_noise": active_noise,
        "stopped_noise": stopped_noise,
        "separation_score": separation_score,
        "threshold": threshold,
        "reason": reason,
    }


@api.get("/machine-monitors/{monitor_id}/calibration/status")
def get_machine_monitor_calibration_status(monitor_id: str, request: Request) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        monitor = obter_machine_monitor(connection, monitor_id)
        if monitor is None:
            raise HTTPException(status_code=404, detail="Monitor nao encontrado.")
        if tenant_filter(user) and monitor.get("client_id") != tenant_filter(user):
            raise HTTPException(status_code=403, detail="Monitor de outro cliente.")
    stream = live_streams.get(str(monitor["camera_id"]))
    stream_status = stream.calibration_status() if stream else {"status": "idle"}
    active_calibration = monitor.get("active_calibration")
    stopped_calibration = monitor.get("stopped_calibration")
    separation = calibration_separation(active_calibration, stopped_calibration)
    diagnostics = {
        "active_baseline": monitor.get("active_baseline"),
        "stopped_baseline": monitor.get("stopped_baseline"),
        "active_samples": (active_calibration or {}).get("samples_count") if isinstance(active_calibration, dict) else 0,
        "stopped_samples": (stopped_calibration or {}).get("samples_count") if isinstance(stopped_calibration, dict) else 0,
        "active_noise": monitor.get("active_noise"),
        "stopped_noise": monitor.get("stopped_noise"),
        "separability": monitor.get("separation_score"),
        "separation": separation,
        "reason": separation.get("message"),
    }
    snapshot = stream.machine_diagnostics(monitor_id) if stream else None
    runtime_diagnostics = snapshot.get("runtime_diagnostics") if snapshot else None
    engine_cal = snapshot.get("calibration") if snapshot else None
    calibration_readiness = _build_calibration_readiness(monitor, separation, engine_cal)
    return {
        "machine_id": monitor_id,
        "camera_id": monitor["camera_id"],
        "stream": stream_status,
        "active_calibration": active_calibration,
        "stopped_calibration": stopped_calibration,
        "active_baseline": monitor.get("active_baseline"),
        "stopped_baseline": monitor.get("stopped_baseline"),
        "separation_score": monitor.get("separation_score"),
        "calibration_result": monitor.get("calibration_result"),
        "calibration_status": monitor.get("calibration_status"),
        "diagnostics": diagnostics,
        "runtime_diagnostics": runtime_diagnostics,
        "calibration_readiness": calibration_readiness,
    }


def start_assisted_machine_calibration(monitor_id: str, payload: AssistedMachineCalibrationIn, request: Request, phase: str) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        monitor = obter_machine_monitor(connection, monitor_id)
        if monitor is None:
            raise HTTPException(status_code=404, detail="Monitor nao encontrado.")
        if tenant_filter(user) and monitor.get("client_id") != tenant_filter(user):
            raise HTTPException(status_code=403, detail="Monitor de outro cliente.")
        region = next(
            (
                area
                for area in listar_areas_camera(connection, str(monitor["camera_id"]))
                if area.get("ativa", True)
                and area.get("tipo") == "machine_region"
                and (not area.get("machine_id") or area.get("machine_id") == monitor_id)
            ),
            None,
        )
    if region is None:
        raise HTTPException(status_code=400, detail="Calibracao exige uma machine_region salva para esta camera.")
    _camera, source = load_camera_source(str(monitor["camera_id"]))
    stream = live_streams.get_or_create(str(monitor["camera_id"]), source)
    stream.start()
    try:
        status_payload = stream.start_machine_calibration(
            monitor,
            region["pontos"],
            phase,
            duration_seconds=payload.duration_seconds,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "machine_id": monitor_id,
        "camera_id": monitor["camera_id"],
        "phase": phase,
        "machine_region_id": region["id"],
        "status": status_payload,
    }


def calibrate_machine_monitor_phase(monitor_id: str, payload: MachineCalibrationIn, request: Request, phase: str) -> dict[str, Any]:
    samples = payload.samples or []
    if phase == "active" and payload.running_motion is not None:
        samples = [payload.running_motion]
    if phase == "stopped" and payload.stopped_motion is not None:
        samples = [payload.stopped_motion]
    try:
        baseline, noise = baseline_stats(samples)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        monitor = obter_machine_monitor(connection, monitor_id)
        if monitor is None:
            raise HTTPException(status_code=404, detail="Monitor nao encontrado.")
        if tenant_filter(user) and monitor.get("client_id") != tenant_filter(user):
            raise HTTPException(status_code=403, detail="Monitor de outro cliente.")
        active = baseline if phase == "active" else monitor.get("active_baseline") or monitor.get("running_motion")
        stopped = baseline if phase == "stopped" else monitor.get("stopped_baseline") or monitor.get("stopped_motion")
        threshold = calibrate_threshold(active, stopped) if active is not None and stopped is not None else monitor.get("motion_threshold")
        status_text = "calibrated" if active is not None and stopped is not None else f"{phase}_calibrated"
        return atualizar_machine_monitor(
            connection,
            monitor_id,
            motion_threshold=threshold,
            calibration_status=status_text,
            running_motion=active,
            stopped_motion=stopped,
            active_baseline=active,
            stopped_baseline=stopped,
            active_noise=noise if phase == "active" else None,
            stopped_noise=noise if phase == "stopped" else None,
        )


def _rule_context(connection, payload: RegraIn, user: dict[str, Any]) -> tuple[str | None, str | None]:
    camera = obter_camera(connection, payload.camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera nao encontrada.")
    require_same_tenant(user, camera.get("cliente_id"), "Camera de outro cliente.")
    cliente_id = payload.cliente_id or camera.get("cliente_id") or tenant_filter(user)
    unidade_id = payload.unidade_id or camera.get("unidade_id")
    return cliente_id, unidade_id


@api.get("/visual-rules/templates")
def get_visual_rule_templates() -> dict[str, Any]:
    return {"conditions": condition_templates()}


@api.get("/visual-rules")
def get_visual_rules(request: Request, camera_id: Optional[str] = None) -> list[dict[str, Any]]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        if camera_id:
            require_camera_access(connection, user, camera_id)
        return listar_regras(connection, tenant_filter(user), camera_id)


@api.post("/visual-rules")
def post_visual_rule(payload: RegraIn, request: Request) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_role(user, ADMIN_ROLES)
        cliente_id, unidade_id = _rule_context(connection, payload, user)
        rule_id = criar_regra(
            connection,
            payload.camera_id,
            payload.tipo_evento,
            payload.tempo_minimo,
            payload.ativo,
            nome=payload.nome,
            cliente_id=cliente_id,
            unidade_id=unidade_id,
            entidade=payload.entidade,
            regiao_id=payload.regiao_id,
            condicao=payload.condicao or {"type": payload.tipo_evento},
            severidade=payload.severidade,
            cooldown_seconds=payload.cooldown_seconds,
            destinatarios=payload.destinatarios,
            alerta_inicio=payload.alerta_inicio,
            alerta_normalizacao=payload.alerta_normalizacao,
            debounce_seconds=payload.debounce_seconds,
            hysteresis_seconds=payload.hysteresis_seconds,
            metadata=payload.metadata,
        )
        return obter_regra(connection, rule_id)


@api.post("/regras")
def post_regra(payload: RegraIn, request: Request) -> dict[str, Any]:
    return post_visual_rule(payload, request)


@api.patch("/visual-rules/{rule_id}")
def patch_visual_rule(rule_id: str, payload: RegraPatchIn, request: Request) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_role(user, ADMIN_ROLES)
        rule = obter_regra(connection, rule_id)
        if rule is None:
            raise HTTPException(status_code=404, detail="Regra nao encontrada.")
        require_same_tenant(user, rule.get("cliente_id"), "Regra de outro cliente.")
        updated = atualizar_regra(connection, rule_id, **payload.model_dump())
    if updated is None:
        raise HTTPException(status_code=404, detail="Regra nao encontrada.")
    return updated


@api.post("/visual-rules/{rule_id}/simulate")
def post_visual_rule_simulate(rule_id: str, payload: VisualRuleSimulationIn, request: Request) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        rule = obter_regra(connection, rule_id)
        if rule is None:
            raise HTTPException(status_code=404, detail="Regra nao encontrada.")
        require_same_tenant(user, rule.get("cliente_id"), "Regra de outro cliente.")
        return evaluate_rule(connection, rule_id, payload.facts, at=payload.at)


@api.post("/cameras/{camera_id}/visual-rules/defaults")
def post_camera_visual_rule_defaults(camera_id: str, payload: VisualRuleDefaultsIn, request: Request) -> dict[str, Any]:
    created: list[dict[str, Any]] = []
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_role(user, ADMIN_ROLES)
        camera = obter_camera(connection, camera_id)
        if camera is None:
            raise HTTPException(status_code=404, detail="Camera nao encontrada.")
        require_same_tenant(user, camera.get("cliente_id"), "Camera de outro cliente.")
        existing_names = {rule["nome"] for rule in listar_regras(connection, camera_id=camera_id)}
        for item in default_rule_payloads(camera_id, payload.zone_id):
            if item["nome"] in existing_names:
                continue
            rule_id = criar_regra(
                connection,
                camera_id,
                item["tipo_evento"],
                item["tempo_minimo"],
                True,
                nome=item["nome"],
                cliente_id=camera.get("cliente_id"),
                unidade_id=camera.get("unidade_id"),
                entidade=item.get("entidade"),
                regiao_id=item.get("regiao_id"),
                condicao=item["condicao"],
                severidade=item["severidade"],
                cooldown_seconds=item["cooldown_seconds"],
                alerta_inicio=item["alerta_inicio"],
                alerta_normalizacao=item["alerta_normalizacao"],
            )
            created.append(obter_regra(connection, rule_id))
    return {"created": created, "total": len(created)}


@api.post("/eventos")
def post_evento(payload: EventoIn, request: Request) -> dict[str, str]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_same_tenant(user, payload.cliente_id, "Evento de outro cliente.")
        require_camera_access(connection, user, payload.camera_id)
        return {"id": registrar_evento(connection, **payload.model_dump())}


@api.patch("/eventos/{evento_id}")
def patch_evento(evento_id: str, payload: EventoUpdateIn, request: Request) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        require_event_access(connection, require_user(request, connection), evento_id)
        if payload.status == "acknowledged":
            event = reconhecer_ocorrencia(
                connection,
                evento_id,
                payload.observacao,
                payload.acknowledged_by,
                now_iso(),
            )
            if event is None:
                raise HTTPException(status_code=404, detail="Evento nao encontrado.")
            return event
        atualizar_evento(
            connection,
            evento_id,
            fim=payload.fim,
            duracao=payload.duracao,
            operador_presente=payload.operador_presente,
            confianca=payload.confianca,
            midia_path=payload.midia_path,
        )
        event = obter_evento(connection, evento_id)
        if event is None:
            raise HTTPException(status_code=404, detail="Evento nao encontrado.")
        return event


@api.delete("/eventos")
def delete_eventos(request: Request) -> dict[str, int]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_role(user, ADMIN_ROLES)

        cliente_id = tenant_filter(user)
        if not cliente_id:
            raise HTTPException(
                status_code=400,
                detail="Selecione um cliente antes de limpar os eventos.",
            )

        rows = connection.execute(
            "SELECT id FROM eventos WHERE cliente_id = ?",
            (cliente_id,),
        ).fetchall()
        event_ids = [row["id"] for row in rows]

        if not event_ids:
            return {"deleted": 0}

        placeholders = ",".join("?" for _ in event_ids)

        connection.execute(
            f"UPDATE visual_rule_states SET active_event_id = NULL "
            f"WHERE active_event_id IN ({placeholders})",
            event_ids,
        )
        connection.execute(
            f"DELETE FROM alert_deliveries WHERE evento_id IN ({placeholders})",
            event_ids,
        )
        connection.execute(
            f"DELETE FROM alertas WHERE evento_id IN ({placeholders})",
            event_ids,
        )
        connection.execute(
            f"DELETE FROM evidences WHERE event_id IN ({placeholders})",
            event_ids,
        )
        connection.execute(
            f"DELETE FROM eventos WHERE id IN ({placeholders})",
            event_ids,
        )
        connection.commit()

        return {"deleted": len(event_ids)}


@api.get("/eventos")
def get_eventos(
    request: Request,
    camera_id: Optional[str] = None,
    area_id: Optional[str] = None,
    status: Optional[str] = None,
    tipo: Optional[str] = None,
    event_family: Optional[str] = None,
    data_inicio: Optional[str] = None,
    data_fim: Optional[str] = None,
) -> list[dict[str, Any]]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        if tenant_filter(user):
            events = listar_eventos_filtrados(connection, camera_id, area_id, status, tipo, data_inicio, data_fim, event_family=event_family)
            return [event for event in events if event.get("cliente_id") == tenant_filter(user)]
        return listar_eventos_filtrados(connection, camera_id, area_id, status, tipo, data_inicio, data_fim, event_family=event_family)


@api.get("/eventos/{evento_id}")
def get_evento(evento_id: str, request: Request) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        return require_event_access(connection, require_user(request, connection), evento_id)


@api.get("/eventos/{evento_id}/detail")
def get_evento_detail(evento_id: str, request: Request) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        event = event_detail(connection, evento_id)
        if event is None:
            raise HTTPException(status_code=404, detail="Evento nao encontrado.")
        if tenant_filter(user) and event.get("cliente_id") != tenant_filter(user):
            raise HTTPException(status_code=403, detail="Evento de outro cliente.")
        return event


@api.get("/events/{event_uuid}/context")
def get_event_context(event_uuid: str, request: Request) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        try:
            return build_context_pack(connection, event_uuid, tenant_id=tenant_filter(user))
        except ContextPackNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Evento nao encontrado.") from exc
        except ContextPackAccessError as exc:
            raise HTTPException(status_code=403, detail="Evento de outro cliente.") from exc


@api.post("/events/{event_uuid}/reason")
def post_event_reason(event_uuid: str, request: Request) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        try:
            context_pack = build_context_pack(connection, event_uuid, tenant_id=tenant_filter(user))
        except ContextPackNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Evento nao encontrado.") from exc
        except ContextPackAccessError as exc:
            raise HTTPException(status_code=403, detail="Evento de outro cliente.") from exc
    try:
        return ReasoningEngine().reason(context_pack)
    except ReasoningError as exc:
        status_code = 503 if exc.code in {"AI_NOT_CONFIGURED", "AI_UNAVAILABLE"} else 502
        raise HTTPException(status_code=status_code, detail=reasoning_error_response(exc)) from exc


@api.post("/events/{event_uuid}/recommend")
def post_event_recommend(event_uuid: str, request: Request) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        try:
            context_pack = build_context_pack(connection, event_uuid, tenant_id=tenant_filter(user))
        except ContextPackNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Evento nao encontrado.") from exc
        except ContextPackAccessError as exc:
            raise HTTPException(status_code=403, detail="Evento de outro cliente.") from exc
    try:
        reasoning = ReasoningEngine().reason(context_pack)
        recommendation = RecommendationEngine().recommend(context_pack, reasoning["reasoning"])
    except ReasoningError as exc:
        status_code = 503 if exc.code in {"AI_NOT_CONFIGURED", "AI_UNAVAILABLE"} else 502
        raise HTTPException(status_code=status_code, detail=reasoning_error_response(exc)) from exc
    except RecommendationError as exc:
        status_code = 503 if exc.code in {"AI_NOT_CONFIGURED", "AI_UNAVAILABLE"} else 502
        raise HTTPException(status_code=status_code, detail=recommendation_error_response(exc)) from exc
    return {"status": "ok", "reasoning": reasoning, "recommendation": recommendation}


@api.post("/eventos/{evento_id}/acknowledge")
def post_evento_acknowledge(evento_id: str, payload: EventHumanContextIn, request: Request) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        event = obter_evento(connection, evento_id)
        if event is None:
            raise HTTPException(status_code=404, detail="Evento nao encontrado.")
        if tenant_filter(user) and event.get("cliente_id") != tenant_filter(user):
            raise HTTPException(status_code=403, detail="Evento de outro cliente.")
        acknowledged = acknowledge_event(connection, evento_id, actor=user, human_notes=payload.human_notes)
        if acknowledged is None:
            raise HTTPException(status_code=404, detail="Evento nao encontrado.")
        if payload.confirmed_cause or payload.action_taken:
            acknowledged = update_human_context(
                connection,
                evento_id,
                confirmed_cause=payload.confirmed_cause,
                action_taken=payload.action_taken,
                human_notes=payload.human_notes,
                actor=user,
            )
        return event_detail(connection, evento_id) or acknowledged


@api.patch("/eventos/{evento_id}/human-context")
def patch_evento_human_context(evento_id: str, payload: EventHumanContextIn, request: Request) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        event = obter_evento(connection, evento_id)
        if event is None:
            raise HTTPException(status_code=404, detail="Evento nao encontrado.")
        if tenant_filter(user) and event.get("cliente_id") != tenant_filter(user):
            raise HTTPException(status_code=403, detail="Evento de outro cliente.")
        updated = update_human_context(
            connection,
            evento_id,
            confirmed_cause=payload.confirmed_cause,
            action_taken=payload.action_taken,
            human_notes=payload.human_notes,
            actor=user,
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="Evento nao encontrado.")
        return event_detail(connection, evento_id) or updated


@api.patch("/eventos/{evento_id}/memory")
def patch_evento_operational_memory(evento_id: str, payload: EventOperationalMemoryIn, request: Request) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        event = obter_evento(connection, evento_id)
        if event is None:
            raise HTTPException(status_code=404, detail="Evento nao encontrado.")
        if tenant_filter(user) and event.get("cliente_id") != tenant_filter(user):
            raise HTTPException(status_code=403, detail="Evento de outro cliente.")
        try:
            updated = update_operational_memory(
                connection,
                evento_id,
                actor=user,
                confirmed_cause=payload.confirmed_cause,
                action_taken=payload.action_taken,
                recommendation_id=payload.recommendation_id,
                recommendation_accepted=payload.recommendation_accepted,
                outcome_status=payload.outcome_status,
                outcome_notes=payload.outcome_notes,
                human_notes=payload.human_notes,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if updated is None:
            raise HTTPException(status_code=404, detail="Evento nao encontrado.")
        return event_detail(connection, evento_id) or updated


@api.post("/eventos/{evento_id}/resolve")
def post_evento_resolve(evento_id: str, payload: EventResolveIn, request: Request) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        event = obter_evento(connection, evento_id)
        if event is None:
            raise HTTPException(status_code=404, detail="Evento nao encontrado.")
        if tenant_filter(user) and event.get("cliente_id") != tenant_filter(user):
            raise HTTPException(status_code=403, detail="Evento de outro cliente.")
        resolved = resolve_event(
            connection,
            evento_id,
            actor=user,
            confirmed_cause=payload.confirmed_cause,
            action_taken=payload.action_taken,
            human_notes=payload.human_notes,
        )
        if resolved is None:
            raise HTTPException(status_code=404, detail="Evento nao encontrado.")
        return event_detail(connection, evento_id) or resolved


@api.get("/eventos/{evento_id}/evidence")
def get_evento_evidence(evento_id: str, request: Request) -> FileResponse:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        event = obter_evento(connection, evento_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Evento nao encontrado.")
    if tenant_filter(user) and event.get("cliente_id") != tenant_filter(user):
        raise HTTPException(status_code=403, detail="Evento de outro cliente.")
    midia_path = event.get("midia_path")
    if not midia_path:
        raise HTTPException(status_code=404, detail="Evidencia nao encontrada.")
    path = (ROOT / str(midia_path)).resolve()
    evidence_root = EVIDENCE_DIR.resolve()
    if evidence_root not in path.parents:
        raise HTTPException(status_code=403, detail="Caminho de evidencia invalido.")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Arquivo de evidencia nao encontrado.")
    return FileResponse(path, media_type="image/jpeg", filename=f"{evento_id}.jpg")


@api.get("/eventos/{evento_id}/evidence/{evidence_id}")
def get_evento_evidence_item(
    evento_id: str,
    evidence_id: str,
    request: Request,
) -> FileResponse:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        event = obter_evento(connection, evento_id)

        if event is None:
            raise HTTPException(status_code=404, detail="Evento nao encontrado.")

        if tenant_filter(user) and event.get("cliente_id") != tenant_filter(user):
            raise HTTPException(status_code=403, detail="Evento de outro cliente.")

        evidence = connection.execute(
            """
            SELECT id, path, media_type
            FROM evidences
            WHERE id = ? AND event_id = ?
            LIMIT 1
            """,
            (evidence_id, evento_id),
        ).fetchone()

    if evidence is None:
        raise HTTPException(status_code=404, detail="Evidencia nao encontrada.")

    path = (ROOT / str(evidence["path"])).resolve()
    evidence_root = EVIDENCE_DIR.resolve()

    if evidence_root not in path.parents:
        raise HTTPException(status_code=403, detail="Caminho de evidencia invalido.")

    if not path.exists():
        raise HTTPException(status_code=404, detail="Arquivo de evidencia nao encontrado.")

    return FileResponse(
        path,
        media_type=evidence["media_type"] or "image/jpeg",
        filename=f"{evidence_id}.jpg",
    )


@api.get("/eventos/{evento_id}/replay")
def get_evento_replay(evento_id: str, request: Request) -> FileResponse:
    with connect() as connection:
        init_db(connection)
        event = require_event_access(connection, require_user(request, connection), evento_id)
    replay_path = event.get("replay_path")
    if not replay_path:
        raise HTTPException(status_code=404, detail="Replay nao encontrado.")
    path = (ROOT / str(replay_path)).resolve()
    replay_root = (ROOT / "data" / "replays").resolve()
    if replay_root not in path.parents:
        raise HTTPException(status_code=403, detail="Caminho de replay invalido.")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Arquivo de replay nao encontrado.")
    return FileResponse(path, media_type="video/mp4", filename=f"{evento_id}.mp4")


@api.patch("/eventos/{evento_id}/cause")
def patch_evento_cause(evento_id: str, payload: EventCauseIn, request: Request) -> dict[str, Any]:
    allowed = {
        "manutenção",
        "falta de material",
        "ajuste de máquina",
        "intervalo",
        "operador ausente",
        "bloqueio de processo",
        "parada planejada",
        "falso alerta",
        "outra",
    }
    if payload.cause_category not in allowed:
        raise HTTPException(status_code=400, detail="Categoria de causa invalida.")
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        event = obter_evento(connection, evento_id)
        if event is None:
            raise HTTPException(status_code=404, detail="Evento nao encontrado.")
        if tenant_filter(user) and event.get("cliente_id") != tenant_filter(user):
            raise HTTPException(status_code=403, detail="Evento de outro cliente.")
        return classificar_evento(
            connection,
            evento_id,
            payload.cause_category,
            payload.cause_notes,
            payload.classified_by or user.get("email"),
            now_iso(),
        )


@api.get("/operations/summary")
def get_operations_summary(
    request: Request,
    start: Optional[str] = None,
    end: Optional[str] = None,
    camera_id: Optional[str] = None,
    machine_name: Optional[str] = None,
) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        require_camera_access(connection, require_user(request, connection), camera_id)
        return operations_summary(connection, start, end, camera_id, machine_name)


@api.get("/operations/timeline")
def get_operations_timeline(
    request: Request,
    period: str = "day",
    start: Optional[str] = None,
    end: Optional[str] = None,
    cliente_id: Optional[str] = None,
    site_id: Optional[str] = None,
    area_context_id: Optional[str] = None,
    process_id: Optional[str] = None,
    asset_id: Optional[str] = None,
    camera_id: Optional[str] = None,
    event_family: Optional[str] = None,
    tipo: Optional[str] = None,
    workflow_status: Optional[str] = None,
) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_camera_access(connection, user, camera_id)
        filters = _read_model_filters(
            user,
            cliente_id=cliente_id,
            site_id=site_id,
            area_context_id=area_context_id,
            process_id=process_id,
            asset_id=asset_id,
            camera_id=camera_id,
            event_family=event_family,
            tipo=tipo,
            workflow_status=workflow_status,
            start=start,
            end=end,
            period=period,
        )
        try:
            return read_model_timeline(connection, filters)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@api.get("/operations/events")
def get_operations_events(
    request: Request,
    start: Optional[str] = None,
    end: Optional[str] = None,
    camera_id: Optional[str] = None,
    machine_name: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        require_camera_access(connection, require_user(request, connection), camera_id)
        events = list_operational_events(connection, start, end, camera_id, machine_name, limit, offset)
        return {"events": events, "limit": limit, "offset": offset}


@api.get("/operations/current-status")
def get_operations_current_status(
    request: Request,
    camera_id: Optional[str] = None,
    machine_name: Optional[str] = None,
) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        require_camera_access(connection, require_user(request, connection), camera_id)
        return current_status(connection, camera_id, machine_name)


def _read_model_filters(
    user: dict[str, Any],
    *,
    cliente_id: str | None = None,
    site_id: str | None = None,
    area_context_id: str | None = None,
    process_id: str | None = None,
    asset_id: str | None = None,
    camera_id: str | None = None,
    event_family: str | None = None,
    tipo: str | None = None,
    workflow_status: str | None = None,
    start: str | None = None,
    end: str | None = None,
    period: str = "day",
) -> ReadModelFilters:
    tenant_id = tenant_filter(user) or cliente_id
    start_dt, end_dt = read_model_period_bounds(period, start, end)
    return ReadModelFilters(
        cliente_id=tenant_id,
        site_id=site_id,
        area_context_id=area_context_id,
        process_id=process_id,
        asset_id=asset_id,
        camera_id=camera_id,
        event_family=event_family,
        tipo=tipo,
        workflow_status=workflow_status,
        start=start_dt,
        end=end_dt,
    )


@api.get("/operations/read-model/current")
def get_operations_read_model_current(
    request: Request,
    cliente_id: Optional[str] = None,
    site_id: Optional[str] = None,
    area_context_id: Optional[str] = None,
    process_id: Optional[str] = None,
    asset_id: Optional[str] = None,
    camera_id: Optional[str] = None,
    event_family: Optional[str] = None,
    tipo: Optional[str] = None,
    workflow_status: Optional[str] = None,
) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_camera_access(connection, user, camera_id)
        filters = ReadModelFilters(
            cliente_id=tenant_filter(user) or cliente_id,
            site_id=site_id,
            area_context_id=area_context_id,
            process_id=process_id,
            asset_id=asset_id,
            camera_id=camera_id,
            event_family=event_family,
            tipo=tipo,
            workflow_status=workflow_status,
        )
        return read_model_current(connection, filters)


@api.get("/operations/read-model/summary")
def get_operations_read_model_summary(
    request: Request,
    period: str = "day",
    start: Optional[str] = None,
    end: Optional[str] = None,
    cliente_id: Optional[str] = None,
    site_id: Optional[str] = None,
    area_context_id: Optional[str] = None,
    process_id: Optional[str] = None,
    asset_id: Optional[str] = None,
    camera_id: Optional[str] = None,
    event_family: Optional[str] = None,
    tipo: Optional[str] = None,
    workflow_status: Optional[str] = None,
) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_camera_access(connection, user, camera_id)
        filters = _read_model_filters(
            user,
            cliente_id=cliente_id,
            site_id=site_id,
            area_context_id=area_context_id,
            process_id=process_id,
            asset_id=asset_id,
            camera_id=camera_id,
            event_family=event_family,
            tipo=tipo,
            workflow_status=workflow_status,
            start=start,
            end=end,
            period=period,
        )
        return read_model_summary(connection, filters)


@api.get("/operations/read-model/losses")
def get_operations_read_model_losses(
    request: Request,
    period: str = "day",
    start: Optional[str] = None,
    end: Optional[str] = None,
    cliente_id: Optional[str] = None,
    site_id: Optional[str] = None,
    area_context_id: Optional[str] = None,
    process_id: Optional[str] = None,
    asset_id: Optional[str] = None,
    camera_id: Optional[str] = None,
    event_family: Optional[str] = None,
    tipo: Optional[str] = None,
    workflow_status: Optional[str] = None,
) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_camera_access(connection, user, camera_id)
        filters = _read_model_filters(
            user,
            cliente_id=cliente_id,
            site_id=site_id,
            area_context_id=area_context_id,
            process_id=process_id,
            asset_id=asset_id,
            camera_id=camera_id,
            event_family=event_family,
            tipo=tipo,
            workflow_status=workflow_status,
            start=start,
            end=end,
            period=period,
        )
        return read_model_losses(connection, filters)


@api.get("/operations/read-model/comparison")
def get_operations_read_model_comparison(
    request: Request,
    period: str = "day",
    start: Optional[str] = None,
    end: Optional[str] = None,
    cliente_id: Optional[str] = None,
    site_id: Optional[str] = None,
    area_context_id: Optional[str] = None,
    process_id: Optional[str] = None,
    asset_id: Optional[str] = None,
    camera_id: Optional[str] = None,
    event_family: Optional[str] = None,
    tipo: Optional[str] = None,
    workflow_status: Optional[str] = None,
) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_camera_access(connection, user, camera_id)
        filters = _read_model_filters(
            user,
            cliente_id=cliente_id,
            site_id=site_id,
            area_context_id=area_context_id,
            process_id=process_id,
            asset_id=asset_id,
            camera_id=camera_id,
            event_family=event_family,
            tipo=tipo,
            workflow_status=workflow_status,
            start=start,
            end=end,
            period=period,
        )
        try:
            return read_model_comparison(connection, filters)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@api.get("/operations/read-model/insights")
def get_operations_read_model_insights(
    request: Request,
    period: str = "day",
    start: Optional[str] = None,
    end: Optional[str] = None,
    cliente_id: Optional[str] = None,
    site_id: Optional[str] = None,
    area_context_id: Optional[str] = None,
    process_id: Optional[str] = None,
    asset_id: Optional[str] = None,
    camera_id: Optional[str] = None,
    event_family: Optional[str] = None,
    tipo: Optional[str] = None,
    workflow_status: Optional[str] = None,
) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_camera_access(connection, user, camera_id)
        filters = _read_model_filters(
            user,
            cliente_id=cliente_id,
            site_id=site_id,
            area_context_id=area_context_id,
            process_id=process_id,
            asset_id=asset_id,
            camera_id=camera_id,
            event_family=event_family,
            tipo=tipo,
            workflow_status=workflow_status,
            start=start,
            end=end,
            period=period,
        )
        try:
            return read_model_intelligence(connection, filters)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@api.get("/operations/read-model/operational-data")
def get_operations_read_model_operational_data(
    request: Request,
    period: str = "day",
    start: Optional[str] = None,
    end: Optional[str] = None,
    cliente_id: Optional[str] = None,
    site_id: Optional[str] = None,
    area_context_id: Optional[str] = None,
    process_id: Optional[str] = None,
    asset_id: Optional[str] = None,
    camera_id: Optional[str] = None,
    event_family: Optional[str] = None,
    tipo: Optional[str] = None,
    workflow_status: Optional[str] = None,
) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_camera_access(connection, user, camera_id)
        filters = _read_model_filters(
            user,
            cliente_id=cliente_id,
            site_id=site_id,
            area_context_id=area_context_id,
            process_id=process_id,
            asset_id=asset_id,
            camera_id=camera_id,
            event_family=event_family,
            tipo=tipo,
            workflow_status=workflow_status,
            start=start,
            end=end,
            period=period,
        )
        try:
            return read_model_operational_data(connection, filters)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@api.get("/operations/read-model/daily-report")
def get_operations_read_model_daily_report(
    request: Request,
    period: str = "day",
    start: Optional[str] = None,
    end: Optional[str] = None,
    cliente_id: Optional[str] = None,
    site_id: Optional[str] = None,
    area_context_id: Optional[str] = None,
    process_id: Optional[str] = None,
    asset_id: Optional[str] = None,
    camera_id: Optional[str] = None,
    event_family: Optional[str] = None,
    tipo: Optional[str] = None,
    workflow_status: Optional[str] = None,
) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_camera_access(connection, user, camera_id)
        filters = _read_model_filters(
            user,
            cliente_id=cliente_id,
            site_id=site_id,
            area_context_id=area_context_id,
            process_id=process_id,
            asset_id=asset_id,
            camera_id=camera_id,
            event_family=event_family,
            tipo=tipo,
            workflow_status=workflow_status,
            start=start,
            end=end,
            period=period,
        )
        try:
            return read_model_daily_report(connection, filters)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@api.get("/operations/change-anomalies")
def get_operations_change_anomalies(
    request: Request,
    period: str = "day",
    start: Optional[str] = None,
    end: Optional[str] = None,
    cliente_id: Optional[str] = None,
    site_id: Optional[str] = None,
    area_context_id: Optional[str] = None,
    process_id: Optional[str] = None,
    asset_id: Optional[str] = None,
    camera_id: Optional[str] = None,
    event_family: Optional[str] = None,
    tipo: Optional[str] = None,
    workflow_status: Optional[str] = None,
) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_camera_access(connection, user, camera_id)
        filters = _read_model_filters(
            user,
            cliente_id=cliente_id,
            site_id=site_id,
            area_context_id=area_context_id,
            process_id=process_id,
            asset_id=asset_id,
            camera_id=camera_id,
            event_family=event_family,
            tipo=tipo,
            workflow_status=workflow_status,
            start=start,
            end=end,
            period=period,
        )
        try:
            return read_model_change_anomalies(connection, filters)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@api.get("/operations/impact")
def get_operations_impact(
    request: Request,
    period: str = "day",
    start: Optional[str] = None,
    end: Optional[str] = None,
    cliente_id: Optional[str] = None,
    site_id: Optional[str] = None,
    area_context_id: Optional[str] = None,
    process_id: Optional[str] = None,
    asset_id: Optional[str] = None,
    camera_id: Optional[str] = None,
) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_camera_access(connection, user, camera_id)
        filters = _read_model_filters(
            user,
            cliente_id=cliente_id,
            site_id=site_id,
            area_context_id=area_context_id,
            process_id=process_id,
            asset_id=asset_id,
            camera_id=camera_id,
            start=start,
            end=end,
            period=period,
        )
        try:
            return calculate_operational_impact(connection, filters)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@api.get("/operations/assets/{asset_id}/economic-config")
def get_operations_asset_economic_config(asset_id: str, request: Request) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        config = get_asset_economic_config(connection, asset_id, tenant_id=tenant_filter(user))
    if config is None:
        raise HTTPException(status_code=404, detail="Ativo operacional não encontrado.")
    return config


@api.put("/operations/assets/{asset_id}/economic-config")
def put_operations_asset_economic_config(asset_id: str, payload: AssetEconomicConfigIn, request: Request) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_role(user, ADMIN_ROLES)
        effective_from = read_model_parse_datetime(payload.effective_from) if payload.effective_from else None
        try:
            config = upsert_asset_economic_config(
                connection,
                asset_id,
                tenant_id=tenant_filter(user),
                method=payload.method,
                downtime_cost_per_hour=payload.downtime_cost_per_hour,
                production_rate_per_hour=payload.production_rate_per_hour,
                contribution_value_per_unit=payload.contribution_value_per_unit,
                currency=payload.currency,
                effective_from=effective_from,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if config is None:
        raise HTTPException(status_code=404, detail="Ativo operacional não encontrado.")
    return config


@api.post("/operations/alert-decisions/evaluate")
def post_operations_alert_decisions_evaluate(
    request: Request,
    period: str = "day",
    start: Optional[str] = None,
    end: Optional[str] = None,
    cliente_id: Optional[str] = None,
    site_id: Optional[str] = None,
    area_context_id: Optional[str] = None,
    process_id: Optional[str] = None,
    asset_id: Optional[str] = None,
    camera_id: Optional[str] = None,
    event_family: Optional[str] = None,
    tipo: Optional[str] = None,
    workflow_status: Optional[str] = None,
) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_camera_access(connection, user, camera_id)
        filters = _read_model_filters(
            user,
            cliente_id=cliente_id,
            site_id=site_id,
            area_context_id=area_context_id,
            process_id=process_id,
            asset_id=asset_id,
            camera_id=camera_id,
            event_family=event_family,
            tipo=tipo,
            workflow_status=workflow_status,
            start=start,
            end=end,
            period=period,
        )
        try:
            payload = evaluate_alert_decisions(connection, filters)
            payload["delivery_ids"] = enqueue_alert_decisions_with_connection(connection, payload.get("decisions") or [])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return payload


@api.get("/operations/alert-decisions")
def get_operations_alert_decisions(
    request: Request,
    camera_id: Optional[str] = None,
    asset_id: Optional[str] = None,
    decision: Optional[str] = None,
    severity: Optional[str] = None,
    alert_type: Optional[str] = None,
    active: Optional[bool] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_camera_access(connection, user, camera_id)
        records = list_alert_decisions(
            connection,
            AlertDecisionFilters(
                tenant_id=tenant_filter(user),
                camera_id=camera_id,
                asset_id=asset_id,
                decision=decision,
                severity=severity,
                alert_type=alert_type,
                active=active,
                start=start,
                end=end,
            ),
        )
    return {"decisions": records, "total": len(records)}


@api.get("/operations/alert-decisions/{decision_id}")
def get_operations_alert_decision_detail(decision_id: str, request: Request) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        record = get_alert_decision(connection, decision_id, tenant_id=tenant_filter(user))
    if record is None:
        raise HTTPException(status_code=404, detail="Decisão de alerta não encontrada.")
    return record


@api.get("/operations/briefing")
def get_operations_briefing(
    request: Request,
    period: str = "day",
    start: Optional[str] = None,
    end: Optional[str] = None,
    cliente_id: Optional[str] = None,
    site_id: Optional[str] = None,
    area_context_id: Optional[str] = None,
    process_id: Optional[str] = None,
    asset_id: Optional[str] = None,
    camera_id: Optional[str] = None,
    event_family: Optional[str] = None,
    tipo: Optional[str] = None,
    workflow_status: Optional[str] = None,
) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_camera_access(connection, user, camera_id)
        filters = _read_model_filters(
            user,
            cliente_id=cliente_id,
            site_id=site_id,
            area_context_id=area_context_id,
            process_id=process_id,
            asset_id=asset_id,
            camera_id=camera_id,
            event_family=event_family,
            tipo=tipo,
            workflow_status=workflow_status,
            start=start,
            end=end,
            period=period,
        )
        try:
            return operational_shift_briefing(connection, filters)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@api.get("/operations/video-contexts")
def get_operations_video_contexts(
    request: Request,
    period: str = "day",
    start: Optional[str] = None,
    end: Optional[str] = None,
    cliente_id: Optional[str] = None,
    site_id: Optional[str] = None,
    area_context_id: Optional[str] = None,
    process_id: Optional[str] = None,
    asset_id: Optional[str] = None,
    camera_id: Optional[str] = None,
    event_family: Optional[str] = None,
    tipo: Optional[str] = None,
    workflow_status: Optional[str] = None,
    trigger_type: Optional[str] = None,
    before_seconds: int = 300,
    after_seconds: int = 300,
) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_camera_access(connection, user, camera_id)
        filters = _read_model_filters(
            user,
            cliente_id=cliente_id,
            site_id=site_id,
            area_context_id=area_context_id,
            process_id=process_id,
            asset_id=asset_id,
            camera_id=camera_id,
            event_family=event_family,
            tipo=tipo,
            workflow_status=workflow_status,
            start=start,
            end=end,
            period=period,
        )
        try:
            return read_model_video_contexts(
                connection,
                filters,
                trigger_type=trigger_type,
                before_seconds=before_seconds,
                after_seconds=after_seconds,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@api.get("/operations/video-contexts/{context_id}")
def get_operations_video_context_detail(
    context_id: str,
    request: Request,
    period: str = "day",
    start: Optional[str] = None,
    end: Optional[str] = None,
    cliente_id: Optional[str] = None,
    site_id: Optional[str] = None,
    area_context_id: Optional[str] = None,
    process_id: Optional[str] = None,
    asset_id: Optional[str] = None,
    camera_id: Optional[str] = None,
    event_family: Optional[str] = None,
    tipo: Optional[str] = None,
    workflow_status: Optional[str] = None,
    before_seconds: int = 300,
    after_seconds: int = 300,
) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_camera_access(connection, user, camera_id)
        if start or end:
            filters = _read_model_filters(
                user,
                cliente_id=cliente_id,
                site_id=site_id,
                area_context_id=area_context_id,
                process_id=process_id,
                asset_id=asset_id,
                camera_id=camera_id,
                event_family=event_family,
                tipo=tipo,
                workflow_status=workflow_status,
                start=start,
                end=end,
                period=period,
            )
        else:
            filters = ReadModelFilters(
                cliente_id=tenant_filter(user) or cliente_id,
                site_id=site_id,
                area_context_id=area_context_id,
                process_id=process_id,
                asset_id=asset_id,
                camera_id=camera_id,
                event_family=event_family,
                tipo=tipo,
                workflow_status=workflow_status,
            )
        try:
            context = read_model_video_context_by_id(
                connection,
                filters,
                context_id=context_id,
                before_seconds=before_seconds,
                after_seconds=after_seconds,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if context is None:
        raise HTTPException(status_code=404, detail="Contexto de vídeo não encontrado.")
    return context


@api.post("/operations/video-understanding/{context_id}")
def post_operations_video_understanding(
    context_id: str,
    request: Request,
    cliente_id: Optional[str] = None,
    site_id: Optional[str] = None,
    area_context_id: Optional[str] = None,
    process_id: Optional[str] = None,
    asset_id: Optional[str] = None,
    camera_id: Optional[str] = None,
) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_camera_access(connection, user, camera_id)
        filters = ReadModelFilters(
            cliente_id=tenant_filter(user) or cliente_id,
            site_id=site_id,
            area_context_id=area_context_id,
            process_id=process_id,
            asset_id=asset_id,
            camera_id=camera_id,
        )
        try:
            return VideoUnderstandingService().analyze_context(connection, filters, context_id)
        except VideoUnderstandingError as exc:
            status_code = 404 if exc.code == "VIDEO_CONTEXT_NOT_FOUND" else 503 if exc.code == "VIDEO_UNDERSTANDING_PROVIDER_NOT_CONFIGURED" else 502
            raise HTTPException(status_code=status_code, detail={"code": exc.code, "message": exc.message}) from exc


@api.get("/operations/video-understandings")
def get_operations_video_understandings(
    request: Request,
    context_id: Optional[str] = None,
    camera_id: Optional[str] = None,
    asset_id: Optional[str] = None,
    status: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_camera_access(connection, user, camera_id)
        records = list_validated_understandings(
            connection,
            UnderstandingFilters(
                tenant_id=tenant_filter(user),
                context_id=context_id,
                camera_id=camera_id,
                asset_id=asset_id,
                status=status,
                provider=provider,
                model=model,
                start=start,
                end=end,
            ),
        )
    return {"understandings": records, "total": len(records)}


@api.get("/operations/video-understandings/{understanding_id}")
def get_operations_video_understanding_detail(understanding_id: str, request: Request) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        record = get_validated_understanding(connection, understanding_id, tenant_id=tenant_filter(user))
    if record is None:
        raise HTTPException(status_code=404, detail="Video Understanding não encontrado.")
    return record


@api.get("/analytics/summary")
def get_analytics_summary(
    request: Request,
    machine_id: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    aggregation: str = "hour",
    camera_id: Optional[str] = None,
    event_family: Optional[str] = None,
) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        require_camera_access(connection, require_user(request, connection), camera_id)
        start_dt, end_dt = current_period_range(aggregation)
        if start:
            start_dt = parse_dt(start)
        if end:
            end_dt = parse_dt(end)
        if machine_id:
            return aggregate_period(connection, machine_id=machine_id, start=start_dt, end=end_dt, aggregation=aggregation, camera_id=camera_id, event_family=event_family)
        return compute_summary(connection, machine_id=None, start=start_dt, end=end_dt, camera_id=camera_id, event_family=event_family)


@api.get("/analytics/timeline")
def get_analytics_timeline(
    request: Request,
    machine_id: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    camera_id: Optional[str] = None,
    event_family: Optional[str] = None,
) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        require_camera_access(connection, require_user(request, connection), camera_id)
        start_dt = parse_dt(start) if start else current_period_range("day")[0]
        end_dt = parse_dt(end) if end else current_period_range("day")[1]
        return timeline(connection, machine_id=machine_id, start=start_dt, end=end_dt, camera_id=camera_id, event_family=event_family)


@api.get("/analytics/insights")
def get_analytics_insights(
    request: Request,
    machine_id: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    camera_id: Optional[str] = None,
) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        require_camera_access(connection, require_user(request, connection), camera_id)
        start_dt = parse_dt(start) if start else current_period_range("day")[0]
        end_dt = parse_dt(end) if end else current_period_range("day")[1]
        insights = generate_insights(connection, machine_id=machine_id, start=start_dt, end=end_dt, camera_id=camera_id)
        return {"insights": insights}


@api.get("/analytics/data-quality")
def get_analytics_data_quality(
    request: Request,
    machine_id: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    camera_id: Optional[str] = None,
) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        require_camera_access(connection, require_user(request, connection), camera_id)
        start_dt = parse_dt(start) if start else current_period_range("day")[0]
        end_dt = parse_dt(end) if end else current_period_range("day")[1]
        return data_quality(connection, machine_id=machine_id, start=start_dt, end=end_dt, camera_id=camera_id)


@api.get("/operations")
def get_operations(
    request: Request,
    cliente_id: Optional[str] = None,
    unidade_id: Optional[str] = None,
    camera_id: Optional[str] = None,
    machine_id: Optional[str] = None,
    cause: Optional[str] = None,
) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        effective_cliente = tenant_filter(user) or cliente_id
        monitors = []
        rows = connection.execute("SELECT * FROM machine_monitors ORDER BY nome").fetchall()
        for row in rows:
            monitor = dict(row)
            if effective_cliente and monitor["client_id"] != effective_cliente:
                continue
            if unidade_id and monitor["unit_id"] != unidade_id:
                continue
            if camera_id and monitor["camera_id"] != camera_id:
                continue
            if machine_id and monitor["id"] != machine_id:
                continue
            monitor_public = obter_machine_monitor(connection, monitor["id"])
            events = listar_eventos_filtrados(connection, camera_id=monitor["camera_id"], tipo="machine_stoppage")
            events = [event for event in events if event.get("machine_monitor_id") == monitor["id"]]
            if cause:
                events = [event for event in events if event.get("cause_category") == cause]
            total = sum(float(event.get("duracao") or 0) for event in events)
            monitors.append({
                "monitor": monitor_public,
                "paradas": len(events),
                "tempo_total_parado": total,
                "duracao_media": total / len(events) if events else 0,
                "maior_parada": max([float(event.get("duracao") or 0) for event in events], default=0),
                "operador_ausente_percentual": round(100 * len([e for e in events if not e.get("operator_present_start")]) / len(events), 2) if events else 0,
                "ultimas_ocorrencias": events[:10],
            })
    return {"machines": monitors}


@api.get("/alert-recipients")
def get_alert_recipients(request: Request) -> list[dict[str, Any]]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        recipients = listar_alert_recipients(connection)
        tenant = tenant_filter(user)
        if not tenant:
            return recipients
        cameras = {row["id"] for row in listar_por_cliente(connection, "cameras", tenant)}
        return [r for r in recipients if r.get("cliente_id") == tenant or (not r.get("cliente_id") and (not r.get("camera_id") or r.get("camera_id") in cameras))]


@api.post("/alert-recipients")
def post_alert_recipient(payload: AlertRecipientIn, request: Request) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        require_role(user, ADMIN_ROLES)
        cliente_id = effective_cliente_id(user, payload.cliente_id)
        if cliente_id is None and payload.camera_id:
            camera = obter_camera(connection, payload.camera_id)
            cliente_id = camera.get("cliente_id") if camera else None
        if tenant_filter(user):
            require_same_tenant(user, cliente_id)
        recipient_id = criar_alert_recipient(
            connection,
            payload.nome,
            payload.email,
            payload.ativo,
            payload.camera_id,
            payload.area_id,
            payload.severidade_minima,
            cliente_id,
            payload.event_types,
        )
        registrar_audit_log(
            connection,
            action="config.alert_recipient.create",
            actor=user,
            entity_type="alert_recipient",
            entity_id=recipient_id,
            tenant_id=cliente_id,
            metadata={"camera_id": payload.camera_id, "area_id": payload.area_id},
        )
        return next(recipient for recipient in listar_alert_recipients(connection) if recipient["id"] == recipient_id)


@api.patch("/alert-recipients/{recipient_id}")
def patch_alert_recipient(recipient_id: str, payload: AlertRecipientPatchIn, request: Request) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        existing = obter_alert_recipient(connection, recipient_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Responsavel nao encontrado.")
        require_same_tenant(user, existing.get("cliente_id"))
        recipient = atualizar_alert_recipient(
            connection,
            recipient_id,
            nome=payload.nome,
            email=payload.email,
            ativo=payload.ativo,
            camera_id=payload.camera_id,
            area_id=payload.area_id,
            severidade_minima=payload.severidade_minima,
            event_types=payload.event_types,
        )
        registrar_audit_log(
            connection,
            action="config.alert_recipient.update",
            actor=user,
            entity_type="alert_recipient",
            entity_id=recipient_id,
            tenant_id=existing.get("cliente_id"),
            metadata={"camera_id": payload.camera_id, "area_id": payload.area_id},
        )
    if recipient is None:
        raise HTTPException(status_code=404, detail="Responsavel nao encontrado.")
    return recipient


@api.delete("/alert-recipients/{recipient_id}")
def delete_alert_recipient(recipient_id: str, request: Request) -> dict[str, object]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        existing = obter_alert_recipient(connection, recipient_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Responsavel nao encontrado.")
        require_same_tenant(user, existing.get("cliente_id"))
        deleted = excluir_alert_recipient(connection, recipient_id)
        if deleted:
            registrar_audit_log(
                connection,
                action="config.alert_recipient.delete",
                actor=user,
                entity_type="alert_recipient",
                entity_id=recipient_id,
                tenant_id=existing.get("cliente_id"),
            )
    if not deleted:
        raise HTTPException(status_code=404, detail="Responsavel nao encontrado.")
    return {"id": recipient_id, "deleted": True}


@api.post("/alert-recipients/{recipient_id}/test")
def post_alert_recipient_test(recipient_id: str, request: Request) -> dict[str, object]:
    email_config = email_configuration_status()
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        recipient = obter_alert_recipient(connection, recipient_id)
        if recipient is None:
            raise HTTPException(status_code=404, detail="Responsavel nao encontrado.")
        require_same_tenant(user, recipient.get("cliente_id"))
    delivery_id = send_test_alert(recipient_id)
    if delivery_id is None:
        raise HTTPException(status_code=404, detail="Responsavel nao encontrado.")
    return {"delivery_id": delivery_id, "status": "pending", "email_configuration": email_config}


@api.get("/alert-deliveries")
def get_alert_deliveries(
    request: Request,
    evento_id: Optional[str] = None,
    recipient_id: Optional[str] = None,
    status: Optional[str] = None,
) -> list[dict[str, Any]]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        deliveries = listar_alert_deliveries(connection, evento_id, recipient_id, status)
        if not tenant_filter(user):
            return deliveries
        allowed_events = {event["id"] for event in listar_por_cliente(connection, "eventos", tenant_filter(user))}
        allowed_recipients = {recipient["id"] for recipient in get_alert_recipients(request)}
        return [d for d in deliveries if d.get("evento_id") in allowed_events or d.get("recipient_id") in allowed_recipients]


@api.get("/alert-deliveries/{delivery_id}")
def get_alert_delivery(delivery_id: str, request: Request) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        return require_alert_delivery_access(connection, require_user(request, connection), delivery_id)


@api.post("/alert-deliveries/{delivery_id}/retry")
def post_alert_delivery_retry(delivery_id: str, request: Request) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        require_alert_delivery_access(connection, require_user(request, connection), delivery_id)
    delivery = retry_delivery(delivery_id)
    if delivery is None:
        raise HTTPException(status_code=404, detail="Entrega nao encontrada.")
    return delivery


@api.get("/events/stream")
def get_events_stream(request: Request) -> StreamingResponse:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        scoped_tenant = tenant_filter(user)

    return StreamingResponse(
        stream_events(scoped_tenant),
        media_type="text/event-stream",
    )


@api.get("/cameras/estado")
def get_camera_estado(request: Request) -> list[dict[str, Any]]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        cameras = listar_por_cliente(connection, "cameras", tenant_filter(user))
        streams = {stream.get("camera_id"): stream for stream in live_streams.statuses()}
        cameras = [_camera_with_runtime_status(camera, streams.get(camera.get("id"))) for camera in cameras]
        if user["role"] in {"operador", "visualizador"}:
            for camera in cameras:
                camera.pop("rtsp_host", None)
                camera.pop("rtsp_port", None)
                camera.pop("rtsp_path", None)
                camera.pop("config_ref", None)
        for camera in cameras:
            if "ativa" in camera:
                camera["ativa"] = bool(camera["ativa"])
        return cameras


class ReportSchedulePayload(BaseModel):
    enabled: bool = True
    send_time: str = "08:00"
    timezone: str = "America/Sao_Paulo"
    channel: str = "email"
    email: Optional[str] = None
    recipient_name: Optional[str] = None
    whatsapp_number: Optional[str] = None
    tenant_id: Optional[str] = None


def _report_tenant(user: dict[str, Any], requested_tenant: str | None = None) -> str:
    scoped_tenant = tenant_filter(user)

    if scoped_tenant:
        if requested_tenant and requested_tenant != scoped_tenant:
            raise HTTPException(
                status_code=403,
                detail="Não é permitido configurar relatório de outra empresa.",
            )
        return str(scoped_tenant)

    if requested_tenant:
        return str(requested_tenant)

    raise HTTPException(
        status_code=400,
        detail="Empresa não informada para configuração do relatório.",
    )


@api.get("/reports/tenants")
def get_report_tenants(request: Request) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        scoped_tenant = tenant_filter(user)

        if scoped_tenant:
            rows = connection.execute(
                """
                SELECT id, nome
                FROM clientes
                WHERE id = ?
                """,
                (scoped_tenant,),
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT id, nome
                FROM clientes
                ORDER BY nome
                """
            ).fetchall()

        return {
            "tenants": [
                {
                    "id": str(row["id"]),
                    "nome": str(row["nome"] or "Empresa"),
                }
                for row in rows
            ]
        }


@api.get("/reports/schedule")
def get_reports_schedule(
    request: Request,
    tenant_id: Optional[str] = None,
) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        resolved_tenant = _report_tenant(user, tenant_id)
        schedule = get_report_schedule(connection, resolved_tenant)

        return {
            "tenant_id": resolved_tenant,
            "schedule": schedule,
            "email_configuration": email_configuration_status(),
        }


@api.put("/reports/schedule")
def put_reports_schedule(
    payload: ReportSchedulePayload,
    request: Request,
) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        resolved_tenant = _report_tenant(user, payload.tenant_id)

        try:
            schedule = upsert_report_schedule(
                connection,
                tenant_id=resolved_tenant,
                enabled=payload.enabled,
                send_time=payload.send_time,
                timezone_name=payload.timezone,
                channel=payload.channel,
                email=payload.email,
                recipient_name=payload.recipient_name,
                whatsapp_number=payload.whatsapp_number,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return {
            "status": "ok",
            "schedule": schedule,
        }


@api.post("/reports/send-now")
def post_reports_send_now(
    request: Request,
    tenant_id: Optional[str] = None,
) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        resolved_tenant = _report_tenant(user, tenant_id)

        schedule = get_report_schedule(connection, resolved_tenant)
        if not schedule:
            raise HTTPException(
                status_code=404,
                detail="Configure o relatório antes de testar o envio.",
            )

        channel = str(schedule.get("channel") or "email")
        if channel not in {"email", "both"}:
            raise HTTPException(
                status_code=503,
                detail="WhatsApp ainda não possui provedor configurado.",
            )

        email = schedule.get("email")
        if not email:
            raise HTTPException(
                status_code=400,
                detail="Nenhum email configurado.",
            )

        timezone_name = str(
            schedule.get("timezone") or "America/Sao_Paulo"
        )

        from zoneinfo import ZoneInfo

        now_local = datetime.now(timezone.utc).astimezone(
            ZoneInfo(timezone_name)
        )

        report = build_report_for_tenant(
            connection,
            tenant_id=resolved_tenant,
            end_at=now_local,
        )

        try:
            send_report_email(
                report,
                str(email),
                schedule.get("recipient_name"),
            )
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail=f"Falha ao enviar relatório: {exc}",
            ) from exc

        return {
            "status": "sent",
            "tenant_id": resolved_tenant,
            "channel": "email",
            "destination": email,
            "report": report,
        }


@api.get("/reports/preview")
def get_reports_preview(
    request: Request,
    tenant_id: Optional[str] = None,
) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        resolved_tenant = _report_tenant(user, tenant_id)

        schedule = get_report_schedule(connection, resolved_tenant)
        timezone_name = str(
            (schedule or {}).get("timezone")
            or "America/Sao_Paulo"
        )

        from zoneinfo import ZoneInfo

        now_local = datetime.now(timezone.utc).astimezone(
            ZoneInfo(timezone_name)
        )

        return build_report_for_tenant(
            connection,
            tenant_id=resolved_tenant,
            end_at=now_local,
        )


@api.get("/relatorios/diario")
def get_relatorio_diario(
    request: Request,
    data: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> dict[str, Any]:
    with connect() as connection:
        init_db(connection)
        user = require_user(request, connection)
        resolved_tenant = _report_tenant(user, tenant_id)

        filters = ReadModelFilters(
            cliente_id=resolved_tenant,
            start=data,
            end=data,
            period="day",
        )

        try:
            return read_model_daily_report(connection, filters)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


api.add_api_route(
    "/{internal_path:path}",
    serve_internal_not_found,
    methods=["GET"],
    include_in_schema=False,
    name="internal_not_found",
)
