# Real-Time Live Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the SPA a live layer — data on screen stops being stale — without changing any behavior, appearance, permission, or workflow in the application.

**Architecture:** One authenticated WebSocket endpoint broadcasts *invalidation* events (never payloads); recipients re-fetch through the existing REST API, which re-runs the server's own scoping. The socket is never the system of record, never mutates state, and its failure is invisible. Pure policy lives in `app/domain/realtime.py`, connection state and fan-out in `app/services/realtime.py`, and all enforcement is written visibly in the single endpoint rather than inherited from middleware.

**Tech Stack:** FastAPI 0.136.3 / Starlette 1.3.1 / uvicorn 0.48.0 (Python, synchronous handlers throughout), SQLAlchemy 2.0.50, Postgres. Frontend is plain ES modules with no build step. Tests are pytest 9.0.3 with `fastapi.testclient.TestClient` (built on httpx2).

**Source spec:** `docs/superpowers/specs/2026-08-12-websocket-realtime-layer-design.md`. Read §1 and §3 before starting. §14 records all eight resolved decisions and the reasoning behind them.

---

## Global Constraints

These apply to every task. A change that violates one is wrong even if its tests pass.

- **UX-1** — Every page behaves identically with the socket disconnected. The socket supplements on-activation loading; it never replaces it.
- **UX-2** — **No new UI.** No nav entries, buttons, badges, toasts, banners, counters, or indicators, *including connection-status indicators*. Data freshens; it does not narrate.
- **UX-3** — No workflow gains or loses a step.
- **UX-4** — No permission changes. The socket reveals nothing REST would not already return to that user.
- **UX-5** — No user-facing errors, ever. Socket failure is silent and invisible.
- **UX-6** — A live refresh never discards uncommitted input or disturbs an in-progress interaction.
- **UX-7** — No new perceptible latency on any existing action. A request thread must never block on a socket.
- **P1** — The socket is never the system of record. Every fact delivered is already durable in Postgres and reachable over REST.
- **P2** — Broadcast invalidation, not payloads. Events carry *what changed*, never *what it now is*. **No row data, no auth-surface data, no session state, no credentials go over the wire.**
- **P3** — REST remains the only way state changes. The socket never mutates anything.
- **P5** — One endpoint. Enforcement written visibly in it, not in middleware.
- **No new client dependency and no build step.** Plain ES modules only.
- **Never merge to `main` without asking.** CI deploys to production.
- Backend handlers stay synchronous (`def`, not `async def`) except socket code itself. Nothing existing is converted.

### Threshold constants (D5)

Every number below is a **starting hypothesis**, not a measurement. Each is a named constant with its hypothesis recorded in a comment. They are measured at the Task 22 gate before being trusted.

| Constant | Value | Basis |
|---|---|---|
| `HANDSHAKE_MAX_ATTEMPTS` | `10` | per caller per minute; connection opens are expensive and rare |
| `HANDSHAKE_WINDOW_SECONDS` | `60.0` | login-throttle shape, not request-limiter shape |
| `MAX_CONNECTIONS_PER_USER` | `6` | small crew, a few devices each |
| `INBOUND_MAX_FRAMES` | `20` | per second; far above human typing, far below a loop |
| `INBOUND_WINDOW_SECONDS` | `1.0` | matches the existing limiter's window |
| `MAX_FRAME_BYTES` | `65536` | 64 KB; a chat message needs kilobytes |
| `SEND_QUEUE_MAX` | `32` | per connection; overflow closes rather than buffers |
| `HANDOFF_QUEUE_MAX` | `1000` | process-wide thread→loop buffer |
| `HEARTBEAT_INTERVAL_SECONDS` | `30.0` | below typical proxy idle timeouts |
| `REVALIDATE_INTERVAL_SECONDS` | `60.0` | bounds revocation lag to one minute |
| `DISPATCH_MAX_RESTARTS` | `3` | separates a transient fault from a crash loop |

---

## File Structure

**Created — backend**

| File | Responsibility |
|---|---|
| `backend/app/domain/realtime.py` | Pure policy: envelope shape, event types, audience rules, every threshold. No I/O, no clock reads beyond parameters, no FastAPI. Unit-testable exactly like `domain/rate_limit.py`. |
| `backend/app/services/realtime.py` | Connection registry, the thread→loop handoff queue, the supervised dispatch task. State and orchestration, no FastAPI. |
| `backend/app/routers/realtime.py` | The one endpoint. Handshake auth, every limit check, the receive loop. Enforcement is visible here by inspection (P5). |

**Modified — backend**

| File | Change |
|---|---|
| `backend/requirements.txt` | Add the `websockets` protocol library. Without it uvicorn refuses every handshake. |
| `backend/app/domain/rate_limit.py` | Parameterize the three window functions with defaults. No behavior change for existing callers. |
| `backend/app/services/auth.py` | Add `hash_session_token` and `get_active_session_user_by_hash`, so the registry stores a hash rather than a live credential. |
| `backend/app/main.py` | Add the lifespan hook, mount the socket router, widen the "four things" docstring to five. |
| `backend/app/routers/work_orders.py` | Emit at the three routes that change the Admin Review queue. |

**Created — frontend**

| File | Responsibility |
|---|---|
| `backend/static/realtime.js` | Foundation-layer transport, peer to `api.js`. Owns the connection, reconnection with jittered backoff, and event routing. No DOM access, no view imports. |

**Modified — frontend**

| File | Change |
|---|---|
| `backend/static/views/auth.js` | Connect after `enterApp`, disconnect on `showLoginScreen`. |
| `backend/static/views/adminReview.js` | Subscribe to the work-order event (the only view that changes). |
| `backend/static/main.js` | Wire the transport at the composition root. |

**Created — tests**

`tests/test_realtime_dependency.py`, `tests/test_realtime_domain.py`, `tests/test_realtime_registry.py`, `tests/test_realtime_endpoint.py`, `tests/test_realtime_session_binding.py`, `tests/test_realtime_limits.py`, `tests/test_realtime_emit.py`

---

# Phase 1 — Transport skeleton

## Task 1: Install the WebSocket protocol library

**This task exists because the test suite cannot catch its absence.** `uvicorn==0.48.0` is installed without `[standard]`, so neither `websockets` nor `wsproto` is present, and uvicorn will refuse every WebSocket upgrade in production. Starlette's `TestClient.websocket_connect` uses `WebSocketTestSession`, which talks ASGI directly and imports no protocol library — so **every socket test in this plan would pass while production was completely broken.** This is the same "the test suite would lie" shape §9.1 records for commit hooks, in a second place nobody anticipated.

The guard below is therefore not ceremony. It is the only thing standing between a green suite and a dead feature.

**Files:**
- Modify: `backend/requirements.txt`
- Test: `backend/tests/test_realtime_dependency.py`

**Interfaces:**
- Consumes: nothing.
- Produces: a working WebSocket transport for uvicorn. No Python symbols.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_realtime_dependency.py`:

```python
"""The WebSocket protocol library must actually be installed.

This is the one test in the real-time suite that does not exercise app
code, and it is the most important one. Starlette's TestClient implements
`websocket_connect` against the ASGI app directly -- it never opens a
socket and never imports a protocol library. So every other socket test
here passes whether or not uvicorn can serve a real handshake.

Without `websockets` (or `wsproto`), uvicorn logs "Unsupported upgrade
request" and closes. The suite stays green; production has no real-time
layer at all. This test is what makes that state impossible to ship.
"""


def test_uvicorn_websocket_implementation_is_importable():
    from uvicorn.protocols.websockets.websockets_impl import (
        WebSocketProtocol,
    )

    assert WebSocketProtocol is not None


def test_websockets_is_declared_in_requirements():
    from pathlib import Path

    requirements = (
        Path(__file__).resolve().parent.parent / "requirements.txt"
    ).read_text(encoding="utf-8")

    assert "websockets==" in requirements, (
        "websockets must be pinned in requirements.txt -- uvicorn cannot "
        "serve a WebSocket handshake without a protocol library, and no "
        "other test in this suite can detect its absence."
    )
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && python -m pytest tests/test_realtime_dependency.py -v
```

Expected: both tests FAIL — `ModuleNotFoundError: No module named 'websockets'` and an assertion error on requirements.txt.

- [ ] **Step 3: Install and pin the dependency**

```bash
cd backend && python -m pip install "websockets==15.0.1"
python -m pip show websockets | head -2
```

Add to `backend/requirements.txt`, immediately after the `uvicorn==0.48.0` line, with the reasoning — this file is curated and every pin in it carries a comment:

```
# uvicorn is installed WITHOUT [standard], so it ships no WebSocket
# protocol implementation. Without this package uvicorn answers every
# upgrade request with "Unsupported upgrade request" and closes.
#
# This cannot be caught by the test suite: Starlette's TestClient drives
# `websocket_connect` against the ASGI app directly and never imports a
# protocol library, so the socket tests pass either way. See
# tests/test_realtime_dependency.py, which exists solely to guard this.
websockets==15.0.1
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd backend && python -m pytest tests/test_realtime_dependency.py -v
```

Expected: both PASS.

- [ ] **Step 5: Verify the rest of the suite is unaffected**

```bash
cd backend && python -m pytest -q
```

Expected: no new failures. Adding a package must not disturb anything.

- [ ] **Step 6: Commit**

```bash
git add backend/requirements.txt backend/tests/test_realtime_dependency.py
git commit -m "build: add the websockets protocol library uvicorn needs

uvicorn 0.48.0 is installed without [standard], so it has no WebSocket
protocol implementation and refuses every upgrade request. Nothing in the
test suite can detect this -- Starlette's TestClient drives websocket
routes through ASGI directly and imports no protocol library, so socket
tests pass identically with the package absent and production dead.

test_realtime_dependency.py exists only to close that gap."
```

---

## Task 2: Parameterize the sliding-window policy

§7.3 is explicit: **parameterize rather than fork.** `domain/rate_limit.py:is_over_limit` documents an off-by-one that makes exactly `MAX_REQUESTS` requests succeed rather than `MAX_REQUESTS - 1`. A hand-written second copy is a coin flip on reintroducing that bug in the one module whose purpose is being the single place the rule is written.

Defaults keep every existing caller working unchanged.

**Files:**
- Modify: `backend/app/domain/rate_limit.py`
- Test: `backend/tests/test_rate_limit.py` (existing — add cases)

**Interfaces:**
- Consumes: nothing.
- Produces: `window_start(now: float, window_seconds: float = WINDOW_SECONDS) -> float`; `is_over_limit(count_in_window: int, max_requests: int = MAX_REQUESTS) -> bool`; `retry_after_seconds(oldest_in_window: float, now: float, window_seconds: float = WINDOW_SECONDS) -> int`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_rate_limit.py`:

```python
# --- parameterized reuse (real-time inbound frame limiting) -------------
#
# The socket's inbound limiter is a second *policy* over the same *rule*.
# These cases pin the parameterized form so the two policies can never
# drift apart -- in particular the off-by-one, which is the reason the
# design forbids forking this module.


def test_window_start_accepts_a_custom_window():
    assert rate_limit.window_start(100.0, window_seconds=60.0) == 40.0


def test_window_start_defaults_to_the_http_window():
    assert rate_limit.window_start(100.0) == 100.0 - rate_limit.WINDOW_SECONDS


def test_is_over_limit_accepts_a_custom_cap():
    assert rate_limit.is_over_limit(19, max_requests=20) is False
    assert rate_limit.is_over_limit(20, max_requests=20) is True


def test_custom_cap_preserves_the_off_by_one():
    """Exactly `max_requests` must succeed, not `max_requests - 1`.

    This is the specific bug a forked copy would risk reintroducing.
    """
    allowed = sum(
        1 for count in range(10) if not rate_limit.is_over_limit(count, max_requests=10)
    )
    assert allowed == 10


def test_retry_after_accepts_a_custom_window():
    assert rate_limit.retry_after_seconds(100.0, 130.0, window_seconds=60.0) == 30


def test_retry_after_never_reports_zero_with_a_custom_window():
    assert rate_limit.retry_after_seconds(100.0, 160.0, window_seconds=60.0) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend && python -m pytest tests/test_rate_limit.py -v -k "custom or off_by_one or defaults_to"
```

Expected: FAIL with `TypeError: window_start() got an unexpected keyword argument 'window_seconds'`.

- [ ] **Step 3: Parameterize the three functions**

In `backend/app/domain/rate_limit.py`, change the three signatures. Keep every existing docstring and add the note about the second policy:

```python
def window_start(now: float, window_seconds: float = WINDOW_SECONDS) -> float:
    """The oldest timestamp still inside the window ending at `now`.

    Anything at or before this has aged out and no longer counts.

    `window_seconds` is a parameter so the real-time layer's inbound frame
    limiter can share this rule rather than fork it. It defaults to the
    HTTP window, so every existing caller is unchanged.
    """
    return now - window_seconds


def is_over_limit(count_in_window: int, max_requests: int = MAX_REQUESTS) -> bool:
    """Whether a request arriving now would exceed the cap.

    `count_in_window` is the number of *already recorded* requests still
    inside the window, so the incoming one is allowed while that count
    is below `max_requests` -- making exactly `max_requests` requests per
    window succeed rather than `max_requests - 1`.

    That off-by-one is the reason this module is parameterized rather than
    copied: a second hand-written implementation is a coin flip on getting
    it right, in the one module whose purpose is being the single place
    the rule is written.
    """
    return count_in_window >= max_requests


def retry_after_seconds(
    oldest_in_window: float,
    now: float,
    window_seconds: float = WINDOW_SECONDS,
) -> int:
    """Whole seconds until the window has room again.

    Rounded up, and never below 1: reporting 0 while still limited would
    invite an immediate retry that just fails again. Mirrors the same
    guard in `services.login_throttle._remaining_seconds`.
    """
    frees_at = oldest_in_window + window_seconds
    return max(1, math.ceil(frees_at - now))
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_rate_limit.py tests/test_rate_limit_service.py tests/test_rate_limit_middleware.py -v
```

Expected: all PASS, including every pre-existing case. The defaults mean no existing caller changed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/domain/rate_limit.py backend/tests/test_rate_limit.py
git commit -m "refactor(domain): parameterize the sliding-window rate rule

The real-time inbound frame limiter is a second policy over the same
rule. Parameterizing with defaults gives one implementation and two named
policies, leaving every existing caller untouched.

Forking was the alternative and is worse: is_over_limit documents an
off-by-one that makes exactly MAX_REQUESTS succeed rather than
MAX_REQUESTS - 1, and a second hand-written copy is a coin flip on
reintroducing that bug."
```

---

## Task 3: Session-token hashing and hash-keyed resolution

D1 binds sockets to session validity by periodic revalidation. To revalidate, a connection must remember its session — but `get_active_session_user` takes the **raw** token, and holding raw tokens in a process-wide registry for hours contradicts the precedent §7.1 praises: `services/rate_limit.caller_key` hashes the token precisely so a live credential never lands in a process-wide dict.

This task exposes the existing private `_hash_token` and adds a hash-keyed resolver, so the registry stores only a digest.

**Files:**
- Modify: `backend/app/services/auth.py`
- Test: `backend/tests/test_realtime_session_binding.py` (created here)

**Interfaces:**
- Consumes: nothing.
- Produces: `hash_session_token(token: str) -> str`; `get_active_session_user_by_hash(db: Session, token_hash: str) -> Optional[User]`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_realtime_session_binding.py`:

```python
"""Session binding for real-time connections (design D1, §6.2).

A socket authenticated once at handshake has no next request, so the
instant revocation every HTTP route gets for free does not apply. These
tests pin the mechanism that replaces it: periodic re-resolution against
a stored token *hash*.
"""

import pytest

from app.models import User
from app.services import auth as auth_service


def _make_user(db, *, username="ws_bind_user", role="technician"):
    user = User(
        username=username,
        first_name="Ws",
        last_name="Bind",
        role=role,
        password_hash=auth_service.hash_password("correct horse"),
    )
    db.add(user)
    db.flush()
    return user


def test_hash_session_token_is_stable_and_not_the_token():
    digest = auth_service.hash_session_token("a-raw-token")

    assert digest == auth_service.hash_session_token("a-raw-token")
    assert "a-raw-token" not in digest
    assert len(digest) == 64


def test_resolve_by_hash_returns_the_user_for_a_live_session(db):
    user = _make_user(db)
    token = auth_service.create_session(db, user)

    resolved = auth_service.get_active_session_user_by_hash(
        db, auth_service.hash_session_token(token)
    )

    assert resolved is not None
    assert resolved.id == user.id


def test_resolve_by_hash_returns_none_after_revocation(db):
    """Covers role change, archival, and password reset in one mechanism.

    All three call `revoke_user_sessions`, which deletes the rows -- so a
    re-resolve returns None for every one of them.
    """
    user = _make_user(db, username="ws_revoked_user")
    token = auth_service.create_session(db, user)
    token_hash = auth_service.hash_session_token(token)

    auth_service.revoke_user_sessions(db, user.id)
    db.flush()

    assert auth_service.get_active_session_user_by_hash(db, token_hash) is None


def test_resolve_by_hash_returns_none_for_an_unknown_hash(db):
    assert auth_service.get_active_session_user_by_hash(db, "0" * 64) is None


def test_resolve_by_hash_agrees_with_the_raw_token_resolver(db):
    """The two resolvers must never disagree -- one is the socket's view
    of the same fact the HTTP layer reads on every request."""
    user = _make_user(db, username="ws_parity_user")
    token = auth_service.create_session(db, user)

    by_token = auth_service.get_active_session_user(db, token)
    by_hash = auth_service.get_active_session_user_by_hash(
        db, auth_service.hash_session_token(token)
    )

    assert by_token is not None and by_hash is not None
    assert by_token.id == by_hash.id
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && python -m pytest tests/test_realtime_session_binding.py -v
```

Expected: FAIL — `AttributeError: module 'app.services.auth' has no attribute 'hash_session_token'`.

- [ ] **Step 3: Implement both functions**

In `backend/app/services/auth.py`, rename `_hash_token` to a public `hash_session_token` and keep `_hash_token` as an alias so nothing else breaks. Then add the resolver next to `get_active_session_user`:

```python
def hash_session_token(token: str) -> str:
    """Return the lowercase hex SHA-256 of a session token -- the only
    form ever written to the database, and the only form a long-lived
    real-time connection is allowed to remember.

    Plain SHA-256 (not scrypt) is correct here: the input is 256 bits of
    CSPRNG output, so there is no guessable keyspace for a slow KDF to
    defend, and this runs on every authenticated request."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# Retained so existing internal callers read unchanged.
_hash_token = hash_session_token


def get_active_session_user_by_hash(db: Session, token_hash: str) -> Optional[User]:
    """`get_active_session_user`, keyed by an already-hashed token.

    Exists for the real-time layer. A socket is authenticated once at
    handshake and has no next request, so it re-resolves its session on a
    timer to stay bound to revocation, role change, and the 12-hour cap
    (design D1). It stores the **hash** rather than the raw token: a raw
    token is a live credential, and a connection registry is exactly the
    process-wide structure `services.rate_limit.caller_key` hashes to stay
    out of.

    Identical policy to the raw-token resolver, and deliberately a thin
    wrapper over one shared implementation so the two cannot drift.
    """
    return _resolve_active_session(db, token_hash)
```

Refactor the body of `get_active_session_user` into `_resolve_active_session(db, token_hash)`, so both entry points share one implementation:

```python
def get_active_session_user(db: Session, token: str) -> Optional[User]:
    """Return the `User` for a valid, non-expired session token, or
    `None`. `token` is the raw cookie value; it is hashed here to find
    the row.

    Lifetime policy:
    - If no session matches the hash, returns None.
    - If the session is past its `expires_at` cap, the row is deleted and
      None is returned (expired on the server). Every session has a cap.
    - Otherwise the owning user is returned, unless that user has since
      been archived -- an archived user is treated as having no valid
      session (defense in depth: the archive path also deletes the user's
      sessions, but this guards any that slip through). There is no idle
      timeout and no per-request write.
    """
    return _resolve_active_session(db, hash_session_token(token))


def _resolve_active_session(db: Session, token_hash: str) -> Optional[User]:
    """Shared body of the two resolvers above. See `get_active_session_user`
    for the lifetime policy this implements."""
    session = (
        db.query(AuthSession)
        .filter(AuthSession.token_hash == token_hash)
        .first()
    )
    if session is None:
        return None

    expires_at = session.expires_at
    # Postgres returns tz-aware datetimes; guard defensively in case
    # a naive value ever slips in so the comparison cannot crash.
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > expires_at:
        db.delete(session)
        db.commit()
        return None

    return (
        db.query(User)
        .filter(User.id == session.user_id, User.archived_at.is_(None))
        .first()
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_realtime_session_binding.py tests/test_session_token_hashing.py tests/test_auth_session_lifetime.py tests/test_password_reset_revokes_sessions.py -v
```

Expected: all PASS. The existing session tests are included deliberately — this task refactors their subject.

- [ ] **Step 5: Fix the stale docstring in `auth_deps.py`**

`backend/app/auth_deps.py:47-49` claims "Touching the session (sliding the idle timeout) happens inside `get_active_session_user`". The implementation does no such thing and says so. Correct it while you are in this code:

```python
    """Resolve the request's session cookie to the logged-in `User`, or
    raise 401. Sessions have a hard absolute cap and no idle timeout, so
    this is a pure read -- see `get_active_session_user`.
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/auth.py backend/app/auth_deps.py backend/tests/test_realtime_session_binding.py
git commit -m "feat(auth): resolve a session from its hash, for real-time binding

A socket authenticated once at handshake has no next request, so it
re-resolves on a timer to stay bound to revocation. Storing the raw token
to do that would put a live credential in a process-wide registry --
exactly what services.rate_limit.caller_key hashes to avoid.

Both resolvers now share one body so their policy cannot drift.

Also corrects auth_deps.get_current_user's docstring, which claimed
get_active_session_user slides an idle timeout. It does not, and its own
docstring says so."
```

---

## Task 4: The pure real-time policy module

Everything with a number or a rule, and nothing with a socket, a clock, or a database. Unit-testable with no app running, exactly like `domain/rate_limit.py`.

**Files:**
- Create: `backend/app/domain/realtime.py`
- Test: `backend/tests/test_realtime_domain.py`

**Interfaces:**
- Consumes: `app.domain.rate_limit.{is_over_limit, window_start, retry_after_seconds}`; `app.domain.roles.role_at_least`.
- Produces: constants from the Global Constraints table; `EVENT_WORK_ORDER_CHANGED: str`; `build_envelope(*, event_type, entity_id, actor_id, request_id) -> dict`; `is_valid_inbound(frame: dict) -> bool`; `audience_allows(event_type: str, role: str) -> bool`; `INBOUND_PING: str`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_realtime_domain.py`:

```python
"""Pure real-time policy -- no sockets, no clock, no database.

Mirrors the shape of tests/test_rate_limit.py: the rules are decidable in
isolation, so they are tested in isolation.
"""

from app.domain import realtime


# --- envelope ----------------------------------------------------------


def test_envelope_carries_a_discriminating_type():
    envelope = realtime.build_envelope(
        event_type=realtime.EVENT_WORK_ORDER_CHANGED,
        entity_id="wo-1",
        actor_id="user-1",
        request_id="req-1",
    )

    assert envelope["type"] == realtime.EVENT_WORK_ORDER_CHANGED


def test_envelope_carries_actor_and_correlation_id():
    """Actor lets a client ignore its own echo (§8.4, a UX-7 protection).
    The request id is what makes one write traceable to N deliveries
    (§8.2) -- it must travel as data, never through a context variable."""
    envelope = realtime.build_envelope(
        event_type=realtime.EVENT_WORK_ORDER_CHANGED,
        entity_id="wo-1",
        actor_id="user-1",
        request_id="req-1",
    )

    assert envelope["actor"] == "user-1"
    assert envelope["req"] == "req-1"


def test_envelope_carries_no_row_data():
    """P2: events say what changed, never what it now is. The whole
    security argument for the socket rests on this -- if payloads ship,
    every fan-out decision becomes an independent disclosure review."""
    envelope = realtime.build_envelope(
        event_type=realtime.EVENT_WORK_ORDER_CHANGED,
        entity_id="wo-1",
        actor_id="user-1",
        request_id="req-1",
    )

    assert set(envelope) == {"type", "id", "actor", "req"}


def test_envelope_stringifies_ids():
    """UUIDs must survive json.dumps without a custom encoder."""
    import uuid

    entity = uuid.uuid4()
    envelope = realtime.build_envelope(
        event_type=realtime.EVENT_WORK_ORDER_CHANGED,
        entity_id=entity,
        actor_id=None,
        request_id=None,
    )

    assert envelope["id"] == str(entity)
    assert envelope["actor"] is None


# --- inbound validation ------------------------------------------------


def test_ping_is_the_only_accepted_inbound_frame():
    assert realtime.is_valid_inbound({"type": realtime.INBOUND_PING}) is True


def test_unknown_inbound_types_are_rejected():
    assert realtime.is_valid_inbound({"type": "mutate_everything"}) is False


def test_malformed_inbound_frames_are_rejected():
    assert realtime.is_valid_inbound({}) is False
    assert realtime.is_valid_inbound({"type": None}) is False
    assert realtime.is_valid_inbound([]) is False
    assert realtime.is_valid_inbound("ping") is False


# --- audience ----------------------------------------------------------


def test_work_order_events_reach_admin_and_owner():
    assert realtime.audience_allows(realtime.EVENT_WORK_ORDER_CHANGED, "admin") is True
    assert realtime.audience_allows(realtime.EVENT_WORK_ORDER_CHANGED, "owner") is True


def test_work_order_events_do_not_reach_lower_roles_in_v1():
    """Not a security boundary -- P2 makes a mis-scoped audience a wasted
    message, since the recipient's re-fetch is still authorized
    server-side. This is a noise and efficiency rule, and the Admin
    Review surface is Admin+ only."""
    assert realtime.audience_allows(realtime.EVENT_WORK_ORDER_CHANGED, "supervisor") is False
    assert realtime.audience_allows(realtime.EVENT_WORK_ORDER_CHANGED, "technician") is False


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
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend && python -m pytest tests/test_realtime_domain.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.domain.realtime'`.

- [ ] **Step 3: Implement the policy module**

Create `backend/app/domain/realtime.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_realtime_domain.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/domain/realtime.py backend/tests/test_realtime_domain.py
git commit -m "feat(domain): add pure real-time policy

Envelope shape, inbound allowlist, audience map, and every threshold --
no sockets, no clock, no database, testable in isolation like
domain/rate_limit.py.

The envelope carries a discriminating type from day one and no row data
at all. That is P2, and it is what makes the socket structurally
incapable of leaking anything REST would not already return.

Every number records the hypothesis that produced it, so measuring it at
the first-surface gate is a comparison rather than a fresh argument."
```

---

## Task 5: Connection registry, handoff queue, and the supervised dispatch task

The first genuine concurrency boundary in the codebase. The app is entirely synchronous — 75 handlers running in a threadpool — and sockets live on the event loop, so a threadpool handler cannot `await` a broadcast.

Two properties are mandatory: **non-blocking** (a request thread must never wait on a socket, or a phone on bad wifi can stall an inventory write and violate UX-7) and **bounded** (overflow is a designed decision, and P2 makes dropping safe).

**Files:**
- Create: `backend/app/services/realtime.py`
- Test: `backend/tests/test_realtime_registry.py`

**Interfaces:**
- Consumes: `app.domain.realtime` constants; `app.services.auth.get_active_session_user_by_hash`.
- Produces: `class Connection` with attributes `.user_id`, `.token_hash`, `.role`, `.websocket`, `.connection_id`, `.queue`, `.overflowed`, and method `enqueue(envelope: dict) -> bool`; `class DispatchSupervisor` with `.restarts`, `.gave_up`, `should_restart() -> bool`; `register(connection) -> bool`; `deregister(connection) -> None`; `connection_count(user_id) -> int`; `all_connections() -> list[Connection]`; `emit(envelope: dict) -> bool`; `dropped_event_count() -> int`; `start_dispatch() -> None`; `async stop_dispatch() -> None`; `reset() -> None`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_realtime_registry.py`:

```python
"""Connection registry, bounded handoff, and dispatch supervision.

These are the parts that make the socket safe rather than merely working:
the registry is what the concurrency cap is checked against, and the
handoff is the boundary between 75 synchronous threadpool handlers and a
single event loop.
"""

import asyncio

import pytest

from app.domain import realtime as policy
from app.services import realtime as service


@pytest.fixture(autouse=True)
def _clean_registry():
    service.reset()
    yield
    service.reset()


def _conn(user_id="user-1", role="admin"):
    return service.Connection(
        user_id=user_id,
        token_hash="a" * 64,
        role=role,
        websocket=None,
    )


# --- registry ----------------------------------------------------------


def test_registry_is_keyed_by_user_not_by_connection():
    """One person on two devices must receive on both. A flat set of
    sockets supports broadcast only; a keyed map supports broadcast,
    targeted delivery, multi-device, and per-user revocation -- which is
    what makes messaging additive later."""
    first, second = _conn(), _conn()

    assert service.register(first) is True
    assert service.register(second) is True
    assert service.connection_count("user-1") == 2


def test_registry_refuses_past_the_concurrency_cap():
    accepted = [
        service.register(_conn()) for _ in range(policy.MAX_CONNECTIONS_PER_USER + 2)
    ]

    assert accepted.count(True) == policy.MAX_CONNECTIONS_PER_USER
    assert accepted.count(False) == 2
    assert service.connection_count("user-1") == policy.MAX_CONNECTIONS_PER_USER


def test_deregistration_frees_a_cap_slot():
    """Leaked entries consume cap slots and produce phantom fan-out
    targets. Enough zombies and a legitimate user is locked out by their
    own dead sockets."""
    connections = [_conn() for _ in range(policy.MAX_CONNECTIONS_PER_USER)]
    for connection in connections:
        service.register(connection)

    assert service.register(_conn()) is False

    service.deregister(connections[0])

    assert service.register(_conn()) is True


def test_deregistering_twice_is_harmless():
    """Every close path -- clean, error, timeout, revocation, shutdown --
    deregisters, and several can run for one connection."""
    connection = _conn()
    service.register(connection)

    service.deregister(connection)
    service.deregister(connection)

    assert service.connection_count("user-1") == 0


def test_users_have_independent_caps():
    for _ in range(policy.MAX_CONNECTIONS_PER_USER):
        service.register(_conn(user_id="user-1"))

    assert service.register(_conn(user_id="user-2")) is True


# --- handoff -----------------------------------------------------------


def test_emit_never_blocks_and_reports_acceptance():
    assert service.emit({"type": "work_order.changed"}) is True


def test_emit_drops_newest_when_the_handoff_is_full():
    """D3. Dropping is safe because of P2 -- an invalidation event is
    disposable, and the client's next page activation refetches. What
    matters is that a request thread is never blocked (UX-7) and that the
    drop is counted rather than silent."""
    for _ in range(policy.HANDOFF_QUEUE_MAX):
        service.emit({"type": "work_order.changed"})

    assert service.emit({"type": "work_order.changed"}) is False
    assert service.dropped_event_count() == 1


def test_dropped_events_are_counted_cumulatively():
    for _ in range(policy.HANDOFF_QUEUE_MAX + 3):
        service.emit({"type": "work_order.changed"})

    assert service.dropped_event_count() == 3


# --- backpressure ------------------------------------------------------


def test_send_queue_overflow_marks_the_connection_for_closure():
    """D6/§7.5. Nothing else protects the server from a *slow* client: a
    phone on one bar cannot drain what it is sent, and that is a bad
    connection rather than abuse, which is exactly why a rate limiter
    never catches it.

    Closing is lossless because of P1 and P2 -- the event is disposable
    and the durable fact is in Postgres, reachable over REST."""
    connection = _conn()

    for _ in range(policy.SEND_QUEUE_MAX):
        assert connection.enqueue({"type": "work_order.changed"}) is True

    assert connection.enqueue({"type": "work_order.changed"}) is False
    assert connection.overflowed is True


# --- dispatch supervision ----------------------------------------------


def test_dispatch_restarts_are_bounded():
    """D2. A transient fault should not kill real-time for hours; a crash
    loop must not look identical to healthy operation, which is the
    silent-failure mode §8.3 names."""
    assert policy.DISPATCH_MAX_RESTARTS >= 1

    supervisor = service.DispatchSupervisor()

    for _ in range(policy.DISPATCH_MAX_RESTARTS):
        assert supervisor.should_restart() is True

    assert supervisor.should_restart() is False


def test_supervisor_reports_permanent_failure():
    supervisor = service.DispatchSupervisor()
    for _ in range(policy.DISPATCH_MAX_RESTARTS + 1):
        supervisor.should_restart()

    assert supervisor.gave_up is True
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend && python -m pytest tests/test_realtime_registry.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.realtime'`.

- [ ] **Step 3: Implement the service module**

Create `backend/app/services/realtime.py`. Key structure — write it in full following this shape:

```python
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
import json
import logging
import threading
import uuid
from collections import deque
from typing import Any, Optional

from app.domain import realtime as policy

logger = logging.getLogger(__name__)

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
    optional step.
    """
    global _dropped_events
    with _handoff_lock:
        if len(_handoff) >= policy.HANDOFF_QUEUE_MAX:
            _dropped_events += 1
            logger.warning(
                "realtime handoff full; event dropped total_dropped=%s",
                _dropped_events,
            )
            return False
        _handoff.append(envelope)

    if _loop is not None and _wakeup is not None:
        try:
            _loop.call_soon_threadsafe(_wakeup.set)
        except RuntimeError:
            # The loop closed between the check and the call (shutdown).
            # The event is already queued; stop_dispatch drains it.
            pass
    return True


def dropped_event_count() -> int:
    return _dropped_events


def reset() -> None:
    """Discard all state. For tests -- module state is process global, so a
    test that fills the handoff would otherwise leak into the next one.
    Mirrors `services.rate_limit.reset`."""
    global _dropped_events, _wakeup, _loop, _dispatch_task
    _connections.clear()
    with _handoff_lock:
        _handoff.clear()
    _dropped_events = 0
    _wakeup = None
    _loop = None
    _dispatch_task = None
```

Also implement `start_dispatch()` / `stop_dispatch()` (binding `_loop` and `_wakeup`, starting the supervised task, and on shutdown closing every connection deliberately so clients see a clean close and reconnect on their own schedule), and the `_dispatch_loop` coroutine which waits on `_wakeup`, drains `_handoff` under the lock, resolves the audience via `policy.audience_allows(envelope["type"], connection.role)`, calls `connection.enqueue(...)`, and closes any connection whose `enqueue` returns `False`.

**No test-only seam is needed.** Because the fullness decision in `emit` is synchronous and the loop wakeup is a separate optional step, the tests drive `emit` directly with no running loop. Do not add an `_install_handoff_for_tests`-style hook: production code shaped by tests is a defect, and this design does not need one.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_realtime_registry.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/realtime.py backend/tests/test_realtime_registry.py
git commit -m "feat(services): add the connection registry and bounded handoff

The first real concurrency boundary in the codebase: 75 synchronous
handlers in a threadpool on one side, one event loop on the other.

emit() never blocks a request thread -- a phone on bad wifi must not be
able to stall an inventory write (UX-7) -- and the handoff is bounded,
dropping newest and counting it (D3). P2 is what makes dropping safe.

The registry is keyed by user rather than by session so one person on two
devices receives on both, which is also what makes targeted messaging
additive later rather than a rewrite."
```

---

## Task 6: The endpoint, handshake authentication, and the lifespan hook

One endpoint. Every limit is enforced visibly here rather than inherited, per P5 — with a single endpoint, explicit enforcement is complete by inspection: you read one file and know the entire policy.

**Note the trap §7 records:** the HTTP rate limiter does **not** apply to this route. The handshake arrives as a `websocket` scope and never enters HTTP middleware, despite being an HTTP GET on the wire. Nothing is inherited; everything is written here.

**Files:**
- Create: `backend/app/routers/realtime.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_realtime_endpoint.py`

**Interfaces:**
- Consumes: `app.services.realtime.{Connection, register, deregister, start_dispatch, stop_dispatch}`; `app.services.auth.{hash_session_token, get_active_session_user_by_hash}`; `app.services.rate_limit.caller_key`; `app.domain.realtime`; `app.auth_deps.SESSION_COOKIE`.
- Produces: `router: APIRouter` with `WEBSOCKET /ws`; `lifespan` async context manager exported for `main.py`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_realtime_endpoint.py`:

```python
"""The single socket endpoint: handshake auth and connection lifecycle.

Read tests/test_realtime_dependency.py before trusting a green run here.
TestClient drives websocket routes through ASGI directly, so these tests
pass whether or not uvicorn can serve a real handshake in production.
"""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.domain import realtime as policy
from app.main import app
from app.models import User
from app.services import auth as auth_service
from app.services import realtime as service


@pytest.fixture(autouse=True)
def _clean_registry():
    service.reset()
    yield
    service.reset()


def _session_for(db, *, role="admin", username="ws_endpoint_user"):
    user = User(
        username=username,
        first_name="Ws",
        last_name="Endpoint",
        role=role,
        password_hash=auth_service.hash_password("correct horse"),
    )
    db.add(user)
    db.flush()
    db.commit()
    return user, auth_service.create_session(db, user)


def test_handshake_without_a_cookie_is_refused(db):
    """Refused immediately, before any expensive work."""
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws"):
                pass


def test_handshake_with_an_unknown_token_is_refused(db):
    with TestClient(app) as client:
        client.cookies.set("session", "not-a-real-token")
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws"):
                pass


def test_authenticated_handshake_is_accepted_and_registered(db):
    user, token = _session_for(db)

    with TestClient(app) as client:
        client.cookies.set("session", token)
        with client.websocket_connect("/ws"):
            assert service.connection_count(user.id) == 1


def test_connection_is_deregistered_on_close(db):
    user, token = _session_for(db, username="ws_close_user")

    with TestClient(app) as client:
        client.cookies.set("session", token)
        with client.websocket_connect("/ws"):
            pass

        assert service.connection_count(user.id) == 0


def test_ping_is_answered(db):
    """The endpoint accepts client->server frames from day one. A strictly
    one-way socket has no seam at which to add message send later."""
    _user, token = _session_for(db, username="ws_ping_user")

    with TestClient(app) as client:
        client.cookies.set("session", token)
        with client.websocket_connect("/ws") as socket:
            socket.send_json({"type": policy.INBOUND_PING})
            assert socket.receive_json()["type"] == "pong"


def test_unknown_inbound_frames_do_not_mutate_or_crash(db):
    """P3 is permanent: the socket never mutates anything."""
    _user, token = _session_for(db, username="ws_bad_frame_user")

    with TestClient(app) as client:
        client.cookies.set("session", token)
        with client.websocket_connect("/ws") as socket:
            socket.send_json({"type": "delete_everything"})
            socket.send_json({"type": policy.INBOUND_PING})
            assert socket.receive_json()["type"] == "pong"


def test_oversized_frames_are_rejected(db):
    _user, token = _session_for(db, username="ws_big_frame_user")

    with TestClient(app) as client:
        client.cookies.set("session", token)
        with client.websocket_connect("/ws") as socket:
            socket.send_text("x" * (policy.MAX_FRAME_BYTES + 1))
            with pytest.raises(WebSocketDisconnect):
                socket.receive_json()
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend && python -m pytest tests/test_realtime_endpoint.py -v
```

Expected: FAIL — no `/ws` route exists.

- [ ] **Step 3: Implement the endpoint**

Create `backend/app/routers/realtime.py`. It must, in this order:

1. Read the session cookie from `websocket.cookies.get(SESSION_COOKIE)`. Absent → `await websocket.close(code=1008)` and return, **before** `accept()`.
2. Compute `caller_key(token, websocket.client.host)` and check the handshake attempt budget against `HANDSHAKE_MAX_ATTEMPTS` / `HANDSHAKE_WINDOW_SECONDS` using the parameterized domain functions. Over budget → close with `1008`. **Note the protocol point:** there is no `Retry-After` on a WebSocket close, so if a wait hint is ever needed it must ride in an application frame *before* the close — the client derives its own backoff.
3. Resolve `get_active_session_user_by_hash(db, hash_session_token(token))`. `None` → close `1008` before `accept()`.
4. Build a `Connection` and `register(...)`. Refused (at the cap) → close `1008`.
5. `await websocket.accept()`, log the connect line with `connection_id` and `user`.
6. Run three concurrent tasks: the receive loop (validating each frame against `MAX_FRAME_BYTES`, `is_valid_inbound`, and the inbound frame limiter), the send pump (draining `connection.queue`), and the maintenance loop (heartbeat at `HEARTBEAT_INTERVAL_SECONDS`, session revalidation at `REVALIDATE_INTERVAL_SECONDS`).
7. `finally: deregister(connection)` and log the disconnect line — on **every** path.

Add the lifespan context manager in the same file:

```python
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
```

- [ ] **Step 4: Wire it into `main.py`**

Update the module docstring — `main.py` states "this file does four things and nothing else", and that boundary is now five. This must be a deliberate edit, not a silent contradiction:

```python
"""FastAPI application entrypoint -- the composition root.

Layer: app entry. This file does five things and nothing else:

1. Configure logging and instantiate the `FastAPI` app -- including whether
   its built-in docs endpoints exist at all, which depends on the
   environment (see `_doc_urls`).
2. Mount the resource routers and the static-files directory that serves
   the single-page frontend at `/`.
3. Expose the two database probes: `/healthz`, the unauthenticated
   liveness check the deployment platform polls, and `/db-test`, the
   Admin-gated probe deployment scripts use to confirm *which*
   database is connected.
4. Wrap every request in the middleware pair: the security headers and
   the logging/request-id scope.
5. Own the application lifespan, which starts and stops the real-time
   dispatch task. This is the app's only startup/shutdown hook; fan-out
   requires a long-lived background task and there was previously
   nowhere for one to live.

Business logic lives in `app.services`, validation in
`app.schemas`, rules in `app.domain`. Nothing in this file should
ever grow beyond wiring.
"""
```

Pass `lifespan=lifespan` to the `FastAPI(...)` constructor and include the router alongside the others.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_realtime_endpoint.py -v
cd backend && python -m pytest -q
```

Expected: the new tests PASS and the full suite is green.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/realtime.py backend/app/main.py backend/tests/test_realtime_endpoint.py
git commit -m "feat(realtime): add the socket endpoint and application lifespan

One endpoint, with every limit written visibly in it rather than
inherited. That is P5, and it matters here specifically: the handshake
arrives as a websocket scope and never enters HTTP middleware, so the
existing rate limiter does not apply despite this being an HTTP GET on
the wire. Nothing is inherited automatically.

Authentication reuses the existing session cookie and resolver -- no new
token scheme, no new credential, no change to how anyone logs in.

main.py's stated boundary widens from four things to five, edited
deliberately rather than silently contradicted."
```

---

# Phase 2 — Connection lifecycle and session binding

## Task 7: Heartbeat and session revalidation

**This closes the most important item in the design.** Today every request re-resolves the session, so revocation is instant and automatic. A socket authenticated once at handshake has no next request: demote a Supervisor and their open socket keeps streaming Supervisor-scoped events; archive a user and their socket keeps receiving; sessions carry a hard 12-hour cap a socket would simply outlive.

**Files:**
- Modify: `backend/app/routers/realtime.py`
- Test: `backend/tests/test_realtime_session_binding.py` (extend)

**Interfaces:**
- Consumes: `app.services.auth.get_active_session_user_by_hash`; `policy.{HEARTBEAT_INTERVAL_SECONDS, REVALIDATE_INTERVAL_SECONDS}`.
- Produces: `async def revalidate_once(connection, db) -> bool` — `False` means the session is gone and the connection must close.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_realtime_session_binding.py`:

```python
# --- connection binding ------------------------------------------------


@pytest.mark.anyio
async def test_revalidate_keeps_a_live_session(db):
    from app.routers import realtime as endpoint
    from app.services import realtime as service

    user = _make_user(db, username="ws_live_user", role="admin")
    token = auth_service.create_session(db, user)
    connection = service.Connection(
        user_id=user.id,
        token_hash=auth_service.hash_session_token(token),
        role="admin",
        websocket=None,
    )

    assert await endpoint.revalidate_once(connection, db) is True


@pytest.mark.anyio
async def test_revalidate_closes_after_revocation(db):
    """Archive, role change, and password reset all delete the session
    row, so one mechanism catches all three."""
    from app.routers import realtime as endpoint
    from app.services import realtime as service

    user = _make_user(db, username="ws_revoke_user", role="supervisor")
    token = auth_service.create_session(db, user)
    connection = service.Connection(
        user_id=user.id,
        token_hash=auth_service.hash_session_token(token),
        role="supervisor",
        websocket=None,
    )

    auth_service.revoke_user_sessions(db, user.id)
    db.flush()

    assert await endpoint.revalidate_once(connection, db) is False


@pytest.mark.anyio
async def test_revalidate_refreshes_the_cached_role(db):
    """A demoted user must not keep receiving events scoped to the role
    they used to hold."""
    from app.routers import realtime as endpoint
    from app.services import realtime as service

    user = _make_user(db, username="ws_demote_user", role="admin")
    token = auth_service.create_session(db, user)
    connection = service.Connection(
        user_id=user.id,
        token_hash=auth_service.hash_session_token(token),
        role="admin",
        websocket=None,
    )

    user.role = "technician"
    db.flush()

    assert await endpoint.revalidate_once(connection, db) is True
    assert connection.role == "technician"


def test_revalidation_interval_bounds_revocation_lag():
    """The accepted cost of choosing revalidation over an explicit signal
    (D1). Recorded as a test so the number is a decision, not a drift."""
    from app.domain import realtime as policy

    assert policy.REVALIDATE_INTERVAL_SECONDS <= 300.0
```

Add `anyio` to `requirements-dev.txt` if `pytest.mark.anyio` is not already available, plus an `anyio_backend` fixture returning `"asyncio"` in `conftest.py`.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend && python -m pytest tests/test_realtime_session_binding.py -v -k "revalidate or interval"
```

Expected: FAIL — `revalidate_once` does not exist.

- [ ] **Step 3: Implement revalidation and the heartbeat**

In `backend/app/routers/realtime.py`:

```python
async def revalidate_once(connection, db) -> bool:
    """Re-resolve this connection's session. False means close it.

    **This preserves a property the app already has and would otherwise
    silently lose.** Every HTTP request re-resolves the session, so
    revocation is instant; a socket has no next request. Without this a
    demoted Supervisor keeps streaming Supervisor-scoped events, an
    archived user keeps receiving, and the hard 12-hour session cap is
    simply outlived.

    One mechanism covers every case because all three revoking paths --
    archive_user, update_role, reset_password -- delete the session rows,
    and the resolver checks the cap on the same call.

    The role is refreshed rather than merely checked, so a demotion
    narrows what the connection receives at the next fan-out instead of
    waiting for a reconnect.
    """
    user = get_active_session_user_by_hash(db, connection.token_hash)
    if user is None:
        return False
    connection.role = user.role
    return True
```

Wire the maintenance loop to call it every `REVALIDATE_INTERVAL_SECONDS` with a fresh DB session, and to send a heartbeat frame every `HEARTBEAT_INTERVAL_SECONDS`, closing and deregistering on a `False` result or an unanswered heartbeat.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_realtime_session_binding.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/realtime.py backend/tests/test_realtime_session_binding.py backend/tests/conftest.py backend/requirements-dev.txt
git commit -m "feat(realtime): bind connections to session validity

A socket that outlives its authorization is a security defect, and this
is the one place the app would have silently lost a property it already
has. Every HTTP request re-resolves the session so revocation is instant;
a socket authenticated once at handshake has no next request.

Periodic revalidation against the stored token hash covers archival, role
change, password reset, and the 12-hour cap in one mechanism, because all
three revoking paths delete the session row (D1). The role is refreshed
as well as checked, so a demotion narrows delivery without a reconnect."
```

---

# Phase 3 — Resource and abuse control

## Task 8: Handshake throttling, frame limits, and backpressure enforcement

Five distinct problems, none of which the existing HTTP limiter addresses, because the handshake never enters HTTP middleware.

**Files:**
- Modify: `backend/app/routers/realtime.py`
- Test: `backend/tests/test_realtime_limits.py`

**Interfaces:**
- Consumes: `app.services.rate_limit.caller_key`; parameterized `domain.rate_limit` functions; every threshold in `domain.realtime`.
- Produces: `handshake_attempt_allowed(key: str, now: float) -> bool`; `inbound_frame_allowed(connection, now: float) -> bool`; `reset_limits() -> None`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_realtime_limits.py` covering, with one test each and an explicit assertion per bullet:

- Handshake attempts are counted per caller and refused past `HANDSHAKE_MAX_ATTEMPTS` in `HANDSHAKE_WINDOW_SECONDS`.
- The handshake budget is **separate from** the HTTP budget: exhausting the socket budget leaves `services.rate_limit.check_and_record` untouched, so socket churn cannot consume the budget a user's inventory writes need.
- `caller_key` is reused unchanged — assert the key for a given token matches `services.rate_limit.caller_key(token, ip)` exactly.
- Inbound frames are refused past `INBOUND_MAX_FRAMES` per `INBOUND_WINDOW_SECONDS`, per connection.
- Exactly `INBOUND_MAX_FRAMES` succeed, not `INBOUND_MAX_FRAMES - 1` — the off-by-one Task 2 preserved.
- A frame over `MAX_FRAME_BYTES` closes the connection.
- **Each limit has a test that fails when the limit is removed.** This is a named requirement of the §11 verification gate — after writing each test, comment out the limit, confirm the test fails, restore it.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend && python -m pytest tests/test_realtime_limits.py -v
```

- [ ] **Step 3: Implement the limiters**

Reuse `caller_key` unchanged — it already hashes the session token so a live credential never enters a process-wide dict, and already falls back to client address for unauthenticated callers. The socket object exposes everything it needs via `websocket.cookies` and `websocket.client.host`.

Use the parameterized `window_start` / `is_over_limit` from Task 2 with the socket constants. Do **not** write a second sliding window.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_realtime_limits.py -v
```

- [ ] **Step 5: Verify each limit is load-bearing**

For each of the four limits: comment it out, run the suite, confirm a test fails, restore it. Record the result in the commit message.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/realtime.py backend/tests/test_realtime_limits.py
git commit -m "feat(realtime): enforce handshake, frame, and size limits

None of this is inherited. The handshake arrives as a websocket scope and
never enters HTTP middleware, so the existing limiter does not apply.

The budget is deliberately separate from the HTTP one: 60-per-second is
calibrated for page loads, and sixty socket opens per second is a
catastrophe that sails straight through it. Sharing the bucket would also
let socket churn consume the budget a user's inventory writes need.

caller_key and the sliding-window math are reused unchanged rather than
forked. Verified each limit is load-bearing by removing it and confirming
a test fails."
```

---

# Phase 4 — Observability

## Task 9: Connection identity, causal correlation, and dispatch supervision logging

The app's observability bar is high and deliberate. **None of it is inherited.** The logging formatter reads a request-scoped context variable at format time; outside a request scope it emits a placeholder, and `bind_user` is an explicit no-op. Concretely: every log line from socket code would be both un-correlatable and un-attributable — present in the stream, greppable by nothing, attached to no one. That is worse than not logging, because absent lines get noticed and anonymous lines look fine until the day you need them.

**Files:**
- Modify: `backend/app/services/realtime.py`, `backend/app/routers/realtime.py`
- Test: `backend/tests/test_realtime_endpoint.py` (extend)

- [ ] **Step 1: Write the failing tests**

Add tests asserting, via `caplog`:
- A connect line carries `conn=` and `user=`.
- A disconnect line carries the same `conn=` value.
- A delivery line carries `conn=`, `user=`, and the originating `req=` from the envelope.
- Dispatch-task death logs at `ERROR` with the restart count.
- Permanent give-up logs at `ERROR` and says so explicitly.

- [ ] **Step 2: Run to verify they fail**

- [ ] **Step 3: Implement**

Mint the connection id at handshake (already on `Connection`), stable for the socket's life. Log connect, disconnect, and delivery with it.

**The correlation id must be read from the envelope's `req` field, never from a context variable.** The logging module already documents being bitten by a near-identical issue: middleware runs downstream work in a separate task, and a task gets a *copy* of the context, which is why `bind_user` mutates in place rather than re-setting. The dispatch task is worse than a copy — it is started at lifespan, lives independently of any request, and inherits nothing from any of them.

- [ ] **Step 4: Run to verify they pass**

- [ ] **Step 5: Commit**

---

# Phase 5 — Event vocabulary and the emit seam

## Task 10: Emit at the work-order routes

Events must fire after the change is durable. "After commit" is not currently a well-defined moment — commits happen in routers in some places and inside services in others, and `open-work.md` SCL-006 documents helpers that commit internally while callers keep working. Emission goes at the **router layer**, the one place where "this command is finished" is unambiguous today.

**Do not use a database commit hook.** The shared test fixture binds sessions to an outer transaction in `join_transaction_mode="create_savepoint"`, so **every commit under test is a savepoint release, not a real commit.** A commit-hook design would fire events in tests that never fire in production and vice versa.

**Files:**
- Modify: `backend/app/routers/work_orders.py`
- Test: `backend/tests/test_realtime_emit.py`

- [ ] **Step 1: Write the failing tests**

Assert that `update_work_order` (`routers/work_orders.py:474`), `complete_work_order` (`:536`), and `archive_work_order` (`:598`) each emit exactly one `work_order.changed` envelope carrying the work order id and the acting user, and that a route which raises before commit emits **nothing**.

- [ ] **Step 2: Run to verify they fail**

- [ ] **Step 3: Add the emit line to each route**

One visible line per mutating route, after the service call returns and the commit has happened. The accepted cost is that routers currently doing pure translation gain a second job, and that this is something you can forget to write — so **emission is a review-checklist item for any new mutating route.** Add that line to the repo's review checklist as part of this task.

- [ ] **Step 4: Run to verify they pass, and run the whole suite**

- [ ] **Step 5: Commit**

---

# Phase 6 — Client transport

## Task 11: The client transport module

A new foundation-layer module, peer to `api.js` — no DOM access, no view imports, wired at the composition root. Plain ES modules; no build step, no tooling change, no new dependency.

**Files:**
- Create: `backend/static/realtime.js`
- Modify: `backend/static/views/auth.js`, `backend/static/main.js`

**Interfaces:**
- Produces: `connectRealtime()`, `disconnectRealtime()`, `subscribe(eventType, handler)`, `setActivePageGetter(fn)`.

- [ ] **Step 1: Implement the transport**

Requirements, each load-bearing:

- **Reconnect with jittered backoff.** The free tier spins down when idle and every deploy drops every socket simultaneously, so disconnection is routine rather than exceptional. **Backoff must be jittered, not fixed** — in lockstep, every client retries as a thundering herd against a cold-starting instance, potentially forever. A small crew makes this minor today; it is trivial to get right up front and annoying to diagnose later.
- **Ignore your own echo.** Compare `envelope.actor` against the current user id and return early if they match. Without this, every write costs the writer an extra round trip — a UX-7 regression.
- **Silent failure, always (UX-5).** Refused handshake, rate-limited, closed mid-session, never connected at all — all invisible. No message, no indicator, no degraded mode, and **no connection-status UI of any kind** (UX-2).
- **On reconnect, refresh the active page.** There is no event log, no sequence numbering, and no resume cursor — P1 and P2 make refetch a complete recovery.

Connect from `enterApp` in `views/auth.js` (after the session is confirmed) and disconnect from `showLoginScreen` (`views/auth.js:170`).

- [ ] **Step 2: Verify no new UI exists**

```bash
cd backend && grep -rn "connected\|offline\|reconnect" static/*.html static/views/*.js | grep -iv "^static/realtime.js" | head
```

Expected: no user-visible strings introduced. UX-2 has no exceptions.

- [ ] **Step 3: Commit**

---

# Phase 7 — First consumer surface

## Task 12: Admin Review consumes the event

**Why this surface (D4):** its audience is the flat `["owner", "admin"]` gate, and `can_view_work_order` (`domain/work_orders.py:445`) short-circuits to `True` for Admin and Owner, so the per-row predicate is trivially satisfied rather than merely avoided. Its staleness is genuine — Supervisors move work orders into Review while an Admin works the queue.

**Its UX-6 safety is already built.** `loadAdminReview()` (`views/adminReview.js:116`) calls only `renderQueue()` and never touches `receiptSection`; `buildCard` (`:51`) re-applies the selection from `selectedDetail?.id`. A queue reload already preserves the open receipt and the selected card, and the existing Reopen handler depends on exactly that, deliberately. **Nothing has to be built to make the first surface UX-6-safe.**

**Files:**
- Modify: `backend/static/views/adminReview.js`

- [ ] **Step 1: Subscribe**

Register a handler for `work_order.changed` that calls `loadAdminReview()` **only when Admin Review is the active page**; otherwise mark dirty and let the existing on-activation loader in `nav.js` do the work it already does (D8: opt-in live refresh over a mark-dirty default).

This view keeps no `state.js` cache — it fetches on load — so the cache-freshness concept §10.3 introduces is **not needed here** and is deferred to Phase 8.

- [ ] **Step 2: Verification gate**

Every item below is a named requirement of §11. Check each explicitly and record the result:

- [ ] The queue updates live for a second user (two browsers, two accounts).
- [ ] With the socket blocked (DevTools → block `/ws`), the page behaves **exactly** as it does today.
- [ ] An open receipt survives a live queue refresh with its selection intact.
- [ ] Every log line from socket code carries connection identity and user.
- [ ] Fan-out is traceable from the originating request id.
- [ ] Every limit in Phase 3 has a test that fails when the limit is removed.
- [ ] **No new UI element exists anywhere.**
- [ ] **The local CSP check (precondition 4.2):** confirm in the browser console that the socket opens over `ws://localhost:8124`. CSP3's upgrade allowance names `https:` and `wss:`; local dev is `http:` → `ws:`, which is neither same-origin nor in that set. If it is blocked, state `connect-src` explicitly rather than weakening `default-src`. **Production over `wss:` is already confirmed permitted and needs no change.**
- [ ] Measure every threshold in the Global Constraints table against real behavior and record the actual numbers (D5).

- [ ] **Step 3: Commit**

---

# Phase 8 — Widening

Not tasks. Widening is additive: each surface is a new audience-map entry, emission at already-identified routes, and a subscription in one view. **No transport change.** If a surface requires transport changes, that is a signal the transport design was wrong, not that the surface is special.

Re-check every UX invariant per surface, particularly UX-6.

**The constraint that makes this harder than it looks:** there is no uniform way to detect an open interaction today. `state.js` uses module flags (`editingItemId`, `editingNotesItemId`), `tools.js` has `editingToolId`, and **User Requests keeps its state entirely in the DOM** — the open panel *is* `panel.innerHTML` and the picked item is `panel.dataset.pickedItemId`, with no flag to consult, while `render()` calls `listEl.replaceChildren()` unconditionally. Any view opting into live refresh must answer the busy question in its own terms. A uniform `isBusy()` predicate is the right answer for the first surface that genuinely needs one — User Requests will — and can be added then without changing the registration shape.

**Suggested order:** Saved Users (simple, low value) → Tools → Work Orders (highest value, hardest fan-out, the per-row predicate genuinely applies) → User Requests (form-heavy, needs busy-detection first).

---

## Self-review notes

**Spec coverage:** §4 preconditions → done pre-plan except the local CSP check, which is Task 12's gate. §5 → Tasks 5–6. §6 → Task 7. §7 → Tasks 2, 5, 8. §8 → Task 9. §9 → Task 10. §10 → Task 11. §11 → Task 12. §12 → Phase 8. §13 (messaging readiness) is a statement, not work; Tasks 4–6 preserve it via the typed envelope, the inbound seam, and the user-keyed registry.

**Not in the spec, found while planning:** Task 1 (the missing `websockets` dependency and the fact that no socket test can detect it) and Task 3 (the hash-keyed resolver D1 implies). Both are load-bearing.

**Deferred deliberately:** `state.js` cache freshness (§10.3) — the first surface keeps no cache, so it belongs to the first Phase 8 surface that does.
