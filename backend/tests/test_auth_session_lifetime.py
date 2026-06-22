"""Database integration tests for the session lifetime policy.

These exercise `create_session` (which encodes the remember-me policy in
`expires_at`) and `get_active_session_user` (which enforces the absolute
cap and deletes an expired remembered session) against Postgres via the
`db` fixture's rolled-back transaction. They skip if no DB is reachable.

There is no idle timeout: a non-remembered session (`expires_at` NULL)
stays valid server-side indefinitely -- it ends only when the browser
drops its session cookie or the user logs out.
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


def test_remember_sets_absolute_cap(db):
    user = _seed_user(db)
    before = datetime.now(timezone.utc)
    token = auth.create_session(db, user, remember=True)
    after = datetime.now(timezone.utc)

    session = db.query(AuthSession).filter(AuthSession.token == token).one()
    assert session.expires_at is not None
    # Cap is ~now + REMEMBER_LIFETIME, bracketed by the call's wall clock.
    assert before + auth.REMEMBER_LIFETIME <= session.expires_at <= after + auth.REMEMBER_LIFETIME


def test_not_remembered_has_no_cap(db):
    user = _seed_user(db)
    token = auth.create_session(db, user, remember=False)

    session = db.query(AuthSession).filter(AuthSession.token == token).one()
    assert session.expires_at is None


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


def test_remembered_session_expired_is_deleted(db):
    user = _seed_user(db)
    now = datetime.now(timezone.utc)
    # Construct a remembered session whose cap is already in the past --
    # no need to wait out the real 12h window.
    session = AuthSession(
        token=auth.secrets.token_urlsafe(32),
        user_id=user.id,
        created_at=now - timedelta(hours=13),
        expires_at=now - timedelta(hours=1),
    )
    db.add(session)
    db.flush()

    resolved = auth.get_active_session_user(db, session.token)
    assert resolved is None
    # Expired row is removed server-side.
    assert db.query(AuthSession).filter(AuthSession.token == session.token).first() is None


def test_unknown_token_returns_none(db):
    assert auth.get_active_session_user(db, "no-such-token") is None
