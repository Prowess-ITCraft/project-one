# ADR 0029: BOQ line prediction and price checks, in shadow until the Director approves

Status: accepted
Date: 2026-10-08
Decided by: Aditya Kumar

## Context

ADR 0020 put a learned ranker next to the rules in shadow mode. Two more models were planned:
which BOQ lines a set of audit findings leads to, and prices that do not fit their history. The
stack had to stay light, free and open source (ADR 0011), and no model may touch a verdict, a
waiver or a certificate.

## Decision

1. **Light stack.** scikit-learn and LightGBM, trained on frozen training sets only (RULES 2.6).
   Every run is recorded in the database with its data, settings and scores. MLflow is an
   optional compose profile (`mlflow`, port 9606), off by default, used only when
   `P1_MLFLOW_TRACKING_URI` is set. This replaces ADR 0020's "MLflow is not needed"; the
   database stays the record either way.
2. **Three models, one kind each:** the ranker (ADR 0020), BOQ line prediction from audit
   findings, and a price drift check on new price book entries. The price check sees item,
   price and date, never the supplier or the person who entered it.
3. **Model cards.** Each trained model has a card: what it is for, the training set and its data
   card, scores, known limits, and what it must never be used for.
4. **Shadow first.** A new model runs in shadow mode, beside the rules, and its suggestions are
   only compared, never shown as advice. After at least **30 days and 20 comparisons**, the
   Director alone may approve it, with a note. An approved model only advises: a person reviews
   every predicted BOQ line before anything is issued.
5. **One off switch.** The feature flag `ml_enabled` stops examples, training, shadow runs,
   suggestions and price alerts at once, and changes nothing in any other module.
6. **Never in the verdicts.** Verification, deviations, waivers and certificate conditions do not
   read any model output. Import-linter enforces it.

## Consequences

- Nothing can be trained until about 20 accepted BOQs exist; the Learning page says so.
- Shadow runs cost a little work per BOQ draft and per price entry.
- Moving to MLflow for everything later needs no code change beyond the tracking address.
