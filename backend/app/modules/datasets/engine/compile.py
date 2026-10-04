"""Run a list of steps over a table. Each step becomes one DuckDB statement built only from
validated identifiers and bound parameters, materialised as a temp table so a failure points at
one step."""

from __future__ import annotations

import uuid
from typing import Any

import duckdb
import pyarrow as pa
from rapidfuzz import fuzz, process

from app.modules.datasets.engine import expr, frame
from app.modules.datasets.engine.frame import q, sql_type
from app.modules.datasets.engine.steps import (
    MAX_STEPS,
    CanonicalNames,
    Cast,
    Dedupe,
    Derive,
    Drop,
    FillMissing,
    Filter,
    FuzzyDedupe,
    Group,
    Join,
    Limit,
    NormaliseUnits,
    ParseInr,
    Pivot,
    Rename,
    Sample,
    Select,
    Sort,
    Step,
    Trim,
    Unpivot,
)


class StepError(ValueError):
    def __init__(self, index: int, message: str) -> None:
        super().__init__(f"Step {index + 1}: {message}")
        self.index = index
        self.message = message


_AGG = {
    "sum": "SUM",
    "avg": "AVG",
    "min": "MIN",
    "max": "MAX",
    "count": "COUNT",
    "count_distinct": "COUNT(DISTINCT",
    "median": "MEDIAN",
}


def _agg_sql(fn: str, col: str) -> str:
    if fn == "count_distinct":
        return f"COUNT(DISTINCT {q(col)})"
    return f"{_AGG[fn]}({q(col)})"


def _columns(con: duckdb.DuckDBPyConnection, table: str) -> dict[str, str]:
    return {r[0]: r[1] for r in con.execute(f"DESCRIBE {table}").fetchall()}


def _need(cols: dict[str, str] | set[str], *names: str) -> None:
    for n in names:
        if n not in cols:
            raise ValueError(f"There is no column named '{n}'.")


def _cluster(
    values: list[tuple[str, int]], threshold: int, seed: dict[str, str] | None = None
) -> dict[str, str]:
    """Map each spelling to a canonical one. Most frequent spellings win; `seed` holds known
    aliases (lower case) and is always honoured first."""
    seed = seed or {}
    canon: list[str] = sorted({v for v in seed.values()})
    out: dict[str, str] = {}
    for val, _ in sorted(values, key=lambda x: -x[1]):
        key = val.strip().lower()
        if key in seed:
            out[val] = seed[key]
            continue
        match = (
            process.extractOne(val, canon, scorer=fuzz.WRatio, score_cutoff=threshold)
            if canon
            else None
        )
        if match:
            out[val] = match[0]
        else:
            canon.append(val)
            out[val] = val
    return out


def run_pipeline(
    base: pa.Table,
    steps: list[Step],
    *,
    others: dict[uuid.UUID, pa.Table] | None = None,
    synonyms: dict[str, dict[str, str]] | None = None,
) -> pa.Table:
    if len(steps) > MAX_STEPS:
        raise ValueError(f"A pipeline can have at most {MAX_STEPS} steps.")
    others = others or {}
    synonyms = synonyms or {}
    tables: dict[str, pa.Table] = {"t0": base}
    for vid, tbl in others.items():
        tables["o_" + vid.hex] = tbl
    with frame.connection(**tables) as con:
        cur = "t0"
        for i, step in enumerate(steps):
            nxt = f"t{i + 1}"
            try:
                _apply(con, cur, nxt, step, i, synonyms)
            except StepError:
                raise
            except duckdb.Error as exc:
                raise StepError(i, _friendly(str(exc))) from exc
            except ValueError as exc:
                raise StepError(i, str(exc)) from exc
            cur = nxt
            n = con.execute(f"SELECT COUNT(*) FROM {cur}").fetchone()  # nosec B608
            if n and n[0] > frame.MAX_ROWS:
                raise StepError(i, f"This step produced more than {frame.MAX_ROWS:,} rows.")
            if len(_columns(con, cur)) > frame.MAX_COLUMNS:
                raise StepError(i, f"This step produced more than {frame.MAX_COLUMNS} columns.")
        return frame.fetch(con, f"SELECT * FROM {cur}")  # nosec B608


def _friendly(msg: str) -> str:
    first = msg.strip().splitlines()[0]
    return first[:240]


def _condition_sql(c: Any, cols: dict[str, str]) -> tuple[str, list[Any]]:
    _need(cols, c.column)
    col = q(c.column)
    v = c.value
    if c.op == "is_null":
        return f"{col} IS NULL", []
    if c.op == "not_null":
        return f"{col} IS NOT NULL", []
    if c.op == "in":
        if not isinstance(v, list) or not v:
            raise ValueError("'in' needs a list of values.")
        return f"{col} IN ({', '.join('?' for _ in v)})", list(v)
    if c.op == "between":
        if not isinstance(v, list) or len(v) != 2:
            raise ValueError("'between' needs exactly two values.")
        return f"{col} BETWEEN ? AND ?", list(v)
    if v is None or isinstance(v, list):
        raise ValueError(f"'{c.op}' needs a single value.")
    if c.op == "contains":
        return f"CONTAINS(LOWER(CAST({col} AS VARCHAR)), LOWER(?))", [str(v)]
    if c.op == "starts_with":
        return f"STARTS_WITH(LOWER(CAST({col} AS VARCHAR)), LOWER(?))", [str(v)]
    op = {"eq": "=", "ne": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}[c.op]
    return f"{col} {op} ?", [v]


def _apply(
    con: duckdb.DuckDBPyConnection,
    cur: str,
    nxt: str,
    s: Step,
    i: int,
    synonyms: dict[str, dict[str, str]],
) -> None:
    cols = _columns(con, cur)
    names = list(cols)
    params: list[Any] = []
    sql: str

    if isinstance(s, Filter):
        parts = []
        for c in s.conditions:
            frag, p = _condition_sql(c, cols)
            parts.append(frag)
            params += p
        sql = f"SELECT * FROM {cur} WHERE {(' AND ' if s.combine == 'and' else ' OR ').join(parts)}"  # nosec B608
    elif isinstance(s, Sort):
        _need(cols, *[k.column for k in s.by])
        sql = f"SELECT * FROM {cur} ORDER BY " + ", ".join(  # nosec B608
            f"{q(k.column)} {'DESC' if k.desc else 'ASC'} NULLS LAST" for k in s.by
        )
    elif isinstance(s, Select):
        _need(cols, *s.columns)
        sql = f"SELECT {', '.join(q(c) for c in s.columns)} FROM {cur}"  # nosec B608
    elif isinstance(s, Drop):
        _need(cols, *s.columns)
        keep = [c for c in names if c not in set(s.columns)]
        if not keep:
            raise ValueError("That would remove every column.")
        sql = f"SELECT {', '.join(q(c) for c in keep)} FROM {cur}"  # nosec B608
    elif isinstance(s, Rename):
        _need(cols, *s.mapping)
        new = [s.mapping.get(c, c) for c in names]
        if len(set(new)) != len(new):
            raise ValueError("Two columns would end up with the same name.")
        sql = f"SELECT {', '.join(f'{q(c)} AS {q(s.mapping.get(c, c))}' for c in names)} FROM {cur}"  # nosec B608
    elif isinstance(s, Cast):
        _need(cols, s.column)
        exprs = [
            f"TRY_CAST({q(c)} AS {sql_type(s.to)}) AS {q(c)}" if c == s.column else q(c)
            for c in names
        ]
        sql = f"SELECT {', '.join(exprs)} FROM {cur}"  # nosec B608
    elif isinstance(s, Derive):
        if s.name in cols:
            raise ValueError(f"A column named '{s.name}' already exists.")
        e = expr.compile_expr(s.expr, set(names))
        sql = f"SELECT *, {e} AS {q(s.name)} FROM {cur}"  # nosec B608
    elif isinstance(s, Group):
        _need(cols, *s.by, *[a.column for a in s.aggs])
        aliases = [a.alias for a in s.aggs]
        if len(set(aliases + s.by)) != len(aliases) + len(s.by):
            raise ValueError("Output column names must be different.")
        sel = [q(b) for b in s.by] + [f"{_agg_sql(a.fn, a.column)} AS {q(a.alias)}" for a in s.aggs]
        sql = f"SELECT {', '.join(sel)} FROM {cur}" + (  # nosec B608
            f" GROUP BY {', '.join(q(b) for b in s.by)}" if s.by else ""
        )
    elif isinstance(s, Join):
        other = "o_" + s.other_version_id.hex
        try:
            ocols = _columns(con, other)
        except duckdb.Error as exc:
            raise ValueError("The other dataset version is not available.") from exc
        _need(cols, *[a for a, _ in s.on])
        _need(ocols, *[b for _, b in s.on])
        drop_right = {b for _, b in s.on}
        right = [c for c in ocols if c not in drop_right]
        clash = [c for c in right if c in cols]
        sel = [f"l.{q(c)}" for c in names] + [
            f"r.{q(c)} AS {q(c + ('_other' if c in clash else ''))}" for c in right
        ]
        cond = " AND ".join(f"l.{q(a)} = r.{q(b)}" for a, b in s.on)
        sql = f"SELECT {', '.join(sel)} FROM {cur} l {'LEFT' if s.how == 'left' else 'INNER'} JOIN {other} r ON {cond}"  # nosec B608
    elif isinstance(s, Pivot):
        _need(cols, s.index, s.column, s.value)
        distinct = [
            r[0]
            for r in con.execute(
                f"SELECT DISTINCT {q(s.column)} FROM {cur} ORDER BY 1 LIMIT 51"  # nosec B608
            ).fetchall()
        ]
        if len(distinct) > 50:
            raise ValueError("The pivot column has more than 50 distinct values.")
        agg = _AGG[s.agg] if s.agg != "count_distinct" else "COUNT"
        sel = [q(s.index)] + [
            f"{agg}({q(s.value)}) FILTER (WHERE {q(s.column)} IS NOT DISTINCT FROM ?) AS {q('(empty)' if v is None else str(v))}"
            for v in distinct
        ]
        params = list(distinct)
        sql = f"SELECT {', '.join(sel)} FROM {cur} GROUP BY {q(s.index)} ORDER BY 1"  # nosec B608
    elif isinstance(s, Unpivot):
        _need(cols, *s.columns)
        ids = [c for c in names if c not in set(s.columns)]
        parts = [
            f"SELECT {', '.join(q(c) for c in ids + [])}{', ' if ids else ''}'{c.replace(chr(39), chr(39) * 2)}' AS {q(s.name_col)}, CAST({q(c)} AS VARCHAR) AS {q(s.value_col)} FROM {cur}"  # nosec B608
            for c in s.columns
        ]
        sql = " UNION ALL ".join(parts)
    elif isinstance(s, Sample):
        if (s.n is None) == (s.fraction is None):
            raise ValueError("Give either a row count or a fraction.")
        if s.n is not None:
            sql = f"SELECT * FROM {cur} USING SAMPLE reservoir({s.n} ROWS) REPEATABLE ({s.seed})"  # nosec B608
        else:
            sql = f"SELECT * FROM {cur} USING SAMPLE {(s.fraction or 0) * 100} PERCENT (bernoulli, {s.seed})"  # nosec B608
    elif isinstance(s, Limit):
        sql = f"SELECT * FROM {cur} LIMIT {int(s.n)}"  # nosec B608
    elif isinstance(s, Dedupe):
        if s.subset:
            _need(cols, *s.subset)
            sql = f"SELECT * FROM {cur} QUALIFY ROW_NUMBER() OVER (PARTITION BY {', '.join(q(c) for c in s.subset)}) = 1"  # nosec B608
        else:
            sql = f"SELECT DISTINCT * FROM {cur}"  # nosec B608
    elif isinstance(s, FillMissing):
        _need(cols, s.column)
        col = q(s.column)
        if s.strategy == "constant":
            if s.value is None:
                raise ValueError("A constant needs a value.")
            fill, params = "?", [s.value]
        elif s.strategy == "zero":
            fill = "0"
        elif s.strategy in ("mean", "median"):
            fill = f"(SELECT {'AVG' if s.strategy == 'mean' else 'MEDIAN'}({col}) FROM {cur})"  # nosec B608
        else:
            fill = f"(SELECT MODE({col}) FROM {cur})"  # nosec B608
        sql = f"SELECT {', '.join(f'COALESCE({q(n)}, {fill}) AS {q(n)}' if n == s.column else q(n) for n in names)} FROM {cur}"  # nosec B608
    elif isinstance(s, Trim):
        _need(cols, *s.columns)
        sql = f"SELECT {', '.join(f'TRIM({q(n)}) AS {q(n)}' if n in s.columns else q(n) for n in names)} FROM {cur}"  # nosec B608
    elif isinstance(s, ParseInr):
        _need(cols, s.column)
        col = q(s.column)
        conv = f"TRY_CAST(REGEXP_REPLACE(CAST({col} AS VARCHAR), '[^0-9.\\-]', '', 'g') AS DECIMAL(14,2))"
        sql = f"SELECT {', '.join(f'{conv} AS {q(n)}' if n == s.column else q(n) for n in names)} FROM {cur}"  # nosec B608
    elif isinstance(s, NormaliseUnits):
        _need(cols, s.column)
        txt = f"LOWER(CAST({q(s.column)} AS VARCHAR))"
        if s.family == "size_gb":
            unit = f"REGEXP_EXTRACT({txt}, '([0-9]+(?:\\.[0-9]+)?)\\s*(kb|mb|gb|tb)', 2)"
            factor = f"CASE {unit} WHEN 'kb' THEN 1.0/1048576 WHEN 'mb' THEN 1.0/1024 WHEN 'gb' THEN 1.0 WHEN 'tb' THEN 1024.0 END"
            num = f"TRY_CAST(REGEXP_EXTRACT({txt}, '([0-9]+(?:\\.[0-9]+)?)\\s*(kb|mb|gb|tb)', 1) AS DOUBLE)"
        else:
            unit = f"REGEXP_EXTRACT({txt}, '([0-9]+(?:\\.[0-9]+)?)\\s*(kbps|mbps|gbps)', 2)"
            factor = f"CASE {unit} WHEN 'kbps' THEN 0.001 WHEN 'mbps' THEN 1.0 WHEN 'gbps' THEN 1000.0 END"
            num = f"TRY_CAST(REGEXP_EXTRACT({txt}, '([0-9]+(?:\\.[0-9]+)?)\\s*(kbps|mbps|gbps)', 1) AS DOUBLE)"
        sql = f"SELECT {', '.join(f'({num} * ({factor})) AS {q(n)}' if n == s.column else q(n) for n in names)} FROM {cur}"  # nosec B608
    elif isinstance(s, CanonicalNames | FuzzyDedupe):
        _need(cols, s.column)
        counts = con.execute(
            f"SELECT CAST({q(s.column)} AS VARCHAR) v, COUNT(*) FROM {cur} WHERE {q(s.column)} IS NOT NULL GROUP BY 1"  # nosec B608
        ).fetchall()
        seed = synonyms.get(s.domain, {}) if isinstance(s, CanonicalNames) else {}
        mapping = _cluster([(v, int(n)) for v, n in counts], s.threshold, seed)
        mtab = pa.table({"k": list(mapping.keys()), "c": list(mapping.values())})
        con.register(f"map_{i}", mtab)
        sel = [
            f"COALESCE(m.c, CAST(t.{q(s.column)} AS VARCHAR)) AS {q(s.column)}"
            if n == s.column
            else f"t.{q(n)}"
            for n in names
        ]
        body = f"SELECT {', '.join(sel)} FROM {cur} t LEFT JOIN map_{i} m ON CAST(t.{q(s.column)} AS VARCHAR) = m.k"  # nosec B608
        sql = f"SELECT DISTINCT * FROM ({body})" if isinstance(s, FuzzyDedupe) else body  # nosec B608
    else:  # pragma: no cover - the union is closed
        raise ValueError("Unknown step.")

    con.execute(f"CREATE TEMP TABLE {nxt} AS {sql}", params)
