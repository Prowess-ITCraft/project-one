"""The learned ranker: how much each recommendation criterion actually mattered (ADR 0020).

The rule engine scores every candidate on the same eight criteria and adds them up with fixed
weights. This learns those weights from what customers really accepted. Each training group is
one recommendation (a BOQ line where several products were ranked); every pair of a kept and a
not-kept candidate is one example, and a pairwise logistic model (Bradley-Terry) fits

    P(kept beats not kept) = sigmoid(w . (x_kept - x_not_kept))

Weights are kept non-negative and summed to 1, so the result reads exactly like the rule
weights and can be shown to people: a criterion can matter more or less, never count against.
Plain Python on purpose: eight features and hundreds of pairs do not need a library.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from typing import Any

# The rule engine's criteria, in a fixed order (boq.recommend.DEFAULT_WEIGHTS has the same keys).
FEATURES: tuple[str, ...] = (
    "need_fit",
    "budget_fit",
    "tco",
    "market",
    "lifecycle",
    "vendor",
    "stock",
    "history",
)
MIN_GROUPS = 20
NEUTRAL = 0.5  # what the rule engine uses when it knows nothing about a criterion


@dataclass(frozen=True)
class Example:
    group: str  # boq id and recommendation key
    item_id: str
    criteria: dict[str, float]
    rule_score: float
    kept: bool


@dataclass
class Result:
    weights: dict[str, float]
    metrics: dict[str, Any] = field(default_factory=dict)


def vector(criteria: dict[str, Any]) -> list[float]:
    out = []
    for k in FEATURES:
        v = criteria.get(k)
        out.append(float(v) if isinstance(v, int | float) else NEUTRAL)
    return out


def score(weights: dict[str, float], criteria: dict[str, Any]) -> float:
    return sum(weights.get(k, 0.0) * x for k, x in zip(FEATURES, vector(criteria), strict=True))


def usable_groups(examples: list[Example]) -> dict[str, list[Example]]:
    """Groups that teach something: at least one kept and one not-kept candidate."""
    groups: dict[str, list[Example]] = {}
    for e in examples:
        groups.setdefault(e.group, []).append(e)
    return {
        g: xs for g, xs in groups.items() if any(x.kept for x in xs) and any(not x.kept for x in xs)
    }


def _holdout(group: str) -> bool:
    # Stable across runs and machines, so a retrain on the same set gives the same split.
    return int(hashlib.sha256(group.encode()).hexdigest(), 16) % 5 == 0


def _pairs(groups: dict[str, list[Example]]) -> list[list[float]]:
    out = []
    for xs in groups.values():
        for a in (x for x in xs if x.kept):
            va = vector(a.criteria)
            for b in (x for x in xs if not x.kept):
                out.append([p - q for p, q in zip(va, vector(b.criteria), strict=True)])
    return out


def _sigmoid(z: float) -> float:
    return 1 / (1 + math.exp(-z)) if z >= 0 else math.exp(z) / (1 + math.exp(z))


def fit(
    diffs: list[list[float]], *, l2: float = 0.05, steps: int = 600, lr: float = 0.5
) -> list[float]:
    """Gradient descent on the pairwise log-loss with L2, starting from equal weights."""
    n = len(FEATURES)
    w = [1.0 / n] * n
    if not diffs:
        return w
    m = len(diffs)
    for _ in range(steps):
        grad = [l2 * wi for wi in w]
        for d in diffs:
            p = _sigmoid(sum(wi * di for wi, di in zip(w, d, strict=True)))
            for i in range(n):
                grad[i] -= (1 - p) * d[i] / m
        w = [max(0.0, wi - lr * gi) for wi, gi in zip(w, grad, strict=True)]
    return w


def _normalise(w: list[float]) -> dict[str, float]:
    total = sum(w)
    if total <= 0:
        return {k: round(1 / len(FEATURES), 4) for k in FEATURES}
    return {k: round(v / total, 4) for k, v in zip(FEATURES, w, strict=True)}


def top1(groups: dict[str, list[Example]], key: Any) -> float | None:
    """Share of groups where the highest-scored candidate is one the customer kept."""
    if not groups:
        return None
    hits = sum(1 for xs in groups.values() if max(xs, key=key).kept)
    return round(hits / len(groups), 3)


def pairwise_accuracy(groups: dict[str, list[Example]], weights: dict[str, float]) -> float | None:
    diffs = _pairs(groups)
    if not diffs:
        return None
    w = [weights[k] for k in FEATURES]
    right = sum(1 for d in diffs if sum(a * b for a, b in zip(w, d, strict=True)) > 0)
    return round(right / len(diffs), 3)


class NotEnoughData(ValueError):
    pass


def train(examples: list[Example], *, min_groups: int = MIN_GROUPS) -> Result:
    groups = usable_groups(examples)
    if len(groups) < min_groups:
        raise NotEnoughData(
            f"Only {len(groups)} accepted recommendations can teach the ranker; it needs at "
            f"least {min_groups}. Accept more BOQs, then build a new training set."
        )
    test = {g: xs for g, xs in groups.items() if _holdout(g)}
    train_groups = {g: xs for g, xs in groups.items() if g not in test}
    if len(test) < 3:  # too few to judge on unseen data; report on everything instead
        train_groups, test, holdout = groups, groups, False
    else:
        holdout = True
    weights = _normalise(fit(_pairs(train_groups)))
    return Result(
        weights,
        {
            "groups": len(groups),
            "train_groups": len(train_groups),
            "test_groups": len(test),
            "holdout": holdout,
            "pairs": len(_pairs(train_groups)),
            "rules_top1": top1(test, key=lambda x: x.rule_score),
            "model_top1": top1(test, key=lambda x: score(weights, x.criteria)),
            "model_pairwise": pairwise_accuracy(test, weights),
        },
    )
