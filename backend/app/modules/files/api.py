from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status
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


routers = [router]
