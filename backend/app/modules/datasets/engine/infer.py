"""Schema inference for imports. Everything arrives as text and is proposed a type; the user
confirms or overrides before any row is stored. Indian money formats and dates are understood."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import pyarrow as pa

from app.core.money import MoneyError, parse_inr
from app.modules.datasets.engine import frame

_NULLS = {"", "na", "n/a", "null", "none", "nan", "-", "--"}
_BOOL_T = {"true", "yes", "y", "1"}
_BOOL_F = {"false", "no", "n", "0"}
_INT = re.compile(r"^-?\d{1,18}$")
_FLOAT = re.compile(r"^-?\d+\.\d+([eE][-+]?\d+)?$")
_INR = re.compile(
    r"^(?:₹|rs\.?|inr)\s*-?[\d,]+(?:\.\d{1,2})?$|^-?\d{1,3}(?:,\d{2})*(?:,\d{3})(?:\.\d{1,2})?$",
    re.I,
)
_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%d %b %Y",
    "%d %B %Y",
    "%d %B, %Y",
)
_LONG_DATE = re.compile(r"^(\d{1,2})(?:st|nd|rd|th)\s+([A-Za-z]+),?\s+(\d{4})$")


def is_null(v: Any) -> bool:
    return v is None or (isinstance(v, str) and v.strip().lower() in _NULLS)


def parse_date(s: str) -> date | None:
    s = s.strip()
    m = _LONG_DATE.match(s)
    if m:
        s = f"{m.group(1)} {m.group(2)} {m.group(3)}"
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_value(s: Any, typ: str) -> Any:
    """Convert one text cell. Raises ValueError when it does not fit the type."""
    if is_null(s):
        return None
    t = str(s).strip()
    if typ == "string":
        return t
    if typ == "int":
        if _INT.match(t.replace(",", "")):
            return int(t.replace(",", ""))
        raise ValueError(f"'{t}' is not a whole number")
    if typ == "decimal":
        try:
            d = parse_inr(t)
        except (MoneyError, ValueError, InvalidOperation) as exc:
            raise ValueError(f"'{t}' is not an amount") from exc
        if abs(d) > Decimal("999999999999.99"):
            raise ValueError(f"'{t}' is too large")
        return d.quantize(Decimal("0.01"))
    if typ == "float":
        try:
            return float(t.replace(",", ""))
        except ValueError as exc:
            raise ValueError(f"'{t}' is not a number") from exc
    if typ == "bool":
        low = t.lower()
        if low in _BOOL_T:
            return True
        if low in _BOOL_F:
            return False
        raise ValueError(f"'{t}' is not yes or no")
    if typ == "date":
        d2 = parse_date(t)
        if d2 is None:
            raise ValueError(f"'{t}' is not a date")
        return d2
    if typ == "timestamp":
        try:
            dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"'{t}' is not a date and time") from exc
        return dt
    raise ValueError(f"unknown type {typ}")


def infer_column(values: list[Any]) -> tuple[str, float]:
    """Best type and the share of non-empty cells that fit it."""
    cells = [str(v).strip() for v in values if not is_null(v)]
    if not cells:
        return "string", 1.0
    n = len(cells)

    def share(pred: Any) -> float:
        return sum(1 for c in cells if pred(c)) / n

    if any(len(c) > 1 and c.isdigit() and c.startswith("0") for c in cells):
        return "string", 1.0  # codes such as PIN codes keep their leading zeros
    lowers = [c.lower() for c in cells]
    if all(low in _BOOL_T | _BOOL_F for low in lowers) and any(
        low in {"true", "false", "yes", "no", "y", "n"} for low in lowers
    ):
        return "bool", 1.0
    if (s := share(lambda c: bool(_INT.match(c.replace(",", ""))))) >= 0.98:
        return "int", s
    if (s := share(lambda c: bool(_INR.match(c)))) >= 0.9:
        return "decimal", s
    if (s := share(lambda c: bool(_FLOAT.match(c)) or bool(_INT.match(c)))) >= 0.98:
        # two decimal places at most and modest size reads as money
        if all(re.match(r"^-?\d{1,12}(\.\d{1,2})?$", c) for c in cells) and any(
            "." in c for c in cells
        ):
            return "decimal", s
        return "float", s
    if (s := share(lambda c: parse_date(c) is not None)) >= 0.95:
        return "date", s
    return "string", 1.0


def infer_schema(header: list[str], data: list[list[Any]]) -> list[dict[str, Any]]:
    cols = []
    for i, name in enumerate(header):
        col = [r[i] if i < len(r) else None for r in data[:5000]]
        typ, conf = infer_column(col)
        cols.append({"name": name, "type": typ, "confidence": round(conf, 3)})
    return cols


def build_table(
    header: list[str], data: list[list[Any]], schema: list[dict[str, Any]]
) -> tuple[pa.Table, list[dict[str, Any]]]:
    """Apply a confirmed schema. Rows with cells that do not fit go to `bad` (the quarantine),
    not into the table."""
    if len(data) > frame.MAX_ROWS:
        raise ValueError(f"A dataset can have at most {frame.MAX_ROWS:,} rows.")
    types = {c["name"]: c["type"] for c in schema}
    good: dict[str, list[Any]] = {h: [] for h in header}
    bad: list[dict[str, Any]] = []
    for idx, raw in enumerate(data):
        row = list(raw) + [None] * (len(header) - len(raw))
        parsed: dict[str, Any] = {}
        errors: list[str] = []
        for h, cell in zip(header, row, strict=False):
            try:
                parsed[h] = parse_value(cell, types.get(h, "string"))
            except ValueError as exc:
                errors.append(f"{h}: {exc}")
        if errors:
            bad.append(
                {
                    "row_index": idx + 1,
                    "errors": errors,
                    "raw": {
                        h: (None if c is None else str(c))
                        for h, c in zip(header, row, strict=False)
                    },
                }
            )
            continue
        for h in header:
            good[h].append(parsed[h])
    arrays = {h: pa.array(good[h], type=frame.arrow_type(types.get(h, "string"))) for h in header}
    return pa.table(arrays), bad
