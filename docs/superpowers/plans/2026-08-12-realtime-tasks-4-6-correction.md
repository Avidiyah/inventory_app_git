# Real-Time Tasks 4-6 Correction Record

**Status:** Tasks 4-8 are implemented on `feat/realtime-live-layer` on
2026-08-12; changes are uncommitted pending review. This record is authoritative
wherever the original implementation plan's Tasks 4-8 or 11 disagree with it.

## Why this correction exists

The first Tasks 4-6 draft had three architectural defects:

1. It put an `actor` user id in the envelope so a client could suppress its own
   echo. A user id cannot identify the originating tab or device, so suppression
   would also hide invalidations from the same user's other live screens.
2. It added JSON `ping`/`pong` messages even though Uvicorn already owns
   WebSocket protocol ping/pong. Two liveness systems create two timeout models
   and unnecessary application vocabulary.
3. It let the service registry hold and write a `WebSocket`, so queue overflow
   and shutdown could race the endpoint send pump with a second transport writer.

The corrected policy is: **always refresh on a relevant invalidation, use native
protocol liveness, and give the endpoint exclusive ownership of every socket
write.**

## Task 4 - pure policy

Implemented in `backend/app/domain/realtime.py` and
`backend/tests/test_realtime_domain.py`.

- The v1 envelope has exactly `type`, `id`, and `req`.
- The envelope contains identifiers only, never row data or an actor id.
- There is no application inbound vocabulary and no JSON heartbeat constant.
- `MAX_FRAME_BYTES` remains 65,536 bytes.
- `SHUTDOWN_CLOSE_GRACE_SECONDS` is 2 seconds. It bounds the service's wait for
  endpoint close acknowledgement; it is not a transport timeout.
- Audience rules remain pure and fail closed for unknown event types.

## Task 5 - registry, handoff, dispatch, and close ownership

Implemented in `backend/app/services/realtime.py` and
`backend/tests/test_realtime_registry.py`.

`Connection` stores identity, its bounded outbound queue, and close state. It
does **not** store a `WebSocket`. `request_close(code, reason)` is first-writer-
wins, so simultaneous overflow, revocation, and shutdown requests have a stable
cause.

The service layer never writes to a socket:

- fan-out queue overflow deregisters the connection and requests close `1013`;
- shutdown requests close `1001` for every connection;
- the endpoint acknowledges final cleanup through `connection.closed`;
- shutdown waits at most `SHUTDOWN_CLOSE_GRACE_SECONDS` for acknowledgements.

The existing bounded thread-to-loop handoff remains non-blocking and drops the
newest event when full. The dispatch task remains supervised with bounded
restarts. All state remains process-local, so the single-instance deployment
constraint is still load-bearing.

## Task 6 - endpoint and production transport policy

Implemented in `backend/app/routers/realtime.py`, `backend/entrypoint.sh`, and
the endpoint/dependency tests.

Handshake order is strict:

1. Require exactly one valid `Origin` and one `Host`, normalize default ports,
   and compare the Origin to the request-derived scheme and host.
2. Read and hash the existing session cookie.
3. Resolve the active session on a worker thread using a short-lived DB session.
4. Reserve a per-user connection slot.
5. Accept the WebSocket and start its receive/send/close-wait tasks.

Failures before acceptance are HTTP denial responses: Origin failure is `403`,
missing or invalid authentication is `401`, and the per-user cap is `429`.
Origin is checked before cookie hashing or database access.

After acceptance, application frames up to 65,536 bytes are inert. The socket
never mutates state. Larger frames request close `1009`. The endpoint cancels
and joins the send pump before it writes any requested close frame, preserving a
single transport writer.

Production Uvicorn is explicit rather than dependent on defaults:

```text
--ws-max-size 65536 --ws-ping-interval 30 --ws-ping-timeout 30
```

The `websockets==15.0.1` requirement is a verified compatibility pin for the
current Uvicorn version, not a claim that it is the latest available release.

## Task 7 - periodic session revalidation

Implemented in `backend/app/routers/realtime.py`, with coverage in
`backend/tests/test_realtime_session_binding.py`,
`backend/tests/test_realtime_endpoint.py`, and
`backend/tests/test_realtime_domain.py`.

Every accepted connection now runs an authorization-maintenance task beside its
receive loop, send pump, and close waiter. It sleeps for
`REVALIDATE_INTERVAL_SECONDS` after the handshake, then repeatedly re-resolves
the stored token hash through `_resolve_identity` on a worker thread. That
helper opens and closes a fresh short-lived database session and returns only
the primitive `(user_id, role)` pair, so neither a pooled connection nor an ORM
object is retained for the socket lifetime.

Revalidation is exact and fail-closed:

- the resolved user id and role must both match the handshake identity;
- a missing, expired, or revoked session requests close 1008;
- unexpected identity or role drift also requests 1008 rather than mutating the
  connection's cached audience;
- resolver/database failure requests close 1011 and re-raises so the existing
  connection-failure log retains the cause.

All closes still travel through `Connection.request_close`. The AnyIO task group
cancels and joins the send pump before the endpoint writes the close frame, so
Task 7 preserves Task 6's single-transport-writer rule. There is no JSON
heartbeat; Uvicorn remains the sole owner of ping/pong liveness.

## Task 8 - handshake and inbound-frame rate limiting

Implemented in `backend/app/services/realtime_limits.py`,
`backend/app/services/realtime.py`, and `backend/app/routers/realtime.py`, with
coverage in `backend/tests/test_realtime_limits.py`.

The handshake counter runs after same-origin validation but before cookie
rejection or database resolution. It reuses the existing caller-key function,
has state separate from the HTTP request limiter, allows exactly 10 attempts per
caller per 60 seconds, and returns a pre-accept HTTP `429` with `Retry-After` on
the next attempt. Rejections do not extend the lockout; idle caller buckets are
swept and raw session tokens are never stored.

Each accepted connection owns its inbound timestamp deque. Acceptable-size text
and binary frames are limited to exactly 20 per second; the next requests close
`1008`. The existing size check runs first and therefore retains deterministic
`1009` precedence. Close requests still flow through the endpoint-only writer.

## Consequences for later tasks

- **Task 7:** implemented as periodic, exact-identity, fail-closed session
  revalidation. Transport liveness remains owned by Uvicorn.
- **Task 8:** implemented as separate handshake-attempt and per-connection
  inbound-frame-rate limits. Frame size, per-user capacity, and send-queue
  backpressure remain the existing implementations.
- **Tasks 10-12:** emit/build the three-field envelope. Clients refresh for every
  relevant invalidation, including one caused by the same user; there is no
  `envelope.actor` suppression.

## Verification completed in this pass

- Task 4 focused tests: 10 passed.
- Task 5 focused tests: 25 passed.
- Combined Tasks 4-8 real-time tests after correction: 79 passed.
- Task 8 focused tests: 13 passed; HTTP rate-limit regression tests: 53 passed.
- Full backend suite: 789 passed with two known Uvicorn/websockets legacy
  deprecation warnings.
- Endpoint coverage includes Origin rejection/order, 401/429 HTTP denials,
  registration cleanup, frame boundaries, end-to-end dispatch, a forced
  send/close race, and periodic invalid-session closure.

The remaining verification gate is the existing owner-run real-server/browser
smoke test. TestClient cannot prove that Uvicorn's actual network protocol stack
upgrades a connection.
