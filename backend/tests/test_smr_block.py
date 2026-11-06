"""`domain.work_orders_smr_block` (spec 2026-11-04, D4): the correction block
pasted into NetFacilities, pinned the way `test_receipt.py` pins the receipt.
Lines are stand-ins with the column names as attributes."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace as NS

from app.domain import receipt
from app.domain import work_orders_smr_block as block
from app.domain.work_orders_smr_lines import WEEK1_PLACEMENT_BASIS, WEEK_PLACEMENT_BASIS


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
        "SMR27 LABOR CORRECTION v2        11/10/26",
        "WO 23281563",
        "NetFacilities has      10.0 h SL  $625.00",
        "Paper shows                        16.5 h",
        "Add to WO                          +6.5 h",
        "                                  $406.25",
        "",
        "Corrected labor record:",
        "week of 05/25 Belfor x3        2.0 h each",
        "06/20 BT Restoration x2        3.0 h each",
        "06/20 Belfor assessment             0.5 h",
        "06/22 Trinton Smith (XXL)           4.0 h",
        "",
        "Reason: billed accurately; who and when,",
        "  crew billed as one person,",
        "  overhead added, label only,",
        "replacing the 10.0 h SL on the WO.",
        "Paper on file.",
    ])


def test_lines_never_exceed_the_destination_width():
    # An over-long name, kind list, ground and reason all truncate with `...`
    # and the amount stays flush right, like `receipt.pricing_line`.
    long_name = NS(display_name="Bartholomew Montgomery-Fitzwilliam the Third")
    lines = _sample_lines() + [
        _line(worker=long_name, vendor="XXL Construction", kind="assessment, audit, staging",
              reason_code="hours_on_paper_above_billed", hours_each=Decimal("12.5")),
        _line(worker=long_name, vendor="BT Restoration", headcount=12, hours_each=Decimal("10.0"),
              status="excluded", exclusion_ground="awaiting invoice (GC, Week 7)"),
        _line(reason_code="a_code_nobody_has_seen_before_that_runs_well_past_the_width_of_the_box"),
    ]
    rendered = _render(lines).split("\n")
    assert all(len(row) <= receipt.PRICING_LINE_WIDTH for row in rendered)
    truncated = [row for row in rendered if "..." in row]
    assert len(truncated) >= 2  # the long name row and the long reason; the excluded row no longer prints
    assert any(row.endswith(" 12.5 h") and len(row) == receipt.PRICING_LINE_WIDTH for row in truncated)
    assert any(row.startswith("Reason: a code nobody has seen before") and row.endswith("...") for row in rendered)


def test_a_decrease_prints_with_a_minus_and_lowers_the_total():
    lines = [_line(hours_each=Decimal("3.0")), _line(hours_each=Decimal("-2.0"), reason_code="over_billed")]
    rendered = _render(lines, target=_target("3.0", "187.50")).split("\n")
    assert "06/20 Belfor                       -2.0 h" in rendered
    assert "  paper supports less than billed," in rendered
    assert "Paper shows                         1.0 h" in rendered
    assert "Add to WO                          -2.0 h" in rendered
    assert "                                 -$125.00" in rendered


def test_an_order_without_a_sheet_row_says_so():
    rendered = _render([_line()], target=None).split("\n")
    assert "NetFacilities has (no sheet row)    0.0 h" in rendered
    assert "Add to WO                          +1.0 h" in rendered
    assert "no labor on the WO." in rendered


def test_one_paper_day_names_itself_in_the_heading():
    assert "Corrected labor record (paper 06/20):" in _render([_line(), _line(hours_each=Decimal("2.0"))]).split("\n")
    assert "Corrected labor record:" in _render(_sample_lines()).split("\n")


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


def test_a_week_placement_prints_the_monday_of_its_week_and_sorts_into_it():
    # Decision 13 generalised (user 2026-11-06): hours the weekly reports
    # placed print as "week of" that week's Monday, ahead of the week's days.
    lines = [_line(), _line(work_date=None, date_basis=WEEK_PLACEMENT_BASIS, week=3, hours_each=Decimal("0.5"))]
    rendered = _render(lines).split("\n")
    assert rendered[8].startswith("week of 06/08 Belfor") and rendered[8].endswith(" 0.5 h")
    assert len(rendered[8]) == receipt.PRICING_LINE_WIDTH
    assert rendered[9].startswith("06/20 Belfor")


def test_a_line_removed_in_the_app_does_not_print():
    # User 2026-11-06: a removed line is a keying mistake, not paper. History
    # keeps it; the pasted text does not show it.
    removed = _line(status="excluded", exclusion_ground="removed", hours_each=Decimal("9.0"))
    assert _render(_sample_lines() + [removed]) == _render(_sample_lines())


def test_reason_text_falls_back_to_the_code_in_words():
    assert block.reason_text("crew_as_one") == "crew billed as one person"
    assert block.reason_text("as_read") == "hours as read on the paper"
    assert block.reason_text("some_new_code") == "some new code"
