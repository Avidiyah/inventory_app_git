"""The core security property of API-hardening item X1: a read of the
`sessions` table yields nothing that can be replayed as a credential.

Previously `sessions.token` was the raw bearer token, stored in
plaintext as the primary key. Anyone who could read one row -- from a
backup, a replica, a dashboard query, a read-only injection -- could
paste it into a cookie and be that user, with no login event and nothing
to distinguish it from legitimate traffic.

These tests skip if no DB is reachable.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hashlib
import uuid

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


def test_hash_token_is_sha256_hex():
    token = "some-opaque-token"
    assert auth._hash_token(token) == hashlib.sha256(token.encode("utf-8")).hexdigest()
    assert len(auth._hash_token(token)) == 64


def test_raw_token_is_never_stored(db):
    user = _seed_user(db)
    token = auth.create_session(db, user, remember=False)

    stored = [row.token_hash for row in db.query(AuthSession).all()]
    assert token not in stored
    assert auth._hash_token(token) in stored


def test_stored_value_cannot_be_used_as_a_cookie(db):
    """The stolen-database scenario: presenting the stored hash must not
    authenticate. If this ever passes, hashing has bought nothing."""
    user = _seed_user(db)
    token = auth.create_session(db, user, remember=False)
    stolen = auth._hash_token(token)

    assert auth.get_active_session_user(db, stolen) is None
    # ...while the real cookie still works.
    assert auth.get_active_session_user(db, token).id == user.id


def test_delete_session_resolves_through_the_hash(db):
    user = _seed_user(db)
    token = auth.create_session(db, user, remember=False)

    auth.delete_session(db, token)

    assert auth.get_active_session_user(db, token) is None
    assert (
        db.query(AuthSession)
        .filter(AuthSession.token_hash == auth._hash_token(token))
        .first()
        is None
    )


def test_two_sessions_get_distinct_tokens_and_hashes(db):
    user = _seed_user(db)
    first = auth.create_session(db, user, remember=False)
    second = auth.create_session(db, user, remember=False)

    assert first != second
    assert auth._hash_token(first) != auth._hash_token(second)
    assert auth.get_active_session_user(db, first).id == user.id
    assert auth.get_active_session_user(db, second).id == user.id
