"""Write a production .env with strong, random secrets. Standard library only, so it runs with
any Python 3.10+ on the server:

    python3 scripts/new_env.py --domain p1.itcraft.net.in --smtp-host smtp.example.net \
        --smtp-user no-reply@itcraft.net.in --smtp-from no-reply@itcraft.net.in

It asks for the SMTP password (not echoed) unless --smtp-password is given. It refuses to
overwrite an existing .env: the encryption key in it protects data already stored, and a new key
would make that data unreadable. See DEPLOYMENT.md.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import os
import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def token(n: int = 32) -> str:
    return secrets.token_urlsafe(n)


def fernet_key() -> str:
    """The same format as cryptography's Fernet.generate_key(): 32 random bytes, url-safe base64."""
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


def main() -> int:
    ap = argparse.ArgumentParser(description="Write a production .env with random secrets.")
    ap.add_argument("--domain", required=True, help="the address people use, e.g. p1.itcraft.net.in")
    ap.add_argument("--smtp-host", required=True)
    ap.add_argument("--smtp-port", type=int, default=587)
    ap.add_argument("--smtp-user", default="")
    ap.add_argument("--smtp-password", default=None)
    ap.add_argument("--smtp-from", required=True, help="the sender address on every email")
    ap.add_argument(
        "--proxy",
        choices=["prod", "conf.d"],
        default="prod",
        help="prod: HTTPS with a certificate on this server; conf.d: a load balancer does HTTPS",
    )
    ap.add_argument("--version", default="1.0.0", help="image tag to build and run")
    ap.add_argument("--out", default=str(ROOT / ".env"))
    a = ap.parse_args()

    domain = a.domain.strip().lower().removeprefix("https://").removeprefix("http://").strip("/")
    if not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", domain) or "localhost" in domain:
        print(f"{domain!r} does not look like a public domain name.", file=sys.stderr)
        return 2
    out = Path(a.out)
    if out.exists():
        print(
            f"{out} already exists. Not overwriting: its encryption key protects stored data.",
            file=sys.stderr,
        )
        return 1
    smtp_password = a.smtp_password
    if smtp_password is None:
        smtp_password = getpass.getpass("SMTP password (leave empty if none): ")

    url = f"https://{domain}"
    lines = [
        "# Production settings, written by scripts/new_env.py. Never commit this file.",
        "# Keep a copy in the company password manager: losing P1_FERNET_KEYS loses encrypted data.",
        "P1_ENV=prod",
        f"P1_VERSION={a.version}",
        f"P1_PUBLIC_BASE_URL={url}",
        f"P1_CORS_ALLOW_ORIGINS={url}",
        f"P1_PROXY_CONF={a.proxy}",
        "P1_COOKIE_SECURE=true",
        "# Empty: files are served through the app; MinIO stays on the internal network.",
        "P1_S3_PUBLIC_ENDPOINT_URL=",
        "",
        f"P1_POSTGRES_PASSWORD={token()}",
        f"P1_OWNER_PASSWORD={token()}",
        f"P1_APP_PASSWORD={token()}",
        f"P1_REDIS_PASSWORD={token()}",
        f"P1_S3_ACCESS_KEY=p1-{secrets.token_hex(6)}",
        f"P1_S3_SECRET_KEY={token()}",
        f"P1_GRAFANA_PASSWORD={token(18)}",
        f"P1_FERNET_KEYS={fernet_key()}",
        f"P1_JWT_SIGNING_KEYS={token(48)}",
        "",
        f"P1_SMTP_HOST={a.smtp_host}",
        f"P1_SMTP_PORT={a.smtp_port}",
        f"P1_SMTP_USER={a.smtp_user}",
        f"P1_SMTP_PASSWORD={smtp_password}",
        f"P1_SMTP_FROM={a.smtp_from}",
        "P1_SMTP_STARTTLS=true",
        "",
        "P1_SENTRY_DSN=",
        "P1_OTEL_EXPORTER_OTLP_ENDPOINT=",
        "P1_CORPUS_ORIGINALS_RETENTION_DAYS=0",
        "",
    ]
    out.write_text("\n".join(lines), encoding="utf-8")
    try:
        out.chmod(0o600)
    except OSError:
        pass  # Windows: file permissions work differently
    print(f"Wrote {out} for {url}. Next: DEPLOYMENT.md, step 4.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
