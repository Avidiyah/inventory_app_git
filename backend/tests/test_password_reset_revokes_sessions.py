"""A password reset must sign the target out.

`reset_password` used to leave sessions intact on the stated grounds
that "the idle timeout will retire them" -- but no idle timeout exists
(migration `c7e9a1b3d5f8` removed the sliding window), so a reset
prompted by a suspected compromise left the existing session working
indefinitely. This pins the fix, alongside the two paths that always
revoked correctly.

Skips if no DB is reachable.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid

from app.models import AuthSession, User
from app.services import auth
from app.services import users as users_service


def _seed_user(db, role="technician"):
    user = User(
        username=f"u-{uuid.uuid4().hex[:10]}",
        first_name="Test",
        last_name="User",
        password_hash=auth.hash_password("hunter2"),
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def test_reset_password_revokes_active_sessions(db):
    user = _seed_user(db)
    token = auth.create_session(db, user, remember=True)
    assert auth.get_active_session_user(db, token) is not None

    users_service.reset_password(db, user.id, auth.hash_password("new-password"))

    assert auth.get_active_session_user(db, token) is None
    assert db.query(AuthSession).filter(AuthSession.user_id == user.id).count() == 0


def test_reset_password_revokes_every_session_not_just_one(db):
    """A user signed in on the phone and the shop terminal must lose
    both, or the reset has not actually cut off access."""
    user = _seed_user(db)
    phone = auth.create_session(db, user, remember=True)
    terminal = auth.create_session(db, user, remember=False)

    users_service.reset_password(db, user.id, auth.hash_password("new-password"))

    assert auth.get_active_session_user(db, phone) is None
    assert auth.get_active_session_user(db, terminal) is None


def test_reset_password_still_sets_the_new_hash(db):
    user = _seed_user(db)
    new_hash = auth.hash_password("new-password")

    users_service.reset_password(db, user.id, new_hash)
    db.refresh(user)

    assert user.password_hash == new_hash
    assert auth.verify_password("new-password", user.password_hash)


def test_reset_password_leaves_other_users_sessions_alone(db):
    target = _seed_user(db)
    bystander = _seed_user(db)
    target_token = auth.create_session(db, target, remember=False)
    bystander_token = auth.create_session(db, bystander, remember=False)

    users_service.reset_password(db, target.id, auth.hash_password("new-password"))

    assert auth.get_active_session_user(db, target_token) is None
    assert auth.get_active_session_user(db, bystander_token) is not None
