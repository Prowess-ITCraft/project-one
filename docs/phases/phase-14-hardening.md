# Phase 14: Hardening, performance and a usability pass

Window: 15 to 24 Dec 2026 (planned). Status: mostly done (4 Oct 2026); open items below.

## What we found and fixed

**Backups were failing.** The restore drill's first step showed `pg_dump` refusing to run: the
backend image installed Debian's PostgreSQL 15 client against a PostgreSQL 16 server. The nightly
job had been failing the same way. The image now installs the 16 client from the PostgreSQL
project's repository.

**Rate limits looked like outages.** Under load, Nginx answered throttled requests with 503
("service unavailable"). It now answers 429 ("slow down"). The per-address limits were also too
tight for an office where everyone shares one public address (10 sign-ins a minute, 20 requests
a second); they are now 30 a minute and 60 a second. The API still limits each person (300
requests a minute) and locks accounts after failed sign-ins.

**Field engineers could not tell tasks apart.** Task refs restart in every project, so "T03
Sanitize system" appeared twice with nothing to say which customer. My tasks now shows the
customer and project on every task, splits "Needs you" from "Waiting on someone else", can filter
by project, and no longer repeats the device name in the title. A dependency check that matched
tasks by ref across projects was fixed at the same time.

**Smaller fixes.** Task history shows the date for anything not from today. Role names and
statuses are capitalised. The Director's nav starts with the Dashboard. A finished project links
straight to its report and certificate. Theme switch reads "match device" instead of "system".

## Security pass

| Check | Result |
| --- | --- |
| pip-audit (backend dependencies) | No known vulnerabilities |
| bandit | Clean. 57 findings reviewed and marked `# nosec` with a reason on the line: 49 SQL strings in the dataset engine (identifiers quoted by `q()`, values bound or validated), the documented demo password, plain-text mail templates, the backup subprocess. Asserts skipped project-wide: they only narrow types |
| npm audit (web app) | 2 findings in the PostCSS copy bundled inside Next.js. Build-time only, on our own CSS; the fix is Next 16 (breaking). Accepted until the Next upgrade |
| Permission matrix | Every route against every role, in the test suite |
| Images | Every third-party image in compose pinned by digest (tag kept for reading) |

## Load test (`scripts/loadtest.py`)

20 virtual users, no pause between requests, 60 seconds, through Nginx, on the development
laptop (Docker Desktop, Windows 11):

| Path | p50 | p95 |
| --- | --- | --- |
| `/auth/me` | 186 ms | 276 ms |
| `/projects` | 195 ms | 298 ms |
| `/field/my` | 232 ms | 398 ms |
| `/catalogue/items` | 189 ms | 278 ms |
| `/dashboard` | 308 ms | 705 ms |

No errors. The rest were 429s from the per-person limit, as designed: the test drives each demo
account as five users at once.

## Restore drill (`scripts/restore_drill.py`)

| Step | Time |
| --- | --- |
| Backup (same command as the nightly job) | 4.9 s |
| Fetch the dump (0.8 MB) | 2.2 s |
| Restore into a throwaway database | 3.4 s |

76 tables, row counts identical to the live database, 745 audit log entries. Recovery time at
today's size: about 6 seconds. Run it again before go-live and after any large data import.

## BOQ estimate (ADR 0021)

Added during this pass at Aditya's request: a **Draft BOQ estimate** button once the report and
questionnaire are in, labelled "Not approved", saved nowhere, with PDF and Excel.

## Still open

- (done) Python and Node base images in the Dockerfiles pinned by digest.
- (done) The Director dashboard now loads every project in four queries (projects, task runs,
  check-ins, deviations) instead of about seven per project. Same output, checked against the
  old code on the demo data.
- (done) Backend coverage is back to 85 percent (332 tests).
- Trivy image scan and TLS certificates are deployment steps (phase 15).
