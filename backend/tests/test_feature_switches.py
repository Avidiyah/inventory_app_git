"""The Owner's SMR switch over real HTTP: who may flip it, the 404 every SMR
route answers while it is off, and `smr_enabled` on `/auth/me`."""

import uuid

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import User
from app.services import auth as auth_service


def _client(db, role):
    user = User(username=f"u-{uuid.uuid4().hex[:10]}", first_name="Pat", last_name="X",
                password_hash=auth_service.hash_password("hunter2"), role=role)
    db.add(user)
    db.flush()
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    client.cookies.set("session", auth_service.create_session(db, user))
    return client


def test_off_by_default_hides_smr_and_the_owner_turns_it_back_on(db):
    client = _client(db, "owner")
    try:
        assert client.get("/auth/me").json()["smr_enabled"] is False
        assert client.get("/work-orders/smr").status_code == 404

        on = client.put("/feature-switches/smr", json={"enabled": True})
        assert on.status_code == 200 and on.json() == {"enabled": True}
        assert client.get("/auth/me").json()["smr_enabled"] is True
        assert client.get("/work-orders/smr").status_code == 200

        client.put("/feature-switches/smr", json={"enabled": False})
        assert client.get("/work-orders/smr").status_code == 404
    finally:
        del app.dependency_overrides[get_db]


def test_only_the_owner_may_flip_it(db):
    client = _client(db, "admin")
    try:
        assert client.put("/feature-switches/smr", json={"enabled": True}).status_code == 403
    finally:
        del app.dependency_overrides[get_db]
