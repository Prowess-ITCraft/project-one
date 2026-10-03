"""Celery app: runs the outbox dispatcher and scheduled jobs.

Start with:
    celery -A app.worker worker -l info        # executes tasks
    celery -A app.worker beat -l info          # schedules them
Every task is idempotent and safe to run twice.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings
from app.core.logging import configure_logging

configure_logging()
log = structlog.get_logger(__name__)
_s = get_settings()

celery_app = Celery("project_one", broker=_s.celery_broker_url, backend=None)


def _load_modules() -> None:
    """Every task may publish events (the inbox scan does), so subscribers load with the worker."""
    from app.modules import registry

    registry.load_models()
    registry.load_handlers()


_load_modules()
celery_app.conf.update(
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_time_limit=300,
    task_soft_time_limit=240,
    broker_connection_retry_on_startup=True,
    task_ignore_result=True,
    beat_schedule={
        "outbox-dispatch": {"task": "p1.outbox.dispatch", "schedule": 5.0},
        # 00:10 IST is 18:40 UTC the previous day.
        "price-expiry": {
            "task": "p1.catalogue.expire_prices",
            "schedule": crontab(hour=18, minute=40),
        },
        "nightly-backup": {"task": "p1.ops.backup", "schedule": crontab(hour=21, minute=0)},
        "notifications-retry": {"task": "p1.notifications.send_pending", "schedule": 60.0},
        "library-inbox": {"task": "p1.library.scan_inbox", "schedule": 300.0},
        # 01:30 IST is 20:00 UTC. Does nothing while the retention setting is 0 (ADR 0014).
        "corpus-retention": {
            "task": "p1.corpus.purge_originals",
            "schedule": crontab(hour=20, minute=0),
        },
    },
)


def _run(coro: Any) -> Any:
    """Each task gets a fresh event loop, so the engine is rebuilt per run (no cross-loop reuse)."""
    from app.core import db, redis

    async def wrapped() -> Any:
        try:
            return await coro
        finally:
            await redis.close_redis()
            await db.dispose_engine()

    return asyncio.run(wrapped())


@celery_app.task(name="p1.outbox.dispatch")  # type: ignore[untyped-decorator]
def dispatch_outbox() -> int:
    from app.core import outbox
    from app.core.db import get_sessionmaker
    from app.modules import registry

    registry.load_handlers()
    total = 0

    async def drain() -> int:
        nonlocal total
        while True:
            n = await outbox.dispatch_batch(get_sessionmaker(), limit=50)
            total += n
            if n < 50:
                return total

    return int(_run(drain()))


@celery_app.task(name="p1.catalogue.expire_prices")  # type: ignore[untyped-decorator]
def expire_prices() -> int:
    from app.core.db import get_sessionmaker
    from app.modules.catalogue import service

    n = int(_run(service.expire_prices(get_sessionmaker())))
    log.info("prices_expired", count=n)
    return n


@celery_app.task(name="p1.ops.backup")  # type: ignore[untyped-decorator]
def backup() -> str:
    from app import ops

    return str(ops.run_backup())


@celery_app.task(name="p1.notifications.send_pending")  # type: ignore[untyped-decorator]
def send_notifications() -> int:
    from app.core.db import get_sessionmaker
    from app.modules.notifications.contracts import send_pending

    return int(_run(send_pending(get_sessionmaker())))


@celery_app.task(name="p1.library.scan_inbox")  # type: ignore[untyped-decorator]
def scan_inbox() -> dict[str, int]:
    from pathlib import Path

    from app.core.config import get_settings
    from app.core.db import get_sessionmaker
    from app.modules.datasets.contracts import scan_library_folder

    folder = get_settings().library_inbox_dir
    if not folder:
        return {}
    counts = dict(_run(scan_library_folder(get_sessionmaker(), Path(folder))))
    log.info("library_inbox_scanned", **counts)
    return counts


@celery_app.task(name="p1.corpus.purge_originals")  # type: ignore[untyped-decorator]
def purge_corpus_originals() -> int:
    from app.core.db import get_sessionmaker
    from app.modules.datasets.contracts import purge_corpus_originals

    async def go() -> int:
        async with get_sessionmaker()() as s:
            return await purge_corpus_originals(s)

    return int(_run(go()))
