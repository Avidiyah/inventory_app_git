"""Tutorial progress routes (0b spec 5.2), over real HTTP via TestClient."""

import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

from app.database import get_db
from app.domain import tutorials as rules
from app.main import app
from app.models import TutorialProgress, User
from app.services import auth as auth_service

KEY = "work-orders.card.notes"


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


def _run(db, user, fn):
    """Run `fn(client)` as `user`, always removing the db override."""
    try:
        with _as(db, user) as client:
            return fn(client)
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_me_is_empty_for_a_new_user_and_unauthenticated_is_401(db):
    user = _seed_user(db); db.commit()
    assert _run(db, user, lambda c: c.get("/tutorials/progress/me").json()) == []
    try:
        app.dependency_overrides[get_db] = lambda: db
        assert TestClient(app).get("/tutorials/progress/me").status_code == 401
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_seen_then_completed_and_rows_are_private_to_the_caller(db):
    a, b = _seed_user(db), _seed_user(db); db.commit()

    def flow(client):
        url = f"/tutorials/progress/{KEY}"
        r1 = client.put(url, json={"event": "seen"})
        mid = client.get("/tutorials/progress/me").json()
        r2 = client.put(url, json={"event": "completed"})
        return r1, mid, r2, client.get("/tutorials/progress/me").json()

    r1, mid, r2, end = _run(db, a, flow)
    assert (r1.status_code, r2.status_code) == (204, 204)
    assert mid[0]["key"] == KEY and mid[0]["seen_at"] and mid[0]["completed_at"] is None
    assert end[0]["completed_at"] is not None
    assert _run(db, b, lambda c: c.get("/tutorials/progress/me").json()) == []


def test_bad_key_bad_event_and_the_501st_key(db):
    user = _seed_user(db)
    now = datetime.now(timezone.utc)
    db.add_all(TutorialProgress(user_id=user.id, script_key=f"k{i}", seen_at=now)
               for i in range(rules.MAX_ROWS_PER_USER))
    db.commit()

    def calls(client):
        return (
            client.put("/tutorials/progress/Bad_Key", json={"event": "seen"}).status_code,
            client.put(f"/tutorials/progress/{KEY}", json={"event": "done"}).status_code,
            client.put("/tutorials/progress/one-too-many", json={"event": "seen"}).status_code,
        )

    assert _run(db, user, calls) == (400, 422, 400)


def test_users_route_is_supervisor_plus_and_lists_active_completed_only(db):
    tech, sup = _seed_user(db), _seed_user(db, "supervisor")
    gone = _seed_user(db); db.commit()
    for who, ev in ((tech, "completed"), (gone, "completed"), (sup, "seen")):
        _run(db, who, lambda c, ev=ev: c.put(f"/tutorials/progress/{KEY}", json={"event": ev}))
    gone.archived_at = datetime.now(timezone.utc); db.commit()

    assert _run(db, tech, lambda c: c.get("/tutorials/progress/users")).status_code == 403
    body = _run(db, sup, lambda c: c.get("/tutorials/progress/users")).json()

    assert body[str(tech.id)] == [KEY]
    assert str(gone.id) not in body and str(sup.id) not in body
