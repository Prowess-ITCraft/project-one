"""Public surface of the catalogue module. Other modules import only from here."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Forbidden, NotFound
from app.modules.catalogue import service as _service
from app.modules.catalogue.models import CatalogueItem
from app.modules.catalogue.schemas import ItemIn, VendorIn
from app.modules.identity.contracts import P, Principal
from app.modules.search.contracts import SearchDoc

PRICE_CHANGED = _service.PRICE_CHANGED
PRICE_EXPIRED = _service.PRICE_EXPIRED_EVENT
STOCK_CHANGED = _service.STOCK_CHANGED


@dataclass(frozen=True)
class ItemRef:
    """An item as other modules see it. No prices: use `get_price_quote` for those."""

    id: uuid.UUID
    code: str
    kind: str
    category: str
    name: str
    description: str | None
    inclusions: tuple[str, ...]
    uom: str
    gst_rate: Decimal
    active: bool
    stock_status: str
    alternative_item_id: uuid.UUID | None
    eol_date: date | None
    eos_date: date | None
    vendor_id: uuid.UUID | None
    vendor_name: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PriceQuote:
    item_id: uuid.UUID
    state: str  # valid, expiring, expired, missing
    selling: Decimal | None
    cost: Decimal | None
    currency: str
    valid_until: date | None
    price_id: uuid.UUID | None

    @property
    def usable(self) -> bool:
        """Expired or missing prices block BOQ approval until refreshed."""
        return self.state in ("valid", "expiring")


def _ref(i: CatalogueItem, vendor_name: str | None = None) -> ItemRef:
    return ItemRef(
        id=i.id,
        code=i.code,
        kind=i.kind,
        category=i.category,
        name=i.name,
        description=i.description,
        inclusions=tuple(i.inclusions),
        uom=i.uom,
        gst_rate=i.gst_rate,
        active=i.active,
        stock_status=i.stock_status,
        alternative_item_id=i.alternative_item_id,
        eol_date=i.eol_date,
        eos_date=i.eos_date,
        vendor_id=i.vendor_id,
        vendor_name=vendor_name,
        attributes=dict(i.attributes or {}),
    )


async def _vendor_names(session: AsyncSession, items: list[CatalogueItem]) -> dict[uuid.UUID, str]:
    ids = {i.vendor_id for i in items if i.vendor_id}
    if not ids:
        return {}
    return {v.id: v.name for v in await _service.list_vendors(session) if v.id in ids}


async def search_documents(session: AsyncSession) -> list[SearchDoc]:
    """Every live catalogue item, for rebuilding the search index. No prices."""
    items = list(
        await session.scalars(select(CatalogueItem).where(CatalogueItem.deleted_at.is_(None)))
    )
    names = await _vendor_names(session, items)
    return [_service.item_doc(i, names.get(i.vendor_id) if i.vendor_id else None) for i in items]


async def get_item_ref(session: AsyncSession, principal: Principal, item_id: uuid.UUID) -> ItemRef:
    principal.require(P.CATALOGUE_READ)
    item = await _service.get_item(session, item_id)
    names = await _vendor_names(session, [item])
    return _ref(item, names.get(item.vendor_id) if item.vendor_id else None)


async def find_item_by_code(session: AsyncSession, principal: Principal, code: str) -> ItemRef:
    principal.require(P.CATALOGUE_READ)
    item = await session.scalar(
        select(CatalogueItem).where(CatalogueItem.code == code, CatalogueItem.deleted_at.is_(None))
    )
    if item is None:
        raise NotFound(f"No catalogue item with code {code}.")
    names = await _vendor_names(session, [item])
    return _ref(item, names.get(item.vendor_id) if item.vendor_id else None)


async def list_items_by_category(
    session: AsyncSession, principal: Principal, category: str, *, active_only: bool = True
) -> list[ItemRef]:
    principal.require(P.CATALOGUE_READ)
    stmt = _service.items_query(
        q=None,
        kind=None,
        category=category,
        vendor_id=None,
        active=True if active_only else None,
        priced=None,
    )
    items = list(await session.scalars(stmt))
    names = await _vendor_names(session, items)
    return [_ref(i, names.get(i.vendor_id) if i.vendor_id else None) for i in items]


async def resolve_orderable(
    session: AsyncSession, principal: Principal, item_id: uuid.UUID
) -> ItemRef:
    """The item to put on a BOQ: the item itself, or its listed alternative when out of stock."""
    item = await _service.get_item(session, item_id)
    principal.require(P.CATALOGUE_READ)
    if item.stock_status == "out_of_stock" and item.alternative_item_id is not None:
        return _ref(await _service.get_item(session, item.alternative_item_id))
    return _ref(item)


async def get_price_quote(
    session: AsyncSession, principal: Principal, item_id: uuid.UUID
) -> PriceQuote:
    """Current price state. Needs `price:read`: field engineers never get this far."""
    if not principal.has(P.PRICE_READ):
        raise Forbidden()
    st = await _service.current_price(session, item_id)
    p = st.price
    return PriceQuote(
        item_id=item_id,
        state=st.state,
        selling=p.selling if p else None,
        cost=p.cost if p else None,
        currency=p.currency if p else "INR",
        valid_until=p.valid_until if p else None,
        price_id=p.id if p else None,
    )


def _draft_to_item(draft: dict[str, Any]) -> ItemIn:
    data = {k: v for k, v in draft.items() if k != "vendor"}
    return ItemIn.model_validate(data)


def check_item_draft(draft: dict[str, Any]) -> list[str]:
    """Problems with a proposed catalogue item (empty when it would be accepted). Used by the
    library before a row is put forward for review."""
    try:
        _draft_to_item(draft)
    except ValidationError as exc:
        return [f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors()]
    return []


async def create_item_from_draft(
    session: AsyncSession, principal: Principal, draft: dict[str, Any]
) -> ItemRef:
    """Create an item from an approved proposal. `vendor` is a name; a missing vendor is added.
    Needs `catalogue:write`, which the caller already checked against the approver."""
    principal.require(P.CATALOGUE_WRITE)
    data = dict(draft)
    vendor_name = data.pop("vendor", None)
    if vendor_name:
        existing = next(
            (
                v
                for v in await _service.list_vendors(session, q=str(vendor_name))
                if v.name.lower() == str(vendor_name).lower()
            ),
            None,
        )
        vendor = existing or await _service.create_vendor(
            session, principal, VendorIn(name=str(vendor_name))
        )
        data["vendor_id"] = vendor.id
    item = await _service.create_item(session, principal, ItemIn.model_validate(data))
    return _ref(item)


async def get_market_data(
    session: AsyncSession, principal: Principal, item_id: uuid.UUID
) -> dict[str, Any]:
    """Current market facts for an item, newest value per key: {key: number or text}."""
    principal.require(P.CATALOGUE_READ)
    out: dict[str, Any] = {}
    for m in await _service.list_market_data(session, item_id, current_only=True):
        out[m.key] = float(m.value_num) if m.value_num is not None else m.value_text
    return out


__all__ = [
    "PRICE_CHANGED",
    "PRICE_EXPIRED",
    "STOCK_CHANGED",
    "ItemRef",
    "PriceQuote",
    "check_item_draft",
    "create_item_from_draft",
    "find_item_by_code",
    "get_item_ref",
    "get_market_data",
    "get_price_quote",
    "list_items_by_category",
    "resolve_orderable",
]
