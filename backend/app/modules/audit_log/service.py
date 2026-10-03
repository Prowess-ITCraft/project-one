"""Audit trail rules: what is recorded, how it is chained, how personal data is erased."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crypto
from app.core.timeutil import utcnow
from app.modules.audit_log.models import AuditEntry, SubjectKey

GENESIS_HASH = "0" * 64
ERASED = "[erased]"

# Never written to the audit log, even encrypted.
_SECRET_KEYS = frozenset(
    {
        "password",
        "password_hash",
        "mfa_secret",
        "mfa_secret_enc",
        "token",
        "token_hash",
        "refresh_token",
        "code_hash",
        "credentials",
        "credentials_enc",
    }
)
_HASHED_FIELDS = (
    "occurred_at",
    "actor_id",
    "actor_label",
    "action",
    "entity_type",
    "entity_id",
    "subject_id",
    "before",
    "after",
    "payload_ciphertext",
)
_CHAIN_LOCK_KEY = 0x50_31_41_55  # "P1AU": serialises inserts so the hash chain stays linear


@dataclass(frozen=True)
class AuditContext:
    actor_id: uuid.UUID | None
    actor_label: str
    ip: str | None = None
    user_agent: str | None = None
    request_id: str | None = None

    @classmethod
    def system(cls, label: str = "system") -> AuditContext:
        return cls(actor_id=None, actor_label=label)


def sanitize(data: dict[str, Any] | None) -> dict[str, Any] | None:
    if data is None:
        return None
    out: dict[str, Any] = {}
    for k, v in data.items():
        if k in _SECRET_KEYS:
            continue
        out[k] = sanitize(v) if isinstance(v, dict) else v
    cleaned: dict[str, Any] = json.loads(json.dumps(out, default=str))
    return cleaned


def diff(
    before: dict[str, Any] | None, after: dict[str, Any] | None
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Keep only keys that changed, so update entries stay readable."""
    if before is None or after is None:
        return before, after
    keys = {k for k in before.keys() | after.keys() if before.get(k) != after.get(k)}
    return {k: before.get(k) for k in keys}, {k: after.get(k) for k in keys}


def _canonical(entry: dict[str, Any]) -> str:
    return json.dumps(entry, sort_keys=True, separators=(",", ":"), default=str)


def compute_hash(prev_hash: str, fields: dict[str, Any]) -> str:
    return hashlib.sha256((prev_hash + _canonical(fields)).encode()).hexdigest()


def _hash_fields(e: AuditEntry | dict[str, Any]) -> dict[str, Any]:
    src: dict[str, Any] = e if isinstance(e, dict) else {k: getattr(e, k) for k in _HASHED_FIELDS}
    occurred: datetime = src["occurred_at"]
    return {
        "occurred_at": occurred.isoformat(),
        "actor_id": str(src["actor_id"]) if src["actor_id"] else None,
        "actor_label": src["actor_label"],
        "action": src["action"],
        "entity_type": src["entity_type"],
        "entity_id": src["entity_id"],
        "subject_id": str(src["subject_id"]) if src["subject_id"] else None,
        "before": src["before"],
        "after": src["after"],
        "payload_ciphertext": src["payload_ciphertext"],
    }


async def _subject_data_key(session: AsyncSession, subject_id: uuid.UUID) -> bytes | None:
    row = await session.get(SubjectKey, subject_id)
    if row is None:
        key = crypto.new_data_key()
        session.add(SubjectKey(subject_id=subject_id, wrapped_key=crypto.wrap_data_key(key)))
        await session.flush()
        return key
    if row.wrapped_key is None:
        return None  # erased: new personal data for an erased subject is not stored
    return crypto.unwrap_data_key(row.wrapped_key)


async def record(
    session: AsyncSession,
    ctx: AuditContext,
    *,
    action: str,
    entity_type: str,
    entity_id: str | uuid.UUID,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    subject_id: uuid.UUID | None = None,
    only_changes: bool = True,
) -> None:
    """Add an audit entry in the caller's transaction. Commit with the business change."""
    b, a = sanitize(before), sanitize(after)
    if only_changes:
        b, a = diff(b, a)
    ciphertext: str | None = None
    if subject_id is not None and (b or a):
        key = await _subject_data_key(session, subject_id)
        if key is not None:
            ciphertext = crypto.encrypt_with(
                key, json.dumps({"before": b, "after": a}, default=str).encode()
            ).decode()
        b = {"_personal_data": "encrypted"} if b is not None else None
        a = {"_personal_data": "encrypted"} if a is not None else None

    await session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _CHAIN_LOCK_KEY})
    prev = await session.scalar(select(AuditEntry.hash).order_by(AuditEntry.id.desc()).limit(1))
    prev_hash = prev or GENESIS_HASH
    fields = {
        "occurred_at": utcnow(),
        "actor_id": ctx.actor_id,
        "actor_label": ctx.actor_label[:200],
        "action": action,
        "entity_type": entity_type,
        "entity_id": str(entity_id),
        "subject_id": subject_id,
        "before": b,
        "after": a,
        "payload_ciphertext": ciphertext,
    }
    entry = AuditEntry(
        **fields,
        ip=ctx.ip,
        user_agent=(ctx.user_agent or "")[:400] or None,
        request_id=ctx.request_id,
        prev_hash=prev_hash,
        hash=compute_hash(prev_hash, _hash_fields(fields)),
    )
    session.add(entry)
    await session.flush()


async def reveal(session: AsyncSession, entry: AuditEntry) -> tuple[Any, Any]:
    """Return (before, after) for display, decrypting personal data while its key exists."""
    if entry.payload_ciphertext is None or entry.subject_id is None:
        return entry.before, entry.after
    row = await session.get(SubjectKey, entry.subject_id)
    if row is None or row.wrapped_key is None:
        return (
            ERASED if entry.before is not None else None,
            ERASED if entry.after is not None else None,
        )
    key = crypto.unwrap_data_key(row.wrapped_key)
    data = json.loads(crypto.decrypt_with(key, entry.payload_ciphertext.encode()))
    return data["before"], data["after"]


async def shred_subject(session: AsyncSession, subject_id: uuid.UUID, by: uuid.UUID) -> bool:
    """Destroy the subject's data key. Their audit payloads become permanently unreadable."""
    row = await session.get(SubjectKey, subject_id)
    if row is None:
        session.add(
            SubjectKey(
                subject_id=subject_id, wrapped_key=None, shredded_at=utcnow(), shredded_by=by
            )
        )
        return False
    if row.wrapped_key is None:
        return False
    row.wrapped_key = None
    row.shredded_at = utcnow()
    row.shredded_by = by
    return True


@dataclass(frozen=True)
class ChainReport:
    ok: bool
    checked: int
    first_bad_id: int | None
    reason: str | None


async def verify_chain(session: AsyncSession, *, batch: int = 5000) -> ChainReport:
    prev_hash = GENESIS_HASH
    checked = 0
    last_id = 0
    while True:
        rows = (
            await session.scalars(
                select(AuditEntry)
                .where(AuditEntry.id > last_id)
                .order_by(AuditEntry.id)
                .limit(batch)
            )
        ).all()
        if not rows:
            return ChainReport(ok=True, checked=checked, first_bad_id=None, reason=None)
        for e in rows:
            if e.prev_hash != prev_hash:
                return ChainReport(False, checked, e.id, "prev_hash does not match previous entry")
            if compute_hash(prev_hash, _hash_fields(e)) != e.hash:
                return ChainReport(False, checked, e.id, "entry content does not match its hash")
            prev_hash = e.hash
            checked += 1
            last_id = e.id
