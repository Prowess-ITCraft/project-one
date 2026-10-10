"""Outbox subscribers owned by verification, and the export driver installed for field work.

Loaded at start-up by `registry.load_handlers()` in the API, the worker and the CLI."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import DomainEvent, subscribe
from app.modules.fieldops.contracts import (
    CHECK_COMPLETED,
    ExportFacts,
    register_driver,
    register_export_reader,
)
from app.modules.verification import service
from app.modules.verification.driver import ExportDriver
from app.modules.verification.exports import parse_export, read_key_values

# Devices whose configuration can be exported. A brand without a parser falls back to the
# engineer's recorded values, so registering broadly is safe.
for _device in ("firewall", "switch", "nas", "server"):
    register_driver(_device, ExportDriver(_device))


def read_any_export(name: str, data: bytes) -> ExportFacts | None:
    """Field work shows what an uploaded export contains and compares the export taken before
    the work with the one after. A known brand first; otherwise any readable key and value
    lines, with no brand."""
    parsed = parse_export(name, data)
    if parsed is not None:
        return ExportFacts(parsed.brand, parsed.shape, dict(parsed.facts))
    plain = read_key_values(data)
    return ExportFacts(None, plain[0], plain[1]) if plain else None


register_export_reader(read_any_export)


@subscribe(CHECK_COMPLETED, name="verification.record_check")
async def on_check_completed(session: AsyncSession, event: DomainEvent) -> None:
    await service.record_check(session, event)
