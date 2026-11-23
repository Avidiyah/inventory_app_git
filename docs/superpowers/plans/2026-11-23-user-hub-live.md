# User Hub Live (W7) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This repo bars subagents unless the owner authorizes them for the task; default is inline execution.

**Goal:** Every User Hub tab follows live changes and patches in place, keeping what the user has open or typed; a worker's own punch and clock show on all their devices.

**Architecture:** Two audience lines widen in `domain/realtime.py`. `userHub.js` sheds its feeds, timer and subscriptions into `hubLive.js`, where each feed is a coalesced fetcher. One helper, `hubPatch.js`, wraps `morphInto` + `keepPlace` with the hub's shared skip set; every tab module paints through it.

**Tech Stack:** FastAPI, pytest (real `TestClient`); plain ES modules, idiomorph 0.8.0 via `morph.js`, Vitest + jsdom + msw.

**Spec:** `docs/superpowers/specs/2026-11-23-user-hub-live-design.md`. Rule numbers below are the spec's.

## Global Constraints

- CSP: classes only, no inline style or script.
- Every file under 500 lines; `userHub.js` (601) must end under it (rule 9).
- Envelope shape unchanged; no new event type, no new route.
- Subscribe handlers receive `{ activePage, envelope, reason }`; `reason === "reconnect"` means anything may have changed.
- The clock node `#hub-clock-mount` is reparented, never rebuilt.
- Delegated listeners on tab mounts stay; `morphInto` must not drop the `data-wired` mount.
- One push for all of W7, after the owner's phone check. Pushing deploys: ask first.
- Shared checkout: stage explicit paths only. Targeted tests only. Vitest from PowerShell at `C:\Users\mcclu\Desktop\inventory_app_git` (`npx vitest run <file>`); pytest from `backend\` with the main checkout's venv.
- An existing test that fails is a finding. Change it only when it asserts retired behaviour (wipe on refresh, attendance audience Supervisor+, own action calls `loadUserHub`); name each in the commit body.
- Exact copy (rule 4): `"That punch was changed on another device."`

## Risk register

Spec risks 1–10, plus:

| # | Hazard | Closed by |
|---|---|---|
| 11 | `morphInto` over a mount whose first child is a skeleton glows everything | First draw: a mount holding no `flashSelector` match flags nothing (`morph.js` contract); T3 test |
| 12 | Error panel replaced by a patch keeps a stale Retry listener | Error/skeleton paths keep `innerHTML` (rule 1 exception); T3 |
| 13 | User change mid-flight paints the previous user's feed | `hubLive` feeds expose `reset()`; `loadUserHub` calls it where it bumps request ids today; T2 |
| 14 | Tab-hidden feeds still fetching on events | Each feed's `when` predicate; T2 test |

## Review Focus

1. Phone on Home with "This week's punches" open; desktop punches out → list stays open, new row glows, hero switches to "Not punched in" (T4).
2. Punch editor open on a punch an Admin deletes → editor closes with the rule 4 note (T4).
3. Twenty `work_order.status.changed` in one tick while an Admin is on Dashboard → at most two `/hub/admin` requests (T2).
4. Leaderboards showing month; an hours edit → only the month refetches; tab hidden → nothing fetches (T7).
5. Running clock ticks through a Home patch without restarting from zero (T4).

---

### Task 1: Widen two event audiences

**Files:** Modify `backend/app/domain/realtime.py:110-121` (comments + map). Test: `backend/tests/test_realtime_domain.py:204-218`, `backend/tests/test_realtime_emit.py` cases asserting a Technician socket gets nothing for these two events.

**Interfaces:** Produces: `audience_allows("attendance.changed" | "labor.session.changed", "technician") is True`.

- [ ] **Step 1:** Replace `test_attendance_events_do_not_reach_technicians` with `test_attendance_events_reach_technicians` (asserts `True` for `"technician"`), and add `test_labor_session_events_reach_technicians` (same for `EVENT_LABOR_SESSION_CHANGED`).
- [ ] **Step 2:** `pytest tests/test_realtime_domain.py -q` → 2 FAIL.
- [ ] **Step 3:** Set both entries to `roles.ROLE_TECHNICIAN`; rewrite their comments: consumers now include the worker's own Home tab on another device (W7), not a security boundary (P2).
- [ ] **Step 4:** `pytest tests/test_realtime_domain.py tests/test_realtime_emit.py -q` → PASS (fix any emit test pinning the old audience; name it in the commit body).
- [ ] **Step 5:** Commit `feat(realtime): attendance and clock events reach technicians (W7 T1)`.

### Task 2: `hubLive.js` — coalesced feeds, timer, subscriptions

**Files:** Create `backend/static/views/hubLive.js`. Modify `backend/static/views/userHub.js` (move `refreshCrew`, `refreshAdmin`, `refreshPersonal`, `loadGraphs`, `loadReport`, the safety timer and all three `subscribe` blocks out). Test: create `tests/frontend/views/hubLive.test.js`; `tests/frontend/views/userHub.test.js` must stay green; add `hubLive.js` to `tests/frontend/unit/staticImports.test.js` if it lists modules.

**Interfaces:**
- Produces: `createFeed(fetcher: () => Promise<any>, onData: (payload) => void, { when?: () => boolean, onError?: (err) => void }) -> { run({ background }?: object) => Promise<void>, reset() => void }`. At most one fetch in flight; a `run` during a fetch queues exactly one rerun; `when()` false → no fetch; `reset()` drops in-flight results.
- Produces: `startHubLive(ctx)` / `stopHubLive()` where `ctx` exposes `{ feeds: { personal, attendance, crew, admin, graphs, leaderboards, report, timesheets }, activeTab: () => string, role: () => string }`. Event → feed table (rule 4/6/7):

| Trigger | Feeds run |
|---|---|
| `attendance.changed` | personal, attendance, timesheets, leaderboards, report |
| `labor.session.changed` | personal, crew, admin |
| `work_order.status.changed` | personal, crew, admin, graphs, leaderboards, report |
| `user_request.changed` | personal |
| reconnect, 60 s timer (visible only) | all |

- [ ] **Step 1: Failing tests** in `hubLive.test.js`: `createFeed coalesces a burst into two fetches` (20 `run()` calls while the first is pending → fetcher called 2 times); `createFeed skips when the predicate is false`; `reset discards an in-flight result` (onData not called); `attendance.changed runs the attendance feed for a technician`; `the timer does nothing while the document is hidden`.
- [ ] **Step 2:** `npx vitest run tests/frontend/views/hubLive.test.js` → FAIL (module missing).
- [ ] **Step 3:** Implement `hubLive.js`; rewire `userHub.js` to build feeds with each `when` gated on role and active tab (crew: Supervisor+; admin, graphs: techfm_oa+; leaderboards, report: Admin+ and that tab active; report also `reportWeek === null` for events; timesheets: tab active). `loadUserHub` calls each feed's `reset()` where it bumps request ids today.
- [ ] **Step 4:** `npx vitest run tests/frontend/views/hubLive.test.js tests/frontend/views/userHub.test.js tests/frontend/unit/staticImports.test.js` → PASS; `wc -l` both files < 500.
- [ ] **Step 5:** Commit `refactor(hub): feeds, timer and events move to hubLive with coalescing (W7 T2)`.

### Task 3: `hubPatch.js` — the one patch path

**Files:** Create `backend/static/views/hubPatch.js`. Test: create `tests/frontend/views/hubPatch.test.js`.

**Interfaces:** Produces: `patchHub(mount: Element, html: string, { flashSelector?: string, skipSelector?: string }) -> void`. Builds `html` into a detached `<div>`, runs `morphInto(mount, div.childNodes, { flashSelector, skip })` between `keepPlace(mount)` and its restore. `skip(old)` is true when `old` is `document.activeElement`, a dirty `input|select|textarea` (`isDirty`), matches `.punch-editor, [data-live-skip]`, or matches `skipSelector`.

- [ ] **Step 1: Failing tests:** `keeps a focused input's value`; `keeps a dirty field`; `leaves a .punch-editor subtree untouched`; `keeps an open details open`; `flags a changed [id] element with just-changed`; `a first draw over a skeleton flags nothing`; `an unchanged repaint flags nothing`.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** run → PASS.
- [ ] **Step 5:** Commit `feat(hub): one patch helper for hub tabs (W7 T3)`.

### Task 4: Home and clock live (rules 2, 4, 5, 8)

**Files:** Modify `backend/static/views/hubHome.js`, `backend/static/views/hubClock.js`, `backend/static/views/userHub.js::renderHome`. Test: `tests/frontend/views/hubHome.test.js`, `hubClock.test.js`, `userHub.test.js`.

**Interfaces:** Consumes `patchHub` (T3), feeds `personal`/`attendance` (T2). Produces: `mountHubHome(mountEl, hub, attendance, { onChanged })` unchanged signature, now patching; `onChanged` is the targeted refresh `refreshHomeFeeds(): Promise<void>` (runs personal + attendance), not `refreshUserHub`. Ids: `hub-punch`, `hub-home-week-punches`, `hub-home-punch-<id>`, `hub-tile-assigned|in-progress|ready`.

- [ ] **Step 1: Failing tests:** `a live attendance change patches Home and keeps the week list open`; `an open punch editor survives a patch`; `an editor whose punch is gone closes with "That punch was changed on another device."`; `own punch-out calls the targeted refresh, not loadUserHub`; `the clock slot node is the same element after a patch`; `a running clock keeps its start time through a patch`; `the per-second hero tick does not add just-changed` (flashSelector excludes `.hub-punch-hero`, `.hub-clock-elapsed`; flashKey reads the element without its ticking child).
- [ ] **Step 2:** run the three files → FAIL.
- [ ] **Step 3:** Paint Home via `patchHub(container, html, { flashSelector: "[id^=hub-home-punch-], .hub-tile[id]", skipSelector: "#hub-home-clock-slot" })`; on repaint, if the editor's punch id is absent from `week_punches`, clear the editor host and set the message. `hubClock.js` paints via `patchHub`.
- [ ] **Step 4:** run → PASS.
- [ ] **Step 5:** Commit `feat(hub): Home and clock follow live changes and patch in place (W7 T4)`.

### Task 5: Dashboard modules patch

**Files:** Modify `hubTechnician.js` (dashboard + work-orders mounts), `hubPriorities.js`, `hubSupervisor.js`, `hubAdmin.js`, `hubPerformanceBoard.js`. Test: their existing `*.test.js` files.

**Interfaces:** Consumes `patchHub`. Each module's `mount*` keeps its signature. Ids: `hub-priority-<kind>-<id>`, `hub-crew-<userId>`, `hub-admin-<key>`, `hub-board-<userId>`.

- [ ] **Step 1: Failing tests** (one per module): `a repaint with one changed row flags only that row`; `an open details in the section stays open`. Supervisor: `crew rows keep identity when order changes`.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** Swap each `container.innerHTML = …` for `patchHub(container, …, { flashSelector })`; empty-state branches in `hubPriorities.js` patch to `""`.
- [ ] **Step 4:** run → PASS.
- [ ] **Step 5:** Commit `feat(hub): Dashboard sections patch in place (W7 T5)`.

### Task 6: Timesheets patch

**Files:** Modify `hubTimesheetsTab.js` (week/live areas), `hubAttendanceRoster.js`, `hubAttendanceHours.js`, `hubAttendanceDay.js`. Test: their `*.test.js`.

**Interfaces:** Consumes `patchHub`, feed `timesheets` (T2: `refreshTimesheetsLive` becomes its fetcher). Keeps the existing "no week refetch while profile or `.punch-editor` open" guard. Ids: `ts-roster-<userId>`, `ts-hours-<userId>`.

- [ ] **Step 1: Failing tests:** `a roster change patches without rebuilding the shell`; `a changed hours row glows, others do not`; `the week does not refetch while a punch editor is open` (existing — keep green).
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** Swap list/area repaints to `patchHub`; shell (`buildShell`) and error/skeleton paths unchanged.
- [ ] **Step 4:** run → PASS.
- [ ] **Step 5:** Commit `feat(hub): Timesheets patch in place (W7 T6)`.

### Task 7: Leaderboards, Report and Graphs live (rule 7)

**Files:** Modify `hubLeaderboardsTab.js`, `hubReport.js`, `hubGraphs.js` (outer paint only), `userHub.js` feed wiring. Test: `hubLeaderboardsTab.test.js`, `hubReport.test.js`, `hubGraphs.test.js`, `hubLive.test.js`.

**Interfaces:** Consumes feeds `leaderboards`, `report`, `graphs` (T2), `patchHub`. Produces: `refreshLeaderboardsLive(panelEl)` exported from `hubLeaderboardsTab.js` (refetches the current period, background, keeps last good on error). Ids: `lb-row-<userId>`, `report-row-<key>`.

- [ ] **Step 1: Failing tests:** `work_order.status.changed refetches leaderboards for the selected period while the tab is showing`; `no leaderboards fetch while the tab is hidden`; `an event refetches the report only for the week in progress`; `a closed report week is not refetched by an event`; `a reordered leaderboard keeps row identity and glows the changed row`; `graphs keep the open pop-up through a live patch`.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** Implement; report/leaderboard/graph bodies paint via `patchHub`.
- [ ] **Step 4:** run → PASS.
- [ ] **Step 5:** Commit `feat(hub): Leaderboards, Report and Graphs follow live changes (W7 T7)`.

### Task 8: Census, docs, full hub run

**Files:** Create `tests/frontend/views/hubIdsCensus.test.js`. Modify `docs/current-state.md` (realtime event rows: audiences, hub live), `docs/open-work.md` (W7 line, if listed).

- [ ] **Step 1:** Census test: render each tab from `tests/frontend/helpers/hub.js` fixtures; every element matching each module's `flashSelector` has a unique non-empty `id`.
- [ ] **Step 2:** `npx vitest run tests/frontend/views/hub tests/frontend/views/userHub.test.js tests/frontend/views/hubIdsCensus.test.js tests/frontend/unit/staticImports.test.js` → PASS; `pytest tests/test_realtime_domain.py tests/test_realtime_emit.py -q` → PASS.
- [ ] **Step 3:** Update the two docs within their word budgets.
- [ ] **Step 4:** Commit `test(hub): id census; docs for W7 (W7 T8)`.
- [ ] **Step 5:** Owner's phone check (spec Testing list); then ask before pushing.
