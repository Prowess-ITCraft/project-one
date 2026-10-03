"""Identity rules: sign-in, lockout, MFA, token rotation, sessions and user administration."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crypto, flags
from app.core.config import get_settings
from app.core.errors import (
    Conflict,
    Forbidden,
    Locked,
    NotFound,
    StaleVersion,
    Unauthenticated,
    ValidationFailed,
)
from app.core.timeutil import utcnow
from app.modules.audit_log.contracts import AuditContext, record, shred_subject
from app.modules.identity import repository as repo
from app.modules.identity import security as sec
from app.modules.identity.models import AuthSession, RecoveryCode, RefreshToken, User, UserRole
from app.modules.identity.permissions import (
    MFA_REQUIRED_ROLES,
    STAFF_ROLES,
    Role,
    permissions_for,
)
from app.modules.identity.principal import Principal
from app.modules.identity.schemas import (
    ChallengeOut,
    MeOut,
    TokenOut,
    UserCreateIn,
    UserOut,
    UserUpdateIn,
)

log = structlog.get_logger(__name__)

WRONG_CREDENTIALS = "Email or password is wrong."
REFRESH_REUSE_GRACE = timedelta(seconds=10)
MFA_CHALLENGE_TTL = timedelta(minutes=5)
MFA_ENROL_TTL = timedelta(minutes=15)


@dataclass(frozen=True)
class ClientInfo:
    ip: str | None
    user_agent: str | None
    request_id: str | None = None


def user_roles(user: User) -> frozenset[Role]:
    return frozenset(Role(r.role) for r in user.roles)


def mfa_required(user: User) -> bool:
    return bool(user_roles(user) & MFA_REQUIRED_ROLES)


def _ctx(user: User | None, client: ClientInfo, label: str | None = None) -> AuditContext:
    return AuditContext(
        actor_id=user.id if user else None,
        actor_label=label or (f"{user.full_name} <{user.email}>" if user else "anonymous"),
        ip=client.ip,
        user_agent=client.user_agent,
        request_id=client.request_id,
    )


def principal_ctx(p: Principal) -> AuditContext:
    return AuditContext(
        actor_id=p.user_id,
        actor_label=p.label,
        ip=p.ip,
        user_agent=p.user_agent,
        request_id=p.request_id,
    )


def user_snapshot(user: User) -> dict[str, Any]:
    return {
        "email": user.email,
        "full_name": user.full_name,
        "initials": user.initials,
        "designation": user.designation,
        "phone": user.phone,
        "is_active": user.is_active,
        "customer_id": str(user.customer_id) if user.customer_id else None,
        "roles": sorted(r.role for r in user.roles),
        "mfa_enabled": user.mfa_enabled,
    }


def to_user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        initials=user.initials,
        designation=user.designation,
        phone=user.phone,
        roles=sorted(user_roles(user)),
        is_active=user.is_active,
        mfa_enabled=user.mfa_enabled,
        customer_id=user.customer_id,
        locked_until=user.locked_until,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        version=user.version,
    )


def to_me_out(user: User) -> MeOut:
    base = to_user_out(user).model_dump()
    return MeOut(
        **base,
        permissions=sorted(permissions_for(user_roles(user))),
        mfa_required=mfa_required(user),
    )


# ---------------------------------------------------------------- sign-in


async def _register_failure(
    session: AsyncSession, user: User, client: ClientInfo, reason: str
) -> None:
    s = get_settings()
    user.failed_logins += 1
    if user.failed_logins >= s.login_max_failures:
        user.lockouts += 1
        minutes = min(
            s.login_lockout_base_minutes * 2 ** (user.lockouts - 1), s.login_lockout_max_minutes
        )
        user.locked_until = utcnow() + timedelta(minutes=minutes)
        user.failed_logins = 0
        await record(
            session,
            _ctx(user, client),
            action="account_locked",
            entity_type="user",
            entity_id=user.id,
            after={"locked_minutes": minutes, "lockouts": user.lockouts},
            only_changes=False,
        )
    await record(
        session,
        _ctx(user, client),
        action=reason,
        entity_type="user",
        entity_id=user.id,
        only_changes=False,
    )
    await session.commit()


def _check_locked(user: User) -> None:
    if user.locked_until and user.locked_until > utcnow():
        retry = int((user.locked_until - utcnow()).total_seconds()) + 1
        raise Locked(
            "Too many failed attempts. Try again later or ask an admin to unlock the account.",
            headers={"Retry-After": str(retry)},
        )


async def login(
    session: AsyncSession, email: str, password: str, client: ClientInfo
) -> TokenOut | ChallengeOut:
    user = await repo.user_by_email(session, email)
    if user is None:
        sec.verify_password(None, password)  # equal timing for unknown emails
        raise Unauthenticated(WRONG_CREDENTIALS, code="invalid_credentials")
    await session.refresh(user, with_for_update=True)
    _check_locked(user)
    if not sec.verify_password(user.password_hash, password):
        await _register_failure(session, user, client, "login_failed")
        raise Unauthenticated(WRONG_CREDENTIALS, code="invalid_credentials")
    if not user.is_active:
        raise Unauthenticated(
            "This account is deactivated. Ask an admin to reactivate it.", code="account_inactive"
        )
    if Role.CUSTOMER_REP in user_roles(user) and not await flags.is_enabled(
        session, "customer_portal_login"
    ):
        raise Forbidden(
            "Customer sign-in is not enabled yet. Use the link we sent you.",
            code="customer_login_disabled",
        )

    user.failed_logins = 0
    if sec.needs_rehash(user.password_hash):
        user.password_hash = sec.hash_password(password)

    if user.mfa_enabled:
        token, exp = sec.issue_jwt(
            user_id=user.id, session_id=None, purpose="mfa_challenge", ttl=MFA_CHALLENGE_TTL
        )
        await session.commit()
        return ChallengeOut(status="mfa_required", challenge_token=token, expires_at=exp)
    if mfa_required(user):
        token, exp = sec.issue_jwt(
            user_id=user.id, session_id=None, purpose="mfa_enrol", ttl=MFA_ENROL_TTL
        )
        await session.commit()
        return ChallengeOut(status="mfa_enrolment_required", challenge_token=token, expires_at=exp)
    return await _start_session(session, user, client, mfa_verified=False)


async def _start_session(
    session: AsyncSession, user: User, client: ClientInfo, *, mfa_verified: bool
) -> TokenOut:
    s = get_settings()
    now = utcnow()
    auth = AuthSession(
        user_id=user.id,
        last_used_at=now,
        expires_at=now + timedelta(days=s.refresh_token_ttl_days),
        ip=client.ip,
        user_agent=(client.user_agent or "")[:400] or None,
        mfa_verified=mfa_verified,
    )
    session.add(auth)
    await session.flush()
    user.last_login_at = now
    tokens = await _issue_tokens(session, user, auth)
    await record(
        session,
        _ctx(user, client),
        action="login",
        entity_type="user",
        entity_id=user.id,
        after={"session_id": str(auth.id), "mfa": mfa_verified},
        only_changes=False,
    )
    await session.commit()
    return tokens


async def _issue_tokens(session: AsyncSession, user: User, auth: AuthSession) -> TokenOut:
    s = get_settings()
    access, access_exp = sec.issue_jwt(
        user_id=user.id,
        session_id=auth.id,
        purpose="access",
        ttl=timedelta(minutes=s.access_token_ttl_minutes),
    )
    raw_refresh = sec.new_opaque_token()
    now = utcnow()
    session.add(
        RefreshToken(
            session_id=auth.id,
            token_hash=sec.hash_token(raw_refresh),
            issued_at=now,
            expires_at=auth.expires_at,
        )
    )
    auth.last_used_at = now
    return TokenOut(
        access_token=access,
        access_expires_at=access_exp,
        refresh_token=raw_refresh,
        refresh_expires_at=auth.expires_at,
    )


async def _user_from_challenge(session: AsyncSession, token: str, purpose: str) -> User:
    claims = sec.decode_jwt(token, purpose=purpose)  # type: ignore[arg-type]
    if claims is None:
        raise Unauthenticated("This sign-in step expired. Sign in again.", code="challenge_invalid")
    user = await repo.user_by_id(session, claims.sub, lock=True)
    if user is None or not user.is_active:
        raise Unauthenticated("This sign-in step expired. Sign in again.", code="challenge_invalid")
    return user


async def verify_mfa(
    session: AsyncSession,
    challenge_token: str,
    code: str | None,
    recovery_code: str | None,
    client: ClientInfo,
) -> TokenOut:
    if bool(code) == bool(recovery_code):
        raise ValidationFailed("Send either a 6 digit code or a recovery code.")
    user = await _user_from_challenge(session, challenge_token, "mfa_challenge")
    _check_locked(user)
    if not user.mfa_enabled or not user.mfa_secret_enc:
        raise Unauthenticated(
            "MFA is not set up for this account. Sign in again.", code="challenge_invalid"
        )
    ok = False
    if code:
        step = sec.verify_totp(
            crypto.decrypt_str(user.mfa_secret_enc), code, last_used_step=user.mfa_last_used_step
        )
        if step is not None:
            user.mfa_last_used_step = step
            ok = True
    elif recovery_code:
        wanted = sec.hash_token(sec.normalise_recovery_code(recovery_code))
        for rc in await repo.unused_recovery_codes(session, user.id):
            if rc.code_hash == wanted:
                rc.used_at = utcnow()
                ok = True
                await record(
                    session,
                    _ctx(user, client),
                    action="mfa_recovery_code_used",
                    entity_type="user",
                    entity_id=user.id,
                    only_changes=False,
                )
                break
    if not ok:
        await _register_failure(session, user, client, "mfa_failed")
        raise Unauthenticated(
            "That code is not right. Check your authenticator app and try again.",
            code="invalid_mfa_code",
        )
    user.failed_logins = 0
    return await _start_session(session, user, client, mfa_verified=True)


async def mfa_enrol_start(session: AsyncSession, user: User) -> tuple[str, str]:
    secret = sec.new_totp_secret()
    user.mfa_pending_secret_enc = crypto.encrypt_str(secret)
    await session.commit()
    return secret, sec.totp_uri(secret, user.email)


async def user_for_enrolment(
    session: AsyncSession, enrol_token: str | None, principal: Principal | None
) -> tuple[User, bool]:
    """Enrol with a challenge token (MFA forced at first sign-in) or from a signed-in session."""
    if enrol_token:
        return await _user_from_challenge(session, enrol_token, "mfa_enrol"), True
    if principal is None:
        raise Unauthenticated()
    user = await repo.user_by_id(session, principal.user_id, lock=True)
    if user is None:
        raise Unauthenticated()
    return user, False


async def mfa_enrol_confirm(
    session: AsyncSession, user: User, code: str, client: ClientInfo, *, start_session: bool
) -> tuple[list[str], TokenOut | None]:
    if not user.mfa_pending_secret_enc:
        raise Conflict("Start MFA set-up first.", code="mfa_not_started")
    secret = crypto.decrypt_str(user.mfa_pending_secret_enc)
    step = sec.verify_totp(secret, code, last_used_step=None)
    if step is None:
        await _register_failure(session, user, client, "mfa_enrol_failed")
        raise Unauthenticated(
            "That code is not right. Check the time on your phone and try again.",
            code="invalid_mfa_code",
        )
    user.mfa_secret_enc = user.mfa_pending_secret_enc
    user.mfa_pending_secret_enc = None
    user.mfa_enabled = True
    user.mfa_last_used_step = step
    for rc in await repo.unused_recovery_codes(session, user.id):
        rc.used_at = utcnow()
    codes = sec.new_recovery_codes()
    for c in codes:
        session.add(
            RecoveryCode(user_id=user.id, code_hash=sec.hash_token(sec.normalise_recovery_code(c)))
        )
    await record(
        session,
        _ctx(user, client),
        action="mfa_enabled",
        entity_type="user",
        entity_id=user.id,
        only_changes=False,
    )
    if start_session:
        tokens = await _start_session(session, user, client, mfa_verified=True)
        return codes, tokens
    await session.commit()
    return codes, None


async def refresh(session: AsyncSession, raw_token: str, client: ClientInfo) -> TokenOut:
    rt = await repo.refresh_token_by_hash(session, sec.hash_token(raw_token))
    if rt is None:
        raise Unauthenticated("Your session has ended. Sign in again.", code="refresh_invalid")
    auth = await session.get(AuthSession, rt.session_id, with_for_update=True)
    now = utcnow()
    if (
        auth is None
        or auth.revoked_at is not None
        or auth.expires_at <= now
        or rt.expires_at <= now
    ):
        raise Unauthenticated("Your session has ended. Sign in again.", code="refresh_invalid")
    user = await repo.user_by_id(session, auth.user_id)
    if user is None or not user.is_active:
        raise Unauthenticated("Your session has ended. Sign in again.", code="refresh_invalid")
    if rt.used_at is not None:
        if now - rt.used_at <= REFRESH_REUSE_GRACE:
            # Two tabs refreshing at once. Reject this one without killing the session.
            raise Unauthenticated("Session refresh already in progress.", code="refresh_race")
        auth.revoked_at = now
        auth.revoke_reason = "refresh_token_reuse"
        await record(
            session,
            _ctx(user, client),
            action="refresh_token_reuse_detected",
            entity_type="auth_session",
            entity_id=auth.id,
            only_changes=False,
        )
        await session.commit()
        log.warning("refresh_token_reuse", user_id=str(user.id), session_id=str(auth.id))
        raise Unauthenticated("Your session has ended. Sign in again.", code="refresh_invalid")
    rt.used_at = now
    tokens = await _issue_tokens(session, user, auth)
    await session.commit()
    return tokens


async def logout(session: AsyncSession, principal: Principal) -> None:
    auth = await session.get(AuthSession, principal.session_id)
    if auth and auth.revoked_at is None:
        auth.revoked_at = utcnow()
        auth.revoke_reason = "logout"
        await record(
            session,
            principal_ctx(principal),
            action="logout",
            entity_type="auth_session",
            entity_id=auth.id,
            only_changes=False,
        )
        await session.commit()


# ---------------------------------------------------------------- per-request principal


async def load_principal(
    session: AsyncSession, access_token: str, *, via_cookie: bool, client: ClientInfo
) -> Principal:
    claims = sec.decode_jwt(access_token, purpose="access")
    if claims is None or claims.sid is None:
        raise Unauthenticated("Your sign-in has expired. Sign in again.", code="token_invalid")
    auth = await session.get(AuthSession, claims.sid)
    if (
        auth is None
        or auth.revoked_at is not None
        or auth.expires_at <= utcnow()
        or auth.user_id != claims.sub
    ):
        raise Unauthenticated("Your session has ended. Sign in again.", code="session_revoked")
    user = await repo.user_by_id(session, claims.sub)
    if user is None or not user.is_active:
        raise Unauthenticated("Your session has ended. Sign in again.", code="session_revoked")
    roles = user_roles(user)
    if roles & MFA_REQUIRED_ROLES and not auth.mfa_verified:
        raise Unauthenticated(
            "Your role needs MFA. Sign in again to set it up.", code="mfa_required"
        )
    return Principal(
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        initials=user.initials,
        roles=roles,
        permissions=permissions_for(roles),
        session_id=auth.id,
        customer_id=user.customer_id,
        via_cookie=via_cookie,
        ip=client.ip,
        user_agent=client.user_agent,
        request_id=client.request_id,
    )


# ---------------------------------------------------------------- sessions


async def list_sessions(session: AsyncSession, user_id: uuid.UUID) -> list[AuthSession]:
    return await repo.active_sessions(session, user_id)


async def revoke_session(
    session: AsyncSession, principal: Principal, session_id: uuid.UUID, *, any_user: bool
) -> None:
    auth = await session.get(AuthSession, session_id)
    if auth is None or (auth.user_id != principal.user_id and not any_user):
        raise NotFound("Session not found.")
    if auth.revoked_at is None:
        auth.revoked_at = utcnow()
        auth.revoke_reason = (
            "revoked_by_user" if auth.user_id == principal.user_id else "revoked_by_admin"
        )
        await record(
            session,
            principal_ctx(principal),
            action="session_revoked",
            entity_type="auth_session",
            entity_id=auth.id,
            after={"user_id": str(auth.user_id)},
            only_changes=False,
        )
        await session.commit()


async def revoke_all(
    session: AsyncSession, principal: Principal, user_id: uuid.UUID, *, keep_current: bool
) -> None:
    await repo.revoke_all_sessions(
        session, user_id, "revoked_all", except_id=principal.session_id if keep_current else None
    )
    await record(
        session,
        principal_ctx(principal),
        action="sessions_revoked_all",
        entity_type="user",
        entity_id=user_id,
        only_changes=False,
    )
    await session.commit()


# ---------------------------------------------------------------- users


def _validate_roles(roles: set[Role], customer_id: uuid.UUID | None) -> None:
    if Role.CUSTOMER_REP in roles:
        if roles & STAFF_ROLES:
            raise ValidationFailed(
                "A customer representative cannot also hold staff roles.",
                code="role_mix_not_allowed",
            )
        if customer_id is None:
            raise ValidationFailed("A customer representative must be linked to a customer.")
    elif customer_id is not None:
        raise ValidationFailed("Only customer representatives can be linked to a customer.")


async def create_user(
    session: AsyncSession,
    actor: Principal | None,
    data: UserCreateIn,
    *,
    audit: AuditContext | None = None,
) -> User:
    roles = set(data.roles)
    _validate_roles(roles, data.customer_id)
    if problems := sec.password_problems(data.password, email=data.email, full_name=data.full_name):
        raise ValidationFailed(" ".join(problems), code="weak_password")
    if await repo.user_by_email(session, data.email) is not None:
        raise Conflict("A user with this email already exists.", code="email_taken")
    user = User(
        email=repo.normalise_email(data.email),
        full_name=data.full_name,
        initials=data.initials,
        designation=data.designation,
        phone=data.phone,
        password_hash=sec.hash_password(data.password),
        customer_id=data.customer_id,
        is_active=True,
    )
    user.roles = [
        UserRole(role=r.value, granted_by=actor.user_id if actor else None) for r in sorted(roles)
    ]
    session.add(user)
    await session.flush()
    ctx = audit or (principal_ctx(actor) if actor else AuditContext.system())
    await record(
        session,
        ctx,
        action="create",
        entity_type="user",
        entity_id=user.id,
        after=user_snapshot(user),
        subject_id=user.id,
    )
    await session.commit()
    return user


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> User:
    user = await repo.user_by_id(session, user_id)
    if user is None:
        raise NotFound("User not found.")
    return user


def _check_version(entity_version: int, sent: int) -> None:
    if entity_version != sent:
        raise StaleVersion()


async def update_user(
    session: AsyncSession, actor: Principal, user_id: uuid.UUID, data: UserUpdateIn
) -> User:
    user = await get_user(session, user_id)
    _check_version(user.version, data.version)
    before = user_snapshot(user)
    changes = data.model_dump(exclude_unset=True, exclude={"version"})
    if user.id == actor.user_id and changes.get("is_active") is False:
        raise ValidationFailed("You cannot deactivate your own account.")
    for k, v in changes.items():
        setattr(user, k, v.upper() if k == "initials" and v else v)
    if changes.get("is_active") is False:
        await repo.revoke_all_sessions(session, user.id, "deactivated")
    await session.flush()
    await record(
        session,
        principal_ctx(actor),
        action="update",
        entity_type="user",
        entity_id=user.id,
        before=before,
        after=user_snapshot(user),
        subject_id=user.id,
    )
    await session.commit()
    return user


async def set_roles(
    session: AsyncSession, actor: Principal, user_id: uuid.UUID, roles: list[Role], version: int
) -> User:
    user = await get_user(session, user_id)
    _check_version(user.version, version)
    wanted = set(roles)
    _validate_roles(wanted, user.customer_id)
    if user.id == actor.user_id and Role.ADMIN in user_roles(user) and Role.ADMIN not in wanted:
        raise ValidationFailed("You cannot remove your own admin role. Ask another admin.")
    before = user_snapshot(user)
    current = {r.role: r for r in user.roles}
    user.roles = [
        current.get(r.value) or UserRole(role=r.value, granted_by=actor.user_id)
        for r in sorted(wanted)
    ]
    user.updated_at = utcnow()  # roles live in another table; touching the row bumps `version`
    # New MFA-required roles apply at next sign-in; end existing sessions so that happens now.
    if (wanted & MFA_REQUIRED_ROLES) and not user.mfa_enabled:
        await repo.revoke_all_sessions(session, user.id, "mfa_now_required")
    await session.flush()
    await record(
        session,
        principal_ctx(actor),
        action="roles_changed",
        entity_type="user",
        entity_id=user.id,
        before=before,
        after=user_snapshot(user),
        subject_id=user.id,
    )
    await session.commit()
    return user


async def unlock_user(session: AsyncSession, actor: Principal, user_id: uuid.UUID) -> User:
    user = await get_user(session, user_id)
    user.locked_until = None
    user.failed_logins = 0
    await record(
        session,
        principal_ctx(actor),
        action="unlock",
        entity_type="user",
        entity_id=user.id,
        only_changes=False,
    )
    await session.commit()
    return user


async def reset_mfa(session: AsyncSession, actor: Principal, user_id: uuid.UUID) -> User:
    if user_id == actor.user_id:
        raise Forbidden("Another admin must reset your MFA.", code="segregation_of_duties")
    user = await get_user(session, user_id)
    user.mfa_enabled = False
    user.mfa_secret_enc = None
    user.mfa_pending_secret_enc = None
    user.mfa_last_used_step = None
    for rc in await repo.unused_recovery_codes(session, user.id):
        rc.used_at = utcnow()
    await repo.revoke_all_sessions(session, user.id, "mfa_reset")
    await record(
        session,
        principal_ctx(actor),
        action="mfa_reset",
        entity_type="user",
        entity_id=user.id,
        only_changes=False,
    )
    await session.commit()
    return user


async def change_password(
    session: AsyncSession, principal: Principal, current: str, new: str
) -> None:
    user = await get_user(session, principal.user_id)
    if not sec.verify_password(user.password_hash, current):
        await _register_failure(
            session,
            user,
            ClientInfo(principal.ip, principal.user_agent, principal.request_id),
            "password_change_failed",
        )
        raise Unauthenticated("Your current password is wrong.", code="invalid_credentials")
    await _set_password(session, user, new)
    await repo.revoke_all_sessions(
        session, user.id, "password_changed", except_id=principal.session_id
    )
    await record(
        session,
        principal_ctx(principal),
        action="password_changed",
        entity_type="user",
        entity_id=user.id,
        only_changes=False,
    )
    await session.commit()


async def admin_reset_password(
    session: AsyncSession, actor: Principal, user_id: uuid.UUID, new: str
) -> None:
    if user_id == actor.user_id:
        raise ValidationFailed("Use change password for your own account.")
    user = await get_user(session, user_id)
    await _set_password(session, user, new)
    await repo.revoke_all_sessions(session, user.id, "password_reset_by_admin")
    await record(
        session,
        principal_ctx(actor),
        action="password_reset",
        entity_type="user",
        entity_id=user.id,
        only_changes=False,
    )
    await session.commit()


async def _set_password(session: AsyncSession, user: User, new: str) -> None:
    if problems := sec.password_problems(new, email=user.email, full_name=user.full_name):
        raise ValidationFailed(" ".join(problems), code="weak_password")
    if sec.verify_password(user.password_hash, new):
        raise ValidationFailed(
            "Choose a password you have not used for this account.", code="password_reused"
        )
    user.password_hash = sec.hash_password(new)
    user.password_changed_at = utcnow()


async def erase_personal_data(session: AsyncSession, actor: Principal, user_id: uuid.UUID) -> None:
    """GDPR-style erasure: anonymise the user row and crypto-shred their audit payloads."""
    if user_id == actor.user_id:
        raise ValidationFailed("You cannot erase your own account.")
    user = await get_user(session, user_id)
    await repo.revoke_all_sessions(session, user.id, "erased")
    user.email = f"erased-{user.id.hex}@erased.invalid"
    user.full_name = "Erased user"
    user.phone = None
    user.designation = None
    user.is_active = False
    user.mfa_enabled = False
    user.mfa_secret_enc = None
    user.password_hash = sec.hash_password(sec.new_opaque_token())
    user.deleted_at = utcnow()
    await shred_subject(session, user.id, actor.user_id)
    await record(
        session,
        principal_ctx(actor),
        action="personal_data_erased",
        entity_type="user",
        entity_id=user.id,
        only_changes=False,
    )
    await session.commit()
