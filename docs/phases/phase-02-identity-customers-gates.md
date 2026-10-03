# Phase 2: Identity, access, audit log, customers and projects

Window: 1 to 6 Oct 2026 (mock plan). Status: built.

## Goal

Know who is doing what, let them do only what their role allows, keep a tamper-evident
record of everything, and move each customer project through eight approval gates.

## Features added

**Sign-in and accounts**

- Email and password with argon2id hashing, a 12 character minimum, and checks against
  common passwords and the person's own name or email.
- Short-lived access tokens (15 minutes) and rotating refresh tokens stored hashed. Using an
  old refresh token again ends the whole session (theft detection), with a short grace for two
  browser tabs refreshing at once.
- Authenticator app (TOTP) MFA, mandatory for Director and Admin, with recovery codes and
  replay protection (a used code cannot be reused).
- Lockout with growing delays after repeated wrong passwords; an Admin can unlock.
- Sessions list and revoke, "sign out everywhere else", password change that ends other
  sessions, and deactivation that stops tokens at once.
- Web cookies with CSRF protection, or bearer tokens for API clients.

**Roles and permissions**

- Ten roles: Audit engineer, Solution architect, Technical lead, Sales manager, Sales head,
  Project manager, Field engineer, Director, Customer representative, Admin.
- A permission matrix (29 permissions), deny by default. One person can hold several roles.
- Object-level checks: staff see only projects they are assigned to; customers see only their
  own company.
- Segregation of duties in code: the person who did the work can never verify or approve it.
- An automated test tries every endpoint with every role and fails if any answer is wrong.

**Audit log**

- Every create, update, delete, approval and state change writes who, what, when, from where
  and before/after values.
- Append-only: database privileges and triggers block edits and deletes, and each entry is
  chained to the previous one by a hash. A verify endpoint detects tampering even if someone
  bypasses the database rules.
- Personal data inside entries is encrypted per person; erasing a person destroys their key
  without breaking the chain (ADR 0004).

**Customers and projects**

- Customers with legal name, GSTIN (unique), segment, sites and contacts. Soft delete and
  restore (Admin only). Optimistic locking on every record.
- Projects with a generated code, members and project roles.
- The eight-stage gate model: Audit intake, Current infrastructure, Ideal infrastructure,
  Gap analysis, BOQ, Implementation plan, Field work, Completion.
  - A stage cannot open until the previous gate is approved.
  - Each gate needs a locked output from the module that owns the stage, plus a named approver
    from the configured roles. Gate settings can be changed by an Admin.
  - Some gates need the customer to acknowledge through a single-use link.
  - Approved outputs are locked; a change means a new version.
  - Submitter and the person who locked the output cannot approve the gate.
- Stage tracker, gate history and locked artifacts listed per project.

**Files**

- Upload pipeline: size cap, file type checked by content (not just the name), ClamAV scan
  that fails closed, random storage keys, short-lived download links.
- Photos: location data stripped, except evidence photos where time and GPS are kept.
- Infected uploads are refused, recorded and never stored.

## Acceptance criteria

| Criterion | State |
| --- | --- |
| Permission tests for every role and endpoint | Done: 93 endpoints by 10 roles, checked automatically (about 930 requests) |
| Doer is not verifier | Done and tested at the gate and at audit review |
| Audit entries for every mutation | Tested for the main flows; chain verification tested including tamper detection |

## Numbers

- 93 API endpoints in total across all modules, 12 for auth, 12 for users, 17 customers,
  17 projects, 3 files.
- Tests: 11 sign-in and session tests, 9 gate and customer tests, 8 upload tests, 5 matrix
  tests.

## Decisions

ADR 0003 (no prices for field engineers), ADR 0004 (audit log and personal data).

## Known limitations

- Customer sign-in is switched off by a feature flag; customers use links in v1.
- Email and SMS delivery are not connected yet (Phase 8).
- Test coverage of the customers and identity services is below the 85% goal: contacts,
  sites, gate configuration and several account paths have no dedicated tests yet. Closing
  this is on the Batch B task list.
- Single sign-on (Google or Microsoft) is not built.

## Demo script

1. Create an Admin with `scripts\dev.ps1 admin`, sign in, enrol MFA.
2. Create a customer and a project; add an audit engineer and a solution architect.
3. Try to approve your own gate and show the refusal.
4. Open the audit log and run the chain verification.
