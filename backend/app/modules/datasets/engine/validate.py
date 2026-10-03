"""Validation rules for a dataset. Rows that break a rule go to the quarantine table instead of
the dataset, with the reasons, so nothing bad is stored silently and nothing good is lost."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Annotated, Any, Literal

import pyarrow as pa
from pydantic import BaseModel, ConfigDict, Field

from app.modules.datasets.engine import frame

Col = Annotated[str, Field(min_length=1, max_length=120)]


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column: Col
    kind: Literal["required", "min", "max", "regex", "allowed", "unique"]
    value: str | int | float | list[str] | None = None
    message: str | None = Field(default=None, max_length=200)


def apply_rules(table: pa.Table, rules: list[Rule]) -> tuple[pa.Table, list[dict[str, Any]]]:
    """Return (clean table, quarantine rows). Row numbers are 1-based positions in `table`."""
    if not rules:
        return table, []
    names = set(table.column_names)
    for r in rules:
        if r.column not in names:
            raise ValueError(f"Rule refers to unknown column '{r.column}'.")
    errors: dict[int, list[str]] = {}
    cols = {n: table.column(n).to_pylist() for n in names if any(r.column == n for r in rules)}
    for r in rules:
        vals = cols[r.column]
        label = r.message
        seen: dict[Any, int] = {}
        pattern = re.compile(str(r.value)) if r.kind == "regex" else None
        if pattern is not None and len(str(r.value)) > 200:
            raise ValueError("A pattern can have at most 200 characters.")
        for i, v in enumerate(vals):
            msg: str | None = None
            if r.kind == "required" and (v is None or v == ""):
                msg = f"{r.column} is required"
            elif v is not None:
                if (
                    r.kind in ("min", "max")
                    and r.value is not None
                    and isinstance(v, int | float | Decimal)
                ):
                    bound, x = Decimal(str(r.value)), Decimal(str(v))
                    if r.kind == "min" and x < bound:
                        msg = f"{r.column} is below {r.value}"
                    elif r.kind == "max" and x > bound:
                        msg = f"{r.column} is above {r.value}"
                elif pattern is not None and not pattern.fullmatch(str(v)):
                    msg = f"{r.column} does not match the expected pattern"
                elif r.kind == "allowed" and isinstance(r.value, list) and str(v) not in r.value:
                    msg = f"{r.column} must be one of {', '.join(r.value)}"
                elif r.kind == "unique":
                    if v in seen:
                        msg = f"{r.column} repeats the value on row {seen[v] + 1}"
                    else:
                        seen[v] = i
            if msg:
                errors.setdefault(i, []).append(label or msg)
    if not errors:
        return table, []
    bad_idx = sorted(errors)
    keep = [i for i in range(table.num_rows) if i not in errors]
    raw = table.take(bad_idx).to_pylist()
    quarantine = [
        {
            "row_index": i + 1,
            "errors": errors[i],
            "raw": {k: frame._jsonable(v) for k, v in row.items()},
        }
        for i, row in zip(bad_idx, raw, strict=True)
    ]
    return table.take(keep), quarantine
