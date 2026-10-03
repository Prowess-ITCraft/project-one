"""The rule condition language: JSON predicates over facts, with three outcomes.

    {"fact": "nas.used_percent", "op": "gte", "value": 90}
    {"all": [p, p]}   {"any": [p, p]}   {"not": p}

Evaluating returns True, False or None (unknown, because a fact the rule needs is missing). Unknown
propagates the careful way: `all` is False if any part is False, otherwise unknown if any part
is unknown; `any` is True if any part is True, otherwise unknown if any part is unknown.
There is no eval and no code in a rule.
"""

from __future__ import annotations

from typing import Any

from app.modules.infra.facts import FACT_CATALOGUE, FactSheet

OPS = {"eq", "ne", "gt", "gte", "lt", "lte", "in", "exists", "missing", "contains"}
MAX_DEPTH = 6
MAX_NODES = 40


class RuleError(ValueError):
    pass


def validate(pred: Any, *, _depth: int = 0, _count: list[int] | None = None) -> None:
    count = _count if _count is not None else [0]
    count[0] += 1
    if count[0] > MAX_NODES or _depth > MAX_DEPTH:
        raise RuleError("The condition is too large or too deeply nested.")
    if not isinstance(pred, dict) or len(pred) == 0:
        raise RuleError("A condition must be an object.")
    if "all" in pred or "any" in pred:
        key = "all" if "all" in pred else "any"
        if set(pred) != {key} or not isinstance(pred[key], list) or not pred[key]:
            raise RuleError(f"'{key}' needs a non-empty list and nothing else.")
        for p in pred[key]:
            validate(p, _depth=_depth + 1, _count=count)
        return
    if "not" in pred:
        if set(pred) != {"not"}:
            raise RuleError("'not' stands alone.")
        validate(pred["not"], _depth=_depth + 1, _count=count)
        return
    if set(pred) - {"fact", "op", "value"} or "fact" not in pred or "op" not in pred:
        raise RuleError("A test needs 'fact' and 'op' (and 'value' for most operators).")
    if pred["fact"] not in FACT_CATALOGUE:
        raise RuleError(f"Unknown fact '{pred['fact']}'.")
    if pred["op"] not in OPS:
        raise RuleError(f"Unknown operator '{pred['op']}'.")
    if pred["op"] not in ("exists", "missing") and "value" not in pred:
        raise RuleError(f"Operator '{pred['op']}' needs a value.")


def facts_used(pred: dict[str, Any]) -> set[str]:
    if "fact" in pred:
        return {pred["fact"]}
    out: set[str] = set()
    for key in ("all", "any"):
        for p in pred.get(key, []):
            out |= facts_used(p)
    if "not" in pred:
        out |= facts_used(pred["not"])
    return out


def evaluate(pred: dict[str, Any], sheet: FactSheet) -> bool | None:
    if "all" in pred:
        results = [evaluate(p, sheet) for p in pred["all"]]
        if any(r is False for r in results):
            return False
        return None if any(r is None for r in results) else True
    if "any" in pred:
        results = [evaluate(p, sheet) for p in pred["any"]]
        if any(r is True for r in results):
            return True
        return None if any(r is None for r in results) else False
    if "not" in pred:
        r = evaluate(pred["not"], sheet)
        return None if r is None else not r
    value = sheet.get(pred["fact"])
    op = pred["op"]
    if op == "exists":
        return value is not None
    if op == "missing":
        return value is None
    if value is None:
        return None
    target = pred["value"]
    try:
        if op == "eq":
            return bool(value == target)
        if op == "ne":
            return bool(value != target)
        if op == "gt":
            return bool(value > target)
        if op == "gte":
            return bool(value >= target)
        if op == "lt":
            return bool(value < target)
        if op == "lte":
            return bool(value <= target)
        if op == "in":
            return value in target
        if op == "contains":
            return str(target).lower() in str(value).lower()
    except TypeError:
        return None
    return None
