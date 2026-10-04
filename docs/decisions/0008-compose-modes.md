# ADR 0008: Compose modes: base, dev and prod files plus profiles

Status: accepted
Date: 2026-09-30

## Context

We need dev and prod modes with optional services.

## Decision

docker-compose.yml defines services without published ports. docker-compose.dev.yml publishes ports on 127.0.0.1 and enables the dev profile (mailpit, flower). docker-compose.prod.yml publishes the proxy only. The monitoring profile adds Prometheus and Grafana.

## Consequences

Ports cannot leak from the base file. Image digests are pinned by hand during hardening (phase 14).
