# ADR 0012: Reconcile the build with the Product Flow and Proposed Scope

Status: accepted
Date: 2026-10-01

## Context

On 1 October 2026 we got the Product Flow and Proposed Scope (draft of 30 September) along
with the whiteboard and notebook notes. They confirm the eight stages, ten roles and gates
already built, and add requirements the earlier spec did not stress. They also make clear that
PrismSuite is a separate tool and that old BOQs and reports will be added over time and should
be used as data.

## Decision

1. The PRD's functional requirements table is the traceability page from requirement to phase.
2. **Audit imports get a kind**: `baseline` (before) and `rescan` (after). One approved import
   per project and kind. A JSON adapter (`prismsuite.json.v1`) reads a structured export that
   has the same shape as the internal snapshot.
3. **The library replaces the dataset workspace.** Uploaded old BOQs and reports are read
   automatically into two built-in collections (historical BOQ lines, audit findings), with
   provenance, de-duplication by file hash and a review queue for low-confidence rows. A folder
   can also be watched. The generic engine (steps, EDA, charts) stays as API only.
4. **ML is replaced by learning from the library**: statistics over history (typical quantity
   per gap, option pairs, price ranges, acceptance) shown as suggestions beside the rule engine.
5. **Open questions get safe defaults** (ADRs 0013 and 0017) until someone decides otherwise.
6. Phase order keeps the scope's priority: BOQ engine and gated checklist first.

## Consequences

- Phase 3 gains a small migration (kind column) and a parser.
- Phase 4 is smaller and more useful: the library. Charts and pivots have no screens yet.
- Phase 13 shrinks and moves earlier in value, because suggestions come from data that already
  exists.
- Stage 1 gains an intake questionnaire, stage 5 a purchase order, and every stage a
  return-to-earlier-stage path. These are added in phases 5 and 6.
