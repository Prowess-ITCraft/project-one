"""Public surface of the identity module. Other modules import only from here."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit_log.contracts import AuditContext
from app.modules.identity import principal as _principal
from app.modules.identity import repository as _repo
from app.modules.identity import service as _service
from app.modules.identity.deps import CurrentPrincipal, get_principal, optional_principal, require
from app.modules.identity.permissions import P, Role
from app.modules.identity.principal import Principal, ensure_different_people
from app.modules.identity.schemas import UserCreateIn


@dataclass(frozen=True)
class UserSummary:
    id: uuid.UUID
    full_name: str
    initials: str
    designation: str | None
    email: str
    roles: frozenset[Role]
    is_active: bool


async def get_user_summary(session: AsyncSession, user_id: uuid.UUID) -> UserSummary | None:
    u = await _repo.user_by_id(session, user_id)
    if u is None:
        return None
    return UserSummary(
        id=u.id,
        full_name=u.full_name,
        initials=u.initials,
        designation=u.designation,
        email=u.email,
        roles=_service.user_roles(u),
        is_active=u.is_active,
    )


async def users_with_role(session: AsyncSession, role: Role) -> list[UserSummary]:
    """Active users holding a role, for example every Director to notify."""
    from sqlalchemy import select

    from app.modules.identity.models import User, UserRole

    users = await session.scalars(
        select(User)
        .join(UserRole, UserRole.user_id == User.id)
        .where(UserRole.role == role.value, User.is_active.is_(True), User.deleted_at.is_(None))
        .order_by(User.full_name)
    )
    out = []
    for u in users:
        s = await get_user_summary(session, u.id)
        if s is not None:
            out.append(s)
    return out


async def create_customer_representative(
    session: AsyncSession,
    actor: Principal,
    *,
    customer_id: uuid.UUID,
    email: str,
    full_name: str,
    phone: str | None,
    password: str,
) -> uuid.UUID:
    """Used by the customers module after it has checked the customer exists and is visible."""
    initials = "".join(w[0] for w in full_name.split() if w[:1].isalpha())[:6].upper() or "CR"
    user = await _service.create_user(
        session,
        actor,
        UserCreateIn(
            email=email,
            full_name=full_name,
            initials=initials,
            phone=phone,
            password=password,
            roles=[Role.CUSTOMER_REP],
            customer_id=customer_id,
        ),
    )
    return user.id


def system_principal(name: str = "system", permissions: frozenset[P] = frozenset()) -> Principal:
    return _principal.system_principal(name, permissions)


def audit_context(principal: Principal) -> AuditContext:
    return _service.principal_ctx(principal)


__all__ = [
    "CurrentPrincipal",
    "P",
    "Principal",
    "Role",
    "UserSummary",
    "audit_context",
    "create_customer_representative",
    "ensure_different_people",
    "get_principal",
    "get_user_summary",
    "optional_principal",
    "require",
    "system_principal",
    "users_with_role",
]
