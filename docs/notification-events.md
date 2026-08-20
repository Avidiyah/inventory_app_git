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
| Trigger sites | `backend/app/routers/work_orders.py` |
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

**Every rule suppresses the acting user, by id.** A supervisor completing work
on someone else's behalf is as much the actor as a technician is, so
suppression never reads a role. It happens centrally in
`select_recipients`, which also drops `None` and de-duplicates — a supervisor
who is also an assignee is one person and gets one notification.

## What each one says

Notification text renders on a locked phone, so a work-order **number** is the
only variable any of these interpolate. No customer, no address, no
description, no note text, no price.

| Event | Title | Body |
| --- | --- | --- |
| `work_order.assigned` | Work order assigned | You were assigned to `{number}`. |
| `work_order.completed` | Work order completed | `{number}` was marked Completed. |
| `work_order.reopened` | Work order reopened | `{number}` is no longer Completed. |
| `work_order.returned_from_review` | Work order returned | `{number}` came back from Review and needs another look. |
| `work_order.held` | Work order on hold | `{number}` was placed On-Hold. |
| `work_order.held_for_review` | Work order ready for review | `{number}` is finished and waiting on your review. |

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
- **Nothing is batched or digested.** One event, one notification. Deliberate,
  until real volume argues otherwise.

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
- **Send Back notifies nobody, and that is a stated gap.** A supervisor
  rejecting work from Ready to Complete sends `PATCH {status: "in_progress"}`,
  which matches no arm of the chain, so the technician learns their work came
  back when they next open the app. If field use shows they need a push, it is
  a new arm and a new event following this document — not a change to the
  existing chain.
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
| `work_order.status.changed` | any caller authorized for the write | `PATCH`, `start`, `complete`, `hold`, `resume`, archive, restore | connected clients at **Technician** and above |

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

If someone asks "was this person notified?", the honest answer today is that the
counts were logged and discarded. Adding a delivery record is a schema change,
not a trigger.
