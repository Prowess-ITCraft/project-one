from __future__ import annotations

import secrets
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import flags
from app.core.config import get_settings
from app.core.db import get_session
from app.core.documents import qr_data_url
from app.core.errors import NotFound, Unauthenticated, ValidationFailed
from app.core.pagination import Page, PageParams, page_params, paginate_rows
from app.core.ratelimit import Limit, by_ip, check
from app.core.timeutil import utcnow
from app.modules.audit_log.contracts import record
from app.modules.identity import repository as repo
from app.modules.identity import service
from app.modules.identity.deps import (
    ACCESS_COOKIE,
    CSRF_COOKIE,
    REFRESH_COOKIE,
    CurrentPrincipal,
    check_csrf,
    client_info,
    optional_principal,
    require,
)
from app.modules.identity.models import AuthSession
from app.modules.identity.permissions import ROLE_LABELS, ROLE_PERMISSIONS, P, Role
from app.modules.identity.principal import Principal
from app.modules.identity.schemas import (
    ChallengeOut,
    LoginIn,
    MeOut,
    MfaEnrolConfirmIn,
    MfaEnrolConfirmOut,
    MfaEnrolStartIn,
    MfaEnrolStartOut,
    MfaVerifyIn,
    PasswordChangeIn,
    PasswordResetIn,
    RefreshIn,
    RolesIn,
    SessionOut,
    TokenOut,
    UserCreateIn,
    UserOut,
    UserUpdateIn,
)

Session = Annotated[AsyncSession, Depends(get_session)]
AuthMode = Annotated[str | None, Header(alias="X-Auth-Mode")]

_auth_limit = by_ip(Limit("auth", get_settings().rate_limit_auth_per_minute, strict=True))
# Refresh tokens are long random values, so guessing is not the risk here; a looser per-address
# limit keeps an office's token refreshes from using up the sign-in allowance.
_refresh_limit = by_ip(Limit("refresh", get_settings().rate_limit_default_per_minute))

auth_router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(_auth_limit)])
account_router = APIRouter(prefix="/auth", tags=["auth"])
users_router = APIRouter(prefix="/users", tags=["users"])
admin_router = APIRouter(prefix="/admin", tags=["admin"])
roles_router = APIRouter(prefix="/roles", tags=["users"])


# ------------------------------------------------------------------ cookies (web app)


def _deliver(response: Response, tokens: TokenOut, mode: str | None) -> TokenOut:
    """Bearer mode returns tokens in the body. Cookie mode sets httpOnly cookies instead."""
    if mode != "cookie":
        return tokens
    s = get_settings()
    now = utcnow()
    common = {"secure": s.cookie_secure, "domain": s.cookie_domain}
    response.set_cookie(
        ACCESS_COOKIE,
        tokens.access_token or "",
        max_age=int((tokens.access_expires_at - now).total_seconds()),
        httponly=True,
        samesite="lax",
        path="/",
        **common,  # type: ignore[arg-type]
    )
    response.set_cookie(
        REFRESH_COOKIE,
        tokens.refresh_token or "",
        max_age=int((tokens.refresh_expires_at - now).total_seconds()),
        httponly=True,
        samesite="strict",
        path=f"{s.api_prefix}/auth",
        **common,  # type: ignore[arg-type]
    )
    response.set_cookie(
        CSRF_COOKIE,
        secrets.token_urlsafe(32),
        max_age=int((tokens.refresh_expires_at - now).total_seconds()),
        httponly=False,
        samesite="strict",
        path="/",
        **common,  # type: ignore[arg-type]
    )
    return tokens.model_copy(update={"access_token": None, "refresh_token": None})  # nosec B105


def _clear_cookies(response: Response) -> None:
    s = get_settings()
    response.delete_cookie(ACCESS_COOKIE, path="/", domain=s.cookie_domain)
    response.delete_cookie(REFRESH_COOKIE, path=f"{s.api_prefix}/auth", domain=s.cookie_domain)
    response.delete_cookie(CSRF_COOKIE, path="/", domain=s.cookie_domain)


async def _email_limit(email: str) -> None:
    await check(f"email:{email.strip().lower()}", Limit("auth_email", 20, strict=True))


# ------------------------------------------------------------------ sign-in


@auth_router.post(
    "/token", response_model=TokenOut | ChallengeOut, summary="Sign in (OAuth2 form, for /docs)"
)
async def token(
    request: Request, session: Session, form: Annotated[OAuth2PasswordRequestForm, Depends()]
) -> TokenOut | ChallengeOut:
    await _email_limit(form.username)
    return await service.login(session, form.username, form.password, client_info(request))


@auth_router.post("/login", response_model=TokenOut | ChallengeOut, summary="Sign in")
async def login(
    request: Request, response: Response, session: Session, body: LoginIn, mode: AuthMode = None
) -> TokenOut | ChallengeOut:
    await _email_limit(body.email)
    result = await service.login(session, body.email, body.password, client_info(request))
    return _deliver(response, result, mode) if isinstance(result, TokenOut) else result


@auth_router.post("/mfa/verify", response_model=TokenOut, summary="Finish sign-in with an MFA code")
async def mfa_verify(
    request: Request, response: Response, session: Session, body: MfaVerifyIn, mode: AuthMode = None
) -> TokenOut:
    tokens = await service.verify_mfa(
        session, body.challenge_token, body.code, body.recovery_code, client_info(request)
    )
    return _deliver(response, tokens, mode)


@auth_router.post("/mfa/enrol/start", response_model=MfaEnrolStartOut, summary="Start MFA set-up")
async def mfa_enrol_start(
    session: Session,
    body: MfaEnrolStartIn,
    principal: Annotated[Principal | None, Depends(optional_principal)],
) -> MfaEnrolStartOut:
    user, _ = await service.user_for_enrolment(session, body.enrol_token, principal)
    secret, uri = await service.mfa_enrol_start(session, user)
    return MfaEnrolStartOut(secret=secret, otpauth_uri=uri, qr_svg=qr_data_url(uri))


@auth_router.post(
    "/mfa/enrol/confirm", response_model=MfaEnrolConfirmOut, summary="Confirm MFA set-up"
)
async def mfa_enrol_confirm(
    request: Request,
    response: Response,
    session: Session,
    body: MfaEnrolConfirmIn,
    principal: Annotated[Principal | None, Depends(optional_principal)],
    mode: AuthMode = None,
) -> MfaEnrolConfirmOut:
    user, via_challenge = await service.user_for_enrolment(session, body.enrol_token, principal)
    codes, tokens = await service.mfa_enrol_confirm(
        session, user, body.code, client_info(request), start_session=via_challenge
    )
    return MfaEnrolConfirmOut(
        recovery_codes=codes, tokens=_deliver(response, tokens, mode) if tokens else None
    )


@account_router.post(
    "/refresh",
    response_model=TokenOut,
    summary="Swap a refresh token for new tokens",
    dependencies=[Depends(_refresh_limit)],
)
async def refresh(
    request: Request,
    response: Response,
    session: Session,
    body: RefreshIn | None = None,
    mode: AuthMode = None,
) -> TokenOut:
    raw = body.refresh_token if body else None
    if raw is None:
        raw = request.cookies.get(REFRESH_COOKIE)
        if raw is not None:
            check_csrf(request)
            mode = "cookie"
    if not raw:
        raise Unauthenticated("Your session has ended. Sign in again.", code="refresh_invalid")
    tokens = await service.refresh(session, raw, client_info(request))
    return _deliver(response, tokens, mode)


# ------------------------------------------------------------------ own account


@account_router.post(
    "/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Sign out of this session"
)
async def logout(response: Response, session: Session, principal: CurrentPrincipal) -> Response:
    await service.logout(session, principal)
    response.status_code = status.HTTP_204_NO_CONTENT
    _clear_cookies(response)
    return response


@account_router.get("/me", response_model=MeOut)
async def me(session: Session, principal: CurrentPrincipal) -> MeOut:
    return service.to_me_out(await service.get_user(session, principal.user_id))


@account_router.post(
    "/password", status_code=status.HTTP_204_NO_CONTENT, summary="Change your password"
)
async def change_password(
    session: Session, principal: CurrentPrincipal, body: PasswordChangeIn
) -> None:
    await check(f"pwd:{principal.user_id}", Limit("auth_password", 5, strict=True))
    await service.change_password(session, principal, body.current_password, body.new_password)


def _session_out(s: AuthSession, current: uuid.UUID) -> SessionOut:
    return SessionOut(
        id=s.id,
        created_at=s.created_at,
        last_used_at=s.last_used_at,
        expires_at=s.expires_at,
        ip=str(s.ip) if s.ip else None,
        user_agent=s.user_agent,
        current=s.id == current,
    )


@account_router.get("/sessions", response_model=list[SessionOut], summary="Your active sessions")
async def my_sessions(session: Session, principal: CurrentPrincipal) -> list[SessionOut]:
    rows = await service.list_sessions(session, principal.user_id)
    return [_session_out(s, principal.session_id) for s in rows]


@account_router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_my_session(
    session: Session, principal: CurrentPrincipal, session_id: uuid.UUID
) -> None:
    await service.revoke_session(session, principal, session_id, any_user=False)


@account_router.post("/sessions/revoke-others", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_other_sessions(session: Session, principal: CurrentPrincipal) -> None:
    await service.revoke_all(session, principal, principal.user_id, keep_current=True)


# ------------------------------------------------------------------ users (admin)


@users_router.get("", response_model=Page[UserOut])
async def list_users(
    session: Session,
    _: Annotated[Principal, Depends(require(P.USER_READ))],
    params: Annotated[PageParams, Depends(page_params)],
    role: Role | None = None,
    active: bool | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> Page[UserOut]:
    rows, total = await paginate_rows(
        session, repo.users_query(role=role, active=active, q=q), params
    )
    return Page(
        items=[service.to_user_out(u) for u in rows],
        page=params.page,
        size=params.size,
        total=total,
    )


@users_router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    session: Session,
    actor: Annotated[Principal, Depends(require(P.USER_MANAGE))],
    body: UserCreateIn,
) -> UserOut:
    if Role.CUSTOMER_REP in body.roles:
        raise ValidationFailed(
            "Add customer representatives from the customer's page.", code="use_customer_endpoint"
        )
    return service.to_user_out(await service.create_user(session, actor, body))


@users_router.get("/{user_id}", response_model=UserOut)
async def get_user(
    session: Session, _: Annotated[Principal, Depends(require(P.USER_READ))], user_id: uuid.UUID
) -> UserOut:
    return service.to_user_out(await service.get_user(session, user_id))


@users_router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    session: Session,
    actor: Annotated[Principal, Depends(require(P.USER_MANAGE))],
    user_id: uuid.UUID,
    body: UserUpdateIn,
) -> UserOut:
    return service.to_user_out(await service.update_user(session, actor, user_id, body))


@users_router.put("/{user_id}/roles", response_model=UserOut)
async def set_roles(
    session: Session,
    actor: Annotated[Principal, Depends(require(P.USER_MANAGE))],
    user_id: uuid.UUID,
    body: RolesIn,
) -> UserOut:
    return service.to_user_out(
        await service.set_roles(session, actor, user_id, body.roles, body.version)
    )


@users_router.post("/{user_id}/unlock", response_model=UserOut)
async def unlock_user(
    session: Session,
    actor: Annotated[Principal, Depends(require(P.USER_MANAGE))],
    user_id: uuid.UUID,
) -> UserOut:
    return service.to_user_out(await service.unlock_user(session, actor, user_id))


@users_router.post("/{user_id}/reset-mfa", response_model=UserOut)
async def reset_mfa(
    session: Session,
    actor: Annotated[Principal, Depends(require(P.USER_MANAGE))],
    user_id: uuid.UUID,
) -> UserOut:
    return service.to_user_out(await service.reset_mfa(session, actor, user_id))


@users_router.post("/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    session: Session,
    actor: Annotated[Principal, Depends(require(P.USER_MANAGE))],
    user_id: uuid.UUID,
    body: PasswordResetIn,
) -> None:
    await service.admin_reset_password(session, actor, user_id, body.new_password)


@users_router.get("/{user_id}/sessions", response_model=list[SessionOut])
async def user_sessions(
    session: Session,
    actor: Annotated[Principal, Depends(require(P.SESSION_MANAGE_ANY))],
    user_id: uuid.UUID,
) -> list[SessionOut]:
    return [
        _session_out(s, actor.session_id) for s in await service.list_sessions(session, user_id)
    ]


@users_router.delete("/{user_id}/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_user_session(
    session: Session,
    actor: Annotated[Principal, Depends(require(P.SESSION_MANAGE_ANY))],
    user_id: uuid.UUID,
    session_id: uuid.UUID,
) -> None:
    await service.revoke_session(session, actor, session_id, any_user=True)


@users_router.post("/{user_id}/sessions/revoke-all", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_user_sessions(
    session: Session,
    actor: Annotated[Principal, Depends(require(P.SESSION_MANAGE_ANY))],
    user_id: uuid.UUID,
) -> None:
    await service.revoke_all(session, actor, user_id, keep_current=False)


@users_router.post(
    "/{user_id}/erase", status_code=status.HTTP_204_NO_CONTENT, summary="Erase personal data (GDPR)"
)
async def erase_user(
    session: Session,
    actor: Annotated[Principal, Depends(require(P.PERSONAL_DATA_ERASE))],
    user_id: uuid.UUID,
) -> None:
    await service.erase_personal_data(session, actor, user_id)


# ------------------------------------------------------------------ roles and flags


class RoleOut(BaseModel):
    role: Role
    label: str
    permissions: list[str]


@roles_router.get("", response_model=list[RoleOut], summary="Roles and their permissions")
async def list_roles(_: Annotated[Principal, Depends(require(P.USER_READ))]) -> list[RoleOut]:
    return [
        RoleOut(role=r, label=ROLE_LABELS[r], permissions=sorted(ROLE_PERMISSIONS[r])) for r in Role
    ]


class FlagOut(BaseModel):
    key: str
    enabled: bool
    default: bool


class FlagIn(BaseModel):
    enabled: bool
    description: str | None = Field(default=None, max_length=300)


@admin_router.get("/feature-flags", response_model=list[FlagOut])
async def list_flags(
    session: Session, _: Annotated[Principal, Depends(require(P.FLAGS_MANAGE))]
) -> list[FlagOut]:
    rows = {f.key: f.enabled for f in (await session.scalars(select(flags.FeatureFlag))).all()}
    return [
        FlagOut(key=k, enabled=rows.get(k, d), default=d) for k, d in sorted(flags.DEFAULTS.items())
    ]


@admin_router.put("/feature-flags/{key}", response_model=FlagOut)
async def set_flag(
    session: Session,
    actor: Annotated[Principal, Depends(require(P.FLAGS_MANAGE))],
    key: str,
    body: FlagIn,
) -> FlagOut:
    if key not in flags.DEFAULTS:
        raise NotFound("Unknown feature flag.")
    row = await session.get(flags.FeatureFlag, key)
    before = {"enabled": row.enabled if row else flags.DEFAULTS[key]}
    if row is None:
        row = flags.FeatureFlag(key=key, enabled=body.enabled, description=body.description)
        session.add(row)
    else:
        row.enabled = body.enabled
        row.description = body.description
    await record(
        session,
        service.principal_ctx(actor),
        action="update",
        entity_type="feature_flag",
        entity_id=key,
        before=before,
        after={"enabled": body.enabled},
    )
    await session.commit()
    flags.clear_cache()
    return FlagOut(key=key, enabled=body.enabled, default=flags.DEFAULTS[key])
