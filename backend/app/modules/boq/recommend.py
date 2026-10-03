"""The recommendation engine, v1: hard filters, then a transparent weighted score.

It never hides why. Every choice carries reasons ("supports 50 users, you need 35", "within
budget by 12,000", "customer prefers Sophos") and the runner-ups stay visible. Prices come only
from the price book; a missing price lowers nothing silently, it is reported.

`score_candidates` is pure so it can be tested and later swapped for a learned ranker behind
the same contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from app.core.money import format_inr
from app.modules.catalogue.contracts import ItemRef, PriceQuote

DEFAULT_WEIGHTS: dict[str, float] = {
    "need_fit": 0.25,
    "budget_fit": 0.20,
    "tco": 0.15,
    "market": 0.10,
    "lifecycle": 0.10,
    "vendor": 0.10,
    "stock": 0.05,
    "history": 0.05,
}


@dataclass
class Candidate:
    item: ItemRef
    price: PriceQuote | None
    market: dict[str, Any] = field(default_factory=dict)
    history_count: int = 0
    swapped_from: str | None = None  # set when the original was out of stock


@dataclass
class Context:
    users: int | None = None
    preferred: tuple[str, ...] = ()
    excluded: tuple[str, ...] = ()
    budget: Decimal | None = None  # for this category
    today: date = field(default_factory=date.today)


@dataclass
class Ranked:
    candidate: Candidate
    score: float
    criteria: dict[str, float]
    reasons: list[str]


@dataclass
class Rejected:
    item: ItemRef
    reason: str


def _norm(name: str | None) -> str:
    return (name or "").strip().lower()


def hard_filter(cands: list[Candidate], ctx: Context) -> tuple[list[Candidate], list[Rejected]]:
    keep: list[Candidate] = []
    out: list[Rejected] = []
    excluded = {_norm(x) for x in ctx.excluded}
    for c in cands:
        it = c.item
        if not it.active:
            out.append(Rejected(it, "No longer sold"))
        elif _norm(it.vendor_name) in excluded:
            out.append(Rejected(it, f"The customer excludes {it.vendor_name}"))
        elif it.stock_status == "out_of_stock" and it.alternative_item_id is None:
            out.append(Rejected(it, "Out of stock and no alternative is listed"))
        elif (it.eos_date and it.eos_date <= ctx.today) or (
            it.eol_date and it.eol_date <= ctx.today
        ):
            out.append(Rejected(it, "Past end of life or end of support"))
        else:
            cap = it.attributes.get("concurrent_users_max")
            if ctx.users and isinstance(cap, int | float) and cap < ctx.users:
                out.append(Rejected(it, f"Supports {int(cap)} users but {ctx.users} are needed"))
            else:
                keep.append(c)
    return keep, out


def score_candidates(
    cands: list[Candidate], ctx: Context, weights: dict[str, float] | None = None
) -> tuple[list[Ranked], list[Rejected]]:
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    total_w = sum(w.values()) or 1.0
    kept, rejected = hard_filter(cands, ctx)
    prices = [
        c.price.selling for c in kept if c.price and c.price.usable and c.price.selling is not None
    ]
    lo, hi = (min(prices), max(prices)) if prices else (None, None)
    ranked: list[Ranked] = []
    for c in kept:
        it, reasons = c.item, []
        crit: dict[str, float] = {}

        cap = it.attributes.get("concurrent_users_max")
        if ctx.users and isinstance(cap, int | float):
            crit["need_fit"] = 1.0 if cap <= 2 * ctx.users else 0.6
            reasons.append(f"supports {int(cap)} users, {ctx.users} needed")
        else:
            crit["need_fit"] = 0.5

        price = (
            c.price.selling if c.price and c.price.usable and c.price.selling is not None else None
        )
        if price is None:
            crit["budget_fit"] = crit["tco"] = 0.3
            reasons.append("no current price: enter one by hand")
        else:
            if ctx.budget:
                gap = ctx.budget - price
                crit["budget_fit"] = 1.0 if gap >= 0 else max(0.0, 1 + float(gap / ctx.budget))
                reasons.append(
                    f"within budget by {format_inr(gap)}"
                    if gap >= 0
                    else f"over budget by {format_inr(-gap)}"
                )
            else:
                crit["budget_fit"] = 0.5
            crit["tco"] = (
                1.0
                if lo == hi
                else float((hi - price) / (hi - lo))
                if lo is not None and hi is not None
                else 0.5
            )

        rating = c.market.get("analyst_rating")
        crit["market"] = min(float(rating) / 5.0, 1.0) if isinstance(rating, int | float) else 0.5
        if isinstance(rating, int | float):
            reasons.append(f"rated {rating:g} out of 5")

        eol = it.eol_date or it.eos_date
        if eol is None:
            crit["lifecycle"] = 0.8
        else:
            years = (eol - ctx.today).days / 365
            crit["lifecycle"] = 1.0 if years > 3 else 0.6 if years > 1 else 0.2
            if years <= 3:
                reasons.append(f"support ends {eol:%b %Y}")

        pref = {_norm(x) for x in ctx.preferred}
        if _norm(it.vendor_name) in pref and pref:
            crit["vendor"] = 1.0
            reasons.append(f"customer prefers {it.vendor_name}")
        else:
            crit["vendor"] = 0.5

        crit["stock"] = {"in_stock": 1.0, "limited": 0.7, "on_order": 0.4}.get(it.stock_status, 0.4)
        if c.swapped_from:
            reasons.append(f"replaces {c.swapped_from}, which is out of stock")
        elif it.stock_status != "in_stock":
            reasons.append(it.stock_status.replace("_", " "))

        crit["history"] = min(c.history_count / 3, 1.0)
        if c.history_count:
            reasons.append(
                f"proposed in {c.history_count} past BOQ{'s' if c.history_count != 1 else ''}"
            )

        score = sum(crit[k] * w[k] for k in crit) / total_w
        ranked.append(
            Ranked(c, round(score, 4), {k: round(v, 3) for k, v in crit.items()}, reasons)
        )
    ranked.sort(key=lambda r: (-r.score, r.candidate.item.name))
    return ranked, rejected
