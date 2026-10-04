# Working notes

Things worth knowing before you change anything: the ground rules we agreed on, the defaults we
picked, machine quirks, stubs that later phases fill, and known gaps. Read this, then `TASKS.md`.

Maintained by Aditya Kumar.

## Ground rules

- Free and open-source components only (ADR 0011). That is why we run Valkey, not Redis.
- Old BOQs and PrismSuite reports keep arriving. Every file is converted once to compact JSON and
  kept as training data (ADR 0014). Treat the samples and the library as a product asset; never
  delete library data.
- Frontend: Next.js and React only, plain CSS. Keep it minimal and easy to use. Office staff are
  on desktops, field engineers on phones.
- No em dashes in docs, UI copy or generated documents.
- Never guess money, certification or security rules. If nobody has decided, pick the safest
  default, write an ADR, and put the question on the open list in `TASKS.md`.

## Defaults we picked (ADRs)

| Topic | Default | ADR |
| --- | --- | --- |
| Totals and GST rows | Off by default, per quote toggle | 0013 |
| Quote refs | One sequence per FY, issuer initials in the ref | 0013, 0017 |
| Pricing approval | Sales head or Director who did not edit | 0013 |
| Engineer hours | Mon to Sat, 10:00 to 18:00 IST, 30 min buffer | 0017 |
| OTP channel | Email to the sign-off contact (SMS, WhatsApp adapters off). Customer codes at check-in and hand over are switched off for now (flag `field_customer_codes`) | 0017, 0025 |
| Offline window | 72 hours | 0017 |
| Field states | Dependents may start after hand over | 0015 |
| Originals retention | Keep forever (0 days) | 0014 |
| PDF | WeasyPrint only, through `core/documents.py` | 0016 |
| First device brand | SonicWall, read from config exports, no remote access | 0019 |
| Certificate | Director signs, IITPL stamp, rescan required first | 0019 |
| Severity policy | Critical blocks the certificate and cannot be accepted | 0019 |
| Learned ranker | Shadow mode only, at least 20 accepted recommendations to train | 0020 |
| BOQ estimate | Any time after the report and questionnaire, saved nowhere, labelled | 0021 |
| Certificate wording | IITPL implemented the work; no "Implemented by"; Director and stamp only | 0022 |

## Machine quirks

- Windows 11, Docker Desktop (start it by hand), Python 3.12 in `backend/.venv`, Node 22.
- Use `backend/.venv/Scripts/python.exe`; the system Python lacks the dependencies. There is no
  `make` on Windows, use `scripts/dev.ps1`.
- WeasyPrint cannot load on Windows, so PDFs answer 503 `pdf_unavailable` outside the container.
- The full backend suite takes 10 to 12 minutes (testcontainers start Postgres, Valkey, MinIO).
  Run it in the background.
- Another local project may hold Docker containers; ports 9595 to 9606 are ours.
- Git Bash rewrites `/data/...` arguments into Windows paths; prefix `docker exec` commands with
  `MSYS_NO_PATHCONV=1`.
- After backend API changes: `python -m app.cli openapi`, then `npm run api-types` in `frontend/`.

## Stubs and interfaces

| Interface | Today | Filled by |
| --- | --- | --- |
| `fieldops.engine.ConfigCheckDriver` | `ExportDriver` reads SonicWall exports; everything else falls back to `AnswerDriver` (recorded values) | One driver per new brand, via `register_driver` |
| `verification.exports.ExportParser` | SonicWall (`.exp`, key/value text, JSON) | One parser per brand |
| `notifications.providers` SMS, WhatsApp | `UnconfiguredProvider` (recorded as skipped) | When a provider is chosen |
| `boq.recommend` learned ranker | Rules decide; a learned model can run in shadow mode (ADR 0020) | A new ADR before it may influence a BOQ |
| Market data feed | Manual entry | Later, behind the feed adapter |

## Known limitations

- The SonicWall key mappings are guesses until we see a real export. They are stored as
  unconfirmed, so a failure read through them goes to the verifier instead of sending work back.
  Confirm them with `/verification/inspect` on the first real export.
- Free-text targets such as "Managed, reachable on the management VLAN" cannot be judged by a
  driver; they are `not_checked` and the verifier decides.
- BOQ versions issued before 5 October 2026 have no stored PDF and are still rendered on
  request. Every version issued since keeps its quotation PDF in MinIO.
- The cleaning taxonomy is keyword rules. More real BOQs will show gaps; unlabelled lines are
  listed in the analysis as `other`.
- One PrismSuite sample and two BOQ samples. Parser and label quality need more.

## Still waiting on

1. Severity rules beyond critical, major and minor (ADR 0019). The default policy is in place.
2. The IITPL stamp image. The demo uses a placeholder clearly marked "DEMO STAMP".

## Changelog

- 2026-10-05: Customer codes at check-in and hand over switched off (ADR 0025). The code flow,
  its emails and its tests stay; the admin flag `field_customer_codes` turns it back on.
  Bug check: the task record PDF failed (500) for any task with steps still open, and it said
  "customer code confirmed" even when no code was used; both fixed. Worker logs no longer show
  routine messages as WARNING. A sweep of every document and detail route over all demo
  projects (913 requests) found no other server error.
- 2026-10-05: **Upload report and draft BOQ** on the project Overview: report, five questions
  and the priced estimate in one step (ADR 0024). Sales can import reports; audit engineers can
  save the questionnaire, draft the estimate and see prices. Same file twice is refused with
  `already_imported` and the button carries on. Sign-in fix: people were asked for the password
  and authenticator code again after 15 minutes, because the web app never renewed the session
  when the first request on a page was `/auth/me`. It now renews, so a sign-in lasts 14 days;
  the sign-in page also goes straight in when the session is still valid.
  Found in a full check the same day: the Field work tab started its live feed from the
  oldest 500 events, so a project with a longer history replayed every later event as new and
  reloaded the lists for each one until the rate limit answered 429 (now starts from the newest
  events, `?latest=true`, and reloads once per burst); the Audit intake list needed review
  rights even for people allowed to upload (new `prismsuite:read`); saving the questionnaire
  from the web app wiped `category_budgets`.
- 2026-10-05: Issuing a BOQ now stores the quotation PDF in MinIO (`boq/<id>/v<n>-quotation.pdf`)
  with its SHA-256 on the version (migration 0014). Downloads of an issued quotation return
  those exact bytes, so a later letterhead or template change cannot alter what the customer
  was sent. The database guard refuses any change to the stored key or hash.
- 2026-10-04 (night): Sign-in refused after browsing: the strict nginx and API sign-in limits
  also counted `/auth/me` and token refresh. Now only sign-in and MFA, 60 a minute per address.
  Accounts panel, Back on inner pages, Help guide, recovery codes at sign-in, sign-in redesign
  with Phosphor icons, all animation removed (ADR 0023). Production: DEPLOYMENT.md, a
  dry run of the full prod stack over HTTPS (20 checks pass), files through the app with
  signed links (MinIO was unreachable in prod, so downloads would have failed), stricter
  prod settings, `new_env.py`, `backup-export`, docs/API_ROUTES.md. Phone test of a whole
  field task found four bugs, all fixed: a save made while another was sending stayed on the
  phone as "waiting for signal"; the visit code could be asked for before the arrival photo;
  a double tap on a finished step gave an error; the photo button flashed back after sending.
  Incident runbook. Coverage 85 percent.
- 2026-10-04 (evening): Phase 14 pass. Backups were failing (pg_dump 15 against PostgreSQL 16),
  fixed and proven by a restore drill. Nginx limits answer 429 and fit an office behind one
  address. Load test numbers recorded. Bandit clean, images pinned. My tasks shows customer and
  project per task. BOQ estimate before approvals (ADR 0021). HTTPS three ways: Let's Encrypt,
  your own certificate, or behind a load balancer (operations guide 4a). Certificate names
  IITPL only, groups the work, fits one page (ADR 0022). Demo staff from the team list, with
  Satish Agadi as Director. Director dashboard batched (four queries for any number of
  projects). Dockerfile base images pinned by digest.
- 2026-10-04 (later): Phase 13, learning from accepted BOQs, in shadow mode (ADR 0020).
  BOQ version compare; the web app installs on phones. GitHub Actions and Dependabot removed.
- 2026-10-04: Verification (phase 9) and completion report and certificate (phase 10) built,
  with the Director dashboard, completion tab, certificate settings and the public QR page.
  Demo walker builds two projects, one through to a signed certificate. Playwright smoke tests.
  Demo staff are now the ITCraft / IITPL team.
- 2026-10-03: Field work rebuilt on the final state machine (ADR 0015) with OTP, evidence,
  verifier queue, notifications and live feed. Document corpus and cleaning (ADR 0014), shared
  PDF renderer (ADR 0016), plan PDF. Brand pass with the ITCraft and IITPL logos. New sign-in
  screen with a QR code for authenticator set-up. Outbox start-up guard (ADR 0018).
  `cli render-samples` renders all sample PDFs; a handful of PDF layout bugs fixed from that.
- 2026-10-01: Phases 4 to 6, planning code, first web app slice.
- 2026-09-30: Phases 1 to 3.
