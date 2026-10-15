"""The coupling in both directions and the midnight close."""
import os, sys, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, datetime, timedelta, timezone

import pytest

from app.domain import attendance as attendance_domain
from app.domain.errors import PunchAlreadyOpenError, PunchNotFoundError, PunchTimeInvalidError
from app.models import AttendancePunch, AttendancePunchEdit, User, WorkOrderLaborSession
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






def _charging(db):
    """A technician on shift and charging a work order, the clock backdated
    so a stated end time can land inside it."""
    admin, tech = _seed_user(db, "admin"), _seed_user(db)
    order = _seed_work_order(db, admin, tech)
    attendance_service.punch_in(db, user=tech)
    wo_service.start_labor_session(db, order.id, user=tech)
    now = datetime.now(timezone.utc)
    attendance_service.open_punch_for(db, tech.id).started_at = now - timedelta(hours=3)
    wo_service.running_labor_session_for(db, tech.id).started_at = now - timedelta(hours=2)
    db.commit()
    return admin, tech, now


def test_admin_clock_out_closes_the_punch_stops_the_clock_and_audits(db):
    admin, tech, _now = _charging(db)
    punch = attendance_service.admin_clock_out(db, actor=admin, user_id=tech.id)
    assert punch.ended_at is not None
    assert punch.end_source == attendance_domain.END_SOURCE_ADMIN_EDIT
    assert wo_service.running_labor_session_for(db, tech.id) is None
    edit = db.query(AttendancePunchEdit).filter_by(punch_id=punch.id).one()
    assert edit.field == "ended_at" and edit.edited_by_id == admin.id


def test_admin_clock_out_of_someone_not_clocked_in_is_a_404(db):
    admin, tech = _seed_user(db, "admin"), _seed_user(db)
    with pytest.raises(PunchNotFoundError):
        attendance_service.admin_clock_out(db, actor=admin, user_id=tech.id)


def test_admin_edit_closing_an_open_punch_stops_the_clock_at_that_time(db):
    admin, tech, now = _charging(db)
    punch = attendance_service.open_punch_for(db, tech.id)
    end = now - timedelta(hours=1)
    attendance_service.admin_edit_punch(db, actor=admin, punch_id=punch.id, ended_at=end)
    assert wo_service.running_labor_session_for(db, tech.id) is None
    stopped = (db.query(WorkOrderLaborSession)
               .filter_by(technician_id=tech.id).one())
    assert stopped.ended_at == end


def test_an_end_before_the_clock_started_is_refused_not_zeroed(db):
    admin, tech, now = _charging(db)
    punch = attendance_service.open_punch_for(db, tech.id)
    with pytest.raises(PunchTimeInvalidError):
        attendance_service.admin_edit_punch(
            db, actor=admin, punch_id=punch.id, ended_at=now - timedelta(hours=2, minutes=30))
    db.rollback()
    assert wo_service.running_labor_session_for(db, tech.id) is not None
    assert attendance_service.open_punch_for(db, tech.id) is not None




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


# --- The midnight close (M1-M5) -------------------------------------------

YESTERDAY_7AM = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)   # 7:00 AM CDT Sun
MIDNIGHT = datetime(2026, 9, 21, 5, 0, tzinfo=timezone.utc)
NOW = datetime(2026, 9, 21, 18, 0, tzinfo=timezone.utc)              # 1:00 PM CDT Mon


def _open_punch(db, user, started_at):
    punch = AttendancePunch(id=uuid.uuid4(), user_id=user.id, started_at=started_at,
                            start_source=attendance_domain.START_SOURCE_MANUAL)
    db.add(punch); db.commit()
    return punch


def test_sweep_closes_yesterday_at_midnight_and_leaves_today(db):
    tech, other = _seed_user(db), _seed_user(db)
    old = _open_punch(db, tech, YESTERDAY_7AM)
    today = _open_punch(db, other, NOW - timedelta(hours=2))
    assert attendance_service.sweep_open_punches(db, now=NOW) == 1
    db.refresh(old); db.refresh(today)
    assert old.ended_at == MIDNIGHT
    assert old.end_source == attendance_domain.END_SOURCE_AUTO_CLOCK_OUT
    assert old.needs_review is True
    assert today.ended_at is None
    assert attendance_service.sweep_open_punches(db, now=NOW) == 0
    assert db.query(AttendancePunchEdit).filter_by(punch_id=old.id).count() == 0


def test_sweep_leaves_the_work_order_clock_running(db):
    admin, tech = _seed_user(db, "admin"), _seed_user(db)
    order = _seed_work_order(db, admin, tech)
    wo_service.start_labor_session(db, order.id, user=tech)
    _open_punch(db, tech, datetime.now(timezone.utc) - timedelta(days=1))
    assert attendance_service.sweep_open_punches(db, user_id=tech.id) == 1
    assert wo_service.running_labor_session_for(db, tech.id) is not None


def test_punch_in_after_a_forgotten_day_succeeds(db):
    tech = _seed_user(db)
    _open_punch(db, tech, YESTERDAY_7AM)
    punch = attendance_service.punch_in(db, user=tech, now=NOW)
    assert punch.started_at == NOW


def test_labor_start_after_a_forgotten_day_opens_a_fresh_punch(db):
    tech = _seed_user(db)
    _open_punch(db, tech, YESTERDAY_7AM)
    punch = attendance_service.ensure_punch_for_labor_start(db, user=tech, now=NOW)
    assert punch.started_at == NOW
    assert punch.start_source == attendance_domain.START_SOURCE_AUTO_WORK_ORDER


def test_punch_out_after_midnight_closes_at_midnight_and_reports_not_punched_in(db):
    tech = _seed_user(db)
    old = _open_punch(db, tech, YESTERDAY_7AM)
    with pytest.raises(PunchNotFoundError):
        attendance_service.punch_out(db, user=tech, now=NOW)
    db.refresh(old)
    assert old.ended_at == MIDNIGHT


def test_admin_clock_out_after_midnight_is_a_404_not_a_cross_midnight_end(db):
    admin, tech = _seed_user(db, "admin"), _seed_user(db)
    old = _open_punch(db, tech, YESTERDAY_7AM)
    with pytest.raises(PunchNotFoundError):
        attendance_service.admin_clock_out(db, actor=admin, user_id=tech.id, now=NOW)
    db.refresh(old)
    assert old.ended_at == MIDNIGHT


def test_looks_right_on_a_legacy_cross_midnight_punch_succeeds(db):
    admin, tech = _seed_user(db, "admin"), _seed_user(db)
    legacy = AttendancePunch(id=uuid.uuid4(), user_id=tech.id, started_at=YESTERDAY_7AM,
                             ended_at=MIDNIGHT + timedelta(hours=2), start_source="manual",
                             end_source="self_reported", needs_review=True)
    db.add(legacy); db.commit()
    attendance_service.admin_edit_punch(db, actor=admin, punch_id=legacy.id,
                                        needs_review=False, now=NOW)
    db.refresh(legacy)
    assert legacy.needs_review is False


def test_an_admin_edit_across_midnight_is_refused(db):
    admin, tech = _seed_user(db, "admin"), _seed_user(db)
    punch = attendance_service.admin_add_punch(
        db, actor=admin, user_id=tech.id, started_at=YESTERDAY_7AM,
        ended_at=YESTERDAY_7AM + timedelta(hours=8), now=NOW)
    with pytest.raises(PunchTimeInvalidError, match="cross midnight"):
        attendance_service.admin_edit_punch(
            db, actor=admin, punch_id=punch.id,
            ended_at=MIDNIGHT + timedelta(minutes=1), now=NOW)


def test_mark_week_reviewed_accepts_a_midnight_close(db):
    admin, tech = _seed_user(db, "admin"), _seed_user(db)
    old = _open_punch(db, tech, YESTERDAY_7AM)
    result = attendance_service.mark_week_reviewed(
        db, actor=admin, week_start=date(2026, 9, 14), now=NOW)   # Mon 9/14 - Sun 9/20
    db.refresh(old)
    assert result.punches >= 1 and old.needs_review is False


def test_me_payload_does_not_count_yesterdays_open_punch_into_today(db):
    tech = _seed_user(db)
    _open_punch(db, tech, YESTERDAY_7AM)
    me = attendance_service.me_payload(db, user=tech, now=NOW)
    assert me.open_punch is None and me.clocked_minutes_today == 0


# --- The lunch waiver (L2/L4) ---------------------------------------------

def test_waiving_lunch_writes_an_audit_row_and_keeps_needs_review(db):
    admin, tech = _seed_user(db, "admin"), _seed_user(db)
    old = _open_punch(db, tech, YESTERDAY_7AM)
    attendance_service.sweep_open_punches(db, now=NOW)          # flagged
    attendance_service.admin_edit_punch(db, actor=admin, punch_id=old.id,
        lunch_waived=True, reason="Lunch removed by an Admin", now=NOW)
    db.refresh(old)
    assert old.lunch_waived is True and old.needs_review is True
    edit = db.query(AttendancePunchEdit).filter_by(punch_id=old.id).one()
    assert (edit.field, edit.old_value, edit.new_value) == ("lunch_waived", "false", "true")
    assert edit.reason == "Lunch removed by an Admin"


def test_restating_the_same_waiver_changes_nothing(db):
    from app.domain.errors import NoChangeError
    admin, tech = _seed_user(db, "admin"), _seed_user(db)
    old = _open_punch(db, tech, YESTERDAY_7AM)
    attendance_service.sweep_open_punches(db, now=NOW)
    with pytest.raises(NoChangeError):
        attendance_service.admin_edit_punch(db, actor=admin, punch_id=old.id,
                                            lunch_waived=False, now=NOW)
