"""The certificate lists kinds of work, not every task; the completion report has the full list."""

from typing import Any

from app.modules.reporting.service import certificate_scope


def test_same_work_on_many_devices_is_one_line() -> None:
    title = "Sanitize system: remove extra antivirus agents"
    delivered: list[dict[str, Any]] = [
        {"title": "Install the managed switch", "device": "SW-01"},
        {"title": f"{title}: ACCOUNTS-1", "device": "ACCOUNTS-1"},
        {"title": f"{title}: unit 7 of 27", "device": None},
        {"title": f"{title}: unit 8 of 27", "device": None},
        {"title": "Configure the managed switch: VLANs, management and firmware", "device": None},
    ]
    assert certificate_scope(delivered) == [
        "Install the managed switch (SW-01)",
        f"{title}, 3 devices",
        "Configure the managed switch: VLANs, management and firmware",
    ]


def test_nothing_delivered_gives_an_empty_list() -> None:
    assert certificate_scope([]) == []
