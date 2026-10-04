# Tasks

Phase status and what is left. Status words: `done`, `in progress`, `blocked`, `not started`.
Planned dates are in `ROADMAP.md`, decisions in `decisions/`.

## Where we are (4 October 2026)

- Phases 1 to 10 are built. Backend: 320 tests pass at 84 percent coverage (4 Oct).
- The web app covers every stage, from audit intake to the certificate. Phase 12 has a few
  screens and the installable phone app left.
- Next: finish phase 12, then 13 (learning from the library), 14 (hardening), 15 (go-live).

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
| 12 | Frontend core workflows | in progress | see below |
| 13 | Learning from the library (ML) | not started | corpus, labels and frozen snapshots ready |
| 14 | Hardening and performance | not started | |
| 15 | Go-live | not started | |

## Open items by phase

### Phase 6: BOQ and recommendations

- [ ] Store issued PDFs in MinIO linked to the BOQ version (needs a column and migration)
- [ ] Visual golden test (rasterise page 1, compare to a reference) in the container CI job

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
- [ ] Playwright test that walks one field task end to end on a phone

### Phase 13: Learning from the library

- [ ] Features from frozen snapshots only (RULES 2.6)
- [ ] Learned ranker behind the recommender contract, in shadow mode next to the rules
- [ ] Agreement report: where the ranker and the rules disagree, and on what

### Phase 14: Hardening and performance

- [ ] Load test of the busiest paths, with numbers recorded
- [ ] Security pass: dependency audit, image scan, permission matrix, secrets
- [ ] Backup and restore drill with timings
- [ ] Pin CI actions by commit SHA and image digests

### Phase 15: Go-live

- [ ] Production compose and TLS
- [ ] Deploy, rollback and incident runbooks
- [ ] First-day checklist and a short training guide per role

## Questions still open

1. Severity rules beyond critical, major and minor (ADR 0019).
2. The IITPL stamp image.
