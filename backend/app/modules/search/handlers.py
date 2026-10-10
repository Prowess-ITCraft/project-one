"""Outbox subscribers that keep the search index in step with the modules that own the data.

Loaded at start-up by `registry.load_handlers()` in the API, the worker and the CLI."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import DomainEvent, subscribe
from app.modules.search import service
from app.modules.search.contracts import SEARCH_REMOVE, SEARCH_UPSERT, SEARCH_UPSERT_MANY


@subscribe(SEARCH_UPSERT, name="search.upsert")
async def on_upsert(session: AsyncSession, event: DomainEvent) -> None:
    await service.upsert(session, event.payload)


@subscribe(SEARCH_UPSERT_MANY, name="search.upsert_many")
async def on_upsert_many(session: AsyncSession, event: DomainEvent) -> None:
    for doc in event.payload.get("docs", []):
        await service.upsert(session, doc)


@subscribe(SEARCH_REMOVE, name="search.remove")
async def on_remove(session: AsyncSession, event: DomainEvent) -> None:
    await service.remove(session, str(event.payload["kind"]), str(event.payload["ref_id"]))
