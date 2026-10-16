"""`services.person_week`: one person's week, composed from the attendance
week, the labor range summaries, and one completed-work-order query (spec
2026-10-15-user-profile-week-design.md). Side-effect-free."""
import os, sys, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, datetime, timedelta, timezone

import pytest

from app.domain import roles
from app.domain.errors import PersonNotProfilableError, UserNotFoundError
from app.models import (
    AttendancePunch, User, WorkOrder, WorkOrderLabor, WorkOrderLaborSession,
    WorkOrderTechnician,
)
from app.services import auth as auth_service
from app.services import person_week


def test_person_not_profilable_maps_to_403():
    from app.routers._errors import to_http
    assert to_http(PersonNotProfilableError("x")).status_code == 403


def test_response_models_are_from_attributes():
    from app.schemas.attendance import (
        PersonWeekCharged, PersonWeekCompleted, PersonWeekDay, PersonWeekResponse,
    )
    for model in (PersonWeekCharged, PersonWeekCompleted, PersonWeekDay, PersonWeekResponse):
        assert model.model_config.get("from_attributes") is True


MONDAY = date(2026, 9, 14)
NOW = datetime(2026, 9, 20, 23, 0, tzinfo=timezone.utc)
# Central day boundaries in UTC (CDT): 05:00Z is midnight.
def _utc(day, hour, minute=0):
    return datetime(2026, 9, day, hour, minute, tzinfo=timezone.utc)


def _user(db, role=roles.ROLE_TECHNICIAN, first="Ann", last="Lee", archived=False):
    user = User(username=f"u-{uuid.uuid4().hex[:10]}",
                password_hash=auth_service.hash_password("hunter2"),
                role=role, first_name=first, last_name=last,
                archived_at=NOW if archived else None)
    db.add(user); db.flush()
    return user


def _wo(db, created_by, *, completed_at=None, crew=(), number=None, location="Bldg 4"):
    work_order = WorkOrder(id=uuid.uuid4(), number=number or f"WO-{uuid.uuid4().hex[:6]}",
                           status="completed" if completed_at else "created",
                           created_by_id=created_by.id, completed_at=completed_at,
                           location=location)
    db.add(work_order); db.flush()
    for tech in crew:
        db.add(WorkOrderTechnician(work_order_id=work_order.id, technician_id=tech.id))
    db.flush()
    return work_order


def _session(db, work_order, tech, started_at, ended_at=None, auto_closed=False):
    session = WorkOrderLaborSession(
        id=uuid.uuid4(), work_order_id=work_order.id, technician_id=tech.id,
        started_at=started_at, ended_at=ended_at,
        auto_closed_at=ended_at if auto_closed else None)
    db.add(session); db.flush()
    return session


def _punch(db, user, started_at, ended_at=None, needs_review=False):
    punch = AttendancePunch(id=uuid.uuid4(), user_id=user.id, started_at=started_at,
                            ended_at=ended_at, start_source="manual",
                            end_source=None if ended_at is None else "manual",
                            needs_review=needs_review)
    db.add(punch); db.flush()
    return punch


def _payload(db, user, week_start=MONDAY):
    return person_week.week_payload(db, user_id=user.id, week_start=week_start, now=NOW)


def _day(payload, day):
    return next(d for d in payload.days if d.date == day)


def test_seven_days_always_present(db):
    tech = _user(db)
    _punch(db, tech, _utc(14, 13), _utc(14, 21))
    db.commit()
    payload = _payload(db, tech)
    assert [d.date for d in payload.days] == [MONDAY + timedelta(days=i) for i in range(7)]
    assert _day(payload, MONDAY).clocked_minutes == 480
    assert payload.total_clocked_minutes == 480
    assert payload.total_charged_minutes == 0
    assert payload.total_completed == 0
    assert payload.user.id == tech.id and payload.archived is False
    assert payload.week_end == MONDAY + timedelta(days=6)


def test_completed_is_bucketed_by_central_day(db):
    tech = _user(db)
    # 11:30 PM Central Monday == 04:30Z Tuesday: a UTC bucket would say Tuesday.
    _wo(db, tech, completed_at=_utc(15, 4, 30), crew=[tech], number="WO-1")
    db.commit()
    payload = _payload(db, tech)
    assert _day(payload, MONDAY).completed_count == 1
    assert _day(payload, MONDAY).completed[0].number == "WO-1"
    assert _day(payload, MONDAY).completed[0].location == "Bldg 4"
    assert _day(payload, MONDAY + timedelta(days=1)).completed_count == 0
    assert payload.total_completed == 1


def test_every_crew_member_is_credited_and_no_crew_credits_nobody(db):
    a, b, c = _user(db), _user(db, first="Bo"), _user(db, first="Cy")
    _wo(db, a, completed_at=_utc(16, 15), crew=[a, b, c])
    _wo(db, a, completed_at=_utc(16, 16), crew=[])
    db.commit()
    for person in (a, b, c):
        assert _payload(db, person).total_completed == 1


def test_a_reopened_work_order_drops_off(db):
    tech = _user(db)
    # services/work_orders.py clears completed_at on reopen; the column is the
    # only signal, so None is what the profile sees.
    _wo(db, tech, completed_at=None, crew=[tech])
    db.commit()
    assert _payload(db, tech).total_completed == 0


def test_charged_collapses_two_sessions_on_one_work_order(db):
    tech = _user(db)
    wo = _wo(db, tech, crew=[tech], number="WO-7")
    _session(db, wo, tech, _utc(14, 13), _utc(14, 15))
    _session(db, wo, tech, _utc(14, 16), _utc(14, 17), auto_closed=True)
    db.commit()
    monday = _day(_payload(db, tech), MONDAY)
    assert monday.charged_minutes == 180
    assert len(monday.charged) == 1
    assert monday.charged[0].number == "WO-7"
    assert monday.charged[0].minutes == 180
    assert monday.charged[0].auto_closed is True
    assert monday.charged[0].running is False
    assert [(s.started_at, s.ended_at) for s in monday.charged[0].spans] == [
        (_utc(14, 13), _utc(14, 15)), (_utc(14, 16), _utc(14, 17))]


def test_charged_includes_hand_entered_labor(db):
    """2026-10-16 U6: hand-entered labor counts as charged; the split rides
    beside it in `adjustment_minutes`."""
    tech = _user(db)
    wo = _wo(db, tech, crew=[tech])
    _session(db, wo, tech, _utc(14, 13), _utc(14, 14))
    db.add(WorkOrderLabor(id=uuid.uuid4(), work_order_id=wo.id, technician_id=tech.id,
                          minutes=30, recorded_by_id=tech.id, created_at=_utc(14, 18)))
    db.commit()
    payload = _payload(db, tech)
    monday = _day(payload, MONDAY)
    assert monday.charged_minutes == 90
    assert monday.adjustment_minutes == 30
    assert monday.adjustments[0].minutes == 30
    assert payload.total_charged_minutes == 90
    assert payload.total_adjustment_minutes == 30


def test_a_running_session_is_capped_and_marked_running_without_writing(db):
    tech = _user(db)
    wo = _wo(db, tech, crew=[tech])
    session = _session(db, wo, tech, NOW - timedelta(hours=20))
    db.commit()
    payload = _payload(db, tech)
    charged = [c for d in payload.days for c in d.charged]
    assert charged and all(c.running for c in charged)
    # Past the cap the day is pending: shown at the cap, kept out of totals.
    assert sum(d.charged_minutes for d in payload.days) == 12 * 60
    assert payload.total_charged_minutes == 0
    db.refresh(session)
    assert session.ended_at is None


def test_a_session_crossing_the_week_end_is_clipped(db):
    tech = _user(db)
    wo = _wo(db, tech, crew=[tech])
    # Sunday 10 PM Central -> Monday 2 AM Central: only 2h belong to this week.
    _session(db, wo, tech, _utc(21, 3), _utc(21, 7))
    db.commit()
    assert _payload(db, tech).total_charged_minutes == 120


def test_needs_review_and_reviewable_follow_punches_and_sessions(db):
    tech = _user(db)
    _punch(db, tech, _utc(15, 13), _utc(15, 21), needs_review=True)
    db.commit()
    payload = _payload(db, tech)
    assert _day(payload, MONDAY + timedelta(days=1)).needs_review is True
    assert payload.reviewable is True


def test_an_open_punch_sets_has_open(db):
    tech = _user(db)
    _punch(db, tech, NOW - timedelta(hours=1))
    db.commit()
    payload = _payload(db, tech)
    assert any(d.has_open for d in payload.days)


def test_archived_target_with_no_punches_is_allowed(db):
    tech = _user(db, archived=True)
    db.commit()
    payload = _payload(db, tech)
    assert payload.archived is True
    assert len(payload.days) == 7
    assert payload.total_clocked_minutes == 0


@pytest.mark.parametrize("role", [roles.ROLE_SUPERVISOR, roles.ROLE_TECHFM_OA])
def test_team_lead_and_techfm_oa_are_profilable(db, role):
    person = _user(db, role=role)
    db.commit()
    assert _payload(db, person).user.role == role


def test_owner_target_raises(db):
    person = _user(db, role=roles.ROLE_OWNER)
    db.commit()
    with pytest.raises(PersonNotProfilableError):
        _payload(db, person)


def test_admin_target_is_profilable(db):
    person = _user(db, role=roles.ROLE_ADMIN)
    db.commit()
    assert _payload(db, person).user.role == roles.ROLE_ADMIN


def test_unknown_user_raises_not_found(db):
    with pytest.raises(UserNotFoundError):
        person_week.week_payload(db, user_id=uuid.uuid4(), week_start=MONDAY, now=NOW)


def test_completed_carries_status_and_archived(db):
    tech = _user(db)
    _wo(db, tech, completed_at=_utc(15, 15), crew=[tech], number="WO-L")
    gone = _wo(db, tech, completed_at=_utc(15, 16), crew=[tech], number="WO-A")
    gone.archived_at = NOW
    db.commit()
    day = _day(_payload(db, tech), MONDAY + timedelta(days=1))
    by_number = {c.number: c for c in day.completed}
    assert (by_number["WO-L"].status, by_number["WO-L"].archived) == ("completed", False)
    assert (by_number["WO-A"].status, by_number["WO-A"].archived) == ("completed", True)
    from app.schemas.attendance import PersonWeekCompleted
    assert PersonWeekCompleted.model_validate(by_number["WO-A"]).archived is True



def test_paid_and_lunch_ride_on_each_day_and_the_week(db):
    tech = _user(db)
    _punch(db, tech, _utc(14, 13), _utc(14, 21))
    db.commit()
    payload = _payload(db, tech)
    monday = _day(payload, MONDAY)
    assert (monday.clocked_minutes, monday.lunch_minutes, monday.paid_minutes) == (480, 30, 450)
    assert payload.total_paid_minutes == 450


# --- 2026-10-16: uncharged, pending, edit marks ---------------------------

def test_uncharged_is_floored_at_zero(db):
    tech = _user(db)
    wo = _wo(db, tech, crew=[tech])
    _punch(db, tech, _utc(14, 13), _utc(14, 15))                 # 2h, no lunch
    db.add(WorkOrderLabor(id=uuid.uuid4(), work_order_id=wo.id, technician_id=tech.id,
                          minutes=180, recorded_by_id=tech.id, created_at=_utc(14, 18)))
    db.commit()
    monday = _day(_payload(db, tech), MONDAY)
    assert (monday.paid_minutes, monday.charged_minutes) == (120, 180)
    assert monday.uncharged_minutes == 0


def test_pending_day_is_shown_but_left_out_of_week_totals(db):
    tech = _user(db)
    _punch(db, tech, _utc(14, 13), _utc(14, 21))
    _punch(db, tech, _utc(15, 13), _utc(15, 21), needs_review=True)
    db.commit()
    payload = _payload(db, tech)
    tuesday = _day(payload, MONDAY + timedelta(days=1))
    assert tuesday.pending_review is True and tuesday.paid_minutes == 450
    assert _day(payload, MONDAY).pending_review is False
    assert payload.total_paid_minutes == 450
    assert payload.total_clocked_minutes == 480
    assert payload.total_uncharged_minutes == 450


def test_punch_marks_ride_the_day(db):
    from app.models import AttendancePunchEdit
    tech, admin = _user(db), _user(db, role=roles.ROLE_ADMIN)
    punch = _punch(db, tech, _utc(14, 13), _utc(14, 21))
    db.add(AttendancePunchEdit(id=uuid.uuid4(), punch_id=punch.id, edited_by_id=admin.id,
                               edited_at=_utc(15, 1), field="ended_at",
                               old_value="a", new_value="b"))
    db.commit()
    marks = _day(_payload(db, tech), MONDAY).punch_marks
    assert [(m.punch_id, m.tags) for m in marks] == [(punch.id, ["admin"])]


def test_adjustment_carries_labor_id_and_recorded_by_self(db):
    tech, admin = _user(db), _user(db, role=roles.ROLE_ADMIN)
    wo = _wo(db, tech, crew=[tech])
    own = WorkOrderLabor(id=uuid.uuid4(), work_order_id=wo.id, technician_id=tech.id,
                         minutes=30, recorded_by_id=tech.id, created_at=_utc(14, 18))
    keyed = WorkOrderLabor(id=uuid.uuid4(), work_order_id=wo.id, technician_id=tech.id,
                           minutes=20, recorded_by_id=admin.id, created_at=_utc(14, 19))
    db.add_all([own, keyed]); db.commit()
    adjustments = _day(_payload(db, tech), MONDAY).adjustments
    assert [(a.labor_id, a.recorded_by_self) for a in adjustments] == [
        (own.id, True), (keyed.id, False)]
