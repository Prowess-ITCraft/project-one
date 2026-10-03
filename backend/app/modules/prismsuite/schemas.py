from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Pointer = Annotated[str, StringConstraints(pattern=r"^(/[A-Za-z0-9_\-]+)+$", max_length=200)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ImportCreateIn(_In):
    project_id: uuid.UUID
    file_id: uuid.UUID
    kind: Literal["baseline", "rescan"] = "baseline"


class CorrectionIn(_In):
    path: Pointer
    value: Any = None
    reason: Reason
    resolves: Annotated[str, StringConstraints(max_length=200)] | None = Field(
        default=None, description="A read-report field this value settles, e.g. a conflict."
    )
    version: int = Field(ge=1, description="The import version you last read (optimistic lock).")


class ResolveIn(_In):
    path: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    reason: Reason
    version: int = Field(ge=1)


class DecisionIn(_In):
    note: Annotated[str, StringConstraints(max_length=1000)] | None = None
    version: int = Field(ge=1)


class RejectIn(_In):
    reason: Reason
    version: int = Field(ge=1)


class ImportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    file_id: uuid.UUID
    revision: int
    kind: str
    parser_name: str
    schema_version: str
    status: str
    imported_by: uuid.UUID
    decided_by: uuid.UUID | None
    decided_at: datetime | None
    decision_note: str | None
    version: int
    created_at: datetime
    read_summary: dict[str, Any] = Field(default_factory=dict)


class CorrectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    path: str
    old_value: Any
    new_value: Any
    reason: str
    corrected_by: uuid.UUID
    corrected_at: datetime


class ImportDetailOut(ImportOut):
    snapshot: dict[str, Any]
    read_report: dict[str, Any]
    corrections: list[CorrectionOut]
