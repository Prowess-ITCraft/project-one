# ADR 0021: A BOQ estimate before the approvals

Status: accepted
Date: 2026-10-04
Decided by: Aditya Kumar

## Context

Sales want to talk numbers as soon as the PrismSuite report and the questionnaire are in. The
official BOQ only exists after five stages, each approved by a different person (audit, current
IT, ideal IT, gap analysis). A one-click "upload, then BOQ" would skip those approvals and the
rule that the doer never approves, and a quotation could then go out on an audit nobody checked.

Options considered: an estimate that saves nothing; an "auto-prepare" button that builds and
submits every stage and waits for approvals; or skipping the gates. We chose the estimate.

## Decision

1. **Draft BOQ estimate** button on the Audit intake and Questionnaire tabs (with a checklist of
   what is still missing) and on the BOQ tab while there is no official BOQ.
2. It runs the same code as the official path (`infra.estimate_gaps`, then the shared
   `boq.service._assemble`) entirely in memory, from the approved audit or the newest one still
   in review, the questionnaire and today's price book.
3. Nothing is saved, nothing is published (the learning module does not see it), no gate moves.
4. "Verify on site" items are listed, not priced.
5. It is labelled "Not approved" on screen, and the PDF and Excel carry
   "ESTIMATE, NOT APPROVED" where the quote reference goes.
6. Same permission as editing a BOQ (`boq:edit`).

## Consequences

- The official BOQ, the approvals and the audit trail are unchanged.
- An estimate from an unreviewed report can be wrong where the parser misread something; the
  screen says which audit revision it used and whether it was approved.
