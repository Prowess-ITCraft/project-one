"""Outbox subscribers owned by the datasets module."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import DomainEvent, subscribe
from app.modules.datasets import library


@subscribe(library.LIBRARY_ADDED, name="datasets.process_library_file")
async def process_library_file(session: AsyncSession, event: DomainEvent) -> None:
    await library.process(session, uuid.UUID(event.payload["library_file_id"]))
