# Attendance: midnight close and the lunch rule — design

Date: 2026-10-15
Status: approved 2026-10-15 (review fixes folded in)
Amends `2026-09-21-attendance-timesheet-design.md`: supersedes D4 (no
auto-close), D5 (self-close), and §9's cross-midnight ownership rule.

## Problem

Field users do not punch accurately, and the record is built as if they did.

- A forgotten punch-out never closes (D4). It counts up to "now" on every
  Central day it spans, reads red on the live roster indefinitely, and blocks
  the next punch-in and the next Begin Charging until the technician types a
  guessed time (D5) or an Admin edits it.
- Lunch exists only as a pair of punches. Forgotten, it is paid silently.
  Taken, it force-stops the work-order clock and parks the work order
  On-Hold.
- The work-order clock already caps at 12 hours, flags the session an
  estimate, and lets the week review accept it. The pay record refuses the
  same courtesy. That asymmetry is the whole mechanism behind multi-day
  shifts.

Owner inputs, 2026-10-15: lunch differs too much per person to model, so
assume a flat 30 minutes with no time-of-day logic and expect one punch pair
per day; an Admin must be able to remove a lunch in one tap; every user clocks
out at midnight no matter what; hours are mostly predictable with frequent
exceptions, so no schedule model.

## Goal

- No punch survives the Central midnight after its start. The close is
  stamped at midnight, flagged, and corrected in the existing review.
- A flat 30-minute lunch comes off any qualifying day, shown as its own
  number, removable per day by an Admin with an audit row.
- Everything "stale", including the technician's self-close, is deleted.

## Non-goals

- No schedule or expected-hours table (hours have frequent exceptions).
- No technician correction of an auto-closed punch. Reopen if Admins report
  they cannot learn the real time.
- No end-of-day push nudge; the app has no scheduler. Reopen if the review
  queue stays large after this ships.
- No change to the work-order clock, its 12-hour cap, billing, or 30-minute
  rounding.
- No lunch on the Home tab's `clocked_minutes_today`: the technician sees
  on-shift time; pay is the Admin's number. (It does take the midnight cap.)
- No night-shift handling. A clock still running at midnight keeps running
  with no punch; its after-midnight time reads "charged outside shift".
  Reopen when a crossing shift actually happens.

## Decisions

| # | Decision | Why |
|---|---|---|
| M1 | An open punch ends at the Central midnight after its start: `ended_at = midnight`, `end_source = auto_clock_out`, `needs_review = true`. **Midnight is the recorded time**, not an estimate from activity. | Owner rule. An obviously wrong time gets corrected; a plausible one taken from the last work-order stop would get bulk-accepted and systematically under-pay travel and cleanup. |
| M2 | Reads compute the midnight cap; a sweep writes it lazily from the same call sites as `sweep_stale_sessions`, plus before every punch-in and labor start. | The pattern `capped_session_end` already proves. No scheduler. |
| M3 | The midnight close does not touch the work-order clock. | It is a cap, not a punch-out; the 12-hour cap owns forgotten clocks. |
| M4 | No punch may cross Central midnight, Admin adds and edits included (400). A night shift is two punches. Checked only when a write sets or changes a time, so "Looks right" and the lunch toggle still work on legacy cross-midnight rows. | One rule for every writer; `carried` becomes legacy-only. |
| M5 | `is_stale`, self-close, and both stale prompts are deleted, not left dormant. | Unreachable once M1 holds, and the owner named user edits as the problem. |
| L1 | `LUNCH_MINUTES = 30` off any day whose gross clocked minutes reach `LUNCH_MIN_DAY_MINUTES` (360, owner 2026-10-15), unless waived. No time-of-day logic, no gap detection. | Owner rule: one punch pair per day. |
| L2 | The waiver is `attendance_punches.lunch_waived`, set through the existing PATCH with an audit row. A day is waived when any of its non-carried punches is; the UI toggles the day's earliest non-carried punch. | One column, no new table or route. Unambiguous under M4 and one-pair days. |
| L3 | Lunch is a fourth number. `clocked_minutes` stays gross; `paid_minutes = clocked − lunch`. Cells, totals, the profile, and the CSV print paid; the comparison delta keeps using gross. | `delta = clocked − tracked` must stay ≥ 0 when a job is charged through lunch. |
| L4 | Toggling the waiver never clears `needs_review`. | A different fact from the punch times; clearing would hide a midnight estimate. |

## 1. Rules — `domain/attendance.py`

- `midnight_after(started_at)`: `labor_day.day_bounds(central_date_of(started_at))[1]`.
- `effective_end(started_at, ended_at, *, now)`: `ended_at` if set, else
  `min(now, midnight_after(started_at))`. Sibling of `capped_session_end`.
- `punch_needs_review(...)`: the stored flag, or open and
  `now >= midnight_after`. Sibling of `session_needs_review`.
- `validate_punch_window` adds `ended_at <= midnight_after(started_at)`, else
  `PunchTimeInvalidError("A punch may not cross midnight.")`.
- `lunch_minutes(gross, *, waived)`: 30 when `gross >= LUNCH_MIN_DAY_MINUTES`
  and not waived, else 0.
- Deleted: `is_stale`. `END_SOURCE_SELF_REPORTED` stays declared for legacy
  rows; nothing writes it. `END_SOURCE_AUTO_CLOCK_OUT` gains its writer.

## 2. Data

One migration revising `a7c3e9f1b2d4`: `attendance_punches.lunch_waived
boolean not null default false`. No data migration: existing cross-midnight
rows render through the existing `carried` path, and the sweep closes any open
legacy punch at its own start day's midnight on the first hub load after
deploy. Editing a legacy cross-midnight row means bringing its end inside its
start day (M4); an Admin who needs both halves adds the second as a punch
starting at midnight.

The sweep writes no `attendance_punch_edits` row: `edited_by_id` is NOT NULL
and the sweep has no actor. `end_source = auto_clock_out` plus `needs_review`
is the record, exactly as `auto_closed_at` is for a session.

## 3. Services — `services/attendance.py`

- `sweep_open_punches(db, *, now, user_id=None) -> int`: every live open
  punch with `started_at < day_bounds(central_date_of(now))[0]` is closed per
  M1. Commits if it closed anything; idempotent; emits nothing, because every
  read already computes the cap.
- Call sites: beside the four `sweep_stale_sessions` calls (`hub.personal_hub`
  scoped, `hub.crew_hub` per member, `hub.admin_hub` global,
  `mark_week_reviewed` global), and first thing in `punch_in`,
  `ensure_punch_for_labor_start`, `punch_out`, and `admin_clock_out`, scoped
  to the person, so yesterday's punch never blocks today and no punch-out
  writes an end past midnight. A 12:30 AM punch-out therefore answers "You
  are not punched in." (night shifts are a non-goal).
- `punch_in`'s refusal is only "You are already punched in since 7:02 AM.";
  the stale branch and `PunchAlreadyOpenError.stale` go.
- `me_payload`, `attendance_week`, `attendance_live.roster`, and
  `attendance_compare` use `effective_end` and `punch_needs_review`, so a
  punch past midnight reads closed and flagged before any sweep. `me_payload`
  reports `open_punch` only while `effective_end > now` and counts
  `clocked_minutes_today` to `effective_end`; the roster lists that person
  under `absent`. `person_week` inherits all of it, lunch and paid included,
  through `attendance_week`.
- `attendance_week` adds `lunch_minutes`, `lunch_waived`, `paid_minutes` per
  day, `paid_minutes` per row and week, and `paid_minutes` on each
  `totals_by_day` entry.
- `admin_edit_punch` accepts `lunch_waived`: audit field `lunch_waived`,
  values `"false"`/`"true"`, excluded from the `clearing` rule (L4).
  `admin_add_punch` and `admin_edit_punch` inherit M4 from
  `validate_punch_window`.
- Deleted: `self_close`.

## 4. Endpoints and schemas

| Route | Change |
|---|---|
| `POST /attendance/self-close` | removed, with `SelfCloseRequest` and `apiSelfClosePunch` |
| `GET /attendance/me` | `open_punch.stale` removed |
| `PATCH /hub/attendance/punches/{id}` | `PunchEditRequest.lunch_waived: Optional[bool]`; 400 on a cross-midnight window |
| `POST /hub/attendance/punches` | 400 on a cross-midnight window |
| `GET /hub/attendance/week`, `GET /hub/people/{id}/week` | day gains `lunch_minutes`, `lunch_waived`, `paid_minutes`; row and week gain `paid_minutes`; `totals_by_day[]` gains `paid_minutes` |
| `GET /hub/attendance/export` | two metric rows per block, `Lunch` and `Paid`, after `Clocked` |

No new route, so `test_route_role_gates.py`'s Admin-floor set is unchanged.

## 5. Frontend

- **Home tab** (`hubHome.js`): `stalePunchHtml`, `handleSelfClose`, and the
  `promptTime` import go; nothing is added. A technician whose yesterday was
  auto-closed sees "Not punched in". The flag is the Admin's.
- **Work-order card** (`workOrderActions.js`): `resolveStalePunch` goes. A
  punch can no longer refuse Begin Charging, so any remaining 409 is the
  inline message it already is.
- **Hours drill-down** (`hubAttendanceHours.js`): heading prints
  `7:12 paid`. Under the punch rows, one line: `Lunch −0:30 [Remove lunch]`
  when deducted, `No lunch deducted [Restore lunch]` when waived on a
  qualifying day, nothing under the threshold. Both buttons go through
  `hubTimesheetsTab.write` like "Looks right", PATCHing the day's earliest
  punch with `lunch_waived` and the reason "Lunch removed by an Admin" or
  "Lunch restored by an Admin". A midnight-closed row reads
  `7:02 AM – 12:00 AM · auto-closed at midnight · needs review`, with Edit
  and Looks right as today.
- **Grid cells, day page, profile, leaderboard**: every printed day or week
  total is `paid_minutes`. The profile's expanded day adds a `lunch −0:30`
  note. The leaderboard's uncharged figure stays gross-based (L3).
- Unchanged: `clockInPrompt.js`, `hubAttendanceRoster.js` and its Clock out
  button, `hubClock.js`.

## 6. Diff — current behavior → new behavior

| Area | Today | After |
|---|---|---|
| Forgotten punch-out | Open indefinitely; counts to now on every day it spans; roster red until a human acts | Ends at midnight (recorded), `auto_clock_out`, `needs_review`; roster shows absent; week review accepts or an Admin edits |
| Next-day punch-in / Begin Charging | 409 until the technician self-closes with a typed time | Caller's own sweep runs first; never blocked by yesterday |
| `domain.attendance.is_stale` | Defines "stale" | Deleted |
| `services.attendance.self_close`, `POST /attendance/self-close`, `SelfCloseRequest`, `apiSelfClosePunch` | The D5 flow | Deleted |
| `AttendanceOpenPunch.stale`, `PunchAlreadyOpenError.stale` | Drive both prompts | Deleted |
| `hubHome.js` stale section; `workOrderActions.resolveStalePunch` | Two self-close prompts | Deleted; `promptTime` keeps one caller, the punch editor |
| `validate_punch_window` | Order and future checks | + no cross-midnight (M4) |
| `attendance_punches` | 9 columns | + `lunch_waived` |
| `attendance_week` day | `clocked_minutes`, `needs_review`, `has_open`, punches | + `lunch_minutes`, `lunch_waived`, `paid_minutes`; `open` and `needs_review` via `effective_end` / `punch_needs_review` |
| `attendance_compare.pending_review` | flagged punch, **or an open punch from an earlier day**, or an unaccepted session | flagged punch or unaccepted session; the earlier-day case cannot exist |
| `mark_week_reviewed` | leaves an open punch alone | sweeps punches first, so a midnight close is accepted with the rest |
| `PunchEditRequest` | `started_at`, `ended_at`, `needs_review`, `reason` | + `lunch_waived`, which never clears `needs_review` |
| Hours drill-down | heading `7:42 clocked`; rows; `+ Add punch` | heading `7:12 paid`; rows; **lunch line with its button**; `+ Add punch` |
| Grid cells, totals, day page, profile | gross clocked | paid |
| CSV | Clocked, Charged, Off job, Charged outside shift, Adjustments | Clocked, **Lunch, Paid**, Charged, Off job, Charged outside shift, Adjustments |
| `carried` | cross-midnight punch on each day, editable on its start day | legacy rows only; no new row can need it |
| Tests to delete or rewrite | `test_attendance_domain` staleness ×3; `test_attendance_service` stale-blocks-start and `self_close` ×3; `test_attendance_router` self-close ×2 and the stale 409; `test_attendance_compare_service` earlier-day pending and review-leaves-open-punch; `test_attendance_week_service` open-counts-to-now and cross-midnight-carries; `hubHome.test.js` "Close it"; `workOrderStartPunch.test.js` ×4; `endpointTable.js` and `helpers/hub.js` self-close rows | replaced per §7 |
| Docs | `current-state.md` Hard Invariants (lines 442–445, 457–460) and `attendance_punches` rules (1408–1409); `endpoint-map.md` A4 row, H9/H10 notes, `attendance.changed` row, `AttendanceWeekDay` shape; `notification-events.md` `attendance.changed` trigger list; `open-work.md` IMP-041 | updated in the shipping commits |

## 7. Testing

| File | Covers |
|---|---|
| `test_attendance_domain.py` | `midnight_after` across DST and the UTC boundary; `effective_end`; `punch_needs_review`; cross-midnight 400; `lunch_minutes` at the threshold and when waived |
| `test_attendance_service.py` | sweep closes at midnight with source and flag, leaves today's punch, is idempotent, leaves the work-order clock alone; punch-in and labor start after a forgotten day succeed; `lunch_waived` audit row; the waiver does not clear `needs_review` |
| `test_attendance_week_service.py`, `test_person_week_service.py` | a punch past midnight reads closed and flagged before any sweep; paid, lunch, waived per day and totals |
| `test_attendance_compare_service.py`, `test_attendance_export_router.py` | delta uses gross; `mark_week_reviewed` accepts a midnight close; CSV rows |
| `test_attendance_live_service.py` | a punch past midnight is absent, not red |
| `test_attendance_router.py`, `test_attendance_admin_router.py` | self-close route gone (404); PATCH `lunch_waived`; cross-midnight 400 |
| frontend | `hubHome.test.js` no stale branch; `hubAttendanceHours.test.js` paid heading, lunch line, both buttons; `workOrderActions` 409 stays inline; `userProfile.test.js` lunch note; `api.shapes` and `endpointTable` rows |

## 8. Phasing

| P | Scope |
|---|---|
| P1 | M1–M5: domain rules, sweep and call sites, read-side cap, deletions, tests, docs |
| P2 | L1–L4: migration, lunch maths, PATCH field, drill-down control, paid everywhere, CSV rows |

P1 first because it deletes before P2 adds, and because the midnight
invariant is what makes "a day's punches" unambiguous for the lunch rule.
