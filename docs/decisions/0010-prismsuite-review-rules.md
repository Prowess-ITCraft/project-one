# ADR 0010: PrismSuite review and approval rules

Status: accepted
Date: 2026-09-30

## Context

Parsed reports are never perfect and approval locks the stage.

## Decision

Every parse keeps the original snapshot and a working copy. Reviewers correct values by JSON pointer with a reason, or confirm a conflicting field as it stands. Approval is blocked while required fields are unreadable or conflicts are unresolved. The importer and every corrector are barred from approving. One approved import per project; approving a newer one supersedes the old.

## Consequences

Approval can need three people (importer, reviewer, approver) on small teams. That is intended.
