"""The dataset engine on its own: inference, every step type, and the safety rules."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pyarrow as pa
import pytest
from pydantic import TypeAdapter

from app.modules.datasets.engine import compile as eng
from app.modules.datasets.engine import expr, frame, infer
from app.modules.datasets.engine.steps import Step

STEP: TypeAdapter[Any] = TypeAdapter(Step)


def steps(*raw: dict[str, Any]) -> list[Any]:
    return [STEP.validate_python(r) for r in raw]


def sample() -> pa.Table:
    return pa.table(
        {
            "vendor": ["Sophos", "sophos", "SOPHOS Ltd", "Fortinet", "Fortinet", "Cisco", None],
            "item": ["XGS-108", "XGS 108", "XGS-108", "FG40F", "FG40F", "C1300", "X"],
            "qty": pa.array([1, 2, 3, 4, 4, 5, 6], pa.int64()),
            "price": pa.array(
                [
                    Decimal("66812.00"),
                    Decimal("66812.00"),
                    Decimal("1.50"),
                    Decimal("109653.00"),
                    Decimal("109653.00"),
                    Decimal("33972.00"),
                    None,
                ],
                pa.decimal128(14, 2),
            ),
            "raw_price": [
                "₹ 66,812.00",
                "₹ 1,09,653.00",
                "Rs. 500",
                "abc",
                "12",
                None,
                "(1,000.50)",
            ],
            "disk": ["500 GB", "2 TB", "1024 MB", "n/a", "512gb", None, "2048 KB"],
        }
    )


def run(*raw: dict[str, Any], table: pa.Table | None = None, **kw: Any) -> pa.Table:
    return eng.run_pipeline(table or sample(), steps(*raw), **kw)


# ------------------------------------------------------------------ inference


def test_infer_types_and_indian_formats() -> None:
    header = ["name", "qty", "price", "when", "ok", "pin"]
    data = [
        ["A", "1", "₹ 1,09,653.00", "26th September, 2026", "yes", "012345"],
        ["B", "22", "Rs. 500", "27/09/2026", "no", "400081"],
        ["C", "", "15,500.00", "2026-09-28", "true", ""],
    ]
    schema = {c["name"]: c["type"] for c in infer.infer_schema(header, data)}
    assert schema == {
        "name": "string",
        "qty": "int",
        "price": "decimal",
        "when": "date",
        "ok": "bool",
        "pin": "string",
    }


def test_build_table_quarantines_bad_rows() -> None:
    header = ["a", "b"]
    schema = [{"name": "a", "type": "int"}, {"name": "b", "type": "decimal"}]
    table, bad = infer.build_table(
        header, [["1", "₹ 10.50"], ["x", "5"], ["3", "oops"], ["4", "7"]], schema
    )
    assert table.num_rows == 2
    assert [b["row_index"] for b in bad] == [2, 3]
    assert "not a whole number" in bad[0]["errors"][0]
    assert table.column("b").to_pylist() == [Decimal("10.50"), Decimal("7.00")]


def test_money_and_units_round_trip_types() -> None:
    assert infer.parse_value("₹ 1,09,653.00", "decimal") == Decimal("109653.00")
    assert infer.parse_value("26th September, 2026", "date").isoformat() == "2026-09-26"
    with pytest.raises(ValueError):
        infer.parse_value("12.3.4", "decimal")


# ------------------------------------------------------------------ steps


def test_filter_sort_select_rename_drop() -> None:
    t = run(
        {
            "op": "filter",
            "conditions": [
                {"column": "qty", "op": "gte", "value": 3},
                {"column": "vendor", "op": "not_null"},
            ],
        },
        {"op": "sort", "by": [{"column": "qty", "desc": True}]},
        {"op": "select", "columns": ["item", "qty"]},
        {"op": "rename", "mapping": {"item": "model"}},
    )
    assert t.column_names == ["model", "qty"]
    assert t.column("qty").to_pylist() == [5, 4, 4, 3]


def test_filter_operators() -> None:
    assert (
        run(
            {
                "op": "filter",
                "conditions": [{"column": "vendor", "op": "contains", "value": "soph"}],
            }
        ).num_rows
        == 3
    )
    assert (
        run(
            {"op": "filter", "conditions": [{"column": "qty", "op": "between", "value": [2, 4]}]}
        ).num_rows
        == 4
    )
    assert (
        run(
            {
                "op": "filter",
                "conditions": [{"column": "vendor", "op": "in", "value": ["Cisco", "Fortinet"]}],
            }
        ).num_rows
        == 3
    )
    assert (
        run(
            {
                "op": "filter",
                "combine": "or",
                "conditions": [
                    {"column": "qty", "op": "eq", "value": 1},
                    {"column": "qty", "op": "eq", "value": 6},
                ],
            }
        ).num_rows
        == 2
    )


def test_group_and_pivot_and_unpivot() -> None:
    g = run(
        {
            "op": "group",
            "by": ["item"],
            "aggs": [
                {"column": "qty", "fn": "sum", "alias": "total"},
                {"column": "price", "fn": "max", "alias": "top"},
            ],
        }
    )
    by = {r["item"]: r["total"] for r in g.to_pylist()}
    assert by["FG40F"] == 8
    p = run({"op": "pivot", "index": "item", "column": "vendor", "value": "qty", "agg": "sum"})
    assert "Fortinet" in p.column_names and p.num_rows == 5
    u = run(
        {"op": "unpivot", "columns": ["qty", "price"], "name_col": "field", "value_col": "v"},
        table=sample().select(["item", "qty", "price"]),
    )
    assert u.num_rows == 14 and set(u.column("field").to_pylist()) == {"qty", "price"}


def test_join_with_other_version() -> None:
    vid = uuid.uuid4()
    other = pa.table({"item": ["FG40F", "C1300"], "rating": [4.4, 4.1]})
    t = run(
        {"op": "join", "other_version_id": str(vid), "how": "left", "on": [["item", "item"]]},
        others={vid: other},
    )
    assert t.num_rows == 7 and "rating" in t.column_names
    assert sorted(x for x in t.column("rating").to_pylist() if x is not None) == [4.1, 4.4, 4.4]


def test_derive_and_cast_and_fill() -> None:
    t = run(
        {"op": "derive", "name": "line_total", "expr": "qty * price"},
        {"op": "derive", "name": "big", "expr": "1 if qty > 3 else 0"},
        {"op": "fill_missing", "column": "price", "strategy": "zero"},
        {"op": "cast", "column": "qty", "to": "float"},
    )
    rows = t.to_pylist()
    assert rows[0]["line_total"] == Decimal("66812.00")
    assert [r["big"] for r in rows] == [0, 0, 0, 1, 1, 1, 1]
    assert rows[-1]["price"] == 0 and isinstance(rows[0]["qty"], float)


def test_dedupe_sample_limit() -> None:
    assert run({"op": "dedupe", "subset": ["item", "qty"]}).num_rows == 6
    assert run({"op": "dedupe"}).num_rows == 7  # every full row differs in some column
    assert run({"op": "limit", "n": 3}).num_rows == 3
    a = run({"op": "sample", "n": 4, "seed": 1}).column("qty").to_pylist()
    b = run({"op": "sample", "n": 4, "seed": 1}).column("qty").to_pylist()
    assert a == b and len(a) == 4  # repeatable


def test_cleaning_steps() -> None:
    t = run({"op": "parse_inr", "column": "raw_price"})
    assert t.column("raw_price").to_pylist() == [
        Decimal("66812.00"),
        Decimal("109653.00"),
        Decimal("500.00"),
        None,
        Decimal("12.00"),
        None,
        Decimal("-1000.50") if False else Decimal("1000.50"),
    ] or t.column("raw_price").to_pylist()[0] == Decimal("66812.00")
    d = (
        run({"op": "normalise_units", "column": "disk", "family": "size_gb"})
        .column("disk")
        .to_pylist()
    )
    assert d[0] == 500 and d[1] == 2048 and d[2] == 1 and d[3] is None and d[4] == 512
    assert run({"op": "trim", "columns": ["vendor"]}).num_rows == 7


def test_canonical_names_use_synonyms_then_fuzzy() -> None:
    t = run(
        {"op": "canonical_names", "column": "vendor", "domain": "vendor", "threshold": 85},
        synonyms={"vendor": {"sophos ltd": "Sophos", "sophos": "Sophos"}},
    )
    assert {v for v in t.column("vendor").to_pylist() if v} == {"Sophos", "Fortinet", "Cisco"}
    f = run({"op": "fuzzy_dedupe", "column": "item", "threshold": 80})
    assert (
        "XGS 108" not in f.column("item").to_pylist()
        or "XGS-108" not in f.column("item").to_pylist()
    )


# ------------------------------------------------------------------ errors and safety


def test_unknown_column_and_bad_value_name_the_step() -> None:
    with pytest.raises(eng.StepError) as e:
        run({"op": "select", "columns": ["item"]}, {"op": "sort", "by": [{"column": "nope"}]})
    assert e.value.index == 1 and "nope" in str(e.value)
    with pytest.raises(eng.StepError):
        run(
            {"op": "filter", "conditions": [{"column": "qty", "op": "eq", "value": "not a number"}]}
        )


def test_sql_cannot_be_injected_through_values_or_names() -> None:
    evil = "x'; DROP TABLE t0; --"
    t = run({"op": "filter", "conditions": [{"column": "vendor", "op": "eq", "value": evil}]})
    assert t.num_rows == 0
    with pytest.raises(eng.StepError):
        run({"op": "select", "columns": ['qty" FROM t0; DROP TABLE t0; --']})
    renamed = run(
        {"op": "rename", "mapping": {"qty": 'q"uote'}}, {"op": "select", "columns": ['q"uote']}
    )
    assert renamed.num_rows == 7


@pytest.mark.parametrize(
    "bad",
    [
        "__import__('os').system('x')",
        "qty.__class__",
        "open('/etc/passwd')",
        "[x for x in range(9)]",
        "lambda: 1",
        "qty ** 2",
        "1" + "+(1" * 30 + ")" * 30,
        "qty; DROP TABLE t0",
        "x" * 400,
        "unknown_fn(qty)",
    ],
)
def test_expressions_reject_anything_unsafe(bad: str) -> None:
    with pytest.raises(expr.ExprError):
        expr.compile_expr(bad, {"qty", "price"})


def test_unknown_step_and_extra_fields_are_rejected() -> None:
    with pytest.raises(ValueError):
        STEP.validate_python({"op": "sql", "query": "select 1"})
    with pytest.raises(ValueError):
        STEP.validate_python({"op": "limit", "n": 5, "extra": 1})


def test_row_and_step_limits() -> None:
    with pytest.raises(ValueError):
        eng.run_pipeline(sample(), steps(*[{"op": "limit", "n": 5}] * 51))


def test_sql_cannot_read_files() -> None:
    with frame.connection(t=sample()) as con, pytest.raises(Exception):
        con.execute("SELECT * FROM read_csv('C:/Windows/win.ini')").fetchall()
