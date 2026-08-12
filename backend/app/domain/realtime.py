"""Real-time layer policy -- pure rules, no I/O.

Layer: domain. No FastAPI, no SQLAlchemy, no sockets, no clock reads
beyond what is passed in, so the whole policy is unit-testable without a
database or a running app. `app.services.realtime` owns the connection
state and `app.routers.realtime` enforces these rules visibly, per P5.

**Every number here is a starting hypothesis, not a measurement.** The
standing rule in `docs/open-work.md` is to ask what the number actually
is before building what an item describes; each constant below records
the reasoning that produced its guess so that measuring it later is a
comparison rather than a fresh argument.

**The envelope is the hardest thing to change later**, because every
client and every emitter depends on it. It carries a discriminating
`type` from day one even though only one event type exists, and it
carries no row data at all (P2): events say *what changed*, and the
recipient re-fetches through REST, which re-runs the server's own
scoping. That is what makes the socket structurally incapable of leaking
anything REST would not already return.
"""

from typing import Any, Optional

from app.domain import roles
from app.domain.rate_limit import is_over_limit, retry_after_seconds, window_start

__all__ = [
    "EVENT_WORK_ORDER_CHANGED",
    "INBOUND_PING",
    "HANDSHAKE_MAX_ATTEMPTS",
    "HANDSHAKE_WINDOW_SECONDS",
    "MAX_CONNECTIONS_PER_USER",
    "INBOUND_MAX_FRAMES",
    "INBOUND_WINDOW_SECONDS",
    "MAX_FRAME_BYTES",
    "SEND_QUEUE_MAX",
    "HANDOFF_QUEUE_MAX",
    "HEARTBEAT_INTERVAL_SECONDS",
    "REVALIDATE_INTERVAL_SECONDS",
    "DISPATCH_MAX_RESTARTS",
    "build_envelope",
    "is_valid_inbound",
    "audience_allows",
    "is_over_limit",
    "retry_after_seconds",
    "window_start",
]

# --- vocabulary --------------------------------------------------------

# The only server->client event type in v1. Named for what changed, not
# for what a view should do about it -- views decide that themselves.
EVENT_WORK_ORDER_CHANGED = "work_order.changed"

# The only client->server frame type in v1.
#
# The endpoint accepts inbound frames from the start even though this is
# all it does with them. A strictly one-way socket has no seam at which
# to later add message send, inbound validation, or inbound rate
# limiting: this is the cheapest forward-compatibility decision in the
# design and the most expensive one to retrofit.
INBOUND_PING = "ping"

_AUDIENCE_MIN_ROLE = {
    EVENT_WORK_ORDER_CHANGED: roles.ROLE_ADMIN,
}

# --- thresholds --------------------------------------------------------

# Handshake attempts per caller per window.
#
# Deliberately NOT the HTTP limiter's budget. 60-per-second is calibrated
# for page loads, where a cold SPA load is ~35 requests fired at once;
# sixty socket opens per second is a catastrophe that sails straight
# through it. Connection establishment is expensive and rare, which is
# the login-throttle problem shape rather than the request-limiter one.
#
# Sharing the HTTP bucket would also let socket churn consume the budget
# the user's actual inventory writes need.
#
# Hypothesis: reconnect-with-backoff is the most likely retry loop in the
# app, and free-tier spin-downs guarantee that path runs constantly.
HANDSHAKE_MAX_ATTEMPTS = 10
HANDSHAKE_WINDOW_SECONDS = 60.0

# Simultaneous connections per **user**, not per session: phone-plus-desktop
# is legitimate, and multi-device delivery is the whole reason the registry
# is keyed by user. Bounds accumulation where the attempt limiter bounds
# arrival rate -- a loop that squeaks past the limiter still hits a ceiling
# and stays there.
#
# Hypothesis: a small crew with a few devices each.
MAX_CONNECTIONS_PER_USER = 6

# Inbound frames per connection per window. Far above human typing, far
# below a loop. Only bites once messaging exists, but the seam belongs in
# v1 -- retrofitting a limiter into an established message loop is exactly
# the kind of change this design exists to avoid.
INBOUND_MAX_FRAMES = 20
INBOUND_WINDOW_SECONDS = 1.0

# Largest inbound frame accepted at the application layer. A chat message
# needs kilobytes; the server's own default ceiling is measured in
# megabytes.
MAX_FRAME_BYTES = 65536

# Per-connection outbound queue depth. On overflow the connection is
# CLOSED rather than buffered -- see `services.realtime`. This is the one
# protection against a *slow* client, which no rate limiter catches
# because a bad connection is not abuse.
SEND_QUEUE_MAX = 32

# Process-wide buffer between request threads and the event loop. Bounded
# so a phone on bad wifi can never become a server-side memory risk.
HANDOFF_QUEUE_MAX = 1000

# Liveness exchange interval. TCP does not reliably report a vanished
# peer; a phone that walks into a dead zone leaves a half-open connection
# the server still believes in. The concurrency cap above is only as
# correct as the registry's view of what is alive.
HEARTBEAT_INTERVAL_SECONDS = 30.0

# How often a connection re-resolves its session (D1). Bounds how long a
# demoted, archived, or logged-out user keeps receiving.
REVALIDATE_INTERVAL_SECONDS = 60.0

# Dispatch-task restarts before giving up permanently (D2). Bounded so a
# transient fault self-heals while a crash loop surfaces instead of
# hiding behind endless restarts.
DISPATCH_MAX_RESTARTS = 3


# --- envelope ----------------------------------------------------------


def build_envelope(
    *,
    event_type: str,
    entity_id: Any,
    actor_id: Any,
    request_id: Optional[str],
) -> dict[str, Any]:
    """One server->client frame.

    Four fields and no more:

    - `type` -- the discriminator. Present from day one so a second event
      type is additive rather than a wire-format change.
    - `id`   -- which entity changed. An identifier, never its contents.
    - `actor`-- who caused it, so a client can ignore its own echo (§8.4).
      Without this every write costs the writer an extra round trip,
      which is a UX-7 regression.
    - `req`  -- the originating request id, so one HTTP write and its N
      deliveries are a single traceable chain (§8.2).

    `req` travels as **data**, deliberately. The dispatch task is started
    at lifespan, lives independently of any request, and inherits nothing
    from any of them, so request context cannot reach it through a context
    variable under any circumstances. Anyone reasoning "context variables
    propagate, this is fine" gets anonymous log lines and will not notice,
    because the lines still appear.

    Ids are stringified here so the envelope survives `json.dumps` without
    a custom encoder.
    """
    return {
        "type": event_type,
        "id": None if entity_id is None else str(entity_id),
        "actor": None if actor_id is None else str(actor_id),
        "req": request_id,
    }


# --- inbound validation ------------------------------------------------


def is_valid_inbound(frame: Any) -> bool:
    """Whether a client->server frame is one this version understands.

    Rejects by allowlist, so an unknown type can never fall through to a
    handler. P3 is permanent: the socket never mutates anything, so there
    is no inbound frame that changes state and there never will be.
    """
    if not isinstance(frame, dict):
        return False
    return frame.get("type") in (INBOUND_PING,)


# --- audience ----------------------------------------------------------


def audience_allows(event_type: str, role: str) -> bool:
    """Whether a user holding `role` should receive `event_type`.

    **This is not the security boundary.** Because of P2 an event carries
    no data, so a mis-scoped audience is a wasted message rather than a
    disclosure -- the recipient's re-fetch is still authorized
    server-side by the REST layer, which is unchanged. This map is an
    efficiency and noise concern.

    Unknown event types reach nobody, so adding an event without adding
    an audience fails closed and silently rather than broadcasting.
    """
    minimum = _AUDIENCE_MIN_ROLE.get(event_type)
    if minimum is None:
        return False
    return roles.role_at_least(role, minimum)
