"""`GET /hub/attendance/live` -- the roster, at the Admin floor.

Same idiom as `test_attendance_week_router.py`: every case goes through
`TestClient` rather than calling the handler directly.
"""
import os, sys, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import AttendancePunch, User
from app.services import auth as auth_service


def _seed_user(db, role="technician", first="Ann", last="Lee"):
    user = User(username=f"u-{uuid.uuid4().hex[:10]}",
                password_hash=auth_service.hash_password("hunter2"),
                role=role, first_name=first, last_name=last)
    db.add(user); db.flush()
    return user


def _as(db, user):
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    client.cookies.set("session", auth_service.create_session(db, user))
    return client


def _get(db, user):
    try:
        with _as(db, user) as client:
            return client.get("/hub/attendance/live")
    finally:
        del app.dependency_overrides[get_db]


def test_the_roster_is_team_lead_and_above(db):
    # 2026-10-22: Team Leads edit anyone's hours, so they read the roster.
    person = _seed_user(db, role="technician")
    db.commit()
    assert _get(db, person).status_code == 403
    for role in ("supervisor", "techfm_oa", "admin"):
        person = _seed_user(db, role=role, first="Dee", last="Ops")
        db.commit()
        assert _get(db, person).status_code == 200, role


def test_the_roster_serialises_both_lists_and_the_three_counts(db):
    admin = _seed_user(db, role="admin", first="Dee", last="Ops")
    db.commit()
    body = _get(db, admin).json()
    assert set(body) == {
        "server_now", "idle_red_minutes", "on_shift", "absent",
        "on_shift_count", "charging_count", "idle_count",
    }
    assert body["idle_red_minutes"] == 10
    assert isinstance(body["on_shift"], list)
    assert isinstance(body["absent"], list)


def test_an_on_shift_entry_carries_the_two_tick_anchors(db):
    admin = _seed_user(db, role="admin", first="Dee", last="Ops")
    tech = _seed_user(db)
    db.add(AttendancePunch(
        id=uuid.uuid4(), user_id=tech.id,
        started_at=datetime.now(timezone.utc) - timedelta(hours=1),
        ended_at=None, start_source="manual"))
    db.commit()
    entry = next(
        e for e in _get(db, admin).json()["on_shift"]
        if e["user"]["id"] == str(tech.id)
    )
    assert set(entry) == {
        "user", "state", "punch_started_at", "idle_since", "idle_minutes",
        "charging_since", "work_order_number",
    }
    assert entry["punch_started_at"] is not None
    # Exactly one of the two anchors is set on any on-shift card.
    assert (entry["idle_since"] is None) != (entry["charging_since"] is None)
