# Adding a Notification Trigger

How to make a business event send a Web Push notification, without
rediscovering the constraints every time. Read this instead of reading
`services/push.py`; come back to the source only when this file and the code
disagree, and then fix this file.

The transport (VAPID keys, service worker, subscription table, delivery,
dead-subscription cleanup) is finished and is **not** what you change. Adding a
trigger touches three places and nothing else:

1. a rule in `domain/notifications.py` — *who* and *what text*,
2. a function in `services/notifications.py` — resolve the rule, hand it off,
3. one call at the event site in a router — beside the existing realtime emit.

If a change you are making needs a fourth place, stop: either the transport is
being modified (a much bigger change, see *API Surface → Web Push* in
`current-state.md`), or the trigger is in the wrong layer.

---

## The five rules

These are not style preferences. Each of them is a bug that has either happened
or was one review comment away from happening.

**1. Notification text renders on a locked phone.** No customer names, no
addresses, no job descriptions, no note text, no prices. A work-order **number**
is allowed and wanted — it is an opaque identifier that makes the notification
actionable, and it is already visible to anyone holding the phone. The line is
*identifiers yes, human-readable detail no*. `routers/push.py::send_test` is the
reference for tone.

**2. Only 404 and 410 may delete a subscription.**
`domain/push.py::classify_push_response` is the single authority and no trigger
code should ever inspect a status code. A wrong VAPID key returns 401 for
*every* device at once; treating that as "dead subscription" empties the table
and silently opts the whole crew out.

**3. A push failure must never fail a durable write.** The work order was
already saved. Delivery is best-effort exactly like `services/realtime.py::emit`
— it returns nothing useful, raises nothing, and its result is deliberately
ignored at the call site.

**4. The request's database session is already closed when a background task
runs.** Since FastAPI 0.106, dependencies with `yield` are torn down *before*
background tasks execute, and this repo pins 0.136.3. Anything the notification
needs from the database must be read **during** the request; the background half
opens its own `SessionLocal()` for the one write it may need (deleting dead
subscriptions). This is the single easiest way to break notifications, and it
breaks them in production only — tests that drive the handler synchronously will
not catch it.

**5. The endpoint allowlist is re-checked on every send.** Free — it lives in
the shared fan-out — but do not add a send path that bypasses
`is_allowed_push_endpoint`. A stored endpoint is otherwise an SSRF primitive
aimed at the hosting provider's network.

---

## The path an event takes

```
router handler (request thread, session alive)
  │  the durable write already committed
  ├─ _emit_status_changed(...)              realtime, unrelated, keep it
  └─ notifications.notify_<event>(db, background, ...)
        ├─ domain.notifications.recipients_for_<event>(...)   pure: who
        │     └─ select_recipients(candidates, actor_id)      dedup, drop actor
        ├─ domain.notifications.build_message(event, ...)     pure: title, body
        ├─ resolves recipient ids against the live session    ← must happen here
        └─ background.add_task(_deliver, user_ids, title, body)
                                                       ── response is sent ──
              _deliver  (background, its own SessionLocal)
                └─ push.send_to_users(session, user_ids, title, body)
                      └─ shared fan-out: allowlist → pywebpush → classify
                            └─ 404/410 only: batch-delete dead rows
```

The split is the whole design: **decide inside the request, deliver outside
it.** Deciding needs the database and must be correct; delivering needs the
network and must not be on the user's tap.

---

## Recipe: adding one trigger

Worked example is "notify the supervisor when a work order goes On-Hold".

### Step 1 — Name the event and write the rule (pure, no database)

In `backend/app/domain/notifications.py`:

```python
EVENT_WORK_ORDER_HELD = "work_order.held"

def recipients_for_held(*, assignee_ids, supervisor_id, actor_id):
    """The supervisor owns the schedule; assignees may not be the one who held it."""
    return select_recipients([*assignee_ids, supervisor_id], actor_id=actor_id)
```

`select_recipients` drops `None`, de-duplicates while preserving order, and
removes `actor_id`. Actor suppression is centralised there on purpose — every
event suppresses the actor, and a trigger that does not is a decision worth
arguing for in a docstring.

Add the body text to `build_message`. Re-read rule 1 before you write the
string.

### Step 2 — Add the service function (touches the database, still no HTTP)

In `backend/app/services/notifications.py`, beside the existing ones:

```python
def notify_work_order_held(db, background, *, work_order, actor_id):
    _dispatch(
        background,
        policy.EVENT_WORK_ORDER_HELD,
        work_order,
        policy.recipients_for_held(
            assignee_ids=wo_service.assigned_technician_ids(work_order),
            supervisor_id=work_order.supervisor_id,
            actor_id=actor_id,
        ),
    )
```

`_dispatch` builds the text and hands it to `_schedule`; you should not
need to touch either.

Read every attribute you need off `work_order` **now**. Touching a lazy
relationship inside `_deliver` raises `DetachedInstanceError` (rule 4).
`_schedule` returns immediately when `user_ids` is empty, so no-recipient events
cost one list comprehension and no task.

### Step 3 — Call it at the event site

In the router, immediately after the existing realtime emit:

```python
work_order = wo_service.hold_work_order(db, work_order_id, user=user)
_emit_status_changed(work_order.id)
previous = wo_service.previous_status(work_order)
if previous is not None and previous != work_order.status:
    _notify(
        notifications_service.notify_work_order_held,
        db,
        background,
        work_order=work_order,
        actor_id=user.id,
    )
```

Add `background: BackgroundTasks` to the handler signature if it is not already
there — as a plain parameter, not one defaulting to `None`. FastAPI injects it.
A default would keep direct callers compiling and give you a deployment where
notifications silently never fire.

Go through `_notify`. It swallows rule failures, because the work order is
already committed by the time any of this runs and a bug in recipient
resolution must cost a notification rather than the save.

**The `previous_status` guard is not optional on any status transition**, and
it has two halves:

- `previous != work_order.status` — every narrow transition endpoint (`start`,
  `complete`, `hold`, `resume`) returns early and unchanged when the row is
  already in the target state, because a slow tap double-fires. Without this,
  the second tap sends a second notification for an event that did not happen.
- `previous is not None` — a row that did not come from a write which records
  transition facts has no prior status, and inferring an event from the
  post-write status alone is guessing.

For a PATCH, follow `_notify_work_order_patch`: evaluate assignment
independently of the transition. One write can be several events, and a chain
of `elif`s drops whichever arm comes second.

### Step 4 — Test what is worth testing

| Layer | File | Test this | Do not test this |
| --- | --- | --- | --- |
| Rule | `tests/test_notifications_domain.py` | recipient selection, actor suppression, dedup, message text | anything needing a session |
| Service | `tests/test_notifications.py` | resolves the right user ids; schedules once; schedules nothing when empty | real delivery |
| Route | `tests/test_work_orders_notifications.py` | the endpoint fires the right event with the right recipients; the idempotent repeat fires nothing | pywebpush |

Nothing in the suite sends a real push. Assert on recipients and on the fact
that a task was scheduled — the transport has its own tests
(`test_push_domain.py`, `test_push_subscriptions.py`) and does not need
re-proving per trigger.

### Step 5 — Verify on a real phone

CI cannot prove delivery. Before merging a trigger, on an iPhone with the app
installed to the Home Screen and notifications already granted: cause the event
from a *different* account, confirm the notification arrives with the app fully
closed, and confirm the actor's own phone stays silent.

---

## What you can address a notification to

| Helper | In | Sends to |
| --- | --- | --- |
| `push.send_to_users(db, user_ids, …)` | `services/push.py` | exactly those users' devices |
| `push.send_to_min_role(db, minimum, …)` | `services/push.py` | every device of every user at or above a role |
| `push.user_ids_for_min_role(db, minimum)` | `services/push.py` | the *people* at or above a role, so the actor can be filtered out |
| `wo_service.assigned_technician_ids(wo)` | `services/work_orders.py` | plural assignments, with the legacy singular folded in |
| `work_order.supervisor_id` | model | the routed supervisor, may be `None` |

Prefer `user_ids_for_min_role` + `send_to_users` over `send_to_min_role` for
anything with an actor. A role-addressed send cannot express "everyone at this
rank except this person", so an Admin who completes a work order through the
PATCH would notify themselves.

Both send functions share one fan-out body, so the 404/410 rule and the
allowlist re-check exist in exactly one place. Keep it that way.

Archived users are excluded by the query, not by the caller. A user with no
subscription is not an error — they simply receive nothing.

## Who can receive anything at all

Two constants in `routers/push.py`, deliberately separate:

- **`SUBSCRIBE_MIN_ROLE`** — who may hold a subscription, mirrored in
  `static/views/push.js` to decide whether the opt-in button is visible. The
  backend `/push/subscribe` route accepts any authenticated user; this constant
  is the product decision about who is *offered* it.
- **`TEST_AUDIENCE_MIN_ROLE`** — who receives `POST /push/test`, the Owner's
  diagnostic. Nothing else uses it.

Collapsing these back into one constant is how the Owner's test button starts
buzzing every technician's phone. They look redundant and are not.

## Currently wired

| Event | Trigger site | Recipients |
| --- | --- | --- |
| Assigned to you | `update_work_order` (PATCH) | technicians **newly** added by that write |
| Marked Completed | `complete_work_order` for a Supervisor+ caller, and PATCH to `completed` | Admin and above |
| Reopened from Completed | `update_work_order` (PATCH) | assigned technicians + the routed supervisor |
| Returned from Review | `update_work_order` (PATCH), `review → in_progress` | assigned technicians + the routed supervisor |
| Placed On-Hold | `hold_work_order`, and PATCH to `on_hold` | the routed supervisor — or Admin+ if unrouted |
| Held for review | `complete_work_order` for a **Technician** caller | the routed supervisor — or Admin+ if unrouted |

Every one of them suppresses the acting user.

Two things about that table that are not obvious:

- **Reopen has exactly one trigger site.** The narrow `start` / `hold` /
  `resume` endpoints all reject a Completed row outright, so the only way out
  of Completed is the Supervisor+ PATCH.
- **Completed → Review is carved out of the reopen rule.** It is a move out of
  Completed, so the literal rule would fire, but Review is the forward handoff
  rather than work coming back: the assignees have nothing to do about it and
  "no longer Completed" reads as a setback. Every other exit from Completed
  does mean the work is live again and does notify. Owner decision,
  2026-08-18, pinned by two tests — one that Review is silent and one that the
  carve-out stays a carve-out.
- **Two rules can share an audience and still be two rules.** Reopen and
  Returned-from-Review both address the assignees plus the supervisor, and are
  deliberately separate functions with separate wording: one says the work is
  live again, the other says somebody looked at it and wants it changed. Merging
  them to remove the duplication would delete the only thing the recipient
  actually needs from the lock screen.
- **Branch order decides overlapping transitions.** `review → completed` is
  both "leaves Review" and "is now Completed"; it is evaluated as a completion
  because the completion arm comes first. `completed → on_hold` is both "leaves
  Completed" and "entered On-Hold"; the On-Hold arm sorts ahead of everything,
  so it is a hold. That one is not a style choice — the reopen audience already
  contains the routed supervisor, so evaluating both would buzz one person twice
  for one edit. If you add a rule whose transition can overlap an existing one,
  add a test that pins which one wins.
- **The same endpoint can raise different events.** `complete_work_order` fires
  *Marked Completed* or *Held for review* depending on where the row landed,
  which is a function of the caller's role
  (`domain.work_orders.completion_target_status`). The router chooses from the
  **resulting status**, never from the role — reading the role twice is how the
  notification and the database start disagreeing.
- **An audience of one can still need a fallback.** The two hold events address
  the routed supervisor, and an unrouted work order would otherwise alert
  nobody at all. They fall back to `UNROUTED_HOLD_AUDIENCE_MIN_ROLE`. Note the
  rule branches on *who is routed*, not on how many recipients survived
  suppression: a supervisor pausing their own job must not escalate it to every
  Admin by taking it.

## Traps

- **A `None` supervisor and an empty assignee list are normal.** Guard by
  letting `select_recipients` drop them, not with an `if` at the call site.
- **The actor is not always a technician.** A supervisor completing work on
  someone's behalf is the actor; suppress by id, never by role.
- **`update_work_order` is one write that can be several events.** A single
  PATCH can add assignees *and* change status. Evaluate each rule
  independently rather than choosing one event per request.
- **Assignment changes are computed, not declared.** The newly-added set comes
  from `_sync_technician_assignments`, which knows the prior membership.
  Re-sending an unchanged assignee list must stay silent, and does.
- **Do not add a notification inside a service function.** Services take no
  FastAPI types, so `BackgroundTasks` cannot reach them; the trigger belongs at
  the router where the realtime emit already is.
- **Do not batch or digest.** Deliberately excluded until real volume is
  observed. One event, one notification.

## Deliberately not built

No per-user opt-out, no per-event preferences, no delivery record. Routing is by
role and assignment only. If someone asks "was this person notified?", the
honest answer today is that the counts were logged and discarded — adding a
delivery record is a schema change, not a trigger.
