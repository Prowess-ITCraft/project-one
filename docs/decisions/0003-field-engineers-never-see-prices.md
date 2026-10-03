# ADR 0003: The no-price rule beats role union

Status: accepted
Date: 2026-09-30

## Context

Field engineers never see prices, but one person can hold several roles.

## Decision

Prices are removed at the schema level for every field-work endpoint, whatever roles the caller holds. Price endpoints exist only in the catalogue and BOQ modules. A person who is both engineer and sales manager sees prices only in sales screens.

## Consequences

Slightly less convenient for multi-role staff. It removes a whole class of leaks.
