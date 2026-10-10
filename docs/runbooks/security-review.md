# Security review: OWASP ASVS 4.0.3, Level 2

Reviewed 8 October 2026 by Aditya Kumar, on the code in this repository and the development
stack. Repeat it before each major release and after any change to sign-in, files or roles.

How it was checked: reading the code against each ASVS chapter, the automated tests named
below, `pip-audit` (no known vulnerabilities), `bandit -ll` on `backend/app` (no findings),
`npm audit --omit=dev` (see F1), the licence check (`scripts/licenses.py --check`), and the
chaos checks (`scripts/chaos.py`).

**Result: no critical or high finding open.** Two medium findings are accepted with reasons
(F1, F2), one medium finding must be fixed before go-live (F6), and the rest are low.

## By chapter

| ASVS chapter | Status | Evidence |
| --- | --- | --- |
| V1 Architecture | Pass | Modules talk only through contracts (import-linter, 3 contracts). Business rules only in services. Verification and reporting cannot import the learning module (ADR 0029). Security model in ARCHITECTURE.md, section 8. |
| V2 Authentication | Pass | Passwords 12 to 128 characters, common passwords refused, Argon2id. Authenticator (TOTP) required for staff, recovery codes single use. Lockout with doubling wait (15 minutes up to a day). Sign-in limit 60 a minute per address. The authenticator set-up token is refused once one is set up. |
| V3 Sessions | Pass | Access token 15 minutes, refresh 14 days and rotated on every use, reuse of an old refresh token ends the session family. Refresh cookie `HttpOnly`, `SameSite=Strict`, `Secure` in production. Sign out everywhere. Field app signs out after 15 minutes idle (ADR 0027). |
| V4 Access control | Pass | Deny by default. `tests/test_permission_matrix.py` checks every route for every role and fails if a route is unclassified. Object checks per project membership and per customer. The doer is never the verifier (tests per gate). Field engineers never receive a price field (`tests/test_field_role_never_sees_prices.py`, and the browser test `field-no-prices.spec.ts`). |
| V5 Validation and encoding | Pass | Pydantic strict models with `extra="forbid"`, length limits on every string. No `eval`; quantity rules use `core/safeexpr.py`. SQL only through SQLAlchemy with bound parameters. Jinja2 autoescape for PDFs. Search input is cut to letters and digits before it becomes a `to_tsquery` argument, and `LIKE` patterns are escaped. |
| V6 Cryptography | Pass | Fernet envelope encryption for device credentials and config exports, keys rotatable (`P1_FERNET_KEYS`). Tokens and upload links stored only as SHA-256 hashes. JWT HS256 with a key id and rotation; production refuses a short or development key. |
| V7 Errors and logging | Pass | RFC 9457 problem responses with stable codes, no stack traces to clients. Structured JSON logs without passwords, tokens or codes. Append-only audit log (a trigger refuses updates and deletes) with a hash chain, checked on the Audit log page (`GET /api/v1/audit-log/verify`). GlitchTip collects errors. |
| V8 Data protection | Pass with F2 | No prices in field caches; caches cleared on sign-out. `Cache-Control: no-store` on API answers. Personal data erasure for an account (audit subject keys). Backups are copied off the server every night; they are not encrypted at rest (F6). |
| V9 Communications | Pass | Only 80 and 443 published in production (ADR 0030); HSTS one year; TLS from Let's Encrypt or your own certificate. Internal services on a network with no published ports. |
| V10 Malicious code | Pass | No dynamic code loading. Dependencies pinned; images pinned by digest. Licence check passes. |
| V11 Business logic | Pass | State machines enforced in services with tests for every transition. Idempotency keys on money and state changes. Optimistic locking on editable rows. Offline work older than 72 hours refused. Per-user API limit 300 a minute. Minimum margin needs a named approver's reason (ADR 0028). |
| V12 Files | Pass | Size limit (50 MB), type sniffed from content, ClamAV scan, random object keys, served through the app with short-signed links and `nosniff`. Upload links: single use (claimed in one statement, so two uploads at once cannot both use it), 15 minutes, rate limited, scanned like any upload, and audited. |
| V13 API | Pass | Everything under `/api/v1`, listed in `docs/API_ROUTES.md` and kept current by a test. Strict CORS (production refuses http or localhost origins). CSRF: the refresh cookie is `SameSite=Strict` and state changes need the bearer token, which a cross-site page cannot read. Web Push only to known push services over HTTPS (no server-side request to an address a user chooses). |
| V14 Configuration | Pass with F1 | Production refuses unsafe settings at start (tested in `tests/test_prod_config.py`). Non-root containers, read-only file systems for the app services, health checks and resource limits. Security headers on the web app and the API; CSP in production. |

## Findings

| # | Finding | Severity | Status |
| --- | --- | --- | --- |
| F1 | `npm audit` reports PostCSS advisories (GHSA-6g55-p6wh-862q, GHSA-r28c-9q8g-f849 and two related) in the copy Next.js 15 bundles. PostCSS runs only at build time, on our own CSS, so the advisories (reading files through a crafted source map comment) cannot be reached by a user. The fix is Next.js 16, a major upgrade. | Medium | Accepted until the Next.js 16 upgrade; decision on the open list in TASKS.md |
| F2 | The web app's CSP allows `'unsafe-inline'` scripts, because Next.js writes small inline scripts into each page and a nonce would make every page dynamic. All user text is escaped by React, and no HTML from users is rendered. | Medium | Accepted; revisit with the Next.js 16 upgrade |
| F3 | A task held by a worker that is killed went back on the queue only after an hour (the Valkey default), so a nightly backup interrupted by a restart was not redone that night. | Low | Fixed: the visibility timeout is 10 minutes, longer than any task may run; checked by `scripts/chaos.py` |
| F4 | Push subscriptions follow the signed-in person on a shared phone: whoever signs in last gets the messages on that device. This is intended: on a shared phone, messages should reach whoever is using it. Turning phone messages off on the Account page removes that device. | Low | Accepted |
| F5 | GlitchTip and Uptime Kuma accounts are created by hand on first start and are not covered by the app's authenticator rule. They are on loopback only (VPN or SSH tunnel). | Low | Accepted; turn on their own two-step sign-in when setting them up |
| F6 | Database dumps in the backup bucket and the off-server copy are not encrypted. Anyone with the off-server disk can read customer data. | Medium | Open: encrypt the off-server copy (for example `age` with a key kept offline) before go-live; on the open list in TASKS.md |

## Next review

Before go-live on the real server (Phase 15): repeat the dependency audits, run
`scripts/chaos.py` and `scripts/restore_drill.py` on the server, and scan the built images with
Trivy.
