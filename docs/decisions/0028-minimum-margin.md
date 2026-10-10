# ADR 0028: A minimum margin, accepted line by line

Status: accepted
Date: 2026-10-08
Decided by: Aditya Kumar

## Context

Sales may lower a selling price to win a quote. Nothing stopped a line going out below cost or
at a margin the company does not accept, and nobody had to say why. No minimum margin was given
for the company.

## Decision

1. Company settings hold a minimum margin on the selling price, `min_margin_pct`. The default is
   **10 percent**. The Director can change it on the Company settings page; the change is in
   the audit log.
2. The BOQ editor marks every line under the minimum.
3. Whoever approves the pricing (the Sales head or the Director, never the person who drafted
   or edited the BOQ) must accept each low-margin line one by one and give a reason. Approval is
   refused until every such line is accepted (`low_margin_ack_required`) and a reason is given
   (`low_margin_reason_required`).
4. The accepted lines and the reason are written to the BOQ's history with the approval.

## Consequences

- A low-margin quote can still go out, but only with a named person's reason on record.
- The 10 percent default is a guess. It is on the open list in TASKS.md for the Director to
  confirm.
