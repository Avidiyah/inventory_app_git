"""The SMR27 correction block pasted into NetFacilities (spec
docs/superpowers/specs/2026-11-04-smr-paper-import-design.md, D4).

Layer: pure domain. One function renders the block an Admin copies into the
order's follow-up field, the way the receipt is pasted today, so it inherits
the receipt's contract: every line fits within 41 characters
(`receipt.PRICING_LINE_WIDTH`), because the destination hard-wraps at 42.
Every row goes through the receipt's own `pricing_amount_line` / `sanitise`,
which right-align the amount and truncate an over-long label with `...`.
`tests/test_smr_block.py` pins the output.

Shape (user 2026-11-06, the TechFM correction memo): the date and the
order; the itemized receipt of the materials keyed on the card (headed
MATERIAL CORRECTION with the NetFacilities estimate when the totals
differ); what NetFacilities has (the Breakdown hours, labor type and
labor $), what the paper shows, and what to add to the WO in hours and
dollars; then the corrected labor record -- every charged line, name, day,
hours, kind; then one reason block naming the distinct reasons and what the
record replaces; the corrected WO total (materials at the marked-up charge
plus the corrected labor). Excluded lines do not print: only what is added to a work
order needs a justification, and the auditor reads the lines in the app.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal
from typing import Optional, Sequence

from app.domain import receipt
from app.domain import work_orders as wo
from app.domain.work_orders_smr_lines import (
    GROUND_REMOVED,
    STATUS_CHARGED,
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
FOOTER = "Paper on file."


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


def _day(line) -> str:
    """The SMR week the line bills in (user 2026-11-06: the memo points at
    the week's vendor invoice, not a day), or undated."""
    return f"Week {line.week}" if line.week else "undated"


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
    return (line.week or 99, line.work_date or date.max, _who(line))


def _charged_row(line) -> str:
    amount = _hours(line.hours_each) + (" each" if line.headcount > 1 else "")
    return _row(f"{_day(line)} {_who(line)}", amount)


def _has(target: Optional[dict]) -> tuple[Decimal, str]:
    """What NetFacilities has: the Breakdown hours, and the amount text with
    the labor type and labor dollars when the sheet row carries them."""
    if not target:
        return Decimal(0), _hours(Decimal(0))
    hours = Decimal(target["hours"])
    source = target.get("source_row") or {}
    kind = (source.get("Labor Type") or "").strip()
    money = target.get("labor_total")
    text = _hours(hours) + (f" {kind}" if kind else "") + (f"  ${Decimal(money):,.2f}" if money else "")
    return hours, text


def _paper_days(charged) -> str:
    weeks = sorted({l.week for l in charged if l.week})
    return f" (SMR Week {weeks[0]})" if len(weeks) == 1 else ""


def _materials_rows(materials: Sequence[receipt.ReceiptLine], target: Optional[dict]) -> tuple[list[str], Decimal]:
    """The itemized receipt above the labor (user 2026-11-06): each material
    at the marked-up charge, like the work-order receipt, and its total.
    When that total differs from what NetFacilities estimated, the section
    opens as a MATERIAL CORRECTION naming the NetFacilities figure."""
    rows, total = [], Decimal(0)
    for line in materials:
        quantity = receipt.effective_billable(line)
        charge = receipt.marked_material_charge(line)
        if charge is None:
            rows.append(receipt.pricing_line(receipt.format_quantity(quantity), line.name, "NO PRICE"))
            continue
        total += charge
        rows.append(receipt.pricing_line(receipt.format_quantity(quantity), line.name, receipt.format_money(charge)))
    estimated = Decimal(target["materials_total"]) if target and target.get("materials_total") is not None else None
    head = []
    if estimated is not None and receipt.format_money(estimated) != receipt.format_money(total):
        head = [_fit("MATERIAL CORRECTION"), _row("Original estimated total", receipt.format_money(estimated))]
    body = rows or [_fit("  (no materials keyed)")]
    return head + [_fit("ITEMIZED RECEIPT")] + body + [_row("Materials", receipt.format_money(total))], total


def render_correction_block(order_number: str, target: Optional[dict], lines, version: int,
                            generated_on: date, materials: Sequence[receipt.ReceiptLine] = ()) -> str:
    """The block for one order from its current lines and materials.
    `target` is the order's `smr_target` (the Breakdown row NetFacilities
    billed, D6); None when the order has no sheet row, which the block says."""
    lines = list(lines)
    charge = lines_charge(lines)
    billed, has = _has(target)
    change = charge.charged_hours - billed
    charged = sorted((l for l in lines if l.status == STATUS_CHARGED and l.exclusion_ground != GROUND_REMOVED),
                     key=_sort_key)
    material_rows, materials_total = _materials_rows(materials, target)
    out = [
        _row("SMR27 LABOR CORRECTION", generated_on.strftime("%m/%d/%y")),
        _fit(f"WO {order_number}"),
        "",
        *material_rows,
        "",
        _row("NetFacilities has" if target else "NetFacilities has (no sheet row)", has),
        _row("Paper shows", _hours(charge.charged_hours)),
        _row("Add to WO", _hours(change, signed=True)),
        _row("", receipt.format_money(change * wo.LABOR_RATE)),
        "",
        _fit(f"Corrected labor record{_paper_days(charged)}:"),
    ]
    out += [_charged_row(line) for line in charged] or [_fit("  (nothing charged)")]
    # User 2026-11-06: no Reason lines; a change is justified if asked.
    out += [
        "",
        _row("Labor total", receipt.format_money(charge.labor_total)),
        _row("Materials total", receipt.format_money(materials_total)),
        _row("Total", receipt.format_money(materials_total + charge.labor_total)),
        _fit(FOOTER),
    ]
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
