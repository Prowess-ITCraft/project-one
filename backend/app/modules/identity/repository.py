from __future__ import annotations

import uuid

from sqlalchemy import Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import utcnow
from app.modules.identity.models import AuthSession, RecoveryCode, RefreshToken, User, UserRole


def normalise_email(email: str) -> str:
    return email.strip().lower()


async def user_by_email(session: AsyncSession, email: str) -> User | None:
    return await session.scalar(
        select(User).where(
            func.lower(User.email) == normalise_email(email), User.deleted_at.is_(None)
        )
    )


async def user_by_id(
    session: AsyncSession, user_id: uuid.UUID, *, lock: bool = False
) -> User | None:
    stmt = select(User).where(User.id == user_id, User.deleted_at.is_(None))
    if lock:
        stmt = stmt.with_for_update()
    return await session.scalar(stmt)


def users_query(
    *, role: str | None = None, active: bool | None = None, q: str | None = None
) -> Select[User]:
    stmt = select(User).where(User.deleted_at.is_(None)).order_by(User.full_name)
    if role:
        stmt = stmt.where(User.id.in_(select(UserRole.user_id).where(UserRole.role == role)))
    if active is not None:
        stmt = stmt.where(User.is_active.is_(active))
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(func.lower(User.full_name).like(like) | func.lower(User.email).like(like))
    return stmt


async def refresh_token_by_hash(session: AsyncSession, token_hash: str) -> RefreshToken | None:
    return await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update()
    )


async def active_sessions(session: AsyncSession, user_id: uuid.UUID) -> list[AuthSession]:
    rows = await session.scalars(
        select(AuthSession)
        .where(
            AuthSession.user_id == user_id,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > utcnow(),
        )
        .order_by(AuthSession.last_used_at.desc())
    )
    return list(rows)


async def revoke_all_sessions(
    session: AsyncSession, user_id: uuid.UUID, reason: str, *, except_id: uuid.UUID | None = None
) -> None:
    stmt = (
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=utcnow(), revoke_reason=reason)
    )
    if except_id is not None:
        stmt = stmt.where(AuthSession.id != except_id)
    await session.execute(stmt)


async def unused_recovery_codes(session: AsyncSession, user_id: uuid.UUID) -> list[RecoveryCode]:
    rows = await session.scalars(
        select(RecoveryCode).where(RecoveryCode.user_id == user_id, RecoveryCode.used_at.is_(None))
    )
    return list(rows)
