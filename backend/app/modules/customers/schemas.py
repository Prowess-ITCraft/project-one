from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.money import Amount
from app.modules.customers.stages import Stage
from app.modules.identity.contracts import Role

_GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
_GSTIN_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_PINCODE_RE = re.compile(r"^[1-9][0-9]{5}$")
_PHONE_RE = re.compile(r"^\+?[0-9 ()-]{7,20}$")

Segment = Literal["micro", "small", "medium", "large"]
ProjectStatus = Literal["active", "on_hold", "completed", "cancelled"]


def gstin_checksum_ok(gstin: str) -> bool:
    """GSTIN check digit: weighted base-36 sum over the first 14 characters."""
    total = 0
    for i, ch in enumerate(gstin[:14]):
        value = _GSTIN_CHARS.index(ch) * (2 if i % 2 else 1)
        total += value // 36 + value % 36
    check = (36 - total % 36) % 36
    return _GSTIN_CHARS[check] == gstin[14]


def validate_gstin(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip().upper()
    if not _GSTIN_RE.match(v) or not gstin_checksum_ok(v):
        raise ValueError("GSTIN is not valid. It has 15 characters, for example 27AAPCP3476M1ZL")
    return v


def validate_pincode(v: str) -> str:
    if not _PINCODE_RE.match(v):
        raise ValueError("PIN code must be 6 digits and cannot start with 0")
    return v


def validate_phone(v: str | None) -> str | None:
    if v is not None and not _PHONE_RE.match(v):
        raise ValueError("phone must be 7 to 20 digits, optionally with + ( ) -")
    return v


class StrictIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AddressIn(StrictIn):
    address_line1: str = Field(min_length=3, max_length=250)
    address_line2: str | None = Field(default=None, max_length=250)
    city: str = Field(min_length=2, max_length=100)
    state: str = Field(min_length=2, max_length=100)
    pincode: str

    _pin = field_validator("pincode")(validate_pincode)


class CustomerCreateIn(AddressIn):
    legal_name: str = Field(min_length=2, max_length=250)
    display_name: str | None = Field(default=None, min_length=2, max_length=120)
    gstin: str | None = None
    segment: Segment = "small"
    industry: str | None = Field(default=None, max_length=120)
    employee_count: int | None = Field(default=None, ge=1, le=1_000_000)
    notes: str | None = Field(default=None, max_length=5000)
    account_owner_id: uuid.UUID | None = None

    _gst = field_validator("gstin")(validate_gstin)


class CustomerUpdateIn(StrictIn):
    version: int = Field(ge=1)
    legal_name: str | None = Field(default=None, min_length=2, max_length=250)
    display_name: str | None = Field(default=None, min_length=2, max_length=120)
    gstin: str | None = None
    segment: Segment | None = None
    industry: str | None = Field(default=None, max_length=120)
    employee_count: int | None = Field(default=None, ge=1, le=1_000_000)
    address_line1: str | None = Field(default=None, min_length=3, max_length=250)
    address_line2: str | None = Field(default=None, max_length=250)
    city: str | None = Field(default=None, min_length=2, max_length=100)
    state: str | None = Field(default=None, min_length=2, max_length=100)
    pincode: str | None = None
    notes: str | None = Field(default=None, max_length=5000)
    account_owner_id: uuid.UUID | None = None

    _gst = field_validator("gstin")(validate_gstin)

    @field_validator("pincode")
    @classmethod
    def _pin(cls, v: str | None) -> str | None:
        return validate_pincode(v) if v is not None else None


class CustomerOut(BaseModel):
    id: uuid.UUID
    code: str
    legal_name: str
    display_name: str
    gstin: str | None
    segment: str
    industry: str | None
    employee_count: int | None
    address_line1: str
    address_line2: str | None
    city: str
    state: str
    pincode: str
    country: str
    notes: str | None
    account_owner_id: uuid.UUID | None
    created_at: datetime
    deleted_at: datetime | None
    version: int


class SiteIn(AddressIn):
    name: str = Field(min_length=2, max_length=120)
    is_primary: bool = False


class SiteUpdateIn(StrictIn):
    version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=2, max_length=120)
    address_line1: str | None = Field(default=None, min_length=3, max_length=250)
    address_line2: str | None = Field(default=None, max_length=250)
    city: str | None = Field(default=None, min_length=2, max_length=100)
    state: str | None = Field(default=None, min_length=2, max_length=100)
    pincode: str | None = None
    is_primary: bool | None = None

    @field_validator("pincode")
    @classmethod
    def _pin(cls, v: str | None) -> str | None:
        return validate_pincode(v) if v is not None else None


class SiteOut(BaseModel):
    id: uuid.UUID
    customer_id: uuid.UUID
    name: str
    address_line1: str
    address_line2: str | None
    city: str
    state: str
    pincode: str
    is_primary: bool
    deleted_at: datetime | None
    version: int


class ContactIn(StrictIn):
    full_name: str = Field(min_length=2, max_length=200)
    designation: str | None = Field(default=None, max_length=120)
    email: EmailStr | None = None
    phone: str | None = None
    site_id: uuid.UUID | None = None
    is_primary: bool = False
    can_sign_off: bool = False

    _ph = field_validator("phone")(validate_phone)


class ContactUpdateIn(StrictIn):
    version: int = Field(ge=1)
    full_name: str | None = Field(default=None, min_length=2, max_length=200)
    designation: str | None = Field(default=None, max_length=120)
    email: EmailStr | None = None
    phone: str | None = None
    site_id: uuid.UUID | None = None
    is_primary: bool | None = None
    can_sign_off: bool | None = None

    _ph = field_validator("phone")(validate_phone)


class ContactOut(BaseModel):
    id: uuid.UUID
    customer_id: uuid.UUID
    site_id: uuid.UUID | None
    full_name: str
    designation: str | None
    email: str | None
    phone: str | None
    is_primary: bool
    can_sign_off: bool
    deleted_at: datetime | None
    version: int


class RepresentativeIn(StrictIn):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=200)
    phone: str | None = None
    password: str = Field(min_length=12, max_length=128)

    _ph = field_validator("phone")(validate_phone)


class ProjectCreateIn(StrictIn):
    customer_id: uuid.UUID
    site_id: uuid.UUID | None = None
    name: str = Field(min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=5000)


class ProjectUpdateIn(StrictIn):
    version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    site_id: uuid.UUID | None = None
    status: Literal["active", "on_hold", "cancelled"] | None = None


class MemberOut(BaseModel):
    user_id: uuid.UUID
    full_name: str | None
    project_role: str
    added_at: datetime


class ProjectOut(BaseModel):
    id: uuid.UUID
    code: str
    customer_id: uuid.UUID
    site_id: uuid.UUID | None
    name: str
    description: str | None
    current_stage: Stage
    status: str
    created_at: datetime
    deleted_at: datetime | None
    version: int


class MemberIn(StrictIn):
    user_id: uuid.UUID
    project_role: Role


class GateConfigOut(BaseModel):
    stage: Stage
    label: str
    approver_roles: list[Role]
    artifact_type: str | None
    requires_artifact: bool
    requires_customer_ack: bool
    version: int


class GateConfigIn(StrictIn):
    version: int = Field(ge=1)
    approver_roles: list[Role] = Field(min_length=1)
    requires_artifact: bool
    requires_customer_ack: bool

    @field_validator("approver_roles")
    @classmethod
    def _no_customer(cls, v: list[Role]) -> list[Role]:
        if Role.CUSTOMER_REP in v:
            raise ValueError("customers acknowledge stages; they do not approve gates")
        return v


class ArtifactOut(BaseModel):
    id: uuid.UUID
    stage: Stage
    artifact_type: str
    artifact_id: str
    artifact_version: int
    title: str
    locked_at: datetime


class SubmitIn(StrictIn):
    note: str | None = Field(default=None, max_length=2000)
    artifact_id: uuid.UUID | None = None


class DecisionIn(StrictIn):
    comment: str | None = Field(default=None, max_length=2000)


class RejectIn(StrictIn):
    comment: str = Field(min_length=5, max_length=2000)


class SubmissionOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    stage: Stage
    status: str
    submitted_by: uuid.UUID
    note: str | None
    artifact_id: uuid.UUID | None
    requires_customer_ack: bool
    customer_ack_at: datetime | None
    created_at: datetime


class DecisionOut(BaseModel):
    id: uuid.UUID
    submission_id: uuid.UUID
    stage: Stage
    decision: str
    decided_by: uuid.UUID
    decided_by_name: str
    decided_at: datetime
    comment: str | None
    artifact_type: str | None
    artifact_ref: str | None
    artifact_version: int | None


class StageStatusOut(BaseModel):
    stage: Stage
    label: str
    state: Literal["done", "current", "locked"]
    decision: DecisionOut | None
    pending_submission: SubmissionOut | None


class ProjectTrackerOut(BaseModel):
    project: ProjectOut
    stages: list[StageStatusOut]


class AckIssueIn(StrictIn):
    contact_id: uuid.UUID
    valid_hours: int = Field(default=72, ge=1, le=168)


class AckIssueOut(BaseModel):
    ack_id: uuid.UUID
    url: str
    expires_at: datetime


class AckViewOut(BaseModel):
    customer_name: str
    project_name: str
    stage_label: str
    contact_name: str
    expires_at: datetime
    already_acknowledged: bool


class AckConfirmIn(StrictIn):
    full_name: str = Field(min_length=2, max_length=200)
    accept: Literal[True]


# ------------------------------------------------------------------ brief and stage return

CompanySize = Literal["micro", "small", "medium", "large"]
BudgetTier = Literal["essential", "standard", "premium"]


class BriefIn(StrictIn):
    version: int | None = Field(default=None, ge=1, description="Omit when creating the brief")
    company_size: CompanySize
    budget_tier: BudgetTier = "standard"
    users_now: int | None = Field(default=None, ge=1, le=100_000)
    users_12m: int | None = Field(default=None, ge=1, le=100_000)
    sites: int = Field(default=1, ge=1, le=500)
    preferred_brands: list[str] = Field(default_factory=list, max_length=20)
    excluded_brands: list[str] = Field(default_factory=list, max_length=20)
    budget_ceiling: Amount | None = None
    category_budgets: dict[str, Amount] = Field(default_factory=dict, max_length=30)
    keep_assets: list[str] = Field(default_factory=list, max_length=50)
    compliance: list[str] = Field(default_factory=list, max_length=20)
    notes: str | None = Field(default=None, max_length=3000)


class BriefOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_id: uuid.UUID
    company_size: str
    budget_tier: str
    users_now: int | None
    users_12m: int | None
    sites: int
    preferred_brands: list[str]
    excluded_brands: list[str]
    budget_ceiling: Amount | None
    category_budgets: dict[str, Any]
    keep_assets: list[str]
    compliance: list[str]
    notes: str | None
    version: int
    updated_at: datetime


class ReturnIn(StrictIn):
    reason: str = Field(min_length=5, max_length=1000)
