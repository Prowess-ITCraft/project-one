"""Field engineers never receive prices (ADR 0003). A field engineer with real
work in progress calls every GET route in the API that can be filled in with their own ids; no
answer may carry a price, a cost, an amount, a margin or a rupee sign. The test fails as soon as
any route ever does."""

from __future__ import annotations

import re
import uuid
from typing import Any

from app.core import outbox
from app.core.db import get_sessionmaker
from app.main import create_app
from app.modules.fieldops.tests.test_field_flow import _evidence, _post, field_ready

API = "/api/v1"
PRICE_KEY = re.compile(
    r"(^|_)(price|prices|selling|cost|costs|amount|amounts|margin|subtotal|total|totals|gst)"
    r"($|_)|unit_price|hint_price|price_|_price",
    re.I,
)
# Keys that look like money words but are not money: tax rates, durations and counts.
NOT_MONEY = {"total", "total_tasks", "totals_rows"}
NOT_MONEY_SUFFIX = ("_rate", "_minutes", "_hours", "_days", "_count")


def _money_keys(value: Any, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for k, v in value.items():
            key = str(k)
            money = (
                PRICE_KEY.search(key)
                and key not in NOT_MONEY
                and not key.endswith(NOT_MONEY_SUFFIX)
            )
            if money and v not in (None, [], {}):
                found.append(f"{path}.{key}")
            found.extend(_money_keys(v, f"{path}.{key}"))
    elif isinstance(value, list):
        for i, v in enumerate(value[:50]):
            found.extend(_money_keys(v, f"{path}[{i}]"))
    elif isinstance(value, str) and "₹" in value:
        found.append(f"{path} (rupee sign)")
    return found


async def test_no_answer_to_a_field_engineer_carries_a_price(client: Any) -> None:
    p, _both, runs = await field_ready(client)
    eng = p.eng[0]
    run = next(r for r in runs if r["assignee_id"] == str(eng.id) and not r["depends_on"])
    rid = run["id"]
    await _post(client, eng, f"{rid}/accept")
    ev = await _evidence(client, eng, run, 0)
    assert ev.status_code == 201, ev.text
    file_id = ev.json()["file_id"]
    for _ in range(10):
        if not await outbox.dispatch_batch(get_sessionmaker()):
            break
    boq = (await client.get(f"{API}/projects/{p.pid}/boq", headers=p.c.sm.headers)).json()
    item = (await client.get(f"{API}/catalogue/items", headers=eng.headers)).json()["items"][0]
    ids = {
        "project_id": p.pid,
        "run_id": rid,
        "customer_id": p.c.ws.customer["id"],
        "file_id": file_id,
        "item_id": item["id"],
        "boq_id": boq["id"],
        "number": "1",
        "user_id": str(eng.id),
        "stage": "field_work",
    }

    spec = create_app().openapi()
    checked, skipped = 0, 0
    leaks: dict[str, list[str]] = {}
    for path, ops in spec["paths"].items():
        if "get" not in ops or "/public/" in path or path.endswith("/stream"):
            continue
        names = re.findall(r"{(\w+)}", path)
        if any(n not in ids for n in names):
            skipped += 1
            continue
        url = path
        for n in names:
            url = url.replace("{" + n + "}", ids[n])
        r = await client.get(url, headers=eng.headers)
        if r.status_code != 200 or "json" not in r.headers.get("content-type", ""):
            # PDFs answer 503 pdf_unavailable on a laptop without WeasyPrint's libraries
            pdf_off = r.status_code == 503 and "pdf_unavailable" in r.text
            assert r.status_code < 500 or pdf_off, f"{url} answered {r.status_code}"
            continue
        checked += 1
        hits = _money_keys(r.json())
        if hits:
            leaks[url] = hits[:5]
    assert not leaks, f"prices reached a field engineer: {leaks}"
    assert checked >= 15, f"only {checked} routes answered a field engineer (skipped {skipped})"


def test_the_detector_catches_prices() -> None:
    assert _money_keys({"lines": [{"unit_price": "1.00"}]}) == [".lines[0].unit_price"]
    assert _money_keys({"selling": 5}) == [".selling"]
    assert _money_keys({"note": "Rs ₹ 100"}) == [".note (rupee sign)"]
    assert _money_keys({"cost": None, "total": 3, "price_ref": {}}) == []
    assert _money_keys({"gst_rate": "18.00", "total_minutes": 90}) == []
    assert _money_keys({"margin_pct": "12.0", "gst": "180.00"}) == [".margin_pct", ".gst"]
    assert _money_keys({"id": str(uuid.uuid4()), "title": "Firewall"}) == []
