"""Service tests for the weekly closed work order report: week resolution,
the window, the row projection, ordering, and the lazy freeze.

Spec: docs/superpowers/specs/2026-09-13-weekly-closed-report-design.md

The `db` fixture rolls back, but it runs against a *developer* Postgres that
may already hold real work orders. Every test here uses weeks in 1999, which
no real row can fall into, and cleans its own frozen rows.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from app.domain import labor_day
from app.domain import work_orders as wo
from app.domain.errors import ReportWeekError
from app.models import WorkOrder, WorkOrderReportWeek
from app.schemas.hub import HubReportResponse, HubReportRow
from app.services import work_order_report

# Mondays no real row can collide with.
WEEK = date(1999, 1, 4)
NEXT_WEEK = date(1999, 1, 11)
# A `now` inside WEEK (Wednesday noon Central) and one after it.
DURING = datetime(1999, 1, 6, 12, 0, tzinfo=labor_day.CENTRAL)
AFTER = datetime(1999, 1, 20, 12, 0, tzinfo=labor_day.CENTRAL)


def _central(*args) -> datetime:
    return datetime(*args, tzinfo=labor_day.CENTRAL)


def _work_order(db, **kwargs):
    """A closed work order inside WEEK unless told otherwise."""
    fields = {
        "number": f"WO-{uuid.uuid4().hex[:10]}",
        "status": wo.STATUS_COMPLETED,
        "created_at": _central(1999, 1, 4, 8, 0),
        "archived_at": _central(1999, 1, 6, 9, 0),
        "location": "Scholars 12-304",
        "service_type": "Maintenance",
        "vendor_assignee": "Belfor Dispatch",
        "priority": "Normal",
        "schedule_date": "1/5/1999",
        "entry_mode": "dispense",
    }
    fields.update(kwargs)
    record = WorkOrder(id=uuid.uuid4(), **fields)
    db.add(record)
    db.commit()
    return record


def _report(db, week_start=WEEK, now=DURING) -> HubReportResponse:
    return work_order_report.weekly_report(db, week_start=week_start, now=now)


def _numbers(payload: HubReportResponse) -> list[str]:
    return [row.number for row in payload.rows]


@pytest.fixture
def clean_frozen(db):
    for week in (WEEK, NEXT_WEEK):
        db.query(WorkOrderReportWeek).filter_by(week_start=week).delete()
    db.commit()
    yield
    for week in (WEEK, NEXT_WEEK):
        db.query(WorkOrderReportWeek).filter_by(week_start=week).delete()
    db.commit()


# --- resolve_week / week_window / is_completed --------------------------------


def test_resolve_week_defaults_to_the_current_central_monday():
    now = datetime(2026, 9, 10, 3, 0, tzinfo=timezone.utc)  # Wed 22:00 Central Tue 9th
    expected = labor_day.week_bounds_containing(labor_day.central_date_of(now))[0]

    assert work_order_report.resolve_week(None, now) == expected


def test_resolve_week_accepts_a_past_monday():
    assert work_order_report.resolve_week(WEEK, DURING) == WEEK


def test_resolve_week_rejects_a_non_monday():
    with pytest.raises(ReportWeekError, match="Monday"):
        work_order_report.resolve_week(date(1999, 1, 5), DURING)


def test_resolve_week_rejects_a_future_monday():
    with pytest.raises(ReportWeekError, match="future"):
        work_order_report.resolve_week(NEXT_WEEK, DURING)


def test_week_window_is_monday_midnight_to_next_monday_midnight_central():
    start, end = work_order_report.week_window(WEEK)

    assert start == labor_day.day_bounds(WEEK)[0]
    assert end == labor_day.day_bounds(WEEK + timedelta(days=6))[1]
    assert end == _central(1999, 1, 11, 0, 0).astimezone(timezone.utc)


def test_is_completed_flips_at_monday_midnight_central():
    assert not work_order_report.is_completed(WEEK, _central(1999, 1, 10, 23, 59, 59))
    assert work_order_report.is_completed(WEEK, _central(1999, 1, 11, 0, 0, 0))


# --- weekly_report: window edges and population --------------------------------


def test_window_edges_sunday_last_second_in_monday_first_second_out(db):
    last_second = _work_order(db, archived_at=_central(1999, 1, 10, 23, 59, 59))
    first_second = _work_order(db, archived_at=_central(1999, 1, 11, 0, 0, 0))

    this_week = _numbers(_report(db))
    next_week = _numbers(_report(db, week_start=NEXT_WEEK, now=AFTER))

    assert last_second.number in this_week
    assert first_second.number not in this_week
    assert first_second.number in next_week
    assert last_second.number not in next_week


def test_live_and_restored_rows_are_absent(db):
    live = _work_order(db, archived_at=None, status=wo.STATUS_CREATED)
    restored = _work_order(db)
    restored.archived_at = None
    db.commit()

    numbers = _numbers(_report(db))

    assert live.number not in numbers
    assert restored.number not in numbers


def test_count_status_and_frozen_at(db):
    _work_order(db)

    during = _report(db, now=DURING)
    after = _report(db, now=AFTER)

    assert during.count == len(during.rows) >= 1
    assert during.status == "in_progress"
    assert after.status == "completed"
    assert during.frozen_at is None and after.frozen_at is None
    assert during.week_start == WEEK
    assert during.week_end == date(1999, 1, 10)
    assert during.generated_at == DURING


# --- the row projection ----------------------------------------------------------


def test_row_carries_the_six_raw_columns_and_the_primary_community(db):
    order = _work_order(db, vendor_assignee="Hayden Hurst", priority="High")

    row = next(r for r in _report(db).rows if r.number == order.number)

    assert row.work_order_id == order.id
    assert row.assigned_to == "Hayden Hurst"
    assert row.location == "Scholars 12-304"
    assert row.service_type == "Maintenance"
    assert row.service_type_label == "Maintenance"
    assert row.community == "scholars"
    assert row.schedule_date == "1/5/1999"
    assert row.priority == "High"
    assert labor_day.as_utc(row.archived_at) == labor_day.as_utc(order.archived_at)


def test_service_type_label_is_normalised_and_blank_is_unspecified(db):
    padded = _work_order(db, service_type="  plumbing ")
    blank = _work_order(db, service_type=None)

    rows = {r.number: r for r in _report(db).rows}

    assert rows[padded.number].service_type == "  plumbing "
    assert rows[padded.number].service_type_label == "plumbing"
    assert rows[blank.number].service_type_label == "Unspecified"


def test_community_is_the_first_membership_with_academics_fallback(db):
    both = _work_order(db, location="Centennial lobby, near Scholars")
    none = _work_order(db, location="Somewhere else")

    rows = {r.number: r for r in _report(db).rows}
    expected_first = wo.community_memberships(None, both.location)[0]

    assert rows[both.number].community == expected_first
    assert expected_first == wo.ALL_COMMUNITY_FILTERS[
        min(wo.ALL_COMMUNITY_FILTERS.index(k) for k in ("centennial", "scholars"))
    ]
    assert rows[none.number].community == "academics"


def test_rows_sort_by_label_then_community_order_then_number(db):
    # Labels compare case-insensitively; communities in ALL_COMMUNITY_FILTERS
    # order; numbers last.
    b = _work_order(db, number="WO-1999-B", service_type="b", location="Scholars 1")
    a_academics = _work_order(db, number="WO-1999-A2", service_type="A", location="Nowhere")
    a_scholars_2 = _work_order(db, number="WO-1999-A1b", service_type="a", location="Scholars 2")
    a_scholars_1 = _work_order(db, number="WO-1999-A1a", service_type="a", location="Scholars 3")

    numbers = [n for n in _numbers(_report(db)) if n.startswith("WO-1999-")]

    assert numbers == [
        a_scholars_1.number,
        a_scholars_2.number,
        a_academics.number,
        b.number,
    ]


def test_row_sort_key_shape():
    row = HubReportRow(
        work_order_id=uuid.uuid4(),
        number="7",
        service_type_label="Maintenance",
        community="commons",
        archived_at=datetime(1999, 1, 6, tzinfo=timezone.utc),
    )

    assert work_order_report.row_sort_key(row) == (
        "maintenance",
        wo.ALL_COMMUNITY_FILTERS.index("commons"),
        "7",
    )


# --- the lazy freeze --------------------------------------------------------------


class TestFreeze:
    def _stored(self, db, week=WEEK):
        return db.query(WorkOrderReportWeek).filter_by(week_start=week).all()

    def test_first_request_for_a_completed_week_freezes_it(self, db, clean_frozen):
        _work_order(db)
        assert self._stored(db) == []

        payload = work_order_report.report_for_week(db, week_start=WEEK, now=AFTER)

        stored = self._stored(db)
        assert len(stored) == 1
        assert stored[0].schema_version == work_order_report.SCHEMA_VERSION
        assert payload.status == "completed"
        assert payload.frozen_at == stored[0].frozen_at
        assert payload.count >= 1

    def test_a_frozen_week_ignores_later_closes_and_restores(self, db, clean_frozen):
        frozen_row = _work_order(db)
        first = work_order_report.report_for_week(db, week_start=WEEK, now=AFTER)

        _work_order(db)  # closes into the week after the freeze
        frozen_row.archived_at = None  # restored after the freeze
        db.commit()
        second = work_order_report.report_for_week(db, week_start=WEEK, now=AFTER)

        live = {"frozen_at", "new_work_order_rows", "new_work_order_count"}
        assert second.model_dump(exclude=live) == first.model_dump(exclude=live)
        assert frozen_row.number in _numbers(second)
        assert len(self._stored(db)) == 1

    def test_the_current_week_is_never_stored(self, db, clean_frozen):
        _work_order(db)

        payload = work_order_report.report_for_week(db, week_start=WEEK, now=DURING)

        assert payload.status == "in_progress"
        assert payload.frozen_at is None
        assert self._stored(db) == []

    def test_a_lost_insert_race_serves_the_winner(self, db, clean_frozen, monkeypatch):
        # Simulate the other request winning: the first `get` misses, the
        # insert then conflicts (the row exists), and the re-read serves it.
        _work_order(db)
        winner = work_order_report.report_for_week(db, week_start=WEEK, now=AFTER)
        real_get = db.get
        calls = {"n": 0}

        def flaky_get(entity, ident, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return None
            return real_get(entity, ident, *args, **kwargs)

        monkeypatch.setattr(db, "get", flaky_get)

        loser = work_order_report.report_for_week(db, week_start=WEEK, now=AFTER)

        assert calls["n"] == 2
        assert loser.model_dump() == winner.model_dump()
        assert len(self._stored(db)) == 1


# --- new rows (the New Work Orders sheet, W14) ----------------------------------


def _new_work_orders(payload: HubReportResponse) -> list[str]:
    return [row.number for row in payload.new_work_order_rows]


def _open(db, **kwargs):
    """A work order created inside WEEK and still open unless told otherwise."""
    return _work_order(db, archived_at=None, status=wo.STATUS_CREATED, **kwargs)


def test_new_work_order_rows_follow_created_at_window_edges(db):
    last_second = _open(db, created_at=_central(1999, 1, 10, 23, 59, 59))
    first_second = _open(db, created_at=_central(1999, 1, 11, 0, 0, 0))
    before = _open(db, created_at=_central(1999, 1, 3, 12, 0))

    this_week = _new_work_orders(_report(db))
    next_week = _new_work_orders(_report(db, week_start=NEXT_WEEK, now=AFTER))

    assert last_second.number in this_week
    assert first_second.number not in this_week
    assert first_second.number in next_week
    assert last_second.number not in next_week
    assert before.number not in this_week


def test_new_work_order_rows_include_open_rows_with_no_close_and_are_counted(db):
    open_row = _open(db)

    payload = _report(db)
    row = next(r for r in payload.new_work_order_rows if r.number == open_row.number)

    assert row.archived_at is None
    assert row.community == "scholars"
    assert payload.new_work_order_count == len(payload.new_work_order_rows) >= 1
    assert open_row.number not in _numbers(payload)


def test_a_new_and_closed_row_in_the_same_week_is_in_both_lists(db):
    both = _work_order(db)

    payload = _report(db)

    assert both.number in _numbers(payload)
    assert both.number in _new_work_orders(payload)


def test_new_work_order_rows_sort_by_community_order_then_number(db):
    academics = _open(db, number="WO-1999-I-A", location="Nowhere")
    scholars_2 = _open(db, number="WO-1999-I-S2", location="Scholars 2", service_type="b")
    scholars_1 = _open(db, number="WO-1999-I-S1", location="Scholars 3", service_type="a")

    numbers = [n for n in _new_work_orders(_report(db)) if n.startswith("WO-1999-I-")]

    assert numbers == [scholars_1.number, scholars_2.number, academics.number]


def test_new_work_order_rows_project_the_six_vendor_fields(db):
    record = _open(
        db,
        number="WO-1999-NEW-PROJECTION",
        vendor_assignee="Vendor Dispatch",
        location="Centennial 4-210",
        service_type="  plumbing ",
        schedule_date="1/8/1999",
        priority="Urgent",
    )

    row = next(r for r in _report(db).new_work_order_rows if r.number == record.number)

    assert (
        row.assigned_to,
        row.location,
        row.service_type,
        row.service_type_label,
        row.schedule_date,
        row.priority,
    ) == (
        "Vendor Dispatch",
        "Centennial 4-210",
        "  plumbing ",
        "plumbing",
        "1/8/1999",
        "Urgent",
    )


class TestNewWorkOrdersStayLive:
    def _stored(self, db, week=WEEK):
        return db.query(WorkOrderReportWeek).filter_by(week_start=week).all()

    def test_a_frozen_week_serves_new_work_orders_live_and_never_stores_them(
        self, db, clean_frozen
    ):
        first = work_order_report.report_for_week(db, week_start=WEEK, now=AFTER)

        late = _open(db)  # created after the freeze, with created_at inside WEEK
        second = work_order_report.report_for_week(db, week_start=WEEK, now=AFTER)

        assert late.number not in _new_work_orders(first)
        assert late.number in _new_work_orders(second)
        assert second.rows == first.rows
        stored = self._stored(db)[0].payload
        assert "new_work_order_rows" not in stored
        assert "new_work_order_count" not in stored

    def test_a_version_1_record_validates_with_no_new_work_orders(self):
        payload = HubReportResponse.model_validate({
            "week_start": "1999-01-04", "week_end": "1999-01-10", "status": "completed",
            "generated_at": "1999-01-11T06:00:00Z", "count": 0, "rows": [],
        })

        assert payload.new_work_order_count == 0
        assert payload.new_work_order_rows == []
