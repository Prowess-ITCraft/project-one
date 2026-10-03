"""Exploratory data analysis over one table: per-column statistics, distributions, missingness,
outliers, correlations and trends. Everything is aggregated in DuckDB and returned small."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

import pyarrow as pa

from app.modules.datasets.engine import frame
from app.modules.datasets.engine.frame import q

NUMERIC = {"int", "decimal", "float"}
BINS = 20
TOP = 10
MAX_CORR_COLUMNS = 20


def _f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) or math.isinf(x) else round(x, 6)


def config_hash(cfg: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True, default=str).encode()).hexdigest()[:16]


def column_stats(
    table: pa.Table, *, outlier_z: float = 3.0, iqr_k: float = 1.5
) -> list[dict[str, Any]]:
    schema = frame.schema_of(table)
    out: list[dict[str, Any]] = []
    with frame.connection(t=table) as con:
        total = table.num_rows
        for col in schema:
            name, typ = col["name"], col["type"]
            c = q(name)
            nulls, distinct = con.execute(
                f"SELECT COUNT(*) FILTER (WHERE {c} IS NULL), COUNT(DISTINCT {c}) FROM t"
            ).fetchone() or (0, 0)
            s: dict[str, Any] = {
                "name": name,
                "type": typ,
                "count": total - nulls,
                "missing": nulls,
                "missing_percent": round(100 * nulls / total, 2) if total else 0.0,
                "distinct": distinct,
                "cardinality": "unique"
                if total and distinct == total - nulls and total > 1
                else ("constant" if distinct <= 1 else "varied"),
            }
            if typ in NUMERIC and total - nulls > 0:
                row = con.execute(
                    f"SELECT MIN({c}), MAX({c}), AVG({c}), STDDEV_SAMP({c}), MEDIAN({c}), "
                    f"QUANTILE_CONT({c}, 0.25), QUANTILE_CONT({c}, 0.75) FROM t"
                ).fetchone()
                mn, mx, mean, sd, med, q1, q3 = (_f(x) for x in (row or (None,) * 7))
                s |= {
                    "min": mn,
                    "max": mx,
                    "mean": mean,
                    "std": sd,
                    "median": med,
                    "q1": q1,
                    "q3": q3,
                }
                if q1 is not None and q3 is not None:
                    lo, hi = q1 - iqr_k * (q3 - q1), q3 + iqr_k * (q3 - q1)
                    iqr_n = con.execute(
                        f"SELECT COUNT(*) FROM t WHERE {c} < ? OR {c} > ?", [lo, hi]
                    ).fetchone()
                    s["outliers_iqr"] = {
                        "count": iqr_n[0] if iqr_n else 0,
                        "low": _f(lo),
                        "high": _f(hi),
                    }
                if sd and mean is not None and sd > 0:
                    z_n = con.execute(
                        f"SELECT COUNT(*) FROM t WHERE ABS(({c} - ?) / ?) > ?",
                        [mean, sd, outlier_z],
                    ).fetchone()
                    s["outliers_z"] = {"count": z_n[0] if z_n else 0, "threshold": outlier_z}
                s["histogram"] = histogram(con, name, mn, mx)
            elif typ in ("date", "timestamp") and total - nulls > 0:
                row = con.execute(f"SELECT MIN({c}), MAX({c}) FROM t").fetchone()
                s["min"], s["max"] = (str(row[0]), str(row[1])) if row else (None, None)
            elif typ == "string" and total - nulls > 0:
                row = con.execute(
                    f"SELECT MIN(LENGTH({c})), AVG(LENGTH({c})), MAX(LENGTH({c})) FROM t"
                ).fetchone()
                s["length"] = {"min": row[0], "mean": _f(row[1]), "max": row[2]} if row else None
            if typ in ("string", "bool", "int") and distinct > 0:
                s["top"] = [
                    {"value": None if v is None else str(v), "count": n}
                    for v, n in con.execute(
                        f"SELECT {c}, COUNT(*) n FROM t WHERE {c} IS NOT NULL GROUP BY 1 ORDER BY n DESC, 1 LIMIT {TOP}"
                    ).fetchall()
                ]
            out.append(s)
    return out


def histogram(
    con: Any, name: str, mn: float | None, mx: float | None, bins: int = BINS
) -> list[dict[str, Any]]:
    if mn is None or mx is None:
        return []
    c = q(name)
    if mn == mx:
        n = con.execute(f"SELECT COUNT({c}) FROM t").fetchone()[0]
        return [{"from": mn, "to": mx, "count": n}]
    width = (mx - mn) / bins
    rows = con.execute(
        f"SELECT LEAST(CAST(FLOOR((CAST({c} AS DOUBLE) - ?) / ?) AS INTEGER), {bins - 1}) b, COUNT(*) "
        f"FROM t WHERE {c} IS NOT NULL GROUP BY 1 ORDER BY 1",
        [mn, width],
    ).fetchall()
    counts = {b: n for b, n in rows}
    return [
        {"from": _f(mn + i * width), "to": _f(mn + (i + 1) * width), "count": counts.get(i, 0)}
        for i in range(bins)
    ]


def correlations(table: pa.Table) -> dict[str, Any]:
    cols = [c["name"] for c in frame.schema_of(table) if c["type"] in NUMERIC][:MAX_CORR_COLUMNS]
    matrix: list[list[float | None]] = []
    with frame.connection(t=table) as con:
        for a in cols:
            sel = ", ".join("1.0" if a == b else f"CORR({q(a)}, {q(b)})" for b in cols)
            row = con.execute(f"SELECT {sel} FROM t").fetchone() or ()
            matrix.append([_f(x) for x in row])
    return {"columns": cols, "matrix": matrix}


def trend(
    table: pa.Table, date_col: str, value_col: str, agg: str = "sum", grain: str = "month"
) -> list[dict[str, Any]]:
    if agg not in ("sum", "avg", "min", "max", "count"):
        raise ValueError("Unknown aggregation.")
    if grain not in ("day", "week", "month", "quarter", "year"):
        raise ValueError("Unknown grain.")
    names = {c["name"]: c["type"] for c in frame.schema_of(table)}
    if names.get(date_col) not in ("date", "timestamp"):
        raise ValueError(f"'{date_col}' is not a date column.")
    if value_col not in names:
        raise ValueError(f"There is no column named '{value_col}'.")
    with frame.connection(t=table) as con:
        rows = con.execute(
            f"SELECT DATE_TRUNC('{grain}', {q(date_col)}) p, {agg.upper()}({q(value_col)}) v FROM t "
            f"WHERE {q(date_col)} IS NOT NULL GROUP BY 1 ORDER BY 1"
        ).fetchall()
    return [{"period": str(p)[:10], "value": _f(v)} for p, v in rows]


def outlier_rows(
    table: pa.Table, column: str, method: str = "iqr", k: float = 1.5, limit: int = 50
) -> list[dict[str, Any]]:
    names = {c["name"]: c["type"] for c in frame.schema_of(table)}
    if names.get(column) not in NUMERIC:
        raise ValueError(f"'{column}' is not a numeric column.")
    c = q(column)
    with frame.connection(t=table) as con:
        if method == "iqr":
            q1, q3 = con.execute(
                f"SELECT QUANTILE_CONT({c}, 0.25), QUANTILE_CONT({c}, 0.75) FROM t"
            ).fetchone() or (None, None)
            if q1 is None:
                return []
            lo, hi = (
                float(q1) - k * (float(q3) - float(q1)),
                float(q3) + k * (float(q3) - float(q1)),
            )
            res = frame.fetch(
                con, f"SELECT * FROM t WHERE {c} < ? OR {c} > ? LIMIT {int(limit)}", [lo, hi]
            )
        else:
            mean, sd = con.execute(f"SELECT AVG({c}), STDDEV_SAMP({c}) FROM t").fetchone() or (
                None,
                None,
            )
            if not sd:
                return []
            res = frame.fetch(
                con,
                f"SELECT * FROM t WHERE ABS(({c} - ?) / ?) > ? LIMIT {int(limit)}",
                [float(mean), float(sd), k],
            )
    return frame.rows(res, limit)
