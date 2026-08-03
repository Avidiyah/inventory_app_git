"""The Python receipt builder, pinned against its JavaScript twin.

`app/domain/receipt.py` is a port of `static/adminReviewReceipt.js` +
`static/pricingText.js`. Admin Review renders the receipt in the browser; the
"For Client" CSV export renders it on the server. They bill the same customer,
so these tests pin the exact characters -- width, alignment, truncation,
mark-up, rounding, and the incomplete-total wording. If the JS changes, these
fail and the port has to follow.

Layer: unit (no DB, no HTTP).
"""

import os
import sys
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.domain import receipt


def _line(name, quantity, unit_price, billable=None):
    return receipt.ReceiptLine(
        name=name,
        quantity=Decimal(quantity),
        billable_quantity=None if billable is None else Decimal(billable),
        unit_price=None if unit_price is None else Decimal(unit_price),
    )


# --- formatting primitives -----------------------------------------------

@pytest.mark.parametrize(
    "value,expected",
    [
        ("0", "$0.00"),
        ("2.5", "$2.50"),
        ("88.75", "$88.75"),
        ("1234.5", "$1,234.50"),
        ("1234567.891", "$1,234,567.89"),
        ("-5", "-$5.00"),
        # Half-cent rounds away from zero, as the browser displays it.
        ("2.345", "$2.35"),
    ],
)
def test_format_money_matches_the_browser(value, expected):
    assert receipt.format_money(Decimal(value)) == expected


@pytest.mark.parametrize(
    "value,expected",
    [("3.00", "3"), ("0.50", "0.5"), ("2.25", "2.25"), ("10", "10"), ("0", "0")],
)
def test_format_quantity_is_shortest_form(value, expected):
    assert receipt.format_quantity(Decimal(value)) == expected


@pytest.mark.parametrize(
    "minutes,expected",
    [(0, "0"), (30, "0.5"), (60, "1"), (90, "1.5"), (50, "0.83"), (150, "2.5")],
)
def test_billed_labor_hours(minutes, expected):
    assert receipt.billed_labor_hours(minutes) == expected


def test_lines_never_exceed_the_destination_width():
    # The company's receipt box hard-wraps at 42 characters.
    line = receipt.pricing_line("1", "A" * 80, "$1,000.00")
    assert len(line) == receipt.PRICING_LINE_WIDTH
    assert line.startswith("1 AAA")
    assert line.endswith("...$1,000.00")


def test_short_name_is_padded_so_amounts_stay_flush_right():
    line = receipt.pricing_line("2", "Caulk", "$23.00")
    assert len(line) == receipt.PRICING_LINE_WIDTH
    assert line == "2 Caulk" + " " * (receipt.PRICING_LINE_WIDTH - len("2 Caulk") - len("$23.00")) + "$23.00"


def test_total_line_is_right_aligned():
    line = receipt.pricing_amount_line("Total", "$88.75")
    assert len(line) == receipt.PRICING_LINE_WIDTH
    assert line.endswith("$88.75")
    assert line.startswith("Total ")


def test_tabs_and_newlines_collapse_to_one_space():
    # A multi-line item name would otherwise break the one-row-per-line
    # contract in the destination.
    assert receipt.sanitise("Spray\n\tPaint") == "Spray Paint"


# --- the receipt itself ---------------------------------------------------

def test_receipt_marks_materials_up_and_totals_with_labor():
    document = receipt.build_receipt(
        lines=[_line("Spray Paint", "4", "2.50")],  # 10.00 x 1.15 = 11.50
        labor_billed_minutes=30,
        labor_total=Decimal("31.25"),
    )

    assert document.missing_prices == ()
    assert document.text.splitlines() == [
        receipt.pricing_line("4", "Spray Paint", "$11.50"),
        receipt.pricing_line("[0.5]", "Labor Hours", "$31.25"),
        "",
        receipt.pricing_amount_line("Total", "$42.75"),
    ]


def test_receipt_charges_the_billable_override_not_the_quantity():
    document = receipt.build_receipt(
        lines=[_line("Spray Paint", "4", "2.50", billable="1")],
        labor_billed_minutes=0,
        labor_total=Decimal(0),
    )

    first = document.text.splitlines()[0]
    assert first.startswith("1 Spray Paint")  # the billable count, not 4
    assert first.endswith("$2.88")  # 1 x 2.50 x 1.15, rounded for display


def test_labor_is_not_marked_up():
    # Only materials carry the mark-up; labor is already priced by the rate.
    document = receipt.build_receipt(
        lines=[], labor_billed_minutes=60, labor_total=Decimal("62.50")
    )
    assert document.text.splitlines()[0].endswith("$62.50")
    assert document.text.splitlines()[-1].endswith("$62.50")


def test_unpriced_item_says_so_and_marks_the_total_incomplete():
    document = receipt.build_receipt(
        lines=[_line("Spray Paint", "4", "2.50"), _line("Mystery Part", "1", None)],
        labor_billed_minutes=30,
        labor_total=Decimal("31.25"),
    )

    assert document.missing_prices == ("Mystery Part",)
    lines = document.text.splitlines()
    assert lines[1].endswith("NO PRICE")
    # The total is real but understated, and the label says as much.
    assert lines[-1].startswith("Total (incomplete)")
    assert lines[-1].endswith("$42.75")


def test_receipt_with_no_materials_or_labor_still_totals_zero():
    document = receipt.build_receipt(
        lines=[], labor_billed_minutes=0, labor_total=Decimal(0)
    )
    assert document.text.splitlines()[-1].endswith("$0.00")
    assert document.missing_prices == ()
