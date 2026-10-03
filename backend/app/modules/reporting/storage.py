"""Locked report and certificate PDFs in the files bucket. Keys are never reused."""

from __future__ import annotations

import asyncio

from botocore.exceptions import BotoCoreError

from app.core.config import get_settings
from app.core.resilience import CircuitBreaker, call_with_retry
from app.core.s3 import s3_client

_breaker = CircuitBreaker("Report storage", threshold=5, reset_after=20)
_ERRORS = (OSError, TimeoutError, BotoCoreError)


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
