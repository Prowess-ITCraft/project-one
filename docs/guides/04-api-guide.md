# API guide

Base address (dev): `http://localhost:9597/api/v1`. Interactive reference: `/docs`.
The machine-readable schema is at `/api/v1/openapi.json` (or `python -m app.cli openapi`).

## Conventions

- JSON in and out. Field names use `snake_case`.
- Money is a string with two decimals, for example `"66812.00"`. Floats are refused.
- Dates are `YYYY-MM-DD`; timestamps are UTC ISO 8601.
- Lists are paged: `?page=1&size=50` (size up to 200) and return
  `{items, page, size, total}`.
- Editable records carry `version`. Send it back when you update; a stale version returns 409.
- Requests that create money or change state need an `Idempotency-Key` header (16 to 128
  letters, digits, `-` or `_`). Repeating a request with the same key returns the first answer
  and the header `Idempotent-Replayed: true`.
- Errors use `application/problem+json`:

```json
{ "type": "https://errors.project-one.itcraft/segregation_of_duties",
  "title": "You do not have permission to do this", "status": 403,
  "detail": "You did this work yourself, so someone else must verify or approve it.",
  "code": "segregation_of_duties", "request_id": "..." }
```

Branch on `code`, show `detail` to people.

| Status | Meaning |
| --- | --- |
| 401 | Not signed in, or token ended |
| 403 | Signed in but not allowed (or a segregation rule) |
| 404 | Not found, **or you may not see it** |
| 409 | Conflict: stale version, duplicate, wrong state |
| 413 / 415 | File too big / file type not allowed |
| 422 | Validation failed; `errors` lists the fields |
| 423 | Account locked |
| 429 | Too many requests; see `Retry-After` |
| 503 | A needed service (for example the virus scanner) is unavailable |

## Signing in

```bash
# 1. login
curl -s localhost:9597/api/v1/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"..."}'
# -> {"status":"authenticated","access_token":"...","refresh_token":"..."}
#    or {"status":"mfa_required","challenge_token":"..."}
# 2. if mfa_required
curl -s localhost:9597/api/v1/auth/mfa/verify -H 'Content-Type: application/json' \
  -d '{"challenge_token":"...","code":"123456"}'
# 3. call the API
curl -s localhost:9597/api/v1/auth/me -H 'Authorization: Bearer <access_token>'
# 4. before the token ends (15 minutes)
curl -s localhost:9597/api/v1/auth/refresh -H 'Content-Type: application/json' \
  -d '{"refresh_token":"..."}'
```

Each refresh token works once. The answer contains the next one.

## Endpoint map

| Area | Path prefix | Highlights |
| --- | --- | --- |
| Auth | `/auth` | login, mfa, refresh, me, password, sessions |
| Users | `/users`, `/roles`, `/admin` | create, roles, unlock, reset, feature flags |
| Audit log | `/audit-log` | list with filters, `verify` the hash chain |
| Customers | `/customers` | customers, sites, contacts, representatives |
| Projects | `/projects` | projects, members, tracker, artifacts, gate submit/approve/reject |
| Gates | `/gates` | read and change gate settings |
| Public | `/public/acks/{token}` | customer acknowledgement links |
| Files | `/files` | upload, metadata, short-lived download link |
| PrismSuite | `/prismsuite/imports` | import, read report, corrections, resolutions, approve |
| Catalogue | `/catalogue` | items, vendors, categories, stock, market data, prices |
| Datasets | `/datasets` | versions, preview, profile, charts, pipeline steps, promote, export |
| Library | `/library` | drop files, status, collections, held rows |
| Corpus | `/library/corpus`, `/library/analysis`, `/library/rebuild` | canonical JSON per file, quality, label balance, price bands, outliers; rebuild (Admin) |
| Questionnaire | `/projects/{id}/brief` | read and save the customer brief |
| Infrastructure | `/projects/{id}/infra` | build, read and lock current and ideal states |
| Rules | `/infra/rules` | list, propose, approve rule changes |
| Gaps | `/projects/{id}/gaps` | draft, edit, add, lock the gap register |
| BOQ | `/projects/{id}/boq`, `/boq/{id}` | generate, edit operations, refresh prices, submit, pricing decision, issue, compare versions, accept, reopen, render |
| Plan | `/projects/{id}/plan`, `/planning` | generate, schedule, tasks, baselines, downtime, leave, lock, `render` (plan PDF) |
| Field work | `/projects/{id}/field` | `start`, `runs`, `summary`, `events?after=`, `stream` (server-sent events) |
| Field tasks | `/field` | `my`, `runs/{id}`, `accept`, `depart`, `codes/{check_in or handover}`, `check-in`, `evidence`, `prechecks-done`, `steps/{n}`, `values`, `configured`, `submit-evidence`, `hand-over`, `block`, `unblock`, `reassign`, `review-queue`, `decision`, `render` |
| Notifications | `/account/notification-preferences`, `/notifications` | mute optional messages; message log for auditors |
| Verification | `/verification` | `projects/{id}/deviations`, add or `accept` a deviation, severity `policy`, brand `mappings`, `inspect` an export |
| Dashboard | `/dashboard` | every visible project: stage, field progress, blocked work, open deviations (Director) |
| Completion | `/reporting` | `projects/{id}/conditions`, `waivers` and their `decision`, `field-summary`, `report/preview`, `reports` (lock, `pdf`), `certificates` (issue, `revoke`, `pdf`), `settings` (wording, stamp) |
| Learning | `/ml` | `report`, `training-sets` (list, freeze), `models` (list, train, `status`: shadow or retired) |
| Public | `/public/waivers/{token}`, `/public/certificates/{number}` | customer waiver acknowledgement; certificate check behind the QR code |

## Worked example: from report to approved audit

```bash
TOKEN=...   # access token of an Audit engineer on the project
# upload
curl -s -X POST localhost:9597/api/v1/files -H "Authorization: Bearer $TOKEN" \
  -F purpose=audit_report -F project_id=$PROJECT \
  -F file=@samples/"Shakti Equipments Pvt. Ltd. PrismSuite Audit Report.docx"
# import (note the idempotency key)
curl -s -X POST localhost:9597/api/v1/prismsuite/imports \
  -H "Authorization: Bearer $TOKEN" -H "Idempotency-Key: import-shakti-0001-abcdef" \
  -H 'Content-Type: application/json' \
  -d "{\"project_id\":\"$PROJECT\",\"file_id\":\"$FILE\"}"
# read what was extracted and what could not be read
curl -s localhost:9597/api/v1/prismsuite/imports/$IMPORT -H "Authorization: Bearer $TOKEN"
```

The `read_report.fields` list shows each field's status (`ok`, `missing`, `unreadable`,
`conflict`, `corrected`). Fix with `POST .../corrections` (a value and a reason) or confirm
with `POST .../resolutions`. A different person then calls `POST .../approve`.

## Who can call what

The authoritative answer is `GET /api/v1/roles` (roles and their permissions) and, per
endpoint, the padlock and description in `/docs`. The automated matrix test guarantees the
code matches.

## Field work from the phone (offline safe)

Every engineer action accepts `client_event_id` (a UUID made on the phone) and `captured_at`
(when it really happened, up to 72 hours ago). Sending the same action twice changes nothing,
so the phone's queue can simply retry. Evidence uses `client_id` the same way.

```bash
# accept, then ask the customer for the visit code (it goes to their email)
curl -X POST $API/field/runs/$RUN/accept -H "Authorization: Bearer $T" \
     -d '{"client_event_id":"6f1c...","captured_at":"2026-11-10T09:58:00+05:30"}'
curl -X POST $API/field/runs/$RUN/codes/check_in -H "Authorization: Bearer $T"
# arrival photo (requirement 0), then check in with the code the customer reads out
curl -X POST $API/field/runs/$RUN/evidence -H "Authorization: Bearer $T" \
     -F requirement_index=0 -F client_id=9a2e... -F file=@site.jpg
curl -X POST $API/field/runs/$RUN/check-in -H "Authorization: Bearer $T" \
     -d '{"code":"482913","lat":19.07,"lng":72.87}'
```

Each response is the whole task with `next_action`, one sentence saying what to do next.
A state that is not allowed answers 409 `bad_state`; missing evidence answers 409
`evidence_missing` with the list. Live updates: `GET /projects/{id}/field/stream` sends
server-sent events and closes after 25 seconds; reconnect with `Last-Event-ID`. Without SSE,
poll `GET /projects/{id}/field/events?after=<last seq>`.
