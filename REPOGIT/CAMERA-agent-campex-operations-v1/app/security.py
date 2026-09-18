from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from pathlib import Path

from app.config import ROOT


PLACEHOLDER_KEYS = {
    "campex-dev-change-me",
    "troque-antes-do-piloto",
    "troque-por-uma-chave-grande-antes-do-piloto",
    "troque-por-outra-chave-grande-se-desejar",
}


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
    return f"pbkdf2_sha256${salt}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        _algo, salt, expected = stored_hash.split("$", 2)
    except ValueError:
        return False
    return hmac.compare_digest(hash_password(password, salt).split("$", 2)[2], expected)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _configured_key() -> str | None:
    raw = os.getenv("CAMPEX_CREDENTIAL_KEY") or os.getenv("CAMPEX_SECRET_KEY")
    return raw.strip() if raw else None


def require_configured_credential_key() -> None:
    raw = _configured_key()
    if not raw or raw in PLACEHOLDER_KEYS or len(raw) < 24:
        raise RuntimeError("Configure CAMPEX_CREDENTIAL_KEY com uma chave segura antes de iniciar em produção.")


def _key() -> bytes:
    raw = _configured_key()
    if not raw:
        if os.getenv("CAMPEX_ENV", "development").lower() == "production":
            require_configured_credential_key()
        local_key = ROOT / "data" / "credential_key"
        local_key.parent.mkdir(parents=True, exist_ok=True)
        if local_key.exists():
            raw = local_key.read_text(encoding="utf-8").strip()
        else:
            raw = secrets.token_urlsafe(48)
            local_key.write_text(raw, encoding="utf-8")
            try:
                local_key.chmod(0o600)
            except OSError:
                pass
    if raw in PLACEHOLDER_KEYS:
        if os.getenv("CAMPEX_ENV", "development").lower() == "production":
            require_configured_credential_key()
    return hashlib.sha256(raw.encode()).digest()


def encrypt_secret(value: str | None) -> str | None:
    if not value:
        return None
    key = _key()
    nonce = secrets.token_bytes(16)
    stream = hashlib.pbkdf2_hmac("sha256", key, nonce, 100_000, dklen=len(value.encode()))
    cipher = bytes(a ^ b for a, b in zip(value.encode(), stream))
    mac = hmac.new(key, nonce + cipher, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(nonce + mac + cipher).decode()


def decrypt_secret(payload: str | None) -> str | None:
    if not payload:
        return None
    raw = base64.urlsafe_b64decode(payload.encode())
    nonce, mac, cipher = raw[:16], raw[16:48], raw[48:]
    key = _key()
    expected = hmac.new(key, nonce + cipher, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expected):
        raise ValueError("Credencial criptografada invalida.")
    stream = hashlib.pbkdf2_hmac("sha256", key, nonce, 100_000, dklen=len(cipher))
    return bytes(a ^ b for a, b in zip(cipher, stream)).decode()


def mask_sensitive_error(text: str | None) -> str | None:
    if not text:
        return text
    lowered = text.lower()
    if "rtsp://" in lowered or "rtsps://" in lowered or "password" in lowered or "senha" in lowered:
        return "Erro tecnico com detalhe sensivel ocultado."
    return text[:300]
