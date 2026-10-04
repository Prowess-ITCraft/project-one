# ADR 0015: Field task state machine

Status: accepted
Date: 2026-10-03

## Context

Work started on 1 October used a delivery-style flow (assigned, accepted, on the way, checked
in, working, submitted, handed over, verified, rework, blocked). The 3 October spec update fixes
the states:

`assigned -> accepted -> checked_in -> prechecks_done -> configured -> evidence_uploaded ->
engine_check -> verifier_review -> closed`

with an engine mismatch or verifier rejection returning the task to `configured`, and customer
OTP at check-in and at handover. The earlier code was never registered or released, so we
switched over.

## Decision

| From | To | Who | Gate (all must hold) |
| --- | --- | --- | --- |
| assigned | accepted | assigned engineer | none |
| accepted | checked_in | engineer | dependencies closed, customer check-in OTP, site photo, location |
| checked_in | prechecks_done | engineer | backup confirmed and access confirmed, each with evidence |
| prechecks_done | configured | engineer | every configuration step ticked in order, actual value recorded for every baseline field |
| configured | evidence_uploaded | engineer | every required evidence item present |
| evidence_uploaded | engine_check | system | config comparison runs at once |
| engine_check | configured | system | any critical or major field failed (deviations recorded) |
| engine_check | verifier_review | engineer | engine passed, customer handover OTP |
| verifier_review | closed | verifier, not the engineer | approves |
| verifier_review | configured | verifier | rejects with a reason |
| any working state | blocked | engineer | reason; returns to the state it came from when a manager unblocks |

- Every transition notifies the customer sign-off contact and the Director (email in v1), and
  the project manager. Messages to customers never contain prices.
- The config comparison sits behind `ConfigCheckDriver`. v1 is `AnswerDriver`: it compares the
  engineer's recorded values with the baseline's expected values (booleans such as Enabled and
  Disabled, "at least N", "above N percent"). Values it cannot judge are `not_checked` and go to
  the verifier. Brand drivers that read config exports (SonicWall, Sophos, Fortinet, Cisco) are
  Phase 9.
- The `on_the_way` state is dropped; departure is an optional event with a location, not a state.

## Consequences

- Migration 0009 widens the state columns and adds `run_checks` (one row per engine run).
- The verifier queue is part of Phase 8 so a task can reach `closed`; the full verification
  module (drivers, dashboard API) is Phase 9.
