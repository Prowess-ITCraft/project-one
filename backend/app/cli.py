"""Operator commands: `python -m app.cli <command>`.

seed             create catalogue categories, vendors and the sample-BOQ items
create-admin     create the first Admin (password from P1_ADMIN_PASSWORD or a prompt)
expire-prices    run the price expiry job once
dispatch-outbox  drain the outbox once
backup           pg_dump to the backups bucket
backup-export    copy backups not yet in a folder into it (a daily copy off the server)
openapi          write the OpenAPI schema to a file (for the typed frontend client)
api-routes       write every API route, grouped by area, as Markdown (docs/API_ROUTES.md)
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import sys
from pathlib import Path

from app.core import db, redis
from app.core.db import get_sessionmaker


async def _seed() -> None:
    from app.modules import registry
    from app.modules.catalogue.seed import seed_catalogue

    registry.load_models()
    from app.modules.boq.seed import seed_boq
    from app.modules.infra.seed import seed_rules
    from app.modules.planning.seed import seed_planning
    from app.modules.verification.seed import seed_verification

    async with get_sessionmaker()() as s:
        out: dict[str, object] = dict(await seed_catalogue(s))
        out["infra_rules"] = await seed_rules(s)
        out["boq"] = await seed_boq(s)
        out["planning"] = await seed_planning(s)
        out["verification"] = await seed_verification(s)
        print(json.dumps(out))


DEMO_EMAIL = "adi@test.com"
DEMO_PASSWORD = "test1234"  # nosec B105  # noqa: S105  (a documented demo login, refused in prod)


async def _seed_demo() -> None:
    """A login for trying the web app on a development machine. The password is deliberately
    simple, which the normal account rules would refuse, so the account is written directly.
    It holds Admin and every staff role except Director, so the whole app can be seen. Admin
    needs MFA, so the first sign-in sets up an authenticator. Refuses to run when P1_ENV is prod."""
    from sqlalchemy import select

    from app.core.config import get_settings
    from app.modules import registry
    from app.modules.customers import service as customers
    from app.modules.customers.schemas import CustomerCreateIn, ProjectCreateIn
    from app.modules.identity.contracts import P, system_principal
    from app.modules.identity.models import User, UserRole
    from app.modules.identity.permissions import Role
    from app.modules.identity.security import hash_password

    if get_settings().is_prod:
        raise SystemExit(
            "seed-demo is for development machines and refuses to run when P1_ENV=prod."
        )
    registry.load_models()
    roles = [
        Role.ADMIN,  # Admin needs MFA, so the first sign-in sets up an authenticator
        Role.AUDIT_ENGINEER,
        Role.SOLUTION_ARCHITECT,
        Role.TECHNICAL_LEAD,
        Role.SALES_MANAGER,
        Role.SALES_HEAD,
        Role.PROJECT_MANAGER,
        Role.FIELD_ENGINEER,
    ]
    async with get_sessionmaker()() as s:
        user = await s.scalar(select(User).where(User.email == DEMO_EMAIL))
        if user is None:
            user = User(
                email=DEMO_EMAIL,
                full_name="Aditya Kumar",
                initials="AD",
                designation="Demo login",
                password_hash=hash_password(DEMO_PASSWORD),
                is_active=True,
            )
            user.roles = [UserRole(role=r.value) for r in roles]
            s.add(user)
            await s.commit()
            print(f"Created {DEMO_EMAIL} with roles: {', '.join(r.value for r in roles)}")
        else:
            user.password_hash, user.failed_logins, user.locked_until = (
                hash_password(DEMO_PASSWORD),
                0,
                None,
            )
            # Back to a first sign-in: an authenticator entry from an older database no longer
            # matches, so the next sign-in sets one up again.
            user.mfa_enabled = False
            user.mfa_secret_enc = user.mfa_pending_secret_enc = None
            user.mfa_last_used_step = None
            have = {
                r.role for r in await s.scalars(select(UserRole).where(UserRole.user_id == user.id))
            }
            for r in roles:
                if r.value not in have:
                    s.add(UserRole(user_id=user.id, role=r.value))
            await s.commit()
            print(
                f"{DEMO_EMAIL} already exists; password reset to the demo value, unlocked, "
                "and the authenticator cleared (set it up again at sign-in)."
            )
    perms = frozenset(
        {
            P.CUSTOMER_WRITE,
            P.CUSTOMER_READ_ALL,
            P.PROJECT_WRITE,
            P.PROJECT_READ_ALL,
            P.CUSTOMER_READ,
            P.PROJECT_READ,
        }
    )
    sysp = system_principal("demo", perms)
    async with get_sessionmaker()() as s:
        from app.modules.customers.models import Customer

        if (
            await s.scalar(
                select(Customer.id).where(Customer.legal_name == "Shakti Equipments Pvt Ltd")
            )
            is None
        ):
            c = await customers.create_customer(
                s,
                sysp,
                CustomerCreateIn(
                    legal_name="Shakti Equipments Pvt Ltd",
                    address_line1="Plot 12, Wagle Estate",
                    city="Thane",
                    state="Maharashtra",
                    pincode="400605",
                    segment="small",
                    employee_count=35,
                ),
            )
            await customers.create_project(
                s, sysp, ProjectCreateIn(customer_id=c.id, name="IT infrastructure hardening")
            )
            print("Created the demo customer Shakti Equipments and its project.")


async def _create_admin(email: str, name: str, initials: str) -> None:
    from app.modules import registry
    from app.modules.identity import service
    from app.modules.identity.permissions import Role
    from app.modules.identity.schemas import UserCreateIn

    registry.load_models()
    password = os.environ.get("P1_ADMIN_PASSWORD") or getpass.getpass("Admin password: ")
    async with get_sessionmaker()() as s:
        user = await service.create_user(
            s,
            None,
            UserCreateIn(
                email=email,
                full_name=name,
                initials=initials,
                password=password,
                roles=[Role.ADMIN],
            ),
        )
        print(f"Created admin {user.email}. MFA enrolment is required at first sign in.")


async def _expire() -> None:
    from app.modules.catalogue import service

    print(await service.expire_prices(get_sessionmaker()))


async def _dispatch() -> None:
    from app.core import outbox
    from app.modules import registry

    registry.load_handlers()
    total = 0
    while (n := await outbox.dispatch_batch(get_sessionmaker(), limit=50)) > 0:
        total += n
    print(total)


def _openapi(out: str) -> None:
    from app.main import app

    Path(out).write_text(json.dumps(app.openapi(), indent=2), encoding="utf-8")
    print(f"Wrote {out}")


def api_routes_markdown(schema: dict[str, object]) -> str:
    """Every operation in the schema as one table per area (the schema's tags)."""
    methods = ("get", "post", "put", "patch", "delete")
    areas: dict[str, list[tuple[str, str, str, bool]]] = {}
    paths = schema.get("paths", {})
    assert isinstance(paths, dict)
    for path, ops in paths.items():
        for method in methods:
            op = ops.get(method)
            if not op:
                continue
            area = (op.get("tags") or ["other"])[0]
            summary = (op.get("summary") or "").replace("|", "/")
            areas.setdefault(area, []).append(
                (method.upper(), path, summary, bool(op.get("security")))
            )
    total = sum(len(v) for v in areas.values())
    out = [
        "# API routes",
        "",
        f"All {total} operations of the Project One API, grouped by area. Generated from the",
        "code with `python -m app.cli api-routes`; do not edit by hand. The interactive",
        "reference, where you can try each call, is at `/docs` on a running server;",
        "conventions, errors and sign-in are in the [API guide](guides/04-api-guide.md).",
        "",
        '"Sign-in" means the call needs a signed-in user (a bearer token or the session cookie);',
        "what each role may call is in the permission matrix test.",
        "",
    ]
    for area in sorted(areas, key=str.lower):
        rows = sorted(areas[area], key=lambda r: (r[1], methods.index(r[0].lower())))
        out += [
            f"## {area[:1].upper()}{area[1:]}",
            "",
            "| Method | Path | What it does | Sign-in |",
        ]
        out.append("| --- | --- | --- | --- |")
        out += [f"| {m} | `{pth}` | {s} | {'yes' if sec else 'no'} |" for m, pth, s, sec in rows]
        out.append("")
    return "\n".join(out)


def _api_routes(out: str) -> None:
    from app.main import app

    Path(out).write_text(api_routes_markdown(app.openapi()), encoding="utf-8")
    print(f"Wrote {out}")


def _corpus_convert(folder: str, out: str) -> int:
    """Convert every PDF, Word, Excel and JSON file in `folder` into canonical corpus JSON in
    `out`, without a database (ADR 0014). Writes `<name>.json` (readable) and an index."""
    import json
    from pathlib import Path

    from app.modules.datasets.corpus import EPOCH, build_record
    from app.modules.datasets.library import SUFFIXES

    src, dest = Path(folder), Path(out)
    dest.mkdir(parents=True, exist_ok=True)
    index = []
    for path in sorted(src.iterdir()):
        if not path.is_file() or path.suffix.lower() not in SUFFIXES:
            continue
        # A fixed build time keeps the output byte-stable for files kept in git.
        built = build_record(path.read_bytes(), path.name, origin="folder", built_at=EPOCH)
        rec = built.record
        name = f"{path.stem}.json"
        (dest / name).write_text(
            json.dumps(rec, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8"
        )
        index.append(
            {
                "file": name,
                "source": path.name,
                "kind": rec["kind"],
                "quality": rec["quality"]["score"],
                "original_bytes": rec["sizes"]["original"],
                "gzip_bytes": rec["sizes"]["gzip"],
            }
        )
        print(
            f"{rec['kind']:6} q={rec['quality']['score']:3} "
            f"{rec['sizes']['original']:>9} -> {rec['sizes']['gzip']:>7} bytes  {path.name}"
        )
    (dest / "index.json").write_text(json.dumps(index, indent=1) + "\n", encoding="utf-8")
    return len(index)


async def _corpus_rebuild() -> None:
    from app.modules.datasets import corpus_service

    async with db.get_sessionmaker()() as s:
        print(await corpus_service.rebuild(s))


async def _corpus_purge(days: int | None) -> None:
    from app.modules.datasets import corpus_service

    async with db.get_sessionmaker()() as s:
        print(f"purged {await corpus_service.purge_originals(s, days=days)} original(s)")


async def _corpus_ingest(folder: str) -> None:
    """Add every file in `folder` to the library without moving it (used for samples/)."""
    from pathlib import Path

    from app.modules.datasets import library

    print(await library.scan_folder(db.get_sessionmaker(), Path(folder), move=False))


def main(argv: list[str] | None = None) -> int:
    from app.modules import registry

    registry.load_models()
    registry.load_handlers()  # events published by commands must reach their subscribers
    p = argparse.ArgumentParser(prog="app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed")
    a = sub.add_parser("create-admin")
    a.add_argument("--email", required=True)
    a.add_argument("--name", required=True)
    a.add_argument("--initials", required=True)
    sub.add_parser("expire-prices")
    sub.add_parser("dispatch-outbox")
    sub.add_parser("backup")
    be = sub.add_parser("backup-export", help="copy new backups into a folder")
    be.add_argument("--out", required=True)
    sub.add_parser("init-storage")
    sub.add_parser("seed-demo")
    dp = sub.add_parser("demo-projects", help="walk two demo projects through the API (dev only)")
    dp.add_argument("--samples", default="../samples")
    dp.add_argument("--out", default="demo-accounts.json")
    o = sub.add_parser("openapi")
    o.add_argument("--out", default="openapi.json")
    ar = sub.add_parser("api-routes", help="write every API route as Markdown")
    ar.add_argument("--out", default="../docs/API_ROUTES.md")
    c = sub.add_parser("corpus", help="document corpus tools (ADR 0014)")
    csub = c.add_subparsers(dest="corpus_cmd", required=True)
    cc = csub.add_parser("convert", help="convert a folder offline, no database needed")
    cc.add_argument("folder")
    cc.add_argument("--out", default="corpus")
    ci = csub.add_parser("ingest", help="add a folder to the library without moving files")
    ci.add_argument("folder")
    csub.add_parser("rebuild", help="re-read kept originals and rebuild the collections")
    csub.add_parser("requeue", help="send files still waiting in the library to be read again")
    rs = sub.add_parser("render-samples", help="render every PDF template from the samples")
    rs.add_argument("--corpus", default="../samples/corpus")
    rs.add_argument("--out", default="sample-documents")
    cp = csub.add_parser("purge", help="apply the originals retention rule")
    cp.add_argument("--days", type=int, default=None)
    args = p.parse_args(argv)

    if args.cmd == "demo-projects":
        from pathlib import Path

        from app.demo import run as run_demo

        asyncio.run(run_demo(Path(args.samples), Path(args.out)))
        return 0
    if args.cmd == "render-samples":
        from pathlib import Path

        from app.sample_documents import render_all

        render_all(Path(args.corpus), Path(args.out))
        return 0
    if args.cmd == "corpus" and args.corpus_cmd == "convert":
        print(f"{_corpus_convert(args.folder, args.out)} file(s) converted")
        return 0

    if args.cmd == "openapi":
        _openapi(args.out)
        return 0
    if args.cmd == "api-routes":
        _api_routes(args.out)
        return 0
    if args.cmd == "init-storage":
        from app.core.config import get_settings
        from app.core.s3 import ensure_bucket

        cfg = get_settings()
        for bucket in (cfg.s3_bucket_files, cfg.s3_bucket_backups):
            ensure_bucket(bucket)
            print(f"bucket ready: {bucket}")
        return 0
    if args.cmd == "backup":
        from app import ops

        print(ops.run_backup())
        return 0
    if args.cmd == "backup-export":
        from app import ops

        print(f"{ops.export_backups(args.out)} new backup(s) copied to {args.out}")
        return 0

    async def run() -> None:
        try:
            if args.cmd == "seed":
                await _seed()
            elif args.cmd == "seed-demo":
                await _seed_demo()
            elif args.cmd == "create-admin":
                await _create_admin(args.email, args.name, args.initials)
            elif args.cmd == "expire-prices":
                await _expire()
            elif args.cmd == "dispatch-outbox":
                await _dispatch()
            elif args.cmd == "corpus" and args.corpus_cmd == "rebuild":
                await _corpus_rebuild()
            elif args.cmd == "corpus" and args.corpus_cmd == "purge":
                await _corpus_purge(args.days)
            elif args.cmd == "corpus" and args.corpus_cmd == "requeue":
                from app.modules.datasets import library

                async with db.get_sessionmaker()() as s:
                    print(f"{await library.requeue_waiting(s)} file(s) sent to be read")
            elif args.cmd == "corpus" and args.corpus_cmd == "ingest":
                await _corpus_ingest(args.folder)
        finally:
            await redis.close_redis()
            await db.dispose_engine()

    asyncio.run(run())
    return 0


if __name__ == "__main__":
    sys.exit(main())
