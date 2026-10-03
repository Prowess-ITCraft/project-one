# ADR 0004: Append-only audit log with crypto-shredding

Status: accepted
Date: 2026-09-30

## Context

Erasure requests conflict with an append-only log whose snapshots contain personal data.

## Decision

Personal data in audit snapshots is encrypted with a per-person data key. Erasing the person deletes the key. The hash chain still verifies because the ciphertext stays. Database triggers and revoked privileges block UPDATE and DELETE.

## Consequences

Erased entries remain as 'personal data encrypted' markers. Restoring a person's history after erasure is impossible by design.
