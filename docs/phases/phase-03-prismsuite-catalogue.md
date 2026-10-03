# Phase 3: PrismSuite ingestion, catalogue and price book

Window: 5 to 9 Oct 2026 (mock plan). Status: built.

## Goal

Turn a PrismSuite Word report into clean, reviewed data the rest of the system can trust,
and hold the products, services and prices that later become a BOQ.

## Features added

**PrismSuite ingestion**

- A parser for the PrismSuite Word report (`PrismSuiteParserV1`) that produces a neutral
  `AuditSnapshot`. New report layouts or a future PrismSuite JSON export are added as new
  parsers without touching anything downstream.
- What it reads from the Shakti sample (`PS-10092026-SHA`): customer, report reference,
  audit date and auditor; the five headline scores (security 58.7, high availability 50,
  system health 74.2, performance 60.3, IT structure 66.7) and per-component scores; asset
  counts (27 endpoints: 4 laptops, 23 desktops, 1 server, 1 firewall, 1 backup device, 2
  switches, 2 routers); devices such as SonicWall TZ 270, Synology DS218+ at 100% used, and
  the unmanaged D-Link switch; server hardening score 3.83 of 10; 45 vulnerabilities;
  upgrade needs (3 systems at 4 GB RAM, 2 on Office 2013, 6 with two antivirus agents);
  the report's recommendations.
- A **field-by-field read report**: each field is ok, missing, unreadable, in conflict, or
  corrected by a person. Nothing fails silently. The sample shows one real conflict (the
  report says both that firewall HA is configured and that it is not).
- Human review: reviewers correct a value with a reason, or confirm a conflicting field.
  The original parse is kept untouched next to the working copy, and every correction is
  recorded.
- Approval rules: blocked while required fields are unreadable or conflicts remain; the
  importer and anyone who corrected a value cannot approve. Approval locks the audit for the
  Audit intake gate and announces it to other modules.
- The same report cannot be imported twice; a rejected one can be re-imported as a new
  revision.

**Catalogue**

- Products and services with vendor, category, description, bullet inclusions (as printed
  on a quotation), unit, GST rate per item (default 18%), technical attributes, and end of
  life and end of support dates.
- Stock status with a listed alternative that the BOQ engine will swap in when an item is
  out of stock.
- Manually entered market data (ratings, analyst tier, India support) with source and date;
  newest value is current, older values are history.
- Vendors and 15 categories. Soft delete and optimistic locking.

**Price book**

- Every price records supplier, cost, selling price, date quoted, valid-until date, source
  note and who entered it. Margin is calculated.
- Append-only history: a new price replaces the active one, and the old one stays. Database
  triggers stop anyone editing or deleting price history.
- Rules: selling price cannot be below cost; no future quote dates; already-expired prices
  are refused; validity up to one year.
- A nightly job marks expired prices. Independently, a price is treated as unusable from its
  first expired day even if the job has not run.
- A work list of items with missing, expired or soon-to-expire prices.
- Only Sales manager and Sales head enter prices. Field engineers can read the catalogue but
  never see any price field, and the tests prove it.

**Seed data**

- 14 items from the two Shobhaglobs sample BOQs: sanitization, Acronis XDR, EPS setup,
  Cisco C1300 switch and setup, Sophos XGS-108, FortiGate FG40F, firewall setup and support,
  plus the unpriced summary items (server, NAS, Phoenix ODR, DLP, firewall
  reconfiguration). Prices carry the quote's own 5 day validity, so they show up for
  refresh quickly, which is intended.

## Acceptance criteria

| Criterion | State |
| --- | --- |
| Parser extracts every count and score in the brief from the sample | Done, checked by automated tests |
| Fuzz tests do not crash the parser | Done: random bytes, random byte flips and truncation of the sample |
| Expired prices flagged by a scheduled job | Done and tested with simulated dates |
| Upload pipeline with ClamAV, sniffing and MinIO | Done (Phase 2 files module) |

## Numbers

- 16 parser tests, 11 import flow tests, 11 catalogue tests.
- 7 prismsuite endpoints, 16 catalogue endpoints.

## Decisions

ADR 0001 (sanitization quantity), 0002 (two validity concepts), 0009 (price book rules),
0010 (review and approval rules).

## Known limitations

- Only one report layout version exists; the parser has been tested on one real report.
  More samples will reveal more variation.
- Seed costs equal selling prices because the quotations show only selling prices.
- Only 10 of the 45 vulnerabilities are listed in the sample report body; the total of 45
  is captured.
- There is no JSON adapter yet; the interface is ready for one.

## Demo script

1. Upload the Shakti `.docx`, import it, open the read report.
2. Confirm the firewall HA conflict, approve as a different person.
3. Open the price book work list and refresh a price.
4. Sign in as a field engineer and show the catalogue has no prices.
