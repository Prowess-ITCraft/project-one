"""Prices that do not fit their history (Phase 13, ADR 0029).

The rule, always on while learning is on: compare a new price with the same item's earlier
prices. With three or more, a robust score on the log price (median and median absolute
deviation) above 3.5 and at least 15 percent away from the median flags it; with one or two,
more than 30 percent away from the last price flags it. The rule is deterministic and its
alert is advice to the sales head, never a block.

The model, in shadow mode until approved: a LightGBM regression of the log price on the item's
category, kind, vendor and the item itself, trained from a frozen set of price points. A price
more than three residual standard deviations from the prediction is what the model would flag.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import date
from typing import Any

MIN_POINTS = 100
ROBUST_Z = 3.5
MIN_CHANGE_PCT = 15.0
FEW_POINTS_CHANGE_PCT = 30.0
MODEL_SIGMAS = 3.0


class NotEnoughData(Exception):
    pass


@dataclass(frozen=True)
class Verdict:
    flag: bool
    change_pct: float | None
    reason: str | None


def rule_check(history: list[float], price: float) -> Verdict:
    """`history` is the item's earlier selling prices, oldest first."""
    prior = [p for p in history if p > 0]
    if not prior or price <= 0:
        return Verdict(False, None, None)
    if len(prior) < 3:
        last = prior[-1]
        change = (price - last) / last * 100
        if abs(change) > FEW_POINTS_CHANGE_PCT:
            return Verdict(True, round(change, 1), f"{change:+.0f}% against the last price")
        return Verdict(False, round(change, 1), None)
    logs = [math.log(p) for p in prior]
    med = statistics.median(logs)
    mad = statistics.median(abs(v - med) for v in logs)
    scale = 1.4826 * mad if mad > 0 else 0.05  # a flat history still tolerates small moves
    z = (math.log(price) - med) / scale
    change = (price - math.exp(med)) / math.exp(med) * 100
    if abs(z) > ROBUST_Z and abs(change) >= MIN_CHANGE_PCT:
        return Verdict(
            True,
            round(change, 1),
            f"{change:+.0f}% against the usual price of {len(prior)} earlier quotes",
        )
    return Verdict(False, round(change, 1), None)


@dataclass
class DriftModel:
    artifact: dict[str, Any]
    metrics: dict[str, Any] = field(default_factory=dict)


def _row_features(row: dict[str, Any]) -> dict[str, float]:
    out = {
        f"category={row['category']}": 1.0,
        f"kind={row['item_kind']}": 1.0,
        f"item={row['item_id']}": 1.0,
    }
    if row.get("vendor"):
        out[f"vendor={row['vendor']}"] = 1.0
    return out


def train(rows: list[dict[str, Any]]) -> DriftModel:
    if len(rows) < MIN_POINTS:
        raise NotEnoughData(
            f"Training needs at least {MIN_POINTS} prices in the price book history; this "
            f"training set has {len(rows)}."
        )
    import lightgbm as lgb

    feats = [_row_features(r) for r in rows]
    names = sorted({k for f in feats for k in f})
    x = [[f.get(n, 0.0) for n in names] for f in feats]
    y = [math.log(float(r["selling"])) for r in rows]
    reg = lgb.LGBMRegressor(
        n_estimators=200,
        num_leaves=15,
        min_child_samples=3,
        learning_rate=0.05,
        random_state=0,
        deterministic=True,
        force_row_wise=True,
        verbose=-1,
    )
    reg.fit(x, y)
    pred = list(reg.predict(x))
    resid = [a - b for a, b in zip(y, pred, strict=True)]
    sigma = max(statistics.pstdev(resid), 0.02)
    artifact = {"features": names, "model": reg.booster_.model_to_string(), "sigma": sigma}
    flagged = sum(1 for r in resid if abs(r) > MODEL_SIGMAS * sigma)
    metrics = {
        "points": len(rows),
        "items": len({r["item_id"] for r in rows}),
        "residual_sigma_log": round(sigma, 4),
        "mean_abs_error_pct": round(statistics.fmean(abs(math.exp(r) - 1) for r in resid) * 100, 2),
        "would_flag_in_training": flagged,
    }
    return DriftModel(artifact, metrics)


def model_check(artifact: dict[str, Any], row: dict[str, Any]) -> tuple[float, bool]:
    """(expected selling price, flag) for one new price."""
    import lightgbm as lgb

    names: list[str] = artifact["features"]
    f = _row_features(row)
    x = [f.get(n, 0.0) for n in names]
    booster = lgb.Booster(model_str=artifact["model"])
    expected_log = float(booster.predict([x])[0])
    gap = abs(math.log(float(row["selling"])) - expected_log)
    return round(math.exp(expected_log), 2), gap > MODEL_SIGMAS * float(artifact["sigma"])


def point_row(p: Any) -> dict[str, Any]:
    """A price point as a training row: no supplier names, no people."""
    return {
        "item_id": str(p.item_id),
        "category": p.category,
        "item_kind": p.item_kind,
        "vendor": p.vendor,
        "selling": p.selling,
        "quoted_on": p.quoted_on.isoformat() if isinstance(p.quoted_on, date) else p.quoted_on,
    }
