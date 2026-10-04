"""Issued quotation PDFs in the files bucket under `boq/`. One object per issued version; the
row that points at it cannot change, so the PDF the customer got is the PDF we keep."""

from __future__ import annotations

import asyncio
import uuid

from botocore.exceptions import BotoCoreError

from app.core.config import get_settings
from app.core.resilience import CircuitBreaker, call_with_retry
from app.core.s3 import s3_client

_breaker = CircuitBreaker("BOQ storage", threshold=5, reset_after=20)
_ERRORS = (OSError, TimeoutError, BotoCoreError)


def key_for(boq_id: uuid.UUID, number: int) -> str:
    return f"boq/{boq_id.hex}/v{number}-quotation.pdf"


async def put_pdf(key: str, pdf: bytes) -> None:
    bucket = get_settings().s3_bucket_files

    def work() -> None:
        s3_client().put_object(Bucket=bucket, Key=key, Body=pdf, ContentType="application/pdf")

    await call_with_retry(
        lambda: asyncio.to_thread(work), breaker=_breaker, timeout=60, retry_on=_ERRORS
    )


async def get_pdf(key: str) -> bytes:
    bucket = get_settings().s3_bucket_files

    def work() -> bytes:
        return bytes(s3_client().get_object(Bucket=bucket, Key=key)["Body"].read())

    return await call_with_retry(
        lambda: asyncio.to_thread(work), breaker=_breaker, timeout=60, retry_on=_ERRORS
    )
