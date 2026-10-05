# Developer guide

For people who will read, change or extend the code.

## 1. Architecture in one page

Project One is a **modular monolith**: one deployable FastAPI application split into strict
modules. A change should touch one module and, at most, its public contract.

```
backend/app/
  core/       shared plumbing: config, db, errors, logging, money, time, outbox, crypto, limits
  modules/
    identity/     users, roles, permissions, MFA, sessions
    audit_log/    append-only audit trail
    customers/    customers, sites, contacts, projects, stage gates
    files/        upload pipeline, ClamAV, object storage
    prismsuite/   versioned parsers -> AuditSnapshot, review and approval
    catalogue/    products, services, vendors, price book
    datasets/     library inbox, document corpus, cleaning, quality, versions, EDA
    infra/        current and ideal model, rule DSL, gap engine
    boq/          templates, recommender, editor, versions, quotation rendering
    planning/     tasks, scheduler, baselines, plan document
    notifications/ email (SMS and WhatsApp adapters), preferences, retries
    fieldops/     field task state machine, evidence, OTP, engine check, live feed
  main.py     builds the app; modules/registry.py lists installed modules
  worker.py   Celery app and schedules
  cli.py      operator commands
```

Each module uses the same files:

| File | Purpose |
| --- | --- |
| `api.py` | Routers: HTTP in, HTTP out, nothing else |
| `schemas.py` | Pydantic input and output models (strict, `extra="forbid"`) |
| `models.py` | SQLAlchemy tables |
| `service.py` | **All business rules live here and only here** |
| `contracts.py` | The only file other modules may import |
| `handlers.py` | Outbox subscribers (reacting to other modules' events) |
| `tests/` | Module tests |

### Boundary rules (enforced by import-linter)

- A module never imports another module's `models`, `service` or `repository`.
- Cross-module calls go through the other module's `contracts.py`.
- Side effects in other modules go through the **outbox**: publish an event inside your
  transaction, and a worker delivers it. A failing subscriber never rolls back your change.
- `core` never imports a module.

Run the check: `backend\.venv\Scripts\lint-imports.exe --config .importlinter`.

## 2. Setting up for development

```powershell
cd backend
uv sync                      # creates .venv with runtime and dev tools
.venv\Scripts\python.exe -m pytest -q        # needs Docker running
.venv\Scripts\python.exe -m ruff check app tests
.venv\Scripts\python.exe -m ruff format app tests
.venv\Scripts\python.exe -m mypy app tests
```

Use `backend\.venv\Scripts\python.exe` explicitly. The shell's default Python does not have the
dependencies.

## 3. The request life cycle

1. Nginx adds a request id and passes the request on.
2. Middleware: request context, security headers, CORS, body size limit.
3. Router dependencies: `get_session`, then `require(P.SOMETHING)` which loads the signed-in
   person, checks the token and session, rate limits, and checks permissions.
4. The router calls `service.something(session, principal, ...)`.
5. The service applies object-level checks, business rules, writes data, **writes an audit
   entry, publishes outbox events, then commits once**.
6. The router turns the result into a schema. Errors become `application/problem+json`.

## 4. Conventions you must follow

- **Deny by default.** Every route uses `Depends(require(P.X))` (or `CurrentPrincipal`). A
  test lists every route and every role and fails if a new route is unprotected.
- **Object-level access.** After the permission check, verify the person may see *that* record
  (for example `get_project_ref(...)` for anything inside a project).
- **Segregation of duties.** Use `ensure_different_people(doer_id, approver_id, "what")`.
- **Audit everything that changes data**: `record(session, audit_context(principal), action=...,
  entity_type=..., entity_id=..., before=..., after=...)` in the same transaction.
- **Optimistic locking.** Editable records use the `Versioned` mixin; inputs carry `version`;
  a stale write returns 409.
- **Idempotency.** POSTs that create money or change state use `Idem` and `run_idempotent`.
- **Money** is `Decimal`; use `app.core.money` types (`Amount`, `NonNegativeAmount`,
  `RatePercent`). Never floats.
- **Time** is UTC in the database and IST for display. Use `utcnow()` and `today_ist()`.
- **No prices in field-work responses**, ever (ADR 0003).
- **Plain writing**: no em dashes in docs, UI copy or generated reports.
- **Errors**: raise `ValidationFailed`, `Conflict`, `NotFound`, `Forbidden` with a helpful
  message and a stable `code`.

## 5. Recipes

### Add an endpoint to an existing module

1. Add input and output models to `schemas.py`.
2. Add the rule to `service.py` (permission check, object check, audit, commit).
3. Add the route in `api.py`, protected with `require(...)`.
4. Add tests in the module's `tests/`. The permission matrix test picks the route up by itself.

### Add a new permission or role

Edit `modules/identity/permissions.py` (`P` and `ROLE_PERMISSIONS`). Keep it minimal; the
matrix test will tell you which roles reach which routes.

### Add a table or change a column

1. Edit `models.py`.
2. Generate a migration against a scratch database:
   `backend\.venv\Scripts\python.exe -m tests._autogen "what changed" 0003`
   (it starts a temporary PostgreSQL, applies all migrations, autogenerates the next one).
3. Read the generated file in `backend/migrations/versions`. Fix anything hand-written
   (triggers, data) and make sure `downgrade()` works.
4. Run the tests; they apply all migrations from scratch.

### Add a new module

1. Create `modules/<name>/` with the files above and a `tests/` folder.
2. Add the name to `MODULES` in `modules/registry.py` (and `_HANDLER_MODULES` if it has
   outbox handlers). Routers are discovered from `api.routers`.
3. Add the module to the lists in `.importlinter`.
4. Write `contracts.py` first; other modules will depend on it.

### Add a PrismSuite parser version

1. Copy `prismsuite/parsers/docx_v1.py` to a new class with a new `name` (for example
   `prismsuite.docx.v2`), implement `detect()` and `parse()`.
2. Call `register(...)` at the bottom and import it in `parsers/__init__.py`.
3. Add a sample file under `samples/` and a golden test. Nothing else changes.

### React to another module's event

```python
# modules/<yours>/handlers.py
@subscribe("catalogue.price_expired", name="yourmodule.on_price_expired")
async def on_price_expired(session, event): ...
```

Handlers must be idempotent (they can run twice). Subscriber names are unique.

### Add a scheduled job

Add a task to `worker.py` and an entry in `beat_schedule`. Keep the logic in a module's
service so it can be tested without Celery (see `catalogue.service.expire_prices`).

## 6. Testing

- Tests use **real** PostgreSQL, Redis and MinIO via testcontainers. The app connects as the
  restricted runtime role, exactly like production.
- Fixtures: `client` (HTTP client on the app), `db` (session), `clean_state` (empties all
  tables between tests). Helpers in `tests/helpers.py`: `make_user`, `make_workspace`,
  `make_customer`, `upload_sample_report`, `idem()`.
- The virus scanner is replaced by a fake that flags the standard EICAR test string.
- `tests/test_permission_matrix.py` checks every route against every role.
- Parser tests use the real samples in `samples/` plus hypothesis fuzzing.
- Coverage goal: 85% on domain and service layers. Check with `pytest --cov=app`.

## 7. Roles and permissions (summary)

| Role | Main abilities |
| --- | --- |
| Admin | Users, gate settings, audit verify, feature flags, catalogue edit. No prices. |
| Director | Approves gates, reviews audits, reads prices, and holds every Admin permission (ADR 0026). MFA required. |
| Sales head | Customers, projects, members, prices, approves BOQ gate. |
| Sales manager | Customers, projects, enters prices. |
| Solution architect | Imports, reviews and approves audits, edits catalogue. |
| Audit engineer | Uploads and imports audits, reviews. |
| Technical lead | Reviews and approves audits and gates. |
| Project manager | Project members, plan gate. |
| Field engineer | Catalogue (no prices), uploads evidence. |
| Customer representative | Reads their own company and projects, acknowledges gates. |

The exact matrix is `ROLE_PERMISSIONS` in `identity/permissions.py`, also available at
`GET /api/v1/roles`.

## 8. Git workflow

- Branch from `main`: `feature/short-name`. Small pull requests.
- Commit messages: what and why in the first line. The pull request template lists the checks.
- Run `scripts/dev.ps1 lint`, `typecheck` and `test` before pushing (no hosted CI for now). Pre-commit
  runs ruff, gitleaks and import-linter on each commit.
- Never commit `.env`, keys or customer data.

## 9. Code map for common questions

| Question | Look at |
| --- | --- |
| How is a password checked? | `identity/security.py`, `identity/service.py: login` |
| Where are tokens issued and rotated? | `identity/service.py: _issue_tokens, refresh` |
| Where are gate rules? | `customers/service.py: submit_stage, approve, reject` |
| How does an upload get scanned? | `files/service.py: ingest`, `files/scanner.py` |
| How does the parser work? | `prismsuite/parsers/docx_v1.py` |
| How is a price judged expired? | `catalogue/service.py: state_of` |
| How do events get delivered? | `core/outbox.py`, `worker.py: dispatch_outbox` |
| How is the ideal state worked out? | `infra/dsl.py`, `infra/facts.py`, `infra/service.py` |
| How is a BOQ drafted? | `boq/generate.py`, `boq/templates.py`, `boq/recommend.py` |
| How are BOQ edits applied? | `boq/draft.py` (operations), `boq/service.py: edit` |
| How does a quantity rule run? | `core/safeexpr.py` |
| How is the quotation rendered? | `boq/render.py`, `boq/html/quotation.html` |
| How does the library pick a parser? | `datasets/library.py`, `datasets/importers/` |
| How is a file turned into corpus JSON? | `datasets/corpus.py`, `datasets/extract.py` |
| Where are cleaning and labels? | `datasets/cleaning.py` (bump `CLEANING_VERSION` on change) |
| How is data quality scored? | `datasets/quality.py` |
| How are PDFs made? | `core/documents.py` (the only WeasyPrint user) |
| How does a field task move? | `fieldops/service.py`, states in `fieldops/models.py` |
| How is configuration checked? | `fieldops/engine.py` (`ConfigCheckDriver`) |
| Where are the web app tabs? | `frontend/components/project/*.tsx` |
