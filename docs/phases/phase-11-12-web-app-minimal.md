# Phases 11 and 12: web app, minimal edition

Window: pulled forward from 30 Nov to 16 Dec in the mock plan, built on 1 Oct 2026 as a first
slice against the screens the backend already supports. Status: first slice built.

## Goal

A calm, professional, very simple interface for the people who use the system every day,
built with as little machinery as possible.

## Features added

- **Sign in** with email and password, then the authenticator code for Director and Admin.
  First-time set-up of the authenticator and the one-time recovery codes are part of the flow.
- **Projects**: list with stage and status; create a project and, if needed, its customer in
  one form.
- **Project page**: the stage rail (eight stages on one line: approved, current, locked),
  the current stage with its next action, the team, and approvals so far.
  - Submit a locked output for approval, approve it or send it back with a reason.
  - The page tells you when you cannot approve something because you did the work.
- **Audit reports**: upload the PrismSuite Word file and import it from the project page.
- **Audit review**: what was read (scores, asset counts, upgrade needs, vulnerabilities),
  a list of fields that need attention with a reason box to confirm or correct each, the
  history of reviewer changes, and approve or reject. Approval stays disabled while items block it.
- **Catalogue**: search and filter products and services. People with price access also see
  selling price and a price badge (valid, expires in N days, expired, none).
- **Prices to refresh**: the work list of missing, expired and expiring prices.
- **Item page**: inclusions, stock, dates, current price with margin, history, and a form to
  enter a new price (with a live warning when selling is below cost).
- **Users** (Admin): list, create, unlock, deactivate and reactivate.
- Light and dark themes following the system, with a manual switch.
- Loading skeletons, empty states that invite the next step, and errors that say what happened
  and how to fix it.

## Design

See `docs/design/frontend-design-plan.md`. Plain CSS tokens, one accent colour, hairlines
instead of cards, sentence case, no icon or component libraries. The stage rail is the one
memorable element. Responsive to 360 px: the sidebar becomes a top bar, tables become stacked
rows and the rail turns vertical.

## Numbers

- 8 routes, about 110 kB of JavaScript on first load.
- Two runtime dependencies: Next.js and React.
- API types generated from the backend schema (about 5,800 lines, never hand written).

## Acceptance

| Criterion | State |
| --- | --- |
| Responsive to 360 px, keyboard focus, AA contrast, reduced motion | Built; manual review recorded in PROGRESS.md |
| Typed API client generated from OpenAPI | Done |
| Sign in with MFA | Done |
| Planner, field engineer mobile flow, dataset workspace, BOQ editor, Director live view | Not yet: their backends arrive in phases 4 to 9 |

## Known limitations

- No automated browser tests yet (Playwright arrives with phase 12 proper).
- Offline queue and PWA install for engineers come with the field operations work.
- Customer sign-in is not part of this slice.

## Demo script

1. Sign in as the Admin, open Users, create a Solution architect and an Audit engineer.
2. Create a project, add both to the team (as a Sales head).
3. As the audit engineer upload the Shakti report, open the review, confirm the firewall conflict.
4. As the architect approve it; submit the gate; approve as a technical lead.
5. Open Catalogue, then Prices to refresh, enter a new price.

## Brand pass and Batch 1 screens (3 Oct 2026)

- **Brand:** ITCraft's logo (from itcraft.net.in) in the sidebar, sign-in and favicon; IITPL's mark (from
  iitpl.co.in) on the sign-in panel, because IITPL certifies the work. Accent changed from a generic cobalt to
  ITCraft blue #2C629F; completed stations use a deeper circuit green (#2A9445) because the logo green is too light
  to carry meaning. Tokens and the contrast table are in `DESIGN.md`.
- **My tasks** (field engineer, phone first): tasks by day with the next step in plain words.
- **Task page**: the nine-state timeline with a drawn loop when work is sent back, one big next action, camera
  capture for evidence, the customer code entry, ordered steps, what the device shows, and an offline outbox in
  IndexedDB (photos included) that sends when signal returns. Project managers unblock and reassign here;
  verifiers approve or send back here.
- **Review** (technical lead): handed over tasks, oldest first, never your own.
- **Project, Plan tab**: draft, downtime windows, schedule, lock, plan PDF, targets per device.
- **Project, Field work tab**: counts per state on the trace, what needs attention, all tasks, live feed (server-sent
  events with polling fallback).
- **Library**: Files (status names fixed, held lines confirmed in place), Corpus (document drawer with labels and
  the text read), Data quality (label balance, price bands per gap type, outliers, rebuild for Admin).
- Still only Next.js and React at runtime. The impeccable design hook is on for this project (`.claude/`).
