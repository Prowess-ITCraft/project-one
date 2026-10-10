"""Which BOQ lines a set of audit findings leads to (Phase 13, ADR 0029).

Each example is one accepted BOQ: its features are the gap types found in the audit with how
many of each (log scaled), its labels the lines the customer bought. A label is the BOQ
template line key when the line came from a template, otherwise the line title in lower case.

Small data (fewer than 200 examples): one logistic regression per label (scikit-learn). More:
one LightGBM classifier per label. Both are saved as plain data (coefficients, or LightGBM's own
text model), never pickled, so loading a model cannot run code. Training is deterministic for a
given training set.

The rules stay in charge. A model in shadow mode only records what it would have drafted; an
approved model only suggests lines that a person may add.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from typing import Any

MIN_EXAMPLES = 20
MIN_LABEL_COUNT = 2  # a line seen once cannot be learned
LIGHTGBM_FROM = 200
THRESHOLD = 0.5


class NotEnoughData(Exception):
    pass


@dataclass(frozen=True)
class LineExample:
    key: str  # the BOQ id
    features: dict[str, float]
    labels: frozenset[str]
    rule_labels: frozenset[str] = frozenset()


@dataclass
class LineModel:
    artifact: dict[str, Any]
    metrics: dict[str, Any] = field(default_factory=dict)


def label_of(line: dict[str, Any]) -> str:
    """The stable name of a BOQ line: its template line key, or its title."""
    key = line.get("template_key")
    if key:
        return str(key)
    title = re.sub(r"\s+", " ", str(line.get("title", "")).strip().lower())
    return f"title:{title[:80]}"


def featurise(gap_counts: dict[str, Any]) -> dict[str, float]:
    return {
        str(k): round(math.log1p(float(v)), 6)
        for k, v in gap_counts.items()
        if isinstance(v, int | float) and v > 0
    }


def _held_out(key: str) -> bool:
    return int(hashlib.sha256(key.encode()).hexdigest(), 16) % 5 == 0


def _sigmoid(z: float) -> float:
    if z < -60:
        return 0.0
    return 1.0 / (1.0 + math.exp(-z))


def _f1(pred: list[frozenset[str]], truth: list[frozenset[str]]) -> dict[str, float | None]:
    tp = sum(len(p & t) for p, t in zip(pred, truth, strict=True))
    fp = sum(len(p - t) for p, t in zip(pred, truth, strict=True))
    fn = sum(len(t - p) for p, t in zip(pred, truth, strict=True))
    prec = tp / (tp + fp) if tp + fp else None
    rec = tp / (tp + fn) if tp + fn else None
    f1 = 2 * prec * rec / (prec + rec) if prec and rec else (0.0 if tp + fp + fn else None)
    return {"precision": _r(prec), "recall": _r(rec), "f1": _r(f1)}


def _r(v: float | None) -> float | None:
    return round(v, 3) if v is not None else None


def train(examples: list[LineExample]) -> LineModel:
    if len(examples) < MIN_EXAMPLES:
        raise NotEnoughData(
            f"Training needs at least {MIN_EXAMPLES} accepted BOQs drafted from an audit; this "
            f"training set has {len(examples)}."
        )
    held = [e for e in examples if _held_out(e.key)]
    fit = [e for e in examples if not _held_out(e.key)]
    if len(held) < 3:
        held, fit = examples, examples  # too few to hold back; judged on the training data
    features = sorted({f for e in fit for f in e.features})
    counts: dict[str, int] = {}
    for e in fit:
        for lab in e.labels:
            counts[lab] = counts.get(lab, 0) + 1
    labels = sorted(lab for lab, n in counts.items() if n >= MIN_LABEL_COUNT)
    dropped = sorted(lab for lab, n in counts.items() if n < MIN_LABEL_COUNT)
    if not labels:
        raise NotEnoughData("No BOQ line appears in more than one accepted BOQ yet.")
    x = [[e.features.get(f, 0.0) for f in features] for e in fit]
    algo = "lightgbm" if len(fit) >= LIGHTGBM_FROM else "logreg"
    per_label: dict[str, dict[str, Any]] = {}
    for lab in labels:
        y = [1 if lab in e.labels else 0 for e in fit]
        positives = sum(y)
        if positives in (0, len(y)):
            per_label[lab] = {"type": "const", "p": positives / len(y)}
            continue
        if algo == "lightgbm":
            import lightgbm as lgb

            clf = lgb.LGBMClassifier(
                n_estimators=100,
                num_leaves=7,
                min_child_samples=5,
                learning_rate=0.1,
                random_state=0,
                deterministic=True,
                force_row_wise=True,
                verbose=-1,
            )
            clf.fit(x, y)
            per_label[lab] = {"type": "lgbm", "model": clf.booster_.model_to_string()}
        else:
            from sklearn.linear_model import LogisticRegression

            clf = LogisticRegression(
                C=1.0, class_weight="balanced", solver="liblinear", random_state=0
            )
            clf.fit(x, y)
            per_label[lab] = {
                "type": "logreg",
                "coef": [round(float(c), 8) for c in clf.coef_[0]],
                "intercept": round(float(clf.intercept_[0]), 8),
            }
    artifact = {
        "algo": algo,
        "features": features,
        "labels": per_label,
        "threshold": THRESHOLD,
    }
    truth = [e.labels for e in held]
    model_pred = [predict(artifact, e.features) for e in held]
    rule_pred = [e.rule_labels for e in held]
    metrics = {
        "algo": algo,
        "examples": len(examples),
        "trained_on": len(fit),
        "held_out": len(held),
        "judged_on_training_data": held is examples,
        "labels": len(labels),
        "labels_dropped_seen_once": len(dropped),
        "features": len(features),
        "model": _f1(model_pred, truth),
        "rules": _f1(rule_pred, truth),
    }
    return LineModel(artifact, metrics)


def probabilities(artifact: dict[str, Any], features: dict[str, float]) -> dict[str, float]:
    names: list[str] = artifact["features"]
    x = [features.get(f, 0.0) for f in names]
    out: dict[str, float] = {}
    for lab, spec in artifact["labels"].items():
        if spec["type"] == "const":
            p = float(spec["p"])
        elif spec["type"] == "logreg":
            p = _sigmoid(
                sum(c * v for c, v in zip(spec["coef"], x, strict=True)) + spec["intercept"]
            )
        else:
            import lightgbm as lgb

            booster = lgb.Booster(model_str=spec["model"])
            p = float(booster.predict([x])[0])
        out[lab] = round(p, 4)
    return out


def predict(artifact: dict[str, Any], features: dict[str, float]) -> frozenset[str]:
    t = float(artifact.get("threshold", THRESHOLD))
    return frozenset(lab for lab, p in probabilities(artifact, features).items() if p >= t)
