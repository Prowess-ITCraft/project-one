from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.modules.identity.permissions import Role

_PHONE_RE = re.compile(r"^\+?[0-9 ()-]{7,20}$")


class StrictIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LoginIn(StrictIn):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class MfaVerifyIn(StrictIn):
    challenge_token: str = Field(min_length=20, max_length=2000)
    code: str | None = Field(default=None, min_length=6, max_length=7)
    recovery_code: str | None = Field(default=None, min_length=10, max_length=20)


class MfaEnrolStartIn(StrictIn):
    enrol_token: str | None = Field(default=None, min_length=20, max_length=2000)


class MfaEnrolConfirmIn(StrictIn):
    enrol_token: str | None = Field(default=None, min_length=20, max_length=2000)
    code: str = Field(min_length=6, max_length=7)


class RefreshIn(StrictIn):
    refresh_token: str | None = Field(default=None, min_length=20, max_length=200)


class TokenOut(BaseModel):
    status: Literal["authenticated"] = "authenticated"
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 (OAuth2 token type, not a secret)
    access_token: str | None = None
    access_expires_at: datetime
    refresh_token: str | None = None
    refresh_expires_at: datetime


class ChallengeOut(BaseModel):
    status: Literal["mfa_required", "mfa_enrolment_required"]
    challenge_token: str
    expires_at: datetime


class MfaEnrolStartOut(BaseModel):
    secret: str
    otpauth_uri: str
    qr_svg: str  # data URL of the QR code for the URI, so a desktop user can scan it


class MfaEnrolConfirmOut(BaseModel):
    recovery_codes: list[str]
    tokens: TokenOut | None = None


class SessionOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime
    ip: str | None
    user_agent: str | None
    current: bool


class UserCreateIn(StrictIn):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=200)
    initials: str = Field(min_length=1, max_length=6, pattern=r"^[A-Za-z]{1,6}$")
    designation: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=20)
    password: str = Field(min_length=12, max_length=128)
    roles: list[Role] = Field(min_length=1, max_length=len(Role))
    customer_id: uuid.UUID | None = None

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        if v is not None and not _PHONE_RE.match(v):
            raise ValueError("phone must be 7 to 20 digits, optionally with + ( ) -")
        return v

    @field_validator("initials")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()


class UserUpdateIn(StrictIn):
    version: int = Field(ge=1)
    full_name: str | None = Field(default=None, min_length=2, max_length=200)
    initials: str | None = Field(default=None, pattern=r"^[A-Za-z]{1,6}$")
    designation: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=20)
    is_active: bool | None = None

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        if v is not None and not _PHONE_RE.match(v):
            raise ValueError("phone must be 7 to 20 digits, optionally with + ( ) -")
        return v


class RolesIn(StrictIn):
    version: int = Field(ge=1)
    roles: list[Role] = Field(min_length=1, max_length=len(Role))


class PasswordChangeIn(StrictIn):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class PasswordResetIn(StrictIn):
    new_password: str = Field(min_length=12, max_length=128)


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    initials: str
    designation: str | None
    phone: str | None
    roles: list[Role]
    is_active: bool
    mfa_enabled: bool
    customer_id: uuid.UUID | None
    locked_until: datetime | None
    last_login_at: datetime | None
    created_at: datetime
    version: int


class MeOut(UserOut):
    permissions: list[str]
    mfa_required: bool
