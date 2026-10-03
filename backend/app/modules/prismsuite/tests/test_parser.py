"""The V1 parser against the real Shakti sample, plus fuzzing. No containers needed."""

from __future__ import annotations

import contextlib
import io
import zipfile
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.modules.prismsuite.parsers import base, docx_v1
from app.modules.prismsuite.snapshot import DeviceCategory, FieldStatus

SAMPLE = next((Path(__file__).parents[5] / "samples").glob("*PrismSuite Audit Report.docx"))


@pytest.fixture(scope="module")
def sample_bytes() -> bytes:
    return SAMPLE.read_bytes()


@pytest.fixture(scope="module")
def parsed(sample_bytes: bytes) -> base.ParseResult:
    return docx_v1.PrismSuiteParserV1().parse(sample_bytes)


def test_detects_and_is_picked(sample_bytes: bytes) -> None:
    p = base.pick(sample_bytes, "docx")
    assert p is not None and p.name == "prismsuite.docx.v1"
    assert base.pick(sample_bytes, "pdf") is None
    assert base.pick(b"not a zip", "docx") is None


def test_header(parsed: base.ParseResult) -> None:
    h = parsed.snapshot.header
    assert h.customer_name == "Shakti Equipments Pvt Ltd"
    assert h.report_reference == "PS-10092026-SHA"
    assert str(h.audit_date) == "2026-09-10"
    assert h.auditor


def test_headline_scores(parsed: base.ParseResult) -> None:
    s = parsed.snapshot.scores
    assert s.security.value == Decimal("58.7")
    assert s.high_availability.value == Decimal("50")
    assert s.system_health.value == Decimal("74.2")
    assert s.performance.value == Decimal("60.3")
    assert parsed.snapshot.server_hardening_score is not None
    assert parsed.snapshot.server_hardening_score.value == Decimal("3.83")
    assert parsed.snapshot.server_hardening_score.out_of == Decimal(10)


def test_component_scores(parsed: base.ParseResult) -> None:
    c = parsed.snapshot.component_scores
    assert c.health["firewall"].value == Decimal("62")
    assert c.health["nas"].value == Decimal("56")
    assert c.health["access_point"].value is None  # the report says N/A


def test_asset_counts(parsed: base.ParseResult) -> None:
    a = parsed.snapshot.assets
    assert (a.laptops, a.desktops, a.servers, a.firewalls) == (4, 23, 1, 1)
    assert a.endpoints_total == 27
    assert len(parsed.snapshot.endpoints) == 27


def test_devices(parsed: base.ParseResult) -> None:
    snap = parsed.snapshot
    fw = snap.devices_of(DeviceCategory.FIREWALL)
    assert [d.brand_model for d in fw] == ["SONICWALL TZ 270"]
    nas = snap.devices_of(DeviceCategory.NAS)[0]
    assert nas.brand_model == "Synology DS218+"
    assert nas.storage_used_percent == Decimal(100)
    switches = {d.brand_model: d.managed for d in snap.devices_of(DeviceCategory.SWITCH)}
    assert switches["D-Link DGS-1024C"] is False  # the unmanaged switch
    assert switches["Cisco Business 350 Series"] is True


def test_upgrade_needs_match_the_brief(parsed: base.ParseResult) -> None:
    u = parsed.snapshot.upgrades
    assert u.ram_upgrade_count == 3  # three systems at 4 GB
    assert u.licence_upgrade_count == 2  # two on Office 2013
    assert u.conflicting_av_count == 6  # six systems with two AV agents
    assert all(len(c.products) == 2 for c in u.conflicting_av)


def test_vulnerabilities(parsed: base.ParseResult) -> None:
    assert parsed.snapshot.vulnerabilities.total == 45
    assert parsed.snapshot.vulnerabilities.listed
    assert all(v.title for v in parsed.snapshot.vulnerabilities.listed)


def test_recommendations(parsed: base.ParseResult) -> None:
    assert {r.area for r in parsed.snapshot.recommendations} >= {"EPS", "DR"}


def test_read_report_is_honest(parsed: base.ParseResult) -> None:
    by_path = {f.path: f for f in parsed.report.fields}
    assert parsed.report.blocking == []
    conflict = by_path["/devices[firewall]/high_availability"]
    assert conflict.status == FieldStatus.CONFLICT
    assert conflict.message


def test_snapshot_round_trips(parsed: base.ParseResult) -> None:
    from app.modules.prismsuite.snapshot import AuditSnapshot

    again = AuditSnapshot.model_validate(parsed.snapshot.model_dump(mode="json"))
    assert again == parsed.snapshot


def test_missing_sections_are_reported_not_fatal(sample_bytes: bytes) -> None:
    """Remove the vulnerability and recommendation text and the parser must still return."""
    src = zipfile.ZipFile(io.BytesIO(sample_bytes))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "word/document.xml":
                data = data.replace(b"Vulnerabilit", b"Xxxxxxxxxxxx")
            dst.writestr(item, data)
    result = docx_v1.PrismSuiteParserV1().parse(out.getvalue())
    assert result.snapshot.header.customer_name == "Shakti Equipments Pvt Ltd"
    assert any(f.status != FieldStatus.OK for f in result.report.fields)


def test_garbage_is_a_parse_failure() -> None:
    with pytest.raises(base.ParseFailure):
        docx_v1.PrismSuiteParserV1().parse(b"PK\x03\x04 definitely not a docx")


# ------------------------------------------------------------------ fuzzing

_FUZZ = settings(
    max_examples=40,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)


@_FUZZ
@given(st.binary(max_size=4000))
def test_detect_never_raises(data: bytes) -> None:
    for p in base.all_parsers():
        assert 0.0 <= p.detect(data) <= 1.0


@_FUZZ
@given(st.data())
def test_parse_survives_byte_flips(data: st.DataObject) -> None:
    raw = bytearray(SAMPLE.read_bytes())
    for _ in range(data.draw(st.integers(1, 30))):
        raw[data.draw(st.integers(0, len(raw) - 1))] = data.draw(st.integers(0, 255))
    with contextlib.suppress(base.ParseFailure):  # the only allowed failure
        docx_v1.PrismSuiteParserV1().parse(bytes(raw))


@_FUZZ
@given(st.integers(0, 10_000))
def test_parse_survives_truncation(cut: int) -> None:
    raw = SAMPLE.read_bytes()
    with contextlib.suppress(base.ParseFailure):
        docx_v1.PrismSuiteParserV1().parse(raw[: max(1, len(raw) - cut)])
