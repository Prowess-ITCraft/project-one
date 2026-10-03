"""Password hashing (argon2id), JWTs, opaque refresh tokens and TOTP."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import get_settings
from app.core.timeutil import utcnow

# OWASP 2024 argon2id baseline: m=19 MiB, t=2, p=1. We use a little more memory.
_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
# Verified against when the email is unknown, so timing does not reveal which emails exist.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(24))

TokenPurpose = Literal["access", "mfa_challenge", "mfa_enrol"]

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128
_COMMON = frozenset(
    {
        "password1234",
        "123456789012",
        "qwertyuiop12",
        "itcraft@1234",
        "welcome@1234",
        "admin@123456",
        "password@123",
        "changeme1234",
    }
)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(stored_hash or _DUMMY_HASH, password) and stored_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    return _hasher.check_needs_rehash(stored_hash)


def password_problems(password: str, *, email: str, full_name: str) -> list[str]:
    problems: list[str] = []
    if len(password) < MIN_PASSWORD_LENGTH:
        problems.append(f"Use at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password) > MAX_PASSWORD_LENGTH:
        problems.append(f"Use at most {MAX_PASSWORD_LENGTH} characters.")
    lowered = password.lower()
    if lowered in _COMMON:
        problems.append("This password is too common.")
    local = email.split("@")[0].lower()
    if len(local) >= 4 and local in lowered:
        problems.append("Do not include your email name in the password.")
    for part in full_name.lower().split():
        if len(part) >= 4 and part in lowered:
            problems.append("Do not include your name in the password.")
            break
    if len(set(password)) < 5:
        problems.append("Use a wider mix of characters.")
    return problems


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_opaque_token() -> str:
    return secrets.token_urlsafe(48)


@dataclass(frozen=True)
class TokenClaims:
    sub: uuid.UUID
    sid: uuid.UUID | None
    purpose: TokenPurpose
    exp: datetime


def issue_jwt(
    *, user_id: uuid.UUID, session_id: uuid.UUID | None, purpose: TokenPurpose, ttl: timedelta
) -> tuple[str, datetime]:
    s = get_settings()
    now = utcnow()
    exp = now + ttl
    payload: dict[str, Any] = {
        "iss": s.jwt_issuer,
        "aud": s.jwt_audience,
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "jti": uuid.uuid4().hex,
        "pur": purpose,
    }
    if session_id is not None:
        payload["sid"] = str(session_id)
    keys = s.jwt_keys()
    token = jwt.encode(payload, keys[0], algorithm="HS256", headers={"kid": _kid(keys[0])})
    return token, exp


def _kid(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def decode_jwt(token: str, *, purpose: TokenPurpose) -> TokenClaims | None:
    s = get_settings()
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        return None
    candidates = [k for k in s.jwt_keys() if _kid(k) == header.get("kid")] or []
    for key in candidates:
        try:
            data = jwt.decode(
                token,
                key,
                algorithms=["HS256"],
                audience=s.jwt_audience,
                issuer=s.jwt_issuer,
                options={"require": ["exp", "iat", "sub", "pur"]},
                leeway=5,
            )
        except jwt.PyJWTError:
            continue
        if data.get("pur") != purpose:
            return None
        try:
            return TokenClaims(
                sub=uuid.UUID(data["sub"]),
                sid=uuid.UUID(data["sid"]) if data.get("sid") else None,
                purpose=purpose,
                exp=datetime.fromtimestamp(data["exp"], tz=utcnow().tzinfo),
            )
        except (ValueError, KeyError):
            return None
    return None


# TOTP: RFC 6238, 30 s steps, 6 digits, accept one step of clock drift, never the same step twice.
TOTP_ISSUER = "Project One (IITPL)"


def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, email: str) -> str:
    return str(pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=TOTP_ISSUER))


def verify_totp(secret: str, code: str, *, last_used_step: int | None) -> int | None:
    """Returns the matched time step, or None. Rejects replays of the last used step."""
    code = code.strip().replace(" ", "")
    if not (code.isdigit() and len(code) == 6):
        return None
    totp = pyotp.TOTP(secret)
    now_step = int(utcnow().timestamp()) // 30
    for step in (now_step - 1, now_step, now_step + 1):
        if last_used_step is not None and step <= last_used_step:
            continue
        if hmac.compare_digest(totp.at(step * 30), code):
            return step
    return None


def new_recovery_codes(n: int = 10) -> list[str]:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return [
        "-".join("".join(secrets.choice(alphabet) for _ in range(5)) for _ in range(2))
        for _ in range(n)
    ]


def normalise_recovery_code(code: str) -> str:
    return code.strip().upper().replace(" ", "")
