# ADR 0011: Free and open-source components only

Status: accepted
Date: 2026-10-01

## Context

Project One should use only free and open-source services (Aditya, 1 Oct). Redis 7.4 and later
moved to source-available licences (RSALv2 and SSPL), so it no longer counts as open source.

## Decision

Every runtime component must be free to use and under an OSI-approved open-source licence, and
must be self-hostable. Current choices:

| Component | Licence | Note |
| --- | --- | --- |
| PostgreSQL 16 | PostgreSQL | |
| Valkey 8 (replaces Redis 7.4) | BSD 3 | Drop-in: same protocol and client library |
| MinIO (Chainguard build) | AGPL v3 | Used unmodified as a separate service |
| ClamAV | GPL v2 | Separate service |
| Nginx | BSD 2 | |
| Prometheus | Apache 2 | |
| Grafana | AGPL v3 | Used unmodified as a separate service |
| Mailpit | MIT | Dev only |
| Celery, Flower, FastAPI, SQLAlchemy, Alembic, Pydantic | BSD or MIT | |
| Polars, DuckDB, PyArrow, rapidfuzz, WeasyPrint, Jinja2, qrcode | MIT, BSD | |
| Next.js, React | MIT | |
| Geist fonts | SIL OFL | Fetched at build time by `next/font` |

Rules going forward:

1. New components need an OSI licence and a self-hosted option, recorded here.
2. No paid SaaS in a required path. Optional integrations must be replaceable by a free
   self-hosted equivalent (error reporting: Sentry SDK is MIT and can point at self-hosted
   GlitchTip; it is off unless a DSN is set).
3. Notifications: email through any SMTP server (self-hosted Postfix or a free relay). SMS and
   WhatsApp normally need a paid carrier account; phase 8 will use adapters, ship an open
   gateway option (for example a self-hosted Gammu or a phone-based SMS gateway) and treat paid
   carriers as an optional adapter, chosen later.
4. Machine learning (phase 13) uses scikit-learn, LightGBM and MLflow (all open source),
   no hosted ML services.

## Consequences

- No licence fees and no vendor lock-in; everything runs on one server.
- Two points to watch: Docker Desktop is free only for small businesses (Docker Engine or
  Podman are free alternatives on servers), and GitHub Actions has free minutes for public
  repositories only (Gitea or Woodpecker can run the same pipeline on a private server).

Dev note: a volume written by Redis 7.4 cannot be read by Valkey 8. Drop it once with `docker volume rm project-one_redisdata` (it only holds rate-limit and queue state).
