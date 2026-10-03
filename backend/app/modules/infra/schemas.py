from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]
Component = Literal[
    "endpoint", "server", "firewall", "nas", "switch", "router", "access_point", "general"
]
Lens = Literal["productivity", "resilience", "security", "health"]
Priority = Literal["high", "consider"]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    title: str
    component: str
    lens: str
    gap_type: str
    priority: str
    priority_overrides: list[dict[str, Any]]
    when: dict[str, Any]
    verify_if_unknown: bool
    affected_list: str | None
    qty_fact: str | None
    recommendation: str
    target: str
    company_sizes: list[str]
    budget_tiers: list[str]
    rule_version: int
    active: bool


class RuleBody(_In):
    code: Annotated[str, StringConstraints(max_length=40)] | None = None
    title: Annotated[str, StringConstraints(min_length=3, max_length=200)] | None = None
    component: Component | None = None
    lens: Lens | None = None
    gap_type: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{2,59}$")] | None = None
    priority: Priority | None = None
    priority_overrides: list[dict[str, Any]] | None = Field(default=None, max_length=10)
    when: dict[str, Any] | None = None
    verify_if_unknown: bool | None = None
    affected_list: str | None = None
    qty_fact: str | None = None
    recommendation: Annotated[str, StringConstraints(max_length=2000)] | None = None
    target: Annotated[str, StringConstraints(max_length=1000)] | None = None
    company_sizes: list[Literal["micro", "small", "medium", "large"]] | None = None
    budget_tiers: list[Literal["essential", "standard", "premium"]] | None = None


class RuleChangeIn(_In):
    rule_id: uuid.UUID | None = None
    kind: Literal["create", "update", "deactivate"]
    proposed: RuleBody = Field(default_factory=RuleBody)
    reason: Reason


class RuleChangeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    rule_id: uuid.UUID | None
    kind: str
    proposed: dict[str, Any]
    before: dict[str, Any] | None
    reason: str
    status: str
    submitted_by: uuid.UUID
    decided_by: uuid.UUID | None
    decision_note: str | None
    created_at: datetime


class DecisionIn(_In):
    approve: bool
    note: Annotated[str, StringConstraints(max_length=500)] | None = None


class StateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    kind: str
    number: int
    status: str
    data: dict[str, Any]
    created_by: uuid.UUID
    locked_by: uuid.UUID | None
    locked_at: datetime | None
    created_at: datetime


class GapOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    register_id: uuid.UUID
    number: int
    code: str = ""
    rule_code: str | None
    rule_version: int | None
    gap_type: str
    component: str
    lens: str
    title: str
    description: str | None
    priority: str
    status: str
    source: str
    affected: list[str]
    qty_hint: int | None
    evidence: dict[str, Any]
    recommendation: str | None
    last_change_reason: str | None
    version: int


class RegisterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    number: int
    status: str
    created_by: uuid.UUID
    locked_by: uuid.UUID | None
    locked_at: datetime | None
    created_at: datetime
    version: int


class RegisterDetailOut(RegisterOut):
    gaps: list[GapOut]
    counts: dict[str, int]


class GapUpdateIn(_In):
    version: int = Field(ge=1)
    reason: Reason
    title: Annotated[str, StringConstraints(min_length=3, max_length=200)] | None = None
    description: Annotated[str, StringConstraints(max_length=2000)] | None = None
    priority: Priority | None = None
    status: Literal["open", "accepted", "disputed", "dismissed"] | None = None
    affected: list[Annotated[str, StringConstraints(max_length=200)]] | None = Field(
        default=None, max_length=500
    )
    qty_hint: int | None = Field(default=None, ge=0, le=100_000)
    recommendation: Annotated[str, StringConstraints(max_length=2000)] | None = None


class ManualGapIn(_In):
    reason: Reason
    title: Annotated[str, StringConstraints(min_length=3, max_length=200)]
    description: Annotated[str, StringConstraints(max_length=2000)] | None = None
    component: Component
    lens: Lens
    gap_type: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{2,59}$")]
    priority: Priority = "consider"
    affected: list[Annotated[str, StringConstraints(max_length=200)]] = Field(
        default_factory=list, max_length=500
    )
    qty_hint: int | None = Field(default=None, ge=0, le=100_000)
    recommendation: Annotated[str, StringConstraints(max_length=2000)] | None = None
