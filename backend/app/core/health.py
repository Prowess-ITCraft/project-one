"""Liveness (/healthz), readiness (/readyz: DB, Redis, MinIO) and Prometheus metrics (/metrics)."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import get_engine
from app.core.redis import get_redis
from app.core.s3 import s3_client

router = APIRouter(include_in_schema=False)

CHECK_TIMEOUT = 3.0


async def _check_db() -> None:
    async with get_engine().connect() as conn:
        await conn.execute(text("SELECT 1"))


async def _check_redis() -> None:
    await get_redis().ping()


async def _check_s3() -> None:
    bucket = get_settings().s3_bucket_files
    await asyncio.to_thread(s3_client().head_bucket, Bucket=bucket)


async def _timed(name: str, fn: Any) -> tuple[str, dict[str, Any]]:
    start = time.perf_counter()
    try:
        await asyncio.wait_for(fn(), timeout=CHECK_TIMEOUT)
        return name, {"ok": True, "ms": round((time.perf_counter() - start) * 1000, 1)}
    except Exception as exc:
        # Report the failure type only; connection strings and hosts stay out of responses.
        return name, {"ok": False, "error": type(exc).__name__}


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz() -> JSONResponse:
    results = dict(
        await asyncio.gather(
            _timed("database", _check_db),
            _timed("redis", _check_redis),
            _timed("object_storage", _check_s3),
        )
    )
    ready = all(r["ok"] for r in results.values())
    return JSONResponse(
        {"status": "ready" if ready else "not_ready", "checks": results},
        status_code=200 if ready else 503,
    )


@router.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
