"""Chart-ready specs. The API returns aggregated data, never the raw table, with hard row caps,
so the browser can draw any of these with a few lines of code and no charting library."""

from __future__ import annotations

from typing import Any, Literal

import pyarrow as pa

from app.modules.datasets.engine import eda, frame
from app.modules.datasets.engine.frame import q

ChartType = Literal["histogram", "box", "scatter", "bar", "line", "heatmap", "pivot"]
SCATTER_CAP = 2000
BAR_CAP = 30
PIVOT_ROWS, PIVOT_COLS = 100, 30


def _names(table: pa.Table) -> dict[str, str]:
    return {c["name"]: c["type"] for c in frame.schema_of(table)}


def _need(names: dict[str, str], *cols: str | None) -> None:
    for c in cols:
        if c is not None and c not in names:
            raise ValueError(f"There is no column named '{c}'.")


def _numeric(names: dict[str, str], col: str) -> None:
    if names[col] not in eda.NUMERIC:
        raise ValueError(f"'{col}' is not a numeric column.")


def build(
    table: pa.Table,
    kind: ChartType,
    *,
    x: str | None = None,
    y: str | None = None,
    group: str | None = None,
    agg: str = "sum",
    grain: str = "month",
    bins: int = 20,
) -> dict[str, Any]:
    names = _names(table)
    _need(names, x, y, group)
    if agg not in ("sum", "avg", "min", "max", "count", "median"):
        raise ValueError("Unknown aggregation.")
    title = f"{kind}"
    with frame.connection(t=table) as con:
        if kind == "histogram":
            if not x:
                raise ValueError("A histogram needs a column (x).")
            _numeric(names, x)
            mn, mx = con.execute(f"SELECT MIN({q(x)}), MAX({q(x)}) FROM t").fetchone() or (  # nosec B608
                None,
                None,
            )
            data = eda.histogram(con, x, eda._f(mn), eda._f(mx), max(2, min(bins, 100)))
            return {"type": kind, "x": x, "y": "count", "data": data, "truncated": False}
        if kind == "box":
            if not y:
                raise ValueError("A box plot needs a numeric column (y).")
            _numeric(names, y)
            by = f"{q(x)}, " if x else ""
            grp = "GROUP BY 1 ORDER BY 1 LIMIT 30" if x else ""
            rows = con.execute(
                f"SELECT {by}MIN({q(y)}), QUANTILE_CONT({q(y)}, 0.25), MEDIAN({q(y)}), QUANTILE_CONT({q(y)}, 0.75), MAX({q(y)}), COUNT({q(y)}) FROM t {grp}"  # nosec B608
            ).fetchall()
            keys = ["min", "q1", "median", "q3", "max", "count"]
            data = []
            for r in rows:
                label, vals = (str(r[0]), r[1:]) if x else ("all", r)
                data.append(
                    {"group": label, **{k: eda._f(v) for k, v in zip(keys, vals, strict=True)}}
                )
            return {"type": kind, "x": x, "y": y, "data": data, "truncated": False}
        if kind == "scatter":
            if not x or not y:
                raise ValueError("A scatter plot needs x and y.")
            _numeric(names, x)
            _numeric(names, y)
            sel = f"{q(x)}, {q(y)}" + (f", {q(group)}" if group else "")
            total = table.num_rows
            res = frame.fetch(
                con,
                f"SELECT {sel} FROM t WHERE {q(x)} IS NOT NULL AND {q(y)} IS NOT NULL USING SAMPLE {SCATTER_CAP} ROWS REPEATABLE (7)",  # nosec B608
            )
            return {
                "type": kind,
                "x": x,
                "y": y,
                "group": group,
                "data": frame.rows(res, SCATTER_CAP),
                "truncated": total > SCATTER_CAP,
            }
        if kind == "bar":
            if not x:
                raise ValueError("A bar chart needs a category column (x).")
            if agg != "count":
                if not y:
                    raise ValueError("Give a numeric column (y) or use count.")
                _numeric(names, y)
            val = "COUNT(*)" if agg == "count" else f"{agg.upper()}({q(y or x)})"
            rows = con.execute(
                f"SELECT CAST({q(x)} AS VARCHAR), {val} v FROM t WHERE {q(x)} IS NOT NULL GROUP BY 1 ORDER BY v DESC NULLS LAST, 1 LIMIT {BAR_CAP + 1}"  # nosec B608
            ).fetchall()
            return {
                "type": kind,
                "x": x,
                "y": y or "count",
                "agg": agg,
                "data": [{"label": a, "value": eda._f(b)} for a, b in rows[:BAR_CAP]],
                "truncated": len(rows) > BAR_CAP,
            }
        if kind == "line":
            if not x or not y:
                raise ValueError("A line chart needs a date column (x) and a value (y).")
            _numeric(names, y)
            return {
                "type": kind,
                "x": x,
                "y": y,
                "agg": agg,
                "grain": grain,
                "data": eda.trend(table, x, y, agg, grain),
                "truncated": False,
            }
        if kind == "heatmap":
            if x and y:
                _need(names, x, y)
                rows = con.execute(
                    f"SELECT CAST({q(x)} AS VARCHAR), CAST({q(y)} AS VARCHAR), COUNT(*) FROM t WHERE {q(x)} IS NOT NULL AND {q(y)} IS NOT NULL "  # nosec B608
                    f"GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 400"
                ).fetchall()
                return {
                    "type": kind,
                    "x": x,
                    "y": y,
                    "data": [{"x": a, "y": b, "value": c} for a, b, c in rows],
                    "truncated": len(rows) == 400,
                }
            corr = eda.correlations(table)
            cols = corr["columns"]
            cells = [
                {"x": a, "y": b, "value": corr["matrix"][i][j]}
                for i, a in enumerate(cols)
                for j, b in enumerate(cols)
            ]
            return {
                "type": kind,
                "x": "column",
                "y": "column",
                "data": cells,
                "truncated": False,
                "columns": cols,
            }
        if kind == "pivot":
            if not (x and y and group):
                raise ValueError("A pivot table needs rows (x), columns (group) and values (y).")
            _numeric(names, y)
            fn = "COUNT" if agg == "count" else agg.upper()
            rows = con.execute(
                f"SELECT CAST({q(x)} AS VARCHAR), CAST({q(group)} AS VARCHAR), {fn}({q(y)}) FROM t GROUP BY 1, 2"  # nosec B608
            ).fetchall()
            rkeys = sorted({r[0] for r in rows if r[0] is not None})[:PIVOT_ROWS]
            ckeys = sorted({r[1] for r in rows if r[1] is not None})[:PIVOT_COLS]
            cell = {(a, b): eda._f(v) for a, b, v in rows}
            return {
                "type": kind,
                "rows": rkeys,
                "columns": ckeys,
                "data": [[cell.get((r, c)) for c in ckeys] for r in rkeys],
                "truncated": len(rkeys) == PIVOT_ROWS or len(ckeys) == PIVOT_COLS,
            }
    raise ValueError(f"Unknown chart type {title}.")
