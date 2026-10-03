from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, Query, UploadFile
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.modules.files.contracts import read_limited
from app.modules.identity.contracts import P, Principal, require
from app.modules.verification import service

router = APIRouter(prefix="/verification", tags=["verification"])
dashboard_router = APIRouter(prefix="/dashboard", tags=["verification"])
Session = Annotated[AsyncSession, Depends(get_session)]
Reader = Annotated[Principal, Depends(require(P.FIELD_READ))]
Verifier = Annotated[Principal, Depends(require(P.FIELD_VERIFY))]
Mapper = Annotated[Principal, Depends(require(P.TEMPLATE_EDIT))]
PolicyEditor = Annotated[Principal, Depends(require(P.POLICY_EDIT))]
DashboardReader = Annotated[Principal, Depends(require(P.DASHBOARD_READ))]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)]
Severity = Literal["critical", "major", "minor"]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DeviationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    run_id: uuid.UUID
    task_ref: str
    device: str | None
    field_key: str
    label: str
    severity: str
    expected: str | None
    actual: str | None
    reason: str | None
    source: str
    opened_attempt: int | None
    status: str
    resolution: str | None
    created_at: datetime
    resolved_at: datetime | None


class DeviationIn(_In):
    run_id: uuid.UUID
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=200)]
    severity: Severity
    note: Text
    field_key: Annotated[str, StringConstraints(max_length=60)] | None = None


class NoteIn(_In):
    note: Text


def _critical_only() -> list[Severity]:
    return ["critical"]


class PolicyIn(_In):
    certificate_blocking: list[Severity] = Field(min_length=1)
    not_acceptable: list[Severity] = Field(default_factory=_critical_only)
    note: Annotated[str, StringConstraints(max_length=500)] | None = None


class MapOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    brand: str
    device_type: str
    field_key: str
    keys: list[str]
    rule: dict[str, Any]
    verified: bool
    note: str | None
    version: int


class RuleIn(_In):
    op: Literal["truthy", "falsy", "eq", "ne", "in", "not_in", "version_gte", "record"]
    value: str | list[str] | None = None


class MapPatchIn(_In):
    version: int
    keys: list[Annotated[str, StringConstraints(min_length=1, max_length=120)]] | None = Field(
        default=None, max_length=20
    )
    rule: RuleIn | None = None
    verified: bool | None = None
    note: Annotated[str, StringConstraints(max_length=500)] | None = None


def _dev(d: Any) -> DeviationOut:
    return DeviationOut.model_validate(d, from_attributes=True)


@router.get("/projects/{project_id}/deviations", response_model=list[DeviationOut])
async def deviations(
    session: Session,
    principal: Reader,
    project_id: uuid.UUID,
    status: Annotated[Literal["open", "resolved", "accepted", "waived"] | None, Query()] = None,
) -> list[DeviationOut]:
    return [_dev(d) for d in await service.list_deviations(session, principal, project_id, status)]


@router.post("/deviations", response_model=DeviationOut, status_code=201)
async def add_deviation(session: Session, principal: Verifier, body: DeviationIn) -> DeviationOut:
    """Record a deviation the check could not judge. The engineer who did the task cannot."""
    return _dev(
        await service.add_deviation(
            session,
            principal,
            body.run_id,
            label=body.label,
            severity=body.severity,
            note=body.note,
            field_key=body.field_key,
        )
    )


@router.post("/deviations/{deviation_id}/accept", response_model=DeviationOut)
async def accept(
    session: Session, principal: Verifier, deviation_id: uuid.UUID, body: NoteIn
) -> DeviationOut:
    """Accept a deviation with a reason. Severities the policy marks not acceptable must be fixed
    or waived instead."""
    return _dev(await service.accept_deviation(session, principal, deviation_id, note=body.note))


@router.get("/policy")
async def get_policy(session: Session, principal: Reader) -> dict[str, Any]:
    return await service.get_policy(session)


@router.put("/policy")
async def put_policy(session: Session, principal: PolicyEditor, body: PolicyIn) -> dict[str, Any]:
    """Which open severities stop the certificate, and which a verifier may not accept."""
    return await service.set_policy(session, principal, body.model_dump(exclude_none=True))


@router.get("/mappings", response_model=list[MapOut])
async def mappings(
    session: Session, principal: Mapper, brand: Annotated[str | None, Query(max_length=30)] = None
) -> list[MapOut]:
    return [
        MapOut.model_validate(m, from_attributes=True)
        for m in await service.list_maps(session, principal, brand)
    ]


@router.patch("/mappings/{map_id}", response_model=MapOut)
async def patch_mapping(
    session: Session, principal: Mapper, map_id: uuid.UUID, body: MapPatchIn
) -> MapOut:
    changes = body.model_dump(exclude={"version"}, exclude_none=True)
    return MapOut.model_validate(
        await service.update_map(session, principal, map_id, version=body.version, changes=changes),
        from_attributes=True,
    )


@router.post("/inspect")
async def inspect(
    session: Session, principal: Mapper, file: Annotated[UploadFile, File()]
) -> dict[str, Any]:
    """What a configuration export contains and which settings the mappings would read. Nothing
    is stored."""
    data = await read_limited(file, get_settings().max_upload_bytes)
    return await service.inspect_export(
        session, principal, name=file.filename or "export", data=data
    )


@dashboard_router.get("")
async def dashboard(session: Session, principal: DashboardReader) -> dict[str, Any]:
    """The Director's view: every active project, its stage, field progress, blocked work with
    reasons, open deviations, check-ins today and whether it is behind plan."""
    return await service.dashboard(session, principal)


routers = [router, dashboard_router]
