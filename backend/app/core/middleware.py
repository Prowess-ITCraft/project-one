"""Pure ASGI middleware: request id + access log, security headers, body size cap, metrics."""

from __future__ import annotations

import re
import time
import uuid
from typing import Any

import structlog
from prometheus_client import Counter, Histogram
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import get_settings

log = structlog.get_logger("access")

HTTP_REQUESTS = Counter("p1_http_requests_total", "HTTP requests", ["method", "route", "status"])
HTTP_LATENCY = Histogram(
    "p1_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "route"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,64}$")

# Upload routes get the larger cap; everything else gets the JSON cap.
_UPLOAD_PATH_SUFFIXES = ("/files", "/files/")


def client_ip(scope: Scope) -> str:
    """Take the client IP from X-Forwarded-For, trusting only the configured number of proxies."""
    hops = get_settings().trusted_proxy_hops
    headers = Headers(scope=scope)
    xff = headers.get("x-forwarded-for")
    if xff and hops > 0:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if len(parts) >= hops:
            return parts[-hops]
    client = scope.get("client")
    return client[0] if client else "unknown"


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        incoming = headers.get("x-request-id", "")
        request_id = incoming if _REQUEST_ID_RE.match(incoming) else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        scope["state"]["client_ip"] = client_ip(scope)
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        start = time.perf_counter()
        status_holder: dict[str, int] = {"status": 500}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                MutableHeaders(scope=message)["x-request-id"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed = time.perf_counter() - start
            route = scope.get("route")
            route_path: str = getattr(route, "path", "unmatched")
            HTTP_REQUESTS.labels(scope["method"], route_path, str(status_holder["status"])).inc()
            HTTP_LATENCY.labels(scope["method"], route_path).observe(elapsed)
            if route_path not in ("/healthz", "/metrics"):
                log.info(
                    "request",
                    method=scope["method"],
                    path=scope["path"],
                    route=route_path,
                    status=status_holder["status"],
                    duration_ms=round(elapsed * 1000, 1),
                    client_ip=scope["state"]["client_ip"],
                )


class SecurityHeadersMiddleware:
    API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
    # Swagger UI loads its bundle from jsdelivr.
    DOCS_CSP = (
        "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "img-src 'self' data: https://fastapi.tiangolo.com; frame-ancestors 'none'"
    )

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.hsts = get_settings().is_prod

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        is_docs = scope["path"] in ("/docs", "/redoc", "/docs/oauth2-redirect")

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                h = MutableHeaders(scope=message)
                h["x-content-type-options"] = "nosniff"
                h["x-frame-options"] = "DENY"
                h["referrer-policy"] = "no-referrer"
                h["permissions-policy"] = "camera=(), microphone=(), geolocation=()"
                h["cross-origin-opener-policy"] = "same-origin"
                h["content-security-policy"] = self.DOCS_CSP if is_docs else self.API_CSP
                if "cache-control" not in h:
                    h["cache-control"] = "no-store"
                if self.hsts:
                    h["strict-transport-security"] = "max-age=63072000; includeSubDomains"
            await send(message)

        await self.app(scope, receive, send_wrapper)


class BodySizeLimitMiddleware:
    """Rejects bodies over the cap, by Content-Length up front and by counting streamed bytes."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        s = get_settings()
        self.json_cap = s.max_json_body_bytes
        self.upload_cap = s.max_upload_bytes

    def _cap_for(self, path: str) -> int:
        return self.upload_cap if path.endswith(_UPLOAD_PATH_SUFFIXES) else self.json_cap

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            await self.app(scope, receive, send)
            return
        cap = self._cap_for(scope["path"])
        declared = Headers(scope=scope).get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > cap:
            await _reject_too_large(scope, send, cap)
            return
        received = 0
        too_large = False

        async def limited_receive() -> Message:
            nonlocal received, too_large
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > cap:
                    too_large = True
                    raise _BodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _BodyTooLarge:
            await _reject_too_large(scope, send, cap)


class _BodyTooLarge(Exception):
    pass


async def _reject_too_large(scope: Scope, send: Send, cap: int) -> None:
    import json

    body: dict[str, Any] = {
        "type": "https://errors.project-one.itcraft/payload_too_large",
        "title": "The request is too large",
        "status": 413,
        "code": "payload_too_large",
        "detail": f"The limit for this endpoint is {cap} bytes.",
        "instance": scope["path"],
    }
    raw = json.dumps(body).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/problem+json"),
                (b"content-length", str(len(raw)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": raw})
