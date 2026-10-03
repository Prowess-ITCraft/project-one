# Architecture

How Project One is built. Decisions behind it are in `decisions/` (linked at the end).

## 1. Shape

A **modular monolith**: one FastAPI deployable split into strict modules, plus a Next.js web
app. One Docker image runs the API, the Celery worker and Celery beat with different commands.

```
backend/app/
  core/        config, db, errors, logging, money, time, outbox, crypto, rate limits,
               safe expressions, sequences, flags, idempotency, documents (PDF renderer)
  modules/     one folder per module (below)
  main.py      builds the app      worker.py  Celery app and schedules     cli.py  operator commands
frontend/      Next.js 15, React 19, plain CSS, typed client generated from OpenAPI
samples/       the reference inputs; samples/corpus/ holds their canonical JSON
```

## 2. Modules

| Module | Owns | Status |
| --- | --- | --- |
| `identity` | users, roles, permissions, MFA, sessions, refresh tokens | built |
| `audit_log` | hash-chained append-only audit trail | built |
| `customers` | customers, sites, contacts, projects, members, 8-stage gates, acknowledgements | built |
| `files` | upload pipeline: sniff, ClamAV, random keys, presigned URLs | built |
| `prismsuite` | versioned parsers (docx v1, json v1), snapshot review and approval | built |
| `catalogue` | vendors, items, market data, price book with validity | built |
| `datasets` | library inbox, importers, **document corpus**, cleaning, quality, versions, EDA, promotion | built; corpus in Batch 1 |
| `infra` | current and ideal model, rule DSL, gap engine | built |
| `boq` | templates, quantity rules, recommender, editor, versions, quote refs, rendering | built |
| `planning` | task and config templates, plan, dependencies, scheduler, baselines, leave, downtime | built |
| `notifications` | queue, providers (email; SMS and WhatsApp adapters), preferences, retries | Batch 1 |
| `fieldops` | task run state machine, evidence, OTP, offline idempotency, live events | Batch 1 |
| `verification` | config comparison drivers, deviations, verifier review | Phase 9 (interface in Batch 1) |
| `reporting` | completion report, certificate, QR verification | Phase 10 |
| `ml` | training on frozen snapshots, learned ranker, shadow mode | Phase 13 |

Every module has `api.py`, `schemas.py`, `models.py`, `service.py` (the only place rules live),
`contracts.py` (the only file other modules import), optional `handlers.py`, and `tests/`.

### Dependency rules (enforced by import-linter in CI, `.importlinter`)

- A module never imports another module's `models`, `service` or `repository`. It uses that
  module's `contracts.py`, or reacts to its events.
- `core` never imports a module.
- Cross-module side effects go through the **transactional outbox**: the event is written in
  the same transaction as the change, and a worker delivers it. A failing subscriber never rolls
  back the change that caused it.

Main contract edges: `boq -> infra, catalogue, customers, datasets(history)`;
`planning -> boq(accepted, no prices)`; `fieldops -> planning, customers, notifications, files`;
`datasets -> prismsuite(parse), files`.

## 3. Data model (table groups)

| Group | Tables |
| --- | --- |
| Identity | users, user_roles, auth_sessions, refresh_tokens, mfa_recovery_codes |
| Audit | audit_log, audit_subject_keys |
| Customers and gates | customers, customer_sites, customer_contacts, projects, project_members, project_briefs, stage_gate_configs, stage_artifacts, stage_submissions, gate_decisions, customer_acks |
| Files | stored_files, rejected_uploads |
| PrismSuite | audit_imports, audit_corrections |
| Catalogue | vendors, catalogue_categories, catalogue_items, catalogue_market_data, price_entries |
| Datasets and library | datasets, dataset_versions (immutable), dataset_shares, dataset_quarantine, dataset_synonyms, dataset_promotions, library_files, corpus_documents (Batch 1) |
| Infra and gaps | infra_rules, infra_rule_changes, infra_states, gap_registers, gaps |
| BOQ | boq_templates, reco_weights, company_settings, boqs, boq_versions, boq_edits |
| Planning | plan_task_templates, plan_config_templates, plans, plan_tasks, plan_config_baselines, engineer_leaves, downtime_windows |
| Notifications | notifications, notification_prefs |
| Field ops | task_runs, run_events (append only), run_evidence (append only), otp_challenges |
| Platform | outbox, idempotency keys, sequences, feature flags |

Money is `NUMERIC(14,2)`. Editable rows carry a `version` column for optimistic locking.
Approved outputs are stored as locked `stage_artifacts`; changes create new versions.

## 4. The document corpus and data pipeline

Heavy source files (PDF, DOCX, XLSX) are read **once**. Everything downstream works from compact
data. This keeps the API light, keeps deployment storage small and gives the ML phase a clean,
reproducible training set. Details: ADR 0014.

```
 upload / watched folder / samples/
        |
        v
 files: sniff, virus scan, sha256          (original stored once, never read again on the hot path)
        |
        v
 extract: text per page + tables          (pdfplumber, python-docx, openpyxl)
        |
        v
 parse: BoqDocument | AuditSnapshot        (versioned parsers, confidence per row)
        |
        v
 clean: normalise text and names, parse money and dates, de-duplicate, label (taxonomy)
        |
        v
 validate and score: completeness, validity, consistency, uniqueness, outliers
        |
        +--> corpus_documents row + canonical JSON (p1.corpus.v1, gzipped in MinIO)
        +--> collection rows (Parquet, versioned)   +--> quarantine for low-confidence rows
        |
        v
 analysis: label stats, price bands, typical quantities, option pairs, drift
        |
        v
 frozen training snapshot + data card (Phase 13 trains only on these)
```

- **Canonical JSON** (`p1.corpus.v1`): source facts (name, sha256, bytes, pages), parser name
  and version, plain text per page, the structured document, cleaned lines with labels, and the
  quality report. Typically 5 to 40 times smaller than the original.
- **Originals** are kept in object storage by default (data is valuable and parsers improve).
  `P1_CORPUS_ORIGINALS_RETENTION_DAYS` can purge originals once their JSON is verified; the JSON
  and its checksum remain the record.
- **Re-parse**: when a parser version improves, `cli corpus reparse` rebuilds JSON from the
  originals that are still kept, and the collection gets a new version (old versions stay).
- **Offline**: `cli corpus convert <folder>` runs the same pipeline without a database. It is
  how `samples/corpus/` is built and how a laptop can prepare a batch of old files.

## 5. Events and the outbox

Modules publish `DomainEvent`s through `core/outbox.py` inside their transaction. The worker
task `dispatch_outbox` delivers them to subscribers registered with `@subscribe`. Handlers are
idempotent. Every process loads its subscribers at start-up and `publish` refuses otherwise
(ADR 0018). Examples: `datasets.library_file_added` (process the file),
`prismsuite.snapshot_approved`, `catalogue.price_expired`, `fieldops.transition` (notify customer
and Director, Batch 1).

## 6. Documents (PDF)

One shared renderer in `core/documents.py`: Jinja2 template plus print CSS, rendered by
WeasyPrint with a restricted URL fetcher (no network, only bundled assets), fonts loaded with
`@font-face` from the image, checksum recorded. Used by the quotation and summary BOQ (Phase 6),
plan and schedule (Phase 7), checklist export (Phase 8), and later reports and the certificate.
No other PDF generator is allowed without an ADR.

## 7. Ports and environments

| Port | Service | Published in prod |
| --- | --- | --- |
| 9595 | web (Next.js) | yes |
| 9596 | API | dev only |
| 9597 | Nginx proxy | yes |
| 9598 | Flower | no |
| 9599 | PostgreSQL 16 | no |
| 9600 | Valkey (Redis-compatible) | no |
| 9601 / 9602 | MinIO API / console | no |
| 9603 / 9604 | Prometheus / Grafana | admin only |
| 9605 | Mailpit | dev only |
| 9606 | MLflow | Phase 13 |

Compose files: `docker-compose.yml` (base), `docker-compose.dev.yml` (publishes ports, Mailpit),
`docker-compose.prod.yml`. On Windows `scripts/dev.ps1` replaces `make`.

## 8. Security model

Argon2id passwords, short JWT access tokens plus rotating refresh tokens with reuse detection,
TOTP MFA for Director and Admin, Valkey rate limits and lockout, RBAC with object-level checks
and deny by default, doer is never the verifier, RFC 9457 errors, append-only hash-chained audit
log, uploads sniffed and ClamAV-scanned, presigned URLs, envelope encryption for device
credentials and config exports, field engineers never receive prices, customer OTPs stored as
salted hashes and wiped from the message log after an hour.

## 9. Decisions

| ADR | Title |
| --- | --- |
| [0001](decisions/0001-sanitization-quantity-rule.md) | Sanitization quantity rule |
| [0002](decisions/0002-two-validity-concepts.md) | Two validity concepts |
| [0003](decisions/0003-field-engineers-never-see-prices.md) | Field engineers never see prices |
| [0004](decisions/0004-audit-log-and-personal-data.md) | Audit log and personal data |
| [0005](decisions/0005-ports-and-proxy.md) | Ports and proxy |
| [0006](decisions/0006-minio-image.md) | MinIO image |
| [0007](decisions/0007-windows-tooling.md) | Windows tooling |
| [0008](decisions/0008-compose-modes.md) | Compose modes |
| [0009](decisions/0009-price-book-rules.md) | Price book rules |
| [0010](decisions/0010-prismsuite-review-rules.md) | PrismSuite review rules |
| [0011](decisions/0011-open-source-and-free-only.md) | Open source and free only |
| [0012](decisions/0012-scope-reconciliation.md) | Scope reconciliation |
| [0013](decisions/0013-boq-defaults.md) | BOQ defaults |
| [0014](decisions/0014-document-corpus.md) | Document corpus: convert once to canonical JSON |
| [0015](decisions/0015-field-task-state-machine.md) | Field task state machine follows the v2.1 brief |
| [0016](decisions/0016-shared-pdf-renderer.md) | One shared WeasyPrint renderer |
| [0017](decisions/0017-batch-1-defaults.md) | Batch 1 defaults (planning and field ops) |
| [0018](decisions/0018-outbox-subscribers-load-first.md) | Event subscribers load before anything publishes |
| [0019](decisions/0019-batch-2-answers.md) | Batch 2 answers from the owner |
