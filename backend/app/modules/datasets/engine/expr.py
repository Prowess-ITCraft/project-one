"""A tiny safe expression language for derived columns. No eval: the text is parsed with `ast`
and only whitelisted nodes are turned into SQL. Column names are checked against the table."""

from __future__ import annotations

import ast

from app.modules.datasets.engine.frame import q

_BIN = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/", ast.Mod: "%"}
_CMP = {ast.Gt: ">", ast.GtE: ">=", ast.Lt: "<", ast.LtE: "<=", ast.Eq: "=", ast.NotEq: "<>"}
_FUNCS = {
    "round": ("ROUND", (1, 2)),
    "abs": ("ABS", (1, 1)),
    "lower": ("LOWER", (1, 1)),
    "upper": ("UPPER", (1, 1)),
    "trim": ("TRIM", (1, 1)),
    "length": ("LENGTH", (1, 1)),
    "coalesce": ("COALESCE", (2, 6)),
    "least": ("LEAST", (2, 6)),
    "greatest": ("GREATEST", (2, 6)),
    "year": ("YEAR", (1, 1)),
    "month": ("MONTH", (1, 1)),
}


class ExprError(ValueError):
    pass


def compile_expr(text: str, columns: set[str]) -> str:
    if len(text) > 300:
        raise ExprError("The expression is too long (300 characters at most).")
    try:
        tree = ast.parse(text.strip(), mode="eval")
    except SyntaxError as exc:
        raise ExprError(
            "The expression could not be read. Use column names in quotes, numbers, + - * /, and functions like round()."
        ) from exc
    return _node(tree.body, columns, depth=0)


def _node(n: ast.AST, cols: set[str], depth: int) -> str:
    if depth > 12:
        raise ExprError("The expression is nested too deeply.")
    if isinstance(n, ast.Constant):
        v = n.value
        if isinstance(v, bool):
            return "TRUE" if v else "FALSE"
        if isinstance(v, int | float):
            return repr(v)
        if isinstance(v, str):
            # A string constant is a column name when it matches one, otherwise a text literal.
            if v in cols:
                return q(v)
            return "'" + v.replace("'", "''") + "'"
        raise ExprError("Only numbers and text are allowed.")
    if isinstance(n, ast.Name):
        if n.id in cols:
            return q(n.id)
        raise ExprError(f"Unknown column '{n.id}'. Put names with spaces in quotes.")
    if isinstance(n, ast.BinOp) and type(n.op) in _BIN:
        return f"({_node(n.left, cols, depth + 1)} {_BIN[type(n.op)]} {_node(n.right, cols, depth + 1)})"
    if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
        return f"(-{_node(n.operand, cols, depth + 1)})"
    if isinstance(n, ast.Compare) and len(n.ops) == 1 and type(n.ops[0]) in _CMP:
        return f"({_node(n.left, cols, depth + 1)} {_CMP[type(n.ops[0])]} {_node(n.comparators[0], cols, depth + 1)})"
    if isinstance(n, ast.IfExp):
        return (
            f"(CASE WHEN {_node(n.test, cols, depth + 1)} THEN {_node(n.body, cols, depth + 1)} "
            f"ELSE {_node(n.orelse, cols, depth + 1)} END)"
        )
    if (
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id in _FUNCS
        and not n.keywords
    ):
        sql, (lo, hi) = _FUNCS[n.func.id]
        if not lo <= len(n.args) <= hi:
            raise ExprError(f"{n.func.id}() takes {lo} to {hi} values.")
        return f"{sql}({', '.join(_node(a, cols, depth + 1) for a in n.args)})"
    raise ExprError("That expression uses something that is not allowed.")
