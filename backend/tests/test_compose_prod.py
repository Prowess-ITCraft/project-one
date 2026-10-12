"""The production compose files restart and health-check every service and publish only 80 and 443."""

from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[2]
# These get their healthcheck from the image: our two Dockerfiles, and Uptime Kuma's own.
IMAGE_HEALTHCHECK = {
    "api": ROOT / "backend/Dockerfile",
    "web": ROOT / "frontend/Dockerfile",
    "uptime-kuma": None,
}
ONE_OFF_JOBS = {"migrate", "glitchtip-migrate"}

pytestmark = pytest.mark.skipif(
    not (ROOT / "docker-compose.prod.yml").exists(),
    reason="the compose files are not in this checkout",
)


def _services() -> dict[str, dict[str, Any]]:
    base = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))["services"]
    prod = yaml.safe_load((ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8"))[
        "services"
    ]
    merged = {}
    for name in base.keys() | prod.keys():
        a, b = base.get(name, {}), prod.get(name, {})
        merged[name] = {**a, **b, "ports": [*a.get("ports", []), *b.get("ports", [])]}
    return merged


def test_every_long_running_service_restarts_and_has_a_healthcheck() -> None:
    for name, svc in _services().items():
        if name in ONE_OFF_JOBS:
            assert svc["restart"] == "no", name
            continue
        assert svc.get("restart") == "unless-stopped", name
        if name in IMAGE_HEALTHCHECK:
            dockerfile = IMAGE_HEALTHCHECK[name]
            assert dockerfile is None or "HEALTHCHECK" in dockerfile.read_text(encoding="utf-8"), (
                name
            )
        else:
            assert svc.get("healthcheck", {}).get("test"), f"{name} has no healthcheck"


def test_only_the_proxy_publishes_and_only_80_and_443() -> None:
    public: dict[str, list[str]] = {}
    for name, svc in _services().items():
        for port in svc["ports"]:
            if not str(port).startswith("127.0.0.1:"):
                public.setdefault(name, []).append(str(port))
    assert public == {"proxy": ["80:80", "443:443"]}
