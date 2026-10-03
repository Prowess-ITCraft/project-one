"""Public surface of the files module. Other modules import only from here."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.files import service as _service
from app.modules.files.models import StoredFile
from app.modules.identity.contracts import Principal


@dataclass(frozen=True)
class FileRef:
    id: uuid.UUID
    purpose: str
    kind: str
    original_name: str
    size_bytes: int
    sha256: str
    project_id: uuid.UUID | None
    uploaded_by: uuid.UUID


def _ref(f: StoredFile) -> FileRef:
    return FileRef(
        f.id,
        f.purpose,
        f.kind,
        f.original_name,
        f.size_bytes,
        f.sha256,
        f.project_id,
        f.uploaded_by,
    )


async def store_upload(
    session: AsyncSession,
    principal: Principal,
    *,
    data: bytes,
    filename: str,
    purpose: str,
    project_id: uuid.UUID | None,
    client_ip: str | None = None,
) -> FileRef:
    """Run the full upload pipeline (sniff, scan, store). Commits."""
    f = await _service.ingest(
        session,
        principal,
        data=data,
        filename=filename,
        purpose_code=purpose,
        project_id=project_id,
        client_ip=client_ip,
    )
    return _ref(f)


async def get_file(session: AsyncSession, principal: Principal, file_id: uuid.UUID) -> FileRef:
    return _ref(await _service.get_visible(session, principal, file_id))


async def read_file(
    session: AsyncSession, principal: Principal, file_id: uuid.UUID
) -> tuple[FileRef, bytes]:
    f, data = await _service.read_bytes(session, principal, file_id)
    return _ref(f), data


async def read_file_system(session: AsyncSession, file_id: uuid.UUID) -> tuple[FileRef, bytes]:
    """For background workers acting on an already-authorised job. Never call from a router."""
    f = await session.get(StoredFile, file_id)
    if f is None or f.deleted_at is not None:
        from app.core.errors import NotFound

        raise NotFound("File not found.")
    return _ref(f), await _service.read_object(f)


async def purge_library_original(session: AsyncSession, file_id: uuid.UUID, reason: str) -> bool:
    """Remove a library original's bytes under the corpus retention rule (ADR 0014). System use
    only. Returns False when the file is already gone. The caller commits."""
    f = await session.get(StoredFile, file_id)
    if f is None or f.deleted_at is not None:
        return False
    await _service.purge_object(f, reason)
    return True


async def read_limited(upload: "UploadFile", limit: int) -> bytes:  # noqa: UP037
    """Read an uploaded file in chunks, refusing anything over `limit` bytes."""
    from app.modules.files.api import read_limited as _read

    return await _read(upload, limit)


__all__ = [
    "FileRef",
    "get_file",
    "purge_library_original",
    "read_file",
    "read_file_system",
    "read_limited",
    "store_upload",
]
