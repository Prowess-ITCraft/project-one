from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]
Code = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\d{6}$")]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClientIn(_In):
    """Every engineer action may come from the offline queue: `client_event_id` makes a resend
    harmless and `captured_at` is when it really happened (up to 72 hours ago)."""

    client_event_id: uuid.UUID | None = None
    captured_at: datetime | None = None


class LocatedIn(ClientIn):
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    accuracy_m: float | None = Field(default=None, ge=0, le=100_000)


class CodeIn(LocatedIn):
    code: Code | None = None  # needed only while customer codes are on


class StepIn(ClientIn):
    note: Annotated[str, StringConstraints(max_length=1000)] | None = None


class ValuesIn(ClientIn):
    values: dict[
        Annotated[str, StringConstraints(max_length=40)],
        Annotated[str, StringConstraints(max_length=200)],
    ] = Field(min_length=1, max_length=50)


class BlockIn(ClientIn):
    reason: Reason


class NoteIn(_In):
    note: Reason


class ReassignIn(_In):
    assignee_id: uuid.UUID
    reason: Reason


class DecisionIn(_In):
    decision: Literal["approve", "reject"]
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None = None


class RunOut(BaseModel):
    """A task in the field. There are no prices anywhere in field work (ADR 0003)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    task_ref: str
    kind: str
    title: str
    asset: str | None
    device_type: str | None
    requires_downtime: bool
    depends_on: list[str]
    steps: list[dict[str, Any]]
    evidence_reqs: list[dict[str, Any]]
    baseline: list[dict[str, Any]]
    actuals: dict[str, Any]
    assignee_id: uuid.UUID
    planned_start: datetime
    planned_end: datetime
    state: str
    blocked_from: str | None
    block_reason: str | None
    state_changed_at: datetime
    accepted_at: datetime | None
    checked_in_at: datetime | None
    handed_over_at: datetime | None
    closed_at: datetime | None
    verified_by: uuid.UUID | None
    last_check_passed: bool | None
    rework_count: int
    version: int


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    seq: int
    run_id: uuid.UUID
    at: datetime
    captured_at: datetime | None
    actor_id: uuid.UUID | None
    action: str
    from_state: str | None
    to_state: str | None
    detail: dict[str, Any]
    lat: float | None
    lng: float | None


class EvidenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    requirement_index: int
    type: str
    file_id: uuid.UUID | None
    text_value: str | None
    note: str | None
    client_id: uuid.UUID
    captured_at: datetime
    uploaded_by: uuid.UUID
    created_at: datetime
    lat: float | None = None
    lng: float | None = None
    accuracy_m: float | None = None
    location_note: str | None = None
    stamped_file_id: uuid.UUID | None = None
    parse: dict[str, Any] | None = None
    via: str = "app"


class CheckOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    attempt: int
    driver: str
    passed: bool
    deviations: int
    critical_open: int
    result: dict[str, Any]
    created_at: datetime


class ProjectBriefOut(BaseModel):
    """Which job a task belongs to. Task refs (T01, T02) restart in every project, so an
    engineer needs this to tell two sites apart."""

    code: str
    name: str
    customer: str | None


class MyRunOut(RunOut):
    project: ProjectBriefOut | None = None


class RunDetailOut(BaseModel):
    run: RunOut
    project: ProjectBriefOut | None = None
    events: list[EventOut]
    evidence: list[EvidenceOut]
    checks: list[CheckOut]
    waiting_on: list[str]
    next_action: str
    customer_codes: bool  # whether check-in and hand over ask for the customer's code


class UploadLinkIn(_In):
    requirement_index: int = Field(ge=0, le=100)


class UploadLinkOut(BaseModel):
    """Shown once. The token itself is never stored, only its hash."""

    url: str
    path: str
    expires_at: datetime
    valid_minutes: int
    qr_svg: str


class UploadLinkInfoOut(BaseModel):
    """What the person opening an upload link sees: the task and what to upload, nothing else."""

    task_ref: str
    title: str
    asset: str | None
    label: str
    project: str
    expires_at: datetime
    accept: str


class UploadLinkDoneOut(BaseModel):
    received: bool
    file_name: str
    parse: dict[str, Any] | None


class ConfigChangeOut(BaseModel):
    key: str
    before: str | None
    after: str | None
    change: Literal["added", "removed", "changed"]


class ConfigDiffOut(BaseModel):
    """The configuration export taken before the work (the rollback point) against the one
    after. Values that look like secrets are masked."""

    available: bool
    reason: str | None = None
    before_file: str | None = None
    after_file: str | None = None
    before_at: datetime | None = None
    after_at: datetime | None = None
    method: Literal["settings", "lines"] | None = None
    brand: str | None = None
    changes: list[ConfigChangeOut] = Field(default_factory=list)
    unchanged: int = 0
    truncated: bool = False


class DeviceStatusIn(_In):
    """What the phone reports about the work saved on it, each time it syncs or opens."""

    pending: int = Field(ge=0, le=10_000)
    failed: int = Field(ge=0, le=10_000)
    oldest_pending_at: datetime | None = None
    last_sync_at: datetime | None = None
    app_version: Annotated[str, StringConstraints(max_length=40)] | None = None
    platform: Annotated[str, StringConstraints(max_length=40)] | None = None


class EngineerStatusOut(BaseModel):
    """One field engineer as the Director sees them: is their phone holding unsent work, and
    when did it last reach us."""

    user_id: uuid.UUID
    full_name: str
    open_tasks: int
    working_now: int
    blocked: int
    pending: int
    failed: int
    oldest_pending_at: datetime | None
    last_sync_at: datetime | None
    last_seen_at: datetime | None
    last_activity_at: datetime | None
    state: Literal["synced", "waiting", "refused", "quiet", "never"]
    summary: str


class WorkloadDayOut(BaseModel):
    day: str
    tasks: int
    hours: float


class WorkloadOut(BaseModel):
    user_id: uuid.UUID
    full_name: str
    open_tasks: int
    blocked: int
    overdue: int
    hours_next_14_days: float
    days: list[WorkloadDayOut]


class CodeSentOut(BaseModel):
    sent_to: str
    expires_at: datetime
    valid_minutes: int


class SummaryOut(BaseModel):
    counts: dict[str, int]
    total: int
    closed_share: float
    blocked: list[RunOut]
    late: list[RunOut]
    overdue: list[RunOut]
    failing_checks: list[RunOut]
    rework: int
