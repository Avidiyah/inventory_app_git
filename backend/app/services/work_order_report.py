"""The Admin daily report: what closed, what is closing, what arrived.

Layer: services. Owns the whole feature -- window derivation, the five section
queries, the row projection, and the CSV render -- so neither `services/hub.py`
nor `services/work_orders.py` (both long past the 500-line rule) grows a
surface that belongs to neither.

Spec: docs/superpowers/specs/2026-08-30-work-order-daily-report-design.md

Two things about this module are load-bearing:

**One payload, three renderers.** `daily_report` composes everything; the JSON
route validates it and `report_csv` renders it. Neither renderer queries. That
is what makes the screen and the file incapable of disagreeing (R9), including
when the `closing` cap bites (§7). The Excel workbook
(`work_order_report_xlsx.py`) renders the same payload plus its `distribution`
/ `all_rows`, computed here for the same reason.

**There is no status-history table.** So `closing` is a snapshot of current
state, not a delta, and a restore erases a close retroactively -- this is a
live view, not an archival record (§3). Do not "fix" either by inferring
history from `updated_at`.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload, selectinload

from app.domain import labor_day
from app.domain import work_orders as wo
from app.domain.list_limits import fetch_limit
from app.models import WorkOrder, WorkOrderItem
from app.services._list_cap import capped
from app.services.work_order_report_buckets import (
    BUCKET_KEYS,
    ReportDistribution,
    distribution,
    row_bucket,
)
from app.services.work_orders import export_row, work_order_totals

# Lifecycle order, not alphabetical: this is the order the `closing` section
# sorts by and the order an Admin reads the pipeline in.
CLOSING_STATUSES: tuple[str, ...] = (
    wo.STATUS_READY_TO_COMPLETE,
    wo.STATUS_COMPLETED,
    wo.STATUS_REVIEW,
)

# The CSV's fixed section order (§5). Also the order the page renders.
SECTION_ORDER: tuple[str, ...] = (
    "closed_today",
    "closed_week",
    "closing",
    "new_today",
    "new_week",
)

CSV_SECTION_HEADER = "SECTION"

# The page's own labels (`static/views/hubReport.js` STATUS_LABELS), so the
# workbook's STATUS column and the screen name a status the same way.
STATUS_LABELS: dict[str, str] = {
    wo.STATUS_CREATED: "Created",
    wo.STATUS_ASSIGNED: "Assigned",
    wo.STATUS_IN_PROGRESS: "In progress",
    wo.STATUS_ON_HOLD: "On hold",
    wo.STATUS_READY_TO_COMPLETE: "Ready to complete",
    wo.STATUS_COMPLETED: "Completed",
    wo.STATUS_REVIEW: "Review",
}


@dataclass(frozen=True)
class ReportRow:
    """One work order as the report shows it.

    `export_cells` is the row's 26 `EXPORT_HEADERS` values, rendered here so
    `report_csv` is a pure function of this payload (R9) without handing an ORM
    object to a renderer. It is deliberately absent from
    `schemas.hub.HubReportRow`, so it never reaches the JSON response."""

    work_order_id: UUID
    number: str
    # The row's `status` column as it stands. Archiving does not rewrite it, so
    # a closed row still reads `completed` or `review` -- the badge must not be
    # misread as "still open".
    status: str
    community: Optional[str]
    location: Optional[str]
    building_number: Optional[str]
    unit_number: Optional[str]
    service_type: Optional[str]
    priority: Optional[str]
    supervisor_name: Optional[str]
    technician_names: list[str]
    materials_total: Decimal
    labor_minutes: int
    labor_total: Decimal
    total: Decimal
    created_at: Optional[datetime]
    completed_at: Optional[datetime]
    archived_at: Optional[datetime]
    auto_closed: bool
    legacy: bool
    # Read by the workbook's Work Orders sheet (redesign E5); absent from
    # `schemas.hub.HubReportRow`, so neither reaches the JSON.
    notes: Optional[str] = None
    material_lines: int = 0
    export_cells: list = field(default_factory=list)


@dataclass(frozen=True)
class ClosedSection:
    count: int
    # Sweep closes in the window, left out of `count` and `rows`: how many the
    # section does not show, not a subset of what it does.
    auto_closed_count: int
    rows: list[ReportRow] = field(default_factory=list)


@dataclass(frozen=True)
class ClosingSection:
    count: int
    by_status: dict[str, int]
    truncated: bool
    rows: list[ReportRow] = field(default_factory=list)


@dataclass(frozen=True)
class NewSection:
    count: int
    rows: list[ReportRow] = field(default_factory=list)


@dataclass(frozen=True)
class ReportWeek:
    start: date
    end: date


@dataclass(frozen=True)
class ReportSections:
    closed_today: ClosedSection
    closed_week: ClosedSection
    closing: ClosingSection
    new_today: NewSection
    new_week: NewSection


@dataclass(frozen=True)
class DailyReport:
    generated_at: datetime
    day: date
    week: ReportWeek
    sections: ReportSections
    # The workbook's population (redesign E1): every live row plus every row
    # closed this week, in `reading_order`, and the four-bucket distribution
    # computed over exactly that list. Neither reaches the JSON response.
    distribution: ReportDistribution
    all_rows: list[ReportRow]


def _auto_closed(work_order: WorkOrder) -> bool:
    """Whether the NetFacilities reconcile sweep closed this row.

    Never true on a `closed_*` row -- `_closed_section` leaves those out. It
    survives on `new_*` rows, where the page's badge says what became of an
    arrival."""
    return work_order.auto_closed_batch_id is not None


def _base_query(db: Session):
    """Eager-load everything a row and its export cells read, so a section of N
    rows is a constant number of queries rather than 5N."""
    return db.query(WorkOrder).options(
        joinedload(WorkOrder.supervisor),
        selectinload(WorkOrder.technicians),
        selectinload(WorkOrder.items).joinedload(WorkOrderItem.item),
        selectinload(WorkOrder.labor_entries),
    )


def _row(work_order: WorkOrder) -> ReportRow:
    totals = work_order_totals(work_order)
    return ReportRow(
        work_order_id=work_order.id,
        number=work_order.number,
        status=work_order.status,
        community=work_order.community,
        location=work_order.location,
        building_number=work_order.building_number,
        unit_number=work_order.unit_number,
        service_type=work_order.service_type,
        priority=work_order.priority,
        supervisor_name=(
            work_order.supervisor.full_name if work_order.supervisor else None
        ),
        technician_names=[t.full_name for t in work_order.technicians],
        materials_total=totals.materials_total,
        labor_minutes=totals.labor_minutes,
        labor_total=totals.labor_total,
        total=totals.total,
        created_at=work_order.created_at,
        completed_at=work_order.completed_at,
        archived_at=work_order.archived_at,
        auto_closed=_auto_closed(work_order),
        legacy=bool(work_order.legacy),
        notes=work_order.notes,
        material_lines=len(work_order.items),
        export_cells=export_row(work_order),
    )


def _closed_section(db: Session, *, start: datetime, end: datetime) -> ClosedSection:
    """Rows a person archived within [start, end), newest close first.

    The NetFacilities reconcile sweep's closes are left out -- of `rows`, of
    `count`, and so of every figure computed from them -- and reported as
    `auto_closed_count`, so the Admin still sees how many tickets NetFacilities
    closed. This revises the spec's R10 ("a close is a close"): a sweep close
    is not the team's output, and mixing the two made Closed unreadable.

    Uncapped on purpose (§7): the window is the bound, and a report that
    silently omits closures while looking complete is a record-keeping problem,
    not a performance one -- the same reasoning that exempts the work-order
    export."""
    window = (WorkOrder.archived_at >= start, WorkOrder.archived_at < end)
    records = (
        _base_query(db)
        .filter(*window, WorkOrder.auto_closed_batch_id.is_(None))
        .order_by(WorkOrder.archived_at.desc())
        .all()
    )
    auto_closed_count = (
        db.query(func.count(WorkOrder.id))
        .filter(*window, WorkOrder.auto_closed_batch_id.is_not(None))
        .scalar()
    )
    rows = [_row(record) for record in records]
    return ClosedSection(
        count=len(rows),
        auto_closed_count=auto_closed_count or 0,
        rows=rows,
    )


def _new_section(db: Session, *, start: datetime, end: datetime) -> NewSection:
    """Rows created within [start, end), newest first. Uncapped for the same
    reason as `_closed_section`: the window is the bound."""
    records = (
        _base_query(db)
        .filter(WorkOrder.created_at >= start, WorkOrder.created_at < end)
        .order_by(WorkOrder.created_at.desc())
        .all()
    )
    rows = [_row(record) for record in records]
    return NewSection(count=len(rows), rows=rows)


def _closing_section(db: Session) -> ClosingSection:
    """Every live work order in a closing status, right now (R3).

    The only unbounded section, so the only capped one. `count` and `by_status`
    are separate aggregate queries rather than tallies over `rows`, so both stay
    true when the cap bites (§7)."""
    live = (WorkOrder.archived_at.is_(None), WorkOrder.status.in_(CLOSING_STATUSES))

    by_status = {
        status: count
        for status, count in db.query(WorkOrder.status, func.count())
        .filter(*live)
        .group_by(WorkOrder.status)
        .all()
    }
    count = sum(by_status.values())

    # SQL has no "order by this tuple's position", so sort in Python over a
    # bounded fetch: `fetch_limit()` is one more than the ceiling, which is what
    # makes truncation detectable without a second COUNT.
    records = _base_query(db).filter(*live).limit(fetch_limit()).all()
    records.sort(key=lambda r: (CLOSING_STATUSES.index(r.status), r.created_at))
    kept = capped(records, what="hub_report_closing")

    return ClosingSection(
        count=count,
        by_status=by_status,
        truncated=len(kept) < count,
        rows=[_row(record) for record in kept],
    )


def _live_rows(db: Session) -> list[ReportRow]:
    """Every non-archived work order, uncapped (redesign E4).

    The workbook's Work Orders sheet is a downloadable record; one that
    silently omitted rows while looking complete would be a record-keeping
    problem, not a performance one -- the reasoning that already exempts the
    `closed_*` and `new_*` sections from the cap. The on-screen `closing` list
    keeps its cap; the file does not."""
    records = _base_query(db).filter(WorkOrder.archived_at.is_(None)).all()
    return [_row(record) for record in records]


# Reading order for `all_rows` (redesign §4.3): Closed first, then the live
# buckets in reverse lifecycle order -- what came off the plate this week,
# then what is nearest to coming off it.
_BUCKET_RANK: dict[str, int] = {
    key: rank for rank, key in enumerate(reversed(BUCKET_KEYS))
}


def reading_order(row: ReportRow) -> tuple:
    """Sort key: bucket rank, then most recent close first, then number."""
    closed_at = (
        -labor_day.as_utc(row.archived_at).timestamp()
        if row.archived_at is not None
        else 0.0
    )
    return (_BUCKET_RANK[row_bucket(row)], closed_at, row.number)


def daily_report(db: Session, *, now: datetime) -> DailyReport:
    """The whole report for the Central day containing `now`.

    Parameterless by design (R1): the windows come from the clock, which is what
    makes this a daily report rather than a filter. `now` is injected so tests
    can freeze it."""
    today = labor_day.central_date_of(now)
    day_start, day_end = labor_day.day_bounds(today)
    week_start, week_end = labor_day.week_bounds_containing(today)
    week_start_at, _ = labor_day.day_bounds(week_start)

    # Today's upper bound is `day_end`, the week's is `now`: the week is
    # explicitly week-to-date, while the day stays a clean half-open Central
    # day. Nothing is stamped in the future, so the difference is immaterial.
    closed_week = _closed_section(db, start=week_start_at, end=now)
    # The one population (E1): everything live right now, plus everything
    # closed this week. Disjoint by construction -- a row is archived or it is
    # not -- so this is a union, not a merge, and it needs no dedup.
    all_rows = sorted([*_live_rows(db), *closed_week.rows], key=reading_order)
    return DailyReport(
        generated_at=now,
        day=today,
        week=ReportWeek(start=week_start, end=week_end),
        sections=ReportSections(
            closed_today=_closed_section(db, start=day_start, end=day_end),
            closed_week=closed_week,
            closing=_closing_section(db),
            new_today=_new_section(db, start=day_start, end=day_end),
            new_week=_new_section(db, start=week_start_at, end=now),
        ),
        distribution=distribution(all_rows),
        all_rows=all_rows,
    )


def _section_rows(payload: DailyReport, key: str) -> list[ReportRow]:
    return getattr(payload.sections, key).rows


def report_csv(payload: DailyReport) -> str:
    """The whole report as one `SECTION`-prefixed CSV.

    A pure render of `payload` -- no queries, no clock -- so the file can never
    disagree with the screen, cap included (R9, §7).

    **The 26 cells after `SECTION` are `export_row`'s, verbatim.** That is what
    keeps the file re-importable: `parse_import_row` reads its seven headers by
    name and ignores every other column, a column *before* them included. Do not
    add the R10 badge columns here -- `export_row` is shared with the operational
    export and its consumers (§10).

    **A row can appear twice**, under `closed_today` and `closed_week` (or the
    two `new_*` keys). That is the nesting (R1) made filterable: a spreadsheet
    narrows on `SECTION`, where the page uses a badge.

    **Timestamp seam, deliberate:** `export_row` writes UTC while the sections
    are Central calendar periods, so a row closed at 8 PM Central on the 30th
    sits in `closed_today` with an `ARCHIVED AT` cell reading the 31st. The
    covered day is in the filename, not the cells. Do not "fix" this by
    reformatting the shared export."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow((CSV_SECTION_HEADER,) + wo.EXPORT_HEADERS)
    for key in SECTION_ORDER:
        for row in _section_rows(payload, key):
            writer.writerow([key, *row.export_cells])
    return buffer.getvalue()


def report_filename(payload: DailyReport) -> str:
    """Named for the period it covers, not the moment of export -- the timesheet
    convention (user-hub-design.md D14). This report *is* the day, so the day is
    the name."""
    return f"wo-report_{payload.day.isoformat()}.csv"
