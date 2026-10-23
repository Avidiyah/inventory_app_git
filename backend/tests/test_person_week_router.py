"""`GET /hub/people/{user_id}/week` at the route boundary, via TestClient."""
import os, sys, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import User, WorkOrder, WorkOrderLaborSession, WorkOrderTechnician
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


def _get(db, viewer, target_id, **params):
    try:
        with _as(db, viewer) as client:
            return client.get(f"/hub/people/{target_id}/week", params=params)
    finally:
        del app.dependency_overrides[get_db]


def test_an_admin_reads_a_technicians_week(db):
    admin = _seed_user(db, role="admin", first="Dee", last="Ops")
    tech = _seed_user(db)
    wo = WorkOrder(id=uuid.uuid4(), number="WO-9", status="completed",
                   created_by_id=admin.id,
                   completed_at=datetime(2026, 9, 16, 15, 0, tzinfo=timezone.utc))
    db.add(wo); db.flush()
    db.add(WorkOrderTechnician(work_order_id=wo.id, technician_id=tech.id))
    db.commit()
    response = _get(db, admin, tech.id, week="2026-09-14")
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["id"] == str(tech.id)
    assert body["week_start"] == "2026-09-14" and body["week_end"] == "2026-09-20"
    assert len(body["days"]) == 7
    assert body["days"][2]["completed"][0]["number"] == "WO-9"
    assert body["total_completed"] == 1
    assert "billed" not in response.text


def test_week_omitted_is_the_current_week(db):
    admin = _seed_user(db, role="admin")
    tech = _seed_user(db)
    db.commit()
    body = _get(db, admin, tech.id).json()
    assert datetime.fromisoformat(body["week_start"]).weekday() == 0


def test_technician_viewer_is_refused_and_team_lead_reads(db):
    viewer = _seed_user(db, role="technician", first="Vi", last="Ewer")
    lead = _seed_user(db, role="supervisor", first="Le", last="Ad")
    tech = _seed_user(db)
    db.commit()
    assert _get(db, viewer, tech.id, week="2026-09-14").status_code == 403
    assert _get(db, lead, tech.id, week="2026-09-14").status_code == 200


def test_admin_target_is_200(db):
    admin = _seed_user(db, role="admin")
    other = _seed_user(db, role="admin", first="Bo", last="Kay")
    db.commit()
    assert _get(db, admin, other.id, week="2026-09-14").status_code == 200


def test_owner_target_is_403(db):
    admin = _seed_user(db, role="admin")
    owner = _seed_user(db, role="owner")
    db.commit()
    assert _get(db, admin, owner.id, week="2026-09-14").status_code == 403


def test_unknown_user_is_404(db):
    admin = _seed_user(db, role="admin")
    db.commit()
    assert _get(db, admin, uuid.uuid4(), week="2026-09-14").status_code == 404


def test_a_non_monday_is_422(db):
    admin = _seed_user(db, role="admin")
    tech = _seed_user(db)
    db.commit()
    assert _get(db, admin, tech.id, week="2026-09-15").status_code == 422


def test_a_future_week_is_422(db):
    admin = _seed_user(db, role="admin")
    tech = _seed_user(db)
    db.commit()
    future = datetime.now(timezone.utc).date() + timedelta(days=14)
    monday = future - timedelta(days=future.weekday())
    assert _get(db, admin, tech.id, week=monday.isoformat()).status_code == 422


def test_the_read_does_not_sweep_an_open_session(db):
    admin = _seed_user(db, role="admin")
    tech = _seed_user(db)
    wo = WorkOrder(id=uuid.uuid4(), number="WO-open", status="in_progress",
                   created_by_id=admin.id)
    db.add(wo); db.flush()
    session = WorkOrderLaborSession(
        id=uuid.uuid4(), work_order_id=wo.id, technician_id=tech.id,
        started_at=datetime.now(timezone.utc) - timedelta(hours=20))
    db.add(session); db.commit()
    assert _get(db, admin, tech.id).status_code == 200
    db.expire_all()
    assert db.get(WorkOrderLaborSession, session.id).ended_at is None
