# Project One

Project One is the ITCraft / IITPL platform that turns a **PrismSuite IT audit** into a
**verified, certified implementation**.

```
Audit report  ->  Current vs ideal IT  ->  Gaps  ->  BOQ and quotation
     ->  Implementation plan  ->  Gated field work  ->  Verification  ->  "Certified by IITPL"
```

Every stage ends with a named approval gate. Nothing moves on until the gate is recorded,
the person who does the work never approves it, and every change is written to a
tamper-evident audit log.

## Where to start

| You are | Read |
| --- | --- |
| New and want to run it on your laptop | [Beginner's guide](docs/guides/01-beginners-guide.md) |
| A developer who will change the code | [Developer guide](docs/guides/02-developer-guide.md) |
| Putting it on a server for real use | [DEPLOYMENT.md](DEPLOYMENT.md), step by step |
| Running it on a server day to day | [Operations guide](docs/guides/03-operations-guide.md) |
| Calling the API from another tool | [API guide](docs/guides/04-api-guide.md) and every route in [API_ROUTES.md](docs/API_ROUTES.md) |
| Keeping the docs complete | [Documentation map](docs/DOCUMENTATION_MAP.md) |
| Showing the work to colleagues | [Roadmap](docs/ROADMAP.md) and [phase pages](docs/phases/README.md) |
| Learning the tech stack and how the main processes work | [Tech stack and processes](docs/guides/05-tech-stack-and-processes.md) |
| Wondering why something was done this way | [Decision records](docs/decisions) |
| Picking the work up again | [NOTES.md](docs/NOTES.md), then [TASKS.md](docs/TASKS.md) |
| How the data library and corpus work | [Data guide](docs/guides/06-data-guide.md) |

## Quick start (Windows, about 15 minutes)

1. Install Docker Desktop, Python 3.12 and uv (see the beginner's guide).
2. Copy `.env.example` to `.env` and fill the secrets (the guide shows how).
3. `scripts\dev.ps1 up`
4. Open http://localhost:9597 for the web app and http://localhost:9597/docs for the API reference.

## What is in the repository

```
backend/    FastAPI application, database migrations and tests
frontend/   Next.js web app (plain CSS, no component library)
infra/      Nginx, Prometheus, Grafana and PostgreSQL set-up files
docs/       Guides, phase pages, roadmap and decision records
samples/    The real PrismSuite report and the two ITCraft BOQs used by the tests, and their corpus JSON
inbox/      Drop old BOQs and reports here; the worker reads them every 5 minutes (never committed)
brand/      ITCraft and IITPL logos from their websites
scripts/    Helper commands for Windows (dev.ps1)
.github/    Automated checks (tests, security scans, image build)
```

## Status

Phases 1 to 10 are built, with 320 backend tests passing at 84 percent coverage (4 October 2026). The web app
covers every stage from audit intake to the signed certificate, including the field engineer's phone flow, the
verifier's review queue and the Director's dashboard. Next: the rest of phase 12, then learning from the library,
hardening and go-live. Exact state: [TASKS.md](docs/TASKS.md); plan to December: [roadmap](docs/ROADMAP.md).
