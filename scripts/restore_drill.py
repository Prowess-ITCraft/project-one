"""Backup and restore drill against the running Docker stack (development or a spare server).

    backend/.venv/Scripts/python.exe scripts/restore_drill.py          (development)
    python3 scripts/restore_drill.py --prod                              (production server)

1. Takes a fresh backup with the same command as the nightly job (`cli backup`).
2. Copies that dump out of the worker and restores it into a throwaway database
   `project_one_drill` on the same PostgreSQL, as the postgres superuser.
3. Compares row counts of every table between the live database and the restored one.
4. Drops the throwaway database and prints the timings: the restore time is the recovery time.

It never writes to `project_one`. Run it from the repository root.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time

MODE = "docker-compose.prod.yml" if "--prod" in sys.argv else "docker-compose.dev.yml"
COMPOSE = ["docker", "compose", "-f", "docker-compose.yml", "-f", MODE]
DRILL_DB = "project_one_drill"
ENV = {**os.environ, "MSYS_NO_PATHCONV": "1"}


def sh(*args: str, capture: bool = True) -> str:
    r = subprocess.run(args, capture_output=capture, text=True, env=ENV, check=False)
    if r.returncode != 0:
        sys.exit(f"Failed: {' '.join(args)}\n{r.stderr or r.stdout}")
    return r.stdout if capture else ""


def run_bytes(args: list[str], stdin: bytes | None = None) -> bytes:
    r = subprocess.run(args, input=stdin, capture_output=True, env=ENV, check=False)
    if r.returncode != 0:
        err = r.stderr.decode(errors="replace")[-800:]
        sys.exit(f"Failed: {' '.join(args[:8])}\n{err}")
    return r.stdout


def psql(db: str, sql: str) -> str:
    return sh(
        *COMPOSE, "exec", "-T", "postgres", "psql", "-U", "postgres", "-d", db, "-At", "-c", sql
    )


def counts(db: str) -> dict[str, int]:
    tables = psql(
        db,
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename",
    ).split()
    sql = " UNION ALL ".join(f"SELECT '{t}', count(*) FROM public.\"{t}\"" for t in tables)
    out = {}
    for line in psql(db, sql).splitlines():
        name, n = line.split("|")
        out[name] = int(n)
    return out


def main() -> None:
    t0 = time.perf_counter()
    log = sh(*COMPOSE, "exec", "-T", "worker", "python", "-m", "app.cli", "backup")
    m = re.search(r"pg_dump/[\w/]+\.dump", log)
    if not m:
        sys.exit(f"Could not find the backup key in:\n{log}")
    key = m.group(0)
    t_backup = time.perf_counter() - t0
    print(f"backup      {t_backup:6.1f} s   {key}")

    t1 = time.perf_counter()
    # Stream the dump through stdout: the containers' /tmp is an in-memory mount that
    # `docker cp` cannot read.
    fetch = (
        "import sys; from app.core.config import get_settings; from app.core.s3 import s3_client; "
        f"sys.stdout.buffer.write(s3_client().get_object(Bucket=get_settings().s3_bucket_backups, "
        f"Key='{key}')['Body'].read())"
    )
    dump = run_bytes([*COMPOSE, "exec", "-T", "worker", "python", "-c", fetch])
    t_fetch = time.perf_counter() - t1
    print(f"fetch       {t_fetch:6.1f} s   {len(dump) / 1_048_576:.1f} MB")

    psql("postgres", f"DROP DATABASE IF EXISTS {DRILL_DB}")
    psql("postgres", f"CREATE DATABASE {DRILL_DB}")
    t2 = time.perf_counter()
    run_bytes(
        [
            *COMPOSE,
            "exec",
            "-T",
            "postgres",
            "pg_restore",
            "-U",
            "postgres",
            "-d",
            DRILL_DB,
            "--no-owner",
            "--exit-on-error",
        ],
        stdin=dump,
    )
    t_restore = time.perf_counter() - t2
    print(f"restore     {t_restore:6.1f} s")

    live, restored = counts("project_one"), counts(DRILL_DB)
    diff = {
        t: (live.get(t), restored.get(t))
        for t in live.keys() | restored.keys()
        if live.get(t) != restored.get(t)
    }
    print(f"tables      {len(restored)} restored, {sum(restored.values())} rows")
    if diff:
        # The live database keeps working during the drill (outbox, notifications), so a few
        # rows written after the dump are expected there and nowhere else.
        print(
            "different   "
            + ", ".join(f"{t} live {a} restored {b}" for t, (a, b) in sorted(diff.items()))
        )
    else:
        print("different   none")
    chain = psql(DRILL_DB, "SELECT count(*) FROM audit_log")
    print(f"audit log   {chain.strip()} entries restored")

    psql("postgres", f"DROP DATABASE {DRILL_DB}")
    print(f"total       {time.perf_counter() - t0:6.1f} s (recovery time = fetch + restore)")


if __name__ == "__main__":
    main()
