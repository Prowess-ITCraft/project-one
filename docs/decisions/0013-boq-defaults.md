# 0013: BOQ defaults

Status: accepted (chosen by the builder under "assume the best answers possible"). The Director can change any of these.

## Decisions

1. **Totals and GST rows are off by default** on the quotation, because the ITCraft sample
   BOQs print neither. Each quote can switch them on.
2. **Quote numbers** follow the financial year (April to March) and carry the issuer's
   initials, allocated by the `next_value` counter so two people never get the same number.
3. **The pricing approver must not be an editor or the submitter** of that draft. This is the
   same "doer is not verifier" rule used at the gates.
4. **Prices come only from the price book or from a person.** A price typed by hand needs a
   source note. Past BOQs can show a hint and never fill a price.
5. **Alternatives (5A, 5B) are never added together.** Totals show a low to high range until
   the customer chooses.
6. **Blockers** before pricing review: missing price, expired price, zero quantity.
7. **Acceptance needs a purchase order number and every alternative chosen**, then locks the
   BOQ as the stage output. A later change means reopening it as a new draft with a reason.
8. **Field engineers never see prices.** The accepted BOQ passed to planning carries
   quantities only (see ADR 0003).
9. **Sanitization of free text** happens per endpoint at the boundary, before storage.

## Consequences

- Quotes match the sample layout by default.
- A sales person cannot approve their own pricing, so a small team needs two sales roles.
