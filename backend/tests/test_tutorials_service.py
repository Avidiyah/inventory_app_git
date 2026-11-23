"""Tutorial progress service rules (0b spec 5.1, 5.2)."""

import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from app.domain import tutorials as rules
from app.domain.errors import InvalidTutorialKeyError, TutorialProgressLimitError
from app.models import TutorialProgress, User
from app.schemas.tutorials import ProgressEvent
from app.services import auth as auth_service
from app.services import tutorials as svc

SEEN, DONE = ProgressEvent.seen, ProgressEvent.completed
KEY = "work-orders.card.notes"


def _seed_user(db, role="technician"):
    user = User(
        username=f"u-{uuid.uuid4().hex[:10]}",
        password_hash=auth_service.hash_password("hunter2"),
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def _row(db, user, key=KEY):
    rows = {r.script_key: r for r in svc.list_mine(db, user.id)}
    return rows[key]


def test_first_seen_sets_seen_at_and_a_later_seen_does_not_move_it(db):
    user = _seed_user(db)
    svc.record(db, user.id, KEY, SEEN)
    first = _row(db, user)
    assert first.seen_at is not None and first.completed_at is None
    stamp = first.seen_at

    svc.record(db, user.id, KEY, SEEN)

    assert _row(db, user).seen_at == stamp


def test_completed_on_a_new_key_fills_both_timestamps_equal(db):
    user = _seed_user(db)
    svc.record(db, user.id, KEY, DONE)
    row = _row(db, user)
    assert row.completed_at is not None
    assert row.completed_at == row.seen_at


def test_completed_is_final_and_seen_or_completed_again_change_nothing(db):
    user = _seed_user(db)
    svc.record(db, user.id, KEY, DONE)
    before = _row(db, user)
    seen_at, completed_at = before.seen_at, before.completed_at

    svc.record(db, user.id, KEY, SEEN)
    svc.record(db, user.id, KEY, DONE)

    after = _row(db, user)
    assert (after.seen_at, after.completed_at) == (seen_at, completed_at)


def test_seen_then_completed_keeps_the_original_seen_at(db):
    user = _seed_user(db)
    svc.record(db, user.id, KEY, SEEN)
    seen_at = _row(db, user).seen_at

    svc.record(db, user.id, KEY, DONE)

    row = _row(db, user)
    assert row.seen_at == seen_at
    assert row.completed_at is not None and row.completed_at >= seen_at


@pytest.mark.parametrize("bad", ["", "Upper", "a b", "a" * 81, ".leading", "-lead"])
def test_bad_keys_are_refused(db, bad):
    user = _seed_user(db)
    with pytest.raises(InvalidTutorialKeyError):
        svc.record(db, user.id, bad, SEEN)


def test_the_longest_legal_key_is_accepted():
    assert rules.validate_key("a" * 80) == "a" * 80


def test_the_501st_distinct_key_is_refused_but_an_existing_key_still_rewrites(db):
    user = _seed_user(db)
    now = datetime.now(timezone.utc)
    db.add_all(
        TutorialProgress(user_id=user.id, script_key=f"k{i}", seen_at=now)
        for i in range(rules.MAX_ROWS_PER_USER)
    )
    db.flush()

    with pytest.raises(TutorialProgressLimitError):
        svc.record(db, user.id, "one-too-many", SEEN)

    svc.record(db, user.id, "k0", DONE)
    assert _row(db, user, "k0").completed_at is not None


def test_completed_by_user_lists_active_users_completed_keys_only(db):
    active, archived, idle = _seed_user(db), _seed_user(db), _seed_user(db)
    svc.record(db, active.id, "a.one", DONE)
    svc.record(db, active.id, "a.two", SEEN)  # seen only: not listed
    svc.record(db, active.id, "a.three", DONE)
    svc.record(db, archived.id, "b.one", DONE)
    svc.record(db, idle.id, "c.one", SEEN)
    archived.archived_at = datetime.now(timezone.utc)
    db.flush()

    result = svc.completed_by_user(db)

    assert result[str(active.id)] == ["a.one", "a.three"]
    assert str(archived.id) not in result
    assert str(idle.id) not in result
