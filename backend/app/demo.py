"""Demo data: two real projects walked through the API exactly as people would, for looking
around the screens and for the browser smoke tests. Development only; refuses to run in prod.

    python -m app.cli demo --samples /data/samples --out /out/demo-accounts.json

- "Head office IT hardening" goes through every gate to a signed certificate: audit, current
  and ideal state, gaps (customer acknowledged), BOQ with a purchase order, plan, field work
  (one configuration check fails first, then passes), rescan, report, certificate.
- "Plant network refresh" stops in field work: one task closed, one waiting for the
  verifier, one sent back by a failed check with a critical deviation open, one blocked,
  and a waiver waiting for the Director.

Staff accounts get realistic names and one shared demo password; the Director and Admin need
MFA, so their TOTP secrets go into the accounts file (add them to an authenticator app, or let
the smoke tests compute the codes). Nothing here is presented as real customer data.
"""

from __future__ import annotations

import io
import json
import re
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pyotp
from PIL import Image, ImageDraw
from sqlalchemy import select

from app.core import crypto, outbox
from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.redis import get_redis
from app.core.timeutil import IST, today_ist, utcnow

API = "/api/v1"
DOMAIN = "itcraft.net.in"

STAFF = [
    ("rajesh.iyer", "Rajesh Iyer", "RI", "Director", ["director"]),
    ("priya.nair", "Priya Nair", "PN", "Sales manager", ["sales_manager"]),
    ("arvind.rao", "Arvind Rao", "AR", "Sales head", ["sales_head"]),
    ("shruti", "Shruti Satam", "SS", "Audit engineer", ["audit_engineer"]),
    ("nikhil.joshi", "Nikhil Joshi", "NJ", "Solution architect", ["solution_architect"]),
    ("aditya", "Aditya Kumar", "AK", "Technical lead", ["technical_lead"]),
    ("farah.khan", "Farah Khan", "FK", "Project manager", ["project_manager"]),
    ("ravi.kulkarni", "Ravi Kulkarni", "RK", "Field engineer", ["field_engineer"]),
    ("sneha.patil", "Sneha Patil", "SP", "Field engineer", ["field_engineer"]),
]
PRICES = {
    "SVC-SANITIZE": "500.00",
    "LIC-ACRONIS-XDR": "1562.00",
    "SVC-EPS-SETUP": "12000.00",
    "HW-SW-CISCO-C1300-24T": "33972.00",
    "SVC-SWITCH-SETUP": "6000.00",
    "HW-FW-SOPHOS-XGS108": "66812.00",
    "HW-FW-FORTI-FG40F": "109653.00",
    "SVC-FW-SETUP": "12000.00",
    "SVC-FW-SUPPORT": "15000.00",
}
BRIEF = {
    "company_size": "small",
    "budget_tier": "standard",
    "users_now": 27,
    "users_12m": 35,
    "sites": 1,
    "preferred_brands": ["Sophos"],
    "excluded_brands": [],
    "budget_ceiling": "600000.00",
    "keep_assets": ["Cisco Business 350 switch"],
    "compliance": [],
}


class DemoError(RuntimeError):
    pass


@dataclass
class Person:
    key: str
    name: str
    email: str
    roles: list[str]
    id: str = ""
    totp: str | None = None
    headers: dict[str, str] = field(default_factory=dict)


def _png(label: str, color: tuple[int, int, int] = (44, 98, 159)) -> bytes:
    img = Image.new("RGB", (480, 320), (243, 245, 248))
    d = ImageDraw.Draw(img)
    d.rectangle((12, 12, 468, 308), outline=color, width=4)
    d.text((28, 140), f"Demo photo: {label}"[:60], fill=color)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def demo_stamp() -> bytes:
    """A placeholder stamp, clearly marked, until IITPL sends the real one."""
    img = Image.new("RGBA", (360, 360), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    blue = (31, 64, 140, 235)
    d.ellipse((10, 10, 350, 350), outline=blue, width=10)
    d.ellipse((46, 46, 314, 314), outline=blue, width=4)
    d.text((130, 150), "IITPL", fill=blue)
    d.text((112, 180), "DEMO STAMP", fill=blue)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


class Demo:
    def __init__(self, client: httpx.AsyncClient, samples: Path) -> None:
        self.c = client
        self.samples = samples
        self.people: dict[str, Person] = {}
        self.password = "Demo-" + secrets.token_urlsafe(9)
        self.log: list[str] = []
        self.cust: dict[str, Any] = {}
        self.previous: dict[str, Any] | None = None
        self.certificate: str | None = None

    # ------------------------------------------------------------------ plumbing

    def say(self, text: str) -> None:
        self.log.append(text)
        print(text, flush=True)

    async def call(
        self,
        method: str,
        path: str,
        who: Person | None,
        *,
        json_body: Any = None,
        ok: tuple[int, ...] = (200, 201, 204),
        idem: bool = False,
        **kw: Any,
    ) -> Any:
        headers = dict(who.headers) if who else {}
        if idem:
            headers["Idempotency-Key"] = uuid.uuid4().hex
        r = await self.c.request(method, f"{API}{path}", json=json_body, headers=headers, **kw)
        if r.status_code not in ok:
            raise DemoError(
                f"{method} {path} as {who.name if who else 'public'}: "
                f"{r.status_code} {r.text[:400]}"
            )
        return r.json() if r.content and "json" in r.headers.get("content-type", "") else None

    async def settle(self) -> None:
        """Deliver outbox events now, so locked artifacts reach the stage tracker."""
        for _ in range(5):
            if not await outbox.dispatch_batch(get_sessionmaker()):
                break

    async def _clear_limits(self) -> None:
        r = get_redis()
        async for k in r.scan_iter(match="rl:*"):
            await r.delete(k)

    async def _code(self, related: str, template: str) -> str:
        from app.modules.notifications.models import Notification

        async with get_sessionmaker()() as s:
            n = await s.scalar(
                select(Notification)
                .where(Notification.related_id == related, Notification.template == template)
                .order_by(Notification.created_at.desc())
                .limit(1)
            )
        if n is None:
            raise DemoError(f"No {template} message for {related}")
        m = re.search(r"\b(\d{6})\b", n.body) or re.search(
            r"/ack/waiver/([A-Za-z0-9_\-]{20,})", n.body
        )
        if not m:
            raise DemoError(f"No code in {template}")
        return m.group(1)

    # ------------------------------------------------------------------ people

    async def staff(self) -> None:
        from app.modules.identity import service
        from app.modules.identity.models import User
        from app.modules.identity.permissions import MFA_REQUIRED_ROLES, Role
        from app.modules.identity.schemas import UserCreateIn

        async with get_sessionmaker()() as s:
            taken = await s.scalar(select(User.id).where(User.email == f"{STAFF[0][0]}@{DOMAIN}"))
        if taken:
            await self._resume_staff()
            return
        for key, name, initials, designation, roles in STAFF:
            email = f"{key}@{DOMAIN}"
            secret = None
            async with get_sessionmaker()() as s:
                u = await service.create_user(
                    s,
                    None,
                    UserCreateIn(
                        email=email,
                        full_name=name,
                        initials=initials,
                        designation=designation,
                        password=self.password,
                        roles=[Role(r) for r in roles],
                    ),
                )
                if {Role(r) for r in roles} & MFA_REQUIRED_ROLES:
                    secret = pyotp.random_base32()
                    u.mfa_secret_enc = crypto.encrypt_str(secret)
                    u.mfa_enabled = True
                    await s.commit()
                uid = str(u.id)
            self.people[key] = Person(key, name, email, roles, uid, secret)
        for p in self.people.values():
            await self.login(p)
        self.say(f"{len(STAFF)} staff accounts ready")

    async def _resume_staff(self) -> None:
        """A second run reuses the accounts the first one wrote."""
        from app.modules.identity.models import User

        if not self.previous:
            raise DemoError("Demo staff exist but the accounts file is missing. Nothing changed.")
        self.password = self.previous["password"]
        known = {u["email"]: u for u in self.previous["users"]}
        for key, name, _i, _d, roles in STAFF:
            email = f"{key}@{DOMAIN}"
            async with get_sessionmaker()() as s:
                uid = await s.scalar(select(User.id).where(User.email == email))
            self.people[key] = Person(
                key, name, email, roles, str(uid), known.get(email, {}).get("totp_secret")
            )
        for p in self.people.values():
            await self.login(p)
        self.say("Reusing the demo staff accounts")

    async def login(self, p: Person) -> None:
        await self._clear_limits()
        body = await self.call(
            "POST", "/auth/login", None, json_body={"email": p.email, "password": self.password}
        )
        if body["status"] == "mfa_required":
            body = await self.call(
                "POST",
                "/auth/mfa/verify",
                None,
                json_body={
                    "challenge_token": body["challenge_token"],
                    "code": pyotp.TOTP(p.totp or "").now(),
                },
            )
        p.headers = {"Authorization": f"Bearer {body['access_token']}"}

    # ------------------------------------------------------------------ reference data

    async def reference(self) -> None:
        from app.modules.boq.seed import seed_boq
        from app.modules.catalogue.seed import seed_catalogue
        from app.modules.infra.seed import seed_rules
        from app.modules.planning.seed import seed_planning
        from app.modules.verification.seed import seed_verification

        for fn in (seed_catalogue, seed_rules, seed_boq, seed_planning, seed_verification):
            async with get_sessionmaker()() as s:
                await fn(s)
        today = today_ist()
        sales = self.people["priya.nair"]
        for code, selling in PRICES.items():
            items = (await self.call("GET", "/catalogue/items", sales, params={"q": code}))["items"]
            if not items:
                continue
            await self.call(
                "POST",
                f"/catalogue/items/{items[0]['id']}/prices",
                sales,
                idem=True,
                json_body={
                    "supplier": "Ingram Micro India",
                    "cost": str(round(float(selling) * 0.82, 2)),
                    "selling": selling,
                    "quoted_on": str(today),
                    "valid_until": str(today + timedelta(days=21)),
                    "source_note": "Distributor quote for the demo",
                },
            )
        self.say("Catalogue prices, rules and templates ready")

    async def customer(self) -> dict[str, Any]:
        sales = self.people["priya.nair"]
        found = await self.call("GET", "/customers", sales, params={"q": "Shakti"})
        items = found["items"] if isinstance(found, dict) else found
        cust = (
            items[0]
            if items
            else await self.call(
                "POST",
                "/customers",
                sales,
                json_body={
                    "legal_name": "Shakti Equipments Pvt Ltd",
                    "address_line1": "Plot 12, Wagle Estate",
                    "city": "Thane",
                    "state": "Maharashtra",
                    "pincode": "400605",
                },
            )
        )
        contacts = await self.call("GET", f"/customers/{cust['id']}/contacts", sales)
        if not any(c["full_name"] == "Meera Shah" for c in contacts):
            await self.call(
                "POST",
                f"/customers/{cust['id']}/contacts",
                sales,
                json_body={
                    "full_name": "Meera Shah",
                    "email": "meera.shah@shakti.example",
                    "designation": "IT manager",
                    "can_sign_off": True,
                    "is_primary": True,
                },
            )
        return dict(cust)

    # ------------------------------------------------------------------ gates

    async def gate(
        self, pid: str, stage: str, artifact_type: str, submitter: Person, approver: Person
    ) -> None:
        await self.settle()
        arts = await self.call("GET", f"/projects/{pid}/artifacts", submitter)
        art = [a for a in arts if a["artifact_type"] == artifact_type]
        if not art:
            raise DemoError(f"No locked {artifact_type} for {stage}")
        sub = await self.call(
            "POST",
            f"/projects/{pid}/stages/{stage}/submit",
            submitter,
            idem=True,
            json_body={"artifact_id": art[-1]["id"], "note": None},
        )
        if sub.get("requires_customer_ack"):
            contacts = await self.call(
                "GET", f"/customers/{self.cust['id']}/contacts", self.people["priya.nair"]
            )
            meera = next(c for c in contacts if c["full_name"] == "Meera Shah")
            link = await self.call(
                "POST",
                f"/projects/{pid}/submissions/{sub['id']}/customer-ack",
                self.people["priya.nair"],
                json_body={"contact_id": meera["id"]},
            )
            token = link["url"].rsplit("/", 1)[-1]
            await self.call(
                "POST",
                f"/public/acks/{token}",
                None,
                json_body={"full_name": "Meera Shah", "accept": True},
            )
        await self.call(
            "POST",
            f"/projects/{pid}/submissions/{sub['id']}/approve",
            approver,
            idem=True,
            json_body={"comment": "Checked and approved"},
        )
        self.say(f"  gate approved: {stage}")

    # ------------------------------------------------------------------ one project

    async def project(self, name: str, rescan_scores: dict[str, str] | None) -> str:
        ppl = self.people
        sales, head, auditor, arch = (
            ppl["priya.nair"],
            ppl["arvind.rao"],
            ppl["shruti.satam"],
            ppl["nikhil.joshi"],
        )
        lead, pm, director = ppl["anil.deshmukh"], ppl["farah.khan"], ppl["rajesh.iyer"]
        proj = await self.call(
            "POST",
            "/projects",
            sales,
            idem=True,
            json_body={"customer_id": self.cust["id"], "name": name},
        )
        pid = proj["id"]
        self.say(f"Project {proj['code']} {name}")
        for who, role in [
            (head, "sales_head"),
            (auditor, "audit_engineer"),
            (arch, "solution_architect"),
            (lead, "technical_lead"),
            (pm, "project_manager"),
            (director, "director"),
            (ppl["ravi.kulkarni"], "field_engineer"),
            (ppl["sneha.patil"], "field_engineer"),
        ]:
            await self.call(
                "PUT",
                f"/projects/{pid}/members",
                head,
                json_body={"user_id": who.id, "project_role": role},
            )

        # audit intake: the PrismSuite Word report, read, one conflict resolved, approved
        docx = next(self.samples.glob("*PrismSuite Audit Report.docx"))
        f = await self.call(
            "POST",
            "/files",
            auditor,
            files={
                "file": (
                    docx.name,
                    docx.read_bytes(),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
            data={"purpose": "audit_report", "project_id": pid},
        )
        imp = await self.call(
            "POST",
            "/prismsuite/imports",
            auditor,
            idem=True,
            json_body={"project_id": pid, "file_id": f["id"]},
        )
        version = imp["version"]
        detail = await self.call("GET", f"/prismsuite/imports/{imp['id']}", auditor)
        for fld in detail.get("fields", detail.get("items", [])):
            if fld.get("state") == "conflict" or fld.get("status") == "conflict":
                r = await self.call(
                    "POST",
                    f"/prismsuite/imports/{imp['id']}/resolutions",
                    auditor,
                    json_body={
                        "path": fld["path"],
                        "reason": "Confirmed on site with the IT manager.",
                        "version": version,
                    },
                )
                version = r["version"]
        try:
            r = await self.call(
                "POST",
                f"/prismsuite/imports/{imp['id']}/resolutions",
                auditor,
                json_body={
                    "path": "/devices[firewall]/high_availability",
                    "reason": "Confirmed on site with the IT manager.",
                    "version": version,
                },
            )
            version = r["version"]
        except DemoError:
            pass
        await self.call(
            "POST",
            f"/prismsuite/imports/{imp['id']}/approve",
            arch,
            idem=True,
            json_body={"version": version},
        )
        await self.gate(pid, "audit_intake", "prismsuite_audit", auditor, lead)

        # current and ideal state
        cur = await self.call("POST", f"/projects/{pid}/infra/current", arch)
        await self.call("POST", f"/projects/{pid}/infra/{cur['id']}/lock", arch, idem=True)
        await self.gate(pid, "current_infra", "infra_current", arch, lead)
        await self.call("PUT", f"/projects/{pid}/brief", sales, json_body=BRIEF)
        ideal = await self.call("POST", f"/projects/{pid}/infra/ideal", arch)
        await self.call("POST", f"/projects/{pid}/infra/{ideal['id']}/lock", arch, idem=True)
        await self.gate(pid, "ideal_infra", "infra_ideal", arch, lead)

        # gaps: anything marked "verify" is settled, then locked; the customer acknowledges
        reg = await self.call("POST", f"/projects/{pid}/gaps", arch)
        for g in reg["gaps"]:
            if g["status"] == "verify":
                await self.call(
                    "PATCH",
                    f"/projects/{pid}/gaps/{reg['id']}/items/{g['id']}",
                    arch,
                    json_body={
                        "status": "dismissed",
                        "reason": "Checked with the customer on site.",
                        "version": g["version"],
                    },
                )
        await self.call("POST", f"/projects/{pid}/gaps/{reg['id']}/lock", arch, idem=True)
        await self.gate(pid, "gap_analysis", "gap_register", arch, director)

        # BOQ: drafted from the gaps, priced, approved, issued, accepted with a purchase order
        b = await self.call("POST", f"/projects/{pid}/boq/generate", sales, json_body={})
        ops = [
            {
                "op": "update_line",
                "id": x["id"],
                "fields": {
                    "unit_price": "1500.00",
                    "cost": "1180.00",
                    "manual_price_reason": "Distributor quote by phone",
                },
            }
            for x in b["lines"]
            if x["unit_price"] is None
        ]
        if ops:
            b = await self.call(
                "POST",
                f"/boq/{b['id']}/edit",
                sales,
                json_body={
                    "draft_rev": b["draft_rev"],
                    "reason": "Prices from today's distributor quotes",
                    "ops": ops,
                },
            )
        await self.call("POST", f"/boq/{b['id']}/submit", sales)
        await self.call(
            "POST", f"/boq/{b['id']}/pricing-decision", head, json_body={"approve": True}
        )
        await self.call("POST", f"/boq/{b['id']}/issue", sales, idem=True)
        cur_b = await self.call("GET", f"/boq/{b['id']}", sales)
        chosen = {ln["option_group"]: "A" for ln in cur_b["lines"] if ln["option_group"]}
        await self.call(
            "POST",
            f"/boq/{b['id']}/versions/1/accept",
            sales,
            idem=True,
            json_body={
                "po_number": f"SEPL/PO/{today_ist().year}/{secrets.randbelow(900) + 100}",
                "po_date": str(today_ist()),
                "selected_options": chosen,
            },
        )
        await self.gate(pid, "boq", "boq_version", sales, head)

        # the plan: generated, a downtime window, scheduled, locked
        await self.call("POST", f"/projects/{pid}/plan/generate", pm, json_body={})
        start = (
            (utcnow() + timedelta(days=1))
            .astimezone(IST)
            .replace(hour=0, minute=0, second=0, microsecond=0)
        )
        await self.call(
            "POST",
            f"/projects/{pid}/plan/downtime",
            pm,
            json_body={
                "start_at": start.isoformat(),
                "end_at": (start + timedelta(days=30)).isoformat(),
                "note": "Evenings and Sundays",
            },
        )
        await self.call(
            "POST",
            f"/projects/{pid}/plan/schedule",
            pm,
            json_body={"start_date": str(today_ist() + timedelta(days=1)), "auto_assign": True},
        )
        plan = (await self.call("GET", f"/projects/{pid}/plan", pm))["plan"]
        await self.call("POST", f"/projects/{pid}/plan/{plan['id']}/baseline", lead, idem=True)
        await self.gate(pid, "implementation_plan", "implementation_plan", lead, pm)
        await self.call("POST", f"/projects/{pid}/field/start", pm, idem=True)
        self.say("  field work started")
        return str(pid)

    # ------------------------------------------------------------------ field work

    def _assignee(self, run: dict[str, Any]) -> Person:
        return next(p for p in self.people.values() if p.id == run["assignee_id"])

    async def evidence(self, who: Person, run: dict[str, Any], i: int) -> None:
        req = run["evidence_reqs"][i]
        data = {"requirement_index": str(i), "client_id": str(uuid.uuid4())}
        files = None
        if req["type"] in ("photo", "screenshot"):
            files = {"file": (f"evidence-{i}.png", _png(req.get("label", "evidence")), "image/png")}
        elif req["type"] == "config_export":
            files = {
                "file": (
                    "running-config.txt",
                    b"# exported configuration\nset admin mfa enable\nset ips enable\n",
                    "text/plain",
                )
            }
        elif req["type"] == "serial":
            data["text_value"] = f"SN-{secrets.token_hex(4).upper()}"
        else:
            data["text_value"] = "Done with Meera Shah, IT manager"
        await self.call("POST", f"/field/runs/{run['id']}/evidence", who, data=data, files=files)

    @staticmethod
    def values(run: dict[str, Any], fail: bool = False) -> dict[str, str]:
        good = {}
        for f in run["baseline"]:
            exp = (f.get("expected") or "").lower()
            good[f["key"]] = "99" if exp.startswith(("at least", "above")) else "enabled"
        if fail:
            crit = next(
                (
                    f
                    for f in run["baseline"]
                    if f["severity"] in ("critical", "major")
                    and f["expected"] in ("Enabled", "Configured")
                ),
                None,
            )
            if crit:
                good[crit["key"]] = "disabled"
        return good

    async def walk(
        self, run: dict[str, Any], until: str = "closed", fail_first: bool = False
    ) -> None:
        """Take one task as far as `until`: configured, verifier_review or closed."""
        rid = run["id"]
        eng, lead = self._assignee(run), self.people["anil.deshmukh"]

        async def post(path: str, who: Person, body: dict[str, Any] | None = None) -> Any:
            return await self.call("POST", f"/field/runs/{rid}/{path}", who, json_body=body or {})

        await post("accept", eng)
        await self._clear_limits()
        await post("codes/check_in", eng)
        await self.evidence(eng, run, 0)
        await post(
            "check-in",
            eng,
            {"code": await self._code(rid, "otp_check_in"), "lat": 19.1972, "lng": 72.9722},
        )
        for i in (1, 2):
            await self.evidence(eng, run, i)
        await post("prechecks-done", eng)
        for i in range(len(run["steps"])):
            await post(f"steps/{i}", eng)
        if run["baseline"]:
            await post("values", eng, {"values": self.values(run, fail=fail_first)})
        await post("configured", eng)
        for i in range(3, len(run["evidence_reqs"])):
            await self.evidence(eng, run, i)
        r = await post("submit-evidence", eng)
        if until == "configured":
            return
        if r["run"]["state"] == "configured" and run["baseline"]:  # sent back: fix, resubmit
            await post("values", eng, {"values": self.values(run)})
            await post("submit-evidence", eng)
        await self._clear_limits()
        await post("codes/handover", eng)
        await post("hand-over", eng, {"code": await self._code(rid, "otp_handover")})
        if until == "verifier_review":
            return
        await post("decision", lead, {"decision": "approve"})

    async def free_name(self, *names: str) -> str:
        found = await self.call("GET", "/projects", self.people["arvind.rao"], params={"size": 200})
        items = found["items"] if isinstance(found, dict) else found
        used = {x["name"] for x in items}
        return next((n for n in names if n not in used), f"{names[0]} {secrets.randbelow(90) + 10}")

    async def runs(self, pid: str) -> list[dict[str, Any]]:
        runs = await self.call("GET", f"/projects/{pid}/field/runs", self.people["farah.khan"])
        out = []
        for r in sorted(runs, key=lambda r: (r.get("planned_start") or "", r["task_ref"])):
            out.append((await self.call("GET", f"/field/runs/{r['id']}", self._assignee(r)))["run"])
        return out

    # ------------------------------------------------------------------ the two stories

    async def finished(self) -> str:
        pid = await self.project(
            await self.free_name(
                "Head office IT hardening",
                "Corporate office security upgrade",
                "Head office IT hardening, phase 2",
            ),
            {},
        )
        runs = await self.runs(pid)
        failed_once = False
        for run in runs:
            fail = not failed_once and any(
                f["severity"] in ("critical", "major")
                and f["expected"] in ("Enabled", "Configured")
                for f in run["baseline"]
            )
            failed_once = failed_once or fail
            await self.walk(run, fail_first=fail)
        self.say(f"  {len(runs)} tasks closed and verified")
        ppl = self.people
        pm, lead, director, auditor, arch = (
            ppl["farah.khan"],
            ppl["aditya"],
            ppl["rajesh.iyer"],
            ppl["shruti"],
            ppl["nikhil.joshi"],
        )
        await self.settle()
        await self.call("POST", f"/reporting/projects/{pid}/field-summary", pm, idem=True)
        await self.gate(pid, "field_work", "field_work_summary", pm, lead)

        # the after-work rescan, as PrismSuite's JSON export with the improved scores
        from app.modules.prismsuite.parsers import docx_v1

        docx = next(self.samples.glob("*PrismSuite Audit Report.docx"))
        snap = (
            docx_v1.PrismSuiteParserV1().parse(docx.read_bytes()).snapshot.model_dump(mode="json")
        )
        for k, v in {"performance": "71.8", "security": "79.4", "system_health": "81.0"}.items():
            if snap["scores"].get(k):
                snap["scores"][k]["value"] = v
        snap["header"]["report_reference"] = f"PS-{today_ist():%d%m%Y}-SHA-R"
        f = await self.call(
            "POST",
            "/files",
            auditor,
            files={"file": ("rescan.json", json.dumps(snap).encode(), "application/json")},
            data={"purpose": "audit_report", "project_id": pid},
        )
        imp = await self.call(
            "POST",
            "/prismsuite/imports",
            auditor,
            idem=True,
            json_body={"project_id": pid, "file_id": f["id"], "kind": "rescan"},
        )
        await self.call(
            "POST",
            f"/prismsuite/imports/{imp['id']}/approve",
            arch,
            idem=True,
            json_body={"version": imp["version"]},
        )
        self.say("  rescan approved")

        await self.call(
            "POST",
            "/reporting/settings/stamp",
            director,
            files={"file": ("iitpl-demo-stamp.png", demo_stamp(), "image/png")},
        )
        await self.call("POST", f"/reporting/projects/{pid}/reports", pm, idem=True)
        await self.gate(pid, "completion", "completion_report", pm, director)
        cert = await self.call(
            "POST", f"/reporting/projects/{pid}/certificates", director, idem=True
        )
        self.say(f"  certificate {cert['number']} signed")
        self.certificate = cert["number"]
        return pid

    async def in_progress(self) -> str:
        pid = await self.project(
            await self.free_name(
                "Plant network refresh",
                "Warehouse network refresh",
                "Plant network refresh, phase 2",
            ),
            None,
        )
        runs = await self.runs(pid)
        pm = self.people["farah.khan"]
        plan = ["closed", "verifier_review", "failed", "blocked", "accepted"]
        for run, what in zip(runs, plan, strict=False):
            if what in ("closed", "verifier_review"):
                await self.walk(run, until=what)
            elif what == "failed":
                await self.walk(run, until="configured", fail_first=True)
            elif what == "blocked":
                eng = self._assignee(run)
                await self.call("POST", f"/field/runs/{run['id']}/accept", eng, json_body={})
                await self.call(
                    "POST",
                    f"/field/runs/{run['id']}/block",
                    eng,
                    json_body={
                        "reason": "Server room locked; the customer's admin is away till Monday."
                    },
                )
            else:
                await self.call(
                    "POST", f"/field/runs/{run['id']}/accept", self._assignee(run), json_body={}
                )
        await self.settle()
        last = runs[-1]
        if last["state"] == "assigned" and len(runs) > len(plan):
            await self.call(
                "POST",
                f"/reporting/projects/{pid}/waivers",
                pm,
                json_body={
                    "scope": "task",
                    "target_id": last["id"],
                    "kind": "deferred_by_customer",
                    "reason": "The customer moves this to the next financial year.",
                },
            )
        self.say(
            "  field work in progress: closed, waiting review, failed check, blocked, waiver asked"
        )
        return pid

    def accounts(self) -> dict[str, Any]:
        return {
            "note": "Demo accounts, development only. One password; TOTP secrets for MFA roles.",
            "password": self.password,
            "base_url": get_settings().public_base_url,
            "certificate": self.certificate,
            "users": [
                {"email": p.email, "name": p.name, "roles": p.roles, "totp_secret": p.totp}
                for p in self.people.values()
            ],
        }


def _read(out: Path) -> dict[str, Any] | None:
    return json.loads(out.read_text(encoding="utf-8")) if out.exists() else None


def _write(out: Path, data: dict[str, Any]) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2), encoding="utf-8")


async def run(samples: Path, out: Path) -> dict[str, Any]:
    from app.main import app as fastapi_app
    from app.modules import registry

    if get_settings().is_prod:
        raise DemoError("Demo data is for development only.")
    registry.load_handlers()
    transport = httpx.ASGITransport(app=fastapi_app, client=("127.0.0.1", 50000))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://demo", timeout=120
    ) as client:
        d = Demo(client, samples)
        d.previous = _read(out)
        await d.staff()
        await d.reference()
        d.cust = await d.customer()
        try:
            await d.finished()
            await d.in_progress()
        finally:
            _write(out, d.accounts())
            print(f"Accounts written to {out}")
        return d.accounts()
