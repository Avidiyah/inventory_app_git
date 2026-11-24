"""Admin+ "Message many": POST /messages/broadcast through a real TestClient."""
import os, sys, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import User
from app.routers import _message_events
from app.services import auth as auth_service
from app.services import notifications as notifications_service

SECRET = "SECRET-broadcast-body"


@pytest.fixture(autouse=True)
def _db_override(db):
    app.dependency_overrides[get_db] = lambda: db
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture(autouse=True)
def emitted(monkeypatch):
    calls = []
    monkeypatch.setattr(_message_events.realtime_service, "emit",
                        lambda envelope, *, user_ids=None: calls.append((envelope, user_ids)) or True)
    return calls


@pytest.fixture(autouse=True)
def notified(monkeypatch):
    calls = []
    monkeypatch.setattr(notifications_service, "notify_chat_message",
                        lambda background, **kwargs: calls.append(kwargs))
    return calls


def _user(db, role="technician", archived=False):
    user = User(username=f"u-{uuid.uuid4().hex[:10]}",
                password_hash=auth_service.hash_password("hunter2"), role=role)
    if archived:
        user.archived_at = datetime.now(timezone.utc)
    db.add(user); db.flush()
    return user


def _as(db, user):
    client = TestClient(app)
    client.cookies.set("session", auth_service.create_session(db, user))
    return client


def _send(db, sender, people, body=SECRET):
    return _as(db, sender).post("/messages/broadcast", json={
        "user_ids": [str(p.id) for p in people], "body": body})


def test_each_person_gets_their_own_direct_chat(db, emitted, notified):
    admin, a, b = _user(db, "admin"), _user(db), _user(db)
    response = _send(db, admin, [a, b, a])  # a duplicate id sends once
    assert response.status_code == 201, response.text
    assert response.json() == {"sent": 2}

    for person in (a, b):
        rows = _as(db, person).get("/messages/conversations").json()
        assert rows["unread_people"] == 1
        [chat] = rows["conversations"]
        assert chat["kind"] == "direct" and chat["last_message"]["body"] == SECRET
    # Each ping and push reaches only that pair, and never carries the text.
    assert sorted(len(ids) for _, ids in emitted) == [2, 2]
    assert sorted(str(n["recipient_ids"][0]) for n in notified) == sorted([str(a.id), str(b.id)])
    assert SECRET not in repr(emitted) + repr(notified)


def test_reuses_an_existing_direct_chat(db):
    owner, a = _user(db, "owner"), _user(db)
    existing = _as(db, owner).post("/messages/direct", json={"user_id": str(a.id)}).json()["id"]
    assert _send(db, owner, [a]).status_code == 201
    [chat] = _as(db, a).get("/messages/conversations").json()["conversations"]
    assert chat["id"] == existing


@pytest.mark.parametrize("role", ["technician", "supervisor", "techfm_oa"])
def test_below_admin_is_refused(db, role):
    assert _send(db, _user(db, role), [_user(db)]).status_code == 403


def test_bad_lists_and_bodies_are_422_and_send_nothing(db):
    admin, a, gone = _user(db, "admin"), _user(db), _user(db, archived=True)
    assert _send(db, admin, []).status_code == 422
    assert _send(db, admin, [admin]).status_code == 422  # only yourself
    assert _send(db, admin, [a], body="   ").status_code == 422
    assert _send(db, admin, [a, gone]).status_code == 422
    assert _as(db, a).get("/messages/conversations").json()["conversations"] == []


def test_signed_out_is_401(db):
    assert TestClient(app).post("/messages/broadcast", json={"user_ids": [], "body": "x"}).status_code == 401
