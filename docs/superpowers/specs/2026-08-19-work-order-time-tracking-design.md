# Work-order time tracking: Start Tracking, labor sessions, and Ready to Complete — design

Date: 2026-08-19
Status: draft, awaiting owner approval

## Problem

Three problems, and the third is the one that forces a migration.

1. **Labor is a hand-keyed number.** `work_order_labor` stores `minutes` and
   nothing else (`models.py:475-497`). A technician types "1.25" into an hours
   box from memory at the end of a job. There is no record of when the work
   started, when it stopped, or whether the number was ever true. The billed
   figure — `$62.50/hour`, `domain/work_orders.py:207-233` — rests entirely on
   that recollection.
2. **On-Hold means two different things.** The 2026-08-18 design routed a
   Technician's completion to On-Hold and distinguished it from an ordinary
   pause with a note string, `REVIEW_HOLD_NOTE`
   (`domain/work_orders.py:76`). That was the cheapest thing that could work
   without a new status. It means a supervisor's On-Hold filter mixes "the crew
   is at lunch" with "the job is done and waiting on you", and the only way to
   tell them apart is to open the card and read the note log.
3. **The technician's status buttons describe the lifecycle, not the work.**
   "Set In-Progress" and "Mark Completed" ask a technician to operate a state
   machine. What the technician actually does is start working and stop working.

## Goal

- Replace the technician walkthrough's status buttons with **Start Tracking**,
  backed by **timestamped labor sessions** rather than a typed duration.
- Promote the overloaded review-hold into a real status, **`ready_to_complete`**
  ("Ready to Complete"), so a supervisor can see and filter the review queue
  without reading note text.
- **Notify Supervisor** replaces "Mark Completed" for a technician: it stops the
  clock and moves the row to Ready to Complete.
- A Supervisor reviews the work order *and the real-world work*, then approves
  to Completed or rejects back to In-Progress.
- A Supervisor who does the work can track their own time **without being
  assigned as a technician**.
- Every start, stop, and finish is written into the **public note log** in a
  single normalized timestamp format that human-typed notes share.
- When the last technician clocks out, the work order **puts itself On-Hold** —
  the status stops being something anyone has to remember to set.

## Superseded prior decisions

Five prior decisions are partly reversed. All were deliberate, so all are named
rather than quietly overwritten.

- **The 2026-08-18 technician-permissions design, section 2.** A Technician's
  walkthrough completion landed On-Hold with `REVIEW_HOLD_NOTE` appended. It now
  lands `ready_to_complete`. `completion_target_status` survives with the same
  signature and the same role-not-assignment reasoning; only its Technician
  return value changes. `REVIEW_HOLD_NOTE` is **replaced** by
  `NOTE_READY_TO_COMPLETE` — the status now carries the state, so the note
  describes the action instead (section 4). Historical note text already written
  into `work_orders.notes` stays as it is; the log is append-only and those lines
  remain true about what happened at the time.
- **The note log's timestamp format**, introduced with `append_note_log`. Every
  new line moves from `[2:14 PM] [081826] [Jane Doe] text` to
  `08/19/26 02:30 PM Jane Doe text`. Existing lines are not rewritten, so the two
  shapes coexist (section 4).
- **That same design's non-goals, both of them.** It promised "no new status
  value" and "no schema or migration change." This design breaks both, on
  purpose: the status because the note-as-discriminator proved to be exactly the
  ambiguity worth removing, and the schema because start/stop timestamps do not
  exist anywhere and cannot be derived.
- **IMP-014, reopened once and now partly re-closed.** The 2026-08-18 design
  reopened labor *create* for a Technician recording their own hours. With
  tracked time authoritative, a Technician no longer keys hours by hand at all —
  their labor rows are produced by stopping a session. Supervisor+ keeps the
  manual create path as the correction route. Edit and delete stay Supervisor+,
  unchanged since IMP-014.
- **IMP-029** established `POST /work-orders/{id}/complete` as a narrow
  assigned-worker step. The endpoint survives again, with a new destination for
  a Technician. The two-person Review handoff it established is untouched.

## Non-goals

- **No change to the Admin Review queue.** `review` keeps its current meaning
  (`views/adminReview.js`, receipt output, Review → Closed) and its Admin floor.
  Ready to Complete is a *different, earlier* gate and does **not** feed that
  queue. See section 1.
- No change to the labor rate, the 30-minute rounding rule, or any billing
  total. Sessions feed the existing arithmetic more accurate raw minutes.
- No per-user notification preferences, no digesting, no new notification
  transport.
- No change to archiving, the `closed` (archived) concept, or the export
  contract beyond the automatic consequences of a new status value.
- No live/ticking timer display driven by a socket. The running state is
  rendered on card repaint like everything else.

---

## 1. The `ready_to_complete` status

### Vocabulary

`domain/work_orders.py:39-57` gains one constant and one tuple entry:

```python
STATUS_READY_TO_COMPLETE = "ready_to_complete"
```

placed between `STATUS_ON_HOLD` and `STATUS_COMPLETED` in `ALL_STATUSES`, which
is the lifecycle order and the order every dropdown and filter renders in.
`ACTIVE_STATUSES` remains an alias of `ALL_STATUSES` — Ready to Complete is a
live status, and `closed` is still `archived_at` rather than a status value.

`validate_status`'s message string is extended to list it. That string is
asserted in tests and shown to API callers, so it changes with the vocabulary.

### No migration for the status itself

`work_orders.status` is a plain `Text` column with **no CHECK constraint**
(`models.py:370`; migration `f4c6e8a0b2d3` only moved the server default).
Adding a status value is app-level only. The migration this design needs is for
sessions (section 2), and it does not touch `work_orders`.

### Why not reuse `review`

`review` is taken and means the Admin Review queue — a later, Admin-floored,
second-person handoff that produces the client receipt. Ready to Complete is the
*first* gate: one supervisor confirming the work happened. A row moves
`ready_to_complete → completed → review`, in that order. Nothing that reads
`review` is touched, and no query that builds the Admin Review queue learns
about the new value.

### Export

`validate_export_scope` accepts any member of `ALL_STATUSES`
(`domain/work_orders.py:384-445`), so `?scope=ready_to_complete` becomes a valid
export filter the moment the constant lands. `EXPORT_HEADERS` is unchanged — the
`STATUS` column simply carries a sixth possible value. No export code changes.

---

## 2. Labor sessions: the schema

### A new table, not new columns

`work_order_labor_sessions`:

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID pk | |
| `work_order_id` | UUID FK → `work_orders.id` `ON DELETE CASCADE` | matches `work_order_labor` |
| `technician_id` | UUID FK → `users.id`, not null | who was working, not who recorded it |
| `started_at` | timestamptz, not null | |
| `ended_at` | timestamptz, nullable | `NULL` means running |
| `labor_id` | UUID FK → `work_order_labor.id` `ON DELETE SET NULL`, nullable | the row this session produced on stop |
| `auto_closed_at` | timestamptz, nullable | set by the 12-hour cap (section 9) |
| `created_at` / `updated_at` | timestamptz | repo convention |

Indexes: `ix_work_order_labor_sessions_work_order_id`, and a **partial unique
index** on `(technician_id) WHERE ended_at IS NULL` — one running session per
person, enforced by the database rather than by a service check that races.

The alternative was nullable `started_at`/`ended_at` directly on
`work_order_labor`. It was rejected because a *running* session has no duration,
which would force `work_order_labor.minutes` to become nullable — and every
consumer of that column (`billed_labor_minutes`, the receipt, the CSV export,
`_detail`'s `labor_minutes` sum at `routers/work_orders.py:360-371`, the
front-end labor card) would have to learn to skip NULLs. A separate table keeps
`minutes NOT NULL` and leaves every one of those read paths untouched.

### Sessions produce labor rows; billing still reads labor rows

On **stop**, the service computes `minutes` from `ended_at - started_at`,
rounded to the nearest whole minute with a **floor of 1** (a 20-second session
records one minute rather than zero, which would trip
`validate_labor_minutes`'s positive-integer rule), creates a `WorkOrderLabor`
row, and links it back via `labor_id`.

An **open session contributes nothing to billing.** There is no labor row yet, so
`labor_minutes`, `billed_labor_minutes`, the receipt, and the export are all
exactly as correct as they are today for a job in progress. This is the property
that makes the whole change additive rather than a rewrite of the billing path.

`recorded_by_id` on the produced labor row is the actor who stopped the session,
which for a self-tracked session is the technician themselves.

---

## 3. Start Tracking and Stop

### Two new endpoints

| Route | Floor | Effect |
| --- | --- | --- |
| `POST /work-orders/{id}/tracking/start` | Technician (assigned) or Supervisor+ (any visible) | opens a session for the caller |
| `POST /work-orders/{id}/tracking/stop` | same | closes the caller's running session, writes the labor row |

Both follow the shape the existing walkthrough endpoints already established
(`routers/work_orders.py:690-806`): `_require_role` floor, `_get_locked` row
lock, archived/visibility check, then the action. Both are **idempotent** —
starting an already-running session returns it unchanged, stopping when nothing
is running returns unchanged. This is the same slow-double-tap protection
`start`/`complete`/`hold`/`resume` each carry, and it matters more here because
the button is the primary thing a technician taps in the field.

Both return `WorkOrderDetail`, like every other walkthrough endpoint, so the
front end refreshes the whole card from one response.

### Status side effects

Start Tracking advances the work order through the existing domain rule, not a
new one: `status_after_activity` already moves Created/Assigned → In-Progress
and deliberately leaves On-Hold stable (`domain/work_orders.py`). Starting a
timer is activity in exactly the sense that rule was written for.

This means **"Set In-Progress" disappears as a separate button** — its
transition is now a side effect of starting work, which is what the owner
actually wanted the button to mean. `POST /{id}/start` stays as an endpoint: it
is still called from the Scan / Stock confirmation flow, which is a different
surface with its own reasons.

**Start Tracking resumes an On-Hold row.** This is a consequence of the auto-hold
rule below, and it reverses an earlier draft of this section. Once "nobody is
tracking" *causes* On-Hold, the two conditions are the same fact, so the inverse
has to hold as well or a technician clocking back in after lunch needs two taps
(Resume, then Start Tracking) every single time. Start Tracking on an On-Hold row
moves it to In-Progress and opens the session in one action.

`status_after_activity` is **not** changed to do this. Its "On-Hold is
intentionally stable" rule governs *material and labor activity* — a supervisor
logging a part against a held job must not restart it — and that stays true. The
tracking service performs its own explicit On-Hold → In-Progress transition,
which is the same thing `/resume` already does and is subject to the same
`_record_transition` bookkeeping.

Start Tracking is therefore accepted on `created`, `assigned`, `on_hold`, and
`in_progress`, and rejected on `ready_to_complete` and `completed` — the same
narrow, status-checked shape `/hold` and `/resume` already have.

### Stop is automatic wherever work provably ended

| Action | Effect on the actor's running session | Effect on others' |
| --- | --- | --- |
| Stop Tracking | stops | none — but see the auto-hold rule below |
| Place On-Hold (`/hold`) | stops | **stops all** — the job is paused for everyone |
| Resume (`/resume`) | **no auto-start** | none |
| Notify Supervisor (`/complete`) | stops | **stops all** (section 6) |
| Archive | stops | stops all (section 9) |
| Supervisor PATCH into `on_hold` / `completed` / `ready_to_complete` | stops all | stops all |

Resume never auto-starts, and that is the asymmetry worth stating: stopping a
clock can only ever under-bill, while starting one bills somebody for time they
may not be working. A Supervisor resuming a row from the Edit-details dropdown
must not start a clock running against a technician who is not back on site.

### The last clock out puts the job On-Hold

When `/tracking/stop` closes the **last running session** on an **In-Progress**
work order, the work order moves to **On-Hold**. Nobody is working on it, and
that is precisely what On-Hold now means.

All four conditions are load-bearing:

- **Only from `/tracking/stop`.** Notify Supervisor also stops every session, but
  it has its own destination (`ready_to_complete`) and must not be intercepted.
  `/hold` is already On-Hold.
- **Only from In-Progress.** No other source status auto-transitions.
- **Only when no session remains open** on the work order — a co-worker still on
  the clock keeps it In-Progress.
- **Only on a real stop.** An idempotent repeat closes nothing, so the guard
  `previous is not None and previous != status` is false and neither the status
  nor the notification moves.

A short job therefore ends On-Hold: a technician who starts, works ten minutes,
and stops leaves a row that went Assigned → In-Progress → On-Hold. That is the
intended reading — the work is not finished and nobody is on it. Finishing is
Notify Supervisor, which is a different button.

This fires `work_order.held` to the routed supervisor like every other hold
(section 10). It is the design's largest source of new alert volume, and it is
named as a risk rather than smoothed over.

---

## 4. The note log

Sessions live in a table only supervisors think about. The **note log is the
public record** — every role that can open the card can read it — so the work
timeline is written there in plain language, and the same format covers
system-written and human-written entries alike.

### The format

`append_note_log` (`domain/work_orders.py:79`) is the single place any note line
is built, and the only place this changes. Its output shape becomes:

```
08/19/26 02:30 PM Jane Doe began work
```

`MM/DD/YY hh:MM AM/PM Author body` — zero-padded 12-hour clock, slashed date, no
brackets. The timezone is unchanged: `NOTE_TIMEZONE`, America/Chicago.

The current format is `[2:14 PM] [081826] [Jane Doe] text`. Three things change:
the date gains slashes and moves to the front, the hour is zero-padded, and the
bracket delimiters are dropped.

### Existing lines are not rewritten

Only new entries use the new shape. `work_orders.notes` is append-only free text
that also contains pre-log notes which were never formatted at all, so
retroactively normalizing it means regex-parsing stored prose across every work
order with no reliable verification and no undo. Mixed formats coexist and age
out. This is stated so the inconsistency reads as a decision rather than an
oversight.

### What gets written automatically

Three server-authored bodies, as domain constants beside `NOTE_TIMEZONE`:

```python
NOTE_BEGAN_WORK = "began work"
NOTE_STOPPED_WORK = "stopped work"
NOTE_READY_TO_COMPLETE = "marked work ready to complete"
```

| Moment | Line |
| --- | --- |
| `/tracking/start` | `08/19/26 02:30 PM Jane Doe began work` |
| `/tracking/stop` | `08/19/26 04:05 PM Jane Doe stopped work` |
| Notify Supervisor | `08/19/26 04:05 PM Jane Doe marked work ready to complete` |

Each is authored by the acting user and stamped at the moment of the action, so
the log carries the start/stop timeline in public even though the billable
arithmetic lives in `work_order_labor_sessions`.

`REVIEW_HOLD_NOTE` is **replaced** rather than simply retired (section 6):
`NOTE_READY_TO_COMPLETE` occupies the same call site with a body that describes
the person's action instead of the row's state.

**Nothing else writes a note.** In particular:

- The **auto-hold** transition writes none. The `stopped work` line immediately
  above it already states the cause, and a second line saying the same thing in
  status vocabulary would double every clock-out in the log.
- **Approve → Completed** writes none. `completed_at` records that moment, and
  the crew's `marked work ready to complete` line is the timestamp for when the
  work itself ended — which is the one people argue about.
- **Send Back** writes none.

A `stop` that closes nothing (idempotent repeat) writes no line, for the same
reason it fires no notification.

### Auto-closed sessions

A session closed by the 12-hour cap (section 9) writes its `stopped work` line at
the **capped** time, not at the moment the cap was noticed — the log must agree
with the labor row it produced. Because the cap is lazy, that line can appear in
the log later than lines above it. Entries are therefore appended in write order,
not sorted by timestamp, and this is the one case where the two differ. The
auto-closed marker on the labor entry (section 9) is what flags it for
correction.

### Human notes

A technician's or supervisor's typed note goes through the same function and
comes out the same way, which is what "normalized" means here:

```
08/19/26 04:30 PM Jane Doe Replaced the compressor, unit cooling normally.
```

No call site changes — `update_work_order` (`services/work_orders.py:1650`)
already routes typed notes through `append_note_log`. Reformatting is a one-place
change with a repo-wide effect, which is the argument for it.

---

## 5. Supervisors track without being assigned

A Supervisor who does the work should record it without adding themselves to the
crew list. Two rules relax, for Supervisor+ only:

1. **The tracking endpoints' assignment check.** `/tracking/start` and
   `/tracking/stop` require the caller to be an assigned worker *when the caller
   is a Technician*. Supervisor+ may track on any work order they can see. The
   existing `_visible` scope check still applies to everyone.
2. **`add_work_order_labor`'s assignment check.** Today a labor row's
   `technician_id` must be in `_assigned_technician_ids(work_order)`, or
   `InvalidAssigneeError` (`services/work_orders.py:1833-1870`). That check is
   narrowed to "assigned **or** Supervisor+ recording themselves." A supervisor's
   session-produced labor row therefore posts without them being listed as a
   technician on the card.

Everything else about `_require_labor_author` / `_require_labor_manager` stands.
A Technician still cannot record labor for anyone but themselves, and cannot
edit or delete any row.

This is a genuine permission widening and is named as such: a Supervisor can now
attach billable labor to a work order they are not assigned to. It is bounded by
visibility, it is attributed to them by name, and it is the point of the change.

### The tracked labor of an unassigned supervisor is still visible labor

The labor card lists every `work_order_labor` row on the work order regardless of
assignment (`views/workOrders.js:400-444` renders `detail.labor`), and labor
already "survives later technician unassignment as historical work"
(`models.py:475-497` docstring). So a supervisor's row displays with their name
alongside the crew's with no rendering change.

---

## 6. Notify Supervisor → Ready to Complete

### It reuses `POST /{id}/complete`

`completion_target_status(role)` (`domain/work_orders.py:291`) keeps its
signature, its docstring reasoning, and its role-not-assignment keying. One
return value changes:

| Role | Today | After |
| --- | --- | --- |
| Technician (or unrecognised role) | `on_hold` | **`ready_to_complete`** |
| Supervisor and above, and the `None` internal caller | `completed` | unchanged |

No new route. A technician running a stale cached SPA calls the same path and
gets the new behavior rather than a 403 — the same reasoning that kept
`/complete` in the 2026-08-18 design, and it applies more strongly now that the
button's label is changing too.

### Service behavior

`complete_work_order` (`services/work_orders.py:1390`) keeps its structure. The
`target == STATUS_COMPLETED` branch is unchanged. The other branch becomes:

| Target | Status written | `completed_at` | Note appended | Sessions |
| --- | --- | --- | --- | --- |
| `completed` | `completed` | `now()` | none | all stopped |
| `ready_to_complete` | `ready_to_complete` | `None` | `NOTE_READY_TO_COMPLETE` | all stopped |

`completed_at` stays `None` until a Supervisor approves. It remains the "when was
this accepted as billable" timestamp that the export's `COMPLETED AT` column and
the receipt already mean by it; a row that was never approved must not populate
it.

**The note stays, with a new body.** `REVIEW_HOLD_NOTE` described the row's state
("Placed On-Hold for Supervisor Review") because the status could not. The status
can now, so the line describes the person's action instead —
`marked work ready to complete` (section 4). The call site, the author, and the
`append_note_log` timestamp are unchanged.

The stop that this action performs on the actor's own session writes its own
`stopped work` line first, so a technician's finish produces two lines in order:
they stopped, then they marked it ready. Co-workers' sessions are stopped by the
same action and each writes its own `stopped work` line authored by **that
technician**, not by the actor — the log records who was working, and the person
whose clock it was is the subject of the sentence.

Idempotency still compares against the **target**, unchanged in principle: a
second tap on an already `ready_to_complete` row returns unchanged. Every other
source status is still rejected, with the error text naming the target the caller
would have reached.

### Multiple technicians

If tech A hits Notify Supervisor while tech B is still tracking, **the work order
moves and every running session on it stops.** The row has been declared
finished, so no clock survives it — B is not billed for time after the job was
handed to a supervisor. B's stopped session still produces its labor row, so B's
real time is recorded in full up to that moment.

B **cannot start a new session** on a `ready_to_complete` row: `/tracking/start`
rejects that status, the same way `/hold` and `/resume` reject a Completed row.
If the Supervisor rejects the work back to In-Progress, B can start again.

This is the point where a technician can stop a colleague's clock, which is worth
naming. It is bounded to co-assigned workers on one work order, and the
alternative — refusing the finish until everyone has stopped — blocks the crew's
last member on somebody else's forgotten timer.

---

## 7. Supervisor review: approve and reject

From a `ready_to_complete` row, Supervisor+ gets two buttons on the card:

| Button | Sends | Result |
| --- | --- | --- |
| **Approve — Mark Completed** | `PATCH {status: "completed"}` | `completed`, `completed_at` set, fires `work_order.completed` |
| **Send Back** | `PATCH {status: "in_progress"}` | `in_progress`, the crew is live again |

Both reuse the existing PATCH contract, its Supervisor+ permission, its
notification path, and its realtime emit. **No new endpoint.** This mirrors how
the 2026-08-18 design gave the On-Hold card a one-tap `complete-wo` button.

Send Back lands In-Progress rather than On-Hold: rejection means "go finish the
job," the crew is live, and it keeps On-Hold meaning purely "paused" — which is
the ambiguity this whole design exists to remove.

Send Back fires no new event. `in_progress` matches no arm of
`_notify_work_order_patch`'s chain, so the crew is not notified by this design.
That is a deliberate, stated gap: the technician learns their work came back when
they next open the app. If field use shows they need a push, it is a new arm and
a new event, following `docs/adding-a-notification-trigger.md` — not a change to
this design.

### The status dropdown

`editableStatusOptions` (`views/workOrders.js:704-737`) does **not** gain
`ready_to_complete` as a selectable option. Like `review`, it is a state reached
by an action rather than chosen from a menu — a supervisor moving a row *into*
"ready to complete" from a dropdown would be asserting on a technician's behalf
that the work is done.

A `ready_to_complete` row's dropdown offers the same choices an On-Hold row's
does (prework / `in_progress` / `on_hold` / `completed`), so a supervisor retains
the full rollback path. Unlike `review`, the status field is **not** disabled —
Ready to Complete is an ordinary supervisory decision point, not a locked
handoff.

---

## 8. Billing: tracked time is authoritative

- A Technician's hand-keyed hours input is **removed**. Their labor rows come
  from stopping a session.
- Supervisor+ keeps the manual add path (`POST …/labor`) unchanged. It is the
  correction route for a dead battery, a forgotten Start, or a paper sheet.
- Edit and delete stay Supervisor+ (IMP-014, unchanged).
- **Rounding is unchanged**: `billed_labor_minutes` sums every entry on the work
  order and rounds the total up once to the next 30 minutes
  (`domain/work_orders.py:207-233`). Not per session. A tracker makes short
  sessions easy — a 5-minute return trip rounded to half an hour, three times a
  day, would silently inflate every invoice.

The one number a customer is billed still comes from one place, and a supervisor
can still fix it.

---

## 9. Stale sessions: the 12-hour cap

A session left running overnight must not bill fourteen hours, and must not be
silently invented either.

`LABOR_SESSION_MAX_MINUTES = 720` (12 hours) in `domain/work_orders.py`, with a
pure helper:

```python
def capped_session_minutes(started_at, ended_at, *, now) -> tuple[int, bool]:
    """Billable minutes for a session and whether the cap truncated it."""
```

**The cap is applied lazily, not by a scheduler.** This app has no periodic task
runner — `services/netfacilities_jobs.py` is a one-shot job, and `lifespan.py`
is the only startup hook. A cron would be new infrastructure for one rule.
Instead, any running session older than the cap is closed at
`started_at + 12h` the next time the work order is read or written
(`get_work_order`, the tracking endpoints, `_detail`), with `auto_closed_at` set
to the moment it was noticed. This follows the same lazy-repair pattern
`_heal_orphan_lines` already uses on the detail path.

The produced labor row is flagged as auto-closed so the front end can mark it and
a Supervisor can correct it — an auto-closed session is a **prompt to review**,
never a billing fact accepted on its own.

**Archiving** a work order stops every running session on it immediately, at the
real clock time. Archive is an explicit action with an actor, so there is nothing
to guess.

A session whose work order was archived and later restored stays stopped. It is
not resumed.

---

## 10. Notifications

### One event, repointed

`work_order.held_for_review` is **repointed**, not replaced. Its only trigger
site today is `/complete` landing On-Hold (`routers/work_orders.py:690-806`) —
the exact path this design retargets — so repointing leaves no orphan and no dead
rule.

| | Today | After |
| --- | --- | --- |
| Fires when | `/complete` lands `on_hold` | `/complete` lands `ready_to_complete` |
| Title | "Work order ready for review" | unchanged |
| Body | `{number} is finished and waiting on your review.` | unchanged |
| Audience | routed supervisor, actor-suppressed, Admin fallback when unrouted | unchanged |

The wording was already written for this meaning. The constant name, the audience
selector `recipients_for_hold` (`domain/notifications.py:176`), and
`UNROUTED_HOLD_AUDIENCE_MIN_ROLE` are all unchanged.

The router's branch at `/complete` changes only its comparison — it already
chooses from the resulting status rather than the role, precisely so the
notification can never disagree with what was written:

```python
notify_work_order_held_for_review
    if work_order.status == wo.STATUS_READY_TO_COMPLETE
    else notify_work_order_completed
```

`work_order.held` is untouched and now means an unambiguous pause.

### PATCH branch order

`_notify_work_order_patch` (`routers/work_orders.py:109-200`) gains **no new
arm**. Ready to Complete is reachable by PATCH only in principle — the dropdown
does not offer it (section 7) — and a supervisor moving a row there by API is not
a technician declaring work finished.

The existing chain's behavior on the new transitions:

| Transition | Arm hit | Correct? |
| --- | --- | --- |
| `ready_to_complete → completed` (Approve) | `completed` | yes — the routed supervisor and Admins hear the job closed |
| `ready_to_complete → in_progress` (Send Back) | none | yes, per section 7 |
| `ready_to_complete → on_hold` | `held` | yes — the row was paused |
| `completed → ready_to_complete` | none | acceptable; API-only, no UI path |

The On-Hold-first ordering and its
`test_completed_to_on_hold_is_a_hold_not_a_reopen` guard stand unchanged.

### The tracking endpoints

`/tracking/start` fires **nothing**. Starting a timer is not news to a
supervisor, and its Assigned → In-Progress or On-Hold → In-Progress transition
matches no arm of any chain. Stated so it reads as a decision rather than an
omission.

`/tracking/stop` fires **`work_order.held`, but only when it auto-holds** — that
is, only when it closed the last running session on an In-Progress row (section
3). A stop that leaves a co-worker on the clock changes no status and notifies
nobody.

This is a **fourth trigger site** for `work_order.held`, alongside `/hold`, the
PATCH arm, and now this. It reuses `notify_work_order_held` unchanged: same
audience (routed supervisor, actor-suppressed, Admin fallback when unrouted),
same body, same `recipients_for_hold` selector. Adding a trigger site to an
existing rule still requires the process in
`docs/adding-a-notification-trigger.md`, including its **Currently wired** table.

The standard `previous is not None and previous != work_order.status` guard is
what makes this correct on the idempotent path: a repeat stop closes no session,
performs no transition, and therefore sends nothing.

Per `docs/adding-a-notification-trigger.md`, both the repointed
`held_for_review` and the new `held` trigger site get step 5's real-phone check
before merge.

---

## 11. Front end

### The technician's button ladder

`renderBody` (`views/workOrders.js:1323-1365`), handlers at `:1554-1620`:

| Row state (assigned worker, or Supervisor+ on a visible row) | Buttons |
| --- | --- |
| `created` / `assigned` | **Start Tracking** |
| `in_progress`, caller not tracking | **Start Tracking** · Place On-Hold |
| `in_progress`, caller tracking | **Stop Tracking** · **Notify Supervisor** · Place On-Hold |
| `on_hold` | **Start Tracking** (assigned) · Resume In-Progress (assigned) · Mark Completed (Supervisor+) |
| `ready_to_complete` (Supervisor+) | **Approve — Mark Completed** · **Send Back** |
| `ready_to_complete` (technician) | status hint only, no actions |
| `completed` / `review` | unchanged |

`start-wo` and `complete-assigned-wo` are replaced by `start-tracking-wo`,
`stop-tracking-wo`, and `notify-supervisor-wo`. `hold-assigned-wo`,
`resume-assigned-wo`, `complete-wo`, `review-wo`, `reopen-wo`, and `archive-wo`
keep their action names and behavior.

The card needs to know whether *the current user* is tracking. `WorkOrderDetail`
gains `active_labor_session` — the caller's own running session
(`started_at`, `id`) or `null` — and `tracking_technician_ids`, so a supervisor
can see that somebody is on the clock. The per-caller shaping happens in
`_detail` (`routers/work_orders.py:350-371`), which already varies its output by
caller through `include_price`.

On an On-Hold row, **Start Tracking** sits beside Resume: it does the same
transition and starts the clock, so it is the one a returning technician taps.
Resume stays for the case where work resumes without the tapper being the one
doing it.

The success message that told a technician "Sent to your supervisor for review."
is kept and retargeted to `status === "ready_to_complete"`. It is still chosen
from the returned row rather than from the role.

**Stop Tracking gets its own message** when the stop auto-held the work order —
*"Work stopped. Nobody is tracking, so this is now On-Hold."* Without it, a
technician taps Stop and watches the badge change to On-Hold on its own, which
reads as something going wrong. Chosen from the refreshed row's status, like the
message above, so the UI and the server cannot disagree.

### Note log

`notesLogContentsHtml` (`views/workOrders.js:342-346`) renders
`detail.notes` as escaped preformatted text and needs **no change** — the format
is produced server-side, and mixed old/new lines render the same way. The note
input, the `save-notes` handler (`:1626-1639`), and the PATCH it sends are all
unchanged; only the string that comes back is shaped differently.

This is worth stating explicitly because it is the reason the format change is
cheap: one server function, no client parsing anywhere.

### Labor card

`laborSectionHtml` / `laborTechnicianControl` (`views/workOrders.js:400-444`):

- The "Actual hours" input and **Add labor** button render for **Supervisor+
  only**. A technician's labor card becomes a read-only list of their tracked
  sessions.
- Each entry shows its session window when it has one (`2:10–3:25 PM`), and
  falls back to the duration alone for manually entered rows and for every row
  that predates this change. Existing labor rows have no session; they must
  render, not error.
- An auto-closed entry is marked — a short "auto-stopped" tag beside the
  duration — so a supervisor scanning the card can see which figures are
  estimates.
- Money stays redacted below TechFM OA. `detail.labor_rate` is already `None`
  for those roles; no new redaction.

### Status label, badge, and accent

`statusLabel` (`views/workOrders.js:446-459`) gains
`ready_to_complete: "Ready to Complete"`.

CSS needs a sixth pair, following the existing structure exactly
(`styles.css:2512-2530`, `2535-2603`, `2665-2670`). The established pattern is
badge = the -900 tone, card accent = -700, keycap "wall" shadow = -800:

| | Value |
| --- | --- |
| `.wo-status-ready_to_complete` background | `#4C1D95` |
| `.wo-card-status-ready_to_complete` accent / border / hover border | `#6D28D9` (`--card-accent-rgb: 109, 40, 217`) |
| keycap wall shadow | `#5B21B6` |

Violet is chosen because it is unmistakable against all five existing accents —
gray, dark red, amber, orange, blue, green — at a glance on a phone in daylight.
Per `docs/design-system.md`, status color stays **badge and card-accent only**;
TechFM red remains the primary action color, and no button in this design is
recolored.

### Filter

`backend/static/pages/work-orders.html:19-26` gains
`<option value="ready_to_complete">Ready to Complete</option>` between On-Hold
and Completed. This is the payoff for making it a real status: a supervisor can
filter to their review queue.

---

## Permission matrix after this change

| Action | Technician (assigned) | Technician (unassigned) | Supervisor+ |
| --- | --- | --- | --- |
| Start / Stop tracking | ✅ new | ❌ | ✅ new, **on any visible work order** |
| Add labor by hand | ❌ **removed** | ❌ | ✅ unchanged |
| Edit / remove labor | ❌ | ❌ | ✅ unchanged |
| Labor attributed to a non-assigned person | ❌ | ❌ | ✅ new, **self only** |
| Walkthrough finish → `ready_to_complete` | ✅ new | ❌ | — |
| Walkthrough finish → `completed` | ❌ | ❌ | ✅ unchanged |
| Approve / Send Back from Ready to Complete | ❌ | ❌ | ✅ new (existing PATCH) |
| Place On-Hold / Resume | ✅ unchanged | ❌ | ✅ |
| PATCH status directly | ❌ unchanged | ❌ | ✅ unchanged |
| Send to Review | ❌ | ❌ | Admin+ / unassigned routed Supervisor (unchanged) |

---

## Testing

| Layer | File | Pins |
| --- | --- | --- |
| Domain | `test_work_orders_domain.py` | `ready_to_complete` in `ALL_STATUSES` and `validate_status`; `completion_target_status` returns it for Technician and unrecognised roles, `completed` for Supervisor+ and `None`; `status_after_activity` unchanged (On-Hold stable); `capped_session_minutes` — under cap, at cap, over cap, sub-minute floors to 1; `billed_labor_minutes` unchanged; `validate_export_scope` accepts the new value; `append_note_log` emits `MM/DD/YY hh:MM AM/PM Author body` with a zero-padded hour, midnight and noon render as `12:00 AM` / `12:00 PM`, a naive `occurred_at` is still treated as UTC and converted to Central, prior free-form text is still preserved verbatim above the new entry, and an empty body still raises |
| Domain | `test_notifications_domain.py` | `held_for_review` body/title unchanged; `recipients_for_hold` unchanged; routed-but-suppressed still does not escalate to Admins |
| Service | `test_work_orders_service.py` | start opens one session and advances Assigned → In-Progress; start on an On-Hold row moves it to In-Progress and opens a session; start is idempotent; start rejected on `ready_to_complete` and `completed`; stop writes a labor row with floored-to-1 minutes and links `labor_id`; stop is idempotent; `/hold` stops **all** sessions; `/resume` starts none; **stopping the last running session on an In-Progress row moves it to On-Hold**; stopping while a co-worker is still tracking leaves it In-Progress; an idempotent repeat stop neither transitions nor writes a note; a stop on an already On-Hold row does not re-transition; technician finish lands `ready_to_complete` with `completed_at is None`, one `NOTE_READY_TO_COMPLETE` line appended, and every session stopped including a co-worker's — whose `stopped work` line is authored by **that** technician, not the actor; the finish does **not** auto-hold despite stopping every session; second tap changes nothing; supervisor finish still reaches `completed`; supervisor tracks on an unassigned work order and the labor row posts; technician tracking on an unassigned work order is refused; technician manual `POST …/labor` now refused; supervisor manual add unchanged; start and stop each append exactly one note line; archive stops running sessions; an over-cap session closes at `started_at + 12h`, writes its `stopped work` line at the **capped** time rather than the noticed time, and sets `auto_closed_at`; the partial unique index refuses a second concurrent session for one technician |
| Route | `test_work_orders_notifications.py` | `/complete` fires `held_for_review` for a technician (now on `ready_to_complete`) and `completed` for a supervisor; idempotent repeat fires nothing; `/tracking/start` fires **nothing**; `/tracking/stop` fires `held` **only** when it auto-holds, and nothing when a co-worker is still tracking or when the repeat is idempotent; the auto-hold `held` is actor-suppressed, so the technician who clocked out is not buzzed by their own stop; `ready_to_complete → completed` fires `completed`; `ready_to_complete → in_progress` fires nothing; `ready_to_complete → on_hold` fires `held`; `completed → on_hold` still fires `held` and not `reopened` |
| Gates | `test_route_role_gates.py` | both tracking routes sit at the Technician floor, not Admin |

Frontend changes are verified by `node --check` plus the focused source-contract
assertions this repo already uses — the action-name set in `renderBody`, the
`statusLabel` map, and the presence of the new CSS classes. Click-through QA is
**owner-performed**; the preview server on port 8124 is not auto-run.

Step 5 of `adding-a-notification-trigger.md` (real-phone check, event caused from
a different account, actor's own phone silent) applies to the repointed
`held_for_review` before merge.

## Docs to update

- `current-state.md` — the status vocabulary, the labor model and its new
  sessions table, the walkthrough contract, the labor permission floors, and the
  role matrix rows the 2026-08-18 design touched.
- `endpoint-map.md` — the two new tracking routes; `/complete`'s new technician
  destination; `POST …/labor` back to Supervisor+.
- `notification-events.md` — `held_for_review`'s trigger condition, and
  `held`'s new fourth trigger site.
- `adding-a-notification-trigger.md` — the **Currently wired** table.
- The **note log format** is written down in more places than any other detail
  in this design, and every one of them states the old shape:
  `current-state.md:1134` and `:2496`, `endpoint-map.md:475` and `:1380`,
  `project-summary.md:177`, the `models.py:368` column comment, and
  `append_note_log`'s own docstring. All seven change together — this is the
  single easiest thing in the change to leave half-updated.
- `open-work.md` — the backlog entry this closes, plus two new ones: the
  Send-Back notification gap (section 7) and the auto-hold alert volume named in
  Risks.

`docs/` is seven files. No new doc archives.

## Risks

- **A technician's muscle memory says "Mark Completed."** The button now says
  Notify Supervisor and there is a Start Tracking step in front of it. The
  retargeted success message is the mitigation; the label itself is the ask.
- **A forgotten Start Tracking means unbilled labor.** Removing the technician's
  manual hours input makes this unrecoverable by them — only a Supervisor can
  add the missing time. This is the direct cost of "tracked is authoritative"
  and is accepted. If it bites in the field, reopening self-add for a technician
  is a one-function change (`_require_labor_author` already exists).
- **The 12-hour cap invents a number.** An auto-closed session is flagged and
  reads as an estimate, but nothing forces a supervisor to look at it before the
  work order is billed. A blocking rule — "a work order with an auto-closed
  session cannot reach Completed" — was considered and deliberately not adopted:
  it would strand jobs on an audit that has no owner.
- **The lazy cap only fires when someone looks.** A running session on a work
  order nobody opens stays open past 12 hours until it is read. It is closed at
  the correct capped time whenever that happens, so the billed figure is right;
  only the flag is late. A scheduler would fix it and is not worth new
  infrastructure here.
- **Supervisors can now bill labor to work orders they are not assigned to.**
  Bounded by visibility and attributed by name, but it is a wider surface than
  before and is the change most worth watching in the first weeks.
- **Auto-hold is the design's biggest new alert source.** Every clock-out on
  every job — lunch, a parts run, the end of a shift — now moves the row to
  On-Hold and pushes `work_order.held` to the routed supervisor. That is the
  chosen behavior, and it is consistent with the 2026-08-18 rule that every
  entry into On-Hold notifies. But that rule was written when On-Hold happened
  only by deliberate tap, and this makes it happen several times a day per crew.
  If it proves noisy, the mitigation is narrow: suppress the notification on the
  auto-hold path only, leaving `/hold` and the PATCH arm untouched. One
  condition at one trigger site, no change to the audience or the rule.
- **The note log doubles in length.** A two-technician job that pauses twice now
  writes six or more automatic lines, and typed notes are interleaved among
  them. The log is the public record, which is the point, but it becomes
  something people scroll. No filtering or grouping is proposed here; if it is
  needed it is a front-end change to `notesLogContentsHtml` and nothing else.
- **A human note reads slightly run-on.** With brackets dropped, a typed note
  renders as `08/19/26 04:30 PM Jane Doe Replaced the compressor.` — the author
  and the body run together with no delimiter. It is unambiguous and it is the
  requested shape; if it reads badly in the field, inserting a separator is a
  one-line change to `append_note_log` that affects only lines written after it.
- **Auto-closed lines can appear out of chronological order.** The lazy cap
  writes a `stopped work` line stamped at the capped time, which may be earlier
  than lines already in the log. Entries are appended in write order and never
  sorted, so a reader can see a 6:00 PM line below an 8:00 AM one. Named because
  a timestamped log implies ordering it does not guarantee.
- **Stale cached clients.** `/complete` keeps its path and shape, so an old SPA
  gets the new destination rather than a 403 — the reason no `/submit-review`
  route exists. The *tracking* endpoints are genuinely new, so a stale client
  simply shows the old buttons and calls `/start`, which still works. It degrades
  to today's behavior rather than breaking — with one wrinkle worth stating: an
  old client never opens a session, so it never triggers the auto-hold either.
  Its work orders sit In-Progress until someone acts on them, which is exactly
  today's behavior.
