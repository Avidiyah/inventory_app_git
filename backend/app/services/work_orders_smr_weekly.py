"""Vendor invoices and the weekly hours chart series (spec
docs/superpowers/specs/2026-11-06-smr-weekly-hours-chart-design.md, bars
redefined by the user 2026-11-06).

One bar per vendor (Green Choice, XXL, BT) per Mon-Sun week: the hours the
vendor invoiced, split into `original` (the Breakdown sheet's billed hours,
i.e. the NetFacilities charge before any audit), `found` (charged paper
hours worked that week) and `missing` (the rest of the invoice). Undated
paper hours have no week; they sit in a trailing Undated column
(`week = None`) with the original hours of the orders they belong to.
An order's original hours follow its paper lines, pro rata by hours.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session, selectinload

from app.domain import work_orders_smr_lines as rules
from app.domain.errors import WorkOrderStateError
from app.models import SmrLaborLine, SmrVendorInvoice, User, WorkOrder
from app.schemas.work_orders_smr_lines import SmrInvoiceImportResult, SmrWeeklyCell, SmrWeeklyHoursOut
from app.services import work_orders_smr as smr_service

INVOICE_HEADERS: tuple[str, ...] = ("Invoice", "Date", "Vendor", "Hours")
CHART_VENDORS: tuple[str, ...] = ("Green Choice", "XXL Construction", "BT Restoration")
FIGURES: tuple[str, ...] = ("original", "found", "undated", "invoiced")


def _parse_invoice_row(index: int, row: dict) -> dict:
    where = f"Row {index}"
    invoice = (row.get("Invoice") or "").strip()
    vendor = (row.get("Vendor") or "").strip()
    if not invoice:
        raise WorkOrderStateError(f"{where}: Invoice is blank.")
    if vendor not in rules.VENDORS:
        raise WorkOrderStateError(f"{where}: unknown vendor {vendor!r}.")
    day = rules.parse_date((row.get("Date") or "").strip() or None, where=where)
    if day is None:
        raise WorkOrderStateError(f"{where}: Date is blank.")
    try:
        hours = Decimal((row.get("Hours") or "").strip())
    except ArithmeticError as exc:
        raise WorkOrderStateError(f"{where}: Hours {row.get('Hours')!r} is not a number.") from exc
    if hours <= 0:
        raise WorkOrderStateError(f"{where}: Hours must be above zero.")
    return {"invoice": invoice, "vendor": vendor, "work_date": day, "week": rules.week_of(day), "hours": hours}


def import_invoices(db: Session, *, csv_bytes: bytes, user: User) -> SmrInvoiceImportResult:
    """Load vendor invoice labor lines (Owner). Every row parses before the
    first write; the invoices the file names lose their earlier rows, so a
    re-upload replaces rather than doubles."""
    rows = [
        _parse_invoice_row(index, row)
        for index, row in enumerate(smr_service._read_sheet(csv_bytes, required=INVOICE_HEADERS), start=2)
    ]
    invoices = sorted({row["invoice"] for row in rows})
    now = datetime.now(timezone.utc)
    if invoices:
        db.query(SmrVendorInvoice).filter(SmrVendorInvoice.invoice.in_(invoices)).delete(synchronize_session=False)
    db.add_all(SmrVendorInvoice(**row, uploaded_at=now, uploaded_by_id=user.id) for row in rows)
    db.commit()
    return SmrInvoiceImportResult(
        total=len(rows), invoices=invoices, hours=sum((row["hours"] for row in rows), Decimal(0)),
    )


def _slot(line: SmrLaborLine) -> Optional[tuple[Optional[int], str]]:
    """The (week, vendor) a line's hours land in: a charged line in its week,
    an undated line in the Undated column; anything else is off the chart."""
    if line.vendor not in CHART_VENDORS:
        return None
    if line.status == rules.STATUS_CHARGED and line.week is not None:
        return (line.week, line.vendor)
    if line.status == rules.STATUS_EXCLUDED and line.exclusion_ground == rules.GROUND_UNDATED:
        return (None, line.vendor)
    return None


def weekly_hours(db: Session) -> SmrWeeklyHoursOut:
    cells: dict[tuple[Optional[int], str], dict[str, Decimal]] = {}

    def cell(key: tuple[Optional[int], str]) -> dict[str, Decimal]:
        return cells.setdefault(key, {figure: Decimal(0) for figure in FIGURES})

    orders = (
        db.query(WorkOrder).filter(WorkOrder.smr_imported_at.isnot(None))
        .options(selectinload(WorkOrder.smr_lines)).all()
    )
    for order in orders:
        placed = [(slot, rules.line_hours(line)) for line in order.smr_lines if (slot := _slot(line)) is not None]
        for (slot, hours) in placed:
            cell(slot)["found" if slot[0] is not None else "undated"] += hours
        original = Decimal((order.smr_target or {}).get("hours") or 0)
        total = sum((hours for _, hours in placed), Decimal(0))
        if original and total > 0:
            for (slot, hours) in placed:
                cell(slot)["original"] += original * hours / total
    for row in db.query(SmrVendorInvoice).filter(SmrVendorInvoice.vendor.in_(CHART_VENDORS)).all():
        cell((row.week, row.vendor))["invoiced"] += Decimal(row.hours)

    out = [
        SmrWeeklyCell(
            week=week, week_label=rules.week_label(week), vendor=vendor,
            missing=max(figures["invoiced"] - figures["original"] - figures["found"], Decimal(0)),
            **{figure: value.quantize(Decimal("0.1")) for figure, value in figures.items()},
        )
        for (week, vendor), figures in cells.items()
        if any(figures.values())
    ]
    order = {name: index for index, name in enumerate(CHART_VENDORS)}
    out.sort(key=lambda c: (c.week is None, c.week or 0, order[c.vendor]))
    weeks = sorted({c.week for c in out if c.week is not None})
    if any(c.week is None for c in out):
        weeks.append(None)
    return SmrWeeklyHoursOut(weeks=weeks, vendors=list(CHART_VENDORS), cells=out)
