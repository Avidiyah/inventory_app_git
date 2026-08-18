"""Tests for the Web Push subscription store, audience and fan-out.

Two layers in one file, matching how the feature splits:

- **Pure** (no DB): the route role gates, and the recipient-role
  expansion. These pin the probe's blast radius -- only the Owner may
  trigger a send, and the audience is Admin and above.
- **Database** (`db` fixture, rolled back): the subscription store's
  reassignment rule and the fan-out's delete-on-dead behavior.

`domain/push.py` already has exhaustive coverage in `test_push_domain.py`;
nothing here re-tests classification. What is tested here is that the
service *obeys* it -- in particular that only PUSH_DROP_SUBSCRIPTION
deletes a row, since the alternative empties the table on the first
misconfiguration.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid

import pytest
from fastapi.routing import APIRoute

from app.domain import push as push_policy
from app.domain import roles
from app.models import PushSubscription, User
from app.routers import push as push_router
from app.services import auth as auth_service
from app.services import push as push_service


# --- helpers ------------------------------------------------------------

def _seed_user(db, role):
    user = User(
        username=f"u-{uuid.uuid4().hex[:10]}",
        password_hash=auth_service.hash_password("hunter2"),
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def _endpoint(suffix=""):
    """A well-formed Apple endpoint. Real subscriptions always come from
    a host in ALLOWED_PUSH_HOSTS, so tests use one too -- a fabricated
    host would be rejected before reaching the code under test."""
    return f"https://web.push.apple.com/{uuid.uuid4().hex}{suffix}"


def _route(endpoint_name):
    for route in push_router.router.routes:
        if isinstance(route, APIRoute) and route.endpoint.__name__ == endpoint_name:
            return route
    raise AssertionError(f"route {endpoint_name!r} not found")


def _find_min_role(dependant):
    """Walk a route's dependant tree for the `minimum` captured by a
    `require_min_role(...)` closure. Same technique as
    `test_route_role_gates.py`, kept local so that file stays untouched."""
    for sub in dependant.dependencies:
        call = getattr(sub, "call", None)
        closure = getattr(call, "__closure__", None) or ()
        freevars = call.__code__.co_freevars if call is not None else ()
        for name, cell in zip(freevars, closure):
            if name == "minimum" and isinstance(cell.cell_contents, str):
                return cell.cell_contents
        found = _find_min_role(sub)
        if found is not None:
            return found
    return None


# --- pure: gates and audience -------------------------------------------

def test_only_the_owner_can_trigger_a_send():
    """The probe's blast radius. Anything below Owner here would let an
    Admin make every other Admin's phone buzz."""
    assert _find_min_role(_route("send_test").dependant) == roles.ROLE_OWNER


def test_registering_a_device_is_not_role_gated():
    """An Admin must be able to enrol their own phone. Holding a
    subscription confers no authority, so there is no minimum here --
    only `get_current_user`, which these routes reach through the
    dependency tree without a `minimum` closure."""
    for name in ("subscribe", "unsubscribe", "push_config"):
        assert _find_min_role(_route(name).dependant) is None


def test_notify_audience_is_admin_and_above():
    assert push_router.NOTIFY_MIN_ROLE == roles.ROLE_ADMIN


def test_recipient_roles_expand_upward_only():
    """Admin-and-above must include the Owner -- that is what lets the
    Owner prove the loop on one device -- and must exclude everyone
    below Admin."""
    recipients = set(push_service._recipient_roles(roles.ROLE_ADMIN))

    assert recipients == {roles.ROLE_ADMIN, roles.ROLE_OWNER}
    assert roles.ROLE_TECHFM_OA not in recipients
    assert roles.ROLE_SUPERVISOR not in recipients
    assert roles.ROLE_TECHNICIAN not in recipients


def test_recipient_roles_are_derived_from_rank_not_hardcoded():
    """Every role at or above the floor, computed. A role inserted into
    the middle of the hierarchy later must be classified automatically --
    the TechFM OA insertion is the precedent."""
    for minimum, expected in [
        (roles.ROLE_OWNER, 1),
        (roles.ROLE_ADMIN, 2),
        (roles.ROLE_TECHFM_OA, 3),
        (roles.ROLE_SUPERVISOR, 4),
        (roles.ROLE_TECHNICIAN, 5),
    ]:
        assert len(push_service._recipient_roles(minimum)) == expected


# --- database: the subscription store -----------------------------------

def test_saving_a_subscription_stores_the_keys(db):
    user = _seed_user(db, roles.ROLE_ADMIN)
    endpoint = _endpoint()

    push_service.save_subscription(db, user.id, endpoint, "p256dh-value", "auth-value")

    row = db.get(PushSubscription, endpoint)
    assert row.user_id == user.id
    assert row.p256dh == "p256dh-value"
    assert row.auth == "auth-value"


def test_resubscribing_reassigns_the_device_instead_of_duplicating(db):
    """The shared-phone rule, and the reason `endpoint` is the primary
    key. One physical device produces one endpoint; if a second user logs
    in on it, the row must move rather than multiply -- otherwise the
    first user keeps receiving on a phone they no longer hold."""
    first = _seed_user(db, roles.ROLE_ADMIN)
    second = _seed_user(db, roles.ROLE_ADMIN)
    endpoint = _endpoint()

    push_service.save_subscription(db, first.id, endpoint, "k1", "a1")
    push_service.save_subscription(db, second.id, endpoint, "k2", "a2")

    rows = db.query(PushSubscription).filter(PushSubscription.endpoint == endpoint).all()
    assert len(rows) == 1
    assert rows[0].user_id == second.id
    assert rows[0].p256dh == "k2"


def test_deleting_is_scoped_to_the_owning_user(db):
    """A caller must not be able to unsubscribe someone else's device by
    presenting its endpoint."""
    owner_of_device = _seed_user(db, roles.ROLE_ADMIN)
    other = _seed_user(db, roles.ROLE_ADMIN)
    endpoint = _endpoint()
    push_service.save_subscription(db, owner_of_device.id, endpoint, "k", "a")

    assert push_service.delete_subscription(db, other.id, endpoint) is False
    assert db.get(PushSubscription, endpoint) is not None

    assert push_service.delete_subscription(db, owner_of_device.id, endpoint) is True
    assert db.get(PushSubscription, endpoint) is None


def test_deleting_a_missing_subscription_is_not_an_error(db):
    """Logging out twice, or from a device that never opted in, is
    ordinary rather than exceptional."""
    user = _seed_user(db, roles.ROLE_ADMIN)
    assert push_service.delete_subscription(db, user.id, _endpoint()) is False


# --- database: the audience ---------------------------------------------

def test_audience_includes_admin_and_owner_only(db):
    wanted = []
    for role in (roles.ROLE_ADMIN, roles.ROLE_OWNER):
        user = _seed_user(db, role)
        endpoint = _endpoint()
        push_service.save_subscription(db, user.id, endpoint, "k", "a")
        wanted.append(endpoint)

    for role in (roles.ROLE_TECHFM_OA, roles.ROLE_SUPERVISOR, roles.ROLE_TECHNICIAN):
        user = _seed_user(db, role)
        push_service.save_subscription(db, user.id, _endpoint(), "k", "a")

    found = {
        s.endpoint
        for s in push_service.subscriptions_for_min_role(db, roles.ROLE_ADMIN)
    }
    assert set(wanted) <= found
    assert len(found & set(wanted)) == 2


def test_archived_users_do_not_receive(db):
    """An archived account cannot log in; it must not keep receiving
    notifications either."""
    from datetime import datetime, timezone

    user = _seed_user(db, roles.ROLE_ADMIN)
    endpoint = _endpoint()
    push_service.save_subscription(db, user.id, endpoint, "k", "a")

    user.archived_at = datetime.now(timezone.utc)
    db.flush()

    found = {
        s.endpoint
        for s in push_service.subscriptions_for_min_role(db, roles.ROLE_ADMIN)
    }
    assert endpoint not in found


# --- database: the fan-out ----------------------------------------------

@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(push_service, "VAPID_PRIVATE_KEY", "test-private-key")
    return True


@pytest.fixture
def only_seeded_subscriptions(db):
    """Hide any subscription this database already holds from the fan-out.

    A fan-out queries *every* subscription at or above a role, so a real
    device enrolled on a development machine -- the Owner's phone, for
    instance -- joins every send under test. The scripted `_send_one` below
    then sees an endpoint it has no outcome for, and the counting assertions
    see a send they did not seed.

    The delete runs inside the `db` fixture's transaction and is discarded
    with it, so a developer's genuinely enrolled device survives the run.
    CI never needed this because its database is empty, which is precisely
    why the failure appears only on a machine that has actually used the
    feature.
    """
    db.query(PushSubscription).delete()
    db.flush()


def _fake_send(outcomes):
    """Replace `_send_one` with a scripted sequence of outcomes, keyed by
    endpoint so ordering does not matter."""
    def send(subscription, payload):
        return outcomes[subscription.endpoint]

    return send


def test_a_dead_subscription_is_deleted(db, monkeypatch, configured, only_seeded_subscriptions):
    """404/410 is the only status class where deletion is correct."""
    user = _seed_user(db, roles.ROLE_ADMIN)
    endpoint = _endpoint()
    push_service.save_subscription(db, user.id, endpoint, "k", "a")

    monkeypatch.setattr(
        push_service,
        "_send_one",
        _fake_send({endpoint: push_policy.PUSH_DROP_SUBSCRIPTION}),
    )

    result = push_service.send_to_min_role(db, roles.ROLE_ADMIN, "t", "b")

    assert result["dropped"] == 1
    assert db.get(PushSubscription, endpoint) is None


@pytest.mark.parametrize(
    "outcome",
    [
        push_policy.PUSH_CONFIGURATION_ERROR,
        push_policy.PUSH_PAYLOAD_TOO_LARGE,
        push_policy.PUSH_RETRY,
    ],
)
def test_a_failed_send_never_deletes_the_subscription(
    db, monkeypatch, configured, only_seeded_subscriptions, outcome
):
    """The disaster `classify_push_response` was written to prevent: a
    bad key returns 401 for *every* device, and deleting on that would
    wipe the table and force everyone to opt in again."""
    user = _seed_user(db, roles.ROLE_ADMIN)
    endpoint = _endpoint()
    push_service.save_subscription(db, user.id, endpoint, "k", "a")

    monkeypatch.setattr(push_service, "_send_one", _fake_send({endpoint: outcome}))

    result = push_service.send_to_min_role(db, roles.ROLE_ADMIN, "t", "b")

    assert result["failed"] == 1
    assert result["dropped"] == 0
    assert db.get(PushSubscription, endpoint) is not None


def test_a_disallowed_endpoint_is_never_requested(db, monkeypatch, configured, only_seeded_subscriptions):
    """The SSRF guard. A row whose host is not on the allowlist must fail
    without the send being attempted at all -- reaching `_send_one` would
    mean the server made the request."""
    user = _seed_user(db, roles.ROLE_ADMIN)
    hostile = "https://internal.example.com/hook"
    db.add(PushSubscription(endpoint=hostile, user_id=user.id, p256dh="k", auth="a"))
    db.flush()

    def explode(subscription, payload):  # pragma: no cover - must not run
        raise AssertionError("send attempted for a disallowed endpoint")

    monkeypatch.setattr(push_service, "_send_one", explode)

    result = push_service.send_to_min_role(db, roles.ROLE_ADMIN, "t", "b")

    assert result["failed"] == 1
    assert result["sent"] == 0


def test_mixed_outcomes_are_counted_separately(db, monkeypatch, configured, only_seeded_subscriptions):
    """A partial failure is the interesting case during a rollout, so the
    three counts must not collapse into one."""
    user = _seed_user(db, roles.ROLE_ADMIN)
    ok, dead, broken = _endpoint("a"), _endpoint("b"), _endpoint("c")
    for endpoint in (ok, dead, broken):
        push_service.save_subscription(db, user.id, endpoint, "k", "a")

    monkeypatch.setattr(
        push_service,
        "_send_one",
        _fake_send({
            ok: push_policy.PUSH_OK,
            dead: push_policy.PUSH_DROP_SUBSCRIPTION,
            broken: push_policy.PUSH_RETRY,
        }),
    )

    result = push_service.send_to_min_role(db, roles.ROLE_ADMIN, "t", "b")

    assert result == {"sent": 1, "dropped": 1, "failed": 1}
    assert db.get(PushSubscription, ok) is not None
    assert db.get(PushSubscription, dead) is None
    assert db.get(PushSubscription, broken) is not None


# --- configuration ------------------------------------------------------

def test_push_is_disabled_without_a_private_key(monkeypatch):
    """A deployment that never configured push must still serve every
    other route, so the missing key disables the feature rather than
    raising at import."""
    monkeypatch.setattr(push_service, "VAPID_PRIVATE_KEY", "")
    assert push_service.is_configured() is False

    monkeypatch.setattr(push_service, "VAPID_PRIVATE_KEY", "something")
    assert push_service.is_configured() is True


def test_the_committed_public_key_is_a_valid_p256_point():
    """The public key is a constant in the source. A truncated or
    mistyped copy would be accepted by the server and rejected by the
    browser at `subscribe()` time, which reports nothing useful."""
    import base64

    raw = base64.urlsafe_b64decode(
        push_service.VAPID_PUBLIC_KEY
        + "=" * (-len(push_service.VAPID_PUBLIC_KEY) % 4)
    )
    assert len(raw) == 65
    assert raw[0] == 0x04

    from cryptography.hazmat.primitives.asymmetric import ec

    # Raises if the bytes are not actually on the curve.
    ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)
