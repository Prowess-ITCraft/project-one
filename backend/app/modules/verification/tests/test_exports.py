"""Reading configuration exports and judging values (phase 9). Pure tests."""

from __future__ import annotations

import base64
import json

import pytest

from app.modules.verification.exports import apply_rule, parse_export, read_key_values


def _exp(pairs: dict[str, str]) -> bytes:
    raw = "&".join(f"{k}={v}" for k, v in pairs.items()) + "&"
    return base64.b64encode(raw.encode())


def test_classic_sonicwall_exp_is_read() -> None:
    data = _exp(
        {"firmwareVersion": "SonicOS 7.0.1-5145", "adminName": "admin", "ipsGlobalEnable": "on"}
    )
    got = parse_export("TZ270.exp", data)
    assert got is not None and got.brand == "sonicwall" and got.shape == "exp"
    assert got.facts["adminName"] == "admin" and got.facts["ipsGlobalEnable"] == "on"


def test_text_and_json_exports_are_read() -> None:
    text = b"# SonicWall TZ 270 settings\nfirmware_version = 7.0.1\nadmin_name: fw-admin\n"
    got = parse_export("settings.txt", text)
    assert got is not None and got.shape == "text" and got.facts["admin_name"] == "fw-admin"
    js = json.dumps(
        {
            "device": "SonicWall TZ 270",
            "administration": {"admin_name": "x", "two_factor": {"enable": True}},
        }
    )
    got = parse_export("api.json", js.encode())
    assert got is not None and got.shape == "json"
    assert got.facts["administration.two_factor.enable"] == "True"


def test_other_brands_are_not_claimed_as_sonicwall() -> None:
    assert (
        parse_export("fortigate.conf", b"config system global\nset hostname FGT40F\nend\n") is None
    )
    assert read_key_values(b"") is None


@pytest.mark.parametrize(
    ("rule", "value", "outcome"),
    [
        ({"op": "truthy"}, "on", "pass"),
        ({"op": "truthy"}, "off", "fail"),
        ({"op": "falsy"}, "disabled", "pass"),
        ({"op": "ne", "value": "admin"}, "fw-admin", "pass"),
        ({"op": "ne", "value": "admin"}, "Admin", "fail"),
        ({"op": "eq", "value": "https"}, "HTTPS", "pass"),
        ({"op": "in", "value": ["ssh", "https"]}, "telnet", "fail"),
        ({"op": "not_in", "value": ["telnet"]}, "ssh", "pass"),
        ({"op": "version_gte", "value": "7.0.1"}, "SonicOS 7.1.2-7019", "pass"),
        ({"op": "version_gte", "value": "7.0.1"}, "SonicOS 6.5.4", "fail"),
        ({"op": "record"}, "7.0.1", "not_checked"),
    ],
)
def test_rules(rule: dict, value: str, outcome: str) -> None:  # type: ignore[type-arg]
    assert apply_rule(rule, value)[0] == outcome
