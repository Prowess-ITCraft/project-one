"""Licence report and check for every dependency (ADR 0011, RULES 1.7).

Reads the backend's installed runtime packages (the ones requirements.txt pins, plus what they
pull in) and the web app's production packages (package.json dependencies and everything under
them in node_modules), then:

  python scripts/licenses.py            write docs/LICENSES.md
  python scripts/licenses.py --check    exit 1 if any licence is unknown or not on the allowed list

Run it with the backend's Python (backend/.venv/Scripts/python.exe on Windows) so the installed
packages are the ones the app uses. Services and Docker images are listed by hand in SERVICES.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "LICENSES.md"

# Free to use, change and run inside the company, including for commercial work.
ALLOWED = (
    "MIT",
    "BSD",
    "Apache",
    "ISC",
    "PSF",
    "Python Software Foundation",
    "Python-2.0",
    "MPL-2.0",
    "Mozilla Public License 2.0",
    "Unlicense",
    "CC0",
    "0BSD",
    "Zlib",
    "HPND",
    "Historical Permission Notice",
    "LGPL",
    "BlueOak",
    "CC-BY-4.0",
    "OFL",
)
# Packages whose metadata says nothing useful, checked by hand: name -> licence.
KNOWN = {
    "pywebpush": "MPL-2.0",
    "py-vapid": "MPL-2.0",
    "http-ece": "MIT",
    "psycopg-binary": "LGPL-3.0 (used as a library, unchanged)",
    "psycopg": "LGPL-3.0 (used as a library, unchanged)",
    "pyphen": "GPL-2.0+ or LGPL-2.1+ or MPL-1.1 (used under LGPL)",
    "polars-runtime-32": "MIT",
    "typing-extensions": "PSF-2.0",
    "uvloop": "MIT or Apache-2.0",
    "narwhals": "MIT",
    "brotlicffi": "MIT (only installed on PyPy)",
}

# Services the stack runs (docker-compose*.yml). Image licences checked by hand on 8 Oct 2026.
SERVICES = [
    ("PostgreSQL 16", "PostgreSQL License (permissive)", "database"),
    ("Valkey 8", "BSD-3-Clause", "cache, Celery broker, rate limits"),
    ("MinIO (Chainguard build)", "AGPL-3.0, used unchanged as a separate service", "file storage behind the S3 interface; Garage or SeaweedFS can replace it (ADR 0006)"),
    ("ClamAV", "GPL-2.0, separate service", "virus scan of every upload"),
    ("Nginx", "BSD-2-Clause", "reverse proxy and TLS"),
    ("Mailpit", "MIT", "development mail catcher only"),
    ("Prometheus and Alertmanager", "Apache-2.0", "metrics and alert rules"),
    ("Grafana", "AGPL-3.0, used unchanged as a separate service", "dashboards, admin only"),
    ("GlitchTip", "MIT", "error tracking, self-hosted, Sentry protocol (profile ops)"),
    ("Uptime Kuma", "MIT", "uptime checks and alerts (profile ops)"),
    ("MLflow", "Apache-2.0", "optional experiment tracking (profile mlflow)"),
    ("Flower", "BSD-3-Clause", "Celery monitor, admin only"),
    ("certbot", "Apache-2.0 and MIT", "Let's Encrypt certificates"),
    ("ntfy", "Apache-2.0 or GPL-2.0", "alerts to phones (Alertmanager), self-hosted or ntfy.sh free tier"),
]


def allowed(lic: str) -> bool:
    return any(a.lower() in lic.lower() for a in ALLOWED)


def _python_licence(dist: metadata.Distribution) -> str:
    name = (dist.metadata.get("Name") or "").lower()
    if name in KNOWN:
        return KNOWN[name]
    expr = dist.metadata.get("License-Expression")
    if expr:
        return expr.strip()
    classifiers = [
        c.split("::")[-1].strip()
        for c in dist.metadata.get_all("Classifier") or []
        if c.startswith("License ::") and "OSI Approved" not in c.split("::")[-1]
    ]
    if classifiers:
        return " or ".join(sorted(set(classifiers)))
    raw = (dist.metadata.get("License") or "").strip()
    if raw and len(raw) < 80 and "\n" not in raw:
        return raw
    if raw:
        first = raw.splitlines()[0][:80]
        return first
    return "UNKNOWN"


def python_packages() -> list[tuple[str, str, str]]:
    req = (ROOT / "backend" / "requirements.txt").read_text(encoding="utf-8")
    wanted = {
        re.split(r"[=<>;\[ ]", line.strip())[0].lower().replace("_", "-").replace(".", "-")
        for line in req.splitlines()
        if line.strip() and not line.startswith(("#", " "))
    }
    out = []
    for dist in metadata.distributions():
        name = (dist.metadata.get("Name") or "").lower().replace("_", "-").replace(".", "-")
        if name in wanted:
            out.append((name, dist.version, _python_licence(dist)))
    missing = wanted - {n for n, _v, _l in out}
    for name in sorted(missing):
        out.append((name, "not installed here", KNOWN.get(name, "UNKNOWN (not installed)")))
    return sorted(set(out))


def node_packages() -> list[tuple[str, str, str]]:
    web = ROOT / "frontend"
    pkg = json.loads((web / "package.json").read_text(encoding="utf-8"))
    nm = web / "node_modules"
    seen: dict[str, tuple[str, str]] = {}
    todo = list(pkg.get("dependencies", {}))
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        meta = nm / name / "package.json"
        if not meta.exists():
            seen[name] = ("not installed", "UNKNOWN (not installed)")
            continue
        data = json.loads(meta.read_text(encoding="utf-8"))
        lic = data.get("license") or data.get("licenses") or "UNKNOWN"
        if isinstance(lic, dict):
            lic = lic.get("type", "UNKNOWN")
        if isinstance(lic, list):
            lic = " or ".join(x.get("type", "?") if isinstance(x, dict) else str(x) for x in lic)
        seen[name] = (str(data.get("version", "?")), str(lic))
        todo.extend(data.get("dependencies", {}))
        # optional native builds (one per platform) are counted when installed
        todo.extend(k for k in data.get("optionalDependencies", {}) if (nm / k).exists())
    return sorted((n, v, lic) for n, (v, lic) in seen.items())


def table(rows: list[tuple[str, str, str]]) -> list[str]:
    lines = ["| Package | Version | Licence |", "| --- | --- | --- |"]
    lines += [f"| {n} | {v} | {lic} |" for n, v, lic in rows]
    return lines


def main() -> int:
    py, js = python_packages(), node_packages()
    bad = [(n, lic) for n, _v, lic in py + js if not allowed(lic)]
    if "--check" in sys.argv:
        for n, lic in bad:
            print(f"NOT ALLOWED OR UNKNOWN: {n}: {lic}")
        print(f"{len(py)} backend and {len(js)} web packages checked, {len(bad)} to look at")
        return 1 if bad else 0
    doc = [
        "# Licences",
        "",
        "Every dependency and service Project One uses, with its licence. Free and open-source",
        "only (ADR 0011): each must allow commercial use inside the company.",
        "Generated by `python scripts/licenses.py`; `--check` fails on anything unknown or not",
        "allowed, and runs before every release (RULES 6).",
        "",
        f"Last generated: {date.today().isoformat()}. Maintained by Aditya Kumar.",
        "",
        "## Allowed licences",
        "",
        "MIT, BSD, Apache-2.0, ISC, PSF, MPL-2.0, LGPL (as unchanged libraries), Unlicense, CC0,",
        "Zlib, HPND, OFL (fonts). Copyleft services (AGPL, GPL) are allowed only as separate,",
        "unchanged programs the app talks to over the network.",
        "",
        "Things that may cost money: the server, the domain, and SMS or WhatsApp per message (their",
        "adapters exist and are off by default). Nothing else.",
        "",
        "## Services",
        "",
        "| Service | Licence | Used for |",
        "| --- | --- | --- |",
        *[f"| {n} | {lic} | {use} |" for n, lic, use in SERVICES],
        "",
        f"## Backend (Python, {len(py)} packages)",
        "",
        *table(py),
        "",
        f"## Web app (JavaScript, {len(js)} packages in production)",
        "",
        *table(js),
        "",
        "Development tools (pytest, ruff, mypy, Playwright, TypeScript, openapi-typescript,",
        "Lighthouse) are not shipped. They are MIT, Apache-2.0 or BSD.",
        "",
    ]
    if bad:
        doc += ["## To check by hand", ""] + [f"- {n}: {lic}" for n, lic in bad] + [""]
    OUT.write_text("\n".join(doc), encoding="utf-8")
    print(f"wrote {OUT} ({len(py)} backend, {len(js)} web, {len(bad)} to check)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
