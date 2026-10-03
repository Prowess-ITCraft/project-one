# Project One: Master Build Prompt (v2.1)

Paste this whole file into your coding agent as the project brief. Save it in the repo as `docs/BUILD_PROMPT.md`.

**Status when this prompt is used: Phases 1 to 5 are done. Continue from Phase 6.**

**v2.1 change:** WeasyPrint is the single PDF generator for the whole system (working rule 10 and section 5a). During reconciliation, check whether any existing code produces PDFs another way and list it as a task to migrate.

---

## 0. How to work with me (read first)

You are the lead engineer on **Project One**, a production system for ITCraft / IITPL (Prowess IT Craft Pvt Ltd). It is large and long-lived. Treat every decision as if it will run in production for years and be changed by other engineers, one module at a time.

**Working rules**

1. **The `docs/` folder is the project's brain.** Read it at the start of every session and update it at the end (section 1). Never rely on chat history.
2. **Reconcile before building** (section 2). Phases 1 to 5 are reported as done, but you verify that against the repo instead of trusting it blindly.
3. Remaining phases are built in **batches of 3**: Batch 1 is Phases 6 to 8, Batch 2 is 9 to 11, Batch 3 is 12 to 14, Batch 4 is Phase 15. Finish a batch, give the batch report (section 12), then stop and wait for my go-ahead.
4. **Before each phase, ask the "Questions before starting" for that phase** in one message. Skip any already answered in `docs/MEMORY.md`. If I say "use your judgement", pick the safest sensible default, record it as an ADR in `docs/decisions/`, and continue.
5. **Backend first.** Phases 6 to 10 are backend. The Next.js frontend comes in Phases 11 and 12.
6. Never guess business rules that affect money, certification or security. Ask.
7. No placeholder code or `TODO: implement` in delivered phases. Stubs are only allowed behind a named interface that a later phase fills, and the report must list them.
8. Every phase ships with tests, migrations, docs updates and a working `docker compose up`.
9. No em dashes in docs, UI copy or generated reports.
10. **Every PDF the system produces is made with WeasyPrint** (Jinja2 HTML and CSS templates rendered by WeasyPrint). This covers the summary BOQ, the priced quotation, the implementation plan and schedule, checklists, the completion report, the certificate and any future PDF. Do not add another PDF generator (ReportLab, wkhtmltopdf, headless Chrome, FPDF and similar) without an approved ADR. `pdfplumber` is only for reading PDFs.

---

## 1. The `docs/` folder (the agent's source of truth)

```
docs/
  PRD.md            what we build and why
  ARCHITECTURE.md   how it is built
  RULES.md          the rules every change must follow
  DESIGN.md         the UI and document design system
  TASKS.md          the phase and task tracker
  MEMORY.md         running memory across sessions
  BUILD_PROMPT.md   this file
  decisions/        ADRs, one file per decision (0001-title.md)
  runbooks/         backup/restore, deploy, rollback, on-call
  api/              exported OpenAPI snapshots per release
```

| File | Holds | Update when |
| --- | --- | --- |
| `PRD.md` | Purpose, users and roles, the 8-stage flow with Input / Activity / Output / Responsible / Approval, functional requirements (FR-01 onward), non-functional requirements, scope in and out, open questions | Scope or a requirement changes |
| `ARCHITECTURE.md` | Module map and dependency rules, data model overview, event and outbox flow, port map, environments, integrations, security model, link to every ADR | A module, contract, table group or service is added or changed |
| `RULES.md` | Non-negotiables, production hardening checklist, coding standards, testing and coverage bars, git and CI rules, definition of done, writing style (no em dashes) | A rule is added or changed (needs my approval) |
| `DESIGN.md` | Colour tokens, typefaces and roles, layout concepts and wireframes, component rules, copy rules, quote/report/certificate document styling | UI or document design changes |
| `TASKS.md` | Every phase with its tasks as checkboxes, status (`done`, `in progress`, `blocked`, `not started`), acceptance criteria, owner, links to PRs and ADRs, the next batch | Every task starts, finishes or is blocked |
| `MEMORY.md` | My answers to your questions, decisions and defaults, gotchas and fixes, environment facts, stubs and their interfaces, known limitations, a dated changelog | At the end of every session and every phase |

**Session protocol**

- Start: read `MEMORY.md`, then `TASKS.md`, then the files relevant to the work. Re-read `RULES.md` before any change.
- End: update `TASKS.md`, append to `MEMORY.md`, update `ARCHITECTURE.md` or `PRD.md` if the change touched them, add an ADR for any significant decision.
- A pull request that changes behaviour without updating the relevant doc is not done.
- Keep each file short and current. Split or archive rather than letting a file grow past what you can read at the start of a session.

---

## 2. First task: reconcile Phases 1 to 5

Do this before Phase 6. Do not rebuild anything that works.

1. Inspect the repo against the Phase 1 to 5 acceptance criteria in section 11 (`make up`, `make test`, CI, health endpoints, auth and RBAC tests, audit log, PrismSuite parser against the sample, catalogue and price book, dataset engine, infra rules and gap engine).
2. Run the test suite and `docker compose up`. Record what passes and what fails.
3. Create or backfill the six docs from what actually exists in the code and from this brief. Mark Phases 1 to 5 `done` in `TASKS.md` only where the acceptance criteria are verified.
4. Record every gap, deviation, weak test, stub or undocumented decision in `MEMORY.md` and as a task in `TASKS.md`. Fix small gaps now. Ask me before spending more than a short effort on a large one.
5. The owner has reported the implementation schedule module as already complete. If any part of Phases 6 or later already exists, list it in `TASKS.md` as "exists, to verify" and fold it into the right phase instead of rebuilding it.
6. Give me a short reconciliation report (what is verified, what is missing, what you changed) and then ask the Batch 1 questions.

---

## 3. What Project One does

Project One turns a **PrismSuite IT audit** into a **verified, certified implementation**:

1. Audit intake from PrismSuite
2. Current IT infrastructure (baseline)
3. Ideal IT infrastructure (target, from a rule library)
4. Gap analysis and recommendations
5. BOQ creation (automated draft, human-edited, exact ITCraft quotation format)
6. Implementation and configuration plan, plus scheduler
7. Field work with **gated checklists** and verification
8. Completion report and **"Certified by IITPL"** sign-off certificate

Each stage ends with a named approval gate. The next stage cannot open until the gate is recorded. Approved outputs are stored as locked versions; changes create a new version, never overwrite.

**Checklists work like a food-delivery app.** A field engineer cannot move a task to the next state until the current state's checklist and evidence are complete. Every transition notifies the customer and the Director. Customer OTP is required at on-site check-in and at handover.

`assigned -> accepted -> checked_in (customer OTP + photo) -> prechecks_done (backup, access) -> configured -> evidence_uploaded -> engine_check (actual vs target config) -> verifier_review -> closed`

An engine mismatch or verifier rejection sends the task back to `configured`. A task never reaches `closed` without passing both.

**The certificate and completion report cannot be generated** unless: every mandatory checklist item is verified with evidence, no open critical deviation exists, any skipped item has a Director-approved and customer-acknowledged waiver, a post-implementation check is complete, customer sign-off is captured, and the Director has approved. There is no override button. Waived items appear on the certificate as exclusions.

The four reporting lenses across the product are **Productivity, Resilience, Security, Health**.

**Roles (10):** Audit engineer, Solution architect, Technical lead / verifier, Sales / BD manager, Sales head, Project manager, Field engineer, Director, Customer representative, Admin. One person may hold several, but **the person who performs a task can never verify it** (enforced in code). Field engineers never see prices.

---

## 4. Sample inputs (keep in `samples/`, test against them)

**PrismSuite audit report (.docx), customer Shakti Equipments Pvt Ltd, ref `PS-10092026-SHA`:** 27 endpoints, 1 server, SonicWall TZ 270 firewall (performance 40/100), Synology DS218+ NAS at 100% used with no backup schedule, retention or encryption, 2 switches (one unmanaged D-Link DGS-1024C), 45 vulnerabilities, HA score 50/100, security score 58.7/100, server hardening 3.83/10, 6 systems with two AV agents, 3 systems at 4 GB RAM, 2 on Office 2013. Layouts vary by PrismSuite version, so parsers are versioned and adapter-based and report fields they could not read. A JSON adapter must be addable without touching downstream modules.

**Manual BOQs (two PDFs), customer Shobhaglobs Engineers Hub Pvt Ltd:**
- Summary page (`Sr N | Components | Qty`), sections High Priority and To Consider: Sanitization 31, End Point Security 31, Managed Switch 1, Firewall Reconfiguration 1, Firewall configuration set up and management 1, Server for AD/DC 1, NAS 1, Phoenix ODR 1, DLP 1.
- Priced quotation (the exact output format): ITCRAFT letterhead and address, GSTIN; title QUOTATION; "To," block; date and quote ref `ITCraft/NN/2627/030`; table `Sr N | Components | Qty | Price | Amount`; section rows; bold line titles with bullet inclusions; alternatives numbered `6A`, `6B` (not summed); rupees with Indian grouping (`₹ 1,09,653.00`); terms (GST 18% extra, delivery 1 to 2 weeks, 100% advance with PO, manufacturer warranty, delivery charges outside Mumbai, no cancellation, customer arranges engineer travel and stay, **price validity 5 days**); signature block. No totals row in the sample.

Manual BOQs will become the largest training dataset later. Until then, the dataset engine imports, cleans and labels more of them.

---

## 5. Tech stack (unchanged unless I approve an ADR)

**Backend:** Python 3.12, FastAPI, Pydantic v2 (strict, `extra="forbid"`), Gunicorn + Uvicorn; PostgreSQL 16, SQLAlchemy 2.0 async, asyncpg, Alembic; Redis 7; Celery + Beat; MinIO (presigned URLs, versioned buckets); Polars, DuckDB, rapidfuzz, scipy/statsmodels; python-docx, pdfplumber, openpyxl, Jinja2 + WeasyPrint (the only PDF generator, see section 5a), qrcode; argon2id, JWT access + rotating refresh tokens, TOTP MFA for Director and Admin; structlog, OpenTelemetry, Prometheus, Grafana, optional Sentry; ruff, mypy `--strict`, pytest + testcontainers, hypothesis, import-linter, bandit, pip-audit; MLflow + scikit-learn/LightGBM later.

**Frontend (Phases 11 and 12):** Next.js 15 App Router, TypeScript strict, Tailwind v4, shadcn/ui, TanStack Query and Table, React Hook Form + Zod, Apache ECharts, typed client generated from OpenAPI (`openapi-typescript` + `openapi-fetch`), WebSocket with SSE fallback, Vitest, Playwright.

**Platform:** Docker multi-stage, non-root, healthchecks, resource limits; compose `dev` and `prod` profiles; Nginx reverse proxy with TLS and security headers; ClamAV on every upload; GitHub Actions with Trivy and SBOM.

**Port map:** 9595 web, 9596 API, 9597 Nginx, 9598 Flower, 9599 PostgreSQL, 9600 Redis, 9601 MinIO API, 9602 MinIO console, 9603 Prometheus, 9604 Grafana, 9605 Mailpit, 9606 MLflow. Only 9595 and 9597 (and 9596 in dev) are published in prod; the rest are internal or admin-only.

## 5a. PDF generation standard (WeasyPrint)

All PDF output goes through one shared rendering service in `core/` (or a `documents` sub-package of `reporting`), exposed through a contract so every module calls the same code:

- **Pipeline:** data from the module's service, then a Jinja2 HTML template plus a print CSS stylesheet, then WeasyPrint, then the PDF stored in MinIO with a checksum and linked to the record and version it came from.
- **Where it is used:** summary BOQ and priced quotation (Phase 6), implementation plan and schedule (Phase 7), checklist and evidence exports (Phase 8), verification report (Phase 9), completion report and certificate (Phase 10), and any later PDF.
- **Templates:** versioned, stored with the code, styled from `DESIGN.md`. Letterhead, address, GSTIN, terms and signature come from company settings, never hard-coded. Use CSS paged media for A4 size, margins, running headers and footers, page numbers and `page-break-inside: avoid` on table rows.
- **Fonts:** bundle the fonts in the Docker image and load them with `@font-face`. The chosen font must render the rupee sign (₹) and Indian digit grouping correctly. Never depend on system fonts or remote URLs.
- **Assets:** logo, signature image and QR code are embedded locally (base64 or local file URLs). WeasyPrint must not fetch from the network; use a restricted URL fetcher.
- **Docker:** install WeasyPrint's system libraries (Pango, HarfBuzz, fontconfig) in the image and pin the WeasyPrint version.
- **Performance:** render in a Celery worker for large documents; the API returns a job ID and a presigned URL when done. Small quotes may render inline within a timeout.
- **Tests:** golden-file tests compare extracted text and layout against the samples, plus a visual check by rasterising page 1 and comparing to a reference image within a tolerance.
- **Security:** templates autoescape all user content; no user-supplied HTML or CSS reaches WeasyPrint.

---

## 6. Architecture: a modular monolith, one module at a time

One FastAPI deployable split into strict modules: `identity`, `audit_log`, `customers`, `files`, `prismsuite`, `infra`, `gaps`, `catalogue`, `datasets`, `recommend`, `boq`, `planning`, `fieldops`, `verification`, `reporting`, `notifications`, `realtime`, `ml`, plus `core/`.

Each module has `api.py`, `schemas.py`, `models.py`, `repository.py`, `service.py` (the only place rules live), `contracts.py` (the only thing other modules may import), `events.py`, `tests/`.

- Modules never import another module's models, repositories or services. They use `contracts.py` or domain events.
- Cross-module side effects go through a transactional outbox and workers, so a notification failure never rolls back a BOQ approval.
- Swappable pieces sit behind interfaces with a registry: parser versions, price sources, recommenders, notification channels, per-brand config comparison drivers, PDF templates.
- Feature flags (DB-backed) for anything partly rolled out.
- import-linter enforces all of this in CI. A fix or change should touch one module, plus its contract if the contract must change.

---

## 7. Production hardening (applies to every phase, mirrored in `RULES.md`)

Strict input validation and size limits; RFC 9457 problem+json errors with stable codes; Redis rate limiting and lockout; RBAC plus object-level checks with deny by default; doer is never the verifier; security headers, strict CORS, CSRF for cookie auth; uploads sniffed, ClamAV-scanned, stored under random keys, served by short-lived presigned URLs; envelope encryption for device credentials and config exports, read-only device access; append-only audit log on every mutation; optimistic locking and idempotency keys; `Decimal` money (`NUMERIC(14,2)`, INR default, GST per line, central rounding, Indian number formatting); UTC storage with IST display and an April to March financial-year helper; timeouts, retries and circuit breakers on external calls; soft delete with restore; nightly backups with a tested restore runbook; `/healthz`, `/readyz`, `/metrics`; API under `/api/v1`; non-root containers, pinned versions, Trivy clean of criticals.

---

## 8. BOQ engine (Phase 6, the core module)

Draft a BOQ from the approved gap register in minutes, let sales edit everything, and render the **exact ITCraft quotation format**.

1. **Templates per gap type:** each maps to product lines plus service lines (supply, one-time setup, one-year support). Admin-editable and versioned.
2. **Quantity rules:** per endpoint, per server, per site, per flagged system, per unmanaged switch, fixed N, or a whitelisted expression DSL (never `eval`).
3. **Options:** alternative groups (`6A`, `6B`); totals per option, never summed across alternatives.
4. **Priority groups:** High Priority and To Consider.
5. **Dynamic manual prices:** from the price book (vendor, cost, selling price, margin, date quoted, valid-until, source, entered by). Expired prices block approval. Out-of-stock items trigger the listed alternative. Full price history.
6. **Everything editable** with a short recorded reason: add, remove, reorder, swap, override price or qty, edit inclusions and terms.
7. **Versioning:** drafts, then issued `v1`, `v2` with a diff summary. The customer-accepted version is locked and drives planning.
8. **Quote reference:** `ITCraft/{initials}/{FY e.g. 2627}/{seq:03d}`, per-FY sequence, safe under concurrency.
9. **Rendering:** Jinja2 to WeasyPrint PDF through the shared rendering service (section 5a), plus XLSX, for both the summary BOQ and the priced quotation, with letterhead, terms and signature from company settings. **Golden-file tests** against the samples.
10. **Totals:** subtotal, GST and grand-total rows are a per-quote toggle (ask me the default).

Seed mapping from the Shakti audit: conflicting AV to sanitization (per endpoint); no unified EPS to XDR licence plus EPS setup and one-year management; unmanaged switch to managed switch plus setup and support; under-configured firewall to reconfiguration or replacement options; NAS 100% used with no backup to NAS plus backup configuration; no DR to ODR; server hardening 3.83/10 to hardening service (per server); 4 GB RAM systems to RAM upgrade; Office 2013 to Office upgrade.

## 9. Recommendation engine (Phase 6)

Recommends products and services per gap from **customer dependencies, needs, budget and what is best in the market**.

- **v1 is a transparent rule and scoring engine:** hard filters (compatibility with existing assets, concurrent users and throughput, OS mix, brand exclusions), then weighted scoring on need fit, budget fit, 3-year total cost, market standing (rating, analyst tier, India support), lifecycle (end-of-life dates), vendor preference, stock, and past acceptance in our BOQs. Weights are configurable per customer segment.
- Every result returns **reasons** and runner-ups.
- Market data is **entered manually** in the catalogue (attribute, source, date). No scraping in v1; leave a feed adapter interface.
- Customer inputs: preferred and excluded brands, total and per-category budget, assets to keep, 12-month growth, compliance needs.
- Same contract for `RuleBasedRecommender` now and `LearnedRanker` in Phase 13, with shadow mode to compare them.

---

## 10. Other modules and the frontend brief

**planning:** tasks per accepted BOQ line, dependencies (sanitization before EPS on the same machine), engineer assignment, schedule with customer downtime windows, per-device target configuration baselines from config templates.

**fieldops:** the state machine in section 3, mandatory evidence per step (photos, screenshots, config exports, serials), customer OTP at check-in and handover, timestamps and location, offline-tolerant idempotent resumable uploads.

**verification:** actual vs target config. v1 uses uploaded config exports and structured checklist answers; per-brand drivers (SonicWall, Sophos, Fortinet, Cisco) behind an interface for later read-only API pulls. Results: pass, fail or not checked, with deviations and severity.

**realtime and Director dashboard API:** progress, tasks by state, blocked items with reasons, deviations, check-ins, time vs plan.

**reporting:** all PDFs rendered with WeasyPrint (section 5a). Completion report (scope delivered, before/after scores on the four lenses, config summary, deviations closed, waivers, open recommendations) and certificate (ID, customer, project, BOQ ref, scope, dates, verifier and Director names, "Certified by IITPL", QR to a public verification endpoint returning only non-sensitive fields). Release conditions enforced in the service layer.

**notifications:** email, SMS and WhatsApp through provider adapters, templated, with retries and user preferences; Mailpit in dev.

**Frontend (use the frontend-design skill process):** write a compact design plan first in `docs/DESIGN.md` (4 to 6 named hex colours, typefaces and roles, ASCII wireframes, principles), review it against this brief, revise anything that reads as a generic default, then build. Minimal and calm; data-dense where it matters (BOQ editor, dataset grid); very simple on mobile for field engineers; spend boldness in one place (the task timeline and live status). Avoid generated-UI tells: cream-and-terracotta, black with acid-green, identical rounded cards, all-caps eyebrow labels, middle-dot meta strings, arrows on every button, fade-in on every section. Plain active copy in sentence case named by what users do ("Issue quote"). Responsive to 360 px, keyboard accessible, WCAG AA, reduced motion respected, dark mode.

Key screens: sign-in and MFA; projects and stage tracker; audit import review; gap register; BOQ editor (inline edit, options, price-validity warnings, version diff, PDF preview); catalogue and price book; dataset workspace; planner; field engineer mobile flow (task list, step checklist, camera evidence, OTP, offline queue); verification review; Director live dashboard; report and certificate preview; admin.

---

## 11. Phases

### Phases 1 to 5: done (verify in section 2, do not rebuild)

| Phase | Scope | Verify |
| --- | --- | --- |
| 1 | Platform foundation: repo layout, `core/`, Docker compose and port map, CI, import-linter, health and metrics | `make up` healthy, `make test` green, CI passes, Trivy has no criticals |
| 2 | Identity, RBAC, MFA, audit log, customers, projects, 8-stage gate model | Permission tests for every role and endpoint, doer is not verifier, audit entry per mutation |
| 3 | PrismSuite ingestion (`PrismSuiteParserV1`, upload pipeline), catalogue and price book | Parser reads every count and score in section 4 from the sample, expired prices flagged |
| 4 | Dataset engine: import, cleaning, segregation, EDA, manipulation pipelines, visualisation specs, dataset management, versions and lineage | Replayable pipelines, versioned Parquet, review queue before master catalogue |
| 5 | Infra model, ideal-infra rule library, gap engine | Current vs ideal produces gap register with priority, lens and linked assets |

### Batch 1 (build next): Phases 6 to 8

**Phase 6: BOQ engine and recommendation engine** (sections 8 and 9), including exact-format PDF and XLSX rendering and golden tests.
- Acceptance: generated quotation matches the sample format, options are not summed, expired price blocks approval, every edit has a reason and a version, quote refs are collision-free under concurrent requests, every recommendation shows reasons.
- Questions: show totals and GST rows by default? quote numbering per company or per salesperson? who may override prices? default recommendation weights? which market attributes to capture first?

**Phase 7: Planning, scheduling and configuration baselines.** Plan and schedule PDFs use the WeasyPrint service (section 5a).
- Acceptance: tasks generated from an accepted BOQ, dependencies enforced, schedule respects downtime windows, each device has a target config baseline.
- Questions: engineer calendars and working hours? travel time? which config fields per device type matter for verification?
- Note: the owner reports the schedule module exists. Verify it, then extend rather than rebuild.

**Phase 8: Field ops state machine, evidence, OTP, notifications, realtime.**
- Acceptance: no skipping states, each transition notifies customer and Director, OTP required at check-in and handover, uploads resume after a dropped connection, doer cannot verify.
- Questions: OTP channel (SMS, WhatsApp, email)? mandatory photo evidence per step type? how long must offline work be supported?

### Batch 2: Phases 9 to 11

**Phase 9: Verification engine and Director dashboard API.** Questions: which device brands first? read-only remote access or evidence-only in v1? deviation severity rules?

**Phase 10: Completion report and certificate** (WeasyPrint PDFs per section 5a, release conditions, waivers, QR verification, digital signature). Questions: legal wording of "Certified by IITPL"? who may sign? is a PrismSuite rescan mandatory?

**Phase 11: Frontend foundation** (design plan in `DESIGN.md`, design system, auth and MFA, app shell, projects, audit import review, gap register, catalogue and price book). Questions: brand assets and colours? primary device per role?

### Batch 3: Phases 12 to 14

**Phase 12: Frontend core workflows** (BOQ editor, dataset workspace, planner, field engineer mobile flow with offline queue, verification review, Director live dashboard, report and certificate preview, admin). Questions: PWA install for engineers? languages other than English?

**Phase 13: ML pipeline** (MLflow, training on frozen dataset snapshots: BOQ line prediction from findings, learned ranker, price-drift alerts; shadow mode against the rule engine; model cards). Questions: how many manual BOQs exist and how are they labelled?

**Phase 14: Hardening and performance** (k6 or Locust load tests, OWASP ASVS L2 review, pen-test fixes, worker failure chaos checks, indexing and query review, backup and restore drill).

### Batch 4: Phase 15

**Phase 15: Go-live** (prod deployment, TLS, alerts, runbooks, on-call guide, data migration from spreadsheets, user training docs, rollback plan).

---

## 12. Batch report (after every batch)

1. What was built per phase, mapped to the acceptance criteria.
2. How to run it (`make` commands, URLs on the port map, seeded demo users per role).
3. Test results and coverage.
4. Decisions made (ADR links) and defaults chosen for unanswered questions.
5. Docs updated (list the changes to each of the six files).
6. Known limitations, stubs behind interfaces, risks.
7. Questions for the next batch.

Then stop and wait for my go-ahead.

---

## 13. Start now

1. Read this brief and the existing `docs/` folder if present.
2. Run the reconciliation in section 2 and send me the report.
3. List any contradictions or gaps you see in this brief.
4. Ask the Batch 1 questions (Phases 6 to 8) in one message.
5. After I answer, build Phases 6, 7 and 8.
