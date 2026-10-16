# Edited Time, Profile Day Timeline, and Leaderboards — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Workers can edit their own punches (Home tab) and their own hand-entered labor (WO Labor card) while the week is open. Every edit is marked Self or Admin on a colour-coded profile day timeline. Needs-review days are left out of every hours total. Admins get a Leaderboards tab with an Accuracy board and an Efficiency board.

**Architecture:**
- **Permissions** are row-level guards in the existing services: the attendance punch writes and `_require_labor_editor`. The punch routes drop their Admin floor and the service decides instead.
- **Edit marks** are derived from `attendance_punch_edits` and `WorkOrderLabor.recorded_by_id`. No migration.
- **The flagged-day rule** is one domain predicate. `attendance_compare` (Hours, CSV, boards) and `person_week` (profile) both read it.
- **The timeline** is a new pure view module that `userProfile.js` renders into each opened day.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic (`from_attributes`), vanilla ES modules, pytest, vitest + jsdom + MSW.

**Spec:** `docs/superpowers/specs/2026-10-16-edited-time-timeline-and-leaderboards-design.md` (read it first; U1–U11 and B1–B6 are not restated).

## Global Constraints

- **Paths** are relative to `backend/` unless they start with `tests/frontend` or `docs/`.
- **Commands:** run pytest from `backend/` as `venv/Scripts/python -m pytest <file> -q`, and vitest from the repo root as `npx vitest run <file>`.
- **Targeted tests only.** Commit after each task, staging explicit paths and never `git add -A` (peer sessions share this checkout). Never push: pushing main deploys.
- **No `style=` attributes** (CSP drops them). Set positions through CSSOM from `data-left` and `data-width`, as `hubTechnician.js` does. No nested `<button>`.
- **Line caps:** keep files under 500 lines. `userHub.js` is already 575, so add 15 lines at most there and do no refactor.
- **"Week open"** means `week_bounds_containing(central_date_of(instant))[0] == week_bounds_containing(central_date_of(now))[0]` (B1).
- **Workers never** clear `needs_review` on its own, never waive lunch, and never touch session-produced labor rows. Those stay Admin-only.
- **Refusal copy, verbatim:** `"You can only change your own time in the current week."`
- **Deviations from the spec:**
  - **B4:** an Admin's delete reason is *optional* today, so a self-delete reason is optional too ("same as Admin").
  - **Export CSV and Mark all reviewed** are payroll and review actions, so they stay on the Timesheets tab. Only the board moves, and the CSV gets no per-board sections.

## Review Focus

1. A worker edits their own open-week punch so its new start lands in a closed week. Expect 403: check the new start as well as the old one. Pinned in Task 2 (`test_self_edit_cannot_move_a_punch_into_a_closed_week`).
2. A worker sends `needs_review=False` alone, or `lunch_waived`, on their own punch. Expect 403 and nothing changed. Pinned in Task 2 (`test_self_edit_cannot_look_right_or_waive_lunch`).
3. A worker keys labor for themselves on a work order whose crew they are not on. Expect a refusal; today's `technician_id == user.id` escape exists only for Admin/Owner. Pinned in Task 4 (`test_worker_off_the_crew_cannot_key_own_labor`).
4. A worker edits the labor row their own Stop Charging produced. Expect a refusal (session-backed). Pinned in Task 4 (`test_worker_cannot_edit_a_session_labor_row`).
5. Once the server excludes pending days, the board must not subtract them a second time. Pinned in Task 9 (`computeLeaderboard uses server row totals as-is`).

---

### Task 1: Domain helpers and the 403 error

**Goal:** Add the shared predicates and the refusal error that every later task uses.

**Files:**
- Modify: `app/domain/labor_day.py`, `app/domain/attendance.py`, `app/domain/errors.py`, `app/routers/_errors.py`
- Test: `tests/test_labor_day.py`, `tests/test_attendance_domain.py`

**Interfaces (produces):**
- `labor_day.week_is_open(instant: datetime, now: datetime) -> bool`
- `attendance.END_SOURCE_SELF_EDIT = "self_edit"`
- `attendance.day_pending_review(punches, timeline) -> bool`. This is `any(p.needs_review or getattr(p, "crosses_midnight", False) for p in punches) or any(e.needs_review for e in timeline)`. It is duck-typed over `WeekPunch` and `TimelineEntry`.
- `errors.TimeEditForbiddenError(DomainError)`, mapped to 403 in `_STATUS_MAP`.

- [ ] **Step 1: Write the failing tests.**
  - `test_week_is_open_same_central_week`: Mon 00:30 Central and Sun 23:00 Central of the same week → True.
  - `test_week_is_open_previous_week_is_closed`: Sun 23:59 Central of the previous week → False.
  - `test_day_pending_review_flags`: three cases. A punch with `needs_review=True` → True. `crosses_midnight=True` alone → True. A timeline entry with `needs_review=True` → True. All clean → False.
  - `test_time_edit_forbidden_maps_to_403`: `to_http(TimeEditForbiddenError("x")).status_code == 403`.
- [ ] **Step 2: Run** `venv/Scripts/python -m pytest tests/test_labor_day.py tests/test_attendance_domain.py -q`. Expect FAIL (import errors).
- [ ] **Step 3: Implement the four items above.**
- [ ] **Step 4: Rerun.** Expect PASS.
- [ ] **Step 5: Commit** `feat(attendance): week_is_open, day_pending_review, TimeEditForbiddenError`.

### Task 2: Workers edit their own punches (service + routes)

**Goal:** Let workers add, edit and delete their own punches in the open week. The Admin path stays as it is.

**Files:**
- Modify: `app/services/attendance.py` (`admin_add_punch`, `admin_edit_punch`, `admin_delete_punch`; the names stay, and each docstring gains one line saying a worker may act on their own open-week time), `app/routers/hub.py:246-318` (three routes)
- Test: `tests/test_attendance_admin_service.py`, `tests/test_attendance_admin_router.py`

**Interfaces:**
- Consumes: Task 1.
- Produces: `attendance._require_punch_editor(actor: User, *, owner_id: uuid.UUID, starts: Iterable[datetime], now: datetime) -> bool`, which returns `is_self`.
  - Admin+ returns `actor.id == owner_id` and never raises.
  - Anyone else passes only when `actor.id == owner_id` and every instant in `starts` is `week_is_open`. Otherwise it raises `TimeEditForbiddenError` with the refusal copy.
- Behaviour for a self actor (non-Admin):
  - **add:** `end_source=END_SOURCE_SELF_EDIT`.
  - **edit:** refused when `lunch_waived is not None`, or when `needs_review is False` and no time changed. A time change still clears `needs_review` (U11, existing code). `end_source=END_SOURCE_SELF_EDIT` when the end changes.
  - **delete:** guarded on the punch's `started_at`.
- Routes: `require_min_role(roles.ROLE_ADMIN)` becomes `get_current_user` on POST, PATCH and DELETE `/hub/attendance/punches`. Clock-out and week/review stay Admin.

- [ ] **Step 1: Write the failing service tests.**
  - `test_worker_adds_edits_deletes_own_open_week_punch`:
    - Each call succeeds.
    - Each writes an `AttendancePunchEdit` row whose `edited_by_id` is the worker.
    - The added punch has `end_source == "self_edit"`.
  - `test_worker_cannot_touch_another_persons_punch`: edit and delete on a peer's punch, and add with `user_id=peer.id`, each raise `TimeEditForbiddenError`.
  - `test_self_edit_cannot_touch_a_closed_week`: a punch started last week raises on edit and on delete.
  - `test_self_edit_cannot_move_a_punch_into_a_closed_week`: an open-week punch edited with `started_at` set to last Sunday raises, and the punch is unchanged.
  - `test_self_edit_cannot_look_right_or_waive_lunch`: `needs_review=False` alone raises, and `lunch_waived=True` raises.
  - `test_self_fix_clears_needs_review`: a flagged own punch edited with a new `ended_at` ends with `needs_review is False` and an audit row `field == "needs_review"`.
- [ ] **Step 2: Add the router test** `test_technician_patches_own_punch_200`. Keep `test_techfm_oa_is_refused` unchanged: it edits someone else's punch, so it is still 403.
- [ ] **Step 3: Run both files.** Expect FAIL.
- [ ] **Step 4: Implement the guard and wire it in.** In `admin_edit_punch` the starts are `(punch.started_at, new_start)`. In `admin_add_punch` they are `(started_at,)` and the owner is `user_id`.
- [ ] **Step 5: Rerun.** Expect PASS. Then run `tests/test_attendance_service.py` to catch regressions.
- [ ] **Step 6: Commit** `feat(attendance): workers edit their own punches in the open week`.

### Task 3: Punch edit marks and the Home payload

**Goal:** Derive the Self/Admin marks for punches and give the Home tab the worker's punches for the open week.

**Files:**
- Modify: `app/services/attendance.py` (`me_payload`, new `punch_marks`), `app/schemas/attendance.py` (`AttendanceMeResponse`)
- Test: `tests/test_attendance_service.py`

**Interfaces (produces):**
- `TAG_FIELDS = ("created", "started_at", "ended_at", "lunch_waived")`. "Looks right" rows (`needs_review`) are not edits.
- Dataclasses `PunchEditView(by_name: str, self: bool, field: str, old: str | None, new: str | None, at: datetime)` and `PunchMarks(punch_id: uuid.UUID, tags: list[str], edits: list[PunchEditView])`. `tags` is drawn from `"self"` and `"admin"`, in that order.
- `punch_marks(db, owners: dict[uuid.UUID, uuid.UUID]) -> dict[uuid.UUID, PunchMarks]`. It takes `punch_id → owner_id` and runs one query joining `AttendancePunchEdit` to `User`, filtered to `TAG_FIELDS`. A punch with no edits is absent from the result.
- `AttendanceMe.week_punches: list[MyPunch]`, where `MyPunch(id, started_at, ended_at, needs_review, tags)`.
  - It holds the user's live punches with `started_at` in the open Central week, oldest first.
  - The end goes through `capped_end`, as `me_payload` already does.
  - Schemas: `AttendanceMyPunch` and `week_punches: list[AttendanceMyPunch] = []` on `AttendanceMeResponse`.

- [ ] **Step 1: Write the failing tests.**
  - `test_punch_marks_self_admin_both_and_none`. It uses four punches:
    - Owner-edited → `["self"]`.
    - Admin-edited → `["admin"]`.
    - Both → `["self", "admin"]`.
    - "Looks right" only → absent.
  - `test_me_payload_lists_this_weeks_punches_only`: last week's punch is absent, and this week's two are present in order with their tags.
- [ ] **Step 2: Run.** Expect FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Rerun.** Expect PASS. Also run `tests/test_attendance_router.py` to check that the `/attendance/me` shape still validates.
- [ ] **Step 5: Commit** `feat(attendance): edit marks and this week's punches on the Home payload`.

### Task 4: Workers edit their own hand-entered labor

**Goal:** Let workers key, revise and remove their own hand-entered labor while the week is open, and expose what the Labor card needs to show it.

**Files:**
- Modify: `app/services/work_orders.py:2112-2205`, `app/routers/work_orders.py:453` (`_labor_detail`), `app/schemas/work_orders.py:203` (`WorkOrderLaborDetail`)
- Test: `tests/test_work_orders_service.py` (rewrite the tests at :500 and :520), plus a router test in the same file family that asserts the detail fields

**Interfaces:**
- `_require_labor_editor(user, *, technician_id: uuid.UUID, entry: WorkOrderLabor | None = None, work_order: WorkOrder | None = None, now: datetime | None = None) -> None`. Admin/Owner and `user is None` pass. Anyone else needs all of the following, or raises `RoleManagementError` with the refusal copy:
  - `technician_id == user.id`;
  - for an add, `user.id in _assigned_technician_ids(work_order)`;
  - for an update or delete, `entry.session is None`, which means hand-entered;
  - `week_is_open(entry.created_at, now)`.
- `update_work_order_labor` also sets `entry.recorded_by_id = user.id` when `user` is set (B2: the latest editor wins).
- `WorkOrderLaborDetail` gets three new fields:
  - `hand_entered: bool = False`, which is `session is None`;
  - `recorded_by_self: bool = False`, which is `entry.recorded_by_id == entry.technician_id`;
  - `week_open: bool = True`, which is `week_is_open(entry.created_at, now)`.

- [ ] **Step 1: Rewrite the two tests.**
  - `test_worker_keys_and_revises_own_labor_on_their_crew`:
    - A crew tech adds 35 minutes for themselves → OK, and `recorded_by_id == tech.id`.
    - The tech updates the row → OK.
    - The tech deletes the row → OK.
  - `test_worker_off_the_crew_cannot_key_own_labor`: a stranger tech's add for themselves raises `RoleManagementError`.
  - `test_worker_cannot_edit_another_persons_labor`: a supervisor or OA editing the tech's row is refused, and the row is unchanged.
  - `test_worker_cannot_edit_a_session_labor_row`: a row produced by `stop_labor_session` is refused for its own tech.
  - `test_worker_cannot_edit_labor_from_a_closed_week`: set `created_at` to last week; the edit is refused.
  - `test_worker_revising_an_admin_row_takes_recorded_by`: an Admin adds a row for the tech, then the tech updates it, and `recorded_by_id == tech.id`.
  - Keep the Owner/Admin happy path.
- [ ] **Step 2: Add a detail test.** A work-order detail response's `labor` entries carry `hand_entered`, `recorded_by_self` and `week_open` with the expected values for one session row and one hand row.
- [ ] **Step 3: Run.** Expect FAIL.
- [ ] **Step 4: Implement.**
- [ ] **Step 5: Rerun.** Expect PASS. Then run `tests/test_work_order_name_responses.py`.
- [ ] **Step 6: Commit** `feat(work-orders): workers key and revise their own hand-entered labor in the open week`.

### Task 5: Flagged days are left out of Hours totals and the CSV

**Goal:** Take needs-review days out of every Hours total, and give the boards the counted hand-entered minutes they need.

**Files:**
- Modify: `app/services/attendance_compare.py`, `app/schemas/attendance.py` (row schema)
- Test: `tests/test_attendance_compare_service.py`, `tests/test_attendance_export_router.py`

**Interfaces:**
- `pending` becomes `attendance.day_pending_review(day.punches, summary.timeline if summary else [])`. It now also catches `crosses_midnight` (U8).
- These totals sum **only the days that are not pending**, recomputed here and not taken from `clocked`:
  - row `total_minutes`, `paid_minutes`, `tracked_minutes` and `delta_minutes`;
  - `totals_by_day[*].minutes` and `.paid_minutes`;
  - the week's `total_minutes`, `paid_minutes`, `tracked_minutes` and `delta_minutes`.
- New `CompareRow.adjustment_minutes: int` holds counted hand-entered minutes, with the matching schema field on the row.
- CSV:
  - The per-day cells print as now.
  - The `Week` column and the Company block skip pending days.
  - Each person's block gets an eighth metric `("Pending review", …)`, with the cell `"yes"` on a pending day and `""` otherwise. The Company block gets no such row.
- Update the module docstring: the totals rule now lives here.

- [ ] **Step 1: Write the failing tests.**
  - `test_pending_day_is_out_of_every_total`: a two-day person where day 2 is flagged. Row paid, `totals_by_day` for day 2, and the week paid all exclude day 2, while day 2's own `paid_minutes` is still reported.
  - `test_crosses_midnight_day_is_pending`.
  - `test_row_adjustment_minutes_counts_unflagged_days_only`.
  - `test_csv_week_column_skips_pending_and_marks_it`.
- [ ] **Step 2: Run.** Expect FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Rerun.** Expect PASS. Also run `tests/test_attendance_week_router.py`.
- [ ] **Step 5: Commit** `feat(attendance): needs-review days are left out of Hours totals and the CSV`.

### Task 6: Profile payload: hand-entered labor charged, uncharged, pending, marks

**Goal:** Give the profile everything the day timeline and the new totals need.

**Files:**
- Modify: `app/services/labor_summary.py` (`Adjustment`, `_adjustments_for_day`), `app/services/person_week.py`, `app/schemas/hub.py` (`HubAdjustment`, `PersonWeekDay`, `PersonWeekResponse`)
- Test: `tests/test_person_week_service.py`, `tests/test_labor_summary.py`

**Interfaces:**
- `Adjustment` gets `labor_id: uuid.UUID` and `recorded_by_self: bool` (`entry.recorded_by_id == technician_id`). Mirror both on `HubAdjustment` with defaults, so the hub's other readers are unaffected.
- `PersonDay` changes:
  - `charged_minutes = closed + running + adjustment` (U6);
  - new `uncharged_minutes = max(0, paid - charged)` (B3);
  - new `pending_review = attendance.day_pending_review(punches, summary.timeline)`;
  - new `punch_marks: list[attendance.PunchMarks]`, from one `punch_marks` call for the week's non-carried punches.
- `PersonWeek` changes:
  - `total_clocked/paid/charged/adjustment/uncharged_minutes` sum non-pending days only;
  - new `total_uncharged_minutes`;
  - `total_completed` is unchanged (it is not hours).

- [ ] **Step 1: Write the failing tests.**
  - `test_charged_includes_hand_entered_labor`.
  - `test_uncharged_is_floored_at_zero`: hand-entered labor exceeds paid.
  - `test_pending_day_is_shown_but_left_out_of_week_totals`.
  - `test_punch_marks_ride_the_day`.
  - `test_adjustment_carries_labor_id_and_recorded_by_self`.
  - Update the existing assertions that read the old `charged_minutes`.
- [ ] **Step 2: Run.** Expect FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Rerun.** Expect PASS. Also run `tests/test_person_week_router.py` and `tests/test_labor_summary.py`.
- [ ] **Step 5: Commit** `feat(users): profile counts hand-entered labor as charged, adds uncharged, pending, and edit marks`.

### Task 7: The day timeline on the profile

**Goal:** Render the colour-coded day timeline inside each opened profile day and update the summary columns.

**Files:**
- Create: `static/views/dayTimeline.js`
- Modify: `static/views/hubTechnician.js` (import `minutesSinceMidnight` and `hourLabelsHtml` from `dayTimeline.js` and delete its own copies), `static/views/userProfile.js`, `static/styles.css` (next to `.hub-timeline` at ~2514)
- Test: `tests/frontend/views/dayTimeline.test.js` (new), `tests/frontend/views/userProfile.test.js`

**Interfaces (produces):**
- `dayTimelineHtml(day) -> string`. `day` is a `PersonWeekDay`. It returns `""` when the day has no punches, no charged entries and no adjustments.
- `applyTimelinePositions(root: Element) -> void` sets left and width through CSSOM.
- `subtractSpans(outer: [startMin, endMin][], inner: [startMin, endMin][]) -> [startMin, endMin][]` is exported for its test. It produces the uncharged lane.
- Range: the earliest start (no later than 8:00) to the latest end, rounded out to whole hours.

**Markup contract** (the tests assert these classes):

| Element | Class | Content |
|---|---|---|
| Lanes | `.day-tl-lane-punched`, `.day-tl-lane-charged`, `.day-tl-lane-uncharged` | |
| Divider | `.day-tl-divider` | |
| Hand-entered lane | `.day-tl-lane-hand` | chips |
| Punch block | `button.day-tl-punch` | `data-punch` |
| Charged block | `button.day-tl-charged` | `data-number` |
| Hand-entered chip | `button.day-tl-chip` | `data-number` |
| Tag | `span.day-tl-tag.day-tl-tag-self` with text `Self-edited` / `.day-tl-tag-admin` with text `Admin-edited` | |
| Edited block | `.day-tl-edited` (stripes) | |
| Pending wrapper | `.day-tl-pending` | visible text `Not counted — needs review` |
| Legend | `.day-tl-legend` | |

- **`aria-label` and `title` on every block** state the full fact, including the old→new times from `edits`.
- **CSS:**
  - Punched: neutral surface.
  - Charged: `var(--color-brand)` fill with white text.
  - Uncharged: a thin neutral hatch.
  - Chip: a `var(--color-brand)` outline, hollow.
  - `.day-tl-edited`: a `repeating-linear-gradient` stripe overlay.
  - Self tag: brand outline. Admin tag: neutral outline.
  - `.day-tl-pending`: `filter: grayscale(1)` plus reduced opacity.
  - The divider is dashed with an 8px gap.
  - Hide labels on blocks narrower than 40px (`.day-tl-narrow`, set in `applyTimelinePositions`).
  - Define light and dark tokens the way the existing hub timeline does.
- **`userProfile.js`:**
  - Insert `dayTimelineHtml(day)` at the top of `dayBodyHtml` and call `applyTimelinePositions(body)` in `wire`.
  - Wire `.day-tl-charged` and `.day-tl-chip` to `openByNumber`, and `.day-tl-punch` to the same `editing = id; paint()` path, but only when `canEdit`.
  - The summary columns become Day · Paid · Charged · Uncharged · Completed. Charged shows a muted `incl. Xh Ym hand-entered` when `adjustment_minutes > 0`.
  - A pending day gets the class `user-profile-day-pending` and a ⚠.
  - The week row uses the new totals.
  - Delete the "not counted as charged" hint.
  - In the Adjustments list, append the Self/Admin tag (`recorded_by_self`). Append punch tags to the Punches list from `punch_marks`.

- [ ] **Step 1: Write the failing tests** in `dayTimeline.test.js`:
  - `subtractSpans removes charged time from punched time`: `[[480,720]]` minus `[[540,600]]` gives `[[480,540],[600,720]]`.
  - `renders three timed lanes and a separated hand-entered lane`.
  - `edited punch shows striped block and text tag`, for both self and admin.
  - `pending day is greyed and labelled Not counted`.
  - `chip width scales with minutes and never implies a time`: chips carry no `data-left`.
- [ ] **Step 2: Add profile tests** in `userProfile.test.js`:
  - `summary shows Uncharged and hand-entered split`.
  - `clicking a charged block opens the work order`.
  - `Admin clicking a punch block opens the editor`.
  - Update the existing column assertions.
- [ ] **Step 3: Run** `npx vitest run tests/frontend/views/dayTimeline.test.js tests/frontend/views/userProfile.test.js tests/frontend/views/hubTechnician.test.js`. Expect FAIL.
- [ ] **Step 4: Implement.**
- [ ] **Step 5: Rerun.** Expect PASS.
- [ ] **Step 6: Commit** `feat(users): colour-coded day timeline on the profile`.

### Task 8: Hours grid and day page show pending days without counting them

**Goal:** Grey out pending days in the Hours grid and on the day page, and stop counting them in the totals there.

**Files:**
- Modify: `static/views/hubAttendanceHours.js` (cell class), `static/views/hubAttendanceDay.js:104` (sum), `static/styles.css`
- Test: `tests/frontend/views/hubAttendanceHours.test.js`, `tests/frontend/views/hubAttendanceDay.test.js`

**Changes:**
- A cell whose `day.pending_review` is set gets `hub-hours-cell-pending`, which greys it, and its `aria-label` gains `, not counted, needs review`.
- The day page's total skips people whose day is `pending_review`.
- The row and footer totals already come from the server (Task 5).

- [ ] **Step 1: Write the failing tests.**
  - `a pending cell is greyed and labelled not counted`.
  - `day page total skips a pending person`.
- [ ] **Step 2: Run.** Expect FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Rerun.** Expect PASS.
- [ ] **Step 5: Commit** `feat(attendance): Hours grid greys needs-review days and leaves them out`.

### Task 9: Leaderboards tab (Accuracy and Efficiency)

**Goal:** Give Admins a Leaderboards tab with two ranked boards, and move the payroll actions to the top of the Timesheets tab.

**Files:**
- Modify: `static/views/hubTimesheetLeaderboard.js` (it becomes a pure board), `static/views/hubTimesheetsTab.js` (it takes over Export CSV and Mark all reviewed), `static/views/userHub.js` (tab wiring, ≤15 lines), `static/pages/user-hub.html` (the tab button `hub-tab-leaderboards` after Timesheets, `hidden` by default, plus the panel `hub-tabpanel-leaderboards`), `static/tips.js` (`hub.leaderboard` copy, new `hub.leaderboard-accuracy` and `hub.leaderboard-efficiency`), `static/styles.css`
- Create: `static/views/hubLeaderboardsTab.js`
- Test: `tests/frontend/views/hubTimesheetLeaderboard.test.js`, `tests/frontend/views/hubTimesheetsTab.test.js`, `tests/frontend/views/userHub.test.js`, `tests/frontend/views/hubLeaderboardsTab.test.js` (new)

**Interfaces:**
- **`computeLeaderboard(payload, { kind: "accuracy" | "efficiency" })`:**
  - `clocked = row.total_minutes`.
  - `charged = row.tracked_minutes`, plus `row.adjustment_minutes` for efficiency.
  - The server has already removed pending days, so there is no subtraction here.
  - `uncharged = max(0, clocked - charged)`. Made and lost are as now.
  - `pct = clocked ? round(charged / clocked * 100) : (charged ? 100 : 0)`. It is uncapped (B6).
  - Sort by `pct` descending, then `made` descending, then name. `pendingDays` still counts the `pending_review` days for the ⚠ note.
- **`mountLeaderboardBoard(container, payload, { kind })`** renders one board.
  - Columns: Rank · Person · % · Clocked · Charged · Uncharged · Made · Lost.
  - Heading: `Accuracy` or `Efficiency`, each with its tip.
  - It has no buttons and makes no fetches.
- **`renderLeaderboardsTab(panelEl)`** in `hubLeaderboardsTab.js`:
  - It holds its own `week`, fetches with `apiGetHubAttendanceWeek({ week })`, and shows ◀/▶ week navigation using `shiftMonday` and `weekLabel` from `hubWeek.js`.
  - The two boards sit in a `.hub-leaderboards-grid`: two columns at ≥900px, stacked below that.
  - It shows a skeleton while loading, and on error an error message with Retry.
- **Timesheets tab:** in `renderWeek`, `.hub-timesheets-leaderboard` becomes `.hub-timesheets-actions`. It holds `Mark all reviewed (N)` (Admin, when `reviewable_count`) and `Export CSV`. Both handlers move over verbatim from the leaderboard module, along with the notice line.
- **`userHub.js`:**
  - Add `leaderboards` to `tabPanels`.
  - Show the button under the same `canViewTimesheets` gate, **and** only for Admin+ (`roleAtLeast(role, "admin")`).
  - `renderActive` calls `renderLeaderboardsTab(tabPanels.leaderboards)`.

- [ ] **Step 1: Rewrite the leaderboard tests.**
  - `computeLeaderboard uses server row totals as-is`: a row with a pending day and `total_minutes` already reduced gives `clocked === total_minutes`.
  - `accuracy ranks by live % and ignores hand-entered`.
  - `efficiency adds adjustment_minutes and may exceed 100`.
  - `zero clocked with charge is 100%, with none is 0%`.
- [ ] **Step 2: Write the tab tests.**
  - `hubLeaderboardsTab renders both boards and steps weeks`.
  - `userHub hides Leaderboards for a Team Lead and shows it for Admin`.
  - `Timesheets tab keeps Export CSV and Mark all reviewed`.
- [ ] **Step 3: Run the five frontend files.** Expect FAIL.
- [ ] **Step 4: Implement.** Tip copy:
  - Accuracy: `"Ranks the share of clocked time charged on a live work-order clock. Hand-entered labor is not counted."`
  - Efficiency: `"Ranks the share of clocked time charged, counting live clocks and hand-entered labor. Above 100% means more labor was keyed than clocked."`
- [ ] **Step 5: Rerun.** Expect PASS.
- [ ] **Step 6: Commit** `feat(users): Leaderboards tab with Accuracy and Efficiency boards`.

### Task 10: Home tab — "This week's punches"

**Goal:** Let a worker fix, add and delete their own punches for the open week from the Home tab.

**Files:**
- Modify: `static/views/hubHome.js`, `static/styles.css`
- Test: `tests/frontend/views/hubHome.test.js`

**Changes:**
- **Placement:** below `punchHtml()`, add `<details class="hub-home-week-punches">` with the summary `This week's punches`.
- **Each row:** the date, `start – end` (or `running`), the minutes, the `Self-edited` / `Admin-edited` tags, `⚠ needs review` when flagged, and an `Edit` button (`data-action="hub-home-edit-punch"`, `data-punch`).
- **Add:** a `+ Add punch` button, and a `.hub-home-punch-editor` host.
- **Editor:** reuse `mountPunchEditor` from `hubAttendancePunchEditor.js`:
  - Save calls `apiAddAttendancePunch({ userId: getCurrentUser().id, ... })` or `apiEditAttendancePunch(id, values)`.
  - Delete calls `apiDeleteAttendancePunch(id, reason)`.
  - On success, call `refreshCallback`. On error, show `friendlyError` in the editor's message line, the same way `userProfile.js` `write()` does.
- **State:** keep the open editor's id in a module variable; a refresh closes it.

- [ ] **Step 1: Write the failing tests.**
  - `lists this week's punches with tags`.
  - `Edit opens the editor and PATCHes the punch`.
  - `Add posts with the viewer's own user id`.
  - `a 403 shows the refusal copy in the editor`.
- [ ] **Step 2: Run.** Expect FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Rerun.** Expect PASS.
- [ ] **Step 5: Commit** `feat(attendance): workers fix their own punches from the Home tab`.

### Task 11: Labor card self-edit

**Goal:** Show Update/Remove and the Add form on a work order's Labor card to the workers the server now allows.

**Files:**
- Modify: `static/views/workOrderPresenters.js`, `static/views/workOrderCardHtml.js:48-120`, `static/styles.css`
- Test: `tests/frontend/views/workOrders/roles.test.js`, `tests/frontend/views/workOrders/render.test.js`

**Interfaces:**
- `canEditLaborEntry(entry) -> boolean`: Admin+ → true. Otherwise `entry.hand_entered && entry.week_open && entry.technician_id === getCurrentUser()?.id`.
- `canAddLabor(detail) -> boolean`: Admin+ → `canKeyLabor()`. Otherwise the viewer is in `detail.technician_ids`. Builder: use whatever field `laborTechnicianControl` already reads.
- **`renderLaborEntryHtml`:** gate Update/Remove on `canEditLaborEntry(entry)`. For hand-entered rows, append `Self-entered` or `Admin-entered`, using the same tag classes as Task 7.
- **`laborTechnicianControl`:** a non-Admin gets a single-option select holding only themselves.
- **Unchanged:** the action handlers in `workOrderActions.js` already post `technician_id` from that select. The server enforces the rule.

- [ ] **Step 1: Write the failing tests.**
  - `technician sees Update on own hand-entered row in the open week only`.
  - `technician never sees Update on a session row or a peer's row`.
  - `technician on the crew sees Add labor with only themselves`.
  - `admin unchanged`.
- [ ] **Step 2: Run.** Expect FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Rerun.** Expect PASS.
- [ ] **Step 5: Commit** `feat(work-orders): Labor card offers self-edit on a worker's own hand-entered rows`.

### Task 12: Living docs

**Goal:** Bring the living docs up to date with what shipped.

**Files:** `docs/current-state.md`, `docs/endpoint-map.md`, `docs/open-work.md` (only if an item closes)

- [ ] **Step 1: Update `current-state.md`.** Replace the "hand-keyed labor Admin/Owner only" line with the self-edit rule. Add the totals rule, the profile timeline, and the Leaderboards tab. Stay inside the word budget, deleting stale lines in the same edit.
- [ ] **Step 2: Update `endpoint-map.md`.**
  - The punch routes are now `get_current_user` plus the service guard.
  - `/attendance/me` gains `week_punches`.
  - `WorkOrderLaborDetail` gains `hand_entered`, `recorded_by_self` and `week_open`.
  - The person-week day gains `uncharged_minutes`, `pending_review` and `punch_marks`, and its charged figure now includes hand-entered labor.
  - The compare row gains `adjustment_minutes`, and its totals now leave out pending days.
- [ ] **Step 3: Commit** `docs: self-edited time, profile timeline, Leaderboards tab`.
