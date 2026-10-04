"""Upload pipeline: size cap -> type sniff -> virus scan -> EXIF policy -> object storage."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import io
import re
import unicodedata
import uuid
from dataclasses import dataclass
from typing import Any

import structlog
from botocore.exceptions import BotoCoreError
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import (
    AppError,
    Forbidden,
    NotFound,
    PayloadTooLarge,
    ServiceUnavailable,
    UnsupportedMedia,
    ValidationFailed,
)
from app.core.resilience import CircuitBreaker, call_with_retry
from app.core.s3 import s3_client, s3_presign_client
from app.core.timeutil import utcnow
from app.modules.audit_log.contracts import record
from app.modules.customers.contracts import get_project_ref
from app.modules.files import sniff
from app.modules.files.models import RejectedUpload, StoredFile
from app.modules.files.scanner import get_scanner
from app.modules.identity.contracts import P, Principal, audit_context

log = structlog.get_logger(__name__)
_storage_breaker = CircuitBreaker("Object storage", threshold=5, reset_after=20)
_STORAGE_ERRORS = (OSError, TimeoutError, BotoCoreError)

MB = 1024 * 1024


@dataclass(frozen=True)
class Purpose:
    code: str
    allowed: frozenset[str]
    max_bytes: int
    keep_exif: bool = False
    needs_project: bool = False


PURPOSES: dict[str, Purpose] = {
    p.code: p
    for p in (
        Purpose("audit_report", frozenset({"docx", "json"}), 25 * MB, needs_project=True),
        Purpose("boq_import", frozenset({"pdf", "xlsx"}), 20 * MB),
        Purpose(
            "library",
            frozenset({"pdf", "xlsx", "docx", "json", "csv"}),
            25 * MB,
        ),
        Purpose("dataset_import", frozenset({"csv", "xlsx", "parquet", "json"}), 50 * MB),
        Purpose(
            "evidence_photo",
            frozenset({"jpeg", "png", "webp"}),
            15 * MB,
            keep_exif=True,
            needs_project=True,
        ),
        Purpose("config_export", frozenset({"text", "json", "zip"}), 10 * MB, needs_project=True),
        Purpose("document", frozenset({"pdf", "docx", "xlsx", "png", "jpeg"}), 20 * MB),
    )
}


class InfectedFile(AppError):
    status, code, title = 422, "file_infected", "The file was rejected by the virus scanner"


def safe_filename(name: str) -> str:
    name = unicodedata.normalize("NFKC", name).replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"[^\w.\- ()&,]+", "_", name).strip(" .")
    return (name or "file")[:200]


def _strip_exif(data: bytes, kind: sniff.FileKind) -> bytes:
    """Re-encode the image without metadata. Pixel data is kept; EXIF (incl. GPS) is dropped."""
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            clean = Image.new(img.mode, img.size)
            if img.mode == "P" and (palette := img.getpalette()) is not None:
                clean.putpalette(palette)
            clean.paste(img)  # pixels only: the new image carries no metadata
            out = io.BytesIO()
            fmt = {"jpeg": "JPEG", "png": "PNG", "webp": "WEBP"}[kind.code]
            clean.save(out, format=fmt, quality=92 if fmt != "PNG" else None)
            return out.getvalue()
    except (UnidentifiedImageError, OSError) as exc:
        raise UnsupportedMedia("The image could not be read.") from exc


def _exif_meta(data: bytes) -> dict[str, Any]:
    """For evidence photos: keep capture time and GPS so field visits can be verified."""
    try:
        with Image.open(io.BytesIO(data)) as img:
            exif = img.getexif()
            meta: dict[str, Any] = {}
            if dt := exif.get(0x0132):
                meta["taken_at"] = str(dt)
            gps = exif.get_ifd(0x8825)
            if gps:
                meta["gps"] = {str(k): str(v) for k, v in gps.items()}
            return meta
    except (UnidentifiedImageError, OSError):
        return {}


async def _put(bucket: str, key: str, data: bytes, content_type: str, sha256: str) -> str | None:
    def work() -> str | None:
        r = s3_client().put_object(
            Bucket=bucket, Key=key, Body=data, ContentType=content_type, Metadata={"sha256": sha256}
        )
        return r.get("VersionId")

    return await call_with_retry(
        lambda: asyncio.to_thread(work),
        breaker=_storage_breaker,
        timeout=60,
        retry_on=_STORAGE_ERRORS,
    )


async def ingest(
    session: AsyncSession,
    principal: Principal,
    *,
    data: bytes,
    filename: str,
    purpose_code: str,
    project_id: uuid.UUID | None,
    client_ip: str | None = None,
) -> StoredFile:
    purpose = PURPOSES.get(purpose_code)
    if purpose is None:
        raise ValidationFailed(
            f"Unknown upload purpose. Use one of: {', '.join(sorted(PURPOSES))}."
        )
    if purpose.needs_project and project_id is None:
        raise ValidationFailed(
            "This kind of file must belong to a project.", code="project_required"
        )
    if project_id is not None:
        await get_project_ref(session, principal, project_id)  # object-level check
    if len(data) > purpose.max_bytes:
        raise PayloadTooLarge(
            f"The limit for {purpose.code} files is {purpose.max_bytes // MB} MB."
        )
    name = safe_filename(filename)
    try:
        kind = sniff.check(data, name, purpose.allowed)
    except sniff.SniffError as exc:
        raise UnsupportedMedia(str(exc)) from exc

    digest = hashlib.sha256(data).hexdigest()
    try:
        result = await get_scanner().scan(data)
    except (OSError, TimeoutError) as exc:  # fail closed: no scan, no upload
        log.error("scanner_unavailable", error=str(exc))
        raise ServiceUnavailable(
            "The virus scanner is not reachable, so nothing was uploaded. Try again shortly."
        ) from exc
    if not result.clean:
        session.add(
            RejectedUpload(
                purpose=purpose.code,
                original_name=name,
                sha256=digest,
                size_bytes=len(data),
                reason=f"{result.engine}: {result.signature}",
                uploaded_by=principal.user_id,
                ip=client_ip,
            )
        )
        await record(
            session,
            audit_context(principal),
            action="upload_rejected_malware",
            entity_type="file",
            entity_id=digest[:32],
            after={"name": name, "signature": result.signature},
            only_changes=False,
        )
        await session.commit()
        log.warning("upload_infected", sha256=digest, signature=result.signature)
        raise InfectedFile(
            f"The virus scanner flagged this file ({result.signature}). It was not stored."
        )

    meta: dict[str, Any] = {}
    stripped = False
    if kind.code in ("jpeg", "png", "webp"):
        if purpose.keep_exif:
            meta = _exif_meta(data)
        else:
            data = _strip_exif(data, kind)
            stripped = True
            digest = hashlib.sha256(data).hexdigest()

    now = utcnow()
    file_id = uuid.uuid4()
    key = f"{purpose.code}/{now:%Y/%m}/{file_id.hex}"
    bucket = get_settings().s3_bucket_files
    version = await _put(bucket, key, data, kind.mime, digest)
    f = StoredFile(
        id=file_id,
        purpose=purpose.code,
        original_name=name,
        kind=kind.code,
        content_type=kind.mime,
        size_bytes=len(data),
        sha256=digest,
        bucket=bucket,
        object_key=key,
        object_version=version,
        scan_engine=result.engine,
        exif_stripped=stripped,
        meta=meta,
        project_id=project_id,
        uploaded_by=principal.user_id,
    )
    session.add(f)
    await session.flush()
    await record(
        session,
        audit_context(principal),
        action="upload",
        entity_type="file",
        entity_id=f.id,
        after={
            "name": name,
            "purpose": purpose.code,
            "sha256": digest,
            "size": len(data),
            "project_id": str(project_id) if project_id else None,
        },
    )
    await session.commit()
    return f


async def get_stored(session: AsyncSession, file_id: uuid.UUID) -> StoredFile:
    """A file that is still kept, with no visibility check (callers have already proved access,
    for example with a signed link)."""
    f = await session.scalar(
        select(StoredFile).where(StoredFile.id == file_id, StoredFile.deleted_at.is_(None))
    )
    if f is None:
        raise NotFound("File not found.")
    return f


async def open_body(f: StoredFile) -> Any:
    """The stored object as a stream, for the API to pass on without holding it in memory."""
    kwargs: dict[str, Any] = {"Bucket": f.bucket, "Key": f.object_key}
    if f.object_version and f.object_version != "null":
        kwargs["VersionId"] = f.object_version
    return await call_with_retry(
        lambda: asyncio.to_thread(lambda: s3_client().get_object(**kwargs)["Body"]),
        breaker=_storage_breaker,
        timeout=30,
        retry_on=_STORAGE_ERRORS,
    )


async def get_visible(
    session: AsyncSession, principal: Principal, file_id: uuid.UUID
) -> StoredFile:
    f = await session.scalar(
        select(StoredFile).where(StoredFile.id == file_id, StoredFile.deleted_at.is_(None))
    )
    if f is None:
        raise NotFound("File not found.")
    if f.uploaded_by == principal.user_id:
        return f
    if f.project_id is not None:
        try:
            await get_project_ref(session, principal, f.project_id)
            return f
        except NotFound:
            pass
    elif principal.has(P.PROJECT_READ_ALL):
        return f
    raise NotFound("File not found.")


async def read_bytes(
    session: AsyncSession, principal: Principal, file_id: uuid.UUID
) -> tuple[StoredFile, bytes]:
    f = await get_visible(session, principal, file_id)
    return f, await read_object(f)


async def read_object(f: StoredFile) -> bytes:
    def work() -> bytes:
        kwargs: dict[str, Any] = {"Bucket": f.bucket, "Key": f.object_key}
        if f.object_version and f.object_version != "null":
            kwargs["VersionId"] = f.object_version
        body = s3_client().get_object(**kwargs)["Body"]
        return bytes(body.read())

    data = await call_with_retry(
        lambda: asyncio.to_thread(work),
        breaker=_storage_breaker,
        timeout=60,
        retry_on=_STORAGE_ERRORS,
    )
    if hashlib.sha256(data).hexdigest() != f.sha256:
        log.error("file_integrity_mismatch", file_id=str(f.id))
        raise Forbidden("The stored file failed its integrity check.", code="file_integrity")
    return data


async def purge_object(f: StoredFile, reason: str) -> None:
    """Remove the stored bytes of a library original for good (ADR 0014 retention). The row stays,
    soft deleted, with its hash and the reason, so the record of what existed is kept."""
    if f.purpose != "library":
        raise Forbidden("Only library originals can be purged.", code="purge_not_allowed")

    def work() -> None:
        kwargs: dict[str, Any] = {"Bucket": f.bucket, "Key": f.object_key}
        if f.object_version and f.object_version != "null":
            kwargs["VersionId"] = f.object_version
        s3_client().delete_object(**kwargs)

    await call_with_retry(
        lambda: asyncio.to_thread(work),
        breaker=_storage_breaker,
        timeout=60,
        retry_on=_STORAGE_ERRORS,
    )
    f.deleted_at = utcnow()
    f.meta = {**(f.meta or {}), "purged": True, "purge_reason": reason[:200]}


def _link_signature(file_id: uuid.UUID, expires: int, key: str) -> str:
    msg = f"file-download:{file_id}:{expires}".encode()
    return hmac.new(key.encode(), msg, hashlib.sha256).hexdigest()


def link_is_valid(file_id: uuid.UUID, expires: int, sig: str) -> bool:
    """A download link the API signed itself: not expired, and signed with a current or older
    signing key (so rotating keys does not break links already handed out)."""
    if expires < int(utcnow().timestamp()):
        return False
    keys = get_settings().jwt_keys()
    return any(hmac.compare_digest(_link_signature(file_id, expires, k), sig) for k in keys)


def download_url(f: StoredFile) -> str:
    s = get_settings()
    if not s.s3_public_endpoint_url:
        # Storage is not reachable from browsers (production: MinIO stays on the internal
        # network). The API serves the file itself, through a short-lived signed link on the
        # same address as the app, so no second domain or certificate is needed.
        expires = int(utcnow().timestamp()) + s.s3_presign_ttl_seconds
        sig = _link_signature(f.id, expires, s.jwt_keys()[0])
        return f"{s.api_prefix}/public/files/{f.id}?expires={expires}&sig={sig}"
    params: dict[str, Any] = {
        "Bucket": f.bucket,
        "Key": f.object_key,
        "ResponseContentType": f.content_type,
        "ResponseContentDisposition": f'attachment; filename="{f.original_name}"',
    }
    if f.object_version and f.object_version != "null":
        params["VersionId"] = f.object_version
    return str(
        s3_presign_client().generate_presigned_url(
            "get_object", Params=params, ExpiresIn=s.s3_presign_ttl_seconds
        )
    )
