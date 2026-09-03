# Notification Events

The register of every event this system tells someone about: what raises it,
who can raise it, and who is told.

**This file is living. A commit that adds, removes, or re-audiences a
notification updates this file in the same commit.** That is the whole point of
it — a registry that lags the code is worse than no registry, because the next
person trusts it. If you are *wiring* a notification rather than recording one,
the procedure is `adding-a-notification-trigger.md`; this file is the record of
what came out of it.

Sources of truth, in the order to trust them: the code, then this file. The
constants named below are real symbols — grep them rather than re-deriving the
audience from a screen.

| Layer | File |
| --- | --- |
| Event names, audiences, message text | `backend/app/domain/notifications.py` |
| Recipient resolution against the database | `backend/app/services/notifications.py` |
| Trigger sites | `backend/app/routers/work_orders.py`, `backend/app/services/netfacilities_cloud_auth.py` |
| Subscription floors, the Owner probe | `backend/app/routers/push.py` |
| Realtime vocabulary and audiences | `backend/app/domain/realtime.py` |

---

# Part 1 — Web Push

These reach a phone. Each one is delivered by a background task after the
response, to every device the recipient has registered, and renders on a locked
screen whether or not the app is open.

## Who is told

| Event | Raised by | Trigger site | Told |
| --- | --- | --- | --- |
| `work_order.assigned` | Supervisor+ (only they may edit assignments) | `PATCH /work-orders/{id}` | the technicians that write **newly added** — not the whole assignee list |
| `work_order.completed` | an assigned worker who is Supervisor+, or any Supervisor+ editor | `POST /work-orders/{id}/complete`, and `PATCH` to `completed` | everyone at `COMPLETED_AUDIENCE_MIN_ROLE` (**Admin** and above) |
| `work_order.reopened` | Supervisor+ | `PATCH` only | assigned technicians + the routed supervisor |
| `work_order.returned_from_review` | Supervisor+ — in practice the Admin Review page's Return button, the only UI that sends it | `PATCH`, `review → in_progress` | assigned technicians + the routed supervisor |
| `work_order.held` | an assigned worker (Technician+), or any Supervisor+ editor | `POST /work-orders/{id}/hold`, `PATCH` to `on_hold`, and `POST /work-orders/{id}/tracking/stop` **only when it auto-holds** (see below) | the routed supervisor — or `UNROUTED_HOLD_AUDIENCE_MIN_ROLE` (**Admin** and above) when nobody is routed |
| `work_order.held_for_review` | an assigned **Technician** — the role is what makes their finish a handoff | `POST /work-orders/{id}/complete` when it lands `ready_to_complete` | the routed supervisor — or **Admin** and above when nobody is routed |
| `work_order.sent_back` | Supervisor+ — in practice the work-order card's **Send Back** button, the only UI that sends it | `PATCH`, `ready_to_complete → in_progress` | assigned technicians + the routed supervisor |
| `work_order.supervisor_assigned` | Supervisor+ (routing is a `_SUPERVISOR_UPDATE_FIELDS` edit, **not** Admin-only) | `PATCH` that *changes* `supervisor_id` to somebody | the newly routed supervisor, and nobody else |
| `work_order.supervisor_assigned_bulk` | TechFM OA+ (whoever ran the import) | `POST /work-orders/import` | each supervisor the import name-matched, **once for the whole import** |
| `netfacilities.import_finished` | the capture chain, acting for the TechFM OA+ user who exported the CSV | `netfacilities_cloud_auth.dispatch_capture` -- the automatic capture trigger and `POST /integrations/netfacilities/cloud/downloads/import` both run it | **the ceremony's own user** -- deliberately the actor; see below |
| `netfacilities.import_failed` | same chain | same -- fired instead of `import_finished` when the import or the enrichment start fails | the ceremony's own user |
| `item.low_stock` | any stock write, or a threshold raise | `POST /transactions/`, `POST /transactions/adjust`, `DELETE /transactions/{id}`, `POST /mass-stages/{id}/load`, `POST /mass-stages/{id}/return`, the three `/work-orders/{id}/items` routes, `PATCH /items/{id}/low-stock-threshold` | everyone at `LOW_STOCK_AUDIENCE_MIN_ROLE` (**TechFM OA** and above), **including the actor** |

`item.low_stock` does not suppress the actor. It is a state alarm about
the stockroom rather than a report of somebody's action, and whoever just
took the last of an item is standing in front of the empty shelf. The
inversion is expressed as `actor_id=None` in
`recipients_for_low_stock`, not by skipping `select_recipients`.

**Every other rule suppresses the acting user, by id.** A supervisor completing work
on someone else's behalf is as much the actor as a technician is, so
suppression never reads a role. It happens centrally in
`select_recipients`, which also drops `None` and de-duplicates — a supervisor
who is also an assignee is one person and gets one notification.

## What each one says

Notification text renders on a locked phone, so a work-order **number**, a
**count**, and an item **name** / **quantity** are the only variables any of
these interpolate. No customer, no address, no description, no note text, no
price.

`count` exists for one event. "40 work orders have been assigned to you" names
no work order, no customer, and no job — a tally of your own queue tells a
stranger holding the phone nothing the app's icon badge would not. That is the
whole argument for widening `build_message` past a number.

`name` / `quantity` exist for the low-stock event. An item name is a
catalogue/manufacturer string ("3M Blue Tape") that identifies no person, site,
or job, and without it the notification is unactionable -- nobody reads a
barcode off a lock screen. A *price* on the same item stays forbidden.

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
| `netfacilities.import_failed` | NetFacilities import needs you | Names the failing stage and the next move: *import* → still signed in, export again; *enrichment* → imported `{created}` work orders, click Enrich when it frees up. |

An import that matched a supervisor to exactly **one** work order sends the
singular `work_order.supervisor_assigned` text instead, naming the number. Correct
grammar is the smaller reason; the larger one is that a supervisor who received
one work order can be told which one.

## Why the chain events notify the actor

`netfacilities.import_finished` / `netfacilities.import_failed` are the one
deliberate inversion of the actor-suppression rule. The unattended capture
chain (auto-capture spec, E10) runs after the user clicked *Download CSV* in
a cloud browser window and possibly closed the tab; its owner is the one
person who must hear how it ended, and a push is the only channel that still
reaches them. Their bodies are counts and a stage word only -- built by
`build_netfacilities_chain_message`, not a `build_message` template, because
the reconcile clauses appear only when non-zero. Text lives beside the other
events in `domain/notifications.py`.

## The one non-work-order send

| What | Raised by | Trigger site | Told |
| --- | --- | --- | --- |
| Push probe | **Owner only** | `POST /push/test` | every device of every user at `TEST_AUDIENCE_MIN_ROLE` (**Admin** and above), actor included |

Fixed text — "Inventory" / "Test notification. Push is working on this device."
It is the Owner's diagnostic and deliberately includes the Owner in its own
audience, so the loop can be proven on one phone without a second person.

`TEST_AUDIENCE_MIN_ROLE` and `SUBSCRIBE_MIN_ROLE` look redundant and are not.
Collapsing them is how the Owner's test button starts buzzing every
technician's phone.

## Who can receive anything at all

- **`SUBSCRIBE_MIN_ROLE` = Technician** (`routers/push.py`, mirrored in
  `static/views/push.js`) — who is *offered* the opt-in button. Technician,
  because assignment and reopen notifications are addressed to technicians by
  id: a technician never offered the button can never be reached by them.
- `POST /push/subscribe` itself accepts any authenticated user. Holding a
  subscription grants no authority, so the floor above is a product decision
  about who is asked, not a security gate.
- **Archived users are excluded by the query**, not by any caller.
- A recipient with no subscription is not an error. They receive nothing and
  the event is not retried, queued, or recorded.

## Rules that hold for every row above

- **A push never fails a write.** The durable write committed before any of
  this ran. Rule resolution and delivery both swallow their failures.
- **No recipients means no task.** The common case on a small crew is an
  audience that empties out under actor suppression; it costs one list
  comprehension.
- **No VAPID key means no task**, rather than one guaranteed failure per device
  per response.
- **Nothing is batched or digested, with one named exception.** One event, one
  notification — except `work_order.supervisor_assigned_bulk`, which is one send
  per supervisor per import however many rows matched them. Real volume did
  argue otherwise: an import creating forty work orders for one supervisor
  would fire forty pushes in a few seconds, which is not a notification but a
  denial of service aimed at the person who most needs to read it. The
  exception is the *import*, not a general licence to digest.

## Why some of these are separate rules

Read this before "simplifying" two rows into one.

- **Reopen has exactly one trigger site.** The narrow `start` / `hold` /
  `resume` endpoints all reject a Completed row outright, so the only way out of
  Completed is the Supervisor+ PATCH.
- **Completed → Review is carved out of the reopen rule.** It is a move out of
  Completed, so the literal rule would fire, but Review is the forward handoff
  rather than work coming back: the assignees have nothing to do about it, and
  "no longer Completed" reads as a setback. Every other exit from Completed does
  mean the work is live again and does notify. Owner decision, 2026-08-18,
  pinned by two tests — one that Review is silent, one that the carve-out stays
  a carve-out.
- **Reopen and Returned-from-Review share an audience and stay two rules.**
  Both address the assignees plus the supervisor. One says the work is live
  again; the other says somebody looked at it and wants it changed. Merging them
  to remove the duplication would delete the only thing the recipient actually
  needs from a lock screen.
- **Branch order decides overlapping transitions.** `review → completed` is both
  "leaves Review" and "is now Completed"; it resolves as a completion because
  that arm comes first. `completed → on_hold` is both "leaves Completed" and
  "entered On-Hold"; the On-Hold arm sorts ahead of everything, so it is a hold
  — the reopen audience already contains the routed supervisor, and evaluating
  both would buzz one person twice for one edit. A new rule whose transition can
  overlap an existing one needs a test pinning which wins.
- **One endpoint can raise different events.** `POST /complete` raises
  *completed* or *held_for_review* depending on where the row landed, which is a
  function of the caller's role (`domain.work_orders.completion_target_status`).
  The router chooses from the **resulting status**, never by re-reading the
  role — reading it twice is how the notification and the database start
  disagreeing. When tracked time promoted the technician's destination from
  `on_hold` to `ready_to_complete`, that comparison was the only line that had
  to move, which is the payoff of choosing from the row.
- **`work_order.held` has a fourth trigger site, and it is conditional.**
  `POST /tracking/stop` fires it *only* when the stop closed the last running
  clock on an In-Progress row and the work order therefore put itself On-Hold.
  A stop that leaves a co-worker tracking changes no status and notifies
  nobody, and an idempotent repeat closes nothing — the standard
  `previous is not None and previous != status` guard is what makes both
  correct. The rule, the audience, and the wording are reused unchanged; only
  the trigger site is new.
  **This is the design's largest new source of alert volume** and is named
  rather than smoothed over: every lunch break, parts run, and end of shift now
  moves a row into On-Hold and pushes to the routed supervisor. That is
  consistent with the existing rule that every entry into On-Hold notifies, but
  that rule was written when On-Hold happened only by deliberate tap. If it
  proves noisy the mitigation is narrow — suppress on the auto-hold path only,
  one condition at one trigger site, leaving `/hold` and the PATCH arm alone.
- **Starting a clock notifies nobody.** `POST /tracking/start` is silent by
  decision, not by omission: starting a timer is not news to a supervisor, and
  the Assigned → In-Progress transition it performs matches no arm of any
  chain. It can still emit one `held` indirectly — if the caller had a clock
  running on a *different* work order, that row is closed here and may
  auto-hold, and it is handed back through `side_transitions` precisely so its
  alert is not silently dropped.
- **Three rules now share the assignees-plus-supervisor audience, and they stay
  three.** Reopen says the work is live again; returned-from-review says an
  Admin looked at it and wants changes; sent-back says the crew's own
  supervisor rejected the handoff. Identical recipient lists, three different
  next moves for the technician, and the words are the only thing that carries
  which. Merging any two of them to remove the duplication deletes the only
  thing the recipient needed from a lock screen — the same argument the
  reopen/returned pair has always rested on, now applying to a third rule.
- **Send Back and the Review return send byte-identical payloads.** Both are
  `PATCH {status: "in_progress"}`; only `previous` tells them apart
  (`ready_to_complete` versus `review`). Their arms cannot currently overlap, so
  the ordering between them is free rather than load-bearing — but
  `test_send_back_is_its_own_event_not_a_return_from_review` pins the wording
  anyway, because they share an audience and nothing else would catch a mix-up.
- **Routing a supervisor is evaluated outside the transition chain**, beside the
  technician-assignment rule and for the same reason: one PATCH can route a
  supervisor *and* move the status, and a chain of `elif`s drops whichever arm
  comes second. A person routed as supervisor and added as a technician in the
  same write receives two notifications. Both are true, they say different
  things, and suppression is per-rule by design.
- **`work_order.supervisor_assigned` fires on a change, not on a field.** The
  editor sends the whole form, so "`supervisor_id` was in the payload" would
  re-notify a supervisor every time somebody saved a note. `services/work_orders.
  newly_routed_supervisor_id` carries the fact off the write, exactly as
  `previous_status` does for transitions — the post-write row cannot tell a real
  re-route from a re-save. Clearing the routing sends nothing.
- **The import counts only rows it created, and that is a deliberate
  under-count.** An import also routes *existing* unrouted work orders to a
  matched supervisor, and those are silent. The reason is that
  `supervisors_matched` — the number the operator sees on screen — is computed on
  the same branch, so the push and the import summary can never tell two people
  different stories about the same upload. Owner decision, 2026-08-20. Widening
  one without the other is the bug this is written to prevent.
- **An audience of one still needs a fallback.** Both hold events address the
  routed supervisor, and an unrouted work order would otherwise alert nobody.
  The fallback branches on *who is routed*, never on how many recipients
  survived suppression: a supervisor pausing their own job must not escalate it
  to every Admin by taking it.

---

# Part 2 — Realtime broadcast

Not notifications. These are cache-invalidation envelopes pushed over the `/ws`
socket to clients that are **connected right now**; they carry no row data and
tell a page to refetch. They are registered here because they are events with a
sender and a role-gated audience, and because it is otherwise easy to reach for
one when you meant a push.

| Event | Raised by | Trigger sites | Received by |
| --- | --- | --- | --- |
| `work_order.review_queue.changed` | any caller authorized for the write | work-order import, legacy archive, `PATCH`, archive, restore | connected clients at **TechFM OA** and above |
| `work_order.status.changed` | any caller authorized for the write | work-order import, bulk legacy archive, `PATCH`, `start`, `complete`, `hold`, `resume`, archive, restore, tracking `start`/`stop` | connected clients at **Technician** and above |
| `labor.session.changed` | any caller authorized for the write | tracking `start`, tracking `stop` | connected clients at **Supervisor** and above |
| `item.low_stock.changed` | any caller authorized for the write | an item entered or left the low-stock set; a threshold edit; item create or archive | connected clients at **TechFM OA** and above |

Four differences from Part 1 that matter:

- **The actor is not suppressed.** Fan-out filters on role and nothing else, so
  the client that caused the change receives its own invalidation. That is
  correct for a cache signal and wrong for a notification.
- **The audience map is not a security boundary.** An envelope carries no data,
  so a mis-scoped audience is a wasted message rather than a disclosure — the
  recipient's refetch is still authorized server-side by REST.
- **An unknown event type reaches nobody.** Adding an event without adding an
  audience fails closed and silently.
- **An offline user misses it entirely.** There is no queue and no replay. If a
  person needs to learn about something while their phone is in their pocket, it
  belongs in Part 1.

---

## Keeping this file honest

When a change touches notifications:

1. **New push event** — add a row to *Who is told* and to *What each one says*.
   If it exists for a reason that is not obvious from the row, add a bullet to
   *Why some of these are separate rules* — that section exists so the arguments
   already settled do not have to be had again.
2. **New trigger site for an existing event** — extend that row's *Trigger site*
   cell. A second site is exactly where a double-notification bug lives.
3. **Changed audience** — update the row *and* the constant name if it moved.
   The constants are load-bearing: `COMPLETED_AUDIENCE_MIN_ROLE` and
   `UNROUTED_HOLD_AUDIENCE_MIN_ROLE` are deliberately separate and must be able
   to diverge.
4. **New realtime event** — add a row to Part 2 and an entry to
   `_AUDIENCE_MIN_ROLE`, or it silently reaches nobody.
5. **Removed event** — delete the row. Git holds the history; a registry of
   things that no longer happen is how this file stops being read.

## Deliberately not built

No per-user opt-out. No per-event preferences. No delivery record. Routing is by
role and assignment only.

**Losing a work order is not an event.** Re-routing tells the new supervisor and
says nothing to the one who held it, who may keep working a job that is no
longer theirs. Named here rather than left undocumented, because the recipient
list in `recipients_for_supervisor_assignment` looks like an oversight and is
not. If it needs building it is a new event with its own words, not a second
recipient bolted onto this one.

If someone asks "was this person notified?", the honest answer today is that the
counts were logged and discarded. Adding a delivery record is a schema change,
not a trigger.
