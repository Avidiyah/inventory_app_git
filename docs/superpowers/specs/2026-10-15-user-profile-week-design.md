# User profile — per-person weekly history — design

Date: 2026-10-15
Status: draft, awaiting owner approval
Budget: ≤ 1,800 words

## Problem

An Admin can see the whole crew's week on the Timesheets tab and the whole
company's closed work orders on the Report tab, but cannot look at **one
person** and read their history by date. "What did this technician do last
Tuesday" takes three tabs and a mental join.

## Goal

An Admin or Owner clicks a name on the Users page and gets that person's
history, one week at a time, one row per day: **work orders completed**,
**labor charged**, **time clocked in**. Read-only.

## Decisions (locked 2026-10-15)

| # | Decision | One-line rationale |
|---|---|---|
| D1 | Viewer gate: **Admin and Owner** (`require_min_role(ROLE_ADMIN)`) | Same gate as every `/hub/attendance/*` read |
| D2 | Target roles: **Technician, Team Lead (`supervisor`), TechFM OA** only; Admin/Owner target → 403 | The owner's stated scope; `WORK_ORDER_TECHNICIAN_ROLES` + `ROLE_TECHFM_OA` |
| D3 | Archived targets are allowed | History outlives the account |
| D4 | "Completed" = work order whose crew (`work_order_technicians`) includes the person and whose `completed_at` falls on that Central day | No `completed_by` column, no status-event table; a 3-person job credits all 3 |
| D5 | Layout: Monday–Sunday **week picker**, same resolver as Timesheets (`work_order_report.resolve_week`) | One week model across every Admin surface |
| D6 | Placement: a **panel on the Users page** that replaces the table, with a Back link | No new route, no new nav item |
| D7 | Day rows show totals; a native `<details>` expand lists the detail | Totals first, detail on demand, no JS toggle state |
| D8 | The read is **side-effect-free**: no sweep, no row locks, no commit; an open labor session is clipped at the 12-hour cap on read (`cap_running=True`) | Matches `/hub/attendance/week` |
| D9 | Minutes are **wall-clock**, never `billed_labor_minutes`; no dollar figure | No honest per-person billed number exists (see `open-work.md`) |
| D10 | Out of scope: CSV export, editing punches or labor from the profile, a per-person billing figure | YAGNI; Timesheets already edits punches |

## Known consequence of D4

A work order that is reopened, put On Hold, or dropped back from Ready to
Complete loses `completed_at` (`services/work_orders.py` clears it on every
such transition), so it leaves the profile until it is completed again. The
receipt and the CSV export already behave this way. A work order completed
with **no crew** appears on nobody's profile.

## Endpoint

`GET /hub/people/{user_id}/week?week=YYYY-MM-DD` — `routers/hub.py`.

| Case | Response |
|---|---|
| `week` omitted | current week, via `resolve_week` |
| `week` not a Monday | 422 (existing resolver behaviour) |
| unknown `user_id` | 404 |
| target role Admin or Owner | 403 |
| viewer below Admin | 403 (route gate) |

Response model `PersonWeekResponse` in `schemas/hub.py`, all `from_attributes`:

```
PersonWeekResponse
  user: HubUser                 # id, first_name, last_name, role
  archived: bool
  week_start, week_end: date
  server_now: datetime
  days: list[PersonWeekDay]     # always 7, zero-valued days present
  total_clocked_minutes: int
  total_charged_minutes: int
  total_adjustment_minutes: int
  total_completed: int
  reviewable: bool              # any day needs_review

PersonWeekDay
  date: date
  clocked_minutes: int
  charged_minutes: int          # closed + running (capped) session minutes
  adjustment_minutes: int       # hand-entered labor, shown, never summed into charged
  completed_count: int
  needs_review: bool            # a punch or auto-closed session awaits review
  has_open: bool                # an open punch; clocked climbs to server_now
  completed: list[PersonWeekCompleted]
  charged: list[PersonWeekCharged]
  adjustments: list[HubAdjustment]           # existing schema
  punches: list[AttendanceWeekPunch]         # existing schema

PersonWeekCompleted
  work_order_id: uuid, number: str, location: str | None, completed_at: datetime

PersonWeekCharged
  work_order_id: uuid, number: str, minutes: int, auto_closed: bool, running: bool
```

`charged` is one entry per **work order per day**, summed from that day's
timeline sessions (a work order clocked twice in a day is one line).

## Service

New `services/person_week.py`, one public function:

```
week_payload(db, *, user_id, week_start, now) -> PersonWeek
```

Composition, three reads, no new maths:

| Column | Source | New code |
|---|---|---|
| Clocked, punches, `needs_review`, `has_open` | `attendance_week.week_payload(db, week_start=…, now=…)`, pick the target's `WeekRow`; absent row → seven zero days | pick-a-row |
| Charged, adjustments | `labor_summary.crew_range_summaries(db, [user_id], week_start, week_end, now=now, cap_running=True)` → `DaySummary` per day; collapse `timeline` by `work_order_id` | collapse |
| Completed | `WorkOrder` joined `WorkOrderTechnician` on `technician_id == user_id`, `completed_at` in `[week_window)`; bucket with `labor_day.central_date_of` | one query |

The role check (D2) and 404 live in the service (`PersonNotProfilable`, mapped
to 403 at the route), so a future caller cannot skip it.

`attendance_week.week_payload` computes the whole population; for this crew
size that is cheap and reuses every clipping and `carried` rule unchanged.

> ponytail: whole-population attendance read; add a `user_ids` filter to
> `attendance_week._population` if the roster grows past ~100.

## Screen

**Users page** (`static/views/users.js`, `static/pages/saved-users.html`):

- For an Admin/Owner viewer, the name cell of a Technician, Team Lead, or
  TechFM OA row renders as `<button class="link-btn user-profile-btn"
  data-id>`. Other rows and other viewers keep plain text.
- Clicking hides the users table, shows a `#user-profile` container, and
  calls `mountUserProfile(container, user)` from a new
  `static/views/userProfile.js`. Back restores the table without refetching.
  (The create form is its own page, `create-user.html`, and is untouched.)

**Profile panel** (`userProfile.js`, ≤ 500 lines):

- Header: name, role label, `(archived)` tag when archived, Back link.
- Week picker: `‹ week › ` + "Mon D – Sun D" label; reuses
  `shiftMonday` / `weekLabel` / `formatHm`, which move from
  `hubAttendanceHours.js` into a small shared `static/views/hubWeek.js`
  (pure functions, re-imported by the Hours grid; no behaviour change).
- Table, seven rows: Day · Clocked · Charged · Completed. Footer: week totals.
  A review flag glyph on a day that `needs_review`, same class as the Hours
  grid. A day with `has_open` shows the server's clocked value as fetched plus
  an "(on shift)" note; no client-side ticking.
- Each row is a `<details>`: the summary is the totals row; the body lists
  Completed (number · location), Charged (number · h:mm · "auto-stopped" /
  "running" markers), Adjustments (h:mm · recorded by · number), Punches
  (in – out · source · flag). Work order numbers hand off to the Work Orders
  page via the existing `openWorkOrdersByNumberSearch`.
- Fetch via new `apiGetPersonWeek(userId, { week })` in `api.js`. Loading
  uses `skeletonTableRows`; failure shows `friendlyError` with a Retry.
- Styling via existing table/panel classes plus a handful of new rules in
  `styles.css`; no inline `style=` (CSP drops them).

## Tests

| Layer | File | Pins |
|---|---|---|
| service | `tests/test_person_week_service.py` | 7 days always present; completed bucketed by Central day across midnight; crew attribution (3 crew → 3 profiles, no crew → none); reopened WO drops off; charged collapses two sessions on one WO; adjustments never summed into charged; archived target allowed; Admin/Owner target raises |
| router | `tests/test_person_week_router.py` | Admin 200, TechFM OA 403, unknown user 404, Owner target 403, non-Monday 422, no commit/sweep (open session still open after read) |
| gates | `tests/test_route_role_gates.py` | new route registered at Admin |
| frontend | `tests/frontend/views/userProfile.test.js` | mount renders 7 rows + totals; week step refetches with the shifted Monday; expand shows WO numbers and punches; Back restores table; error → Retry |
| frontend | `tests/frontend/views/users.test.js` (new; none exists today) | name is a button only for Admin+ viewer on the three roles; click swaps table for profile, Back restores |

## Docs

One row in `endpoint-map.md` (H16) and one feature row in
`current-state.md` under User Hub. No new doc.

## Files

| Area | Files |
|---|---|
| backend | `services/person_week.py` (new), `schemas/hub.py`, `routers/hub.py` |
| frontend | `static/views/userProfile.js` (new), `static/views/hubWeek.js` (new, extracted), `static/views/hubAttendanceHours.js` (import swap), `static/views/users.js`, `static/pages/saved-users.html`, `static/api.js`, `static/styles.css` |
| tests | as above |
