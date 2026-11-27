# Flagged Clock Hours Edit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In Fix flagged time, an auto-stopped work-order clock's step shows the order's details and lets a Team Lead set the real stop time, which moves the clock, the billed labor line and the Timesheets hours together and accepts the clock; a guided tutorial chapter teaches it.

**Architecture:** The existing accept route takes an optional `ended_at`. One transaction moves the session's stop, sets its labor row's minutes and accepts it. A new view module renders the clock step (no requests). The flow and the Timesheets tab pass it `loadWorkOrder` / `saveSession` callbacks. The tutorial uses the sample responder.

**Tech Stack:** FastAPI + SQLAlchemy + pytest (real TestClient); vanilla ES modules + Vitest/MSW.

**Spec:** `docs/superpowers/specs/2026-11-27-flagged-clock-hours-edit-design.md`

## Global Constraints

- Built on a branch from `origin/main`, in a worktree. Takeoff (local `main`) must not ride along. Nothing is pushed until the user's in-app check and go-ahead.
- No `style=` attributes (CSP); no button inside a button; no sideways scroll at phone width; times shown in Central (`America/Chicago`).
- Files under 500 lines.
- Tutorial lines under 120 characters. Sample ids use the prefix `ffffffff-ffff-4fff-8fff-`.
- Workers never see clock steps (`canAccept` gate unchanged).
- `auto_closed_at` is never cleared: the Leaderboard keeps excluding the order.
- Vitest runs from PowerShell at `C:\...` (uppercase drive), not from the Bash tool.
- Stage explicit paths only (shared checkout); never `git add -A`.

## Review Focus

1. A clock that crosses midnight (7 PM Mon → 7 AM Tue): picking "11:00 PM" must mean Mon 11 PM, not Tue 11 PM. Covered by the `resolveStop` tests in Task 4.
2. The clock's labor line was deleted on the order (`labor_id` NULL): save still moves and accepts the clock without a 500. Test in Task 2.
3. The order detail fails to load (403/404/network): the step still edits and accepts. Test in Task 4.
4. A double tap on Save & accept: one request only (the flow's `busy` gate). Test in Task 5.
5. Someone accepted the clock in another tab: the save returns 404, the step shows the message, and the refresh drops the item. Existing flow behaviour; asserted in Task 5.

---

### Task 1: Worktree and docs

**Files:**
- Move in: `docs/superpowers/specs/2026-11-27-flagged-clock-hours-edit-design.md`, `docs/superpowers/plans/2026-11-27-flagged-clock-hours-edit.md` (untracked in the main checkout)

- [ ] **Step 1:** `git fetch`, then create the worktree on branch `flagged-clock-hours` from `origin/main` (superpowers:using-git-worktrees / `EnterWorktree`).
- [ ] **Step 2:** Copy `backend/.env` from the main checkout. Run `npm ci` in the worktree (never junction `node_modules`). Python runs on the main checkout's `backend/venv` interpreter, with cwd set to the worktree's `backend/`.
- [ ] **Step 3:** Move the two docs into the worktree at the same paths, and delete the main-checkout copies.
- [ ] **Step 4:** Commit: `git add <the two paths>`; `git commit -m "docs: flagged clock hours edit design and plan"`.

### Task 2: Accept route sets the real stop

**Files:**
- Modify: `backend/app/schemas/attendance.py` (add `SessionReviewRequest` next to `SessionReviewResponse`)
- Modify: `backend/app/services/attendance.py` (`review_session`)
- Modify: `backend/app/domain/work_orders.py` (add `NOTE_STOP_CORRECTED`)
- Modify: `backend/app/routers/hub.py` (`review_hub_attendance_session`)
- Test: `backend/tests/test_attendance_admin_router.py`

**Interfaces:**
- Produces: `POST /hub/attendance/sessions/{session_id}/review` with optional JSON body `{"ended_at": "<ISO instant>"}`. The response is unchanged: `{session_id, reviewed_at}`.
- Produces: `review_session(db, *, actor, session_id, ended_at: Optional[datetime] = None, now=None) -> WorkOrderLaborSession`.
- `SessionReviewRequest(BaseModel)`: `ended_at: Optional[datetime] = None`.
- `NOTE_STOP_CORRECTED = "corrected the stop time to {new} (was {old})"`. Both times are Central `h:MM AM/PM` (`%I:%M %p`, leading zero stripped).

- [ ] **Step 1: Write the failing tests.** Extend `_labor_session` with `with_labor=False`. When true, it adds a `WorkOrderLabor(minutes=720, technician_id=tech.id)` and sets `session.labor_id`. `_review(db, actor, session_id, body=None)` posts `json=body` when given.

```python
def test_a_team_lead_sets_the_real_stop(db):
    lead, tech = _seed_user(db, "supervisor"), _seed_user(db)
    s = _labor_session(db, tech, ended_hours_ago=2, with_labor=True)  # 12 h clock
    new_end = s.started_at + timedelta(hours=8, minutes=30)
    r = _review(db, lead, s.id, {"ended_at": new_end.isoformat()})
    assert r.status_code == 200
    db.expire_all()
    row = db.get(WorkOrderLaborSession, s.id)
    assert row.ended_at == new_end and row.reviewed_at is not None
    assert row.auto_closed_at is not None
    labor = db.get(WorkOrderLabor, row.labor_id)
    assert labor.minutes == 510 and labor.recorded_by_id == lead.id
    assert "corrected the stop time to" in row.work_order.notes

def test_a_stop_before_the_start_is_400(db): ...      # ended_at = started_at → 400, reviewed_at still None
def test_a_stop_after_the_auto_stop_is_400(db): ...   # ended_at = ended_at + 1 min → 400
def test_a_stop_with_no_labor_line_still_accepts(db): # with_labor=False → 200, ended_at moved
def test_no_body_accepts_as_is(db): ...               # existing behaviour: ended_at unchanged
def test_a_technician_cannot_set_a_stop(db): ...      # 403
```

- [ ] **Step 2:** Run `venv\Scripts\python -m pytest tests/test_attendance_admin_router.py -k "stop or body" -v`. Expected: FAIL (422 on the unknown body / the assertions fail).
- [ ] **Step 3: Implement.**
  - Route: `body: Optional[SessionReviewRequest] = None`; pass `ended_at=body.ended_at if body else None`. After the commit, emit `emit_attendance_changed()`, then `_emit_status_changed(session.work_order_id)` (import from `app.routers.work_orders`, as `work_orders_smr.py` does).
  - Service: run the existing sweep / 404 check first. When `ended_at` is given, it must satisfy `session.started_at < ended_at <= session.ended_at`; otherwise raise `PunchTimeInvalidError("The stop must be after the start and no later than the automatic stop.")`. Then append the note to `session.work_order.notes` via `wo.append_note_log(..., author_name=actor.full_name, occurred_at=now)`, set `session.ended_at = ended_at`, and when `session.labor_id` is set, `labor.minutes = int((ended_at - started_at).total_seconds() // 60)` and `labor.recorded_by_id = actor.id`. Then `reviewed_at = now`. One commit.
- [ ] **Step 4:** Run the whole file: `venv\Scripts\python -m pytest tests/test_attendance_admin_router.py -v`. Expected: all PASS.
- [ ] **Step 5:** Commit: `feat(hub): accepting an auto-stopped clock can set its real stop time`.

### Task 3: Labor detail names its session

**Files:**
- Modify: `backend/app/schemas/work_orders.py` (`WorkOrderLaborDetail`)
- Modify: `backend/app/routers/work_orders.py` (`_labor_detail`)
- Test: the existing work-order detail router test file (find it with `grep -l "session_window" backend/tests`)

**Interfaces:**
- Produces: `WorkOrderLaborDetail.session_id: Optional[UUID] = None`, set from `entry.session.id` when a session is behind the row.

- [ ] **Step 1:** Failing test: a labor row produced by stopping a session has `session_id` equal to that session's id, and a hand-entered row has `session_id is None`.
- [ ] **Step 2:** Run it. Expected: FAIL (`KeyError` / missing field).
- [ ] **Step 3:** Add the field and set it in `_labor_detail`.
- [ ] **Step 4:** Run the test file. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(work-orders): labor detail names the clock behind a row`.

### Task 4: The clock step module

**Files:**
- Create: `backend/static/views/flaggedClockStep.js`
- Test: `tests/frontend/views/flaggedClockStep.test.js`

**Interfaces:**
- Produces: `resolveStop(chosen: Date, startedAt: string, endedAt: string) -> string | null`. The picker returns a time on the auto-stop's calendar day. If that is later than `endedAt`, take it 24 h earlier. Return the ISO string when `startedAt < result <= endedAt`, else `null`. `// ponytail: fixed 24 h step, wrong by an hour across a DST change; use a Central calendar shift if that ever bites.`
- Produces: `recentNotes(notes: string | null, n = 5) -> string[]`: split on `/\n\s*\n/`, trim, drop empties, take the last `n`, newest first.
- Produces: `mountClockStep(hostEl, { item, loadWorkOrder, onSave, onAccept, onOpen, onSkip })`.
  - `item`: `{ id, workOrderId, number, started_at, ended_at }`.
  - `loadWorkOrder(workOrderId) -> Promise<WorkOrderDetail>`.
  - `onSave(endedAtIso)`; `onAccept()`; `onOpen()`; `onSkip()`.
- DOM hooks (the tutorial and tests use them): `.flagged-clock-order`, `.flagged-clock-stop` (button, label `Stopped: <time>`), `.flagged-clock-hours`, `[data-flow="save-accept"]`, `[data-flow="accept"]` (text "Accept as is"), `[data-flow="open-wo"]`, `[data-flow="skip"]`, `details.flagged-clock-labor`, `details.flagged-clock-notes`.
- Copy (from the spec): "Save & accept sets the clock and the billed hours to the new stop time. Accept as is keeps 12 hours."; "Loading work order…"; "Could not load the work order."; summaries "Crew and labor (N)" and "Recent notes (N)"; "No notes"; the label "this clock" on the labor row whose `session_id === item.id`.

- [ ] **Step 1: Write failing tests.**
  - `resolveStop`: same-day clock 7:02 AM→7:02 PM, chosen 3:30 PM → 3:30 PM the same day. Crossing clock Mon 7 PM → Tue 7 AM, chosen (Tue) 11 PM → Mon 11 PM. Chosen (Tue) 6 PM, before the Mon 7 PM start once moved back → `null`. Chosen equal to `endedAt` → returned unchanged.
  - `recentNotes`: 7 entries → the last 5, newest first; `null` → `[]`.
  - Mount: the order line reads `WO <number> · <location> · <description> · <status>` after the load. Save & accept is disabled until a stop is picked (stub `promptTime` via `vi.mock("../../../backend/static/dom.js")`), then calls `onSave` with the ISO. The hours text updates (`8.5 h`). Both `<details>` are closed and their summaries carry the counts. A rejecting `loadWorkOrder` shows "Could not load the work order." while the Stopped button and Save & accept still work.
- [ ] **Step 2:** In PowerShell, run `npx vitest run tests/frontend/views/flaggedClockStep.test.js`. Expected: FAIL (module missing).
- [ ] **Step 3:** Implement. Hours are `(minutes / 60).toFixed(1) + " h"`. Use `promptTime({ title: "Stopped at", help: "Central time.", initial: new Date(stop) })` (dom.js) and `escapeHtml` (format.js). The labor rows show `technician_name`, `formatMinutes(minutes)` (workOrderPresenters.js), and "Self"/"Admin" from `recorded_by_self`.
- [ ] **Step 4:** Run the test again. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(hub): clock step shows the order and sets the real stop`.

### Task 5: Flow and Timesheets wiring

**Files:**
- Modify: `backend/static/views/flaggedTimeFlow.js` (`flaggedItems` session items gain `workOrderId: s.work_order_id`; `sessionStep`/`stepHtml` mount `mountClockStep`; options gain `actions.loadWorkOrder`, `actions.saveSession`)
- Modify: `backend/static/views/hubTimesheetsTab.js` (`openFlow` actions)
- Modify: `backend/static/api.js` (`apiReviewAttendanceSession(sessionId, { endedAt } = {})` sends `{ ended_at: endedAt }` when given, `{}` otherwise)
- Modify: `backend/static/flaggedTimeFlow` CSS block (stylesheet that holds `.flagged-flow-*`): one column, wrapping actions, `details` summaries
- Test: `tests/frontend/views/flaggedTimeFlow.test.js`, `tests/frontend/views/hubTimesheetsTab.test.js`

**Interfaces:**
- Consumes: `mountClockStep`, `resolveStop` (Task 4). Route body (Task 2).
- Timesheets: `loadWorkOrder: (id) => apiGetWorkOrder(id)`, memoised per id in a `Map` created in `openFlow`. `saveSession: (id, endedAt) => apiReviewAttendanceSession(id, { endedAt })`. `acceptSession` stays.

- [ ] **Step 1: Update and add failing tests.**
  - Flow: a session step mounts `.flagged-clock-order`. Save & accept calls `actions.saveSession(id, iso)` and advances. A double click sends one call. A rejected save shows the server message and stays put. "Accept as is" still calls `acceptSession`. The worker set (`canAccept: false`) still has no clock step.
  - Timesheets (MSW): the POST to `/hub/attendance/sessions/:id/review` carries `{"ended_at": ...}` after Save & accept; `GET /work-orders/:id` is requested once per step.
  - Update existing assertions on the old "Accept" button text.
- [ ] **Step 2:** Run both files in PowerShell. Expected: the new tests FAIL.
- [ ] **Step 3:** Implement the wiring and CSS (within `docs/design-system.md`).
- [ ] **Step 4:** Run `npx vitest run tests/frontend/views/flaggedTimeFlow.test.js tests/frontend/views/flaggedClockStep.test.js tests/frontend/views/hubTimesheetsTab.test.js tests/frontend/views/hubTimesheetsLive.test.js tests/frontend/unit/staticImports.test.js`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(hub): Fix flagged time edits an auto-stopped clock in place`.

### Task 6: Tutorial chapter

**Files:**
- Modify: `backend/static/tutorials/user-hub.js` (new script after `user-hub.hub.timesheets`)
- Modify: `backend/static/tutorials/user-hub.sample.js`
- Test: `tests/frontend/views/tutorialGuard.test.js` (existing guard; no edits expected)

**Interfaces:**
- Consumes: the DOM hooks from Task 4, and `.hub-timesheets-fix-flagged`.
- Script: `key: "user-hub.hub.fix-clock"`, `title: "Fix an auto-stopped clock"`, `minRole: "supervisor"`, `here: ".flagged-flow .flagged-clock-order"`, `open: ["#hub-tab-timesheets", ".hub-timesheets-fix-flagged"]`. Steps target, in order: `.flagged-flow-reason`, `.flagged-clock-order`, `.flagged-clock-stop`, `[data-flow="save-accept"]`, `[data-flow="accept"]`, `details.flagged-clock-labor`, `details.flagged-clock-notes`, `[data-flow="open-wo"]`. Text follows the spec's tutorial steps; one idea per line.
- Sample: `week.flagged_sessions = [{ session_id: id("000000210030"), user_id: <a sample person whose name sorts before the auto-punch row's person>, date: mon, work_order_id: id("000000210031"), number: "SAMPLE-31", started_at, ended_at (12 h later), running: false }]`. `reviewable_count` 1 → 2. Add `"GET /work-orders/" + id("000000210031")` mapped to a detail shaped like `tests/frontend/helpers/factories.js` `workOrderDetail`, with location, description, status "in_progress", two `assigned_to_names`, two `labor` rows (one with `session_id: id("000000210030")`, `auto_closed: true`), and three note entries separated by blank lines.

- [ ] **Step 1:** Add the script and sample, then run `npx vitest run tests/frontend/views/tutorialGuard.test.js tests/frontend/views/hubTutorials.test.js`. Expected: PASS. If the guard can't reach the pop-up targets, its failure names the step; fix the selector or the sample order, never the guard.
- [ ] **Step 2:** Commit: `feat(tutorials): Fix an auto-stopped clock chapter`.

### Task 7: Docs and hand-off

**Files:**
- Modify: `docs/current-state.md` (Attendance: the accept route's optional stop time moves the clock and its billed labor line; `auto_closed_at` stays)

- [ ] **Step 1:** Edit the doc (one line, current-truth only).
- [ ] **Step 2:** Targeted runs: `pytest tests/test_attendance_admin_router.py tests/test_attendance_compare_service.py tests/test_performance_service.py` plus Task 3's file; Vitest as in Task 5 plus the tutorial files. Record the pass counts.
- [ ] **Step 3:** Commit: `docs: accepting a flagged clock can set its real stop`.
- [ ] **Step 4:** Hand over for the user's in-app check. Give the worktree path and the run command from the runbook (port 8124). Don't start the server: the user validates by hand. The push to `origin/main` happens only after the user says go. Rebasing Takeoff onto the result comes after that.
