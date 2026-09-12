# Frontend Test Harness — P6c (`hubTimesheets.js` + `hubGraphs.js` + `hubReport.js`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task, **inline in the session — no subagents** (`CLAUDE.md` forbids them here). Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Status: go-ahead given 2026-09-11 ("Do the next step of p6"). Third P6 chunk.**

**Goal:** Characterization coverage for the three lazily fetched hub tabs — Timesheets (255 lines, the grid, its drill-down, week nav and CSV export), Graphs (189 lines, the two-level drill, the donuts, the duration chart, the Work Orders hand-off) and the Admin daily Report (264 lines, three sections over five payload sections, the row hand-offs, the skeleton and the retry) — plus the payload sub-shapes the three need.

**Architecture:** Tests only, on P5f's `helpers/hub.js`. Each tab is entered the way a user does: `openHub({role, timesheets | graphs | report})` then a click on `el.tab(name)`, which is what fires the lazy fetch. `userHub.js` owns every callback (`onWeekChange` → a re-fetch with the new range, `onTabChange` → a repaint from memory, `onDistributionClick` → `openWorkOrdersFilteredByDistribution` + `showPage`), so the callbacks are asserted at their far end — a request query, or the Work Orders page's own controls. Only `largestCommunityKey` and `destroyHubGraphs` are driven directly: both are pure (parent deviation 5).

**Tech Stack:** Vitest, jsdom, @testing-library/dom, @testing-library/user-event, msw.

**Spec:** `docs/superpowers/specs/2026-09-10-frontend-test-harness-design.md` §3.2–3.3; the report's own `docs/superpowers/specs/2026-08-30-work-order-daily-report-design.md`
**Parent plan:** `docs/superpowers/plans/2026-09-11-frontend-test-harness-p6.md` (P6c bullets are the requirement set)
**Depends on:** P6a/P6b (the hub fixture in anger), P5f (`helpers/hub.js`, `queries`), P2 (`filterOptions()`, the Work Orders filter controls), P0 (`stubObjectUrl`, `stubScroll`).

## Global constraints

- Tests only. No edit under `backend/static/` or `backend/app/`.
- Characterization, not correction. Findings → `docs/open-work.md` → `N-P6-CHARACTERIZED`.
- No `vi.mock` of any app module. Seams: `fetch` (MSW), fake timers, `URL.createObjectURL` (`stubObjectUrl`), `window.scrollTo` (`stubScroll`).
- `onUnhandledRequest: "error"` stays on. `/hub/timesheets/export` is not in the fixture's default set — every export test passes its own handler.
- **One `openHub` per test.** `setup.js` resets modules per test, so a second mount inside one test reuses that test's own instance, still bound to the first shell (P6b filed this).
- `afterEach`: `stopClock()`, `expect(vi.getTimerCount()).toBe(0)`, `restoreHub()`, `restoreBrowserStubs()`. The export path queues `setTimeout(revokeObjectURL, 0)`, so an export test flushes timers before the zero-timer check.
- Every date/time string is computed in the test with the module's own `Intl` options (UTC for the grid and report labels, `America/Chicago` for the session and generated stamps) — never typed as a literal.
- New factories get a drift row in `unit/api.endpoints.test.js` in the same commit.
- Commit messages end with the attribution lines the session provides.

## Already pinned — do not re-cover

- P5f: tab visibility per role, the lazy first fetch per tab, per-tab failure isolation, the timesheet retry inside `userHub.js`'s own error line, `report: 500` reaching the error render.
- P2: the Work Orders list and its filter controls' own behaviour; `openWorkOrdersByNumberSearch` / `openWorkOrdersFilteredByDistribution` resetting every other filter.
- P6b: the pipeline hand-off (this chunk asserts the Graphs and Report hand-offs, which take different entry points).

## Entry gate

- [x] `npm test` green (P6b close: 1382 / 45, 123 s).

---

### Task 1: Payload sub-shape factories and drift rows

**Files:** Modify `tests/frontend/helpers/factories.js`, `tests/frontend/unit/api.endpoints.test.js`.

**Interfaces:** `hubTimesheetDay()`, `hubTimesheetRow()`, `hubTimesheetDayTotal()`, `hubGraphDistribution()`, `hubGraphCommunity()`, `hubGraphBucket()`, `hubReport()`, `hubReportRow()` — fields off `backend/app/schemas/hub.py` (`total_minutes` is a computed field and is on the wire, so it is in `hubTimesheetDay()`). `hubTimesheets()`'s and `hubGraphs()`'s inline row/community literals are re-pointed at the new factories, as P6b did for the crew technician.

- [x] **Step 1:** Add the eight factories; re-point the two inline literals.
- [x] **Step 2:** Eight drift rows.
- [x] **Step 3:** `npx vitest run tests/frontend/unit/api.endpoints.test.js` — green, eight more tests.
- [x] **Step 4:** Commit `test(p6c): timesheet, graph and report payload factories`.

---

### Task 2: `hubTimesheets.test.js`

**Files:** Create `tests/frontend/views/hubTimesheets.test.js`.

Entry: `openHub({role: "supervisor", timesheets})` → `await user().click(el.tab("timesheets"))` → the panel is `el.panel("timesheets")`. Local helpers: `openSheet(timesheets, role)`; `headerCells()`; `bodyRow(n)`; `cell(row, dateIso)`; `footerCells()`; `message()` = `.hub-timesheet-message`; `utcShort(iso)` / `utcLong(iso)` / `central(iso)` computing the module's own labels.

- [x] **Grid shape:** one header cell per `crew_totals_by_day` date in UTC short form, plus `Technician` and `Total`; a row per `rows` entry with `userName` (`Unknown` when both names are blank); a date the row has no `days` entry for renders `0:00`; row total, footer per-day totals, and the grand total as the sum of `crew_totals_by_day`.
- [x] **Flags:** `running` → `●` with the sr-only "running"; `assigned_idle` → `⚠ assigned but idle`; an unmapped flag → `⚠` plus its snake-case words; the cell's `aria-label` carries name, long date, total and the flag labels.
- [x] **Scope copy:** supervisor → `Crew total`, the `Crew timesheets for <start> through <end>` caption, and the routed-to-you empty hint when `rows: []`; techfm_oa (through `openHub`) → `Company total`, `Company …` caption, `No live Supervisors or Technicians to show.`
- [x] **Drill-down:** a cell click renders `.hub-timesheet-drilldown` in a `colspan = dates + 2` row — heading `name · <long date>` and `h:mm total`, a row per session (`start – end · Work order n`, `running` when `ended_at` is null, `⚠ estimate` when `auto_closed`), the `Charged` subtotal from `tracked_minutes`, a row per adjustment, the `Total` row; `aria-expanded` / `aria-controls` on the button; a second click collapses it; clicking a different cell in the same row moves it; a day with neither sessions nor adjustments shows the no-detail hint.
- [x] **Week nav:** `◀` → `onWeekChange(start − 7, end − 7)` → `GET /hub/timesheets` with those exact ISO dates; `▶` → `+7`; the range label reads both dates in UTC.
- [x] **Export:** `Export CSV` → `GET /hub/timesheets/export?start&end` under `stubObjectUrl()`; `Preparing export…` then `Exported <filename>.` with the `success` class, the filename from `Content-Disposition`, falling back to `timesheet.csv` when the header is absent; the button is disabled while in flight and re-enabled after; a 500 → `friendlyError` with the `error` class and the button re-enabled. Flush the queued `revokeObjectURL` timer before the zero-timer check.
- [x] **Finding to file:** the module's private `formatHm` renders `h:mm` while `format.js`'s export of the same name renders `N h M m` — two different renderings under one name, and the hub shows both on one screen.

- [x] Run the file; commit `test(p6c): hubTimesheets — the grid, flags, the drill-down, week nav, CSV export`.

---

### Task 3: `hubGraphs.test.js`

**Files:** Create `tests/frontend/views/hubGraphs.test.js`.

Entry: `openHub({role: "techfm_oa", graphs})` → click `el.tab("graphs")` → `el.panel("graphs")`. `stubScroll()` in `beforeEach` for the hand-off test.

- [x] **`largestCommunityKey`** (direct import): the largest wins; a tie takes the payload's first; `communities: []` → null; a missing `communities` key → null.
- [x] **Community donut:** `total: 0` → the `role="img"` empty block reading `No circulating work orders` and no `<path>`; otherwise one `path.hub-graph-slice` per status with `count > 0`, each carrying `data-status`, in payload status order, and the `.hub-donut-total` badge reading the total.
- [x] **Legend:** one row per status even at zero, `n · p%` with one decimal, `0.0%` on an empty total; `View all N`.
- [x] **Tabs:** a community tab per community labelled `label (total)`, the active one carrying `active` and `aria-selected="true"`; the two inner tabs (`Service Type`, `Priority`) with `service_type` active by default; a community tab click re-renders from memory — the new community's card is shown and **no** `/hub/graphs` request fires.
- [x] **Inner grid:** a card per `service_types` row carrying `data-community` + `data-service-type` with the raw label; after a Priority tab click, `data-priority`; the empty reasons — priority with `total > 0` → `No imported priorities in this community`, priority with `total: 0` and service type always → `No circulating work orders`.
- [x] **Duration:** no non-null samples → `No duration samples in this range.` and no `<svg class="hub-duration-chart">`; a null bucket splits the series into two `polyline`s (asserted per class: age and close); the details table rows read `start – end`, `(partial)` when set, `No sample` for a null average and `N.NN days (n=K)` otherwise.
- [x] **Range select:** the `<option>` matching `payload.weeks` is selected; a change to `26` → `onWeekChange(26)` → `GET /hub/graphs?weeks=26` (the value reaches the query as a number).
- [x] **Hand-off:** a slice click, a legend-row click and a `View all` click each → `showPage("work-orders")` with `#work-orders-page` active; the status reaches `#work-orders-status-filter` (its `<option>`s are hard-coded in the page). **Verify and file:** the community / service-type / priority values are set before `loadFilterOptions()` has ever run for that session, so the dynamic `<select>`s have no matching `<option>` yet and the value is dropped — every role lands on User Hub (`LANDING_PAGE_BY_ROLE`), so this is the normal path, not an edge case. Assert what actually happens, in both the selects and the list request query.
- [x] **`distributionClickBound`:** a community tab click then a slice click still yields exactly one page swap's worth of list requests; `destroyHubGraphs()` called by name (a no-op that must not throw).

- [x] Run the file; commit `test(p6c): hubGraphs — donuts, the two-level drill, duration, the Work Orders hand-off`.

---

### Task 4: `hubReport.test.js`

**Files:** Create `tests/frontend/views/hubReport.test.js`.

Entry: `openHub({role: "admin", report: hubReport({…})})` → click `el.tab("report")`. `stubScroll()` in `beforeEach`.

- [x] **Header:** `Week of <short> – <short>` (UTC), the long day label, `Generated <Central stamp>`, and the `/hub/report/export` download link.
- [x] **Closed:** `Today` and `This week` counts from `count` (never from row counts); the week rows in the table with the `Closed` timestamp column from `archived_at` in Central; a row whose number is in `closed_today.rows` carries the `Today` badge and one with `legacy: true` the `Legacy` badge; `rows: []` → `Nothing closed yet today.`; the footnote.
- [x] **Row cells:** `placeLabel` — community · building-unit · location, the `—` when all are null; `service_type` / `supervisor_name` `—` fallbacks; `technician_names` joined, `—` when empty; `statusLabel` mapping (`in_progress` → `In progress`) and the raw status for an unmapped one; a null timestamp → `—`.
- [x] **Closing:** the `In the pipeline` count; the `by_status` breakdown in lifecycle order skipping zeros (`ready to complete N · completed N · review N`); `truncated: true` → the notice, absent otherwise; the `Created` column from `created_at`; the empty copy.
- [x] **New:** counts and week rows as Closed, `Created` column, `Nothing new has arrived today.`
- [x] **Row buttons:** an archived row → `openWorkOrdersByNumberSearch(number)` + `showPage` — assert `#work-orders-search` holds the number and the list request carries `q`; a live row → `focusWorkOrderNumber` + `showPage` — assert the page swap and the `?q=<number>` list request (P2 owns the archived prompt itself).
- [x] **Skeleton and retry:** with the fetch still in flight, the panel reads `Loading the daily report…`; `report: 500` → the error copy from `friendlyError` and a `Retry` button; swapping in a passing handler and clicking Retry renders the report (both `renderReportSkeleton` and `renderReportError` reached by name through the shell).

- [x] Run the file; commit `test(p6c): hubReport — the three sections, row hand-offs, skeleton and retry`.

---

### Task 5: Findings, docs, parent plan

- [x] `docs/open-work.md` → `N-P6-CHARACTERIZED`: the two `formatHm`s; the Graphs hand-off dropping its dynamic filters on a cold Work Orders page; anything else the run surfaces.
- [x] `docs/current-state.md`: the Vitest bullet names the three files (and the User Hub Graphs / Report rows in the coverage table name their tests, which the parent plan's "Done when" asks for); count / time updated.
- [x] Parent plan: tick the P6c bullets; suite-budget row `P6c | N / 48 | S s`.
- [x] `npm test` to completion; commit `docs: record P6c — the lazy hub tabs`.

## Done when

- [x] Five commits, each green.
- [x] Every export exercised: `mountHubTimesheets`, `mountHubGraphs`, `largestCommunityKey`, `destroyHubGraphs`, `mountHubReport`, `renderReportSkeleton`, `renderReportError`.
- [x] Findings filed; docs updated.

## Deliberately not in P6c

- `userHub.js`'s own tab shell, lazy-fetch wiring and failure isolation (P5f).
- The Work Orders list the hand-offs land on, and the archived-restore prompt (P2).
- The XLSX export's contents (backend tests own it; the page only carries the link).
- P6d–P6g.
