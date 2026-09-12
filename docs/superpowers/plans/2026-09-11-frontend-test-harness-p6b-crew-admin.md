# Frontend Test Harness — P6b (`hubSupervisor.js` + `hubAdmin.js`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task, **inline in the session — no subagents** (`CLAUDE.md` forbids them here). Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Status: go-ahead given 2026-09-11 ("Continue P6B"). Second P6 chunk.**

**Goal:** Characterization coverage for the two views that paint into the mounts P6a only asserted exist — the crew board (139 lines, `GET /hub/crew`) and the company-wide admin summary (175 lines, `GET /hub/admin`) — plus the three row sub-shapes both payloads default to empty.

**Architecture:** Tests only, on P5f's `helpers/hub.js`. Every branch of both modules is reachable through `openHub({role, crew, admin})`, because `userHub.js` mounts each renderer off the payload the fixture answers with: `refreshCrew()` → `renderCrew()` → `mountHubCrew(#hub-crew-mount, …, {isAdminPlus})`, and `refreshAdmin()` → `mountHubAdminSummary(#hub-admin-mount, …)`. No direct mount is needed (parent deviation 5 is available but unused here); the `isAdminPlus` half of the crew board is driven by role, and D16's absent board by `led.total`.

**Tech Stack:** Vitest, jsdom, @testing-library/user-event, msw.

**Spec:** `docs/superpowers/specs/2026-09-10-frontend-test-harness-design.md` §3.2–3.3
**Parent plan:** `docs/superpowers/plans/2026-09-11-frontend-test-harness-p6.md` (P6b bullets are the requirement set)
**Depends on:** P6a (the hub fixture in anger), P5f (`helpers/hub.js`, `connectHub`, `hubCrew()`, `hubAdmin()`), P2 (`filterOptions()`, the Work Orders page's own filter controls).

## Global constraints

- Tests only. No edit under `backend/static/` or `backend/app/`.
- Characterization, not correction. Findings land in `docs/open-work.md` → `N-P6-CHARACTERIZED`.
- No `vi.mock` of any app module. Seams: `fetch` (MSW), fake timers, the fake `WebSocket` (`connectHub`), `window.scrollTo` (`stubScroll`).
- `onUnhandledRequest: "error"` stays on. A pipeline-tile click swaps to Work Orders, which fires the page's reference loads; `handOff()` answers them.
- `afterEach`: `stopClock()`, `expect(vi.getTimerCount()).toBe(0)`, `restoreHub()`, `restoreBrowserStubs()`.
- New factories get a drift row in `unit/api.endpoints.test.js` in the same commit.
- Commit messages end with the attribution lines the session provides.

## Already pinned — do not re-cover

- P5f: the per-role fetch set (`/hub/crew` for supervisor+, `/hub/admin` for techfm_oa+), background-vs-foreground failure isolation, the crew error copy, the socket and safety-timer refresh paths, the techfm_oa+ Priorities blank after a first load.
- P6a: the Dashboard body around the mounts; `hub-crew-mount` / `hub-admin-mount` presence per role.
- P2 (`workOrders/solo.test.js`): `openWorkOrdersFilteredByStatus` resetting every other filter, and the list request `loadWorkOrders` builds from the dropdowns. P6b asserts the hand-off, not the list.

## Entry gate

- [x] `npm test` green, run to completion: **1343 tests / 43 files, 123 s**. The P6a close recorded 191 s for the same suite; re-measured here as the parent plan asked, it is 123 s — the jump was run-to-run noise on this machine, not P6a's cost.

---

### Task 1: Row sub-shape factories and drift rows

**Files:** Modify `tests/frontend/helpers/factories.js` (after `hubAdmin`), `tests/frontend/unit/api.endpoints.test.js` (the drift table).

**Interfaces:** `hubCrewTechnician()` (`HubCrewTechnician`), `hubAttentionItem()` (`HubAttentionItem`), `hubOnClockEntry()` (`HubAdminOnClockEntry`). One wire row each, fields off `backend/app/schemas/hub.py`; `hubCrew({technicians: [hubCrewTechnician({…})]})` is how a card test names only the field under test. `hubCrew()`'s inline technician literal is replaced by a `hubCrewTechnician()` call so there is one shape, not two.

- [x] **Step 1:** Add the three factories; re-point `hubCrew()`'s `technicians` default at `hubCrewTechnician()`.
- [x] **Step 2:** Three drift rows after `["hubStockedRequest", …]`.
- [x] **Step 3:** `npx vitest run tests/frontend/unit/api.endpoints.test.js` — green, three more tests.
- [x] **Step 4:** Commit `test(p6b): crew technician, attention and on-clock row factories`.

---

### Task 2: `hubSupervisor.test.js`

**Files:** Create `tests/frontend/views/hubSupervisor.test.js`.

Local helpers: `board()` = `el.crewMount().querySelector(".hub-crew")`; `tilesIn(root)` in the `hubPriorities.test.js` form (label / value / sub); `cards()` = `el.crewMount().querySelectorAll(".hub-crew-card")`; `crewWith(tech, extra)` = `hubCrew({technicians: [hubCrewTechnician(tech)], ...extra})`.

- [x] **Roll-ups, supervisor:** `led {total: 4, in_progress: 2}`, `crew_on_clock: 2`, `crew_total: 5`, `crew_minutes_today: 185` → three tiles in order: `Work orders I lead` / `4` / `2 in progress`; `Crew on the clock` / `2 of 5` / no sub; `Crew time today` / `3 h 5 m` / `ticking`.
- [x] **Roll-ups, quiet crew:** `in_progress: 0` → no sub on the first tile; `crew_on_clock: 0` → `0 of 5` and no `ticking`.
- [x] **Roll-ups, techfm_oa:** `Crew on the clock` dropped — two tiles, `Work orders I lead` then `Crew time today`.
- [x] **Attention:** empty → no `.hub-attention`; two items → the label contains `Needs attention`, its tip is `hub.attention`, `.hub-tile-count` is `2`, and each row is `⚠` + `subject — detail` (`.hub-attention-row span:last-child`), the subject escaped.
- [x] **Card, on clock:** `running_session` started 75 min before the payload's `server_now` → `.hub-crew-card-on`, `.hub-crew-dot-on`, `ON CLOCK`, `.hub-crew-subject` `WO 7001`, `.hub-crew-running` `running 1 h 15 m`.
- [x] **Card, off clock:** no `.hub-crew-card-on`, `OFF CLOCK`, subject `Last worked <weekday h:mm>` computed in the test with the module's own `toLocaleString` options; `last_worked: null` → `Last worked Never`.
- [x] **Card, numbers:** `minutes_today: 120` → `Today` + `2 h 0 m` in the `<strong>`; `Assigned 3 · In-prog 1 · Ready 2`.
- [x] **Card, flags** (`it.each`): `["long_session", "approaching_cap", "assigned_idle"]` → `⚠ long session`, `⚠ approaching cap`, `⚠ idle`; `["weird_new_flag"]` → `⚠ weird new flag` (the snake-case fallback); `[]` → no `.hub-crew-flags`.
- [x] **Card, name:** both names blank → `Unknown`; `<b>Bob</b>` renders literally with no `<b>` node.
- [x] **No crew:** `technicians: []` → the `My crew` label, the "No one is currently routed to you." hint, no `.hub-crew-grid`.
- [x] **Through `openHub` (D16, both sides):** supervisor with `led.total: 0` → the board still renders (three tiles); techfm_oa with `led.total: 0` → `el.crewMount().innerHTML === ""`; techfm_oa with `led.total: 1` → the board, two tiles.

- [x] Run the file; commit `test(p6b): hubSupervisor — roll-ups, attention, the card matrix, the D16 absent board`.

---

### Task 3: `hubAdmin.test.js`

**Files:** Create `tests/frontend/views/hubAdmin.test.js`.

Local helpers: `summary()` = `el.adminMount()`; `rows(sel)` → text pairs from `.hub-exceptions-row` spans; `pipelineTiles()` → `[{status, label, value}]`; `handOff()` in the `hubTechnician.test.js` form (filter-options, `/items/`, `/users/`); `listQueries()` in the same form; `stubScroll()` in `beforeEach`. Role is `techfm_oa` unless the test says otherwise.

- [x] **On the clock, empty:** `Nobody is on the clock right now.`, `.hub-tile-count` `0`, no `.hub-onclock-list`; the label's tip is `hub.clock-attention`.
- [x] **On the clock, rows:** `technician_name`, subject `WO 7001 · Scholars`; `community: null` → `WO 7001`; `.hub-onclock-elapsed` starts with `formatHm(elapsed_minutes)` (95 → `1 h 35 m`); `flag: "long_session"` → a `.hub-attention-icon` reading `⚠ long session`; an unknown flag → `⚠ odd flag`; `flag: null` → no icon in that row. **Finding:** `hubAdmin.js`'s `FLAG_LABELS` omits `assigned_idle`, so the same domain flag reads `idle` on the crew board and `assigned idle` here — assert both and file it.
- [x] **Time tiles:** `Supervisor Time` and `Technician Time` through `formatHm`.
- [x] **Pipeline, shape:** six tiles in order, `data-status` = `created assigned in_progress ready_to_complete completed review`, each label equal to that value's `<option>` text read out of `backend/static/pages/work-orders.html` with `readFileSync` (the module's own drift claim), values off the payload. **Finding:** the page offers `on_hold`, which the pipeline has no tile for — file it.
- [x] **Pipeline, flag:** `ready_to_complete: 2` → a `⚠` in that tile's label only; `0` → none anywhere.
- [x] **Pipeline, click:** a tile click → `#work-orders-status-filter` is that status, `#work-orders-page` is active, and one `GET /work-orders/` carrying `status=review`.
- [x] **`pipelineBound` once-guard:** `connectHub()`, two `labor.session.changed` emits (each remounts the summary on the same node — `mountHubDashboard` is what replaces it, and nothing here rebuilds the tab), then one tile click → exactly one list request.
- [x] **Exceptions:** five rows in order — `Inventory recounts`, `Missing price / link`, `Catalogue requests` as `N open`; `Admin review queue`, `Stale > 3 days` bare.
- [x] **Billing:** `Materials` / `Labor` / `Total` through `formatMoney` (asserted by `/1,234\.50/`-style regex, as `unit/format.test.js` does), `.hub-billing-total` on the Total row; `avg_days_to_complete: null` → `—`, `3.4` → `3.4 d`; the sparkline `[0, 4, 8]` → `▁▄█`, all zeros → `▁▁▁`, `[]` → an empty span; `legacy_live_count: null` → five rows, `7` → a sixth `Legacy work orders live` / `7`.

- [x] Run the file; commit `test(p6b): hubAdmin — on-the-clock rows, the pipeline hand-off and once-guard, exceptions and billing`.

---

### Task 4: Findings, docs, parent plan

- [x] `docs/open-work.md` → `N-P6-CHARACTERIZED`: the two-vocabulary flag map; the missing `on_hold` pipeline tile; anything else the run surfaces.
- [x] `docs/current-state.md`: the Vitest bullet names the two new files; count / time updated.
- [x] Parent plan: tick the P6b bullets; suite-budget row `P6b | N / 45 | S s`.
- [x] `npm test` to completion; commit `docs: record P6b — the crew board and the admin summary`.

## Done when

- [x] Four commits, each green.
- [x] Both exports exercised: `mountHubCrew` and `mountHubAdminSummary`, each through `openHub` only — neither module has a branch the shell cannot reach, so nothing is called by name (parent deviation 5's second half stays unused).
- [x] Findings filed; docs updated.

## Deliberately not in P6b

- `userHub.js`'s own fetch / failure / refresh wiring (P5f).
- The Work Orders list the pipeline click lands on (P2).
- The Priorities card's crew and admin tiles (P6a).
- The lazy tabs (P6c) and everything after them.
