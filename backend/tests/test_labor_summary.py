"""Database tests for the hub's time engine.

Covers the global stale-session sweep (this task) and the daily labor
aggregate (next task). Skips without a reachable Postgres, like every other
`db`-fixture test in this suite.

Seed helpers mirror `tests/test_work_orders_service.py` so the two files read
the same way.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.domain import roles
from app.domain import work_orders as wo
from app.models import (
    User,
    WorkOrder,
    WorkOrderLabor,
    WorkOrderLaborSession,
)
from app.services import auth
from app.services import work_orders as wos


# --- seed helpers --------------------------------------------------------

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


def _seed_work_order(db, *, created_by, assigned_to=None, number=None):
    return wos.get_or_create_work_order(
        db,
        number=number or f"WO-{uuid.uuid4().hex[:8]}",
        created_by_id=created_by.id,
        assigned_to_id=assigned_to.id if assigned_to else None,
    )


def _seed_session(db, work_order, technician, *, started_at, ended_at=None):
    """A session written straight to the table.

    Bypasses `start_labor_session` on purpose: these tests need exact
    timestamps, including ones in the past, and the service always stamps
    `now`.
    """
    session = WorkOrderLaborSession(
        id=uuid.uuid4(),
        work_order_id=work_order.id,
        technician_id=technician.id,
        started_at=started_at,
        ended_at=ended_at,
    )
    db.add(session)
    db.flush()
    return session


# --- the global sweep ----------------------------------------------------

def test_sweep_closes_a_stale_session_at_the_capped_instant(db):
    tech = _seed_user(db)
    work_order = _seed_work_order(db, created_by=tech, assigned_to=tech)
    started = datetime.now(timezone.utc) - timedelta(hours=20)
    session = _seed_session(db, work_order, tech, started_at=started)

    closed = wos.sweep_stale_sessions(db, technician_id=tech.id)

    assert closed == 1
    db.refresh(session)
    # Closed at start + 720 minutes, NOT at sweep time: the billed figure has
    # to be right even though the flag is late.
    assert session.ended_at == started + timedelta(
        minutes=wo.LABOR_SESSION_MAX_MINUTES
    )
    assert session.auto_closed_at is not None


def test_sweep_writes_a_labor_row_capped_at_twelve_hours(db):
    tech = _seed_user(db)
    work_order = _seed_work_order(db, created_by=tech, assigned_to=tech)
    _seed_session(
        db, work_order, tech, started_at=datetime.now(timezone.utc) - timedelta(hours=20)
    )

    wos.sweep_stale_sessions(db, technician_id=tech.id)

    entries = (
        db.query(WorkOrderLabor)
        .filter(WorkOrderLabor.work_order_id == work_order.id)
        .all()
    )
    assert [e.minutes for e in entries] == [wo.LABOR_SESSION_MAX_MINUTES]


def test_sweep_does_not_auto_hold(db):
    # A supervisor's phone must not buzz because somebody opened a dashboard.
    tech = _seed_user(db)
    work_order = _seed_work_order(db, created_by=tech, assigned_to=tech)
    work_order.status = wo.STATUS_IN_PROGRESS
    db.flush()
    _seed_session(
        db, work_order, tech, started_at=datetime.now(timezone.utc) - timedelta(hours=20)
    )

    wos.sweep_stale_sessions(db, technician_id=tech.id)

    db.refresh(work_order)
    assert work_order.status == wo.STATUS_IN_PROGRESS


def test_sweep_leaves_a_fresh_session_running(db):
    tech = _seed_user(db)
    work_order = _seed_work_order(db, created_by=tech, assigned_to=tech)
    session = _seed_session(
        db, work_order, tech, started_at=datetime.now(timezone.utc) - timedelta(hours=2)
    )

    assert wos.sweep_stale_sessions(db, technician_id=tech.id) == 0
    db.refresh(session)
    assert session.ended_at is None


def test_sweep_is_idempotent(db):
    tech = _seed_user(db)
    work_order = _seed_work_order(db, created_by=tech, assigned_to=tech)
    _seed_session(
        db, work_order, tech, started_at=datetime.now(timezone.utc) - timedelta(hours=20)
    )

    assert wos.sweep_stale_sessions(db, technician_id=tech.id) == 1
    assert wos.sweep_stale_sessions(db, technician_id=tech.id) == 0


def test_a_scoped_sweep_leaves_other_peoples_clocks_alone(db):
    mine = _seed_user(db)
    theirs = _seed_user(db, first_name="Marisol", last_name="Chen")
    work_order = _seed_work_order(db, created_by=mine, assigned_to=mine)
    stale_other = _seed_session(
        db, work_order, theirs, started_at=datetime.now(timezone.utc) - timedelta(hours=20)
    )
    _seed_session(
        db, work_order, mine, started_at=datetime.now(timezone.utc) - timedelta(hours=20)
    )

    assert wos.sweep_stale_sessions(db, technician_id=mine.id) == 1
    db.refresh(stale_other)
    assert stale_other.ended_at is None


def test_an_unscoped_sweep_closes_every_stale_session(db):
    mine = _seed_user(db)
    theirs = _seed_user(db, first_name="Marisol", last_name="Chen")
    work_order = _seed_work_order(db, created_by=mine, assigned_to=mine)
    _seed_session(
        db, work_order, mine, started_at=datetime.now(timezone.utc) - timedelta(hours=20)
    )
    _seed_session(
        db, work_order, theirs, started_at=datetime.now(timezone.utc) - timedelta(hours=20)
    )

    assert wos.sweep_stale_sessions(db) == 2


def test_tracking_start_statuses_is_exported_for_the_hub_picker(db):
    # The hub's `Start on...` picker must offer exactly what
    # `start_labor_session` accepts, so it reads the same tuple.
    assert wos.TRACKING_START_STATUSES == (
        wo.STATUS_CREATED,
        wo.STATUS_ASSIGNED,
        wo.STATUS_IN_PROGRESS,
        wo.STATUS_ON_HOLD,
    )
