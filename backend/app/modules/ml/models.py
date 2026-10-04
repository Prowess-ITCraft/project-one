from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk

MODEL_STATUSES = ("trained", "shadow", "retired")


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
    rows: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    data_card: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    frozen_by: Mapped[uuid.UUID] = mapped_column(nullable=False)
    frozen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class MlModel(UUIDPk, Timestamps, Base):
    """Learned criteria weights from one training set. At most one runs in shadow mode."""

    __tablename__ = "ml_models"
    __table_args__ = (
        Index(
            "uq_ml_models_shadow", "status", unique=True, postgresql_where=text("status = 'shadow'")
        ),
    )

    number: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    training_set_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    weights: Mapped[dict[str, float]] = mapped_column(JSONB, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="trained")
    trained_by: Mapped[uuid.UUID] = mapped_column(nullable=False)
    note: Mapped[str | None] = mapped_column(String(500))


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
