# Operations guide

For the person who runs Project One on a server.

## 1. Environments

| Mode | Command | What is published |
| --- | --- | --- |
| Dev | `docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile dev --profile monitoring up -d --build` | Whole port map on `127.0.0.1` |
| Prod | `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d` | Proxy only: 80, 443, 9597 |

Add `--profile monitoring` in prod if you want Prometheus and Grafana (reach them through an
SSH tunnel, they are not published).

## 2. Port map

| Port | Service | Public in prod |
| --- | --- | --- |
| 9595 | Web app (phase 11) | via proxy |
| 9596 | API | no (dev only) |
| 9597 | Proxy, plain HTTP | yes, for a load balancer that does TLS |
| 9598 | Flower | no |
| 9599 | PostgreSQL | no |
| 9600 | Redis | no |
| 9601 | MinIO S3 | no |
| 9602 | MinIO console | no |
| 9603 | Prometheus | no |
| 9604 | Grafana | no (tunnel) |
| 9605 | Mailpit | no |
| 9606 | MLflow (phase 13) | no |

## 3. Configuration

All settings are environment variables with the `P1_` prefix (or files in `/run/secrets`).

| Variable | Meaning |
| --- | --- |
| `P1_ENV` | `dev`, `test` or `prod`. Prod refuses dev keys. |
| `P1_POSTGRES_PASSWORD` | PostgreSQL superuser password (used only at first start) |
| `P1_OWNER_PASSWORD` | Database owner role, used by migrations |
| `P1_APP_PASSWORD` | Runtime role. Cannot edit or delete audit rows |
| `P1_REDIS_PASSWORD` | Redis password |
| `P1_S3_ACCESS_KEY`, `P1_S3_SECRET_KEY` | Object storage credentials |
| `P1_FERNET_KEYS` | Encryption keys, comma separated. First encrypts, all decrypt |
| `P1_JWT_SIGNING_KEYS` | Token signing keys, comma separated. At least 32 characters in prod |
| `P1_COOKIE_SECURE` | Must be `true` in prod |
| `P1_CORS_ALLOW_ORIGINS` | Allowed web origins, comma separated |
| `P1_PUBLIC_BASE_URL` | Used in links sent to customers |
| `P1_S3_PUBLIC_ENDPOINT_URL` | Address browsers use for download links |
| `P1_SENTRY_DSN`, `P1_OTEL_EXPORTER_OTLP_ENDPOINT` | Optional error and trace reporting |
| `P1_LIBRARY_INBOX_DIR` | Folder the worker watches for old BOQs and reports (compose: `./inbox`) |
| `P1_CORPUS_ORIGINALS_RETENTION_DAYS` | 0 keeps original files forever. A positive number deletes originals older than that once their JSON is verified. Irreversible (ADR 0014) |

### Key rotation

Add the new key at the **front** of the list and keep the old one after it. Restart. Old data
still decrypts; new data uses the new key. Remove the old key only after re-encrypting.

## 4. First deployment checklist

1. Server with Docker and Compose, 4 GB RAM or more, disk for database and uploads.
2. Copy the repository, create `.env` with strong unique values (see the beginner's guide
   for generating them). Set `P1_ENV=prod`, `P1_COOKIE_SECURE=true`, real
   `P1_PUBLIC_BASE_URL`, `P1_CORS_ALLOW_ORIGINS` and `P1_S3_PUBLIC_ENDPOINT_URL`.
3. TLS: terminate at a front load balancer and forward to port 9597, or add a 443 server
   block in `infra/nginx/conf.d` with certificates placed in `infra/nginx/tls`.
4. Start: the prod command above. The `migrate` job creates the schema and storage buckets.
5. Create the first admin: `docker compose exec api python -m app.cli create-admin ...`
6. Load starter data: `docker compose exec api python -m app.cli seed`.
7. Check `/healthz` and `/readyz`, then sign in and enrol MFA.
8. Run a backup and a restore drill (next section) before real data arrives.

## 5. Backups and restore

- **What**: a nightly `pg_dump` (custom format) to the `p1-backups` bucket, kept 30 days
  (`P1_BACKUP_RETENTION_DAYS`). The files bucket has versioning turned on.
- **Run now**: `docker compose exec worker python -m app.cli backup`
- **Restore drill** (do this on a spare machine, never on production first):
  1. Start a clean stack.
  2. Download a dump from the backups bucket (MinIO console, folder `pg_dump/`).
  3. `docker compose exec -T postgres pg_restore -U postgres -d project_one --clean
     --if-exists --no-owner < backup.dump`
  4. Start the api, call `/readyz`, then `GET /api/v1/audit-log/verify` as an Admin and
     expect `ok: true`.
  5. Record the time it took. That is your recovery time.
- Copy backups off the server as well. A backup on the same disk is not a backup.

## 6. Monitoring

- `/healthz`: process alive. `/readyz`: database, Redis and storage reachable.
- `/metrics`: Prometheus metrics `p1_http_requests_total` and
  `p1_http_request_duration_seconds`. Nginx hides this path from outside.
- Grafana dashboard "Project One API": request rate by status, p95 latency, 5xx rate.
- Logs are JSON, one line per event, each with a `request_id`. Search by it to follow one
  request across api, worker and proxy.
- Watch for: outbox rows with status `dead`, growing `pending` rows, nightly backup failures,
  prices `expired`, rising 5xx.

### Useful checks

```sql
-- stuck background events
SELECT subscriber, status, count(*) FROM outbox_messages GROUP BY 1,2;
-- dead events with reasons
SELECT event_type, subscriber, last_error FROM outbox_messages WHERE status = 'dead';
```

## 7. Routine tasks

| Task | Command |
| --- | --- |
| Unlock a user | `POST /api/v1/users/{id}/unlock` as Admin |
| Reset someone's MFA | `POST /api/v1/users/{id}/reset-mfa` as Admin |
| End all sessions of a user | `POST /api/v1/users/{id}/sessions/revoke-all` |
| Turn on customer sign-in | `PUT /api/v1/admin/feature-flags/customer_portal_login` |
| Verify the audit log | `GET /api/v1/audit-log/verify` |
| Run price expiry now | `python -m app.cli expire-prices` |
| Load starter catalogue, rules and BOQ defaults | `python -m app.cli seed` |
| Load the dev demo user | `python -m app.cli seed-demo` (development only) |
| Approve a rule change | Director, `POST /api/v1/infra/rules/{id}/approve` |
| Check PDF rendering | open a quotation as PDF. A 503 `pdf_unavailable` means the image lacks the pango libraries |
| Drain the outbox now | `python -m app.cli dispatch-outbox` |
| Apply migrations | `docker compose run --rm migrate` |
| Add old BOQs or reports in bulk | copy them into `./inbox`; the worker reads it every 5 minutes |
| Load the reference samples into the library | `docker compose exec worker python -m app.cli corpus ingest /data/samples` (dev) |
| Convert a folder to corpus JSON on a laptop | `python -m app.cli corpus convert <folder> --out <dir>` (no database) |
| Rebuild the corpus after a parser or cleaning change | `python -m app.cli corpus rebuild` or `POST /api/v1/library/rebuild` as Admin |
| Apply the originals retention now | `python -m app.cli corpus purge --days N` |
| Re-send library files stuck at "Waiting" | `python -m app.cli corpus requeue` |
| See every PDF the system makes, from the samples | `docker compose exec worker python -m app.cli render-samples --corpus /data/samples/corpus --out /tmp/sample-documents` (copy out with `docker exec ... cat`) |
| Check a field task's record | `GET /api/v1/field/runs/{id}/render` (PDF) |

Scheduled jobs (Celery beat): outbox every 5 s, notification retries every minute, library inbox every
5 minutes, price expiry 00:10 IST, backup 02:30 IST, corpus retention 01:30 IST (does nothing at 0 days).

## 8. Updating

1. `git pull`, then `docker compose ... build`.
2. Take a backup.
3. `docker compose ... up -d`. The `migrate` job runs first; the api waits for it.
4. Check `/readyz` and the dashboard.
5. Rollback: redeploy the previous image tag. If a migration must be undone,
   `alembic downgrade -1` (only for migrations written to be reversible) from a one-off
   container using the owner credentials, after a backup.

## 9. Troubleshooting

| Symptom | Check |
| --- | --- |
| `api` restarts in a loop | `docker compose logs api`. Usually a missing or unsafe setting in prod |
| Uploads fail with 503 | ClamAV not ready yet (first start downloads signatures, up to 3 minutes) |
| Emails or jobs do not run | `worker` and `beat` healthy? `outbox_messages` pending or dead? |
| Downloads fail in the browser | `P1_S3_PUBLIC_ENDPOINT_URL` must be reachable by the browser |
| Sign-in loops on the web app | `P1_COOKIE_SECURE` and HTTPS mismatch, or wrong `P1_CORS_ALLOW_ORIGINS` |
| Slow requests | Grafana p95, then database statement timeout (15 s) in logs |
