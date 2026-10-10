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
    # A task held by a worker that died goes back on the queue after this long. The default is
    # an hour; 10 minutes is still longer than any task may run (task_time_limit), so a task
    # that is only slow is never handed out twice.
    broker_transport_options={"visibility_timeout": 600},
    task_ignore_result=True,
    # Our structured logs go to stdout with their own level inside the JSON. Celery would
    # otherwise relabel every line WARNING, which makes routine scans look like warnings.
    worker_redirect_stdouts_level="INFO",
    beat_schedule={
        "outbox-dispatch": {"task": "p1.outbox.dispatch", "schedule": 5.0},
        # 00:10 IST is 18:40 UTC the previous day.
        "price-expiry": {
            "task": "p1.catalogue.expire_prices",
            "schedule": crontab(hour=18, minute=40),
        },
        "nightly-backup": {"task": "p1.ops.backup", "schedule": crontab(hour=21, minute=0)},
        "notifications-retry": {"task": "p1.notifications.send_pending", "schedule": 60.0},
        # 02:00 IST is 20:30 UTC. Repairs anything an event missed.
        "search-reindex": {
            "task": "p1.search.reindex",
            "schedule": crontab(hour=20, minute=30),
        },
        # 09:00 IST is 03:30 UTC: the day before a quote's prices lapse, on the day, and after.
        "quote-expiry": {
            "task": "p1.boq.quote_expiry_alerts",
            "schedule": crontab(hour=3, minute=30),
        },
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


@celery_app.task(name="p1.boq.quote_expiry_alerts")  # type: ignore[untyped-decorator]
def quote_expiry_alerts() -> int:
    from app.core.db import get_sessionmaker
    from app.modules.boq import service

    n = int(_run(service.quote_expiry_alerts(get_sessionmaker())))
    log.info("quote_expiry_alerts", count=n)
    return n


@celery_app.task(name="p1.search.reindex")  # type: ignore[untyped-decorator]
def search_reindex() -> dict[str, int]:
    from app.core.db import get_sessionmaker
    from app.modules.search import service

    async def go() -> dict[str, int]:
        async with get_sessionmaker()() as s:
            return await service.reindex(s)

    counts: dict[str, int] = _run(go())
    log.info("search_reindexed", **counts)
    return counts


PROBE_KEY = "p1:ops:probe:"
PROBE_MAX_SECONDS = 120


@celery_app.task(name="p1.ops.probe")  # type: ignore[untyped-decorator]
def probe(token: str, seconds: float = 0) -> str:
    """A harmless task for checks: waits, then records that it ran. `scripts/chaos.py` kills the
    worker during the wait to prove the task is handed out again and finishes."""
    import time

    import redis

    time.sleep(max(0.0, min(float(seconds), PROBE_MAX_SECONDS)))
    r = redis.from_url(get_settings().redis_url)  # type: ignore[no-untyped-call]
    try:
        r.set(PROBE_KEY + token[:64], str(int(time.time())), ex=3600)
    finally:
        r.close()
    return token


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
