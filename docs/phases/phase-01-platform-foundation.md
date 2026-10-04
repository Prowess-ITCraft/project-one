# Phase 1: Platform foundation

Window: 28 Sep to 2 Oct 2026 (planned). Status: built.

## Goal

A production-grade base that every later module sits on, so no module has to solve security,
logging, money, time, background work or storage again.

## Features added

**Application core (`backend/app/core`)**

- Settings read from the environment and Docker secrets; the app refuses to start in
  production with dev keys or missing encryption keys.
- Async PostgreSQL access with a restricted runtime role. The migration owner and the
  runtime role are different database users.
- Errors returned in the standard `application/problem+json` format with stable error codes.
  No stack traces ever reach a client.
- Structured JSON logs carrying a request ID on every line and every response.
- Pagination with a hard cap of 200 rows per page.
- Security headers, a strict CORS allow-list and request body size limits.
- Rate limiting per user and per IP on Redis, stricter on sign-in, upload and public links.
- Idempotency keys on requests that create money or change state: a repeated request returns
  the original answer instead of doing the work twice.
- Optimistic locking (`version` column) so two people editing the same record cannot
  silently overwrite each other.
- Money in `Decimal` only, rounded half-up to paise, with Indian number formatting
  (`₹ 1,09,653.00`). Floats are rejected.
- Time stored in UTC and shown in IST; Indian financial year helper (April to March) for
  quote numbers such as `ITCraft/NN/2627/030`.
- Gap-free, collision-safe counters for project codes and quote numbers.
- Envelope encryption for sensitive fields with key rotation support.
- Retry, timeout and circuit breaker helper for every call to an outside service.
- Feature flags stored in the database.

**Reliable background work**

- Transactional outbox: a change and the event announcing it are saved together, so a
  failing email or notification can never undo a business change. Failed handlers retry with
  increasing delays and end in a "dead" state for follow-up.
- Celery worker and scheduler: outbox dispatch every 5 seconds, daily price expiry,
  nightly database backup to object storage with 30 day retention.

**Operations**

- `/healthz` (is it alive), `/readyz` (are database, Redis and storage reachable) and
  `/metrics` for Prometheus.
- One command starts everything: API, worker, scheduler, PostgreSQL, Redis, MinIO storage,
  ClamAV virus scanner, Nginx proxy, Prometheus, Grafana, Mailpit (dev email capture) and
  Flower (dev Celery monitor).
- Operator commands: `seed`, `create-admin`, `expire-prices`, `dispatch-outbox`, `backup`,
  `init-storage`, `openapi`.
- Containers run as a non-root user with a read-only filesystem, dropped capabilities and
  memory limits.
- Docker Compose in three files: base, dev (ports on localhost) and prod (only the proxy is
  public).
- Windows script `scripts/dev.ps1` and a Makefile give the same commands.

**Quality gates**

- Ruff, strict mypy, import-linter (modules may only talk through `contracts.py`), bandit,
  pip-audit, gitleaks, CodeQL, Trivy image scan and SBOM in GitHub Actions.
- Migration checks: apply, roll back and detect model drift.
- Pre-commit hooks, pull request template, Dependabot.

## Acceptance criteria

| Criterion | State |
| --- | --- |
| One command starts everything healthy | Done; first full start verified on 30 Sep |
| Tests green with real containers | 92 tests pass against real PostgreSQL, Redis and MinIO started by the test suite |
| CI passes | Workflows written; they run once the repository is pushed to GitHub |
| No critical image vulnerabilities | Trivy runs in CI; not yet run locally |

## Numbers

- 18 core tests (money properties, financial year, crypto, sequences, outbox retry and dead
  letters, audit chain, rate limits).
- 2 import-linter contracts kept (module boundaries, core independence).

## Decisions

ADR 0005 (ports and proxy), 0006 (MinIO image), 0007 (Windows tooling), 0008 (compose modes).

## Known limitations

- CI actions are pinned by version tag, not commit SHA. Dependabot and a pinning pass should
  fix this before go-live.
- Image digests other than MinIO are not pinned yet.
- TLS certificates are a deployment step (Phase 15).

## Demo script

1. `scripts\dev.ps1 up`, then open `http://localhost:9597/healthz` and `/readyz`.
2. Open Grafana at `http://localhost:9604` and Mailpit at `http://localhost:9605`.
3. `scripts\dev.ps1 backup` and show the dump in MinIO.
