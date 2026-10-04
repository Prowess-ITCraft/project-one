# Phase 6: BOQ and recommendation engine

Window: 26 Oct to 6 Nov 2026 (planned). Status: built.

## Goal

Draft a complete BOQ from the locked gap register in minutes, let the Director shape it
freely, and render it as the ITCraft quotation in PDF and Excel. Automation of the BOQ is
the main goal. Prices stay manual.

## Features added

- **Templates.** Each gap type maps to BOQ lines with a quantity rule: fixed, per fact, per
  gap, per site, or a safe arithmetic expression.
- **Recommender.** For each line that needs a product, candidates from the catalogue are
  filtered (brand rules, end of life, stock) and scored, with the reasons shown. Where
  several good products exist they become numbered alternatives (5A, 5B), never added
  together.
- **Prices by hand.** The price book is the only automatic source. A missing or expired
  price is a blocker. Anyone with BOQ edit rights can type a price, but must say where it
  came from. Past BOQs may show a hint, which never fills a price on its own.
- **Director editing.** Add a line from the catalogue or by hand, edit anything, delete,
  reorder, add and rename sections, choose alternatives. Changes are queued and saved with
  one reason. A `draft_rev` check stops two people overwriting each other.
- **Totals as ranges.** While alternatives are open, the total is a low to high range.
- **Pricing review.** Submit, then a sales head or the Director approves pricing. The
  approver cannot have edited or submitted the draft.
- **Versions.** Issuing creates an immutable version with a change summary and a quote
  reference per financial year. Acceptance needs the customer PO and the chosen
  alternatives, and locks the BOQ as the gate output. A locked BOQ can be reopened as a new
  draft with a reason.
- **Documents.** Quotation as HTML, PDF (WeasyPrint) and Excel, plus a summary BOQ. Totals
  and GST rows are off by default, matching the sample, and can be turned on per quote.
- **Privacy.** Field engineers never see prices. The accepted BOQ handed to planning has
  quantities only.

## Endpoints

`/projects/{id}/boq`, `/boq/{id}/edit`, `/refresh-prices`, `/submit`, `/pricing-decision`,
`/issue`, `/versions/{n}/accept`, `/reopen`, `/render`, `/lines/{id}/history`. See the
[API guide](../guides/04-api-guide.md).

## Web app

Project page, **BOQ** tab: sticky summary bar, blockers and warnings, inline quantity and
price cells, line drawer, catalogue drawer, settings and terms, versions, acceptance form
and edit history.

## Known limits

- PDF rendering needs the Linux libraries in the container. On Windows outside Docker the
  API answers 503 `pdf_unavailable` and HTML and Excel still work.
- The learned recommendations arrive in phase 13. Until then the recommender is rule based.

## Demo script

1. Lock the gap register, open the BOQ tab and draft the BOQ.
2. Enter prices the price book lacks, with a source.
3. Submit, approve as another person, issue, open the PDF.
4. Record the PO and accept. The stage output is now locked.
