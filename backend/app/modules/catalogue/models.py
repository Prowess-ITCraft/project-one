from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, SoftDelete, Timestamps, UUIDPk, Versioned

KINDS = ("product", "service")
STOCK_STATUSES = ("in_stock", "limited", "on_order", "out_of_stock")
PRICE_ACTIVE = "active"
PRICE_SUPERSEDED = "superseded"
PRICE_EXPIRED = "expired"


class Vendor(UUIDPk, Timestamps, SoftDelete, Versioned, Base):
    """A brand or manufacturer (Sophos, Cisco, Acronis) or a service partner."""

    __tablename__ = "vendors"
    __table_args__ = (
        Index(
            "uq_vendors_name_active",
            text("lower(name)"),
            unique=True,
            postgresql_where="deleted_at IS NULL",
        ),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    website: Mapped[str | None] = mapped_column(String(200))
    india_support: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    preferred: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str | None] = mapped_column(Text)


class Category(Base):
    __tablename__ = "catalogue_categories"

    code: Mapped[str] = mapped_column(String(40), primary_key=True)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    sort_order: Mapped[int] = mapped_column(nullable=False, default=100)


class CatalogueItem(UUIDPk, Timestamps, SoftDelete, Versioned, Base):
    """A product or a service that can appear on a BOQ line."""

    __tablename__ = "catalogue_items"
    __table_args__ = (
        Index("uq_catalogue_items_code", "code", unique=True),
        CheckConstraint("kind IN ('product','service')", name="kind_valid"),
        CheckConstraint(
            "stock_status IN ('in_stock','limited','on_order','out_of_stock')",
            name="stock_status_valid",
        ),
        CheckConstraint("gst_rate >= 0 AND gst_rate <= 100", name="gst_rate_range"),
    )

    code: Mapped[str] = mapped_column(String(40), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    category: Mapped[str] = mapped_column(
        ForeignKey("catalogue_categories.code"), nullable=False, index=True
    )
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vendors.id"), index=True)
    name: Mapped[str] = mapped_column(String(250), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    inclusions: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    uom: Mapped[str] = mapped_column(String(20), nullable=False, default="nos")
    gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal(18))
    hsn_sac: Mapped[str | None] = mapped_column(String(10))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    stock_status: Mapped[str] = mapped_column(String(12), nullable=False, default="in_stock")
    alternative_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("catalogue_items.id"))
    eol_date: Mapped[date | None] = mapped_column(Date)
    eos_date: Mapped[date | None] = mapped_column(Date)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_by: Mapped[uuid.UUID | None] = mapped_column()


class MarketDatum(UUIDPk, Base):
    """Manually entered market facts (rating, analyst tier, India support). Append-only: the
    newest row per (item, key) is current, older rows are the history."""

    __tablename__ = "catalogue_market_data"
    __table_args__ = (Index("ix_market_item_key", "item_id", "key", "as_of"),)

    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalogue_items.id"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(60), nullable=False)
    value_text: Mapped[str | None] = mapped_column(String(300))
    value_num: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    source_note: Mapped[str] = mapped_column(String(300), nullable=False)
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    entered_by: Mapped[uuid.UUID | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PriceEntry(UUIDPk, Base):
    """The price book. Append-only history: a new price supersedes the active one, it never
    edits it. At most one row per item is `active`."""

    __tablename__ = "price_entries"
    __table_args__ = (
        Index(
            "uq_price_entries_one_active",
            "item_id",
            unique=True,
            postgresql_where="status = 'active'",
        ),
        Index("ix_price_entries_item_created", "item_id", "created_at"),
        CheckConstraint("cost >= 0 AND selling >= 0", name="non_negative"),
        CheckConstraint("selling >= cost", name="selling_not_below_cost"),
        CheckConstraint("valid_until >= quoted_on", name="validity_after_quote"),
        CheckConstraint("status IN ('active','superseded','expired')", name="status_valid"),
    )

    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalogue_items.id"), nullable=False, index=True
    )
    supplier: Mapped[str] = mapped_column(String(160), nullable=False)
    cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    selling: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    quoted_on: Mapped[date] = mapped_column(Date, nullable=False)
    valid_until: Mapped[date] = mapped_column(Date, nullable=False)
    source_note: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default=PRICE_ACTIVE)
    entered_by: Mapped[uuid.UUID | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
