"""Model cards: what a model is for, what it learned from, how well it did, and what it must
never be used for. Written when a model is trained and kept with it."""

from __future__ import annotations

import platform
from importlib.metadata import PackageNotFoundError, version
from typing import Any

PURPOSE = {
    "ranker": "Learns how much each recommendation criterion matters from the products "
    "customers accepted, to compare with the fixed rule weights.",
    "boq_lines": "Predicts which BOQ lines a set of audit findings leads to, to compare with the "
    "lines the BOQ templates draft.",
    "price_drift": "Predicts a catalogue item's price from the price book history, to point out "
    "a new price that does not fit.",
}
NEVER = [
    "Verification verdicts, deviations or their severity",
    "Waivers, the completion report or certificate conditions",
    "Issuing, approving or pricing a quote without a person",
    "Anything about a field engineer's work or pay",
]


def _lib(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "not installed"


def build(
    *,
    kind: str,
    number: int,
    training_set: dict[str, Any],
    metrics: dict[str, Any],
    trained_by: str,
) -> dict[str, Any]:
    return {
        "model": f"{kind} #{number}",
        "kind": kind,
        "purpose": PURPOSE[kind],
        "status_rule": "Runs in shadow mode first. Only the Director can approve it, after at "
        "least 30 days and 20 comparisons in shadow mode. Even approved, it only advises a "
        "person; it never changes a BOQ, a price or a verdict by itself (ADR 0020, 0029).",
        "never_used_for": NEVER,
        "training_data": {
            "training_set": training_set.get("number"),
            "frozen_at": training_set.get("frozen_at"),
            "data_card": training_set.get("data_card", {}),
        },
        "metrics": metrics,
        "limitations": _limits(kind, metrics),
        "reproducibility": {
            "python": platform.python_version(),
            "scikit-learn": _lib("scikit-learn"),
            "lightgbm": _lib("lightgbm"),
            "random_state": 0,
            "note": "Training the same training set again gives the same model.",
        },
        "personal_data": "None. Gap types, line names, catalogue categories and prices only.",
        "trained_by": trained_by,
    }


def _limits(kind: str, metrics: dict[str, Any]) -> list[str]:
    out = []
    if metrics.get("judged_on_training_data"):
        out.append("Too few examples to hold some back, so the scores are on the training data.")
    if kind == "boq_lines":
        out.append("Lines seen in only one accepted BOQ are not learned.")
        out.append("It knows the gap types and counts, not the customer's budget or brands.")
    if kind == "price_drift":
        out.append("A new item has no history; the prediction falls back to its category.")
    if kind == "ranker":
        out.append("Learns weights for the existing criteria only; it cannot add a criterion.")
    return out


def markdown(card: dict[str, Any]) -> str:
    lines = [f"# Model card: {card['model']}", "", card["purpose"], "", "## Use"]
    lines.append(card["status_rule"])
    lines += ["", "## Never used for"] + [f"- {x}" for x in card["never_used_for"]]
    td = card["training_data"]
    lines += ["", "## Training data", f"- Training set {td.get('training_set')}"]
    for k, v in (td.get("data_card") or {}).items():
        if isinstance(v, str | int | float):
            lines.append(f"- {k.replace('_', ' ')}: {v}")
    lines += ["", "## Results"]
    for k, v in card["metrics"].items():
        lines.append(f"- {k.replace('_', ' ')}: {v}")
    lines += ["", "## Limitations"] + [f"- {x}" for x in card["limitations"]]
    rep = card["reproducibility"]
    lines += [
        "",
        "## Reproducibility",
        f"- Python {rep['python']}, scikit-learn {rep['scikit-learn']}, LightGBM {rep['lightgbm']}",
        f"- {rep['note']}",
        "",
        f"Personal data: {card['personal_data']}",
        "",
    ]
    return "\n".join(lines)
