# Frontend Test Harness — P6a (`hubClock.js` + `hubTechnician.js` + `hubPriorities.js`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task, **inline in the session — no subagents** (`CLAUDE.md` forbids them here). Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Status: go-ahead given 2026-09-11 ("gogo"). First P6 chunk.**

**Goal:** Characterization coverage for the three views that render the personal `GET /hub` payload — the clock widget (206 lines), the Dashboard and My Work Orders tabs (252), the Priorities card (64) — plus the six sub-shape factories `hubPayload()` defaults to empty.

**Architecture:** Tests only, on P5f's `helpers/hub.js`. Every test is `openHub({role, hub: hubPayload({…})})` and assertions on the roots the three modules paint (`el.clockMount()`, `el.panel("dashboard")`, `el.panel("work-orders")`, `el.prioritiesMount()`). Fake timers are already on (the hub rule); the clock's tick and warnings are driven with `vi.advanceTimersByTime`. Where `userHub.js` gates a branch away, the renderer is called directly after `mountHub()` (parent deviation 5).

**Tech Stack:** Vitest, jsdom, @testing-library/user-event, msw.

**Spec:** `docs/superpowers/specs/2026-09-10-frontend-test-harness-design.md` §3.2–3.3
**Parent plan:** `docs/superpowers/plans/2026-09-11-frontend-test-harness-p6.md` (P6a bullets are the requirement set)
**Depends on:** P5f (`helpers/hub.js`, `hubPayload()`), P2 (`workOrderCard()`, `workOrderDetail()`, `filterOptions()`), P5d (`helpers/requests.js`).

## Global constraints

- Tests only. No edit under `backend/static/` or `backend/app/`.
- Characterization, not correction.
- No `vi.mock` of any app module. Seams: `fetch` (MSW), fake timers, `document` events, `window.scrollTo` (`stubScroll`).
- `onUnhandledRequest: "error"` stays on. The Work Orders hand-off fires the reference loads and the number search; `handOff()` below answers all of them.
- `afterEach`: `stopClock()`, `expect(vi.getTimerCount()).toBe(0)`, `restoreHub()`, `restoreBrowserStubs()`.
- Six new factories each get a drift row in `unit/api.endpoints.test.js`; `hubPayload` itself gains one (it never had one).
- Commit messages end with the attribution lines the session provides.

## Already pinned by P5f — do not re-cover

- The capped-list query per role (`limit=10`, `mine=true` for a supervisor only).
- Start button → `POST …/tracking/start` → a second `GET /hub` (the hand-off through `onChanged`).
- The techfm_oa+ Priorities card blank after the first load.
- Per-tab failure isolation, the safety interval, the visibility lifecycle.

## Entry gate

- [x] `npm test` green (1286 / 40, 112 s at the P6 plan).
- [x] P6 parent plan and roadmap drift committed (`9c45f1e`, `d35410f`).

---

### Task 1: Sub-shape factories and drift rows

**Files:**
- Modify: `tests/frontend/helpers/factories.js` (after `hubPayload`)
- Modify: `tests/frontend/unit/api.endpoints.test.js` (the `it.each` table)

**Interfaces:** produces `hubRunningSession()`, `hubAdjustment()`, `hubTimelineEntry()`, `hubStartable()`, `hubToolOut()`, `hubStockedRequest()` — one wire row each, fields read off `backend/app/schemas/hub.py`.

- [x] **Step 1:** Add the six factories:

```js
// --- Hub sub-shapes (backend/app/schemas/hub.py) ----------------------------
// The rows hubPayload() defaults to empty lists or null. One wire row each;
// a test passes them through hubPayload({ timeline: [hubTimelineEntry()] }).
export function hubRunningSession(overrides = {}) {
  return {
    work_order_id: uuid(), number: "7001",
    started_at: "2026-09-10T11:00:00Z", day_counting_from: "2026-09-10T11:00:00Z",
    ...overrides,
  };
}
export function hubAdjustment(overrides = {}) {
  return { minutes: 30, recorded_by_name: "Sue Super", work_order_number: "7001", ...overrides };
}
export function hubTimelineEntry(overrides = {}) {
  return {
    work_order_id: uuid(), number: "7001", started_at: "2026-09-10T13:00:00Z",
    ended_at: "2026-09-10T14:00:00Z", auto_closed: false, minutes: 60,
    ...overrides,
  };
}
export function hubStartable(overrides = {}) {
  return {
    work_order_id: uuid(), number: "7001", status: "assigned",
    community: null, building_number: null, unit_number: null, location: null,
    ...overrides,
  };
}
export function hubToolOut(overrides = {}) {
  return { tool_id: uuid(), name: "Drill", barcode: "T1", quantity: "1", since: "2026-09-08T12:00:00Z", ...overrides };
}
export function hubStockedRequest(overrides = {}) {
  return {
    request_id: uuid(), item_name: "Bulb", work_order_id: uuid(), work_order_number: "7001",
    quantity: "2", stocked_at: "2026-09-10T11:30:00Z",
    ...overrides,
  };
}
```

- [x] **Step 2:** Add seven rows to the drift table, after `["hubGraphs", …]`: `hubPayload`, `hubRunningSession`, `hubAdjustment`, `hubTimelineEntry`, `hubStartable`, `hubToolOut`, `hubStockedRequest`, all against `backend/app/schemas/hub.py`.
- [x] **Step 3:** `npx vitest run tests/frontend/unit/api.endpoints.test.js` — green, seven more tests.
- [x] **Step 4:** Commit `test(p6a): hub sub-shape factories with drift rows`.

---

### Task 2: `hubClock.test.js`

**Files:** Create `tests/frontend/views/hubClock.test.js`.

Helpers local to the file: `minus(iso, minutes)` (an ISO string `minutes` before `iso`), `onClock(startedMinutesAgo, extra)` (a `hubPayload()` whose `clock.running_session` is `hubRunningSession({ started_at: minus(server_now, n) })`), `clock()` = `el.clockMount().querySelector(".hub-clock")`, `message()` = `#hub-clock-message`.

- [x] **Off clock:** `hubPayload({ clock: { …, total: 95 } })` → status contains "Not clocked in"; `.hub-clock-today` contains "1 h 35 m"; no startable → the "Nothing assigned…" hint and no `.hub-clock-start-btn`; advancing 60 s changes nothing (tick is a no-op off clock).
- [x] **Start label table** (`it.each`): `{community: "Scholars", building_number: "3", unit_number: "12"}` → `Track WO 7001 — Scholars · Bldg 3 · Unit 12`; `{location: "Roof"}` → `Track WO 7001 — Roof`; all null → `Track WO 7001`; two startables → one button, the first's number and `data-value` = its `work_order_id`.
- [x] **Start failure:** `POST /work-orders/:id/tracking/start` → `{detail: "Clock is locked"}` 500 → `#hub-clock-message` reads that detail with class `error`; no `GET /hub` follows (clear requests before the click).
- [x] **On clock render:** started 75 min before `server_now` → "ON THE CLOCK", `.hub-clock-subject` "WO 7001", hero "1 h 15 m", `.hub-clock-started` = `"started " + new Date(started_at).toLocaleTimeString([], {hour: "numeric", minute: "2-digit"})`, a Stop button with `data-action="hub-clock-stop"`, no `.hub-clock-warning`.
- [x] **Stop:** click → `POST /work-orders/{work_order_id}/tracking/stop` with body `{}` → a `GET /hub`; failure (`{detail: "Nope"}` 500) → the detail in the message, no refetch.
- [x] **Tick:** `vi.advanceTimersByTime(60_000)` → hero "1 h 16 m"; `stopClock()` then another 60 s → unchanged.
- [x] **8 h warning by tick:** started 479 min ago, no warning; +60 s → `.hub-clock-warning` "Still on the clock after 8 h" and the hero "8 h 0 m" (the one-time re-render).
- [x] **Cap warning is NOT reached by tick** (characterization, file it): started 659 min ago → the 8 h text; +60 s → still the 8 h text, because `tick()` re-renders only when a warning appears or disappears. A fresh `openHub` at 660 renders the cap text ("At 12 h this session is capped").
- [x] **Once-guard:** `openHub` on clock, then `mod.loadUserHub()` again (same container, `dataset.wired` set), one Stop click → exactly one `POST …/tracking/stop`.

- [x] Run the file; commit `test(p6a): hubClock — off/on render, start and stop, tick, warnings, once-guard`.

---

### Task 3: `hubTechnician.test.js`

**Files:** Create `tests/frontend/views/hubTechnician.test.js`.

Local helpers:

```js
// hubTechnician.js does its timeline math in LOCAL time (getHours), so the
// fixtures are built from local components and serialised, never typed as Z.
const local = (h, m = 0) => new Date(2026, 8, 10, h, m).toISOString();
const dash = () => el.panel("dashboard");
// Everything a card click / stocked-request click fires once showPage("work-orders")
// consumes the pending number: the reference lists, the number search (already
// answered by mountHub's /work-orders/ handler), the detail and its requests strip.
// filter-options precedes :id because :id matches any segment.
const handOff = () => [
  http.get("/work-orders/filter-options", () => HttpResponse.json(filterOptions())),
  http.get("/items/", () => HttpResponse.json([])),
  http.get("/users/", () => HttpResponse.json([])),
  http.get("/work-orders/:id/requests", () => HttpResponse.json([])),
  http.get("/work-orders/:id", () => HttpResponse.json(workOrderDetail({ number: "7001" }))),
];
```

`stubScroll()` in `beforeEach` (the page swap scrolls); `restoreBrowserStubs()` in `afterEach`.

- [x] **Counts tiles:** three `.hub-tile`s in order with labels "Assigned to me" (sub "work orders"), "In progress" (no sub), "Ready to complete" (sub "waiting on supervisor" only when `> 0`, asserted both ways).
- [x] **Time today:** hero = `formatHm(total_minutes_today)`; "Charged" = `formatHm(closed + running)`; `.hub-running-badge` iff a running session; one `.hub-adjustment-line` per adjustment containing "30 m", "recorded by Sue Super", "WO 7001".
- [x] **Timeline, empty:** no entries and no running session → the "No time charged yet today" hint, no `.hub-timeline`; a running session with no entries → a `.hub-timeline` with an axis and zero blocks.
- [x] **Timeline range and axis:** `server_now: local(12)`, one entry `local(9)`–60 min → labels `8a … 12p … 5p` (ten); an entry at `local(6, 30)` → the first label is `6a`; `server_now: local(19, 15)` → the last label is `8p`.
- [x] **Blocks:** `style.left` / `style.width` equal `${((540 - 480) / 540) * 100}%` (computed the same way in the test); a 1-minute entry → width `0.5%`; `ended_at: null` → class `hub-timeline-block-running` and text "7001 (running)"; `title` contains "WO 7001 — 1 h 0 m" and, with `auto_closed: true`, "(auto-closed estimate)".
- [x] **Tools out:** empty → the "No tools currently checked out." hint; two rows → `.hub-tile-count` "2", each `li` with the name and `since <weekday m/d>` computed with the same `toLocaleDateString` options; `since: null` → the span reads "since " (empty date — file it as cosmetic).
- [x] **Stocked requests:** empty → no `.hub-stocked-requests`; one row → `.hub-stocked-item` "Bulb", the `.hub-stocked-wo` button text "7001", the hint "requested 2 · stocked …" (and only "requested 2" when `stocked_at` is null); the item name is escaped. Click (with `handOff()`) → `#work-orders-page` active and `requestFor("/work-orders/?q=7001")` not null.
- [x] **techfm_oa+:** no `.hub-time-today`, no `.hub-tools-out`; `#hub-priorities-mount`, `#hub-admin-mount`, `#hub-crew-mount` present for both a technician and an admin.
- [x] **My Work Orders tab** (`workOrders: [workOrderCard({ number: "7001" })]`, `handOff()`): a card's `summary.wo-summary` click → `#work-orders-page` active and the `?q=7001` search; "View all" → the page active and the last `/work-orders/` query carries no `q`; with the tab open, `vi.advanceTimersByTimeAsync(60_000)` → one more `/work-orders/` request with `{limit: "10"}` (`refreshHubWorkOrders` on the personal refresh).

- [x] Run the file; commit `test(p6a): hubTechnician — dashboard tiles, timeline math, tools out, stocked requests, work-orders tab hand-offs`.

---

### Task 4: `hubPriorities.test.js`

**Files:** Create `tests/frontend/views/hubPriorities.test.js`.

- [x] **Through `openHub`:** technician → one tile "High priority — assigned to you" = `personal.assigned`; supervisor → "High priority — your crew" = `crew.priority.assigned` and "High priority — unassigned" = `crew.priority.unassigned`; techfm_oa after a dashboard tab click → "High priority — company-wide" from `admin.priority`; the label carries the `hub.priorities` tip button.
- [x] **Missing source through `openHub`:** supervisor with `crew: 500` → `el.prioritiesMount().innerHTML === ""`.
- [x] **Direct table** (`importView("views/hubPriorities.js")` after `mountHub()`, mounting into `el.prioritiesMount()`): `unassigned: 0` → no `.hub-tile-sub`; `3` → "needs a technician"; `personal` / `crew` / `admin` null for its role → empty; `owner` uses `admin`; a null container → no throw.

- [x] Run the file; commit `test(p6a): hubPriorities — the three role shapes, the missing-payload blank`.

---

### Task 5: Findings, docs, parent plan

- [x] `docs/open-work.md`: new heading `N-P6-CHARACTERIZED` under §2 in the P5 table form, first rows: the cap warning unreachable by tick; the empty "since " on a tool with no `since`; anything else the run surfaced.
- [x] `docs/current-state.md`: the Vitest bullet gains the three files after the `userHub.js` clause; count / time updated.
- [x] Parent plan: tick the P6a bullets; suite-budget row `P6a | N / 43 | S s`.
- [x] `npm test` to completion; commit `docs: record P6a — clock, dashboard and priorities coverage`.

## Done when

- [x] Four commits, each green.
- [x] Every export of the three modules called by name: `mountHubClock`, `stopHubClockTicking`, `startHubClockTicking` (through the shell), `mountHubDashboard`, `mountHubWorkOrders`, `refreshHubWorkOrders`, `mountHubPriorities`.
- [x] Findings filed; docs updated.

## Deliberately not in P6a

- `hubSupervisor.js` / `hubAdmin.js` internals (P6b) — this chunk only asserts their mounts exist.
- The list mount's own empty / error / locked-filter behaviour (P2, `filters.test.js` → "mountWorkOrderList").
- The card page that opens after the hand-off (P2 solo tests); only the page swap and the number search are asserted here.
