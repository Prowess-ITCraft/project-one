"""Gzipped corpus records in the files bucket under `corpus/`. A key is the source file's hash
plus the cleaning version, so a rebuild with new cleaning never overwrites an older record."""

from __future__ import annotations

import asyncio

from botocore.exceptions import BotoCoreError

from app.core.config import get_settings
from app.core.resilience import CircuitBreaker, call_with_retry
from app.core.s3 import s3_client

_breaker = CircuitBreaker("Corpus storage", threshold=5, reset_after=20)
_ERRORS = (OSError, TimeoutError, BotoCoreError)


def key_for(sha256: str, cleaning_version: str) -> str:
    return f"corpus/{sha256[:2]}/{sha256}.c{cleaning_version}.json.gz"


async def put_record(key: str, gz: bytes) -> None:
    bucket = get_settings().s3_bucket_files

    def work() -> None:
        s3_client().put_object(
            Bucket=bucket,
            Key=key,
            Body=gz,
            ContentType="application/json",
            ContentEncoding="gzip",
        )

    await call_with_retry(
        lambda: asyncio.to_thread(work), breaker=_breaker, timeout=60, retry_on=_ERRORS
    )


async def get_record(key: str) -> bytes:
    bucket = get_settings().s3_bucket_files

    def work() -> bytes:
        return bytes(s3_client().get_object(Bucket=bucket, Key=key)["Body"].read())

    return await call_with_retry(
        lambda: asyncio.to_thread(work), breaker=_breaker, timeout=60, retry_on=_ERRORS
    )
