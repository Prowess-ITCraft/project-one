"""Test harness: real Postgres, Redis and MinIO in containers (testcontainers).

Containers start once per session. Migrations run once as the owner role; the app connects as
the restricted runtime role, exactly as in production. Tables are truncated between tests.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from cryptography.fernet import Fernet
from testcontainers.minio import MinioContainer
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

PG_IMAGE = "postgres:16.6-alpine"
REDIS_IMAGE = "valkey/valkey:8.0-alpine"  # Redis-compatible and BSD licensed, see ADR 0011
# Official minio/minio images are no longer published; see docs/decisions/0006.
MINIO_IMAGE = "cgr.dev/chainguard/minio@sha256:4692462f35d97d7e82c30371d82f057703c5d9489bcae726010594c812f2d285"

_ROLE_SQL = [
    "CREATE ROLE p1_owner LOGIN PASSWORD 'owner_test'",
    "CREATE ROLE p1_app LOGIN PASSWORD 'app_test'",
    "CREATE DATABASE project_one OWNER p1_owner",
]
_SCHEMA_SQL = [
    "REVOKE CREATE ON SCHEMA public FROM PUBLIC",
    "ALTER SCHEMA public OWNER TO p1_owner",
    "GRANT USAGE ON SCHEMA public TO p1_app",
    "ALTER DEFAULT PRIVILEGES FOR ROLE p1_owner IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO p1_app",
    "ALTER DEFAULT PRIVILEGES FOR ROLE p1_owner IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO p1_app",
]


@pytest.fixture(scope="session")
def containers() -> Iterator[dict[str, Any]]:
    pg = PostgresContainer(
        PG_IMAGE, username="postgres", password="pgtest", dbname="postgres", driver=None
    )
    redis = RedisContainer(REDIS_IMAGE)
    minio = MinioContainer(MINIO_IMAGE, access_key="p1test", secret_key="p1test-secret-key")
    pg.start()
    redis.start()
    minio.start()
    try:
        yield {"pg": pg, "redis": redis, "minio": minio}
    finally:
        for c in (minio, redis, pg):
            c.stop()


def _pg_exec(pg: PostgresContainer, db: str, statements: list[str]) -> None:
    import psycopg

    host, port = pg.get_container_host_ip(), pg.get_exposed_port(5432)
    with psycopg.connect(
        f"postgresql://postgres:pgtest@{host}:{port}/{db}", autocommit=True
    ) as conn:
        for sql in statements:
            conn.execute(sql)


@pytest.fixture(scope="session")
def settings_env(containers: dict[str, Any]) -> Iterator[None]:
    pg, redis, minio = containers["pg"], containers["redis"], containers["minio"]
    _pg_exec(pg, "postgres", _ROLE_SQL)
    _pg_exec(pg, "project_one", _SCHEMA_SQL)
    host, port = pg.get_container_host_ip(), pg.get_exposed_port(5432)
    r_host, r_port = redis.get_container_host_ip(), redis.get_exposed_port(6379)
    m_host, m_port = minio.get_container_host_ip(), minio.get_exposed_port(9000)
    env = {
        "P1_ENV": "test",
        "P1_DATABASE_URL": f"postgresql+asyncpg://p1_app:app_test@{host}:{port}/project_one",
        "P1_DATABASE_OWNER_URL": f"postgresql+asyncpg://p1_owner:owner_test@{host}:{port}/project_one",
        "P1_REDIS_URL": f"redis://{r_host}:{r_port}/0",
        "P1_CELERY_BROKER_URL": f"redis://{r_host}:{r_port}/1",
        "P1_S3_ENDPOINT_URL": f"http://{m_host}:{m_port}",
        "P1_S3_ACCESS_KEY": "p1test",
        "P1_S3_SECRET_KEY": "p1test-secret-key",
        "P1_FERNET_KEYS": Fernet.generate_key().decode(),
        "P1_JWT_SIGNING_KEYS": "test-signing-key-0123456789abcdef0123456789",
        "P1_COOKIE_SECURE": "false",
        "P1_LOG_JSON": "false",
        "P1_LOG_LEVEL": "WARNING",
        "P1_CLAMAV_HOST": "127.0.0.1",
        "P1_CLAMAV_PORT": "1",
    }
    os.environ.update(env)
    from app.core import crypto, s3
    from app.core.config import get_settings

    get_settings.cache_clear()
    crypto.reset_key_cache()
    s3.reset_clients()
    yield


@pytest.fixture(scope="session")
def migrated(settings_env: None) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option(
        "script_location", os.path.join(os.path.dirname(__file__), "..", "migrations")
    )
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
def buckets(settings_env: None) -> None:
    from app.core.config import get_settings
    from app.core.s3 import ensure_bucket

    s = get_settings()
    ensure_bucket(s.s3_bucket_files)
    ensure_bucket(s.s3_bucket_backups)


_KEEP_TABLES = {"alembic_version"}


async def _truncate() -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import get_settings

    engine = create_async_engine(get_settings().database_owner_url)
    async with engine.begin() as conn:
        rows = await conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        )
        tables = [r[0] for r in rows if r[0] not in _KEEP_TABLES]
        if tables:
            await conn.execute(
                text(
                    "TRUNCATE " + ", ".join(f'"{t}"' for t in tables) + " RESTART IDENTITY CASCADE"
                )
            )
    await engine.dispose()


@pytest.fixture
async def clean_state(migrated: None, buckets: None) -> AsyncIterator[None]:
    from app.core import flags
    from app.core.redis import get_redis
    from app.modules import registry

    # Like every entry point (API, worker, CLI), the test process loads its event subscribers
    # before anything publishes; the outbox refuses to publish otherwise.
    registry.load_handlers()
    await _truncate()
    await get_redis().flushall()
    flags.clear_cache()
    yield


@pytest.fixture
async def app(clean_state: None) -> Any:
    from app.main import app as fastapi_app
    from app.modules import registry

    registry.load_handlers()
    return fastapi_app


@pytest.fixture
async def client(app: Any) -> AsyncIterator[Any]:
    import httpx

    transport = httpx.ASGITransport(app=app, client=("203.0.113.10", 50000))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest.fixture
async def db(clean_state: None) -> AsyncIterator[Any]:
    from app.core.db import get_sessionmaker

    async with get_sessionmaker()() as s:
        yield s


class EicarScanner:
    """Local stand-in for clamd: flags the standard EICAR test string, passes everything else."""

    EICAR = rb"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"

    async def scan(self, data: bytes) -> Any:
        from app.modules.files.scanner import ScanResult

        if self.EICAR in data:
            return ScanResult(clean=False, signature="Eicar-Test-Signature", engine="test")
        return ScanResult(clean=True, signature=None, engine="test")


@pytest.fixture(autouse=True)
def fake_scanner() -> Iterator[None]:
    from app.modules.files.scanner import set_scanner

    set_scanner(EicarScanner())
    yield
    set_scanner(None)
