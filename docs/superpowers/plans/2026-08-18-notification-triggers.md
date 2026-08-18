# Notification Triggers — Session Handoff

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement Part 3 task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.
>
> **Read Part 2 before executing anything.** Four decisions are unresolved and two of them change the shape of the code. Task 0 is a decision gate, not a formality.

**Goal:** Wire real work-order events to the Web Push transport that shipped 2026-08-18, so technicians, supervisors and admins are notified about assignments and status changes without opening the app.

**Architecture:** The transport is done and proven on a real iPhone. What is missing is (a) per-user targeting, (b) a non-blocking send path, and (c) subscription eligibility below Admin. Triggers hang off the seven existing realtime emitter call sites in `routers/work_orders.py`, which already fire at exactly the moments notifications are wanted.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Alembic, `pywebpush==2.4.0`, vanilla ES modules. Postgres 18 local on port 8801.

**Spec:** No separate design doc. This file is both the review and the plan; Part 2 is the design work that has not happened yet.

## Global Constraints

- **Notification bodies must never contain customer names, addresses, or job details.** Text renders on a locked iPhone. Established during the probe; `routers/push.py::send_test` is the reference.
- **Only 404/410 deletes a subscription.** `domain/push.py::classify_push_response` is the sole authority. A 401 from a bad key hits every device at once; deleting on it empties the table.
- **The endpoint allowlist is re-checked on every send**, not just at registration (`domain/push.py::is_allowed_push_endpoint`).
- **A push failure must never fail a durable write.** Same rule the realtime emitter follows (`services/realtime.py::emit` — "never blocks and never raises").
- **iOS: Home-Screen install required**, the installed PWA has its own cookie jar, and permission is one-shot with no re-prompt.
- **`VAPID_PUBLIC_KEY` in `services/push.py` must stay paired with `VAPID_PRIVATE_KEY` in the Render dashboard.** Rotating one without the other returns 401 on every send.
- Verification runs the real database: `cd backend && ./venv/Scripts/python.exe -m pytest -q` must report **1031 passed, 0 skipped** (as of 2026-08-18) before and after.

---

## Part 1 — Review: what actually shipped

Landed 2026-08-18 on `main`. Verified end-to-end on a real iPhone: notification delivered with the app fully closed, low latency.

### Delivery path

```
POST /push/test  (owner only)
  → services/push.py::send_to_min_role(db, minimum, title, body)
      → subscriptions_for_min_role()   — SELECT joined to users, role IN (…), archived_at IS NULL
      → per subscription: is_allowed_push_endpoint()  — SSRF guard, re-checked
      → _send_one() → pywebpush → Apple/FCM/Mozilla
      → classify_push_response(status) → OK | DROP | CONFIG_ERROR | TOO_LARGE | RETRY
      → dead endpoints deleted in one batch after the loop
  → returns {sent, dropped, failed}
```

Browser side: `static/service-worker.js` (served from **root** by `main.py::service_worker`, not `/static`, so its scope is `/`) shows the notification; `static/views/push.js` owns opt-in and the Owner's test button.

### Trigger points available today

`routers/work_orders.py` already emits realtime invalidations at seven places. These are the natural notification hooks — the moments are correct, only the payload is missing.

| Line | Handler | Corresponds to |
|---|---|---|
| 562 | `update_work_order` | **assignment changes** (`assigned_to_ids`, `supervisor_id`) — requirement 1 |
| 588 | `start_work_order` | → `in_progress` |
| 612 | `complete_work_order` | → `completed` — requirement 2 |
| 630 | `hold_work_order` | → `on_hold` |
| 648 | `resume_work_order` | leaves `on_hold` |
| 671 | `archive_work_order` | row leaves everyone's list |
| 693 | `restore_work_order` | row re-enters lists (`entity_id=None`) |

Statuses (`domain/work_orders.py:40-45`): `created`, `assigned`, `in_progress`, `on_hold`, `completed`, `review`.

### Event data available at those points

- The `WorkOrder` row, post-write.
- Assignees via `services/work_orders.py::_assigned_technician_ids` (:258) and `assigned_technicians` (:270). The model is **plural** (`work_order_technicians`) with a legacy singular `assigned_to_id` kept in sync at `services/work_orders.py:344`.
- `work_order.supervisor_id`.
- The acting user, as `user` in every handler.

### Known limitations — these are the reason Part 3 exists

1. **No per-user targeting.** `send_to_min_role` fans out by *role floor* only. Requirements 1 and 3 need "notify these specific people." There is no `send_to_users`.
2. **Sending is synchronous and blocking.** `_send_one` makes one blocking HTTPS request per device. The realtime emitter is explicitly the opposite — non-blocking, never raises, drop-newest. Calling push inline from `complete_work_order` puts an Apple round trip per device inside the user's request.
3. **Subscription is Admin-and-above only.** `routers/push.py:46` sets `NOTIFY_MIN_ROLE = roles.ROLE_ADMIN`; `static/views/push.js:26` mirrors it and hides the opt-in button below Admin. **Technicians and supervisors currently cannot subscribe at all**, so requirements 1 and 3 are dead on arrival until this changes.
4. **The previous status is not available at the emit site.** `_emit_status_changed(work_order.id)` carries only an id. Requirement 3 is a *transition* rule (Completed → anything) and cannot be evaluated from the post-write row alone.
5. **No actor suppression.** A supervisor who completes their own work order would notify themselves.
6. **No dedup or rate limiting.** A row toggled repeatedly sends one push per toggle.
7. **No per-user preferences.** No opt-out per event type; opting in is all-or-nothing.
8. **No delivery record.** `{sent, dropped, failed}` is returned to the caller and logged, then discarded. Nothing can answer "was this person notified?"

### Needs re-verification before relying on it

- Line numbers above are accurate as of `main` on 2026-08-18 but `routers/work_orders.py` is actively edited — re-grep for `_emit_status_changed(` rather than trusting the table.
- `static/views/push.js` has **no automated coverage** (no JS test runner in the repo; CI runs `node --check` only). Every claim about frontend behavior is manual-validation only.
- Whether `update_work_order` can distinguish "assignee added" from "assignee removed" was not investigated. `services/work_orders.py:321-354` computes a desired set and replaces; confirm whether the prior set is recoverable before writing requirement 1.

---

## Part 2 — Planning: decisions needed before execution

### Confirmed requirements

1. Technicians and Supervisors notified when a work order is **assigned to them**.
2. Admins notified when a work order is **marked Completed**.
3. Assignees notified when a work order **moves from Completed to any other status**.

### D1 — Send path: how does push get off the request thread? **(blocking, architectural)**

Requirement 2 fires inside `complete_work_order`. With N admin devices, an inline send adds N sequential Apple round trips to the user's tap.

| Option | Cost |
|---|---|
| **A. FastAPI `BackgroundTasks`** | Runs after the response is sent. ~10 lines, no new infrastructure. Dies with the worker; no retry. |
| **B. Mirror `services/realtime.py::emit`** | Reuses a proven in-process handoff queue and drop-newest policy. More code; a second queue to reason about. |
| **C. Inline** | Simplest, wrong. Puts a third-party network call in the write path. |

**Recommendation: A.** It satisfies "never fail a durable write" with the least new machinery, and the free Render instance has no worker pool to lose work to. Revisit if delivery guarantees are ever needed.

### D2 — Subscription eligibility floor

Requirements 1 and 3 need technicians subscribed. Dropping `NOTIFY_MIN_ROLE` to `ROLE_TECHNICIAN` makes everyone eligible — but that constant currently serves **two** purposes: who may subscribe, and who receives `/push/test`. Those must split, or the Owner's test button starts buzzing the entire crew.

**Recommendation:** rename to `SUBSCRIBE_MIN_ROLE = ROLE_TECHNICIAN` and `TEST_AUDIENCE_MIN_ROLE = ROLE_ADMIN`, mirroring both in `views/push.js`.

### D3 — Actor suppression

Should the person who caused the event be notified of it?

**Recommendation: suppress.** Pass the acting user id and filter it from recipients. Cheap now, awkward to retrofit once people are used to the noise.

### D4 — Capturing the transition for requirement 3

The old status must reach the emit site. Options: return it from the service, read it before the write in the router, or add an event-type parameter to a new notification emitter.

**Recommendation:** have `wo_service.complete/hold/resume/...` return or expose the prior status, and pass `(previous_status, new_status)` into the notification call. Do **not** infer it client-side.

### Open questions needing your input

- **Q1.** Requirement 3 says "assignees." Does that include the **supervisor**, or only assigned technicians?
- **Q2.** Requirement 1 — notify on *every* assignment write, or only when the assignee set actually changes? A PATCH that re-sends the same assignees should probably stay silent.
- **Q3.** Should archiving a work order notify its assignees? They may be actively working it. I'd say yes; it is not in your list.
- **Q4.** Do you want any per-user opt-out, or is role-based routing enough for now? (Recommend: enough for now.)

### Low-hanging fruit — proposals, not committed

Each reuses an existing emitter and the same machinery. Ordered by value-to-effort.

1. **Completed → Review** notifies Admin. The Review handoff is already Admin-only and is the queue they watch. Nearly free once requirement 2 exists.
2. **On-Hold** notifies the supervisor and assignees. Same shape as requirement 3, different trigger (`hold_work_order`, :630).
3. **Archive** notifies assignees (Q3 above) — stops wasted trips.
4. **New user request / recount** notifies TechFM OA and above. Different router (`routers/user_requests.py`) and a different audience; genuinely useful but a larger step than 1-3.
5. **NetFacilities enrichment finished** notifies the Admin who started it. Long-running job, currently poll-only. Worth doing but touches `services/netfacilities_jobs.py` and is the least related to this batch.

**Deliberately excluded:** anything that puts customer or job detail in the body (lock-screen rule), and any digest/batching scheme — premature until real volume is observed.

---

## Part 3 — Execution

### Task 0: Decision gate — no code — RESOLVED 2026-08-18

- [x] **Step 1:** Read Part 2 with the user. Resolve **D1, D2, D3, D4** and **Q1-Q4**.
- [x] **Step 2:** Record each decision inline in this file with a one-line rationale.
- [x] **Step 3:** Confirm the low-hanging-fruit list — which are in scope for this batch.

| # | Decision | Rationale |
|---|---|---|
| D1 | **FastAPI `BackgroundTasks`** | Least machinery that satisfies "never fail a durable write"; one instance, no worker pool to lose work to. |
| D2 | **Split into `SUBSCRIBE_MIN_ROLE` / `TEST_AUDIENCE_MIN_ROLE`** | One constant serving two audiences is how the Owner's test button ends up buzzing the whole crew. |
| D3 | **Suppress the actor** | Cheap now, awkward to retrofit once people are used to the noise. |
| D4 | **Services surface the prior status** | Needed for the Completed→other rule *and* to stop an idempotent double-tap sending twice. |
| Q1 | **Assignees + the routed supervisor** | The supervisor owns the outcome and is usually the one who has to react. |
| Q2 | **Only newly-added assignees** | Re-saving an unchanged form must stay silent; the prior set is available in `_sync_technician_assignments`. |
| Q3 | **No** — archive does not notify | Deferred with the rest of the low-hanging fruit. |
| Q4 | **No per-user opt-out** | Role and assignment routing is enough at this volume. |

**Low-hanging fruit: none in scope.** Completed→Review, archive, on-hold,
user-request and NetFacilities triggers are all deferred. The procedure doc
written in this session makes each a short job later.

**Two Part 1 claims were wrong and are corrected here** (verified against `main`
before any code was written):

1. *"Subscription is Admin-and-above only."* It is not. `POST /push/subscribe`
   depends on `get_current_user` — **any authenticated user may already
   subscribe**, and `routers/push.py`'s own docstring says so. `NOTIFY_MIN_ROLE`
   only selects the `/push/test` audience. The single thing keeping technicians
   out is the frontend mirror at `static/views/push.js:26`, so Task 1 is a
   rename plus one frontend constant, not a backend policy change.
2. *"Whether `update_work_order` can distinguish added from removed assignees
   was not investigated."* It can. `_sync_technician_assignments`
   (`services/work_orders.py:326-330`) builds `existing` before replacing it, so
   both the added and the removed sets are available at that point.

**And one discovery that moves Task 3's scope:** none of the narrow transition
endpoints can leave `completed` — `start` accepts only `assigned`, `hold` only
`in_progress`, `resume` only `on_hold`. Requirement 3 therefore has exactly one
trigger site, the Supervisor+ PATCH. The narrow endpoints still need the prior
status, but for idempotency suppression rather than for requirement 3.

> **Do not start Task 1 until every item above is answered.** D1 and D4 determine function signatures used by all later tasks; guessing means rewriting them.

### Task 1: Split the eligibility constant and drop the subscribe floor

Depends on: D2.

**Files:**
- Modify: `backend/app/routers/push.py:46`, `:136`
- Modify: `backend/static/views/push.js:26`, `:138`
- Test: `backend/tests/test_push_subscriptions.py`

**Interfaces:**
- Produces: `SUBSCRIBE_MIN_ROLE`, `TEST_AUDIENCE_MIN_ROLE` in `routers/push.py`.

- [x] **Step 1:** Update the two existing assertions that pin the current behavior — `test_notify_audience_is_admin_and_above` and `test_recipient_roles_expand_upward_only` — to reference `TEST_AUDIENCE_MIN_ROLE`, and add a test asserting `SUBSCRIBE_MIN_ROLE == roles.ROLE_TECHNICIAN`.
- [x] **Step 2:** Run `./venv/Scripts/python.exe -m pytest tests/test_push_subscriptions.py -v`. Expected: the new assertion FAILS.
- [x] **Step 3:** Split the constant in `routers/push.py`; point `send_test` at `TEST_AUDIENCE_MIN_ROLE`.
- [x] **Step 4:** Mirror both constants in `views/push.js` and gate the opt-in button on `SUBSCRIBE_MIN_ROLE`. Run `node --check backend/static/views/push.js`.
- [x] **Step 5:** Run the file's tests. Expected: PASS.
- [x] **Step 6:** Commit — `feat(push): let technicians and supervisors subscribe`.

> **Review checkpoint.** Confirm the Owner's test button still reaches only Admin+. A regression here buzzes the whole crew on every test.

### Task 2: Per-user targeting

Depends on: nothing beyond Task 1.

**Files:**
- Modify: `backend/app/services/push.py` (beside `send_to_min_role`, :165)
- Test: `backend/tests/test_push_subscriptions.py`

**Interfaces:**
- Produces: `send_to_users(db, user_ids: Sequence[UUID], title: str, body: str) -> dict` returning the same `{sent, dropped, failed}` shape as `send_to_min_role`.

- [x] **Step 1:** Write failing tests: delivers only to the named users; an archived user is excluded; an empty `user_ids` sends nothing and returns zeros; a dead endpoint is still deleted.
- [x] **Step 2:** Run them. Expected: FAIL, `send_to_users` not defined.
- [x] **Step 3:** Extract the shared loop out of `send_to_min_role` so both entry points use one send-and-classify body. **Do not duplicate it** — the delete-only-on-404/410 rule must exist in exactly one place.
- [x] **Step 4:** Run the full file. Expected: PASS.
- [x] **Step 5:** Commit — `feat(push): add per-user fan-out`.

> **Review checkpoint.** Verify `send_to_min_role` still passes every pre-existing test unchanged — the refactor in Step 3 is where a regression would hide.

### Task 3: Surface the status transition

Depends on: D4.

**Files:**
- Modify: `backend/app/services/work_orders.py` (transition functions)
- Modify: `backend/app/routers/work_orders.py:588, 612, 630, 648`
- Test: `backend/tests/test_work_orders_service.py`

- [x] **Step 1:** Write a failing test asserting each transition function reports the prior status.
- [x] **Step 2:** Run it. Expected: FAIL.
- [x] **Step 3:** Implement, per the shape chosen in D4.
- [x] **Step 4:** Run `pytest tests/test_work_orders_service.py -q`. Expected: PASS.
- [x] **Step 5:** Run the **full** suite — this touches the most heavily tested module in the repo. Expected: 1031+ passed, 0 skipped.
- [x] **Step 6:** Commit — `feat(work-orders): expose the prior status on transitions`.

> **Review checkpoint.** `test_work_orders_service.py` is large and covers subtle lifecycle rules. Read its failures carefully rather than adjusting assertions to match new behavior.

### Task 4: The notification emitter

Depends on: D1, D3.

**Files:**
- Create: `backend/app/services/notifications.py`
- Test: `backend/tests/test_notifications.py`

**Interfaces:**
- Produces: one function per event, e.g. `notify_work_order_assigned(db, work_order, actor_id, background)` — exact signature set by D1 and D3.

- [x] **Step 1:** Write failing tests for recipient selection **only** — assignment notifies the new assignees and not the actor; completion notifies Admin+; a Completed→other transition notifies assignees. Mock the send.
- [x] **Step 2:** Run. Expected: FAIL.
- [x] **Step 3:** Implement. Keep this module free of HTTP concerns: it decides *who* and *what text*, and delegates delivery to `services/push.py`.
- [x] **Step 4:** Run. Expected: PASS.
- [x] **Step 5:** Commit — `feat(notifications): add work-order notification rules`.

> **Review checkpoint.** Check every body string against the lock-screen rule. No names, no addresses, no job detail.

### Task 5: Wire the three required triggers

Depends on: Tasks 1-4, and Q1/Q2.

**Files:**
- Modify: `backend/app/routers/work_orders.py:562` (assignment), `:612` (completed), plus the transition sites for requirement 3
- Test: `backend/tests/test_work_orders_notifications.py` (create)

- [x] **Step 1:** Write failing route-level tests asserting each of the three requirements fires the right call with the right recipients.
- [x] **Step 2:** Run. Expected: FAIL.
- [x] **Step 3:** Add the calls beside the existing `_emit_status_changed` lines. Follow that function's contract exactly: best-effort, never raises, never fails the write.
- [x] **Step 4:** Run the full suite. Expected: 0 failures, 0 skips.
- [x] **Step 5:** Commit — `feat(work-orders): notify on assignment, completion and reopen`.

> **Review checkpoint — the important one.** Manually verify on a real iPhone before merging: assign a work order to a technician and confirm the notification arrives with the app closed. CI cannot prove this.

### Task 6: Documentation

- [x] **Step 1:** Add the trigger table and recipient rules to `docs/current-state.md` under *API Surface → Web Push*.
- [x] **Step 2:** Update the N9 entry in `docs/open-work.md` — it currently says no business event is wired.
- [x] **Step 3:** Record any accepted low-hanging-fruit items not built as a new numbered backlog entry.
- [x] **Step 4:** Commit — `docs: record the notification trigger rules`.

### Where to pull more context

| Need | Source |
|---|---|
| How push works end to end | `docs/current-state.md` → *API Surface → Web Push* |
| Why only 404/410 deletes | `backend/app/domain/push.py:55` docstring |
| Non-blocking emit precedent | `backend/app/services/realtime.py::emit` docstring |
| Audience-by-role precedent | `backend/app/domain/realtime.py:67` (`_AUDIENCE_MIN_ROLE`) |
| Assignment model | `backend/app/services/work_orders.py:258-354` |
| What the probe deliberately left out | `docs/open-work.md` → N9 |
| Local DB / running tests | memory: `local-postgres-port-8801` |
| Original push build session | commits on `main` dated 2026-08-18 |

---

## Outcome — 2026-08-18

All six tasks implemented and committed on `main`. Suite: **1094 passed, 0
failed, 0 skipped** (baseline was 1031).

**Not done, and only you can do it:** the Task 5 review checkpoint. Assign a
work order to a technician on a real iPhone with the app installed and
notifications granted, cause the event from a different account, and confirm it
arrives with the app closed. CI cannot prove delivery.

Where execution diverged from the plan, and why:

| Plan said | Reality |
|---|---|
| Baseline is 1031 passing | Six push fan-out tests failed locally before any change. They assumed `push_subscriptions` was empty, so they passed in CI and failed on any machine with an enrolled device. Fixed first, in its own commit. |
| Task 1 drops a backend subscribe floor | There was no backend floor. `/push/subscribe` takes any authenticated user; the gate was one constant in `views/push.js`. |
| Task 3 touches four transition routes | Requirement 3 needed only the PATCH — no narrow endpoint can leave Completed. The four still surface the prior status, but for idempotency suppression. |
| Task 4 creates `services/notifications.py` | Split into `domain/notifications.py` (pure rules) and `services/notifications.py` (resolution + handoff), matching the existing push and realtime layering. |
| — | `BackgroundTasks` as an explicit handler parameter meant updating eight direct handler calls in existing tests. Worth it over a `None` default that would silently disable notifications. |
| — | A procedure doc, `docs/adding-a-notification-trigger.md`, was written before Task 1 and reconciled against the shipped code at Task 6. |

One behavior worth a second look: **Completed → Review fires the reopen rule**,
because Review is "any other status". Pinned by
`test_sending_completed_work_to_review_counts_as_leaving_completed`. Narrowing
it is one condition in `_notify_work_order_patch`.
