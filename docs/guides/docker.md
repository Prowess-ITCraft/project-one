# Docker guide

How Project One is built and run with Docker: every Docker file in the repository, what it is
for, and the commands to build, start, check, update and stop the stack. For a first production
install read `DEPLOYMENT.md` as well; for day-to-day operations see `03-operations-guide.md`.

Maintained by Aditya Kumar.

## 1. What you need

- Docker Engine 24 or later with Compose v2 (`docker compose`, not `docker-compose`). On Windows,
  Docker Desktop, started by hand before any command.
- A `.env` file in the repository root: copy `.env.example` and fill every value. Never commit it.
- On Windows in Git Bash, prefix commands that pass container paths (`/data/...`) with
  `MSYS_NO_PATHCONV=1`, or Git Bash rewrites them into Windows paths.

## 2. The Docker files and what they do

| File | What it is | What it does |
| --- | --- | --- |
| `backend/Dockerfile` | The backend image (Python 3.12, multi-stage) | Installs `requirements.txt` into a virtualenv, then a slim runtime with WeasyPrint's libraries (Pango, HarfBuzz, fonts), `libgomp1` for LightGBM, the PostgreSQL 16 client for backups, and a non-root user `p1`. One image runs the API (Gunicorn with Uvicorn workers), the Celery worker, Celery beat, the migrations and Flower; only the command differs. Healthcheck: `/healthz`. |
| `frontend/Dockerfile` | The web app image (Node 22, multi-stage) | `npm ci`, `next build` (standalone output, a new build id for the service worker), then a small runtime as non-root `p1` serving on 9595. `API_ORIGIN` (build argument and environment) is where `/api` is proxied. Healthcheck: `/login`. |
| `docker-compose.yml` | The base stack | Every service, on one internal network, publishing nothing. Services: `postgres`, `redis` (Valkey), `minio`, `clamav`, `migrate` (runs `alembic upgrade head` and creates the buckets, then exits), `api`, `worker`, `beat`, `web`, `proxy` (Nginx). Profiles add the optional services below. Backend containers are read-only, drop all Linux capabilities and have memory limits. |
| `docker-compose.dev.yml` | Development mode, on top of the base | Publishes the port map on `127.0.0.1` only, points mail at Mailpit, turns off secure cookies for plain HTTP, mounts `samples/` into the worker, and adds `mailpit` and `flower` (profile `dev`). |
| `docker-compose.prod.yml` | Production mode, on top of the base | Publishes only 80 and 443 on the proxy (ADR 0030), mounts the TLS certificates, adds `certbot` (profile `tls`) to renew them, serves files through the app, and puts admin tools (Grafana, Uptime Kuma, GlitchTip, MLflow) on the server's loopback only, for the VPN or an SSH tunnel. Node exporter watches the host's disk. |
| `docker-compose.lb.yml` | Optional, on top of prod | Only when a load balancer in front terminates TLS: publishes the proxy's plain HTTP on 9597 for it. |
| `infra/nginx/nginx.conf`, `conf.d/`, `prod/`, `snippets/app.conf` | Reverse proxy | Routes `/api`, `/docs`, `/healthz`, `/readyz` to the API and everything else to the web app; rate limits; security headers. `conf.d` is plain HTTP (development, or behind a load balancer); `prod` is HTTPS with the certbot challenge on 80. |
| `infra/nginx/tls/` | Certificates | Laid out as certbot does (`live/project-one/fullchain.pem`, `privkey.pem`). See its README. |
| `infra/postgres/init/01-roles.sh` | Database first start | Creates the database, the owner role (runs migrations) and the restricted runtime role the app uses. Runs only when the `pgdata` volume is new. |
| `infra/prometheus/prometheus.yml` | Metrics | Scrapes the API, the node exporter and the public address (blackbox), sends alerts to Alertmanager. |
| `infra/prometheus/alerts.yml`, `alerts.test.yml` | Alert rules and their tests | API down, address down, server errors, slow responses, outbox backlog, failed jobs, queue depth, failing messages, missing backup, disk, memory, certificate expiry. |
| `infra/alertmanager/alertmanager.yml` | Alert routing | Warnings by email; critical alerts by email and to a phone through ntfy. Edit the three lines marked EDIT. |
| `infra/blackbox/blackbox.yml` | Probe settings | How the public address is checked. |
| `infra/grafana/provisioning/` | Grafana | Data source and dashboards loaded at start. |
| `Makefile` | Shortcuts (Linux, macOS) | `make up`, `make down`, `make logs`, `make test` and so on, with the dev files and profiles. |
| `scripts/dev.ps1` | Shortcuts (Windows) | The same commands in PowerShell: `.\scripts\dev.ps1 up`. |

### Profiles

| Profile | Adds | Ports (loopback) |
| --- | --- | --- |
| `dev` | Mailpit (catches every email), Flower (Celery monitor) | 9605, 9598 |
| `monitoring` | Prometheus, Alertmanager, node exporter, blackbox exporter, Grafana | 9603, 9604 |
| `ops` | GlitchTip (error tracking, Sentry protocol) with its own database and worker, Uptime Kuma | 9608, 9607 |
| `mlflow` | MLflow experiment tracking (optional, ADR 0029) | 9606 |
| `tls` | certbot renewal (production) | none |

### Port map (development)

9595 web, 9596 API, 9597 proxy, 9598 Flower, 9599 PostgreSQL, 9600 Valkey, 9601 MinIO API,
9602 MinIO console, 9603 Prometheus, 9604 Grafana, 9605 Mailpit, 9606 MLflow, 9607 Uptime Kuma,
9608 GlitchTip. All on `127.0.0.1`. In production only 80 and 443 are public.

## 3. Development commands

Always start with the dev file on top of the base, or SMTP and the web port are missing.

```sh
# shorthand used below
DEV="docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile dev --profile monitoring"

$DEV up -d --build                 # build images and start everything (make up / dev.ps1 up)
$DEV ps                            # what runs and its health
$DEV logs -f --tail=100 api worker # follow logs of some services
$DEV up -d --build api worker beat # rebuild and restart the backend only
$DEV up -d --build web             # rebuild and restart the web app only
$DEV --profile ops up -d           # add GlitchTip and Uptime Kuma
$DEV --profile mlflow up -d mlflow # add MLflow
$DEV down                          # stop and remove containers (data volumes stay)
```

First run and data:

```sh
$DEV exec api python -m app.cli seed                       # catalogue, rules, templates, settings, search index
$DEV exec api python -m app.cli create-admin --email you@itcraft.net.in --name "Your Name" --initials YN
$DEV exec api python -m app.cli vapid-keys                 # Web Push keys for .env
$DEV exec api python -m app.cli search-reindex             # rebuild global search
MSYS_NO_PATHCONV=1 $DEV exec worker python -m app.cli corpus ingest /data/samples
$DEV run --rm migrate                                      # run migrations again by hand
```

`seed-demo` and `demo-projects` build demo accounts and projects for development only. Note that
`seed-demo` resets the development admin's password and authenticator.

Open: web http://localhost:9595, through the proxy http://localhost:9597, API reference
http://localhost:9596/docs, Mailpit http://localhost:9605, Grafana http://localhost:9604.

## 4. Production commands

```sh
PROD="docker compose -f docker-compose.yml -f docker-compose.prod.yml"

$PROD build                                     # or pull images built by CI: $PROD pull
$PROD up -d                                     # start (migrations run first, by themselves)
$PROD --profile monitoring --profile ops up -d  # with monitoring, alerts, GlitchTip, Uptime Kuma
$PROD --profile tls up -d certbot               # certificate renewal with Let's Encrypt
$PROD exec worker python -m app.cli backup      # a database backup now
$PROD -f docker-compose.lb.yml up -d proxy      # only behind a load balancer (publishes 9597)
```

Updating: set `P1_VERSION` to the new tag in `.env`, `$PROD pull` (or `build`), `$PROD up -d`.
Rolling back: set the previous tag and `$PROD up -d` again. Migrations only add (expand, then
contract in a later release), so the previous version runs on the new schema. Details:
`DEPLOYMENT.md` and `docs/runbooks/`.

## 5. Checks

```sh
curl -fsS http://localhost:9596/healthz          # the API process is up
curl -fsS http://localhost:9596/readyz           # database, Valkey and MinIO reachable
curl -fsS http://localhost:9596/metrics | grep p1_   # app metrics and operational gauges
$DEV config -q                                   # the compose files are valid

# alert rules fire on the data that should fire them
MSYS_NO_PATHCONV=1 docker run --rm -v "$PWD/infra/prometheus:/p" -w /p --entrypoint promtool \
  prom/prometheus:v2.55.1 test rules alerts.test.yml
MSYS_NO_PATHCONV=1 docker run --rm -v "$PWD/infra/alertmanager:/a" --entrypoint amtool \
  prom/alertmanager:v0.27.0 check-config /a/alertmanager.yml

# browser tests against the running web container
cd frontend && BASE_URL=http://localhost:9595 npx playwright test --grep-invert "Admin"
```

## 6. Volumes and clean-up

Data lives in named volumes: `pgdata` (database), `miniodata` (files), `redisdata`, `clamdata`
(virus signatures), `promdata`, `grafanadata`, `alertdata`, `glitchtipdb`, `uptimedata`,
`mlflowdata`. `down` keeps them. `down -v` deletes them all, including the database and every
uploaded file: never on a server with real data, and take a backup first anywhere else.

```sh
docker image prune -f      # remove old, unused image layers
docker system df           # how much space Docker uses
```

## 7. Troubleshooting

- `set P1_... in .env`: a required value is empty in `.env`.
- The API waits on ClamAV: the first start downloads virus signatures (up to 3 minutes).
- Port already in use: another project holds 9595 to 9608; stop it or change the dev ports.
- No emails in Mailpit: the stack was started without `docker-compose.dev.yml`.
- Changes not visible: rebuild the service (`up -d --build web`), and on a phone tap Reload when
  "A new version is ready" appears.
