"""Migrations are safe to roll back, and the models match the schema they build.

Release policy (RULES section 4): a migration only expands the schema. A column or table is removed in
a later release, after no running code reads it, so the previous image still works against the
new schema and a rollback is just redeploying the previous tag. These tests hold every migration
to that:

1. `upgrade()` never drops or renames a table or column, never changes a column's type, and
   never adds a NOT NULL column without a server default. Older migrations written before the
   first release are listed in `_BEFORE_POLICY` with the reason.
2. Every `downgrade()` runs: a throwaway database goes up to head, down to base and up again.
3. The models and the migrated schema agree (no drift), so nothing relies on a table or column
   that only exists in Python.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from tests.harness import _SCHEMA_SQL, _pg_exec

VERSIONS = Path(__file__).resolve().parent.parent / "migrations" / "versions"
ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"

_DESTRUCTIVE_OPS = {"drop_table", "drop_column", "rename_table"}
_DESTRUCTIVE_SQL = ("DROP TABLE", "DROP COLUMN", "RENAME COLUMN", "RENAME TO", "ALTER COLUMN")

# Written before the first production release, when no older image could be running.
_BEFORE_POLICY = {
    "20261003_0010_field_states_v21.py": "field state names widened and submitted_at removed "
    "before the first release (ADR 0015)",
}


def _upgrade_calls(path: Path) -> list[ast.Call]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "upgrade")
    return [n for n in ast.walk(fn) if isinstance(n, ast.Call)]


def _op_name(call: ast.Call) -> str | None:
    f = call.func
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "op":
        return f.attr
    return None


def _kw(call: ast.Call, name: str) -> ast.expr | None:
    return next((k.value for k in call.keywords if k.arg == name), None)


def _problems(path: Path) -> list[str]:
    found: list[str] = []
    for call in _upgrade_calls(path):
        name = _op_name(call)
        if name in _DESTRUCTIVE_OPS:
            found.append(f"op.{name}")
        elif name == "alter_column":
            if _kw(call, "type_") is not None or _kw(call, "new_column_name") is not None:
                found.append("op.alter_column changes a type or a name")
            nullable = _kw(call, "nullable")
            if isinstance(nullable, ast.Constant) and nullable.value is False:
                found.append("op.alter_column sets NOT NULL on an existing column")
        elif name == "execute" and call.args and isinstance(call.args[0], ast.Constant):
            sql = str(call.args[0].value).upper()
            found += [f"SQL {s}" for s in _DESTRUCTIVE_SQL if s in sql]
        elif name == "add_column" and len(call.args) >= 2:
            col = call.args[1]
            if isinstance(col, ast.Call):
                nullable = _kw(col, "nullable")
                not_null = isinstance(nullable, ast.Constant) and nullable.value is False
                if not_null and _kw(col, "server_default") is None:
                    found.append("op.add_column NOT NULL without a server default")
    return found


def test_every_upgrade_only_expands_the_schema() -> None:
    files = sorted(p for p in VERSIONS.glob("*.py") if not p.name.startswith("__"))
    assert files, "no migrations found"
    bad = {p.name: probs for p in files if p.name not in _BEFORE_POLICY and (probs := _problems(p))}
    assert not bad, f"migrations that would break a rollback: {bad}"


def test_policy_exceptions_still_exist() -> None:
    # A stale entry would hide nothing today but excuse a future file with the same name.
    for name in _BEFORE_POLICY:
        assert (VERSIONS / name).exists(), name


def _alembic(url: str) -> Any:
    from alembic.config import Config

    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(VERSIONS.parent))
    cfg.attributes["url"] = url
    return cfg


def test_downgrade_to_base_and_up_again(containers: dict[str, Any], settings_env: None) -> None:
    from alembic import command

    pg = containers["pg"]
    db = "p1_migration_check"
    _pg_exec(
        pg, "postgres", [f"DROP DATABASE IF EXISTS {db}", f"CREATE DATABASE {db} OWNER p1_owner"]
    )
    _pg_exec(pg, db, _SCHEMA_SQL)
    host, port = pg.get_container_host_ip(), pg.get_exposed_port(5432)
    cfg = _alembic(f"postgresql+asyncpg://p1_owner:owner_test@{host}:{port}/{db}")
    try:
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")
    finally:
        _pg_exec(pg, "postgres", [f"DROP DATABASE IF EXISTS {db} WITH (FORCE)"])


# Objects the models do not describe on purpose: the generated search vector and the indexes
# and triggers written as raw SQL in the migrations.
_NOT_IN_MODELS = {"alembic_version"}


def _include(obj: Any, name: str | None, kind: str, reflected: bool, compare_to: Any) -> bool:
    return name not in _NOT_IN_MODELS


@pytest.mark.usefixtures("migrated")
def test_models_match_migrated_schema() -> None:
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from sqlalchemy import create_engine

    from app.core.config import get_settings
    from app.core.db import Base
    from app.modules.registry import load_models

    load_models()
    url = get_settings().database_owner_url.replace("+asyncpg", "+psycopg")
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(
                conn, opts={"compare_type": True, "include_object": _include}
            )
            diff = compare_metadata(ctx, Base.metadata)
    finally:
        engine.dispose()
    assert diff == [], f"models and migrations disagree: {diff}"
