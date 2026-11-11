"""`domain.work_orders_smr_block` (spec 2026-11-04, D4): the correction block
pasted into NetFacilities, pinned the way `test_receipt.py` pins the receipt.
Lines are stand-ins with the column names as attributes."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace as NS

from app.domain import receipt
from app.domain import work_orders_smr_block as block
from app.domain.work_orders_smr_lines import WEEK1_PLACEMENT_BASIS


def _line(**overrides):
    fields = dict(work_date=date(2026, 6, 20), date_basis="paper", week=4, vendor="Belfor", worker=None, headcount=1,
                  hours_each=Decimal("1.0"), kind="field", reason_code="accurate", status="charged",
                  exclusion_ground=None)
    if overrides.get("work_date", fields["work_date"]) is None:
        fields["week"] = None
    fields.update(overrides)
    return NS(**fields)


def _sample_lines():
    return [
        _line(vendor="BT Restoration", headcount=2, hours_each=Decimal("3.0"), reason_code="crew_as_one"),
        _line(hours_each=Decimal("0.5"), kind="assessment", reason_code="overhead_added"),
        _line(work_date=date(2026, 6, 22), vendor="XXL Construction", worker=NS(display_name="Trinton Smith"),
              hours_each=Decimal("4.0"), reason_code="crew_as_one"),
        _line(work_date=None, date_basis=WEEK1_PLACEMENT_BASIS, week=1, headcount=3, hours_each=Decimal("2.0")),
        _line(work_date=None, vendor="Green Choice", worker=NS(display_name="Rye"), hours_each=Decimal("7.0"),
              status="excluded", exclusion_ground="undated", reason_code="not_on_paper"),
        _line(work_date=date(2026, 7, 15), vendor="Green Choice", headcount=4, hours_each=Decimal("24.0"),
              status="excluded", exclusion_ground="after 07/12 (no invoices)", reason_code="awaiting_invoice"),
    ]


TARGET = {"hours": "10.0", "labor_total": "625.00", "source_row": {"Labor Type": "SL"}}


def _target(hours, money):
    return {"hours": hours, "labor_total": money, "source_row": {"Labor Type": "SL"}}


def _render(lines, target=TARGET, version=2):
    return block.render_correction_block("23281563", target, lines, version, date(2026, 11, 10))


def test_one_full_block_verbatim():
    # The TechFM correction memo (user 2026-11-06): what NetFacilities has,
    # what the paper shows, what to add; the corrected record in date order
    # with a Week 1 placement first ("week of 05/25"); one reason block;
    # excluded lines left out. The width is the destination's: it wraps at 42.
    assert _render(_sample_lines()) == "\n".join([
        "SMR27 LABOR CORRECTION           11/10/26",
        "WO 23281563",
        "",
        "ITEMIZED RECEIPT",
        "  (no materials keyed)",
        "Materials                           $0.00",
        "",
        "Original Estimate      10.0 h SL  $625.00",
        "Finalized Total                    16.5 h",
        "Add to WO                          +6.5 h",
        "                                  $406.25",
        "",
        "Finalized labor record:",
        "ST $62.50/h  GL $43.50/h",
        "Belfor ST                           6.0 h",
        "Belfor Assessment ST                0.5 h",
        "XXL Construction ST                 4.0 h",
        "BT Restoration ST                   6.0 h",
        "",
        "Labor total                     $1,031.25",
        "Materials total                     $0.00",
        "Total                           $1,031.25",
    ])


def test_lines_never_exceed_the_destination_width():
    # Names no longer print (user 2026-11-11), so the longest row is a
    # vendor, a kind and the labor type; it still fits the destination.
    long_name = NS(display_name="Bartholomew Montgomery-Fitzwilliam the Third")
    lines = _sample_lines() + [
        _line(worker=long_name, vendor="XXL Construction", kind="assessment, audit, staging",
              reason_code="hours_on_paper_above_billed", hours_each=Decimal("12.5")),
        _line(vendor="XXL Construction", kind="material preparation", headcount=40, hours_each=Decimal("30.0")),
        _line(reason_code="a_code_nobody_has_seen_before_that_runs_well_past_the_width_of_the_box"),
    ]
    rendered = _render(lines).split("\n")
    assert all(len(row) <= receipt.PRICING_LINE_WIDTH for row in rendered)
    assert _r("XXL Construction Prep GL", "1200.0 h") in rendered
    assert "Bartholomew" not in "\n".join(rendered)
    assert not any(row.startswith("Reason") for row in rendered)  # user 2026-11-06: no Reason lines


def _r(label, amount):
    return label.ljust(receipt.PRICING_LINE_WIDTH - len(amount)) + amount


def test_labor_rows_are_one_line_per_vendor_and_kind_with_the_labor_type():
    # User 2026-11-11: no names; "{vendor} {Audit/Prep/Stage/Assessment/Clean
    # or blank} {GL/ST} {total hours}", one line each, the two rates named
    # once above them. A leftover mixed line is plain ST.
    lines = [
        _line(vendor="Green Choice", worker=NS(display_name="Rye"), hours_each=Decimal("4.0")),
        _line(vendor="XXL Construction", hours_each=Decimal("2.0")),
        _line(kind="audit, staging", hours_each=Decimal("0.5")),
        _line(kind="staging", hours_each=Decimal("0.5")),
        _line(kind="audit", hours_each=Decimal("0.5")),
        _line(kind="assessment", hours_each=Decimal("0.5")),
        _line(vendor="Green Choice", kind="clean-up", hours_each=Decimal("0.5")),
        _line(vendor="Green Choice", kind="material preparation", hours_each=Decimal("1.0")),
        _line(vendor="Green Choice", kind="material preparation", headcount=2, hours_each=Decimal("1.0")),
    ]
    rendered = _render(lines, target=_target("3.0", "187.50")).split("\n")
    start = rendered.index("Finalized labor record (SMR Week 4):")
    assert rendered[start + 1:start + 10] == [
        "ST $62.50/h  GL $43.50/h",
        _r("Belfor ST", "0.5 h"),
        _r("Belfor Assessment ST", "0.5 h"),
        _r("Belfor Audit GL", "0.5 h"),
        _r("Belfor Stage GL", "0.5 h"),
        _r("Green Choice ST", "4.0 h"),
        _r("Green Choice Prep GL", "3.0 h"),
        _r("Green Choice Clean GL", "0.5 h"),
        _r("XXL Construction ST", "2.0 h"),
    ]
    assert "Rye" not in "\n".join(rendered)
    # 7.0 h x 62.50 + 4.5 h x 43.50 = 633.25; the add is that less the 187.50 NetFacilities has.
    assert _r("Labor total", "$633.25") in rendered
    assert rendered[rendered.index(_r("Add to WO", "+8.5 h")) + 1] == _r("", "$445.75")


def test_the_same_hours_at_a_lower_rate_still_print_the_dollar_difference():
    rendered = _render([_line(kind="audit")], target=_target("1.0", "62.50")).split("\n")
    assert rendered[rendered.index(_r("Add to WO", "+0.0 h")) + 1] == _r("", "-$19.00")


def test_a_decrease_prints_with_a_minus_and_lowers_the_total():
    lines = [_line(hours_each=Decimal("3.0")), _line(hours_each=Decimal("-2.0"), reason_code="over_billed")]
    rendered = _render(lines, target=_target("3.0", "187.50")).split("\n")
    assert _r("Belfor ST", "1.0 h") in rendered
    assert "Finalized Total                     1.0 h" in rendered
    assert "Add to WO                          -2.0 h" in rendered
    assert "                                 -$125.00" in rendered


def test_an_order_without_a_sheet_row_says_so():
    rendered = _render([_line()], target=None).split("\n")
    assert "Original Estimate                   0.0 h" in rendered
    assert "Add to WO                          +1.0 h" in rendered
    assert not any("on the WO." in row for row in rendered)


def test_one_week_names_itself_in_the_heading():
    assert "Finalized labor record (SMR Week 4):" in _render([_line(), _line(hours_each=Decimal("2.0"))]).split("\n")
    assert "Finalized labor record:" in _render(_sample_lines()).split("\n")


def test_excluded_lines_do_not_print():
    # Only what is added to a work order needs a justification (user
    # 2026-11-06): the auditor reads excluded lines in the app, not here.
    rendered = _render(_sample_lines())
    assert "Not charged" not in rendered and "Rye" not in rendered and "96.0" not in rendered
    assert "  (nothing charged)" in _render([_line(status="excluded")]).split("\n")


def test_a_changed_line_changes_the_digest_and_order_does_not():
    lines = _sample_lines()
    before = block.lines_digest(lines)
    assert before == block.lines_digest(list(reversed(lines)))
    assert len(before) == 64

    lines[1].hours_each = Decimal("1.0")
    assert block.lines_digest(lines) != before

    lines[1].hours_each = Decimal("0.5")
    assert block.lines_digest(lines) == before
    lines[0].status, lines[0].exclusion_ground = "excluded", "removed"
    assert block.lines_digest(lines) != before

    lines[0].status, lines[0].exclusion_ground = "charged", None
    assert block.lines_digest(lines) == before
    lines[3].week = 2  # a placement moved to another week prints differently
    assert block.lines_digest(lines) != before


def _materials():
    return [
        receipt.ReceiptLine(name="Duct tape 2in", quantity=Decimal("2"), billable_quantity=None, unit_price=Decimal("5.35")),
        receipt.ReceiptLine(name="Ceiling tile", quantity=Decimal("1"), billable_quantity=None, unit_price=None),
    ]


def test_materials_print_as_the_itemized_receipt_and_join_the_total():
    # User 2026-11-06: the receipt sits above the labor; the Total is the
    # corrected WO total, materials at the marked-up charge plus labor.
    target = dict(TARGET, materials_total="21.57")
    rendered = block.render_correction_block("23281563", target, [_line()], 2, date(2026, 11, 10), materials=_materials()).split("\n")
    assert rendered[3:9] == [
        "MATERIAL CORRECTION",
        "Original estimated total           $21.57",
        "ITEMIZED RECEIPT",
        "2 Duct tape 2in                    $12.31",
        "1 Ceiling tile                   NO PRICE",
        "Materials                          $12.31",
    ]
    assert "Total                              $74.81" in rendered  # 12.31 + 1.0 h x $62.50


def test_matching_material_totals_print_no_correction_header():
    target = dict(TARGET, materials_total="12.31")
    rendered = block.render_correction_block("23281563", target, [_line()], 2, date(2026, 11, 10), materials=_materials()[:1]).split("\n")
    assert rendered[3] == "ITEMIZED RECEIPT" and "MATERIAL CORRECTION" not in rendered
    assert "Original estimated total" not in "\n".join(rendered)


def test_a_line_removed_in_the_app_does_not_print():
    # User 2026-11-06: a removed line is a keying mistake, not paper. History
    # keeps it; the pasted text does not show it.
    removed = _line(status="excluded", exclusion_ground="removed", hours_each=Decimal("9.0"))
    assert _render(_sample_lines() + [removed]) == _render(_sample_lines())


def test_reason_text_falls_back_to_the_code_in_words():
    assert block.reason_text("crew_as_one") == "crew billed as one person"
    assert block.reason_text("as_read") == "hours as read on the paper"
    assert block.reason_text("some_new_code") == "some new code"


def test_no_diff_line_when_the_paper_matches_the_estimate():
    rendered = _render([_line(hours_each=Decimal("1.0"))], target=_target("1.0", "62.50")).split("\n")
    assert "Finalized Total                     1.0 h" in rendered
    assert not any(row.startswith("Add to WO") for row in rendered)


def test_the_work_description_wraps_to_the_width_under_its_heading():
    text = "Replaced the vanity top and patched drywall behind it; hauled debris.\n\nCrew of two, one full day."
    rows = block.render_correction_block("23281563", TARGET, [_line()], 1, date(2026, 11, 10),
                                         description=text).split("\n")
    start = rows.index("WORK DESCRIPTION")
    assert rows[start + 1:rows.index("ITEMIZED RECEIPT")] == [
        "Replaced the vanity top and patched",
        "drywall behind it; hauled debris.",
        "",
        "Crew of two, one full day.",
        "",
    ]
    assert all(len(row) <= receipt.PRICING_LINE_WIDTH for row in rows)
    assert "WORK DESCRIPTION" not in _render([_line()])
