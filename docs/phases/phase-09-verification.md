# Phase 9: Verification and the Director dashboard

Window: 16 to 24 Nov 2026 (planned). Status: built (4 Oct 2026).

## Goal

Check what was actually configured on site against the target baseline, keep a register of
everything that does not match, and give the Director one screen that shows where every project
stands.

## Features added

**Reading configuration exports**

- A parser per brand turns an export into flat key and value facts. SonicWall is first (ADR 0019):
  the classic `.exp` settings file, plain `key=value` text, and JSON from the SonicOS API.
- Which export key proves which target setting is data (`brand_field_maps`), not code. Each
  mapping has a rule: `truthy`, `falsy`, `eq`, `ne`, `in`, `record` and a few more.
- `POST /verification/inspect` shows what an export contains and which target settings the
  current mappings would judge. That is how the first real export gets checked before anyone
  trusts the mappings.
- Mappings start as unconfirmed. A failure read through an unconfirmed mapping never sends work
  back on its own; it goes to the verifier with the reason.

**The check during field work**

- `ExportDriver` is registered with field work for device types that have a brand parser. It
  judges what the export proves and falls back to the engineer's recorded values for the rest.

**Deviation register**

- A failed setting opens a deviation, or updates the open one. A later passing check resolves it.
- A verifier can add a deviation by hand for something the check could not judge, or accept one
  with a reason. The person who did the work cannot.
- Severity policy (`/verification/policy`): which severities block the certificate and which a
  verifier may not accept. Default: critical, for both. Those are fixed or waived (phase 10).

**Director dashboard** (`GET /dashboard`)

- Every active project the caller can see: stage, tasks closed, blocked work with reasons,
  check-ins today, open deviations by severity, and whether it is behind plan. Totals on top.

## Acceptance

| Criterion | State |
| --- | --- |
| Actual vs target compared per device | Done, tested with `.exp`, text and JSON exports |
| Deviations raised with severity and resolved by a later pass | Done, tested |
| Verifier cannot accept a critical deviation | Done, tested |
| The doer cannot accept a deviation on their own work | Done, tested |
| Director sees live status of every project | Done (API and dashboard screen) |

## Decisions

ADR 0015 (field states), ADR 0019 (SonicWall first, evidence only, severity rules to follow).

## Known limitations

- No real SonicWall export in the samples yet, so the key names are educated guesses and stay
  unconfirmed until one arrives.
- Other brands (Sophos, Fortinet, Cisco) need one parser and one set of mappings each.
- Severity rules beyond critical, major and minor are still to be written up.

## Demo script

1. Run `python -m app.cli demo-projects` and sign in as the Director (Satish Agadi in the demo data).
2. Open Dashboard: the finished project is complete, "Plant network refresh" shows blocked work
   and an open critical deviation.
3. Open the in-progress project, Field work tab, and the task that was sent back: the failed
   setting and the deviation it opened.
4. As the technical lead, try to accept the critical deviation: it is refused with the reason.
