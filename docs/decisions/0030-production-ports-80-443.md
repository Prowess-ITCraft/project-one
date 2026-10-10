# ADR 0030: Production publishes only ports 80 and 443

Status: accepted
Date: 2026-10-08
Decided by: Aditya Kumar

## Context

The production compose file published the proxy's plain HTTP port 9597 next to 80 and 443, so a
front load balancer could reach it. On a server without a load balancer, that left a plain HTTP
way in that skips TLS. Monitoring and admin tools (Grafana, Uptime Kuma, GlitchTip, MLflow) must
not be public either.

## Decision

1. `docker-compose.prod.yml` publishes only 443 (HTTPS) and 80 (the certificate challenge and a
   redirect to HTTPS), both on the reverse proxy.
2. The plain HTTP port for a front load balancer moves to its own file, `docker-compose.lb.yml`,
   added on the command line only when a load balancer terminates TLS. The firewall must then
   let only the load balancer reach 9597 (DEPLOYMENT.md, section 4a).
3. Admin tools are bound to the server's loopback address only, for the VPN or an SSH tunnel.
   PostgreSQL, Valkey and MinIO are never published in production.

## Consequences

- A server set up from the old instructions with a load balancer must add `-f
  docker-compose.lb.yml` to its compose command; DEPLOYMENT.md shows it.
- Reaching Grafana or Uptime Kuma needs the VPN or a tunnel.
