# ADR 0024: One step from a PrismSuite report to a BOQ estimate

Status: accepted
Date: 2026-10-05
Decided by: Aditya Kumar

## Context

The main reason for Project One is a BOQ drafted from a PrismSuite audit report. The pieces
were there (upload on Audit intake, the Questionnaire, Draft BOQ estimate on the BOQ tab, ADR
0021), but they were spread over three tabs, and no role could do all three: sales could not
import a report, and audit engineers could not save the questionnaire or draft the estimate.

## Decision

1. The project Overview has an **Upload report and draft BOQ** button while the project is
   before the BOQ stage. It uploads and reads the report, saves the few answers the rules need
   (company size, budget tier, sites, users now and in 12 months) and drafts the estimate.
   Leaving the file empty reuses the report already imported; the same file again is not
   imported twice (`already_imported`) and the estimate carries on.
2. Two narrow permissions: `boq:estimate` (draft the estimate, held by everyone with
   `boq:edit` and by audit engineers) and `brief:write` (save the questionnaire, held by
   everyone with `project:write` and by audit engineers).
3. Sales manager, Sales head and Director may import a PrismSuite report
   (`prismsuite:import`). Reviewing and approving the import stays with the audit side.
4. Audit engineers get `price:read` (cost, selling price and margin) and `infra:read`, which
   the estimate needs.
5. Prices stay manual: they come only from the price book, entered by hand in the Catalogue,
   with an expiry date. Lines without a price are left blank and listed.

## Consequences

- Nothing about the approvals changes. The estimate is saved nowhere and marked "ESTIMATE,
  NOT APPROVED"; the official BOQ still comes from the approved gap register.
- Audit engineers can now see cost prices and margins.
