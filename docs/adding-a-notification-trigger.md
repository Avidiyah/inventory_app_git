# Adding a Notification Trigger

How to make a business event send a Web Push, without rediscovering the
constraints. Come back to the source only when this file and the code disagree,
and then fix this file.

The transport (VAPID, service worker, subscriptions, delivery, dead-subscription
cleanup) is finished. A trigger touches three places and nothing else:

1. a rule in `domain/notifications.py` — *who* and *what text* (pure);
2. a function in `services/notifications.py` — resolve the rule, hand it off;
3. one call at the event site in a router, beside the realtime emit.

Events raised several frames below a router (stock writes) buffer a plain fact
in a ContextVar that `routers/_stock_events.py` drains after commit; see
`services/low_stock.py` and `services/material_requests.py`. A fourth place
means you are changing the transport or the trigger is in the wrong layer.

---

## The five rules

Each is a bug that happened or was one review comment away.

1. **Text renders on a locked phone.** Catalogue identifiers, counts, and
   quantities yes; customer, address, description, note, and price no.
   `build_message` takes exactly `number`, `count`, `name`, `quantity`; widening
   that signature is the change to argue about, not the strings.
2. **Only 404 and 410 delete a subscription.**
   `domain/push.py::classify_push_response` is the single authority; trigger
   code never inspects a status code. A wrong VAPID key returns 401 for every
   device at once and would silently opt the whole crew out.
3. **A push failure never fails a durable write.** Delivery is best-effort and
   its result is ignored at the call site, like `services/realtime.py::emit`.
4. **The request's DB session is closed when a background task runs** (FastAPI
   0.106+; repo pins 0.136.3). Read everything needed from the database *during*
   the request; the background half opens its own `SessionLocal()` only for
   deleting dead subscriptions. This breaks in production only — synchronous
   handler tests will not catch it. (The NetFacilities chain notifier is the
   one synchronous exception, called directly from the chain, which has no
   request; see `notification-events.md`.)
5. **The endpoint allowlist is re-checked on every send** in the shared
   fan-out. Never add a send path that bypasses `is_allowed_push_endpoint`; a
   stored endpoint is otherwise an SSRF primitive.

The split is the design: **decide inside the request, deliver outside it.**

---

## Recipe

Example: notify the Team Lead when a work order goes On-Hold.

**1. Rule** (`domain/notifications.py`): add `EVENT_...`, a
`recipients_for_<event>(...)` returning `select_recipients([...], actor_id=...)`,
and the text in `build_message` (re-read rule 1 first). `select_recipients`
drops `None`, de-duplicates, and removes the actor; a trigger that should not
suppress the actor needs a docstring arguing why.

**2. Service** (`services/notifications.py`): a `notify_<event>(db, background,
*, work_order, actor_id)` that calls `_dispatch` with the event, the order, and
the recipients. Read every attribute you need off the order **now**; a lazy
relationship inside `_deliver` raises `DetachedInstanceError` (rule 4).
`_schedule` returns immediately on an empty list.

**3. Call site** (router), right after the realtime emit:

```python
previous = wo_service.previous_status(work_order)
if previous is not None and previous != work_order.status:
    _notify(notifications_service.notify_work_order_held, db, background,
            work_order=work_order, actor_id=user.id)
```

- Add `background: BackgroundTasks` to the handler as a **plain parameter**,
  never defaulting to `None`: a default keeps direct callers compiling and ships
  notifications that silently never fire.
- Go through `_notify`: it swallows rule failures so a recipient bug costs a
  notification, not the save.
- **The `previous_status` guard is mandatory on any status transition.**
  `previous != status` stops a double tap re-notifying (narrow endpoints return
  early when already in the target state); `previous is not None` stops
  guessing an event from post-write status alone.
- On a PATCH, follow `_notify_work_order_patch`: evaluate assignment independently
  of the transition — one write can be several events and `elif` drops the second.

**4. Tests** — nothing in the suite sends a real push; assert recipients and
that a task was scheduled.

| Layer | File | Test |
| --- | --- | --- |
| Rule | `tests/test_notifications_domain.py` | selection, actor suppression, dedup, text |
| Service | `tests/test_notifications.py` | right ids; scheduled once; nothing when empty |
| Route | `tests/test_work_orders_notifications.py` | right event and recipients; idempotent repeat fires nothing |

**5. Real phone** — CI cannot prove delivery. On an iPhone with the app on the
Home Screen: cause the event from a *different* account, confirm it arrives with
the app fully closed, and that the actor's phone stays silent.

**6. Registry** — add the event to `notification-events.md` (a row in *Who is
told* and in *What each one says*) in the same commit.

---

## Addressing

Prefer `push.user_ids_for_min_role` + `push.send_to_users` over
`send_to_min_role` for anything with an actor: a role-addressed send cannot
express "everyone at this rank except this person". Both send paths share one
fan-out, so the 404/410 rule and allowlist live in one place; keep it that way.
Who can receive anything at all: see `notification-events.md`.

## Traps

- **A `None` Team Lead and an empty assignee list are normal.** Let
  `select_recipients` drop them; no `if` at the call site.
- **The actor is not always a technician.** Suppress by id, never by role.
- **`update_work_order` is one write, several events.** Evaluate each rule
  independently.
- **Assignment changes are computed, not declared.** The newly-added set comes
  from `_sync_technician_assignments`; re-sending an unchanged list stays silent.
- **No notifications inside service functions** — they take no FastAPI types, so
  `BackgroundTasks` cannot reach them. The trigger belongs at the router.
- **Do not batch or digest.** The one exception is the CSV import
  (`work_order.supervisor_assigned_bulk`), argued from observed volume (N14 in
  `open-work.md`) and scoped to the import.
- **Fire on a change, not on a field being present.** The editor sends the
  whole form; `previous_status`, `newly_assigned_ids`, and
  `newly_routed_supervisor_id` exist because the post-write row cannot tell a
  change from a re-save.

Not built (no opt-out, preferences, or delivery record): see
`notification-events.md`.
