from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import PayloadTooLarge
from app.core.ratelimit import Limit, check
from app.core.timeutil import utcnow
from app.modules.files import service
from app.modules.identity.contracts import P, Principal, require

router = APIRouter(prefix="/files", tags=["files"])
public_router = APIRouter(prefix="/public/files", tags=["public"])
Session = Annotated[AsyncSession, Depends(get_session)]


class FileOut(BaseModel):
    id: uuid.UUID
    purpose: str
    original_name: str
    kind: str
    content_type: str
    size_bytes: int
    sha256: str
    exif_stripped: bool
    meta: dict[str, Any]
    project_id: uuid.UUID | None
    uploaded_by: uuid.UUID
    created_at: datetime


class DownloadOut(BaseModel):
    url: str
    expires_at: datetime


async def read_limited(upload: UploadFile, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while chunk := await upload.read(1024 * 1024):
        total += len(chunk)
        if total > limit:
            raise PayloadTooLarge(f"The limit is {limit // (1024 * 1024)} MB.")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post(
    "", response_model=FileOut, status_code=status.HTTP_201_CREATED, summary="Upload a file"
)
async def upload(
    request: Request,
    session: Session,
    principal: Annotated[Principal, Depends(require(P.FILE_UPLOAD))],
    file: Annotated[UploadFile, File()],
    purpose: Annotated[str, Form(max_length=40)],
    project_id: Annotated[uuid.UUID | None, Form()] = None,
) -> FileOut:
    await check(
        f"user:{principal.user_id}",
        Limit("upload", get_settings().rate_limit_upload_per_minute, strict=True),
    )
    data = await read_limited(file, get_settings().max_upload_bytes)
    f = await service.ingest(
        session,
        principal,
        data=data,
        filename=file.filename or "upload",
        purpose_code=purpose,
        project_id=project_id,
        client_ip=request.state.client_ip,
    )
    return FileOut.model_validate(f, from_attributes=True)


@router.get("/{file_id}", response_model=FileOut)
async def get_file(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.FILE_READ))],
    file_id: uuid.UUID,
) -> FileOut:
    return FileOut.model_validate(
        await service.get_visible(session, principal, file_id), from_attributes=True
    )


@router.get("/{file_id}/download", response_model=DownloadOut, summary="Short-lived download link")
async def download(
    session: Session,
    principal: Annotated[Principal, Depends(require(P.FILE_READ))],
    file_id: uuid.UUID,
) -> DownloadOut:
    from datetime import timedelta

    f = await service.get_visible(session, principal, file_id)
    ttl = get_settings().s3_presign_ttl_seconds
    return DownloadOut(url=service.download_url(f), expires_at=utcnow() + timedelta(seconds=ttl))


@public_router.get("/{file_id}", summary="Open a file through a signed download link")
async def open_signed(
    session: Session,
    file_id: uuid.UUID,
    expires: Annotated[int, Query()],
    sig: Annotated[str, Query(max_length=128)],
) -> StreamingResponse:
    """The link from `/files/{id}/download` when storage is not public. The signature stands in
    for sign-in (an image tag cannot send a token); it names one file and ends in minutes."""
    from app.core.errors import NotFound

    if not service.link_is_valid(file_id, expires, sig):
        raise NotFound("This download link has ended or is not valid. Open the file again.")
    f = await service.get_stored(session, file_id)
    body = await service.open_body(f)
    return StreamingResponse(
        body.iter_chunks(64 * 1024),
        media_type=f.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{f.original_name}"',
            "Cache-Control": "private, max-age=300",
            "X-Content-Type-Options": "nosniff",
        },
    )


routers = [router, public_router]
