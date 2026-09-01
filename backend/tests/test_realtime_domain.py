"""Pure real-time policy -- no sockets, no clock, no database.

Mirrors the shape of tests/test_rate_limit.py: the rules are decidable in
isolation, so they are tested in isolation.
"""

from app.domain import realtime


# --- envelope ----------------------------------------------------------


def test_envelope_carries_a_discriminating_type():
    envelope = realtime.build_envelope(
        event_type=realtime.EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED,
        entity_id="wo-1",
        request_id="req-1",
    )

    assert envelope["type"] == realtime.EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED


def test_envelope_carries_correlation_id():
    """The request id is what makes one write traceable to N deliveries
    (§8.2) -- it must travel as data, never through a context variable."""
    envelope = realtime.build_envelope(
        event_type=realtime.EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED,
        entity_id="wo-1",
        request_id="req-1",
    )

    assert envelope["req"] == "req-1"


def test_envelope_carries_no_row_data():
    """P2: events say what changed, never what it now is. The whole
    security argument for the socket rests on this -- if payloads ship,
    every fan-out decision becomes an independent disclosure review."""
    envelope = realtime.build_envelope(
        event_type=realtime.EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED,
        entity_id="wo-1",
        request_id="req-1",
    )

    assert set(envelope) == {"type", "id", "req"}


def test_envelope_stringifies_ids():
    """UUIDs must survive json.dumps without a custom encoder."""
    import uuid

    entity = uuid.uuid4()
    envelope = realtime.build_envelope(
        event_type=realtime.EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED,
        entity_id=entity,
        request_id=None,
    )

    assert envelope["id"] == str(entity)


def test_envelope_allows_a_collection_invalidation_without_an_entity_id():
    envelope = realtime.build_envelope(
        event_type=realtime.EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED,
        entity_id=None,
        request_id="req-1",
    )

    assert envelope["id"] is None


def test_v1_has_no_application_heartbeat_vocabulary():
    """Uvicorn owns protocol ping/pong. Adding JSON heartbeat frames would
    create a second liveness mechanism and a wire contract with no product
    meaning."""
    assert not hasattr(realtime, "INBOUND_PING")
    assert not hasattr(realtime, "HEARTBEAT_INTERVAL_SECONDS")
    assert not hasattr(realtime, "is_valid_inbound")


# --- audience ----------------------------------------------------------


def test_review_queue_events_reach_admin_and_owner():
    assert (
        realtime.audience_allows(
            realtime.EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED, "admin"
        )
        is True
    )
    assert (
        realtime.audience_allows(
            realtime.EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED, "owner"
        )
        is True
    )


def test_review_queue_events_do_not_reach_lower_roles_in_v1():
    """Not a security boundary -- P2 makes a mis-scoped audience a wasted
    message, since the recipient's re-fetch is still authorized
    server-side. This is a noise and efficiency rule, and the Admin
    Review surface is Admin+ only."""
    assert (
        realtime.audience_allows(
            realtime.EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED, "supervisor"
        )
        is False
    )
    assert (
        realtime.audience_allows(
            realtime.EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED, "technician"
        )
        is False
    )


def test_unknown_event_types_reach_nobody():
    assert realtime.audience_allows("invented_event", "owner") is False


# --- thresholds --------------------------------------------------------


def test_handshake_budget_is_not_the_http_budget():
    """60-per-second is calibrated for page loads; sixty socket opens per
    second is a catastrophe that sails straight through it."""
    from app.domain import rate_limit

    assert realtime.HANDSHAKE_MAX_ATTEMPTS < rate_limit.MAX_REQUESTS
    assert realtime.HANDSHAKE_WINDOW_SECONDS > rate_limit.WINDOW_SECONDS


def test_every_threshold_is_positive():
    assert realtime.MAX_CONNECTIONS_PER_USER > 0
    assert realtime.INBOUND_MAX_FRAMES > 0
    assert realtime.MAX_FRAME_BYTES > 0
    assert realtime.SEND_QUEUE_MAX > 0
    assert realtime.HANDOFF_QUEUE_MAX > 0
    assert realtime.SHUTDOWN_CLOSE_GRACE_SECONDS > 0
    assert realtime.REVALIDATE_INTERVAL_SECONDS > 0
    assert realtime.DISPATCH_MAX_RESTARTS > 0


def test_revalidation_interval_bounds_authorization_lag():
    """D1 accepts bounded lag, never an effectively permanent session."""
    assert realtime.REVALIDATE_INTERVAL_SECONDS <= 300.0


def test_status_events_reach_every_role_that_can_open_the_page():
    """Work Orders is available to all five roles (static/views/nav.js:67), so
    the status event's audience is the whole hierarchy. This is a noise rule,
    not a security one -- P2 means the re-fetch is what enforces scoping."""
    for role in ("technician", "supervisor", "techfm_oa", "admin", "owner"):
        assert (
            realtime.audience_allows(realtime.EVENT_WORK_ORDER_STATUS_CHANGED, role)
            is True
        )


def test_status_and_review_queue_are_distinct_event_types():
    assert (
        realtime.EVENT_WORK_ORDER_STATUS_CHANGED
        != realtime.EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED
    )
    assert realtime.EVENT_WORK_ORDER_STATUS_CHANGED == "work_order.status.changed"


def test_low_stock_events_reach_techfm_oa_and_above():
    for role in ("techfm_oa", "admin", "owner"):
        assert (
            realtime.audience_allows(realtime.EVENT_ITEM_LOW_STOCK_CHANGED, role)
            is True
        ), role


def test_low_stock_events_do_not_reach_lower_roles():
    """Noise, not security -- P2 keeps row data out of the envelope. The
    Low Stock page is TechFM OA+ only, so nobody below it can act on the
    invalidation."""
    for role in ("supervisor", "technician"):
        assert (
            realtime.audience_allows(realtime.EVENT_ITEM_LOW_STOCK_CHANGED, role)
            is False
        ), role
