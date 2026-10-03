# Rules

Every change follows these. Changing a rule needs the owner's approval and an ADR.

## 1. Non-negotiables

1. `docs/` is the source of truth. Read `MEMORY.md` and `TASKS.md` at the start of a session;
   update them at the end. A change in behaviour without the matching doc update is not done.
2. Never guess business rules that affect money, certification or security. Ask, or record a
   safe default as an ADR and flag it in the batch report.
3. No placeholder code or `TODO: implement` in delivered work. Stubs only behind a named
   interface that a later phase fills, listed in `MEMORY.md`.
4. The person who does a piece of work never verifies or approves it (`ensure_different_people`).
5. Field engineers never receive prices, in any response, export or notification.
6. Every PDF is made by WeasyPrint through `core/documents.py`. No other generator without an ADR.
   `pdfplumber` is for reading only.
7. Free and open-source components only (ADR 0011).
8. No em dashes in docs, UI copy or generated documents. Sentence case. Plain words.

## 2. Data rules (the library and corpus)

1. **Sample and library data is a product asset.** Never delete a library file, corpus record
   or dataset version by hand. Soft delete only, with an audit entry.
2. Every incoming document is hashed; the same file never adds rows twice.
3. A document is parsed once into canonical JSON (`p1.corpus.v1`). Code downstream reads the
   JSON or the Parquet collections, never the original binary.
4. Low-confidence rows go to quarantine for a person. They are never dropped and never trusted
   silently.
5. Cleaning steps are deterministic and versioned (`CLEANING_VERSION`). A change to cleaning
   bumps the version and re-runs as a new dataset version; old versions stay readable.
6. Models train only on **frozen** dataset versions with a data card. Training never reads live
   tables.
7. Customer names and contact details in the corpus are kept for provenance but never leave the
   system in exports used for model sharing. Training features use labels, quantities and
   prices, not personal data.
8. `samples/` files are part of every test run. A parser change that breaks a sample golden test
   does not merge.

## 3. Production hardening checklist

- Strict input validation (Pydantic v2 strict, `extra="forbid"`), size limits on bodies and files.
- Errors as RFC 9457 `application/problem+json` with stable codes.
- Valkey rate limiting and account lockout.
- RBAC plus object-level checks, deny by default. The permission matrix test covers every route.
- Security headers, strict CORS, CSRF protection for cookie auth.
- Uploads: type sniffed, ClamAV scanned, random object keys, short-lived presigned URLs.
- Envelope encryption for device credentials and config exports; device access read-only.
- Append-only audit log entry for every mutation, in the same transaction.
- Optimistic locking on editable rows; idempotency keys on POSTs that change money or state.
- Money as `Decimal`, `NUMERIC(14,2)`, INR, GST per line, central rounding, Indian grouping.
- UTC stored, IST shown, April to March financial year helper.
- Timeouts, retries and circuit breakers on external calls.
- Soft delete with restore. Nightly backups with a tested restore runbook.
- `/healthz`, `/readyz`, `/metrics`. API under `/api/v1`.
- Non-root containers, pinned versions, healthchecks, resource limits, Trivy clean of criticals.

## 4. Coding standards

- Python 3.12, `ruff` (lint and format), `mypy --strict`, import-linter.
- Business rules live only in `service.py`. Routers translate HTTP; contracts expose data.
- Raise `ValidationFailed`, `Conflict`, `NotFound`, `Forbidden` with a helpful message and a
  stable `code`. Messages say what happened and how to fix it.
- Never `eval`. Quantity rules use `core/safeexpr.py`.
- Frontend: TypeScript strict, Next.js and React only, plain CSS tokens, typed client generated
  from OpenAPI (never hand-written types).

## 5. Testing

- Real PostgreSQL, Valkey and MinIO through testcontainers. The app connects as the restricted
  runtime role.
- Coverage bar: 85% on services and domain logic. Every state machine transition, permission
  and money rule has a test.
- Golden tests against `samples/` for parsers and rendered documents.
- Property tests (hypothesis) for parsers, money and the expression DSL.

## 6. Git and CI

- Branch from `main` as `feature/<short-name>`. Small pull requests with the template checklist.
- CI: lint, types, import boundaries, tests, bandit, pip-audit, Trivy, SBOM, image build,
  migration up and down. All green before merge.
- Never commit `.env`, keys, customer data outside `samples/`, or generated binaries.

## 7. Definition of done

A task is done when: the code and migration are in, tests pass and cover the new rules, the
permission matrix passes, `docker compose up` is healthy, the OpenAPI types are regenerated if
the API changed, `TASKS.md` and `MEMORY.md` are updated, and any decision is an ADR.
