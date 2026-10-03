"""The pipeline step vocabulary. Every transformation is one of these JSON steps, validated
strictly, so a pipeline can be saved, replayed on new data, undone and diffed. There is no way
to send SQL or code."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Col = Annotated[str, Field(min_length=1, max_length=120)]
Agg = Literal["sum", "avg", "min", "max", "count", "count_distinct", "median"]
ColType = Literal["string", "int", "decimal", "float", "bool", "date", "timestamp"]
Op = Literal[
    "eq",
    "ne",
    "gt",
    "gte",
    "lt",
    "lte",
    "in",
    "contains",
    "starts_with",
    "is_null",
    "not_null",
    "between",
]


class _S(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Condition(_S):
    column: Col
    op: Op
    value: str | int | float | bool | list[str | int | float] | None = None


class Filter(_S):
    op: Literal["filter"] = "filter"
    conditions: list[Condition] = Field(min_length=1, max_length=20)
    combine: Literal["and", "or"] = "and"


class SortKey(_S):
    column: Col
    desc: bool = False


class Sort(_S):
    op: Literal["sort"] = "sort"
    by: list[SortKey] = Field(min_length=1, max_length=5)


class Select(_S):
    op: Literal["select"] = "select"
    columns: list[Col] = Field(min_length=1, max_length=200)


class Drop(_S):
    op: Literal["drop"] = "drop"
    columns: list[Col] = Field(min_length=1, max_length=200)


class Rename(_S):
    op: Literal["rename"] = "rename"
    mapping: dict[Col, Col] = Field(min_length=1, max_length=50)


class Cast(_S):
    op: Literal["cast"] = "cast"
    column: Col
    to: ColType


class Derive(_S):
    op: Literal["derive"] = "derive"
    name: Col
    expr: Annotated[str, Field(min_length=1, max_length=300)]


class AggSpec(_S):
    column: Col
    fn: Agg
    alias: Col


class Group(_S):
    op: Literal["group"] = "group"
    by: list[Col] = Field(default_factory=list, max_length=10)
    aggs: list[AggSpec] = Field(min_length=1, max_length=20)


class Join(_S):
    op: Literal["join"] = "join"
    other_version_id: uuid.UUID
    how: Literal["inner", "left"] = "left"
    on: list[tuple[Col, Col]] = Field(min_length=1, max_length=4)


class Pivot(_S):
    op: Literal["pivot"] = "pivot"
    index: Col
    column: Col
    value: Col
    agg: Agg = "sum"


class Unpivot(_S):
    op: Literal["unpivot"] = "unpivot"
    columns: list[Col] = Field(min_length=2, max_length=100)
    name_col: Col = "variable"
    value_col: Col = "value"


class Sample(_S):
    op: Literal["sample"] = "sample"
    n: int | None = Field(default=None, ge=1, le=1_000_000)
    fraction: float | None = Field(default=None, gt=0, le=1)
    seed: int = 7


class Limit(_S):
    op: Literal["limit"] = "limit"
    n: int = Field(ge=1, le=2_000_000)


class Dedupe(_S):
    op: Literal["dedupe"] = "dedupe"
    subset: list[Col] | None = None


class FuzzyDedupe(_S):
    """Merge near-identical spellings in one text column, then drop exact duplicates."""

    op: Literal["fuzzy_dedupe"] = "fuzzy_dedupe"
    column: Col
    threshold: int = Field(default=92, ge=60, le=100)


class FillMissing(_S):
    op: Literal["fill_missing"] = "fill_missing"
    column: Col
    strategy: Literal["constant", "mean", "median", "mode", "zero"]
    value: str | int | float | None = None


class Trim(_S):
    op: Literal["trim"] = "trim"
    columns: list[Col] = Field(min_length=1, max_length=50)


class ParseInr(_S):
    """Turn text like '₹ 1,09,653.00' into a decimal column."""

    op: Literal["parse_inr"] = "parse_inr"
    column: Col


class NormaliseUnits(_S):
    """Bring sizes to GB (from KB, MB, GB, TB) or speeds to Mbps (from Kbps, Mbps, Gbps)."""

    op: Literal["normalise_units"] = "normalise_units"
    column: Col
    family: Literal["size_gb", "speed_mbps"]


class CanonicalNames(_S):
    """Replace vendor or product spellings with their canonical name (synonyms table, then fuzzy)."""

    op: Literal["canonical_names"] = "canonical_names"
    column: Col
    domain: Literal["vendor", "product"]
    threshold: int = Field(default=90, ge=60, le=100)


Step = Annotated[
    Filter
    | Sort
    | Select
    | Drop
    | Rename
    | Cast
    | Derive
    | Group
    | Join
    | Pivot
    | Unpivot
    | Sample
    | Limit
    | Dedupe
    | FuzzyDedupe
    | FillMissing
    | Trim
    | ParseInr
    | NormaliseUnits
    | CanonicalNames,
    Field(discriminator="op"),
]
MAX_STEPS = 50
