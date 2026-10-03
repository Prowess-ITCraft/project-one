# ADR 0002: Price validity and quote validity are separate

Status: accepted
Date: 2026-09-30

## Context

The price book holds supplier price validity (valid-until per price). The quotation terms state a 5 day offer validity.

## Decision

Price validity lives on each price entry and blocks BOQ approval when expired. Quote validity is a per-quote setting with a company default of 5 days and is printed in the terms. The two are never mixed.

## Consequences

A quote can be valid for 5 days only if every price it uses is valid for at least that long. The BOQ engine will warn when a price expires before the quote does.
