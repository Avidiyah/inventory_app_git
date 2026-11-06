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
    fields = dict(work_date=date(2026, 6, 20), date_basis="paper", vendor="Belfor", worker=None, headcount=1,
                  hours_each=Decimal("1.0"), kind="field", reason_code="accurate", status="charged",
                  exclusion_ground=None)
    fields.update(overrides)
    return NS(**fields)


def _sample_lines():
    return [
        _line(vendor="BT Restoration", headcount=2, hours_each=Decimal("3.0"), reason_code="crew_as_one"),
        _line(hours_each=Decimal("0.5"), kind="assessment", reason_code="overhead_added"),
        _line(work_date=date(2026, 6, 22), vendor="XXL Construction", worker=NS(display_name="Trinton Smith"),
              hours_each=Decimal("4.0"), reason_code="crew_as_one"),
        _line(work_date=None, date_basis=WEEK1_PLACEMENT_BASIS, headcount=3, hours_each=Decimal("2.0")),
        _line(work_date=None, vendor="Green Choice", worker=NS(display_name="Rye"), hours_each=Decimal("7.0"),
              status="excluded", exclusion_ground="undated", reason_code="not_on_paper"),
        _line(work_date=date(2026, 7, 15), vendor="Green Choice", headcount=4, hours_each=Decimal("24.0"),
              status="excluded", exclusion_ground="after 07/12 (no invoices)", reason_code="awaiting_invoice"),
    ]


def _render(lines, target=Decimal("10.0"), version=2):
    return block.render_correction_block("23281563", target, lines, version, date(2026, 11, 10))


def test_one_full_block_verbatim():
    # Dated charges in date order, a Week 1 placement first (decision 13:
    # "week of 05/25"), each reason on the line below, then what was left out
    # and why. The width is the destination's: it wraps at 42.
    assert _render(_sample_lines()) == "\n".join([
        "SMR27 LABOR CORRECTION v2        11/10/26",
        "WO 23281563",
        "Billed in NetFacilities            10.0 h",
        "Corrected                          16.5 h",
        "Change                             +6.5 h",
        "                                  $406.25",
        "",
        "week of 05/25 Belfor x3        2.0 h each",
        "  billed accurately; who and when",
        "06/20 BT Restoration x2        3.0 h each",
        "  crew billed as one person",
        "06/20 Belfor assessment             0.5 h",
        "  overhead added, label only",
        "06/22 Trinton Smith (XXL)           4.0 h",
        "  crew billed as one person",
        "",
        "Not charged:",
        "  after 07/12  Green Choice x4     96.0 h",
        "  undated  Rye (GC)                 7.0 h",
        "",
        "Paper on file. Reasons under each line.",
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
    assert len(truncated) >= 3
    assert any(row.endswith(" 12.5 h") and len(row) == receipt.PRICING_LINE_WIDTH for row in truncated)
    assert any(row.endswith(" 120.0 h") for row in truncated)
    assert "  a code nobody has seen before that r..." in rendered


def test_a_decrease_prints_with_a_minus_and_lowers_the_total():
    lines = [_line(hours_each=Decimal("3.0")), _line(hours_each=Decimal("-2.0"), reason_code="over_billed")]
    rendered = _render(lines, target=Decimal("3.0")).split("\n")
    assert "06/20 Belfor                       -2.0 h" in rendered
    assert "  paper supports less than billed" in rendered
    assert "Corrected                           1.0 h" in rendered
    assert "Change                             -2.0 h" in rendered
    assert "                                 -$125.00" in rendered


def test_an_order_without_a_sheet_row_says_so():
    rendered = _render([_line()], target=None).split("\n")
    assert "Billed (no sheet row)               0.0 h" in rendered
    assert "Change                             +1.0 h" in rendered
    assert "Not charged:" not in rendered


def test_excluded_lines_print_under_not_charged_with_their_ground():
    rendered = _render(_sample_lines()).split("\n")
    not_charged = rendered[rendered.index("Not charged:") + 1:]
    assert [row.split()[0] for row in not_charged if row.startswith("  ")] == ["after", "undated"]
    assert all("week of" in row or "/" in row or "undated" in row for row in not_charged if row.startswith("  "))


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


def test_reason_text_falls_back_to_the_code_in_words():
    assert block.reason_text("crew_as_one") == "crew billed as one person"
    assert block.reason_text("some_new_code") == "some new code"
