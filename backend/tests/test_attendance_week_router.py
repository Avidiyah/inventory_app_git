"""`GET /hub/attendance/week` at the route boundary.

Every case goes through `TestClient` rather than calling the handler
directly -- this repo has been bitten once by FastAPI parsing a signature
differently than a direct call does.
"""
import os, sys, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone

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


def test_an_admin_reads_the_week(db):
    admin = _seed_user(db, role="admin", first="Dee", last="Ops")
    tech = _seed_user(db)
    db.add(AttendancePunch(
        id=uuid.uuid4(), user_id=tech.id,
        started_at=datetime(2026, 9, 14, 13, 0, tzinfo=timezone.utc),
        ended_at=datetime(2026, 9, 14, 21, 0, tzinfo=timezone.utc),
        start_source="manual", end_source="manual"))
    db.commit()
    try:
        with _as(db, admin) as client:
            response = client.get("/hub/attendance/week", params={"week": "2026-09-14"})
    finally:
        del app.dependency_overrides[get_db]

    assert response.status_code == 200
    body = response.json()
    assert body["week_start"] == "2026-09-14"
    assert body["week_end"] == "2026-09-20"
    assert len(body["days"]) == 7
    row = next(r for r in body["rows"] if r["user"]["id"] == str(tech.id))
    assert row["total_minutes"] == 480
    assert row["days"][0]["punches"][0]["minutes"] == 480


def test_techfm_oa_is_refused(db):
    # D1: this is the pay record, and it sits above the rest of the admin
    # toolkit that TechFM OA holds.
    oa = _seed_user(db, role="techfm_oa", first="Oa", last="Person")
    db.commit()
    try:
        with _as(db, oa) as client:
            response = client.get("/hub/attendance/week", params={"week": "2026-09-14"})
    finally:
        del app.dependency_overrides[get_db]
    assert response.status_code == 403


def test_a_technician_is_refused(db):
    tech = _seed_user(db)
    db.commit()
    try:
        with _as(db, tech) as client:
            response = client.get("/hub/attendance/week")
    finally:
        del app.dependency_overrides[get_db]
    assert response.status_code == 403


def test_a_non_monday_is_422(db):
    admin = _seed_user(db, role="admin", first="Dee", last="Ops")
    db.commit()
    try:
        with _as(db, admin) as client:
            response = client.get("/hub/attendance/week", params={"week": "2026-09-15"})
    finally:
        del app.dependency_overrides[get_db]
    assert response.status_code == 422


def test_no_week_means_the_week_in_progress(db):
    admin = _seed_user(db, role="admin", first="Dee", last="Ops")
    db.commit()
    try:
        with _as(db, admin) as client:
            body = client.get("/hub/attendance/week").json()
    finally:
        del app.dependency_overrides[get_db]
    assert datetime.fromisoformat(body["week_start"]).weekday() == 0
