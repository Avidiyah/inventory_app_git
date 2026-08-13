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
logs in. The handshake retains only the token hash, and every accepted
connection periodically re-resolves it so revocation remains bounded for a
long-lived socket. The revalidation must return the exact handshake identity;
missing sessions and identity or role drift all fail closed.

Refusal happens **before** `accept()` as an HTTP denial response. A foreign
origin, missing or unresolvable session, and a user already at
`MAX_CONNECTIONS_PER_USER` never become WebSocket connections. Close codes
exist only after acceptance; Starlette maps a pre-accept `close()` to a bare
HTTP 403, so authentication and capacity use explicit 401/429 responses.

**P3 is permanent: the socket never mutates anything.** V1 has no
application-level inbound vocabulary. Uvicorn owns protocol ping/pong;
application frames inside the size limit are ignored until a later feature
has a real message type to validate.

Handshake attempts and accepted application frames have independent,
process-local sliding-window budgets. The handshake budget is also independent
from the HTTP request limiter so reconnect churn cannot consume the requests an
inventory write needs. Transport liveness remains configured in Uvicorn rather
than duplicated in application JSON.
"""

import contextlib
import logging
from time import monotonic
from typing import Optional
from urllib.parse import urlsplit

import anyio
from fastapi import APIRouter, HTTPException, WebSocket
from starlette.concurrency import run_in_threadpool
from starlette.websockets import WebSocketDisconnect

from app.auth_deps import SESSION_COOKIE
from app.database import SessionLocal
from app.domain import realtime as policy
from app.services import auth as auth_service
from app.services import rate_limit as rate_limit_service
from app.services import realtime_limits
from app.services.realtime import (
    Connection,
    deregister,
    register,
    start_dispatch,
    stop_dispatch,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# 1009 is the standard "message too big". It is a post-accept transport
# close, unlike handshake policy failures, which are HTTP denial responses.
CLOSE_POLICY_VIOLATION = 1008
CLOSE_MESSAGE_TOO_BIG = 1009
CLOSE_INTERNAL_ERROR = 1011


def _connection_log_fields(connection: Connection) -> dict[str, str]:
    """Stable identity fields for every accepted-connection log line."""
    return {
        "connection_id": connection.connection_id,
        "user_id": connection.user_id,
    }


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


async def _revalidate_once(connection: Connection) -> bool:
    """Re-resolve one accepted connection's authorization.

    The database work stays off the event loop and uses `_resolve_identity`'s
    short-lived session. Returning primitives keeps ORM state out of the
    connection registry. The identity must match the handshake exactly:
    production role changes revoke the session, and an unexpected surviving
    mismatch is an invariant violation that must fail closed rather than
    silently changing the connection's audience.

    Resolver failures also fail closed. The exception is re-raised so the
    existing connection-failure log retains the operational cause, while the
    requested 1011 close gives the client an honest retryable transport result.
    """
    try:
        identity = await run_in_threadpool(
            _resolve_identity,
            connection.token_hash,
        )
    except Exception:
        connection.request_close(
            CLOSE_INTERNAL_ERROR,
            "session revalidation failed",
        )
        raise

    if identity != (connection.user_id, connection.role):
        connection.request_close(
            CLOSE_POLICY_VIOLATION,
            "session no longer valid",
        )
        return False
    return True


def _normalise_origin(value: str) -> Optional[tuple[str, str, int]]:
    """Return a comparable browser origin, or None when it is not one.

    Browser Origin serialization has a scheme and authority only. Rejecting
    credentials and every other URL component keeps this comparison narrower
    than general URL equivalence, which is exactly what a cookie-authenticated
    same-origin channel needs.
    """
    if not value or value == "null":
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    if parsed.path or parsed.query or parsed.fragment:
        return None
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    return parsed.scheme, parsed.hostname.lower(), port


def _same_origin(websocket: WebSocket) -> bool:
    """Whether this browser handshake came from the page it targets.

    Browser clients cannot forge Origin or Host. Non-browser clients can
    forge both, which is fine: this boundary prevents cookie-bearing browser
    JavaScript on another origin from borrowing the user's authority; session
    authentication remains authoritative for every client.
    """
    origins = websocket.headers.getlist("origin")
    hosts = websocket.headers.getlist("host")
    if len(origins) != 1 or len(hosts) != 1 or not hosts[0]:
        return False
    host = hosts[0]

    request_scheme = {
        "ws": "http",
        "wss": "https",
        "http": "http",
        "https": "https",
    }.get(websocket.url.scheme)
    if request_scheme is None:
        return False
    return _normalise_origin(origins[0]) == _normalise_origin(
        f"{request_scheme}://{host}"
    )


@router.websocket("/ws")
async def realtime_socket(websocket: WebSocket) -> None:
    """The app's only WebSocket route. Refuse, register, accept, serve.

    The ordering is the substance of this function, so it is written as a
    flat sequence rather than factored into helpers: validate Origin, count
    the attempt, resolve the session, take a slot, and only then accept. Each
    failed step raises an HTTP denial and none has accepted a connection yet.

    `deregister` runs in a `finally` covering **every** exit after
    registration -- clean close, client vanishing, unhandled error, task
    cancellation at shutdown. A leaked registry entry is not merely
    untidy: it consumes one of the user's cap slots for the life of the
    process and becomes a phantom fan-out target that the dispatch loop
    keeps enqueuing to.
    """
    if not _same_origin(websocket):
        raise HTTPException(status_code=403, detail="WebSocket origin is not allowed.")

    token = websocket.cookies.get(SESSION_COOKIE)
    client = websocket.client
    caller_key = rate_limit_service.caller_key(
        token,
        client.host if client and client.host else "unknown",
    )
    retry_after = realtime_limits.check_handshake_and_record(
        caller_key,
        monotonic(),
    )
    if retry_after is not None:
        logger.warning(
            "realtime.connection_refused",
            extra={"fields": {
                "reason": "handshake_rate_limit",
                "retry_after": retry_after,
                "cap": policy.HANDSHAKE_MAX_ATTEMPTS,
                "window_seconds": policy.HANDSHAKE_WINDOW_SECONDS,
            }},
        )
        raise HTTPException(
            status_code=429,
            detail="Too many WebSocket connection attempts.",
            headers={"Retry-After": str(retry_after)},
        )

    if not token:
        # No log line. An unauthenticated handshake is the ordinary shape
        # of a logged-out browser reconnecting, not an event.
        raise HTTPException(status_code=401, detail="Not authenticated.")

    # The raw token is passed only to the two established hash boundaries --
    # caller identity above and session identity here -- and is never stored.
    # A raw session token is a live credential; the connection registry and
    # limiter buckets are process-wide structures that must not retain it.
    token_hash = auth_service.hash_session_token(token)

    # Offloaded to a worker thread rather than awaited on the loop. The
    # entire app is synchronous-in-a-threadpool for exactly this reason:
    # psycopg blocks, and a blocking driver call on the event loop stalls
    # every other socket and the dispatch task with it. This is the only
    # database access on the socket path, and it costs two queries.
    identity = await run_in_threadpool(_resolve_identity, token_hash)
    if identity is None:
        raise HTTPException(status_code=401, detail="Not authenticated.")

    user_id, role = identity
    connection = Connection(
        user_id=user_id,
        token_hash=token_hash,
        role=role,
    )

    if not register(connection):
        # Registered *before* accept, so a user at the cap never becomes a
        # connection that then has to be torn down. This is concurrent
        # capacity rather than a timed rate limit, so no Retry-After value
        # would be honest.
        logger.warning(
            "realtime.connection_refused",
            extra={"fields": {
                "user_id": user_id,
                "reason": "per_user_cap",
                "cap": policy.MAX_CONNECTIONS_PER_USER,
            }},
        )
        raise HTTPException(status_code=429, detail="Too many WebSocket connections.")

    try:
        await websocket.accept()
        logger.info(
            "realtime.connected",
            extra={"fields": {
                **_connection_log_fields(connection),
                "role": role,
            }},
        )
        await _serve(connection, websocket)
    finally:
        # Nothing awaited in here. This block also runs under
        # cancellation at shutdown, where the first `await` would
        # immediately re-raise and skip whatever followed it.
        deregister(connection)
        connection.closed.set()
        logger.info(
            "realtime.disconnected",
            extra={"fields": {
                **_connection_log_fields(connection),
                "overflowed": connection.overflowed,
            }},
        )


async def _serve(connection: Connection, websocket: WebSocket) -> None:
    """Run the connection loops, then serialize any requested close.

    Reading, writing, and close signaling are separate tasks because they
    block on different things. Whichever finishes first cancels and joins
    the other two. Only after the data writer is gone may this supervisor
    send a close frame, so the socket never has concurrent writers.

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
            task_group.start_soon(
                _until_done, task_group, _wait_for_close, connection, websocket
            )
            task_group.start_soon(
                _until_done, task_group, _revalidation_loop, connection, websocket
            )
    except Exception as error:
        # Logged, not raised. UX-5: socket failure is silent, and there is
        # no request to fail -- the only useful outcome is a greppable
        # line. `CancelledError` is a `BaseException` and is deliberately
        # not caught here: shutdown must keep propagating.
        logger.warning(
            "realtime.connection_failed",
            exc_info=error,
            extra={"fields": _connection_log_fields(connection)},
        )

    if connection.close_requested.is_set():
        await _send_requested_close(connection, websocket)


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

    Oversized input requests code 1009 before the rate counter is touched, so
    the existing size failure keeps deterministic precedence. Acceptable-size
    frames are counted and then ignored: v1 has no application-level inbound
    vocabulary, and P3 means there is no state mutation they could reach.
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
                    **_connection_log_fields(connection),
                    "bytes": len(raw),
                    "limit": policy.MAX_FRAME_BYTES,
                }},
            )
            connection.request_close(CLOSE_MESSAGE_TOO_BIG, "frame too large")
            return

        if not realtime_limits.inbound_frame_allowed(
            connection,
            monotonic(),
        ):
            logger.warning(
                "realtime.frame_rate_limited",
                extra={"fields": {
                    **_connection_log_fields(connection),
                    "limit": policy.INBOUND_MAX_FRAMES,
                    "window_seconds": policy.INBOUND_WINDOW_SECONDS,
                }},
            )
            connection.request_close(
                CLOSE_POLICY_VIOLATION,
                "inbound frame rate exceeded",
            )
            return


async def _revalidation_loop(
    connection: Connection,
    _websocket: WebSocket,
) -> None:
    """Keep a long-lived socket bound to its handshake authorization.

    Sleep before the first check because the handshake has just performed the
    same resolution. Uvicorn's protocol ping/pong owns transport liveness;
    this loop is authorization maintenance only.
    """
    while True:
        await anyio.sleep(policy.REVALIDATE_INTERVAL_SECONDS)
        if not await _revalidate_once(connection):
            return


async def _send_pump(connection: Connection, websocket: WebSocket) -> None:
    """Drain this connection's queue. The socket's only data writer.

    Starlette's `WebSocket.send_*` is not safe to call from two coroutines
    at once. Requested closure cancels and joins this pump before the
    supervisor sends a close frame.
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
        logger.info(
            "realtime.delivered",
            extra={
                # This is ordinary envelope data, not request context. The
                # socket task was born at handshake and cannot inherit the
                # HTTP request that emitted this event.
                "request_id": envelope.get("req"),
                "fields": {
                    **_connection_log_fields(connection),
                    "event_type": envelope.get("type"),
                    "entity_id": envelope.get("id"),
                },
            },
        )


async def _wait_for_close(connection: Connection, _websocket: WebSocket) -> None:
    """Wake the connection supervisor when a service or policy requests close."""
    await connection.close_requested.wait()


async def _send_requested_close(
    connection: Connection,
    websocket: WebSocket,
) -> None:
    """Send one close frame after every data writer has stopped."""
    if connection.close_code is None:
        return
    try:
        await websocket.close(
            code=connection.close_code,
            reason=connection.close_reason or "",
        )
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.info(
            "realtime.close_failed",
            extra={"fields": _connection_log_fields(connection)},
        )


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
