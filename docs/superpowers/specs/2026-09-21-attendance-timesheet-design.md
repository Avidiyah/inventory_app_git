# Attendance clock-in, the Home tab, and the Admin timesheet — design

Date: 2026-09-21
Status: draft, awaiting owner approval

## Problem

The app has a **work-order clock** and no **attendance clock**. Recorded time
exists only as `work_order_labor_sessions` rows, so the app can answer "how long
was this job" and cannot answer "was this person at work." Three consequences:

1. **No payroll record.** Billable hours round up to 30 minutes
   (`domain/work_orders.billed_labor_minutes`) — wrong to pay from, in both
   directions.
2. **Unbilled on-shift time is invisible.** Someone on site but not charging is
   indistinguishable from someone who went home.
3. **The clock widget is buried** — above the tabs for crew, at the page
   *bottom* for Admin+ (`userHub.js::placeClockMount`). The quick-start work
   order has no home of its own.

## Goal

- An **attendance punch** record, separate from billable labor, owned and
  editable by Admin+.
- A **Home** tab as the hub's first tab: punch in/out plus the relocated
  quick-start work order.
- The **Timesheets** tab becomes Admin+ and gains two sub-tabs: **Hours** (the
  weekly clocked-in record, with editing) and **Charged vs clocked** (the live
  comparison).
- The attendance week is the **work-order report's week**, by construction.

## Non-goals

- No change to billing, the labor rate, 30-minute rounding, or any receipt.
- No reason codes (Travel / Parts / Lunch). Deferred until red proves noisy;
  multiple punches per day already let a technician punch out for lunch.
- No scheduled/expected hours, no overtime rules, no payroll export format.
- No notification on a red row.

## Decisions

| # | Decision | Why |
|---|---|---|
| D1 | Attendance is the Admin+ payroll record; billable stays the customer record | The board's job is to explain the gap, never to close it |
| D2 | An Admin edits **punch times**, N punches per day, with `+ Add punch` | A day is a list, not an in/out pair; lunch is a punch-out |
| D3 | **One-way coupling**: starting a WO clock off-shift auto-punches in; punching out force-stops the running WO clock | A technician who ignores the punch button still produces a correct timesheet |
| D4 | **No auto-close.** An open punch blocks the next punch-in | Nothing estimated silently reaches a pay record |
| D5 | A technician meeting D4 **self-closes** the stale punch at a stated time, flagged `needs_review` | D3 + D4 together would otherwise block real work; a clerical error must not stop Wednesday's jobs |
| D6 | `GET /hub/timesheets` **retires**; Timesheets becomes Admin+ | The comparison sub-tab subsumes it. Accepted cost: Supervisors lose the tab |

## 1. Data

```
attendance_punches
  id            uuid pk
  user_id       uuid fk users
  started_at    timestamptz not null
  ended_at      timestamptz null        -- NULL = on shift
  start_source  text  manual | auto_work_order
  end_source    text  null | manual | auto_clock_out | self_reported | admin_edit
  needs_review  bool  default false
  created_at    timestamptz
  UNIQUE (user_id) WHERE ended_at IS NULL     -- partial index

attendance_punch_edits            -- append-only audit
  id, punch_id fk, edited_by_id fk users, edited_at,
  field, old_value, new_value, reason
```

The partial unique index is the mechanism `work_order_labor_sessions` already
uses for one running clock per person — in the database, not in a service check
that races. It guards **open** punches only; overlap between *closed* punches is
a domain check (§9), because D2 lets an Admin create them.

`needs_review` is set by D5 self-closes and drives the Hours grid's flag. No
auto-close column: per D4 a forgotten punch stays open until a human resolves it.

## 2. Domain — `domain/attendance.py`

Pure: no FastAPI, no SQLAlchemy, no DB. Owns:

- **The state machine.** `green` = punch open **and** a labor session open ·
  `yellow` = punch open, not charging, idle < 10 min · `red` = punch open, not
  charging, idle ≥ 10 min · `gray` = no open punch.
- **Idle.** `now − max(punch.started_at, last_labor_session.ended_at)`. The row
  prints `idle 12m`, so the color never needs explaining. Accepted consequence:
  a slow start after arrival shows red before the first job.
- **`IDLE_RED_MINUTES = 10`** — one constant, one home.
- **Validation** (§9), including punch overlap.

`labor_day.py` is reused **unchanged** for day bounds, `split_by_day`,
`overlap_minutes`, and `week_bounds_containing` — which is what makes the
attendance week *the same week* as `work_order_report.resolve_week` (Monday
00:00 Central through the next Monday 00:00) rather than a parallel definition
free to drift. DST is already correct there; the spring-forward week is genuinely
167 hours and the Hours grid's footer says so.

## 3. Services — `services/attendance.py`

| Call | Effect |
|---|---|
| `punch_in` | opens a punch; refuses when one is open, returning the stale punch so the UI can prompt (D4/D5) |
| `punch_out` | closes the punch **and** force-stops any running labor session (D3) |
| `ensure_punch_for_labor_start` | called before `work_orders.start_labor_session`: opens a punch with `start_source=auto_work_order`, or refuses with the stale punch (D3/D4) |
| `self_close` | closes the stale punch at the stated instant, `end_source=self_reported`, `needs_review=true` (D5) |
| `edit_punch` / `add_punch` / `delete_punch` | Admin+; validates, writes an `attendance_punch_edits` row |

The coupling lives **here**, in the caller of `start_labor_session`, not inside
the ~2,600-line `services/work_orders.py`. The dependency points one way:
attendance knows about labor, labor knows nothing about attendance.

## 4. Endpoints

| Route | Role | Notes |
|---|---|---|
| `POST /attendance/punch-in` · `punch-out` · `self-close` | self | |
| `GET /attendance/me` | self | Home tab state |
| `GET /hub/attendance/week?week=<Monday>` | **admin+** | one payload for both sub-tabs: clocked / tracked / billed + punch rows per user per day. 422 on a non-Monday, mirroring `resolve_week`. Hours renders the clocked column and the punches; Charged vs clocked renders all three columns |
| `GET /hub/attendance/live` | **admin+** | roster; read-only |
| `GET /hub/attendance/export?week=` | **admin+** | CSV: clocked / tracked / billed per user per day |
| `POST/PATCH/DELETE /hub/attendance/punches/{id}` | **admin+** | audited |

Every read is **side-effect-free** — no sweep, no row locks — unlike
`/hub/timesheets`, so the live sub-tab can poll safely.

`test_route_role_gates.py:505` asserts that exactly `{get_hub_report,
export_hub_report}` sit at the Admin floor. That expected set grows to include
these endpoints, edited deliberately with the reason recorded in the test — the
way that test is built to require.

## 5. Realtime

A new `attendance.changed` envelope, audience admin+, emitted on every punch
write. Mirrors `labor.session.changed` in shape and policy; no new transport.
Consumed by **Charged vs clocked** only.

## 6. Frontend

### Home (new first hub tab)

Punch-in hero, the quick-start work order button relocated out of `hubClock.js`'s
current perch, and today's own counts. `placeClockMount` already shows that
moving the widget's node preserves its state and event wiring, so this is a
mount-point change, not a rewrite.

### Timesheets (now admin+) — two sub-tabs

`initSubNav` from `views/subnav.js` hosts them. It reads `.sub-nav` and
`.feature-panel` from whatever element it is given, so the hub tabpanel works as
the host unchanged.

**Hours.** Monday-anchored weekly grid, per-user week tally, company total. A
cell click expands that day's punch rows with `[Edit]` per punch and
`[+ Add punch]` — the drill-down pattern `hubTimesheets.js` established (editing
arrives in P3). A `needs_review` punch renders flagged. Static: no subscription,
refetch after an edit, so an Admin correcting punches is not fighting a repaint.

**Charged vs clocked.** A live roster strip over a weekly comparison.

- Roster: one card per person, colored left rail (§2), sorted red → yellow →
  green, longest-idle first; header counts (`7 on shift · 5 charging · 2 idle`);
  absent people behind an expandable `N not clocked in` footer. Elapsed ticks
  client-side from `started_at` + server skew — the `hubClock.js` pattern.
- Comparison: per user per day, **clocked · tracked · delta**, with **billed** in
  a separately labelled column (§8). Export lives here.
- Owns the `attendance.changed` subscription and the hub's existing 60 s safety
  poll.
- The colored roster covers `WORK_ORDER_TECHNICIAN_ROLES` only. An Admin who
  punches in accrues hours in Hours but is not color-judged.

### `dom.js` gains `promptTime()`

Hour / minute / AM-PM `<select>`s plus a `−15 −5 +5 +15` nudge row; an analog
dial layered on top writing into the same state. Two callers — the Admin edit
popup and the technician's D5 self-close prompt — which earns it a place beside
`confirmDialog` and `promptUserRole` rather than inside a view.

Two constraints from this codebase:

- **CSP drops `style=`.** `main.py:143` is `default-src 'self'` with no
  `style-src`, so inline style attributes are silently discarded. The dial hand
  rotates via CSSOM (`el.style.transform` on a node the module owns), never a
  `style=` in a template literal.
- **No nested buttons.** A `<button>` inside a `<button>` is hoisted into a
  sibling, so the dial's number targets cannot be buttons inside a button.

The dropdowns are complete and keyboard-accessible alone, so if the dial is cut
editing still ships. The dial snaps to 5 minutes; the dropdown accepts any
minute.

## 7. Retiring `GET /hub/timesheets` (D6)

**Safe.** `sweep_stale_sessions` has four callers — `hub.py:247` (personal),
`:492` (crew), `:892` (admin), `:1287` (timesheets). Deleting the fourth leaves
three, so the 12-hour cap on forgotten *work-order* clocks still fires.

**`labor_summary.py` survives.** `crew_range_summaries` is exactly what the
comparison's charged column needs, as are `MAX_TIMESHEET_RANGE_DAYS = 92`,
`TimesheetRangeInvalidError`, and `TimesheetRangeTooLargeError`.

**Removed:** routes H3/H4, `services/hub.timesheets_hub` + `timesheet_csv`,
`views/hubTimesheets.js`, `apiGetHubTimesheets` / `apiExportHubTimesheets`, their
`userHub.js` wiring, `hubTimesheets.test.js`, the timesheet arms of
`test_hub_router.py` / `test_hub_service.py` / `api.endpoints.test.js` /
`api.shapes.test.js` / `helpers/hub.js` / `helpers/factories.js` /
`helpers/endpointTable.js`, and the endpoint-map H3/H4 + current-state rows.

**Accepted cost:** a Supervisor loses the Timesheets tab. The Dashboard crew
board still shows live crew status at their scope.

## 8. Time semantics — three numbers, never blurred

`domain/labor_day.py` already warns about this, and it is the likeliest way this
feature ships subtly wrong:

| Number | Source | Meaning |
|---|---|---|
| **Clocked** | `attendance_punches` | on shift — the pay number |
| **Tracked** | `labor_day.split_by_day` over labor sessions | real wall-clock on jobs |
| **Billed** | `billed_labor_minutes` | **rounded up to 30 min** — the customer number |

The comparison's delta is **clocked − tracked**, both real wall-clock, so it is
always ≥ 0 and always means "on shift, not on a job." Billed is shown in its own
labelled column and is never differenced against clocked: six short jobs would
show more billed than clocked, which is arithmetically right and reads as a bug.

## 9. Validation

| Condition | Result |
|---|---|
| `ended_at <= started_at` | 400 |
| `started_at` or `ended_at` in the future | 400 |
| overlaps another punch for the same user | 409, naming the conflicting punch |
| punch-in while one is open | 409, returning the stale punch (drives D5's prompt) |
| labor start while a stale punch is open | 409, same payload |
| edit / add / delete by below Admin | 403 |
| non-Monday `week` | 422, matching `resolve_week` |

**Charged time outside the shift is allowed and flagged, not refused.** An Admin
shortening a shift below the labor charged inside it produces `⚠ 2:00 charged
outside shift` in that day's drill-down. Refusing the edit is how people end up
editing Postgres by hand.

A cross-midnight punch is owned by the day it **started**; the following day's
cell shows the carried minutes and offers no edit button.

## 10. Testing

| File | Covers |
|---|---|
| `test_attendance_domain.py` | state machine, the 10-minute edge, overlap, DST weeks — no Postgres |
| `test_attendance_service.py` | coupling both directions, stale refusal, self-close, edit audit rows |
| `test_attendance_router.py` | the status codes in §9 |
| `test_route_role_gates.py` | the amended Admin-floor exemption |
| `tests/frontend/views/hubAttendance.test.js` | sub-nav, grid + drill, roster colors and sort, absent footer, live subscription |
| `tests/frontend/unit/dom.promptTime.test.js` | dropdowns, nudge row, dial↔dropdown binding, no `style=` emitted |

Plus the §7 retirement sweep.

## 11. Phasing

| P | Scope |
|---|---|
| P1 | table + migration, `domain/attendance.py`, `services/attendance.py`, punch in/out, D3 coupling, D4/D5, Home tab |
| P2 | Timesheets sub-nav + **Hours** grid, tally, drill-down (read-only) |
| P3 | `promptTime()` + edit / add / delete + audit |
| P4 | **Charged vs clocked** + live layer + export + §7 retirement |

P3 precedes P4 deliberately: editing is what makes the record trustworthy, and a
comparison built on uncorrected days is worse than none.
