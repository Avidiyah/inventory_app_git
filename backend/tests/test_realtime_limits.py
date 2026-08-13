"""State and endpoint enforcement for the two Task 8 WebSocket limits."""

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from starlette.testclient import WebSocketDenialResponse
from starlette.websockets import WebSocketDisconnect

from app.auth_deps import SESSION_COOKIE
from app.domain import rate_limit as rate_policy
from app.domain import realtime as policy
from app.main import app
from app.models import User
from app.routers import realtime as realtime_router
from app.services import auth as auth_service
from app.services import rate_limit as http_rate_limit
from app.services import realtime as realtime_service
from app.services import realtime_limits


SAME_ORIGIN = {"origin": "http://testserver"}


@pytest.fixture(autouse=True)
def _clean_process_state():
    realtime_limits.reset()
    http_rate_limit.reset()
    realtime_service.reset()
    yield
    realtime_service.reset()
    http_rate_limit.reset()
    realtime_limits.reset()


@pytest.fixture
def endpoint_db(db, monkeypatch):
    """Point the endpoint's short-lived sessions at the test transaction."""
    connection = db.get_bind()

    def factory():
        return Session(
            bind=connection,
            join_transaction_mode="create_savepoint",
            autoflush=False,
        )

    monkeypatch.setattr(realtime_router, "SessionLocal", factory)
    return db


def _session_for(db, *, username: str):
    user = User(
        username=username,
        first_name="Ws",
        last_name="Limits",
        role="admin",
        password_hash=auth_service.hash_password("correct horse"),
    )
    db.add(user)
    db.flush()
    db.commit()
    return user, auth_service.create_session(db, user)


def _connect(client: TestClient):
    return client.websocket_connect("/ws", headers=dict(SAME_ORIGIN))


def _connection(*, user_id: str):
    return realtime_service.Connection(
        user_id=user_id,
        token_hash="a" * 64,
        role="admin",
    )


# --- process-local service state --------------------------------------


def test_exactly_the_handshake_cap_is_allowed_then_retry_after_is_returned():
    key = "s:caller"

    for _ in range(policy.HANDSHAKE_MAX_ATTEMPTS):
        assert realtime_limits.check_handshake_and_record(key, 1000.0) is None

    assert realtime_limits.check_handshake_and_record(key, 1000.0) == 60
    assert len(realtime_limits._handshake_buckets[key]) == policy.HANDSHAKE_MAX_ATTEMPTS


def test_rejected_handshakes_do_not_extend_the_lockout():
    key = "s:looping-caller"
    for _ in range(policy.HANDSHAKE_MAX_ATTEMPTS):
        realtime_limits.check_handshake_and_record(key, 1000.0)

    for _ in range(500):
        assert realtime_limits.check_handshake_and_record(key, 1000.0) == 60

    assert realtime_limits.check_handshake_and_record(
        key,
        1000.0 + policy.HANDSHAKE_WINDOW_SECONDS + 0.001,
    ) is None


def test_handshake_callers_are_isolated_and_idle_buckets_are_swept():
    for _ in range(policy.HANDSHAKE_MAX_ATTEMPTS):
        realtime_limits.check_handshake_and_record("s:old", 1000.0)

    assert realtime_limits.check_handshake_and_record("s:other", 1000.0) is None
    later = 1000.0 + realtime_limits.SWEEP_INTERVAL_SECONDS + 1.0
    assert realtime_limits.check_handshake_and_record("s:new", later) is None
    assert "s:old" not in realtime_limits._handshake_buckets
    assert "s:new" in realtime_limits._handshake_buckets


def test_websocket_and_http_budgets_are_independent_even_when_ws_resets():
    key = "s:shared-identity"
    for _ in range(policy.HANDSHAKE_MAX_ATTEMPTS):
        assert realtime_limits.check_handshake_and_record(key, 1000.0) is None
    assert realtime_limits.check_handshake_and_record(key, 1000.0) == 60

    for _ in range(rate_policy.MAX_REQUESTS):
        assert http_rate_limit.check_and_record(key, 1000.0) is None
    assert http_rate_limit.check_and_record(key, 1000.0) == 1

    realtime_limits.reset()
    assert http_rate_limit.check_and_record(key, 1000.0) == 1


def test_exactly_the_inbound_frame_cap_is_allowed_per_connection():
    first = _connection(user_id="first")
    second = _connection(user_id="second")

    for _ in range(policy.INBOUND_MAX_FRAMES):
        assert realtime_limits.inbound_frame_allowed(first, 1000.0) is True

    assert realtime_limits.inbound_frame_allowed(first, 1000.0) is False
    assert len(first.inbound_frames) == policy.INBOUND_MAX_FRAMES
    assert realtime_limits.inbound_frame_allowed(second, 1000.0) is True


def test_inbound_frame_budget_returns_after_the_sliding_window():
    connection = _connection(user_id="sliding")
    for _ in range(policy.INBOUND_MAX_FRAMES):
        realtime_limits.inbound_frame_allowed(connection, 1000.0)

    assert realtime_limits.inbound_frame_allowed(connection, 1000.0) is False
    assert realtime_limits.inbound_frame_allowed(
        connection,
        1000.0 + policy.INBOUND_WINDOW_SECONDS + 0.001,
    ) is True


# --- endpoint ordering and protocol behavior --------------------------


def test_foreign_origin_is_rejected_before_the_handshake_counter(monkeypatch):
    def forbidden_counter(_key, _now):
        raise AssertionError("foreign origin reached the handshake counter")

    monkeypatch.setattr(
        realtime_limits,
        "check_handshake_and_record",
        forbidden_counter,
    )

    with TestClient(app) as client:
        with pytest.raises(WebSocketDenialResponse) as refusal:
            with client.websocket_connect(
                "/ws",
                headers={"origin": "https://other.example"},
            ):
                pass

    assert refusal.value.status_code == 403


def test_missing_cookie_attempts_use_the_ip_budget_and_return_retry_after(
    monkeypatch,
):
    monkeypatch.setattr(realtime_router, "monotonic", lambda: 1000.0)

    with TestClient(app) as client:
        for _ in range(policy.HANDSHAKE_MAX_ATTEMPTS):
            with pytest.raises(WebSocketDenialResponse) as refusal:
                with _connect(client):
                    pass
            assert refusal.value.status_code == 401

        with pytest.raises(WebSocketDenialResponse) as refusal:
            with _connect(client):
                pass

    assert refusal.value.status_code == 429
    assert refusal.value.headers["retry-after"] == "60"
    assert refusal.value.json() == {
        "detail": "Too many WebSocket connection attempts."
    }
    assert "i:testclient" in realtime_limits._handshake_buckets


def test_endpoint_reuses_caller_key_without_storing_the_raw_token(monkeypatch):
    token = "live-cookie-value"
    captured = {}
    real_caller_key = http_rate_limit.caller_key

    def caller_key_spy(session_token, ip):
        captured["token"] = session_token
        captured["ip"] = ip
        captured["key"] = real_caller_key(session_token, ip)
        return captured["key"]

    def refuse(key, _now):
        captured["counter_key"] = key
        return 17

    monkeypatch.setattr(http_rate_limit, "caller_key", caller_key_spy)
    monkeypatch.setattr(realtime_limits, "check_handshake_and_record", refuse)

    with TestClient(app) as client:
        client.cookies.set(SESSION_COOKIE, token)
        with pytest.raises(WebSocketDenialResponse) as refusal:
            with _connect(client):
                pass

    assert refusal.value.status_code == 429
    assert refusal.value.headers["retry-after"] == "17"
    assert captured == {
        "token": token,
        "ip": "testclient",
        "key": real_caller_key(token, "testclient"),
        "counter_key": real_caller_key(token, "testclient"),
    }
    assert token not in captured["counter_key"]


def test_throttled_handshake_never_reaches_session_resolution(monkeypatch):
    def forbidden_resolver(_token_hash):
        raise AssertionError("rate-limited handshake reached the database")

    monkeypatch.setattr(realtime_router, "_resolve_identity", forbidden_resolver)
    monkeypatch.setattr(
        realtime_limits,
        "check_handshake_and_record",
        lambda _key, _now: 11,
    )

    with TestClient(app) as client:
        client.cookies.set(SESSION_COOKIE, "some-token")
        with pytest.raises(WebSocketDenialResponse) as refusal:
            with _connect(client):
                pass

    assert refusal.value.status_code == 429
    assert refusal.value.headers["retry-after"] == "11"


def test_receive_loop_requests_1008_when_the_frame_budget_is_exhausted(
    monkeypatch,
):
    class ScriptedSocket:
        def __init__(self):
            self.messages = [
                {"type": "websocket.receive", "text": "inert"}
                for _ in range(policy.INBOUND_MAX_FRAMES + 1)
            ]
            self.messages.append({"type": "websocket.disconnect"})

        async def receive(self):
            return self.messages.pop(0)

    connection = _connection(user_id="scripted")
    monkeypatch.setattr(realtime_router, "monotonic", lambda: 1000.0)

    asyncio.run(realtime_router._receive_loop(connection, ScriptedSocket()))

    assert connection.close_requested.is_set() is True
    assert connection.close_code == realtime_router.CLOSE_POLICY_VIOLATION
    assert connection.close_reason == "inbound frame rate exceeded"


def test_exactly_the_frame_cap_is_inert_then_the_next_frame_closes_1008(
    endpoint_db,
    monkeypatch,
):
    _user, token = _session_for(endpoint_db, username="ws_frame_rate_user")
    monkeypatch.setattr(realtime_router, "monotonic", lambda: 1000.0)
    envelope = {
        "type": policy.EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED,
        "id": "work-order-1",
        "req": "request-1",
    }

    with TestClient(app) as client:
        client.cookies.set(SESSION_COOKIE, token)
        with _connect(client) as socket:
            for _ in range(policy.INBOUND_MAX_FRAMES // 2):
                socket.send_text("inert")
                socket.send_bytes(b"inert")

            assert realtime_service.emit(envelope) is True
            assert socket.receive_json() == envelope

            socket.send_text("one too many")
            with pytest.raises(WebSocketDisconnect) as refusal:
                socket.receive_json()

    assert refusal.value.code == realtime_router.CLOSE_POLICY_VIOLATION
    assert refusal.value.reason == "inbound frame rate exceeded"


def test_oversized_frame_keeps_1009_precedence_at_the_rate_boundary(
    endpoint_db,
    monkeypatch,
):
    _user, token = _session_for(endpoint_db, username="ws_size_precedence_user")
    monkeypatch.setattr(realtime_router, "monotonic", lambda: 1000.0)

    with TestClient(app) as client:
        client.cookies.set(SESSION_COOKIE, token)
        with _connect(client) as socket:
            for _ in range(policy.INBOUND_MAX_FRAMES):
                socket.send_text("inert")
            socket.send_text("x" * (policy.MAX_FRAME_BYTES + 1))

            with pytest.raises(WebSocketDisconnect) as refusal:
                socket.receive_json()

    assert refusal.value.code == realtime_router.CLOSE_MESSAGE_TOO_BIG
    assert refusal.value.reason == "frame too large"
