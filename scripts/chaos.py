"""Chaos checks against the running development stack. Never run it against production.

    backend/.venv/Scripts/python.exe scripts/chaos.py [--accounts .demo/demo-accounts.json]
                                                      [--only worker,api,valkey,database]

Each check breaks one thing on purpose, then proves the system comes back by itself:

worker     Starts a 60 second probe task, kills the worker while it holds it, starts it again.
           The outbox must keep draining, and the killed task must be run again (tasks are
           acknowledged late and given back when a worker dies; Valkey hands an unacknowledged
           task out again after the visibility timeout, 10 minutes).
api        Asks for a quotation PDF and kills the API while it is laid out. The request fails
           cleanly, the API comes back on its own (restart policy), and the same PDF downloads.
valkey     Restarts Valkey. /healthz stays up, /readyz says not ready and then ready, and signed
           in requests work again once it is back (rate limits and sessions reconnect).
database   Cuts every app connection to PostgreSQL. The next requests succeed, because the pool
           tests a connection before using it.

Prints one line per step and PASS or FAIL per check; exits 1 if any check fails.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pyotp

COMPOSE = ["docker", "compose", "-f", "docker-compose.yml", "-f", "docker-compose.dev.yml"]
ENV = {**os.environ, "MSYS_NO_PATHCONV": "1"}
API_BASE = "http://localhost:9596"
API = "/api/v1"
REDELIVERY_WAIT = 780  # Valkey visibility timeout (600 s), the 60 s task and some slack


def sh(*args: str, check: bool = True) -> str:
    r = subprocess.run(args, capture_output=True, text=True, env=ENV, check=False)
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(args)}\n{r.stderr or r.stdout}")
    return r.stdout


def step(msg: str) -> None:
    print(f"  {time.strftime('%H:%M:%S')}  {msg}", flush=True)


def wait_for(what: str, ok, timeout: float, every: float = 1.0) -> float:
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout:
        try:
            if ok():
                took = time.perf_counter() - t0
                step(f"{what} after {took:.1f} s")
                return took
        except (httpx.HTTPError, RuntimeError):
            pass
        time.sleep(every)
    raise AssertionError(f"{what}: not within {timeout:.0f} s")


def ready() -> bool:
    return httpx.get(f"{API_BASE}/readyz", timeout=5).status_code == 200


def metric(name: str) -> float | None:
    body = httpx.get(f"{API_BASE}/metrics", timeout=10).text
    m = re.search(rf"^{name}\s+([0-9.e+]+)$", body, re.M)
    return float(m.group(1)) if m else None


def sign_in(accounts: Path) -> httpx.Client:
    acc = json.loads(accounts.read_text(encoding="utf-8"))
    user = next(u for u in acc["users"] if "director" in u["roles"])
    c = httpx.Client(base_url=API_BASE, timeout=60)
    for attempt in range(2):
        r = c.post(f"{API}/auth/login", json={"email": user["email"], "password": acc["password"]})
        body = r.json()
        if body.get("status") == "mfa_required":
            body = c.post(
                f"{API}/auth/mfa/verify",
                json={
                    "challenge_token": body["challenge_token"],
                    "code": pyotp.TOTP(user["totp_secret"]).now(),
                },
            ).json()
        if "access_token" in body:
            c.headers["Authorization"] = f"Bearer {body['access_token']}"
            return c
        if attempt == 0:
            time.sleep(31 - time.time() % 30)  # a code is accepted once; wait for the next
    raise SystemExit(f"Could not sign in as {user['email']}: {body}")


def signed_in_ok(c: httpx.Client) -> bool:
    return c.get(f"{API}/auth/me").status_code == 200


def a_boq(c: httpx.Client) -> str:
    for p in c.get(f"{API}/projects", params={"size": 50}).json()["items"]:
        r = c.get(f"{API}/projects/{p['id']}/boq")
        if r.status_code == 200:
            return str(r.json()["id"])
    raise SystemExit("No project has a BOQ yet; build the demo data first.")


# --- checks -----------------------------------------------------------------------------------


def probe_ran(token: str) -> bool:
    code = (
        "from app.core.config import get_settings; import redis; "
        f"print(redis.from_url(get_settings().redis_url).get('p1:ops:probe:{token}'))"
    )
    out = sh(*COMPOSE, "exec", "-T", "worker", "python", "-c", code, check=False)
    return out.strip() not in ("", "None")


def check_worker(c: httpx.Client) -> None:
    # The probe waits 60 seconds and then records that it ran, so the kill is sure to land
    # while the task is held by the worker (a backup of a small database is over in a second).
    token = f"chaos-{int(time.time())}"
    args = json.dumps([token, 60])
    sh(
        *COMPOSE,
        "exec",
        "-T",
        "worker",
        "celery",
        "-A",
        "app.worker",
        "call",
        "p1.ops.probe",
        "--args",
        args,
    )
    step("a 60 second task started on the worker")
    time.sleep(5.0)
    sh(*COMPOSE, "kill", "-s", "SIGKILL", "worker")
    step("worker killed while it held the task")
    sh(*COMPOSE, "up", "-d", "--no-deps", "worker")
    wait_for(
        "worker answers a ping",
        lambda: (
            "pong"
            in sh(
                *COMPOSE,
                "exec",
                "-T",
                "worker",
                "celery",
                "-A",
                "app.worker",
                "inspect",
                "ping",
                "--timeout",
                "5",
                check=False,
            )
        ),
        timeout=120,
        every=5,
    )
    wait_for("outbox drained", lambda: (metric("p1_outbox_pending") or 0) == 0, timeout=120)
    assert not probe_ran(token), "the task finished although its worker was killed"
    wait_for(
        "the killed task was handed out again and finished",
        lambda: probe_ran(token),
        timeout=REDELIVERY_WAIT,
        every=15,
    )
    assert signed_in_ok(c)


def check_api(c: httpx.Client) -> None:
    boq = a_boq(c)
    url = f"{API}/boq/{boq}/render"
    result: dict[str, object] = {}

    def download() -> None:
        try:
            result["status"] = c.get(url, params={"fmt": "pdf"}).status_code
        except httpx.HTTPError as exc:
            result["status"] = type(exc).__name__

    t = threading.Thread(target=download)
    t.start()
    time.sleep(0.3)
    sh(*COMPOSE, "kill", "-s", "SIGKILL", "api")
    step("API killed while the PDF was laid out")
    t.join(timeout=60)
    step(f"the request in flight ended with {result.get('status')}")
    sh(*COMPOSE, "up", "-d", "--no-deps", "api")
    wait_for("API ready", ready, timeout=180, every=2)
    r = c.get(url, params={"fmt": "pdf"})
    assert r.status_code == 200, r.status_code
    assert r.content[:4] == b"%PDF", r.content[:40]
    step(f"same PDF downloads again ({len(r.content) // 1024} KB)")


def check_valkey(c: httpx.Client) -> None:
    sh(*COMPOSE, "stop", "redis")
    step("Valkey stopped")
    assert httpx.get(f"{API_BASE}/healthz", timeout=5).status_code == 200
    wait_for("/readyz says not ready", lambda: not ready(), timeout=30)
    while_down = c.get(f"{API}/auth/me").status_code
    step(f"a signed in request while Valkey is down answers {while_down}")
    assert while_down < 500 or while_down == 503, while_down
    sh(*COMPOSE, "start", "redis")
    step("Valkey started")
    wait_for("/readyz says ready", ready, timeout=90)
    wait_for("signed in requests work", lambda: signed_in_ok(c), timeout=60)


def check_database(c: httpx.Client) -> None:
    assert signed_in_ok(c)
    cut = sh(
        *COMPOSE,
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        "postgres",
        "-At",
        "-c",
        "SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity "
        "WHERE usename = 'p1_app' AND pid <> pg_backend_pid()",
    ).strip()
    step(f"{cut} app connections cut")
    codes = [c.get(f"{API}/projects", params={"size": 5}).status_code for _ in range(5)]
    step(f"next five requests answered {codes}")
    assert all(code == 200 for code in codes), codes


CHECKS = {
    "worker": check_worker,
    "api": check_api,
    "valkey": check_valkey,
    "database": check_database,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--accounts", default=".demo/demo-accounts.json")
    ap.add_argument("--only", default=",".join(CHECKS))
    a = ap.parse_args()
    if not ready():
        sys.exit("The stack is not ready; start it with scripts/dev.ps1 up first.")
    c = sign_in(Path(a.accounts))
    failed = []
    for name in a.only.split(","):
        print(f"{name}:", flush=True)
        t0 = time.perf_counter()
        try:
            CHECKS[name](c)
            print(f"  PASS {name} ({time.perf_counter() - t0:.0f} s)\n", flush=True)
        except (AssertionError, RuntimeError) as exc:
            failed.append(name)
            print(f"  FAIL {name}: {exc}\n", flush=True)
            # Leave the stack running for the next check.
            sh(*COMPOSE, "up", "-d", "--no-deps", "redis", "api", "worker", check=False)
            try:
                wait_for("stack ready again", ready, timeout=180, every=2)
                c = sign_in(Path(a.accounts))
            except AssertionError:
                break
    print("all passed" if not failed else f"failed: {', '.join(failed)}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
