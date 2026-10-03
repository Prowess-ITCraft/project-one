"""Money rules, in one place.

- Decimal only. Floats are rejected.
- Amounts are stored as NUMERIC(14,2), rates (GST, margin) as NUMERIC(5,2) percentages.
- Rounding is ROUND_HALF_UP to 2 places (paise), applied per line amount, then totals are
  sums of already rounded line amounts, which is how the ITCraft quotations add up.
- Indian digit grouping: 1,09,653.00.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Annotated

from pydantic import AfterValidator, BeforeValidator, PlainSerializer
from sqlalchemy import Numeric

PAISE = Decimal("0.01")
MAX_AMOUNT = Decimal("999999999999.99")  # fits NUMERIC(14,2)
DEFAULT_CURRENCY = "INR"
DEFAULT_GST_RATE = Decimal("18.00")
RUPEE = "₹"

AmountColumn = Numeric(14, 2)
RateColumn = Numeric(5, 2)


class MoneyError(ValueError):
    pass


def to_decimal(value: object) -> Decimal:
    if isinstance(value, bool | float):
        raise MoneyError("money must be a Decimal, int or numeric string, never a float")
    if isinstance(value, Decimal):
        d = value
    elif isinstance(value, int):
        d = Decimal(value)
    elif isinstance(value, str):
        try:
            d = Decimal(value.strip())
        except InvalidOperation as exc:
            raise MoneyError(f"not a number: {value!r}") from exc
    else:
        raise MoneyError(f"unsupported money type: {type(value).__name__}")
    if not d.is_finite():
        raise MoneyError("money must be finite")
    return d


def quantize(amount: Decimal) -> Decimal:
    return amount.quantize(PAISE, rounding=ROUND_HALF_UP)


def line_amount(unit_price: Decimal, qty: Decimal | int) -> Decimal:
    return quantize(to_decimal(unit_price) * to_decimal(qty))


def gst_amount(taxable: Decimal, rate_percent: Decimal) -> Decimal:
    return quantize(to_decimal(taxable) * to_decimal(rate_percent) / Decimal(100))


def margin_percent(cost: Decimal, selling: Decimal) -> Decimal | None:
    """Margin on selling price, 2 dp. None when selling price is zero."""
    if selling == 0:
        return None
    return quantize((selling - cost) / selling * Decimal(100))


def _group_indian(integer_digits: str) -> str:
    if len(integer_digits) <= 3:
        return integer_digits
    last3 = integer_digits[-3:]
    rest = integer_digits[:-3]
    groups: list[str] = []
    while len(rest) > 2:
        groups.insert(0, rest[-2:])
        rest = rest[:-2]
    if rest:
        groups.insert(0, rest)
    return ",".join([*groups, last3])


def format_inr(amount: Decimal, *, symbol: bool = True) -> str:
    """format_inr(Decimal('109653')) -> '₹ 1,09,653.00'."""
    q = quantize(to_decimal(amount))
    sign = "-" if q < 0 else ""
    text = f"{abs(q):.2f}"
    integer, fraction = text.split(".")
    body = f"{sign}{_group_indian(integer)}.{fraction}"
    return f"{RUPEE} {body}" if symbol else body


def parse_inr(text: str) -> Decimal:
    """Parse '₹ 1,09,653.00', 'Rs. 1,09,653', 'INR 500' and plain numbers."""
    cleaned = text.strip()
    for token in (RUPEE, "INR", "Rs.", "Rs", "/-"):
        cleaned = cleaned.replace(token, "")
    cleaned = cleaned.replace(",", "").replace(" ", "")
    negative = cleaned.startswith("(") and cleaned.endswith(")")
    cleaned = cleaned.strip("()")
    if not cleaned:
        raise MoneyError(f"no amount in {text!r}")
    value = to_decimal(cleaned)
    return -value if negative else value


def _validate_amount(v: Decimal) -> Decimal:
    if v.as_tuple().exponent < -2:  # type: ignore[operator]
        raise ValueError("at most 2 decimal places")
    if abs(v) > MAX_AMOUNT:
        raise ValueError("amount too large")
    return quantize(v)


def _validate_rate(v: Decimal) -> Decimal:
    if v < 0 or v > 100:
        raise ValueError("rate must be between 0 and 100")
    return quantize(v)


def _non_negative(v: Decimal) -> Decimal:
    if v < 0:
        raise ValueError("must be zero or more")
    return v


def _no_float(v: object) -> object:
    if isinstance(v, float):
        raise ValueError("send money as a string or integer, not a float")
    return v


# Pydantic field types. Serialised as strings so clients never see binary floats.
Amount = Annotated[
    Decimal,
    BeforeValidator(_no_float),
    AfterValidator(_validate_amount),
    PlainSerializer(lambda d: f"{d:.2f}", return_type=str, when_used="json"),
]
NonNegativeAmount = Annotated[Amount, AfterValidator(_non_negative)]
RatePercent = Annotated[
    Decimal,
    BeforeValidator(_no_float),
    AfterValidator(_validate_rate),
    PlainSerializer(lambda d: f"{d:.2f}", return_type=str, when_used="json"),
]
