"""Connection registry, bounded handoff, and dispatch supervision.

These are the parts that make the socket safe rather than merely working:
the registry is what the concurrency cap is checked against, and the
handoff is the boundary between 75 synchronous threadpool handlers and a
single event loop.
"""

import asyncio

import pytest

from app.domain import realtime as policy
from app.services import realtime as service


@pytest.fixture(autouse=True)
def _clean_registry():
    service.reset()
    yield
    service.reset()


def _conn(user_id="user-1", role="admin"):
    return service.Connection(
        user_id=user_id,
        token_hash="a" * 64,
        role=role,
    )


# --- registry ----------------------------------------------------------


def test_registry_is_keyed_by_user_not_by_connection():
    """One person on two devices must receive on both. A flat set of
    sockets supports broadcast only; a keyed map supports broadcast,
    targeted delivery, multi-device, and per-user revocation -- which is
    what makes messaging additive later."""
    first, second = _conn(), _conn()

    assert service.register(first) is True
    assert service.register(second) is True
    assert service.connection_count("user-1") == 2


def test_registry_refuses_past_the_concurrency_cap():
    accepted = [
        service.register(_conn()) for _ in range(policy.MAX_CONNECTIONS_PER_USER + 2)
    ]

    assert accepted.count(True) == policy.MAX_CONNECTIONS_PER_USER
    assert accepted.count(False) == 2
    assert service.connection_count("user-1") == policy.MAX_CONNECTIONS_PER_USER


def test_deregistration_frees_a_cap_slot():
    """Leaked entries consume cap slots and produce phantom fan-out
    targets. Enough zombies and a legitimate user is locked out by their
    own dead sockets."""
    connections = [_conn() for _ in range(policy.MAX_CONNECTIONS_PER_USER)]
    for connection in connections:
        service.register(connection)

    assert service.register(_conn()) is False

    service.deregister(connections[0])

    assert service.register(_conn()) is True


def test_deregistering_twice_is_harmless():
    """Every close path -- clean, error, timeout, revocation, shutdown --
    deregisters, and several can run for one connection."""
    connection = _conn()
    service.register(connection)

    service.deregister(connection)
    service.deregister(connection)

    assert service.connection_count("user-1") == 0


def test_users_have_independent_caps():
    for _ in range(policy.MAX_CONNECTIONS_PER_USER):
        service.register(_conn(user_id="user-1"))

    assert service.register(_conn(user_id="user-2")) is True


# --- handoff -----------------------------------------------------------


def test_emit_never_blocks_and_reports_acceptance():
    assert service.emit({"type": "work_order.review_queue.changed"}) is True


def test_emit_drops_newest_when_the_handoff_is_full():
    """D3. Dropping is safe because of P2 -- an invalidation event is
    disposable, and the client's next page activation refetches. What
    matters is that a request thread is never blocked (UX-7) and that the
    drop is counted rather than silent."""
    for _ in range(policy.HANDOFF_QUEUE_MAX):
        service.emit({"type": "work_order.review_queue.changed"})

    assert service.emit({"type": "work_order.review_queue.changed"}) is False
    assert service.dropped_event_count() == 1


def test_dropped_events_are_counted_cumulatively():
    for _ in range(policy.HANDOFF_QUEUE_MAX + 3):
        service.emit({"type": "work_order.review_queue.changed"})

    assert service.dropped_event_count() == 3


def test_a_dropped_event_is_logged_as_a_greppable_event_name(caplog):
    """A line that is present but anonymous is worse than one that is
    absent: a missing line gets noticed, an unfilterable one looks fine
    until the day the drop counter is the question. The app's format puts
    the message in the `event=` slot and structured data in `fields`, so a
    prose message with the count inlined would render as one quoted,
    escaped blob that `grep event=realtime.handoff_full` never finds."""
    for _ in range(policy.HANDOFF_QUEUE_MAX):
        service.emit({"type": "work_order.review_queue.changed"})

    with caplog.at_level("WARNING"):
        assert service.emit({"type": "work_order.review_queue.changed"}) is False

    record = next(
        r for r in caplog.records if r.getMessage() == "realtime.handoff_full"
    )
    assert record.fields == {"total_dropped": 1}


# --- backpressure ------------------------------------------------------


def test_send_queue_overflow_marks_the_connection_for_closure():
    """D6/§7.5. Nothing else protects the server from a *slow* client: a
    phone on one bar cannot drain what it is sent, and that is a bad
    connection rather than abuse, which is exactly why a rate limiter
    never catches it.

    Closing is lossless because of P1 and P2 -- the event is disposable
    and the durable fact is in Postgres, reachable over REST."""
    connection = _conn()

    for _ in range(policy.SEND_QUEUE_MAX):
        assert connection.enqueue({"type": "work_order.review_queue.changed"}) is True

    assert connection.enqueue({"type": "work_order.review_queue.changed"}) is False
    assert connection.overflowed is True


def test_connection_has_no_transport_reference():
    """Only the endpoint may write or close a WebSocket. Keeping the
    transport out of the registry makes that boundary structural."""
    assert not hasattr(_conn(), "websocket")


def test_first_close_request_wins():
    connection = _conn()

    assert connection.request_close(1013, "send queue overflow") is True
    assert connection.request_close(1001, "server shutting down") is False

    assert connection.close_requested.is_set()
    assert connection.close_code == 1013
    assert connection.close_reason == "send queue overflow"


# --- dispatch supervision ----------------------------------------------


def test_dispatch_restarts_are_bounded():
    """D2. A transient fault should not kill real-time for hours; a crash
    loop must not look identical to healthy operation, which is the
    silent-failure mode §8.3 names."""
    assert policy.DISPATCH_MAX_RESTARTS >= 1

    supervisor = service.DispatchSupervisor()

    for _ in range(policy.DISPATCH_MAX_RESTARTS):
        assert supervisor.should_restart() is True

    assert supervisor.should_restart() is False


def test_supervisor_reports_permanent_failure():
    supervisor = service.DispatchSupervisor()
    for _ in range(policy.DISPATCH_MAX_RESTARTS + 1):
        supervisor.should_restart()

    assert supervisor.gave_up is True


# --- the dispatch task itself ------------------------------------------
#
# The suite has no async plugin, so these follow `test_rate_limit_middleware`
# and drive a coroutine with `asyncio.run`. `_settle` polls instead of
# sleeping a fixed interval: a fixed sleep is either flaky or slow, and this
# is the one place in the suite where another task has to make progress
# before an assertion is meaningful.


async def _settle(predicate, timeout=2.0):
    """Yield until `predicate` holds, or give up. Returns the outcome so a
    timeout fails the assertion rather than hanging the suite."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            return False
        await asyncio.sleep(0.001)
    return True


async def _stop_cleanly():
    """Acknowledge endpoint ownership when a service-only scenario ends."""
    for connection in service.all_connections():
        connection.closed.set()
    await service.stop_dispatch()


def test_dispatch_delivers_only_to_the_permitted_audience():
    """The audience map is an efficiency concern, not a security boundary
    (P2 -- the envelope carries no data), but a technician's socket should
    not be woken for an event no technician view consumes."""
    admin = _conn(user_id="user-1", role="admin")
    technician = _conn(user_id="user-2", role="technician")

    async def scenario():
        service.register(admin)
        service.register(technician)
        service.start_dispatch()

        service.emit(
            {"type": policy.EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED, "id": "7"}
        )

        assert await _settle(lambda: admin.queue.qsize() == 1)
        assert technician.queue.qsize() == 0
        assert admin.queue.get_nowait() == {
            "type": policy.EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED,
            "id": "7",
        }

        await _stop_cleanly()

    asyncio.run(scenario())


def test_dispatch_drains_events_emitted_before_the_loop_existed():
    """`emit` works with no running loop -- that is what makes the
    fullness decision synchronous -- so the queue can already hold events
    when dispatch starts."""
    connection = _conn()

    async def scenario():
        service.register(connection)
        service.emit(
            {"type": policy.EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED, "id": "1"}
        )

        service.start_dispatch()

        assert await _settle(lambda: connection.queue.qsize() == 2)
        await _stop_cleanly()

    # Emitted with no event loop running anywhere in the process.
    service.emit(
        {"type": policy.EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED, "id": "0"}
    )
    asyncio.run(scenario())

    assert [connection.queue.get_nowait()["id"] for _ in range(2)] == ["0", "1"]


def test_dispatch_closes_and_deregisters_a_connection_that_overflows():
    """The backpressure policy: a socket that cannot drain what it is sent
    is closed, not buffered. Deregistration is immediate so the cap slot
    is freed and no later event is fanned out to a doomed socket."""
    connection = _conn()
    for _ in range(policy.SEND_QUEUE_MAX):
        connection.enqueue({"type": policy.EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED})

    async def scenario():
        service.register(connection)
        service.start_dispatch()

        service.emit(
            {"type": policy.EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED, "id": "9"}
        )

        assert await _settle(connection.close_requested.is_set)
        assert service.connection_count("user-1") == 0
        assert connection.overflowed is True
        assert connection.close_code == service.CLOSE_TRY_AGAIN_LATER
        assert connection.close_reason == "send queue overflow"

        await service.stop_dispatch()

    asyncio.run(scenario())


def test_an_overflow_close_request_does_not_stall_dispatch_for_everyone_else():
    """The service signals closure without touching the socket, so one
    slow peer cannot stall fan-out for every healthy connection."""
    slow = _conn(user_id="user-slow")
    for _ in range(policy.SEND_QUEUE_MAX):
        slow.enqueue({"type": policy.EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED})
    healthy = _conn(user_id="user-fine")

    async def scenario():
        service.register(slow)
        service.register(healthy)
        service.start_dispatch()

        service.emit(
            {"type": policy.EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED, "id": "1"}
        )
        service.emit(
            {"type": policy.EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED, "id": "2"}
        )

        assert await _settle(lambda: healthy.queue.qsize() == 2)
        assert slow.close_requested.is_set()

        await _stop_cleanly()

    asyncio.run(scenario())


def test_stop_dispatch_requests_every_connection_close_and_waits_for_ack():
    """A clean close lets the client reconnect on its own schedule. Being
    dropped without one looks like a network fault, and every client
    reconnects at once."""
    connections = [
        _conn(user_id="user-1"),
        _conn(user_id="user-2"),
    ]

    async def scenario():
        for connection in connections:
            service.register(connection)
        service.start_dispatch()

        async def acknowledge(connection):
            await connection.close_requested.wait()
            connection.closed.set()

        acknowledgements = [
            asyncio.create_task(acknowledge(connection))
            for connection in connections
        ]
        await service.stop_dispatch()
        await asyncio.gather(*acknowledgements)

    asyncio.run(scenario())

    assert all(connection.close_code == service.CLOSE_GOING_AWAY for connection in connections)
    assert all(connection.close_reason == "server shutting down" for connection in connections)
    assert service.connection_count("user-1") == 0
    assert service.connection_count("user-2") == 0


def test_stop_dispatch_timeout_is_bounded_and_logged(monkeypatch, caplog):
    connection = _conn()
    monkeypatch.setattr(service.policy, "SHUTDOWN_CLOSE_GRACE_SECONDS", 0.0)

    async def scenario():
        service.register(connection)
        service.start_dispatch()
        await service.stop_dispatch()

    with caplog.at_level("WARNING"):
        asyncio.run(scenario())

    assert any(
        record.getMessage() == "realtime.shutdown_close_timeout"
        for record in caplog.records
    )


def test_stop_dispatch_without_a_start_is_harmless():
    asyncio.run(service.stop_dispatch())


def test_emit_does_not_raise_when_the_loop_has_already_closed():
    """`emit` runs on a request thread *after* the write has committed, so
    anything that escapes it turns a successful inventory write into a 500.
    Shutdown is the realistic case: the loop can be gone while the module
    still holds handles to it, and an in-flight request finds them."""

    async def scenario():
        service.start_dispatch()
        # Deliberately no stop_dispatch. `asyncio.run` closes the loop out
        # from under the module, leaving _loop and _wakeup bound to a dead
        # loop -- which is exactly what a request thread can find mid-shutdown.

    asyncio.run(scenario())

    assert (
        service.emit({"type": policy.EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED}) is True
    )
    assert service.dropped_event_count() == 0


def test_emit_does_not_raise_once_the_handles_are_cleared():
    """The other half of the same shutdown window: handles nulled rather
    than pointing at a dead loop."""

    async def scenario():
        service.start_dispatch()
        await service.stop_dispatch()

    asyncio.run(scenario())

    assert (
        service.emit({"type": policy.EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED}) is True
    )


def test_dispatch_restarts_after_a_transient_fault(monkeypatch, caplog):
    """D2's first half: a one-off fault must not end real-time until the
    next deploy."""
    connection = _conn()
    calls = {"n": 0}
    real = policy.audience_allows

    def flaky(event_type, role):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")
        return real(event_type, role)

    monkeypatch.setattr(service.policy, "audience_allows", flaky)

    async def scenario():
        service.register(connection)
        service.start_dispatch()

        service.emit(
            {"type": policy.EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED, "id": "1"}
        )
        assert await _settle(lambda: calls["n"] >= 1)

        service.emit(
            {"type": policy.EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED, "id": "2"}
        )
        assert await _settle(lambda: connection.queue.qsize() >= 1)

        await _stop_cleanly()

    with caplog.at_level("ERROR", logger=service.__name__):
        asyncio.run(scenario())

    crashed = next(
        record for record in caplog.records
        if record.getMessage() == "realtime.dispatch_crashed"
    )
    assert crashed.levelname == "ERROR"
    assert crashed.fields["restarts"] == 1
    assert crashed.fields["will_restart"] is True


def test_dispatch_gives_up_loudly_after_the_restart_cap(caplog):
    """D2's second half, and the §8.3 silent-failure mode: when the task
    stops for good, HTTP keeps serving perfectly and health checks stay
    green. The log line is the only thing that says real-time is gone, so
    its absence is the actual defect."""
    connection = _conn()

    def always_fails(event_type, role):
        raise RuntimeError("permanent")

    def gave_up():
        return any(
            record.getMessage() == "realtime.dispatch_gave_up"
            for record in caplog.records
        )

    async def scenario():
        service.register(connection)
        service.start_dispatch()

        for index in range(policy.DISPATCH_MAX_RESTARTS + 2):
            service.emit(
                {
                    "type": policy.EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED,
                    "id": str(index),
                }
            )

        assert await _settle(gave_up)
        await _stop_cleanly()

    with caplog.at_level("ERROR"):
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(service.policy, "audience_allows", always_fails)
            asyncio.run(scenario())

    assert connection.queue.qsize() == 0
    crashed = [
        record for record in caplog.records
        if record.getMessage() == "realtime.dispatch_crashed"
    ]
    gave_up_record = next(
        record for record in caplog.records
        if record.getMessage() == "realtime.dispatch_gave_up"
    )
    assert crashed[-1].levelname == "ERROR"
    assert crashed[-1].fields["restarts"] == policy.DISPATCH_MAX_RESTARTS
    assert crashed[-1].fields["will_restart"] is False
    assert gave_up_record.levelname == "ERROR"
    assert gave_up_record.fields["restarts"] == policy.DISPATCH_MAX_RESTARTS
    assert gave_up_record.fields["restart_limit"] == policy.DISPATCH_MAX_RESTARTS
    assert "stopped until restart" in gave_up_record.fields["detail"]
