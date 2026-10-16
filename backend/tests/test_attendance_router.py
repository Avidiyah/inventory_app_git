"""Status codes at the route boundary (spec 9), over real HTTP.

Every case goes through `TestClient` rather than calling the handler
directly -- this repo has been bitten once by FastAPI parsing a signature
differently than a direct call does.
"""
import os, sys, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.database import get_db
from app.domain import attendance as attendance_domain
from app.main import app
from app.models import AttendancePunch, User
from app.services import attendance as attendance_service
from app.services import auth as auth_service


def _seed_user(db, role="technician"):
    user = User(username=f"u-{uuid.uuid4().hex[:10]}",
                password_hash=auth_service.hash_password("hunter2"), role=role)
    db.add(user); db.flush()
    return user


def _client(db, token):
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    client.cookies.set("session", token)
    return client


def _as(db, user):
    return _client(db, auth_service.create_session(db, user))


def test_me_reports_no_punch_for_a_fresh_user(db):
    user = _seed_user(db); db.commit()
    try:
        with _as(db, user) as client:
            body = client.get("/attendance/me").json()
    finally:
        del app.dependency_overrides[get_db]
    assert body["open_punch"] is None
    assert body["clocked_minutes_today"] == 0


def test_punch_in_then_me_reports_the_open_punch(db):
    user = _seed_user(db); db.commit()
    try:
        with _as(db, user) as client:
            assert client.post("/attendance/punch-in").status_code == 200
            body = client.get("/attendance/me").json()
    finally:
        del app.dependency_overrides[get_db]
    assert body["open_punch"]["start_source"] == "manual"
    assert "stale" not in body["open_punch"]
    assert [p["id"] for p in body["week_punches"]] == [body["open_punch"]["id"]]
    assert body["week_punches"][0]["tags"] == []


def test_a_second_punch_in_is_409(db):
    user = _seed_user(db); db.commit()
    try:
        with _as(db, user) as client:
            client.post("/attendance/punch-in")
            response = client.post("/attendance/punch-in")
    finally:
        del app.dependency_overrides[get_db]
    assert response.status_code == 409
    assert isinstance(response.json()["detail"], str)


def test_punch_out_without_a_punch_is_404(db):
    user = _seed_user(db); db.commit()
    try:
        with _as(db, user) as client:
            response = client.post("/attendance/punch-out")
    finally:
        del app.dependency_overrides[get_db]
    assert response.status_code == 404


def test_the_self_close_route_is_gone(db):
    user = _seed_user(db); db.commit()
    try:
        with _as(db, user) as client:
            response = client.post("/attendance/self-close", json={
                "ended_at": datetime.now(timezone.utc).isoformat()})
    finally:
        del app.dependency_overrides[get_db]
    assert response.status_code in (404, 405)


def test_every_attendance_route_requires_a_session(db):
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            assert client.get("/attendance/me").status_code == 401
            assert client.post("/attendance/punch-in").status_code == 401
    finally:
        del app.dependency_overrides[get_db]


def test_a_forgotten_punch_does_not_block_the_work_order_start(db):
    from app.services import work_orders as wo_service
    admin, tech = _seed_user(db, "admin"), _seed_user(db)
    order = wo_service.get_or_create_work_order(
        db, number=f"WO-ATT-{uuid.uuid4().hex[:8]}", created_by_id=admin.id,
        assigned_to_id=tech.id)
    old = AttendancePunch(user_id=tech.id,
                          started_at=datetime.now(timezone.utc) - timedelta(days=2),
                          start_source=attendance_domain.START_SOURCE_MANUAL)
    db.add(old)
    db.commit()
    try:
        with _as(db, tech) as client:
            response = client.post(f"/work-orders/{order.id}/tracking/start")
    finally:
        del app.dependency_overrides[get_db]
    assert response.status_code == 200
    db.refresh(old)
    assert old.end_source == attendance_domain.END_SOURCE_AUTO_CLOCK_OUT


def test_starting_a_work_order_clock_off_shift_opens_a_punch(db):
    from app.services import work_orders as wo_service
    admin, tech = _seed_user(db, "admin"), _seed_user(db)
    order = wo_service.get_or_create_work_order(
        db, number=f"WO-ATT-{uuid.uuid4().hex[:8]}", created_by_id=admin.id,
        assigned_to_id=tech.id)
    db.commit()
    try:
        with _as(db, tech) as client:
            assert client.post(f"/work-orders/{order.id}/tracking/start").status_code == 200
            body = client.get("/attendance/me").json()
    finally:
        del app.dependency_overrides[get_db]
    assert body["open_punch"]["start_source"] == "auto_work_order"
