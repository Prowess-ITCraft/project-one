# Alerts runbook

What each alert means and what to do about it. The rules are in
`infra/prometheus/alerts.yml`; Alertmanager (`infra/alertmanager/alertmanager.yml`) sends
critical alerts to the on-call phone (ntfy) and email, and warnings to email only. Commands use
the `p1` shorthand from [DEPLOYMENT.md](../../DEPLOYMENT.md), section 5. For anything that
stops people working, also follow the [incident runbook](incident.md).

## Setting it up

1. Start monitoring with the stack: `p1 --profile monitoring --profile ops up -d`.
2. In `infra/alertmanager/alertmanager.yml`, change the three lines marked `EDIT`: the SMTP
   server, the on-call address, and the ntfy topic. Pick a long, unguessable topic name; anyone
   who knows it can read the alerts.
3. Install the ntfy app on the on-call phone and subscribe to that topic.
4. In `infra/prometheus/prometheus.yml`, job `public`, change the target `http://proxy/healthz` to
   the real address, for example `https://p1.itcraft.net.in/healthz`, so the certificate is
   checked too.
5. Restart: `p1 restart prometheus alertmanager`.
6. Send a test alert and check it reaches the phone:
   ```bash
   p1 exec alertmanager amtool alert add TestAlert severity=critical \
     --annotation=summary="Test, please ignore" --alertmanager.url=http://localhost:9093
   ```

Prometheus (9603) and Grafana (9604) are on the server's loopback only; reach them over the VPN
or `ssh -L 9603:127.0.0.1:9603 server`.

## Testing the rules

Every rule has a test that feeds it data and checks it fires, and stays quiet when all is well:

```bash
docker run --rm -v ./infra/prometheus:/p -w /p --entrypoint promtool \
  prom/prometheus:v2.55.1 test rules alerts.test.yml
```

Run it after changing any rule.

## The alerts

### ApiDown (critical)

Prometheus has not reached the API for 2 minutes. Nobody can sign in or save work.

1. `p1 ps api`: is it restarting? `p1 logs --since 15m api | tail -60`.
2. "Refusing unsafe settings" in the log means `.env` changed; fix it and `p1 up -d api`.
3. Database or storage errors: see the readiness check, `curl -s localhost:9596/readyz` from the
   server, and fix what it names.
4. Out of memory (`dmesg | grep -i oom`): see MemoryLow.
5. If a new version broke it, roll back (DEPLOYMENT.md, section 11).

### PublicAddressDown (critical)

The public address has not answered for 3 minutes, as seen from the server itself.

1. If ApiDown fires too, start there.
2. Otherwise check the proxy: `p1 ps proxy`, `p1 logs --since 15m proxy`.
3. A certificate problem shows as a TLS error in `curl -vI https://p1.itcraft.net.in`; see
   CertificateExpiring.
4. If everything works from the server, the problem is outside it (DNS, the internet line, the
   load balancer). Check from a phone on mobile data.

### ServerErrors (warning)

More than 5 percent of requests failed with a server error for 10 minutes.

1. Open GlitchTip (9608): the newest issue usually names the cause.
2. `p1 logs --since 15m api | grep -i error | tail -40`.
3. If it started with a deploy, roll back.

### SlowResponses (warning)

The slowest 5 percent of requests take more than 1.5 seconds, for 15 minutes.

1. Grafana, API dashboard: which paths are slow?
2. A load spike (many people at once) passes by itself. A steady slowdown usually means the
   database: `p1 exec postgres psql -U postgres -d project_one -c "SELECT pid, now() - query_start AS took, left(query, 120) FROM pg_stat_activity WHERE state <> 'idle' ORDER BY took DESC LIMIT 10"`.
3. Check MemoryLow and DiskSpaceLow; a full disk makes everything slow.

### OutboxBacklog (warning)

More than 500 background messages waiting for 10 minutes: emails, push messages, search updates
and learning examples are late.

1. `p1 ps worker beat`: both must be running. Start whichever is stopped.
2. `p1 logs --since 15m worker | tail -60` for errors.
3. Once the worker runs, the backlog drains by itself (every 5 seconds).

### FailedJobs (warning)

Some background messages gave up after every retry.

1. Find them: `p1 exec postgres psql -U postgres -d project_one -c "SELECT event_type, subscriber, attempts, left(last_error, 200) FROM outbox_messages WHERE status = 'dead' ORDER BY created_at DESC LIMIT 20"`.
2. Fix the cause the error names (often a mail setting, see MessagesFailing).
3. Retry them: `p1 exec postgres psql -U postgres -d project_one -c "UPDATE outbox_messages SET status = 'pending', attempts = 0, available_at = now() WHERE status = 'dead'"`.
   Every handler is safe to run twice.

### QueueDepth (warning)

More than 200 tasks waiting for a Celery worker for 10 minutes.

1. Is the worker running and answering? `p1 exec worker celery -A app.worker inspect ping`.
2. A task stuck on an outside service (mail, ClamAV) holds the queue; the logs name it. Tasks
   stop after 5 minutes at most.
3. A worker killed in the middle of a task gives it back; it runs again within 10 minutes.

### MessagesFailing (warning)

More than 20 emails or push messages failed in a day.

1. Check the mail settings in `.env` (`P1_SMTP_*`) and that the mail provider has not blocked
   the account (log in to it).
2. `p1 logs --since 1h worker | grep -i smtp | tail -20`.
3. Failed messages are retried every minute for a while, then given up.

### BackupMissing (critical)

The last good database backup is more than 26 hours old.

1. Run one now and read the error: `p1 exec worker python -m app.cli backup`.
2. Usual causes: the disk is full (DiskSpaceLow), storage is down (`curl -s
   localhost:9596/readyz`), or the database password changed.
3. Once a backup succeeds, check the copy off the server ran too (DEPLOYMENT.md, section 9).

### DiskSpaceLow (critical)

A disk has less than 15 percent free.

1. `df -h` and `docker system df`: what is using it?
2. Old images: `docker image prune -a` (keep the previous version's tag for a rollback).
3. Logs: `docker` keeps them small already; check `/var/log`.
4. Never delete anything in the `pgdata` or `miniodata` volumes by hand. If file storage is
   simply full, add disk.

### MemoryLow (warning)

Less than 10 percent of memory free for 10 minutes.

1. `docker stats --no-stream`: which service uses most?
2. ClamAV needs about 1.5 GB; that is normal. A growing API or worker means a leak: restart it
   (`p1 restart api`) and report it.
3. If it keeps coming back, the server needs more memory.

### CertificateExpiring (warning)

The HTTPS certificate expires within 14 days. Certbot should have renewed it.

1. `p1 --profile tls logs --since 48h certbot` for the renewal error.
2. Renew by hand, then reload the proxy:
   ```bash
   p1 --profile tls run --rm --entrypoint certbot certbot renew --webroot -w /var/www/certbot
   p1 exec proxy nginx -s reload
   ```
3. With your own certificate (option B), get a new one from its issuer and copy it in.
