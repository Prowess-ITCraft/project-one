"""Transactional outbox.

`publish()` writes one row per subscriber in the caller's transaction, so the event exists if
and only if the business change committed. The worker's `dispatch_batch()` claims due rows with
FOR UPDATE SKIP LOCKED, runs each handler in its own transaction, and retries failures with
exponential backoff. After MAX_ATTEMPTS the row is marked dead for manual follow-up.
A failing subscriber (for example notifications) never rolls back the publishing change.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import DateTime, Index, Integer, String, Text, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.events import DomainEvent, subscriber, subscribers_for
from app.core.timeutil import utcnow

log = structlog.get_logger(__name__)

MAX_ATTEMPTS = 8
NO_SUBSCRIBER = "-"


class OutboxMessage(Base):
    __tablename__ = "outbox_messages"
    __table_args__ = (Index("ix_outbox_due", "status", "available_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    subscriber: Mapped[str] = mapped_column(String(120), nullable=False)
    event: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


def publish(session: AsyncSession, event: DomainEvent) -> None:
    from app.core.events import handlers_loaded

    if not handlers_loaded():
        # Subscribers are fixed when the event is written. Publishing before they are loaded
        # would record the event with nobody to receive it, and it would be lost.
        raise RuntimeError(
            "Event subscribers are not loaded in this process. Call "
            "app.modules.registry.load_handlers() at start-up."
        )
    now = utcnow()
    data = event.model_dump(mode="json")
    subs = subscribers_for(event.event_type)
    if not subs:
        session.add(
            OutboxMessage(
                event_id=event.event_id,
                event_type=event.event_type,
                subscriber=NO_SUBSCRIBER,
                event=data,
                status="done",
                available_at=now,
                created_at=now,
                processed_at=now,
            )
        )
        return
    for sub in subs:
        session.add(
            OutboxMessage(
                event_id=event.event_id,
                event_type=event.event_type,
                subscriber=sub.name,
                event=data,
                status="pending",
                available_at=now,
                created_at=now,
            )
        )


def backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(2**attempts * 5, 3600))


async def dispatch_batch(sessionmaker: async_sessionmaker[AsyncSession], *, limit: int = 50) -> int:
    """Process up to `limit` due messages. Returns how many were attempted."""
    async with sessionmaker() as session:
        rows = (
            await session.scalars(
                select(OutboxMessage)
                .where(OutboxMessage.status == "pending", OutboxMessage.available_at <= utcnow())
                .order_by(OutboxMessage.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
        claimed = [(r.id, r.subscriber, r.event, r.attempts) for r in rows]
        # Lease the rows so a parallel dispatcher skips them while handlers run.
        if claimed:
            await session.execute(
                update(OutboxMessage)
                .where(OutboxMessage.id.in_([c[0] for c in claimed]))
                .values(available_at=utcnow() + timedelta(minutes=5))
            )
        await session.commit()

    for msg_id, sub_name, raw_event, attempts in claimed:
        await _run_one(sessionmaker, msg_id, sub_name, raw_event, attempts)
    return len(claimed)


async def _run_one(
    sessionmaker: async_sessionmaker[AsyncSession],
    msg_id: uuid.UUID,
    sub_name: str,
    raw_event: dict[str, Any],
    attempts: int,
) -> None:
    sub = subscriber(sub_name)
    event = DomainEvent.model_validate(raw_event)
    error: str | None = None
    if sub is None:
        error = f"no subscriber registered as {sub_name}"
    else:
        async with sessionmaker() as session:
            try:
                await sub.handler(session, event)
                await session.commit()
            except Exception as exc:  # handler failures are recorded, never raised
                await session.rollback()
                error = f"{type(exc).__name__}: {exc}"[:2000]
                log.warning("outbox_handler_failed", subscriber=sub_name, error=error)

    async with sessionmaker() as session:
        values: dict[str, Any]
        if error is None:
            values = {"status": "done", "processed_at": utcnow(), "attempts": attempts + 1}
        else:
            n = attempts + 1
            values = {
                "attempts": n,
                "last_error": error,
                "status": "dead" if n >= MAX_ATTEMPTS else "pending",
                "available_at": utcnow() + backoff(n),
            }
        await session.execute(
            update(OutboxMessage).where(OutboxMessage.id == msg_id).values(**values)
        )
        await session.commit()
