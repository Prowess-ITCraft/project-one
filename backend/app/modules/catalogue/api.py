from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.idempotency import IdempotencyGuard, require_idempotency_key, run_idempotent
from app.core.money import NonNegativeAmount
from app.core.pagination import Page, PageParams, page_params, paginate_rows
from app.modules.catalogue import service
from app.modules.catalogue.schemas import (
    CategoryOut,
    ItemIn,
    ItemOut,
    ItemUpdateIn,
    MarketDatumIn,
    MarketDatumOut,
    PriceIn,
    PriceOut,
    PriceStateOut,
    StockIn,
    VendorIn,
    VendorOut,
    VendorUpdateIn,
)
from app.modules.identity.contracts import P, Principal, require

router = APIRouter(prefix="/catalogue", tags=["catalogue"])
Session = Annotated[AsyncSession, Depends(get_session)]
Idem = Annotated[IdempotencyGuard, Depends(require_idempotency_key)]
Reader = Annotated[Principal, Depends(require(P.CATALOGUE_READ))]
Writer = Annotated[Principal, Depends(require(P.CATALOGUE_WRITE))]
PriceReader = Annotated[Principal, Depends(require(P.PRICE_READ))]
PriceWriter = Annotated[Principal, Depends(require(P.PRICE_WRITE))]


def _item(obj: object) -> ItemOut:
    return ItemOut.model_validate(obj, from_attributes=True)


# ------------------------------------------------------------------ reference data


@router.get("/categories", response_model=list[CategoryOut])
async def categories(session: Session, _: Reader) -> list[CategoryOut]:
    return [
        CategoryOut.model_validate(c, from_attributes=True)
        for c in await service.list_categories(session)
    ]


@router.get("/vendors", response_model=list[VendorOut])
async def vendors(
    session: Session, _: Reader, q: Annotated[str | None, Query(max_length=100)] = None
) -> list[VendorOut]:
    return [
        VendorOut.model_validate(v, from_attributes=True)
        for v in await service.list_vendors(session, q=q)
    ]


@router.post("/vendors", response_model=VendorOut, status_code=status.HTTP_201_CREATED)
async def create_vendor(session: Session, principal: Writer, body: VendorIn) -> VendorOut:
    return VendorOut.model_validate(
        await service.create_vendor(session, principal, body), from_attributes=True
    )


@router.patch("/vendors/{vendor_id}", response_model=VendorOut)
async def update_vendor(
    session: Session, principal: Writer, vendor_id: uuid.UUID, body: VendorUpdateIn
) -> VendorOut:
    return VendorOut.model_validate(
        await service.update_vendor(session, principal, vendor_id, body), from_attributes=True
    )


# ------------------------------------------------------------------ items


@router.get("/items", response_model=Page[ItemOut])
async def list_items(
    session: Session,
    _: Reader,
    params: Annotated[PageParams, Depends(page_params)],
    q: Annotated[str | None, Query(max_length=100)] = None,
    kind: Annotated[str | None, Query(pattern="^(product|service)$")] = None,
    category: Annotated[str | None, Query(max_length=40)] = None,
    vendor_id: uuid.UUID | None = None,
    active: bool | None = None,
) -> Page[ItemOut]:
    stmt = service.items_query(
        q=q, kind=kind, category=category, vendor_id=vendor_id, active=active, priced=None
    )
    rows, total = await paginate_rows(session, stmt, params)
    return Page(items=[_item(i) for i in rows], page=params.page, size=params.size, total=total)


@router.post("/items", response_model=ItemOut, status_code=status.HTTP_201_CREATED)
async def create_item(session: Session, principal: Writer, body: ItemIn) -> ItemOut:
    return _item(await service.create_item(session, principal, body))


@router.get("/items/{item_id}", response_model=ItemOut)
async def get_item(session: Session, _: Reader, item_id: uuid.UUID) -> ItemOut:
    return _item(await service.get_item(session, item_id))


@router.patch("/items/{item_id}", response_model=ItemOut)
async def update_item(
    session: Session, principal: Writer, item_id: uuid.UUID, body: ItemUpdateIn
) -> ItemOut:
    return _item(await service.update_item(session, principal, item_id, body))


@router.post("/items/{item_id}/stock", response_model=ItemOut)
async def set_stock(
    session: Session, principal: Writer, item_id: uuid.UUID, body: StockIn
) -> ItemOut:
    return _item(await service.set_stock(session, principal, item_id, body))


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(session: Session, principal: Writer, item_id: uuid.UUID) -> Response:
    await service.delete_item(session, principal, item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------ market data


@router.get("/items/{item_id}/market-data", response_model=list[MarketDatumOut])
async def market_data(
    session: Session, _: Reader, item_id: uuid.UUID, history: bool = False
) -> list[MarketDatumOut]:
    rows = await service.list_market_data(session, item_id, current_only=not history)
    return [MarketDatumOut.model_validate(r, from_attributes=True) for r in rows]


@router.post(
    "/items/{item_id}/market-data",
    response_model=MarketDatumOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_market_data(
    session: Session, principal: Writer, item_id: uuid.UUID, body: MarketDatumIn
) -> MarketDatumOut:
    return MarketDatumOut.model_validate(
        await service.add_market_datum(session, principal, item_id, body), from_attributes=True
    )


# ------------------------------------------------------------------ price book


class AttentionRow(BaseModel):
    item_id: uuid.UUID
    code: str
    name: str
    state: str
    valid_until: date | None
    days_left: int | None


class CurrentPriceRow(BaseModel):
    item_id: uuid.UUID
    state: str
    selling: NonNegativeAmount
    valid_until: date
    days_left: int | None


@router.get("/prices/current", response_model=list[CurrentPriceRow])
async def current_prices(session: Session, _: PriceReader) -> list[CurrentPriceRow]:
    """Price state and selling price for every priced item, so list screens need one call."""
    return [CurrentPriceRow(**r) for r in await service.current_prices(session)]


@router.get("/prices/attention", response_model=list[AttentionRow])
async def price_attention(
    session: Session, _: PriceReader, within_days: Annotated[int, Query(ge=0, le=60)] = 2
) -> list[AttentionRow]:
    """Items with a missing, expired or soon-to-expire price: the price book work list."""
    return [
        AttentionRow(**r) for r in await service.attention_list(session, within_days=within_days)
    ]


@router.get("/items/{item_id}/price", response_model=PriceStateOut)
async def current_price(session: Session, _: PriceReader, item_id: uuid.UUID) -> PriceStateOut:
    return await service.current_price(session, item_id)


@router.get("/items/{item_id}/prices", response_model=list[PriceOut])
async def price_history(session: Session, _: PriceReader, item_id: uuid.UUID) -> list[PriceOut]:
    return [service.price_out(p) for p in await service.price_history(session, item_id)]


@router.post(
    "/items/{item_id}/prices", response_model=PriceOut, status_code=status.HTTP_201_CREATED
)
async def add_price(
    session: Session, principal: PriceWriter, item_id: uuid.UUID, body: PriceIn, guard: Idem
) -> Any:
    async def work() -> PriceOut:
        return service.price_out(await service.add_price(session, principal, item_id, body))

    return await run_idempotent(guard, str(principal.user_id), 201, work)


routers = [router]
