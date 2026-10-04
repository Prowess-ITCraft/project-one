# ADR 0020: A learned ranker that only runs in shadow mode

Status: accepted
Date: 2026-10-04
Decided by: Aditya Kumar

## Context

Phase 13 asks for learned BOQ ranking next to the rules. The data we have is thin: one PrismSuite
audit, two old BOQs, and a handful of BOQs drafted in the system. A model that recommends
products to customers changes what we quote, so it touches money, and it must earn trust before
it is used. ADR 0012 already said learning should come from the library and from real decisions,
and RULES 2.6 says models train only on frozen, versioned data with a data card.

## Decision

1. **Learn the weights, keep the criteria.** The rule engine scores each candidate on eight
   explainable criteria (need fit, budget, three-year cost, market standing, support life,
   preferred vendor, stock, past use) with fixed weights. The learned ranker keeps those criteria
   and learns only how much each one matters, from what customers accepted. Weights stay
   non-negative and sum to 1, so they read like the rule weights and every suggestion can still
   be explained.
2. **The label is the customer's decision.** While a BOQ is drafted, every ranked candidate and
   its criteria are kept (`boq.recommended`). When the customer accepts a version, each candidate
   is labelled kept or not kept (`boq.accepted` now carries the accepted item ids). A group only
   teaches something if it has at least one kept and one not-kept candidate.
3. **Model.** Pairwise logistic regression (Bradley-Terry) on kept versus not-kept pairs, with a
   small L2 penalty, in plain Python. Eight features and hundreds of pairs need no library, and
   nothing new has to be licensed or installed (ADR 0011). MLflow is not needed at this size;
   models, metrics and their training set live in the database.
4. **Frozen training sets.** Labelled examples are frozen into numbered training sets with a data
   card; a database trigger stops any change. A model records which set it learned from.
5. **Too little data is refused.** Training needs at least 20 usable groups and says how many it
   has. One in five groups is held back (by a stable hash) to report how often each ranker picked
   what the customer took; with fewer than three held back, the report says it judged on the
   training data.
6. **Shadow mode only.** At most one model runs in shadow mode. It ranks the same candidates as
   the rules whenever a BOQ is drafted, and the agreement goes to the Learning page. It never
   changes a BOQ. Letting a model influence real quotations needs a new ADR and the Director's
   sign-off, with the agreement report as evidence.
7. **Coupling.** The `ml` module and `boq` talk only through outbox events; neither imports the
   other's code.

## Consequences

- Until roughly 20 accepted, recommender-drafted BOQs exist, the Learning page shows progress
  and no model. That is expected and stated on the page.
- Old BOQs in the library still feed the "used in past BOQs" criterion, but they cannot be labels:
  we do not know which alternatives were offered and rejected.
- If the criteria change (a new one is added), old training sets stay valid; missing criteria
  count as neutral (0.5), as in the rule engine.
