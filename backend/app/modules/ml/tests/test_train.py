"""The pairwise ranker on its own: it learns what decided past choices, stays readable, and
refuses to pretend when there is too little data."""

from __future__ import annotations

import random

import pytest

from app.modules.ml import train as t


def _criteria(rng: random.Random, vendor: float) -> dict[str, float]:
    c = {k: round(rng.uniform(0.3, 0.9), 2) for k in t.FEATURES}
    c["vendor"] = vendor
    return c


def _history(groups: int, seed: int = 7) -> list[t.Example]:
    """Customers always kept the preferred vendor, whatever the other criteria said. The rule
    score is built to prefer the cheaper option, so the rules are often wrong here."""
    rng = random.Random(seed)
    out = []
    for g in range(groups):
        kept = _criteria(rng, vendor=1.0)
        other = _criteria(rng, vendor=0.5)
        kept["tco"], other["tco"] = 0.2, 0.9
        out.append(t.Example(f"g{g}", f"a{g}", kept, rule_score=0.4, kept=True))
        out.append(t.Example(f"g{g}", f"b{g}", other, rule_score=0.6, kept=False))
    return out


def test_learns_the_criterion_that_decided() -> None:
    result = t.train(_history(40))
    w = result.weights
    assert abs(sum(w.values()) - 1) < 0.01 and all(v >= 0 for v in w.values())
    assert max(w, key=lambda k: w[k]) == "vendor"
    assert w["tco"] < w["vendor"]
    m = result.metrics
    assert m["groups"] == 40 and m["model_top1"] == 1.0 and m["rules_top1"] == 0.0
    assert m["model_pairwise"] == 1.0


def test_same_data_gives_the_same_model() -> None:
    assert t.train(_history(30)).weights == t.train(_history(30)).weights


def test_refuses_with_the_count_when_data_is_thin() -> None:
    with pytest.raises(t.NotEnoughData, match="Only 5 accepted recommendations"):
        t.train(_history(5))


def test_groups_without_a_choice_teach_nothing() -> None:
    ex = [
        t.Example("all-kept", "a", {}, 0.5, True),
        t.Example("all-kept", "b", {}, 0.4, True),
        t.Example("none-kept", "c", {}, 0.5, False),
        t.Example("choice", "d", {}, 0.5, True),
        t.Example("choice", "e", {}, 0.4, False),
    ]
    assert list(t.usable_groups(ex)) == ["choice"]


def test_missing_criteria_count_as_neutral() -> None:
    assert t.vector({"need_fit": 1, "vendor": "high"}) == [1.0] + [t.NEUTRAL] * 7
