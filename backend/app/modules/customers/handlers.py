"""Outbox subscribers owned by the customers module."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import DomainEvent, subscribe
from app.modules.customers import service


@subscribe(service.ARTIFACT_LOCKED, name="customers.record_stage_artifact")
async def record_stage_artifact(session: AsyncSession, event: DomainEvent) -> None:
    await service.record_artifact(session, event)
