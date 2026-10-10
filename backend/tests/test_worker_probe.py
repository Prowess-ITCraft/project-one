"""The probe task the chaos checks use: it records that it ran, and never waits too long."""

import redis

from app import worker
from app.core.config import get_settings


def test_probe_records_that_it_ran(settings_env: None) -> None:
    assert worker.probe("unit-test", 0) == "unit-test"
    r = redis.from_url(get_settings().redis_url)
    try:
        assert r.get(worker.PROBE_KEY + "unit-test") is not None
        assert 0 < r.ttl(worker.PROBE_KEY + "unit-test") <= 3600
    finally:
        r.delete(worker.PROBE_KEY + "unit-test")
        r.close()


def test_probe_wait_is_capped(monkeypatch, settings_env: None) -> None:
    waited: list[float] = []
    monkeypatch.setattr("time.sleep", waited.append)
    worker.probe("capped", 10_000)
    assert waited == [worker.PROBE_MAX_SECONDS]
