"""The socket endpoint: handshake policy and connection lifecycle.

Read tests/test_realtime_dependency.py before trusting a green run here.
TestClient drives websocket routes through ASGI directly, so these tests
pass whether or not Uvicorn can serve a real handshake in production.
"""

import asyncio
import contextlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from starlette.testclient import WebSocketDenialResponse
from starlette.websockets import WebSocket, WebSocketDisconnect

from app.domain import realtime as policy
from app.main import app
from app.models import User
from app.routers import realtime as realtime_router
from app.services import auth as auth_service
from app.services import realtime as service


SAME_ORIGIN = {"origin": "http://testserver"}


@pytest.fixture(autouse=True)
def _clean_registry():
    service.reset()
    yield
    service.reset()


@pytest.fixture(autouse=True)
def _endpoint_sees_this_transaction(db, monkeypatch):
    """Point the endpoint's short-lived session at this test transaction."""
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


def _connect(client: TestClient):
    return client.websocket_connect("/ws", headers=dict(SAME_ORIGIN))


def _scope_socket(headers, *, scheme="ws"):
    """Build a WebSocket whose headers can include deliberate duplicates."""
    scope = {
        "type": "websocket",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "scheme": scheme,
        "server": ("testserver", 80),
        "client": ("testclient", 50000),
        "root_path": "",
        "path": "/ws",
        "raw_path": b"/ws",
        "query_string": b"",
        "headers": [(key.encode(), value.encode()) for key, value in headers],
        "subprotocols": [],
        "state": {},
    }

    async def receive():  # pragma: no cover - origin checks do not receive
        return {"type": "websocket.disconnect"}

    async def send(_message):  # pragma: no cover - origin checks do not send
        return None

    return WebSocket(scope, receive, send)


@pytest.mark.parametrize(
    "origin",
    [
        "https://other.example",
        "null",
        "not a URL",
        "http://user:test@testserver",
        "http://testserver/path",
        "http://testserver?query=yes",
    ],
)
def test_foreign_or_malformed_origin_is_denied_before_accept(db, origin):
    _user, token = _session_for(db, username=f"ws_origin_{abs(hash(origin))}")

    with TestClient(app) as client:
        client.cookies.set("session", token)
        with pytest.raises(WebSocketDenialResponse) as refusal:
            with client.websocket_connect("/ws", headers={"origin": origin}):
                pass

    assert refusal.value.status_code == 403


def test_origin_is_required_and_checked_before_session_resolution(db, monkeypatch):
    _user, token = _session_for(db, username="ws_origin_order_user")
    resolver_called = False

    def forbidden_resolver(_token_hash):
        nonlocal resolver_called
        resolver_called = True
        raise AssertionError("foreign-origin request reached the database")

    monkeypatch.setattr(realtime_router, "_resolve_identity", forbidden_resolver)

    with TestClient(app) as client:
        client.cookies.set("session", token)
        with pytest.raises(WebSocketDenialResponse) as refusal:
            with client.websocket_connect("/ws"):
                pass

    assert refusal.value.status_code == 403
    assert resolver_called is False


def test_origin_comparison_normalises_default_ports_and_rejects_duplicates():
    assert realtime_router._same_origin(
        _scope_socket([("host", "testserver:80"), ("origin", "http://testserver")])
    )
    assert realtime_router._same_origin(
        _scope_socket(
            [("host", "testserver"), ("origin", "https://testserver:443")],
            scheme="wss",
        )
    )
    assert not realtime_router._same_origin(
        _scope_socket(
            [
                ("host", "testserver"),
                ("origin", "http://testserver"),
                ("origin", "http://other.example"),
            ]
        )
    )
    assert not realtime_router._same_origin(
        _scope_socket(
            [
                ("host", "testserver"),
                ("host", "other.example"),
                ("origin", "http://testserver"),
            ]
        )
    )


def test_handshake_without_cookie_is_http_401_with_positive_control(db):
    _user, token = _session_for(db, username="ws_no_cookie_user")

    with TestClient(app) as client:
        with pytest.raises(WebSocketDenialResponse) as refusal:
            with _connect(client):
                pass
        assert refusal.value.status_code == 401

        client.cookies.set("session", token)
        with _connect(client):
            pass


def test_handshake_with_unknown_token_is_http_401_with_positive_control(db):
    _user, token = _session_for(db, username="ws_bad_token_user")

    with TestClient(app) as client:
        client.cookies.set("session", "not-a-real-token")
        with pytest.raises(WebSocketDenialResponse) as refusal:
            with _connect(client):
                pass
        assert refusal.value.status_code == 401

        client.cookies.set("session", token)
        with _connect(client):
            pass


def test_authenticated_handshake_is_registered_then_deregistered(db, caplog):
    user, token = _session_for(db)

    with caplog.at_level("INFO", logger=realtime_router.__name__):
        with TestClient(app) as client:
            client.cookies.set("session", token)
            with _connect(client):
                assert service.connection_count(user.id) == 1
            assert service.connection_count(user.id) == 0

    connected = next(
        record for record in caplog.records
        if record.getMessage() == "realtime.connected"
    )
    disconnected = next(
        record for record in caplog.records
        if record.getMessage() == "realtime.disconnected"
    )
    assert connected.fields["connection_id"] == disconnected.fields["connection_id"]
    assert connected.fields["user_id"] == disconnected.fields["user_id"] == str(user.id)


def test_periodic_revalidation_closes_a_now_invalid_session(monkeypatch):
    """Prove the revalidation helper is wired into the live task group."""
    class WaitingSocket:
        def __init__(self):
            self.never = asyncio.Event()
            self.closes = []

        async def receive(self):
            await self.never.wait()

        async def send_json(self, _envelope):
            await self.never.wait()

        async def close(self, *, code, reason):
            self.closes.append((code, reason))

    async def scenario():
        connection = service.Connection(
            user_id="user-1",
            token_hash="a" * 64,
            role="admin",
        )
        socket = WaitingSocket()
        monkeypatch.setattr(realtime_router, "_resolve_identity", lambda _hash: None)
        monkeypatch.setattr(policy, "REVALIDATE_INTERVAL_SECONDS", 0.01)

        await asyncio.wait_for(
            realtime_router._serve(connection, socket),
            timeout=1,
        )

        assert socket.closes == [
            (realtime_router.CLOSE_POLICY_VIOLATION, "session no longer valid")
        ]

    asyncio.run(scenario())


def test_connection_cap_is_http_429_before_accept(db):
    _user, token = _session_for(db, username="ws_cap_user")

    with TestClient(app) as client:
        client.cookies.set("session", token)
        with contextlib.ExitStack() as sockets:
            for _ in range(policy.MAX_CONNECTIONS_PER_USER):
                sockets.enter_context(_connect(client))

            with pytest.raises(WebSocketDenialResponse) as refusal:
                with _connect(client):
                    pass

            assert refusal.value.status_code == 429


def test_small_inbound_frames_are_inert_and_dispatch_still_reaches_socket(db, caplog):
    """V1 accepts no commands; its only application messages are outbound."""
    user, token = _session_for(db, username="ws_inert_frame_user")
    envelope = {
        "type": policy.EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED,
        "id": "item-1",
        "req": "request-1",
    }

    with caplog.at_level("INFO", logger=realtime_router.__name__):
        with TestClient(app) as client:
            client.cookies.set("session", token)
            with _connect(client) as socket:
                socket.send_json({"type": "delete_everything"})
                assert service.emit(envelope) is True
                assert socket.receive_json() == envelope

    delivered = next(
        record for record in caplog.records
        if record.getMessage() == "realtime.delivered"
    )
    assert delivered.request_id == envelope["req"]
    assert delivered.fields == {
        "connection_id": delivered.fields["connection_id"],
        "user_id": str(user.id),
        "event_type": envelope["type"],
        "entity_id": envelope["id"],
    }


def test_a_failed_send_does_not_claim_delivery(caplog):
    class GoneSocket:
        async def send_json(self, _envelope):
            raise WebSocketDisconnect(code=1006)

    async def scenario():
        connection = service.Connection(user_id="user-1", token_hash="hash", role="admin")
        connection.enqueue({
            "type": policy.EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED,
            "id": "item-1",
            "req": "request-1",
        })
        await realtime_router._send_pump(connection, GoneSocket())

    with caplog.at_level("INFO", logger=realtime_router.__name__):
        asyncio.run(scenario())

    assert not any(
        record.getMessage() == "realtime.delivered"
        for record in caplog.records
    )


def test_oversized_frames_close_with_1009(db, caplog):
    user, token = _session_for(db, username="ws_big_frame_user")

    with caplog.at_level("WARNING", logger=realtime_router.__name__):
        with TestClient(app) as client:
            client.cookies.set("session", token)
            with _connect(client) as socket:
                socket.send_text("x" * (policy.MAX_FRAME_BYTES + 1))
                with pytest.raises(WebSocketDisconnect) as refusal:
                    socket.receive_json()

    assert refusal.value.code == realtime_router.CLOSE_MESSAGE_TOO_BIG
    record = next(
        record for record in caplog.records
        if record.getMessage() == "realtime.frame_too_large"
    )
    assert record.fields["connection_id"]
    assert record.fields["user_id"] == str(user.id)


def test_a_frame_at_exactly_the_limit_is_accepted(db):
    _user, token = _session_for(db, username="ws_exact_frame_user")
    frame = "x" * policy.MAX_FRAME_BYTES
    envelope = {
        "type": policy.EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED,
        "id": "item-2",
        "req": "request-2",
    }
    assert len(frame.encode("utf-8")) == policy.MAX_FRAME_BYTES

    with TestClient(app) as client:
        client.cookies.set("session", token)
        with _connect(client) as socket:
            socket.send_text(frame)
            assert service.emit(envelope) is True
            assert socket.receive_json() == envelope


def test_requested_close_waits_until_the_send_pump_has_stopped():
    """A close frame must never race the endpoint's JSON data writer."""

    class BlockingSocket:
        def __init__(self):
            self.send_started = asyncio.Event()
            self.never = asyncio.Event()
            self.sending = False
            self.closes = []

        async def receive(self):
            await self.never.wait()

        async def send_json(self, _envelope):
            self.sending = True
            self.send_started.set()
            try:
                await self.never.wait()
            finally:
                self.sending = False

        async def close(self, *, code, reason):
            assert self.sending is False
            self.closes.append((code, reason))

    async def scenario():
        connection = service.Connection(user_id="1", token_hash="hash", role="admin")
        socket = BlockingSocket()
        connection.enqueue(
            {
                "type": policy.EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED,
                "id": "1",
                "req": "r",
            }
        )

        serving = asyncio.create_task(realtime_router._serve(connection, socket))
        await asyncio.wait_for(socket.send_started.wait(), timeout=1)
        assert connection.request_close(
            service.CLOSE_TRY_AGAIN_LATER,
            "send queue overflow",
        )
        await asyncio.wait_for(serving, timeout=1)

        assert socket.closes == [
            (service.CLOSE_TRY_AGAIN_LATER, "send queue overflow")
        ]

    asyncio.run(scenario())
