"""A small, safe arithmetic evaluator for quantity rules. No eval, no attribute access, no
calls except a fixed set of functions. Names come from a dict the caller supplies."""

from __future__ import annotations

import ast
import math
import operator
from decimal import Decimal
from typing import Any

_BIN = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}
_FUNCS: dict[str, Any] = {
    "ceil": math.ceil,
    "floor": math.floor,
    "round": round,
    "max": max,
    "min": min,
    "abs": abs,
}
MAX_LEN = 200
MAX_DEPTH = 10


class ExprError(ValueError):
    pass


def evaluate(text: str, names: dict[str, Any]) -> Decimal:
    if len(text) > MAX_LEN:
        raise ExprError("The expression is too long.")
    try:
        tree = ast.parse(text.strip(), mode="eval")
    except SyntaxError as exc:
        raise ExprError("The expression could not be read.") from exc
    value = _eval(tree.body, names, 0)
    if isinstance(value, bool) or not isinstance(value, int | float | Decimal):
        raise ExprError("The expression must produce a number.")
    return Decimal(str(value))


def _eval(n: ast.AST, names: dict[str, Any], depth: int) -> Any:
    if depth > MAX_DEPTH:
        raise ExprError("The expression is nested too deeply.")
    if isinstance(n, ast.Constant):
        if isinstance(n.value, int | float) and not isinstance(n.value, bool):
            return n.value
        raise ExprError("Only numbers are allowed.")
    if isinstance(n, ast.Name):
        if n.id not in names:
            raise ExprError(f"Unknown name '{n.id}'.")
        v = names[n.id]
        if v is None:
            raise ExprError(f"'{n.id}' is not known for this project.")
        return v
    if isinstance(n, ast.BinOp) and type(n.op) in _BIN:
        a, b = _eval(n.left, names, depth + 1), _eval(n.right, names, depth + 1)
        try:
            return _BIN[type(n.op)](a, b)
        except ZeroDivisionError as exc:
            raise ExprError("Division by zero.") from exc
    if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
        return -_eval(n.operand, names, depth + 1)
    if (
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id in _FUNCS
        and not n.keywords
    ):
        if not 1 <= len(n.args) <= 4:
            raise ExprError("Functions take one to four values.")
        return _FUNCS[n.func.id](*[_eval(a, names, depth + 1) for a in n.args])
    raise ExprError("That expression uses something that is not allowed.")
