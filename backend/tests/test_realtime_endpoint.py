"""The single socket endpoint: handshake auth and connection lifecycle.

Read tests/test_realtime_dependency.py before trusting a green run here.
TestClient drives websocket routes through ASGI directly, so these tests
pass whether or not uvicorn can serve a real handshake in production.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from starlette.websockets import WebSocketDisconnect

from app.domain import realtime as policy
from app.main import app
from app.models import User
from app.routers import realtime as realtime_router
from app.services import auth as auth_service
from app.services import realtime as service


@pytest.fixture(autouse=True)
def _clean_registry():
    service.reset()
    yield
    service.reset()


@pytest.fixture(autouse=True)
def _endpoint_sees_this_transaction(db, monkeypatch):
    """Point the endpoint's session factory at this test's transaction.

    The endpoint deliberately does **not** take a session from
    `Depends(get_db)`: a dependency declared with `yield` is torn down
    when the endpoint returns, and a socket endpoint returns hours later,
    so every live socket would pin a pooled connection inside an open
    transaction. It opens its own short-lived session instead -- which
    means that by default it queries a *different* connection and cannot
    see the rows `_session_for` created inside the `db` fixture's
    rolled-back transaction.

    Binding the factory to the same connection fixes that. It hands back
    a distinct `Session` rather than the fixture's own, so the endpoint
    closing it (as it must) does not close the session the test is still
    using.
    """
    connection = db.get_bind()

    def factory():
        return Session(
            bind=connection,
            join_transaction_mode="create_savepoint",
            autoflush=False,
        )

    monkeypatch.setattr(realtime_router, "SessionLocal", factory)


def _session_for(db, *, role="admin", username="ws_endpoint_user"):
    user = User(
        username=username,
        first_name="Ws",
        last_name="Endpoint",
        role=role,
        password_hash=auth_service.hash_password("correct horse"),
    )
    db.add(user)
    db.flush()
    db.commit()
    return user, auth_service.create_session(db, user)


def test_handshake_without_a_cookie_is_refused(db):
    """Refused immediately, before any expensive work.

    Both halves of this test are load-bearing, and the reason is worth
    stating because the obvious version of it is decorative:

        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws"):
                pass

    That passes when `/ws` is **not mounted at all** -- a missing route
    closes the socket too -- so it cannot tell "refused for the right
    reason" from "nothing is there", and it would keep passing if this
    endpoint were deleted outright. It was the first version of this
    test.

    So: assert the *specific* refusal this endpoint produces, and pair it
    with the same handshake succeeding once the missing precondition is
    supplied. The positive control is what proves the route exists, which
    is what makes the refusal attributable to the absent cookie.
    """
    _user, token = _session_for(db, username="ws_no_cookie_user")

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as refusal:
            with client.websocket_connect("/ws"):
                pass

        assert refusal.value.code == realtime_router.CLOSE_POLICY_VIOLATION
        assert refusal.value.reason == "not authenticated"

        # Positive control: same client, same route, cookie supplied.
        client.cookies.set("session", token)
        with client.websocket_connect("/ws"):
            pass


def test_handshake_with_an_unknown_token_is_refused(db):
    """A cookie that resolves to no session is refused, distinctly.

    Same structure and same reasoning as the test above. The reason
    string is asserted because both pre-accept refusals close with 1008,
    so the code alone cannot distinguish "you sent no cookie" from "you
    sent one that does not resolve" -- and a regression that collapsed
    the two would be invisible without it.
    """
    _user, token = _session_for(db, username="ws_bad_token_user")

    with TestClient(app) as client:
        client.cookies.set("session", "not-a-real-token")
        with pytest.raises(WebSocketDisconnect) as refusal:
            with client.websocket_connect("/ws"):
                pass

        assert refusal.value.code == realtime_router.CLOSE_POLICY_VIOLATION
        assert refusal.value.reason == "session invalid"

        # Positive control: the same client with a token that does resolve.
        client.cookies.set("session", token)
        with client.websocket_connect("/ws"):
            pass


def test_authenticated_handshake_is_accepted_and_registered(db):
    user, token = _session_for(db)

    with TestClient(app) as client:
        client.cookies.set("session", token)
        with client.websocket_connect("/ws"):
            assert service.connection_count(user.id) == 1


def test_connection_is_deregistered_on_close(db):
    user, token = _session_for(db, username="ws_close_user")

    with TestClient(app) as client:
        client.cookies.set("session", token)
        with client.websocket_connect("/ws"):
            pass

        assert service.connection_count(user.id) == 0


def test_ping_is_answered(db):
    """The endpoint accepts client->server frames from day one. A strictly
    one-way socket has no seam at which to add message send later."""
    _user, token = _session_for(db, username="ws_ping_user")

    with TestClient(app) as client:
        client.cookies.set("session", token)
        with client.websocket_connect("/ws") as socket:
            socket.send_json({"type": policy.INBOUND_PING})
            assert socket.receive_json()["type"] == "pong"


def test_unknown_inbound_frames_do_not_mutate_or_crash(db):
    """P3 is permanent: the socket never mutates anything."""
    _user, token = _session_for(db, username="ws_bad_frame_user")

    with TestClient(app) as client:
        client.cookies.set("session", token)
        with client.websocket_connect("/ws") as socket:
            socket.send_json({"type": "delete_everything"})
            socket.send_json({"type": policy.INBOUND_PING})
            assert socket.receive_json()["type"] == "pong"


def test_oversized_frames_are_rejected(db):
    """One byte over the limit closes the connection, with 1009.

    A milder case of the same weakness the two refusal tests had: bare
    `pytest.raises(WebSocketDisconnect)` here cannot tell "closed because
    the frame was too big" from "closed because something unrelated
    broke". It cannot pass against a missing route -- the handshake above
    it would fail first -- but it would pass if the size check were
    replaced by any other fault. So the close code is asserted too.
    """
    _user, token = _session_for(db, username="ws_big_frame_user")

    with TestClient(app) as client:
        client.cookies.set("session", token)
        with client.websocket_connect("/ws") as socket:
            socket.send_text("x" * (policy.MAX_FRAME_BYTES + 1))
            with pytest.raises(WebSocketDisconnect) as refusal:
                socket.receive_json()

        assert refusal.value.code == realtime_router.CLOSE_MESSAGE_TOO_BIG


def test_a_frame_at_exactly_the_limit_is_accepted(db):
    """The boundary, from the other side.

    Pins `>` rather than `>=`. Without this, the test above passes just
    as happily against a limit that is one byte too strict -- and the
    two together are what make `MAX_FRAME_BYTES` mean exactly what it
    says.
    """
    _user, token = _session_for(db, username="ws_exact_frame_user")

    template = '{"type":"' + policy.INBOUND_PING + '","pad":"%s"}'
    frame = template % ("x" * (policy.MAX_FRAME_BYTES - len(template % "")))
    assert len(frame.encode("utf-8")) == policy.MAX_FRAME_BYTES

    with TestClient(app) as client:
        client.cookies.set("session", token)
        with client.websocket_connect("/ws") as socket:
            socket.send_text(frame)
            assert socket.receive_json()["type"] == "pong"
