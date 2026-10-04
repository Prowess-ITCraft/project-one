# Phase 13: Learning from accepted BOQs

Window: 14 to 21 Dec 2026 (planned). Status: built (4 Oct 2026). Waiting on data: a model needs
about 20 accepted BOQs that the recommender helped draft.

## Goal

Let the recommender learn from what customers actually accept, without letting an unproven model
change a single quotation.

## How it works (ADR 0020)

```
BOQ drafted  -> every ranked candidate kept with its eight criteria   (boq.recommended)
BOQ accepted -> each candidate labelled kept or not kept               (boq.accepted)
Freeze       -> numbered training set + data card, never changed
Train        -> learned criteria weights, refused when data is thin
Shadow       -> ranks next to the rules on every new draft; agreement on the Learning page
```

## Features added

- New `ml` module: examples, frozen training sets (database trigger), models, shadow runs.
- Pairwise ranker in plain Python: learns how much each existing criterion mattered. Weights are
  non-negative and sum to 1, so they compare directly with the rule weights.
- Stable holdout (one group in five) and three numbers per model: how often the rules picked
  what the customer took, how often the model did, and pairwise accuracy.
- API under `/ml`: report, training sets (list, freeze), models (list, train, shadow, retire).
- **Learning page** (Director, Admin; Sales head and Solution architect can read): progress
  towards the first model, training sets, models with their weights next to the rule weights,
  and where the shadow model disagrees with the rules.

## Acceptance

| Criterion | State |
| --- | --- |
| Trains only on frozen, versioned data with a data card | Done, tested; the database refuses changes to a set |
| Learned ranker behind the recommender contract | Done: same criteria, learned weights |
| Shadow mode never changes a BOQ | Done, tested |
| Agreement report | Done: agreement rate, top-1 for rules and model, disagreements |
| Honest with thin data | Done: training refused with the count below 20 groups |

## Decisions

ADR 0012 (learn from the library and real decisions), ADR 0020 (this design).

## Known limitations

- No model can be trained yet; there are too few accepted BOQs.
- Old library BOQs cannot be labels (the rejected alternatives are unknown); they still feed the
  "used in past BOQs" criterion.
- Moving a model out of shadow mode is deliberately not built. It needs a new ADR and the
  Director's sign-off.

## Demo script

1. Sign in as the Director and open **Learning**: the progress bar shows how many accepted
   recommendations exist out of the 20 needed.
2. Accept a BOQ where the customer chose option B of a firewall pair, then refresh: the count
   goes up.
3. **Freeze a new training set** and open its data card. **Train** stays disabled with the
   reason until there is enough data.
