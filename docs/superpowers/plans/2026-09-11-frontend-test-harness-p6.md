# Frontend Test Harness — P6 (Medium-churn views) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan chunk-by-chunk, **inline in the session — no subagents** (`CLAUDE.md` forbids them here). Each chunk gets its own plan file (`2026-09-11-frontend-test-harness-p6<x>-<module>.md`) written at the start of its session, as P5b–P5h did; this file is the requirement set those plans argue from. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Component coverage for the twenty medium-churn view modules the roadmap assigns P6 — the eight `hub*.js` sub-modules, `tools.js` with its three custody editors, `users.js`, the four Saved Items sub-flow panels with the panel helper they share, `push.js`, and `subnav.js` (3,738 lines, 95 commits between them). `billingEditor.js` is struck; see deviation 2.

**Architecture:** Tests only, on the P0 harness and the P5 fixtures. P5's problem was the spine; P6's is the opposite — **these modules are leaves that a P5 module composes**. Every hub sub-module is a `(container, payload)` renderer that `userHub.js` calls with a payload it already fetched; every Saved Items panel opens from an `items.js` row action; `push.js` is entered from `auth.js`; the custody editors are entered from `tools.js`. So P6 builds one new fixture (`helpers/tools.js`) and otherwise mounts through P5's — `helpers/hub.js` (`openHub`), `helpers/items.js` (`mountItems`), `helpers/media.js` (`stubPush`) — and asserts the leaf's own branches, which P5 deliberately left at "the panel opened" / "the root rendered".

**Tech Stack:** Vitest, jsdom, @testing-library/dom, @testing-library/user-event, msw.

**Spec:** `docs/superpowers/specs/2026-09-10-frontend-test-harness-design.md` §3.2–3.3
**Roadmap:** `docs/superpowers/plans/2026-09-10-frontend-test-harness-roadmap.md` (P6)
**Depends on:** P0–P5, all landed. P5f's `helpers/hub.js`, P5c's `helpers/items.js`, P5b's `stubPush`, P5h's `helpers/actionAudit.js`, P5d's `helpers/requests.js` + `helpers/dialogs.js`.

## Entry gate — verify before P6a

P5 closed 2026-09-11 (`688af61`). Measured for this plan, same day:

- [x] `npm test` green, run to completion: **1286 tests / 40 files, 112 s** (P5 close recorded ~135 s; a 20 % run-to-run swing is normal on this machine). That is the budget this phase spends against.
- [ ] `pytest -m e2e` green (asserted at P5 close from a local run; re-run before P6a).
- [ ] No other session is mid-commit in this checkout. Two writers in `tests/frontend/helpers/` will collide.

## Global constraints

- **Tests only.** No change to any file under `backend/static/` or `backend/app/`. If a test cannot be written without a production change, stop and raise it.
- **Characterization, not correction.** Assert what the code does; comment the assertion where that looks wrong; file it in `docs/open-work.md` under `N-P6-CHARACTERIZED` at the chunk's close. No fixes.
- **No `vi.mock` of any app module.** Seams: `fetch` (MSW), `WebSocket` (fake class), timers, browser globals (`stubPush`, `stubObjectUrl`, `stubScrollIntoView`), the shell's real dialog overlays.
- **`onUnhandledRequest: "error"` stays on.**
- **`mountView()` / `mountHub()` / `mountItems()` before any import.** All twenty modules capture element ids or mount scanners at import.
- **Hub rule carries over:** every hub test runs on fake timers and asserts `vi.getTimerCount()` is 0 in `afterEach` (`stopClock()` in `restoreHub()`).
- **Factories, not literals.** Any new payload shape is a factory in `helpers/factories.js` with a drift row in `unit/api.endpoints.test.js` ("factories match the schemas they stand in for"), added in the same commit.
- **One chunk, one session, one green suite.** A chunk is done when `npm test` is green, its own success check passes, and its findings are filed.
- Commit messages end with the attribution lines the session provides.

## Eight deviations from the roadmap text, decided here

1. **P6 is seven chunks.** The roadmap's P6 is one section over twenty-one files; the standing rule (preamble, filed by P5's D1) makes the chunk the unit of work. Three chunks are the hub — same fixture, same factory file, no reason to interleave them with anything else.
2. **`billingEditor.js` is struck.** P5e drove its Save / Don't charge / Cancel for real through History (P5 deviation 8) and recorded that P6 must not re-cover it. Nothing here touches it.
3. **`subnav.js` gets a unit file, inside the tools chunk.** History (P5e), Items (P5c) and Tools (P6e) all drive it; what is left is its own contract (initial selection, `fireInitialOnShow`, idempotence, a page with no `.sub-nav`), which is 75 lines of DOM-only code and belongs in `tests/frontend/unit/`.
4. **`correctionPanel.js` is covered once, through `correction.js`.** The panel's validation ladder, submit, `onSaved`, auto-close and failure path are pinned in P6d against the Saved Items host (`POST /transactions/adjust`). `toolCorrection.js` (P6e) asserts only its wiring: the `tool-correction-*` ids, `POST /tools/{id}/adjust`, and the refresh.
5. **Hub renderers may be called directly after `mountHub()`.** `userHub.js` gates which payload reaches which renderer (a crew board absent for an admin+ viewer with `led.total` 0; a Priorities card blank until `/hub/admin` lands; `isAdminPlus` flags), so several branches are unreachable through `openHub` in one call. Rule: every export is reached through `openHub` at least once (the wiring), and pure `(container, payload, options)` variants may then be driven directly for branch coverage. This is not a module mock — the real module runs against the real shell.
6. **No action audit for the hub modules.** They have three single-wired buttons between them, and `hubTechnician.js`'s `querySelector('[data-action="…"]')` would register as a rendered orphan under the audit's regex. Audits go where delegation tables are: `tools.js` (option values, the Items pattern) and `users.js` (class-name delegation — the roadmap's "delegated-action views" wording assumed `data-action`; `auditActions` takes custom patterns for exactly this).
7. **`push.js` is mounted directly, not through `helpers/auth.js`.** P5b pinned the two entry points (`requestPermissionAtLogin` before the login request; `initPushForUser` after `enterApp`; `unsubscribeThisDevice` on logout). The module's own branches — key rotation, the shared-device re-POST, swallowed failures, the Owner's test button — need `initPushForUser()` called with a chosen `stubPush` state, and the auth fixture clears `requests()` after boot.
8. **`tools.js` cannot be the entry point of its own module graph.** Same cycle P5c hit: `tools → scan → transactions → nav → tools`, with `nav.js` reading `toolsScanner` (a `const`) before `tools.js` finishes evaluating. `helpers/tools.js` primes through `mountView("views/nav.js")` then `importView("views/tools.js")`, as `helpers/items.js` does.

## Chunk sequencing

Churn order, with the hub trio kept contiguous (one fixture, one factory file) and the panel helper's owner (P6d) ahead of its second consumer (P6e).

| Chunk | Module(s) | Lines | Commits | Why here |
| --- | --- | --- | --- | --- |
| P6a | `hubClock.js` + `hubTechnician.js` + `hubPriorities.js` | 522 | 20 | The personal `GET /hub` payload end to end; highest churn in the phase; fixture ready. |
| P6b | `hubSupervisor.js` + `hubAdmin.js` | 314 | 12 | The crew and admin payloads that paint into P6a's mounts. Short; may share a session with P6a. |
| P6c | `hubTimesheets.js` + `hubGraphs.js` + `hubReport.js` | 708 | 11 | The lazily fetched tabs; adds the `hubReport()` factory P5f deferred. |
| P6d | `notes.js` + `itemEditor.js` + `addBarcode.js` + `correction.js` + `correctionPanel.js` | 644 | 20 | Opens through `mountItems()`; owns the panel helper (deviation 4). |
| P6e | `tools.js` + `toolCheckout.js` + `toolReturn.js` + `toolCorrection.js` + `subnav.js` + `helpers/tools.js` + the tools audit | 1,044 | 19 | The largest module left in the app (P5's D8: a full session of its own). |
| P6f | `users.js` + the users audit + three dialog answer helpers | 329 | 10 | Five class-name actions over the real prompt overlays. |
| P6g | `push.js` | 177 | 3 | Smallest; last. |

---

### P6a — the personal hub payload

**Files.** Create `tests/frontend/views/hubClock.test.js`, `tests/frontend/views/hubTechnician.test.js`, `tests/frontend/views/hubPriorities.test.js`. Modify `tests/frontend/helpers/factories.js` (`hubRunningSession()`, `hubTimelineEntry()`, `hubAdjustment()`, `hubStartable()`, `hubToolOut()`, `hubStockedRequest()` — the sub-shapes of `HubResponse` that `hubPayload()` defaults to empty; drift rows for each), `tests/frontend/helpers/hub.js` (getters for the clock, dashboard and work-orders roots as needed).

- [x] **Clock, off:** "Not clocked in", the Today total, and a Track button labelled from `startable[0]` — `WO n — community · Bldg b · Unit u`, the `location` fallback, the bare number — or the "Nothing assigned…" hint when `startable` is empty. Start → `POST /work-orders/{id}/tracking/start` `{}` → `onChanged` → `refreshUserHub` → a second `GET /hub`; a failing start writes `friendlyError` into `#hub-clock-message` and fetches nothing.
- [x] **Clock, on:** "ON THE CLOCK", the WO subject, "started h:mm", a hero computed from `server_now − started_at` (skew: `vi.setSystemTime` well away from the payload's `server_now`), Stop → `…/tracking/stop`. The 1 s tick moves the hero on fake timers; crossing 480 min inserts the 8 h warning by a one-time re-render; crossing 660 does **not** swap it for the cap warning — `tick()` re-renders only when a warning appears or disappears, so the cap text is reachable only through a fresh mount (file it). `dataset.wired` once-guard: two `loadUserHub()` calls, one Stop click, one request. A tick after `stopClock()` leaves the hero alone.
- [x] **Dashboard, technician:** the three count tiles with the "waiting on supervisor" sub only when non-zero; Time today hero, "Charged" line, the running badge; adjustment lines; the timeline — the empty hint when no entries and no running session; range `min(8 am, earliest start)` to `max(5 pm, now)` with the 60-min floor; 12-hour axis labels with `a`/`p`; block `left`/`width` applied through CSSOM (read `style.left`), the 0.5 % width floor, the running class and "(running)" label, the auto-closed title suffix. Tools out: the empty copy, else rows with the weekday `since`. Stocked requests: omitted when empty; rows whose WO button calls `focusWorkOrderNumber` then `showPage("work-orders")` — assert at the boundary as P5f did.
- [x] **Dashboard, techfm_oa+:** no Time today, no Tools out; `#hub-priorities-mount`, `#hub-admin-mount`, `#hub-crew-mount` present regardless of role.
- [x] **My Work Orders:** `mountWorkOrderList` fires `GET /work-orders/` with `limit=10`, plus `mine=true` for a supervisor only; "View all" → `showPage`; a card open → `focusWorkOrderNumber` + `showPage`; `refreshHubWorkOrders` refetches on the personal refresh (P5f pinned the repaint; here the extra list request).
- [x] **Priorities:** technician one tile from `personal`; supervisor two tiles from `crew` ("your crew"); techfm_oa+ two from `admin` ("company-wide"); "needs a technician" sub only when `unassigned > 0`; a missing source payload empties the mount — through `openHub` with `crew: 500` for a supervisor, and the P5-characterized techfm_oa+ first-load blank; the shape table by direct `mountHubPriorities(container, {…})` (deviation 5).

**Test.** `npm test` green; every new factory has a drift row; timers 0 in every `afterEach`.

---

### P6b — the crew board and the admin summary

**Files.** Create `tests/frontend/views/hubSupervisor.test.js`, `tests/frontend/views/hubAdmin.test.js`. Modify `helpers/factories.js` only if a technician-card or on-clock-row sub-factory earns it (`hubCrew()` / `hubAdmin()` are already guarded).

- [x] **Roll-ups:** "Work orders I lead" with the in-progress sub; "Crew on the clock" present for a supervisor, dropped under `isAdminPlus`; "Crew time today" with "ticking" only when `crew_on_clock > 0`.
- [x] **Attention:** omitted when empty; rows `⚠ subject — detail` with the count badge.
- [x] **Cards:** on clock → `WO n` and "running h:mm" from `server_now`; off clock → "Last worked <weekday h:mm>" or "Never"; Today minutes; the counts line; flags through the label map with the snake-case fallback for an unknown flag; "Unknown" when both names are blank; the routed-to-you hint when `technicians` is empty.
- [x] **Through `openHub`:** a supervisor always gets the board; techfm_oa+ gets it only when `led.total > 0` (D16, both sides), and with the on-clock tile dropped.
- [x] **Admin summary:** on-the-clock list (empty copy; rows: name, `WO n · community`, elapsed, flag label incl. the unknown fallback); Supervisor / Technician time tiles; six pipeline tiles whose labels the test reads off `pages/work-orders.html`'s status `<option>`s (the module's own drift claim), `⚠` only on `ready_to_complete > 0`; a tile click → `openWorkOrdersFilteredByStatus` + `showPage` — assert `#work-orders-status-filter` and the active page; `pipelineBound` once-guard: three refreshes on one container, one click, one list request.
- [x] **Exceptions and billing:** five rows with "N open" on the first three; `formatMoney` on the three money rows; avg "—" vs "N.N d"; the sparkline glyphs (max → `█`, zero → `▁`); the legacy row only when non-null.

**Test.** `npm test` green; timers 0. Chunk plan: `2026-09-11-frontend-test-harness-p6b-crew-admin.md`. Three sub-shape factories earned their place (`hubCrewTechnician`, `hubAttentionItem`, `hubOnClockEntry`); no direct renderer call was needed — the shell reaches every branch.

---

### P6c — the lazy tabs

**Files.** Create `tests/frontend/views/hubTimesheets.test.js`, `tests/frontend/views/hubGraphs.test.js`, `tests/frontend/views/hubReport.test.js`. Modify `helpers/factories.js` (`hubReport()` + `hubReportRow()` against `HubReportResponse` / `HubReportRow`; `hubTimesheetDay()`; `hubGraphBucket()`; drift rows), `helpers/hub.js` (nothing structural — `report` stays `500` by default and the tests pass `hubReport()`).

- [x] **Timesheets:** header cells from `crew_totals_by_day` (UTC short labels); a missing day renders `0:00`; flag glyph + sr-only label (`●` running, `⚠` assigned-idle, the fallback); row totals, footer totals, the grand total; "Crew total" / "Company total", the caption and the two empty hints by `isAdminPlus` (supervisor vs techfm_oa through `openHub`); a cell click expands the drilldown (sessions with "running" and "⚠ estimate", adjustments, Charged subtotal, Total, the no-detail copy), a second click collapses, `aria-expanded` / `aria-controls`; prev / next → `onWeekChange` ±7 days → `GET /hub/timesheets?start&end` with the exact ISO dates; Export CSV → `GET /hub/timesheets/export?start&end` under `stubObjectUrl()`, "Preparing export…" then "Exported <filename>." from `Content-Disposition` (fallback `timesheet.csv`), the error copy, the button disabled meanwhile. The module's private `formatHm` duplicates `format.js` — file it.
- [x] **Graphs:** `largestCommunityKey` (largest, ties → first, empty → null); the donut — no total → the empty `role="img"`; arcs only for `count > 0`, each with `data-status`; the total badge; a legend row per status even at zero (`n · p%`, `0.0%` on an empty total); "View all N"; community tabs `label (total)` with `active` / `aria-selected`; the inner tabs; inner-grid empty reasons (priority with `total > 0` → "No imported priorities…", else "No circulating work orders"); cards carrying `data-community` plus `data-service-type` / `data-priority` as raw labels; duration — no samples copy, polylines split at a null bucket, "(partial)" and "No sample" in the details table; the range `<select>` reflects `payload.weeks`, a change → `onWeekChange(Number)` → `GET /hub/graphs?weeks=26`; a community tab click re-renders from memory with no request; a slice / legend row / View all → `onDistributionClick({community, serviceType, priority, status})` → the Work Orders hand-off asserted on the page's filter selects; `distributionClickBound` once-guard.
- [x] **Report:** header (short week range, long day label, "Generated" Central stamp, the `/hub/report/export` link); Closed — Today / This week from `count`, week rows with the Today badge for numbers in `closed_today.rows`, the Legacy badge, `archived_at` in the Closed column, the empty copy; Closing — count, the `by_status` breakdown in lifecycle order skipping zeros, the truncated notice, `created_at`; New — as Closed; a row button: archived → `openWorkOrdersByNumberSearch(number)` + `showPage` (assert the number search input), live → `focusWorkOrderNumber`; `renderReportSkeleton` copy; `renderReportError` → Retry → `onRetry` — through `openHub` with `report: 500`, then a passing handler, so the retry's success render is pinned too. Central-time stamps are computed in the test with the same `Intl` options, never typed as literals.

**Test.** `npm test` green; timers 0; `hubReport()` passes the drift guard. Chunk plan: `2026-09-11-frontend-test-harness-p6c-lazy-tabs.md`. Eight factories landed (the three the bullets named plus five the payload shaping earned).

---

### P6d — the Saved Items sub-flows

**Files.** Create `tests/frontend/views/notes.test.js`, `tests/frontend/views/itemEditor.test.js`, `tests/frontend/views/addBarcode.test.js`, `tests/frontend/views/correction.test.js`. Fixture: `helpers/items.js` `mountItems()` as-is (`stubScrollIntoView` already installed); each panel opens through the row-action `<select>` exactly as `items.test.js` does, so the P5c "opens the panel" assertions become this chunk's setup.

- [ ] **notes:** `renderNotesSummary` (empty → the `—` span; `k: v` joined, escaped, through `formatNoteValue`); open → one blank row when the item has no notes, else a row per entry typed by `detectNoteType`; the type select swaps the value control (text / number with `step="any"` / boolean select) carrying the raw value across; add row, remove row; save — blank keys skipped, duplicate names → error, number required and finite, boolean → `true`/`false`, `PATCH /items/{id}/notes` `{notes}` → "Notes saved." → `onSaved` refresh (the `GET /items/?q=` reload P5c pinned) → close after 1000 ms on fake timers; failure copy, panel stays; cancel; "No item selected." when the editing id is null.
- [ ] **itemEditor:** open prefills the six fields and a row per additional barcode; add / remove rows; validation (barcode, name, location required; a duplicated additional code names the code); the `saveItemCore` sequence at the wire — `PATCH /items/{id}/barcodes` first and only when the list changed, then `PATCH /items/{id}` with `price` parsed or null and `product_link` null when blank; a changed primary barcode → `confirmDialog(BARCODE_CHANGE_WARNING)`: No → `cancelled`, message cleared, panel open, no request; Yes → both writes; a 409 → the archived-reuse prompt → retry with `override_archived: true` on both; "Item saved." → `onSaved` → close after 1000 ms; failure keeps the panel open; `getEditingItemId` set on open and cleared on close.
- [ ] **addBarcode:** open shows the scanned code, an empty search, hidden results; typing → `skeletonList(3)` then, 200 ms later, `GET /items/?q=`; results narrowed by `filterRanked` on the name alone (a barcode-only server match is dropped — the module's `2x4` argument), capped at 8, the no-match copy; a stale answer is discarded (two inputs, first answer last); a failed search renders `friendlyError`; pick → `confirmDialog("Add barcode … to "name"?")` No → nothing; Yes → "Adding…" → `GET /items/{barcode}` fresh → `PATCH /items/{id}/barcodes` with `existing + pending`; a 409 → the archived-reuse prompt → `override_archived: true`; success copy → `onSaved` → close after 1200 ms; `cancelled` → message cleared; failure copy; cancel clears the debounce (timers 0) and the results.
- [ ] **correction (+ the panel):** open → "Correcting: name (barcode)", "Current count: q", new quantity prefilled and selected; the validation ladder in order — no selection, blank / non-finite, negative, missing reason; `POST /transactions/adjust` `{item_id, new_quantity, reason}` → "Count corrected." → `onSaved` → close after 1000 ms; failure copy, panel stays; cancel clears; `getEditingCorrectionItemId` follows open / close.

**Test.** `npm test` green; every export of the four modules (plus `createCorrectionPanel` via `correction.js`) called by name in a test.

---

### P6e — Tools

**Files.** Create `tests/frontend/helpers/tools.js`, `tests/frontend/views/tools.test.js` (split into `toolsCustody.test.js` / `toolsInventory.test.js` if the 500-line cap forces it), `tests/frontend/views/toolsActionCoverage.test.js`, `tests/frontend/unit/subnav.test.js`. Modify `helpers/factories.js` (`tool()` + `toolCustodyEntry()` against `ToolResponse` / `ToolCustodyEntry`; drift rows).

- [ ] **`helpers/tools.js`:** `mountTools({role, tools, users, handlers})` — `mountView("views/nav.js")` then `importView("views/tools.js")` (deviation 8); answers `GET /tools/` and `GET /users/` off its arguments; installs `stubUserMedia`, `stubPermissions`, `stubScrollIntoView` (`toolCheckout.js`, `toolReturn.js` and the tool editor call it unguarded — same class as the P5 finding, extend that row); `el` getters over the custody, inventory and scan ids; `openTools()` = mount + `loadTools()`; `subNavBtn(feature)`.
- [ ] **subnav unit:** the pre-marked `.active` button wins, else the first; `fireInitialOnShow: false` sets the DOM without the callback; `onShow(name, prev)` with `prev` null on the initial call; re-selecting the active feature is a no-op; a page with no `.sub-nav` still initialises; `dataset.activeFeature`.
- [ ] **Add Tool (create-item Tool tab):** the validation copy; quantity blank → 1, else `parseFloat`; `POST /tools/` body; success clears the fields with "Tool saved."; failure. `toolScanWidget` on the upload path only (as P5c did): a match → "Already in use by X." error; a 404 → `#tool-barcode` filled and the controls collapsed; the toggle collapses and calls `stopLive`.
- [ ] **`loadTools` by role:** techfm_oa+ fires `/tools/` and `/users/` (no `include_archived`), shows the picker and "Search for a user to view tool custody."; supervisor / technician fires `/tools/` only, hides the picker, self-selects and paints the card; the 5- / 4-column skeleton; `/tools/` 500 → an error row with `colspan="5"` for every role (a non-manager's table has four columns — file it) plus the custody message; `/users/` 500 → "Could not load active users." and the selection cleared; archived users dropped and the rest name-sorted; a selected user missing from a reload → cleared.
- [ ] **User picker:** focus lists everyone (≤ 8, `filterRanked`), input filters, editing the chosen name clears the selection and closes both editors, ArrowDown / ArrowUp wrap with `aria-activedescendant` + `is-active`, Enter picks the active option, Escape hides, click picks; the card — name, "Role · Created <date>" and "Created date unavailable" (null and invalid), "Active", singular vs plural custody count, holdings rows with Check In or the empty copy, checkout controls hidden below techfm_oa, `userCard.focus()`; a document click outside hides the results and the checkout results.
- [ ] **Check In → `openToolReturn`:** the return section with "name (barcode)", "Name has N checked out", quantity and `max` = N; the checkout editor closed first.
- [ ] **Checkout picker:** focus lists tools with `quantity > 0` name-sorted (≤ 8), the two empty copies, input closes an open checkout, Escape hides, Enter clicks the first, click → `openToolCheckout`: "Checking out to Name", quantity 1, `max` = on hand, the return editor closed.
- [ ] **toolCheckout / toolReturn save:** the no-selection copy; blank / 0 / NaN → "Enter a quantity greater than zero."; over the limit → "Only N on hand." / "Only N checked out."; `POST /tools/{id}/checkout` and `/return` with `{quantity, assigned_to_id, work_order_number}` (null vs trimmed); the success copy → `onSaved` = `refreshTools` (a second `GET /tools/`, the card repainted) → close after 1000 ms; failure copy; cancel resets both fields and drops `max`.
- [ ] **Inventory:** 4 / 5 columns by role; `filterRanked` over name and barcode; the two empty copies; the custody cell `user: qty` joined by `<br>`; the actions select for managers only; `edit` → the editor prefilled ("Editing: name (barcode)"), its validation, `PATCH /tools/{id}` `{barcode, name}`, "Tool updated." → refresh → close after 1000 ms, failure; `correct` → `#tool-correction-section` with the row, Save → `POST /tools/{id}/adjust` `{new_quantity, reason}` → refresh (wiring only, deviation 4); `delete` → `confirmDialog('Archive "name"? …')` both ways → `DELETE /tools/{id}`, closes the editor / correction if open on that tool, "Archived "name".", refresh; failure copy; a failing `refreshTools` writes the "saved, but could not be refreshed" copy into both message slots.
- [ ] **Contextual scanner (`toolsScanner`, upload path):** lookup → the inventory feature, search = barcode, table filtered, the row's guarded `scrollIntoView`; the Scan sub-nav button → lookup context, `reset()`, `refreshPermissionState()`; "Scan for checkout" — no user → "Select an active user first."; with one → heading / hint name the user and the scan feature shows; a found tool → the custody feature and `openToolCheckout(tool, user)`; quantity 0 → "has no units on hand."; a self-selected supervisor → "Select an active user before scanning for checkout."; `onShow` — leaving scan → `stopLive()` + lookup context; leaving custody closes checkout / return and hides the results; leaving inventory closes editor / correction.
- [ ] **`resetToolsView`:** every field and panel cleared, the custody feature active, `getTools()` empty, `toolsScanner.reset()` reached (P5b asserted only "no throw").
- [ ] **Audit:** `toolsActionCoverage.test.js` over `tools.js` with `renderedPattern: /<option value="([a-z-]+)">/g`, frozen `["correct", "delete", "edit"]`, behaviour files = this chunk's only. `tools.js` guards the last branch with `action !== "delete"`, which the default `handledPattern` does not match — pass `handledPattern: /action (?:===|!==) "([a-z-]+)"/g`; no helper change.

**Test.** Delete one action's tests locally; the audit names it. Restore. `npm test` green.

---

### P6f — Users

**Files.** Create `tests/frontend/helpers/users.js` (`mountUsers({role, users, handlers})` → `mountView("views/users.js")` with `GET /users/` answered; `el` getters; `rowFor(username)`), `tests/frontend/views/users.test.js`, `tests/frontend/views/usersActionCoverage.test.js`. Modify `tests/frontend/helpers/dialogs.js`: `answerPasswordReset(password | null)`, `answerUserName({first, last, username} | null)`, `answerUserRole(role | null)` — each drives the real overlay (`#pw-reset-*`, `#user-name-*`, `#user-role-*`, ids in `dom.js` 203–429) the way `answerConfirm` drives `#scan-confirm-overlay`.

- [ ] **`loadUsers`:** the 6-column skeleton; `GET /users/?include_archived=true`; rows — "Name unavailable" fallbacks, the "(archived)" tag and `.archived-user`, `roleLabel`, `created_at` through `toLocaleString()` (a null renders the epoch — the Items finding's twin, file it); the failure row `colspan="6"` with `friendlyError`.
- [ ] **The row-action matrix, frozen and read off the running code as P2's roles table was:** actor × target over the five roles × {active, archived, self} — Edit Details (self or `canManage`), Edit Role (`canManage` ∧ active ∧ actor ≥ techfm_oa), Reset Password + Archive (`canManage` ∧ active), Restore (`canManage` ∧ archived), `—` otherwise.
- [ ] **Selects:** `populateRoleSelect` offers `assignableRoles(actor)` (owner → four, technician → none), keeps the previous value when still offered, writes the help text per role and on change; `populateUserSelects` rebuilds `#history-user-select` (placeholder + an option per user, archived included, `formatUserName`) preserving the selection iff still present — the seeding P5e's fixture faked.
- [ ] **Create:** the validation order (names → username → role → password ≥ 4); `POST /users/` snake_case body; "First Last created as role."; the four fields cleared; a reload fired; failure copy.
- [ ] **Edit Details:** `promptUserName` (username allowed) → `PATCH /users/{id}/name`; a self-edit updates `state.js`'s current user and the header indicator's name / role / `aria-label`; `user-names-updated` dispatched (a listener in the test); "Updated "newusername"."; cancel → no request.
- [ ] **Edit Role:** `promptUserRole` offered the assignable roles with descriptions → `PATCH /users/{id}/role` → "… is now role. They will need to sign in again." + reload; cancel or unchanged → no request.
- [ ] **Reset Password:** `promptPasswordReset` → `POST /users/{id}/reset-password` `{password}` → "Password reset for "u"."; cancel; failure.
- [ ] **Restore:** `POST /users/{id}/restore` + reload; failure.
- [ ] **Archive:** `confirmDialog` No → nothing; Yes → `POST /users/{id}/archive`; a 409 → the archived-reuse prompt with the "still has tools checked out" copy → Yes retries with `?force_return_tools=true`, No → `cancelled`, message cleared; "Archived "u"." + reload; another failure's copy.
- [ ] **Audit:** `usersActionCoverage.test.js` with `renderedPattern: /class="([a-z-]+-btn)[ "]/g` and `handledPattern: /classList\.contains\("([a-z-]+-btn)"\)/g`, frozen `["archive-user-btn", "edit-user-name-btn", "edit-user-role-btn", "reset-pw-btn", "restore-user-btn"]`.

**Test.** Delete one action's tests; the audit names it. Restore. `npm test` green.

---

### P6g — Push

**Files.** Create `tests/frontend/views/push.test.js`. Modify `tests/frontend/helpers/media.js` only if `stubPush` needs a knob the branches below cannot reach (a rejecting `subscribe`, a `/push/config` key other than `QUJD`) — helper change, allowed.

Mount `views/push.js` directly after `setTestUser({role})` and `stubPush({…})` (or no stub for the unsupported branch); `initPushForUser()` and `unsubscribeThisDevice()` are the test's calls.

- [ ] **`initPushForUser`:** the test button visible for owner only, across the five roles; unsupported (no stub) → no request; permission `default` / `denied` → no request; `granted` → `GET /push/config`, `register("/service-worker.js")`, `getSubscription()`; no existing subscription → `subscribe({userVisibleOnly: true, applicationServerKey})` whose bytes decode a key that needs padding and the `-` / `_` swaps (`vapidKeyToBytes` at its only seam); an existing subscription on the same key → no `unsubscribe`, no `subscribe`, still `POST /push/subscribe` (the shared-device re-POST); a different key → `unsubscribe()` then `subscribe()`; `/push/config` 500, or `subscribe` rejecting → swallowed, no `POST /push/subscribe`.
- [ ] **`unsubscribeThisDevice`:** unsupported → nothing; no registration → nothing; no subscription → nothing; `POST /push/unsubscribe {endpoint}` then the browser `unsubscribe()`; a server 500 is swallowed **and the browser subscription is kept** — the "server-side first" order leaves a dead endpoint on the device; file it.
- [ ] **`resetPushView`** hides the button. **`requestPermissionAtLogin`:** `default` → prompts once; `granted` / `denied` → no prompt; unsupported → no prompt; a rejecting prompt is swallowed (P5b owns the login wiring; these are the module's own branches).
- [ ] **The test button:** click → disabled meanwhile → `POST /push/test` → `messageDialog` with "Sent to N device(s). D stale subscription(s) removed, F failed." through the real overlay (see `unit/dom.dialogs.test.js` for the ids); a failure → `friendlyError` in the dialog; re-enabled either way.

**Test.** `npm test` green; every export of `push.js` called by name.

---

## Suite budget

Seven chunks over a suite that costs 112–135 s. P5 added ~470 tests for ~85 s; P6 covers fewer lines with cheaper mounts (the hub fixture is one `GET /hub`, not a boot), so expect the close near 3 min — under the 6-minute line with no lever pulled.

- [ ] Record wall-clock at each chunk's close, in the commit body.
- [ ] If a chunk pushes the total past ~6 minutes locally, stop and raise it before starting the next. The lever is `maxWorkers` and the shell cache, not deleting assertions.

| Close of | Tests / files | Wall-clock |
| --- | --- | --- |
| P5 (entry) | 1286 / 40 | 112 s |
| P6a | 1343 / 43 | 191 s — an outlier; the same suite re-measured 123 s at P6b |
| P6b | 1382 / 45 | 123 s |
| P6c | 1454 / 48 | 145 s |

## Done when

- [ ] All seven chunks are committed, each green at commit time.
- [ ] Every export of the twenty modules is exercised; `tools.js` and `users.js` actions are named by their audits.
- [ ] Findings are filed in `docs/open-work.md` under `N-P6-CHARACTERIZED`, in the P2 table form (defect, pinned by).
- [ ] `docs/current-state.md`: the Tools UI row no longer says "no Vitest suite for these views yet"; the User Hub Graphs / Report rows, the Item CRUD row, the Users row and the Web Push row name their tests; the Vitest bullet's count / time updated and "Remaining views: uncovered, roadmap P6-P7" reads P7 only.
- [ ] Roadmap status row for P6 in the P5 form (date, chunk count, suite size, wall-clock, `npm run test:ci` statements / lines).
- [ ] Coverage recorded, still advisory. P7 gates.

## Deliberately not in P6

- Any production change.
- Fixing anything characterization reveals.
- P7's nine files (`userRequests`, `userRequestCards`, `workOrderRequests`, `lowStock`, `lowStockCard`, `adminReview`, `catalogueRequest`, `scan-test.js`, `service-worker.js`).
- `billingEditor.js` (deviation 2).
- Re-covering P5 wiring: `auth.js`'s push entry points, `items.js`'s row-action opens, `history.js`'s user-select seeding, `userHub.js`'s tab shell and failure isolation, the camera (P5g).
- New E2E journeys.

## Drift register — found while planning P6 (2026-09-11)

| # | Drift | Where | Action |
| --- | --- | --- | --- |
| D1 | The roadmap's P6 file list carries `billingEditor.js`, which P5e already drove for real and recorded as off-limits to P6. | roadmap P6 | **File** — strike it from the list with the reason. |
| D2 | The roadmap says "`push.js` needs the `Notification` and `ServiceWorkerRegistration` APIs stubbed" as if that were P6 work; `helpers/media.js::stubPush()` has done it since P5b. | roadmap P6 | **File** — point the step at `stubPush`. |
| D3 | The roadmap calls `users.js` a delegated-action view alongside `tools.js`; it delegates on class names, not `data-action` or `<option>` values, so the audit needs custom patterns (deviation 6). | roadmap P6 | **File** — one clause. |
| D4 | The roadmap status block says the branch is 45 commits ahead of `origin/main`; it is 74 as of this plan, still unpushed, still un-CI'd. Pushing `main` deploys production — owner decision (P5's D2, still open). | roadmap status | **File** — update the number. |
| D5 | Six P6 files sit at ≤ 4 commits (`notes` 2, `correction` 3, `correctionPanel` 1, `toolCorrection` 2, `subnav` 2, `push` 3), which by the churn table's own rule is P7 territory. They stay: each is coupled to a P6 host and would cost a second fixture later. | roadmap churn table | No action; recorded. |
| D6 | Re-derived churn 2026-09-11: `hubTechnician` 11, `users` 10, `tools` 9, `hubAdmin` 8, `hubClock` 7, `itemEditor` 7, `addBarcode` 7, `hubSupervisor` / `hubGraphs` / `hubReport` 4, `hubTimesheets` 3, `toolCheckout` / `toolReturn` 3 — consistent with the roadmap's "4–11" band. | — | No action; recorded so the chunk sessions do not re-derive it. |
| D7 | `current-state.md`'s Tools UI row still reads "manual UI check (no Vitest suite for these views yet)"; true until P6e, so not drift yet — listed so the P6e close does not miss it. | `current-state.md` | Closed by P6e's doc step. |
