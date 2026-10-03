"""Data quality and analysis for the corpus. Pure functions over plain dicts.

Per document: completeness, validity, consistency, uniqueness, confidence and labelling, each 0
to 1, combined into a score from 0 to 100 with the reasons listed.

Per collection: how many lines per label, price bands per label (median and quartiles), and
robust outliers. Outliers use the median absolute deviation (MAD): a value is flagged when its
modified z-score is above 3.5. MAD is used instead of the mean and standard deviation because a
few very large quotes would otherwise hide every other outlier. Flagged rows are never removed;
a person decides.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal
from statistics import median
from typing import Any

WEIGHTS = {
    "completeness": 0.25,
    "validity": 0.20,
    "consistency": 0.20,
    "uniqueness": 0.10,
    "confidence": 0.15,
    "labelled": 0.10,
}
MAD_Z = 3.5
MIN_FOR_OUTLIERS = 5


def _dec(v: Any) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v))
    except ArithmeticError:
        return None


def _share(n: int, d: int) -> float:
    return 1.0 if d == 0 else round(n / d, 4)


def boq_quality(doc: dict[str, Any], lines: list[dict[str, Any]]) -> dict[str, Any]:
    """`doc` holds the document facts, `lines` the cleaned lines (money as strings or Decimal)."""
    issues: list[str] = []
    priced = doc.get("doc_kind") == "quotation"
    n = len(lines)
    if n == 0:
        return {"score": 0, "parts": dict.fromkeys(WEIGHTS, 0.0), "issues": ["No lines were read."]}

    need = ["component", "qty"] + (["unit_price", "amount"] if priced else [])
    filled = sum(1 for ln in lines for f in need if ln.get(f) not in (None, ""))
    head_need = ["quote_ref", "quote_date", "customer"] if priced else []
    head_filled = sum(1 for f in head_need if doc.get(f))
    completeness = _share(filled + head_filled, n * len(need) + len(head_need))
    for f in head_need:
        if not doc.get(f):
            issues.append(f"The {f.replace('_', ' ')} was not found.")

    valid = 0
    for ln in lines:
        q, p, a = ln.get("qty"), _dec(ln.get("unit_price")), _dec(ln.get("amount"))
        ok = isinstance(q, int) and q > 0 and (p is None or p >= 0) and (a is None or a >= 0)
        valid += ok
        if not ok:
            issues.append(f"Line {ln.get('line_ref')}: quantity or price is not valid.")
    validity = _share(valid, n)

    checked = consistent = 0
    for ln in lines:
        q, p, a = ln.get("qty"), _dec(ln.get("unit_price")), _dec(ln.get("amount"))
        if isinstance(q, int) and p is not None and a is not None:
            checked += 1
            if abs(p * q - a) <= Decimal("0.01"):
                consistent += 1
            else:
                issues.append(
                    f"Line {ln.get('line_ref')}: amount {a} is not quantity {q} times price {p}."
                )
    consistency = _share(consistent, checked)

    keys = Counter(
        (ln.get("name_key"), ln.get("option"), ln.get("qty"), str(ln.get("unit_price")))
        for ln in lines
    )
    dupes = sum(c - 1 for c in keys.values() if c > 1)
    if dupes:
        issues.append(f"{dupes} line(s) repeat another line exactly.")
    uniqueness = _share(n - dupes, n)

    confidence = round(sum(float(ln.get("confidence") or 0) for ln in lines) / n, 4)
    labelled = _share(sum(1 for ln in lines if ln["label"]["gap_type"] != "other"), n)
    for ln in lines:
        if ln["label"]["gap_type"] == "other":
            issues.append(f"Line {ln.get('line_ref')}: no gap type matched; label it by hand.")

    parts = {
        "completeness": completeness,
        "validity": validity,
        "consistency": consistency,
        "uniqueness": uniqueness,
        "confidence": confidence,
        "labelled": labelled,
    }
    score = round(100 * sum(parts[k] * w for k, w in WEIGHTS.items()))
    return {"score": score, "parts": parts, "issues": issues[:50]}


def audit_quality(blocking: int, conflicts: int, facts: int) -> dict[str, Any]:
    issues = []
    if blocking:
        issues.append(f"{blocking} required field(s) could not be read.")
    if conflicts:
        issues.append(f"{conflicts} value(s) disagree inside the report.")
    if facts == 0:
        issues.append("No facts were read.")
    score = 0 if facts == 0 else max(0, 100 - 10 * blocking - 5 * conflicts)
    return {
        "score": score,
        "parts": {"facts": facts, "blocking": blocking, "conflicts": conflicts},
        "issues": issues,
    }


# ------------------------------------------------------------------ collection analysis


def _quartiles(vals: list[Decimal]) -> tuple[Decimal, Decimal, Decimal]:
    s = sorted(vals)

    def q(p: float) -> Decimal:
        if len(s) == 1:
            return s[0]
        pos = (len(s) - 1) * p
        lo = int(pos)
        hi = min(lo + 1, len(s) - 1)
        return s[lo] + (s[hi] - s[lo]) * Decimal(str(pos - lo))

    return q(0.25), q(0.5), q(0.75)


def mad_outliers(values: list[Decimal]) -> list[bool]:
    """True for each value whose modified z-score is above 3.5. Too few values: nothing flagged."""
    if len(values) < MIN_FOR_OUTLIERS:
        return [False] * len(values)
    med = Decimal(str(median(values)))
    mad = Decimal(str(median([abs(v - med) for v in values])))
    if mad == 0:
        return [v != med for v in values] if len(set(values)) > 1 else [False] * len(values)
    return [abs(Decimal("0.6745") * (v - med) / mad) > Decimal(str(MAD_Z)) for v in values]


def analyse_lines(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarise historical BOQ lines by (gap type, line role).

    Each row needs `gap_type`, `line_role`, `qty`, `unit_price`, `customer`, `quote_ref`,
    `component`. Returns label counts, bands and the rows flagged as outliers."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[(r.get("gap_type") or "other", r.get("line_role") or "product")].append(r)

    bands = []
    outliers = []
    for (gap, role), rs in sorted(groups.items()):
        prices = [(r, p) for r in rs if (p := _dec(r.get("unit_price"))) is not None]
        qtys = [int(r["qty"]) for r in rs if isinstance(r.get("qty"), int)]
        band: dict[str, Any] = {
            "gap_type": gap,
            "line_role": role,
            "lines": len(rs),
            "customers": len({r.get("customer") for r in rs if r.get("customer")}),
            "quotes": len({r.get("quote_ref") for r in rs if r.get("quote_ref")}),
            "typical_qty": int(median(qtys)) if qtys else None,
            "price_p25": None,
            "price_median": None,
            "price_p75": None,
        }
        if prices:
            p25, p50, p75 = _quartiles([p for _, p in prices])
            band.update(
                price_p25=str(p25.quantize(Decimal("0.01"))),
                price_median=str(p50.quantize(Decimal("0.01"))),
                price_p75=str(p75.quantize(Decimal("0.01"))),
            )
            for (r, p), flag in zip(prices, mad_outliers([p for _, p in prices]), strict=True):
                if flag:
                    outliers.append(
                        {
                            "gap_type": gap,
                            "line_role": role,
                            "component": r.get("component"),
                            "quote_ref": r.get("quote_ref"),
                            "field": "unit_price",
                            "value": str(p),
                            "median": band["price_median"],
                        }
                    )
        band["enough_for_outliers"] = len(prices) >= MIN_FOR_OUTLIERS
        bands.append(band)

    label_counts = Counter(r.get("gap_type") or "other" for r in rows)
    return {
        "lines": len(rows),
        "labels": dict(sorted(label_counts.items())),
        "unlabelled_share": _share(label_counts.get("other", 0), len(rows)),
        "bands": bands,
        "outliers": outliers,
    }
