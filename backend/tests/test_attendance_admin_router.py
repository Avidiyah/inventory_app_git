"""Status codes for the Admin punch writes (spec §9), over real HTTP.

TestClient, never a direct handler call: this repo has been bitten once by
FastAPI parsing a signature differently than a direct call does.
"""
import os, sys, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.database import get_db
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


def _punch(db, user, *, hours_ago, length_hours=3):
    now = datetime.now(timezone.utc)
    punch = AttendancePunch(
        id=uuid.uuid4(), user_id=user.id,
        started_at=now - timedelta(hours=hours_ago),
        ended_at=now - timedelta(hours=hours_ago - length_hours),
        start_source="manual", end_source="manual")
    db.add(punch); db.flush()
    return punch


def test_an_admin_adds_a_punch(db):
    admin, tech = _seed_user(db, "admin"), _seed_user(db); db.commit()
    now = datetime.now(timezone.utc)
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


def test_techfm_oa_is_refused(db):
    oa, tech = _seed_user(db, "techfm_oa"), _seed_user(db)
    punch = _punch(db, tech, hours_ago=6); db.commit()
    try:
        with _as(db, oa) as client:
            response = client.patch(f"/hub/attendance/punches/{punch.id}",
                                    json={"needs_review": False})
    finally:
        del app.dependency_overrides[get_db]
    assert response.status_code == 403


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
