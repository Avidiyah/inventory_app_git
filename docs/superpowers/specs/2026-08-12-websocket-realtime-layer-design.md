# Real-Time Layer — Reference Design

**Status: decisions resolved 2026-08-12 (see §14). Phases 1–2 are being planned;
nothing is implemented.**

Written 2026-08-12 against `90be427`. This document exists to be read before any
real-time work is planned. It is deliberately abstract: it describes behavior,
responsibilities, and sequencing, not implementations.

Amended 2026-08-12 at `32c8c92`: the eight open decisions in §14 are answered,
the route count in §2/§3/§5.2 is corrected from 97 to 75, and §4.2 is resolved
for production. Behavior described elsewhere is unchanged.

It does not live in `docs/`. That directory is the four consolidated files from
2026-08-10 and `open-work.md` remains the only backlog. This is a design
reference, not an open item; if any part of it is ever promoted to actual work,
it gets an entry in `open-work.md` like anything else.

---

## 1. The governing constraint

**Nothing about the application's behavior or appearance changes, except that
data on screen stops being stale.**

This is not a stylistic preference. It is the constraint that every step below
is checked against, and it is what makes the whole change reviewable — if a step
alters what a user sees, does, or is permitted to do, that step is wrong.

Stated as testable invariants:

| # | Invariant |
|---|---|
| UX-1 | Every page behaves identically with the socket disconnected. The socket supplements on-activation loading; it never replaces it. |
| UX-2 | No new UI. No new nav entries, buttons, badges, toasts, banners, counters, or indicators — including connection-status indicators. |
| UX-3 | No workflow gains or loses a step. Nothing that took three clicks takes two or four. |
| UX-4 | No permission changes. The socket can reveal nothing the REST layer would not already return to that user. |
| UX-5 | No user-facing errors, ever. Socket failure is silent and invisible; the app degrades to exactly today's behavior. |
| UX-6 | A live refresh never discards uncommitted user input or disturbs an in-progress interaction. |
| UX-7 | No new perceptible latency on any existing action. |

**UX-6 deserves emphasis** because it is the easiest to violate accidentally. If
a user has an item editor open, a notes field half-typed, or an active scan
session, and an incoming event triggers a naive reload, their work is destroyed.
That is a worse user experience than the staleness being fixed. Any surface that
consumes events must define what it does while an interaction is open — the
default answer being *defer until the interaction completes*.

UX-2 is the second easiest to violate. "Real-time" invites announcements — *"3
new requests"*, a green connected dot, a toast on every change. All of those are
user experience changes. Data freshens; it does not narrate.

---

## 2. What exists today

Established by inspection at `90be427`:

- **No push, no polling.** Zero occurrences of `setInterval`, `EventSource`, or
  `WebSocket` in `backend/static/`. No ASGI websocket route anywhere.
- **Data enters the SPA at two triggers only:** page activation via `showPage()`
  in `static/views/nav.js`, which calls each page's loader; and explicit user
  action (search, submit, scan).
- **Views share module-level caches** in `static/state.js` across module
  boundaries, so a stale snapshot can be read by a view that never fetched it.
- **The only staleness measure is HTTP-cache bypass** — `liveGet` in
  `static/api.js` uses `cache: "no-store"`. That fixes stale responses, not
  stale screens.
- **The backend is entirely synchronous.** 75 sync route handlers, zero
  `async def`, with the choice documented explicitly in at least two routers.
  (The "97" written here originally was wrong when written, not drifted into;
  re-verified as 75 `APIRoute`s at `c7531ea`.)
- **All three middleware layers are HTTP-scope only** (`app/main.py`): rate
  limiting, security headers, request logging.
- **Authorization primitives already exist** and are reusable without change:
  `domain/work_orders.can_view_work_order` (pure, no I/O) and the role gates in
  `auth_deps.py`.
- **Deployment is a single free-tier instance**, one uvicorn worker, no
  `--workers` flag, spun down when idle.

---

## 3. Architectural principles

Five rules. Each one is load-bearing for something specific; the consequence of
abandoning it is named.

### P1 — The socket is never the system of record

Every fact delivered over the socket must already be durable in Postgres and
already reachable over REST. The socket is a delivery accelerator, never a
source of truth.

*Why it is load-bearing:* it makes aggressive backpressure safe (§7.5), it makes
reconnect-and-refetch a complete recovery story, and it is the single rule that
keeps future messaging additive rather than a rewrite.

*If abandoned:* dropping a slow client's queue means losing user data, which
forces unbounded buffering, which makes the worst network on the crew a
server-side memory risk.

### P2 — Broadcast invalidation, not payloads

Events carry *what changed*, not *what it now is*. Recipients decide whether they
care and re-fetch through the existing API functions, which re-run the server's
own scoping.

*Why it is load-bearing:* it makes the socket structurally incapable of leaking
anything REST would not already return, satisfying UX-4 by construction rather
than by discipline. Every fan-out decision stops being a leak decision.

*If abandoned:* every event type needs its own independently-audited
authorization review, and the surfaces most worth pushing are the sensitive ones
— billing figures, notes, names, request text.

### P3 — REST remains the only way state changes

The socket never mutates anything. Not in v1, not when messaging arrives —
messages are written over REST and *announced* over the socket.

*Why it is load-bearing:* every existing validation, permission gate, audit
trail, and error path stays on one code path. No business rule acquires a second
enforcement site.

### P4 — Degradation is invisible

A user with a dead socket sees exactly today's application. This means the
existing on-activation loading is never removed or weakened as part of adopting
real-time.

*Why it is load-bearing:* it is UX-1 and UX-5 together, and it is what makes the
free tier's guaranteed disconnections (spin-down, deploys) a non-event.

### P5 — Explicit over ambient

There is one socket endpoint. Enforcement, logging, and limits are written
visibly in it rather than hidden in middleware.

*Why it is load-bearing:* middleware exists to avoid repetition across 75 routes.
With one endpoint, explicit enforcement is complete by inspection — you can read
one file and know the entire policy. The cost is that nothing is inherited
automatically, which is precisely why §7 and §8 exist as their own phases.

---

## 4. Phase 0 — Preconditions

Nothing below starts until these are true.

### 4.1 The working tree is clean — **met at `32c8c92`**

*Problem solved:* a real-time change and an unrelated feature must not share one
diff through a gate that deploys to production.

*Behavior:* none. Process only.

*Resolved:* the pending SEC-020 / SEC-021 / PRO-021 entries and this document
were committed as a docs-only change at `32c8c92`. Re-check before starting
implementation; this is a property of the moment, not a permanent state.

### 4.2 CSP permits the connection — **resolved for production, open for local**

*Problem solved:* the page's own Content-Security-Policy governs whether a socket
may be opened. The policy declares `default-src 'self'` with no explicit
`connect-src`, so WebSocket connections fall back to `default-src`. Modern
browsers treat `'self'` as covering same-origin `wss:`, but this policy was
verified clause by clause when written and should not acquire its first assumed
clause now.

*Resolved for production:* CSP Level 3 states that `connect-src` governs
WebSocket and falls back to `default-src`, and that **`'self'` matches the
`https:` and `wss:` variants of the page's origin, even on pages whose scheme is
`http`**. Production is served over HTTPS (`COOKIE_SECURE`), so `wss:` to the
same origin is permitted by the policy as it stands. **No CSP change is
required.**

*Still open for local development, and this is the trap:* the spec's upgrade
allowance names `https:` and `wss:` specifically. Local development runs
`http://localhost:8124` and would open **`ws:`**, which is neither same-origin
(the scheme differs) nor in the upgrade set. Under a strict reading the socket
could be blocked locally while working in production — the most confusing
possible failure shape, since local is where it gets debugged. Browsers have
historically been lenient here, but that is precisely the assumption this
precondition exists to refuse.

*Behavior:* verify in the browser the first time Phase 1 connects locally. If
blocked, state `connect-src` explicitly rather than weakening `default-src`. Not
resolvable by reading the repository.

### 4.3 The multi-instance note is updated

*Problem solved:* `open-work.md` N3 records that the in-process rate limiter is
the first thing to inherit the undecided multi-instance story. The connection
registry becomes the second, and a worse one — a second instance does not degrade
delivery, it silently halves it. Users on instance A would never see events from
B.

*Behavior:* documentation only. Recording it now is the difference between a
known constraint and a production mystery.

### 4.4 The documentation home is decided — **resolved (D7)**

*Problem solved:* `docs/endpoint-map.md` documents "every endpoint traced
DB↔view". A persistent bidirectional channel is not an endpoint in that sense —
it is a second transport. Adding a fifth file to `docs/` contradicts the 2026-08-10
consolidation.

*Resolved:* **no fifth file.** This design stays in `docs/superpowers/` as a
reference; implemented behavior is documented in `docs/current-state.md`; work
that is actually scheduled gets an `open-work.md` entry like anything else. The
2026-08-10 four-file shape is preserved.

*Behavior:* documentation only.

---

## 5. Phase 1 — Transport skeleton

The goal is a socket that connects, authenticates, and stays open. It carries no
application data yet.

### 5.1 Application lifespan

*Problem solved:* fan-out requires a long-lived background task, and the app
currently has no startup or shutdown hooks at all.

*New behavior:* something now starts with the app and stops with it. `main.py`'s
stated boundary — "this file does four things and nothing else" — widens to five,
which should be a deliberate edit to that docstring rather than a silent
contradiction of it.

*Does not change:* request handling, routing, or any existing startup ordering.

### 5.2 The sync/async boundary

*Problem solved:* the app is entirely synchronous; 75 handlers run in a
threadpool. Sockets live on the event loop. A threadpool handler cannot `await` a
broadcast.

*New behavior:* the first genuine concurrency boundary in the codebase — a
thread-safe handoff from request threads into the event loop, drained by the
background task.

Two properties are mandatory:

- **Non-blocking.** A request thread must never wait on a socket. If it can, a
  phone on bad wifi can stall an inventory write, violating UX-7.
- **Bounded.** The handoff buffer has a ceiling, and overflow behavior is a
  designed decision (drop, oldest-first) rather than an accident. P2 makes
  dropping safe.

*Does not change:* the synchronous style of any existing handler. Nothing is
converted to `async def`.

### 5.3 The connection registry

*Problem solved:* fan-out needs to know who is connected.

*New behavior:* an in-process map of `user_id → set of connections`. Keyed by
user rather than by session, because one person on two devices must receive on
both — and because a flat set of sockets supports broadcast only, while a keyed
map supports broadcast, targeted delivery, multi-device, and per-user revocation.

*Note:* this shape is chosen now specifically so that messaging later is additive.
It costs nothing extra today.

### 5.4 The endpoint and handshake authentication

*Problem solved:* a socket must be attributable to a user before it receives
anything.

*New behavior:* one endpoint. Authentication reuses the existing session cookie
and the existing session resolver — no new token scheme, no new credential, no
change to how anyone logs in. The cookie rides a same-origin handshake
automatically.

Unauthenticated handshakes are refused immediately, before any expensive work.

*Does not change:* the login flow, session lifetime, cookie attributes, or any
`/auth` route.

### 5.5 The message envelope

*Problem solved:* the wire format is the hardest thing to change later, because
every client and every emitter depends on it.

*New behavior:* a typed envelope with a discriminating `type` field from day one,
even while only one type exists. Envelopes carry a correlation id (see §6.2) and
an actor id (see §8.4).

*Forward-compatibility note:* the endpoint accepts client→server frames from the
start — even if v1 handles nothing but heartbeats. A strictly one-way socket has
no seam at which to later add message send, inbound validation, or inbound rate
limiting. This is the cheapest forward-compatibility decision in the document and
the most expensive one to retrofit.

---

## 6. Phase 2 — Connection lifecycle and session binding

A socket that outlives its authorization is a security defect. This phase closes
that before any application data flows.

### 6.1 Heartbeat

*Problem solved:* TCP does not reliably tell you a peer is gone. A phone that
walks into a dead zone leaves a half-open connection the server still believes in.

*New behavior:* periodic liveness exchange; unresponsive connections are closed
and deregistered.

*Why it is more than hygiene:* the concurrency cap in §7.2 is only as correct as
the registry's view of what is alive. Enough zombie entries and a legitimate user
is locked out by their own dead sockets. The heartbeat is what makes that cap
enforceable.

*Does not change:* anything visible. Heartbeats are protocol-level.

### 6.2 Authorization is no longer re-checked per request

*Problem solved — and this is the most important item in the document.*

Today, every request re-resolves the session and re-checks the role, so
revocation is instant and automatic. `services/users.py` calls
`revoke_user_sessions` in three places — archive, role change, password reset —
and it works because the *next request* fails.

A socket authenticated once at handshake has no next request:

- Demote a Supervisor to Technician and their open socket keeps streaming
  Supervisor-scoped events.
- Archive a user and their socket keeps receiving.
- Sessions carry a hard 12-hour absolute cap that a socket would simply outlive.

*New behavior:* connections are bound to session validity — closed on
revocation, on role change, and at session expiry. **Resolved (D1): by periodic
revalidation against a stored token hash**, which covers all three revocation
paths because each deletes the session row. See §14 for why this beat an
explicit signal from the revoking code paths.

*Does not change:* who is permitted to do what. It preserves the property the app
already has and would otherwise silently lose.

### 6.3 Deregistration on close

*Problem solved:* leaked registry entries consume concurrency-cap slots and
produce phantom fan-out targets.

*New behavior:* every close path — clean, error, timeout, revocation, shutdown —
removes the connection. Shutdown closes all connections deliberately rather than
dropping them, so clients see a clean close and reconnect on their own schedule.

---

## 7. Phase 3 — Resource and abuse control

Five distinct problems. The existing HTTP limiter addresses one shape of one of
them, and none of it applies automatically, because the handshake arrives as a
`websocket` scope and never enters HTTP middleware — including at handshake time,
despite the handshake being an HTTP GET on the wire.

Numbers below are starting hypotheses. Per the standing rule in `open-work.md`
— *ask what the number actually is before building what an item describes* — each
is to be measured against real behavior before being trusted.

### 7.1 Handshake attempt limiting

*Problem solved:* connection churn. The real-time layer introduces the most
likely retry loop in the entire application — reconnect-with-backoff is new
client code, nothing in the SPA currently retries on a schedule, and free-tier
spin-downs guarantee that path runs constantly rather than rarely. A broken
backoff can open and drop sockets as fast as it spins, entirely uncounted.

*New behavior:* attempts are counted per caller.

Two design points:

- **Reuse the existing caller-identity function unchanged.** It already hashes
  the session token (so a live credential never enters a process-wide dict) and
  already falls back to client address for unauthenticated callers. The socket
  object exposes everything it needs.
- **Do not reuse the existing budget.** 60-per-*second* is calibrated for page
  loads; sixty socket opens per second is a catastrophe that sails through it.
  Connection establishment is expensive and rare, which is the login-throttle
  problem shape, not the request-limiter one. Sharing the bucket would also let
  socket churn consume the budget the user's actual inventory writes need.

*Starting point:* order of ten attempts per minute per caller.

*Protocol note:* there is no `Retry-After` on a WebSocket close. The server closes
with a policy code; the client must derive its own wait. Backoff correctness
therefore lives in the client — the same code most likely to be buggy — so any
wait hint must ride in an application frame before the close.

### 7.2 Concurrent connection cap

*Problem solved:* steady-state resource consumption, and the residual churn that
survives §7.1. It bounds accumulation rather than arrival rate: a loop that
squeaks past the attempt limiter still hits a ceiling and stays there.

*New behavior:* a per-**user** ceiling on simultaneous connections, checked at
accept time against the registry built in §5.3. Per user rather than per session,
because phone-plus-desktop is legitimate and multi-device delivery requires both.

*Cost:* near zero — the registry exists regardless, so this is a size check.

*Dependency:* correctness requires §6.1.

*Starting point:* 5–8 per user, against a small crew with a few devices each.

### 7.3 Inbound frame rate limiting

*Problem solved:* an established socket can send frames at unbounded rate. No
path, no middleware, no counter sees it. This only bites once messaging exists,
but the seam belongs in v1 — retrofitting a limiter into an established message
loop is exactly the kind of change this design is trying to avoid.

*New behavior:* a per-connection sliding window.

*Implementation note:* the existing rate-limit domain module already implements
this window as pure, unit-tested functions; they read their cap and window from
module constants rather than parameters. **Parameterize rather than fork.** The
reason is specific: the over-limit check documents an off-by-one that makes
exactly N requests succeed rather than N−1, and a hand-written second copy is a
coin flip on reintroducing that bug in the one module whose purpose is being the
single place the rule is written. The result is one implementation, two named
policies.

*Starting point:* order of 20 frames per second sustained per connection — far
above human typing, far below a loop.

### 7.4 Frame size limiting

*Problem solved:* an unbounded inbound frame. Absent entirely today; the server's
default ceiling is measured in megabytes.

*New behavior:* a server-level maximum plus an application-level length check.

*Precedent:* the existing upload helper establishes the pattern, including the
reasoning worth copying — it checks the declared size as an optimization *and*
bounds the read as the actual guarantee, because neither alone is sufficient.

*Starting point:* order of 64 KB. A chat message needs kilobytes.

### 7.5 Outbound backpressure

*Problem solved:* the one with no HTTP analogue, and the one least safe to skip.
Nothing above protects the server from a *slow* client. A phone on one bar cannot
drain what it is sent; the send buffer grows with no ceiling and no counter
watching. It is not abuse — it is a bad connection — which is exactly why a rate
limiter never catches it.

*New behavior:* a bounded per-connection send queue that, on overflow, **closes
the connection rather than buffering**. The client reconnects and refetches.

*Why this is safe rather than reckless:* P1 and P2 together. Invalidation events
are disposable by design. Messages are not disposable but do not need to be,
because they are durable in Postgres and reachable over REST. Closing a slow
client is lossless in both cases.

*Does not change:* anything the user perceives. A dropped connection is
indistinguishable from the spin-downs and deploys that will happen anyway, and
P4 guarantees the app still works.

### 7.6 Where enforcement lives

Pure policy in `domain/` — parameterized, no clock, no I/O, unit-testable exactly
like the existing limiter and throttle. Counters and registry in `services/`.
Enforcement written visibly in the endpoint, per P5. Frame size is partly server
configuration. Backpressure belongs to the connection object itself.

**Reused unchanged:** caller identity, sliding-window math, the login-throttle
backoff shape, the two-check upload pattern.
**Genuinely new:** a slower attempt counter, the concurrency cap, the send-queue
bound.

---

## 8. Phase 4 — Observability

The app's existing observability bar is high and deliberate. None of it is
inherited. All of it has to be re-earned explicitly.

### 8.1 Connection identity

*Problem solved:* the logging formatter reads a request-scoped context variable
at format time and stamps a request id onto every line. Outside a request scope
it emits a placeholder, and the user-binding helper is an explicit no-op outside a
request scope.

Concretely: **every log line from socket code would be both un-correlatable and
un-attributable** — present in the stream, greppable by nothing, attached to no
one. That is worse than not logging. Absent lines get noticed; anonymous lines
look fine until the day you need them.

*New behavior:* a connection identity — minted at handshake, stable for the
socket's life, carrying the user — logged on connect, disconnect, and delivery.

*Why not simply port the middleware:* the shape does not match. HTTP is one id per
request, born and retired in milliseconds. A socket is one long-lived entity
generating many events over hours. This is a second identity model alongside the
existing one, not a copy of it.

There is also no response header to hand back. After the upgrade there are none,
so the "user reports it broke around 2:15" workflow needs a different handle.

### 8.2 Causal correlation

*Problem solved:* debugging *"why did that person's screen not update"* means
following one write through to N deliveries.

*New behavior:* the originating request id travels with the emitted event, so an
HTTP write and its fan-out are one traceable chain.

*Trap worth recording:* the logging module already documents being bitten by a
near-identical issue — middleware runs downstream work in a separate task, and a
task gets a *copy* of the context, which is why user-binding mutates in place
rather than re-setting. The dispatch task is worse than a copy: it is started at
lifespan, lives independently of any request, and inherits nothing from any of
them. **Request context cannot reach it through a context variable under any
circumstances.** The id must travel inside the event as ordinary data. Anyone
reasoning "context variables propagate, this is fine" gets anonymous log lines
and will not notice, because the lines still appear.

### 8.3 Supervision of the background task

*Problem solved:* the request logger wraps the whole stack and logs every
unhandled exception before re-raising, so every failure in the app produces a
diagnosable artifact. The dispatch task has no equivalent. A bare task that raises
with nothing awaiting it produces, at best, a generic loop warning — no
correlation, no user, no event.

The failure mode: **the dispatch task dies, real-time silently stops working for
every connected user, HTTP keeps serving perfectly, health checks stay green, and
nothing says so.**

*New behavior:* the task is supervised — its death is logged loudly in the app's
own format, and its restart policy is explicit.

### 8.4 Event attribution

*Problem solved:* a client should not re-fetch in response to its own write.

*New behavior:* events carry the acting user, and clients ignore their own echo.
This is also a UX-7 protection — without it, every write costs the writer an
extra round trip.

---

## 9. Phase 5 — Event vocabulary and the emit seam

### 9.1 The emit seam

*Problem solved:* events must fire after the change is durable, and "after commit"
is not currently a well-defined moment. Commits happen in routers in some places
and inside services in others, and `open-work.md` SCL-006 documents helpers that
commit internally while callers keep working.

*New behavior:* explicit emission at the router layer — the one place where "this
command is finished" is unambiguous today.

*Why not a database commit hook:* the test suite would lie. The shared fixture
binds sessions to an outer transaction in savepoint mode, so **every commit under
test is a savepoint release, not a real commit.** A commit-hook design would fire
events in tests that never fire in production and vice versa.

*Accepted cost:* a visible line per mutating route, and routers that are currently
pure translation gain a second job. The trade is honesty and testability in
exchange for something you can forget to write. Emission is therefore a
review-checklist item for any new mutating route.

### 9.2 The audience vocabulary

*Problem solved:* who receives what, without inventing a second authorization
system.

*New behavior:* a small mapping from event type to audience, built entirely from
primitives that already exist:

| Event | Audience | Existing primitive |
|---|---|---|
| Work order changed | users who may see that work order | the pure visibility predicate in `domain/work_orders.py` |
| Item / tool stock changed | any authenticated session | all roles already reach these pages |
| Operational request changed | Admin and Owner | the existing role gate |

*Note:* because of P2, a mis-scoped audience is a wasted message rather than a
disclosure — the recipient's re-fetch is still authorized server-side. The
audience map is an efficiency and noise concern, not the security boundary. The
security boundary is the REST layer, unchanged.

### 9.3 What never goes over the wire

Row payloads (P2). Anything from the auth surface. Session state. Credentials.

---

## 10. Phase 6 — Client transport

### 10.1 The client module

*Problem solved:* the SPA needs one place that owns the connection.

*New behavior:* a new foundation-layer module, peer to the existing API client —
no DOM access, no view imports, wired at the composition root. Plain ES modules;
no build step, no tooling change, no new dependency.

### 10.2 Reconnection

*Problem solved:* the free tier spins down when idle and every deploy drops every
socket simultaneously. Disconnection is routine, not exceptional.

*New behavior:* automatic reconnect with backoff — genuinely new client
complexity, since nothing in the SPA currently retries anything on a schedule.

**Backoff must be jittered, not fixed.** A deploy drops every client at once; in
lockstep they retry as a thundering herd against a cold-starting instance,
potentially forever. A small crew makes this minor today, and it is a trivial
property to get right up front and an annoying one to diagnose later.

On reconnect, the client refreshes the active page. There is no event log, no
sequence numbering, and no resume cursor — P1 and P2 make refetch a complete
recovery.

### 10.3 Subscription and cache freshness

*Problem solved:* views need to react without every view learning about sockets.

*New behavior:* views register interest; the transport routes events to them.
`state.js` gains one concept it does not have — cache freshness. Its caches are
currently bare arrays with accessors and no notion of being stale.

*The minimal-change path:* an event for a page that is not active marks its cache
dirty; the existing on-activation loader in `nav.js` does the work it already
does. This reuses machinery rather than adding a second refresh path, and it means
inactive pages cost nothing.

### 10.4 Silent failure

*Problem solved:* UX-5.

*New behavior:* every socket failure — refused handshake, rate-limited, closed
mid-session, never connected at all — is invisible to the user. No message, no
indicator, no degraded mode. The app is simply the app it is today.

---

## 11. Phase 7 — First consumer surface

*Problem solved:* proving the entire path end-to-end before widening.

*New behavior:* exactly one view consumes exactly one event type.

*Selection criteria:* the simplest possible audience (no per-row predicate),
genuine staleness cost, and low interaction risk under UX-6 — a queue nobody is
mid-edit in is safer than a form-heavy page.

*Resolved (D4): **Admin Review** (`static/views/adminReview.js`, 179 lines).*

It wins on all three criteria. Its audience is the flat `["owner", "admin"]`
gate, and `domain/work_orders.can_view_work_order` short-circuits to `True` for
Admin and Owner, so the per-row predicate is trivially satisfied rather than
merely avoided. Its staleness is genuine — Supervisors move work orders into
Review while an Admin sits on the page working the queue.

Its UX-6 risk is the lowest in the application: **the page has no text input at
all.** The interaction surface is click-a-card, Reopen, Close. And the safety
property is already built — `loadAdminReview()` calls only `renderQueue()` and
never touches `receiptSection`, while `buildCard` re-applies the selection from
`selectedDetail?.id`. **A queue reload already preserves the open receipt and
the selected card**, and the existing Reopen handler depends on exactly that,
deliberately, with a comment saying the receipt remains available. Nothing has
to be built to make the first surface UX-6-safe.

*Not the User Requests queue*, which this document originally implied. At
`c7531ea` it became form-heavy — inline edit forms, a fulfil panel with a mode
switch and item search, sibling checkboxes — and its in-progress state lives
**entirely in the DOM** (`panel.innerHTML`, `panel.dataset.pickedItemId`), with
no module-level flag to consult. Its `render()` calls `listEl.replaceChildren()`
unconditionally, destroying every open panel. It is a Phase 8 surface, and a
late one.

*Explicitly not first:* the work orders **page**. Highest value, hardest
fan-out, largest file in the repo (`views/workOrders.js`, 1,455 lines). Admin
Review consumes a work-order event without being that page; the §11 exclusion is
about the fan-out predicate and the file, neither of which applies here.

*Verification at this gate:*

- The surface updates live for a second user.
- With the socket blocked, the surface behaves exactly as it does today.
- Every log line from the socket carries connection identity and user.
- Fan-out is traceable from the originating request id.
- Every limit in §7 has a test that fails when the limit is removed.
- No new UI element exists anywhere.

---

## 12. Phase 8 — Widening

*Problem solved:* the remaining stale surfaces.

*New behavior:* one surface at a time, each re-checked against every UX invariant
in §1 — particularly UX-6, since form-heavy and scanner-driven pages are where a
naive refresh destroys work.

Widening is additive: each surface is a new audience-map entry, emission at
already-identified routes, and a subscription in one view. No transport change. If
a surface requires transport changes, that is a signal the transport design was
wrong, not that the surface is special.

---

## 13. Phase 9 — Messaging readiness

No work. A statement of what the preceding phases already make true, so that
future messaging is additive.

**Already in place:** bidirectional framing with an inbound dispatch seam;
per-user, multi-device addressed delivery; a typed envelope; connection identity
and correlated logging; inbound rate and size limits; backpressure that is safe
because delivery is never the system of record.

**What messaging still requires, all additive:** new tables, new REST endpoints
for send and history, new event types, and a view. Presence and typing indicators
are the first things that legitimately live only on the wire, being genuinely
ephemeral — and they are the only exception to P1 in this document.

**What would break additivity if skipped now:** a one-way socket (no inbound
seam), a flat connection set (no targeted or multi-device delivery), an untyped
envelope (no room for a second message type), or treating the socket as
authoritative (forces unbounded buffering, per P1).

---

## 14. Decisions — resolved 2026-08-12

All eight are answered. Each entry records the choice and the reason it beat the
alternatives, so a later reader can tell a decision from a default.

| # | Decision | Resolution |
|---|---|---|
| D1 | Session-binding mechanism (§6.2) | **Periodic revalidation by stored token hash.** Close the connection when the re-resolve returns `None`. |
| D2 | Dispatch-task restart policy (§8.3) | **Supervised, bounded restarts, then permanent stop** — logged loudly in the app's own format. |
| D3 | Handoff overflow behavior (§5.2) | **Drop newest**, log and count. |
| D4 | First surface (§11) | **Admin Review.** See §11. |
| D5 | Every threshold in §7 | **Adopted as named constants with the hypothesis recorded beside each**, measured at the §11 gate rather than trusted. |
| D6 | Backpressure scope | **In v1**, and it lands in Phase 1 rather than Phase 3 — see below. |
| D7 | Documentation home (§4.4) | **No fifth file.** See §4.4. |
| D8 | Active-page refresh policy under UX-6 | **Opt-in live refresh over a mark-dirty default.** See below. |

### D1 — why revalidation rather than an explicit signal

Revalidation has **complete coverage**, which was not obvious until the
revocation paths were read. All three — `archive_user`, `update_role`, and
`reset_password` (`services/users.py:156,178,251`) — call
`revoke_user_sessions`, which **deletes** the rows (`services/auth.py:160`). A
re-resolve therefore returns `None` for role change, archival, and password
reset alike, and checks the 12-hour cap on the same call. One mechanism catches
every case §6.2 names.

It is also cheap in a way that was worth verifying rather than assuming:
`get_active_session_user` (`services/auth.py:200`) is a **pure read** — its own
docstring states "There is no idle timeout and no per-request write." So
revalidation slides nothing and costs two queries per connection per interval.

The decisive argument is that **security does not depend on the sync→async
signal path being correct.** That path is being built anyway for events, but a
missed signal there would be a silent security hole rather than a missed
refresh. Revalidation fails closed.

*The explicit-signal alternative has a specific trap that ruled it out as the
primary mechanism:* `revoke_user_sessions` deliberately **does not commit** —
"the caller folds this into its own transaction." A signal fired from the
service layer fires before commit and could close sockets for a revocation that
then rolls back. It would have to be emitted at the router layer after commit,
per §9.1, which is more moving parts for a promptness gain that has not been
shown to matter.

*Accepted cost:* revocation lags by up to one revalidation interval. Add the
signal later as an optimization if that lag is ever demonstrated to matter — the
shape does not change.

*Implied work not in the original design:* `get_active_session_user` takes the
**raw** token and hashes it internally. Holding raw tokens in the connection
registry for hours would contradict the precedent §7.1 praises — the
caller-identity function hashes the token so that a live credential never enters
a process-wide dict. **Revalidation needs a hash-keyed sibling resolver in
`services/auth.py`**, so the registry stores only the hash. This is a change
outside socket code and belongs in the Phase 2 plan.

### D2 — why bounded restarts

A transient failure should not kill real-time for hours; a crash loop must not
look like healthy operation, which is the silent-failure mode §8.3 names. Bounded
restarts separate the two: the first case self-heals, the second stops and says
so. Free-tier spin-down provides a clean slate on the next cold start regardless,
which bounds the blast radius of the permanent-stop state.

### D3 — why drop newest

`put_nowait`, catch the full-queue error, increment a counter, log. It can never
block a request thread, which is UX-7. P2 makes the drop safe — the client's next
page activation refetches through REST. Drop-oldest buys marginally better
freshness under sustained overflow at the cost of an evicting structure, and the
counter is what actually tells you the ceiling is wrong. Closing connections is
the wrong lever entirely: this queue is shared across all connections, so one
busy moment would disconnect everyone.

### D6 — backpressure moves into Phase 1

§7.5 places backpressure in Phase 3, but it belongs to the connection object and
the connection object is built in §5. Deferring it accepts an unbounded
server-side memory risk driven by whoever has the worst signal on the crew — and
a rate limiter structurally cannot catch a slow client, because a bad connection
is not abuse. P1 and P2 make closing such a client lossless. **The bounded
per-connection send queue is built in Phase 1 alongside the connection object,
not retrofitted into an established send path later.**

### D8 — opt-in live refresh over a mark-dirty default

**The default action for an event arriving for the active page is mark-dirty
only.** A view opts into live refresh by registering a handler it declares
UX-6-safe, and that declaration is reviewed once at opt-in. This is P5 —
explicit over ambient — applied to the client.

*Why the safe behavior is the default:* it means a surface added in Phase 8 that
nobody thought carefully about degrades to today's on-activation loading rather
than destroying someone's half-typed form. Getting it wrong requires an explicit
act.

*Why not a uniform `isBusy()` predicate on every view:* it is the more
"by construction" design, but Admin Review's implementation would be
`return false`, so it builds plumbing the first surface does not need. It remains
the right answer for the first surface that genuinely needs busy-detection —
User Requests will — and can be added then without changing the registration
shape.

*Constraint this places on Phase 8:* there is no uniform way to detect an open
interaction today. `state.js` uses module flags (`editingItemId`,
`editingNotesItemId`), `tools.js` has `editingToolId`, and User Requests keeps
its state **entirely in the DOM** with no flag at all. Any view opting in must
answer the busy question in its own terms. Admin Review does not have to answer
it, because it has no uncommitted state to protect.

*Note on §10.3:* Admin Review keeps no `state.js` cache — it fetches on load. So
the "cache freshness" concept §10.3 introduces is **not needed for the first
surface** and is deferred to Phase 8, where the first cached surface actually
requires it.

---

## 15. Explicit non-goals

- **No new user-visible feature.** Real-time is the absence of staleness, not an
  addition to the product.
- **No optimistic UI.** Clients do not render predicted state.
- **No conflict resolution.** Concurrent edits behave exactly as they do today;
  users just see the outcome sooner.
- **No offline support or queued writes.** Disconnected means today's app.
- **No socket-borne mutation.** P3, permanently.
- **No horizontal scaling.** Single instance, per N3.
- **No refactor of the large files.** N6's standing rule holds: rule-shaped logic
  goes behind the domain boundary; nothing is split for its own sake.
- **No change to authentication.** The session cookie is reused as-is.

---

## 16. Reading order for a future planner

§1 and §3 first — the constraint and the principles. §2 to confirm nothing has
drifted. Then phases in order; they are dependency-ordered, and §6 in particular
precedes any real data flow for a reason. §14 is what needs answering before
anything is scheduled.
