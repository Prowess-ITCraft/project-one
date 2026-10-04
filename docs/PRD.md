# Product requirements (PRD)

Project One turns a **PrismSuite IT audit** into a **verified, certified implementation** for
ITCraft / IITPL (Prowess IT Craft Pvt Ltd). It replaces spreadsheets, hand-built quotations and
phone-call field updates with one gated flow that ends in a "Certified by IITPL" certificate.

Owner: Aditya Kumar. Scope comes from the Product Flow and Proposed Scope draft of
30 September 2026 and the decisions recorded in `decisions/`.

## 1. Boundary

PrismSuite is a separate tool the company already owns. Project One never audits anything. A
person uploads the report PrismSuite produced (and later the rescan report), and Project One does
everything after that: gaps, BOQ, plan, field work, verification, completion report and
certificate.

## 2. Users and roles

Ten roles. One person may hold several, but **the person who does a piece of work can never
verify or approve it** (enforced in code).

| Role | What they do |
| --- | --- |
| Audit engineer | Uploads and imports PrismSuite reports, reviews what was read |
| Solution architect | Approves audits, edits catalogue and rules, shapes the BOQ |
| Technical lead / verifier | Approves gates, reviews field work against target config |
| Sales / BD manager | Customers, projects, enters prices, edits BOQs |
| Sales head | Approves pricing, issues quotes |
| Project manager | Plan, schedule, engineers, field work oversight |
| Field engineer | Does the work on site. Never sees prices |
| Director | Approves gates, waivers and the certificate. MFA required |
| Customer representative | Reads own projects, gives OTPs, signs off |
| Admin | Users, settings, master data. MFA required. No prices |

## 3. The eight stages

Each stage ends with a named approval gate. The next stage cannot open until the gate is
recorded. Approved outputs are locked versions; a change creates a new version.

| # | Stage | Input | Activity | Output | Responsible | Approval |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Audit intake | PrismSuite report (.docx or JSON), intake questionnaire | Parse, review unread fields | Approved audit snapshot | Audit engineer | Solution architect |
| 2 | Current infra | Approved snapshot | Baseline per component, four lenses | Current-state model | Solution architect | Technical lead |
| 3 | Ideal infra | Rule library, questionnaire | Apply tier rules | Target model | Solution architect | Technical lead (rule changes: Director) |
| 4 | Gap analysis | Current vs ideal | Gap register with priority, lens, assets | Locked gap register | Solution architect | Technical lead |
| 5 | BOQ | Gap register, price book, history | Draft, edit, price, issue, accept with PO | Accepted BOQ version | Sales | Sales head, customer PO |
| 6 | Plan | Accepted BOQ | Tasks, dependencies, schedule, baselines | Baselined plan | Project manager | Technical lead, customer dates |
| 7 | Field work | Baselined plan | Gated checklist per task, evidence, OTP | Closed tasks | Field engineer | Verifier (not the doer) |
| 8 | Completion | Closed tasks, rescan | Report and certificate | Certificate | Project manager | Director |

The four reporting lenses everywhere: **Productivity, Resilience, Security, Health**.

## 4. Functional requirements

| FR | Requirement | Phase | State |
| --- | --- | --- | --- |
| 01 | Import a PrismSuite report (.docx now, JSON adapter ready) with versioned parsers that report what they could not read | 3 | Built |
| 02 | Current state per component and endpoint, with PrismSuite scores | 3, 5 | Built |
| 03 | Ideal-infra rule library; Admin edits, Director approves changes | 5 | Built |
| 04 | Gap register with ID, priority, lens, affected assets, recommendation | 5 | Built |
| 05 | BOQ from approved gaps: templates, quantity rules, options, priority groups, price book | 6 | Built |
| 06 | Version every BOQ, block on expired prices, lock the accepted version with a PO | 6 | Built |
| 07 | Quotation and summary BOQ in the exact ITCraft format, PDF (WeasyPrint) and Excel | 6 | Built |
| 08 | Recommendations with reasons and runner-ups, same contract for rules and learned ranker | 6, 13 | Rules built |
| 09 | Tasks, dependencies and schedule from the accepted BOQ, around leave and downtime windows | 7 | Built, with plan PDF |
| 10 | Target configuration baseline per device | 7 | Built |
| 11 | Gated task state machine, mandatory evidence, customer OTP at check-in and handover | 8 | Built |
| 12 | Customer and Director notified at every task transition | 8 | Built |
| 13 | Compare actual to target configuration, raise deviations with severity | 9 | Built (SonicWall exports first) |
| 14 | Director live dashboard | 9, 12 | Built |
| 15 | Block report and certificate until every release condition is met; waivers | 10 | Built |
| 16 | Completion report and certificate with unique ID and QR verification | 10 | Built; real IITPL stamp still to come |
| 17 | **Library**: old BOQs and PrismSuite reports dropped in are read automatically and become datasets | 4 | Built |
| 18 | **Document corpus**: every incoming PDF, DOCX or XLSX is converted once into a compact canonical JSON record (structure plus plain text, gzipped). The app, analysis and ML read the JSON, never the heavy original | 4+ | Built |
| 19 | **Data quality**: cleaning (name normalisation, de-duplication, unit and money parsing), validation, outlier flags on prices and quantities, a quality score per file and per collection, and a labelled taxonomy that maps each BOQ line to a gap type | 4+ | Built |
| 20 | **Training snapshots**: frozen, versioned, reproducible dataset snapshots with a data card, ready for Phase 13 | 4, 13 | Built |
| 21 | The sample files in `samples/` are always part of the corpus and of every test run | 4 | Built |

## 5. Non-functional requirements

| Requirement | Target |
| --- | --- |
| Security | RBAC plus object checks, deny by default, MFA for Director and Admin, append-only audit log, envelope encryption for device credentials and config exports |
| Field use | Works on a 360 px phone with poor signal; evidence queues offline up to 72 hours |
| Documents | Every PDF is made by WeasyPrint through one shared service |
| Data cost | Originals are converted once and archived; the hot path and the training data use compact JSON and Parquet (FR 18) |
| Money | `Decimal`, `NUMERIC(14,2)`, INR, Indian grouping, GST per line, Apr to Mar financial year |
| Time | UTC stored, IST shown |
| Licensing | Free and open-source components only (ADR 0011) |
| Operability | `/healthz`, `/readyz`, `/metrics`, nightly backups with a tested restore |
| Writing | Plain English, sentence case, no em dashes in docs, UI copy or generated documents |

## 6. Scope

**In:** the eight stages above, master data (catalogue and price book, rule library, BOQ
templates, config templates, checklist templates), the library and document corpus, the web app,
email notifications (SMS and WhatsApp behind adapters).

**Changed from the first draft (ADR 0012):** audit imports have a kind (baseline or rescan); an
intake questionnaire drives the tier and recommender; acceptance needs a customer PO; a gate can
return to an earlier stage with a reason; waivers are Not applicable or Deferred by customer.

**Out for v1:** a customer self-service portal (beyond OTPs and acknowledgement links), live
device APIs (verification uses uploaded config exports), scraping of market data, a general
pivot and chart workspace (the engine stays API-only).

## 7. Open questions

Where nobody had decided yet, we picked the safest default and wrote it down as an ADR in
`decisions/` (summary table in `NOTES.md`). Anything touching money, certification or security
stays on the open list in `TASKS.md` until someone signs it off.
