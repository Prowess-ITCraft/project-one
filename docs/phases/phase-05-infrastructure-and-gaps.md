# Phase 5: Infrastructure model, rule library and gap engine

Window: 19 to 27 Oct 2026 (planned). Status: built.

## Goal

From an approved audit and a short customer questionnaire, produce the current state, the
ideal state and a prioritised gap register, with every step reviewable by a person.

## Features added

- **Questionnaire (project brief).** Company size, budget tier, users now and in 12 months,
  sites, preferred and excluded brands, budget ceiling, assets to keep, compliance needs.
  It chooses which rules apply and steers the BOQ.
- **Current infrastructure.** Built from the approved audit: endpoints, servers, firewalls,
  storage, switches, routers, the four lens scores, and what is unknown. Locked as the
  baseline for the Current IT gate.
- **Rule library.** Each rule says "for this company size and tier, this is the target" and
  how to test the current state. Rules use a small JSON condition language with three
  answers: true, false, unknown. Unknown never becomes a guess, it becomes "verify on site".
- **Rule changes.** Admin proposes, the Director approves. Nothing changes silently.
- **Ideal infrastructure.** The rules that apply, with each marked met, not met or to verify.
  Locked as the target for the Ideal IT gate.
- **Gap register.** One entry per not-met rule, with a priority, affected assets, quantity
  hint and recommendation. People can edit, add, dismiss or dispute gaps. Every edit needs a
  reason and is kept. Locking the register requires every verify item to be decided.
- **Return to an earlier stage.** If an upstream change is needed, a project can be sent
  back to that stage and outputs downstream are superseded.
- **Rescan.** A second audit can be imported as a rescan to compare with the baseline.

## Endpoints

`/projects/{id}/brief`, `/projects/{id}/infra`, `/projects/{id}/gaps`, `/infra/rules`,
`/projects/{id}/return-to/{stage}`. See the [API guide](../guides/04-api-guide.md).

## Web app

Project page tabs: **Questionnaire**, **Infrastructure** (current and ideal, with the four
lens tiles) and **Gaps** (high priority, to consider, verify on site, dismissed, with a
side drawer for edits).

## Known limits

- The rules cover the ITCraft starter set. More rules are added through the proposal flow.
- The rules page in the web app is planned for phase 12.

## Demo script

1. Approve the Shakti audit, then fill in the questionnaire.
2. Build current, lock it, build ideal, lock it.
3. Draft the gap register, decide the verify items, lock it.
