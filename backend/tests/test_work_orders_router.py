"""Router-boundary tests for the Work Orders list endpoint.

Drives the route over real HTTP rather than calling the handler function
directly, following `test_hub_router.py`'s
`test_graphs_route_accepts_the_default_week_count_over_real_http`: a
direct call never exercises FastAPI's query-string parsing, which is
where this repo has already been bitten once (FastAPI 0.136 / Pydantic
2.13 and int `Literal` params).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import User
from app.services import auth as auth_service
from app.services import work_orders as wos


def _seed_user(db, role):
    user = User(
        username=f"u-{uuid.uuid4().hex[:10]}",
        password_hash=auth_service.hash_password("hunter2"),
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def _numbers(db, token, query):
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            client.cookies.set("session", token)
            response = client.get(f"/work-orders/{query}")
    finally:
        del app.dependency_overrides[get_db]
    assert response.status_code == 200, response.text
    return {card["number"] for card in response.json()}


def test_mine_returns_a_work_order_routed_to_the_caller(db):
    """The deployment bug: an Admin routes a work order to a Supervisor and
    the Supervisor's User Hub "My Work Orders" tab stays empty, because that
    tab filtered on `assigned_to_id` -- which tests worker assignment only
    and cannot see routing."""
    admin = _seed_user(db, "admin")
    supervisor = _seed_user(db, "supervisor")
    prefix = f"WO-HTTP-{uuid.uuid4().hex[:8]}"

    routed = wos.get_or_create_work_order(
        db, number=f"{prefix}-R", created_by_id=admin.id, supervisor_id=supervisor.id
    )
    db.commit()
    token = auth_service.create_session(db, supervisor)

    # Every query carries the number prefix so the assertions stay
    # independent of how many work orders the database already holds --
    # otherwise `MAX_LIST_ROWS` could quietly drop the fixture row.
    assert routed.number in _numbers(db, token, f"?mine=true&q={prefix}")
    # The old hub filter, kept here as the contrast that explains the flag.
    assert routed.number not in _numbers(
        db, token, f"?assigned_to_id={supervisor.id}&q={prefix}"
    )


def test_mine_defaults_to_off(db):
    """Omitting the flag must not silently narrow an Admin's company-wide
    list -- the standalone Work Orders page sends no `mine`."""
    admin = _seed_user(db, "admin")
    other_supervisor = _seed_user(db, "supervisor")
    prefix = f"WO-HTTPOFF-{uuid.uuid4().hex[:8]}"

    someone_elses = wos.get_or_create_work_order(
        db,
        number=f"{prefix}-X",
        created_by_id=admin.id,
        supervisor_id=other_supervisor.id,
    )
    db.commit()
    token = auth_service.create_session(db, admin)

    assert someone_elses.number in _numbers(db, token, f"?q={prefix}")
    assert someone_elses.number not in _numbers(
        db, token, f"?mine=true&q={prefix}"
    )
