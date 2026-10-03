"""The BOQ draft model: numbering, options, totals, every edit operation, and the checks."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.modules.boq import draft as d

TODAY = date(2026, 9, 30)


def sample() -> d.Draft:
    """The shape of the Shobhaglobs quotation."""
    dr = d.empty_draft()
    hp, tc = dr.groups
    s1 = d.Section(group_id=hp.id, title="Sanitization, End Point Security & Managed Switch")
    s2 = d.Section(group_id=hp.id, title="Firewall Options")
    s3 = d.Section(group_id=tc.id, title="Other")
    dr.sections = [s1, s2, s3]

    def ln(
        section: d.Section,
        title: str,
        qty: int,
        price: str | None,
        group: str | None = None,
        **kw: object,
    ) -> d.Line:
        return d.Line(
            section_id=section.id,
            title=title,
            qty=qty,
            unit_price=Decimal(price) if price else None,
            option_group=group,
            price_source="price_book" if price else "none",
            price_ref=d.PriceRef(valid_until=TODAY + timedelta(days=5)) if price else None,
            **kw,
        )

    dr.lines = [
        ln(s1, "System sanitization", 31, "500.00"),
        ln(s1, "Acronis XDR", 31, "1562.00"),
        ln(s1, "EPS implementation", 1, "12000.00"),
        ln(s1, "Cisco C1300 switch", 1, "33972.00"),
        ln(s2, "Sophos XGS-108", 1, "66812.00", "firewall"),
        ln(s2, "FortiGate FG40F", 1, "109653.00", "firewall"),
        ln(s2, "Firewall setup", 1, "12000.00"),
        ln(s3, "NAS", 1, None),
    ]
    return dr


def test_numbering_follows_the_sample_with_options() -> None:
    refs = [n.ref for n in d.numbered(sample())]
    assert refs == ["1", "2", "3", "4", "5A", "5B", "6", "7"]


def test_amounts_match_the_quotation() -> None:
    c = d.compute(sample(), TODAY)
    amounts = {r.ref: r.amount for r in c.lines}
    assert (
        amounts["1"] == Decimal("15500.00")
        and amounts["2"] == Decimal("48422.00")
        and amounts["5B"] == Decimal("109653.00")
    )
    assert c.lines[0].gst == Decimal("2790.00")  # 18 percent of 15,500


def test_options_are_never_summed_together() -> None:
    c = d.compute(sample(), TODAY)
    t = c.totals
    fixed = (
        Decimal("15500.00")
        + Decimal("48422.00")
        + Decimal("12000.00")
        + Decimal("33972.00")
        + Decimal("12000.00")
    )
    assert t.fixed == fixed and t.options["firewall"] == {
        "A": Decimal("66812.00"),
        "B": Decimal("109653.00"),
    }
    assert t.subtotal_min == fixed + Decimal("66812.00") and t.subtotal_max == fixed + Decimal(
        "109653.00"
    )
    assert t.complete is False


def test_selecting_an_option_fixes_the_total() -> None:
    dr, _ = d.apply_ops(sample(), [{"op": "set_option", "group": "firewall", "letter": "B"}])
    t = d.compute(dr, TODAY).totals
    assert (
        t.complete
        and t.subtotal_min == t.subtotal_max
        and t.total_min == t.subtotal_min + t.gst_min
    )
    bad = [{"op": "set_option", "group": "firewall", "letter": "Z"}]
    with pytest.raises(d.OpError):
        d.apply_ops(sample(), bad)


def test_missing_and_expired_prices_block() -> None:
    c = d.compute(sample(), TODAY)
    assert any("NAS" in b and "no price" in b for b in c.blockers)
    later = d.compute(sample(), TODAY + timedelta(days=6))
    assert sum("expired price" in b for b in later.blockers) == 7
    soon = d.compute(sample(), TODAY + timedelta(days=4))
    assert any("expires within" in w for w in soon.warnings) and not any(
        "expired" in b for b in soon.blockers
    )


def test_manual_prices_need_a_reason_and_are_flagged_not_blocked() -> None:
    dr = sample()
    nas = next(x for x in dr.lines if x.title == "NAS")
    with pytest.raises(d.OpError) as e:
        d.apply_ops(dr, [{"op": "update_line", "id": nas.id, "fields": {"unit_price": "41500.00"}}])
    assert e.value.code == "manual_price_reason"
    dr2, _ = d.apply_ops(
        dr,
        [
            {
                "op": "update_line",
                "id": nas.id,
                "fields": {
                    "unit_price": "41500.00",
                    "manual_price_reason": "Distributor call 30 Sep",
                },
            }
        ],
    )
    c = d.compute(dr2, TODAY + timedelta(days=30))  # long after the price book prices expired
    line = next(r for r in c.lines if r.id == nas.id)
    assert "manual_price" in line.flags and "price_expired" not in line.flags
    assert not any("NAS" in b for b in c.blockers)


def test_below_cost_and_budget_warnings() -> None:
    dr = sample()
    nas = next(x for x in dr.lines if x.title == "NAS")
    dr, _ = d.apply_ops(
        dr,
        [
            {
                "op": "update_line",
                "id": nas.id,
                "fields": {
                    "unit_price": "10.00",
                    "cost": "500.00",
                    "manual_price_reason": "Loss leader approved by the director",
                },
            },
            {"op": "update_settings", "fields": {"budget_ceiling": "1000.00"}},
        ],
    )
    w = d.compute(dr, TODAY).warnings
    assert any("below cost" in x for x in w) and any("budget ceiling" in x for x in w)


def test_every_edit_operation() -> None:
    dr = sample()
    hp = dr.groups[0]
    new, notes = d.apply_ops(
        dr,
        [
            {"op": "add_section", "group_id": hp.id, "title": "Backup", "index": 1},
            {
                "op": "add_line",
                "section_id": dr.sections[0].id,
                "index": 0,
                "line": {
                    "title": "Server hardening",
                    "qty": 1,
                    "unit_price": "9000.00",
                    "manual_price_reason": "ITCraft rate card",
                },
            },
            {
                "op": "update_line",
                "id": dr.lines[0].id,
                "fields": {"qty": 27, "description": "Per endpoint"},
            },
            {"op": "delete_line", "id": dr.lines[3].id},
            {"op": "set_terms", "terms": ["GST extra", "  ", "Valid 5 days"]},
            {"op": "update_settings", "fields": {"show_totals": True, "validity_days": 7}},
        ],
    )
    assert (
        len(notes) == 6
        and new.terms == ["GST extra", "Valid 5 days"]
        and new.settings.show_totals is True
    )
    assert [s.title for s in new.sections][:2] == [dr.sections[0].title, "Backup"]
    first = d.numbered(new)[0].line
    assert first.title == "Server hardening"  # inserted at index 0 of its section
    assert next(x for x in new.lines if x.id == dr.lines[0].id).qty == 27
    assert all(x.title != "Cisco C1300 switch" for x in new.lines)


def test_move_lines_between_sections_and_groups() -> None:
    dr = sample()
    target = dr.sections[2]
    moved, _ = d.apply_ops(
        dr, [{"op": "move_line", "id": dr.lines[0].id, "section_id": target.id, "index": 0}]
    )
    order = [(x.line.title, x.group_id) for x in d.numbered(moved)]
    assert order[-2][0] == "System sanitization" and order[-2][1] == dr.groups[1].id
    tc = dr.groups[1]
    m2, _ = d.apply_ops(dr, [{"op": "update_section", "id": dr.sections[1].id, "group_id": tc.id}])
    assert {x.group_id for x in d.numbered(m2) if x.section_title == "Firewall Options"} == {tc.id}


def test_sections_and_groups_protect_their_contents() -> None:
    dr = sample()
    with pytest.raises(d.OpError) as e:
        d.apply_ops(dr, [{"op": "delete_section", "id": dr.sections[0].id}])
    assert e.value.code == "section_not_empty"
    ok, _ = d.apply_ops(
        dr, [{"op": "delete_section", "id": dr.sections[2].id, "move_lines_to": dr.sections[0].id}]
    )
    assert len(ok.sections) == 2 and any(
        x.title == "NAS" and x.section_id == dr.sections[0].id for x in ok.lines
    )
    with pytest.raises(d.OpError):
        d.apply_ops(dr, [{"op": "delete_group", "id": dr.groups[0].id}])
    ok2, _ = d.apply_ops(
        dr, [{"op": "delete_group", "id": dr.groups[0].id, "move_sections_to": dr.groups[1].id}]
    )
    assert [g.title for g in ok2.groups] == ["To Consider"]
    renamed, _ = d.apply_ops(
        dr,
        [
            {"op": "update_group", "id": dr.groups[1].id, "title": "Later"},
            {"op": "add_group", "title": "Optional"},
        ],
    )
    assert [g.title for g in renamed.groups] == ["High Priority", "Later", "Optional"]


def test_edits_are_all_or_nothing() -> None:
    dr = sample()
    before = dr.model_dump()
    with pytest.raises(d.OpError):
        d.apply_ops(
            dr,
            [
                {"op": "update_line", "id": dr.lines[0].id, "fields": {"qty": 99}},
                {"op": "delete_line", "id": "missing"},
            ],
        )
    assert dr.model_dump() == before


@pytest.mark.parametrize(
    "op",
    [
        {"op": "update_line", "id": "x", "fields": {}},
        {"op": "update_line", "id": "x", "fields": {"section_id": "z"}},
        {"op": "nope"},
        {"op": "update_settings", "fields": {"validity_days": 0}},
        {"op": "update_settings", "fields": {"surprise": 1}},
    ],
)
def test_invalid_edits_are_refused(op: dict[str, object]) -> None:
    dr = sample()
    if op.get("id") == "x":
        op = {**op, "id": dr.lines[0].id}
    with pytest.raises(d.OpError):
        d.apply_ops(dr, [op])


def test_money_rules_are_enforced_on_lines() -> None:
    dr = sample()
    lid = dr.lines[0].id
    for fields in (
        {"unit_price": "10.555", "manual_price_reason": "x y z"},
        {"qty": -1},
        {"gst_rate": "150"},
        {"unit_price": -5, "manual_price_reason": "x y z"},
    ):
        with pytest.raises(d.OpError):
            d.apply_ops(dr, [{"op": "update_line", "id": lid, "fields": fields}])
    with pytest.raises(d.OpError):
        d.apply_ops(
            dr,
            [
                {
                    "op": "update_line",
                    "id": lid,
                    "fields": {"unit_price": 10.5, "manual_price_reason": "float refused"},
                }
            ],
        )


def test_diff_summarises_what_changed() -> None:
    old = sample()
    new, _ = d.apply_ops(
        old,
        [
            {"op": "update_line", "id": old.lines[0].id, "fields": {"qty": 27}},
            {"op": "delete_line", "id": old.lines[7].id},
            {
                "op": "add_line",
                "section_id": old.sections[0].id,
                "line": {
                    "title": "Hardening",
                    "unit_price": "9000.00",
                    "manual_price_reason": "rate card",
                },
            },
        ],
    )
    delta = d.diff(old, new)
    assert (
        delta["added"] == ["Hardening"]
        and delta["removed"] == ["NAS"]
        and delta["changed"][0]["qty"] == ["31", "27"]
    )
    assert d.summarise(delta) == "1 added, 1 removed, 1 changed."
    assert d.summarise(d.diff(None, new)).startswith("First version")
    assert d.summarise(d.diff(new, new)) == "No line changes (terms or settings only)."
