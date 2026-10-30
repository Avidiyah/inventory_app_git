"""`GET /hub/performance` through the real app: Admin+, the window contract,
and the payload shape the Leaderboards tab renders."""
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


def _get(db, user, **params):
    try:
        with _as(db, user) as client:
            return client.get("/hub/performance", params=params)
    finally:
        del app.dependency_overrides[get_db]


def test_week_payload_shape(db):
    admin = _seed_user(db, role="admin", first="Dee", last="Ops")
    tech = _seed_user(db)
    db.add(AttendancePunch(
        id=uuid.uuid4(), user_id=tech.id,
        started_at=datetime(2026, 9, 14, 13, 0, tzinfo=timezone.utc),
        ended_at=datetime(2026, 9, 14, 21, 0, tzinfo=timezone.utc),
        start_source="manual", end_source="manual"))
    db.commit()
    response = _get(db, admin, window="week", start="2026-09-14")
    assert response.status_code == 200
    body = response.json()
    assert (body["window"], body["start"], body["end"], body["to_date"]) == ("week", "2026-09-14", "2026-09-20", False)
    assert body["weights"] == {"billed": 40, "efficiency": 25, "accuracy": 20, "clean_days": 15}
    assert body["floor_minutes"] == 960
    row = next(r for r in body["rows"] if r["user"]["id"] == str(tech.id))
    assert row["rank"] is None and row["below_floor"] is True
    assert row["clocked_minutes"] == 480
    assert (row["counted_days"], row["active_days"]) == (1, 1)
    assert row["billed_dollars"] == "0.00"
    assert row["day_reasons"] == [] and row["excluded_orders"] == []
    assert set(row["scaled"]) == {"billed", "efficiency", "accuracy", "clean_days"}


def test_reasons_carry_labels(db):
    admin = _seed_user(db, role="admin")
    tech = _seed_user(db)
    db.add(AttendancePunch(
        id=uuid.uuid4(), user_id=tech.id,
        started_at=datetime(2026, 9, 14, 13, 0, tzinfo=timezone.utc),
        ended_at=datetime(2026, 9, 15, 5, 0, tzinfo=timezone.utc),
        start_source="manual", end_source="auto_clock_out", needs_review=False))
    db.commit()
    body = _get(db, admin, window="week", start="2026-09-14").json()
    row = next(r for r in body["rows"] if r["user"]["id"] == str(tech.id))
    assert row["day_reasons"] == [{"code": "punch_estimated", "label": "forgotten clock-out", "days": 1}]


def test_month_default_is_current_month_to_date(db):
    admin = _seed_user(db, role="admin")
    body = _get(db, admin, window="month").json()
    assert body["window"] == "month" and body["start"].endswith("-01")
    assert body["floor_minutes"] == 3600


def test_bad_window_is_422(db):
    admin = _seed_user(db, role="admin")
    assert _get(db, admin, window="year").status_code == 422


def test_non_first_month_start_is_422(db):
    admin = _seed_user(db, role="admin")
    assert _get(db, admin, window="month", start="2026-09-02").status_code == 422


def test_a_technician_is_refused(db):
    tech = _seed_user(db)
    assert _get(db, tech, window="week").status_code == 403
