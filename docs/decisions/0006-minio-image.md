# ADR 0006: MinIO image

Status: accepted
Date: 2026-09-30

## Context

The official minio/minio images are no longer published.

## Decision

Use the Chainguard MinIO image pinned by digest, in compose and in tests.

## Consequences

The image has no shell, so there is no container healthcheck. The API readiness check covers storage instead.
