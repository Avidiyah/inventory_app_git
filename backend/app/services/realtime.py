"""Real-time connection state and fan-out.

Layer: services (state + orchestration, no FastAPI). The policy -- every
threshold, the envelope, the audience map -- lives in
`app.domain.realtime`; this module owns the connections and the queues.

**This is the first genuine concurrency boundary in the codebase.** The
app is entirely synchronous: 75 route handlers run in a threadpool, and
sockets live on the event loop, so a threadpool handler cannot `await` a
broadcast. `emit` is the crossing, and it has two mandatory properties:

- **Non-blocking.** A request thread must never wait on a socket. If it
  could, a phone on bad wifi could stall an inventory write, which is a
  UX-7 violation. `emit` uses `put_nowait` and returns immediately.
- **Bounded.** The handoff has a ceiling and overflow is a designed
  decision (drop newest, count it) rather than an accident. P2 is what
  makes dropping safe: the event is disposable and the client's next
  activation refetches.

**In-process, and this app runs one process.** `entrypoint.sh` starts
uvicorn with no `--workers` and `render.yaml` is one instance. A second
instance would not degrade delivery, it would silently halve it -- users
on instance A would never see events from B, with no error on either
side. That is recorded as the third and worst inheritor of the N3
multi-instance story in `docs/open-work.md`, and horizontal scaling is an
explicit non-goal until it is answered.
"""

import asyncio
import logging
import threading
import uuid
from collections import deque
from typing import Any, Optional

from app.domain import realtime as policy

logger = logging.getLogger(__name__)

# WebSocket close codes, which are transport mechanics rather than policy
# -- nothing in `app.domain.realtime` decides them. 1001 is the honest
# code for a shutdown, and 1013 tells a client that could not keep up to
# come back rather than that it did something wrong.
CLOSE_GOING_AWAY = 1001
CLOSE_TRY_AGAIN_LATER = 1013

_connections: dict[str, set["Connection"]] = {}

# The handoff is a plain deque behind a threading.Lock, NOT an asyncio.Queue.
#
# This is deliberate and the reasoning is easy to get wrong. `emit` is called
# from a request thread, so it cannot touch an asyncio.Queue directly. The
# obvious fix -- `loop.call_soon_threadsafe(queue.put_nowait, envelope)` --
# is broken: call_soon_threadsafe *schedules* the call and returns, so a
# QueueFull raises later inside the loop callback where the caller's
# try/except cannot see it. The drop would go uncounted and the request
# thread would be told the event was accepted.
#
# Checking fullness synchronously under a lock keeps the decision on the
# caller's thread, where it can be counted and reported honestly. The lock
# is held for O(1) work only, so UX-7 holds: a request thread never waits
# on a socket.
_handoff: deque = deque()
_handoff_lock = threading.Lock()
_wakeup: Optional[asyncio.Event] = None
_loop: Optional[asyncio.AbstractEventLoop] = None
_dispatch_task: Optional[asyncio.Task] = None
_dropped_events = 0

class Connection:
    """One live socket, with its own bounded outbound queue.

    Identity is minted here and stable for the socket's life. The HTTP
    logging middleware stamps a request id per request, born and retired
    in milliseconds; a socket is one long-lived entity generating many
    events over hours, so this is a second identity model alongside that
    one rather than a copy of it.

    The connection stores the session token **hash**, never the raw token.
    Periodic revalidation uses it to keep authorization current (D1); keeping
    a registry full of live credentials would violate the same boundary that
    makes `services.rate_limit.caller_key` hash its input.

    Inbound frame timestamps also live here rather than in a process-global
    map. Their lifetime is exactly the connection's lifetime, so deregistration
    is cleanup by construction and an abandoned caller cannot leave a key
    behind.
    """

    __slots__ = (
        "user_id", "token_hash", "role", "connection_id", "queue",
        "overflowed", "inbound_frames", "close_requested", "close_code",
        "close_reason", "closed",
    )

    def __init__(self, *, user_id, token_hash, role):
        self.user_id = str(user_id)
        self.token_hash = token_hash
        self.role = role
        self.connection_id = uuid.uuid4().hex[:12]
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=policy.SEND_QUEUE_MAX)
        self.overflowed = False
        self.inbound_frames: deque[float] = deque()
        self.close_requested = asyncio.Event()
        self.close_code: Optional[int] = None
        self.close_reason: Optional[str] = None
        self.closed = asyncio.Event()

    def enqueue(self, envelope: dict[str, Any]) -> bool:
        """Queue one envelope for delivery. False means this connection
        is too slow and must be closed.

        Closing a slow client is safe rather than reckless: P1 and P2
        together make invalidation events disposable, and the durable
        fact is in Postgres reachable over REST. A dropped connection is
        indistinguishable from the spin-downs and deploys that happen
        anyway, and P4 guarantees the app still works.
        """
        try:
            self.queue.put_nowait(envelope)
            return True
        except asyncio.QueueFull:
            self.overflowed = True
            return False

    def request_close(self, code: int, reason: str) -> bool:
        """Ask the endpoint that owns this connection to close it.

        The service layer deliberately has no WebSocket reference and never
        writes to the transport. Close requests are first-writer-wins because
        overflow, revocation, shutdown, and peer failure can converge on one
        connection; preserving the first cause keeps the resulting close code
        deterministic and the log line honest.

        Called only on the application event loop. `emit` is the sole
        cross-thread entry point and it never calls this method.
        """
        if self.close_requested.is_set():
            return False
        self.close_code = code
        self.close_reason = reason
        self.close_requested.set()
        return True


class DispatchSupervisor:
    """Bounded restart policy for the dispatch task (D2).

    The failure this guards against: the task dies, real-time silently
    stops for every connected user, HTTP keeps serving perfectly, health
    checks stay green, and nothing says so.
    """

    def __init__(self):
        self.restarts = 0
        self.gave_up = False

    def should_restart(self) -> bool:
        if self.restarts >= policy.DISPATCH_MAX_RESTARTS:
            self.gave_up = True
            return False
        self.restarts += 1
        return True


def register(connection: "Connection") -> bool:
    """Add a connection, or refuse it at the per-user cap.

    Per **user**, not per session: phone-plus-desktop is legitimate and
    multi-device delivery requires it. Uvicorn's protocol ping/pong and the
    endpoint's receive loop eventually remove dead peers, so zombie entries
    cannot consume cap slots indefinitely.
    """
    existing = _connections.setdefault(connection.user_id, set())
    if len(existing) >= policy.MAX_CONNECTIONS_PER_USER:
        return False
    existing.add(connection)
    return True


def deregister(connection: "Connection") -> None:
    """Remove a connection. Idempotent -- several close paths can run for
    one socket, and a leaked entry consumes a cap slot forever."""
    existing = _connections.get(connection.user_id)
    if not existing:
        return
    existing.discard(connection)
    if not existing:
        _connections.pop(connection.user_id, None)


def connection_count(user_id) -> int:
    return len(_connections.get(str(user_id), ()))


def all_connections() -> list["Connection"]:
    return [c for group in _connections.values() for c in group]


def emit(envelope: dict[str, Any]) -> bool:
    """Hand one event from a request thread to the event loop.

    Returns False when the handoff is full and the event was dropped.
    Never blocks and never raises -- an emit failure must not turn a
    successful inventory write into a 500.

    Drop-newest is D3. P2 is what makes it safe: an invalidation event is
    disposable, and the client's next page activation refetches through
    REST. What matters is that the request thread is never blocked and
    that the drop is counted rather than silent.

    Works with no running loop, which is how the tests drive it: the
    fullness decision is synchronous, and waking the loop is a separate,
    optional step that cannot fail the call.
    """
    global _dropped_events
    with _handoff_lock:
        if len(_handoff) >= policy.HANDOFF_QUEUE_MAX:
            _dropped_events += 1
            logger.warning(
                "realtime.handoff_full",
                extra={"fields": {"total_dropped": _dropped_events}},
            )
            return False
        _handoff.append(envelope)

    # Both handles are read **once**, into locals, and only the locals are
    # used below. Read twice -- once to guard and again to call -- a
    # concurrent `stop_dispatch` or `reset` could null either in between,
    # and `None.call_soon_threadsafe` or `None.set` would raise an
    # AttributeError that no `except RuntimeError` catches. This runs on a
    # request thread after the write has already committed, so anything
    # escaping here turns a successful inventory write into a 500.
    loop, wakeup = _loop, _wakeup
    if loop is not None and wakeup is not None:
        try:
            loop.call_soon_threadsafe(wakeup.set)
        except RuntimeError:
            # The loop closed between the read and the call (shutdown), so
            # nothing will consume this event. Queued-and-unsent is the
            # correct outcome then: the process is going away, and P2 makes
            # the event disposable.
            pass
        except Exception:  # pragma: no cover - belt and braces
            # The handling above is deliberately total. There is no failure
            # of the *wakeup* that is worth failing the caller's request
            # over, and the alternative is a 500 on a write that succeeded.
            logger.warning("realtime.wakeup_failed", exc_info=True)
    return True


def dropped_event_count() -> int:
    return _dropped_events


# --- dispatch ----------------------------------------------------------
#
# One task owns fan-out for the whole process. Everything below runs on
# the event loop; nothing below is called from a request thread.


def start_dispatch() -> None:
    """Bind the loop and start the supervised dispatch task.

    Called once from lifespan startup, and idempotent so a second call
    cannot produce two tasks racing over one handoff.

    `_wakeup` is bound before `_loop` on purpose: `emit` runs on another
    thread and checks both, so the loop must never be visible to it
    before the event it would signal exists.
    """
    global _loop, _wakeup, _dispatch_task

    if _dispatch_task is not None and not _dispatch_task.done():
        return

    _wakeup = asyncio.Event()
    _loop = asyncio.get_running_loop()
    _dispatch_task = _loop.create_task(_supervised_dispatch(), name="realtime-dispatch")


async def stop_dispatch() -> None:
    """Stop dispatch and request deliberate closure of every connection.

    The endpoint owns every transport write. This service signals code 1001,
    then waits a bounded interval for the endpoint's `closed` acknowledgement.
    One vanished peer can therefore neither create concurrent socket writers
    nor hold application shutdown open indefinitely.

    A client that receives the close reconnects on its own schedule; one that
    cannot acknowledge is left to Uvicorn's shutdown path after the grace
    period expires.
    """
    global _loop, _wakeup, _dispatch_task

    task, _dispatch_task = _dispatch_task, None
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:  # pragma: no cover - supervisor already logs
            logger.error("realtime.dispatch_stop_failed", exc_info=True)

    doomed = all_connections()
    _connections.clear()
    for connection in doomed:
        connection.request_close(CLOSE_GOING_AWAY, "server shutting down")

    waiters = [
        asyncio.create_task(
            connection.closed.wait(),
            name=f"realtime-close-{connection.connection_id}",
        )
        for connection in doomed
        if not connection.closed.is_set()
    ]
    if waiters:
        _done, pending = await asyncio.wait(
            waiters,
            timeout=policy.SHUTDOWN_CLOSE_GRACE_SECONDS,
        )
        if pending:
            logger.warning(
                "realtime.shutdown_close_timeout",
                extra={"fields": {
                    "pending": len(pending),
                    "grace_seconds": policy.SHUTDOWN_CLOSE_GRACE_SECONDS,
                }},
            )
        for waiter in pending:
            waiter.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    _loop = None
    _wakeup = None


async def _supervised_dispatch() -> None:
    """Run the dispatch loop, restarting it a bounded number of times.

    Giving up is logged at ERROR with an unmistakable event name because
    of how this fails in production: real-time stops for every connected
    user while HTTP keeps serving perfectly and `/healthz` stays green.
    Nothing else in the system reports it.
    """
    supervisor = DispatchSupervisor()

    while True:
        try:
            await _dispatch_loop()
            return
        except asyncio.CancelledError:
            raise
        except Exception:
            will_restart = supervisor.should_restart()
            logger.error(
                "realtime.dispatch_crashed",
                exc_info=True,
                extra={"fields": {
                    "restarts": supervisor.restarts,
                    "will_restart": will_restart,
                    "connections": len(all_connections()),
                }},
            )
            if not will_restart:
                logger.error(
                    "realtime.dispatch_gave_up",
                    extra={"fields": {
                        "restarts": supervisor.restarts,
                        "restart_limit": policy.DISPATCH_MAX_RESTARTS,
                        "connections": len(all_connections()),
                        "detail": "real-time delivery is stopped until restart",
                    }},
                )
                return


async def _dispatch_loop() -> None:
    """Wait for events, drain the handoff, fan out.

    The wakeup is cleared *before* the drain, not after. Cleared after,
    an event queued mid-drain would set a flag this loop then wipes, and
    it would sit unsent until something unrelated emitted again. Cleared
    first, the worst case is one spurious wakeup that finds nothing.

    The non-empty check at the top of each pass covers the two cases
    where the flag cannot be trusted: events emitted before the loop
    existed (`emit` works with no loop), and events left behind by a
    crash mid-drain that the supervisor has just restarted us from.
    """
    wakeup = _wakeup
    if wakeup is None:  # pragma: no cover - start_dispatch always binds it
        raise RuntimeError("dispatch started without a wakeup event")

    while True:
        if _handoff:
            wakeup.set()
        await wakeup.wait()
        wakeup.clear()

        while True:
            with _handoff_lock:
                if not _handoff:
                    break
                envelope = _handoff.popleft()
            _fan_out(envelope)


def _fan_out(envelope: dict[str, Any]) -> None:
    """Deliver one envelope to every connection whose role may see it.

    Synchronous on purpose: `enqueue` is non-blocking, so fan-out to
    hundreds of connections costs no awaits and cannot interleave with a
    second envelope halfway through.
    """
    event_type = envelope.get("type")

    for connection in all_connections():
        if not policy.audience_allows(event_type, connection.role):
            continue
        if connection.enqueue(envelope):
            continue

        # Backpressure, and it is a decision rather than a failure: this
        # socket cannot drain what it is already holding, so it is closed.
        # Deregistering first frees the cap slot immediately and keeps the
        # next envelope from being fanned out to a socket already going
        # away.
        logger.warning(
            "realtime.connection_overflowed",
            extra={"fields": {
                "connection_id": connection.connection_id,
                "user_id": connection.user_id,
                "depth": policy.SEND_QUEUE_MAX,
            }},
        )
        deregister(connection)
        connection.request_close(
            CLOSE_TRY_AGAIN_LATER,
            "send queue overflow",
        )


def reset() -> None:
    """Discard all state. For tests -- module state is process global, so a
    test that fills the handoff would otherwise leak into the next one.
    Mirrors `services.rate_limit.reset`."""
    global _dropped_events, _wakeup, _loop, _dispatch_task

    if _dispatch_task is not None and not _dispatch_task.done():
        # A task left running against a closed loop is exactly the kind of
        # leak this function exists to prevent; dropping the handle alone
        # would not stop it.
        try:
            _dispatch_task.cancel()
        except RuntimeError:  # pragma: no cover - loop already gone
            pass

    _connections.clear()
    with _handoff_lock:
        _handoff.clear()
    _dropped_events = 0
    _wakeup = None
    _loop = None
    _dispatch_task = None
