"""Database integration tests for the session lifetime policy.

These exercise `create_session` (which sets an absolute cap on every
session) and `get_active_session_user` (which enforces it and deletes
the row once passed) against Postgres via the `db` fixture's rolled-back
transaction. They skip if no DB is reachable.

Two properties this file exists to pin:

- **Every** session has a cap. The old model left `expires_at` NULL for
  any login without "remember this device", which meant the default
  session never expired and nothing ever swept it.
- "Remember this device" no longer changes server-side validity, only
  cookie persistence, so both kinds get the same treatment here.

There is still no idle timeout -- migration `c7e9a1b3d5f8` removed the
sliding window deliberately and this work did not bring it back.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from datetime import datetime, timedelta, timezone

from app.models import AuthSession, User
from app.services import auth


def _seed_user(db):
    user = User(
        username=f"u-{uuid.uuid4().hex[:10]}",
        password_hash=auth.hash_password("hunter2"),
        role="technician",
    )
    db.add(user)
    db.flush()
    return user


def _row(db, token):
    return (
        db.query(AuthSession)
        .filter(AuthSession.token_hash == auth._hash_token(token))
        .one()
    )


def test_remember_sets_absolute_cap(db):
    user = _seed_user(db)
    before = datetime.now(timezone.utc)
    token = auth.create_session(db, user, remember=True)
    after = datetime.now(timezone.utc)

    session = _row(db, token)
    assert session.expires_at is not None
    # Cap is ~now + REMEMBER_LIFETIME, bracketed by the call's wall clock.
    assert before + auth.REMEMBER_LIFETIME <= session.expires_at <= after + auth.REMEMBER_LIFETIME


def test_not_remembered_also_gets_a_cap(db):
    """The regression this whole change exists for: the non-remembered
    session used to be the immortal one."""
    user = _seed_user(db)
    before = datetime.now(timezone.utc)
    token = auth.create_session(db, user, remember=False)
    after = datetime.now(timezone.utc)

    session = _row(db, token)
    assert session.expires_at is not None
    assert before + auth.SESSION_LIFETIME <= session.expires_at <= after + auth.SESSION_LIFETIME


def test_not_remembered_session_stays_valid(db):
    user = _seed_user(db)
    token = auth.create_session(db, user, remember=False)

    resolved = auth.get_active_session_user(db, token)
    assert resolved is not None
    assert resolved.id == user.id


def test_remembered_session_valid_before_cap(db):
    user = _seed_user(db)
    token = auth.create_session(db, user, remember=True)

    resolved = auth.get_active_session_user(db, token)
    assert resolved is not None
    assert resolved.id == user.id


def test_expired_session_is_deleted_on_read(db):
    user = _seed_user(db)
    now = datetime.now(timezone.utc)
    token = auth.create_session(db, user, remember=True)
    # Backdate the cap rather than waiting out the real 12h window.
    session = _row(db, token)
    session.expires_at = now - timedelta(hours=1)
    db.flush()

    assert auth.get_active_session_user(db, token) is None
    assert (
        db.query(AuthSession)
        .filter(AuthSession.token_hash == auth._hash_token(token))
        .first()
        is None
    )


def test_unknown_token_returns_none(db):
    assert auth.get_active_session_user(db, "no-such-token") is None


def test_sweep_removes_only_expired_sessions(db):
    user = _seed_user(db)
    now = datetime.now(timezone.utc)

    live_token = auth.create_session(db, user, remember=True)
    dead_token = auth.create_session(db, user, remember=True)
    dead = _row(db, dead_token)
    dead.expires_at = now - timedelta(minutes=1)
    db.flush()

    auth.sweep_expired_sessions(db)

    assert auth.get_active_session_user(db, live_token) is not None
    assert (
        db.query(AuthSession)
        .filter(AuthSession.token_hash == auth._hash_token(dead_token))
        .first()
        is None
    )


def test_create_session_sweeps_expired_rows(db):
    """The sweep has no scheduler behind it -- login is what triggers it,
    so a login must actually clear someone else's expired row."""
    user = _seed_user(db)
    stale_token = auth.create_session(db, user, remember=True)
    stale = _row(db, stale_token)
    stale.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.flush()

    auth.create_session(db, user, remember=False)

    assert (
        db.query(AuthSession)
        .filter(AuthSession.token_hash == auth._hash_token(stale_token))
        .first()
        is None
    )


def test_revoke_user_sessions_drops_every_row(db):
    user = _seed_user(db)
    first = auth.create_session(db, user, remember=False)
    second = auth.create_session(db, user, remember=True)

    removed = auth.revoke_user_sessions(db, user.id)
    db.commit()

    assert removed == 2
    assert auth.get_active_session_user(db, first) is None
    assert auth.get_active_session_user(db, second) is None
