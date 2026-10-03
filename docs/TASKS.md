# Tasks

Phase and task tracker. Status words: `done`, `in progress`, `blocked`, `not started`,
`exists, to verify`. Dates follow the mock plan in `ROADMAP.md`. Decisions: `decisions/`.

## Where we are (3 October 2026)

- Batch 1 (phases 6 to 8) is built: 302 backend tests pass, 86 percent coverage. Waiting for the
  owner's go-ahead for Batch 2 (9 to 11).
- Next batch: phase 9 (verification engine and Director dashboard API), 10 (completion report
  and certificate), 11 (frontend foundation, mostly done early).

## Reconciliation of phases 1 to 5 (3 Oct 2026)

| Check | Result |
| --- | --- |
| Backend test suite | 222 passed at the start of the session (7 min 50 s) |
| Import boundaries | 2 contracts kept, 0 broken |
| ruff and mypy --strict | Clean after fixes this session |
| PDF generators | WeasyPrint only; moved behind the shared renderer (ADR 0016); rendered in the container with the rupee sign, remote and system files refused |
| `docker compose up`, CI on GitHub, Trivy | Not re-run this session. Last recorded healthy stack on 1 Oct (MEMORY.md) |
| Six core docs | Missing; created this session from the code and the brief |

## Phase status

| # | Phase | Status | Notes |
| --- | --- | --- | --- |
| 1 | Platform foundation | done | compose, CI files, health, metrics, outbox, backups |
| 2 | Identity, RBAC, MFA, audit log, customers, gates | done | permission matrix covers every route |
| 3 | PrismSuite intake, catalogue, price book | done | docx v1 and JSON v1 parsers |
| 4 | Dataset engine and library | done | plus the document corpus (Batch 1) |
| 5 | Infra model, rule library, gap engine | done | |
| 6 | BOQ and recommendation engine | done | gaps listed below |
| 7 | Planning, scheduling, baselines | done | plan PDF added this session |
| 8 | Field ops, evidence, OTP, notifications, realtime | done | rebuilt to the v2.1 states |
| 9 | Verification engine, Director dashboard API | not started | engine interface and answer driver exist (phase 8) |
| 10 | Completion report and certificate | not started | `field_status` contract ready |
| 11 | Frontend foundation | in progress | first slice built 1 Oct |
| 12 | Frontend core workflows | in progress | done: field engineer flow with offline outbox, review queue, plan and field tabs, library corpus and data quality; left: BOQ version diff view, dataset workspace, Playwright tests |
| 13 | ML pipeline | not started | corpus, labels and frozen snapshots ready |
| 14 | Hardening and performance | not started | |
| 15 | Go-live | not started | |

## Batch 1 detail

### Phase 6: BOQ and recommendations

- [x] Templates per gap type, quantity rules, safe expressions
- [x] Options 6A and 6B never summed; totals as ranges
- [x] Priority groups, price book, expired price blocks approval
- [x] Every edit with a reason, versions with diff, PO on acceptance
- [x] Quote refs per financial year, safe under concurrency
- [x] Quotation and summary BOQ as HTML, PDF and Excel; golden tests
- [x] Rule-based recommender with reasons and runner-ups
- [x] PDF through the shared renderer with checksum header (ADR 0016)
- [ ] Store issued PDFs in MinIO linked to the BOQ version (needs a column and migration)
- [ ] Visual golden test (rasterise page 1, compare to a reference) in the container CI job

### Phase 7: Planning

- [x] Tasks from the accepted BOQ, dependencies, engineer leave, downtime windows
- [x] Scheduler, baselines per device from config templates, locking
- [x] Plan and schedule PDF and HTML (`/projects/{id}/plan/render`)

### Phase 8: Field operations

- [x] State machine per ADR 0015, nothing skipped, verified in tests
- [x] Customer OTP at check-in and hand over (email), hashed, rate limited
- [x] Evidence per stage, resumable by `client_id`, offline window 72 hours
- [x] Engine check behind `ConfigCheckDriver` (answer driver v1)
- [x] Verifier queue; the doer cannot verify (tested with a person holding both roles)
- [x] Customer, Director and PM notified at every transition
- [x] Live feed: SSE stream plus polling with a `seq` cursor; Director summary
- [x] Checklist record PDF with embedded photos
- [x] Notifications module registered, retries scheduled every minute
- [ ] WebSocket transport (SSE covers v1; add only if a client needs two-way)

### Data corpus (owner request, 3 Oct)

- [x] Canonical JSON per file (`p1.corpus.v1`), gzipped, indexed (ADR 0014)
- [x] Cleaning: normalisation, spelling, heading-overprint repair, labels per gap type
- [x] Quality score per document; analysis with price bands and MAD outliers
- [x] Rebuild from originals, retention purge (off by default), data card distributions
- [x] Watched inbox folder scheduled every 5 minutes; `samples/corpus` golden files
- [x] `cli corpus convert | ingest | rebuild | purge`

### Frontend (brand pass)

- [x] ITCraft and IITPL logos, brand tokens with contrast checked (DESIGN.md)
- [x] My tasks, task page with timeline, evidence capture, OTP, offline outbox
- [x] Review queue; Plan tab; Field work tab with live feed
- [x] Library: corpus, data quality, held lines; status bugs fixed
- [ ] Playwright tests for the field flow (phase 12)
- [ ] Installable web app (PWA manifest and service worker) for engineers (phase 12)

## Gaps found and fixed this session

- Watched library folder existed but was never scheduled. Fixed (beat task, compose mount).
- Notification retries were never scheduled. Fixed.
- Field permissions (`field:*`) referenced by code did not exist. Added.
- Deprecated DuckDB and Pillow calls. Fixed.
- Library page checked status names and collection keys the API never sends. Fixed.
- Events published from the CLI were silently dropped (no subscribers loaded). Fixed at the root
  with a start-up guard (ADR 0018); `cli corpus requeue` re-sent the three affected samples.
- A file whose held lines were all settled stayed at "Needs a person". Fixed and tested.
- The web image did not include `public/`, so logos were missing in the container. Fixed.
- On phones the top bar row stretched to half the screen and wrapped. Fixed (compact bar).
- Authenticator set-up showed only a key to type; it now shows a QR code drawn by the API.
- PDF review (render-samples): double bullets on every quotation inclusion, a section heading left
  alone at a page foot, page numbers in a fallback serif, an empty "Proven by" column on the plan,
  and a failed configuration check labelled "passed" on the task record. All fixed.
- Cleaning v2 corrects three more misspellings seen in the ITCraft quotation; the dev library was
  rebuilt through `cli corpus rebuild`.

## Next batch questions (phases 9 to 11)

See `MEMORY.md`, section "Open questions".
