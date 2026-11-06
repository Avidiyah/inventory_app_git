"""Vendor invoices and the weekly hours chart series (spec
docs/superpowers/specs/2026-11-06-smr-weekly-hours-chart-design.md).

Per Mon-Sun week and vendor: `original` is the NetFacilities baseline billed
hours of the SMR orders closed that week, `added` the charged paper hours
worked that week, `invoiced` the vendor's invoiced hours, `missing` the part
of the invoice no order carries yet. Weeks are the paper-line week numbers
(`rules.week_of`), None for an order with no close date.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.domain import work_orders_smr_lines as rules
from app.domain.errors import WorkOrderStateError
from app.models import SmrLaborLine, SmrVendorInvoice, SmrWorker, User, WorkOrder
from app.schemas.work_orders_smr_lines import SmrInvoiceImportResult, SmrWeeklyCell, SmrWeeklyHoursOut
from app.services import work_orders_smr as smr_service

INVOICE_HEADERS: tuple[str, ...] = ("Invoice", "Date", "Vendor", "Hours")
UNKNOWN_VENDOR = "Unknown"


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


def _vendor_by_name(db: Session) -> dict[str, str]:
    names: dict[str, str] = {}
    for worker in db.query(SmrWorker).all():
        for name in (worker.display_name, *(worker.aliases or [])):
            names.setdefault(name.casefold(), worker.vendor)
    return names


def _baseline_hours(work_order: WorkOrder) -> Decimal:
    totals = (work_order.smr_baseline or {}).get("totals") or {}
    minutes = int(totals.get("real_billed_minutes") or 0) + int(totals.get("skilled_billed_minutes") or 0)
    return Decimal(minutes) / Decimal(60)


def weekly_hours(db: Session) -> SmrWeeklyHoursOut:
    cells: dict[tuple[Optional[int], str], dict[str, Decimal]] = {}

    def cell(week: Optional[int], vendor: str) -> dict[str, Decimal]:
        return cells.setdefault((week, vendor), {"original": Decimal(0), "added": Decimal(0), "invoiced": Decimal(0)})

    names = _vendor_by_name(db)
    for order in db.query(WorkOrder).filter(WorkOrder.smr_imported_at.isnot(None)).all():
        assignee = ((order.smr_baseline or {}).get("source_row") or {}).get("ASSIGNED TO") or ""
        vendor = names.get(assignee.strip().casefold(), UNKNOWN_VENDOR)
        cell(smr_service.closed_week_number(order), vendor)["original"] += _baseline_hours(order)
    for line in db.query(SmrLaborLine).filter(SmrLaborLine.status == rules.STATUS_CHARGED).all():
        cell(line.week, line.vendor)["added"] += rules.line_hours(line)
    for row in db.query(SmrVendorInvoice).all():
        cell(row.week, row.vendor)["invoiced"] += Decimal(row.hours)

    out = [
        SmrWeeklyCell(week=week, week_label=rules.week_label(week), vendor=vendor, **figures,
                      missing=max(figures["invoiced"] - figures["added"], Decimal(0)))
        for (week, vendor), figures in cells.items()
        if any(figures.values())
    ]
    order = {name: index for index, name in enumerate((*rules.VENDORS, UNKNOWN_VENDOR))}
    out.sort(key=lambda c: (c.week is None, c.week or 0, order.get(c.vendor, len(order))))
    weeks = sorted({c.week for c in out if c.week is not None})
    if any(c.week is None for c in out):
        weeks.append(None)
    vendors = sorted({c.vendor for c in out}, key=lambda v: order.get(v, len(order)))
    return SmrWeeklyHoursOut(weeks=weeks, vendors=vendors, cells=out)
