"""Parquet files for dataset versions, kept in the files bucket under `datasets/`. Versions are
immutable objects; nothing here ever overwrites a key."""

from __future__ import annotations

import asyncio
import hashlib
import uuid

import pyarrow as pa
from botocore.exceptions import BotoCoreError

from app.core.config import get_settings
from app.core.resilience import CircuitBreaker, call_with_retry
from app.core.s3 import s3_client
from app.modules.datasets.engine import frame

_breaker = CircuitBreaker("Dataset storage", threshold=5, reset_after=20)
_ERRORS = (OSError, TimeoutError, BotoCoreError)


def key_for(dataset_id: uuid.UUID, number: int) -> str:
    return f"datasets/{dataset_id.hex}/v{number}.parquet"


async def put_table(dataset_id: uuid.UUID, number: int, table: pa.Table) -> tuple[str, str, int]:
    """Returns (object key, sha256, size in bytes)."""
    data = frame.to_parquet(table)
    key = key_for(dataset_id, number)
    bucket = get_settings().s3_bucket_files
    digest = hashlib.sha256(data).hexdigest()

    def work() -> None:
        s3_client().put_object(
            Bucket=bucket, Key=key, Body=data, ContentType="application/vnd.apache.parquet"
        )

    await call_with_retry(
        lambda: asyncio.to_thread(work), breaker=_breaker, timeout=120, retry_on=_ERRORS
    )
    return key, digest, len(data)


async def get_table(key: str) -> pa.Table:
    bucket = get_settings().s3_bucket_files

    def work() -> bytes:
        body = s3_client().get_object(Bucket=bucket, Key=key)["Body"]
        return bytes(body.read())

    data = await call_with_retry(
        lambda: asyncio.to_thread(work), breaker=_breaker, timeout=120, retry_on=_ERRORS
    )
    return frame.from_parquet(data)
