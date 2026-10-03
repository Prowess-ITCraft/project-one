"""Public surface of the datasets module. Other modules import only from here."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from statistics import median

from rapidfuzz import fuzz, process
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.datasets import service as _service
from app.modules.datasets.library import LIBRARY_ADDED, LIBRARY_PROCESSED
from app.modules.datasets.models import COLLECTION_AUDIT, COLLECTION_BOQ, Dataset


@dataclass(frozen=True)
class HistoryHit:
    """What the library knows about a component from past BOQs. Advice only: it never sets a price."""

    name: str
    matched: str | None
    occurrences: int
    customers: int
    median_unit_price: Decimal | None
    min_unit_price: Decimal | None
    max_unit_price: Decimal | None
    typical_qty: int | None
    last_seen: date | None


async def boq_history(
    session: AsyncSession, names: list[str], *, threshold: int = 82
) -> dict[str, HistoryHit]:
    """For each name, fuzzy match it against the components of past BOQs in the library and
    summarise: how often, for how many customers, typical quantity and price range. Only rows a
    person or the reader was confident about are used."""
    empty = {n: HistoryHit(n, None, 0, 0, None, None, None, None, None) for n in names}
    ds = await session.scalar(
        select(Dataset).where(
            Dataset.collection_key == COLLECTION_BOQ, Dataset.deleted_at.is_(None)
        )
    )
    if ds is None or ds.latest_version == 0:
        return empty
    table = await _service.load_table(await _service.get_version(session, ds))
    if table.num_rows == 0:
        return empty
    rows = [
        r for r in table.to_pylist() if (r.get("confidence") or 0) >= 0.8 and r.get("component")
    ]
    components = sorted({r["component"] for r in rows})
    out: dict[str, HistoryHit] = {}
    for n in names:
        match = process.extractOne(
            n, components, scorer=fuzz.token_set_ratio, score_cutoff=threshold
        )
        if not match:
            out[n] = empty[n]
            continue
        hits = [r for r in rows if r["component"] == match[0]]
        prices: list[Decimal] = [r["unit_price"] for r in hits if r.get("unit_price") is not None]
        qtys = [int(r["qty"]) for r in hits if r.get("qty") is not None]
        dates = [r["quote_date"] for r in hits if r.get("quote_date")]
        out[n] = HistoryHit(
            n,
            match[0],
            len(hits),
            len({r.get("customer") for r in hits if r.get("customer")}),
            Decimal(str(median(prices))).quantize(Decimal("0.01")) if prices else None,
            min(prices) if prices else None,
            max(prices) if prices else None,
            int(median(qtys)) if qtys else None,
            max(dates) if dates else None,
        )
    return out


async def collection_row_count(session: AsyncSession, key: str) -> int:
    """Rows in a built-in collection (0 when it does not exist yet)."""
    ds = await session.scalar(
        select(Dataset).where(Dataset.collection_key == key, Dataset.deleted_at.is_(None))
    )
    if ds is None or ds.latest_version == 0:
        return 0
    return int((await _service.get_version(session, ds)).row_count)


async def scan_library_folder(
    maker: async_sessionmaker[AsyncSession], folder: Path
) -> dict[str, int]:
    """Pick up every supported file in the watched inbox folder (worker, every 5 minutes)."""
    from app.modules.datasets import library

    return await library.scan_folder(maker, folder)


async def purge_corpus_originals(session: AsyncSession) -> int:
    """Apply the corpus originals retention setting (ADR 0014). Nothing happens at 0 days."""
    from app.modules.datasets import corpus_service

    return await corpus_service.purge_originals(session)


__all__ = [
    "COLLECTION_AUDIT",
    "COLLECTION_BOQ",
    "LIBRARY_ADDED",
    "LIBRARY_PROCESSED",
    "HistoryHit",
    "boq_history",
    "collection_row_count",
    "purge_corpus_originals",
    "scan_library_folder",
]
