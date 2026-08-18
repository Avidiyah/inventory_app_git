"""Web Push delivery -- the I/O half of `app.domain.push`.

Layer: services. This module owns the network call, the VAPID
configuration, and the one write the delivery result implies (deleting a
dead subscription). Every *decision* it makes is delegated to
`domain.push`, which is pure and separately tested; nothing here decides
what a status code means.

Configuration is one secret. `VAPID_PRIVATE_KEY` must be set in the
environment (Render dashboard in production, `backend/.env` locally);
the public half and the contact subject are constants below because
neither is secret and both must stay pinned to the private key.

A missing private key disables push rather than crashing the app: this
is an opt-in capability, and a deployment that never configured it
should still serve every other route. `is_configured()` reports the
state and the router turns it into a clear message.
"""

import json
import logging
import os

from sqlalchemy.orm import Session

from app.domain import push as push_policy
from app.domain import roles
from app.models import PushSubscription, User

logger = logging.getLogger(__name__)

# Secret. Signs a JWT on every send. Rotating it invalidates every
# existing subscription -- the browser bound the public half in at
# `subscribe()` time -- so it is set once per environment and left alone.
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "").strip()

# Not a secret: this reaches every browser that subscribes, and the
# frontend cannot call `pushManager.subscribe()` without it. It is
# committed because it must match the private key above exactly; a drift
# between the two is invisible until the first send returns 401, which
# `classify_push_response` maps to PUSH_CONFIGURATION_ERROR rather than
# to a subscription delete for precisely that reason.
VAPID_PUBLIC_KEY = (
    "BBJxbdh7LQZ5afzgga-Cv8Cni_wI-2mRZbQiCO8UKO1DNSKN4c9BL30RovDAVbOIryxycTgZbSxFGilnElVJ78Y"
)

# Push services require a contact for the operator of the application
# server, sent in the VAPID JWT's `sub` claim. It never reaches the user
# and is only read if a push service needs to report an operational
# problem. The repository's existing GitHub no-reply address is used so
# no personal address is committed; swap it for a monitored mailbox if
# you would rather hear from Apple directly.
VAPID_SUBJECT = "mailto:121895367+Avidiyah@users.noreply.github.com"


def is_configured() -> bool:
    """Whether a send can be attempted at all.

    Checked by the router before a fan-out so an unconfigured deployment
    returns one clear error instead of one failure per subscription.
    """
    return bool(VAPID_PRIVATE_KEY)


def _recipient_roles(minimum: str) -> list[str]:
    """Every role ranking at or above `minimum`.

    Derived from `ROLE_RANK` rather than written out, so a role inserted
    into the hierarchy later is included automatically -- the TechFM OA
    insertion between Supervisor and Admin is the precedent this guards
    against repeating.
    """
    floor = roles.ROLE_RANK[minimum]
    return [role for role, rank in roles.ROLE_RANK.items() if rank >= floor]


def subscriptions_for_min_role(db: Session, minimum: str) -> list[PushSubscription]:
    """Every subscription belonging to a user at or above `minimum` rank."""
    return (
        db.query(PushSubscription)
        .join(User, User.id == PushSubscription.user_id)
        .filter(User.role.in_(_recipient_roles(minimum)))
        .filter(User.archived_at.is_(None))
        .all()
    )


def save_subscription(
    db: Session, user_id, endpoint: str, p256dh: str, auth: str
) -> PushSubscription:
    """Create or reassign the subscription identified by `endpoint`.

    An existing row is **reassigned** to `user_id` rather than rejected.
    That is the shared-device rule: the browser hands back the same
    endpoint no matter who is logged in, so a re-subscribe after a
    different login must move the row, leaving the previous user with no
    claim on that device.
    """
    existing = db.get(PushSubscription, endpoint)
    if existing is None:
        existing = PushSubscription(endpoint=endpoint)
        db.add(existing)

    existing.user_id = user_id
    existing.p256dh = p256dh
    existing.auth = auth
    db.commit()
    db.refresh(existing)
    return existing


def delete_subscription(db: Session, user_id, endpoint: str) -> bool:
    """Delete one device's subscription. Returns whether a row went away.

    Scoped to `user_id` so a caller cannot unsubscribe someone else's
    device by guessing an endpoint. A miss is not an error -- logging out
    twice, or from a device that never subscribed, is ordinary.
    """
    deleted = (
        db.query(PushSubscription)
        .filter(PushSubscription.endpoint == endpoint)
        .filter(PushSubscription.user_id == user_id)
        .delete(synchronize_session=False)
    )
    db.commit()
    return bool(deleted)


def _send_one(subscription: PushSubscription, payload: str) -> str:
    """Deliver one message. Returns a `domain.push` outcome constant.

    Imported inside the function so the module stays importable -- and
    the rest of the app testable -- on an environment where `pywebpush`
    is absent.
    """
    from pywebpush import WebPushException, webpush

    try:
        response = webpush(
            subscription_info={
                "endpoint": subscription.endpoint,
                "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
            },
            data=payload,
            vapid_private_key=VAPID_PRIVATE_KEY,
            # A fresh dict per call, deliberately. pywebpush *mutates* the
            # claims it is given, writing an `aud` derived from the
            # endpoint. Sharing one dict across a fan-out would send every
            # device after the first a token audienced to the first
            # device's push service, which rejects it -- a failure that
            # looks like a bad key rather than a reused dict.
            vapid_claims={"sub": VAPID_SUBJECT},
        )
        return push_policy.classify_push_response(response.status_code)
    except WebPushException as exc:
        # A response means the push service answered and its status is
        # authoritative. No response means the request never completed
        # (DNS, TLS, timeout), which is transient by nature.
        if exc.response is not None:
            return push_policy.classify_push_response(exc.response.status_code)
        logger.warning("push send failed with no response: %s", exc)
        return push_policy.PUSH_RETRY


def subscriptions_for_users(db: Session, user_ids) -> list[PushSubscription]:
    """Every subscription belonging to any of `user_ids`.

    Returns every *device* those users hold, not one row per user -- a
    person with a phone and a tablet is one recipient and two sends.

    Archived users are excluded here rather than by the caller, matching
    `subscriptions_for_min_role`. An account that cannot log in must not
    keep receiving, and naming its id explicitly is not a reason to
    bypass that.

    An empty `user_ids` short-circuits: an event whose recipient list
    emptied out (everyone involved was the actor) is ordinary, and
    `WHERE user_id IN ()` is not a query worth issuing.
    """
    ids = list(user_ids)
    if not ids:
        return []
    return (
        db.query(PushSubscription)
        .join(User, User.id == PushSubscription.user_id)
        .filter(PushSubscription.user_id.in_(ids))
        .filter(User.archived_at.is_(None))
        .all()
    )


def _fan_out(db: Session, subscriptions, title: str, body: str) -> dict:
    """Deliver one message to a resolved set of devices.

    The single send-and-classify body, shared by every entry point.
    Returns `{"sent", "dropped", "failed"}`. Subscriptions the push
    service reports as dead (404/410) are deleted here -- that is the one
    status class where deletion is correct, and `classify_push_response`
    is the only thing that decides it.

    This is deliberately the *only* place that decides what a delivery
    outcome implies. A second copy of the loop is how a caller ends up
    deleting on a 401 and emptying the table; the audience query is the
    part that varies between callers, and it is the only part that does.

    Sends are sequential. With a crew-sized audience that is a handful of
    requests; it would need a queue before this grew to hundreds of
    devices.
    """
    payload = json.dumps({"title": title, "body": body})

    sent = dropped = failed = 0
    dead: list[str] = []

    for subscription in subscriptions:
        # Re-checked on every send, not merely at registration: the
        # allowlist is what keeps a stored endpoint from becoming an SSRF
        # primitive pointed at the hosting provider's network.
        if not push_policy.is_allowed_push_endpoint(subscription.endpoint):
            logger.warning("refusing push to disallowed endpoint host")
            failed += 1
            continue

        outcome = _send_one(subscription, payload)

        if outcome == push_policy.PUSH_OK:
            sent += 1
        elif outcome == push_policy.PUSH_DROP_SUBSCRIPTION:
            dead.append(subscription.endpoint)
            dropped += 1
        else:
            # Configuration errors, payload-too-large and retryables all
            # leave the row alone. Only 404/410 is evidence of a dead
            # subscription; deleting on anything else would empty the
            # table on the first misconfiguration.
            logger.warning("push not delivered: %s", outcome)
            failed += 1

    if dead:
        db.query(PushSubscription).filter(
            PushSubscription.endpoint.in_(dead)
        ).delete(synchronize_session=False)
        db.commit()

    return {"sent": sent, "dropped": dropped, "failed": failed}


def send_to_min_role(db: Session, minimum: str, title: str, body: str) -> dict:
    """Fan one notification out to every subscriber at or above `minimum`.

    The audience-by-rank entry point: used for `POST /push/test` and for
    events whose recipients are a role rather than named people, such as
    "an Admin should know this work order was completed".
    """
    return _fan_out(db, subscriptions_for_min_role(db, minimum), title, body)


def send_to_users(db: Session, user_ids, title: str, body: str) -> dict:
    """Fan one notification out to the devices of specific people.

    The per-user entry point: work orders are assigned to people, not to
    a rank, so requirements phrased as "notify the assignees" cannot be
    served by `send_to_min_role` at any floor.

    Both entry points share `_fan_out`, so the delete-on-404/410 rule and
    the endpoint allowlist re-check apply identically here.
    """
    return _fan_out(db, subscriptions_for_users(db, user_ids), title, body)
