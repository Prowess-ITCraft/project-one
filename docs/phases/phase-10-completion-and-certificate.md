# Phase 10: Completion report and certificate

Window: 23 Nov to 1 Dec 2026 (planned). Status: built (4 Oct 2026). The real IITPL stamp is
still to come.

## Goal

Close a project with a completion report the customer can keep, and a "Certified by IITPL"
certificate that is impossible to issue until every condition holds, and that anyone can check
by scanning its QR code.

## Release conditions

Checked in one place (`reporting/service.py`), with no override:

1. Every task is closed, or excluded by an acknowledged waiver.
2. No open deviation of a severity that blocks the certificate (critical, always).
3. No waiver still waiting for the Director or the customer.
4. The after-work PrismSuite rescan is approved.
5. The IITPL stamp is uploaded.
6. The completion report is locked.
7. The customer acknowledged the completion stage.
8. A Director approved the completion stage.

Conditions 1 to 3 let the field work summary be locked, 1 to 5 the report, and all eight let a
Director issue the certificate.

## Features added

- **Waivers**: a project manager asks to exclude a task or a deviation, as Not applicable or
  Deferred by customer. The Director approves or rejects; an approved waiver goes to the
  customer's sign-off contact, who acknowledges it through a link without an account. Waivers
  are printed on the certificate.
- **Field work summary**: locked once field work is finished, so the field work gate can be
  submitted.
- **Completion report**: preview, then lock. Scope delivered, exclusions, before and after scores
  on the four lenses, configuration per device, deviations and open recommendations. No prices.
  The locked PDF is stored with its SHA-256 and never regenerated.
- **Certificate**: Director only. Number per financial year (`IITPL-2627-0001`), payload signed
  with an HMAC, QR code to `/verify/<number>`, stored PDF, revoke with a reason. Names IITPL as
  the implementer, signed by the Director with the IITPL stamp; work grouped by kind, at most 10
  lines, one page (ADR 0022).
- **Public check page**: shows whether a certificate is genuine, revoked or unknown. No prices,
  no contacts, no internal notes.
- **Settings**: certificate wording and the stamp image (PNG or JPEG).
- **Rescan**: the after-work PrismSuite report can be imported as JSON as well as Word.

## Acceptance

| Criterion | State |
| --- | --- |
| Certificate blocked until every condition holds | Done, tested as the conditions are met in turn |
| Only a Director can issue | Done, tested |
| Waiver needs the Director and the customer | Done, tested, including rejection |
| QR check shows genuine, revoked, unknown | Done; API tests for genuine, revoked and a tampered payload, browser test for unknown |
| Locked report never changes | Done; stored PDF and checksum. Certificates are guarded by a database trigger: only revocation can change one |

## Decisions

ADR 0016 (one PDF renderer), ADR 0019 (Director signs, IITPL stamp, rescan first).

## Known limitations

- The demo uses a placeholder stamp marked "DEMO STAMP" until IITPL sends the real one.
- PDFs only render inside the container (WeasyPrint does not load on Windows).

## Demo script

1. After `python -m app.cli demo-projects`, sign in as the Director and open "Head office IT hardening".
2. Completion tab: all eight conditions met, the report locked, the certificate issued.
3. Download the certificate and scan the QR code with a phone: the check page says genuine.
4. Open the in-progress project's Completion tab to see exactly which conditions are missing.
