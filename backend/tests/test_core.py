"""Core platform pieces: money, time, crypto, sequences, outbox, rate limit, audit chain."""

from __future__ import annotations

import asyncio
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from sqlalchemy import func, select, text

from app.core import crypto, money, outbox, timeutil
from app.core.db import get_sessionmaker
from app.core.events import DomainEvent, subscribe
from app.core.sequences import next_value

amounts = st.decimals(min_value=0, max_value=Decimal("9999999999.99"), places=2)


# ------------------------------------------------------------------ money


def test_indian_formatting_matches_the_quotation() -> None:
    assert money.format_inr(Decimal("109653")) == "₹ 1,09,653.00"
    assert money.format_inr(Decimal("15500")) == "₹ 15,500.00"
    assert money.format_inr(Decimal("500")) == "₹ 500.00"
    assert money.format_inr(Decimal("12345678.9")) == "₹ 1,23,45,678.90"
    assert money.format_inr(Decimal("-1234.5"), symbol=False) == "-1,234.50"


@given(amounts)
def test_format_parse_round_trip(a: Decimal) -> None:
    assert money.parse_inr(money.format_inr(a)) == a


@given(amounts, st.integers(0, 10_000))
def test_line_amount_is_exact_for_two_decimal_prices(price: Decimal, qty: int) -> None:
    assert money.line_amount(price, qty) == price * qty


@given(amounts, st.decimals(min_value=0, max_value=28, places=2))
def test_gst_is_rounded_half_up_to_paise(taxable: Decimal, rate: Decimal) -> None:
    g = money.gst_amount(taxable, rate)
    assert g == g.quantize(Decimal("0.01"))
    assert abs(g - taxable * rate / 100) <= Decimal("0.005")


def test_half_up_rounding_and_quote_arithmetic() -> None:
    assert money.quantize(Decimal("0.005")) == Decimal("0.01")
    assert money.quantize(Decimal("0.015")) == Decimal("0.02")
    # From the sample quotation: 31 x 1,562.00 = 48,422.00 and 31 x 500 = 15,500
    assert money.line_amount(Decimal("1562.00"), 31) == Decimal("48422.00")
    assert money.line_amount(Decimal("500.00"), 31) == Decimal("15500.00")
    assert money.gst_amount(Decimal("1000"), Decimal("18")) == Decimal("180.00")


def test_floats_and_garbage_are_refused() -> None:
    for bad in (1.5, True, "abc", "NaN", "Infinity", None):
        with pytest.raises(money.MoneyError):
            money.to_decimal(bad)


def test_margin() -> None:
    assert money.margin_percent(Decimal("40000"), Decimal("49000")) == Decimal("18.37")
    assert money.margin_percent(Decimal("1"), Decimal("0")) is None


# ------------------------------------------------------------------ time


def test_financial_year_helpers() -> None:
    assert timeutil.financial_year_code(date(2026, 9, 26)) == "2627"
    assert timeutil.financial_year_code(date(2027, 3, 31)) == "2627"
    assert timeutil.financial_year_code(date(2027, 4, 1)) == "2728"
    assert timeutil.financial_year_label(date(2026, 4, 1)) == "2026-27"
    assert timeutil.format_long_date(date(2026, 9, 26)) == "26th September, 2026"
    assert timeutil.format_long_date(date(2026, 10, 1)) == "1st October, 2026"
    assert timeutil.format_long_date(date(2026, 10, 2)) == "2nd October, 2026"
    assert timeutil.format_long_date(date(2026, 10, 3)) == "3rd October, 2026"
    assert timeutil.format_long_date(date(2026, 10, 11)) == "11th October, 2026"


def test_naive_datetimes_are_refused() -> None:
    from datetime import datetime

    with pytest.raises(ValueError):
        timeutil.to_ist(datetime(2026, 1, 1))
    assert timeutil.to_ist(timeutil.utcnow()).utcoffset() is not None


# ------------------------------------------------------------------ crypto


def test_encrypt_round_trip_and_rotation(settings_env: None) -> None:
    token = crypto.encrypt_str("device-admin-password")
    assert "device-admin-password" not in token
    assert crypto.decrypt_str(token) == "device-admin-password"
    dk = crypto.new_data_key()
    assert crypto.decrypt_with(dk, crypto.encrypt_with(dk, b"x")) == b"x"
    assert crypto.unwrap_data_key(crypto.wrap_data_key(dk)) == dk


# ------------------------------------------------------------------ sequences


async def test_sequence_is_gap_free_and_collision_safe(clean_state: None) -> None:
    async def take() -> int:
        async with get_sessionmaker()() as s:
            n = await next_value(s, "quote:2627")
            await s.commit()
            return n

    got = await asyncio.gather(*(take() for _ in range(25)))
    assert sorted(got) == list(range(1, 26))
    # A rolled-back transaction gives its number back.
    async with get_sessionmaker()() as s:
        assert await next_value(s, "quote:2627") == 26
        await s.rollback()
    async with get_sessionmaker()() as s:
        assert await next_value(s, "quote:2627") == 26
    async with get_sessionmaker()() as s:
        assert await next_value(s, "quote:2728") == 1


# ------------------------------------------------------------------ outbox

_seen: list[str] = []
_fail_until: dict[str, int] = {}


@subscribe("test.ping", name="test.record")
async def _record(_: Any, event: DomainEvent) -> None:
    _seen.append(event.aggregate_id)


@subscribe("test.ping", name="test.flaky")
async def _flaky(_: Any, event: DomainEvent) -> None:
    left = _fail_until.get(event.aggregate_id, 0)
    if left > 0:
        _fail_until[event.aggregate_id] = left - 1
        raise RuntimeError("boom")


async def _publish(agg: str) -> None:
    async with get_sessionmaker()() as s:
        outbox.publish(s, DomainEvent(event_type="test.ping", aggregate_type="t", aggregate_id=agg))
        await s.commit()


async def test_outbox_delivers_once_per_subscriber(clean_state: None) -> None:
    _seen.clear()
    await _publish("a1")
    assert await outbox.dispatch_batch(get_sessionmaker()) == 2
    assert _seen == ["a1"]
    assert await outbox.dispatch_batch(get_sessionmaker()) == 0


async def test_outbox_failure_retries_and_does_not_block_others(clean_state: None) -> None:
    _seen.clear()
    _fail_until["a2"] = 1
    await _publish("a2")
    await outbox.dispatch_batch(get_sessionmaker())
    assert _seen == ["a2"]  # the healthy subscriber ran despite the flaky one failing
    async with get_sessionmaker()() as s:
        row = (
            await s.scalars(
                select(outbox.OutboxMessage).where(outbox.OutboxMessage.subscriber == "test.flaky")
            )
        ).one()
        assert row.status == "pending" and row.attempts == 1 and "boom" in (row.last_error or "")
        await s.execute(
            text("UPDATE outbox_messages SET available_at = now() - interval '1 minute'")
        )
        await s.commit()
    await outbox.dispatch_batch(get_sessionmaker())
    async with get_sessionmaker()() as s:
        row = (
            await s.scalars(
                select(outbox.OutboxMessage).where(outbox.OutboxMessage.subscriber == "test.flaky")
            )
        ).one()
        assert row.status == "done"
    assert _seen == ["a2"]  # not delivered twice to the healthy subscriber


async def test_outbox_goes_dead_after_max_attempts(clean_state: None) -> None:
    _fail_until["a3"] = 999
    await _publish("a3")
    for _ in range(outbox.MAX_ATTEMPTS):
        async with get_sessionmaker()() as s:
            await s.execute(
                text("UPDATE outbox_messages SET available_at = now() - interval '1 minute'")
            )
            await s.commit()
        await outbox.dispatch_batch(get_sessionmaker())
    async with get_sessionmaker()() as s:
        status = await s.scalar(
            select(outbox.OutboxMessage.status).where(
                outbox.OutboxMessage.subscriber == "test.flaky"
            )
        )
    assert status == "dead"


async def test_event_with_no_subscriber_is_recorded_as_done(clean_state: None) -> None:
    async with get_sessionmaker()() as s:
        outbox.publish(
            s, DomainEvent(event_type="test.nobody", aggregate_type="t", aggregate_id="x")
        )
        await s.commit()
        n = await s.scalar(
            select(func.count())
            .select_from(outbox.OutboxMessage)
            .where(outbox.OutboxMessage.status == "done")
        )
    assert n == 1


# ------------------------------------------------------------------ audit log


async def test_audit_chain_detects_tampering(clean_state: None) -> None:
    from app.core.config import get_settings
    from app.modules.audit_log import service as audit
    from app.modules.audit_log.contracts import AuditContext, record

    async with get_sessionmaker()() as s:
        for i in range(5):
            await record(
                s,
                AuditContext.system("t"),
                action="x",
                entity_type="thing",
                entity_id=str(i),
                after={"n": i},
                only_changes=False,
            )
        await s.commit()
    async with get_sessionmaker()() as s:
        ok = await audit.verify_chain(s)
    assert ok.ok and ok.checked == 5

    # The runtime role cannot rewrite history (privileges and trigger).
    async with get_sessionmaker()() as s:
        with pytest.raises(Exception):
            await s.execute(text("UPDATE audit_log SET action = 'y' WHERE id = 2"))
            await s.commit()

    # Even the owner, bypassing the trigger, is caught by the hash chain.
    from sqlalchemy.ext.asyncio import create_async_engine

    eng = create_async_engine(get_settings().database_owner_url)
    async with eng.begin() as c:
        await c.execute(text("ALTER TABLE audit_log DISABLE TRIGGER audit_log_no_update_delete"))
        await c.execute(text("UPDATE audit_log SET entity_id = 'forged' WHERE id = 3"))
        await c.execute(text("ALTER TABLE audit_log ENABLE TRIGGER audit_log_no_update_delete"))
    await eng.dispose()
    async with get_sessionmaker()() as s:
        bad = await audit.verify_chain(s)
    assert not bad.ok and bad.first_bad_id == 3


async def test_personal_data_can_be_shredded_without_breaking_the_chain(clean_state: None) -> None:
    from app.modules.audit_log import service as audit
    from app.modules.audit_log.contracts import AuditContext, record, shred_subject

    subject = uuid.uuid4()
    async with get_sessionmaker()() as s:
        await record(
            s,
            AuditContext.system("t"),
            action="create",
            entity_type="contact",
            entity_id="c1",
            after={"full_name": "Asha Rao", "email": "asha@example.com"},
            subject_id=subject,
            only_changes=False,
        )
        await s.commit()
    async with get_sessionmaker()() as s:
        entry = (await s.execute(text("SELECT id, after FROM audit_log"))).one()
        assert "Asha" not in str(entry.after)  # never stored in clear text
        assert await shred_subject(s, subject, uuid.uuid4()) is True
        await s.commit()
    async with get_sessionmaker()() as s:
        assert (await audit.verify_chain(s)).ok


# ------------------------------------------------------------------ rate limit


async def test_rate_limit_blocks_after_the_limit(clean_state: None) -> None:
    from app.core.errors import RateLimited
    from app.core.ratelimit import Limit, check

    lim = Limit("unit", 3)
    for _ in range(3):
        await check("k1", lim)
    with pytest.raises(RateLimited):
        await check("k1", lim)
    await check("k2", lim)  # other keys are unaffected


def test_comma_separated_cors_origins_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: compose passes a comma list, which pydantic-settings used to read as JSON."""
    from app.core.config import Settings

    monkeypatch.setenv("P1_CORS_ALLOW_ORIGINS", "http://a.example:1, http://b.example:2")
    assert Settings().cors_allow_origins == ["http://a.example:1", "http://b.example:2"]


def test_publishing_before_subscribers_load_is_refused() -> None:
    """Subscribers are fixed when an event is written, so publishing before they are loaded
    would lose the event silently (it happened to library files sent from the CLI)."""
    from typing import cast

    import pytest
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core import events
    from app.core.events import DomainEvent

    before = events._handlers_loaded
    events._handlers_loaded = False
    try:
        with pytest.raises(RuntimeError, match="not loaded"):
            outbox.publish(
                cast(AsyncSession, None),  # refused before the session is used
                DomainEvent(event_type="x.y", aggregate_type="x", aggregate_id="1", payload={}),
            )
    finally:
        events._handlers_loaded = before
