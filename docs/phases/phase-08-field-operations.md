# Phase 8: Field operations

Window: 9 to 18 Nov 2026 (planned). Status: built (3 Oct 2026).

## Goal

The "food delivery" flow for field work: an engineer cannot move a task on until the current
step's checklist and evidence are complete, the customer confirms arrival and hand over with a
one-time code, the configuration is checked against the target, and someone other than the
engineer verifies it. Everyone who needs to know is told at every step.

## The flow (ADR 0015)

```
assigned -> accepted -> checked_in -> prechecks_done -> configured -> evidence_uploaded
         -> engine_check -> verifier_review -> closed
                 ^                                   |
                 +---- check failed or rejected -----+
```

| Step | What it needs |
| --- | --- |
| Check in | Prerequisite tasks handed over, a site photo, the customer's code, location |
| Prechecks done | Backup confirmed (screenshot for network devices) and access confirmed |
| Configured | Every step ticked in order, a value recorded for every target setting |
| Evidence uploaded | Every required item from the task template |
| Engine check | Runs at once. A failed critical or major setting sends the task back |
| Hand over | A passed check and the customer's second code |
| Closed | A verifier who did not do the work approves; or sends it back with a reason |

## Features added

- State machine with nothing skippable, an append-only event trail (who, when, where).
- Customer one-time codes by email: 6 digits, 15 minutes, 5 tries, hashed, wiped from the log.
- Evidence per stage, uploaded once even if the phone resends; photos keep their EXIF.
- Offline tolerance: every action carries `client_event_id` and `captured_at` (72 hours).
- Engine check behind `ConfigCheckDriver`; v1 judges recorded values (Enabled, at least N);
  free-text targets go to the verifier as "not checked".
- Verifier queue; the doer is refused even if they hold the verifier role.
- Notifications at every state change to the customer's sign-off contact, every Director and
  the project manager; the verifier is asked to review; rework is explained to the engineer.
- Live feed: server-sent events with a `seq` cursor, plus polling. Director summary: tasks by
  state, blocked with reasons, late starts, overdue, failing checks, rework count.
- Printable task record (PDF): timeline, steps, values found, every check, evidence with photos.
- Block and unblock (project manager), reassign before work starts on site.

## Acceptance

| Criterion | State |
| --- | --- |
| No skipping states | Done, tested at every step |
| Each transition notifies customer and Director | Done, tested |
| OTP at check-in and hand over | Done, tested (wrong code, expiry, tries) |
| Uploads resume after a dropped connection | Done, tested (same `client_id` returns the first upload) |
| Doer cannot verify | Done, tested with a person holding both roles |

## Known limits

- Email is the only OTP channel until an SMS or WhatsApp provider is chosen.
- Brand config-export drivers come in phase 9.

## Demo script

1. Start field work on a project with a locked plan.
2. As the engineer on a phone: accept, add the site photo, send the code, check in.
3. Confirm backup and access, tick the steps, record the values, send the evidence.
4. Record one wrong value to show the check sending the task back, fix it, hand over.
5. As the technical lead, open the review queue and close the task. Show the task record PDF.
