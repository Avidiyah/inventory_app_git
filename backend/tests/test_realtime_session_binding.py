"""Session binding for real-time connections (design D1, §6.2).

A socket authenticated once at handshake has no next request, so the
instant revocation every HTTP route gets for free does not apply. These
tests pin the mechanism that replaces it: periodic re-resolution against
a stored token *hash*.
"""

import asyncio

import pytest

from app.models import User
from app.routers import realtime as realtime_router
from app.services import auth as auth_service
from app.services import realtime as realtime_service


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


# --- live connection revalidation -------------------------------------


def _connection(*, user_id="user-1", role="admin"):
    return realtime_service.Connection(
        user_id=user_id,
        token_hash="a" * 64,
        role=role,
    )


def test_revalidate_once_keeps_an_unchanged_live_identity(monkeypatch):
    async def scenario():
        connection = _connection()
        monkeypatch.setattr(
            realtime_router,
            "_resolve_identity",
            lambda _token_hash: ("user-1", "admin"),
        )

        assert await realtime_router._revalidate_once(connection) is True
        assert connection.close_requested.is_set() is False

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "resolved_identity",
    [
        None,
        ("another-user", "admin"),
        ("user-1", "technician"),
    ],
)
def test_revalidate_once_fails_closed_when_authorization_changes(
    monkeypatch,
    resolved_identity,
):
    """Revocation, identity drift, and role drift all end the socket.

    Normal role changes revoke the session and therefore resolve to None.
    The explicit mismatch cases keep this boundary fail-closed even if a
    future write path accidentally changes identity state without revoking.
    """

    async def scenario():
        connection = _connection()
        monkeypatch.setattr(
            realtime_router,
            "_resolve_identity",
            lambda _token_hash: resolved_identity,
        )

        assert await realtime_router._revalidate_once(connection) is False
        assert connection.close_requested.is_set() is True
        assert connection.close_code == realtime_router.CLOSE_POLICY_VIOLATION
        assert connection.close_reason == "session no longer valid"

    asyncio.run(scenario())


def test_revalidate_once_fails_closed_when_resolution_errors(monkeypatch):
    def broken_resolver(_token_hash):
        raise RuntimeError("database unavailable")

    async def scenario():
        connection = _connection()
        monkeypatch.setattr(realtime_router, "_resolve_identity", broken_resolver)

        with pytest.raises(RuntimeError, match="database unavailable"):
            await realtime_router._revalidate_once(connection)

        assert connection.close_requested.is_set() is True
        assert connection.close_code == realtime_router.CLOSE_INTERNAL_ERROR
        assert connection.close_reason == "session revalidation failed"

    asyncio.run(scenario())
