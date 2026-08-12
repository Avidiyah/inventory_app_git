"""Session binding for real-time connections (design D1, §6.2).

A socket authenticated once at handshake has no next request, so the
instant revocation every HTTP route gets for free does not apply. These
tests pin the mechanism that replaces it: periodic re-resolution against
a stored token *hash*.
"""

import pytest

from app.models import User
from app.services import auth as auth_service


def _make_user(db, *, username="ws_bind_user", role="technician"):
    user = User(
        username=username,
        first_name="Ws",
        last_name="Bind",
        role=role,
        password_hash=auth_service.hash_password("correct horse"),
    )
    db.add(user)
    db.flush()
    return user


def test_hash_session_token_is_stable_and_not_the_token():
    digest = auth_service.hash_session_token("a-raw-token")

    assert digest == auth_service.hash_session_token("a-raw-token")
    assert "a-raw-token" not in digest
    assert len(digest) == 64


def test_resolve_by_hash_returns_the_user_for_a_live_session(db):
    user = _make_user(db)
    token = auth_service.create_session(db, user)

    resolved = auth_service.get_active_session_user_by_hash(
        db, auth_service.hash_session_token(token)
    )

    assert resolved is not None
    assert resolved.id == user.id


def test_resolve_by_hash_returns_none_after_revocation(db):
    """Covers role change, archival, and password reset in one mechanism.

    All three call `revoke_user_sessions`, which deletes the rows -- so a
    re-resolve returns None for every one of them.
    """
    user = _make_user(db, username="ws_revoked_user")
    token = auth_service.create_session(db, user)
    token_hash = auth_service.hash_session_token(token)

    auth_service.revoke_user_sessions(db, user.id)
    db.flush()

    assert auth_service.get_active_session_user_by_hash(db, token_hash) is None


def test_resolve_by_hash_returns_none_for_an_unknown_hash(db):
    assert auth_service.get_active_session_user_by_hash(db, "0" * 64) is None


def test_resolve_by_hash_agrees_with_the_raw_token_resolver(db):
    """The two resolvers must never disagree -- one is the socket's view
    of the same fact the HTTP layer reads on every request."""
    user = _make_user(db, username="ws_parity_user")
    token = auth_service.create_session(db, user)

    by_token = auth_service.get_active_session_user(db, token)
    by_hash = auth_service.get_active_session_user_by_hash(
        db, auth_service.hash_session_token(token)
    )

    assert by_token is not None and by_hash is not None
    assert by_token.id == by_hash.id
