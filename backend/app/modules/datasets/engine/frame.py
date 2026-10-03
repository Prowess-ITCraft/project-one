"""Tables as Arrow, stored as Parquet, queried with DuckDB. No SQL ever comes from a client."""

from __future__ import annotations

import io
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

MAX_ROWS = 2_000_000
MAX_COLUMNS = 200
PREVIEW_CAP = 1000

# The small, stable set of column types users see.
TYPES = ("string", "int", "decimal", "float", "bool", "date", "timestamp")


def type_name(t: pa.DataType) -> str:
    if pa.types.is_boolean(t):
        return "bool"
    if pa.types.is_integer(t):
        return "int"
    if pa.types.is_decimal(t):
        return "decimal"
    if pa.types.is_floating(t):
        return "float"
    if pa.types.is_date(t):
        return "date"
    if pa.types.is_timestamp(t):
        return "timestamp"
    return "string"


def arrow_type(name: str) -> pa.DataType:
    return {
        "string": pa.string(),
        "int": pa.int64(),
        "decimal": pa.decimal128(14, 2),
        "float": pa.float64(),
        "bool": pa.bool_(),
        "date": pa.date32(),
        "timestamp": pa.timestamp("us", tz="UTC"),
    }[name]


def sql_type(name: str) -> str:
    return {
        "string": "VARCHAR",
        "int": "BIGINT",
        "decimal": "DECIMAL(14,2)",
        "float": "DOUBLE",
        "bool": "BOOLEAN",
        "date": "DATE",
        "timestamp": "TIMESTAMPTZ",
    }[name]


def schema_of(table: pa.Table) -> list[dict[str, str]]:
    return [{"name": f.name, "type": type_name(f.type)} for f in table.schema]


def to_parquet(table: pa.Table) -> bytes:
    sink = io.BytesIO()
    pq.write_table(table, sink, compression="zstd")
    return sink.getvalue()


def from_parquet(data: bytes) -> pa.Table:
    return pq.read_table(io.BytesIO(data))


def q(name: str) -> str:
    """Quote an identifier. Names are also checked against the real column list by callers."""
    if "\x00" in name:
        raise ValueError("bad column name")
    return '"' + name.replace('"', '""') + '"'


@contextmanager
def connection(**tables: pa.Table) -> Iterator[duckdb.DuckDBPyConnection]:
    con = duckdb.connect(":memory:")
    try:
        con.execute("SET threads TO 2")
        con.execute("SET memory_limit = '1GB'")
        con.execute("SET enable_external_access = false")  # no reading files or URLs from SQL
        for name, tbl in tables.items():
            con.register(name, tbl)
        yield con
    finally:
        con.close()


def fetch(con: duckdb.DuckDBPyConnection, sql: str, params: list[Any] | None = None) -> pa.Table:
    return con.execute(sql, params or []).to_arrow_table()


def rows(table: pa.Table, limit: int = PREVIEW_CAP, offset: int = 0) -> list[dict[str, Any]]:
    """JSON-safe rows for previews: decimals and dates become strings."""
    out: list[dict[str, Any]] = []
    for r in table.slice(offset, limit).to_pylist():
        out.append({k: _jsonable(v) for k, v in r.items()})
    return out


def _jsonable(v: Any) -> Any:
    if v is None or isinstance(v, bool | int | float | str):
        return v
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return str(v)
