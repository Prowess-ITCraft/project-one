# ADR 0018: Event subscribers load before anything publishes

Status: accepted
Date: 2026-10-03

## Context

The outbox decides who receives an event when the event is written, so a failed subscriber can
be retried on its own. A process that published before importing the subscribers wrote the event
with nobody to receive it and marked it done. This happened to library files added through
`cli corpus ingest`: they were stored and never read, with no error anywhere.

## Decision

- `registry.load_handlers()` marks the process ready; the API, the Celery worker (at import) and
  the CLI (`main`) call it at start-up, and so does the test harness.
- `outbox.publish` raises when the process is not ready, so the mistake is loud, never a lost
  event.
- `cli corpus requeue` sends files still waiting in the library to be read again, for anything
  caught before the guard existed.

## Consequences

- A new entry point (a script, a new worker) must call `load_handlers()` first; the error message
  says so.
- A test that publishes outside the `clean_state` fixture must load handlers itself.
