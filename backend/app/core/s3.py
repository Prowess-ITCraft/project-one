"""S3 (MinIO) client factory. boto3 is sync, so callers run it in a thread."""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

import boto3
from botocore.config import Config

from app.core.config import get_settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


def _config() -> Config:
    return Config(
        signature_version="s3v4",
        connect_timeout=3,
        read_timeout=30,
        retries={"max_attempts": 4, "mode": "standard"},
        s3={"addressing_style": "path"},
    )


@lru_cache
def s3_client() -> S3Client:
    s = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=s.s3_endpoint_url,
        aws_access_key_id=s.s3_access_key.get_secret_value(),
        aws_secret_access_key=s.s3_secret_key.get_secret_value(),
        region_name=s.s3_region,
        config=_config(),
    )


@lru_cache
def s3_presign_client() -> S3Client:
    """Signs URLs against the public endpoint so browsers can reach them."""
    s = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=s.s3_public_endpoint_url or s.s3_endpoint_url,
        aws_access_key_id=s.s3_access_key.get_secret_value(),
        aws_secret_access_key=s.s3_secret_key.get_secret_value(),
        region_name=s.s3_region,
        config=_config(),
    )


def ensure_bucket(name: str, *, versioning: bool = True) -> None:
    client = s3_client()
    existing = {b["Name"] for b in client.list_buckets().get("Buckets", [])}
    if name not in existing:
        client.create_bucket(Bucket=name)
    if versioning:
        client.put_bucket_versioning(Bucket=name, VersioningConfiguration={"Status": "Enabled"})


def reset_clients() -> None:
    s3_client.cache_clear()
    s3_presign_client.cache_clear()
