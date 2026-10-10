"""Operational helpers used by the CLI and the nightly job: database backup with retention, and
the operational gauges Prometheus alerts on (docs/runbooks/alerts.md)."""

from __future__ import annotations

import os
import subprocess  # nosec B404
import tempfile
from datetime import timedelta
from urllib.parse import urlparse

import structlog

from app.core.config import get_settings
from app.core.s3 import ensure_bucket, s3_client
from app.core.timeutil import utcnow

log = structlog.get_logger(__name__)
PREFIX = "pg_dump/"
LAST_BACKUP_KEY = "p1:ops:last_backup_ok"


def _pg_env(url: str) -> tuple[list[str], dict[str, str]]:
    u = urlparse(url.replace("+asyncpg", ""))
    args = [
        "-h",
        u.hostname or "localhost",
        "-p",
        str(u.port or 5432),
        "-U",
        u.username or "",
        "-d",
        (u.path or "/").lstrip("/"),
    ]
    env = {**os.environ, "PGPASSWORD": u.password or ""}
    return args, env


def run_backup() -> str:
    """pg_dump (custom format, gzip level via -Z) to the backups bucket, then prune old dumps.
    Returns the object key. Raises when pg_dump fails so the failure is visible in the worker."""
    s = get_settings()
    args, env = _pg_env(s.database_owner_url)
    key = f"{PREFIX}{utcnow():%Y/%m/%d/%H%M%S}.dump"
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "db.dump")
        subprocess.run(  # nosec B603 B607  # noqa: S603
            ["pg_dump", *args, "-Fc", "-Z", "6", "--no-owner", "-f", out],  # noqa: S607
            check=True,
            env=env,
            timeout=1800,
        )
        ensure_bucket(s.s3_bucket_backups)
        with open(out, "rb") as fh:
            s3_client().put_object(Bucket=s.s3_bucket_backups, Key=key, Body=fh)
    log.info("backup_done", key=key)
    prune_backups()
    _mark_backup()
    return key


def _mark_backup() -> None:
    """Remember when the last backup succeeded; Prometheus alerts when it is over a day old."""
    import redis as redis_sync

    try:
        r = redis_sync.Redis.from_url(get_settings().redis_url, socket_timeout=5)
        r.set(LAST_BACKUP_KEY, str(int(utcnow().timestamp())))
    except redis_sync.RedisError as exc:  # the backup itself worked; only the gauge is stale
        log.warning("backup_mark_failed", error=str(exc))


async def ops_metrics() -> str:
    """Gauges for the alert rules: outbox backlog and dead messages (failed jobs), the Celery
    queue, failed notifications in the last day, and the time of the last good backup."""
    from sqlalchemy import text

    from app.core.db import get_engine
    from app.core.redis import get_redis

    lines: list[str] = []

    def gauge(name: str, value: float, help_: str) -> None:
        lines.extend([f"# HELP {name} {help_}", f"# TYPE {name} gauge", f"{name} {value}"])

    async with get_engine().connect() as conn:
        rows: dict[str, int] = dict(
            (
                await conn.execute(
                    text("SELECT status, count(*) FROM outbox_messages GROUP BY status")
                )
            ).all()
        )
        failed = await conn.scalar(
            text(
                "SELECT count(*) FROM notifications WHERE status = 'failed' "
                "AND created_at > now() - interval '1 day'"
            )
        )
    gauge("p1_outbox_pending", float(rows.get("pending", 0)), "Outbox messages waiting")
    gauge("p1_outbox_dead", float(rows.get("dead", 0)), "Outbox messages given up after retries")
    gauge("p1_notifications_failed_1d", float(failed or 0), "Messages that failed in a day")
    try:
        import redis.asyncio as aioredis

        broker = aioredis.from_url(  # type: ignore[no-untyped-call]
            get_settings().celery_broker_url, socket_timeout=3
        )
        try:
            depth = await broker.llen("celery")
        finally:
            await broker.aclose()
        gauge("p1_celery_queue_length", float(depth), "Tasks waiting for a Celery worker")
        last = await get_redis().get(LAST_BACKUP_KEY)
        if last:
            gauge(
                "p1_backup_last_success_timestamp_seconds",
                float(last),
                "Unix time of the last good database backup",
            )
    except Exception as exc:
        log.warning("ops_metrics_redis", error=str(exc)[:200])
    return "\n".join(lines) + "\n"


def export_backups(out: str) -> int:
    """Copy backups that are not in `out` yet (by name and size) into that folder, keeping the
    bucket's year/month/day layout. For a daily copy off the server; returns how many were new.
    Each file is written under a temporary name and renamed when complete, so an interrupted
    copy never leaves a half file that looks finished."""
    s = get_settings()
    client = s3_client()
    copied = 0
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=s.s3_bucket_backups, Prefix=PREFIX):
        for obj in page.get("Contents", []):
            dest = os.path.join(out, *obj["Key"].split("/"))
            if os.path.exists(dest) and os.path.getsize(dest) == obj["Size"]:
                continue
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            part = dest + ".part"
            client.download_file(s.s3_bucket_backups, obj["Key"], part)
            os.replace(part, dest)
            copied += 1
    log.info("backups_exported", copied=copied, out=out)
    return copied


def prune_backups() -> int:
    s = get_settings()
    cutoff = utcnow() - timedelta(days=s.backup_retention_days)
    client = s3_client()
    removed = 0
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=s.s3_bucket_backups, Prefix=PREFIX):
        for obj in page.get("Contents", []):
            if obj["LastModified"] < cutoff:
                client.delete_object(Bucket=s.s3_bucket_backups, Key=obj["Key"])
                removed += 1
    return removed
