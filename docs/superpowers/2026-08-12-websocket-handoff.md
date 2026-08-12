# Real-Time Layer — Session Handoff

**Status: nothing is implemented, scheduled, or approved. Zero lines of socket
code exist.**

Written 2026-08-12 at `c7531ea`. This is the pickup note for the real-time work.
It carries the context that is *not* in the design document: what state the
planning is actually in, which of the design's factual claims still hold, and
what has changed underneath it since it was written.

Read this first, then the design.

---

## 1. What exists

One artifact: **`docs/superpowers/specs/2026-08-12-websocket-realtime-layer-design.md`**.

It is a *reference design*, not a plan and not a spec to implement. It describes
behavior, responsibilities, and sequencing — deliberately abstract, with no
implementations. It was written against `90be427` to be read before any
real-time work is planned.

Deliberate properties of that document, which should survive contact with the
next session:

- **It does not live in `docs/`.** That directory is the four consolidated files
  from 2026-08-10, and `open-work.md` is the only backlog. The design is a
  reference, not an open item. If any part of it is promoted to real work, it
  gets an `open-work.md` entry like anything else. **It does not have one
  today.** That is intentional, not an oversight.
- **It records open decisions rather than resolving them** (§14, D1–D8). Those
  are the gate. Nothing should be scheduled until they are answered.
- **Its numeric thresholds are explicitly hypotheses** (§7), subject to the
  standing rule in `open-work.md`: *ask what the number actually is before
  building what an item describes.* The three worked examples there — C2, B3,
  X3 — all got dramatically cheaper for being checked against data first.

---

## 2. The shape of the thinking so far

Compressed, so the next session inherits the reasoning and not just the
conclusions. The design's own §16 gives the reading order; this is why it is
ordered that way.

**The governing constraint (§1)** is that nothing about the app's behavior or
appearance changes except that data stops being stale. Seven invariants (UX-1
through UX-7) make that testable. Two are called out as easiest to violate:
UX-6 (a live refresh must never destroy in-progress user input) and UX-2 (no new
UI at all — no toasts, badges, counters, or connection indicators; *data
freshens, it does not narrate*).

**Five principles (§3)**, each with its consequence-if-abandoned named:

- **P1** — the socket is never the system of record. This is what makes
  aggressive backpressure safe and reconnect-and-refetch a complete recovery.
- **P2** — broadcast *invalidation*, not payloads. Events say what changed;
  recipients re-fetch through existing REST, which re-runs the server's own
  scoping. This makes the socket structurally incapable of leaking anything REST
  would not already return — UX-4 by construction rather than by discipline.
- **P3** — REST remains the only way state changes.
- **P4** — degradation is invisible.
- **P5** — explicit over ambient: one endpoint, enforcement written visibly in
  it rather than inherited from middleware.

P1 and P2 together are load-bearing for most of the rest of the document. If the
next session is tempted to send row payloads over the wire "since we already
have them", that single change re-opens §7.5, §9.2, and every fan-out decision
as an independent security review.

**The phase order is a dependency order, not a preference.** §6 (connection
lifecycle and session binding) precedes any data flow for a specific reason
recorded as the most important item in the document: today every request
re-resolves the session, so revocation is instant; a socket authenticated once
at handshake has no next request, and would outlive demotion, archival, and the
12-hour session cap.

**The traps already identified**, each of which cost real analysis:

- Request context **cannot** reach the dispatch task through a context variable —
  the task is started at lifespan and inherits nothing. Correlation ids must
  travel inside the event as ordinary data (§8.2).
- A database commit-hook design would make the **test suite lie**, because the
  shared fixture binds sessions to an outer transaction in savepoint mode, so
  every commit under test is a savepoint release (§9.1). Emission belongs at the
  router layer.
- The HTTP rate limiter does **not** apply to the handshake — it arrives as a
  `websocket` scope and never enters HTTP middleware, despite being an HTTP GET
  on the wire (§7).
- Backoff must be **jittered**: a deploy drops every client simultaneously
  (§10.2).

---

## 3. Baseline re-verification at `c7531ea`

The design's §2 established "what exists today" at `90be427`. I re-checked every
claim. **One is wrong; the rest hold.**

| §2 claim | At `c7531ea` |
|---|---|
| No push, no polling — zero `setInterval` / `EventSource` / `WebSocket` in `backend/static/` | **Holds.** 0 occurrences (excluding vendored zxing). |
| No ASGI websocket route anywhere | **Holds.** 0 `APIWebSocketRoute`. |
| The backend is entirely synchronous | **Holds.** 0 async route handlers. The only `async def`s are the 3 HTTP middleware and a static-files override; two more are docstrings *explaining* the deliberate choice of `def`. |
| ~~97 sync route handlers~~ | **Wrong — the number is 75.** See below. |
| All three middleware layers are HTTP-scope only | **Holds.** `@app.middleware("http")` ×3 in `main.py`. |
| No startup or shutdown hooks at all | **Holds.** 0 `lifespan` / `on_event` in `main.py`. §5.1 stands. |
| CSP is `default-src 'self'` with no `connect-src` | **Holds** (`main.py:131`). §4.2 is still an open precondition. |
| `liveGet` uses `cache: "no-store"` | **Holds** (`static/api.js:66`). |
| Single free-tier instance, one worker, spun down when idle | **Holds.** `render.yaml`: `plan: free`, no `numInstances`, no `--workers`. |
| `can_view_work_order` is pure and reusable | **Holds** (`domain/work_orders.py:434`). |

**On the route count:** the app has 75 `APIRoute`s (80 total routes including 4
plain `Route`s and 1 `Mount`), all synchronous. It was 72 at `90be427` — item
requests added 3. The document's "97" was wrong when written, not drifted into.

This does not damage any of the reasoning. §5.2 and §7.6 lean on *"the app is
entirely synchronous and its handlers run in a threadpool"* and *"middleware
exists to avoid repetition across many routes"* — both true at 75. **Correct the
number, keep the argument.** It is flagged here rather than silently fixed
because a reader who spots it should know it was checked and is the only
factual error found.

---

## 4. What changed underneath the design since `90be427`

One commit: `c7531ea`, the Item Request feature. Three consequences for this
work.

### 4.1 The first-surface candidate got worse — this affects D4

§11 selects the first consumer surface by three criteria: simplest possible
audience (no per-row predicate), genuine staleness cost, and **low interaction
risk under UX-6** — *"a queue nobody is mid-edit in is safer than a form-heavy
page."*

At `90be427`, the User Requests queue was close to ideal on all three: its
audience is a flat role gate (Admin+, no per-row predicate), it goes stale
constantly, and it was read-plus-resolve.

**At `c7531ea` it is form-heavy.** The queue now carries inline edit forms, a
fulfil panel with a radio mode switch and an item search picker, and sibling
confirmation checkboxes (`views/userRequestCards.js`). An Admin mid-fulfilment
has uncommitted state on screen that a naive refresh would destroy — exactly the
UX-6 hazard §11 says to keep away from a first surface.

**This does not disqualify it**, but D4 can no longer be answered by pointing at
the queue and calling it simple. Either D8 (active-page refresh policy under
UX-6) gets answered first, or another surface goes first. This is the single
most useful thing in this handoff.

### 4.2 The emit seam gained three routes

§9.1 makes emission an explicit line at the router layer and a
**review-checklist item for any new mutating route**. `user-requests` went from
2 routes to 5:

```
GET   /user-requests/
POST  /user-requests/item-request        (new — any authenticated session)
GET   /user-requests/{id}/siblings       (new)
POST  /user-requests/{id}/fulfill        (new — mutating, cascades)
PATCH /user-requests/{id}
```

`POST /fulfill` is the notable one: it resolves N requests and writes work-order
lines across N work orders in one commit, so it is a single mutating route whose
event fan-out is inherently multi-audience — it touches both the "operational
request changed" and "work order changed" rows of the §9.2 audience map. If the
queue is the first surface, this route is the interesting emission case, not the
easy one.

### 4.3 Three confirmed defects are now logged

A review of `c7531ea` this session found six issues; three are logged in
`open-work.md` as **SEC-020**, **SEC-021**, and **PRO-021**. None blocks
real-time work, and they are noted here only so the next session does not
re-discover them while reading the same files. SEC-020 (unvalidated `details`
values reaching work-order billing) is the one that matters.

---

## 5. Where the planning actually stands

- **Nothing is scheduled.** No `open-work.md` entry exists for real-time, by
  design.
- **No preconditions from §4 are met.** The working tree is clean (4.1 ✓), but
  CSP is unconfirmed (4.2), the multi-instance note is not updated (4.3), and
  the documentation home is undecided (4.4 = D7).
- **All eight open decisions D1–D8 are unanswered.** D4 and D8 are now coupled,
  per §4.1 above.
- **The multi-instance interaction is real.** `open-work.md` N3 records the
  in-process rate limiter as the first thing to inherit the undecided
  multi-instance story. The connection registry would be the second and worse
  one: a second instance does not degrade delivery, it silently halves it.
  N3 has **not** been updated to say so (that is precondition 4.3).

---

## 6. How to pick this up

1. Read §1 and §3 of the design — the constraint and the principles. Everything
   else is downstream of them.
2. Read §2 with the corrections in §3 of this handoff applied.
3. Answer D4 and D8 together, in light of §4.1 above. They are the decisions
   most likely to change what gets built first.
4. Resolve the §4 preconditions — they are all documentation or verification, no
   code.
5. Only then consider whether anything is promoted to `open-work.md`.

**Do not start at Phase 1.** The transport is the easy part and the design says
so; §6 and §7 are where the work actually is, and D1 (session-binding mechanism)
changes the shape of Phase 1 itself.

**Do not merge to `main` without asking.** CI deploys to production.
