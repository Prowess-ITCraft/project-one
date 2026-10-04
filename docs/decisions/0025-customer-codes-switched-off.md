# ADR 0025: Customer codes at check-in and hand over, switched off for now

Status: accepted
Date: 2026-10-05
Decided by: Aditya Kumar

## Context

Field work was built with a one-time code emailed to the customer's sign-off contact at
check-in and again at hand over (ADR 0015, ADR 0017). It is not wanted for now.

## Decision

1. A feature flag, `field_customer_codes`, off by default. An admin turns it on with
   `PUT /api/v1/admin/feature-flags/field_customer_codes` (`{"enabled": true}`); it takes
   effect within 30 seconds, no restart, and the change is in the audit log.
2. While it is off, check-in and hand over do not ask for a code, asking for one answers
   `codes_off`, and the task page shows a single **Check in** or **Confirm hand over** button.
   The event records `customer_code: off`.
3. Everything else stays: the arrival photo, every dependency handed over, the evidence, the
   configuration check and the verifier.
4. The code flow, its email templates and its tests stay in the code. The tests run with the
   flag on, plus a test of the off path.

## Consequences

- The customer is not asked to confirm the engineer's arrival or the hand over. The arrival
  photo, location and time, and the verifier's review are the record instead.
