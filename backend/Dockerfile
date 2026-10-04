# syntax=docker/dockerfile:1.7
# One image runs the API, the Celery worker and beat (different commands in compose).

FROM python:3.14.7-slim-bookworm AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt .
RUN pip install -r requirements.txt

FROM python:3.14.7-slim-bookworm AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    P1_ENV=prod \
    XDG_CACHE_HOME=/tmp/cache
# postgresql-client provides pg_dump for the nightly backup job.
# libpango, libharfbuzz and the fonts are what WeasyPrint needs to render the quotation PDF.
RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client curl tini \
    libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b fonts-dejavu-core shared-mime-info \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 10001 p1 \
 && useradd --system --uid 10001 --gid p1 --home-dir /app --shell /usr/sbin/nologin p1
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY --chown=p1:p1 alembic.ini ./
COPY --chown=p1:p1 migrations ./migrations
COPY --chown=p1:p1 app ./app
USER p1
EXPOSE 9596
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
  CMD curl -fsS http://127.0.0.1:9596/healthz || exit 1
ENTRYPOINT ["tini", "--"]
CMD ["gunicorn", "app.main:app", "--bind", "0.0.0.0:9596", "--worker-class", "uvicorn.workers.UvicornWorker", "--workers", "4", "--timeout", "60", "--graceful-timeout", "30", "--access-logfile", "-", "--forwarded-allow-ips", "*"]
