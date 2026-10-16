"""`GET /hub/attendance/export` at the route boundary.

Through `TestClient`, like every other route test here: a direct handler call
does not exercise `Query` validation, which is where the non-Monday 422 comes
from.
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


def _seed_week(db):
    """One technician with a plain eight-hour Monday."""
    tech = _seed_user(db)
    db.add(AttendancePunch(
        id=uuid.uuid4(), user_id=tech.id,
        started_at=datetime(2026, 9, 14, 13, 0, tzinfo=timezone.utc),
        ended_at=datetime(2026, 9, 14, 21, 0, tzinfo=timezone.utc),
        start_source="manual", end_source="manual"))
    return tech


def _get(db, user, url):
    db.commit()
    try:
        with _as(db, user) as client:
            return client.get(url)
    finally:
        del app.dependency_overrides[get_db]


def test_the_export_is_csv_with_the_week_in_its_filename(db):
    admin = _seed_user(db, role="admin", first="Dee", last="Ops")
    _seed_week(db)

    response = _get(db, admin, "/hub/attendance/export?week=2026-09-14")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"] == (
        'attachment; filename="attendance_2026-09-14.csv"'
    )


def test_every_person_gets_the_same_eight_metric_rows(db):
    admin = _seed_user(db, role="admin", first="Dee", last="Ops")
    _seed_week(db)

    lines = _get(db, admin, "/hub/attendance/export?week=2026-09-14").text.splitlines()

    assert lines[0].split(",")[:2] == ["Person", "Metric"]
    assert lines[0].split(",")[-1] == "Week"
    metrics = [line.split(",")[1] for line in lines[1:9]]
    assert metrics == [
        "Clocked", "Lunch", "Paid", "Charged", "Off job", "Charged outside shift",
        "Adjustments", "Pending review",
    ]


def test_the_figures_are_h_mm_and_the_last_block_is_the_company_total(db):
    admin = _seed_user(db, role="admin", first="Dee", last="Ops")
    tech = _seed_week(db)

    lines = _get(db, admin, "/hub/attendance/export?week=2026-09-14").text.splitlines()

    # The grid holds every live crew member, so find this week's seeded one
    # rather than trusting a row position.
    clocked = next(
        line for line in lines
        if line.startswith(f"{tech.full_name},Clocked,")
    )
    assert clocked.split(",")[2] == "8:00"      # Monday, the seeded 8-hour shift
    assert clocked.split(",")[-1] == "8:00"     # and the week column
    lunch = next(line for line in lines if line.startswith(f"{tech.full_name},Lunch,"))
    paid = next(line for line in lines if line.startswith(f"{tech.full_name},Paid,"))
    assert lunch.split(",")[2] == "0:30" and paid.split(",")[2] == "7:30"
    assert lines[-7].split(",")[0] == "Company total"


def test_a_non_monday_is_422_exactly_as_the_week_read_is(db):
    admin = _seed_user(db, role="admin", first="Dee", last="Ops")
    assert _get(db, admin, "/hub/attendance/export?week=2026-09-15").status_code == 422


def test_below_admin_is_403(db):
    # D1: the pay record sits above the rest of the admin toolkit.
    oa = _seed_user(db, role="techfm_oa", first="Oa", last="Person")
    assert _get(db, oa, "/hub/attendance/export?week=2026-09-14").status_code == 403


def test_csv_week_column_skips_pending_and_marks_it(db):
    admin = _seed_user(db, role="admin", first="Dee", last="Ops")
    tech = _seed_week(db)
    db.add(AttendancePunch(
        id=uuid.uuid4(), user_id=tech.id,
        started_at=datetime(2026, 9, 15, 13, 0, tzinfo=timezone.utc),
        ended_at=datetime(2026, 9, 15, 21, 0, tzinfo=timezone.utc),
        start_source="manual", end_source="manual", needs_review=True))

    lines = _get(db, admin, "/hub/attendance/export?week=2026-09-14").text.splitlines()

    clocked = next(line for line in lines if line.startswith(f"{tech.full_name},Clocked,"))
    cells = clocked.split(",")
    assert cells[3] == "8:00"           # Tuesday still printed
    assert cells[-1] == "8:00"          # but only Monday reaches the week
    pending = next(line for line in lines
                   if line.startswith(f"{tech.full_name},Pending review,")).split(",")
    assert pending[2:4] == ["", "yes"]
