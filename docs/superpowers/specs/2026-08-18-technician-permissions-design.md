# Technician permissions: own labor, no completion, supervisor hold alerts — design

Date: 2026-08-18
Status: approved, ready for implementation planning

## Problem

Three related gaps in what a Technician can do, and one in what a Supervisor
is told.

1. **Labor is Supervisor+ only.** A tech logs their own materials all day
   (`POST /work-orders/{id}/items`) but cannot log the hours they just worked.
   Someone else has to key their time in from memory or a text message.
2. **A Technician can declare their own work Completed.** `POST
   /work-orders/{id}/complete` moves an assigned worker's In-Progress row
   straight to Completed with nobody looking at it. Completed is a billing
   state — it is what the Admin Review queue and the client export read.
3. **Nothing tells a Supervisor a job stopped.** On-Hold is reachable from the
   tech walkthrough, from a Supervisor's status dropdown, and from an Admin's
   manual edit. None of the three notifies anybody, so a paused job is
   invisible until someone opens the card.

## Goal

- A Technician may record labor **for themselves**.
- A Technician may no longer reach Completed. Their "Mark Completed" button
  places the work order **On-Hold**, writes an authored, timestamped note, and
  tells the routed Supervisor the work is waiting on review.
- **Every** entry into On-Hold notifies the routed Supervisor, whatever caused
  it.
- A Supervisor can finish the loop in one tap from the On-Hold card.

## Superseded prior decisions

Two earlier decisions are partly reversed here. Both were deliberate, so both
are named rather than quietly overwritten:

- **IMP-014** locked all labor create/edit/remove to Supervisor+ (recorded in
  `current-state.md` under `work_order_labor`). This design reopens **create,
  for the acting technician's own row only**. Edit and remove stay Supervisor+,
  which is the part of IMP-014 that was actually protecting the billing figure.
- **IMP-029** added `POST /work-orders/{id}/complete` as a narrow assigned-worker
  step that reached Completed "without expanding general Technician status
  permissions." The endpoint survives; for a Technician its destination changes.
  The two-person Review handoff that IMP-029 established is untouched.

## Non-goals

- No change to the Review handoff, its Admin floor, or its second-person rule.
- No new status value. On-Hold is reused; the note distinguishes *why*.
- No per-user notification preferences, no digesting. One event, one send.
- No schema or migration change. Every column already exists.

---

## 1. Technicians record their own labor

### Rule

| Operation | Today | After |
| --- | --- | --- |
| `POST /work-orders/{id}/labor` | Supervisor+ | Supervisor+, **or a Technician whose `technician_id` is their own** |
| `PATCH …/labor/{labor_id}` | Supervisor+ | unchanged |
| `DELETE …/labor/{labor_id}` | Supervisor+ | unchanged |

A technician logs; a supervisor corrects. A tech cannot revise or erase hours
after the fact, which is the property that keeps the billed figure trustworthy.

The existing assignment check is unchanged and still applies first: labor may
only be attributed to a worker assigned to that work order
(`InvalidAssigneeError`). For a technician the new rule is strictly narrower —
they must be assigned *and* be the subject of the row.

### Where it lives

`_require_labor_actor` in `services/work_orders.py:1780` is called by all three
operations and cannot express a per-operation rule. It splits:

- `_require_labor_manager(user)` — the current Supervisor+ check, kept verbatim,
  used by `update_work_order_labor` and `delete_work_order_labor`.
- `_require_labor_author(user, technician_id)` — Supervisor+ passes unchanged;
  otherwise the caller must be recording their own id. Used by
  `add_work_order_labor`.

The refusal message names the actual restriction: *"A Technician can only record
their own labor."*

### Front end

`laborSectionHtml` is rendered today only for `isSupervisorPlus()`
(`views/workOrders.js:1090`). It renders for an **assigned technician** too, in
a reduced form:

- `canEditLabor()` stays `isSupervisorPlus()`, so a tech sees existing rows
  read-only — no hours input, no Update, no Remove.
- `laborTechnicianControl` renders the technician `<select>` for a supervisor as
  it does now; for a technician it renders their own name as fixed text plus a
  hidden value, so there is no picker to aim at somebody else.
- The rate/mark-up hint already redacts money below TechFM OA
  (`detail.labor_rate` is `None`), so the tech's view carries hours and no
  prices. No new redaction needed.

---

## 2. A Technician's "Mark Completed" lands On-Hold

### The rule is the role's, and it is pure

New in `domain/work_orders.py`:

```python
def completion_target_status(role: str) -> str:
    """Where a walkthrough completion actually lands for `role`."""
```

Returns `STATUS_ON_HOLD` for `ROLE_TECHNICIAN`, `STATUS_COMPLETED` for anyone
Supervisor or above (and for a `None`-role internal caller). One pure function,
unit-tested without a session, and the single place the policy is written.

Keying on **role, not on assignment**, is deliberate. A Supervisor who is also
an assigned worker hits the tech walkthrough branch in the UI
(`views/workOrders.js:1016` is evaluated before `:1022`), so an assignment-based
rule would strip Supervisors of completion as a side effect.

Also new, beside `NOTE_TIMEZONE`:

```python
REVIEW_HOLD_NOTE = "Placed On-Hold for Supervisor Review"
```

### Service behaviour

`complete_work_order` (`services/work_orders.py:1389`) asks the domain for its
target and branches on the answer. Everything before that — the Technician+
floor, the visibility check, the row lock, the assigned-worker check — is
unchanged.

| Target | Status written | `completed_at` | Note appended |
| --- | --- | --- | --- |
| `completed` | `completed` | `now()` | none |
| `on_hold` | `on_hold` | `None` | `REVIEW_HOLD_NOTE` |

The note goes through the existing `append_note_log`, authored by the acting
technician. That helper already stamps `[2:14 PM] [081826] [Jane Doe] …` in
America/Chicago, so the requested "note and timestamp" needs no new format and
no new column — the log line *is* the timestamp.

**Idempotency moves with the target.** The current early return is
`if work_order.status == STATUS_COMPLETED: return unchanged`. It becomes a
comparison against the *target* status, so a tech's second tap on an already
On-Hold row returns unchanged — no duplicate note, no second notification.
Every other source status still raises, and the error text names the target the
caller would actually have reached.

### Front end

- The button keeps its label, `Mark Completed`.
- On success the card reports **"Sent to your supervisor for review."** — a
  status message on the existing `.wo-message` element, so the On-Hold badge
  that appears a moment later reads as the intended outcome rather than a
  failed save. A Supervisor+ using the same button gets no such message; their
  row really did complete.
- The message is chosen from the refreshed row's status, not from the role, so
  the UI and the server can never disagree about which happened.

---

## 3. Supervisor+ can complete a reviewed job in one tap

With Technicians out of Completed, every job now passes through a Supervisor —
but the On-Hold card renders only a hint today (`views/workOrders.js:1024`), so
finishing one means opening Edit details and using a status dropdown, every
time.

The On-Hold branch gains a **`Mark Completed`** button for Supervisor+, reusing
the existing `complete-wo` action (`PATCH {status: "completed"}`) and therefore
the existing permissions, notification, and realtime paths. No new endpoint.

The rollback hint stays beside it.

One structural note: the assigned-worker On-Hold branch (`:1020`, `Resume
In-Progress`) is evaluated before the supervisor branch, so a Supervisor who is
also an assigned worker currently sees Resume only. That branch is restructured
to render Resume when assigned **and** Mark Completed when Supervisor+, rather
than one or the other.

---

## 4. On-Hold notifies the routed Supervisor

### Audience

`work_order.supervisor_id` and nobody else — the literal "Supervisors assigned
to the work order only". Actor-suppressed like every other rule, so a
Supervisor who holds a job themselves stays silent.

**Accepted consequence:** an unrouted work order (`supervisor_id IS NULL`)
notifies no one. `select_recipients` drops `None` and `_schedule` returns early
on an empty list, so this costs one list comprehension and no task. Owner
decision, 2026-08-18, chosen over a Supervisor-wide fallback.

### Two events, not one

| Event | Body | Raised by |
| --- | --- | --- |
| `work_order.held` | `{number} was placed On-Hold.` | `/hold`, and a PATCH into `on_hold` |
| `work_order.held_for_review` | `{number} is finished and waiting on your review.` | `/complete` when it lands On-Hold |

Same audience, two rules — which `adding-a-notification-trigger.md` explicitly
sanctions ("Two rules can share an audience and still be two rules"). The
supervisor's next action differs completely between "the crew paused" and "the
crew is done": one is a scheduling problem, the other is a review task. Merging
them would delete the only thing the lock screen needs to convey.

Both bodies carry the work-order number and nothing else, per notification
rule 1. Neither leaks the note text.

### Rule and service

`domain/notifications.py` gains both event constants, both message pairs, and
one shared selector:

```python
def recipients_for_hold(*, supervisor_id, actor_id):
    """The routed supervisor owns a stopped job; the actor already knows."""
    return select_recipients([supervisor_id], actor_id=actor_id)
```

`services/notifications.py` gains `notify_work_order_held` and
`notify_work_order_held_for_review`, both reading `work_order.supervisor_id`
during the request, per rule 4.

### Trigger sites

Three, each behind the mandatory
`previous is not None and previous != work_order.status` guard:

1. **`POST /{id}/hold`** — needs `background: BackgroundTasks` added to the
   handler signature as a plain parameter. Fires `held`.
2. **`POST /{id}/complete`** — chooses by the *resulting status*, not by role:
   `on_hold` fires `held_for_review`, `completed` keeps firing `completed`
   exactly as it does now.
3. **PATCH** — a new arm in `_notify_work_order_patch`.

### PATCH branch order

The `elif` chain in `routers/work_orders.py:157` has an overlap to resolve:
`completed → on_hold` is both "leaves Completed" (the reopen rule) and "entered
On-Hold". Firing both would buzz the routed supervisor twice for one edit,
because the reopen audience already includes them.

The On-Hold arm therefore goes **first**:

```
if   status == ON_HOLD                          -> held
elif status == COMPLETED                        -> completed
elif previous == COMPLETED and status != REVIEW -> reopened
elif previous == REVIEW and status == IN_PROGRESS -> returned_from_review
```

`completed → on_hold` fires `held` only. The assignees are deliberately not told
— the row is paused, not handed back to them, and "no longer Completed" would be
inviting work that is not yet available. That transition is reachable from the
UI: the Edit-details dropdown offers On-Hold on a Completed row
(`editableStatusOptions`, `views/workOrders.js:594`).

`review → on_hold` is API-only — `statusEditorHtml` disables the status field
outright for a Review row — but the new arm covers it, and it does not collide
with `returned_from_review`, which requires In-Progress specifically.

Two tests pin this ordering, as the trigger doc requires for any overlapping
transition.

### A note on "Re-open"

The **Reopen** button sends `{status: "in_progress"}`
(`views/workOrders.js:1241`), so it lands In-Progress and never On-Hold. It
already fires the existing `reopened` rule to assignees + supervisor, so the
supervisor is told either way. The On-Hold-from-reopen case in the request is a
supervisor or admin selecting **On-Hold** in the Edit-details status dropdown,
which trigger site 3 covers.

---

## Permission matrix after this change

| Action | Technician | Supervisor+ |
| --- | --- | --- |
| Add labor for self | ✅ new | ✅ |
| Add labor for another worker | ❌ | ✅ |
| Edit / remove any labor | ❌ | ✅ |
| Walkthrough completion → Completed | ❌ removed | ✅ |
| Walkthrough completion → On-Hold + review note | ✅ new | — |
| PATCH status directly | ❌ unchanged | ✅ |
| Send to Review | ❌ | Admin+ / unassigned routed Supervisor (unchanged) |

---

## Testing

| Layer | File | Pins |
| --- | --- | --- |
| Domain | `test_work_orders_domain.py` | `completion_target_status` per role, including the `None` internal caller |
| Domain | `test_notifications_domain.py` | hold recipients, actor suppression, `None` supervisor drops to empty, both message bodies |
| Service | `test_work_orders_service.py` | tech add-own-labor allowed; tech add-for-another refused; tech edit/delete refused; supervisor unchanged; tech completion lands On-Hold with `completed_at is None` and one appended note; second tap appends nothing; supervisor completion still reaches Completed |
| Route | `test_work_orders_notifications.py` | `/hold` fires `held`; `/complete` fires `held_for_review` for a tech and `completed` for a supervisor; idempotent repeat fires nothing; `completed → on_hold` fires `held` and **not** `reopened`; `review → on_hold` fires `held`; unrouted work order schedules no task |
| Gates | `test_route_role_gates.py` | no new route gate left at the Admin floor |

Frontend changes are verified by `node --check` plus the focused source-contract
assertions this repo already uses, then owner browser QA — per the standing
policy that click-through is owner-performed.

Delivery itself is not re-proved; the transport has its own tests. Step 5 of
`adding-a-notification-trigger.md` (real-phone check, event caused from a
different account, actor's own phone silent) applies to both new events before
merge.

## Docs to update

`current-state.md` (labor floor, walkthrough contract, role matrix rows 756 /
816 / 867 / 1219 / 1528–1530), `endpoint-map.md` (`/complete`, `/hold`,
`POST …/labor`), and the **Currently wired** table plus the branch-order note in
`adding-a-notification-trigger.md`.

## Risks

- **A tech's muscle memory says "Completed" and the badge says On-Hold.** The
  result message is the whole mitigation. If it proves confusing in the field,
  relabelling the button is a one-line follow-up.
- **Unrouted work orders hold silently.** Named above and accepted. If it bites,
  the fallback to Supervisor-wide is a change to one domain function.
- **Stale cached clients.** The remap is server-side and the endpoint keeps its
  path and shape, so a tech running an old cached SPA gets the new behaviour
  rather than a 403 — the reason this design does not add a separate
  `/submit-review` route.
