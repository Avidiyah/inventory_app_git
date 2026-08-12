"""The real-time WebSocket endpoint, and the application lifespan.

Layer: routers. One endpoint -- `/ws` -- and every rule it enforces is
written here rather than inherited. That is design principle P5, and in
this file it is not a stylistic preference:

**None of the app's middleware runs for this route.** The three layers in
`app.main` (`rate_limit`, `add_security_headers`, `log_request`) are
registered with `@app.middleware("http")`, and a handshake arrives in a
`websocket` scope. It never enters any of them -- despite being an HTTP
GET on the wire. This endpoint inherits no rate limiting, no security
headers, and no request-id logging scope. A reader who assumes otherwise,
reasonably, because every other route in the app is wrapped, gets it
wrong in the dangerous direction: believing a limit exists that does not.
So with one endpoint, the whole policy is readable in one file.

Authentication reuses the existing session cookie and the existing
resolver. No new token scheme, no new credential, no change to how anyone
logs in: a socket is exactly as authenticated as the page that opened it,
and revoking a session revokes the socket with it.

Refusal happens **before** `accept()`. A missing cookie, an unresolvable
session, and a user already at `MAX_CONNECTIONS_PER_USER` are all decided
while the handshake is still a handshake, so a refused caller costs one
close frame rather than a registered connection that has to be unwound.
Note the protocol limit this runs into: **there is no `Retry-After` on a
WebSocket close.** The server closes with a code and the client derives
its own wait; a wait hint, if one is ever needed, has to ride in an
application frame *before* the close.

**P3 is permanent: the socket never mutates anything.** The only inbound
frame this version understands is a ping, and there will never be an
inbound frame that changes state. Frames it does not understand are
ignored rather than fatal -- an unknown type is at worst a client from a
newer deploy, and dropping the connection over one would turn a frontend
release into a disconnect storm.

What is deliberately *not* here, because later tasks own it: the
handshake attempt limiter and the inbound frame-rate limiter, the
heartbeat, and periodic session revalidation. The seams they need exist
-- inbound frames are already accepted and validated here, and
`Connection` already carries the session hash it will re-resolve.
"""

import contextlib
import json
import logging
from typing import Optional

import anyio
from fastapi import APIRouter, WebSocket
from starlette.concurrency import run_in_threadpool
from starlette.websockets import WebSocketDisconnect

from app.auth_deps import SESSION_COOKIE
from app.database import SessionLocal
from app.domain import realtime as policy
from app.services import auth as auth_service
from app.services.realtime import (
    CLOSE_TRY_AGAIN_LATER,
    Connection,
    deregister,
    register,
    start_dispatch,
    stop_dispatch,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Close codes used by this endpoint. Transport mechanics rather than
# policy -- nothing in `app.domain.realtime` decides them -- and the two
# that already had a home live in `app.services.realtime` beside the
# shutdown and backpressure closes that use them.
#
# 1008 is "policy violation" and is what every pre-accept refusal sends,
# per the task brief. Worth knowing when the client is written: it is the
# code for *both* "you are not authenticated" (do not retry, re-login)
# and "you are at the connection cap" (do retry later), so the client
# cannot tell those apart from the code alone.
CLOSE_POLICY_VIOLATION = 1008

# 1009 is the standard "message too big". Distinct from 1008 on purpose:
# an oversized frame is the one refusal that happens *after* accept, and
# it says nothing about the caller's credentials.
CLOSE_MESSAGE_TOO_BIG = 1009

# The only server->client frame this task produces. It is not an event,
# so it deliberately does not go through `policy.build_envelope` -- that
# envelope's four keys are the *event* contract, and widening it to also
# describe liveness replies is how a wire format starts meaning two
# things.
#
# Lives here rather than in `app.domain.realtime` beside `INBOUND_PING`
# only because this task's file list is the endpoint and `main.py`.
OUTBOUND_PONG = "pong"


def _resolve_identity(token_hash: str) -> Optional[tuple[str, str]]:
    """Resolve a session token hash to `(user_id, role)`, or `None`.

    Runs on a worker thread -- see the call site. Two things about it are
    deliberate.

    **It opens and closes its own short-lived session** rather than
    taking one from `Depends(get_db)`. A dependency declared with `yield`
    is torn down when the endpoint returns, and this endpoint returns
    when the socket closes, which may be hours. That would pin one pooled
    connection, inside an open Postgres transaction, for the life of
    every live socket; the default pool is 5 with 10 overflow, so the
    sixteenth concurrent socket would block for 30 seconds and then fail
    -- while `MAX_CONNECTIONS_PER_USER` alone allows six per user. The
    handshake needs the database for one resolution and then never again.

    **It returns primitives rather than the `User`.** The row is detached
    the moment the session closes, so handing the ORM object onward would
    give a long-lived connection an object whose attribute access can
    start raising later. `Connection` only ever needs the id and the role.
    """
    with SessionLocal() as db:
        user = auth_service.get_active_session_user_by_hash(db, token_hash)
        if user is None:
            return None
        return str(user.id), user.role


@router.websocket("/ws")
async def realtime_socket(websocket: WebSocket) -> None:
    """The app's only WebSocket route. Refuse, register, accept, serve.

    The ordering is the substance of this function, so it is written as a
    flat sequence rather than factored into helpers: read the cookie,
    resolve the session, take a slot, and only then accept. Each step
    refuses by closing and returning, and none of them has accepted a
    connection yet.

    `deregister` runs in a `finally` covering **every** exit after
    registration -- clean close, client vanishing, unhandled error, task
    cancellation at shutdown. A leaked registry entry is not merely
    untidy: it consumes one of the user's cap slots for the life of the
    process and becomes a phantom fan-out target that the dispatch loop
    keeps enqueuing to.
    """
    token = websocket.cookies.get(SESSION_COOKIE)
    if not token:
        # No log line. An unauthenticated handshake is the ordinary shape
        # of a logged-out browser reconnecting, not an event.
        await websocket.close(code=CLOSE_POLICY_VIOLATION, reason="not authenticated")
        return

    # The raw token is used exactly once, here, and never stored: the
    # `Connection` keeps the hash. A raw session token is a live
    # credential and the registry is a process-wide structure that lives
    # for the life of the process -- the same reasoning that made
    # `services.rate_limit.caller_key` hash its input.
    token_hash = auth_service.hash_session_token(token)

    # Offloaded to a worker thread rather than awaited on the loop. The
    # entire app is synchronous-in-a-threadpool for exactly this reason:
    # psycopg blocks, and a blocking driver call on the event loop stalls
    # every other socket and the dispatch task with it. This is the only
    # database access on the socket path, and it costs two queries.
    identity = await run_in_threadpool(_resolve_identity, token_hash)
    if identity is None:
        await websocket.close(code=CLOSE_POLICY_VIOLATION, reason="session invalid")
        return

    user_id, role = identity
    connection = Connection(
        user_id=user_id,
        token_hash=token_hash,
        role=role,
        websocket=websocket,
    )

    if not register(connection):
        # Registered *before* accept, so a user at the cap never becomes a
        # connection that then has to be torn down. There is no
        # `Retry-After` to send with this; the client picks its own wait.
        logger.warning(
            "realtime.connection_refused",
            extra={"fields": {
                "user_id": user_id,
                "reason": "per_user_cap",
                "cap": policy.MAX_CONNECTIONS_PER_USER,
            }},
        )
        await websocket.close(code=CLOSE_POLICY_VIOLATION, reason="too many connections")
        return

    try:
        await websocket.accept()
        logger.info(
            "realtime.connected",
            extra={"fields": {
                "connection_id": connection.connection_id,
                "user_id": user_id,
                "role": role,
            }},
        )
        await _serve(connection, websocket)
    finally:
        # Nothing awaited in here. This block also runs under
        # cancellation at shutdown, where the first `await` would
        # immediately re-raise and skip whatever followed it.
        deregister(connection)
        logger.info(
            "realtime.disconnected",
            extra={"fields": {
                "connection_id": connection.connection_id,
                "user_id": user_id,
                "overflowed": connection.overflowed,
            }},
        )


async def _serve(connection: Connection, websocket: WebSocket) -> None:
    """Run the connection's two loops until either one finishes.

    Reading and writing are separate tasks because they block on
    different things: the reader waits on the peer, the writer waits on
    the send queue that the process-wide dispatch task fills. A single
    loop polling both would either add latency to delivery or spin.

    **An anyio task group, not `asyncio.wait` over `ensure_future`.** This
    is the one place in the file where the idiomatic-looking asyncio
    version is wrong. Starlette runs every endpoint inside an anyio cancel
    scope, and anyio's cancellation accounting depends on `CancelledError`
    propagating through structures it owns. Bare `asyncio` tasks are not
    children of that scope, so a shutdown cancels the endpoint while they
    keep running, and awaiting `asyncio.gather(..., return_exceptions=True)`
    in a `finally` swallows the cancellation the scope is waiting to see.
    The first version of this function did exactly that; it passed when the
    file was run alone and failed intermittently in the full suite -- two
    different tests on two consecutive runs -- with a `CancelledError`
    surfacing out of the test client's teardown.

    Whichever loop ends first ends the connection, so it cancels the group
    rather than leaving the other waiting on something that will never
    arrive.
    """
    try:
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(
                _until_done, task_group, _receive_loop, connection, websocket
            )
            task_group.start_soon(
                _until_done, task_group, _send_pump, connection, websocket
            )
    except Exception as error:
        # Logged, not raised. UX-5: socket failure is silent, and there is
        # no request to fail -- the only useful outcome is a greppable
        # line. `CancelledError` is a `BaseException` and is deliberately
        # not caught here: shutdown must keep propagating.
        logger.warning(
            "realtime.connection_failed",
            exc_info=error,
            extra={"fields": {"connection_id": connection.connection_id}},
        )


async def _until_done(task_group, loop, connection: Connection, websocket: WebSocket):
    """Run one loop and take the connection down with it when it ends.

    In a `finally`, so a loop that raises cancels its sibling just as a
    loop that returns does. The exception still propagates out of the
    task group; cancelling the scope does not swallow it.
    """
    try:
        await loop(connection, websocket)
    finally:
        task_group.cancel_scope.cancel()


async def _receive_loop(connection: Connection, websocket: WebSocket) -> None:
    """Read client->server frames until the peer goes away.

    Uses the raw `receive()` rather than `receive_json()` so a frame can
    be *measured* before anything tries to parse it -- a size check that
    runs after `json.loads` is not a size check.

    The two rejection kinds are deliberately different in kind:

    - **Oversized** closes the connection. It is a transport-level abuse
      that says nothing about the caller's credentials, so it gets 1009
      rather than the handshake's 1008.
    - **Unparseable or unrecognised** is ignored and the loop continues.
      `is_valid_inbound` is a positive allowlist, so an unknown type can
      never reach a handler; and because of P3 there is no handler it
      could reach that would change anything. Closing over one would make
      every frontend deploy a disconnect storm.
    """
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return

        text = message.get("text")
        raw = text.encode("utf-8") if text is not None else (message.get("bytes") or b"")

        if len(raw) > policy.MAX_FRAME_BYTES:
            logger.warning(
                "realtime.frame_too_large",
                extra={"fields": {
                    "connection_id": connection.connection_id,
                    "bytes": len(raw),
                    "limit": policy.MAX_FRAME_BYTES,
                }},
            )
            await websocket.close(
                code=CLOSE_MESSAGE_TOO_BIG, reason="frame too large"
            )
            return

        try:
            frame = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            continue

        if not policy.is_valid_inbound(frame):
            continue

        if frame["type"] == policy.INBOUND_PING and not connection.enqueue(
            {"type": OUTBOUND_PONG}
        ):
            # The reply queue is full, which for a connection whose only
            # outbound traffic is pongs means the peer is sending faster
            # than it reads. Same decision `services.realtime._fan_out`
            # makes for a slow client, for the same reason: closing is
            # safe because P2 makes everything on this socket disposable.
            logger.warning(
                "realtime.reply_queue_full",
                extra={"fields": {"connection_id": connection.connection_id}},
            )
            await websocket.close(
                code=CLOSE_TRY_AGAIN_LATER, reason="send queue overflow"
            )
            return


async def _send_pump(connection: Connection, websocket: WebSocket) -> None:
    """Drain this connection's queue onto the wire. Its **only** writer.

    Every outbound frame leaves through here -- fan-out envelopes that
    the dispatch task enqueues, and this connection's own pong replies
    alike. Starlette's `WebSocket.send_*` is not safe to call from two
    coroutines at once, and a socket with two writers is a race that
    surfaces as an interleaved frame under load and never once in a test.
    Routing the pong through the queue rather than replying inline in the
    receive loop is what keeps that true.
    """
    while True:
        envelope = await connection.queue.get()
        try:
            await websocket.send_json(envelope)
        except WebSocketDisconnect:
            # The peer went away between the enqueue and the send. Not an
            # error and not worth a log line: it is the ordinary end of a
            # connection, and the receive loop reports the same event.
            return


@contextlib.asynccontextmanager
async def lifespan(app):
    """Start and stop the real-time dispatch task.

    This is the app's first startup/shutdown hook of any kind. Shutdown
    closes every connection deliberately rather than dropping them, so
    clients see a clean close and reconnect on their own schedule.
    """
    start_dispatch()
    try:
        yield
    finally:
        await stop_dispatch()
