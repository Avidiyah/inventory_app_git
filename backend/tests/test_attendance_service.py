"""The coupling in both directions, the stale refusal, and the self-close."""
import os, sys, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone

import pytest

from app.domain import attendance as attendance_domain
from app.domain.errors import PunchAlreadyOpenError, PunchNotFoundError, PunchTimeInvalidError
from app.models import AttendancePunch, User
from app.services import attendance as attendance_service
from app.services import auth as auth_service
from app.services import work_orders as wo_service


def _seed_user(db, role="technician"):
    user = User(username=f"u-{uuid.uuid4().hex[:10]}",
                password_hash=auth_service.hash_password("hunter2"), role=role)
    db.add(user); db.flush()
    return user


def _seed_work_order(db, admin, technician):
    order = wo_service.get_or_create_work_order(
        db, number=f"WO-ATT-{uuid.uuid4().hex[:8]}", created_by_id=admin.id,
        assigned_to_id=technician.id)
    db.commit()
    return order


def test_punch_in_opens_a_manual_punch(db):
    user = _seed_user(db)
    punch = attendance_service.punch_in(db, user=user)
    assert punch.ended_at is None
    assert punch.start_source == attendance_domain.START_SOURCE_MANUAL
    assert punch.needs_review is False


def test_punch_in_refuses_while_one_is_open_and_names_it(db):
    user = _seed_user(db)
    first = attendance_service.punch_in(db, user=user)
    with pytest.raises(PunchAlreadyOpenError) as exc:
        attendance_service.punch_in(db, user=user)
    assert exc.value.punch_id == first.id
    assert exc.value.stale is False


def test_starting_a_work_order_clock_off_shift_punches_in_automatically(db):
    admin, tech = _seed_user(db, "admin"), _seed_user(db)
    order = _seed_work_order(db, admin, tech)
    attendance_service.ensure_punch_for_labor_start(db, user=tech)
    wo_service.start_labor_session(db, order.id, user=tech)
    punch = attendance_service.open_punch_for(db, tech.id)
    assert punch is not None
    assert punch.start_source == attendance_domain.START_SOURCE_AUTO_WORK_ORDER


def test_an_open_punch_from_today_lets_a_labor_start_through_unchanged(db):
    tech = _seed_user(db)
    opened = attendance_service.punch_in(db, user=tech)
    assert attendance_service.ensure_punch_for_labor_start(db, user=tech).id == opened.id


def test_a_stale_punch_blocks_the_labor_start(db):
    tech = _seed_user(db)
    now = datetime.now(timezone.utc)
    db.add(AttendancePunch(user_id=tech.id, started_at=now - timedelta(days=2),
                           start_source=attendance_domain.START_SOURCE_MANUAL))
    db.commit()
    with pytest.raises(PunchAlreadyOpenError) as exc:
        attendance_service.ensure_punch_for_labor_start(db, user=tech)
    assert exc.value.stale is True


def test_punch_out_force_stops_the_running_work_order_clock(db):
    admin, tech = _seed_user(db, "admin"), _seed_user(db)
    order = _seed_work_order(db, admin, tech)
    attendance_service.punch_in(db, user=tech)
    wo_service.start_labor_session(db, order.id, user=tech)
    attendance_service.punch_out(db, user=tech)
    assert wo_service.running_labor_session_for(db, tech.id) is None
    assert attendance_service.open_punch_for(db, tech.id) is None


def test_punch_out_without_a_punch_is_a_404(db):
    with pytest.raises(PunchNotFoundError):
        attendance_service.punch_out(db, user=_seed_user(db))


def test_self_close_flags_the_punch_for_review_at_the_stated_time(db):
    tech = _seed_user(db)
    now = datetime.now(timezone.utc)
    started = now - timedelta(days=1, hours=6)
    db.add(AttendancePunch(user_id=tech.id, started_at=started,
                           start_source=attendance_domain.START_SOURCE_MANUAL))
    db.commit()
    stated = started + timedelta(hours=8)
    punch = attendance_service.self_close(db, user=tech, ended_at=stated)
    assert punch.ended_at == stated
    assert punch.end_source == attendance_domain.END_SOURCE_SELF_REPORTED
    assert punch.needs_review is True
    # And the next punch-in is unblocked -- the whole point of D5.
    assert attendance_service.punch_in(db, user=tech) is not None


def test_self_close_refuses_a_time_before_the_punch_started(db):
    tech = _seed_user(db)
    started = datetime.now(timezone.utc) - timedelta(hours=3)
    db.add(AttendancePunch(user_id=tech.id, started_at=started,
                           start_source=attendance_domain.START_SOURCE_MANUAL))
    db.commit()
    with pytest.raises(PunchTimeInvalidError):
        attendance_service.self_close(db, user=tech, ended_at=started - timedelta(hours=1))


def test_me_payload_sums_todays_clocked_minutes_without_rounding(db):
    tech = _seed_user(db)
    # Pinned to mid-afternoon Central so the seeded window never straddles
    # midnight, whatever time the suite actually runs at.
    now = datetime(2026, 9, 21, 20, 0, tzinfo=timezone.utc)
    db.add(AttendancePunch(user_id=tech.id, started_at=now - timedelta(minutes=47),
                           ended_at=now - timedelta(minutes=5),
                           start_source=attendance_domain.START_SOURCE_MANUAL,
                           end_source=attendance_domain.END_SOURCE_MANUAL))
    db.commit()
    payload = attendance_service.me_payload(db, user=tech, now=now)
    assert payload.open_punch is None
    assert payload.clocked_minutes_today == 42      # not 60, not 30
