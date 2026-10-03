"""The document corpus: cleaning, labels, quality and the canonical JSON record (ADR 0014).
Pure tests, no database."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.modules.datasets import cleaning, corpus, quality

SAMPLES = Path(__file__).parents[5] / "samples"
GOLDEN = SAMPLES / "corpus"


def _sample(pattern: str) -> Path:
    return next(p for p in SAMPLES.glob(pattern) if p.is_file())


# ------------------------------------------------------------------ cleaning


def test_text_is_normalised() -> None:
    raw = "  \u2018Sophos\u2019\u00a0 XGS \u2013 108\u2022 "
    assert cleaning.normalise_text(raw) == "'Sophos' XGS - 108"
    assert cleaning.normalise_text(None) == ""


def test_domain_spelling_is_fixed_keeping_capitals() -> None:
    assert cleaning.fix_spelling("Phoneix ODR") == "Phoenix ODR"
    assert cleaning.fix_spelling("risk of quarentine, set up and managment") == (
        "risk of quarantine, setup and management"
    )


def test_heading_printed_over_a_line_is_taken_out() -> None:
    garbled = "FHoigrhti nPerito /r iStoyphos One Time Setup Installation Charges"
    fixed, heading = cleaning.repair_interleaved(garbled, ["To Consider", "High Priority"])
    assert fixed == "Fortinet / Sophos One Time Setup Installation Charges"
    assert heading == "High Priority"


def test_clean_text_is_left_alone() -> None:
    text = "FortiGate FG40F UTM with 3Year Subscription"
    assert cleaning.repair_interleaved(text, ["High Priority"]) == (text, None)


def test_unrepairable_text_is_returned_unchanged() -> None:
    garbled = "XQabYZcdWWefGGhi"
    assert cleaning.repair_interleaved(garbled, ["High Priority"]) == (garbled, None)


@pytest.mark.parametrize(
    ("component", "gap", "role"),
    [
        ("System sanitization to quarantine", "conflicting_av", "service"),
        ("Acronis XDR - Extended Detection and Response per annum", "no_unified_eps", "product"),
        ("EPS implementation, security set up configuration + One Year", "no_unified_eps", "setup"),
        ("Cisco Catalyst C1300-24T-4G Giga Managed Switch", "unmanaged_switch", "product"),
        (
            "Sophos XGS-108 Firewall With 3 years Xtreme Protection",
            "firewall_underconfigured",
            "product",
        ),
        ("FortiGate FG40F UTM with 3Year Subscription", "firewall_underconfigured", "product"),
        (
            "Fortinet / Sophos One Year Support Charges for VPN Firewall",
            "firewall_underconfigured",
            "support",
        ),
        ("Server for AD/DC", "no_second_dc", "product"),
        ("Phoneix ODR", "no_disaster_recovery", "product"),
        ("DLP", "no_dlp", "product"),
        ("NAS", "backup_at_risk", "product"),
        ("Office 2021 upgrade", "outdated_licence", "product"),
        ("8 GB DDR4 RAM", "underspec_hardware", "product"),
        ("Coffee machine", "other", "product"),
    ],
)
def test_lines_get_the_gap_type_the_boq_templates_use(component: str, gap: str, role: str) -> None:
    lab = cleaning.label_line(component)
    assert (lab.gap_type, lab.line_role) == (gap, role)
    assert lab.gap_type in cleaning.TAXONOMY and lab.line_role in cleaning.LINE_ROLES


def test_a_setup_line_belongs_to_the_product_above_it() -> None:
    labels = cleaning.label_lines(
        [
            ("Switch", "Cisco Catalyst Managed Switch", "", []),
            ("Switch", "One time setup installation charges", "", []),
            ("Other", "One time setup installation charges", "", []),
        ]
    )
    assert (labels[1].gap_type, labels[1].line_role, labels[1].rule) == (
        "unmanaged_switch",
        "setup",
        "follows line 1",
    )
    assert labels[2].gap_type == "other"  # a different section is not inherited


@given(st.text(max_size=200))
def test_normalising_twice_changes_nothing(s: str) -> None:
    once = cleaning.normalise_text(s)
    assert cleaning.normalise_text(once) == once


@given(
    st.text(alphabet="abcdefghij ", max_size=40),
    st.text(alphabet="KLMNOP", min_size=1, max_size=10),
)
def test_removing_a_subsequence_keeps_every_other_character(text: str, noise: str) -> None:
    out = cleaning._remove_subsequence(text + noise, noise)
    assert out == text


# ------------------------------------------------------------------ quality


def _line(
    ref: str, qty: int, price: str | None, amount: str | None, gap: str = "no_dlp"
) -> dict[str, Any]:
    return {
        "line_ref": ref,
        "component": f"Item {ref}",
        "name_key": f"item {ref}",
        "option": None,
        "qty": qty,
        "unit_price": price,
        "amount": amount,
        "confidence": 1.0,
        "label": {"gap_type": gap},
    }


def test_quality_catches_wrong_amounts_duplicates_and_missing_facts() -> None:
    doc = {"doc_kind": "quotation", "quote_ref": None, "quote_date": "2026-09-26", "customer": "A"}
    lines = [
        _line("1", 2, "100.00", "200.00"),
        _line("2", 3, "100.00", "250.00"),
        _line("1", 2, "100.00", "200.00", gap="other"),
    ]
    lines[2]["name_key"] = lines[0]["name_key"]
    q = quality.boq_quality(doc, lines)
    assert q["parts"]["consistency"] == pytest.approx(2 / 3, abs=1e-3)
    assert q["parts"]["uniqueness"] == pytest.approx(2 / 3, abs=1e-3)
    assert any("quote ref" in i for i in q["issues"])
    assert any("250.00 is not quantity 3" in i for i in q["issues"])
    assert any("no gap type matched" in i for i in q["issues"])
    assert 0 < q["score"] < 100


def test_a_clean_document_scores_100() -> None:
    doc = {"doc_kind": "summary"}
    assert quality.boq_quality(doc, [_line("1", 31, None, None)])["score"] == 100


def test_outliers_use_the_median_absolute_deviation() -> None:
    vals = [Decimal(v) for v in ("500", "520", "480", "510", "495", "5000")]
    assert quality.mad_outliers(vals) == [False] * 5 + [True]
    assert quality.mad_outliers(vals[:4]) == [False] * 4  # too few to judge


def test_analysis_gives_price_bands_per_label() -> None:
    rows = [
        {
            "gap_type": "conflicting_av",
            "line_role": "service",
            "qty": q,
            "unit_price": Decimal(p),
            "customer": c,
            "quote_ref": f"R{i}",
            "component": "Sanitization",
        }
        for i, (q, p, c) in enumerate(
            [
                (31, "500", "A"),
                (20, "450", "B"),
                (12, "550", "C"),
                (40, "500", "D"),
                (25, "9000", "E"),
            ]
        )
    ]
    out = quality.analyse_lines(rows)
    band = out["bands"][0]
    assert (band["lines"], band["customers"], band["typical_qty"]) == (5, 5, 25)
    assert band["price_median"] == "500.00" and band["enough_for_outliers"] is True
    assert [o["value"] for o in out["outliers"]] == ["9000"]


# ------------------------------------------------------------------ the canonical record


@pytest.mark.parametrize(
    "pattern",
    ["*- BOQ.pdf", "*Sanitization*.pdf", "*PrismSuite Audit Report.docx"],
)
def test_samples_match_their_committed_corpus_json(pattern: str) -> None:
    """The golden files in samples/corpus are what `cli corpus convert` writes. A parser or
    cleaning change that alters them must regenerate them on purpose."""
    path = _sample(pattern)
    rec = corpus.build_record(
        path.read_bytes(), path.name, origin="folder", built_at=corpus.EPOCH
    ).record
    golden = json.loads((GOLDEN / f"{path.stem}.json").read_text(encoding="utf-8"))
    assert json.loads(json.dumps(rec, sort_keys=True)) == golden


def test_the_priced_quotation_record() -> None:
    path = _sample("*Sanitization*.pdf")
    built = corpus.build_record(path.read_bytes(), path.name)
    rec = built.record
    assert rec["schema"] == "p1.corpus.v1" and rec["kind"] == "boq"
    assert rec["document"]["quote_ref"] == "ITCraft/NN/2627/030"
    assert rec["document"]["gst_rate"] == "18" or rec["document"]["gst_rate"].startswith("18")
    # options are kept as separate lines, never merged
    assert [ln["line_ref"] for ln in rec["lines"]][5:7] == ["6A", "6B"]
    repaired = next(ln for ln in rec["lines"] if ln["line_ref"] == "7")
    assert repaired["component"].startswith("Fortinet / Sophos One Time Setup")
    assert repaired["component_raw"].startswith("FHoigrhti")
    assert "repaired_interleaved_heading" in repaired["flags"] and repaired["confidence"] < 0.8
    assert {ln["label"]["gap_type"] for ln in rec["lines"]} >= {
        "conflicting_av",
        "no_unified_eps",
        "unmanaged_switch",
        "firewall_underconfigured",
    }
    # converted once, the record is far lighter than the PDF, and it round-trips
    assert rec["sizes"]["gzip"] * 20 < rec["sizes"]["original"]
    assert corpus.read_gz(built.gz)["lines"] == rec["lines"]


def test_the_audit_report_record_keeps_the_snapshot_and_facts() -> None:
    path = _sample("*PrismSuite Audit Report.docx")
    rec = corpus.build_record(path.read_bytes(), path.name).record
    assert rec["kind"] == "audit" and rec["parser"]["name"] == "prismsuite.docx.v1"
    assert rec["document"]["report_ref"] == "PS-10092026-SHA"
    assert len(rec["facts"]) > 40 and rec["audit"]["header"]["customer_name"]
    assert rec["sizes"]["gzip"] * 50 < rec["sizes"]["original"]


def test_unknown_files_keep_their_text() -> None:
    rec = corpus.build_record(b'{"hello": "world"}', "notes.json").record
    assert rec["kind"] == "other" and "hello" in rec["text"]["pages"][0]
    assert rec["quality"]["score"] == 0
    assert corpus.collection_rows(rec) == []


def test_collection_rows_carry_labels_and_typed_money() -> None:
    path = _sample("*Sanitization*.pdf")
    rows = corpus.collection_rows(corpus.build_record(path.read_bytes(), path.name).record)
    sophos = next(r for r in rows if r["line_ref"] == "6A")
    assert sophos["unit_price"] == Decimal("66812.00") and sophos["option"] == "A"
    assert (sophos["gap_type"], sophos["line_role"]) == ("firewall_underconfigured", "product")
    assert sophos["cleaning_version"] == cleaning.CLEANING_VERSION
