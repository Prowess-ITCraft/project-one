"""Redis fixed-window rate limiting, per IP and per user.

Fails open with a warning if Redis is unreachable, except for buckets marked strict
(auth, OTP, upload) which fail closed so a Redis outage cannot be used to brute force.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import structlog
from fastapi import Request
from redis.exceptions import RedisError

from app.core.errors import RateLimited, ServiceUnavailable
from app.core.redis import get_redis

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class Limit:
    bucket: str
    per_minute: int
    strict: bool = False


async def hit(key: str, limit: int, window_seconds: int = 60) -> tuple[bool, int]:
    """Count one hit. Returns (allowed, seconds until reset)."""
    r = get_redis()
    pipe = r.pipeline(transaction=True)
    pipe.incr(key)
    pipe.expire(key, window_seconds, nx=True)
    pipe.ttl(key)
    count, _, ttl = await pipe.execute()
    return int(count) <= limit, max(int(ttl), 1)


async def check(key: str, limit: Limit) -> None:
    try:
        allowed, retry_after = await hit(f"rl:{limit.bucket}:{key}", limit.per_minute)
    except RedisError as exc:
        if limit.strict:
            log.error("rate_limit_redis_down_fail_closed", bucket=limit.bucket)
            raise ServiceUnavailable("Rate limiting is unavailable. Try again shortly.") from exc
        log.warning("rate_limit_redis_down_fail_open", bucket=limit.bucket)
        return
    if not allowed:
        raise RateLimited(headers={"Retry-After": str(retry_after)})


def by_ip(limit: Limit) -> Callable[[Request], Awaitable[None]]:
    async def dependency(request: Request) -> None:
        await check(f"ip:{request.state.client_ip}", limit)

    return dependency


async def reset_bucket(bucket: str, key: str) -> None:
    await get_redis().delete(f"rl:{bucket}:{key}")
