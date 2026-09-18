from __future__ import annotations
from pathlib import Path

import hashlib
import json
import logging
import os
import uuid
from urllib.parse import quote
from typing import Any, Optional

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.config import ROOT
from app.auth import (
    ADMIN_ROLES,
    authenticate,
    create_session,
    create_user,
    delete_session,
    get_request_user,
    users_exist,
)
from app.camera_rtsp import build_rtsp_url
from app.security import decrypt_secret, encrypt_secret
from cloud.database import connect, init_cloud_db, is_postgres_url
from cloud.security import hash_edge_secret, verify_edge_secret
from shared.schemas import now_iso

LOGGER = logging.getLogger(__name__)

api = FastAPI(title="Campex Cloud")
FRONTEND_DIR = ROOT / "frontend"
CLOUD_FRAME_DIR = ROOT / "data" / "cloud" / "latest_frames"
MAX_LATEST_FRAME_BYTES = 2 * 1024 * 1024
CLOUD_EVENT_EVIDENCE_DIR = ROOT / "data" / "cloud" / "event_evidence"
MAX_EVENT_EVIDENCE_BYTES = 5 * 1024 * 1024

if FRONTEND_DIR.exists():
    api.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


class LoginIn(BaseModel):
    email: str
    senha: str


class CloudClienteIn(BaseModel):
    nome: str = Field(min_length=1)
    documento: Optional[str] = None
    status: str = "ativo"


class CloudUnidadeIn(BaseModel):
    cliente_id: Optional[str] = None
    nome: str = Field(min_length=1)
    localizacao: Optional[str] = None
    timezone: str = "America/Sao_Paulo"


class CloudUserIn(BaseModel):
    cliente_id: Optional[str] = None
    nome: Optional[str] = None
    email: str = Field(min_length=3)
    senha: str = Field(min_length=8)
    role: str = "visualizador"


class CloudSignupIn(BaseModel):
    nome: str = Field(min_length=1)
    email: str = Field(min_length=3)
    senha: str = Field(min_length=8)
    empresa_nome: str = Field(min_length=1)


class EdgeDeviceIn(BaseModel):
    id: str
    tenant_id: str
    cliente_id: str
    unidade_id: str
    nome: str = "Edge Device"
    secret: str = Field(min_length=12)


class EdgeEventIn(BaseModel):
    event_uuid: str
    tenant_id: str
    cliente_id: str
    unidade_id: str
    camera_id: str
    tipo: str
    inicio: Optional[str] = None
    fim: Optional[str] = None
    duracao: Optional[float] = None
    operador_presente: Optional[bool] = None
    confianca: Optional[float] = None
    severidade: Optional[str] = None
    status: Optional[str] = None
    midia_path: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


class ReportDeliveryIn(BaseModel):
    delivery_id: str = Field(min_length=8)
    cliente_id: str
    recipient: str
    subject: str
    text_body: str
    html_body: str


def _cookie_secure() -> bool:
    return os.getenv("CAMPEX_COOKIE_SECURE", "").strip().lower() in {"1", "true", "yes", "on"}


def _bootstrap_cloud_admin() -> None:
    email = os.getenv("CAMPEX_CLOUD_ADMIN_EMAIL", "").strip().lower()
    password = os.getenv("CAMPEX_CLOUD_ADMIN_PASSWORD", "")
    if not email or not password:
        LOGGER.warning("Cloud sem credenciais bootstrap configuradas.")
        return
    if len(password) < 8:
        raise RuntimeError("CAMPEX_CLOUD_ADMIN_PASSWORD deve ter pelo menos 8 caracteres.")

    with connect() as db:
        init_cloud_db(db)
        if users_exist(db):
            return
        create_user(
            db,
            email=email,
            password=password,
            role="admin_campex",
            nome="Administrador Campex",
        )
        LOGGER.info("Administrador inicial do Campex Cloud criado.")


@api.on_event("startup")
def startup() -> None:
    init_cloud_db()
    _bootstrap_cloud_admin()


@api.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "database": "postgresql" if is_postgres_url() else "sqlite-dev"}


@api.get("/")
def root() -> RedirectResponse:
    return RedirectResponse(url="/operations-view", status_code=307)


INTERNAL_ROUTES = {
    "/dashboard": "workspace.html",
    "/overview": "workspace.html",
    "/operations-dashboard": "workspace.html",
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
    "/edges": "workspace.html",
    "/live-grid": "live-grid.html",
    "/live-view": "live-view.html",
    "/people-zones": "people-zones.html",
    "/local-diagnostics-view": "local-diagnostics.html",
    "/settings": "workspace.html",
    "/settings/cameras": "index.html",
    "/settings/notifications": "workspace.html",
    "/settings/account": "workspace.html",
    "/help": "workspace.html",
}


def _cloud_user(request: Request) -> dict[str, Any] | None:
    with connect() as db:
        init_cloud_db(db)
        return get_request_user(request, db)


def _require_cloud_user(request: Request) -> dict[str, Any]:
    user = _cloud_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Login necessario.")
    return user


def _login_redirect(request: Request) -> RedirectResponse:
    next_path = request.url.path
    if request.url.query:
        next_path = f"{next_path}?{request.url.query}"
    return RedirectResponse(
        url=f"/login?next={quote(next_path, safe='')}",
        status_code=303,
    )


@api.get("/login", include_in_schema=False)
def cloud_login_page() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "login.html")


@api.get("/login/", include_in_schema=False)
def cloud_login_page_slash() -> FileResponse:
    return cloud_login_page()


async def serve_internal(request: Request):
    if _cloud_user(request) is None:
        return _login_redirect(request)
    file_name = INTERNAL_ROUTES.get(request.url.path)
    if file_name is None:
        raise HTTPException(status_code=404, detail="Pagina nao encontrada.")
    return FileResponse(FRONTEND_DIR / file_name)


for internal_route in INTERNAL_ROUTES:
    api.add_api_route(
        internal_route,
        serve_internal,
        methods=["GET"],
        include_in_schema=False,
    )


@api.post("/auth/login")
def cloud_post_login(payload: LoginIn, response: Response) -> dict[str, Any]:
    with connect() as db:
        init_cloud_db(db)
        user = authenticate(db, payload.email, payload.senha)
        if user is None:
            raise HTTPException(status_code=401, detail="E-mail ou senha invalidos.")
        token = create_session(db, user["id"])

    response.set_cookie(
        "campex_session",
        token,
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(),
        max_age=60 * 60 * 12,
    )
    return {"user": user, "next": "/operations-view?view=home"}


@api.post("/auth/logout")
def cloud_post_logout(request: Request, response: Response) -> dict[str, bool]:
    token = request.cookies.get("campex_session")
    if token:
        with connect() as db:
            init_cloud_db(db)
            delete_session(db, token)
    response.delete_cookie("campex_session")
    return {"ok": True}


@api.get("/first-run/status")
def cloud_first_run_status() -> dict[str, Any]:
    with connect() as db:
        init_cloud_db(db)
        available = not users_exist(db)
    return {
        "available": available,
        "locked": not available,
        "message": (
            "First Run disponível."
            if available
            else "First Run já concluído."
        ),
    }


@api.post("/first-run/complete")
def cloud_first_run_complete(payload: dict[str, Any], response: Response) -> dict[str, Any]:
    with connect() as db:
        init_cloud_db(db)
        if users_exist(db):
            raise HTTPException(status_code=409, detail="First Run já concluído.")
        nome = str(payload.get("admin_nome") or payload.get("nome") or "Administrador").strip()
        email = str(payload.get("admin_email") or payload.get("email") or "").strip().lower()
        senha = str(payload.get("admin_senha") or payload.get("senha") or "")
        empresa_nome = str(payload.get("empresa_nome") or payload.get("cliente_nome") or "Organização principal").strip()
        unidade_nome = str(payload.get("unidade_nome") or "Unidade principal").strip()
        if not email or "@" not in email:
            raise HTTPException(status_code=400, detail="E-mail válido é obrigatório.")
        if len(senha) < 8:
            raise HTTPException(status_code=400, detail="A senha deve ter pelo menos 8 caracteres.")
        cliente_id = _cloud_new_id("cli")
        unidade_id = _cloud_new_id("uni")
        db.execute(
            "INSERT INTO clientes (id, nome, documento, status) VALUES (?, ?, NULL, 'ativo')",
            (cliente_id, empresa_nome),
        )
        db.execute(
            "INSERT INTO unidades (id, cliente_id, nome, localizacao, timezone) VALUES (?, ?, ?, NULL, 'America/Sao_Paulo')",
            (unidade_id, cliente_id, unidade_nome),
        )
        user_id = create_user(db, email=email, password=senha, role="admin_cliente", cliente_id=cliente_id, nome=nome)
        token = create_session(db, user_id)
        user = authenticate(db, email, senha)
    response.set_cookie(
        "campex_session",
        token,
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(),
        max_age=60 * 60 * 12,
    )
    return {"cliente_id": cliente_id, "unidade_id": unidade_id, "user": user, "next": "/operations-view?view=home"}


@api.post("/auth/signup")
def cloud_signup(payload: CloudSignupIn, response: Response) -> dict[str, Any]:
    if os.getenv("CAMPEX_ENABLE_PUBLIC_SIGNUP", "").strip().lower() not in {"1", "true", "yes", "on"}:
        raise HTTPException(status_code=403, detail="Cadastro público desativado. Solicite uma demonstração com a Campex.")
    email = payload.email.strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=400, detail="E-mail válido é obrigatório.")
    with connect() as db:
        init_cloud_db(db)
        if db.fetchone("SELECT id FROM users WHERE email = ?", (email,)):
            raise HTTPException(status_code=409, detail="Já existe usuário com este e-mail.")
        cliente_id = _cloud_new_id("cli")
        unidade_id = _cloud_new_id("uni")
        db.execute("INSERT INTO clientes (id, nome, documento, status) VALUES (?, ?, NULL, 'ativo')", (cliente_id, payload.empresa_nome.strip()))
        db.execute("INSERT INTO unidades (id, cliente_id, nome, localizacao, timezone) VALUES (?, ?, 'Unidade principal', NULL, 'America/Sao_Paulo')", (unidade_id, cliente_id))
        user_id = create_user(db, email=email, password=payload.senha, role="admin_cliente", cliente_id=cliente_id, nome=payload.nome.strip())
        token = create_session(db, user_id)
        user = authenticate(db, email, payload.senha)
    response.set_cookie("campex_session", token, httponly=True, samesite="lax", secure=_cookie_secure(), max_age=60 * 60 * 12)
    return {"cliente_id": cliente_id, "unidade_id": unidade_id, "user": user, "next": "/operations-view?view=home"}


@api.get("/auth/oauth/google/start")
def cloud_google_oauth_start(next: str = "/operations-view?view=home") -> RedirectResponse:
    return RedirectResponse(
        url=f"/login?next={quote(next, safe='')}&oauth_error=google_unavailable",
        status_code=303,
    )


@api.get("/auth/me")
def cloud_auth_me(request: Request) -> dict[str, Any]:
    return {"user": _require_cloud_user(request)}


@api.get("/auth/status")
def cloud_auth_status(request: Request) -> dict[str, Any]:
    user = _cloud_user(request)
    return {
        "authenticated": user is not None,
        "bootstrap": False,
        "user": user,
        "public_signup": os.getenv("CAMPEX_ENABLE_PUBLIC_SIGNUP", "").strip().lower()
        in {"1", "true", "yes", "on"},
    }



def _cloud_new_id(prefix: str) -> str:
    import uuid
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _tenant_for_user(user: dict[str, Any]) -> str | None:
    return None if user.get("role") == "admin_campex" else str(user.get("cliente_id") or "")


def _require_cloud_admin(user: dict[str, Any]) -> None:
    if user.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Permissao insuficiente.")


def _require_same_client(user: dict[str, Any], cliente_id: str, detail: str = "Cliente nao autorizado.") -> None:
    if user.get("role") != "admin_campex" and str(user.get("cliente_id") or "") != str(cliente_id or ""):
        raise HTTPException(status_code=403, detail=detail)


def _row_dict(row: dict[str, Any] | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def _json_list(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(str(value))
    except Exception:
        return []
    return parsed if isinstance(parsed, list) else []


def _current_client_id(user: dict[str, Any], requested: str | None = None) -> str:
    if user.get("role") == "admin_campex":
        cliente_id = str(requested or "").strip()
        if not cliente_id:
            raise HTTPException(status_code=400, detail="Informe o cliente.")
        return cliente_id
    cliente_id = str(user.get("cliente_id") or "").strip()
    if not cliente_id:
        raise HTTPException(status_code=403, detail="Usuario sem cliente vinculado.")
    return cliente_id


def _unit_for_user(db, user: dict[str, Any], unidade_id: str | None = None) -> dict[str, Any]:
    if unidade_id:
        row = db.fetchone("SELECT * FROM unidades WHERE id = ?", (unidade_id,))
    elif user.get("role") == "admin_campex":
        row = db.fetchone("SELECT * FROM unidades ORDER BY criado_em ASC LIMIT 1")
    else:
        row = db.fetchone(
            "SELECT * FROM unidades WHERE cliente_id = ? ORDER BY criado_em ASC LIMIT 1",
            (str(user.get("cliente_id") or ""),),
        )
    if not row:
        raise HTTPException(status_code=404, detail="Unidade nao encontrada.")
    _require_same_client(user, str(row["cliente_id"]), "Unidade pertence a outro cliente.")
    return row


def _camera_for_user(db, user: dict[str, Any], camera_id: str) -> dict[str, Any]:
    camera = db.fetchone("SELECT * FROM cloud_cameras WHERE id = ?", (camera_id,))
    if not camera:
        raise HTTPException(status_code=404, detail="Camera nao encontrada.")
    _require_same_client(user, str(camera["cliente_id"]), "Camera pertence a outro cliente.")
    return camera


def _latest_frame_path(camera_id: str) -> Path:
    safe_id = "".join(char for char in str(camera_id) if char.isalnum() or char in {"_", "-"})
    if not safe_id or safe_id != str(camera_id):
        raise HTTPException(status_code=400, detail="Identificador de câmera inválido.")
    return CLOUD_FRAME_DIR / f"{safe_id}.jpg"


def _event_evidence_path(event_uuid: str) -> Path:
    safe_id = "".join(char for char in str(event_uuid) if char.isalnum() or char in {"_", "-"})
    if not safe_id or safe_id != str(event_uuid):
        raise HTTPException(status_code=400, detail="Identificador de evento inválido.")
    return CLOUD_EVENT_EVIDENCE_DIR / f"{safe_id}.jpg"


def _edge_device_from_headers(db, edge_id: str | None, edge_secret: str | None) -> dict[str, Any]:
    if not edge_id or not edge_secret:
        raise HTTPException(status_code=401, detail="Credenciais do Edge ausentes.")
    device = db.fetchone("SELECT * FROM edge_devices WHERE id = ?", (edge_id,))
    if not device or not verify_edge_secret(edge_secret, device["secret_hash"]):
        raise HTTPException(status_code=401, detail="Edge nao autorizado.")
    if device["status"] != "active" or device.get("revoked_at"):
        raise HTTPException(status_code=403, detail="Edge revogado ou inativo.")
    return device


def _area_public(row: dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    item["pontos"] = _json_list(item.pop("pontos_json", "[]"))
    item["ativa"] = bool(item.get("ativa"))
    return item


def _monitor_public(row: dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    item["machine_polygon"] = _json_list(item.pop("machine_polygon_json", "[]"))
    item["operator_polygon"] = _json_list(item.pop("operator_polygon_json", "[]"))
    item["operation_polygon"] = _json_list(item.pop("operation_polygon_json", None))
    item["ativo"] = bool(item.get("ativo"))
    return item


def _runtime_status_payload(row: dict[str, Any]) -> dict[str, Any] | None:
    raw = row.get("runtime_status_json")
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    received_at = payload.get("received_at")
    if received_at:
        try:
            from datetime import datetime, timezone

            parsed = datetime.fromisoformat(str(received_at).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            if (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() > 30:
                payload["stale"] = True
        except Exception:
            payload["stale"] = True
    return payload


@api.get("/clientes")
def cloud_get_clientes(request: Request) -> list[dict[str, Any]]:
    user = _require_cloud_user(request)

    with connect() as db:
        init_cloud_db(db)

        if user.get("role") == "admin_campex":
            rows = db.fetchall(
                "SELECT * FROM clientes ORDER BY nome"
            )
        else:
            cliente_id = user.get("cliente_id")
            if not cliente_id:
                return []
            rows = db.fetchall(
                "SELECT * FROM clientes WHERE id = ? ORDER BY nome",
                (cliente_id,),
            )

    return [dict(row) for row in rows]


@api.post("/clientes")
def cloud_post_cliente(
    payload: CloudClienteIn,
    request: Request,
) -> dict[str, Any]:
    user = _require_cloud_user(request)

    if user.get("role") != "admin_campex":
        raise HTTPException(
            status_code=403,
            detail="Somente admin Campex cria clientes.",
        )

    cliente_id = _cloud_new_id("cli")

    with connect() as db:
        init_cloud_db(db)
        db.execute(
            """
            INSERT INTO clientes (
                id,
                nome,
                documento,
                status
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                cliente_id,
                payload.nome.strip(),
                payload.documento,
                payload.status.strip() or "ativo",
            ),
        )
        db.commit()

        row = db.fetchone(
            "SELECT * FROM clientes WHERE id = ?",
            (cliente_id,),
        )

    return dict(row)


@api.patch("/clientes/{cliente_id}")
def cloud_patch_cliente(
    cliente_id: str,
    payload: dict[str, Any],
    request: Request,
) -> dict[str, Any]:
    user = _require_cloud_user(request)
    _require_cloud_admin(user)
    _require_same_client(user, cliente_id, "Empresa de outro cliente.")
    with connect() as db:
        init_cloud_db(db)
        current = db.fetchone("SELECT * FROM clientes WHERE id = ?", (cliente_id,))
        if not current:
            raise HTTPException(status_code=404, detail="Empresa nao encontrada.")
        nome = str(payload.get("nome") if payload.get("nome") is not None else current["nome"]).strip()
        documento = payload.get("documento") if payload.get("documento") is not None else current.get("documento")
        status_value = str(payload.get("status") if payload.get("status") is not None else current["status"]).strip()
        if not nome:
            raise HTTPException(status_code=400, detail="Nome da organizacao e obrigatorio.")
        db.execute(
            "UPDATE clientes SET nome = ?, documento = ?, status = ? WHERE id = ?",
            (nome, documento, status_value or "ativo", cliente_id),
        )
        db.commit()
        row = db.fetchone("SELECT * FROM clientes WHERE id = ?", (cliente_id,))
    return dict(row)


@api.get("/unidades")
def cloud_get_unidades(
    request: Request,
    cliente_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    user = _require_cloud_user(request)

    effective_cliente_id = cliente_id

    if user.get("role") != "admin_campex":
        effective_cliente_id = user.get("cliente_id")

    with connect() as db:
        init_cloud_db(db)

        if effective_cliente_id:
            rows = db.fetchall(
                """
                SELECT *
                FROM unidades
                WHERE cliente_id = ?
                ORDER BY nome
                """,
                (effective_cliente_id,),
            )
        elif user.get("role") == "admin_campex":
            rows = db.fetchall(
                "SELECT * FROM unidades ORDER BY nome"
            )
        else:
            rows = []

    return [dict(row) for row in rows]


@api.post("/unidades")
def cloud_post_unidade(
    payload: CloudUnidadeIn,
    request: Request,
) -> dict[str, Any]:
    user = _require_cloud_user(request)

    if user.get("role") not in ADMIN_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Permissao insuficiente.",
        )

    if user.get("role") == "admin_campex":
        cliente_id = (payload.cliente_id or "").strip()
        if not cliente_id:
            raise HTTPException(
                status_code=400,
                detail="Informe o cliente da unidade.",
            )
    else:
        cliente_id = str(user.get("cliente_id") or "").strip()
        if not cliente_id:
            raise HTTPException(
                status_code=403,
                detail="Usuario sem cliente vinculado.",
            )

    with connect() as db:
        init_cloud_db(db)

        cliente = db.fetchone(
            "SELECT id FROM clientes WHERE id = ?",
            (cliente_id,),
        )
        if not cliente:
            raise HTTPException(
                status_code=404,
                detail="Cliente nao encontrado.",
            )

        unidade_id = _cloud_new_id("uni")

        db.execute(
            """
            INSERT INTO unidades (
                id,
                cliente_id,
                nome,
                localizacao,
                timezone
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                unidade_id,
                cliente_id,
                payload.nome.strip(),
                payload.localizacao,
                payload.timezone,
            ),
        )
        db.commit()

        row = db.fetchone(
            "SELECT * FROM unidades WHERE id = ?",
            (unidade_id,),
        )

    return dict(row)


SETUP_CAPABILITIES = [
    {"id": "interruption", "label": "Paradas/Interrupções", "supported": True},
    {"id": "absence", "label": "Ausência", "supported": True},
    {"id": "wait", "label": "Espera", "supported": False},
    {"id": "flow", "label": "Movimentação/Fluxo", "supported": False},
]


def _cloud_setup_rows(db, table: str, user: dict[str, Any]) -> list[dict[str, Any]]:
    tenant = _tenant_for_user(user)
    if tenant:
        return db.fetchall(f"SELECT * FROM {table} WHERE cliente_id = ? ORDER BY criado_em DESC", (tenant,))
    return db.fetchall(f"SELECT * FROM {table} ORDER BY criado_em DESC")


def _cloud_cameras(db, user: dict[str, Any]) -> list[dict[str, Any]]:
    tenant = _tenant_for_user(user)
    if tenant:
        rows = db.fetchall("SELECT * FROM cloud_cameras WHERE cliente_id = ? ORDER BY nome", (tenant,))
    else:
        rows = db.fetchall("SELECT * FROM cloud_cameras ORDER BY nome")
    return [_camera_public(row) for row in rows]


def _camera_public(row: dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    item.pop("rtsp_username", None)
    item.pop("rtsp_password_encrypted", None)
    item["ativa"] = bool(item.get("ativa"))
    item["camera_id"] = item["id"]
    item["status"] = item.get("status") or "configured"
    item["online"] = item["status"] == "online"
    item["referencia_segura"] = item.get("secure_ref") or "RTSP armazenado no Edge"
    return item


def _cloud_asset_status(asset: dict[str, Any], cameras: list[dict[str, Any]], areas: list[dict[str, Any]], monitors: list[dict[str, Any]]) -> dict[str, Any]:
    camera_ids = [camera["id"] for camera in cameras if camera.get("asset_id") == asset["id"]]
    monitor_ids = [monitor["id"] for monitor in monitors if monitor.get("asset_id") == asset["id"] or monitor.get("camera_id") in camera_ids]
    missing = []
    if not camera_ids:
        missing.append("associar uma câmera")
    if not any(area.get("tipo") == "machine_region" and area.get("camera_id") in camera_ids and area.get("ativa") for area in areas):
        missing.append("desenhar região da máquina")
    if not any(area.get("tipo") in {"operator_zone", "workstation", "work_area"} and area.get("camera_id") in camera_ids and area.get("ativa") for area in areas):
        missing.append("desenhar zona do operador")
    if not any(monitor.get("id") in monitor_ids and monitor.get("ativo") for monitor in monitors):
        missing.append("ativar monitor do ativo")
    return {
        "asset_id": asset["id"],
        "asset_name": asset.get("nome"),
        "ready": not missing,
        "status": "Pronto para monitorar" if not missing else "Configuração incompleta",
        "missing": missing,
        "camera_ids": camera_ids,
        "monitor_ids": monitor_ids,
    }


@api.get("/setup/operation")
def cloud_setup_operation(request: Request) -> dict[str, Any]:
    user = _require_cloud_user(request)
    with connect() as db:
        init_cloud_db(db)
        clientes = cloud_get_clientes(request)
        unidades = cloud_get_unidades(request)
        areas = _cloud_setup_rows(db, "operational_areas", user)
        processes = _cloud_setup_rows(db, "operational_processes", user)
        assets = _cloud_setup_rows(db, "operational_assets", user)
        cameras = _cloud_cameras(db, user)
        tenant = _tenant_for_user(user)
        if tenant:
            zone_rows = db.fetchall("SELECT * FROM cloud_monitored_areas WHERE cliente_id = ? ORDER BY created_at DESC", (tenant,))
            monitor_rows = db.fetchall("SELECT * FROM cloud_machine_monitors WHERE client_id = ? ORDER BY created_at DESC", (tenant,))
        else:
            zone_rows = db.fetchall("SELECT * FROM cloud_monitored_areas ORDER BY created_at DESC")
            monitor_rows = db.fetchall("SELECT * FROM cloud_machine_monitors ORDER BY created_at DESC")
    monitored_areas = [_area_public(row) for row in zone_rows]
    monitors = [_monitor_public(row) for row in monitor_rows]
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
        "asset_status": [_cloud_asset_status(asset, cameras, monitored_areas, monitors) for asset in assets],
        "readiness": {
            "ready": bool(clientes and unidades and assets and cameras),
            "checks": [
                {"status": "PASS" if clientes else "FAIL", "label": "Empresa", "detail": f"{len(clientes)} empresa(s)"},
                {"status": "PASS" if unidades else "FAIL", "label": "Unidade", "detail": f"{len(unidades)} unidade(s)"},
                {"status": "PASS" if assets else "FAIL", "label": "Contexto operacional", "detail": f"áreas={len(areas)}, processos={len(processes)}, ativos={len(assets)}"},
                {"status": "PASS" if cameras else "FAIL", "label": "Câmera cadastrada", "detail": f"{len(cameras)} câmera(s)"},
            ],
            "summary": {"active_cameras": len([c for c in cameras if c.get("ativa")])},
        },
    }


@api.get("/setup/readiness")
def cloud_setup_readiness(request: Request) -> dict[str, Any]:
    return cloud_setup_operation(request)["readiness"]


@api.post("/setup/areas")
def cloud_setup_area(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    user = _require_cloud_user(request)
    _require_cloud_admin(user)
    with connect() as db:
        init_cloud_db(db)
        unidade = _unit_for_user(db, user, str(payload.get("unidade_id") or ""))
        area_id = _cloud_new_id("oparea")
        db.execute(
            "INSERT INTO operational_areas (id, cliente_id, unidade_id, nome, tipo) VALUES (?, ?, ?, ?, ?)",
            (area_id, unidade["cliente_id"], unidade["id"], str(payload.get("nome") or "").strip(), str(payload.get("tipo") or "area")),
        )
        db.commit()
        return dict(db.fetchone("SELECT * FROM operational_areas WHERE id = ?", (area_id,)))


@api.post("/setup/processes")
def cloud_setup_process(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    user = _require_cloud_user(request)
    _require_cloud_admin(user)
    with connect() as db:
        init_cloud_db(db)
        area = db.fetchone("SELECT * FROM operational_areas WHERE id = ?", (str(payload.get("area_id") or ""),))
        if not area:
            raise HTTPException(status_code=404, detail="Área não encontrada.")
        _require_same_client(user, str(area["cliente_id"]), "Área pertence a outro cliente.")
        process_id = _cloud_new_id("opproc")
        db.execute(
            "INSERT INTO operational_processes (id, cliente_id, unidade_id, area_id, nome, tipo) VALUES (?, ?, ?, ?, ?, ?)",
            (process_id, area["cliente_id"], area["unidade_id"], area["id"], str(payload.get("nome") or "").strip(), str(payload.get("tipo") or "processo")),
        )
        db.commit()
        return dict(db.fetchone("SELECT * FROM operational_processes WHERE id = ?", (process_id,)))


@api.post("/setup/assets")
def cloud_setup_asset(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    user = _require_cloud_user(request)
    _require_cloud_admin(user)
    with connect() as db:
        init_cloud_db(db)
        process = db.fetchone("SELECT * FROM operational_processes WHERE id = ?", (str(payload.get("process_id") or ""),))
        if not process:
            raise HTTPException(status_code=404, detail="Processo não encontrado.")
        _require_same_client(user, str(process["cliente_id"]), "Processo pertence a outro cliente.")
        asset_id = _cloud_new_id("asset")
        db.execute(
            "INSERT INTO operational_assets (id, cliente_id, unidade_id, area_id, process_id, nome, tipo) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (asset_id, process["cliente_id"], process["unidade_id"], process["area_id"], process["id"], str(payload.get("nome") or "").strip(), str(payload.get("tipo") or "ativo")),
        )
        db.commit()
        return dict(db.fetchone("SELECT * FROM operational_assets WHERE id = ?", (asset_id,)))


@api.post("/setup/cameras/{camera_id}/context")
def cloud_camera_context(camera_id: str, payload: dict[str, Any], request: Request) -> dict[str, Any]:
    user = _require_cloud_user(request)
    _require_cloud_admin(user)
    with connect() as db:
        init_cloud_db(db)
        camera = _camera_for_user(db, user, camera_id)
        asset_id = str(payload.get("asset_id") or "")
        asset = db.fetchone("SELECT * FROM operational_assets WHERE id = ?", (asset_id,))
        if not asset:
            raise HTTPException(status_code=404, detail="Ativo não encontrado.")
        _require_same_client(user, str(asset["cliente_id"]), "Ativo pertence a outro cliente.")
        db.execute(
            "UPDATE cloud_cameras SET area_context_id = ?, process_id = ?, asset_id = ?, atualizado_em = ? WHERE id = ?",
            (payload.get("area_context_id") or asset["area_id"], payload.get("process_id") or asset["process_id"], asset_id, now_iso(), camera["id"]),
        )
        db.execute(
            "UPDATE cloud_machine_monitors SET area_context_id = ?, process_id = ?, asset_id = ?, updated_at = ? WHERE camera_id = ?",
            (payload.get("area_context_id") or asset["area_id"], payload.get("process_id") or asset["process_id"], asset_id, now_iso(), camera["id"]),
        )
        db.commit()
        updated = db.fetchone("SELECT * FROM cloud_cameras WHERE id = ?", (camera["id"],))
    return {"camera_id": camera_id, "context": _camera_public(updated)}


@api.post("/admin/edge-devices")
def create_edge_device(payload: EdgeDeviceIn, request: Request) -> dict[str, Any]:
    user = _require_cloud_user(request)
    if user.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Permissao insuficiente.")
    with connect() as db:
        init_cloud_db(db)
        existing = db.fetchone("SELECT id FROM edge_devices WHERE id = ?", (payload.id,))
        if existing:
            raise HTTPException(status_code=409, detail="Edge ja cadastrado.")
        db.execute(
            """
            INSERT INTO edge_devices (
                id, tenant_id, cliente_id, unidade_id, nome, secret_hash, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)
            """,
            (
                payload.id,
                payload.tenant_id,
                payload.cliente_id,
                payload.unidade_id,
                payload.nome,
                hash_edge_secret(payload.secret),
                now_iso(),
                now_iso(),
            ),
        )
        db.commit()
    return {"id": payload.id, "tenant_id": payload.tenant_id, "status": "active"}





@api.get("/edge-installer/windows")
def download_windows_edge_installer(
    request: Request,
    unidade_id: str,
) -> Response:
    import base64
    import os
    import secrets

    from cloud.edge_installer import build_windows_installer_cmd

    user = _require_cloud_user(request)

    if user.get("role") not in ADMIN_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Permissao insuficiente para instalar Edge.",
        )

    with connect() as db:
        init_cloud_db(db)

        unidade = db.fetchone(
            "SELECT * FROM unidades WHERE id = ?",
            (unidade_id,),
        )

        if not unidade:
            raise HTTPException(
                status_code=404,
                detail="Unidade nao encontrada.",
            )

        cliente_id = str(unidade["cliente_id"])

        if (
            user.get("role") != "admin_campex"
            and str(user.get("cliente_id") or "") != cliente_id
        ):
            raise HTTPException(
                status_code=403,
                detail="Unidade pertence a outro cliente.",
            )

        edge = db.fetchone(
            """
            SELECT *
            FROM edge_devices
            WHERE cliente_id = ?
              AND unidade_id = ?
              AND status = 'active'
              AND revoked_at IS NULL
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (cliente_id, unidade_id),
        )
        if edge:
            edge_id = edge["id"]
            encrypted_secret = edge.get("edge_secret_encrypted")
            encrypted_credential_key = edge.get("credential_key_encrypted")
            credentials_unrecoverable = False

            if not encrypted_secret or not encrypted_credential_key:
                credentials_unrecoverable = True
            else:
                try:
                    edge_secret = decrypt_secret(encrypted_secret)
                    credential_key = decrypt_secret(encrypted_credential_key)
                except Exception:
                    credentials_unrecoverable = True

            if credentials_unrecoverable:
                # Um Edge que nunca enviou heartbeat é apenas uma tentativa de
                # instalação incompleta. Pode ser rotacionado com segurança.
                if not edge.get("last_seen_at"):
                    revoked_at = now_iso()
                    db.execute(
                        """
                        UPDATE edge_devices
                        SET status = 'revoked',
                            revoked_at = ?,
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (revoked_at, revoked_at, edge_id),
                    )
                    db.commit()
                    edge = None
                else:
                    raise HTTPException(
                        status_code=409,
                        detail="Este Edge já foi utilizado e suas credenciais não podem ser recuperadas. Reinstalação assistida necessária.",
                    )

        if not edge:
            edge_id = _cloud_new_id("edge")
            edge_secret = secrets.token_urlsafe(32)
            credential_key = base64.urlsafe_b64encode(
                os.urandom(32)
            ).decode("ascii")

            created_at = now_iso()

            db.execute(
                """
                INSERT INTO edge_devices (
                    id,
                    tenant_id,
                    cliente_id,
                    unidade_id,
                    nome,
                    secret_hash,
                    edge_secret_encrypted,
                    credential_key_encrypted,
                    status,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                """,
                (
                    edge_id,
                    cliente_id,
                    cliente_id,
                    unidade_id,
                    f"Campex Edge - {unidade['nome']}",
                    hash_edge_secret(edge_secret),
                    encrypt_secret(edge_secret),
                    encrypt_secret(credential_key),
                    created_at,
                    created_at,
                ),
            )
            db.commit()

    cloud_url = str(request.base_url).rstrip("/")

    installer = build_windows_installer_cmd(
        cloud_url=cloud_url,
        edge_id=edge_id,
        edge_secret=edge_secret,
        credential_key=credential_key,
    )

    return Response(
        content=installer,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": 'attachment; filename="Instalar-Campex.cmd"',
            "Cache-Control": "no-store",
        },
    )


@api.get("/edge-package/windows")
def download_windows_edge_package(
    x_edge_id: Optional[str] = Header(default=None, alias="X-Edge-Id"),
    x_edge_secret: Optional[str] = Header(default=None, alias="X-Edge-Secret"),
):
    import os

    from starlette.background import BackgroundTask
    from cloud.edge_installer import create_windows_edge_package

    if not x_edge_id or not x_edge_secret:
        raise HTTPException(
            status_code=401,
            detail="Credenciais do Edge ausentes.",
        )

    with connect() as db:
        init_cloud_db(db)

        device = db.fetchone(
            "SELECT * FROM edge_devices WHERE id = ?",
            (x_edge_id,),
        )

        if not device or not verify_edge_secret(
            x_edge_secret,
            device["secret_hash"],
        ):
            raise HTTPException(
                status_code=401,
                detail="Edge nao autorizado.",
            )

        if device["status"] != "active" or device.get("revoked_at"):
            raise HTTPException(
                status_code=403,
                detail="Edge revogado ou inativo.",
            )

    project_root = Path(__file__).resolve().parents[1]
    zip_path = create_windows_edge_package(project_root)

    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename="campex-edge-package.zip",
        background=BackgroundTask(
            lambda: os.unlink(zip_path)
            if os.path.exists(zip_path)
            else None
        ),
    )


@api.get("/edge-devices")
def list_edge_devices(
    request: Request,
    cliente_id: Optional[str] = None,
    unidade_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    from datetime import datetime, timezone

    user = _require_cloud_user(request)

    effective_cliente_id = cliente_id
    if user.get("role") != "admin_campex":
        effective_cliente_id = user.get("cliente_id")

    clauses = []
    params: list[Any] = []

    if effective_cliente_id:
        clauses.append("cliente_id = ?")
        params.append(effective_cliente_id)

    if unidade_id:
        clauses.append("unidade_id = ?")
        params.append(unidade_id)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with connect() as db:
        init_cloud_db(db)
        rows = db.fetchall(
            f"""
            SELECT
                id,
                tenant_id,
                cliente_id,
                unidade_id,
                nome,
                status,
                revoked_at,
                created_at,
                updated_at,
                last_seen_at
            FROM edge_devices
            {where}
            ORDER BY nome
            """,
            tuple(params),
        )

    now = datetime.now(timezone.utc)
    result = []

    for row in rows:
        item = dict(row)
        last_seen = item.get("last_seen_at")
        online = False

        if last_seen and item.get("status") == "active" and not item.get("revoked_at"):
            try:
                parsed = datetime.fromisoformat(str(last_seen).replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                online = (
                    now - parsed.astimezone(timezone.utc)
                ).total_seconds() <= 90
            except Exception:
                online = False

        item["online"] = online
        item["connection_status"] = "online" if online else "offline"
        item["last_seen_at"] = last_seen
        result.append(item)

    return result


def _parse_iso_timestamp(value: Any):
    from datetime import datetime, timezone

    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _edge_is_online(row: dict[str, Any], max_age_seconds: float = 90.0) -> bool:
    from datetime import datetime, timezone

    if row.get("status") != "active" or row.get("revoked_at"):
        return False
    parsed = _parse_iso_timestamp(row.get("last_seen_at"))
    if not parsed:
        return False
    return (datetime.now(timezone.utc) - parsed).total_seconds() <= max_age_seconds


def _sanitize_edge_diagnostics(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None

    def safe_text(raw: Any, default: str | None = None) -> str | None:
        if raw is None:
            return default
        text = str(raw)
        blocked = ("rtsp://", "password", "secret", "token", "cookie", "credential", "api_key", ".env")
        if any(item in text.lower() for item in blocked):
            return "[redacted]"
        return text[:300]

    edge = value.get("edge") if isinstance(value.get("edge"), dict) else {}
    cameras = value.get("cameras") if isinstance(value.get("cameras"), dict) else {}
    machines = value.get("machines") if isinstance(value.get("machines"), dict) else {}

    camera_items = []
    for item in cameras.get("items") or []:
        if not isinstance(item, dict):
            continue
        camera_items.append(
            {
                "camera_id": safe_text(item.get("camera_id")),
                "status": safe_text(item.get("status"), "UNKNOWN"),
                "last_frame_at": safe_text(item.get("last_frame_at")),
                "reconnect_attempts": item.get("reconnect_attempts"),
                "analysis_status": safe_text(item.get("analysis_status"), "UNKNOWN"),
                "analysis_error": safe_text(item.get("analysis_error")),
            }
        )

    machine_items = []
    for item in machines.get("items") or []:
        if not isinstance(item, dict):
            continue
        machine_items.append(
            {
                "monitor_id": safe_text(item.get("monitor_id")),
                "camera_id": safe_text(item.get("camera_id")),
                "machine_state": safe_text(item.get("machine_state"), "UNKNOWN"),
                "analysis_status": safe_text(item.get("analysis_status"), "UNKNOWN"),
                "signal_quality": item.get("signal_quality"),
                "calibration_result": safe_text(item.get("calibration_result") or item.get("readiness")),
                "readiness": safe_text(item.get("readiness")),
                "frames_analyzed": item.get("frames_analyzed"),
                "confidence": item.get("confidence"),
                "reason": safe_text(item.get("reason")),
            }
        )

    return {
        "generated_at": safe_text(value.get("generated_at")),
        "edge": {
            "version": safe_text(edge.get("version")),
            "process_uptime_seconds": edge.get("process_uptime_seconds"),
            "python_version": safe_text(edge.get("python_version")),
            "platform": safe_text(edge.get("platform")),
            "local_api_healthy": edge.get("local_api_healthy"),
            "last_local_health_check_at": safe_text(edge.get("last_local_health_check_at")),
        },
        "cameras": {
            "total": cameras.get("total"),
            "online": cameras.get("online"),
            "offline": cameras.get("offline"),
            "items": camera_items,
        },
        "machines": {
            "total": machines.get("total"),
            "items": machine_items,
        },
    }


def _edge_for_user(db, user: dict[str, Any], edge_id: str) -> dict[str, Any]:
    row = db.fetchone("SELECT * FROM edge_devices WHERE id = ?", (edge_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Edge nao encontrado.")
    if user.get("role") != "admin_campex" and row.get("cliente_id") != user.get("cliente_id"):
        raise HTTPException(status_code=403, detail="Edge de outro cliente.")
    return row


@api.get("/edges/{edge_id}/diagnostics")
def edge_diagnostics(edge_id: str, request: Request) -> dict[str, Any]:
    user = _require_cloud_user(request)
    with connect() as db:
        init_cloud_db(db)
        edge = _edge_for_user(db, user, edge_id)

    raw = edge.get("last_diagnostics_json")
    payload = None
    if raw:
        try:
            payload = json.loads(raw)
        except Exception:
            payload = None
    diagnostics = payload.get("diagnostics") if isinstance(payload, dict) else None
    received_at = payload.get("received_at") if isinstance(payload, dict) else None
    generated_at = diagnostics.get("generated_at") if isinstance(diagnostics, dict) else None
    received_dt = _parse_iso_timestamp(received_at)
    generated_dt = _parse_iso_timestamp(generated_at)
    online = _edge_is_online(edge)
    stale = not online
    if diagnostics:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        if received_dt:
            stale = stale or (now - received_dt).total_seconds() > 90
        else:
            stale = True
        if generated_dt:
            stale = stale or (now - generated_dt).total_seconds() > 90
            if received_dt and (generated_dt - received_dt).total_seconds() > 30:
                stale = True
        else:
            stale = True

    return {
        "edge_id": edge_id,
        "online": online,
        "status": "online" if online else "offline",
        "last_seen_at": edge.get("last_seen_at"),
        "generated_at": generated_at,
        "received_at": received_at,
        "stale": stale,
        "diagnostics": diagnostics,
    }


@api.get("/edge/runtime-check")
def edge_runtime_check(
    x_edge_id: Optional[str] = Header(default=None, alias="X-Edge-Id"),
    x_edge_secret: Optional[str] = Header(default=None, alias="X-Edge-Secret"),
) -> dict[str, Any]:
    from datetime import datetime, timezone

    if not x_edge_id or not x_edge_secret:
        raise HTTPException(
            status_code=401,
            detail="Credenciais do Edge ausentes.",
        )

    with connect() as db:
        init_cloud_db(db)
        device = db.fetchone(
            "SELECT * FROM edge_devices WHERE id = ?",
            (x_edge_id,),
        )

    if not device or not verify_edge_secret(
        x_edge_secret,
        device["secret_hash"],
    ):
        raise HTTPException(
            status_code=401,
            detail="Edge nao autorizado.",
        )

    if device["status"] != "active" or device.get("revoked_at"):
        raise HTTPException(
            status_code=403,
            detail="Edge revogado ou inativo.",
        )

    last_seen = device.get("last_seen_at")
    heartbeat_age_seconds = None

    if last_seen:
        try:
            parsed = datetime.fromisoformat(
                str(last_seen).replace("Z", "+00:00")
            )
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            heartbeat_age_seconds = max(
                0.0,
                (
                    datetime.now(timezone.utc)
                    - parsed.astimezone(timezone.utc)
                ).total_seconds(),
            )
        except Exception:
            heartbeat_age_seconds = None

    # Runtime envia heartbeat a cada ~10s.
    # 15s garante que estamos vendo o processo REAL atual,
    # e não um heartbeat antigo do instalador/processo anterior.
    if heartbeat_age_seconds is None or heartbeat_age_seconds > 15:
        raise HTTPException(
            status_code=503,
            detail="Heartbeat real do runtime ainda nao confirmado.",
        )

    return {
        "ok": True,
        "edge_id": x_edge_id,
        "runtime_online": True,
        "last_seen_at": last_seen,
        "heartbeat_age_seconds": heartbeat_age_seconds,
    }


def _approved_edge_update(db, version: str | None = None) -> dict[str, Any] | None:
    if version:
        return db.fetchone(
            """
            SELECT * FROM edge_update_releases
            WHERE version = ? AND approved = 1
            LIMIT 1
            """,
            (version,),
        )
    return db.fetchone(
        """
        SELECT * FROM edge_update_releases
        WHERE approved = 1
        ORDER BY created_at DESC
        LIMIT 1
        """
    )


def _update_package_path(row: dict[str, Any]) -> Path:
    path = Path(str(row.get("package_path") or ""))
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Pacote de update aprovado nao encontrado.")
    return path


def _package_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


@api.post("/edge/update/check")
async def edge_update_check(
    request: Request,
    x_edge_id: Optional[str] = Header(default=None, alias="X-Edge-Id"),
    x_edge_secret: Optional[str] = Header(default=None, alias="X-Edge-Secret"),
) -> dict[str, Any]:
    body: dict[str, Any] = {}
    try:
        body = await request.json()
    except Exception:
        body = {}
    current = str(body.get("current_version") or "").strip()
    with connect() as db:
        init_cloud_db(db)
        _edge_device_from_headers(db, x_edge_id, x_edge_secret)
        release = _approved_edge_update(db)
    if not release:
        return {
            "download_available": False,
            "version": current or None,
            "sha256": None,
            "size": None,
        }
    package = _update_package_path(release)
    sha256 = str(release.get("sha256") or "").lower()
    if not sha256:
        sha256 = _package_sha256(package)
    size = release.get("size_bytes")
    if size is None:
        size = package.stat().st_size
    target = str(release["version"])
    return {
        "download_available": bool(target and target != current),
        "version": target,
        "sha256": sha256,
        "size": int(size),
    }


@api.get("/edge/update/package")
def edge_update_package(
    version: str,
    x_edge_id: Optional[str] = Header(default=None, alias="X-Edge-Id"),
    x_edge_secret: Optional[str] = Header(default=None, alias="X-Edge-Secret"),
) -> FileResponse:
    with connect() as db:
        init_cloud_db(db)
        _edge_device_from_headers(db, x_edge_id, x_edge_secret)
        release = _approved_edge_update(db, version)
    if not release:
        raise HTTPException(status_code=404, detail="Versao de update nao aprovada.")
    package = _update_package_path(release)
    expected = str(release.get("sha256") or "").lower()
    if expected and _package_sha256(package) != expected:
        raise HTTPException(status_code=409, detail="Pacote aprovado nao confere com o hash registrado.")
    return FileResponse(
        package,
        media_type="application/zip",
        filename=f"campex-edge-{version}.zip",
        headers={"Cache-Control": "no-store"},
    )


@api.post("/edge/heartbeat")
async def edge_heartbeat(
    request: Request,
    x_edge_id: Optional[str] = Header(default=None, alias="X-Edge-Id"),
    x_edge_secret: Optional[str] = Header(default=None, alias="X-Edge-Secret"),
) -> dict[str, Any]:
    if not x_edge_id or not x_edge_secret:
        raise HTTPException(
            status_code=401,
            detail="Credenciais do Edge ausentes.",
        )

    with connect() as db:
        init_cloud_db(db)

        device = db.fetchone(
            "SELECT * FROM edge_devices WHERE id = ?",
            (x_edge_id,),
        )

        if not device or not verify_edge_secret(
            x_edge_secret,
            device["secret_hash"],
        ):
            raise HTTPException(
                status_code=401,
                detail="Edge nao autorizado.",
            )

        if device["status"] != "active" or device.get("revoked_at"):
            raise HTTPException(
                status_code=403,
                detail="Edge revogado ou inativo.",
            )

        body: dict[str, Any] = {}
        try:
            body = await request.json()
        except Exception:
            body = {}
        diagnostics = _sanitize_edge_diagnostics(body.get("diagnostics")) if isinstance(body, dict) else None
        seen_at = now_iso()
        diagnostics_snapshot = (
            json.dumps({"received_at": seen_at, "diagnostics": diagnostics}, ensure_ascii=False)
            if diagnostics
            else None
        )

        if diagnostics_snapshot:
            db.execute(
                """
                UPDATE edge_devices
                SET last_seen_at = ?, updated_at = ?, last_diagnostics_json = ?
                WHERE id = ?
                """,
                (seen_at, seen_at, diagnostics_snapshot, x_edge_id),
            )
        else:
            db.execute(
                """
                UPDATE edge_devices
                SET last_seen_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (seen_at, seen_at, x_edge_id),
            )
        db.commit()

    return {
        "ok": True,
        "edge_id": x_edge_id,
        "status": "online",
        "seen_at": seen_at,
        "diagnostics": "stored" if diagnostics_snapshot else "not_provided",
    }


@api.get("/edge/config")
def edge_config(
    x_edge_id: Optional[str] = Header(default=None, alias="X-Edge-Id"),
    x_edge_secret: Optional[str] = Header(default=None, alias="X-Edge-Secret"),
) -> dict[str, Any]:
    with connect() as db:
        init_cloud_db(db)
        device = _edge_device_from_headers(db, x_edge_id, x_edge_secret)
        rows = db.fetchall(
            """
            SELECT *
            FROM cloud_cameras
            WHERE cliente_id = ?
              AND unidade_id = ?
              AND ativa = 1
              AND (edge_id IS NULL OR edge_id = ?)
            ORDER BY nome
            """,
            (device["cliente_id"], device["unidade_id"], device["id"]),
        )
        camera_ids = [row["id"] for row in rows]
        areas: list[dict[str, Any]] = []
        monitors: list[dict[str, Any]] = []
        if camera_ids:
            placeholders = ",".join("?" for _ in camera_ids)
            area_rows = db.fetchall(
                f"""
                SELECT *
                FROM cloud_monitored_areas
                WHERE cliente_id = ?
                  AND camera_id IN ({placeholders})
                ORDER BY created_at
                """,
                (device["cliente_id"], *camera_ids),
            )
            monitor_rows = db.fetchall(
                f"""
                SELECT *
                FROM cloud_machine_monitors
                WHERE client_id = ?
                  AND unit_id = ?
                  AND camera_id IN ({placeholders})
                ORDER BY created_at
                """,
                (device["cliente_id"], device["unidade_id"], *camera_ids),
            )
            areas = [_area_public(row) for row in area_rows]
            monitors = [_monitor_public(row) for row in monitor_rows]

    cameras = []
    for row in rows:
        password = None
        if row.get("rtsp_password_encrypted"):
            try:
                password = decrypt_secret(row.get("rtsp_password_encrypted"))
            except Exception as exc:
                raise HTTPException(status_code=500, detail="Credencial RTSP da câmera está inválida no Cloud.") from exc
        cameras.append(
            {
                "id": row["id"],
                "cliente_id": row["cliente_id"],
                "unidade_id": row["unidade_id"],
                "edge_id": device["id"],
                "nome": row["nome"],
                "host": row.get("rtsp_host"),
                "porta": row.get("rtsp_port") or 554,
                "path": row.get("rtsp_path"),
                "username": row.get("rtsp_username"),
                "password": password,
                "ativa": bool(row.get("ativa")),
                "source_type": row.get("source_type") or "rtsp",
                "secure_ref": row.get("secure_ref"),
                "area_context_id": row.get("area_context_id"),
                "process_id": row.get("process_id"),
                "asset_id": row.get("asset_id"),
            }
        )

    return {
        "edge_id": device["id"],
        "tenant_id": device["tenant_id"],
        "cliente_id": device["cliente_id"],
        "unidade_id": device["unidade_id"],
        "cameras": cameras,
        "areas": areas,
        "machine_monitors": monitors,
    }


@api.post("/edge/cameras/status")
def edge_camera_runtime_status(
    payload: dict[str, Any],
    x_edge_id: Optional[str] = Header(default=None, alias="X-Edge-Id"),
    x_edge_secret: Optional[str] = Header(default=None, alias="X-Edge-Secret"),
) -> dict[str, Any]:
    items = payload.get("cameras") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise HTTPException(status_code=400, detail="Informe cameras como lista.")
    received_at = now_iso()
    updated = 0
    with connect() as db:
        init_cloud_db(db)
        device = _edge_device_from_headers(db, x_edge_id, x_edge_secret)
        for item in items:
            if not isinstance(item, dict):
                continue
            camera_id = str(item.get("camera_id") or "").strip()
            if not camera_id:
                continue
            camera = db.fetchone("SELECT * FROM cloud_cameras WHERE id = ?", (camera_id,))
            if not camera:
                continue
            if camera["cliente_id"] != device["cliente_id"] or camera["unidade_id"] != device["unidade_id"]:
                continue
            if camera.get("edge_id") and camera["edge_id"] != device["id"]:
                continue
            status = {
                "camera_id": camera_id,
                "status": item.get("status") or "offline",
                "last_frame_at": item.get("last_frame_at"),
                "ai_status": item.get("ai_status"),
                "people_count": item.get("people_count"),
                "machine_state": item.get("machine_state") or "UNKNOWN",
                "machine_motion": item.get("machine_motion"),
                "machine_confidence": item.get("machine_confidence"),
                "machine_reason": item.get("machine_reason"),
                "machine_seconds_in_state": item.get("machine_seconds_in_state"),
                "machine_analysis_status": item.get("machine_analysis_status"),
                "machine_monitor_id": item.get("machine_monitor_id"),
                "received_at": received_at,
            }
            db.execute(
                """
                UPDATE cloud_cameras
                SET status = ?, ultimo_frame = COALESCE(?, ultimo_frame),
                    runtime_status_json = ?, atualizado_em = ?
                WHERE id = ?
                """,
                (
                    status["status"],
                    status["last_frame_at"],
                    json.dumps(status, ensure_ascii=False),
                    received_at,
                    camera_id,
                ),
            )
            updated += 1
        db.commit()
    return {"ok": True, "updated": updated, "received_at": received_at}


@api.post("/edge/cameras/{camera_id}/latest-frame")
async def edge_camera_latest_frame(
    camera_id: str,
    request: Request,
    x_edge_id: Optional[str] = Header(default=None, alias="X-Edge-Id"),
    x_edge_secret: Optional[str] = Header(default=None, alias="X-Edge-Secret"),
) -> dict[str, Any]:
    content_type = (request.headers.get("content-type") or "").lower()
    if "image/jpeg" not in content_type and "image/jpg" not in content_type:
        raise HTTPException(status_code=415, detail="Envie a imagem em JPEG.")
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Frame vazio.")
    if len(body) > MAX_LATEST_FRAME_BYTES:
        raise HTTPException(status_code=413, detail="Frame excede o tamanho máximo permitido.")

    with connect() as db:
        init_cloud_db(db)
        device = _edge_device_from_headers(db, x_edge_id, x_edge_secret)
        camera = db.fetchone("SELECT * FROM cloud_cameras WHERE id = ?", (camera_id,))
        if not camera:
            raise HTTPException(status_code=404, detail="Camera nao encontrada.")
        if camera["cliente_id"] != device["cliente_id"] or camera["unidade_id"] != device["unidade_id"]:
            raise HTTPException(status_code=403, detail="Camera pertence a outro cliente ou unidade.")
        if camera.get("edge_id") and camera["edge_id"] != device["id"]:
            raise HTTPException(status_code=403, detail="Camera pertence a outro Edge.")

        path = _latest_frame_path(camera_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        tmp_path.write_bytes(body)
        os.replace(tmp_path, path)
        received_at = now_iso()
        db.execute(
            "UPDATE cloud_cameras SET status = 'online', ultimo_frame = ?, atualizado_em = ? WHERE id = ?",
            (received_at, received_at, camera_id),
        )
        db.commit()

    return {"ok": True, "camera_id": camera_id, "received_at": received_at}


@api.get("/cameras/{camera_id}/latest-frame")
def cloud_camera_latest_frame(camera_id: str, request: Request) -> FileResponse:
    user = _require_cloud_user(request)
    with connect() as db:
        init_cloud_db(db)
        _camera_for_user(db, user, camera_id)
    path = _latest_frame_path(camera_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Ainda não há frame recente enviado pelo Campex Edge.")
    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


def _send_cloud_report_email(payload: ReportDeliveryIn) -> str:
    import os
    import urllib.error
    import urllib.request

    provider = os.getenv("CAMPEX_CLOUD_EMAIL_PROVIDER", "").strip().lower()

    if provider != "resend":
        raise RuntimeError(
            "CLOUD_EMAIL_NOT_CONFIGURED: CAMPEX_CLOUD_EMAIL_PROVIDER deve ser 'resend'."
        )

    api_key = os.getenv("CAMPEX_RESEND_API_KEY", "").strip()
    from_address = os.getenv("CAMPEX_EMAIL_FROM", "").strip()

    if not api_key or not from_address:
        missing = []
        if not api_key:
            missing.append("CAMPEX_RESEND_API_KEY")
        if not from_address:
            missing.append("CAMPEX_EMAIL_FROM")
        raise RuntimeError(
            f"CLOUD_EMAIL_NOT_CONFIGURED: faltam {', '.join(missing)}."
        )

    body = json.dumps(
        {
            "from": from_address,
            "to": [payload.recipient],
            "subject": payload.subject,
            "text": payload.text_body,
            "html": payload.html_body,
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        "https://api.resend.com/emails",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Idempotency-Key": payload.delivery_id,
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(
            f"EMAIL_PROVIDER_ERROR: HTTP {exc.code}: {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"EMAIL_PROVIDER_UNAVAILABLE: {exc.reason}"
        ) from exc

    provider_message_id = str(response_payload.get("id") or "").strip()
    if not provider_message_id:
        raise RuntimeError("EMAIL_PROVIDER_INVALID_RESPONSE: id ausente.")

    return provider_message_id


@api.post("/edge/report-delivery")
def receive_report_delivery(
    payload: ReportDeliveryIn,
    x_edge_id: Optional[str] = Header(default=None, alias="X-Edge-Id"),
    x_edge_secret: Optional[str] = Header(default=None, alias="X-Edge-Secret"),
) -> dict[str, Any]:
    if not x_edge_id or not x_edge_secret:
        raise HTTPException(status_code=401, detail="Credenciais do Edge ausentes.")

    payload_json = json.dumps(
        payload.model_dump(),
        ensure_ascii=False,
        sort_keys=True,
    )

    with connect() as db:
        init_cloud_db(db)

        device = db.fetchone(
            "SELECT * FROM edge_devices WHERE id = ?",
            (x_edge_id,),
        )

        if not device or not verify_edge_secret(
            x_edge_secret,
            device["secret_hash"],
        ):
            LOGGER.warning(
                "Tentativa de report delivery com credencial invalida para edge_id=%s",
                x_edge_id,
            )
            raise HTTPException(status_code=401, detail="Edge nao autorizado.")

        if device["status"] != "active" or device.get("revoked_at"):
            raise HTTPException(
                status_code=403,
                detail="Edge revogado ou inativo.",
            )

        if payload.cliente_id != device["cliente_id"]:
            raise HTTPException(
                status_code=403,
                detail="Relatorio pertence a outro cliente.",
            )

        existing = db.fetchone(
            """
            SELECT *
            FROM report_deliveries
            WHERE id = ?
            """,
            (payload.delivery_id,),
        )

        if existing:
            if (
                existing["cliente_id"] != payload.cliente_id
                or existing["edge_id"] != x_edge_id
                or existing["payload_json"] != payload_json
            ):
                raise HTTPException(
                    status_code=409,
                    detail="delivery_id ja utilizado com outro payload.",
                )

            if existing["status"] == "sent":
                return {
                    "delivery_id": payload.delivery_id,
                    "status": "sent",
                    "idempotent": True,
                    "provider_message_id": existing.get("provider_message_id"),
                }
        else:
            db.execute(
                """
                INSERT INTO report_deliveries (
                    id,
                    tenant_id,
                    cliente_id,
                    unidade_id,
                    edge_id,
                    recipient,
                    subject,
                    status,
                    attempts,
                    payload_json,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?)
                """,
                (
                    payload.delivery_id,
                    device["tenant_id"],
                    payload.cliente_id,
                    device["unidade_id"],
                    x_edge_id,
                    payload.recipient,
                    payload.subject,
                    payload_json,
                    now_iso(),
                    now_iso(),
                ),
            )
            db.commit()

        db.execute(
            """
            UPDATE report_deliveries
            SET
                status = 'pending',
                attempts = attempts + 1,
                last_error = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (now_iso(), payload.delivery_id),
        )
        db.commit()

        try:
            provider_message_id = _send_cloud_report_email(payload)
        except Exception as exc:
            db.execute(
                """
                UPDATE report_deliveries
                SET
                    status = 'failed',
                    last_error = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    str(exc)[:2000],
                    now_iso(),
                    payload.delivery_id,
                ),
            )
            db.commit()
            raise HTTPException(
                status_code=502,
                detail=str(exc),
            ) from exc

        sent_at = now_iso()

        db.execute(
            """
            UPDATE report_deliveries
            SET
                status = 'sent',
                provider_message_id = ?,
                last_error = NULL,
                sent_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                provider_message_id,
                sent_at,
                sent_at,
                payload.delivery_id,
            ),
        )
        db.commit()

        return {
            "delivery_id": payload.delivery_id,
            "status": "sent",
            "idempotent": False,
            "provider_message_id": provider_message_id,
        }


@api.post("/edge/events")
def receive_edge_event(
    payload: EdgeEventIn,
    request: Request,
    x_edge_id: Optional[str] = Header(default=None, alias="X-Edge-Id"),
    x_edge_secret: Optional[str] = Header(default=None, alias="X-Edge-Secret"),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    if not x_edge_id or not x_edge_secret:
        raise HTTPException(status_code=401, detail="Credenciais do Edge ausentes.")
    if idempotency_key and idempotency_key != payload.event_uuid:
        raise HTTPException(status_code=400, detail="Idempotency-Key diferente do event_uuid.")
    with connect() as db:
        init_cloud_db(db)
        device = db.fetchone("SELECT * FROM edge_devices WHERE id = ?", (x_edge_id,))
        if not device or not verify_edge_secret(x_edge_secret, device["secret_hash"]):
            LOGGER.warning("Tentativa de evento com credencial invalida para edge_id=%s", x_edge_id)
            raise HTTPException(status_code=401, detail="Edge nao autorizado.")
        if device["status"] != "active" or device.get("revoked_at"):
            raise HTTPException(status_code=403, detail="Edge revogado ou inativo.")
        if payload.tenant_id != device["tenant_id"] or payload.cliente_id != device["cliente_id"] or payload.unidade_id != device["unidade_id"]:
            raise HTTPException(status_code=403, detail="Evento pertence a outro tenant, cliente ou unidade.")
        existing = db.fetchone("SELECT id, received_at FROM edge_events WHERE event_uuid = ?", (payload.event_uuid,))
        if existing:
            payload_json = json.dumps(payload.model_dump())
            db.execute(
                """
                UPDATE edge_events
                SET fim = COALESCE(?, fim),
                    duracao = COALESCE(?, duracao),
                    operador_presente = COALESCE(?, operador_presente),
                    confianca = COALESCE(?, confianca),
                    severidade = COALESCE(?, severidade),
                    status = COALESCE(?, status),
                    midia_path = COALESCE(?, midia_path),
                    payload_json = ?
                WHERE event_uuid = ?
                """,
                (
                    payload.fim,
                    payload.duracao,
                    payload.operador_presente,
                    payload.confianca,
                    payload.severidade,
                    payload.status,
                    payload.midia_path,
                    payload_json,
                    payload.event_uuid,
                ),
            )
            db.commit()
            return {"status": "duplicate_updated", "event_uuid": payload.event_uuid, "id": existing["id"], "received_at": existing["received_at"]}
        event_id = f"cevt_{uuid.uuid4().hex[:12]}"
        received_at = now_iso()
        payload_json = json.dumps(payload.model_dump())
        db.execute(
            """
            INSERT INTO edge_events (
                id, event_uuid, tenant_id, cliente_id, unidade_id, edge_id, camera_id, tipo,
                inicio, fim, duracao, operador_presente, confianca, severidade, status, midia_path,
                payload_json, received_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                payload.event_uuid,
                payload.tenant_id,
                payload.cliente_id,
                payload.unidade_id,
                x_edge_id,
                payload.camera_id,
                payload.tipo,
                payload.inicio,
                payload.fim,
                payload.duracao,
                payload.operador_presente,
                payload.confianca,
                payload.severidade,
                payload.status,
                payload.midia_path,
                payload_json,
                received_at,
            ),
        )
        db.commit()
    LOGGER.info("Evento recebido do Edge edge_id=%s event_uuid=%s", x_edge_id, payload.event_uuid)
    return {"status": "received", "event_uuid": payload.event_uuid, "id": event_id, "received_at": received_at}


@api.post("/edge/events/{event_uuid}/evidence")
async def receive_edge_event_evidence(
    event_uuid: str,
    request: Request,
    x_edge_id: Optional[str] = Header(default=None, alias="X-Edge-Id"),
    x_edge_secret: Optional[str] = Header(default=None, alias="X-Edge-Secret"),
) -> dict[str, Any]:
    content_type = (request.headers.get("content-type") or "").lower()
    if "image/jpeg" not in content_type and "image/jpg" not in content_type:
        raise HTTPException(status_code=415, detail="Envie a evidência em JPEG.")
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Evidência vazia.")
    if len(body) > MAX_EVENT_EVIDENCE_BYTES:
        raise HTTPException(status_code=413, detail="Evidência excede o tamanho máximo permitido.")

    with connect() as db:
        init_cloud_db(db)
        device = _edge_device_from_headers(db, x_edge_id, x_edge_secret)
        row = db.fetchone("SELECT * FROM edge_events WHERE event_uuid = ?", (event_uuid,))
        if not row:
            raise HTTPException(status_code=404, detail="Evento não encontrado para este Edge.")
        if row["cliente_id"] != device["cliente_id"] or row["unidade_id"] != device["unidade_id"] or row["edge_id"] != device["id"]:
            raise HTTPException(status_code=403, detail="Evento pertence a outro Edge, tenant ou unidade.")

        path = _event_evidence_path(event_uuid)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_bytes(body)
        tmp_path.replace(path)
        try:
            relative_path = path.relative_to(ROOT).as_posix()
        except ValueError:
            relative_path = path.as_posix()
        db.execute(
            "UPDATE edge_events SET midia_path = COALESCE(NULLIF(?, ''), midia_path), payload_json = ? WHERE event_uuid = ?",
            (relative_path, json.dumps({**_payload(row), "cloud_evidence_path": relative_path}, ensure_ascii=False), event_uuid),
        )
        db.commit()
    return {"ok": True, "event_uuid": event_uuid, "evidence_path": relative_path}


@api.get("/eventos")
def list_cloud_events(request: Request, camera_id: Optional[str] = None) -> list[dict[str, Any]]:
    user = _require_cloud_user(request)
    clauses = []
    params: list[Any] = []
    tenant = _tenant_for_user(user)
    if tenant:
        clauses.append("cliente_id = ?")
        params.append(tenant)
    if camera_id:
        clauses.append("camera_id = ?")
        params.append(camera_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with connect() as db:
        init_cloud_db(db)
        rows = db.fetchall(f"SELECT * FROM edge_events {where} ORDER BY received_at DESC LIMIT 200", tuple(params))
    return [
        _event_row_public(row)
        for row in rows
    ]


@api.delete("/eventos")
def cloud_delete_events(request: Request) -> dict[str, Any]:
    user = _require_cloud_user(request)
    if user.get("role") != "admin_campex":
        raise HTTPException(status_code=403, detail="Somente admin Campex pode limpar eventos sincronizados.")
    with connect() as db:
        init_cloud_db(db)
        row = db.fetchone("SELECT COUNT(*) AS total FROM edge_events")
        db.execute("DELETE FROM edge_events")
        db.commit()
    return {"deleted": int((row or {}).get("total") or 0)}


@api.get("/cameras/estado")
def list_cloud_camera_state(request: Request) -> list[dict[str, Any]]:
    user = _require_cloud_user(request)
    with connect() as db:
        init_cloud_db(db)
        cameras = _cloud_cameras(db, user)
        tenant = _tenant_for_user(user)
        if tenant:
            event_rows = db.fetchall(
                """
                SELECT camera_id, edge_id, unidade_id, MAX(received_at) AS ultimo_frame, COUNT(*) AS eventos
                FROM edge_events
                WHERE cliente_id = ?
                GROUP BY camera_id, edge_id, unidade_id
                ORDER BY MAX(received_at) DESC
                LIMIT 200
                """,
                (tenant,),
            )
        else:
            event_rows = db.fetchall(
                """
                SELECT camera_id, edge_id, unidade_id, MAX(received_at) AS ultimo_frame, COUNT(*) AS eventos
                FROM edge_events
                GROUP BY camera_id, edge_id, unidade_id
                ORDER BY MAX(received_at) DESC
                LIMIT 200
                """
            )
    by_id = {camera["id"]: camera for camera in cameras}
    for row in event_rows:
        item = by_id.setdefault(
            row["camera_id"],
            {
                "id": row["camera_id"],
                "nome": row["camera_id"],
                "camera_id": row["camera_id"],
                "edge_id": row["edge_id"],
                "unidade_id": row["unidade_id"],
                "status": "online",
                "ativa": True,
            },
        )
        item["ultimo_frame"] = row["ultimo_frame"]
        item["eventos_recebidos"] = row["eventos"]
        if not item.get("status") or item.get("status") == "configured":
            item["status"] = "online"
    return list(by_id.values())


@api.patch("/cameras/{camera_id}")
def cloud_patch_camera(camera_id: str, payload: dict[str, Any], request: Request) -> dict[str, Any]:
    user = _require_cloud_user(request)
    _require_cloud_admin(user)
    with connect() as db:
        init_cloud_db(db)
        camera = _camera_for_user(db, user, camera_id)
        updates = []
        values: list[Any] = []
        if "nome" in payload:
            updates.append("nome = ?")
            values.append(str(payload.get("nome") or camera["nome"]).strip())
        if "ativa" in payload:
            updates.append("ativa = ?")
            values.append(1 if payload.get("ativa") else 0)
        if updates:
            updates.append("atualizado_em = ?")
            values.append(now_iso())
            values.append(camera_id)
            db.execute(f"UPDATE cloud_cameras SET {', '.join(updates)} WHERE id = ?", tuple(values))
            db.commit()
        return _camera_public(db.fetchone("SELECT * FROM cloud_cameras WHERE id = ?", (camera_id,)))


@api.post("/cameras/{camera_id}/start")
def cloud_start_camera(camera_id: str, request: Request) -> dict[str, Any]:
    user = _require_cloud_user(request)
    with connect() as db:
        init_cloud_db(db)
        camera = _camera_for_user(db, user, camera_id)
    return {
        "camera_id": camera_id,
        "status": camera.get("status") or "configured",
        "stream_running": False,
        "message": "Streaming ao vivo é executado pelo Edge local; a Cloud exibe o estado sincronizado.",
    }


@api.post("/cameras/{camera_id}/stop")
def cloud_stop_camera(camera_id: str, request: Request) -> dict[str, Any]:
    return cloud_start_camera(camera_id, request)


@api.get("/cameras/{camera_id}/status")
def cloud_camera_status(camera_id: str, request: Request) -> dict[str, Any]:
    user = _require_cloud_user(request)
    with connect() as db:
        init_cloud_db(db)
        camera = _camera_for_user(db, user, camera_id)
    runtime = _runtime_status_payload(camera)
    if runtime and not runtime.get("stale"):
        return {
            "camera_id": camera_id,
            "status": runtime.get("status") or camera.get("status") or "configured",
            "width": None,
            "height": None,
            "fps": camera.get("fps"),
            "last_frame_at": runtime.get("last_frame_at") or camera.get("ultimo_frame"),
            "ai_status": runtime.get("ai_status") or "inativa",
            "people_count": runtime.get("people_count"),
            "machine_state": runtime.get("machine_state") or "UNKNOWN",
            "machine_motion": runtime.get("machine_motion"),
            "machine_confidence": runtime.get("machine_confidence"),
            "machine_reason": runtime.get("machine_reason"),
            "machine_seconds_in_state": runtime.get("machine_seconds_in_state"),
            "machine_analysis_status": runtime.get("machine_analysis_status"),
            "machine_monitor_id": runtime.get("machine_monitor_id"),
            "incident_active": False,
            "runtime_source": "edge",
        }
    return {
        "camera_id": camera_id,
        "status": "offline" if runtime and runtime.get("stale") else camera.get("status") or "configured",
        "width": None,
        "height": None,
        "fps": camera.get("fps"),
        "last_frame_at": camera.get("ultimo_frame"),
        "ai_status": "indisponível",
        "people_count": None,
        "machine_state": "UNKNOWN",
        "incident_active": False,
        "error": "Status recente do Edge ainda não disponível." if not runtime else "Status do Edge está desatualizado.",
    }


@api.get("/cameras/{camera_id}/stream")
def cloud_camera_stream(camera_id: str, request: Request) -> Response:
    user = _require_cloud_user(request)
    with connect() as db:
        init_cloud_db(db)
        _camera_for_user(db, user, camera_id)
    raise HTTPException(status_code=503, detail="Stream ao vivo indisponível na Cloud sem relay configurado.")


@api.post("/cameras/{camera_id}/analysis/start")
def cloud_camera_analysis_start(camera_id: str, request: Request) -> dict[str, Any]:
    return cloud_camera_status(camera_id, request)


@api.post("/cameras/{camera_id}/analysis/stop")
def cloud_camera_analysis_stop(camera_id: str, request: Request) -> dict[str, Any]:
    return cloud_camera_status(camera_id, request)


@api.get("/cameras/{camera_id}/areas")
def cloud_camera_areas(camera_id: str, request: Request) -> list[dict[str, Any]]:
    user = _require_cloud_user(request)
    with connect() as db:
        init_cloud_db(db)
        camera = _camera_for_user(db, user, camera_id)
        rows = db.fetchall("SELECT * FROM cloud_monitored_areas WHERE camera_id = ? AND cliente_id = ? ORDER BY created_at DESC", (camera_id, camera["cliente_id"]))
    return [_area_public(row) for row in rows]


@api.post("/cameras/{camera_id}/areas")
def cloud_create_camera_area(camera_id: str, payload: dict[str, Any], request: Request) -> dict[str, Any]:
    user = _require_cloud_user(request)
    _require_cloud_admin(user)
    with connect() as db:
        init_cloud_db(db)
        camera = _camera_for_user(db, user, camera_id)
        area_id = _cloud_new_id("area")
        db.execute(
            "INSERT INTO cloud_monitored_areas (id, cliente_id, camera_id, nome, tipo, pontos_json, ativa, machine_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                area_id,
                camera["cliente_id"],
                camera_id,
                str(payload.get("nome") or "Zona operacional"),
                str(payload.get("tipo") or "operator_zone"),
                json.dumps(payload.get("pontos") or []),
                1 if payload.get("ativa", True) else 0,
                payload.get("machine_id"),
                now_iso(),
            ),
        )
        db.commit()
        row = db.fetchone("SELECT * FROM cloud_monitored_areas WHERE id = ?", (area_id,))
    return _area_public(row)


def _area_for_user(db, user: dict[str, Any], area_id: str) -> dict[str, Any]:
    row = db.fetchone("SELECT * FROM cloud_monitored_areas WHERE id = ?", (area_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Área não encontrada.")
    _require_same_client(user, str(row["cliente_id"]), "Área pertence a outro cliente.")
    return row


@api.delete("/areas/{area_id}")
def cloud_delete_area(area_id: str, request: Request) -> dict[str, Any]:
    user = _require_cloud_user(request)
    _require_cloud_admin(user)
    with connect() as db:
        init_cloud_db(db)
        _area_for_user(db, user, area_id)
        db.execute("DELETE FROM cloud_monitored_areas WHERE id = ?", (area_id,))
        db.commit()
    return {"id": area_id, "deleted": True}


@api.post("/areas/{area_id}/activate")
def cloud_activate_area(area_id: str, request: Request) -> dict[str, Any]:
    return _cloud_set_area_active(area_id, request, True)


@api.post("/areas/{area_id}/deactivate")
def cloud_deactivate_area(area_id: str, request: Request) -> dict[str, Any]:
    return _cloud_set_area_active(area_id, request, False)


def _cloud_set_area_active(area_id: str, request: Request, active: bool) -> dict[str, Any]:
    user = _require_cloud_user(request)
    _require_cloud_admin(user)
    with connect() as db:
        init_cloud_db(db)
        _area_for_user(db, user, area_id)
        db.execute("UPDATE cloud_monitored_areas SET ativa = ? WHERE id = ?", (1 if active else 0, area_id))
        db.commit()
        return _area_public(db.fetchone("SELECT * FROM cloud_monitored_areas WHERE id = ?", (area_id,)))


@api.get("/cameras/{camera_id}/machine-monitors")
def cloud_camera_machine_monitors(camera_id: str, request: Request) -> list[dict[str, Any]]:
    user = _require_cloud_user(request)
    with connect() as db:
        init_cloud_db(db)
        camera = _camera_for_user(db, user, camera_id)
        rows = db.fetchall("SELECT * FROM cloud_machine_monitors WHERE camera_id = ? AND client_id = ? ORDER BY created_at DESC", (camera_id, camera["cliente_id"]))
    return [_monitor_public(row) for row in rows]


@api.post("/cameras/{camera_id}/machine-monitors")
def cloud_create_machine_monitor(camera_id: str, payload: dict[str, Any], request: Request) -> dict[str, Any]:
    user = _require_cloud_user(request)
    _require_cloud_admin(user)
    with connect() as db:
        init_cloud_db(db)
        camera = _camera_for_user(db, user, camera_id)
        existing = db.fetchone("SELECT id FROM cloud_machine_monitors WHERE camera_id = ? ORDER BY created_at ASC LIMIT 1", (camera_id,))
        monitor_id = existing["id"] if existing else _cloud_new_id("mon")
        values = (
            str(payload.get("nome") or "Monitor operacional"),
            json.dumps(payload.get("machine_polygon") or []),
            json.dumps(payload.get("operator_polygon") or []),
            json.dumps(payload.get("operation_polygon")) if payload.get("operation_polygon") is not None else None,
            1 if payload.get("ativo", True) else 0,
            payload.get("motion_sensitivity"),
            payload.get("stop_seconds") or 30,
            payload.get("operator_absence_seconds") or 300,
            payload.get("stopped_with_operator_seconds") or 120,
            camera.get("area_context_id"),
            camera.get("process_id"),
            camera.get("asset_id"),
            now_iso(),
            now_iso(),
        )
        if existing:
            update_values = (
                values[0],
                values[1],
                values[2],
                values[3],
                values[4],
                values[5],
                values[6],
                values[7],
                values[8],
                values[9],
                values[10],
                values[11],
                values[13],
            )
            db.execute(
                """
                UPDATE cloud_machine_monitors
                SET nome = ?, machine_polygon_json = ?, operator_polygon_json = ?,
                    operation_polygon_json = ?, ativo = ?, motion_sensitivity = ?,
                    stop_seconds = ?, operator_absence_seconds = ?,
                    stopped_with_operator_seconds = ?, area_context_id = ?,
                    process_id = ?, asset_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (*update_values, monitor_id),
            )
        else:
            db.execute(
                """
                INSERT INTO cloud_machine_monitors (
                    id, client_id, unit_id, camera_id, nome, machine_polygon_json,
                    operator_polygon_json, operation_polygon_json, ativo,
                    motion_sensitivity, stop_seconds, operator_absence_seconds,
                    stopped_with_operator_seconds, area_context_id, process_id,
                    asset_id, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    monitor_id,
                    camera["cliente_id"],
                    camera["unidade_id"],
                    camera_id,
                    *values,
                ),
            )
        db.commit()
        row = db.fetchone("SELECT * FROM cloud_machine_monitors WHERE id = ?", (monitor_id,))
    return _monitor_public(row)


def _monitor_for_user(db, user: dict[str, Any], monitor_id: str) -> dict[str, Any]:
    row = db.fetchone("SELECT * FROM cloud_machine_monitors WHERE id = ?", (monitor_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Monitor não encontrado.")
    _require_same_client(user, str(row["client_id"]), "Monitor pertence a outro cliente.")
    return row


@api.delete("/machine-monitors/{monitor_id}")
def cloud_delete_machine_monitor(monitor_id: str, request: Request) -> dict[str, Any]:
    user = _require_cloud_user(request)
    _require_cloud_admin(user)
    with connect() as db:
        init_cloud_db(db)
        _monitor_for_user(db, user, monitor_id)
        db.execute("DELETE FROM cloud_machine_monitors WHERE id = ?", (monitor_id,))
        db.commit()
    return {"id": monitor_id, "deleted": True}


@api.post("/machine-monitors/{monitor_id}/activate")
def cloud_activate_machine_monitor(monitor_id: str, request: Request) -> dict[str, Any]:
    return _cloud_set_monitor_active(monitor_id, request, True)


@api.post("/machine-monitors/{monitor_id}/deactivate")
def cloud_deactivate_machine_monitor(monitor_id: str, request: Request) -> dict[str, Any]:
    return _cloud_set_monitor_active(monitor_id, request, False)


def _cloud_set_monitor_active(monitor_id: str, request: Request, active: bool) -> dict[str, Any]:
    user = _require_cloud_user(request)
    _require_cloud_admin(user)
    with connect() as db:
        init_cloud_db(db)
        _monitor_for_user(db, user, monitor_id)
        db.execute("UPDATE cloud_machine_monitors SET ativo = ?, updated_at = ? WHERE id = ?", (1 if active else 0, now_iso(), monitor_id))
        db.commit()
        return _monitor_public(db.fetchone("SELECT * FROM cloud_machine_monitors WHERE id = ?", (monitor_id,)))


@api.post("/machine-monitors/{monitor_id}/calibration/active/start")
def cloud_calibration_active(monitor_id: str, payload: dict[str, Any], request: Request) -> dict[str, Any]:
    return _cloud_calibration_pending(monitor_id, request, "active")


@api.post("/machine-monitors/{monitor_id}/calibration/stopped/start")
def cloud_calibration_stopped(monitor_id: str, payload: dict[str, Any], request: Request) -> dict[str, Any]:
    return _cloud_calibration_pending(monitor_id, request, "stopped")


@api.get("/machine-monitors/{monitor_id}/calibration/status")
def cloud_calibration_status(monitor_id: str, request: Request) -> dict[str, Any]:
    user = _require_cloud_user(request)
    with connect() as db:
        init_cloud_db(db)
        monitor = _monitor_for_user(db, user, monitor_id)
    return {
        "monitor_id": monitor_id,
        "status": monitor.get("calibration_status") or "pending",
        "result": monitor.get("calibration_result") or "PENDING_EDGE_RUNTIME",
        "reason": "Calibração física é executada no Edge com frame real.",
    }


def _cloud_calibration_pending(monitor_id: str, request: Request, phase: str) -> dict[str, Any]:
    user = _require_cloud_user(request)
    _require_cloud_admin(user)
    with connect() as db:
        init_cloud_db(db)
        _monitor_for_user(db, user, monitor_id)
        db.execute(
            "UPDATE cloud_machine_monitors SET calibration_status = 'pending', calibration_result = ?, updated_at = ? WHERE id = ?",
            (f"{phase.upper()}_PENDING_EDGE_RUNTIME", now_iso(), monitor_id),
        )
        db.commit()
    return cloud_calibration_status(monitor_id, request)


def _ensure_cloud_visual_rules(db):
    db.execute("""CREATE TABLE IF NOT EXISTS cloud_visual_rules (id TEXT PRIMARY KEY, cliente_id TEXT, unidade_id TEXT, camera_id TEXT NOT NULL, nome TEXT, tipo_evento TEXT NOT NULL, regiao_id TEXT, tempo_minimo REAL DEFAULT 0, severidade TEXT, cooldown_seconds REAL DEFAULT 0, alerta_inicio INTEGER DEFAULT 0, alerta_normalizacao INTEGER DEFAULT 0, condicao_json TEXT NOT NULL, ativo INTEGER DEFAULT 1, created_at TEXT NOT NULL)""")
    db.commit()

@api.get("/visual-rules")
def list_cloud_visual_rules(request: Request) -> list[dict[str, Any]]:
    user = _require_cloud_user(request)
    with connect() as db:
        init_cloud_db(db); _ensure_cloud_visual_rules(db)
        if user.get("role") == "admin_campex":
            rows = db.fetchall("SELECT * FROM cloud_visual_rules ORDER BY created_at DESC")
        else:
            rows = db.fetchall("SELECT * FROM cloud_visual_rules WHERE cliente_id = ? ORDER BY created_at DESC", (str(user.get("cliente_id") or ""),))
    for row in rows:
        row["condicao"] = json.loads(row.pop("condicao_json") or "{}")
    return rows

@api.post("/visual-rules")
def create_cloud_visual_rule(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    user = _require_cloud_user(request)
    camera_id = str(payload.get("camera_id") or "").strip()
    if not camera_id:
        raise HTTPException(status_code=400, detail="camera_id obrigatorio.")
    cliente_id = str(payload.get("cliente_id") or user.get("cliente_id") or "")
    unidade_id = str(payload.get("unidade_id") or "")
    with connect() as db:
        init_cloud_db(db); _ensure_cloud_visual_rules(db)
        if not cliente_id:
            context = db.fetchone("SELECT cliente_id, unidade_id FROM edge_events WHERE camera_id = ? ORDER BY received_at DESC LIMIT 1", (camera_id,))
            if context:
                cliente_id = str(context.get("cliente_id") or "")
                unidade_id = unidade_id or str(context.get("unidade_id") or "")
        rule_id = "rule_" + uuid.uuid4().hex[:12]
        db.execute("INSERT INTO cloud_visual_rules (id, cliente_id, unidade_id, camera_id, nome, tipo_evento, regiao_id, tempo_minimo, severidade, cooldown_seconds, alerta_inicio, alerta_normalizacao, condicao_json, ativo, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (rule_id, cliente_id, unidade_id, camera_id, payload.get("nome"), str(payload.get("tipo_evento") or ""), payload.get("regiao_id"), float(payload.get("tempo_minimo") or 0), payload.get("severidade"), float(payload.get("cooldown_seconds") or 0), 1 if payload.get("alerta_inicio") else 0, 1 if payload.get("alerta_normalizacao") else 0, json.dumps(payload.get("condicao") or {}), 1, now_iso()))
        db.commit()
        row = db.fetchone("SELECT * FROM cloud_visual_rules WHERE id = ?", (rule_id,))
    row["condicao"] = json.loads(row.pop("condicao_json") or "{}")
    return row


@api.get("/alert-deliveries")
def list_cloud_alert_deliveries(request: Request) -> list[dict[str, Any]]:
    user = _require_cloud_user(request)
    tenant = _tenant_for_user(user)
    with connect() as db:
        init_cloud_db(db)
        if tenant:
            rows = db.fetchall("SELECT * FROM report_deliveries WHERE cliente_id = ? ORDER BY created_at DESC LIMIT 100", (tenant,))
        else:
            rows = db.fetchall("SELECT * FROM report_deliveries ORDER BY created_at DESC LIMIT 100")
    return [
        {
            "id": row["id"],
            "recipient_name": row.get("recipient"),
            "destinatario": row.get("recipient"),
            "canal": "email",
            "status": row.get("status"),
            "attempts": row.get("attempts"),
            "last_attempt_at": row.get("updated_at"),
            "erro": row.get("last_error"),
            "is_test": False,
        }
        for row in rows
    ]


@api.get("/operations/events")
def list_cloud_operational_events(limit: int = 30, offset: int = 0) -> dict[str, Any]:
    with connect() as db:
        init_cloud_db(db)
        rows = db.fetchall(
            """
            SELECT *
            FROM edge_events
            ORDER BY COALESCE(inicio, received_at) DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )
    events = [_event_row_operation(row) for row in rows]
    return {"events": events, "limit": limit, "offset": offset}


@api.get("/operations/summary")
def cloud_operations_summary() -> dict[str, Any]:
    with connect() as db:
        init_cloud_db(db)
        rows = db.fetchall("SELECT * FROM edge_events ORDER BY COALESCE(inicio, received_at)")
    durations = [float(row["duracao"] or 0) for row in rows if row["tipo"] == "machine_stoppage"]
    total_stopped = sum(durations)
    return {
        "tempo_total_monitorado": 0,
        "tempo_maquina_ativa": 0,
        "tempo_maquina_parada": total_stopped,
        "percentual_atividade_estimada": 0,
        "quantidade_paradas": len(durations),
        "duracao_media_paradas": (total_stopped / len(durations)) if durations else 0,
        "maior_parada": max(durations) if durations else 0,
        "tempo_ativa_sem_operador": 0,
        "quantidade_ausencias_operador": 0,
        "disponibilidade_camera": 100 if rows else 0,
        "period": {"start": rows[0]["inicio"] if rows else now_iso(), "end": rows[-1]["fim"] or rows[-1]["received_at"] if rows else now_iso()},
    }


@api.get("/operations/timeline")
def cloud_operations_timeline() -> list[dict[str, Any]]:
    with connect() as db:
        init_cloud_db(db)
        rows = db.fetchall(
            """
            SELECT *
            FROM edge_events
            WHERE tipo IN ('machine_stoppage', 'restricted_area_occupied')
            ORDER BY COALESCE(inicio, received_at)
            LIMIT 200
            """
        )
    return [_event_row_timeline(row) for row in rows]


@api.get("/operations/current-status")
def cloud_current_status() -> dict[str, Any]:
    with connect() as db:
        init_cloud_db(db)
        row = db.fetchone("SELECT * FROM edge_events ORDER BY received_at DESC LIMIT 1")
    return {
        "machine_name": _metadata_value(row, "machine_name") if row else None,
        "machine_state": "NAO_CONFIGURADA",
        "operator_state": "AUSENTE",
        "people_count": 0,
        "camera_status": "online" if row else "unknown",
        "last_event": _event_row_public(row) if row else None,
    }


@api.post("/cameras/test-connection")
def cloud_camera_test_connection(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    _require_cloud_user(request)
    host = str(payload.get("host") or "").strip()
    rtsp_url = str(payload.get("rtsp_url") or "").strip()
    return {
        "compativel": False,
        "conexao_realizada": False,
        "video_recebido": False,
        "resolucao": None,
        "fps": None,
        "tipo_conexao": "rtsp",
        "referencia_segura": rtsp_url.split("@")[-1] if "@" in rtsp_url else (host or "RTSP"),
        "motivo_erro": "Teste de RTSP deve ser executado pelo Campex Edge instalado na rede da câmera.",
    }


@api.post("/cameras/rtsp")
def cloud_camera_rtsp(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    user = _require_cloud_user(request)
    _require_cloud_admin(user)
    try:
        rtsp = build_rtsp_url(
            host=str(payload.get("host") or "").strip() or None,
            port=int(payload.get("porta_rtsp") or 554),
            path=str(payload.get("caminho_rtsp") or "").strip() or None,
            username=str(payload.get("usuario") or "").strip() or None,
            password=str(payload.get("senha") or "") or None,
            full_url=str(payload.get("rtsp_url") or "").strip() or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    with connect() as db:
        init_cloud_db(db)
        unidade = _unit_for_user(db, user, str(payload.get("unidade_id") or "") or None)
        camera_id = _cloud_new_id("cam")
        name = str(payload.get("nome") or "Câmera").strip()
        requested_edge_id = str(payload.get("edge_id") or "").strip() or None
        if requested_edge_id:
            edge = db.fetchone("SELECT * FROM edge_devices WHERE id = ?", (requested_edge_id,))
            if not edge:
                raise HTTPException(status_code=404, detail="Edge não encontrado.")
            if edge["cliente_id"] != unidade["cliente_id"] or edge["unidade_id"] != unidade["id"]:
                raise HTTPException(status_code=403, detail="Edge pertence a outro cliente ou unidade.")
        encrypted_password = encrypt_secret(rtsp.password)
        db.execute(
            """
            INSERT INTO cloud_cameras (
                id, cliente_id, unidade_id, edge_id, nome, status, ativa,
                source_type, secure_ref, rtsp_host, rtsp_port, rtsp_path,
                rtsp_username, rtsp_password_encrypted, criado_em, atualizado_em
            )
            VALUES (?, ?, ?, ?, ?, 'configured', ?, 'rtsp', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                camera_id,
                unidade["cliente_id"],
                unidade["id"],
                requested_edge_id,
                name,
                1 if payload.get("ativa", True) else 0,
                rtsp.safe_url,
                rtsp.host,
                rtsp.port,
                rtsp.path,
                rtsp.username,
                encrypted_password,
                now_iso(),
                now_iso(),
            ),
        )
        db.commit()
        camera = db.fetchone("SELECT * FROM cloud_cameras WHERE id = ?", (camera_id,))
    return {
        "id": camera_id,
        "camera": _camera_public(camera),
        "teste": {
            "compativel": False,
            "conexao_realizada": False,
            "video_recebido": False,
            "motivo_erro": "Câmera cadastrada na Cloud. A conexão RTSP será validada pelo Edge local.",
            "referencia_segura": rtsp.safe_url,
        },
    }



def _cloud_read_model(request: Request, period: str = "day") -> dict[str, Any]:
    user = _require_cloud_user(request)

    with connect() as db:
        init_cloud_db(db)

        if user.get("role") == "admin_campex":
            rows = db.fetchall(
                "SELECT * FROM edge_events ORDER BY COALESCE(inicio, received_at) DESC LIMIT 500"
            )
        else:
            cliente_id = str(user.get("cliente_id") or "")
            rows = db.fetchall(
                """
                SELECT *
                FROM edge_events
                WHERE cliente_id = ?
                ORDER BY COALESCE(inicio, received_at) DESC
                LIMIT 500
                """,
                (cliente_id,),
            )

    stoppages = [
        row for row in rows
        if str(row.get("tipo") or "") == "machine_stoppage"
    ]

    downtime = sum(float(row.get("duracao") or 0) for row in stoppages)
    uuids = [row["event_uuid"] for row in stoppages if row.get("event_uuid")]

    attention = []
    patterns = []

    if stoppages:
        attention.append({
            "statement": f"{len(stoppages)} parada(s) de máquina registrada(s).",
            "number": len(stoppages),
            "why": f"Tempo acumulado parado: {round(downtime / 60, 1)} min.",
            "event_uuids": uuids[:20],
        })

    if len(stoppages) >= 2:
        patterns.append({
            "statement": "Há recorrência de paradas registradas.",
            "number": len(stoppages),
            "why": "Mais de uma parada foi sincronizada pelo Campex Edge.",
            "event_uuids": uuids[:20],
        })

    return {
        "period": period,
        "coverage": {
            "status": "SUFFICIENT" if rows else "INSUFFICIENT",
            "reason": (
                "Dados sincronizados pelo Campex Edge."
                if rows
                else "Ainda não há dados operacionais sincronizados."
            ),
        },
        "data_quality": {
            "classified_events": len(rows),
            "unknown_events": sum(
                1 for row in rows
                if "unknown" in str(row.get("tipo") or "").lower()
            ),
        },
        "summary": {
            "events_total": len(rows),
            "machine_stoppages": len(stoppages),
            "downtime_seconds": downtime,
        },
        "attention": attention,
        "patterns": patterns,
        "kpis": [
            {"name": "Paradas registradas", "value": len(stoppages)},
            {"name": "Tempo parado", "value": round(downtime / 60, 1), "unit": "min"},
        ],
        "confirmed_causes": [],
        "comparison": {},
        "events": [_event_row_public(row) for row in rows[:100]],
    }


@api.get("/operations/read-model/current")
def cloud_read_model_current(request: Request, period: str = "day") -> dict[str, Any]:
    payload = _cloud_read_model(request, period)
    payload["current"] = payload["events"][0] if payload["events"] else None
    return payload


@api.get("/operations/read-model/summary")
def cloud_read_model_summary(request: Request, period: str = "day") -> dict[str, Any]:
    return _cloud_read_model(request, period)


@api.get("/operations/read-model/insights")
def cloud_read_model_insights(request: Request, period: str = "day") -> dict[str, Any]:
    return _cloud_read_model(request, period)


@api.get("/operations/read-model/operational-data")
def cloud_read_model_operational_data(request: Request, period: str = "day") -> dict[str, Any]:
    return _cloud_read_model(request, period)


@api.get("/operations/read-model/losses")
def cloud_read_model_losses(request: Request, period: str = "day") -> dict[str, Any]:
    payload = _cloud_read_model(request, period)
    return {
        "period": payload["period"],
        "coverage": payload["coverage"],
        "losses": payload["attention"],
        "events": payload["events"],
    }


@api.get("/operations/read-model/comparison")
def cloud_read_model_comparison(request: Request, period: str = "day") -> dict[str, Any]:
    payload = _cloud_read_model(request, period)
    return {
        "period": payload["period"],
        "coverage": payload["coverage"],
        "comparison": payload["comparison"],
        "summary": payload["summary"],
    }


@api.get("/operations")
def cloud_operations() -> dict[str, Any]:
    return {"machines": []}


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(row.get("payload_json") or "{}")
    except json.JSONDecodeError:
        return {}


def _metadata_value(row: dict[str, Any] | None, key: str) -> Any:
    if not row:
        return None
    metadata = _payload(row).get("metadata") or {}
    return metadata.get(key)


def _event_row_public(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "event_uuid": row["event_uuid"],
        "cliente_id": row["cliente_id"],
        "unidade_id": row["unidade_id"],
        "camera_id": row["camera_id"],
        "tipo": row["tipo"],
        "inicio": row["inicio"],
        "fim": row["fim"],
        "duracao": row["duracao"],
        "confianca": row["confianca"],
        "severidade": row.get("severidade"),
        "status": row.get("status") or ("closed" if row.get("fim") else "open"),
        "criado_em": row["received_at"],
        "machine_name": _metadata_value(row, "machine_name"),
    }


def _event_row_operation(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "event_uuid": row["event_uuid"],
        "session_id": row["edge_id"],
        "camera_id": row["camera_id"],
        "machine_name": _metadata_value(row, "machine_name") or _metadata_value(row, "machine_monitor_id"),
        "event_type": row["tipo"],
        "previous_state": None,
        "new_state": _state_for_type(row["tipo"]),
        "started_at": row["inicio"] or row["received_at"],
        "ended_at": row["fim"],
        "duration_seconds": row["duracao"] or 0,
        "confidence": row["confianca"],
        "severidade": row.get("severidade"),
        "status": row.get("status") or ("closed" if row.get("fim") else "open"),
        "people_count": 0,
        "snapshot_path": row["midia_path"],
        "created_at": row["received_at"],
    }


def _event_row_timeline(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_type": row["tipo"],
        "state": _state_for_type(row["tipo"]),
        "start": row["inicio"] or row["received_at"],
        "end": row["fim"] or row["received_at"],
        "duration_seconds": row["duracao"] or 0,
    }


def _state_for_type(event_type: str) -> str:
    if event_type == "machine_stoppage":
        return "PARADA"
    if event_type == "active_without_operator":
        return "ATIVA_SEM_OPERADOR"
    if event_type == "restricted_area_occupied":
        return "OCUPADA"
    return event_type


# CAMPEX_UNIFIED_CLOUD_CORE_V1

@api.get("/users")
def cloud_users(request: Request) -> list[dict[str, Any]]:
    user = _require_cloud_user(request)

    with connect() as db:
        init_cloud_db(db)

        if user.get("role") == "admin_campex":
            rows = db.fetchall("""
                SELECT id, cliente_id, nome, email, role, ativo
                FROM users
                ORDER BY nome, email
            """)
        else:
            cliente_id = str(user.get("cliente_id") or "")
            rows = db.fetchall("""
                SELECT id, cliente_id, nome, email, role, ativo
                FROM users
                WHERE cliente_id = ?
                ORDER BY nome, email
            """, (cliente_id,))

    return rows


@api.post("/users")
def cloud_create_user(payload: CloudUserIn, request: Request) -> dict[str, Any]:
    user = _require_cloud_user(request)
    _require_cloud_admin(user)
    allowed = {"admin_cliente", "operador", "visualizador"}
    if payload.role not in allowed:
        raise HTTPException(status_code=400, detail="Função de usuário inválida.")
    cliente_id = _current_client_id(user, payload.cliente_id)
    with connect() as db:
        init_cloud_db(db)
        if not db.fetchone("SELECT id FROM clientes WHERE id = ?", (cliente_id,)):
            raise HTTPException(status_code=404, detail="Empresa não encontrada.")
        if db.fetchone("SELECT id FROM users WHERE email = ?", (payload.email.strip().lower(),)):
            raise HTTPException(status_code=409, detail="Já existe usuário com este e-mail.")
        user_id = create_user(
            db,
            email=payload.email,
            password=payload.senha,
            role=payload.role,
            cliente_id=cliente_id,
            nome=payload.nome,
        )
        row = db.fetchone(
            "SELECT id, cliente_id, nome, email, role, ativo FROM users WHERE id = ?",
            (user_id,),
        )
    return dict(row)


@api.get("/system/health")
def cloud_system_health(request: Request) -> dict[str, Any]:
    _require_cloud_user(request)

    with connect() as db:
        init_cloud_db(db)

        event_count = db.fetchone(
            "SELECT COUNT(*) AS total FROM edge_events"
        )
        edge_count = db.fetchone(
            "SELECT COUNT(*) AS total FROM edge_devices"
        )
        camera_count = db.fetchone(
            "SELECT COUNT(*) AS total FROM cloud_cameras"
        )
        online_count = db.fetchone("""
            SELECT COUNT(*) AS total
            FROM edge_devices
            WHERE last_seen_at IS NOT NULL
        """)

    return {
        "status": "ok",
        "database": "cloud",
        "events": int((event_count or {}).get("total") or 0),
        "edges": int((edge_count or {}).get("total") or 0),
        "cameras_online": 0,
        "cameras_offline": int((camera_count or {}).get("total") or 0),
        "ai_active": 0,
        "ai_inactive": int((camera_count or {}).get("total") or 0),
        "ultimo_frame": None,
        "ultimo_evento": None,
        "ultimo_email": None,
        "edges_with_contact": int((online_count or {}).get("total") or 0),
    }


@api.get("/pilot/checklist")
def cloud_pilot_checklist(request: Request) -> dict[str, Any]:
    setup = cloud_setup_operation(request)
    checks = {
        "empresa": bool(setup["clientes"]),
        "unidade": bool(setup["unidades"]),
        "contexto_operacional": bool(setup["areas"] and setup["processes"] and setup["assets"]),
        "camera_cadastrada": bool(setup["cameras"]),
        "edge_configurado": False,
    }
    with connect() as db:
        init_cloud_db(db)
        user = _require_cloud_user(request)
        tenant = _tenant_for_user(user)
        if tenant:
            edge = db.fetchone("SELECT id FROM edge_devices WHERE cliente_id = ? LIMIT 1", (tenant,))
        else:
            edge = db.fetchone("SELECT id FROM edge_devices LIMIT 1")
        checks["edge_configurado"] = bool(edge)
    return {"ready": all(checks.values()), "checks": checks}


@api.get("/events/stream")
def cloud_events_stream(request: Request) -> StreamingResponse:
    _require_cloud_user(request)

    def iterator():
        yield "event: ping\ndata: {\"type\":\"connected\"}\n\n"

    return StreamingResponse(iterator(), media_type="text/event-stream")



# CAMPEX_UNIFIED_EVENTS_V1

def _cloud_event_for_user(db, request, event_id):
    user = _require_cloud_user(request)
    row = db.fetchone("SELECT * FROM edge_events WHERE id = ? OR event_uuid = ? LIMIT 1", (event_id, event_id))
    if not row:
        raise HTTPException(status_code=404, detail="Evento nao encontrado.")
    if user.get("role") != "admin_campex" and str(row.get("cliente_id") or "") != str(user.get("cliente_id") or ""):
        raise HTTPException(status_code=403, detail="Evento de outro cliente.")
    return row, user


@api.get("/eventos/{evento_id}/detail")
def cloud_event_detail(evento_id: str, request: Request):
    with connect() as db:
        init_cloud_db(db)
        row, _ = _cloud_event_for_user(db, request, evento_id)
        data = _event_row_public(row)
        data["payload"] = _payload(row)
        return data


@api.get("/eventos/{evento_id}")
def cloud_event_get(evento_id: str, request: Request):
    return cloud_event_detail(evento_id, request)


@api.get("/eventos/{evento_id}/evidence")
def cloud_event_evidence(evento_id: str, request: Request):
    with connect() as db:
        init_cloud_db(db)
        row, _ = _cloud_event_for_user(db, request, evento_id)
        path = str(row.get("midia_path") or "").strip()
    if not path:
        raise HTTPException(status_code=404, detail="Este evento não possui evidência visual disponível.")
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = ROOT / path
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail="Evidência não encontrada no armazenamento Cloud.")
    return FileResponse(resolved)


@api.get("/eventos/{evento_id}/replay")
def cloud_event_replay(evento_id: str, request: Request):
    raise HTTPException(status_code=404, detail="Replay causal não está disponível na Cloud para este evento.")


def _cloud_update_event(db, row, status_value=None, human_context=None):
    payload = _payload(row)
    if human_context:
        current = payload.get("human_context") or {}
        current.update({k: v for k, v in human_context.items() if v is not None})
        payload["human_context"] = current
    if status_value:
        payload["workflow_status"] = status_value
    db.execute("UPDATE edge_events SET status = COALESCE(?, status), payload_json = ? WHERE id = ?", (status_value, json.dumps(payload), row["id"]))
    db.commit()
    updated = db.fetchone("SELECT * FROM edge_events WHERE id = ?", (row["id"],))
    data = _event_row_public(updated)
    data["payload"] = _payload(updated)
    return data


@api.patch("/eventos/{evento_id}")
def cloud_patch_event(evento_id: str, payload: dict[str, Any], request: Request):
    with connect() as db:
        init_cloud_db(db)
        row, _ = _cloud_event_for_user(db, request, evento_id)
        return _cloud_update_event(db, row, status_value=payload.get("status"))


@api.patch("/eventos/{evento_id}/cause")
def cloud_event_cause(evento_id: str, payload: dict[str, Any], request: Request):
    with connect() as db:
        init_cloud_db(db)
        row, user = _cloud_event_for_user(db, request, evento_id)
        return _cloud_update_event(
            db,
            row,
            human_context={
                "confirmed_cause": payload.get("cause_category") or payload.get("confirmed_cause"),
                "human_notes": payload.get("cause_notes") or payload.get("human_notes"),
                "updated_by": user.get("email"),
                "updated_at": now_iso(),
            },
        )


def _cloud_event_human(payload, user):
    return {
        "confirmed_cause": payload.get("confirmed_cause"),
        "action_taken": payload.get("action_taken"),
        "human_notes": payload.get("human_notes"),
        "updated_by": user.get("email"),
        "updated_at": now_iso(),
    }


@api.post("/eventos/{evento_id}/acknowledge")
def cloud_ack_event(evento_id: str, payload: dict[str, Any], request: Request):
    with connect() as db:
        init_cloud_db(db)
        row, user = _cloud_event_for_user(db, request, evento_id)
        return _cloud_update_event(db, row, "acknowledged", _cloud_event_human(payload, user))


@api.patch("/eventos/{evento_id}/human-context")
def cloud_human_context(evento_id: str, payload: dict[str, Any], request: Request):
    with connect() as db:
        init_cloud_db(db)
        row, user = _cloud_event_for_user(db, request, evento_id)
        return _cloud_update_event(db, row, human_context=_cloud_event_human(payload, user))


@api.post("/eventos/{evento_id}/resolve")
def cloud_resolve_event(evento_id: str, payload: dict[str, Any], request: Request):
    with connect() as db:
        init_cloud_db(db)
        row, user = _cloud_event_for_user(db, request, evento_id)
        return _cloud_update_event(db, row, "resolved", _cloud_event_human(payload, user))


def _ensure_cloud_alert_recipients(db):
    db.execute("""CREATE TABLE IF NOT EXISTS cloud_alert_recipients (id TEXT PRIMARY KEY, cliente_id TEXT, nome TEXT NOT NULL, email TEXT NOT NULL, ativo INTEGER NOT NULL DEFAULT 1, event_types_json TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL)""")
    db.commit()

@api.get("/alert-recipients")
def cloud_alert_recipients(request: Request):
    user = _require_cloud_user(request)
    with connect() as db:
        init_cloud_db(db)
        _ensure_cloud_alert_recipients(db)
        if user.get("role") == "admin_campex":
            rows = db.fetchall("SELECT * FROM cloud_alert_recipients ORDER BY nome, email")
        else:
            rows = db.fetchall("SELECT * FROM cloud_alert_recipients WHERE cliente_id = ? ORDER BY nome, email", (str(user.get("cliente_id") or ""),))
    for row in rows:
        row["event_types"] = json.loads(row.pop("event_types_json") or "[]")
        row["ativo"] = bool(row.get("ativo"))
    return rows

@api.post("/alert-recipients")
def cloud_create_alert_recipient(payload: dict[str, Any], request: Request):
    user = _require_cloud_user(request)
    cliente_id = str(payload.get("cliente_id") or user.get("cliente_id") or "")
    if user.get("role") != "admin_campex" and cliente_id != str(user.get("cliente_id") or ""):
        raise HTTPException(status_code=403, detail="Cliente nao autorizado.")
    recipient_id = "rec_" + uuid.uuid4().hex[:12]
    with connect() as db:
        init_cloud_db(db)
        _ensure_cloud_alert_recipients(db)
        db.execute("INSERT INTO cloud_alert_recipients (id, cliente_id, nome, email, ativo, event_types_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (recipient_id, cliente_id, str(payload.get("nome") or "Responsavel"), str(payload.get("email") or ""), 1 if payload.get("ativo", True) else 0, json.dumps(payload.get("event_types") or []), now_iso()))
        db.commit()
        row = db.fetchone("SELECT * FROM cloud_alert_recipients WHERE id = ?", (recipient_id,))
    row["event_types"] = json.loads(row.pop("event_types_json") or "[]")
    row["ativo"] = bool(row.get("ativo"))
    return row

@api.post("/alert-recipients/{recipient_id}/test")
def cloud_test_alert_recipient(recipient_id: str, request: Request):
    user = _require_cloud_user(request)
    with connect() as db:
        init_cloud_db(db)
        _ensure_cloud_alert_recipients(db)
        row = db.fetchone("SELECT * FROM cloud_alert_recipients WHERE id = ?", (recipient_id,))
        if not row:
            raise HTTPException(status_code=404, detail="Responsavel nao encontrado.")
        if user.get("role") != "admin_campex" and str(row.get("cliente_id") or "") != str(user.get("cliente_id") or ""):
            raise HTTPException(status_code=403, detail="Responsavel de outro cliente.")
    return {"status": "ready", "recipient_id": recipient_id, "email": row["email"]}


@api.patch("/alert-recipients/{recipient_id}")
def cloud_patch_alert_recipient(recipient_id: str, payload: dict[str, Any], request: Request):
    user = _require_cloud_user(request)
    _require_cloud_admin(user)
    with connect() as db:
        init_cloud_db(db)
        _ensure_cloud_alert_recipients(db)
        row = db.fetchone("SELECT * FROM cloud_alert_recipients WHERE id = ?", (recipient_id,))
        if not row:
            raise HTTPException(status_code=404, detail="Responsavel nao encontrado.")
        _require_same_client(user, str(row.get("cliente_id") or ""), "Responsavel de outro cliente.")
        nome = str(payload.get("nome") if payload.get("nome") is not None else row["nome"]).strip()
        email = str(payload.get("email") if payload.get("email") is not None else row["email"]).strip()
        ativo = row.get("ativo") if "ativo" not in payload else (1 if payload.get("ativo") else 0)
        event_types = payload.get("event_types")
        if event_types is None:
            event_types_json = row.get("event_types_json") or "[]"
        else:
            event_types_json = json.dumps(event_types)
        db.execute(
            "UPDATE cloud_alert_recipients SET nome = ?, email = ?, ativo = ?, event_types_json = ? WHERE id = ?",
            (nome, email, ativo, event_types_json, recipient_id),
        )
        db.commit()
        updated = db.fetchone("SELECT * FROM cloud_alert_recipients WHERE id = ?", (recipient_id,))
    updated["event_types"] = json.loads(updated.pop("event_types_json") or "[]")
    updated["ativo"] = bool(updated.get("ativo"))
    return updated


@api.delete("/alert-recipients/{recipient_id}")
def cloud_delete_alert_recipient(recipient_id: str, request: Request):
    user = _require_cloud_user(request)
    _require_cloud_admin(user)
    with connect() as db:
        init_cloud_db(db)
        _ensure_cloud_alert_recipients(db)
        row = db.fetchone("SELECT * FROM cloud_alert_recipients WHERE id = ?", (recipient_id,))
        if not row:
            raise HTTPException(status_code=404, detail="Responsavel nao encontrado.")
        _require_same_client(user, str(row.get("cliente_id") or ""), "Responsavel de outro cliente.")
        db.execute("DELETE FROM cloud_alert_recipients WHERE id = ?", (recipient_id,))
        db.commit()
    return {"id": recipient_id, "deleted": True}


@api.post("/alert-deliveries/{delivery_id}/retry")
def cloud_retry_alert_delivery(delivery_id: str, request: Request):
    user = _require_cloud_user(request)
    tenant = _tenant_for_user(user)
    with connect() as db:
        init_cloud_db(db)
        row = db.fetchone("SELECT * FROM report_deliveries WHERE id = ?", (delivery_id,))
        if not row:
            raise HTTPException(status_code=404, detail="Entrega nao encontrada.")
        if tenant and str(row.get("cliente_id") or "") != tenant:
            raise HTTPException(status_code=403, detail="Entrega de outro cliente.")
        db.execute(
            "UPDATE report_deliveries SET status = 'pending', updated_at = ? WHERE id = ?",
            (now_iso(), delivery_id),
        )
        db.commit()
    return {"id": delivery_id, "status": "pending"}


# CAMPEX_UNIFIED_REPORTS_V1

def _ensure_cloud_report_schedules(db):
    db.execute("CREATE TABLE IF NOT EXISTS report_schedules (tenant_id TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 1, send_time TEXT NOT NULL DEFAULT '08:00', timezone TEXT NOT NULL DEFAULT 'America/Sao_Paulo', channel TEXT NOT NULL DEFAULT 'email', email TEXT, recipient_name TEXT, updated_at TEXT NOT NULL)")
    db.commit()

def _cloud_report_tenant(user, tenant_id):
    resolved = str(tenant_id or user.get("cliente_id") or "")
    if not resolved:
        raise HTTPException(status_code=400, detail="Empresa nao informada.")
    if user.get("role") != "admin_campex" and resolved != str(user.get("cliente_id") or ""):
        raise HTTPException(status_code=403, detail="Cliente nao autorizado.")
    return resolved

@api.get("/reports/tenants")
def cloud_reports_tenants(request: Request):
    user = _require_cloud_user(request)
    with connect() as db:
        init_cloud_db(db)
        if user.get("role") == "admin_campex":
            rows = db.fetchall("SELECT id, nome FROM clientes ORDER BY nome")
        else:
            rows = db.fetchall("SELECT id, nome FROM clientes WHERE id = ?", (str(user.get("cliente_id") or ""),))
    return {"tenants": rows}

@api.get("/reports/schedule")
def cloud_reports_schedule(request: Request, tenant_id: str = ""):
    user = _require_cloud_user(request)
    tenant_id = _cloud_report_tenant(user, tenant_id)
    with connect() as db:
        init_cloud_db(db); _ensure_cloud_report_schedules(db)
        row = db.fetchone("SELECT * FROM report_schedules WHERE tenant_id = ?", (tenant_id,))
    return {"tenant_id": tenant_id, "schedule": row or {"tenant_id": tenant_id, "enabled": 1, "send_time": "08:00", "timezone": "America/Sao_Paulo", "channel": "email", "email": "", "recipient_name": ""}}


@api.put("/reports/schedule")
def cloud_save_report_schedule(payload: dict[str, Any], request: Request):
    user = _require_cloud_user(request)
    tenant_id = _cloud_report_tenant(user, str(payload.get("tenant_id") or ""))
    with connect() as db:
        init_cloud_db(db); _ensure_cloud_report_schedules(db)
        db.execute("DELETE FROM report_schedules WHERE tenant_id = ?", (tenant_id,))
        db.execute("INSERT INTO report_schedules (tenant_id, enabled, send_time, timezone, channel, email, recipient_name, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (tenant_id, 1 if payload.get("enabled", True) else 0, str(payload.get("send_time") or "08:00"), str(payload.get("timezone") or "America/Sao_Paulo"), str(payload.get("channel") or "email"), str(payload.get("email") or ""), str(payload.get("recipient_name") or ""), now_iso()))
        db.commit()
        row = db.fetchone("SELECT * FROM report_schedules WHERE tenant_id = ?", (tenant_id,))
    return {"status": "ok", "schedule": row}


def _cloud_report_preview_data(db, tenant_id):
    rows = db.fetchall("SELECT * FROM edge_events WHERE cliente_id = ? ORDER BY COALESCE(inicio, received_at) DESC LIMIT 100", (tenant_id,))
    stoppages = [r for r in rows if str(r.get("tipo") or "") == "machine_stoppage"]
    downtime = sum(float(r.get("duracao") or 0) for r in stoppages)
    return {
        "generated_at": now_iso(),
        "summary": {
            "events_total": len(rows),
            "machines": {
                "stoppages": len(stoppages),
                "downtime_seconds": downtime,
                "downtime_minutes": round(downtime / 60, 1),
            },
        },
        "main_events": [_event_row_public(r) for r in rows[:5]],
        "coverage": {
            "status": "SUFFICIENT" if rows else "INSUFFICIENT",
            "reason": "Dados sincronizados pelo Campex Edge." if rows else "Ainda nao existem dados operacionais suficientes.",
        },
    }


@api.get("/reports/preview")
def cloud_reports_preview(request: Request, tenant_id: str = ""):
    user = _require_cloud_user(request)
    tenant_id = _cloud_report_tenant(user, tenant_id)
    with connect() as db:
        init_cloud_db(db)
        report = _cloud_report_preview_data(db, tenant_id)
    return {"report": report}


@api.post("/reports/send-now")
def cloud_reports_send_now(request: Request, tenant_id: str = ""):
    user = _require_cloud_user(request)
    tenant_id = _cloud_report_tenant(user, tenant_id)
    with connect() as db:
        init_cloud_db(db); _ensure_cloud_report_schedules(db)
        schedule = db.fetchone("SELECT * FROM report_schedules WHERE tenant_id = ?", (tenant_id,))
        if not schedule:
            raise HTTPException(status_code=404, detail="Configure o relatorio antes de enviar.")
        email = str(schedule.get("email") or "").strip()
        if not email:
            raise HTTPException(status_code=400, detail="Nenhum email configurado.")
        report = _cloud_report_preview_data(db, tenant_id)

    subject = "Campex | Relatorio Operacional"
    text_body = "Campex - Relatorio Operacional\n\nEventos: %s\nParadas: %s\nTempo parado: %s min" % (report["summary"]["events_total"], report["summary"]["machines"]["stoppages"], report["summary"]["machines"]["downtime_minutes"])
    html_body = "<h2>Campex | Relatorio Operacional</h2><p>Eventos: %s</p><p>Paradas: %s</p><p>Tempo parado: %s min</p>" % (report["summary"]["events_total"], report["summary"]["machines"]["stoppages"], report["summary"]["machines"]["downtime_minutes"])
    delivery = ReportDeliveryIn(delivery_id="rpt_" + uuid.uuid4().hex[:16], cliente_id=tenant_id, recipient=email, subject=subject, text_body=text_body, html_body=html_body)

    try:
        provider_message_id = _send_cloud_report_email(delivery)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {"status": "sent", "destination": email, "provider_message_id": provider_message_id, "report": report}
