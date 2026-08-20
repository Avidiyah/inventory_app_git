"""Database tests for the personal hub payload.

Covers the count convention (a total and two subsets, not three disjoint
buckets), the `Start on...` picker's contents and order, and the sweep that
runs before the read. The time arithmetic itself is covered by
`test_labor_day.py` and `test_labor_summary.py`; this file only checks that
the composer wires them together.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.domain import labor_day
from app.domain import roles
from app.domain import work_orders as wo
from app.models import User, WorkOrderLaborSession, WorkOrderTechnician
from app.services import auth
from app.services import hub as hub_service
from app.services import work_orders as wos


def _seed_user(db, role=roles.ROLE_TECHNICIAN, *, first_name="Jose", last_name="Rivera"):
    user = User(
        username=f"u-{uuid.uuid4().hex[:10]}",
        first_name=first_name,
        last_name=last_name,
        password_hash=auth.hash_password("hunter2"),
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def _seed_work_order(db, *, created_by, assigned_to=None, number=None, status=None):
    work_order = wos.get_or_create_work_order(
        db,
        number=number or f"WO-{uuid.uuid4().hex[:8]}",
        created_by_id=created_by.id,
        assigned_to_id=assigned_to.id if assigned_to else None,
    )
    if status is not None:
        work_order.status = status
        db.flush()
    return work_order


def test_counts_are_a_total_and_two_subsets(db):
    # "8 assigned, 1 in progress, 2 ready" describes 8 work orders, not 11.
    tech = _seed_user(db)
    for _ in range(5):
        _seed_work_order(db, created_by=tech, assigned_to=tech, status=wo.STATUS_ASSIGNED)
    _seed_work_order(db, created_by=tech, assigned_to=tech, status=wo.STATUS_IN_PROGRESS)
    for _ in range(2):
        _seed_work_order(
            db, created_by=tech, assigned_to=tech, status=wo.STATUS_READY_TO_COMPLETE
        )

    payload = hub_service.personal_hub(db, tech)

    assert payload.counts.assigned == 8
    assert payload.counts.in_progress == 1
    assert payload.counts.ready_to_complete == 2


def test_counts_include_work_assigned_through_the_technician_table(db):
    # Assignment lives in two places -- the legacy `assigned_to_id` column and
    # `work_order_technicians` rows. Counting only one silently loses work.
    tech = _seed_user(db)
    creator = _seed_user(db, roles.ROLE_SUPERVISOR)
    work_order = _seed_work_order(db, created_by=creator, status=wo.STATUS_ASSIGNED)
    db.add(
        WorkOrderTechnician(work_order_id=work_order.id, technician_id=tech.id)
    )
    db.flush()

    assert hub_service.personal_hub(db, tech).counts.assigned == 1


def test_an_archived_work_order_is_excluded_everywhere(db):
    tech = _seed_user(db)
    work_order = _seed_work_order(
        db, created_by=tech, assigned_to=tech, status=wo.STATUS_ASSIGNED
    )
    work_order.archived_at = datetime.now(timezone.utc)
    db.flush()

    payload = hub_service.personal_hub(db, tech)

    assert payload.counts.assigned == 0
    assert payload.startable == []


def test_someone_elses_work_order_is_not_mine(db):
    mine = _seed_user(db)
    theirs = _seed_user(db, first_name="Marisol", last_name="Chen")
    _seed_work_order(db, created_by=theirs, assigned_to=theirs, status=wo.STATUS_ASSIGNED)

    assert hub_service.personal_hub(db, mine).counts.assigned == 0


def test_the_picker_offers_only_startable_statuses(db):
    tech = _seed_user(db)
    _seed_work_order(db, created_by=tech, assigned_to=tech, status=wo.STATUS_ASSIGNED)
    _seed_work_order(
        db, created_by=tech, assigned_to=tech, status=wo.STATUS_READY_TO_COMPLETE
    )
    _seed_work_order(db, created_by=tech, assigned_to=tech, status=wo.STATUS_COMPLETED)

    startable = hub_service.personal_hub(db, tech).startable

    assert [s.status for s in startable] == [wo.STATUS_ASSIGNED]


def test_the_picker_puts_live_work_first(db):
    tech = _seed_user(db)
    _seed_work_order(
        db, created_by=tech, assigned_to=tech, number="88301", status=wo.STATUS_CREATED
    )
    _seed_work_order(
        db, created_by=tech, assigned_to=tech, number="88302", status=wo.STATUS_ASSIGNED
    )
    _seed_work_order(
        db, created_by=tech, assigned_to=tech, number="88303", status=wo.STATUS_ON_HOLD
    )
    _seed_work_order(
        db, created_by=tech, assigned_to=tech, number="88304", status=wo.STATUS_IN_PROGRESS
    )

    startable = hub_service.personal_hub(db, tech).startable

    assert [s.number for s in startable] == ["88304", "88303", "88302", "88301"]


def test_the_picker_carries_the_raw_place_fields(db):
    # There is no server-side location composer; `workOrders.js::placeMeta`
    # owns that and needs all four inputs.
    tech = _seed_user(db)
    work_order = _seed_work_order(
        db, created_by=tech, assigned_to=tech, status=wo.STATUS_ASSIGNED
    )
    work_order.community = "Commons"
    work_order.building_number = "B3"
    work_order.unit_number = "214"
    db.flush()

    entry = hub_service.personal_hub(db, tech).startable[0]

    assert entry.community == "Commons"
    assert entry.building_number == "B3"
    assert entry.unit_number == "214"


def test_the_hub_sweeps_the_callers_forgotten_clock_before_reading(db):
    # Without this a technician who forgot to clock out on Tuesday opens the
    # hub on Wednesday to a twenty-hour running clock.
    tech = _seed_user(db)
    work_order = _seed_work_order(
        db, created_by=tech, assigned_to=tech, status=wo.STATUS_IN_PROGRESS
    )
    started = datetime.now(timezone.utc) - timedelta(hours=20)
    session = WorkOrderLaborSession(
        id=uuid.uuid4(),
        work_order_id=work_order.id,
        technician_id=tech.id,
        started_at=started,
    )
    db.add(session)
    db.flush()

    payload = hub_service.personal_hub(db, tech)

    assert payload.clock.running is None
    db.refresh(session)
    assert session.ended_at == started + timedelta(
        minutes=wo.LABOR_SESSION_MAX_MINUTES
    )


def test_the_payload_reports_the_servers_instant_and_central_day(db):
    tech = _seed_user(db)

    payload = hub_service.personal_hub(db, tech)

    assert payload.server_now.tzinfo is not None
    assert payload.day == labor_day.central_date_of(payload.server_now)
    assert payload.user.id == tech.id


def test_an_empty_hub_is_all_zeros_and_empty_lists(db):
    tech = _seed_user(db)

    payload = hub_service.personal_hub(db, tech)

    assert payload.counts.assigned == 0
    assert payload.startable == []
    assert payload.tools_out == []
    assert payload.clock.total_minutes == 0
