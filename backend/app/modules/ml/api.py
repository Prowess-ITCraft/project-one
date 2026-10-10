from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.modules.identity.contracts import P, Principal, require
from app.modules.ml import service

router = APIRouter(prefix="/ml", tags=["learning"])
Session = Annotated[AsyncSession, Depends(get_session)]
Reader = Annotated[Principal, Depends(require(P.ML_READ))]
Manager = Annotated[Principal, Depends(require(P.ML_MANAGE))]
Kind = Literal["ranker", "boq_lines", "price_drift"]


class TrainingSetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    number: int
    kind: str
    data_card: dict[str, Any]
    frozen_at: datetime


class ModelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    number: int
    kind: str
    training_set_id: uuid.UUID
    weights: dict[str, float]
    metrics: dict[str, Any]
    status: str
    created_at: datetime
    shadow_started_at: datetime | None = None
    approved_at: datetime | None = None
    approval_note: str | None = None


class FreezeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Kind = "ranker"


class TrainIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    training_set_id: uuid.UUID


class StatusIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["shadow", "retired"]


class ApproveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=1000)]


class CardOut(BaseModel):
    card: dict[str, Any]
    markdown: str
    status: str
    comparisons: int


class SuggestedLineOut(BaseModel):
    label: str
    title: str
    probability: float


class SuggestionsOut(BaseModel):
    available: bool
    reason: str | None = None
    model: int | None = None
    lines: list[SuggestedLineOut]


@router.get("/report")
async def report(session: Session, principal: Reader) -> dict[str, Any]:
    """How much each kind of model has to learn from, and how a shadow model compares with the
    rules."""
    return await service.report(session, principal)


@router.get("/training-sets", response_model=list[TrainingSetOut])
async def training_sets(session: Session, principal: Reader) -> Any:
    return await service.list_training_sets(session, principal)


@router.post("/training-sets", response_model=TrainingSetOut, status_code=201)
async def freeze(
    session: Session, principal: Manager, body: Annotated[FreezeIn | None, Body()] = None
) -> Any:
    """Freeze every labelled example of one kind into a new numbered training set with a data
    card. Training only ever reads frozen sets."""
    return await service.freeze_training_set(session, principal, (body or FreezeIn()).kind)


@router.get("/models", response_model=list[ModelOut])
async def models(session: Session, principal: Reader) -> Any:
    return await service.list_models(session, principal)


@router.post("/models", response_model=ModelOut, status_code=201)
async def train(session: Session, principal: Manager, body: TrainIn) -> Any:
    """Train on one frozen training set. Refused, with the count, when there is too little data."""
    return await service.train_model(session, principal, body.training_set_id)


@router.post("/models/{model_id}/status", response_model=ModelOut)
async def set_status(
    session: Session, principal: Manager, model_id: uuid.UUID, body: StatusIn
) -> Any:
    """Run a model in shadow mode (it never changes anything) or retire it."""
    return await service.set_status(session, principal, model_id, body.status)


@router.post("/models/{model_id}/approve", response_model=ModelOut)
async def approve(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.ML_APPROVE))],
    model_id: uuid.UUID,
    body: ApproveIn,
) -> Any:
    """The Director approves a model after 30 days and 20 comparisons in shadow mode. It may then
    advise people; it still never decides."""
    return await service.approve_model(session, principal, model_id, body.note)


@router.get("/models/{model_id}/card", response_model=CardOut)
async def card(session: Session, principal: Reader, model_id: uuid.UUID) -> Any:
    """The model card: purpose, data, results, limitations and what it is never used for."""
    return await service.model_card(session, principal, model_id)


@router.get("/projects/{project_id}/suggested-lines", response_model=SuggestionsOut)
async def suggested_lines(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.BOQ_EDIT))],
    project_id: uuid.UUID,
) -> Any:
    """Lines an approved model expects from this project's audit findings. Advice only."""
    return await service.suggest_lines(session, principal, project_id)


routers = [router]
