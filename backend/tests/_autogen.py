"""Dev helper: autogenerate a migration against a throwaway Postgres. Usage:
python -m tests._autogen "message" REV_ID"""

import os
import sys

from testcontainers.postgres import PostgresContainer

from tests.harness import _ROLE_SQL, _SCHEMA_SQL, PG_IMAGE, _pg_exec

msg, rev = sys.argv[1], sys.argv[2]
pg = PostgresContainer(
    PG_IMAGE, username="postgres", password="pgtest", dbname="postgres", driver=None
)
pg.start()
try:
    _pg_exec(pg, "postgres", _ROLE_SQL)
    _pg_exec(pg, "project_one", _SCHEMA_SQL)
    host, port = pg.get_container_host_ip(), pg.get_exposed_port(5432)
    os.environ["P1_DATABASE_OWNER_URL"] = (
        f"postgresql+asyncpg://p1_owner:owner_test@{host}:{port}/project_one"
    )
    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")
    command.revision(cfg, message=msg, autogenerate=True, rev_id=rev)
finally:
    pg.stop()
