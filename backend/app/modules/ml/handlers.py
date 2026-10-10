"""Outbox subscribers owned by the learning module. Loaded at start-up by
`registry.load_handlers()`. Each one does nothing while the flag `ml_enabled` is off."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import DomainEvent, subscribe
from app.modules.boq.contracts import BOQ_ACCEPTED, BOQ_DRAFTED, BOQ_RECOMMENDED
from app.modules.catalogue.contracts import PRICE_CHANGED
from app.modules.ml import service


@subscribe(BOQ_RECOMMENDED, name="ml.record_recommendations")
async def on_recommended(session: AsyncSession, event: DomainEvent) -> None:
    await service.record_recommendations(session, event)


@subscribe(BOQ_ACCEPTED, name="ml.label_accepted")
async def on_accepted(session: AsyncSession, event: DomainEvent) -> None:
    await service.label_accepted(session, event)


@subscribe(BOQ_DRAFTED, name="ml.record_line_draft")
async def on_drafted(session: AsyncSession, event: DomainEvent) -> None:
    await service.record_line_draft(session, event)


@subscribe(PRICE_CHANGED, name="ml.record_price")
async def on_price(session: AsyncSession, event: DomainEvent) -> None:
    await service.record_price(session, event)
