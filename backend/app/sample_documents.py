"""Render every document template from the reference samples, for review and for visual checks.

    python -m app.cli render-samples --corpus ../samples/corpus --out ./out

- quotation and summary BOQ: rebuilt from the Shobhaglobs priced quotation's corpus record, so the
  output can be laid beside the original PDF in `samples/`;
- implementation plan: the tasks those quotation lines become, with the seeded device baselines;
- field task record: the firewall task walked through once, including a failed configuration
  check, the rework and the passed check;
- completion report and certificate: that project finished, with one exclusion by agreement
  (illustrative before and after scores, no IITPL stamp until one is uploaded).

Nothing here touches the database. Rendering needs WeasyPrint, so run it in the API container.
"""

from __future__ import annotations

import io
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.core.documents import render_pdf
from app.core.timeutil import IST, format_long_date
from app.modules.boq import draft as d
from app.modules.boq import render as boq_render
from app.modules.boq.seed import DEFAULT_COMPANY
from app.modules.fieldops import engine
from app.modules.fieldops import render as field_render
from app.modules.planning import render as plan_render
from app.modules.planning.seed import CONFIGS

PRICED = (
    "ITCraft 2627-030-Shobhaglobs Engineers Hub Private Limited- "
    "Sanitization, EPS, Switch & Firewall.json"
)


def quotation_draft(record: dict[str, Any]) -> d.Draft:
    """The sample quotation as an editable BOQ draft."""
    doc = record["document"]
    groups: dict[str, d.Group] = {}
    sections: dict[tuple[str, str], d.Section] = {}
    lines: list[d.Line] = []
    for ln in record["lines"]:
        g_title = ln.get("priority_group") or "High Priority"
        g = groups.setdefault(g_title, d.Group(title=g_title))
        s_title = ln.get("section") or "Items"
        s = sections.setdefault((g.id, s_title), d.Section(group_id=g.id, title=s_title))
        option = ln.get("option")
        lines.append(
            d.Line(
                section_id=s.id,
                option_group=f"opt-{ln['line_ref'].rstrip('ABCDEFGH')}" if option else None,
                title=ln["component"],
                description=ln.get("description") or "",
                inclusions=list(ln.get("inclusions") or []),
                qty=int(ln["qty"]),
                unit_price=Decimal(ln["unit_price"]) if ln.get("unit_price") else None,
                price_source="manual",
            )
        )
    validity = int(doc.get("validity_days") or 5)
    company = DEFAULT_COMPANY
    return d.Draft(
        settings=d.Settings(
            quote_date=date.fromisoformat(doc["quote_date"]) if doc.get("quote_date") else None,
            validity_days=validity,
            customer=d.Party(name=doc.get("customer") or "", address_lines=[]),
            intro=str(company["intro"]).replace(
                "{scope}", "sanitization, endpoint security, managed switch and firewall"
            ),
            signatory_name=str(company["signatory_name"]),
            signatory_designation=str(company["signatory_designation"]),
        ),
        groups=list(groups.values()),
        sections=list(sections.values()),
        lines=lines,
        terms=[  # filled the way the BOQ service fills them
            str(t).replace("{gst}", "18").replace("{validity}", str(validity))
            for t in company["terms"]
        ],
    )


def _at(day: date, hh: int, mm: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hh, mm, tzinfo=IST)


def plan_context(start: date) -> dict[str, Any]:
    """The quotation's lines as a scheduled plan (the shape `planning.render` prints)."""
    d1, d2 = start, start + timedelta(days=1)
    rows = [
        (
            d1,
            "T-01",
            "Sanitise 31 endpoints: remove duplicate antivirus agents",
            "Yash Raikar",
            "31 endpoints",
            "6 h 00 min",
            False,
            "",
            10,
            16,
        ),
        (
            d1,
            "T-02",
            "Install Acronis XDR on 31 endpoints",
            "Sakshi Rajbhar",
            "31 endpoints",
            "4 h 30 min",
            False,
            "T-01",
            16,
            18,
        ),
        (
            d2,
            "T-03",
            "Install the Cisco C1300 managed switch",
            "Yash Raikar",
            "SW-01 (replaces D-Link DGS-1024C)",
            "2 h 00 min",
            True,
            "",
            10,
            12,
        ),
        (
            d2,
            "T-04",
            "Configure the Sophos XGS-108 firewall",
            "Sakshi Rajbhar",
            "FW-01",
            "3 h 00 min",
            True,
            "T-03",
            12,
            15,
        ),
        (
            d2,
            "T-05",
            "One year support hand over and documentation",
            "Sakshi Rajbhar",
            "FW-01",
            "1 h 00 min",
            False,
            "T-04",
            15,
            16,
        ),
    ]
    days: dict[str, list[dict[str, Any]]] = {}
    for day, ref, title, eng, asset, mins, down, after, h1, h2 in rows:
        days.setdefault(format_long_date(day), []).append(
            {
                "ref": ref,
                "title": title,
                "engineer": eng,
                "asset": asset,
                "minutes": mins,
                "downtime": down,
                "after": after,
                "start": f"{h1:02d}:00",
                "end": f"{h2:02d}:00",
            }
        )
    base = {c["device_type"]: c for c in CONFIGS}
    return {
        "company": dict(DEFAULT_COMPANY),
        "title": "Implementation plan 1",
        "project": "IT infrastructure hardening",
        "project_code": "P1-2627-0001",
        "customer": "Shobhaglobs Engineers Hub Private Limited",
        "plan_number": 1,
        "status": "Locked",
        "boq_ref": "ITCraft/NN/2627/030",
        "printed": format_long_date(start - timedelta(days=2)),
        "task_count": len(rows),
        "total": "16 h 30 min",
        "days": list(days.items()),
        "unscheduled": [],
        "windows": [
            {
                "from": _at(d2, 10).strftime("%d %b %Y %H:%M"),
                "to": _at(d2, 16).strftime("%d %b %Y %H:%M"),
                "note": "Saturday: office closed, network may go down",
            }
        ],
        "baselines": [
            {
                "label": "SW-01 Cisco C1300-24T-4G",
                "type": "switch",
                "task": "T-03",
                "fields": base["switch"]["fields"],
            },
            {
                "label": "FW-01 Sophos XGS-108",
                "type": "firewall",
                "task": "T-04",
                "fields": base["firewall"]["fields"],
            },
        ],
        "warnings": [],
    }


def _sample_photo(label: str) -> str:
    """A plain placeholder image standing in for a site photo (there are no real ones yet)."""
    import base64

    from PIL import Image, ImageDraw

    img = Image.new("RGB", (480, 320), (226, 233, 241))
    draw = ImageDraw.Draw(img)
    draw.rectangle([20, 20, 459, 299], outline=(44, 98, 159), width=3)
    draw.text((40, 140), f"Sample photo: {label}", fill=(20, 34, 48))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode()


def checklist_context(day: date) -> dict[str, Any]:
    """The firewall task walked through once, with a failed check and its rework."""
    fw = next(c for c in CONFIGS if c["device_type"] == "firewall")["fields"]
    readings = {
        "firmware": "SFOS 20.0.2 MR-2",
        "admin_mfa": "enabled",
        "ips": "enabled",
        "default_admin": "renamed to fw-admin",
        "bandwidth": "applied for 4 departments",
        "ha": "single unit supplied",
        "logging": "enabled, kept 90 days",
    }
    second = {f["key"]: {"value": readings.get(f["key"], "enabled")} for f in fw}
    first = {**second, "admin_mfa": {"value": "disabled"}}
    checks = [
        engine.AnswerDriver().check_answers(fw, first),
        engine.AnswerDriver().check_answers(fw, second),
    ]

    def t(h: int, m: int) -> str:
        return _at(day, h, m).strftime("%d %b %Y %H:%M")

    timeline = [
        (t(9, 12), "accept", "accepted by the engineer", "Sakshi Rajbhar", "", ""),
        (t(11, 58), "check in", "checked in on site", "Sakshi Rajbhar", "19.07283, 72.87766", ""),
        (
            t(12, 10),
            "prechecks done",
            "prechecks done (backup and access confirmed)",
            "Sakshi Rajbhar",
            "",
            "",
        ),
        (t(13, 40), "configured", "configured", "Sakshi Rajbhar", "", ""),
        (
            t(13, 52),
            "engine check",
            "configuration check failed",
            "Project One",
            "",
            "",
        ),
        (
            t(13, 52),
            "engine mismatch",
            "configured",
            "Project One",
            "",
            "Administrator MFA: Expected Enabled, found disabled.",
        ),
        (
            t(14, 20),
            "engine check",
            "configuration check passed",
            "Project One",
            "",
            "",
        ),
        (
            t(14, 31),
            "hand over",
            "handed over, waiting for verification",
            "Sakshi Rajbhar",
            "19.07281, 72.87760",
            "",
        ),
        (t(17, 5), "verify", "closed and verified", "Amit Deshmukh", "", ""),
    ]
    return {
        "company": dict(DEFAULT_COMPANY),
        "title": "Task record T-04",
        "file_name": "P1-2627-0001-T-04-record.pdf",
        "customer": "Shobhaglobs Engineers Hub Private Limited",
        "project": "IT infrastructure hardening",
        "run": {
            "ref": "T-04",
            "title": "Configure the Sophos XGS-108 firewall",
            "asset": "FW-01",
            "state": "closed and verified",
            "engineer": "Sakshi Rajbhar",
            "planned": f"{t(12, 0)} to {t(15, 0)}",
            "checked_in": t(11, 58),
            "handed_over": t(14, 31),
            "closed": t(17, 5),
            "verified_by": "Amit Deshmukh",
            "rework": 1,
        },
        "steps": [
            {
                "text": s,
                "done": True,
                "when": (_at(day, 12, 20) + timedelta(minutes=15 * i)).strftime("%d %b %Y %H:%M"),
            }
            for i, s in enumerate(
                [
                    "Back up the current configuration",
                    "Update the firmware to the latest stable release",
                    "Turn on MFA for every administrator",
                    "Turn on intrusion prevention and web filtering",
                    "Set up the site to site VPN and test it",
                ]
            )
        ],
        "baseline": [
            {
                "label": f["label"],
                "expected": f["expected"],
                "severity": f["severity"],
                "actual": second[f["key"]]["value"],
            }
            for f in fw
        ],
        "checks": [
            {
                "attempt": i + 1,
                "when": t(13, 52) if i == 0 else t(14, 20),
                "passed": c.passed,
                "fields": c.as_dict()["fields"],
            }
            for i, c in enumerate(checks)
        ],
        "timeline": [
            {"when": w, "action": a, "to": to, "who": who, "place": place, "detail": detail}
            for w, a, to, who, place, detail in timeline
        ],
        "evidence": [
            {
                "label": "Photo of the site on arrival",
                "stage": "check in",
                "type": "photo",
                "text": "",
                "note": "",
                "when": t(11, 55),
                "by": "Sakshi Rajbhar",
                "image": _sample_photo("site on arrival"),
            },
            {
                "label": "Backup of the current configuration",
                "stage": "prechecks",
                "type": "screenshot",
                "text": "",
                "note": "",
                "when": t(12, 5),
                "by": "Sakshi Rajbhar",
                "image": _sample_photo("backup screen"),
            },
            {
                "label": "Access confirmed: admin login works and a customer contact is present",
                "stage": "prechecks",
                "type": "note",
                "text": "Logged in as admin with the customer's IT contact present",
                "note": "",
                "when": t(12, 8),
                "by": "Sakshi Rajbhar",
                "image": None,
            },
            {
                "label": "Serial number",
                "stage": "work",
                "type": "serial",
                "text": "X1A23B4567",
                "note": "",
                "when": t(13, 45),
                "by": "Sakshi Rajbhar",
                "image": None,
            },
        ],
        "printed": format_long_date(day),
        "waiting_on": [],
    }


def report_content(start: date, quote_ref: str | None) -> dict[str, Any]:
    """The finished project as `reporting.content.build_content` returns it.

    Scores are illustrative: "before" reuses the sample PrismSuite report's four headline
    scores, "after" is a made-up rescan."""
    from app.modules.reporting.content import lens_table

    def snap(perf: str, ha: str, sec: str, health: str) -> Any:
        class V:
            def __init__(self, v: str) -> None:
                self.value = v

        class S:
            performance, high_availability = V(perf), V(ha)
            security, system_health = V(sec), V(health)

        class Snap:
            scores = S()

        return Snap()

    tasks = [
        ("T-01", "Sanitise 31 endpoints: remove duplicate antivirus agents", "31 endpoints", 0),
        ("T-02", "Install Acronis XDR on 31 endpoints", "31 endpoints", 0),
        ("T-03", "Install the Cisco C1300 managed switch", "SW-01", 1),
        ("T-04", "Configure the Sophos XGS-108 firewall", "FW-01", 1),
        ("T-05", "One year support hand over and documentation", "FW-01", 2),
    ]
    return {
        "project": {"id": "", "code": "P1-2627-0001", "name": "IT infrastructure hardening"},
        "customer": {
            "name": "Shobhaglobs",
            "legal_name": "Shobhaglobs Engineers Hub Private Limited",
            "address_lines": [],
        },
        "quote_ref": quote_ref,
        "po_number": "SEH/PO/2026/114",
        "work_started": format_long_date(start),
        "work_finished": format_long_date(start + timedelta(days=2)),
        "delivered": [
            {
                "ref": ref,
                "title": title,
                "device": device,
                "closed": format_long_date(start + timedelta(days=day)),
                "verified_by": "Anil Deshmukh",
            }
            for ref, title, device, day in tasks
        ],
        "exclusions": [
            {
                "what": "T-04 Firewall high availability (minor)",
                "kind": "not applicable",
                "reason": "One firewall was bought; a second unit is in next year's budget.",
                "approved_by": "Sattish Agadii",
                "acknowledged_by": "Meera Shah",
            }
        ],
        "waived_task_ids": [],
        "lenses": lens_table(
            snap("60.3", "50", "58.7", "74.2"), snap("71.8", "50", "79.4", "81.0")
        ),
        "baseline_ref": "PS-10092026-SHA",
        "rescan_ref": "PS-RESCAN-SAMPLE",
        "configuration": [
            {
                "ref": "T-03",
                "device": "SW-01",
                "attempts": 1,
                "passed": True,
                "pass": 6,
                "fail": 0,
                "not_checked": 1,
            },
            {
                "ref": "T-04",
                "device": "FW-01",
                "attempts": 2,
                "passed": True,
                "pass": 6,
                "fail": 0,
                "not_checked": 1,
            },
        ],
        "deviations_closed": [
            {
                "task": "T-04",
                "label": "Admin MFA",
                "severity": "critical",
                "status": "resolved",
                "resolution": "Passed on configuration check 2",
            },
            {
                "task": "T-04",
                "label": "Firewall high availability",
                "severity": "minor",
                "status": "waived",
                "resolution": "Not applicable, acknowledged by the customer",
            },
        ],
        "deviations_open": [],
        "open_recommendations": [
            {
                "code": "G-07",
                "title": "No offsite copy of the file server backup",
                "lens": "resilience",
                "priority": "High",
                "recommendation": "Add a cloud backup target with 30 day retention.",
            }
        ],
        "verifiers": ["Anil Deshmukh"],
        "printed": format_long_date(start + timedelta(days=3)),
        "report_number": 1,
    }


def certificate_context(content: dict[str, Any], issued: date) -> dict[str, Any]:
    """The certificate the Director would sign for that report. No stamp until IITPL sends one."""
    import hashlib

    from app.core.documents import qr_data_url
    from app.modules.reporting.service import DEFAULT_WORDING

    number = f"IITPL-{issued.year % 100:02d}{(issued.year + 1) % 100:02d}-0001"
    payload = {
        "number": number,
        "customer": content["customer"]["legal_name"],
        "project": content["project"]["name"],
        "project_code": content["project"]["code"],
        "quote_ref": content["quote_ref"],
        "po_number": content["po_number"],
        "scope": [f"{d['ref']} {d['title']} ({d['device']})" for d in content["delivered"]],
        "exclusions": [f"{x['what']}: {x['kind']}" for x in content["exclusions"]],
        "work_started": content["work_started"],
        "work_finished": content["work_finished"],
        "verifiers": content["verifiers"],
        "director": "Sattish Agadii",
        "issued_on": format_long_date(issued),
        "report_number": 1,
        "wording": DEFAULT_WORDING,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    url = f"https://p1.itcraft.net.in/verify/{number}"
    return {
        "company": dict(DEFAULT_COMPANY),
        "p": payload,
        "scope_shown": payload["scope"],
        "scope_more": 0,
        "fingerprint": digest[:16],
        "verify_url": url,
        "qr": qr_data_url(url),
        "stamp": None,
    }


def render_all(corpus_dir: Path, out: Path, today: date | None = None) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    record = json.loads((corpus_dir / PRICED).read_text(encoding="utf-8"))
    draft = quotation_draft(record)
    company = dict(DEFAULT_COMPANY)
    ref = record["document"].get("quote_ref")
    quote_day = draft.settings.quote_date or (today or date.today())
    made: list[Path] = []

    def save(name: str, html: str) -> None:
        doc = render_pdf(html)
        path = out / name
        path.write_bytes(doc.pdf)
        (out / name.replace(".pdf", ".html")).write_text(html, encoding="utf-8")
        made.append(path)
        print(f"{name}: {doc.pages} page(s), {len(doc.pdf)} bytes, sha256 {doc.sha256[:12]}")

    save(
        "01-quotation.pdf",
        boq_render.render_html(draft, company, quote_ref=ref, kind="quotation", on=quote_day),
    )
    save(
        "02-summary-boq.pdf",
        boq_render.render_html(draft, company, quote_ref=ref, kind="summary", on=quote_day),
    )
    start = quote_day + timedelta(days=14)
    save("03-implementation-plan.pdf", plan_render.render_html(plan_context(start)))
    save(
        "04-field-task-record.pdf",
        field_render.render_html(checklist_context(start + timedelta(days=1))),
    )
    from app.modules.reporting import render as report_render

    content = report_content(start, ref)
    save(
        "05-completion-report.pdf",
        report_render.render_report_html({"company": company, "c": content}),
    )
    save(
        "06-certificate.pdf",
        report_render.render_certificate_html(
            certificate_context(content, start + timedelta(days=4))
        ),
    )
    return made
