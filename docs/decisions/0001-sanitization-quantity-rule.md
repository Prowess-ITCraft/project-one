# ADR 0001: Sanitization quantity is per endpoint

Status: accepted
Date: 2026-09-30

## Context

The brief maps sanitization to 'per endpoint', but the audit finding reads '6 systems with two antivirus agents'. The sample Shobhaglobs BOQ shows sanitization 31 next to end point security 31, so sanitization follows the endpoint count.

## Decision

The BOQ template uses quantity rule 'per endpoint' for sanitization. The gap engine still records the flagged-system count (conflicting antivirus) so the sales user sees it and can reduce the quantity, with a reason.

## Consequences

Matches the sample quotation. A customer with few flagged systems may see a higher quantity than needed, so the override with a reason is important. To be confirmed by the Director.
