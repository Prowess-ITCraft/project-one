from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.core.money import NonNegativeAmount, RatePercent

Kind = Literal["product", "service"]
Stock = Literal["in_stock", "limited", "on_order", "out_of_stock"]
Code = Annotated[
    str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Z0-9][A-Z0-9\-_.]{1,39}$")
]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=250)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=300)]
Line = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ------------------------------------------------------------------ vendors


class VendorIn(_In):
    name: Annotated[str, StringConstraints(min_length=2, max_length=120)]
    website: Annotated[str, StringConstraints(max_length=200)] | None = None
    india_support: bool = True
    preferred: bool = False
    notes: Annotated[str, StringConstraints(max_length=2000)] | None = None


class VendorUpdateIn(_In):
    name: Annotated[str, StringConstraints(min_length=2, max_length=120)] | None = None
    website: Annotated[str, StringConstraints(max_length=200)] | None = None
    india_support: bool | None = None
    preferred: bool | None = None
    notes: Annotated[str, StringConstraints(max_length=2000)] | None = None
    version: int = Field(ge=1)


class VendorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    website: str | None
    india_support: bool
    preferred: bool
    notes: str | None
    version: int


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    label: str
    kind: str


# ------------------------------------------------------------------ items


class ItemIn(_In):
    code: Code
    kind: Kind
    category: Annotated[str, StringConstraints(max_length=40)]
    vendor_id: uuid.UUID | None = None
    name: Name
    description: Annotated[str, StringConstraints(max_length=4000)] | None = None
    inclusions: list[Line] = Field(default_factory=list, max_length=40)
    uom: Annotated[str, StringConstraints(min_length=1, max_length=20)] = "nos"
    gst_rate: RatePercent = Decimal(18)
    hsn_sac: Annotated[str, StringConstraints(pattern=r"^\d{4,8}$")] | None = None
    eol_date: date | None = None
    eos_date: date | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class ItemUpdateIn(_In):
    category: Annotated[str, StringConstraints(max_length=40)] | None = None
    vendor_id: uuid.UUID | None = None
    name: Name | None = None
    description: Annotated[str, StringConstraints(max_length=4000)] | None = None
    inclusions: list[Line] | None = Field(default=None, max_length=40)
    uom: Annotated[str, StringConstraints(min_length=1, max_length=20)] | None = None
    gst_rate: RatePercent | None = None
    hsn_sac: Annotated[str, StringConstraints(pattern=r"^\d{4,8}$")] | None = None
    active: bool | None = None
    eol_date: date | None = None
    eos_date: date | None = None
    attributes: dict[str, Any] | None = None
    version: int = Field(ge=1)


class StockIn(_In):
    stock_status: Stock
    alternative_item_id: uuid.UUID | None = None
    version: int = Field(ge=1)


class ItemOut(BaseModel):
    """What everyone with catalogue access sees. Deliberately has no price fields."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    kind: str
    category: str
    vendor_id: uuid.UUID | None
    name: str
    description: str | None
    inclusions: list[str]
    uom: str
    gst_rate: RatePercent
    hsn_sac: str | None
    active: bool
    stock_status: str
    alternative_item_id: uuid.UUID | None
    eol_date: date | None
    eos_date: date | None
    attributes: dict[str, Any]
    version: int


# ------------------------------------------------------------------ market data


class MarketDatumIn(_In):
    key: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{1,59}$")]
    value_text: Annotated[str, StringConstraints(max_length=300)] | None = None
    value_num: Decimal | None = None
    source_note: Note
    as_of: date


class MarketDatumOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    item_id: uuid.UUID
    key: str
    value_text: str | None
    value_num: Decimal | None
    source_note: str
    as_of: date
    entered_by: uuid.UUID | None


# ------------------------------------------------------------------ prices


class PriceIn(_In):
    supplier: Annotated[str, StringConstraints(min_length=2, max_length=160)]
    cost: NonNegativeAmount
    selling: NonNegativeAmount
    quoted_on: date
    valid_until: date
    source_note: Note


class PriceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    item_id: uuid.UUID
    supplier: str
    cost: NonNegativeAmount
    selling: NonNegativeAmount
    currency: str
    quoted_on: date
    valid_until: date
    source_note: str
    status: str
    entered_by: uuid.UUID | None
    created_at: datetime
    ended_at: datetime | None
    margin_percent: Decimal | None = None


class PriceStateOut(BaseModel):
    item_id: uuid.UUID
    state: Literal["valid", "expiring", "expired", "missing"]
    price: PriceOut | None = None
    days_left: int | None = None
