from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=300)]
Short = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class EvidenceItem(BaseModel):
    type: str
    label: Short
    required: bool = True


class Settings(BaseModel):
    work_start: str = "10:00"
    work_end: str = "18:00"
    work_days: list[int] = [0, 1, 2, 3, 4, 5]
    buffer_minutes: int = 30


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    ref: str
    sequence: int
    kind: str
    title: str
    boq_line_ref: str | None
    asset: str | None
    minutes: int
    depends_on: list[str]
    assignee_id: uuid.UUID | None
    start_at: datetime | None
    end_at: datetime | None
    requires_downtime: bool
    device_type: str | None
    steps: list[str]
    evidence: list[dict[str, Any]]
    notes: str | None
    source: str
    last_change_reason: str | None
    version: int


class BaselineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    task_ref: str | None
    device_type: str
    device_label: str
    fields: list[dict[str, Any]]
    version: int


class WindowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    start_at: datetime
    end_at: datetime
    note: str | None


class PlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    project_id: uuid.UUID
    number: int
    status: str
    boq_quote_ref: str
    start_date: date | None
    settings: dict[str, Any]
    warnings: list[str]
    baselined_at: datetime | None
    version: int


class PlanDetailOut(BaseModel):
    plan: PlanOut
    tasks: list[TaskOut]
    baselines: list[BaselineOut]
    windows: list[WindowOut]
    ends_at: datetime | None
    total_minutes: int


class GenerateIn(BaseModel):
    replace: bool = False
    settings: Settings | None = None


class ScheduleIn(BaseModel):
    start_date: date
    auto_assign: bool = True
    settings: Settings | None = None


class TaskPatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int
    reason: Reason
    title: Short | None = None
    minutes: int | None = None
    depends_on: list[str] | None = None
    assignee_id: uuid.UUID | None = None
    requires_downtime: bool | None = None
    notes: Annotated[str, StringConstraints(max_length=2000)] | None = None
    steps: list[Short] | None = None
    evidence: list[EvidenceItem] | None = None


class TaskCreateIn(BaseModel):
    reason: Reason
    title: Short
    minutes: int = 60
    depends_on: list[str] = Field(default_factory=list)
    steps: list[Short] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    requires_downtime: bool = False
    device_type: str | None = None


class ReasonIn(BaseModel):
    reason: Reason


class BaselineField(BaseModel):
    key: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,40}$")]
    label: Short
    expected: Short
    severity: str
    check: str = "screenshot"


class BaselinePatchIn(BaseModel):
    version: int
    reason: Reason
    fields: list[BaselineField]


class LeaveIn(BaseModel):
    user_id: uuid.UUID
    date_from: date
    date_to: date
    reason: Annotated[str, StringConstraints(max_length=200)] | None = None


class LeaveOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    user_id: uuid.UUID
    date_from: date
    date_to: date
    reason: str | None


class WindowIn(BaseModel):
    start_at: datetime
    end_at: datetime
    note: Annotated[str, StringConstraints(max_length=200)] | None = None


class TaskTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    key: str
    title: str
    minutes_fixed: int
    minutes_per_unit: int
    split_per_unit: bool
    requires_downtime: bool
    device_type: str | None
    depends_on_kinds: list[str]
    steps: list[str]
    evidence: list[dict[str, Any]]
    active: bool
    version: int


class TaskTemplatePatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int
    title: Short | None = None
    minutes_fixed: Annotated[int, Field(ge=0, le=14400)] | None = None
    minutes_per_unit: Annotated[int, Field(ge=0, le=14400)] | None = None
    requires_downtime: bool | None = None
    steps: list[Short] | None = None
    evidence: list[EvidenceItem] | None = None
    active: bool | None = None


class ConfigTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    device_type: str
    title: str
    fields: list[dict[str, Any]]
    version: int
