"""Vendor invoices and the weekly hours chart series (spec
docs/superpowers/specs/2026-11-06-smr-weekly-hours-chart-design.md, bars
redefined by the user 2026-11-06).

One bar per vendor (Green Choice, XXL, BT) per Mon-Sun week: the hours the
vendor invoiced, split into `original` (billed hours the paper supports: the
Breakdown target up to the order's paper hours), `found` (paper hours above
the target) and `missing` (the rest of the invoice), as the final report
counts them. Undated
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
FIGURES: tuple[str, ...] = ("original", "found", "undated", "invoiced", "carried")


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
    worker = (row.get("Worker") or "").strip() or None
    return {"invoice": invoice, "vendor": vendor, "worker": worker, "work_date": day, "week": rules.week_of(day), "hours": hours}


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


def _cell(cells: dict[tuple[Optional[int], str], dict[str, Decimal]], key: tuple[Optional[int], str]) -> dict[str, Decimal]:
    return cells.setdefault(key, {figure: Decimal(0) for figure in FIGURES})


def raw_cells(db: Session) -> dict[tuple[Optional[int], str], dict[str, Decimal]]:
    """Per (week, vendor) before the roll-forward: original / found / undated
    from the lines and targets, invoiced from the invoices."""
    cells: dict[tuple[Optional[int], str], dict[str, Decimal]] = {}
    cell = lambda key: _cell(cells, key)  # noqa: E731

    orders = (
        db.query(WorkOrder).filter(WorkOrder.smr_imported_at.isnot(None))
        .options(selectinload(WorkOrder.smr_lines)).all()
    )
    for order in orders:
        placed = [(slot, rules.line_hours(line)) for line in order.smr_lines if (slot := _slot(line)) is not None]
        for (slot, hours) in placed:
            cell(slot)["found" if slot[0] is not None else "undated"] += hours
        # The paper restates the billed hours: the order's target up to its
        # paper hours is `original` (already billed, now supported), paper
        # above the target is what the review `found`. Both follow the
        # lines pro rata, so original + found + undated = the paper.
        target = Decimal((order.smr_target or {}).get("hours") or 0)
        total = sum((hours for _, hours in placed), Decimal(0))
        if total > 0:
            original = min(target, total)
            for (slot, hours) in placed:
                share = hours / total
                cell(slot)["original"] += original * share
                cell(slot)["found" if slot[0] is not None else "undated"] -= original * share
    for row in db.query(SmrVendorInvoice).filter(SmrVendorInvoice.vendor.in_(CHART_VENDORS)).all():
        cell((row.week, row.vendor))["invoiced"] += Decimal(row.hours)
    return cells


def roll_forward(cells: dict[tuple[Optional[int], str], dict[str, Decimal]]) -> None:
    """A week never explains more than its invoice (user 2026-11-06). Hours
    above a vendor's invoice go to the next vendor that week (Green Choice ->
    XXL -> BT -> Green Choice); what no vendor absorbs carries into the next
    week, offered from Green Choice (ruling 12, user 2026-11-09). Hours land
    as `carried` (found leaves first, then original). Last-week excess no
    vendor absorbs stays on its own bar, above its invoice. In place."""
    vendors = CHART_VENDORS
    n = len(vendors)

    def room(figures) -> Decimal:
        return figures["invoiced"] - figures["original"] - figures["found"] - figures["carried"]

    def place(hours: Decimal, order) -> Decimal:
        for vendor in order:
            figures = cells.get((week, vendor))
            if figures is not None and hours > 0 and room(figures) > 0:
                give = min(hours, room(figures))
                figures["carried"] += give
                hours -= give
        return hours

    carry = Decimal(0)
    for week in range(1, rules.LAST_WEEK + 1):
        carry = place(carry, vendors)  # last week's leftover, offered from Green Choice
        excess: dict[str, Decimal] = {}
        taken: dict[str, dict[str, Decimal]] = {}
        for vendor in vendors:
            figures = cells.get((week, vendor))
            over = figures["original"] + figures["found"] - figures["invoiced"] if figures else Decimal(0)
            if over > 0:
                excess[vendor], taken[vendor] = over, {}
                for key in ("found", "original"):
                    taken[vendor][key] = take = min(figures[key], over)
                    figures[key] -= take
                    over -= take
        for i, vendor in enumerate(vendors):
            if vendor in excess:
                excess[vendor] = place(excess[vendor], [vendors[(i + j) % n] for j in range(1, n)])
        if week < rules.LAST_WEEK:
            carry += sum(excess.values(), Decimal(0))
            continue
        for vendor, hours in excess.items():  # nowhere left: back on its own bar, original first
            for key in ("original", "found"):
                back = min(hours, taken[vendor][key])
                cells[(week, vendor)][key] += back
                hours -= back
        if carry:  # earlier weeks' leftover sits on Green Choice's last bar
            _cell(cells, (week, vendors[0]))["carried"] += carry


def weekly_hours(db: Session) -> SmrWeeklyHoursOut:
    cells = raw_cells(db)
    roll_forward(cells)
    out = [
        SmrWeeklyCell(
            week=week, week_label=rules.week_label(week), vendor=vendor,
            missing=max(figures["invoiced"] - figures["original"] - figures["found"] - figures["carried"], Decimal(0)),
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


# --- names from the invoices (user 2026-11-06) -------------------------------

NAMED_VENDORS: tuple[str, ...] = ("Green Choice", "XXL Construction")  # BT invoices carry classes, not names


def _invoice_name(worker: Optional[str]) -> Optional[str]:
    """`Chris Bryan (REG)` -> `Chris Bryan`; None stays None."""
    if not worker:
        return None
    return worker.split(" (")[0].strip() or None


def fill_invoice_names(db: Session, *, user: User, tag: str, dry_run: bool = False) -> dict:
    """Give each generic vendor-crew line (no worker) the invoiced name with
    the most unused hours in that week. Room = the name's invoiced hours in
    the week minus hours already on lines naming that person there. A line
    of headcount N is N units; a unit is named only when a name has room for
    its whole hours_each, as a new single line; the original keeps the
    unnamed units or is removed when none are left. Every write carries
    `tag` in its history so the run can be undone."""
    from app.models import SmrWorker
    from app.services.work_orders_smr_lines import _text, history, match_worker

    room: dict[tuple[int, str, str], Decimal] = {}
    for row in db.query(SmrVendorInvoice).filter(SmrVendorInvoice.vendor.in_(NAMED_VENDORS)).all():
        name = _invoice_name(row.worker)
        if name:
            key = (row.week, row.vendor, name)
            room[key] = room.get(key, Decimal(0)) + Decimal(row.hours)
    workers: dict[tuple[str, str], Optional[SmrWorker]] = {}
    for (week, vendor, name) in list(room):
        if (vendor, name) not in workers:
            wid = match_worker(db, name=name, vendor=vendor)
            workers[(vendor, name)] = db.get(SmrWorker, wid) if wid else None
    lines = (
        db.query(SmrLaborLine).filter(SmrLaborLine.status == rules.STATUS_CHARGED, SmrLaborLine.vendor.in_(NAMED_VENDORS),
                                      SmrLaborLine.week.isnot(None)).all()
    )
    by_worker = {w.id: (v, n) for (v, n), w in workers.items() if w is not None}
    for line in lines:
        if line.worker_id in by_worker:
            vendor, name = by_worker[line.worker_id]
            key = (line.week, vendor, name)
            room[key] = room.get(key, Decimal(0)) - rules.line_hours(line)

    now = datetime.now(timezone.utc)
    named: list[tuple[str, int, str, Decimal]] = []
    left: list[tuple[str, int, str, Decimal]] = []
    for line in sorted((l for l in lines if l.worker_id is None), key=lambda l: (l.week, -l.hours_each)):
        units = 0
        for _ in range(line.headcount):
            choices = [(h, key) for key, h in room.items() if key[0] == line.week and key[1] == line.vendor and h >= line.hours_each]
            if not choices:
                break
            hours, key = max(choices, key=lambda c: (c[0], c[1][2]))
            room[key] = hours - line.hours_each
            name = key[2]
            named.append((line.work_order.number, line.week, name, line.hours_each))
            units += 1
            if dry_run:
                continue
            worker = workers.get((line.vendor, name))
            if worker is None:
                worker = SmrWorker(display_name=name, vendor=line.vendor)
                db.add(worker)
                db.flush()
                workers[(line.vendor, name)] = worker
            new = SmrLaborLine(
                work_order_id=line.work_order_id, reading_id=line.reading_id, work_date=line.work_date, date_basis=line.date_basis,
                week=line.week, vendor=line.vendor, worker_id=worker.id, alias_on_paper=name, headcount=1, hours_each=line.hours_each,
                kind=line.kind, reason_code=line.reason_code, status=rules.STATUS_CHARGED, note=line.note,
                created_by_id=user.id, updated_by_id=user.id,
            )
            db.add(new)
            db.flush()
            history(db, line=new, actor=user, field="created", old=None, new=f"from line {line.id}", reason=tag, now=now)
        if units < line.headcount:
            left.append((line.work_order.number, line.week, line.vendor, rules.line_hours(line) - units * line.hours_each))
        if units and not dry_run:
            if units == line.headcount:
                history(db, line=line, actor=user, field="status", old=line.status, new=rules.STATUS_EXCLUDED, reason=tag, now=now)
                history(db, line=line, actor=user, field="exclusion_ground", old=None, new=rules.GROUND_REMOVED, reason=tag, now=now)
                line.status, line.exclusion_ground = rules.STATUS_EXCLUDED, rules.GROUND_REMOVED
            else:
                history(db, line=line, actor=user, field="headcount", old=_text(line.headcount), new=_text(line.headcount - units), reason=tag, now=now)
                line.headcount -= units
            line.updated_at, line.updated_by_id = now, user.id
    if not dry_run:
        db.commit()
    return {"named": named, "left": left}


def undo_invoice_names(db: Session, *, user: User, tag: str) -> int:
    """Put a `fill_invoice_names` run back: created lines are removed, the
    originals get their headcount / status back."""
    from app.models import SmrLineEdit
    from app.services.work_orders_smr_lines import history
    now = datetime.now(timezone.utc)
    edits = db.query(SmrLineEdit).filter(SmrLineEdit.reason == tag).all()
    touched = 0
    for edit in edits:
        line = db.get(SmrLaborLine, edit.line_id)
        if line is None:
            continue
        touched += 1
        if edit.field == "created":
            line.status, line.exclusion_ground = rules.STATUS_EXCLUDED, rules.GROUND_REMOVED
            history(db, line=line, actor=user, field="deleted", old=None, new=None, reason=f"undo {tag}", now=now)
        elif edit.field == "headcount":
            line.headcount = int(edit.old_value)
            history(db, line=line, actor=user, field="headcount", old=edit.new_value, new=edit.old_value, reason=f"undo {tag}", now=now)
        elif edit.field == "status":
            line.status, line.exclusion_ground = rules.STATUS_CHARGED, None
            history(db, line=line, actor=user, field="status", old=rules.STATUS_EXCLUDED, new=rules.STATUS_CHARGED, reason=f"undo {tag}", now=now)
        line.updated_at, line.updated_by_id = now, user.id
    db.commit()
    return touched
