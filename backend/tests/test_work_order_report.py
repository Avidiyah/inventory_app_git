"""Service, CSV, and window tests for the Admin daily report.

Spec: docs/superpowers/specs/2026-08-30-work-order-daily-report-design.md

The `db` fixture rolls back, but it runs against a *developer* Postgres that
may already hold real work orders. Count assertions are therefore scoped to
rows the test created, or to a window no pre-existing row can fall into.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.domain import labor_day
from app.domain import work_orders as wo
from app.models import Item, User, WorkOrder, WorkOrderItem, WorkOrderLabor
from app.services import work_order_report
from app.services import work_orders as work_orders_service


def _user(db, role="technician"):
    user = User(
        username=f"u-{uuid.uuid4().hex[:8]}",
        first_name="Test",
        last_name=role.title(),
        password_hash="x",
        role=role,
    )
    db.add(user)
    db.commit()
    return user


def _work_order(db, **kwargs):
    """A work order with a unique number. Every column the report reads is
    settable; the defaults are a plain live row created 'now'."""
    fields = {
        "number": f"WO-{uuid.uuid4().hex[:10]}",
        "status": wo.STATUS_CREATED,
        "created_at": datetime.now(timezone.utc),
        "community": "Cedar Ridge",
        "location": "Bldg 3",
        "service_type": "Plumbing",
        "entry_mode": "dispense",
    }
    fields.update(kwargs)
    record = WorkOrder(id=uuid.uuid4(), **fields)
    db.add(record)
    db.commit()
    return record


def _priced_item(db, price):
    item = Item(
        id=uuid.uuid4(),
        barcode=f"bc-{uuid.uuid4().hex[:12]}",
        name=f"part-{uuid.uuid4().hex[:8]}",
        quantity=Decimal("100"),
        location="A1",
        price=price,
    )
    db.add(item)
    db.commit()
    return item


def _add_material(db, order, item, quantity):
    db.add(
        WorkOrderItem(
            id=uuid.uuid4(),
            work_order_id=order.id,
            item_id=item.id,
            quantity=Decimal(quantity),
            mode="dispense",
        )
    )
    db.commit()


def _add_labor(db, order, minutes, technician=None):
    technician = technician or _user(db)
    db.add(
        WorkOrderLabor(
            id=uuid.uuid4(),
            work_order_id=order.id,
            technician_id=technician.id,
            minutes=minutes,
        )
    )
    db.commit()


def test_work_order_totals_matches_the_export_rows_money(db):
    item = _priced_item(db, Decimal("10.00"))
    order = _work_order(db)
    _add_material(db, order, item, 3)
    _add_labor(db, order, 90)
    db.refresh(order)

    totals = work_orders_service.work_order_totals(order)
    row = work_orders_service.export_row(order)

    headers = list(wo.EXPORT_HEADERS)
    assert row[headers.index("MATERIALS TOTAL")] == f"{totals.materials_total:.2f}"
    assert row[headers.index("LABOR MINUTES")] == totals.labor_minutes
    assert row[headers.index("LABOR TOTAL")] == f"{totals.labor_total:.2f}"
    assert row[headers.index("TOTAL")] == f"{totals.total:.2f}"


def test_totals_sum_materials_and_labor(db):
    item = _priced_item(db, Decimal("10.00"))
    order = _work_order(db)
    _add_material(db, order, item, 2)
    _add_labor(db, order, 60)
    db.refresh(order)

    totals = work_orders_service.work_order_totals(order)

    assert totals.materials_total == Decimal("20.00")
    assert totals.labor_minutes == 60
    assert totals.labor_total == wo.labor_charge(60)
    assert totals.total == totals.materials_total + totals.labor_total


# --- window derivation (R1, §4) --------------------------------------------


def _central_noon(year, month, day):
    """A UTC instant that is unambiguously midday on that Central date.

    17:00 UTC is 12:00 CDT in summer and 11:00 CST in winter -- nowhere near
    either midnight boundary, so the Central date is never in question."""
    return datetime(year, month, day, 17, 0, tzinfo=timezone.utc)


def test_monday_reads_today_and_week_the_same(db):
    # 2026-08-24 is a Monday: This Week is week-to-date, so on Monday it is
    # exactly Today (R1).
    now = _central_noon(2026, 8, 24)
    day_start, _ = labor_day.day_bounds(labor_day.central_date_of(now))
    _work_order(
        db, archived_at=day_start + timedelta(hours=2), status=wo.STATUS_COMPLETED
    )

    payload = work_order_report.daily_report(db, now=now)

    assert payload.day.isoformat() == "2026-08-24"
    assert payload.week.start.isoformat() == "2026-08-24"
    assert payload.week.end.isoformat() == "2026-08-30"
    assert payload.sections.closed_today.count == payload.sections.closed_week.count


def test_tuesday_week_covers_monday_and_tuesday(db):
    # The spec's own worked example: 6 closed Monday, 6 more on Tuesday.
    now = _central_noon(2026, 8, 25)
    monday_start, _ = labor_day.day_bounds(
        labor_day.central_date_of(_central_noon(2026, 8, 24))
    )
    tuesday_start, _ = labor_day.day_bounds(labor_day.central_date_of(now))
    for _ in range(6):
        _work_order(
            db,
            archived_at=monday_start + timedelta(hours=3),
            status=wo.STATUS_COMPLETED,
        )
    for _ in range(6):
        _work_order(
            db,
            archived_at=tuesday_start + timedelta(hours=3),
            status=wo.STATUS_COMPLETED,
        )

    payload = work_order_report.daily_report(db, now=now)

    assert payload.sections.closed_today.count == 6
    assert payload.sections.closed_week.count == 12


def test_a_close_at_2330_central_lands_in_that_central_day(db):
    # 23:30 Central on the 25th is 04:30 UTC on the 26th. The section is a
    # Central day, so it belongs to the 25th.
    now = _central_noon(2026, 8, 25)
    _, day_end = labor_day.day_bounds(labor_day.central_date_of(now))
    order = _work_order(
        db, archived_at=day_end - timedelta(minutes=30), status=wo.STATUS_COMPLETED
    )

    payload = work_order_report.daily_report(db, now=now)

    assert [row.number for row in payload.sections.closed_today.rows] == [order.number]


@pytest.mark.parametrize("month,day", [(3, 8), (11, 1)])
def test_dst_weeks_produce_sane_bounds(db, month, day):
    # 2026-03-08 springs forward and 2026-11-01 falls back; each date's
    # Monday-Sunday week contains its own transition.
    now = _central_noon(2026, month, day)

    payload = work_order_report.daily_report(db, now=now)

    assert payload.week.start.weekday() == 0
    assert (payload.week.end - payload.week.start).days == 6
    week_start_at, _ = labor_day.day_bounds(payload.week.start)
    assert week_start_at < now


# --- sections (§4) ----------------------------------------------------------


def test_a_row_closed_today_is_in_both_closed_sections(db):
    now = _central_noon(2026, 8, 25)
    day_start, _ = labor_day.day_bounds(labor_day.central_date_of(now))
    order = _work_order(
        db, archived_at=day_start + timedelta(hours=1), status=wo.STATUS_COMPLETED
    )

    payload = work_order_report.daily_report(db, now=now)

    assert order.number in [row.number for row in payload.sections.closed_today.rows]
    assert order.number in [row.number for row in payload.sections.closed_week.rows]


def test_created_and_closed_today_appears_in_both_new_and_closed(db):
    now = _central_noon(2026, 8, 25)
    day_start, _ = labor_day.day_bounds(labor_day.central_date_of(now))
    stamp = day_start + timedelta(hours=1)
    order = _work_order(
        db, created_at=stamp, archived_at=stamp, status=wo.STATUS_COMPLETED
    )

    payload = work_order_report.daily_report(db, now=now)

    assert order.number in [row.number for row in payload.sections.new_today.rows]
    assert order.number in [row.number for row in payload.sections.closed_today.rows]


def test_closing_holds_exactly_the_three_live_statuses(db):
    now = _central_noon(2026, 8, 25)
    day_start, _ = labor_day.day_bounds(labor_day.central_date_of(now))
    wanted = {
        status: _work_order(db, status=status).number
        for status in (
            wo.STATUS_READY_TO_COMPLETE,
            wo.STATUS_COMPLETED,
            wo.STATUS_REVIEW,
        )
    }
    early = [
        _work_order(db, status=wo.STATUS_IN_PROGRESS).number,
        _work_order(db, status=wo.STATUS_ON_HOLD).number,
    ]
    archived = _work_order(  # archived: belongs to closed_*, never to closing
        db, status=wo.STATUS_REVIEW, archived_at=day_start + timedelta(hours=1)
    )

    payload = work_order_report.daily_report(db, now=now)
    numbers = {row.number for row in payload.sections.closing.rows}

    assert set(wanted.values()) <= numbers
    assert archived.number not in numbers
    assert not (set(early) & numbers)
    # Scoped to this test's rows: a developer database holds its own pipeline.
    for status in wanted:
        assert payload.sections.closing.by_status[status] >= 1


def test_closing_is_sorted_by_lifecycle_then_oldest_first(db):
    now = _central_noon(2026, 8, 25)
    base = now - timedelta(days=3)
    newer_ready = _work_order(
        db, status=wo.STATUS_READY_TO_COMPLETE, created_at=base + timedelta(hours=2)
    )
    older_ready = _work_order(db, status=wo.STATUS_READY_TO_COMPLETE, created_at=base)
    review = _work_order(db, status=wo.STATUS_REVIEW, created_at=base)
    completed = _work_order(db, status=wo.STATUS_COMPLETED, created_at=base)

    payload = work_order_report.daily_report(db, now=now)
    mine = {older_ready.number, newer_ready.number, completed.number, review.number}
    ordered = [
        row.number for row in payload.sections.closing.rows if row.number in mine
    ]

    assert ordered == [
        older_ready.number,
        newer_ready.number,
        completed.number,
        review.number,
    ]


def test_closed_sections_are_newest_close_first(db):
    now = _central_noon(2026, 8, 26)
    day_start, _ = labor_day.day_bounds(labor_day.central_date_of(now))
    older = _work_order(
        db, status=wo.STATUS_COMPLETED, archived_at=day_start + timedelta(hours=1)
    )
    newer = _work_order(
        db, status=wo.STATUS_COMPLETED, archived_at=day_start + timedelta(hours=5)
    )

    payload = work_order_report.daily_report(db, now=now)

    assert [row.number for row in payload.sections.closed_today.rows] == [
        newer.number,
        older.number,
    ]


def test_closing_truncation_caps_rows_but_not_counts(db, monkeypatch):
    # Lower the ceiling instead of building 5,001 rows -- `_list_cap` reads the
    # module at call time precisely so a test can do this.
    from app.domain import list_limits

    monkeypatch.setattr(list_limits, "MAX_LIST_ROWS", 2)
    now = _central_noon(2026, 8, 25)
    for _ in range(4):
        _work_order(db, status=wo.STATUS_REVIEW)

    payload = work_order_report.daily_report(db, now=now)

    assert payload.sections.closing.truncated is True
    assert len(payload.sections.closing.rows) == 2
    assert payload.sections.closing.count >= 4
    assert payload.sections.closing.by_status[wo.STATUS_REVIEW] >= 4


# --- R10 provenance ---------------------------------------------------------


def test_a_legacy_archived_row_is_flagged_and_a_hand_closed_one_is_not(db):
    now = _central_noon(2026, 8, 25)
    day_start, _ = labor_day.day_bounds(labor_day.central_date_of(now))
    _work_order(
        db,
        status=wo.STATUS_COMPLETED,
        legacy=True,
        archived_at=day_start + timedelta(hours=1),
    )
    _work_order(
        db,
        status=wo.STATUS_COMPLETED,
        legacy=False,
        archived_at=day_start + timedelta(hours=2),
    )

    payload = work_order_report.daily_report(db, now=now)
    flags = sorted(row.legacy for row in payload.sections.closed_today.rows)

    assert flags == [False, True]


def test_report_row_money_matches_export_row(db):
    now = _central_noon(2026, 8, 25)
    day_start, _ = labor_day.day_bounds(labor_day.central_date_of(now))
    item = _priced_item(db, Decimal("7.50"))
    order = _work_order(
        db, status=wo.STATUS_COMPLETED, archived_at=day_start + timedelta(hours=1)
    )
    _add_material(db, order, item, 4)
    _add_labor(db, order, 45)
    db.refresh(order)

    payload = work_order_report.daily_report(db, now=now)
    row = next(r for r in payload.sections.closed_today.rows if r.number == order.number)
    totals = work_orders_service.work_order_totals(order)

    assert (row.materials_total, row.labor_minutes, row.labor_total, row.total) == (
        totals.materials_total,
        totals.labor_minutes,
        totals.labor_total,
        totals.total,
    )


# --- CSV (§5) ---------------------------------------------------------------


def _parse_csv(text):
    return list(csv.reader(io.StringIO(text)))


def test_csv_header_is_section_plus_the_export_headers(db):
    now = _central_noon(2026, 8, 25)
    payload = work_order_report.daily_report(db, now=now)

    rows = _parse_csv(work_order_report.report_csv(payload))

    assert tuple(rows[0]) == ("SECTION",) + wo.EXPORT_HEADERS


def test_csv_writes_sections_in_the_fixed_order(db):
    now = _central_noon(2026, 8, 25)
    day_start, _ = labor_day.day_bounds(labor_day.central_date_of(now))
    _work_order(
        db,
        status=wo.STATUS_COMPLETED,
        created_at=day_start + timedelta(hours=1),
        archived_at=day_start + timedelta(hours=2),
    )
    _work_order(
        db, status=wo.STATUS_REVIEW, created_at=day_start + timedelta(hours=1)
    )

    rows = _parse_csv(
        work_order_report.report_csv(work_order_report.daily_report(db, now=now))
    )
    seen = []
    for row in rows[1:]:
        if not seen or seen[-1] != row[0]:
            seen.append(row[0])

    # Every section that appears does so once, in SECTION_ORDER's order.
    assert seen == [key for key in work_order_report.SECTION_ORDER if key in seen]
    assert len(seen) == len(set(seen))


def test_a_csv_rows_26_cells_are_export_rows_output(db):
    now = _central_noon(2026, 8, 25)
    day_start, _ = labor_day.day_bounds(labor_day.central_date_of(now))
    order = _work_order(
        db, status=wo.STATUS_COMPLETED, archived_at=day_start + timedelta(hours=1)
    )
    db.refresh(order)

    rows = _parse_csv(
        work_order_report.report_csv(work_order_report.daily_report(db, now=now))
    )
    written = next(
        r for r in rows[1:] if r[0] == "closed_today" and r[1] == order.number
    )
    expected = [str(cell) for cell in work_orders_service.export_row(order)]

    assert written[1:] == expected


def test_a_row_closed_today_is_written_under_both_closed_keys(db):
    # The nesting (R1) made filterable: the file carries the row twice, under
    # two SECTION values, because a spreadsheet filters on a column.
    now = _central_noon(2026, 8, 25)
    day_start, _ = labor_day.day_bounds(labor_day.central_date_of(now))
    order = _work_order(
        db, status=wo.STATUS_COMPLETED, archived_at=day_start + timedelta(hours=1)
    )

    rows = _parse_csv(
        work_order_report.report_csv(work_order_report.daily_report(db, now=now))
    )
    sections = {r[0] for r in rows[1:] if r[1] == order.number}

    assert {"closed_today", "closed_week"} <= sections


def test_the_report_csv_still_reimports(db):
    # The round-trip guarantee: `parse_import_row` reads its seven headers by
    # name, so a column *before* them must not break re-import.
    now = _central_noon(2026, 8, 25)
    day_start, _ = labor_day.day_bounds(labor_day.central_date_of(now))
    order = _work_order(
        db, status=wo.STATUS_COMPLETED, archived_at=day_start + timedelta(hours=1)
    )

    text = work_order_report.report_csv(
        work_order_report.daily_report(db, now=now)
    )
    parsed = [wo.parse_import_row(row) for row in csv.DictReader(io.StringIO(text))]
    mine = [entry for entry in parsed if entry["number"] == order.number]

    assert mine
    assert mine[0]["location"] == order.location
    assert mine[0]["service_type"] == order.service_type


def test_csv_uses_crlf_and_quotes_embedded_commas_and_newlines(db):
    now = _central_noon(2026, 8, 25)
    day_start, _ = labor_day.day_bounds(labor_day.central_date_of(now))
    _work_order(
        db,
        status=wo.STATUS_COMPLETED,
        archived_at=day_start + timedelta(hours=1),
        notes="one, two\nthree",
    )

    text = work_order_report.report_csv(
        work_order_report.daily_report(db, now=now)
    )

    assert text.endswith("\r\n")
    assert '"one, two\nthree"' in text
    assert len(_parse_csv(text)[0]) == len(wo.EXPORT_HEADERS) + 1


def test_filename_names_the_central_report_day(db):
    now = _central_noon(2026, 8, 25)
    payload = work_order_report.daily_report(db, now=now)

    assert work_order_report.report_filename(payload) == "wo-report_2026-08-25.csv"


# --- the E1 population (xlsx redesign spec §2.1, E1, E4) -------------------


def test_all_rows_is_live_plus_closed_this_week_and_nothing_else(db):
    now = _central_noon(2026, 8, 26)
    week_start_at, _ = labor_day.day_bounds(
        labor_day.central_date_of(_central_noon(2026, 8, 24))
    )
    live = _work_order(db, status=wo.STATUS_IN_PROGRESS)
    closed_this_week = _work_order(
        db, status=wo.STATUS_COMPLETED, archived_at=week_start_at + timedelta(hours=1)
    )
    closed_last_week = _work_order(
        db, status=wo.STATUS_COMPLETED, archived_at=week_start_at - timedelta(hours=1)
    )

    payload = work_order_report.daily_report(db, now=now)
    numbers = [row.number for row in payload.all_rows]

    assert live.number in numbers
    assert closed_this_week.number in numbers
    assert closed_last_week.number not in numbers
    assert len(numbers) == len(set(numbers))


def test_all_rows_reads_closed_first_then_the_live_buckets_in_reverse_lifecycle(db):
    now = _central_noon(2026, 8, 26)
    day_start, _ = labor_day.day_bounds(labor_day.central_date_of(now))
    older_close = _work_order(
        db, status=wo.STATUS_COMPLETED, archived_at=day_start + timedelta(hours=1)
    )
    newer_close = _work_order(
        db, status=wo.STATUS_COMPLETED, archived_at=day_start + timedelta(hours=2)
    )
    accepted = _work_order(db, status=wo.STATUS_CREATED)
    working = _work_order(db, status=wo.STATUS_ON_HOLD)
    ready = _work_order(db, status=wo.STATUS_REVIEW)
    mine = {r.number for r in (older_close, newer_close, accepted, working, ready)}

    payload = work_order_report.daily_report(db, now=now)
    ordered = [row.number for row in payload.all_rows if row.number in mine]

    assert ordered == [
        newer_close.number,
        older_close.number,
        ready.number,
        working.number,
        accepted.number,
    ]


def test_distribution_is_built_over_all_rows_and_rows_carry_notes(db):
    now = _central_noon(2026, 8, 26)
    day_start, _ = labor_day.day_bounds(labor_day.central_date_of(now))
    order = _work_order(
        db,
        status=wo.STATUS_COMPLETED,
        archived_at=day_start + timedelta(hours=1),
        notes="call first",
        community="Commons",
    )

    payload = work_order_report.daily_report(db, now=now)
    row = next(r for r in payload.all_rows if r.number == order.number)

    # Company Closed is closed_week by another name: same window, same rows.
    assert payload.distribution.company.counts["closed"] == payload.sections.closed_week.count
    assert payload.distribution.company.total == len(payload.all_rows)
    assert row.notes == "call first"
    assert row.material_lines == 0


def test_status_labels_cover_every_status_in_the_pages_spelling():
    assert [work_order_report.STATUS_LABELS[s] for s in wo.ALL_STATUSES] == [
        "Created",
        "Assigned",
        "In progress",
        "On hold",
        "Ready to complete",
        "Completed",
        "Review",
    ]


def test_reading_order_is_a_pure_sort_key():
    from datetime import datetime, timezone
    from decimal import Decimal
    from uuid import uuid4

    def row(number, status, archived_at=None):
        return work_order_report.ReportRow(
            work_order_id=uuid4(), number=number, status=status, community=None,
            location=None, building_number=None, unit_number=None, service_type=None,
            priority=None, supervisor_name=None, technician_names=[],
            materials_total=Decimal("0"), labor_minutes=0, labor_total=Decimal("0"),
            total=Decimal("0"), created_at=None, completed_at=None,
            archived_at=archived_at, legacy=False,
        )

    stamp = datetime(2026, 8, 25, 15, 0, tzinfo=timezone.utc)
    rows = [
        row("B-accepted", wo.STATUS_CREATED),
        row("A-accepted", wo.STATUS_CREATED),
        row("closed-older", wo.STATUS_REVIEW, stamp),
        row("closed-newer", wo.STATUS_COMPLETED, stamp + timedelta(hours=1)),
        row("working", wo.STATUS_ASSIGNED),
        row("ready", wo.STATUS_READY_TO_COMPLETE),
    ]

    assert [r.number for r in sorted(rows, key=work_order_report.reading_order)] == [
        "closed-newer",
        "closed-older",
        "ready",
        "working",
        "A-accepted",
        "B-accepted",
    ]
