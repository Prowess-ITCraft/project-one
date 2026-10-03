"""Time helpers. Everything is stored in UTC and shown in IST (Asia/Kolkata)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def utcnow() -> datetime:
    return datetime.now(UTC)


def to_ist(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("naive datetimes are not allowed; store UTC with tzinfo")
    return dt.astimezone(IST)


def today_ist() -> date:
    return utcnow().astimezone(IST).date()


def financial_year_start(d: date) -> int:
    """Indian financial year runs April to March. 26 Sep 2026 is in FY 2026-27, start year 2026."""
    return d.year if d.month >= 4 else d.year - 1


def financial_year_code(d: date) -> str:
    """Short FY code used in quote refs: FY 2026-27 -> '2627'."""
    start = financial_year_start(d)
    return f"{start % 100:02d}{(start + 1) % 100:02d}"


def financial_year_label(d: date) -> str:
    start = financial_year_start(d)
    return f"{start}-{(start + 1) % 100:02d}"


def _ordinal(n: int) -> str:
    if 11 <= n % 100 <= 13:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def format_long_date(d: date) -> str:
    """Quotation date style: '26th September, 2026'."""
    return f"{_ordinal(d.day)} {d.strftime('%B')}, {d.year}"
