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

# In-flight socket closes. Held only so the tasks are not garbage collected
# mid-close -- asyncio keeps a weak reference to a running task, and a
# fire-and-forget close that is collected simply never happens.
_closing: set[asyncio.Task] = set()


class Connection:
    """One live socket, with its own bounded outbound queue.

    Identity is minted here and stable for the socket's life. The HTTP
    logging middleware stamps a request id per request, born and retired
    in milliseconds; a socket is one long-lived entity generating many
    events over hours, so this is a second identity model alongside that
    one rather than a copy of it.

    The connection stores the session token **hash**, never the raw
    token: it re-resolves its session on a timer (D1) and a registry full
    of live credentials is exactly what `services.rate_limit.caller_key`
    hashes to avoid.
    """

    __slots__ = (
        "user_id", "token_hash", "role", "websocket",
        "connection_id", "queue", "overflowed",
    )

    def __init__(self, *, user_id, token_hash, role, websocket):
        self.user_id = str(user_id)
        self.token_hash = token_hash
        self.role = role
        self.websocket = websocket
        self.connection_id = uuid.uuid4().hex[:12]
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=policy.SEND_QUEUE_MAX)
        self.overflowed = False

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
    multi-device delivery requires it. Correctness depends on the
    heartbeat -- enough zombie entries and a legitimate user is locked out
    by their own dead sockets.
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
    """Stop dispatch and close every connection deliberately.

    The close is the point. A client that is dropped without one sees a
    network fault and reconnects on the shortest backoff it has, so a
    deploy would be followed by every client retrying at once; a clean
    close lets each reconnect on its own schedule.

    Closes run concurrently, so shutdown waits for the slowest socket
    rather than the sum of all of them.
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

    # In-flight overflow closes are cancelled, not awaited. Those sockets
    # are already out of the registry and already going away, and they are
    # by definition the slow ones -- waiting on them is how a shutdown that
    # should take milliseconds ends at the platform's SIGKILL instead.
    in_flight = list(_closing)
    _closing.clear()
    for task in in_flight:
        task.cancel()
    if in_flight:
        await asyncio.gather(*in_flight, return_exceptions=True)

    doomed = all_connections()
    _connections.clear()
    if doomed:
        await asyncio.gather(
            *(
                _close_quietly(connection, CLOSE_GOING_AWAY, "server shutting down")
                for connection in doomed
            ),
            return_exceptions=True,
        )

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
            logger.error(
                "realtime.dispatch_crashed",
                exc_info=True,
                extra={"fields": {
                    "restarts": supervisor.restarts,
                    "connections": len(all_connections()),
                }},
            )
            if not supervisor.should_restart():
                logger.error(
                    "realtime.dispatch_gave_up",
                    extra={"fields": {
                        "restarts": supervisor.restarts,
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
        _close_in_background(connection, CLOSE_TRY_AGAIN_LATER, "send queue overflow")


def _close_in_background(connection: "Connection", code: int, reason: str) -> None:
    """Close a socket beside the dispatch loop rather than inside it.

    The connections closed here are by definition the ones that cannot
    keep up, which makes them the ones whose close is most likely to
    block on a full transport buffer. Awaiting that inline would let one
    phone on bad wifi stall delivery for every other user -- the same
    failure `emit` exists to prevent, one layer in.
    """
    if connection.websocket is None:
        return
    task = asyncio.ensure_future(_close_quietly(connection, code, reason))
    _closing.add(task)
    task.add_done_callback(_closing.discard)


async def _close_quietly(connection: "Connection", code: int, reason: str) -> None:
    """Close one socket, tolerating a peer that has already vanished.

    A close that raises is not interesting: the socket is going away
    either way, and the connection is already out of the registry.
    """
    websocket = connection.websocket
    if websocket is None:
        return
    try:
        await websocket.close(code=code, reason=reason)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.info(
            "realtime.close_failed",
            extra={"fields": {"connection_id": connection.connection_id}},
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
    _closing.clear()
    _wakeup = None
    _loop = None
    _dispatch_task = None
