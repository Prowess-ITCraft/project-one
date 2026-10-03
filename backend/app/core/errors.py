"""RFC 9457 problem+json errors with stable codes. Stack traces never leave the server."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.orm.exc import StaleDataError
from starlette.exceptions import HTTPException as StarletteHTTPException

log = structlog.get_logger(__name__)

PROBLEM_JSON = "application/problem+json"
TYPE_BASE = "https://errors.project-one.itcraft/"


class AppError(Exception):
    """Base for expected, user-facing errors. `code` is stable and documented."""

    status: int = 400
    code: str = "bad_request"
    title: str = "Bad request"

    def __init__(
        self,
        detail: str | None = None,
        *,
        code: str | None = None,
        extra: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(detail or self.title)
        self.detail = detail or self.title
        if code:
            self.code = code
        self.extra = extra or {}
        self.headers = headers or {}


class ValidationFailed(AppError):
    status, code, title = 422, "validation_failed", "Some fields are not valid"


class Unauthenticated(AppError):
    status, code, title = 401, "unauthenticated", "Sign in to continue"


class Forbidden(AppError):
    status, code, title = 403, "forbidden", "You do not have permission to do this"


class NotFound(AppError):
    status, code, title = 404, "not_found", "Not found"


class Conflict(AppError):
    status, code, title = 409, "conflict", "This conflicts with the current state"


class StaleVersion(Conflict):
    code, title = "stale_version", "Someone else changed this record. Reload and try again"


class PayloadTooLarge(AppError):
    status, code, title = 413, "payload_too_large", "The request is too large"


class UnsupportedMedia(AppError):
    status, code, title = 415, "unsupported_media_type", "This file type is not allowed"


class RateLimited(AppError):
    status, code, title = 429, "rate_limited", "Too many requests. Wait a moment and try again"


class Locked(AppError):
    status, code, title = 423, "locked", "This account is temporarily locked"


class ServiceUnavailable(AppError):
    status, code, title = 503, "service_unavailable", "A required service is unavailable"


def problem(
    request: Request,
    *,
    status: int,
    code: str,
    title: str,
    detail: str,
    extra: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": TYPE_BASE + code,
        "title": title,
        "status": status,
        "detail": detail,
        "code": code,
        "instance": request.url.path,
    }
    request_id = getattr(request.state, "request_id", None)
    if request_id:
        body["request_id"] = request_id
    if extra:
        body.update(extra)
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON, headers=headers)


_STATUS_CODES = {
    400: ("bad_request", "Bad request"),
    401: ("unauthenticated", "Sign in to continue"),
    403: ("forbidden", "You do not have permission to do this"),
    404: ("not_found", "Not found"),
    405: ("method_not_allowed", "Method not allowed"),
    406: ("not_acceptable", "Not acceptable"),
    413: ("payload_too_large", "The request is too large"),
    415: ("unsupported_media_type", "Unsupported media type"),
}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return problem(
            request,
            status=exc.status,
            code=exc.code,
            title=exc.title,
            detail=exc.detail,
            extra=exc.extra,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {
                "loc": [str(p) for p in e.get("loc", ())],
                "msg": e.get("msg", ""),
                "type": e.get("type", ""),
            }
            for e in exc.errors()
        ]
        return problem(
            request,
            status=422,
            code="validation_failed",
            title="Some fields are not valid",
            detail="Check the listed fields and send the request again.",
            extra={"errors": errors},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code, title = _STATUS_CODES.get(exc.status_code, ("http_error", "Request failed"))
        detail = exc.detail if isinstance(exc.detail, str) else title
        return problem(
            request,
            status=exc.status_code,
            code=code,
            title=title,
            detail=detail,
            headers=dict(exc.headers) if exc.headers else None,
        )

    @app.exception_handler(StaleDataError)
    async def _stale(request: Request, exc: StaleDataError) -> JSONResponse:
        e = StaleVersion()
        return problem(request, status=e.status, code=e.code, title=e.title, detail=e.detail)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_error", path=request.url.path)
        return problem(
            request,
            status=500,
            code="internal_error",
            title="Something went wrong on our side",
            detail="The error has been logged. Quote the request_id if you contact support.",
        )
