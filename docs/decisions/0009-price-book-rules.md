# ADR 0009: Price book rules

Status: accepted
Date: 2026-09-30

## Context

Money rules were not fully specified.

## Decision

Selling price may not be below cost. Prices are append-only history with one active row per item, enforced by a partial unique index and database triggers. A price is judged expired by its valid-until date, not by a status flag, so a missed nightly job cannot make a stale price usable. Sales manager and Sales head enter prices; Admin edits the catalogue but has no price access. GST is per item, default 18%. The sample quotation gives selling prices only, so seed prices set cost equal to selling and say so in the source note.

## Consequences

Below-cost selling needs a future explicit approval flow. Seed prices must be refreshed by a human before use.
