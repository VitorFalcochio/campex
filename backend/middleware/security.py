from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from threading import Lock

from starlette.types import ASGIApp, Receive, Scope, Send


logger = logging.getLogger("campex.security")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-XSS-Protection": "0",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'none'; "
        "form-action 'self'"
    ),
    "Cache-Control": "no-store",
}


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def _send(message):
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers") or [])
                for name, value in SECURITY_HEADERS.items():
                    headers[name.encode("latin-1")] = value.encode("latin-1")
                message["headers"] = list(headers.items())
            await send(message)

        await self.app(scope, receive, _send)


class RateLimitMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        enabled: bool,
        max_requests: int,
        window_seconds: float,
        unauthorized_only: bool = False,
    ) -> None:
        self.app = app
        self.enabled = enabled
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.unauthorized_only = unauthorized_only
        self._buckets: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def _client_ip(self, scope: Scope) -> str:
        headers = dict(scope.get("headers") or [])
        forwarded = headers.get(b"x-forwarded-for")
        if forwarded:
            return forwarded.decode("latin-1").split(",")[0].strip()
        client = scope.get("client")
        if client and isinstance(client, tuple) and len(client) >= 1:
            return str(client[0])
        return "unknown"

    def _check_limit(self, client_ip: str) -> bool:
        now = time.monotonic()
        window = self.window_seconds
        with self._lock:
            bucket = self._buckets[client_ip]
            cutoff = now - window
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self.max_requests:
                return False
            bucket.append(now)
            return True

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self.enabled or scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if self.unauthorized_only and scope.get("path", "").startswith("/api/v1") and scope.get("path") != "/api/v1/health":
            await self.app(scope, receive, send)
            return

        client_ip = self._client_ip(scope)
        if not self._check_limit(client_ip):
            message = b'{"detail": "Rate limit exceeded. Please reduce request frequency."}'
            await send(
                {
                    "type": "http.response.start",
                    "status": 429,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(message)).encode("ascii")),
                        (b"retry-after", b"60"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": message})
            return

        await self.app(scope, receive, send)
