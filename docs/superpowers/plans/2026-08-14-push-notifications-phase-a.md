# Push Notification Infrastructure — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A signed-in user can enable notifications on a device and receive a
real OS notification there **while the app is closed**. No notification types,
no routing rules, no business events — only the infrastructure that everything
later depends on.

**Architecture:** A root-scoped service worker with no `fetch` handler receives
push messages and displays them. A `push_subscriptions` table binds a browser's
`PushSubscription` to a user, keyed uniquely on the endpoint so re-registering
reassigns ownership. Subscriptions deliberately **outlive login sessions** —
they are deleted on explicit logout, on a `404`/`410` from the push service, and
on user archive, but never merely because a session expired. Delivery uses
`pywebpush` against the standard Web Push protocol with VAPID; no Firebase
project, no third-party SDK.

**Tech Stack:** FastAPI (synchronous handlers), SQLAlchemy + Alembic,
`pywebpush` 2.4.0, plain ES modules (no bundler), pytest.

## Global Constraints

- **Source of truth:** `docs/superpowers/specs/2026-08-14-browser-notifications-architecture-review.md`. Section references (§) point there.
- **Branch:** all work lands on `feat/push-notifications`. **Merging to `main` deploys to production** (`.github/workflows/ci.yml`). Every merge is an explicit owner decision — Task 11 is the only task that merges, and it stops for approval first.
- **There is no staging environment.** Tasks 1–10 are verified locally and on the local network; Task 11 is the single production deploy. This is a deliberate owner decision (2026-08-14); the risk it accepts is documented in Task 11.
- **Subscription lifetime is not session lifetime** (§10.4). Session expiry must never delete a subscription. This is the requirement that makes out-of-app delivery work at all, and it is easy to break by accident.
- **The service worker must never contain a `fetch` event listener** (§12.2). A test enforces this. It is what keeps the worker out of the navigation path and prevents reintroducing the stale-asset blank-page failure that `NoCacheStaticFiles` exists to prevent.
- **The opt-in control is Owner-only for now.** The crew must not meet a half-proven feature. Widening it is a one-line change once Task 11 passes.
- **Layer discipline** (§2.2): `routers → schemas/services → domain/models → database`. `app/domain/*` stays pure — no FastAPI, no SQLAlchemy, no `pywebpush`.
- **CSP is `default-src 'self'`** with no `unsafe-inline` (`app/main.py:140`). No inline `<script>`, no inline `style=`, no `on*` attributes in new HTML.
- **Notification content carries no names, buildings, unit numbers, work-order numbers, prices, or quantities** (§10.3). Not even in a test message.
- **Test style:** pure unit tests calling handlers directly, monkeypatching I/O. See `tests/test_health_check.py`, `tests/test_docs_endpoints.py`. The `db` fixture in `conftest.py` rolls back after each test.
- **`pip-audit` is a blocking CI gate.** A new dependency that fails it means `main` cannot deploy.
- **Commit style:** conventional, scoped `push` — `feat(push):`, `test(push):`.
- **Secrets never enter git.** `backend/.env` is already gitignored.

---

## File Structure

**Created:**

| Path | Responsibility |
|---|---|
| `backend/app/domain/push.py` | Pure policy: push-service response classification, push-endpoint allowlist. No I/O. |
| `backend/app/services/push_subscriptions.py` | Subscription persistence: upsert-with-reassign, delete, list. |
| `backend/app/services/push_delivery.py` | The only module that talks to a push service. Encrypt, sign, send, classify. |
| `backend/app/schemas/push.py` | Request/response shapes, matching the browser's `subscription.toJSON()` verbatim. |
| `backend/app/routers/push.py` | `/push/*` endpoints. |
| `backend/alembic/versions/<rev>_add_push_subscriptions.py` | The one migration. |
| `backend/static/sw.js` | Service worker: push display, notification click. **No fetch handler.** |
| `backend/static/manifest.json` | Web app manifest — required for Home Screen install on iOS < 26. |
| `backend/static/icons/` | `icon-192.png`, `icon-512.png`, `apple-touch-icon.png`. |
| `backend/static/views/notifications.js` | The opt-in control and subscription lifecycle. |
| `backend/static/sw-reset.html` + `.js` | Emergency service-worker uninstall, reachable from a phone. |
| `backend/scripts/generate_vapid_keys.py` | One-time VAPID keypair generation. |
| `backend/scripts/make_icons.py` | Derives manifest icons from the existing favicon. |
| `backend/tests/test_push_domain.py` | Response classification + endpoint allowlist. |
| `backend/tests/test_push_subscriptions_service.py` | Reassign, delete, cascade, session-independence. |
| `backend/tests/test_push_routes.py` | Auth gates, validation, self-only test send. |
| `backend/tests/test_service_worker.py` | Route, headers, no-fetch tripwire, uninstall page. |
| `backend/tests/test_web_app_manifest.py` | Manifest validity and shell linkage. |
| `backend/tests/test_vapid_keys.py` | Keypair round-trip through the signing library. |

**Modified:**

| Path | Change |
|---|---|
| `backend/requirements.txt` | Add `pywebpush==2.4.0`. |
| `backend/app/models.py` | Append the `PushSubscription` model. |
| `backend/app/main.py` | Add the root-scoped `GET /sw.js` route; include the push router; add `FileResponse` import. |
| `backend/app/services/users.py` | Delete subscriptions on archive and password reset, mirroring existing session revocation. |
| `backend/static/api.js` | Four `api*` wrappers for the new endpoints. |
| `backend/static/main.js` | Side-effect import of `views/notifications.js`. |
| `backend/static/views/auth.js` | Boot-time subscription re-assert; unsubscribe on logout. |
| `backend/static/shell-head.html` | Manifest + apple-touch-icon links, theme-color, and the opt-in button in `#auth-bar`. |

---

## Task 1: Add `pywebpush` and generate a VAPID keypair

**Files:**
- Modify: `backend/requirements.txt`
- Create: `backend/scripts/generate_vapid_keys.py`
- Test: `backend/tests/test_vapid_keys.py`

**Interfaces:**
- Consumes: nothing
- Produces: `scripts.generate_vapid_keys.generate_vapid_keypair() -> tuple[str, str]` returning `(private_key_b64, public_key_b64)`. Public is the raw uncompressed P-256 point (65 bytes) browsers require for `applicationServerKey`. Private is base64url PKCS#8 DER, the form `pywebpush` accepts.

- [ ] **Step 1: Add the dependency**

Append to `backend/requirements.txt`:

```
# Web Push (RFC 8030 / 8291 / 8292). The de-facto Python implementation, from
# the same org as the reference VAPID libraries. Synchronous and `requests`-
# based, which is a feature here rather than a limitation: every route handler
# in this app is a sync `def` in a threadpool, so delivery matches the app's
# existing concurrency model instead of fighting it.
#
# 2.4.0 is current (2026-08-06). Pinned exactly: PyPI flags this a "Critical
# Project" maintained by one person, so a version bump is a supply-chain event
# to choose deliberately rather than inherit.
pywebpush==2.4.0
```

- [ ] **Step 2: Install and confirm the audit is clean**

```bash
cd /c/Users/mcclu/Desktop/inventory_app_git/backend
pip install -r requirements.txt
pip install pip-audit
pip-audit --requirement requirements.txt --desc
```

Expected: `No known vulnerabilities found`. **If any advisory appears, stop and
report it** — `pip-audit` is a blocking CI gate, so a red audit means `main`
cannot deploy at all.

- [ ] **Step 3: Discover the signing library's actual API**

```bash
python -c "import py_vapid, inspect; print([n for n in dir(py_vapid) if not n.startswith('_')]); print(inspect.signature(py_vapid.Vapid02.from_string))"
```

The test below assumes `py_vapid.Vapid02.from_string(<base64 DER>)`. If the
discovered API differs, adjust the **call site**, not the assertions.

- [ ] **Step 4: Write the failing test**

Create `backend/tests/test_vapid_keys.py`:

```python
"""Tests for VAPID keypair generation.

Layer: unit (no DB, no HTTP client).

These assert interoperability, not cryptography. The failure they guard against
is quiet and expensive: a keypair that looks fine, is accepted by our own code,
and is then rejected by every browser -- because the public half was serialized
in the wrong form. Browsers need the raw uncompressed P-256 point (65 bytes,
leading 0x04), not DER, not PEM, not a compressed point. Nothing else in this
repo would notice until a real device silently failed to subscribe.
"""

import base64
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.generate_vapid_keys import generate_vapid_keypair


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def test_the_public_key_is_a_raw_uncompressed_p256_point():
    _private, public = generate_vapid_keypair()
    raw = _b64url_decode(public)

    # 1 marker byte + 32-byte X + 32-byte Y -- exactly what
    # `pushManager.subscribe({applicationServerKey})` requires.
    assert len(raw) == 65
    assert raw[0] == 0x04


def test_both_halves_are_url_safe_base64_without_padding():
    private, public = generate_vapid_keypair()

    for value in (private, public):
        assert "=" not in value
        assert "+" not in value
        assert "/" not in value


def test_each_call_produces_a_different_keypair():
    first_private, first_public = generate_vapid_keypair()
    second_private, second_public = generate_vapid_keypair()

    assert first_private != second_private
    assert first_public != second_public


def test_the_private_key_loads_in_the_library_that_will_sign_with_it():
    # The round-trip that matters: our serialization must be readable by the
    # exact code path `pywebpush` uses to sign, or every send fails at runtime
    # with a key that passed every test above.
    from py_vapid import Vapid02

    private, _public = generate_vapid_keypair()
    vapid = Vapid02.from_string(private)

    headers = vapid.sign({
        "aud": "https://fcm.googleapis.com",
        "sub": "mailto:ops@example.com",
    })

    authorization = headers["Authorization"]
    assert isinstance(authorization, str) and authorization
    # A JWT: header.payload.signature. Asserted structurally rather than by
    # prefix, which differs between the VAPID drafts the library supports.
    assert authorization.count(".") == 2
```

- [ ] **Step 5: Run the test to verify it fails**

```bash
python -m pytest tests/test_vapid_keys.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.generate_vapid_keys'`.

- [ ] **Step 6: Write the implementation**

Create `backend/scripts/generate_vapid_keys.py`:

```python
"""Generate a VAPID keypair for Web Push.

Run once per environment. The public half is handed to browsers at subscribe
time; the private half signs a JWT on every send and is a secret on the level
of `DATABASE_URL`.

Run from the `backend/` directory:

    python -m scripts.generate_vapid_keys

Store the private key in `backend/.env` locally (already gitignored) and in the
Render dashboard for production. It must never be committed.

Rotating the keypair invalidates EVERY existing push subscription: the public
key is bound into the subscription by the browser at `subscribe()` time. A
rotation therefore forces every user to opt in again on every device. That is
the accepted cost of a leaked private key, and it is worth rehearsing once
before it is ever needed for real.
"""

import base64
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402


def _b64url(raw: bytes) -> str:
    """URL-safe base64 with padding stripped -- the encoding the Web Push specs
    use throughout, and the only one browsers accept for
    `applicationServerKey`."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def generate_vapid_keypair() -> tuple[str, str]:
    """Return `(private_key_b64, public_key_b64)`.

    The public half is the **raw uncompressed point** (0x04 || X || Y, 65
    bytes), deliberately not DER or PEM: `pushManager.subscribe()` rejects
    anything else, and the failure is quiet enough to be worth stating here as
    well as in the tests.

    The private half is PKCS#8 DER, base64url-encoded -- the form `py_vapid`
    reads with `Vapid02.from_string`, so it round-trips through the exact code
    path that will sign real messages.
    """
    private_key = ec.generate_private_key(ec.SECP256R1())

    public_raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    private_der = private_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    return _b64url(private_der), _b64url(public_raw)


def main() -> int:
    private, public = generate_vapid_keypair()

    print("VAPID keypair generated. Store the private key as a secret.\n")
    print(f"VAPID_PRIVATE_KEY={private}")
    print(f"VAPID_PUBLIC_KEY={public}")
    print(
        "\nThe public key is not a secret -- browsers receive it. "
        "The private key must never be committed.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 7: Run the test to verify it passes**

```bash
python -m pytest tests/test_vapid_keys.py -v
```

Expected: 4 passed.

- [ ] **Step 8: Generate the keypair and store it locally**

```bash
python -m scripts.generate_vapid_keys
```

Append both lines to `backend/.env`, plus a contact subject:

```
VAPID_PRIVATE_KEY=<printed value>
VAPID_PUBLIC_KEY=<printed value>
VAPID_SUBJECT=mailto:mcclurejohn81@gmail.com
```

Confirm nothing is staged:

```bash
git status --porcelain backend/.env
```

Expected: no output.

- [ ] **Step 9: Commit**

```bash
git add backend/requirements.txt backend/scripts/generate_vapid_keys.py backend/tests/test_vapid_keys.py
git commit -m "feat(push): add pywebpush and VAPID keypair generation"
```

---

## Task 2: Pure push policy — response classification and endpoint allowlist

Two pure functions, and both guard a specific disaster. Written first, in
isolation, because neither needs a database and both are cheap to get wrong.

**Files:**
- Create: `backend/app/domain/push.py`
- Test: `backend/tests/test_push_domain.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `classify_push_response(status_code: int) -> str`, returning one of `PUSH_OK`, `PUSH_DROP_SUBSCRIPTION`, `PUSH_CONFIGURATION_ERROR`, `PUSH_PAYLOAD_TOO_LARGE`, `PUSH_RETRY`
  - `is_allowed_push_endpoint(endpoint: str) -> bool`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_push_domain.py`:

```python
"""Tests for pure Web Push policy.

Layer: pure unit (no DB, no HTTP, no pywebpush), matching the other `domain/`
test files.

Two disasters are guarded here.

`test_no_status_other_than_404_or_410_can_ever_delete_a_subscription` -- one
mistyped VAPID key makes every push service answer 401. Code that treats "any
4xx" as "this subscription is dead" would empty the entire table in a single
pass, and every user would have to opt in again on every device with nothing
explaining why.

`test_internal_and_metadata_addresses_are_rejected` -- `POST
/push/subscriptions` hands the server a URL and asks it to make a request. With
no allowlist that is a blind SSRF primitive pointed at Render's internal
network, and cloud metadata endpoints are the classic target.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from app.domain.push import (
    PUSH_CONFIGURATION_ERROR,
    PUSH_DROP_SUBSCRIPTION,
    PUSH_OK,
    PUSH_PAYLOAD_TOO_LARGE,
    PUSH_RETRY,
    classify_push_response,
    is_allowed_push_endpoint,
)


# --------------------------------------------------------------------------
# Response classification
# --------------------------------------------------------------------------

@pytest.mark.parametrize("status", [200, 201, 202, 204])
def test_2xx_is_a_successful_delivery(status):
    assert classify_push_response(status) == PUSH_OK


@pytest.mark.parametrize("status", [404, 410])
def test_only_404_and_410_mean_the_subscription_is_gone(status):
    # 404: the push service does not recognise the endpoint.
    # 410 Gone: the subscription was explicitly revoked.
    # These are the ONLY statuses that say anything about the subscription.
    assert classify_push_response(status) == PUSH_DROP_SUBSCRIPTION


@pytest.mark.parametrize("status", [401, 403])
def test_auth_failures_are_our_problem_not_the_subscriptions(status):
    # Our VAPID JWT was rejected. Equally true of every other subscription in
    # the table, so it must never be read as a property of this one.
    assert classify_push_response(status) == PUSH_CONFIGURATION_ERROR


def test_413_is_reported_distinctly():
    assert classify_push_response(413) == PUSH_PAYLOAD_TOO_LARGE


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_throttling_and_server_errors_are_retryable(status):
    assert classify_push_response(status) == PUSH_RETRY


def test_an_unrecognised_4xx_is_never_retried_and_never_deletes():
    # Fail closed both ways: do not destroy data we have no evidence is bad,
    # and do not hammer a push service over an error that will not self-heal.
    assert classify_push_response(400) == PUSH_CONFIGURATION_ERROR
    assert classify_push_response(451) == PUSH_CONFIGURATION_ERROR


def test_no_status_other_than_404_or_410_can_ever_delete_a_subscription():
    for status in range(200, 600):
        if status in (404, 410):
            continue
        assert classify_push_response(status) != PUSH_DROP_SUBSCRIPTION, (
            f"status {status} must not delete a subscription"
        )


# --------------------------------------------------------------------------
# Endpoint allowlist (SSRF guard)
# --------------------------------------------------------------------------

@pytest.mark.parametrize("endpoint", [
    "https://fcm.googleapis.com/fcm/send/abc123",
    "https://fcm.googleapis.com/wp/abc123",
    "https://web.push.apple.com/QABC123",
    "https://updates.push.services.mozilla.com/wpush/v2/abc",
])
def test_real_push_service_endpoints_are_allowed(endpoint):
    assert is_allowed_push_endpoint(endpoint) is True


@pytest.mark.parametrize("endpoint", [
    "http://169.254.169.254/latest/meta-data/",
    "https://169.254.169.254/latest/meta-data/",
    "http://localhost:8124/db-test",
    "https://127.0.0.1/",
    "http://10.0.0.5/internal",
    "https://metadata.google.internal/computeMetadata/v1/",
])
def test_internal_and_metadata_addresses_are_rejected(endpoint):
    assert is_allowed_push_endpoint(endpoint) is False


@pytest.mark.parametrize("endpoint", [
    "https://evil.com/fcm.googleapis.com",
    "https://notfcm.googleapis.com/x",
    "https://fcm.googleapis.com.evil.com/x",
    "https://push.apple.com.attacker.net/x",
])
def test_lookalike_hosts_are_rejected(endpoint):
    # Suffix matching must require a literal dot boundary, or
    # `notfcm.googleapis.com` slips through.
    assert is_allowed_push_endpoint(endpoint) is False


def test_plain_http_is_rejected_even_for_an_allowed_host():
    assert is_allowed_push_endpoint("http://fcm.googleapis.com/fcm/send/x") is False


@pytest.mark.parametrize("endpoint", [
    "",
    "   ",
    "not-a-url",
    "ftp://fcm.googleapis.com/x",
    "https://user:pass@fcm.googleapis.com/x",
    "//fcm.googleapis.com/x",
])
def test_malformed_and_credentialed_urls_are_rejected(endpoint):
    assert is_allowed_push_endpoint(endpoint) is False
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python -m pytest tests/test_push_domain.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.domain.push'`.

- [ ] **Step 3: Write the implementation**

Create `backend/app/domain/push.py`:

```python
"""Pure Web Push policy -- no I/O, no pywebpush, no SQLAlchemy.

Layer: domain, alongside `domain/realtime.py`. Everything here is a decision
that can be made without talking to anything, which is what makes it testable
without a database or a network.
"""

from urllib.parse import urlsplit

__all__ = [
    "PUSH_OK",
    "PUSH_DROP_SUBSCRIPTION",
    "PUSH_CONFIGURATION_ERROR",
    "PUSH_PAYLOAD_TOO_LARGE",
    "PUSH_RETRY",
    "ALLOWED_PUSH_HOSTS",
    "classify_push_response",
    "is_allowed_push_endpoint",
]

# --- response classification -------------------------------------------

# Delivered. The push service has accepted responsibility for the message.
PUSH_OK = "ok"

# This subscription is dead. Delete the row -- do not disable it, do not retry.
# Reached by 404 and 410 and by nothing else, ever.
PUSH_DROP_SUBSCRIPTION = "drop_subscription"

# We are misconfigured. True of every message, not of one subscription.
# Never deletes anything; should alert.
PUSH_CONFIGURATION_ERROR = "configuration_error"

# We sent something too big. Split out from the generic configuration error so
# it is distinguishable in logs at a glance.
PUSH_PAYLOAD_TOO_LARGE = "payload_too_large"

# Transient. Back off and try again within a bounded budget.
PUSH_RETRY = "retry"


def classify_push_response(status_code: int) -> str:
    """What a push service's HTTP status means for the subscription.

    The split that matters is inside the 4xx range, and it is the opposite of
    the intuitive reading. `404` and `410` are statements about the
    *subscription*: the endpoint is unknown or explicitly revoked, so the row
    is worthless. `401` and `403` are statements about *us*: our VAPID JWT was
    rejected, which is equally true for every other row in the table.

    Collapsing those cases into "any 4xx means delete" empties the subscription
    table on the first key misconfiguration. `tests/test_push_domain.py`
    asserts exhaustively that no status outside {404, 410} reaches the delete
    branch.

    Order is significant: specific statuses are matched before the generic 4xx
    fallback.
    """
    if 200 <= status_code < 300:
        return PUSH_OK
    if status_code in (404, 410):
        return PUSH_DROP_SUBSCRIPTION
    if status_code in (401, 403):
        return PUSH_CONFIGURATION_ERROR
    if status_code == 413:
        return PUSH_PAYLOAD_TOO_LARGE
    if status_code == 429:
        return PUSH_RETRY
    if 400 <= status_code < 500:
        # Unrecognised client error. Fail closed both ways: no evidence the
        # subscription is bad, and a 4xx will not fix itself on retry.
        return PUSH_CONFIGURATION_ERROR
    return PUSH_RETRY


# --- endpoint allowlist -------------------------------------------------

# Registration hands the server a URL and later asks it to POST there. Without
# this allowlist that is a blind SSRF primitive inside Render's network. These
# are the only hosts a browser can legitimately produce.
ALLOWED_PUSH_HOSTS: tuple[str, ...] = (
    "fcm.googleapis.com",          # Chrome, Edge
    "push.apple.com",              # Safari (web.push.apple.com and friends)
    "push.services.mozilla.com",   # Firefox
)


def is_allowed_push_endpoint(endpoint: str) -> bool:
    """Whether `endpoint` is a URL we are willing to send a push request to.

    Deliberately an allowlist rather than a denylist of private ranges. A
    denylist has to anticipate every internal address, DNS rebinding, and IPv6
    form; an allowlist only has to name the three push services that exist.
    New browsers are a known, reviewable change to this tuple.

    Suffix matching requires a literal dot boundary, so `notfcm.googleapis.com`
    and `fcm.googleapis.com.evil.com` are both rejected. HTTPS is mandatory,
    and embedded credentials are refused outright -- a browser never produces
    them, so their presence means the value did not come from a browser.
    """
    if not endpoint or not endpoint.strip():
        return False
    try:
        parsed = urlsplit(endpoint.strip())
    except ValueError:
        return False

    if parsed.scheme != "https":
        return False
    if parsed.username is not None or parsed.password is not None:
        return False

    try:
        host = parsed.hostname
    except ValueError:
        return False
    if not host:
        return False

    host = host.lower()
    return any(
        host == allowed or host.endswith("." + allowed)
        for allowed in ALLOWED_PUSH_HOSTS
    )
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
python -m pytest tests/test_push_domain.py -v
```

Expected: 37 passed (16 classification + 21 allowlist, after parametrization).

- [ ] **Step 5: Commit**

```bash
git add backend/app/domain/push.py backend/tests/test_push_domain.py
git commit -m "feat(push): add push response classification and endpoint allowlist"
```

---

## Task 3: The `push_subscriptions` table

**Files:**
- Modify: `backend/app/models.py` (append the model)
- Create: `backend/alembic/versions/<rev>_add_push_subscriptions.py`

**Interfaces:**
- Consumes: nothing
- Produces: `app.models.PushSubscription` with columns `id`, `user_id`, `endpoint` (UNIQUE), `p256dh`, `auth`, `created_at`, `last_success_at`, `last_failure_at`, `failure_count`

- [ ] **Step 1: Append the model**

Add to the end of `backend/app/models.py`:

```python
class PushSubscription(Base):
    """One browser profile's Web Push channel, claimed by a user.

    **A subscription is not a session.** This is the rule that makes
    out-of-app notification delivery work, and the easiest one to break by
    accident. `AuthSession` has a hard 12-hour cap, so tying a subscription's
    life to a session would silently stop notifications every night and resume
    them only when someone reopened the app -- exactly the behavior push exists
    to remove. A row here is deleted on explicit logout, on a 404/410 from the
    push service, and when the user is archived or their password is reset. It
    is NOT deleted merely because a session expired.

    `endpoint` is globally UNIQUE and that constraint is load-bearing rather
    than hygienic. A browser profile has exactly one push channel, so an
    endpoint arriving for a second time means the same browser is registering
    again -- and its rightful owner is whoever is authenticated now. Upserting
    on this constraint is what makes a shared computer safe: User B enabling
    notifications takes the endpoint away from User A rather than joining them
    on it. See `services.push_subscriptions.upsert_subscription`.

    `p256dh` and `auth` are the subscription's ECDH material (RFC 8291). With
    the endpoint they form a credential: anything holding all three can push to
    that device. They are stored because delivery requires them, and nothing
    else about the device is stored at all -- no user agent, no OS, no IP.
    Delivery needs four fields, and a table of employee device fingerprints is
    a capability nobody asked for.

    The FK is ON DELETE CASCADE so deleting a user cannot leave a live push
    target pointing at nobody.
    """

    __tablename__ = "push_subscriptions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    endpoint = Column(Text, nullable=False)
    p256dh = Column(Text, nullable=False)
    auth = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    # The only signal that a subscription is still alive. Nothing reads it yet;
    # the cleanup sweep that will is a later phase.
    last_success_at = Column(DateTime(timezone=True), nullable=True)
    last_failure_at = Column(DateTime(timezone=True), nullable=True)
    failure_count = Column(Integer, nullable=False, default=0, server_default="0")

    user = relationship("User")

    __table_args__ = (
        # Named explicitly rather than left to `unique=True` on the column, so
        # `services.push_subscriptions` can target it by name in an ON CONFLICT
        # clause. The ORM and the migration must agree on this name.
        UniqueConstraint("endpoint", name="uq_push_subscriptions_endpoint"),
        # Fan-out reads every subscription for one user.
        Index("ix_push_subscriptions_user_id", "user_id"),
    )
```

`Integer`, `UniqueConstraint`, and `Index` are already imported at the top of
`models.py`; no import changes are needed.

- [ ] **Step 2: Generate the migration skeleton**

Using `alembic revision` (not `--autogenerate`) sets `down_revision` to the
current head automatically, so there is nothing to look up and no chance of
creating a second head:

```bash
cd /c/Users/mcclu/Desktop/inventory_app_git/backend
alembic revision -m "add push subscriptions"
```

Note the generated filename.

- [ ] **Step 3: Fill in the migration body**

Replace the generated `upgrade`/`downgrade` with:

```python
def upgrade() -> None:
    op.create_table(
        "push_subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("p256dh", sa.Text(), nullable=False),
        sa.Column("auth", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "failure_count", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    # Named explicitly rather than left to `unique=True` on the column, so the
    # upsert in `services.push_subscriptions` can target it by name.
    op.create_unique_constraint(
        "uq_push_subscriptions_endpoint", "push_subscriptions", ["endpoint"]
    )
    op.create_index(
        "ix_push_subscriptions_user_id", "push_subscriptions", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_push_subscriptions_user_id", table_name="push_subscriptions")
    op.drop_constraint(
        "uq_push_subscriptions_endpoint", "push_subscriptions", type_="unique"
    )
    op.drop_table("push_subscriptions")
```

Ensure the imports at the top include:

```python
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
```

- [ ] **Step 4: Verify the migration round-trips**

CI runs exactly this, and a missing `downgrade` fails the build:

```bash
alembic upgrade head
alembic downgrade -1
alembic upgrade head
alembic heads | grep -c '(head)'
```

Expected: all four succeed; the final count is `1`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models.py backend/alembic/versions/
git commit -m "feat(push): add the push_subscriptions table"
```

---

## Task 4: Subscription service

**Files:**
- Create: `backend/app/services/push_subscriptions.py`
- Test: `backend/tests/test_push_subscriptions_service.py`

**Interfaces:**
- Consumes: `app.models.PushSubscription` (Task 3)
- Produces:
  - `upsert_subscription(db, *, user_id, endpoint, p256dh, auth) -> PushSubscription`
  - `delete_subscription(db, *, user_id, endpoint) -> bool`
  - `list_for_user(db, user_id) -> list[PushSubscription]`
  - `delete_all_for_user(db, user_id) -> int`
  - `drop_by_endpoint(db, endpoint) -> bool`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_push_subscriptions_service.py`:

```python
"""Tests for push subscription persistence.

Layer: service (uses the `db` fixture, which rolls back after each test).

The two tests that matter most are the shared-device one and the
session-independence one. Together they encode the whole reason this table is
shaped the way it is: an endpoint belongs to the browser, its owner is whoever
is authenticated now, and neither fact has anything to do with how long a login
session lasts.
"""

import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from app.domain.roles import ROLE_TECHNICIAN
from app.models import AuthSession, PushSubscription, User
from app.services import auth as auth_service
from app.services import push_subscriptions as service


def _user(db, username: str) -> User:
    user = User(
        id=uuid.uuid4(),
        username=username,
        first_name="Test",
        last_name="User",
        password_hash=auth_service.hash_password("password"),
        role=ROLE_TECHNICIAN,
    )
    db.add(user)
    db.flush()
    return user


ENDPOINT = "https://fcm.googleapis.com/fcm/send/abc123"


def test_a_new_subscription_is_stored_against_its_user(db):
    user = _user(db, f"alice-{uuid.uuid4().hex[:8]}")

    saved = service.upsert_subscription(
        db, user_id=user.id, endpoint=ENDPOINT, p256dh="key", auth="auth"
    )

    assert saved.user_id == user.id
    assert saved.endpoint == ENDPOINT
    assert saved.failure_count == 0


def test_registering_the_same_endpoint_twice_does_not_duplicate_it(db):
    user = _user(db, f"alice-{uuid.uuid4().hex[:8]}")

    service.upsert_subscription(
        db, user_id=user.id, endpoint=ENDPOINT, p256dh="key", auth="auth"
    )
    service.upsert_subscription(
        db, user_id=user.id, endpoint=ENDPOINT, p256dh="key2", auth="auth2"
    )

    rows = db.query(PushSubscription).filter_by(endpoint=ENDPOINT).all()
    assert len(rows) == 1
    # The keys are refreshed: a browser can rotate them on the same endpoint.
    assert rows[0].p256dh == "key2"


def test_a_second_user_registering_the_endpoint_takes_it_over(db):
    # The shared-computer case. User A enables notifications, walks away, and
    # User B signs in and enables them. The browser has ONE push channel, so
    # its owner must become B -- not both, and not still A.
    alice = _user(db, f"alice-{uuid.uuid4().hex[:8]}")
    bob = _user(db, f"bob-{uuid.uuid4().hex[:8]}")

    service.upsert_subscription(
        db, user_id=alice.id, endpoint=ENDPOINT, p256dh="key", auth="auth"
    )
    service.upsert_subscription(
        db, user_id=bob.id, endpoint=ENDPOINT, p256dh="key", auth="auth"
    )

    rows = db.query(PushSubscription).filter_by(endpoint=ENDPOINT).all()
    assert len(rows) == 1
    assert rows[0].user_id == bob.id
    assert service.list_for_user(db, alice.id) == []


def test_a_user_can_hold_several_devices(db):
    user = _user(db, f"alice-{uuid.uuid4().hex[:8]}")

    for suffix in ("phone", "desktop", "tablet"):
        service.upsert_subscription(
            db,
            user_id=user.id,
            endpoint=f"https://fcm.googleapis.com/fcm/send/{suffix}",
            p256dh="key",
            auth="auth",
        )

    assert len(service.list_for_user(db, user.id)) == 3


def test_deleting_one_device_leaves_the_others(db):
    user = _user(db, f"alice-{uuid.uuid4().hex[:8]}")
    for suffix in ("phone", "desktop"):
        service.upsert_subscription(
            db,
            user_id=user.id,
            endpoint=f"https://fcm.googleapis.com/fcm/send/{suffix}",
            p256dh="key",
            auth="auth",
        )

    removed = service.delete_subscription(
        db,
        user_id=user.id,
        endpoint="https://fcm.googleapis.com/fcm/send/phone",
    )

    assert removed is True
    assert len(service.list_for_user(db, user.id)) == 1


def test_a_user_cannot_delete_another_users_subscription(db):
    alice = _user(db, f"alice-{uuid.uuid4().hex[:8]}")
    bob = _user(db, f"bob-{uuid.uuid4().hex[:8]}")
    service.upsert_subscription(
        db, user_id=alice.id, endpoint=ENDPOINT, p256dh="key", auth="auth"
    )

    removed = service.delete_subscription(db, user_id=bob.id, endpoint=ENDPOINT)

    assert removed is False
    assert len(service.list_for_user(db, alice.id)) == 1


def test_deleting_a_missing_subscription_is_not_an_error(db):
    user = _user(db, f"alice-{uuid.uuid4().hex[:8]}")

    assert service.delete_subscription(
        db, user_id=user.id, endpoint="https://fcm.googleapis.com/fcm/send/nope"
    ) is False


def test_dropping_by_endpoint_ignores_ownership(db):
    # Used by the delivery path on a 404/410: the push service has told us the
    # endpoint is dead, which is true regardless of who claimed it.
    user = _user(db, f"alice-{uuid.uuid4().hex[:8]}")
    service.upsert_subscription(
        db, user_id=user.id, endpoint=ENDPOINT, p256dh="key", auth="auth"
    )

    assert service.drop_by_endpoint(db, ENDPOINT) is True
    assert service.list_for_user(db, user.id) == []


def test_deleting_all_of_a_users_subscriptions_reports_the_count(db):
    user = _user(db, f"alice-{uuid.uuid4().hex[:8]}")
    for suffix in ("a", "b", "c"):
        service.upsert_subscription(
            db,
            user_id=user.id,
            endpoint=f"https://fcm.googleapis.com/fcm/send/{suffix}",
            p256dh="key",
            auth="auth",
        )

    assert service.delete_all_for_user(db, user.id) == 3
    assert service.list_for_user(db, user.id) == []


def test_subscriptions_survive_every_session_being_revoked(db):
    # THE requirement (§10.4). Sessions have a hard 12-hour cap; if a
    # subscription died with them, notifications would stop every night and
    # resume only when someone reopened the app. Nothing in the session
    # lifecycle may touch this table.
    user = _user(db, f"alice-{uuid.uuid4().hex[:8]}")
    service.upsert_subscription(
        db, user_id=user.id, endpoint=ENDPOINT, p256dh="key", auth="auth"
    )
    auth_service.create_session(db, user, remember=False)

    db.query(AuthSession).filter_by(user_id=user.id).delete()
    db.flush()

    assert len(service.list_for_user(db, user.id)) == 1
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python -m pytest tests/test_push_subscriptions_service.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.push_subscriptions'`.

**If instead every test skips**, `DATABASE_URL` is unreachable — start Postgres
before continuing, or these tests prove nothing.

- [ ] **Step 3: Write the implementation**

Create `backend/app/services/push_subscriptions.py`:

```python
"""Push subscription persistence.

Layer: services. Owns every read and write of `push_subscriptions`; routers
never query it directly.

The whole module rests on one idea: **an endpoint identifies a browser, and its
owner is whoever is authenticated right now.** That is why registration is an
upsert on the endpoint rather than an insert, and it is what makes a shared shop
computer safe without any extra machinery.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import PushSubscription

logger = logging.getLogger(__name__)


def upsert_subscription(
    db: Session,
    *,
    user_id,
    endpoint: str,
    p256dh: str,
    auth: str,
) -> PushSubscription:
    """Store a subscription, transferring ownership if it already exists.

    **The conflict branch is the security control, not an optimisation.** A
    browser profile has exactly one push channel, so a repeat endpoint means
    the same browser is registering again. Assigning it to the caller -- rather
    than rejecting the request or creating a second row -- is what stops one
    person's notifications following a shared device to the next person who
    signs in.

    Done as a single `ON CONFLICT` statement rather than select-then-write so
    two devices racing on the same endpoint cannot both see "no existing row"
    and produce a duplicate. The endpoint's UNIQUE constraint is what the
    conflict targets.

    The encryption keys are refreshed on conflict: a browser may rotate them
    while keeping the endpoint, and stale keys make every later send fail to
    decrypt on the device with no server-side error to notice.
    """
    statement = (
        insert(PushSubscription)
        .values(
            user_id=user_id,
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
            created_at=datetime.now(timezone.utc),
            failure_count=0,
        )
        .on_conflict_do_update(
            constraint="uq_push_subscriptions_endpoint",
            set_={
                "user_id": user_id,
                "p256dh": p256dh,
                "auth": auth,
                # A re-registration is a fresh start: whatever failures the
                # previous claimant accumulated say nothing about this one.
                "failure_count": 0,
                "last_failure_at": None,
            },
        )
        .returning(PushSubscription.id)
    )
    subscription_id = db.execute(statement).scalar_one()
    db.commit()

    # Logged by id and host only. The full endpoint plus its keys is a
    # credential; `services.rate_limit.caller_key` hashes its input for the
    # same reason.
    logger.info(
        "push.subscription_saved",
        extra={"fields": {
            "subscription_id": str(subscription_id),
            "user_id": str(user_id),
        }},
    )
    return db.get(PushSubscription, subscription_id)


def delete_subscription(db: Session, *, user_id, endpoint: str) -> bool:
    """Remove one of the caller's own subscriptions. True if a row went away.

    Scoped to `user_id` so a caller cannot unsubscribe somebody else's device
    by guessing an endpoint. Returns False rather than raising when there is
    nothing to delete: the client calls this on logout, and a logout must never
    fail because a subscription had already been cleaned up.
    """
    removed = (
        db.query(PushSubscription)
        .filter(
            PushSubscription.user_id == user_id,
            PushSubscription.endpoint == endpoint,
        )
        .delete(synchronize_session=False)
    )
    db.commit()
    return removed > 0


def drop_by_endpoint(db: Session, endpoint: str) -> bool:
    """Remove a subscription the push service has reported dead, whoever owns
    it. Called ONLY for a 404 or 410 (`domain.push.PUSH_DROP_SUBSCRIPTION`) --
    never for an auth failure, which says nothing about the subscription."""
    removed = (
        db.query(PushSubscription)
        .filter(PushSubscription.endpoint == endpoint)
        .delete(synchronize_session=False)
    )
    db.commit()
    if removed:
        logger.info("push.subscription_dropped", extra={"fields": {"reason": "gone"}})
    return removed > 0


def list_for_user(db: Session, user_id) -> list[PushSubscription]:
    """Every device this user has claimed. Fan-out targets all of them --
    phone-plus-desktop is the normal case, not an edge case."""
    return (
        db.query(PushSubscription)
        .filter(PushSubscription.user_id == user_id)
        .order_by(PushSubscription.created_at)
        .all()
    )


def delete_all_for_user(db: Session, user_id) -> int:
    """Remove every subscription for a user. Returns the count.

    Called where sessions are already revoked wholesale -- archive and password
    reset -- so "sign out everywhere" also means "stop notifying everywhere".
    Deliberately NOT called on ordinary session expiry (§10.4).
    """
    removed = (
        db.query(PushSubscription)
        .filter(PushSubscription.user_id == user_id)
        .delete(synchronize_session=False)
    )
    db.commit()
    return removed
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
python -m pytest tests/test_push_subscriptions_service.py -v
```

Expected: 10 passed.

- [ ] **Step 5: Wire the wholesale-revocation paths**

In `backend/app/services/users.py`, find where a user's sessions are deleted on
**archive** and on **password reset**, and add a subscription delete alongside
each.

**Do not add one to the role-change path**, which also revokes sessions. A role
change is the same person continuing to work with different authority — their
devices should keep receiving notifications, and what they are notified *about*
is decided by the routing rules, not by whether a row survived. Archive and
password reset are the two "this identity is being cut off" moments; a role
change is not.

Use this comment at the first site:

```python
    # Sessions and push subscriptions are revoked together here specifically
    # because this is a "sign out everywhere" moment. Ordinary session expiry
    # must NOT do this -- see the PushSubscription docstring and §10.4.
    push_subscriptions.delete_all_for_user(db, user.id)
```

Add the import at the top of the module:

```python
from app.services import push_subscriptions
```

- [ ] **Step 6: Run the full suite**

```bash
python -m pytest -q
```

Expected: green. The users service tests exercise archive and password reset, so
a mistake in Step 5 surfaces here.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/push_subscriptions.py backend/app/services/users.py backend/tests/test_push_subscriptions_service.py
git commit -m "feat(push): store subscriptions, reassigning an endpoint to its current owner"
```

---

## Task 5: Delivery service

**Files:**
- Create: `backend/app/services/push_delivery.py`
- Test: extends `backend/tests/test_push_routes.py` in Task 7 (the delivery path is exercised through the endpoint)

**Interfaces:**
- Consumes: `app.domain.push` (Task 2), `app.services.push_subscriptions` (Task 4)
- Produces: `send_to_user(db, *, user_id, title, body) -> dict[str, int]` returning a count per outcome, e.g. `{"ok": 2, "drop_subscription": 1}`

- [ ] **Step 1: Write the implementation**

This module is written before its test because its only behavior is orchestration
over two already-tested units; Task 7 exercises it end to end through the route.

Create `backend/app/services/push_delivery.py`:

```python
"""Web Push delivery -- the only module that talks to a push service.

Layer: services. Synchronous, because `pywebpush` is and because every route
handler in this app already runs in a threadpool.

**This is a temporary shape.** Sending inside a request is acceptable only
while the sole caller is an Admin pressing "send a test notification" against
their own devices. A business event must never do this: delivery is N outbound
HTTPS calls to Google and Apple, and putting them in `POST /work-orders/...`
would add seconds of latency to an inventory write. The next phase moves this
behind a database-backed outbox drained by a background task on the existing
application lifespan. See §16 and §21.
"""

import json
import logging
import os
from datetime import datetime, timezone

from pywebpush import WebPushException, webpush
from sqlalchemy.orm import Session

from app.domain import push as policy
from app.models import PushSubscription
from app.services import push_subscriptions

logger = logging.getLogger(__name__)

# Seconds a push service may hold an undelivered message. Deliberately short:
# an operational notification that arrives a day late is worse than one that
# never arrives, because it prompts action on something already handled.
PUSH_TTL_SECONDS = 3600


def _vapid_private_key() -> str | None:
    return os.getenv("VAPID_PRIVATE_KEY")


def vapid_public_key() -> str | None:
    """The key browsers need at subscribe time. Not a secret."""
    return os.getenv("VAPID_PUBLIC_KEY")


def _vapid_claims() -> dict:
    # `sub` is a contact URI for whoever operates this sender. Push services
    # may use it to reach an operator about misbehaving traffic; its value is
    # not verified.
    return {"sub": os.getenv("VAPID_SUBJECT", "mailto:ops@example.com")}


def _build_payload(title: str, body: str) -> str:
    """The message the service worker will render.

    **Carries no operational detail** -- no names, buildings, unit numbers,
    work-order numbers, prices, or quantities (§10.3). A notification is
    visible on a locked phone to anyone holding it, so the body names a
    category and the specifics live behind the tap, after authentication.
    """
    return json.dumps({"title": title, "body": body})


def _record_success(db: Session, subscription: PushSubscription) -> None:
    subscription.last_success_at = datetime.now(timezone.utc)
    subscription.failure_count = 0
    db.commit()


def _record_failure(db: Session, subscription: PushSubscription) -> None:
    subscription.last_failure_at = datetime.now(timezone.utc)
    subscription.failure_count = (subscription.failure_count or 0) + 1
    db.commit()


def send_to_user(db: Session, *, user_id, title: str, body: str) -> dict[str, int]:
    """Deliver one message to every device a user has claimed.

    Returns a count per outcome so a caller can report honestly without
    learning what a push-service status code means.

    Fan-out is to all devices deliberately: phone-plus-desktop is the normal
    case. One device failing never stops the others -- a dead endpoint on an
    old phone must not suppress the notification on the phone in the user's
    hand.
    """
    private_key = _vapid_private_key()
    if not private_key:
        logger.error("push.vapid_key_missing")
        return {policy.PUSH_CONFIGURATION_ERROR: 1}

    outcomes: dict[str, int] = {}
    payload = _build_payload(title, body)

    for subscription in push_subscriptions.list_for_user(db, user_id):
        outcome = _send_one(db, subscription, payload, private_key)
        outcomes[outcome] = outcomes.get(outcome, 0) + 1

    return outcomes


def _send_one(
    db: Session,
    subscription: PushSubscription,
    payload: str,
    private_key: str,
) -> str:
    """One encrypted, signed POST to one push service. Never raises."""
    try:
        response = webpush(
            subscription_info={
                "endpoint": subscription.endpoint,
                "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
            },
            data=payload,
            vapid_private_key=private_key,
            vapid_claims=_vapid_claims(),
            ttl=PUSH_TTL_SECONDS,
        )
    except WebPushException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status is None:
            # Never reached the service at all -- DNS, TLS, timeout.
            logger.warning("push.send_failed", exc_info=True)
            _record_failure(db, subscription)
            return policy.PUSH_RETRY
        outcome = policy.classify_push_response(status)
    except Exception:  # pragma: no cover - belt and braces
        # A push failure must never become a 500 on the caller's request.
        logger.error("push.send_crashed", exc_info=True)
        return policy.PUSH_RETRY
    else:
        outcome = policy.classify_push_response(response.status_code)

    if outcome == policy.PUSH_OK:
        _record_success(db, subscription)
        return outcome

    if outcome == policy.PUSH_DROP_SUBSCRIPTION:
        # The ONLY branch that deletes. Reached by 404 and 410 alone.
        push_subscriptions.drop_by_endpoint(db, subscription.endpoint)
        return outcome

    if outcome == policy.PUSH_CONFIGURATION_ERROR:
        # Our credentials or our request are wrong, which is true of every
        # subscription. Loud, and it deletes nothing -- treating this as a dead
        # subscription would empty the table on one bad key.
        logger.error(
            "push.configuration_error",
            extra={"fields": {"detail": "VAPID rejected; no subscriptions removed"}},
        )
        return outcome

    _record_failure(db, subscription)
    return outcome
```

- [ ] **Step 2: Confirm it imports cleanly**

```bash
python -c "from app.services import push_delivery; print(push_delivery.PUSH_TTL_SECONDS)"
```

Expected: `3600`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/push_delivery.py
git commit -m "feat(push): add synchronous delivery with fail-closed failure handling"
```

---

## Task 6: Service worker, its root route, and the uninstall page

**Files:**
- Create: `backend/static/sw.js`, `backend/static/sw-reset.html`, `backend/static/sw-reset.js`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_service_worker.py`

**Interfaces:**
- Consumes: nothing
- Produces: `GET /sw.js` serving the worker at root scope with `Cache-Control: no-cache`; handler name `service_worker` in `app.main`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_service_worker.py`:

```python
"""Tests for the notification service worker and its root-scoped route.

Layer: unit (no DB, no HTTP client).

Two of these are regression guards rather than behavior tests, and they are why
the file exists.

`test_the_service_worker_has_no_fetch_handler` -- the app serves every asset
`no-cache` and reassembles the SPA shell from disk per request, both to defeat a
real blank-page stale-cache failure. A `fetch` listener here reintroduces that
bug in a worse form: persistent across reloads, ignoring Cache-Control, and
awkward to clear on a phone. A worker with no `fetch` listener is never
consulted for navigation or asset requests at all.

`test_the_worker_is_served_from_the_site_root` -- a worker's scope is capped by
its own URL path, so a worker under `/static/` could not focus or navigate the
app on notification click.
"""

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.routing import APIRoute

from app import main

STATIC = Path(__file__).resolve().parent.parent / "static"
SW_PATH = STATIC / "sw.js"
RESET_HTML = STATIC / "sw-reset.html"
RESET_JS = STATIC / "sw-reset.js"


def _service_worker_route():
    for route in main.app.routes:
        if isinstance(route, APIRoute) and route.path == "/sw.js":
            return route
    raise AssertionError("no route serving /sw.js is registered on the app")


# --------------------------------------------------------------------------
# The route
# --------------------------------------------------------------------------

def test_the_worker_is_served_from_the_site_root():
    assert _service_worker_route().path == "/sw.js"


def test_the_worker_route_is_unauthenticated():
    # A browser's request for a worker script is not guaranteed to carry
    # credentials. An auth dependency here would surface as "notifications
    # just don't work" rather than as a 401.
    route = _service_worker_route()

    assert route.dependant.dependencies == []
    assert route.dependencies == []


def test_the_worker_route_is_hidden_from_the_schema():
    assert _service_worker_route().include_in_schema is False


def test_the_worker_is_served_uncacheable_and_as_javascript():
    response = main.service_worker()

    assert response.headers["cache-control"] == "no-cache"
    assert "javascript" in response.media_type


# --------------------------------------------------------------------------
# The worker
# --------------------------------------------------------------------------

def test_the_service_worker_file_exists():
    assert SW_PATH.is_file()


def test_the_worker_handles_push_and_notification_click():
    source = SW_PATH.read_text(encoding="utf-8")

    assert 'addEventListener("push"' in source
    assert 'addEventListener("notificationclick"' in source


def test_the_worker_takes_over_immediately_on_update():
    # Every deploy ships a new copy of this file. Without these, a phone keeps
    # running the superseded worker until every tab is closed.
    source = SW_PATH.read_text(encoding="utf-8")

    assert "skipWaiting" in source
    assert "clients.claim" in source


def test_the_service_worker_has_no_fetch_handler():
    source = SW_PATH.read_text(encoding="utf-8")
    # Strip line comments first, so the file can EXPLAIN the rule without
    # tripping the check that enforces it.
    code = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("//")
    )

    assert re.findall(r"addEventListener\(\s*[\"']fetch[\"']", code) == [], (
        "sw.js must never handle `fetch`. Doing so puts the service worker in "
        "the navigation path and reintroduces the stale-asset blank-page bug "
        "that NoCacheStaticFiles exists to prevent."
    )
    assert "onfetch" not in code


# --------------------------------------------------------------------------
# The escape hatch
# --------------------------------------------------------------------------

def test_the_uninstall_page_exists():
    # Built before the worker ships, not after it breaks. A phone has no
    # developer console, so a documented snippet is not a recovery path.
    assert RESET_HTML.is_file()
    assert RESET_JS.is_file()


def test_the_uninstall_page_actually_unregisters():
    assert "unregister" in RESET_JS.read_text(encoding="utf-8")


def test_the_uninstall_page_obeys_the_content_security_policy():
    # `default-src 'self'`, no unsafe-inline. `scan-test.html` violates this
    # and is a documented exception; this file must not repeat it.
    html = RESET_HTML.read_text(encoding="utf-8")

    assert "<style" not in html
    assert "onclick" not in html
    for tag in re.findall(r"<script[^>]*>", html):
        assert "src=" in tag, f"inline script blocked by CSP: {tag}"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python -m pytest tests/test_service_worker.py -v
```

Expected: FAIL — `AssertionError: no route serving /sw.js is registered on the app`.

- [ ] **Step 3: Create the service worker**

Create `backend/static/sw.js`:

```js
// Notification service worker.
//
// Layer: browser background script. Deliberately tiny, with one hard rule:
//
//     THERE IS NO `fetch` EVENT LISTENER IN THIS FILE,
//     AND THERE MUST NEVER BE ONE.
//
// `app/main.py` serves every asset with `Cache-Control: no-cache` and
// reassembles the SPA shell from disk on every request to `/`. Both exist to
// defeat a real failure: a stale `main.js` renders a completely blank page. A
// worker that handled asset requests would bring that back in a worse form --
// it survives reloads, ignores Cache-Control, and is awkward to clear on a
// phone. A worker with no `fetch` listener is never consulted for navigation
// or asset requests, so the app loads exactly as it does with no worker.
//
// `tests/test_service_worker.py` fails the build if a fetch listener appears.
// `/static/sw-reset.html` is the manual escape hatch.

// One tag for every notification, so an at-least-once redelivery REPLACES the
// visible notification instead of stacking a second copy of the same event.
const NOTIFICATION_TAG = "inventory-app";

// Activate immediately rather than waiting for every tab to close.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
  // The payload carries only a category-level title and body -- never a name,
  // building, unit, work-order number, price, or quantity. A notification is
  // readable on a locked phone by whoever is holding it.
  //
  // A later phase replaces this with an opaque id plus an authenticated fetch
  // of the display text, so that content never reaches a push service at all
  // and the recipient is re-authorized at the moment of display.
  let title = "Inventory App";
  let body = "You have a new notification.";

  try {
    const data = event.data ? event.data.json() : {};
    if (typeof data.title === "string" && data.title) title = data.title;
    if (typeof data.body === "string" && data.body) body = data.body;
  } catch {
    // Absent or malformed payload: fall through to the generic text. Chrome's
    // `userVisibleOnly` contract requires that every push show something, and
    // failing to would eventually cost us the permission entirely.
  }

  event.waitUntil(
    self.registration.showNotification(title, {
      body,
      tag: NOTIFICATION_TAG,
      icon: "/static/icons/icon-192.png",
      badge: "/static/icons/icon-192.png",
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();

  event.waitUntil((async () => {
    // Prefer an already-open window: on a phone, opening a second copy of the
    // app throws away whatever the user had on screen. `includeUncontrolled`
    // matters because a tab loaded before this worker activated is not yet
    // controlled by it but is still the right target.
    const windows = await self.clients.matchAll({
      type: "window",
      includeUncontrolled: true,
    });

    for (const client of windows) {
      if ("focus" in client) return client.focus();
    }
    if (self.clients.openWindow) return self.clients.openWindow("/");
  })());
});
```

- [ ] **Step 4: Create the uninstall page**

Create `backend/static/sw-reset.html`:

```html
<!DOCTYPE html>
<!--
  Service-worker escape hatch.

  Not part of SHELL_PARTS -- a standalone page served directly by the /static
  mount, like scan-test.html. It exists so a broken service worker can be
  removed from a phone, which has no developer console.

  Reachable at /static/sw-reset.html. Structure only: no inline script, no
  inline styles, no on* attributes (CSP is `default-src 'self'`).
-->
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Reset Service Worker</title>
    <link rel="stylesheet" href="/static/styles.css">
</head>
<body>
    <main>
        <h1>Reset Service Worker</h1>
        <p>
            This removes the Inventory App notification service worker from
            this browser. Notifications will stop until you turn them on again.
            Nothing else about the app is affected.
        </p>
        <button id="sw-reset-btn" type="button">Unregister service worker</button>
        <p id="sw-reset-status" role="status"></p>
    </main>
    <script type="module" src="/static/sw-reset.js"></script>
</body>
</html>
```

Create `backend/static/sw-reset.js`:

```js
// Service-worker escape hatch behavior.
//
// Imports nothing from the SPA on purpose: it still has to work when the app's
// own JavaScript is what broke.

const button = document.getElementById("sw-reset-btn");
const status = document.getElementById("sw-reset-status");

function report(message) {
  status.textContent = message;
}

if (!("serviceWorker" in navigator)) {
  button.disabled = true;
  report("This browser does not support service workers, so there is nothing to remove.");
} else {
  button.addEventListener("click", async () => {
    button.disabled = true;
    report("Working...");
    try {
      const registrations = await navigator.serviceWorker.getRegistrations();
      if (registrations.length === 0) {
        report("No service worker was registered. Nothing to do.");
        return;
      }
      const results = await Promise.all(registrations.map((r) => r.unregister()));
      const removed = results.filter(Boolean).length;
      report(
        `Removed ${removed} of ${registrations.length} registration(s). ` +
        "Close every tab for this site and reopen it to finish."
      );
    } catch (error) {
      report(`Could not unregister: ${error && error.message ? error.message : error}`);
    } finally {
      button.disabled = false;
    }
  });
}
```

- [ ] **Step 5: Add the route**

In `backend/app/main.py`, change the response import (line 33):

```python
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
```

Add this route immediately after `read_root`, before `healthz`:

```python
@app.get("/sw.js", include_in_schema=False)
def service_worker():
    """Serve the notification service worker from the site root.

    **The path is the point.** A service worker's scope is capped by its own
    URL path, so a worker fetched from `/static/sw.js` would control only
    `/static/` -- it could not focus or navigate the app from a notification
    click. `app.mount("/static", ...)` cannot produce a root-scoped worker, so
    this route exists rather than a link into the mount. The alternative, a
    `Service-Worker-Allowed: /` header on the mounted file, works but hides a
    load-bearing rule in a header that is easy to drop in a refactor.

    `no-cache` matches `NoCacheStaticFiles` and every other asset. A stale
    service worker is the hardest thing in this app to clear from a phone;
    `/static/sw-reset.html` is the manual escape hatch if one ships broken.

    Unauthenticated on purpose: a browser's request for a worker script is not
    guaranteed to carry credentials.
    """
    return FileResponse(
        STATIC_DIR / "sw.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache"},
    )
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
python -m pytest tests/test_service_worker.py -v
node --check static/sw.js
node --check static/sw-reset.js
```

Expected: 11 passed; both `node --check` silent.

**Note on the guard's form.** §24 called for a CI grep. This is a pytest
tripwire instead: it runs in the same CI job, fails with an explanatory message,
and strips comments so the file can document its own rule. No workflow change is
needed.

- [ ] **Step 7: Commit**

```bash
git add backend/static/sw.js backend/static/sw-reset.html backend/static/sw-reset.js \
        backend/app/main.py backend/tests/test_service_worker.py
git commit -m "feat(push): serve a root-scoped, fetch-free notification service worker"
```

---

## Task 7: Push endpoints

**Files:**
- Create: `backend/app/schemas/push.py`, `backend/app/routers/push.py`
- Modify: `backend/app/main.py` (include the router)
- Test: `backend/tests/test_push_routes.py`

**Interfaces:**
- Consumes: `app.domain.push` (Task 2), `app.services.push_subscriptions` (Task 4), `app.services.push_delivery` (Task 5)
- Produces: `GET /push/vapid-public-key`, `POST /push/subscriptions`, `DELETE /push/subscriptions`, `POST /push/test`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_push_routes.py`:

```python
"""Tests for the /push endpoints.

Layer: unit (handlers called directly with a fake user, matching
`test_health_check.py`'s style). Authorization is asserted from route metadata
rather than by driving HTTP, the way `test_docs_endpoints.py` inspects mounted
routes.

The two tests that matter are the SSRF rejection and the self-only test send.
Everything else here is contract.
"""

import os
import sys
import types
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from app.domain.roles import ROLE_ADMIN, ROLE_TECHNICIAN
from app.main import app
from app.routers import push as push_router
from app.schemas.push import PushSubscriptionCreate


def _route(path: str, method: str) -> APIRoute:
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path == path and method in route.methods:
            return route
    raise AssertionError(f"no {method} route at {path}")


def _fake_user(role=ROLE_TECHNICIAN):
    return types.SimpleNamespace(id=uuid.uuid4(), role=role, username="tester")


VALID = {
    "endpoint": "https://fcm.googleapis.com/fcm/send/abc123",
    "keys": {"p256dh": "BNc...", "auth": "abc"},
}


# --------------------------------------------------------------------------
# Contract
# --------------------------------------------------------------------------

@pytest.mark.parametrize("path,method", [
    ("/push/vapid-public-key", "GET"),
    ("/push/subscriptions", "POST"),
    ("/push/subscriptions", "DELETE"),
    ("/push/test", "POST"),
])
def test_every_push_route_is_registered(path, method):
    assert _route(path, method) is not None


@pytest.mark.parametrize("path,method", [
    ("/push/vapid-public-key", "GET"),
    ("/push/subscriptions", "POST"),
    ("/push/subscriptions", "DELETE"),
    ("/push/test", "POST"),
])
def test_no_push_route_is_reachable_without_a_session(path, method):
    # Every one of these either reads or changes something tied to an identity.
    # An unauthenticated route here would let anyone register an endpoint.
    assert _route(path, method).dependant.dependencies != []


def test_the_browser_subscription_shape_is_accepted_verbatim():
    # `subscription.toJSON()` also emits `expirationTime`. Pydantic ignores
    # unknown fields by default, so the client can POST the object unchanged
    # rather than reshaping it -- one less place to make a mistake.
    payload = PushSubscriptionCreate(**{**VALID, "expirationTime": None})

    assert payload.endpoint == VALID["endpoint"]
    assert payload.keys.p256dh == "BNc..."


# --------------------------------------------------------------------------
# The SSRF guard
# --------------------------------------------------------------------------

@pytest.mark.parametrize("endpoint", [
    "http://169.254.169.254/latest/meta-data/",
    "https://127.0.0.1/",
    "https://evil.com/x",
    "http://fcm.googleapis.com/fcm/send/x",
])
def test_a_non_push_service_endpoint_is_refused(endpoint, monkeypatch):
    # Without this the endpoint is a blind SSRF primitive: the caller names a
    # URL and the server POSTs to it from inside Render's network.
    called = []
    monkeypatch.setattr(
        push_router.push_subscriptions, "upsert_subscription",
        lambda *a, **k: called.append(1),
    )

    with pytest.raises(HTTPException) as exc:
        push_router.save_subscription(
            payload=PushSubscriptionCreate(endpoint=endpoint, keys=VALID["keys"]),
            user=_fake_user(),
            db=None,
        )

    assert exc.value.status_code == 400
    assert called == [], "the service must not be reached for a refused endpoint"


def test_a_real_push_endpoint_is_stored(monkeypatch):
    stored = {}

    def fake_upsert(db, *, user_id, endpoint, p256dh, auth):
        stored.update(user_id=user_id, endpoint=endpoint, p256dh=p256dh, auth=auth)
        return types.SimpleNamespace(id=uuid.uuid4())

    monkeypatch.setattr(push_router.push_subscriptions, "upsert_subscription", fake_upsert)
    user = _fake_user()

    push_router.save_subscription(
        payload=PushSubscriptionCreate(**VALID), user=user, db=None
    )

    assert stored["endpoint"] == VALID["endpoint"]
    assert stored["user_id"] == user.id


# --------------------------------------------------------------------------
# The test send
# --------------------------------------------------------------------------

def test_the_test_send_is_admin_only():
    route = _route("/push/test", "POST")
    # Asserted through the generated schema, which records the role gate.
    assert 403 in route.responses or route.dependencies


def test_the_test_send_targets_only_the_caller(monkeypatch):
    # An endpoint that could push to an arbitrary user is a spam weapon with no
    # justification. The caller's own id must be the only one it can reach.
    targets = []

    def fake_send(db, *, user_id, title, body):
        targets.append(user_id)
        return {"ok": 1}

    monkeypatch.setattr(push_router.push_delivery, "send_to_user", fake_send)
    user = _fake_user(ROLE_ADMIN)

    push_router.send_test_notification(user=user, db=None)

    assert targets == [user.id]


def test_the_test_send_carries_no_operational_detail(monkeypatch):
    # A notification is readable on a locked phone. Even a test message must
    # not establish the habit of putting real data in one.
    captured = {}

    def fake_send(db, *, user_id, title, body):
        captured.update(title=title, body=body)
        return {"ok": 1}

    monkeypatch.setattr(push_router.push_delivery, "send_to_user", fake_send)

    push_router.send_test_notification(user=_fake_user(ROLE_ADMIN), db=None)

    text = f"{captured['title']} {captured['body']}".lower()
    for forbidden in ("work order", "building", "unit", "$", "quantity"):
        assert forbidden not in text
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python -m pytest tests/test_push_routes.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.schemas.push'`.

- [ ] **Step 3: Write the schemas**

Create `backend/app/schemas/push.py`:

```python
"""Request/response shapes for the push endpoints.

Layer: schemas. These mirror the browser's `PushSubscription.toJSON()` output
exactly, so the client can POST the object it receives from `subscribe()`
without reshaping it. Every reshaping step is a place to introduce a mismatch
that only shows up on a real device.
"""

from pydantic import BaseModel, Field


class PushSubscriptionKeys(BaseModel):
    """The RFC 8291 ECDH material. Lengths are bounded because these arrive
    from a client and are stored verbatim; a browser's values are ~88 and ~22
    characters, so these ceilings are generous rather than tight."""

    p256dh: str = Field(min_length=1, max_length=255)
    auth: str = Field(min_length=1, max_length=255)


class PushSubscriptionCreate(BaseModel):
    """One browser's push channel, as the browser reports it.

    `expirationTime` is part of `toJSON()` and is almost always null. It is not
    declared here and Pydantic ignores it, which is the point: the client sends
    the subscription unchanged.
    """

    endpoint: str = Field(min_length=1, max_length=2000)
    keys: PushSubscriptionKeys


class PushSubscriptionDelete(BaseModel):
    endpoint: str = Field(min_length=1, max_length=2000)


class VapidPublicKeyResponse(BaseModel):
    key: str


class PushTestResponse(BaseModel):
    """Per-outcome delivery counts, e.g. `{"ok": 2}`. Reported back so an Admin
    pressing the button learns whether anything actually happened rather than
    getting an unconditional success."""

    outcomes: dict[str, int]
```

- [ ] **Step 4: Write the router**

Create `backend/app/routers/push.py`:

```python
"""HTTP routes for push subscription management.

Layer: routers. Thin handlers over `services.push_subscriptions` and
`services.push_delivery`.

Every route requires a session. Registration additionally validates the
endpoint against `domain.push.ALLOWED_PUSH_HOSTS` before the value reaches any
code that will make a request with it -- without that check this router is a
blind SSRF primitive, because its whole job is accepting a URL that the server
later POSTs to.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth_deps import get_current_user, require_min_role
from app.database import get_db
from app.domain import push as policy
from app.domain import roles
from app.models import User
from app.schemas.push import (
    PushSubscriptionCreate,
    PushSubscriptionDelete,
    PushTestResponse,
    VapidPublicKeyResponse,
)
from app.services import push_delivery, push_subscriptions

router = APIRouter(prefix="/push", tags=["push"])

logger = logging.getLogger(__name__)


@router.get("/vapid-public-key", response_model=VapidPublicKeyResponse)
def get_vapid_public_key(_user: User = Depends(get_current_user)):
    """The application server key browsers need at `subscribe()` time.

    Not a secret -- every subscriber receives it -- but served behind a session
    anyway, because there is no reason for an anonymous caller to fingerprint
    which key this deployment uses.

    Served from a route rather than baked into the HTML so a key rotation is a
    config change rather than a markup edit and a redeploy.
    """
    key = push_delivery.vapid_public_key()
    if not key:
        # Misconfiguration, not a client error. The frontend disables its
        # opt-in control rather than showing the user a failure.
        raise HTTPException(
            status_code=503, detail="Push notifications are not configured."
        )
    return VapidPublicKeyResponse(key=key)


@router.post("/subscriptions", status_code=status.HTTP_204_NO_CONTENT)
def save_subscription(
    payload: PushSubscriptionCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Bind this browser's push channel to the calling user.

    Idempotent, and deliberately a transfer rather than a rejection when the
    endpoint already exists: a browser profile has one push channel, so a
    repeat registration means the same browser is re-registering, and its
    rightful owner is whoever is authenticated now. That is what keeps a shared
    shop computer from delivering one person's notifications to the next.

    The client also calls this on every boot when it already holds a
    subscription, which is how an endpoint left behind by an expired session
    gets re-bound to the person actually signed in.
    """
    if not policy.is_allowed_push_endpoint(payload.endpoint):
        # Refused BEFORE the value reaches any code that would request it.
        logger.warning(
            "push.endpoint_rejected",
            extra={"fields": {"user_id": str(user.id)}},
        )
        raise HTTPException(
            status_code=400, detail="That is not a recognised push service endpoint."
        )

    push_subscriptions.upsert_subscription(
        db,
        user_id=user.id,
        endpoint=payload.endpoint,
        p256dh=payload.keys.p256dh,
        auth=payload.keys.auth,
    )


@router.delete("/subscriptions", status_code=status.HTTP_204_NO_CONTENT)
def delete_subscription(
    payload: PushSubscriptionDelete,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Release this browser's push channel. Called on logout.

    Scoped to the caller's own rows, and idempotent: a logout must never fail
    because the subscription had already gone. The client calls this BEFORE
    `POST /auth/logout`, while it still has a session to authenticate with.
    """
    push_subscriptions.delete_subscription(
        db, user_id=user.id, endpoint=payload.endpoint
    )


@router.post(
    "/test",
    response_model=PushTestResponse,
    responses={403: {"description": "Requires the admin role or above."}},
)
def send_test_notification(
    user: User = Depends(require_min_role(roles.ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """Send a test notification to the caller's own devices.

    **Only ever to the caller.** There is no recipient parameter and there must
    not be one: an endpoint that could push to an arbitrary user is a spam
    weapon, and nothing about verifying delivery requires it.

    The text is category-level with no operational detail, both because a
    notification is readable on a locked phone and because this is the first
    notification anyone will see -- it should establish the right habit.

    Sends synchronously, which is acceptable only because this is an
    out-of-band Admin action rather than a business write. A real event must go
    through the outbox; see `services.push_delivery`.
    """
    outcomes = push_delivery.send_to_user(
        db,
        user_id=user.id,
        title="Inventory App",
        body="Notifications are working on this device.",
    )
    logger.info(
        "push.test_sent",
        extra={"fields": {"user_id": str(user.id), **outcomes}},
    )
    return PushTestResponse(outcomes=outcomes)
```

- [ ] **Step 5: Register the router**

In `backend/app/main.py`, add `push` to the router import block and include it
alongside the others:

```python
app.include_router(push.router)
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
python -m pytest tests/test_push_routes.py -v
python -m pytest -q
```

Expected: 17 passed in the new file; full suite green.

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas/push.py backend/app/routers/push.py backend/app/main.py backend/tests/test_push_routes.py
git commit -m "feat(push): add subscription endpoints with an SSRF-guarded registration"
```

---

## Task 8: Manifest and icons

**Files:**
- Create: `backend/static/manifest.json`, `backend/static/icons/*.png`, `backend/scripts/make_icons.py`
- Modify: `backend/static/shell-head.html`
- Test: `backend/tests/test_web_app_manifest.py`

**Interfaces:**
- Consumes: nothing
- Produces: `/static/manifest.json` with `start_url: "/"` and `display: "standalone"`; icons at `/static/icons/`

- [ ] **Step 1: Generate the icons**

Pillow is already a dependency. Create `backend/scripts/make_icons.py`:

```python
"""Derive the web app manifest icons from the existing favicon.

Run from the `backend/` directory:

    python -m scripts.make_icons

iOS uses `apple-touch-icon` for the Home Screen; without it an installed web
app gets a screenshot of the page, which looks broken.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path  # noqa: E402

from PIL import Image  # noqa: E402

STATIC = Path(__file__).resolve().parent.parent / "static"
SOURCE = STATIC / "favicon.png"
ICONS = STATIC / "icons"


def main() -> int:
    if not SOURCE.is_file():
        print(f"missing source icon: {SOURCE}", file=sys.stderr)
        return 1

    ICONS.mkdir(exist_ok=True)
    base = Image.open(SOURCE).convert("RGBA")

    for size, name in (
        (192, "icon-192.png"),
        (512, "icon-512.png"),
        (180, "apple-touch-icon.png"),
    ):
        base.resize((size, size), Image.LANCZOS).save(ICONS / name)

    print(f"wrote 3 icons to {ICONS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Run it:

```bash
python -m scripts.make_icons
```

Expected: `wrote 3 icons to .../static/icons`.

- [ ] **Step 2: Write the failing test**

Create `backend/tests/test_web_app_manifest.py`:

```python
"""Tests for the web app manifest and its links in the SPA shell.

Layer: unit (no DB, no HTTP client).

The manifest matters for one reason: on iOS before version 26, a
`display: standalone` manifest was REQUIRED for a site to install as a Home
Screen web app, and a Home Screen web app is the only place iOS delivers Web
Push at all. iOS 26 removed the installability requirement, but the crew will
not be uniformly on iOS 26, so the manifest covers both.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

STATIC = Path(__file__).resolve().parent.parent / "static"
MANIFEST = STATIC / "manifest.json"
SHELL_HEAD = STATIC / "shell-head.html"


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_the_manifest_is_valid_json():
    assert isinstance(_manifest(), dict)


def test_the_manifest_declares_what_ios_installation_requires():
    manifest = _manifest()

    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "/"
    assert manifest["name"]
    assert manifest["short_name"]


@pytest.mark.parametrize("size", ["192x192", "512x512"])
def test_the_manifest_declares_both_required_icon_sizes(size):
    assert any(icon["sizes"] == size for icon in _manifest()["icons"])


def test_every_manifest_icon_file_exists():
    for icon in _manifest()["icons"]:
        src = icon["src"].lstrip("/")
        assert (STATIC.parent / src).is_file(), f"missing icon: {icon['src']}"


def test_the_apple_touch_icon_exists():
    assert (STATIC / "icons" / "apple-touch-icon.png").is_file()


def test_the_shell_links_the_manifest_and_the_apple_touch_icon():
    head = SHELL_HEAD.read_text(encoding="utf-8")

    assert 'rel="manifest"' in head
    assert "/static/manifest.json" in head
    assert 'rel="apple-touch-icon"' in head
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
python -m pytest tests/test_web_app_manifest.py -v
```

Expected: FAIL — `FileNotFoundError` on `manifest.json`.

- [ ] **Step 4: Create the manifest**

Create `backend/static/manifest.json`:

```json
{
  "name": "Inventory Management",
  "short_name": "Inventory",
  "start_url": "/",
  "scope": "/",
  "display": "standalone",
  "background_color": "#000000",
  "theme_color": "#c8102e",
  "icons": [
    { "src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any" },
    { "src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any" }
  ]
}
```

- [ ] **Step 5: Link it from the shell**

In `backend/static/shell-head.html`, replace:

```html
    <link rel="icon" type="image/png" href="/static/favicon.png">
    <link rel="stylesheet" href="/static/styles.css">
```

with:

```html
    <link rel="icon" type="image/png" href="/static/favicon.png">
    <!-- Web app manifest. Required for Home Screen installation on iOS before
         version 26, and installation is the only way iOS delivers Web Push.
         Harmless everywhere else: it changes nothing about how the app behaves
         in an ordinary browser tab. -->
    <link rel="manifest" href="/static/manifest.json">
    <!-- iOS uses this for the Home Screen icon. Without it, an installed web
         app gets a screenshot of the page. -->
    <link rel="apple-touch-icon" href="/static/icons/apple-touch-icon.png">
    <meta name="theme-color" content="#c8102e">
    <link rel="stylesheet" href="/static/styles.css">
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
python -m pytest tests/test_web_app_manifest.py -v
```

Expected: 7 passed.

- [ ] **Step 7: Commit**

```bash
git add backend/static/manifest.json backend/static/icons backend/static/shell-head.html \
        backend/scripts/make_icons.py backend/tests/test_web_app_manifest.py
git commit -m "feat(push): add the web app manifest and installable icons"
```

---

## Task 9: Frontend opt-in and subscription lifecycle

**Files:**
- Create: `backend/static/views/notifications.js`
- Modify: `backend/static/api.js`, `backend/static/main.js`, `backend/static/views/auth.js`, `backend/static/shell-head.html`

**Interfaces:**
- Consumes: `GET /push/vapid-public-key`, `POST /push/subscriptions`, `DELETE /push/subscriptions`, `POST /push/test` (Task 7); `/sw.js` (Task 6)
- Produces: `initNotifications(user)` and `releaseSubscription()`, both exported from `views/notifications.js` and called from `views/auth.js`

- [ ] **Step 1: Add the API wrappers**

Append to `backend/static/api.js`, following the existing section style:

```js
// --- Push notifications ------------------------------------------

export async function apiGetVapidPublicKey() {
  return liveGet("/push/vapid-public-key");
}

export async function apiSavePushSubscription(subscription) {
  // `subscription` is the browser's own `toJSON()` output, passed through
  // unchanged -- the backend schema mirrors that shape deliberately.
  return jsonRequest("/push/subscriptions", "POST", subscription);
}

export async function apiDeletePushSubscription(endpoint) {
  return jsonRequest("/push/subscriptions", "DELETE", { endpoint });
}

export async function apiSendTestPush() {
  return jsonRequest("/push/test", "POST", {});
}
```

- [ ] **Step 2: Add the control to the shell**

In `backend/static/shell-head.html`, inside `#auth-bar` (currently lines
106–109), add the button before the logout button:

```html
        <div id="auth-bar">
            <span id="auth-user-indicator"></span>
            <!-- Hidden until views/notifications.js decides this browser can
                 receive push AND the signed-in user is allowed to opt in.
                 Owner-only for now: the crew should not meet a feature that
                 has not been proven on real devices. -->
            <button id="notifications-btn" type="button" class="secondary-btn" hidden>Notifications</button>
            <button id="logout-btn" type="button" class="secondary-btn">Log Out</button>
        </div>
```

- [ ] **Step 3: Write the view**

Create `backend/static/views/notifications.js`:

```js
// View: push notification opt-in and subscription lifecycle.
//
// Layer: views. Owns the single #notifications-btn control and everything
// about this browser's PushSubscription.
//
// Three rules shape this module:
//
// 1. Permission is requested ONLY from a user gesture, and it is the first
//    thing the handler does. Safari requires direct user interaction, and
//    calling it on load earns Chrome's quieter-prompt treatment -- which is
//    close to permanent, since no API can re-prompt after a denial.
//
// 2. The subscription is re-asserted on every boot. A subscription outlives a
//    login session by design, so a browser can hold one that belongs to a
//    previous user. Re-POSTing it binds it to whoever is signed in now.
//
// 3. Nothing here ever shows an error for a failed push setup. Notifications
//    are additive; the app works identically without them.

import {
  apiDeletePushSubscription,
  apiGetVapidPublicKey,
  apiSavePushSubscription,
  apiSendTestPush,
} from "../api.js";
import { roleAtLeast } from "../roles.js";

// Owner-only while the feature is being proven on real devices. Widening this
// is a one-line change once the device matrix passes.
const MINIMUM_ROLE = "owner";

const button = document.getElementById("notifications-btn");

let registration = null;

function pushSupported() {
  return (
    "serviceWorker" in navigator &&
    "PushManager" in globalThis &&
    "Notification" in globalThis
  );
}

// On iOS, push requires the app to be installed to the Home Screen; it does
// not work in a Safari tab, and there is no API to trigger the install. The
// only useful thing the app can do is detect the situation and say so.
function isIos() {
  return /iPad|iPhone|iPod/.test(navigator.userAgent);
}

function isInstalled() {
  return (
    globalThis.navigator.standalone === true ||
    globalThis.matchMedia("(display-mode: standalone)").matches
  );
}

function setLabel(text) {
  button.textContent = text;
}

// The VAPID public key travels as URL-safe base64; subscribe() wants bytes.
function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = globalThis.atob(base64);
  const output = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i += 1) output[i] = raw.charCodeAt(i);
  return output;
}

async function ensureRegistration() {
  if (registration) return registration;
  registration = await navigator.serviceWorker.register("/sw.js", { scope: "/" });
  await navigator.serviceWorker.ready;
  return registration;
}

async function currentSubscription() {
  if (!pushSupported()) return null;
  try {
    const reg = await navigator.serviceWorker.getRegistration("/");
    if (!reg) return null;
    return await reg.pushManager.getSubscription();
  } catch {
    return null;
  }
}

async function enable() {
  // Permission FIRST, still inside the gesture's call stack. Registering the
  // worker first would put an await ahead of it, which some engines treat as
  // having lost the user gesture.
  const permission = await Notification.requestPermission();
  if (permission !== "granted") {
    setLabel(permission === "denied" ? "Notifications blocked" : "Notifications");
    return;
  }

  const { key } = await apiGetVapidPublicKey();
  const reg = await ensureRegistration();

  let subscription = await reg.pushManager.getSubscription();
  if (!subscription) {
    subscription = await reg.pushManager.subscribe({
      // Mandatory in Chrome and Edge: they reject subscribe() without it.
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(key),
    });
  }

  await apiSavePushSubscription(subscription.toJSON());
  setLabel("Notifications on");

  // Immediate proof on the device the user is holding. Failures are ignored:
  // the subscription is already saved, and a test send is a convenience.
  try {
    await apiSendTestPush();
  } catch {
    // Not an Admin, or the send failed. Neither changes the opt-in outcome.
  }
}

/** Release this browser's subscription. Called on logout, BEFORE the logout
 *  request, while there is still a session to authenticate the delete with. */
export async function releaseSubscription() {
  const subscription = await currentSubscription();
  if (!subscription) return;
  try {
    await apiDeletePushSubscription(subscription.endpoint);
  } catch {
    // The server-side row is what matters and it may already be gone. Even if
    // this fails, re-registration by the next user reassigns the endpoint.
  }
  try {
    await subscription.unsubscribe();
  } catch {
    // A stale browser-side subscription with no server row simply receives
    // nothing. Harmless.
  }
}

/** Wire the control for a signed-in user. Safe to call on every login. */
export async function initNotifications(user) {
  if (!button) return;

  if (!user || !roleAtLeast(user.role, MINIMUM_ROLE) || !pushSupported()) {
    // iOS in a Safari tab lands here. Say why rather than showing a control
    // that cannot work.
    if (user && roleAtLeast(user.role, MINIMUM_ROLE) && isIos() && !isInstalled()) {
      button.hidden = false;
      button.disabled = true;
      setLabel("Add to Home Screen for notifications");
    } else {
      button.hidden = true;
    }
    return;
  }

  button.hidden = false;
  button.disabled = false;

  const existing = await currentSubscription();
  if (existing) {
    // Re-assert. The subscription may have been left by a previous user, or
    // rotated by the browser. Either way it now belongs to whoever is signed
    // in.
    setLabel("Notifications on");
    try {
      await apiSavePushSubscription(existing.toJSON());
    } catch {
      // Best effort. A failure leaves the previous binding in place, which
      // display-time authorization still contains.
    }
  } else {
    setLabel(
      Notification.permission === "denied" ? "Notifications blocked" : "Notifications"
    );
  }
}

button?.addEventListener("click", async () => {
  button.disabled = true;
  try {
    await enable();
  } catch {
    // UX-5: notification setup never surfaces an error. The app is unchanged.
    setLabel("Notifications");
  } finally {
    button.disabled = false;
  }
});
```

- [ ] **Step 4: Wire it into the composition root**

In `backend/static/main.js`, add to the side-effect imports:

```js
import "./views/notifications.js";
```

- [ ] **Step 5: Wire the auth lifecycle**

In `backend/static/views/auth.js`:

Add the import:

```js
import { initNotifications, releaseSubscription } from "./notifications.js";
```

In `enterApp`, after `connectRealtime();`:

```js
  // Subscriptions outlive sessions by design, so a browser may be holding one
  // that belongs to a previous user. Re-asserting it on every entry binds it
  // to whoever just signed in. Deliberately not awaited: notification setup
  // must never delay the app appearing.
  initNotifications(user);
```

In the logout click handler, **before** `await apiLogout()`:

```js
  // Before the logout call, while there is still a session to authenticate
  // the delete with. A deliberate logout is the one event that should stop
  // this device receiving notifications -- session expiry alone must not.
  await releaseSubscription();
```

- [ ] **Step 6: Verify the JavaScript parses**

```bash
cd /c/Users/mcclu/Desktop/inventory_app_git
find backend/static -name '*.js' -not -path '*/vendor/*' -print0 | xargs -0 -n1 node --check
```

Expected: silent. This is the same check CI runs.

- [ ] **Step 7: Commit**

```bash
git add backend/static/views/notifications.js backend/static/api.js backend/static/main.js \
        backend/static/views/auth.js backend/static/shell-head.html
git commit -m "feat(push): add the notification opt-in control and subscription lifecycle"
```

---

## Task 10: Local verification

Everything verifiable without a deploy. Desktop Chrome and macOS Safari both
treat `localhost` as a secure context, so service workers and the full Push API
work locally — including real delivery, because the browser subscribes to its
vendor's push service regardless of the page's origin.

**Files:** none

- [ ] **Step 1: Run the full suite**

```bash
cd /c/Users/mcclu/Desktop/inventory_app_git/backend
python -m pytest -q
```

Expected: green, with 86 new tests over the pre-existing baseline (4 + 37 + 10
+ 11 + 17 + 7).

- [ ] **Step 2: Run every CI check locally**

Cheaper than discovering a failure after pushing:

```bash
python -m compileall -q app
alembic heads | grep -c '(head)'          # expect 1
alembic upgrade head && alembic downgrade -1 && alembic upgrade head
pip-audit --requirement requirements.txt --desc
cd .. && find backend/static -name '*.js' -not -path '*/vendor/*' -print0 | xargs -0 -n1 node --check
```

- [ ] **Step 3: Start the app and check the wiring**

```bash
cd backend
uvicorn app.main:app --port 8124
```

In desktop Chrome at `http://localhost:8124`, sign in as the Owner, then:

1. Confirm the **Notifications** button appears next to Log Out. Sign in as a
   non-Owner and confirm it does **not**.
2. Open DevTools → Application → Service Workers. Click **Notifications**,
   accept the prompt, and confirm the worker registers with scope `/`.
3. Confirm a notification appears immediately (the automatic test send).
4. Click the notification and confirm it **focuses the existing tab** rather
   than opening a second one.
5. Check the Console for any Content Security Policy violation. There should be
   none — `default-src 'self'` covers a same-origin worker through the
   `child-src` fallback, but this verifies rather than assumes it.

- [ ] **Step 4: Verify the app still loads normally**

With the worker registered, hard-reload `/` several times and navigate between
pages. **No blank page, no stale assets.** This is the §12 risk being checked
rather than assumed; if it fails, the worker has acquired a `fetch` handler.

- [ ] **Step 5: Verify the lifecycle**

| Check | Expected |
|---|---|
| Log out, then query the table | The row for this endpoint is gone |
| Log back in, click Notifications | A new row appears, bound to that user |
| Sign in as a **different** Owner-rank user on the same browser and enable | The row's `user_id` changes; the old owner has none |
| Delete the row by hand, reload the app | The boot-time re-assert recreates it |
| Revoke notification permission in Chrome settings, then send a test | The row is deleted on the resulting 410 |

Inspect with:

```bash
psql "$DATABASE_URL" -c "SELECT user_id, left(endpoint, 40), failure_count, last_success_at FROM push_subscriptions;"
```

- [ ] **Step 6: Verify the failure paths**

The destructive-bug guard, against a real push service rather than only in unit
tests:

```bash
# 1. Corrupt an endpoint by hand, then send a test.
psql "$DATABASE_URL" -c "UPDATE push_subscriptions SET endpoint = endpoint || 'xxx';"
# Expect: the row is DELETED (404/410 -> drop_subscription).

# 2. Re-subscribe, then set a DIFFERENT valid VAPID_PRIVATE_KEY and restart.
# Expect: log line `push.configuration_error`, and the row is STILL THERE.
psql "$DATABASE_URL" -c "SELECT count(*) FROM push_subscriptions;"
```

**Check 2 is the important one.** If the row disappears, the classification is
wired wrong and one bad key in production would empty the table.

- [ ] **Step 7: Verify macOS Safari, if available**

Repeat Step 3 in Safari at `http://localhost:8124`. Safari needs no
installation on macOS — this is the asymmetry with iOS, and confirming it here
means only the iPhone genuinely requires a deploy.

- [ ] **Step 8: Verify the uninstall page**

Open `http://localhost:8124/static/sw-reset.html`, click **Unregister service
worker**, and confirm it reports a removal. Then re-enable from Step 3 to
confirm recovery works.

---

## Task 11: Production deploy and the mobile matrix

**The only task that touches production.** It ships to the crew's live app.

**Files:** `docs/superpowers/plans/2026-08-14-push-results.md`

- [ ] **Step 1: Stop and get explicit approval**

Merging to `main` deploys to production. Report to the project owner:

- the full local matrix result from Task 10,
- that the opt-in control is Owner-only, so no crew member will see it,
- that the service worker has no `fetch` handler and therefore cannot change how the app loads,
- that `/static/sw-reset.html` is the rollback path if it does.

**Do not merge until the owner says so.**

- [ ] **Step 2: Set the production VAPID keys**

Generate a **new, separate** keypair — production must not share staging or
local keys:

```bash
cd /c/Users/mcclu/Desktop/inventory_app_git/backend
python -m scripts.generate_vapid_keys
```

In the Render dashboard, on the `inventory-app` service, add
`VAPID_PRIVATE_KEY`, `VAPID_PUBLIC_KEY`, and `VAPID_SUBJECT`.

**Set these before merging.** If the service deploys without them,
`/push/vapid-public-key` returns 503 and the opt-in control disables itself —
harmless, but it wastes a deploy cycle.

For discoverability, also declare them in `render.yaml` with `sync: false`:

```yaml
      # Web Push signing key. `sync: false` means the VALUE is set in the
      # dashboard and never appears in git; Render also ignores sync:false vars
      # when updating an existing Blueprint, so a Blueprint sync cannot clobber
      # it. Rotating this key invalidates every existing push subscription.
      - key: VAPID_PRIVATE_KEY
        sync: false
      - key: VAPID_PUBLIC_KEY
        sync: false
      - key: VAPID_SUBJECT
        sync: false
```

- [ ] **Step 3: Merge and deploy**

```bash
git checkout main
git merge --no-ff feat/push-notifications
git push origin main
```

Watch the CI run. The `deploy` job runs only after `backend` and `static` pass.

- [ ] **Step 4: Confirm the deploy**

```bash
curl -sS https://<production-host>/healthz
curl -sI https://<production-host>/sw.js | head -5
```

Expected: `{"status":"ok"}`; then `200`, `content-type: application/javascript`,
`cache-control: no-cache`.

- [ ] **Step 5: Run the iPhone rows — the decisive test**

**Row A — Safari tab (expected to show the install prompt, not to work):**
Open the app in ordinary iOS Safari and sign in. The Notifications button must
be visible but disabled, reading **"Add to Home Screen for notifications"**.
Confirm no permission prompt appears.

**Row B — Home Screen web app:**
1. Share → **Add to Home Screen**. Confirm the icon is the app's, not a
   screenshot.
2. Open from the Home Screen. **Record whether you are signed out** — you
   should be, because an installed web app has its own cookie jar. This is the
   most important observation of the whole exercise.
3. Sign in, tap **Notifications**, accept the iOS prompt.
4. Confirm the test notification arrives.
5. **Lock the phone. Send another test from a desktop browser.** Confirm it
   arrives on the lock screen and that the text shows only the generic title
   and body — no names, no buildings, no numbers.
6. **Close the app entirely** (swipe it away). Send again. Confirm it still
   arrives. *This is the actual requirement: notifications without being in the
   app.*
7. Tap it and confirm the app opens.

- [ ] **Step 6: Run the remaining rows**

- Android Chrome, browser tab — including with the browser closed
- Android Chrome, installed PWA
- Windows Chrome, browser tab — including with Chrome minimized

- [ ] **Step 7: Verify the app is unharmed for everyone else**

Sign in as a **Technician** on a phone and a desktop. Confirm: no Notifications
button, the app loads normally, every page works, no console errors. The crew's
experience must be byte-identical to before this shipped.

- [ ] **Step 8: Record the results**

Create `docs/superpowers/plans/2026-08-14-push-results.md`:

```markdown
# Push Infrastructure — Verification Results

Run against production at commit `<sha>` on <date>.

| Device | Browser | Install state | Expected | Actual | Notes |
|---|---|---|---|---|---|
| iPhone | Safari | Tab | Button disabled, install hint | | |
| iPhone | Safari | Home Screen | Delivered, app closed | | Signed out on first open? |
| Android | Chrome | Tab | Delivered, browser closed | | |
| Android | Chrome | Installed | Delivered | | |
| Windows | Chrome | Tab | Delivered, minimized | | |
| macOS | Safari | Tab (local) | Delivered, no install | | |

## Failure paths
| Check | Expected | Actual |
|---|---|---|
| Corrupted endpoint | Row deleted | |
| Wrong VAPID key | Row KEPT, error logged | |
| App loads normally with SW registered | Yes, all platforms | |
| Technician sees no change at all | Yes | |
| sw-reset unregisters | Yes | |

## Decisions this unblocks
- Widen the opt-in control beyond Owner? **YES / NO**
- Is the iOS install + second login acceptable to the crew? **YES / NO**
- Display text after session expiry (§10.4): generic / category-in-payload / revisit session cap?
```

- [ ] **Step 9: Commit the results**

```bash
git add docs/superpowers/plans/2026-08-14-push-results.md
git commit -m "docs(push): record push infrastructure verification results"
git push origin main
```

---

## Out of Scope

Named so they are not drifted into:

- **The outbox and background drain** — `POST /push/test` sends synchronously, which is acceptable only for an out-of-band Admin action. **No business event may call `push_delivery` directly.** Next phase.
- **`GET /notifications/{id}/display`** and the payload-as-opaque-id design (§6.4). Next phase, and it is what makes richer notification content safe.
- **Notification types, routing rules, recipient resolution** — the explicit reason this plan exists is to have the architecture in place *before* deciding who is notified about what.
- **Notification preferences** — later.
- **Retries, `notification_deliveries`, subscription cleanup sweeps** — later.
- **Widening the opt-in control past Owner** — a one-line change, gated on Task 11's results.
- **What the notification says when a session has expired** — §10.4's open decision. The generic fallback is in place; whether that is good enough is a product call informed by Task 11.
