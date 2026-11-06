"""The SMR27 correction block pasted into NetFacilities (spec
docs/superpowers/specs/2026-11-04-smr-paper-import-design.md, D4).

Layer: pure domain. One function renders the block an Admin copies into the
order's follow-up field, the way the receipt is pasted today, so it inherits
the receipt's contract: every line fits within 41 characters
(`receipt.PRICING_LINE_WIDTH`), because the destination hard-wraps at 42.
Every row goes through the receipt's own `pricing_amount_line` / `sanitise`,
which right-align the amount and truncate an over-long label with `...`.
`tests/test_smr_block.py` pins the output.

Shape: the version and date, the order, billed / corrected / change in hours
and the change in dollars; then each charged line with its reason on the
line below (the user wants the reason beside each charge; the width forbids
one line); then every excluded line with its ground under `Not charged:`,
because the auditor must see what was left out and why. A line removed in
the app is a keying mistake, not paper: history keeps it, the block does not
print it (user 2026-11-06).
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from app.domain import receipt
from app.domain import work_orders as wo
from app.domain.work_orders_smr_lines import (
    GROUND_REMOVED,
    STATUS_CHARGED,
    WEEK1_START,
    line_hours,
    lines_charge,
)

WIDTH = receipt.PRICING_LINE_WIDTH

# The reason printed under a charge, by reason code. An unknown code prints
# as its own words with the underscores dropped.
REASON_TEXT: dict[str, str] = {
    "as_read": "hours as read on the paper",
    "crew_as_one": "crew billed as one person",
    "crew_as_individuals": "crew members added up, over-counted",
    "arithmetic": "paper total was wrong; lines as read",
    "overhead_added": "overhead added, label only",
    "overhead_twice": "overhead keyed twice, counted once",
    "accurate": "billed accurately; who and when",
    "over_billed": "paper supports less than billed",
    "not_on_paper": "paper names no one or no hours",
    "unit_mismatch": "unit differs: app, sheet and paper",
    "date_found": "date found on undated paper",
    "manual_check": "checked by hand against the paper",
    "awaiting_invoice": "awaiting the vendor invoice",
    "belfor_only": "Belfor hours only",
    "time_gap": "time gap on the paper",
    "held_out": "held out of the week",
    "hours_on_paper_above_billed": "paper hours above billed",
}
# Named workers carry their vendor in short form after the name.
VENDOR_SHORT: dict[str, str] = {
    "Green Choice": "GC", "XXL Construction": "XXL", "BT Restoration": "BT",
}
# Long grounds in the width they have under `Not charged:`.
GROUND_SHORT: dict[str, str] = {
    "after 07/12 (no invoices)": "after 07/12",
    "awaiting invoice (GC, Week 7)": "awaiting invoice",
    "reprint (no hours added)": "reprint",
    "read, not charged (user)": "not charged (user)",
    "read, not charged (weekly reports)": "not charged (reports)",
}
FOOTER = "Paper on file. Reasons under each line."


def reason_text(code: str) -> str:
    return REASON_TEXT.get(code) or (code or "").replace("_", " ")


def _row(label: str, amount: str) -> str:
    """Label left, amount right, always a gap between them, never past the width."""
    return receipt.pricing_amount_line(label, " " + amount)


def _fit(text: str) -> str:
    """A label-only line, sanitised and cut to the width like a label is."""
    return receipt.pricing_amount_line(text, "").rstrip()


def _hours(value: Decimal, *, signed: bool = False) -> str:
    value = Decimal(value)
    return f"{value:+.1f} h" if signed else f"{value:.1f} h"


def _monday(week: int) -> date:
    return WEEK1_START + timedelta(weeks=week - 1)


def _day(line) -> str:
    """The day, or "week of <Monday>" for a placement (decision 13), or undated."""
    if line.work_date is not None:
        return line.work_date.strftime("%m/%d")
    if line.week:
        return "week of " + _monday(line.week).strftime("%m/%d")
    return "undated"


def worker_name(line) -> Optional[str]:
    worker = getattr(line, "worker", None)
    return getattr(worker, "display_name", None) if worker is not None else None


def _who(line) -> str:
    name = worker_name(line)
    who = f"{name} ({VENDOR_SHORT.get(line.vendor, line.vendor)})" if name else line.vendor
    if line.headcount > 1:
        who += f" x{line.headcount}"
    if line.kind and line.kind != "field":
        who += f" {line.kind}"
    return who


def _sort_key(line):
    day = line.work_date or (_monday(line.week) if line.week else date.max)
    return (day, _who(line))


def _charged_rows(line) -> list[str]:
    amount = _hours(line.hours_each) + (" each" if line.headcount > 1 else "")
    return [_row(f"{_day(line)} {_who(line)}", amount), _fit("  " + reason_text(line.reason_code))]


def _excluded_row(line) -> str:
    ground = GROUND_SHORT.get(line.exclusion_ground or "", line.exclusion_ground or "")
    return _row(f"  {ground}  {_who(line)}", _hours(line_hours(line)))


def render_correction_block(order_number: str, target_hours: Optional[Decimal], lines, version: int,
                            generated_on: date) -> str:
    """The block for one order from its current lines. `target_hours` is the
    Breakdown figure NetFacilities billed (D6); None when the order has no
    sheet row, which the block says."""
    lines = list(lines)
    charge = lines_charge(lines)
    billed = Decimal(target_hours) if target_hours is not None else Decimal(0)
    change = charge.charged_hours - billed
    out = [
        _row(f"SMR27 LABOR CORRECTION v{version}", generated_on.strftime("%m/%d/%y")),
        _fit(f"WO {order_number}"),
        _row("Billed in NetFacilities" if target_hours is not None else "Billed (no sheet row)", _hours(billed)),
        _row("Corrected", _hours(charge.charged_hours)),
        _row("Change", _hours(change, signed=True)),
        _row("", receipt.format_money(change * wo.LABOR_RATE)),
        "",
    ]
    shown = [l for l in lines if l.exclusion_ground != GROUND_REMOVED]
    charged = sorted((l for l in shown if l.status == STATUS_CHARGED), key=_sort_key)
    excluded = sorted((l for l in shown if l.status != STATUS_CHARGED), key=_sort_key)
    for line in charged:
        out += _charged_rows(line)
    if excluded:
        out += ["", "Not charged:"] + [_excluded_row(line) for line in excluded]
    out += ["", _fit(FOOTER)]
    return "\n".join(out)


def _digest_row(line) -> list:
    return [
        str(line.work_date or ""), line.date_basis, str(line.week or ""), line.vendor, worker_name(line) or "",
        int(line.headcount), str(Decimal(line.hours_each)), line.kind, line.reason_code,
        line.status, line.exclusion_ground or "",
    ]


def lines_digest(lines) -> str:
    """sha256 over the charged and excluded lines in a stable order, so a
    block rendered earlier can be told apart from one the current lines
    would produce."""
    rows = sorted(_digest_row(line) for line in lines)
    return hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode("utf-8")).hexdigest()
