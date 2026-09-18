from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, Request

from app.models import new_id, row_to_dict
from app.security import hash_password, token_hash, verify_password

ROLES = {"admin_campex", "admin_cliente", "operador", "visualizador"}
ADMIN_ROLES = {"admin_campex", "admin_cliente"}


def create_user(connection, email: str, password: str, role: str, cliente_id: str | None = None, nome: str | None = None) -> str:
    if role not in ROLES:
        raise ValueError("Funcao invalida.")
    user_id = new_id("usr")
    connection.execute(
        """
        INSERT INTO users (id, cliente_id, nome, email, password_hash, role)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (user_id, cliente_id, nome, email.lower().strip(), hash_password(password), role),
    )
    connection.commit()
    return user_id


def update_user_password(connection, email: str, new_password: str) -> bool:
    cursor = connection.execute(
        "UPDATE users SET password_hash = ?, atualizado_em = CURRENT_TIMESTAMP WHERE email = ?",
        (hash_password(new_password), email.lower().strip()),
    )
    connection.commit()
    return cursor.rowcount > 0


def authenticate(connection, email: str, password: str) -> dict[str, Any] | None:
    row = connection.execute("SELECT * FROM users WHERE email = ? AND ativo = 1", (email.lower().strip(),)).fetchone()
    if row is None or not verify_password(password, row["password_hash"]):
        return None
    data = row_to_dict(row)
    data.pop("password_hash", None)
    return data


def find_active_user_by_email(connection, email: str) -> dict[str, Any] | None:
    row = connection.execute("SELECT * FROM users WHERE email = ? AND ativo = 1", (email.lower().strip(),)).fetchone()
    if row is None:
        return None
    data = row_to_dict(row)
    data.pop("password_hash", None)
    return data


def create_session(connection, user_id: str, hours: int = 12) -> str:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=hours)
    connection.execute(
        "INSERT INTO user_sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
        (token_hash(token), user_id, expires.isoformat()),
    )
    connection.commit()
    return token


def delete_session(connection, token: str) -> None:
    connection.execute("DELETE FROM user_sessions WHERE token_hash = ?", (token_hash(token),))
    connection.commit()


def current_user(connection, token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    row = connection.execute(
        """
        SELECT u.*
        FROM user_sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.token_hash = ? AND s.expires_at > ?
        """,
        (token_hash(token), datetime.now(timezone.utc).isoformat()),
    ).fetchone()
    if row is None:
        return None
    data = row_to_dict(row)
    data.pop("password_hash", None)
    return data


def users_exist(connection) -> bool:
    row = connection.execute("SELECT COUNT(*) AS total FROM users").fetchone()
    return bool(row and row["total"])


def get_request_user(request: Request, connection) -> dict[str, Any] | None:
    return current_user(connection, request.cookies.get("campex_session"))


def require_user(request: Request, connection) -> dict[str, Any]:
    user = get_request_user(request, connection)
    if user is None and not users_exist(connection):
        return {"id": "bootstrap", "role": "admin_campex", "cliente_id": None, "email": "bootstrap@local"}
    if user is None:
        raise HTTPException(status_code=401, detail="Login necessario.")
    return user


def require_role(user: dict[str, Any], allowed: set[str]) -> None:
    if user["role"] not in allowed:
        raise HTTPException(status_code=403, detail="Permissao insuficiente.")


def tenant_filter(user: dict[str, Any]) -> str | None:
    return None if user["role"] == "admin_campex" else user.get("cliente_id")
