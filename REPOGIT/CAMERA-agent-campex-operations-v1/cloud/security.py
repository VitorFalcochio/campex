from __future__ import annotations

import hashlib
import hmac
import secrets


def hash_edge_secret(secret: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.sha256(f"{salt}:{secret}".encode("utf-8")).hexdigest()
    return f"sha256${salt}${digest}"


def verify_edge_secret(secret: str, stored: str) -> bool:
    try:
        _algorithm, salt, digest = stored.split("$", 2)
    except ValueError:
        return False
    candidate = hashlib.sha256(f"{salt}:{secret}".encode("utf-8")).hexdigest()
    return hmac.compare_digest(candidate, digest)
