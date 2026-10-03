"""Outbox subscribers owned by verification, and the export driver installed for field work.

Loaded at start-up by `registry.load_handlers()` in the API, the worker and the CLI."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import DomainEvent, subscribe
from app.modules.fieldops.contracts import CHECK_COMPLETED, register_driver
from app.modules.verification import service
from app.modules.verification.driver import ExportDriver

# Devices whose configuration can be exported. A brand without a parser falls back to the
# engineer's recorded values, so registering broadly is safe.
for _device in ("firewall", "switch", "nas", "server"):
    register_driver(_device, ExportDriver(_device))


@subscribe(CHECK_COMPLETED, name="verification.record_check")
async def on_check_completed(session: AsyncSession, event: DomainEvent) -> None:
    await service.record_check(session, event)
