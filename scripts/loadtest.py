"""A small load test for the busiest read paths. Run it against a stack you own, never production.

    backend/.venv/Scripts/python.exe scripts/loadtest.py --base http://localhost:9597 \
        --users 20 --seconds 60 --accounts .demo/demo-accounts.json

Each virtual user signs in once as a demo account and then loops over the paths its role uses,
with no think time. The rate limiter is part of the system under test, so 429s are reported
separately from errors. Prints p50, p95 and max per path.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from collections import defaultdict
from pathlib import Path

import httpx
import pyotp

API = "/api/v1"
PATHS = {
    "director": ["/dashboard", "/projects?size=50", "/auth/me"],
    "project_manager": ["/projects?size=50", "/auth/me"],
    "field_engineer": ["/field/my", "/auth/me"],
    "sales_manager": ["/projects?size=50", "/catalogue/items?size=50", "/auth/me"],
}


async def sign_in(c: httpx.AsyncClient, user: dict, password: str) -> str:
    for attempt in range(2):
        r = (
            await c.post(f"{API}/auth/login", json={"email": user["email"], "password": password})
        ).json()
        if r.get("status") == "mfa_required":
            code = pyotp.TOTP(user["totp_secret"]).now()
            r = (
                await c.post(
                    f"{API}/auth/mfa/verify",
                    json={"challenge_token": r["challenge_token"], "code": code},
                )
            ).json()
        if "access_token" in r:
            return str(r["access_token"])
        if attempt == 0 and user.get("totp_secret"):
            # An authenticator code is accepted once; wait for the next one.
            await asyncio.sleep(31 - time.time() % 30)
    raise SystemExit(f"Could not sign in as {user['email']}: {r.get('detail') or r}")


async def worker(base: str, token: str, role: str, until: float, out: dict) -> None:
    async with httpx.AsyncClient(base_url=base, timeout=30) as c:
        c.headers["Authorization"] = f"Bearer {token}"
        paths = PATHS[role]
        i = 0
        while time.perf_counter() < until:
            path = paths[i % len(paths)]
            i += 1
            t0 = time.perf_counter()
            try:
                r = await c.get(API + path)
                code = r.status_code
            except httpx.HTTPError:
                code = 0
            ms = (time.perf_counter() - t0) * 1000
            key = path.split("?")[0]
            if code == 200:
                out["ok"][key].append(ms)
            elif code == 429:
                out["limited"][key] += 1
            else:
                out["errors"][key] += 1
                out["codes"][code] += 1


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:9597")
    ap.add_argument("--users", type=int, default=20)
    ap.add_argument("--seconds", type=int, default=60)
    ap.add_argument("--accounts", default=".demo/demo-accounts.json")
    a = ap.parse_args()
    acc = json.loads(Path(a.accounts).read_text(encoding="utf-8"))
    pool = [(u, r) for r in PATHS for u in acc["users"] if r in u["roles"]]
    out = {
        "ok": defaultdict(list),
        "limited": defaultdict(int),
        "errors": defaultdict(int),
        "codes": defaultdict(int),
    }
    # One sign-in per account (an authenticator code is accepted once), shared by its users.
    tokens = {}
    async with httpx.AsyncClient(base_url=a.base, timeout=30) as c:
        for u, _ in pool:
            tokens[u["email"]] = await sign_in(c, u, acc["password"])
    until = time.perf_counter() + a.seconds
    jobs = [
        worker(a.base, tokens[pool[i % len(pool)][0]["email"]], pool[i % len(pool)][1], until, out)
        for i in range(a.users)
    ]
    started = time.perf_counter()
    await asyncio.gather(*jobs)
    took = time.perf_counter() - started
    total = sum(len(v) for v in out["ok"].values())
    print(f"{a.users} users, {took:.0f} s, {total} ok requests, {total / took:.1f} per second")
    if out["codes"]:
        print("failures by status: " + ", ".join(f"{k}: {v}" for k, v in sorted(out["codes"].items())))
    print(f"{'path':<24}{'ok':>7}{'p50 ms':>9}{'p95 ms':>9}{'max ms':>9}{'429':>6}{'err':>6}")
    for path in sorted(set(out["ok"]) | set(out["limited"]) | set(out["errors"])):
        xs = sorted(out["ok"].get(path, []))
        p50 = statistics.median(xs) if xs else 0
        p95 = xs[int(len(xs) * 0.95) - 1] if xs else 0
        print(
            f"{path:<24}{len(xs):>7}{p50:>9.0f}{p95:>9.0f}{(xs[-1] if xs else 0):>9.0f}"
            f"{out['limited'][path]:>6}{out['errors'][path]:>6}"
        )


if __name__ == "__main__":
    asyncio.run(main())
