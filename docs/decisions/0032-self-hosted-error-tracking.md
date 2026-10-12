# ADR 0032: Error tracking is self-hosted GlitchTip

Status: accepted
Date: 2026-10-12
Decided by: Aditya Kumar

## Context

ADR 0011 allows only free and open-source components and names GlitchTip as the self-hosted
target for error reports. v3 confirms it: the tool is internal, errors can carry customer and
project details, and nothing should be sent to a hosted service.

## Decision

1. The API reports errors with `sentry-sdk` (MIT), which speaks the protocol GlitchTip accepts.
   It is off unless `P1_SENTRY_DSN` is set, and it never sends personal data
   (`send_default_pii=False`).
2. In production, `validate_for_runtime` refuses a DSN on `sentry.io`, so the API will not start
   pointed at hosted Sentry.
3. GlitchTip, its worker and database run in the compose profile `ops`, together with Uptime
   Kuma, off by default. The name is `ops`, not `monitoring`, because `monitoring` already holds
   Prometheus and Grafana and is on in development.
4. GlitchTip is bound to the server's loopback address (ADR 0030) and has a healthcheck like
   every other production service.

## Consequences

- To turn it on: `p1 --profile ops up -d`, create a project in GlitchTip through an SSH tunnel
  to port 9608, put its DSN in `P1_SENTRY_DSN` (the internal address, `http://...@glitchtip:8000/...`),
  then `p1 up -d api`.
- Only the API process reports errors; the worker and the web app send none.
- `tests/test_prod_config.py` checks the sentry.io refusal and that a GlitchTip DSN is allowed.
