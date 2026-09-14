"""The Admin weekly record of closed work orders.

Layer: services. Owns week resolution, the window, the row projection, and
the lazy freeze. The workbook (`work_order_report_xlsx.py`) and the JSON
route both render the `HubReportResponse` this module returns; neither
queries, so the file and the screen cannot disagree.

Spec: docs/superpowers/specs/2026-09-13-weekly-closed-report-design.md

Two things about this module are load-bearing:

**The closed response is the record (W4).** A completed week's closed rows
are stored as JSON and served back from the row on every later request.
`frozen_at` is filled from the row. New work orders are selected by
`created_at` on every request and are deliberately never stored (W14).

**Closed means `archived_at` inside the window (W3).** There is no status
history, so a restore clears `archived_at` and the live computation forgets
the close -- which is exactly why completed weeks are frozen (W5) rather
than recomputed.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.domain import labor_day
from app.domain import work_orders as wo
from app.domain.errors import ReportWeekError
from app.models import WorkOrder, WorkOrderReportWeek
from app.schemas.hub import HubReportResponse, HubReportRow

# Bumped when the stored JSON shape changes. Readers must keep accepting
# every earlier version; stored weeks are never rewritten (W13).
SCHEMA_VERSION = 1

STATUS_IN_PROGRESS = "in_progress"
STATUS_COMPLETED = "completed"
LIVE_NEW_WORK_ORDER_FIELDS = {"new_work_order_count", "new_work_order_rows"}


def resolve_week(week: Optional[date], now: datetime) -> date:
    """The Monday the request names, or the current Central week's (W7).

    Raises `ReportWeekError` (422) for a non-Monday or a week after the
    current one. The UI only ever sends Mondays; this is the API contract."""
    current = labor_day.week_bounds_containing(labor_day.central_date_of(now))[0]
    if week is None:
        return current
    if week.weekday() != 0:
        raise ReportWeekError("week must be a Monday (YYYY-MM-DD).")
    if week > current:
        raise ReportWeekError("week cannot be in the future.")
    return week


def week_window(week_start: date) -> tuple[datetime, datetime]:
    """UTC instants bracketing the Central week, half-open: Monday 00:00
    through the next Monday 00:00 (W1)."""
    start, _ = labor_day.day_bounds(week_start)
    _, end = labor_day.day_bounds(week_start + timedelta(days=6))
    return start, end


def is_completed(week_start: date, now: datetime) -> bool:
    """True from the first instant of the following Monday, Central (W2)."""
    _, end = week_window(week_start)
    return labor_day.as_utc(now) >= end


def row_sort_key(row: HubReportRow) -> tuple:
    """Tab order, then block order, then number: label case-insensitively
    (W8), community in `ALL_COMMUNITY_FILTERS` order (W9), number (W10)."""
    return (
        row.service_type_label.casefold(),
        wo.ALL_COMMUNITY_FILTERS.index(row.community),
        row.number,
    )


def new_work_order_sort_key(row: HubReportRow) -> tuple:
    """New Work Orders sheet order: community block, then number (W14)."""
    return (wo.ALL_COMMUNITY_FILTERS.index(row.community), row.number)


def _project_row(record) -> HubReportRow:
    return HubReportRow(
        work_order_id=record.id,
        number=record.number,
        assigned_to=record.vendor_assignee,
        location=record.location,
        service_type=record.service_type,
        service_type_label=wo.normalize_service_type(record.service_type)[1],
        community=wo.community_memberships(record.community, record.location)[0],
        schedule_date=record.schedule_date,
        priority=record.priority,
        archived_at=record.archived_at,
    )


def _report_columns() -> tuple:
    return (
        WorkOrder.id,
        WorkOrder.number,
        WorkOrder.vendor_assignee,
        WorkOrder.location,
        WorkOrder.service_type,
        WorkOrder.community,
        WorkOrder.schedule_date,
        WorkOrder.priority,
        WorkOrder.archived_at,
    )


def _closed_rows(db: Session, *, start: datetime, end: datetime) -> list[HubReportRow]:
    """Every work order archived within [start, end), columns only -- no
    eager loads, because the six columns are all on the row (W10)."""
    records = (
        db.query(*_report_columns())
        .filter(WorkOrder.archived_at >= start, WorkOrder.archived_at < end)
        .all()
    )
    rows = [_project_row(record) for record in records]
    rows.sort(key=row_sort_key)
    return rows


def _new_work_order_rows(
    db: Session, *, start: datetime, end: datetime
) -> list[HubReportRow]:
    """Every work order first created within [start, end), live on each
    request so completed records remain schema-version 1 (W14)."""
    records = (
        db.query(*_report_columns())
        .filter(WorkOrder.created_at >= start, WorkOrder.created_at < end)
        .all()
    )
    rows = [_project_row(record) for record in records]
    rows.sort(key=new_work_order_sort_key)
    return rows


def weekly_report(db: Session, *, week_start: date, now: datetime) -> HubReportResponse:
    """The week computed live from the database. `now` decides the status
    and stamps `generated_at`; it is injected so tests can freeze it."""
    start, end = week_window(week_start)
    rows = _closed_rows(db, start=start, end=end)
    new_work_order_rows = _new_work_order_rows(db, start=start, end=end)
    return HubReportResponse(
        week_start=week_start,
        week_end=week_start + timedelta(days=6),
        status=STATUS_COMPLETED if is_completed(week_start, now) else STATUS_IN_PROGRESS,
        generated_at=now,
        frozen_at=None,
        count=len(rows),
        rows=rows,
        new_work_order_count=len(new_work_order_rows),
        new_work_order_rows=new_work_order_rows,
    )


def report_for_week(db: Session, *, week_start: date, now: datetime) -> HubReportResponse:
    """The week's record: live while in progress, frozen once completed (W2,
    W5).

    On the first request after a week ends the live computation is stored
    with `ON CONFLICT DO NOTHING`, then re-read -- so two simultaneous first
    requests both serve the one row that won, and no request ever serves a
    computation that was not stored."""
    if not is_completed(week_start, now):
        return weekly_report(db, week_start=week_start, now=now)

    stored = db.get(WorkOrderReportWeek, week_start)
    new_work_order_rows = None
    if stored is None:
        payload = weekly_report(db, week_start=week_start, now=now)
        new_work_order_rows = payload.new_work_order_rows
        db.execute(
            insert(WorkOrderReportWeek)
            .values(
                week_start=week_start,
                schema_version=SCHEMA_VERSION,
                payload=json.loads(
                    payload.model_dump_json(exclude=LIVE_NEW_WORK_ORDER_FIELDS)
                ),
            )
            .on_conflict_do_nothing(index_elements=["week_start"])
        )
        db.commit()
        stored = db.get(WorkOrderReportWeek, week_start)

    if new_work_order_rows is None:
        start, end = week_window(week_start)
        new_work_order_rows = _new_work_order_rows(db, start=start, end=end)

    return HubReportResponse.model_validate(stored.payload).model_copy(
        update={
            "frozen_at": stored.frozen_at,
            "new_work_order_count": len(new_work_order_rows),
            "new_work_order_rows": new_work_order_rows,
        }
    )
