"""The Admin live roster: who is on shift, who is charging, who is idle.

Helpers are `test_attendance_compare_service.py`'s, reused rather than
re-invented. The `db` fixture is a real database with a real crew in it, so
every assertion here is scoped to the people this file creates -- except on
`on_shift`, which holds only people with an open punch and is therefore
exactly ours.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone

import uuid

from app.domain import attendance as attendance_domain
from app.domain import work_orders as wo
from app.models import User, WorkOrder, WorkOrderLaborSession
from app.services import attendance_live
from app.services import auth as auth_service

from tests.test_attendance_compare_service import make_punch, make_technician


NOW = datetime(2026, 9, 21, 15, 0, tzinfo=timezone.utc)


def _iso(moment):
    return moment.isoformat().replace("+00:00", "Z")


def open_punch(db, user, *, started_at):
    return make_punch(db, user, _iso(started_at))


def make_work_order(db, tech):
    from app.services import work_orders as wos

    return wos.get_or_create_work_order(
        db, number=f"WO-{uuid.uuid4().hex[:8]}",
        created_by_id=tech.id, assigned_to_id=tech.id)


def open_session(db, tech, work_order, *, started_at):
    session = WorkOrderLaborSession(
        id=uuid.uuid4(), work_order_id=work_order.id, technician_id=tech.id,
        started_at=started_at, ended_at=None)
    db.add(session); db.flush()
    return session


def make_admin(db):
    user = User(username=f"u-{uuid.uuid4().hex[:10]}",
                password_hash=auth_service.hash_password("hunter2"),
                role="admin", first_name="Ada", last_name="Min")
    db.add(user); db.flush()
    return user


def _entry_for(entries, user):
    return next((e for e in entries if e.user.id == user.id), None)


def test_somebody_with_no_punch_is_absent_not_gray_on_the_strip(db):
    tech = make_technician(db)
    payload = attendance_live.roster(db, now=NOW)
    assert _entry_for(payload.absent, tech) is not None
    assert _entry_for(payload.absent, tech).state == attendance_domain.STATE_GRAY
    assert payload.on_shift == []
    assert payload.on_shift_count == 0


def test_an_open_punch_with_a_running_clock_is_green_and_names_the_job(db):
    tech = make_technician(db)
    work_order = make_work_order(db, tech)
    open_punch(db, tech, started_at=NOW - timedelta(hours=2))
    open_session(db, tech, work_order, started_at=NOW - timedelta(minutes=20))
    entry = attendance_live.roster(db, now=NOW).on_shift[0]
    assert entry.state == attendance_domain.STATE_GREEN
    assert entry.work_order_number == work_order.number
    assert entry.charging_since is not None
    assert entry.idle_since is None
    assert entry.idle_minutes == 0


def test_an_open_punch_with_no_clock_goes_yellow_then_red(db):
    tech = make_technician(db)
    open_punch(db, tech, started_at=NOW - timedelta(minutes=5))
    assert attendance_live.roster(db, now=NOW).on_shift[0].state == (
        attendance_domain.STATE_YELLOW
    )
    later = NOW + timedelta(minutes=attendance_domain.IDLE_RED_MINUTES)
    entry = attendance_live.roster(db, now=later).on_shift[0]
    assert entry.state == attendance_domain.STATE_RED
    assert entry.idle_minutes >= attendance_domain.IDLE_RED_MINUTES


def test_a_clock_past_the_cap_is_not_charging(db):
    """The failure this rule exists to stop: a forgotten clock reading green
    forever. Past `LABOR_SESSION_MAX_MINUTES` the session has effectively
    ended, and idle is measured from where a sweep would have closed it."""
    tech = make_technician(db)
    work_order = make_work_order(db, tech)
    started = NOW - timedelta(minutes=wo.LABOR_SESSION_MAX_MINUTES + 60)
    open_punch(db, tech, started_at=started)
    open_session(db, tech, work_order, started_at=started)
    entry = attendance_live.roster(db, now=NOW).on_shift[0]
    assert entry.state == attendance_domain.STATE_RED
    assert entry.work_order_number is None
    assert entry.idle_minutes == 60


def test_the_strip_sorts_red_then_yellow_then_green_longest_idle_first(db):
    one = make_technician(db, "Ann", "Lee")
    two = make_technician(db, "Bo", "Ruiz")
    three = make_technician(db, "Cy", "Nolan")
    work_order = make_work_order(db, three)
    open_punch(db, one, started_at=NOW - timedelta(minutes=45))
    open_punch(db, two, started_at=NOW - timedelta(minutes=3))
    open_punch(db, three, started_at=NOW - timedelta(hours=3))
    open_session(db, three, work_order, started_at=NOW - timedelta(minutes=5))
    payload = attendance_live.roster(db, now=NOW)
    assert [e.state for e in payload.on_shift] == [
        attendance_domain.STATE_RED,
        attendance_domain.STATE_YELLOW,
        attendance_domain.STATE_GREEN,
    ]
    assert payload.on_shift_count == 3
    assert payload.charging_count == 1
    assert payload.idle_count == 2


def test_the_roster_writes_nothing(db):
    """Spec §4: every attendance read is side-effect-free, which is what lets
    the sub-tab poll it. A forgotten clock is clipped on the way out, never
    swept."""
    tech = make_technician(db)
    work_order = make_work_order(db, tech)
    started = NOW - timedelta(minutes=wo.LABOR_SESSION_MAX_MINUTES + 60)
    open_punch(db, tech, started_at=started)
    session = open_session(db, tech, work_order, started_at=started)
    attendance_live.roster(db, now=NOW)
    db.expire_all()
    assert session.ended_at is None


def test_an_admin_who_punches_in_is_not_colour_judged(db):
    """Spec §6: the coloured roster covers `WORK_ORDER_TECHNICIAN_ROLES`
    only. Their hours still appear in the Hours grid."""
    admin = make_admin(db)
    open_punch(db, admin, started_at=NOW - timedelta(hours=1))
    payload = attendance_live.roster(db, now=NOW)
    assert payload.on_shift == []
    assert _entry_for(payload.absent, admin) is None
