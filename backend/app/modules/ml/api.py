from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.modules.identity.contracts import P, Principal, require
from app.modules.ml import service

router = APIRouter(prefix="/ml", tags=["learning"])
Session = Annotated[AsyncSession, Depends(get_session)]
Reader = Annotated[Principal, Depends(require(P.ML_READ))]
Manager = Annotated[Principal, Depends(require(P.ML_MANAGE))]


class TrainingSetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    number: int
    data_card: dict[str, Any]
    frozen_at: datetime


class ModelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    number: int
    training_set_id: uuid.UUID
    weights: dict[str, float]
    metrics: dict[str, Any]
    status: str
    created_at: datetime


class TrainIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    training_set_id: uuid.UUID


class StatusIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["shadow", "retired"]


@router.get("/report")
async def report(session: Session, principal: Reader) -> dict[str, Any]:
    """How much the ranker has to learn from, and how the shadow model compares with the rules."""
    return await service.report(session, principal)


@router.get("/training-sets", response_model=list[TrainingSetOut])
async def training_sets(session: Session, principal: Reader) -> Any:
    return await service.list_training_sets(session, principal)


@router.post("/training-sets", response_model=TrainingSetOut, status_code=201)
async def freeze(session: Session, principal: Manager) -> Any:
    """Freeze every labelled example into a new numbered training set with a data card."""
    return await service.freeze_training_set(session, principal)


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
    """Run a model in shadow mode (it never changes a BOQ) or retire it."""
    return await service.set_status(session, principal, model_id, body.status)


routers = [router]
