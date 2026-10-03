"""FastAPI dependencies: who is calling, and are they allowed to."""

from __future__ import annotations

import hmac
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import Forbidden, Unauthenticated
from app.core.ratelimit import Limit, check
from app.modules.identity import service
from app.modules.identity.permissions import P
from app.modules.identity.principal import Principal

ACCESS_COOKIE = "p1_access"
REFRESH_COOKIE = "p1_refresh"
CSRF_COOKIE = "p1_csrf"
CSRF_HEADER = "x-csrf-token"
_UNSAFE = frozenset({"POST", "PUT", "PATCH", "DELETE"})

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)


def client_info(request: Request) -> service.ClientInfo:
    return service.ClientInfo(
        ip=getattr(request.state, "client_ip", None),
        user_agent=request.headers.get("user-agent"),
        request_id=getattr(request.state, "request_id", None),
    )


def check_csrf(request: Request) -> None:
    cookie = request.cookies.get(CSRF_COOKIE, "")
    header = request.headers.get(CSRF_HEADER, "")
    if not cookie or not header or not hmac.compare_digest(cookie, header):
        raise Forbidden(
            "Missing or wrong CSRF token. Reload the page and try again.", code="csrf_failed"
        )


async def get_principal(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    bearer: Annotated[str | None, Depends(oauth2_scheme)],
) -> Principal:
    token = bearer
    via_cookie = False
    if not token:
        token = request.cookies.get(ACCESS_COOKIE)
        via_cookie = token is not None
    if not token:
        raise Unauthenticated(headers={"WWW-Authenticate": "Bearer"})
    if via_cookie and request.method in _UNSAFE:
        check_csrf(request)
    principal = await service.load_principal(
        session, token, via_cookie=via_cookie, client=client_info(request)
    )
    await check(
        f"user:{principal.user_id}", Limit("user", get_settings().rate_limit_default_per_minute)
    )
    request.state.principal = principal
    return principal


async def optional_principal(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    bearer: Annotated[str | None, Depends(oauth2_scheme)],
) -> Principal | None:
    if not bearer and not request.cookies.get(ACCESS_COOKIE):
        return None
    return await get_principal(request, session, bearer)


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def require(*perms: P) -> Callable[..., Awaitable[Principal]]:
    """Dependency: the caller must hold every listed permission.

    The returned function carries `__required_permissions__` so the permission matrix test
    can find every protected route and check it against every role.
    """

    async def dependency(principal: CurrentPrincipal) -> Principal:
        for p in perms:
            if p not in principal.permissions:
                raise Forbidden()
        return principal

    dependency.__required_permissions__ = frozenset(perms)  # type: ignore[attr-defined]
    return dependency
