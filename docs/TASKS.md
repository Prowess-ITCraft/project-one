# Tasks

Phase status and what is left. Status words: `done`, `in progress`, `blocked`, `not started`.
Planned dates are in `ROADMAP.md`, decisions in `decisions/`.

## Where we are (4 October 2026)

- Phases 1 to 14 are done. Backend: 355 tests pass at 85 percent coverage; 13 browser tests
  on desktop and phone, including one field task walked from accept to verified (4 Oct, night).
- Phase 13 (learning) is built and waits for data (about 20 accepted BOQs).
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
| 6 | BOQ and recommendation engine | done | two open items below |
| 7 | Planning, scheduling, baselines | done | plan PDF |
| 8 | Field ops, evidence, OTP, notifications, realtime | done | |
| 9 | Verification engine, Director dashboard API | done | SonicWall mappings unconfirmed until a real export |
| 10 | Completion report and certificate | done | real IITPL stamp still needed |
| 11 | Frontend foundation | done | |
| 12 | Frontend core workflows | done | accounts panel, Help guide, phone test of a whole field task |
| 13 | Learning from accepted BOQs | done | shadow mode only; needs about 20 accepted BOQs before a model can train |
| 14 | Hardening and performance | done | one decision left for the owner: hosted CI and dependency updates |
| 15 | Go-live | in progress | ready to deploy: DEPLOYMENT.md, prod dry run passed; real server next |

## Open items by phase

### Phase 6: BOQ and recommendations

- [ ] Store issued PDFs in MinIO linked to the BOQ version (needs a column and migration)
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

### Phase 13: Learning from the library

- [x] Trains only on frozen training sets with a data card (RULES 2.6)
- [x] Learned ranker behind the recommender contract, in shadow mode next to the rules
- [x] Agreement report and Learning page
- [ ] Train the first model once about 20 accepted BOQs exist
- [ ] Decide (new ADR, Director) whether a model may ever influence real BOQs

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
