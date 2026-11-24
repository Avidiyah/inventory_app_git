"""Live messaging service rules (spec 2026-11-24-live-messaging-design.md)."""

import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from app.domain.errors import (
    ConversationNotFoundError,
    GroupPermissionError,
    InvalidMessageError,
    UserNotFoundError,
)
from app.models import User
from app.models_messages import Conversation, ConversationMember, Message
from app.services import auth as auth_service
from app.services import messages as svc

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)


def _user(db, role="technician", first="Pat", last=None, archived=False):
    user = User(
        username=f"u-{uuid.uuid4().hex[:10]}",
        password_hash=auth_service.hash_password("hunter2"),
        role=role,
        first_name=first,
        last_name=last or uuid.uuid4().hex[:6],
        archived_at=NOW if archived else None,
    )
    db.add(user)
    db.commit()  # releases the test savepoint so a later rollback keeps the user
    return user


def _group(db, starter, *others, name="Night crew"):
    conv, _ = svc.create_group(db, starter, name, [o.id for o in others])
    return conv


def _mark(db, conv, user):
    row = (
        db.query(ConversationMember.last_read_message_id)
        .filter_by(conversation_id=conv.id, user_id=user.id)
        .one()
    )
    return row[0]


def _raw_message(db, conv, sender, body, created_at):
    message = Message(conversation_id=conv.id, sender_id=sender.id, body=body, created_at=created_at)
    db.add(message)
    db.commit()
    return message


def test_non_member_gets_not_found_from_every_chat_function(db):
    a, b, stranger = _user(db), _user(db), _user(db, "supervisor")
    chat = svc.get_or_create_direct(db, a, b.id)
    out, _ = svc.send_message(db, a, chat.id, "hi")
    for call in (
        lambda: svc.get_conversation(db, stranger, chat.id),
        lambda: svc.send_message(db, stranger, chat.id, "hi"),
        lambda: svc.mark_read(db, stranger, chat.id, out["id"]),
        lambda: svc.end_group(db, stranger, chat.id),
        lambda: svc.get_conversation(db, stranger, "not-a-uuid"),
    ):
        with pytest.raises(ConversationNotFoundError):
            call()


def test_direct_chat_is_one_row_whichever_side_opens_it(db):
    a, b = _user(db), _user(db)
    first = svc.get_or_create_direct(db, a, b.id)
    second = svc.get_or_create_direct(db, b, a.id)
    assert first.id == second.id
    assert db.query(Conversation).filter_by(direct_key=first.direct_key).count() == 1


def test_direct_chat_race_loser_loads_the_existing_row(db, monkeypatch):
    a, b = _user(db), _user(db)
    existing = svc.get_or_create_direct(db, a, b.id)
    real = svc._find_direct
    calls = []

    def blind_first(db_, key):
        calls.append(key)
        return None if len(calls) == 1 else real(db_, key)

    monkeypatch.setattr(svc, "_find_direct", blind_first)
    loser = svc.get_or_create_direct(db, b, a.id)  # insert hits the unique direct_key

    assert loser.id == existing.id and len(calls) == 2


def test_direct_chat_with_self_or_archived_user_is_user_not_found(db):
    a, gone = _user(db), _user(db, archived=True)
    with pytest.raises(UserNotFoundError):
        svc.get_or_create_direct(db, a, a.id)
    with pytest.raises(UserNotFoundError):
        svc.get_or_create_direct(db, a, gone.id)


def test_two_unread_group_writers_count_as_two_people(db):
    lead, w1, w2 = _user(db, "supervisor"), _user(db), _user(db)
    conv = _group(db, lead, w1, w2)
    svc.send_message(db, w1, conv.id, "one")
    svc.send_message(db, w2, conv.id, "two")

    listing = svc.list_conversations(db, lead)

    assert listing["unread_people"] == 2
    row = listing["conversations"][0]
    assert row["unread_count"] == 2
    assert set(row["unread_sender_ids"]) == {str(w1.id), str(w2.id)}
    assert row["last_message"]["body"] == "two" and row["member_count"] == 3


def test_own_messages_are_never_unread(db):
    lead, w1, w2 = _user(db, "supervisor"), _user(db), _user(db)
    conv = _group(db, lead, w1, w2)
    svc.send_message(db, lead, conv.id, "mine")

    listing = svc.list_conversations(db, lead)

    assert listing["unread_people"] == 0
    assert listing["conversations"][0]["unread_count"] == 0


def test_direct_chat_with_no_messages_is_left_out_of_the_list(db):
    a, b = _user(db), _user(db)
    svc.get_or_create_direct(db, a, b.id)
    assert svc.list_conversations(db, a)["conversations"] == []


def test_mark_read_never_lowers_and_reports_only_a_real_move(db):
    a, b = _user(db), _user(db)
    chat = svc.get_or_create_direct(db, a, b.id)
    first, _ = svc.send_message(db, a, chat.id, "one")
    second, _ = svc.send_message(db, a, chat.id, "two")

    moved = svc.mark_read(db, b, chat.id, second["id"])
    assert set(moved) == {a.id, b.id}
    assert svc.mark_read(db, b, chat.id, first["id"]) == []
    assert svc.mark_read(db, b, chat.id, second["id"]) == []
    assert _mark(db, chat, b) == second["id"]


def test_seen_message_id_follows_the_other_reader(db):
    a, b = _user(db), _user(db)
    chat = svc.get_or_create_direct(db, a, b.id)
    sent, _ = svc.send_message(db, a, chat.id, "ping")
    assert svc.get_conversation(db, a, chat.id)["seen_message_id"] is None

    svc.mark_read(db, b, chat.id, sent["id"])

    detail = svc.get_conversation(db, a, chat.id)
    assert detail["seen_message_id"] == sent["id"]
    assert detail["my_read_message_id"] == sent["id"]  # sending advanced my own mark
    assert detail["name"] == b.full_name


def test_get_conversation_pages_older_messages(db):
    a, b = _user(db), _user(db)
    chat = svc.get_or_create_direct(db, a, b.id)
    for i in range(53):
        svc.send_message(db, a, chat.id, f"m{i}")

    page = svc.get_conversation(db, b, chat.id)
    assert len(page["messages"]) == 50 and page["has_more"]
    assert page["messages"][-1]["body"] == "m52"

    older = svc.get_conversation(db, b, chat.id, before=page["messages"][0]["id"])
    assert [m["body"] for m in older["messages"]] == ["m0", "m1", "m2"]
    assert not older["has_more"]


def test_technician_cannot_create_a_group(db):
    tech, b, c = _user(db), _user(db), _user(db)
    with pytest.raises(GroupPermissionError):
        svc.create_group(db, tech, "Crew", [b.id, c.id])


def test_group_needs_two_others_who_are_active(db):
    lead, b, c = _user(db, "supervisor"), _user(db), _user(db)
    gone = _user(db, archived=True)
    with pytest.raises(InvalidMessageError):
        svc.create_group(db, lead, "Crew", [b.id])
    with pytest.raises(InvalidMessageError):
        svc.create_group(db, lead, "Crew", [b.id, lead.id])  # starter is not an "other"
    with pytest.raises(InvalidMessageError):
        svc.create_group(db, lead, "Crew", [b.id, gone.id])
    with pytest.raises(InvalidMessageError):
        svc.create_group(db, lead, "Crew", [b.id, uuid.uuid4()])
    conv, members = svc.create_group(db, lead, "Crew", [b.id, c.id])
    assert set(members) == {lead.id, b.id, c.id} and conv.created_by == lead.id


def test_only_the_starter_can_end_a_group(db):
    lead, b, c = _user(db, "supervisor"), _user(db), _user(db)
    conv = _group(db, lead, b, c)
    with pytest.raises(GroupPermissionError):
        svc.end_group(db, b, conv.id)


def test_ending_a_group_removes_its_messages_and_returns_the_members(db):
    lead, b, c = _user(db, "supervisor"), _user(db), _user(db)
    conv = _group(db, lead, b, c)
    svc.send_message(db, b, conv.id, "bye")
    cid = conv.id

    former = svc.end_group(db, lead, cid)

    assert set(former) == {lead.id, b.id, c.id}
    assert db.query(Message).filter_by(conversation_id=cid).count() == 0
    assert db.query(Conversation).filter_by(id=cid).count() == 0
    with pytest.raises(ConversationNotFoundError):
        svc.get_conversation(db, lead, cid)


def test_sweep_applies_the_direct_cutoff(db):
    a, b = _user(db), _user(db)
    chat = svc.get_or_create_direct(db, a, b.id)
    old = _raw_message(db, chat, a, "old", NOW - timedelta(days=91))
    fresh = _raw_message(db, chat, a, "fresh", NOW - timedelta(days=89))
    chat_id, old_id, fresh_id = chat.id, old.id, fresh.id

    result = svc.sweep(db, NOW)

    assert result["messages_deleted"] >= 1
    left = {m.id for m in db.query(Message).filter_by(conversation_id=chat_id)}
    assert left == {fresh_id} and old_id not in left


def test_sweep_applies_the_group_quiet_cutoff(db):
    lead, b, c = _user(db, "supervisor"), _user(db), _user(db)
    quiet, active, empty = (_group(db, lead, b, c, name=n) for n in ("quiet", "active", "empty"))
    for conv, age in ((quiet, 8), (active, 6)):
        _raw_message(db, conv, lead, "x", NOW - timedelta(days=age))
        conv.last_message_at = NOW - timedelta(days=age)
    empty.created_at = NOW - timedelta(days=8)
    db.commit()
    ids = [quiet.id, active.id, empty.id]
    active_id = active.id

    result = svc.sweep(db, NOW)

    assert result["groups_deleted"] >= 2
    surviving = {r[0] for r in db.query(Conversation.id).filter(Conversation.id.in_(ids))}
    assert surviving == {active_id}


def test_maybe_sweep_runs_once_per_day(db, monkeypatch):
    monkeypatch.setattr(svc, "_last_sweep", None)
    assert svc.maybe_sweep(db, NOW) is not None
    assert svc.maybe_sweep(db, NOW + timedelta(hours=23)) is None
    assert svc.maybe_sweep(db, NOW + timedelta(hours=25)) is not None


def test_search_finds_my_messages_only(db):
    me, friend, other = _user(db), _user(db), _user(db)
    mine = svc.get_or_create_direct(db, me, friend.id)
    theirs = svc.get_or_create_direct(db, friend, other.id)
    svc.send_message(db, me, mine.id, "Need a new GASKET today")
    svc.send_message(db, friend, theirs.id, "gasket in the other chat")

    result = svc.search(db, me, "gasket")

    assert [h["message"]["body"] for h in result["messages"]] == ["Need a new GASKET today"]
    assert result["messages"][0]["conversation_name"] == friend.full_name


def test_search_percent_matches_literally(db):
    me, friend = _user(db), _user(db)
    chat = svc.get_or_create_direct(db, me, friend.id)
    svc.send_message(db, me, chat.id, "50% off")
    svc.send_message(db, me, chat.id, "plain words")

    hits = svc.search(db, me, "0%")["messages"]
    assert [h["message"]["body"] for h in hits] == ["50% off"]
    assert svc.search(db, me, "%%")["messages"] == []
    assert svc.search(db, me, "x") == {"people": [], "conversations": [], "messages": []}


def test_search_finds_people_and_group_names(db):
    lead, b, c = _user(db, "supervisor"), _user(db, first="Zebulon"), _user(db)
    _group(db, lead, b, c, name="Zebra patrol")

    result = svc.search(db, lead, "zeb")

    assert [p["name"].split()[0] for p in result["people"]] == ["Zebulon"]
    assert [r["name"] for r in result["conversations"]] == ["Zebra patrol"]


def test_list_people_skips_archived_and_the_caller_and_labels_roles(db):
    me, lead = _user(db), _user(db, "supervisor", first="Lee")
    gone = _user(db, archived=True)

    people = {p["id"]: p for p in svc.list_people(db, me)}

    assert str(me.id) not in people and str(gone.id) not in people
    assert people[str(lead.id)]["role_label"] == "Team Lead"
    assert set(people[str(lead.id)]) == {"id", "name", "role_label"}
