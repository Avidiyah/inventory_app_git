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
    "EVENT_ITEM_LOW_STOCK_CHANGED",
    "EVENT_LABOR_SESSION_CHANGED",
    "EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED",
    "EVENT_WORK_ORDER_STATUS_CHANGED",
    "HANDSHAKE_MAX_ATTEMPTS",
    "HANDSHAKE_WINDOW_SECONDS",
    "MAX_CONNECTIONS_PER_USER",
    "INBOUND_MAX_FRAMES",
    "INBOUND_WINDOW_SECONDS",
    "MAX_FRAME_BYTES",
    "SEND_QUEUE_MAX",
    "HANDOFF_QUEUE_MAX",
    "SHUTDOWN_CLOSE_GRACE_SECONDS",
    "REVALIDATE_INTERVAL_SECONDS",
    "DISPATCH_MAX_RESTARTS",
    "build_envelope",
    "audience_allows",
    "is_over_limit",
    "retry_after_seconds",
    "window_start",
]

# --- vocabulary --------------------------------------------------------

# The only server->client event type in v1. This is intentionally narrower
# than a general work-order aggregate event: it invalidates the Review-status
# queue projection (membership plus the fields shown on its cards). Material,
# labor, billing, and price changes do not belong to this vocabulary because
# the first consumer refreshes only the queue, not an open receipt.
EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED = "work_order.review_queue.changed"

# The Work Orders card list. Narrower than an aggregate event in the same way:
# it invalidates a card's *summary* projection -- status, assignee, item count --
# and nothing else. Material, labor, billing, and price stay out of the
# vocabulary, because no consumer refreshes an open card body.
#
# `id` names one work order; `None` means a membership command (restore), where
# the recipient's list may have gained a row that no on-screen card represents.
EVENT_WORK_ORDER_STATUS_CHANGED = "work_order.status.changed"

# A crew member's clock started or stopped -- a membership change to the
# Supervisor hub's crew board, not a row update, so `id` is always `None`
# (spec §6.2) and the recipient refetches the board rather than targeting a
# card. Emitted from `routers/work_orders.py`'s tracking start/stop routes.
EVENT_LABOR_SESSION_CHANGED = "labor.session.changed"

# The Low Stock page's membership. Narrow in the same way the others are:
# it invalidates *which items are low*, not an item's contents, so a name
# or price edit is not in this vocabulary. Emitted whenever an item enters
# or leaves the set -- a crossing in either direction, a threshold edit,
# an item created below its threshold, or an item archived out of the list.
#
# `id` names one item; `None` is unused today and reserved for a command
# that could change several rows at once.
EVENT_ITEM_LOW_STOCK_CHANGED = "item.low_stock.changed"

_AUDIENCE_MIN_ROLE = {
    EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED: roles.ROLE_TECHFM_OA,
    # Every role that can open the Work Orders page. Not a security boundary:
    # P2 keeps row data out of the envelope, so a technician who receives an
    # event for a work order they cannot see simply re-fetches nothing.
    EVENT_WORK_ORDER_STATUS_CHANGED: roles.ROLE_TECHNICIAN,
    # Only supervisors and above can see a crew board at all (spec §4.1).
    EVENT_LABOR_SESSION_CHANGED: roles.ROLE_SUPERVISOR,
    # The page is TechFM OA+ for both viewing and editing, and so is the
    # push, so the socket audience matches both rather than inventing a
    # third rank.
    EVENT_ITEM_LOW_STOCK_CHANGED: roles.ROLE_TECHFM_OA,
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

# Maximum time application shutdown waits for endpoint-owned WebSocket
# close handshakes to finish. The endpoint, not the service registry, owns
# transport writes; a bounded acknowledgement wait preserves that boundary
# without letting one vanished peer hold process shutdown open indefinitely.
SHUTDOWN_CLOSE_GRACE_SECONDS = 2.0

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
    request_id: Optional[str],
) -> dict[str, Any]:
    """One server->client frame.

    Three fields and no more:

    - `type` -- the discriminator. Present from day one so a second event
      type is additive rather than a wire-format change.
    - `id`   -- which entity changed. An identifier, never its contents.
    - `req`  -- the originating request id, so one HTTP write and its N
      deliveries are a single traceable chain (§8.2).

    There is deliberately no actor id. A user id cannot distinguish the
    tab that made a write from another tab or device belonging to the same
    person; suppressing by user would recreate the exact stale-screen bug
    this layer exists to remove. V1 clients refetch on every relevant
    invalidation, including their own.

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
        "req": request_id,
    }


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
