"""Status codes for the Admin punch writes (spec §9), over real HTTP.

TestClient, never a direct handler call: this repo has been bitten once by
FastAPI parsing a signature differently than a direct call does.
"""
import os, sys, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.database import get_db
from app.domain import labor_day
from app.main import app
from app.models import AttendancePunch, User
from app.services import auth as auth_service


def _seed_user(db, role="technician"):
    user = User(username=f"u-{uuid.uuid4().hex[:10]}",
                password_hash=auth_service.hash_password("hunter2"), role=role)
    db.add(user); db.flush()
    return user


def _as(db, user):
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    client.cookies.set("session", auth_service.create_session(db, user))
    return client


def _base(room_hours=9):
    """The moment the punches here count back from: now, or 23:00 Central
    yesterday while today is younger than `room_hours`. A punch may not cross
    Central midnight (M4), so "N hours ago" needs N hours of one day behind it."""
    now = datetime.now(timezone.utc)
    day_start, _ = labor_day.day_bounds(labor_day.central_date_of(now))
    if now - day_start >= timedelta(hours=room_hours):
        return now
    return day_start - timedelta(hours=1)


def _punch(db, user, *, hours_ago, length_hours=3, room_hours=9):
    now = _base(room_hours)
    punch = AttendancePunch(
        id=uuid.uuid4(), user_id=user.id,
        started_at=now - timedelta(hours=hours_ago),
        ended_at=now - timedelta(hours=hours_ago - length_hours),
        start_source="manual", end_source="manual")
    db.add(punch); db.flush()
    return punch


def test_an_admin_adds_a_punch(db):
    admin, tech = _seed_user(db, "admin"), _seed_user(db); db.commit()
    now = _base()
    body = {"user_id": str(tech.id),
            "started_at": (now - timedelta(hours=5)).isoformat(),
            "ended_at": (now - timedelta(hours=2)).isoformat(),
            "reason": "paper timesheet"}
    try:
        with _as(db, admin) as client:
            response = client.post("/hub/attendance/punches", json=body)
    finally:
        del app.dependency_overrides[get_db]
    assert response.status_code == 200
    assert response.json()["end_source"] == "admin_edit"


def test_techfm_oa_may_look_right_but_not_waive_lunch(db):
    # Team Lead+ (OA outranks Team Lead) accepts a flag; the waiver is Admin+.
    oa, tech = _seed_user(db, "techfm_oa"), _seed_user(db)
    punch = _punch(db, tech, hours_ago=6)
    punch.needs_review = True; db.commit()
    try:
        with _as(db, oa) as client:
            looks_right = client.patch(f"/hub/attendance/punches/{punch.id}",
                                       json={"needs_review": False})
            waiver = client.patch(f"/hub/attendance/punches/{punch.id}",
                                  json={"lunch_waived": True})
    finally:
        del app.dependency_overrides[get_db]
    assert looks_right.status_code == 200
    assert waiver.status_code == 403


def test_a_future_end_is_400(db):
    admin, tech = _seed_user(db, "admin"), _seed_user(db)
    punch = _punch(db, tech, hours_ago=6); db.commit()
    ahead = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    try:
        with _as(db, admin) as client:
            response = client.patch(f"/hub/attendance/punches/{punch.id}",
                                    json={"ended_at": ahead})
    finally:
        del app.dependency_overrides[get_db]
    assert response.status_code == 400


def test_an_overlap_is_409(db):
    admin, tech = _seed_user(db, "admin"), _seed_user(db)
    first = _punch(db, tech, hours_ago=9)
    second = _punch(db, tech, hours_ago=4); db.commit()
    try:
        with _as(db, admin) as client:
            response = client.patch(
                f"/hub/attendance/punches/{second.id}",
                json={"started_at": (first.ended_at - timedelta(minutes=30)).isoformat()})
    finally:
        del app.dependency_overrides[get_db]
    assert response.status_code == 409


def test_an_unknown_punch_is_404(db):
    admin = _seed_user(db, "admin"); db.commit()
    try:
        with _as(db, admin) as client:
            response = client.delete(f"/hub/attendance/punches/{uuid.uuid4()}")
    finally:
        del app.dependency_overrides[get_db]
    assert response.status_code == 404


def test_delete_then_the_week_no_longer_shows_it(db):
    admin, tech = _seed_user(db, "admin"), _seed_user(db)
    punch = _punch(db, tech, hours_ago=5); db.commit()
    try:
        with _as(db, admin) as client:
            assert client.delete(
                f"/hub/attendance/punches/{punch.id}?reason=duplicate").status_code == 200
            week = client.get("/hub/attendance/week").json()
    finally:
        del app.dependency_overrides[get_db]
    ids = [entry["id"] for row in week["rows"] for day in row["days"]
           for entry in day["punches"]]
    assert str(punch.id) not in ids


def test_patch_lunch_waived_is_200(db):
    admin, tech = _seed_user(db, "admin"), _seed_user(db)
    start = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)      # 7:00 AM CDT Mon
    punch = AttendancePunch(id=uuid.uuid4(), user_id=tech.id, started_at=start,
                            ended_at=start + timedelta(hours=8),
                            start_source="manual", end_source="manual")
    db.add(punch); db.commit()
    try:
        with _as(db, admin) as client:
            response = client.patch(f"/hub/attendance/punches/{punch.id}",
                                    json={"lunch_waived": True})
            crossing = client.patch(f"/hub/attendance/punches/{punch.id}", json={
                "ended_at": (start + timedelta(hours=17, minutes=1)).isoformat()})
    finally:
        del app.dependency_overrides[get_db]
    assert response.status_code == 200
    db.refresh(punch)
    assert punch.lunch_waived is True
    assert crossing.status_code == 400


def test_technician_patches_own_punch_200(db):
    # ponytail: 2-hour-old punch; would cross into last week only in the first
    # two hours of a Central Monday.
    tech = _seed_user(db)
    punch = _punch(db, tech, hours_ago=2, length_hours=1, room_hours=2); db.commit()
    new_end = (punch.ended_at + timedelta(minutes=30)).isoformat()
    try:
        with _as(db, tech) as client:
            response = client.patch(f"/hub/attendance/punches/{punch.id}",
                                    json={"ended_at": new_end})
    finally:
        del app.dependency_overrides[get_db]
    assert response.status_code == 200
    assert response.json()["end_source"] == "self_edit"


# --- Accepting one auto-stopped work-order clock ---------------------------

def _labor_session(db, tech, *, ended_hours_ago=None, started_hours_ago=14, auto_closed=True,
                   with_labor=False):
    from app.models import WorkOrderLabor, WorkOrderLaborSession
    from app.services import work_orders as wos
    now = datetime.now(timezone.utc)
    order = wos.get_or_create_work_order(
        db, number=f"WO-{uuid.uuid4().hex[:8]}", created_by_id=tech.id,
        assigned_to_id=tech.id)
    ended = None if ended_hours_ago is None else now - timedelta(hours=ended_hours_ago)
    started = now - timedelta(hours=started_hours_ago)
    session = WorkOrderLaborSession(
        id=uuid.uuid4(), work_order_id=order.id, technician_id=tech.id,
        started_at=started, ended_at=ended,
        auto_closed_at=ended if auto_closed else None)
    if with_labor:
        labor = WorkOrderLabor(id=uuid.uuid4(), work_order_id=order.id, technician_id=tech.id,
                               minutes=int((ended - started).total_seconds() // 60),
                               recorded_by_id=tech.id)
        db.add(labor); db.flush()
        session.labor_id = labor.id
    db.add(session); db.commit()
    return session


def _review(db, actor, session_id, body=None):
    try:
        with _as(db, actor) as client:
            url = f"/hub/attendance/sessions/{session_id}/review"
            return client.post(url, json=body) if body is not None else client.post(url)
    finally:
        del app.dependency_overrides[get_db]


def test_a_team_lead_accepts_an_auto_stopped_clock(db):
    from app.models import WorkOrderLaborSession
    lead, tech = _seed_user(db, "supervisor"), _seed_user(db)
    session = _labor_session(db, tech, ended_hours_ago=2)

    response = _review(db, lead, session.id)

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == str(session.id) and body["reviewed_at"]
    db.expire_all()
    assert db.get(WorkOrderLaborSession, session.id).reviewed_at is not None


def test_a_technician_cannot_accept_a_clock(db):
    tech = _seed_user(db)
    session = _labor_session(db, tech, ended_hours_ago=2)
    assert _review(db, tech, session.id).status_code == 403


def test_accepting_an_unknown_clock_is_404(db):
    lead = _seed_user(db, "supervisor"); db.commit()
    assert _review(db, lead, uuid.uuid4()).status_code == 404


def test_accepting_a_clock_twice_is_404(db):
    lead, tech = _seed_user(db, "supervisor"), _seed_user(db)
    session = _labor_session(db, tech, ended_hours_ago=2)
    assert _review(db, lead, session.id).status_code == 200
    assert _review(db, lead, session.id).status_code == 404


def test_accepting_a_manually_stopped_clock_is_404(db):
    lead, tech = _seed_user(db, "supervisor"), _seed_user(db)
    session = _labor_session(db, tech, ended_hours_ago=2, auto_closed=False)
    assert _review(db, lead, session.id).status_code == 404


def test_a_running_over_cap_clock_is_swept_then_accepted(db):
    from app.models import WorkOrderLaborSession
    lead, tech = _seed_user(db, "supervisor"), _seed_user(db)
    session = _labor_session(db, tech, started_hours_ago=20, auto_closed=False)

    response = _review(db, lead, session.id)

    assert response.status_code == 200
    db.expire_all()
    row = db.get(WorkOrderLaborSession, session.id)
    assert row.ended_at is not None and row.auto_closed_at is not None
    assert row.reviewed_at is not None


def test_a_running_clock_inside_the_cap_is_404(db):
    lead, tech = _seed_user(db, "supervisor"), _seed_user(db)
    session = _labor_session(db, tech, started_hours_ago=2, auto_closed=False)
    assert _review(db, lead, session.id).status_code == 404


def test_a_team_lead_clears_a_punch_flag_over_http(db):
    lead, tech = _seed_user(db, "supervisor"), _seed_user(db)
    punch = _punch(db, tech, hours_ago=6)
    punch.needs_review = True; db.commit()
    try:
        with _as(db, lead) as client:
            looks_right = client.patch(f"/hub/attendance/punches/{punch.id}",
                                       json={"needs_review": False})
            waiver = client.patch(f"/hub/attendance/punches/{punch.id}",
                                  json={"lunch_waived": True})
    finally:
        del app.dependency_overrides[get_db]
    assert looks_right.status_code == 200
    assert waiver.status_code == 403


def test_a_technician_is_refused_looks_right_over_http(db):
    tech = _seed_user(db)
    punch = _punch(db, tech, hours_ago=2, length_hours=1, room_hours=2)
    punch.needs_review = True; db.commit()
    try:
        with _as(db, tech) as client:
            response = client.patch(f"/hub/attendance/punches/{punch.id}",
                                    json={"needs_review": False})
    finally:
        del app.dependency_overrides[get_db]
    assert response.status_code == 403


def test_bulk_review_route_is_gone(db):
    admin = _seed_user(db, "admin"); db.commit()
    try:
        with _as(db, admin) as client:
            response = client.post("/hub/attendance/week/review")
    finally:
        del app.dependency_overrides[get_db]
    assert response.status_code in (404, 405)


# --- Setting the real stop while accepting ---------------------------------

def test_a_team_lead_sets_the_real_stop(db):
    from app.models import WorkOrderLabor, WorkOrderLaborSession
    lead, tech = _seed_user(db, "supervisor"), _seed_user(db)
    session = _labor_session(db, tech, ended_hours_ago=2, with_labor=True)
    new_end = session.started_at + timedelta(hours=8, minutes=30)

    response = _review(db, lead, session.id, {"ended_at": new_end.isoformat()})

    assert response.status_code == 200
    db.expire_all()
    row = db.get(WorkOrderLaborSession, session.id)
    assert row.ended_at == new_end and row.reviewed_at is not None
    assert row.auto_closed_at is not None
    labor = db.get(WorkOrderLabor, row.labor_id)
    assert labor.minutes == 510 and labor.recorded_by_id == lead.id
    assert "corrected the stop time to" in row.work_order.notes


def test_a_stop_before_the_start_is_400(db):
    from app.models import WorkOrderLaborSession
    lead, tech = _seed_user(db, "supervisor"), _seed_user(db)
    session = _labor_session(db, tech, ended_hours_ago=2, with_labor=True)
    response = _review(db, lead, session.id, {"ended_at": session.started_at.isoformat()})
    assert response.status_code == 400
    db.expire_all()
    assert db.get(WorkOrderLaborSession, session.id).reviewed_at is None


def test_a_stop_after_the_auto_stop_is_400(db):
    lead, tech = _seed_user(db, "supervisor"), _seed_user(db)
    session = _labor_session(db, tech, ended_hours_ago=2, with_labor=True)
    late = session.ended_at + timedelta(minutes=1)
    assert _review(db, lead, session.id, {"ended_at": late.isoformat()}).status_code == 400


def test_a_stop_with_no_labor_line_still_accepts(db):
    from app.models import WorkOrderLaborSession
    lead, tech = _seed_user(db, "supervisor"), _seed_user(db)
    session = _labor_session(db, tech, ended_hours_ago=2)
    new_end = session.started_at + timedelta(hours=3)
    response = _review(db, lead, session.id, {"ended_at": new_end.isoformat()})
    assert response.status_code == 200
    db.expire_all()
    row = db.get(WorkOrderLaborSession, session.id)
    assert row.ended_at == new_end and row.reviewed_at is not None


def test_an_empty_body_accepts_as_is(db):
    from app.models import WorkOrderLaborSession
    lead, tech = _seed_user(db, "supervisor"), _seed_user(db)
    session = _labor_session(db, tech, ended_hours_ago=2, with_labor=True)
    before = session.ended_at
    assert _review(db, lead, session.id, {}).status_code == 200
    db.expire_all()
    assert db.get(WorkOrderLaborSession, session.id).ended_at == before


def test_a_technician_cannot_set_a_stop(db):
    tech = _seed_user(db)
    session = _labor_session(db, tech, ended_hours_ago=2, with_labor=True)
    new_end = session.started_at + timedelta(hours=3)
    assert _review(db, tech, session.id, {"ended_at": new_end.isoformat()}).status_code == 403
