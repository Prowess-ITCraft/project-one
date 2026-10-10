"""Phase 13 models without the database: BOQ line prediction learns which lines follow from
which findings, deterministically; the price rule flags prices that break their history; the
drift model learns the price book; model cards say what a model must never be used for."""

from __future__ import annotations

import random

import pytest

from app.modules.ml import cards, drift, lines

GAPS = ["conflicting_av", "no_eps", "unmanaged_switch", "nas_full", "no_dr", "old_office"]
LINE_FOR = {
    "conflicting_av": "sanitization",
    "no_eps": "eps.xdr",
    "unmanaged_switch": "switch.managed",
    "nas_full": "nas.backup",
    "no_dr": "dr.odr",
    "old_office": "title:office upgrade",
}


def _examples(n: int, seed: int = 7) -> list[lines.LineExample]:
    rng = random.Random(seed)
    out = []
    for i in range(n):
        found = {g: rng.randint(1, 30) for g in GAPS if rng.random() < 0.5} or {"no_eps": 5}
        bought = frozenset(LINE_FOR[g] for g in found)
        drafted = frozenset(list(bought)[:-1]) if len(bought) > 1 else bought
        out.append(lines.LineExample(f"boq-{i}", lines.featurise(found), bought, drafted))
    return out


def test_line_labels_are_template_keys_or_titles() -> None:
    assert lines.label_of({"template_key": "eps.xdr", "title": "Acronis XDR"}) == "eps.xdr"
    assert lines.label_of({"title": "  Office   Upgrade "}) == "title:office upgrade"
    assert lines.featurise({"no_eps": 27, "bad": "x", "zero": 0}) == {"no_eps": 3.332205}


def test_line_model_learns_findings_to_lines_and_beats_drafts_missing_a_line() -> None:
    model = lines.train(_examples(60))
    assert model.artifact["algo"] == "logreg"
    assert model.metrics["model"]["f1"] > 0.9
    assert model.metrics["model"]["recall"] > model.metrics["rules"]["recall"]
    probs = lines.probabilities(model.artifact, lines.featurise({"no_eps": 20, "no_dr": 1}))
    assert probs["eps.xdr"] > 0.5 and probs["dr.odr"] > 0.5 and probs["sanitization"] < 0.5
    # the same training set always gives the same model
    assert lines.train(_examples(60)).artifact == model.artifact


def test_line_model_switches_to_lightgbm_with_more_data() -> None:
    model = lines.train(_examples(lines.LIGHTGBM_FROM + 100, seed=11))  # 4 in 5 train
    assert model.artifact["algo"] == "lightgbm"
    spec = next(s for s in model.artifact["labels"].values() if s["type"] == "lgbm")
    assert spec["model"].startswith("tree")  # LightGBM's own text format, no pickle
    got = lines.predict(model.artifact, lines.featurise({"unmanaged_switch": 3}))
    assert "switch.managed" in got and "nas.backup" not in got


def test_line_model_refuses_thin_data_with_the_count() -> None:
    with pytest.raises(lines.NotEnoughData, match="this training set has 5"):
        lines.train(_examples(5))


def test_the_price_rule() -> None:
    assert drift.rule_check([], 100).flag is False  # nothing to compare with
    v = drift.rule_check([1000.0], 1400.0)
    assert v.flag and v.change_pct == 40.0 and "last price" in (v.reason or "")
    assert drift.rule_check([1000.0, 1010.0], 1100.0).flag is False
    steady = [1000.0, 1010.0, 990.0, 1005.0, 995.0]
    assert drift.rule_check(steady, 1020.0).flag is False
    jump = drift.rule_check(steady, 1500.0)
    assert jump.flag and jump.change_pct is not None and jump.change_pct > 40
    assert "5 earlier quotes" in (jump.reason or "")
    assert drift.rule_check(steady, 600.0).flag  # a drop is flagged too
    # a perfectly flat history still tolerates a small move
    assert drift.rule_check([500.0, 500.0, 500.0], 520.0).flag is False


def test_the_drift_model_learns_the_price_book() -> None:
    rng = random.Random(5)
    rows = []
    for i in range(30):
        base = rng.choice([500, 12000, 66000])
        for _ in range(5):
            rows.append(
                {
                    "item_id": f"item-{i}",
                    "category": "firewall" if base > 50000 else "service",
                    "item_kind": "product" if base > 50000 else "service",
                    "vendor": f"v{i % 4}",
                    "selling": base * rng.uniform(0.97, 1.03),
                    "quoted_on": "2026-09-01",
                }
            )
    with pytest.raises(drift.NotEnoughData):
        drift.train(rows[:50])
    model = drift.train(rows)
    assert model.metrics["mean_abs_error_pct"] < 10
    normal = dict(rows[0])
    expected, flag = drift.model_check(model.artifact, normal)
    price = float(normal["selling"])
    assert not flag and abs(expected - price) / price < 0.15
    odd = {**rows[0], "selling": rows[0]["selling"] * 3}
    assert drift.model_check(model.artifact, odd)[1] is True


def test_model_cards_say_what_a_model_is_never_for() -> None:
    card = cards.build(
        kind="boq_lines",
        number=3,
        training_set={"number": 2, "frozen_at": "2026-10-08", "data_card": {"rows": 40}},
        metrics={"model": {"f1": 0.9}, "judged_on_training_data": True},
        trained_by="Satish Agadi",
    )
    assert any("certificate" in x.lower() for x in card["never_used_for"])
    assert card["reproducibility"]["random_state"] == 0
    md = cards.markdown(card)
    assert md.startswith("# Model card: boq_lines #3") and "Never used for" in md
    assert "scores are on the training data" in md
    assert "—" not in md  # no em dashes in generated documents
