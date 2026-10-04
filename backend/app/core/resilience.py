"""Retries with exponential backoff and a simple circuit breaker for external calls."""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import structlog

from app.core.errors import ServiceUnavailable

log = structlog.get_logger(__name__)


@dataclass
class CircuitBreaker:
    """Opens after `threshold` consecutive failures, then lets one trial call through after
    `reset_after` seconds."""

    name: str
    threshold: int = 5
    reset_after: float = 30.0
    _failures: int = 0
    _opened_at: float | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        return time.monotonic() - self._opened_at < self.reset_after

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.threshold:
            if self._opened_at is None:
                log.warning("circuit_opened", circuit=self.name)
            self._opened_at = time.monotonic()


async def call_with_retry[T](
    fn: Callable[[], Awaitable[T]],
    *,
    breaker: CircuitBreaker,
    attempts: int = 3,
    base_delay: float = 0.2,
    timeout: float = 10.0,  # noqa: ASYNC109 (a per-call deadline is the point)
    retry_on: tuple[type[BaseException], ...] = (
        OSError,
        TimeoutError,
        ConnectionError,
    ),
) -> T:
    if breaker.is_open:
        raise ServiceUnavailable(f"{breaker.name} is unavailable. Try again shortly.")
    last: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            result = await asyncio.wait_for(fn(), timeout=timeout)
        except retry_on as exc:
            last = exc
            breaker.record_failure()
            if attempt == attempts or breaker.is_open:
                break
            delay = base_delay * 2 ** (attempt - 1) * (1 + random.random() / 2)  # nosec B311  # noqa: S311
            await asyncio.sleep(delay)
            continue
        breaker.record_success()
        return result
    log.warning("external_call_failed", circuit=breaker.name, error=type(last).__name__)
    raise ServiceUnavailable(f"{breaker.name} is unavailable. Try again shortly.") from last
