"""Catalogue and price book rules."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import Select, exists, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import outbox
from app.core.errors import Conflict, NotFound, StaleVersion, ValidationFailed
from app.core.events import DomainEvent
from app.core.money import margin_percent
from app.core.timeutil import today_ist, utcnow
from app.modules.audit_log.contracts import AuditContext, record
from app.modules.catalogue.models import (
    PRICE_ACTIVE,
    PRICE_EXPIRED,
    PRICE_SUPERSEDED,
    CatalogueItem,
    Category,
    MarketDatum,
    PriceEntry,
    Vendor,
)
from app.modules.catalogue.schemas import (
    ItemIn,
    ItemUpdateIn,
    MarketDatumIn,
    PriceIn,
    PriceOut,
    PriceStateOut,
    StockIn,
    VendorIn,
    VendorUpdateIn,
)
from app.modules.identity.contracts import P, Principal, audit_context
from app.modules.search.contracts import SearchDoc
from app.modules.search.contracts import index as search_index
from app.modules.search.contracts import unindex as search_unindex

PRICE_CHANGED = "catalogue.price_changed"
PRICE_EXPIRED_EVENT = "catalogue.price_expired"
STOCK_CHANGED = "catalogue.stock_changed"
EXPIRING_DAYS = 2
MAX_PRICE_VALIDITY_DAYS = 366


def _snap(obj: Any, fields: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for f in fields:
        v = getattr(obj, f)
        out[f] = v if v is None or isinstance(v, bool | int | str | list | dict) else str(v)
    return out


_VENDOR_FIELDS = ["name", "website", "india_support", "preferred", "notes"]
_ITEM_FIELDS = [
    "code",
    "kind",
    "category",
    "vendor_id",
    "name",
    "description",
    "inclusions",
    "uom",
    "gst_rate",
    "hsn_sac",
    "active",
    "stock_status",
    "alternative_item_id",
    "eol_date",
    "eos_date",
    "attributes",
]


def _check_version(obj: Any, version: int) -> None:
    if obj.version != version:
        raise StaleVersion()


# ------------------------------------------------------------------ vendors


async def list_vendors(session: AsyncSession, *, q: str | None = None) -> list[Vendor]:
    stmt = select(Vendor).where(Vendor.deleted_at.is_(None)).order_by(Vendor.name)
    if q:
        stmt = stmt.where(Vendor.name.ilike(f"%{q}%"))
    return list(await session.scalars(stmt))


async def get_vendor(session: AsyncSession, vendor_id: uuid.UUID) -> Vendor:
    v = await session.scalar(
        select(Vendor).where(Vendor.id == vendor_id, Vendor.deleted_at.is_(None))
    )
    if v is None:
        raise NotFound("Vendor not found.")
    return v


async def create_vendor(session: AsyncSession, principal: Principal, body: VendorIn) -> Vendor:
    principal.require(P.CATALOGUE_WRITE)
    v = Vendor(**body.model_dump())
    session.add(v)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise Conflict("A vendor with this name already exists.", code="vendor_exists") from exc
    await record(
        session,
        audit_context(principal),
        action="create",
        entity_type="vendor",
        entity_id=v.id,
        after=_snap(v, _VENDOR_FIELDS),
    )
    await session.commit()
    return v


async def update_vendor(
    session: AsyncSession, principal: Principal, vendor_id: uuid.UUID, body: VendorUpdateIn
) -> Vendor:
    principal.require(P.CATALOGUE_WRITE)
    v = await get_vendor(session, vendor_id)
    _check_version(v, body.version)
    before = _snap(v, _VENDOR_FIELDS)
    for k, val in body.model_dump(exclude_unset=True, exclude={"version"}).items():
        setattr(v, k, val)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise Conflict("A vendor with this name already exists.", code="vendor_exists") from exc
    await record(
        session,
        audit_context(principal),
        action="update",
        entity_type="vendor",
        entity_id=v.id,
        before=before,
        after=_snap(v, _VENDOR_FIELDS),
    )
    await session.commit()
    return v


# ------------------------------------------------------------------ items


async def list_categories(session: AsyncSession) -> list[Category]:
    return list(
        await session.scalars(select(Category).order_by(Category.sort_order, Category.code))
    )


async def _category(session: AsyncSession, code: str, kind: str | None = None) -> Category:
    c = await session.get(Category, code)
    if c is None:
        raise ValidationFailed(f"Unknown category '{code}'.", code="unknown_category")
    if kind and c.kind != kind:
        raise ValidationFailed(
            f"Category '{code}' is for {c.kind} items, not {kind} items.", code="category_kind"
        )
    return c


def items_query(
    *,
    q: str | None,
    kind: str | None,
    category: str | None,
    vendor_id: uuid.UUID | None,
    active: bool | None,
    priced: bool | None,
    include_deleted: bool = False,
) -> Select[CatalogueItem]:
    stmt = select(CatalogueItem).order_by(CatalogueItem.category, CatalogueItem.name)
    if not include_deleted:
        stmt = stmt.where(CatalogueItem.deleted_at.is_(None))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(CatalogueItem.name.ilike(like), CatalogueItem.code.ilike(like)))
    if kind:
        stmt = stmt.where(CatalogueItem.kind == kind)
    if category:
        stmt = stmt.where(CatalogueItem.category == category)
    if vendor_id:
        stmt = stmt.where(CatalogueItem.vendor_id == vendor_id)
    if active is not None:
        stmt = stmt.where(CatalogueItem.active == active)
    if priced is not None:
        has = exists().where(
            PriceEntry.item_id == CatalogueItem.id, PriceEntry.status == PRICE_ACTIVE
        )
        stmt = stmt.where(has if priced else ~has)
    return stmt


async def get_item(session: AsyncSession, item_id: uuid.UUID) -> CatalogueItem:
    it = await session.scalar(
        select(CatalogueItem).where(CatalogueItem.id == item_id, CatalogueItem.deleted_at.is_(None))
    )
    if it is None:
        raise NotFound("Catalogue item not found.")
    return it


def _validate_dates(eol: date | None, eos: date | None) -> None:
    if eol and eos and eos < eol:
        raise ValidationFailed(
            "End of support cannot be before end of life.", code="eos_before_eol"
        )


def item_doc(item: CatalogueItem, vendor: str | None) -> SearchDoc:
    """What search shows for a catalogue item: code, name, category and vendor. Never a price."""
    return SearchDoc(
        kind="item",
        ref_id=str(item.id),
        title=f"{item.code} {item.name}",
        subtitle=f"{item.kind.capitalize()}, {item.category.replace('_', ' ')}"
        + (f", {vendor}" if vendor else ""),
        body=(item.description or "")[:1000] or None,
        url=f"/catalogue/{item.id}",
        perm="catalogue:read",
    )


async def _vendor_name(session: AsyncSession, vendor_id: uuid.UUID | None) -> str | None:
    if vendor_id is None:
        return None
    v = await session.get(Vendor, vendor_id)
    return v.name if v else None


async def create_item(session: AsyncSession, principal: Principal, body: ItemIn) -> CatalogueItem:
    principal.require(P.CATALOGUE_WRITE)
    await _category(session, body.category, body.kind)
    if body.vendor_id:
        await get_vendor(session, body.vendor_id)
    _validate_dates(body.eol_date, body.eos_date)
    item = CatalogueItem(**body.model_dump(), created_by=principal.user_id)
    session.add(item)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise Conflict("An item with this code already exists.", code="item_exists") from exc
    await record(
        session,
        audit_context(principal),
        action="create",
        entity_type="catalogue_item",
        entity_id=item.id,
        after=_snap(item, _ITEM_FIELDS),
    )
    search_index(
        session, item_doc(item, await _vendor_name(session, item.vendor_id)), principal.user_id
    )
    await session.commit()
    return item


async def update_item(
    session: AsyncSession, principal: Principal, item_id: uuid.UUID, body: ItemUpdateIn
) -> CatalogueItem:
    principal.require(P.CATALOGUE_WRITE)
    item = await get_item(session, item_id)
    _check_version(item, body.version)
    changes = body.model_dump(exclude_unset=True, exclude={"version"})
    if changes.get("category"):
        await _category(session, changes["category"], item.kind)
    if changes.get("vendor_id"):
        await get_vendor(session, changes["vendor_id"])
    before = _snap(item, _ITEM_FIELDS)
    for k, val in changes.items():
        setattr(item, k, val)
    _validate_dates(item.eol_date, item.eos_date)
    await session.flush()
    await record(
        session,
        audit_context(principal),
        action="update",
        entity_type="catalogue_item",
        entity_id=item.id,
        before=before,
        after=_snap(item, _ITEM_FIELDS),
    )
    search_index(
        session, item_doc(item, await _vendor_name(session, item.vendor_id)), principal.user_id
    )
    await session.commit()
    return item


async def set_stock(
    session: AsyncSession, principal: Principal, item_id: uuid.UUID, body: StockIn
) -> CatalogueItem:
    principal.require(P.CATALOGUE_WRITE)
    item = await get_item(session, item_id)
    _check_version(item, body.version)
    alt = None
    if body.alternative_item_id:
        if body.alternative_item_id == item.id:
            raise ValidationFailed("An item cannot be its own alternative.")
        alt = await get_item(session, body.alternative_item_id)
        if alt.kind != item.kind:
            raise ValidationFailed("The alternative must be the same kind of item.")
    before = _snap(item, ["stock_status", "alternative_item_id"])
    item.stock_status = body.stock_status
    item.alternative_item_id = alt.id if alt else body.alternative_item_id
    await session.flush()
    outbox.publish(
        session,
        DomainEvent(
            event_type=STOCK_CHANGED,
            aggregate_type="catalogue_item",
            aggregate_id=str(item.id),
            actor_id=principal.user_id,
            payload={"item_id": str(item.id), "stock_status": item.stock_status},
        ),
    )
    await record(
        session,
        audit_context(principal),
        action="set_stock",
        entity_type="catalogue_item",
        entity_id=item.id,
        before=before,
        after=_snap(item, ["stock_status", "alternative_item_id"]),
    )
    await session.commit()
    return item


async def delete_item(session: AsyncSession, principal: Principal, item_id: uuid.UUID) -> None:
    principal.require(P.CATALOGUE_WRITE)
    item = await get_item(session, item_id)
    item.deleted_at = utcnow()
    item.active = False
    await record(
        session,
        audit_context(principal),
        action="delete",
        entity_type="catalogue_item",
        entity_id=item.id,
        before={"code": item.code, "name": item.name},
        only_changes=False,
    )
    search_unindex(session, "item", str(item.id), principal.user_id)
    await session.commit()


# ------------------------------------------------------------------ market data


async def add_market_datum(
    session: AsyncSession, principal: Principal, item_id: uuid.UUID, body: MarketDatumIn
) -> MarketDatum:
    principal.require(P.CATALOGUE_WRITE)
    await get_item(session, item_id)
    if body.value_text is None and body.value_num is None:
        raise ValidationFailed("Give a text value or a number.", code="value_required")
    if body.as_of > today_ist():
        raise ValidationFailed("The 'as of' date cannot be in the future.")
    row = MarketDatum(item_id=item_id, entered_by=principal.user_id, **body.model_dump())
    session.add(row)
    await session.flush()
    await record(
        session,
        audit_context(principal),
        action="add_market_data",
        entity_type="catalogue_item",
        entity_id=item_id,
        after={"key": body.key, "value": body.value_text or str(body.value_num)},
        only_changes=False,
    )
    await session.commit()
    return row


async def list_market_data(
    session: AsyncSession, item_id: uuid.UUID, *, current_only: bool
) -> list[MarketDatum]:
    await get_item(session, item_id)
    rows = list(
        await session.scalars(
            select(MarketDatum)
            .where(MarketDatum.item_id == item_id)
            .order_by(MarketDatum.key, MarketDatum.as_of.desc(), MarketDatum.created_at.desc())
        )
    )
    if not current_only:
        return rows
    seen: set[str] = set()
    out: list[MarketDatum] = []
    for r in rows:
        if r.key not in seen:
            seen.add(r.key)
            out.append(r)
    return out


# ------------------------------------------------------------------ price book


def price_out(p: PriceEntry) -> PriceOut:
    out = PriceOut.model_validate(p, from_attributes=True)
    out.margin_percent = margin_percent(p.cost, p.selling)
    return out


async def add_price(
    session: AsyncSession, principal: Principal, item_id: uuid.UUID, body: PriceIn
) -> PriceEntry:
    principal.require(P.PRICE_WRITE)
    item = await get_item(session, item_id)
    today = today_ist()
    if body.selling < body.cost:
        raise ValidationFailed(
            "The selling price is below the cost price. Check both amounts.",
            code="price_below_cost",
        )
    if body.quoted_on > today:
        raise ValidationFailed("The quote date cannot be in the future.", code="quoted_in_future")
    if body.valid_until < body.quoted_on:
        raise ValidationFailed("Valid-until is before the quote date.", code="validity_order")
    if body.valid_until < today:
        raise ValidationFailed(
            "This price has already expired. Enter a price that is still valid.",
            code="price_already_expired",
        )
    if (body.valid_until - body.quoted_on).days > MAX_PRICE_VALIDITY_DAYS:
        raise ValidationFailed(
            "A price cannot be valid for more than a year.", code="validity_long"
        )

    previous = await session.scalar(
        select(PriceEntry).where(PriceEntry.item_id == item.id, PriceEntry.status == PRICE_ACTIVE)
    )
    if previous is not None:
        previous.status = PRICE_SUPERSEDED
        previous.ended_at = utcnow()
        await session.flush()  # free the one-active slot before inserting
    row = PriceEntry(item_id=item.id, entered_by=principal.user_id, **body.model_dump())
    session.add(row)
    await session.flush()
    outbox.publish(
        session,
        DomainEvent(
            event_type=PRICE_CHANGED,
            aggregate_type="catalogue_item",
            aggregate_id=str(item.id),
            actor_id=principal.user_id,
            payload={
                "item_id": str(item.id),
                "price_id": str(row.id),
                "selling": str(row.selling),
                "previous_selling": str(previous.selling) if previous else None,
                # For the learning module's price check (ADR 0029). No supplier, no person.
                "cost": str(row.cost),
                "quoted_on": str(row.quoted_on),
                "item_name": item.name[:300],
                "category": item.category,
                "item_kind": item.kind,
                "vendor_id": str(item.vendor_id) if item.vendor_id else None,
            },
        ),
    )
    await record(
        session,
        audit_context(principal),
        action="add_price",
        entity_type="catalogue_item",
        entity_id=item.id,
        before={"selling": str(previous.selling), "cost": str(previous.cost)} if previous else None,
        after={
            "selling": str(row.selling),
            "cost": str(row.cost),
            "valid_until": str(row.valid_until),
            "supplier": row.supplier,
            "source_note": row.source_note,
        },
        only_changes=False,
    )
    await session.commit()
    return row


async def price_history(session: AsyncSession, item_id: uuid.UUID) -> list[PriceEntry]:
    await get_item(session, item_id)
    return list(
        await session.scalars(
            select(PriceEntry)
            .where(PriceEntry.item_id == item_id)
            .order_by(PriceEntry.created_at.desc(), PriceEntry.id)
        )
    )


def state_of(price: PriceEntry | None, *, today: date | None = None) -> tuple[str, int | None]:
    """valid, expiring (2 days or fewer left), expired, or missing. Judged on the date, not on
    the status column, so a price is treated as expired from its first expired day even if the
    nightly job has not yet run."""
    if price is None or price.status != PRICE_ACTIVE:
        return ("missing" if price is None else "expired"), None
    days = (price.valid_until - (today or today_ist())).days
    if days < 0:
        return "expired", days
    return ("expiring" if days <= EXPIRING_DAYS else "valid"), days


async def current_price(session: AsyncSession, item_id: uuid.UUID) -> PriceStateOut:
    await get_item(session, item_id)
    p = await session.scalar(
        select(PriceEntry).where(PriceEntry.item_id == item_id, PriceEntry.status == PRICE_ACTIVE)
    )
    if p is None:
        last = await session.scalar(
            select(PriceEntry)
            .where(PriceEntry.item_id == item_id, PriceEntry.status == PRICE_EXPIRED)
            .order_by(PriceEntry.created_at.desc())
            .limit(1)
        )
        return PriceStateOut(
            item_id=item_id,
            state="expired" if last else "missing",
            price=price_out(last) if last else None,
        )
    state, days = state_of(p)
    return PriceStateOut(
        item_id=item_id,
        state=state,
        price=price_out(p),
        days_left=days,
    )


async def current_prices(session: AsyncSession) -> list[dict[str, Any]]:
    """One row per active item that has a price entry: the state and selling price, for lists."""
    today = today_ist()
    rows = await session.scalars(select(PriceEntry).where(PriceEntry.status == PRICE_ACTIVE))
    out: list[dict[str, Any]] = []
    for p in rows:
        state, days = state_of(p, today=today)
        out.append(
            {
                "item_id": p.item_id,
                "state": state,
                "selling": p.selling,
                "valid_until": p.valid_until,
                "days_left": days,
            }
        )
    return out


async def attention_list(
    session: AsyncSession, *, within_days: int = EXPIRING_DAYS
) -> list[dict[str, Any]]:
    """Active items whose price is missing, expired or about to expire: the work list for
    whoever maintains the price book."""
    today = today_ist()
    horizon = today + timedelta(days=within_days)
    rows = (
        await session.execute(
            select(CatalogueItem, PriceEntry)
            .outerjoin(
                PriceEntry,
                (PriceEntry.item_id == CatalogueItem.id) & (PriceEntry.status == PRICE_ACTIVE),
            )
            .where(CatalogueItem.deleted_at.is_(None), CatalogueItem.active.is_(True))
            .where(or_(PriceEntry.id.is_(None), PriceEntry.valid_until <= horizon))
            .order_by(PriceEntry.valid_until.nulls_first(), CatalogueItem.name)
        )
    ).all()
    out: list[dict[str, Any]] = []
    for item, price in rows:
        state, days = state_of(price, today=today)
        out.append(
            {
                "item_id": item.id,
                "code": item.code,
                "name": item.name,
                "state": state,
                "valid_until": price.valid_until if price else None,
                "days_left": days,
            }
        )
    return out


async def expire_prices(
    sessionmaker: async_sessionmaker[AsyncSession], *, today: date | None = None
) -> int:
    """Scheduled job. Marks active prices whose valid-until date has passed as expired and
    publishes one event per price. Safe to run repeatedly and in parallel."""
    today = today or today_ist()
    async with sessionmaker() as session:
        rows = (
            await session.scalars(
                select(PriceEntry)
                .where(PriceEntry.status == PRICE_ACTIVE, PriceEntry.valid_until < today)
                .with_for_update(skip_locked=True)
            )
        ).all()
        for p in rows:
            p.status = PRICE_EXPIRED
            p.ended_at = utcnow()
            outbox.publish(
                session,
                DomainEvent(
                    event_type=PRICE_EXPIRED_EVENT,
                    aggregate_type="catalogue_item",
                    aggregate_id=str(p.item_id),
                    payload={
                        "item_id": str(p.item_id),
                        "price_id": str(p.id),
                        "valid_until": str(p.valid_until),
                    },
                ),
            )
        if rows:
            await record(
                session,
                AuditContext.system("price_expiry"),
                action="expire_prices",
                entity_type="price_book",
                entity_id="batch",
                after={"count": len(rows), "as_of": str(today)},
                only_changes=False,
            )
        await session.commit()
        return len(rows)
