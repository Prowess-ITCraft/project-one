"""Idempotency keys for POSTs that create money or state transitions.

Clients send `Idempotency-Key: <uuid or 16-128 url-safe chars>`. The first request claims the
key; a repeat with the same body replays the stored response; a repeat with a different body is
rejected; a repeat while the first is still running gets 409. Keys are scoped per user and
kept for 24 hours.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated, Any

from fastapi import Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy import DateTime, Integer, String, UniqueConstraint, delete, select, update
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, get_sessionmaker
from app.core.errors import AppError, Conflict
from app.core.timeutil import utcnow

KEY_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
TTL = timedelta(hours=24)
IN_PROGRESS_TIMEOUT = timedelta(minutes=2)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("scope", "key"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    scope: Mapped[str] = mapped_column(String(80), nullable=False)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    method: Mapped[str] = mapped_column(String(8), nullable=False)
    path: Mapped[str] = mapped_column(String(512), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[Any | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class IdempotencyKeyRequired(AppError):
    status, code, title = 428, "idempotency_key_required", "Send an Idempotency-Key header"


class IdempotencyKeyReused(AppError):
    status, code, title = (
        422,
        "idempotency_key_reused",
        ("This Idempotency-Key was already used with a different request"),
    )


@dataclass
class IdempotencyGuard:
    key: str
    method: str
    path: str
    request_hash: str
    _record_id: uuid.UUID | None = None

    async def claim(self, scope: str) -> JSONResponse | None:
        """Claim the key. Returns a replay response if this request already completed."""
        now = utcnow()
        async with get_sessionmaker()() as s:
            await s.execute(delete(IdempotencyRecord).where(IdempotencyRecord.expires_at < now))
            stmt = (
                insert(IdempotencyRecord)
                .values(
                    id=uuid.uuid4(),
                    scope=scope,
                    key=self.key,
                    method=self.method,
                    path=self.path,
                    request_hash=self.request_hash,
                    created_at=now,
                    expires_at=now + TTL,
                )
                .on_conflict_do_nothing(index_elements=["scope", "key"])
                .returning(IdempotencyRecord.id)
            )
            new_id = (await s.execute(stmt)).scalar_one_or_none()
            if new_id is not None:
                await s.commit()
                self._record_id = new_id
                return None
            existing = (
                await s.scalars(
                    select(IdempotencyRecord).where(
                        IdempotencyRecord.scope == scope, IdempotencyRecord.key == self.key
                    )
                )
            ).one()
            await s.commit()
        if existing.request_hash != self.request_hash or existing.path != self.path:
            raise IdempotencyKeyReused()
        if existing.status_code is None:
            if now - existing.created_at > IN_PROGRESS_TIMEOUT:
                raise Conflict(
                    "An earlier request with this key did not finish. Use a new Idempotency-Key.",
                    code="idempotency_key_abandoned",
                )
            raise Conflict(
                "A request with this Idempotency-Key is still running.",
                code="idempotency_in_progress",
            )
        return JSONResponse(
            existing.response_body,
            status_code=existing.status_code,
            headers={"Idempotent-Replayed": "true"},
        )

    async def complete(self, status_code: int, body: Any) -> None:
        if self._record_id is None:
            return
        async with get_sessionmaker()() as s:
            await s.execute(
                update(IdempotencyRecord)
                .where(IdempotencyRecord.id == self._record_id)
                .values(status_code=status_code, response_body=body)
            )
            await s.commit()

    async def release(self) -> None:
        """Forget the claim after a failure so the client can retry with the same key."""
        if self._record_id is None:
            return
        async with get_sessionmaker()() as s:
            await s.execute(
                delete(IdempotencyRecord).where(IdempotencyRecord.id == self._record_id)
            )
            await s.commit()


async def require_idempotency_key(
    request: Request,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> IdempotencyGuard:
    if not idempotency_key:
        raise IdempotencyKeyRequired()
    if not KEY_RE.match(idempotency_key):
        raise IdempotencyKeyRequired("Idempotency-Key must be 16 to 128 letters, digits, - or _.")
    body = await request.body()
    request_hash = hashlib.sha256(body).hexdigest()
    return IdempotencyGuard(
        key=idempotency_key,
        method=request.method,
        path=request.url.path,
        request_hash=request_hash,
    )


async def run_idempotent(
    guard: IdempotencyGuard,
    scope: str,
    status_code: int,
    work: Any,
) -> Any:
    """Claim, run `work()` (an async callable returning a JSON-able model or dict), store, return.

    Usage in a router:
        return await run_idempotent(guard, str(principal.user_id), 201, lambda: svc.approve(...))
    """
    replay = await guard.claim(scope)
    if replay is not None:
        return replay
    try:
        result = await work()
    except BaseException:
        await guard.release()
        raise
    body = _to_json(result)
    await guard.complete(status_code, body)
    return JSONResponse(body, status_code=status_code)


def _to_json(result: Any) -> Any:
    if hasattr(result, "model_dump"):
        return result.model_dump(mode="json")
    return json.loads(json.dumps(result, default=str))
