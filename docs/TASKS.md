# Tasks

Phase status and what is left. Status words: `done`, `in progress`, `blocked`, `not started`.
Planned dates are in `ROADMAP.md`, decisions in `decisions/`.

## Where we are (8 October 2026)

- Phases 1 to 14 are done, with Phase 12A (the field app on phones and the missing office
  screens) added. Backend: 403 tests pass at 86 percent coverage. Browser tests: 25 of 31 pass on desktop, Android and iPhone screens; 5 skip by
  design or for want of unused demo tasks, and the project manager test fails only because that
  demo account's password was changed on 5 Oct. Lighthouse on the field pages: performance 92
  to 96, accessibility 96 to 100.
- The field app installs on Android and iPhone, works offline for up to 72 hours between
  check-in and sending for checking, needs the phone's location at check-in, and never
  receives a price (ADR 0027).
- Quotes record won or lost with a reason, warn before their prices lapse, re-price in one
  click, and lines under the minimum margin need the approver's reason (ADR 0028).
- Phase 13 (learning) has three models in shadow mode (ranker, BOQ lines, price drift) and
  waits for data (about 20 accepted BOQs). Only the Director can approve a model (ADR 0029).
- Only an Admin or the Director creates accounts and assigns roles; the Director holds every
  Admin permission (ADR 0026).
- Phase 15 (go-live): everything is ready to deploy (DEPLOYMENT.md, incident runbook, a
  production dry run that passed). Left: deploy on the real server, the IITPL stamp, and the
  first real SonicWall export.

## Phase status

| # | Phase | Status | Notes |
| --- | --- | --- | --- |
| 1 | Platform foundation | done | compose, CI files, health, metrics, outbox, backups |
| 2 | Identity, RBAC, MFA, audit log, customers, gates | done | permission matrix covers every route |
| 3 | PrismSuite intake, catalogue, price book | done | docx v1 and JSON v1 parsers |
| 4 | Dataset engine and library | done | plus the document corpus |
| 5 | Infra model, rule library, gap engine | done | |
| 6 | BOQ and recommendation engine | done | one open item below |
| 7 | Planning, scheduling, baselines | done | plan PDF |
| 8 | Field ops, evidence, OTP, notifications, realtime | done | |
| 9 | Verification engine, Director dashboard API | done | SonicWall mappings unconfirmed until a real export |
| 10 | Completion report and certificate | done | real IITPL stamp still needed |
| 11 | Frontend foundation | done | |
| 12 | Frontend core workflows | done | accounts panel, Help guide, phone test of a whole field task |
| 12A | Field app on phones, office screens | done | installable, offline, push; tested on Android and iPhone screens in Chrome, not yet on a real iPhone |
| 13 | Learning from accepted BOQs | done | three models in shadow mode; needs about 20 accepted BOQs before one can train |
| 14 | Hardening and performance | done | ASVS Level 2 review, chaos checks, alerts; backup encryption before go-live (F6) |
| 15 | Go-live | in progress | ready to deploy: DEPLOYMENT.md, prod dry run passed; real server next |

## Open items by phase

### Phase 6: BOQ and recommendations

- [x] Store issued PDFs in MinIO linked to the BOQ version (migration 0014)
- [ ] Visual golden test (rasterise page 1, compare to a reference) inside the container

### Phase 8: Field operations

- [ ] WebSocket transport. SSE covers v1; add only if a client needs two-way

### Phase 9: Verification

- [x] Export parsers per brand, SonicWall first (`.exp`, key/value text, JSON)
- [x] Brand key mappings as data, with an inspector to confirm them on a real export
- [x] Deviation register kept in step with every configuration check
- [x] Severity policy: what blocks the certificate, what a verifier may not accept
- [x] Verifier can add a deviation by hand or accept one with a reason; never the doer
- [x] Director dashboard API: stage, field progress, blocked work, open deviations
- [ ] Confirm the SonicWall mappings against the first real export

### Phase 10: Completion report and certificate

- [x] Eight release conditions, checked in one place, no override
- [x] Waivers: Director decides, customer acknowledges, printed on the certificate
- [x] Field work summary, completion report preview, lock, PDF stored with its SHA-256
- [x] Certificate: Director only, signed, QR code to the public check page, revoke
- [x] Certificate wording and stamp settings
- [ ] Upload the real IITPL stamp (waiting on IITPL)

### Phase 12: Frontend core workflows

- [x] Field engineer flow with offline outbox, review queue, plan and field tabs
- [x] Library: corpus, data quality, held lines
- [x] Completion tab, Director dashboard, certificate settings, public check page
- [x] Playwright smoke tests across roles, desktop and phone
- [x] BOQ version compare view
- [x] Installable web app (manifest and service worker) for field engineers
- [x] Playwright test that walks one field task end to end on a phone (`e2e/field-task.spec.ts`;
  each run uses one assigned task, so add demo data when they run out)
- [x] Accounts panel: create with several roles, edit roles and details, reset password or
  authenticator, unlock, sign out everywhere, deactivate; tabs by role and search
- [x] Back button on every inner page; Help guide per role, linked from every sidebar
- [x] Sign-in redesign with icons; Phosphor icons across the shell; no animation (ADR 0023)
- [x] Recovery code accepted at sign-in (the API took it, the page had no field for it)
- [x] Bug sweep (5 Oct): field outbox keeps work through sign-in renewal and restarts, retries
  by itself, Try again for refused items, no double sends, warning at sign-out; downloads renew
  the sign-in; BOQ editor and audit review reload after someone else's change; confirm step for
  password and authenticator resets, deactivation and BOQ issue
- [x] Director manages accounts and roles like the Admin (ADR 0026)

### Phase 12A: Field app on phones and office screens

- [x] Installable app: manifest, service worker, install prompt, "New version ready" banner
- [x] Separate phone layout with bottom navigation; field engineers reach only their pages
- [x] Offline outbox with a badge, Sync now and Background Sync where supported (72 hours)
- [x] Location required at check-in (ADR 0027); evidence stamps with time, location and task
- [x] Single-use upload link with a QR code for configuration exports; before and after compare
- [x] Customer code screen: paste, one-time-code autofill, resend countdown
- [x] Web Push, Messages page, message settings per channel; iPhone note about Add to Home Screen
- [x] Idle sign-out after 15 minutes, warning when work is still waiting, caches cleared
- [x] Account settings, customers, company, templates, stage approvals and switches settings
- [x] Global search (Postgres full text and `pg_trgm`), filtered by role
- [x] Director: how long each project waits and on whom, each engineer's phone sync state;
  project manager's two-week workload
- [x] Quotes: won or lost with a reason, re-price in one click, price lapse alerts, minimum
  margin (ADR 0028)
- [x] Tests: backend test that no route sends a price to a field engineer; browser tests on
  Android and iPhone screens, offline sync, no prices in field traffic, installability
- [x] Lighthouse on the field pages (`npm run lighthouse`) and a bundle budget (`npm run budget`)
- [ ] Try Web Push and Add to Home Screen on a real iPhone
- [ ] Confirm the 10 percent minimum margin with the Director

### Phase 13: Learning from the library

- [x] Trains only on frozen training sets with a data card (RULES 2.6)
- [x] Learned ranker behind the recommender contract, in shadow mode next to the rules
- [x] Agreement report and Learning page
- [x] BOQ line prediction and price drift checks (scikit-learn, LightGBM), model cards
- [x] 30 days and 20 comparisons in shadow before the Director may approve; `ml_enabled` switch
- [x] Optional MLflow (compose profile `mlflow`), off by default (ADR 0029)
- [ ] Train the first models once about 20 accepted BOQs exist

### Phase 14: Hardening and performance

- [x] Load test of the busiest paths, with numbers recorded (`scripts/loadtest.py`)
- [x] Security pass: pip-audit, bandit, npm audit, permission matrix
- [x] Backup and restore drill with timings (`scripts/restore_drill.py`); backups were failing, fixed
- [x] Pin compose images by digest
- [x] Rate limits answer 429 and fit an office behind one address
- [x] Strict sign-in limit only on sign-in and MFA, 60 a minute per address; `/auth/me` and
  token refresh no longer use it up (people were refused sign-in after browsing)
- [x] Demo writes its accounts file before building projects, and re-issues logins if the
  file is lost; `seed-demo` also clears the dev admin's authenticator
- [x] Usability pass on My tasks, the task page and project pages
- [x] BOQ estimate before approvals (ADR 0021)
- [x] Pin the Dockerfile base images by digest
- [x] Director dashboard in four queries for any number of projects (was about seven per project)
- [x] Coverage back to 85 percent (355 tests, with the Accounts actions and backups tested)
- [x] Migrations expand only and every downgrade runs (`tests/test_migrations.py`, RULES 4)
- [x] Models match the migrated schema (same test file)
- [x] Chaos checks: worker killed mid-job, API killed mid-PDF, Valkey restart, database
  connections cut (`scripts/chaos.py`, all pass 8 Oct); a task lost with its worker now
  returns in 10 minutes (measured: 10.5)
- [x] Load test at the agreed size (8 Oct, 30 people at once, no pauses): p95 276 to 392 ms on
  every read path, no errors; the per-person limit answered 429 as designed
- [x] Restore drill (8 Oct): 83 tables and 8,254 rows identical, recovery 3.7 s on demo data
- [x] GlitchTip, Uptime Kuma, Alertmanager, node and blackbox exporters; 12 alert rules tested
  with promtool; `docs/runbooks/alerts.md`
- [x] OWASP ASVS Level 2 review (`docs/runbooks/security-review.md`)
- [x] Production publishes only 80 and 443; load balancer port opt-in (ADR 0030)
- [x] Licence check feeding `docs/LICENSES.md` (`scripts/licenses.py --check`)
- [ ] Encrypt the off-server backup copy before go-live (security review F6)
- [ ] Decide on the Next.js 16 upgrade (security review F1 and F2)
- [ ] Decide whether to bring back hosted CI and dependency updates

### Phase 15: Go-live

- [x] Production compose and TLS (Let's Encrypt, own certificate, or a load balancer)
- [x] DEPLOYMENT.md: server to first sign-in, updates and rollback, backups off the server
- [x] Production dry run on a laptop: HTTPS, sign-in with authenticator, accounts, upload and
  download, the web app over HTTPS, all passing (4 Oct)
- [x] Production refuses unsafe settings (http or localhost addresses, dev secrets, no email)
- [x] Files served through the app with signed links, so storage stays internal
- [x] Every API route listed in docs/API_ROUTES.md, kept current by a test; open routes pinned
- [x] In-app Help guide per role (the short training guide)
- [ ] Deploy on the real server and run DEPLOYMENT.md section 8 there
- [x] Incident runbook: docs/runbooks/incident.md (who does what, first 15 minutes, common
  incidents, break-in, restore, messages to staff and customers)

## Questions still open

1. Severity rules beyond critical, major and minor (ADR 0019).
2. The IITPL stamp image.
3. The minimum margin: 10 percent for now (ADR 0028).
4. Upgrade to Next.js 16 now or after go-live (security review F1, F2).
5. How to encrypt the off-server backup copy, and who keeps the key (security review F6).
