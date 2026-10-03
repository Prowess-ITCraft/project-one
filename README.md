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
| Running it on a server | [Operations guide](docs/guides/03-operations-guide.md) |
| Calling the API from another tool | [API guide](docs/guides/04-api-guide.md) |
| Keeping the docs complete | [Documentation map](docs/DOCUMENTATION_MAP.md) |
| Showing the work to colleagues | [Roadmap](docs/ROADMAP.md) and [phase pages](docs/phases/README.md) |
| Learning the tech stack and how the main processes work | [Tech stack and processes](docs/guides/05-tech-stack-and-processes.md) |
| Wondering why something was done this way | [Decision records](docs/decisions) |
| Picking the work up again | [MEMORY.md](docs/MEMORY.md), then [TASKS.md](docs/TASKS.md) |
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

Phases 1 to 8 are built (Batch 1, phases 6 to 8, finished on 3 October 2026), with 299 backend tests passing at
86 percent coverage. The web app covers every stage up to field work, including the field engineer's phone flow
and the verifier's review queue. Next: phases 9 to 11 (verification engine, completion report and certificate,
frontend foundation). Exact state: [TASKS.md](docs/TASKS.md); plan to December: [roadmap](docs/ROADMAP.md).
