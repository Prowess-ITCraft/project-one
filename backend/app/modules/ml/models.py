from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk

# trained: made, not running. shadow: runs next to the rules, its answers only recorded.
# approved: the Director accepted it after shadow mode; it may advise people (suggested lines,
# price alerts), never decide. retired: never used again.
MODEL_STATUSES = ("trained", "shadow", "approved", "retired")
# ranker: weights for the recommendation criteria (ADR 0020). boq_lines: which BOQ lines a set
# of audit findings leads to. price_drift: what a new price should be, from the price history.
MODEL_KINDS = ("ranker", "boq_lines", "price_drift")


class MlExample(UUIDPk, Timestamps, Base):
    """One candidate the recommender ranked while drafting a BOQ, with its criteria. Labelled
    kept or not when the customer accepts a version. Live data: training never reads this table
    directly, only frozen training sets made from it (RULES 2.6)."""

    __tablename__ = "ml_examples"
    __table_args__ = (
        UniqueConstraint("boq_id", "rec_key", "item_id", name="uq_ml_examples"),
        Index("ix_ml_examples_labelled", "labelled_at"),
    )

    boq_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    rec_key: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(60), nullable=False)
    item_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    item_name: Mapped[str] = mapped_column(String(300), nullable=False)
    rule_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    rule_score: Mapped[float] = mapped_column(Float, nullable=False)
    criteria: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    kept: Mapped[bool | None] = mapped_column(Boolean)
    labelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MlTrainingSet(UUIDPk, Base):
    """A frozen copy of the labelled examples at one moment, with a data card. Never changed or
    deleted (a database trigger enforces it), so a model can always be traced to its data."""

    __tablename__ = "ml_training_sets"

    number: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String(12), nullable=False, server_default="ranker")
    rows: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    data_card: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    frozen_by: Mapped[uuid.UUID] = mapped_column(nullable=False)
    frozen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class MlModel(UUIDPk, Timestamps, Base):
    """A model learned from one frozen training set. Per kind, at most one runs in shadow mode
    and at most one is approved."""

    __tablename__ = "ml_models"
    __table_args__ = (
        Index(
            "uq_ml_models_shadow", "kind", unique=True, postgresql_where=text("status = 'shadow'")
        ),
        Index(
            "uq_ml_models_approved",
            "kind",
            unique=True,
            postgresql_where=text("status = 'approved'"),
        ),
    )

    number: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    training_set_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    weights: Mapped[dict[str, float]] = mapped_column(JSONB, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="trained")
    trained_by: Mapped[uuid.UUID] = mapped_column(nullable=False)
    note: Mapped[str | None] = mapped_column(String(500))
    kind: Mapped[str] = mapped_column(String(12), nullable=False, server_default="ranker")
    # The learned parameters as plain data (coefficients, or LightGBM's own text format), so a
    # model can be loaded without unpickling anything.
    artifact: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    card: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    shadow_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[uuid.UUID | None] = mapped_column()
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approval_note: Mapped[str | None] = mapped_column(String(1000))


class MlShadowRun(UUIDPk, Timestamps, Base):
    """What the shadow model would have picked for one recommendation, next to what the rules
    picked. Never shown in a BOQ; only in the agreement report."""

    __tablename__ = "ml_shadow_runs"
    __table_args__ = (UniqueConstraint("model_id", "boq_id", "rec_key", name="uq_ml_shadow_runs"),)

    model_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    boq_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    rec_key: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(60), nullable=False)
    rule_top: Mapped[str] = mapped_column(String(300), nullable=False)
    model_top: Mapped[str] = mapped_column(String(300), nullable=False)
    agree: Mapped[bool] = mapped_column(Boolean, nullable=False)


class MlLineExample(UUIDPk, Timestamps, Base):
    """One BOQ: the audit findings it was drafted from (gap types and counts), the lines the
    rules drafted, the lines a shadow model would have drafted, and, once the customer accepts,
    the lines actually bought. Live data; training reads frozen copies only."""

    __tablename__ = "ml_line_examples"

    boq_id: Mapped[uuid.UUID] = mapped_column(nullable=False, unique=True)
    project_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    features: Mapped[dict[str, float]] = mapped_column(JSONB, nullable=False)
    rule_labels: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    titles: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False, default=dict)
    model_id: Mapped[uuid.UUID | None] = mapped_column()
    model_labels: Mapped[list[str] | None] = mapped_column(JSONB)
    labels: Mapped[list[str] | None] = mapped_column(JSONB)
    labelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MlPricePoint(UUIDPk, Base):
    """One price entered in the price book, for spotting a price that does not fit its history.
    The rule verdict is deterministic; a shadow model's verdict is kept next to it."""

    __tablename__ = "ml_price_points"
    __table_args__ = (Index("ix_ml_price_points_item", "item_id", "quoted_on"),)

    price_id: Mapped[uuid.UUID] = mapped_column(nullable=False, unique=True)
    item_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    item_name: Mapped[str] = mapped_column(String(300), nullable=False)
    category: Mapped[str] = mapped_column(String(60), nullable=False)
    item_kind: Mapped[str] = mapped_column(String(10), nullable=False)
    vendor: Mapped[str | None] = mapped_column(String(64))
    selling: Mapped[float] = mapped_column(Float, nullable=False)
    cost: Mapped[float | None] = mapped_column(Float)
    quoted_on: Mapped[date] = mapped_column(Date, nullable=False)
    rule_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rule_reason: Mapped[str | None] = mapped_column(String(300))
    change_pct: Mapped[float | None] = mapped_column(Float)
    model_id: Mapped[uuid.UUID | None] = mapped_column()
    model_expected: Mapped[float | None] = mapped_column(Float)
    model_flag: Mapped[bool | None] = mapped_column(Boolean)
    alerted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
