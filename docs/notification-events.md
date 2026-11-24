# Notification Events

The register of every event this system tells someone about: who can raise it
and who is told.

**Living file: a commit that adds, removes, or re-audiences a notification
updates it in the same commit.** A registry that lags the code is worse than
none. To *wire* a notification, see `adding-a-notification-trigger.md`.

Code beats this file. Event names, audiences, and text live in
`backend/app/domain/notifications.py`; recipient resolution in
`services/notifications.py`; realtime audiences in `domain/realtime.py`. Grep
the named constants rather than re-deriving an audience from a screen.

---

# Part 1 — Web Push

These reach a phone: delivered by a background task after the response, to every
registered device of each recipient, and shown on a locked screen.

## Who is told

| Event | Raised by | Trigger site | Told |
| --- | --- | --- | --- |
| `work_order.assigned` | Team Lead+ (only they edit assignments) | `PATCH /work-orders/{id}` | the technicians **newly added** — not the whole list. **Begin Charging adds the caller to the crew silently**: `tracking/start` records no `newly_assigned`; a self-assignment is not news to the caller |
| `work_order.completed` | an assigned worker who is Team Lead+, or any Team Lead+ editor | `POST .../complete`, and `PATCH` to `completed` | everyone at `COMPLETED_AUDIENCE_MIN_ROLE` (**Admin**+) |
| `work_order.reopened` | Team Lead+ | `PATCH` only | assigned technicians + routed Team Lead |
| `work_order.returned_from_review` | Team Lead+ — in practice the Admin Review page's Return button | `PATCH`, `review → in_progress` | assigned technicians + routed Team Lead |
| `work_order.held` | an assigned worker (Technician+), or any Team Lead+ editor | `POST .../hold`, `PATCH` to `on_hold`, and `POST .../tracking/stop` **only when it auto-holds** | the routed Team Lead — or `UNROUTED_HOLD_AUDIENCE_MIN_ROLE` (**Admin**+) when nobody is routed |
| `work_order.held_for_review` | an assigned **Technician** — the role is what makes their finish a handoff | `POST .../complete` when it lands `ready_to_complete` | the routed Team Lead — or **Admin**+ when nobody is routed |
| `work_order.sent_back` | Team Lead+ — in practice the card's **Send Back** button | `PATCH`, `ready_to_complete → in_progress` | assigned technicians + routed Team Lead |
| `work_order.supervisor_assigned` | Team Lead+ (routing is not Admin-only) | `PATCH` that *changes* `supervisor_id` to somebody | the newly routed Team Lead only |
| `work_order.supervisor_assigned_bulk` | TechFM OA+ (whoever ran the import) | `POST /work-orders/import` | each name-matched Team Lead, **once per import** |
| `netfacilities.import_finished` | the capture chain, for the TechFM OA+ user who exported the CSV | `dispatch_capture` (see below) | **the ceremony's own user** — deliberately the actor |
| `netfacilities.import_failed` | same chain | same — instead of `import_finished` when the import or enrichment start fails | the ceremony's own user |
| `item.low_stock` | any stock write, or a threshold raise | the stock-writing routes (drained by `flush_stock_events`) and `PATCH /items/{id}/low-stock-threshold` | everyone at `LOW_STOCK_AUDIENCE_MIN_ROLE` (**TechFM OA**+), **including the actor** |
| `material_request.filed` | any user who can see the work order (Technician+) | `POST /user-requests/material-request`, **new rows only** — a duplicate filing pushes nobody | everyone at `MATERIAL_REQUEST_AUDIENCE_MIN_ROLE` (**TechFM OA**+), **including the actor** |
| `material_request.stocked` | any stock write, or TechFM OA+ pressing **Mark stocked & notify** | the stock-writing sites (as `item.low_stock`, minus the threshold route); `POST /user-requests/{id}/mark-stocked` | the work order's assigned technicians + routed Team Lead **at stocking time** + the original filer, **actor kept** |
| chat message (not in `ALL_EVENTS`; `build_chat_message`) | any chat member | `POST /messages/conversations/{id}/messages` | the conversation's other members, **sender excluded**. Title "TechFM", body "New message from `{sender_name}`" — never message text or a group name. Payload carries `chat` (conversation id); tag `chat-<id>` with `renotify`, so a busy chat re-alerts as one notification; tap opens that chat |

**Actor handling.** Every other rule suppresses the acting user **by id, never
by role** (a Team Lead completing on someone's behalf is the actor too),
centrally in `select_recipients`, which also drops `None` and de-duplicates. The
three state alarms (`item.low_stock`, `material_request.filed`,
`material_request.stocked`) keep the actor: whoever took the last of an item is
standing at the empty shelf, the filer wants confirmation the request went up,
and a restocking Team Lead on the crew is exactly who should see the line is
ready. Low stock inverts via `actor_id=None` in `recipients_for_low_stock`.

**The NetFacilities chain** (`dispatch_capture`, `services/netfacilities_cloud_chain.py`)
is run by `netfacilities_cloud_auth` (auto-capture) and `routers/netfacilities.py`
(import route). It is the one deliberate inversion of actor suppression: the
unattended chain runs after the user clicked *Download CSV* in a cloud browser
window and maybe closed the tab, so its owner must hear how it ended and push is
the only channel left. Bodies are counts and a stage word, built by
`build_netfacilities_chain_message` (not a `build_message` template) because
reconcile clauses appear only when non-zero.
`notify_netfacilities_chain_finished` is called **synchronously** from the chain
— the one exception to "every notifier goes through BackgroundTasks"; the chain
has no request, so no `BackgroundTasks` exists.

## What each one says

Text renders on a locked phone, so a work-order **number**, a **count**, and an
item **name** / **quantity** are the only variables. No customer, address,
description, note text, or price.

- `count` exists for the bulk event only: "40 work orders have been assigned to
  you" names no job, and tells a stranger nothing the icon badge would not.
- `name` / `quantity` exist for low stock: an item name is a catalogue string
  that identifies no person, site, or job, and without it nobody can act on a
  lock screen. A *price* stays forbidden. The material-request events pair
  `name` with `number`.

| Event | Title | Body |
| --- | --- | --- |
| `work_order.assigned` | Work order assigned | You were assigned to `{number}`. |
| `work_order.completed` | Work order completed | `{number}` was marked Completed. |
| `work_order.reopened` | Work order reopened | `{number}` is no longer Completed. |
| `work_order.returned_from_review` | Work order returned | `{number}` came back from Review and needs another look. |
| `work_order.held` | Work order on hold | `{number}` was placed On-Hold. |
| `work_order.held_for_review` | Work order ready for review | `{number}` is finished and waiting on your review. |
| `work_order.sent_back` | Work order sent back | `{number}` was sent back and needs more work. |
| `work_order.supervisor_assigned` | Work order assigned to you | `{number}` has been assigned to you. |
| `work_order.supervisor_assigned_bulk` | Work orders assigned to you | `{count}` work orders have been assigned to you. |
| `netfacilities.import_finished` | NetFacilities import finished | Imported `{created}` work orders; enrichment started. |
| `item.low_stock` | Low stock | `{name}` is down to `{quantity}`. |
| `material_request.filed` | Material requested | `{name}` is needed for `{number}`. |
| `material_request.stocked` | Material in stock | `{name}` for `{number}` is now in stock. |
| `netfacilities.import_failed` | NetFacilities import needs you | Names the failing stage and next move: *import* → still signed in, export again; *enrichment* → imported `{created}` work orders, click Enrich when it frees up. |

An import that matched a Team Lead to exactly **one** work order sends the
singular `work_order.supervisor_assigned` text, naming the number.

## The one non-work-order send

| What | Raised by | Trigger site | Told |
| --- | --- | --- | --- |
| Push probe | **Owner only** | `POST /push/test` | every device of every user at `TEST_AUDIENCE_MIN_ROLE` (**Admin**+), actor included |

Fixed text: "Inventory" / "Test notification. Push is working on this device."
The Owner is deliberately in their own audience so the loop can be proven on one
phone. `TEST_AUDIENCE_MIN_ROLE` and `SUBSCRIBE_MIN_ROLE` look redundant and are
not; collapsing them makes the test button buzz every technician.

## Who can receive anything at all

- **`SUBSCRIBE_MIN_ROLE` = Technician** (`routers/push.py`, mirrored in
  `static/views/push.js`) — who is *offered* the opt-in button. Technician,
  because assignment and reopen pushes address technicians by id.
- `POST /push/subscribe` accepts any authenticated user. A subscription grants
  no authority; the floor is a product decision, not a security gate.
- **Archived users are excluded by the query**, not by any caller.
- A recipient with no subscription is not an error: they get nothing, and it is
  not retried, queued, or recorded.

## Rules that hold for every row

- **A push never fails a write.** The durable write committed first; resolution
  and delivery swallow their failures.
- **No recipients, or no VAPID key, means no task** — no guaranteed failure per
  device per response.
- **One event, one notification, with one named exception:**
  `work_order.supervisor_assigned_bulk` is one send per Team Lead per import.
  Forty pushes in a few seconds is a denial of service on the person who most
  needs to read them. The exception is the *import*, not a licence to digest.

## Why some of these are separate rules

Read before "simplifying" two rows into one.

- **Reopen has exactly one trigger site.** `start` / `hold` / `resume` reject a
  Completed row, so the Team Lead+ PATCH is the only way out of Completed.
- **Completed → Review is carved out of reopen.** Review is the forward handoff,
  not work coming back; "no longer Completed" would read as a setback. Owner
  decision, pinned by two tests (Review is silent; the carve-out stays one).
- **Reopen, Returned-from-Review, and Sent-back share an audience (assignees +
  Team Lead) and stay three rules.** Live again / an Admin wants changes / the
  crew's own Team Lead rejected the handoff are three different next moves, and
  the words are the only thing carrying which.
- **Send Back and the Review return send byte-identical payloads** (`PATCH
  {status: "in_progress"}`); only `previous` differs. Their arms cannot overlap,
  but `test_send_back_is_its_own_event_not_a_return_from_review` pins the
  wording because nothing else would catch a mix-up.
- **Branch order decides overlapping transitions.** `review → completed` is a
  completion (that arm is first); `completed → on_hold` is a hold (the On-Hold
  arm sorts first — the reopen audience already contains the routed Team Lead,
  so both would buzz one person twice). A new overlapping rule needs a test
  pinning which wins.
- **One endpoint, different events.** `POST /complete` raises *completed* or
  *held_for_review* by the **resulting status**
  (`domain.work_orders.completion_target_status`), never by re-reading the role;
  reading it twice is how the notification and the database disagree.
- **`work_order.held` has a conditional fourth site.** `POST /tracking/stop`
  fires it only when the stop closed the last running clock on an In-Progress
  row and the order put itself On-Hold. A stop that leaves a co-worker tracking,
  or an idempotent repeat, notifies nobody — the `previous is not None and
  previous != status` guard makes both correct. This is the largest source of
  alert volume (lunch, parts runs, end of shift). If noisy, the mitigation is
  one condition at that site: suppress on the auto-hold path only.
- **Starting a clock notifies nobody**, by decision. It can emit one `held`
  indirectly: a clock the caller had on a *different* order is closed and may
  auto-hold; it comes back via `side_transitions` so its alert is not dropped.
- **Routing a Team Lead is evaluated outside the transition chain**, beside the
  assignment rule: one PATCH can route *and* change status, and `elif`s drop the
  second arm. Someone routed and also added as a technician in one write gets
  two notifications; they say different things, and suppression is per-rule.
- **`supervisor_assigned` fires on a change, not a field.** The editor sends the
  whole form, so payload presence would re-notify on every note save.
  `services/work_orders.newly_routed_supervisor_id` carries the fact off the
  write. Clearing the routing sends nothing.
- **The import counts only rows it created — a deliberate under-count.** Routing
  *existing* unrouted orders is silent, so the push and the on-screen
  `supervisors_matched` (same branch) can never disagree. Owner decision.
  Widening one without the other is the bug this prevents.
- **Hold fallback branches on who is routed**, never on how many recipients
  survived suppression: a Team Lead pausing their own job must not escalate to
  every Admin.

---

# Part 2 — Realtime broadcast

Not notifications: cache-invalidation envelopes over `/ws` to clients
**connected right now**. They carry no row data and tell a page to refetch.
Listed here so nobody reaches for one when they meant a push.

| Event | Trigger sites | Received by |
| --- | --- | --- |
| `work_order.review_queue.changed` | import, legacy archive, `PATCH`, archive, restore | **TechFM OA**+ |
| `work_order.status.changed` | every work-order write: import, `PATCH`, start/complete/hold/resume, archive/restore, tracking, signature, material and labor lines, SMR `ready` / `paper-reviewed` / lines / `block` / `pasted` | **Technician**+ |
| `labor.session.changed` | tracking `start` / `stop` | **Team Lead**+ |
| `attendance.changed` | `punch-in`, `punch-out`, the three `/hub/attendance/punches` writes | **Admin**+ |
| `item.low_stock.changed` | an item entering/leaving the low-stock set; threshold edit; item create or archive | **TechFM OA**+ |
| `user_request.changed` | filing, `mark-stocked`, `cancel`, `PATCH`, any stock write that stocks or un-stocks a request, adding from a stocked line, catalogue fulfilment | **Technician**+ |

Raised by any caller authorized for the write. Differences from Part 1:

- **The actor is not suppressed** — fan-out filters on role only. Right for a
  cache signal, wrong for a notification.
- **The audience map is not a security boundary.** No data rides along; REST
  re-authorizes the refetch.
- **An unknown event type reaches nobody.** A new event without an
  `_AUDIENCE_MIN_ROLE` entry fails closed and silently.
- **Offline users miss it** — no queue, no replay. If it must reach a pocketed
  phone, it belongs in Part 1.

---

## Keeping this file honest

- **New push event** — a row in *Who is told* and *What each one says*; a bullet
  in *Why some of these are separate rules* if the reason is not obvious.
- **New trigger site** — extend that row's cell; a second site is where
  double-notification bugs live.
- **Changed audience** — update the row and the constant. The audience constants
  (e.g. `COMPLETED_AUDIENCE_MIN_ROLE` vs `UNROUTED_HOLD_AUDIENCE_MIN_ROLE`) are
  deliberately separate and must be able to diverge.
- **New realtime event** — a Part 2 row and an `_AUDIENCE_MIN_ROLE` entry.
- **Removed event** — delete the row; git holds history.

## Deliberately not built

No per-user opt-out, per-event preferences, or delivery record (routing is by
role and assignment only; "was this person notified?" has no answer — counts are
logged and discarded, and a record is a schema change, not a trigger).

**Losing a work order is not an event.** Re-routing tells the new Team Lead and
nothing to the old one, who may keep working a job that is no longer theirs.
`recipients_for_supervisor_assignment` looks like an oversight and is not; if it
is built, it is a new event with its own words, not a second recipient here.
