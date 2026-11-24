"""Live messaging routes at the HTTP boundary.

Every case goes through `TestClient` (this repo has been bitten by FastAPI
parsing a signature differently than a direct call does). The realtime emitter
and the push scheduler are replaced with recorders: the routes decide *who* is
told, which is what these tests pin; delivery has its own tests.
"""
import os, sys, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import User
from app.routers import _message_events
from app.services import auth as auth_service
from app.services import notifications as notifications_service

NIL = "00000000-0000-4000-8000-000000000000"
SECRET = "SECRET-gasket-body"


@pytest.fixture(autouse=True)
def _db_override(db):
    app.dependency_overrides[get_db] = lambda: db
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def emitted(monkeypatch):
    """(envelope, user_ids) for every realtime emission."""
    calls = []
    monkeypatch.setattr(
        _message_events.realtime_service, "emit",
        lambda envelope, *, user_ids=None: calls.append((envelope, user_ids)) or True)
    return calls


@pytest.fixture(autouse=True)
def notified(monkeypatch):
    """kwargs of every `notify_chat_message` call; nothing is really queued."""
    calls = []
    monkeypatch.setattr(
        notifications_service, "notify_chat_message",
        lambda background, **kwargs: calls.append(kwargs))
    return calls


def _user(db, role="technician"):
    user = User(username=f"u-{uuid.uuid4().hex[:10]}",
                password_hash=auth_service.hash_password("hunter2"), role=role)
    db.add(user); db.flush()
    return user


def _as(db, user):
    client = TestClient(app)
    client.cookies.set("session", auth_service.create_session(db, user))
    return client


def _direct(client, other):
    response = client.post("/messages/direct", json={"user_id": str(other.id)})
    assert response.status_code == 200
    return response.json()["id"]


def _group(db, starter, others):
    response = _as(db, starter).post("/messages/groups", json={
        "name": "Crew", "member_ids": [str(o.id) for o in others]})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _send(client, chat_id, body=SECRET):
    return client.post(f"/messages/conversations/{chat_id}/messages", json={"body": body})


def test_every_route_requires_a_session(db):
    anon = TestClient(app)
    c = f"/messages/conversations/{NIL}"
    codes = [
        anon.get("/messages/conversations"),
        anon.get(c),
        anon.post(f"{c}/messages", json={"body": "x"}),
        anon.post(f"{c}/read", json={"up_to": 1}),
        anon.post("/messages/direct", json={"user_id": NIL}),
        anon.post("/messages/groups", json={"name": "g", "member_ids": [NIL, NIL]}),
        anon.delete(f"/messages/groups/{NIL}"),
        anon.get("/messages/search?q=ab"),
        anon.get("/messages/people"),
    ]
    assert [r.status_code for r in codes] == [401] * 9


def test_a_non_member_gets_404_never_403(db):
    starter, t1, t2, outsider = _user(db, "supervisor"), _user(db), _user(db), _user(db)
    chat = _group(db, starter, [t1, t2])
    out = _as(db, outsider)
    assert out.get(f"/messages/conversations/{chat}").status_code == 404
    assert _send(out, chat).status_code == 404
    assert out.post(f"/messages/conversations/{chat}/read", json={"up_to": 1}).status_code == 404
    assert out.delete(f"/messages/groups/{chat}").status_code == 404
    # A chat that does not exist is indistinguishable from one the caller is not in.
    assert out.get(f"/messages/conversations/{NIL}").status_code == 404


def test_a_technician_cannot_start_a_group(db):
    tech, a, b = _user(db), _user(db), _user(db)
    response = _as(db, tech).post("/messages/groups", json={
        "name": "Crew", "member_ids": [str(a.id), str(b.id)]})
    assert response.status_code == 403


def test_a_blank_body_is_422(db):
    a, b = _user(db), _user(db)
    client = _as(db, a)
    chat = _direct(client, b)
    assert _send(client, chat, "   ").status_code == 422


def test_send_then_list_shows_the_message_and_one_unread_person(db):
    a, b = _user(db), _user(db)
    ca, cb = _as(db, a), _as(db, b)
    chat = _direct(ca, b)
    assert _send(ca, chat).status_code == 201
    listed = cb.get("/messages/conversations").json()
    assert listed["unread_people"] == 1
    assert [c["id"] for c in listed["conversations"]] == [chat]
    assert listed["conversations"][0]["last_message"]["body"] == SECRET
    assert listed["conversations"][0]["unread_count"] == 1
    assert ca.get("/messages/conversations").json()["unread_people"] == 0


def test_send_emits_to_exactly_the_members_with_no_text(db, emitted):
    a, b = _user(db), _user(db)
    ca = _as(db, a)
    chat = _direct(ca, b)
    emitted.clear()
    _send(ca, chat)
    assert len(emitted) == 1
    envelope, user_ids = emitted[0]
    assert {str(u) for u in user_ids} == {str(a.id), str(b.id)}
    assert SECRET not in str(envelope)


def test_send_queues_a_push_for_everyone_but_the_sender(db, notified):
    a, b = _user(db), _user(db)
    ca = _as(db, a)
    chat = _direct(ca, b)
    _send(ca, chat)
    assert len(notified) == 1
    assert [str(r) for r in notified[0]["recipient_ids"]] == [str(b.id)]
    assert str(notified[0]["conversation_id"]) == chat
    assert SECRET not in str(notified[0])


def test_a_read_that_moves_the_mark_emits_once_and_a_repeat_emits_nothing(db, emitted):
    a, b = _user(db), _user(db)
    ca, cb = _as(db, a), _as(db, b)
    chat = _direct(ca, b)
    last = _send(ca, chat).json()["id"]
    emitted.clear()
    first = cb.post(f"/messages/conversations/{chat}/read", json={"up_to": last})
    assert first.status_code == 200 and first.json() == {"my_read_message_id": last}
    assert len(emitted) == 1
    again = cb.post(f"/messages/conversations/{chat}/read", json={"up_to": last})
    assert again.json() == {"my_read_message_id": last}
    assert len(emitted) == 1


def test_opening_a_direct_chat_from_both_sides_gives_one_chat(db):
    a, b = _user(db), _user(db)
    ca, cb = _as(db, a), _as(db, b)
    ids = [_direct(ca, b), _direct(cb, a), _direct(ca, b)]
    assert len(set(ids)) == 1


def test_ending_a_group_is_204_emits_to_former_members_and_the_chat_is_gone(db, emitted):
    starter, t1, t2 = _user(db, "supervisor"), _user(db), _user(db)
    chat = _group(db, starter, [t1, t2])
    emitted.clear()
    cs = _as(db, starter)
    assert cs.delete(f"/messages/groups/{chat}").status_code == 204
    assert len(emitted) == 1
    assert {str(u) for u in emitted[0][1]} == {str(starter.id), str(t1.id), str(t2.id)}
    assert _as(db, t1).get(f"/messages/conversations/{chat}").status_code == 404


def test_creating_a_group_emits_to_its_members(db, emitted):
    starter, t1, t2 = _user(db, "supervisor"), _user(db), _user(db)
    emitted.clear()
    _group(db, starter, [t1, t2])
    assert len(emitted) == 1
    assert {str(u) for u in emitted[0][1]} == {str(starter.id), str(t1.id), str(t2.id)}


def test_search_needs_two_characters(db):
    client = _as(db, _user(db))
    assert client.get("/messages/search?q=a").status_code == 422
    assert client.get("/messages/search").status_code == 422
    assert client.get("/messages/search?q=ab").status_code == 200


def test_before_and_up_to_must_be_positive_ids(db):
    a, b = _user(db), _user(db)
    client = _as(db, a)
    chat = _direct(client, b)
    assert client.get(f"/messages/conversations/{chat}?before=0").status_code == 422
    assert client.post(f"/messages/conversations/{chat}/read", json={"up_to": 0}).status_code == 422
    assert client.get(f"/messages/conversations/{chat}?before=5").status_code == 200


def test_people_lists_everyone_but_the_caller(db):
    a, b = _user(db), _user(db)
    ids = {p["id"] for p in _as(db, a).get("/messages/people").json()["people"]}
    assert str(b.id) in ids and str(a.id) not in ids
