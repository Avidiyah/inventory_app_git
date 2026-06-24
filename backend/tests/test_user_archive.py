"""Database integration tests for user archival (soft delete).

Archiving a user keeps their row (so the history join still resolves
their name) but blocks login, revokes their sessions, and hides them from
the active Saved Users list while keeping them available to the History
"by user" filter. Restore reverses it. These skip if no DB (the `db`
fixture).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid

import pytest

from app.domain.errors import InvalidCredentialsError
from app.models import AuthSession, User
from app.services import auth
from app.services import users as users_service


def _seed_user(db, role="technician"):
    user = User(
        username=f"u-{uuid.uuid4().hex[:10]}",
        password_hash=auth.hash_password("hunter2"),
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def test_archive_blocks_authentication(db):
    user = _seed_user(db)
    # Active user authenticates fine.
    assert auth.authenticate(db, username=user.username, password="hunter2").id == user.id

    users_service.archive_user(db, user.id)

    with pytest.raises(InvalidCredentialsError):
        auth.authenticate(db, username=user.username, password="hunter2")


def test_archive_revokes_sessions(db):
    user = _seed_user(db)
    token = auth.create_session(db, user, remember=False)
    assert auth.get_active_session_user(db, token) is not None

    users_service.archive_user(db, user.id)

    # Session row is gone, and even a lingering one would not resolve.
    assert db.query(AuthSession).filter(AuthSession.user_id == user.id).count() == 0
    assert auth.get_active_session_user(db, token) is None


def test_archived_user_hidden_from_default_list_but_visible_with_flag(db):
    user = _seed_user(db)
    users_service.archive_user(db, user.id)

    active_ids = {u.id for u in users_service.list_users(db)}
    assert user.id not in active_ids

    all_ids = {u.id for u in users_service.list_users(db, include_archived=True)}
    assert user.id in all_ids


def test_restore_reactivates_login(db):
    user = _seed_user(db)
    users_service.archive_user(db, user.id)
    users_service.restore_user(db, user.id)

    assert auth.authenticate(db, username=user.username, password="hunter2").id == user.id
    assert user.archived_at is None
