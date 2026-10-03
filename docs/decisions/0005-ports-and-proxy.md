# ADR 0005: Only the proxy is published in production

Status: accepted
Date: 2026-09-30

## Context

The port map lists Grafana as admin only and the proxy as TLS on 443 in production.

## Decision

Production publishes 80, 443 and 9597 (plain HTTP for a front load balancer) on the proxy only. The web app (9595) joins behind the proxy in Phase 11. API, database, cache, storage, Prometheus and Grafana stay internal; admins reach Grafana through an SSH tunnel or VPN. Dev publishes the full 9595 to 9606 map on 127.0.0.1.

## Consequences

One public entry point to secure and monitor. Admin access needs a tunnel.
