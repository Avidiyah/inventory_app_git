# Frontend Test Harness — P2 (`workOrders.js` Characterization Coverage) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pin the current behaviour of the 2,842-line `backend/static/views/workOrders.js` precisely enough that the P4 split can be verified by `npm test` rather than by clicking. Characterization, not correction: the suite records what the code does today, bugs included.

**Architecture:** Tests only, on top of the P0 harness and the P1 foundation suite. One shared mount helper (`helpers/workOrders.js`) owns list seeding, card opening and modal answering so the five behaviour files carry assertions and not setup. A mechanical meta-test greps the 26 `data-action` strings out of the source and fails when one has no test — that is the guardrail P4 leans on.

**Tech Stack:** Vitest, jsdom, @testing-library/dom, @testing-library/user-event, msw.

**Spec:** `docs/superpowers/specs/2026-09-10-frontend-test-harness-design.md`
**Roadmap:** `docs/superpowers/plans/2026-09-10-frontend-test-harness-roadmap.md` (P2)
**Depends on:** P0 (merged) **and P1** (must be merged first — see below). P2 consumes P1 helpers by name; if P1 landed them under different names, fix the imports here rather than re-deriving the plan.

## Inherited from P1 — verify before Task 1

| Helper | What P2 uses it for |
| --- | --- |
| `helpers/fakeSocket.js` — `installFakeWebSocket()` | The only realtime seam. See "Realtime without `__emit`" below. |
| `helpers/factories.js` — `workOrder()` | Base for the card/detail factories Task 1 extends. |
| `unit/api.endpoints.test.js` — the `ENDPOINTS` table | Authoritative method/URL per wrapper. P2 asserts *that a wrapper's endpoint was hit*; it does not re-assert the wrapper's shape. |
| `helpers/session.js` — `setTestUser({role})` | The role dimension. |

If P1 has not landed, **stop and say so.** Building card factories against unverified `api.js` shapes is the exact failure the roadmap's ordering exists to prevent.

## Global Constraints

- **Tests only.** No changes to any file under `backend/static/` or `backend/app/`. If a test cannot be written without changing production code, stop and raise it.
- **Characterization.** A suspected bug is filed in `docs/open-work.md` in Task 13, never fixed here. Assert what the code does; where that looks wrong, say so in a comment on the assertion and file it.
- **No `vi.mock` of any app module.** The real `workOrders.js`, `api.js`, `dom.js`, `realtime.js`, `format.js` all execute. Seams are `fetch` (MSW), `WebSocket` (fake class), timers, and the four browser globals in Task 1.
- **`onUnhandledRequest: "error"` stays on.** Opening a card fires `GET /work-orders/:id`; the reference-data load fires `GET /items` and `GET /users`. Every test registers what it needs — Task 1's helper does this once.
- **`mountView()` before anything.** The module captures 24 element ids and wires 5 listeners at import time.
- **Coverage stays advisory.** P7 turns the threshold blocking.
- Commit messages end with `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.

## Two deviations from the roadmap text, decided here

1. **Realtime without `__emit`.** The roadmap says "via the mocked `__emit`". `realtime.js` exports no such hook (`setActivePageGetter`, `subscribe`, `connectRealtime`, `disconnectRealtime` only), and adding one would be a production change. P2 instead drives the real dispatch path: `installFakeWebSocket()`, `setActivePageGetter(() => "work-orders")`, `connectRealtime()`, then push a frame through the fake socket's `message` event. This exercises `parseEnvelope` and the generation guards too, so it is strictly better than a mocked emitter.
2. **Roles are sampled, not crossed.** 26 actions × 4 roles is 104 tests of mostly identical plumbing. P2 covers role gating at the point where it is actually decided — *which controls render* — with one matrix test per status, then runs each action once at its minimum permitted role plus one denial spot-check for the actions whose predicate is non-obvious (`canEditLabor`, `canCurrentUserSendToReview`, `isAssignedToCurrentUser`).

## File Structure

| File | Responsibility |
| --- | --- |
| `tests/frontend/helpers/workOrders.js` | `mountWorkOrders()`, `seedList()`, `openCard()`, `answerConfirm()`, `lastRequest()` |
| `tests/frontend/helpers/browserStubs.js` | `stubWindowOpen()`, `stubObjectUrl()`, `stubLocationReload()`, `stubScroll()` |
| `tests/frontend/helpers/factories.js` | **extended** — `workOrderCard()`, `workOrderDetail()`, `workOrderItem()`, `workOrderLabor()`, `filterOptions()` |
| `tests/frontend/views/workOrders/render.test.js` | summary, card class, priority/status badges, body sections, skeleton→loaded |
| `tests/frontend/views/workOrders/roles.test.js` | the render-time role matrix and the three gating predicates |
| `tests/frontend/views/workOrders/actions.test.js` | the 26 delegated branches |
| `tests/frontend/views/workOrders/filters.test.js` | filters, sort, search, restore prompt, `RECENT_LIMIT`, `mountWorkOrderList` |
| `tests/frontend/views/workOrders/solo.test.js` | solo card, routing, popstate, scroll, `renderSoloError`, the four `openWorkOrders*` exports |
| `tests/frontend/views/workOrders/realtime.test.js` | envelope routing, held-card defer, reconnect refetch |
| `tests/frontend/views/workOrders/integrations.test.js` | import, export, NetFacilities poll and cloud controls |
| `tests/frontend/views/workOrders/actionCoverage.test.js` | the meta-test |
| `tests/frontend/views/workOrders.test.js` | **unchanged** — P0's exemplar stays where it is |

---

### Task 1: Shared fixtures — mount helper, browser stubs, factories

**Goal.** One place that mounts the view with a seeded list and an open card, so the behaviour files hold assertions only.

**Files.** `helpers/workOrders.js`, `helpers/browserStubs.js`, `helpers/factories.js` (extend).

**Steps.**
- [ ] `factories.js`: add `workOrderCard(overrides)` matching `backend/app/schemas/work_orders.py:232` field-for-field (`id`, `number`, `status`, `entry_mode`, `item_count`, `assigned_to_ids`/`_names`, `location`, `service_type`, `schedule_date`, `supervisor_id`/`_name`, `priority`, `legacy`, …). Defaults: `status: "assigned"`, `legacy: false`, empty assignment arrays.
- [ ] `workOrderDetail(overrides)` = `workOrderCard()` plus the `WorkOrderDetail` fields (`notes`, `items`, `labor`, `active_labor_session`, `tracking_technician_ids`, `materials_total`, `labor_minutes`, `labor_billed_minutes`, `labor_rate`, `labor_total`). Cost fields default to a number, not `null` — a `null` there is the *redacted* case and gets its own test.
- [ ] `workOrderItem()` / `workOrderLabor()` per `WorkOrderItemDetail` / `WorkOrderLaborDetail`. `filterOptions()` per `WorkOrderFilterOptions`.
- [ ] `browserStubs.js`. jsdom throws or no-ops on four things this module uses: `window.open` (`open-netfacilities-wo`), `URL.createObjectURL`/`revokeObjectURL` (`downloadExport`), `window.location.reload` (the 409 already-assigned path), and `window.scrollTo` (`restoreListScrollY`). Each stub is a `vi.fn()` the test can assert on, installed per test and restored in `afterEach`.
- [ ] `workOrders.js` helper:
  - `mountWorkOrders({role, cards, options})` → `setTestUser` → register handlers for `GET /work-orders`, `GET /work-orders/filter-options`, `GET /items`, `GET /users` → `mountView("views/workOrders.js")` → `await mod.loadWorkOrders()` → return `{mod, cards}`.
  - `seedList(cards)` re-registers `GET /work-orders` for a reload.
  - `openCard(number|index, detail)` registers `GET /work-orders/:id` for that detail and clicks the `<summary>`, awaiting the body render.
  - `answerConfirm(yes)` awaits `#confirm-overlay` becoming visible and clicks Yes/No. `confirmDialog` resolves through the real shell modal (`dom.js`), so tests must drive it, not stub it.
  - `lastRequest()` — the recorded `(method, url, body)` of the most recent MSW-intercepted call, so an action test asserts the request without a second spy layer.

**Test.** A smoke test in `render.test.js` mounts with three cards and opens one; the body renders and no unhandled-request error fires.

---

### Task 2: Render — list summary and card class

**Goal.** Pin what a collapsed row looks like for every status and priority.

**Files.** `views/workOrders/render.test.js`.

**Steps.**
- [ ] `summaryHtml` (`views/workOrders.js:1261`) for each of the seven statuses: number, `statusLabel`/`statusBadge` text and class, `placeMeta` composition (`:626`) for an imported row, a legacy row (`hasLegacyPlace`, `:816`), and a row with neither.
- [ ] `priorityBucket` (`:570`) across the real priority strings plus `PRIORITY_NOT_IMPORTED`, `null`, and an unrecognised value; `priorityBadgeClass` / `priorityBadge`.
- [ ] `urgentFireActive` (`:592`) — true for the manual `Urgent` priority, false once status is in `SETTLED_STATUSES` (`completed`, `review`). Assert both directions.
- [ ] `workOrderCardClass` (`:613`) called directly as an export, table-driven. Note in a comment that `adminReview.js` and `transactions.js` consume it too, so P4 must keep it exported.
- [ ] `modeLabel` (`:618`) for each `entry_mode`.
- [ ] Skeleton → loaded: assert `skeletonCard` markup is present while `GET /work-orders` is in flight (resolve the handler manually) and gone after.
- [ ] Empty list renders the empty-state message, not a blank list.

**Test.** Every branch of the six pure render helpers above has a case.

---

### Task 3: Render — the expanded body

**Goal.** Pin `renderBody` (`:1679`) and everything it composes.

**Files.** `views/workOrders/render.test.js`.

**Steps.**
- [ ] `detailsViewHtml` (`:840`) — imported metadata block for admin+, the reduced supervisor view, `importedDetailValueHtml` for a present and an absent value.
- [ ] `detailsEditorHtml` (`:971`) — `editField` per field, `priorityEditField` (`:889`, the `MANUAL_PRIORITY` special case), `statusEditorHtml` + `editableStatusValues`/`editableStatusOptions` (`:914`/`:935`) per current status and role. Assert `data-original-supervisor-id` is stamped — `save-details` sends it as `expected_supervisor_id`.
- [ ] Labor: `laborSummaryHtml` (`:460`), `renderLaborEntryHtml` (`:473`), `laborTechnicianControl` (`:502`), `laborSectionHtml` (`:520`), `formatMinutes`/`hoursInputValue`/`hoursToMinutes` (`:441`–`:454`) table-driven including `0`, blank and non-numeric.
- [ ] Materials: `renderLineHtml` (`:1819`), `lineChargeHtml` (`:403`), `effectiveBillable` (`:394`), `materialsTotalHtml` (`:425`) — including the `MARKUP_RATE` 1.15 arithmetic and the redacted (`materials_total: null`) case.
- [ ] `notesLogContentsHtml` (`:434`) — empty, one entry, many.
- [ ] `technicianPickerHtml` (`:673`), `technicianSelectionHtml`, `emptyTechnicianSelectionHtml`, `assignedNames`/`assignedIds` (`:635`/`:640`).
- [ ] `comboHtml` (`:787`, exported) and `comboListHtml` — assert the native `<select>` fallback is emitted alongside the custom list.
- [ ] `supervisorOptions`/`supervisorChoices` (`:753`/`:765`) with the current supervisor pre-selected.
- [ ] Assert **no `style=` attribute** appears anywhere in the generated card HTML. CSP silently drops inline styles in production; this is the cheapest place to catch a regression.

**Test.** Each section renders for at least one status; the money and minutes helpers are table-driven.

---

### Task 4: Role gating at render time

**Goal.** One matrix that says which controls each role sees, so P4 cannot quietly drop a guard.

**Files.** `views/workOrders/roles.test.js`.

**Steps.**
- [ ] Build a table: rows = (role × status × assigned-to-me?), columns = the control selectors (`start-tracking-wo`, `stop-tracking-wo`, `notify-supervisor-wo`, `hold-assigned-wo`, `resume-assigned-wo`, `send-back-wo`, `complete-wo`, `review-wo`, `reopen-wo`, `archive-wo`, the details editor, the labor section, the add-material block, the notes form). Assert presence/absence per cell. Generate the table from a literal in the test file — read it off the running code once, then freeze it.
- [ ] `isSupervisorPlus` (`:273`) / `isAdminPlus` (`:280`) directly, per role.
- [ ] `isAssignedToCurrentUser` (`:647`) — in `assigned_to_ids`, not in it, and the single-`assigned_to_id` legacy shape.
- [ ] `canCurrentUserSendToReview` (`:655`) and `canEditLabor` (`:469`) across all four roles.
- [ ] Denial spot-check: as a technician *not* assigned, assert the three assigned-only controls are absent from the DOM (not merely disabled).

**Test.** The matrix is exhaustive over the four roles and seven statuses for the controls listed.

---

### Task 5: Actions — the status lifecycle

**Goal.** Ten delegated branches: request issued, DOM result, error surfaced.

**Files.** `views/workOrders/actions.test.js`.

**Steps.** For each of `start-tracking-wo`, `stop-tracking-wo`, `notify-supervisor-wo`, `send-back-wo`, `hold-assigned-wo`, `resume-assigned-wo`, `complete-wo`, `review-wo`, `reopen-wo`, `archive-wo`: click at the minimum permitted role, assert the endpoint and body from `lastRequest()`, and assert the card refreshed (`refreshCard` re-issues `GET /work-orders/:id`). Then the branch-specific parts:
- [ ] `stop-tracking-wo` — when the refreshed row comes back `status: "on_hold"`, the "Nobody is charging, so this is now On-Hold." success message appears in the *refreshed* `.wo-message`.
- [ ] `notify-supervisor-wo` — a 400 with the exact detail `"All Users must Stop Charging before a Supervisor can be notified."` opens `messageDialog` and issues **no** refresh; any other error falls through to the generic handler.
- [ ] `notify-supervisor-wo` — a `ready_to_complete` response shows "Sent to your supervisor for review."
- [ ] `send-back-wo` / `complete-wo` / `reopen-wo` — `PATCH` with `{status: "in_progress"|"completed"|"in_progress"}` respectively.
- [ ] `review-wo` — `confirmDialog` gate: No cancels with no request; Yes patches `{status: "review"}`.
- [ ] `archive-wo` — `confirmDialog` gate, then `apiArchiveWorkOrder`, then a full `loadWorkOrders()` (not a card refresh).
- [ ] The shared 409 path: an error with `status: 409` and a detail starting `"This Work Order was already assigned to "` opens `messageDialog` then calls `window.location.reload` (assert the stub).
- [ ] The generic catch: any other error renders through `friendlyError` into `.wo-message` with the `error` class.

**Test.** Ten branches covered; the two dialog gates asserted in both directions.

---

### Task 6: Actions — editor, labor, materials, technicians, combo

**Goal.** The remaining fourteen branches, including every client-side validation guard.

**Files.** `views/workOrders/actions.test.js`.

**Steps.**
- [ ] `cancel-edit` — re-fetches the detail and discards the draft (change an input, cancel, assert the saved value is back and the editor is collapsed).
- [ ] `save-details` — assert the patch shape at `:2079`: trimmed-or-`null` per field, `undefined` fields **deleted** (the legacy community/building/unit inputs absent on an imported row must not be sent), `expected_supervisor_id` read off `data-original-supervisor-id`, `assigned_to_ids` collected from `.wo-tech-selected-row`.
- [ ] `save-notes` — empty/whitespace shows "Enter a note before saving." and issues no request; a real note patches `{notes}`, clears the input, re-renders `.wo-notes-log` from the response, shows "Note saved.", and collapses `.wo-notes-section`.
- [ ] `add-labor` — no technician → "Assign and select a technician first."; zero/blank hours → "Enter actual labor hours greater than zero."; valid → `apiAddWorkOrderLabor` with `{technicianId, minutes}` and the labor section reopened after refresh.
- [ ] `edit-labor` — zero hours guard; valid → `apiUpdateWorkOrderLabor(id, laborId, {minutes})` from `row.dataset.laborId`.
- [ ] `remove-labor` — confirm gate both ways, then `apiDeleteWorkOrderLabor`.
- [ ] `add-item` — no `data-item-id` → "Search and pick an item first."; non-finite or ≤0 qty → "Enter a quantity greater than zero."; valid → `apiAddWorkOrderItem` with `{itemId, quantity, materialRequestId}`, `data-material-request-id` deleted afterwards, materials section reopened, and the **negative `item_quantity`** response producing "Item added. Please re-count stock." as an `error` message rather than the success one.
- [ ] `edit-item` / `remove-item` — qty guard; confirm gate; `woItemId` from the row dataset.
- [ ] `pick-item` (`:1900`) — stamps `data-item-id`/`data-item-name` onto `.wo-add-item` and fills the search input. Also cover the `input` delegation above it: `filterRanked` over `allItems` capped at 8, and the no-match branch rendering `catalogueRequestPromptHtml` with the card's id and `source: "work_orders"`.
- [ ] `pick-technician` / `remove-technician` (`:1912`/`:1930`) — selection rows added/removed; `renderTechnicianSearch` (`:712`) and `closeTechnicianResults` (`:702`).
- [ ] `toggle-combo` / `pick-combo-option` (`:1941`/`:1955`) — open/close, value written to the hidden native select, `closeCombo` (`:805`) on outside click.
- [ ] `open-netfacilities-wo` (`:1985`) — asserts `window.open` called with the exact `https://system.netfacilities.com/tools/viewworkorders/<encoded number>` URL and `"_blank", "noopener,noreferrer"`. Assert the `encodeURIComponent` on a number needing escaping.

**Test.** Fourteen branches covered; every `setMessage(..., "error")` guard has a case.

---

### Task 7: Filters, sort, search, and `mountWorkOrderList`

**Goal.** Pin the list-loading surface.

**Files.** `views/workOrders/filters.test.js`.

**Steps.**
- [ ] Each of the six `change`-wired selects (`:2726`) triggers one reload with the right query params via `currentFilters`/`listParams` (`:355`/`:375`), and resets `showAll`.
- [ ] `hasActiveFilters` (`:369`) and `resetFilterControls` (`:379`); the Clear button also cancels both keyword debounces.
- [ ] `wireKeywordSearch` (`:2709`) on the location and task inputs with `vi.useFakeTimers()`: 250 ms debounce coalesces rapid input into one reload; Enter flushes immediately.
- [ ] `runWorkOrderNumberSearch` (`:2687`) and its own debounce.
- [ ] Sort: `renderSortControl` (`:348`), a click on the other direction persists to `localStorage` under `workOrders.sort` and reloads; an unknown or same-value `data-sort` is ignored; a pre-seeded `localStorage` value is honoured on import, and a garbage value falls back to `scheduled_desc` (`SORT_VALUES`, `:339`).
- [ ] `RECENT_LIMIT` = 10 (`:129`): eleven cards render ten plus `renderMoreControl` (`:1230`); clicking Show all sets `showAll` and renders all; a subsequent filter change resets it.
- [ ] `loadFilterOptions` / `populateFilterSelect` (`:301`/`:289`) — options populated once (`filterOptionsLoaded`), empty-label first, `PRIORITY_NOT_IMPORTED` handling.
- [ ] `ensureReferenceData` (`:1076`) — `GET /items` and `GET /users` fetched once per visit; the `user-names-updated` event (`:116`) invalidates and forces a refetch.
- [ ] The archived-number restore prompt: `offerRestoreForExactArchivedSearch` (`:1025`) — an exact-number search that returns no live row calls `apiLookupWorkOrder`, prompts, and on Yes calls `apiRestoreWorkOrder` and reloads; on No does nothing. Cover the `archivedSearchToken` guard (a stale response after a newer search must not prompt) and `archivedSearchPromptOpen` (no double prompt).
- [ ] `mountWorkOrderList` (`:1567`) — mounts into a supplied container, honours `lockedFilter`, and invokes `onOpen` instead of the default open. This is the Mass Stage entry point.

**Test.** Fake timers used for every debounce; no real waiting.

---

### Task 8: Solo card and routing

**Goal.** The app's only routed URL, both directions.

**Files.** `views/workOrders/solo.test.js`.

**Steps.**
- [ ] `soloNumberFromPath` (`:215`, exported) table-driven: `/workorder_card/123` → `"123"`, the list path → `null`, a trailing slash, an encoded number, a nested path.
- [ ] `openWorkOrderPage` / `openWorkOrderPageByNumber` (`:1433`/`:1464`) — `history.pushState` payload contains `solo: true` and `woListScrollY`; `setSoloChrome` (`:232`) hides `#work-orders-controls-section`; `showSoloCard` (`:1592`) renders one expanded card with `soloBackControl` (`:257`).
- [ ] `back-to-work-orders` (`:1969`): with `history.state.solo` true it calls `history.back()`; on a cold deep link (no such state) it calls `loadWorkOrders()` directly. Assert both — this branch exists precisely because `back()` would leave the app.
- [ ] `popstate` (`:2830`) both directions: to the list restores `pendingListScrollY` from `history.state.woListScrollY` and exits solo; to a card number opens it; a popstate while the Work Orders page is not `.active` is ignored; a popstate to the same solo number is a no-op.
- [ ] `stampListScrollY`/`restoreListScrollY` (`:184`/`:200`) with the `window.scrollTo` stub.
- [ ] `renderSoloError` (`:1621`) — a 404 on the detail fetch renders the error card with a working back control, not an empty page.
- [ ] `exitSolo` (`:245`) normalizes the URL on a plain `loadWorkOrders()`.
- [ ] The three list-entry exports: `focusWorkOrder` (`:269`) sets `pendingFocusId` and the next load expands that card; `focusWorkOrderNumber` (`:1496`); `openWorkOrdersByNumberSearch` (`:1507`); `openWorkOrdersFilteredByStatus` (`:1520`); `openWorkOrdersFilteredByDistribution` (`:1536`).

**Test.** All eleven exports are now touched by the suite; note which task covers each.

---

### Task 9: Realtime

**Goal.** The socket-driven refresh paths, through the real dispatcher.

**Files.** `views/workOrders/realtime.test.js`.

**Steps.**
- [ ] Setup per the deviation note: `installFakeWebSocket()`, `setActivePageGetter(() => "work-orders")`, `connectRealtime()`, then emit frames as `work_order.status.changed` envelopes.
- [ ] A frame whose `id` matches a rendered `details.wo-card[data-id]` re-issues `GET /work-orders/:id` and updates the summary in place (`refreshCardSummary`, `:1285`) without collapsing the card.
- [ ] An unknown id is ignored — no request at all.
- [ ] `activePage` other than `"work-orders"` is ignored.
- [ ] A **held** card (`isHeld`, `:1337` — `EDITOR_SECTIONS` open) defers: `data-missed-update="1"` is stamped, no request fires, and closing the editor fires the catch-up refresh via the capture-phase `toggle` listener (`:2792`). Assert the capture phase specifically: `toggle` does not bubble, so a regression here is silent.
- [ ] `reason === "reconnect"` or a null envelope `id` triggers `runOrDeferListRefresh` (`:1351`) — a full list refetch, deferred while any card is held (`anyCardHeld`, `:1341`) and flushed on the next toggle.
- [ ] A malformed envelope never reaches the subscriber (`parseEnvelope` rejects it upstream).

**Test.** No real socket, no real timers.

---

### Task 10: Integrations block

**Goal.** The Integrations page surface this module also owns.

**Files.** `views/workOrders/integrations.test.js`.

**Steps.**
- [ ] `loadIntegrationsPage` (`:1208`, exported) mounts the import/export/NetFacilities sections.
- [ ] CSV import: `handleImport` (`:2595`) with no file selected; a successful import rendering `importSummary` (`:2557`); `afterWorkOrderImport` (`:2575`) with and without `chainOwnsEnrichment`; an error surfacing through `friendlyError`.
- [ ] Export: `handleFilteredExport` (`:2654`) sends the current filters and `variant: "full"`; `handleClientExport` (`:2666`) sends the client variant; `exportScopeLabel` (`:2617`) per scope. `downloadExport` (`:2622`) — with the object-URL stub, assert the anchor got `download = filename` and was clicked, the button is re-enabled in `finally`, and the **header-only blob** produces the "downloaded an empty file" message with no `success` class.
- [ ] NetFacilities enrichment: `runNetFacilitiesEnrichment` (`:2360`), `pollNetFacilitiesJob` (`:2330`) with fake timers over the 3 s interval, `describeNetFacilitiesJob`/`netFacilitiesCountsMessage`/`renderNetFacilitiesJob` (`:2296`/`:2281`/`:2324`) for each job state including failure, and that polling stops on a terminal state (`netFacilitiesPollingJobId` cleared).
- [ ] Cloud auth: `refreshNetFacilitiesCloudSession` (`:2388`) and `updateNetFacilitiesCloudControls` (`:2399`) — the enabled/disabled/hidden state of the sign-in, cancel and import-download buttons for each capability shape; `startNetFacilitiesCloudAuthentication`, `cancelNetFacilitiesCloudAuthentication`, `importNetFacilitiesCloudDownload`; `maybeHandleChainCompletion` (`:2476`) fires once per completion (`handledChainCompletion`).

**Test.** Every NetFacilities job/capability state renders; the poll timer is cleaned up.

---

### Task 11: The action-coverage meta-test

**Goal.** The mechanical guarantee P4 depends on. This is the phase's success check — build it last, when the tests it audits exist.

**Files.** `views/workOrders/actionCoverage.test.js`.

**Steps.**
- [ ] Read `backend/static/views/workOrders.js` and the `pages/work-orders.html` fragment; collect every `data-action="…"` literal and every `action === "…"` comparison into one set. Assert the two agree — a rendered action with no branch, or a branch with no renderer, is itself a finding.
- [ ] Read every `*.test.js` under `tests/frontend/views/workOrders/` (excluding this file) as text; assert each action string appears in at least one of them.
- [ ] Fail with the missing action names listed, not a bare count.
- [ ] Assert the set size is 26 with the list inline, so *adding* an action to the source also lands here deliberately rather than silently widening the audit.
- [ ] Same pattern for the eleven exports: assert `workOrders.js`'s export list equals the frozen eleven names, so P4 cannot drop a re-export.

**Test.** Delete one action's tests locally, confirm the meta-test names it, restore.

---

### Task 12: Record coverage and file the findings

**Goal.** Close the phase per the standing rules.

**Files.** `docs/open-work.md`, `docs/current-state.md` (one line only if the coverage story changed).

**Steps.**
- [ ] `npm run test:ci`; record the `backend/static/views/workOrders.js` line and branch coverage in the commit message. Not gated — P7 gates.
- [ ] File every suspected bug found during Tasks 2–10 as a line in `docs/open-work.md`, each naming the file, the line, and the observed behaviour. Nothing is fixed in P2.
- [ ] Confirm CI's `frontend` job is green and the suite runs with no database.

**Test.** `npm test` green; CI green.

---

## Done when

- [ ] `npm test` and the CI `frontend` job are green.
- [ ] All 26 `data-action` branches, all eleven exports, and every role predicate are exercised.
- [ ] The meta-test passes and fails correctly when a test is removed.
- [ ] Every suspected bug is filed in `docs/open-work.md`; no file under `backend/static/` or `backend/app/` was modified.

## Deliberately not in P2

- Any production change, including adding a test hook to `realtime.js`. P4 owns the only production edits in this effort.
- Fixing anything the characterization tests reveal.
- `workOrderRequests.js`, `catalogueRequest.js`, `billingEditor.js`, `adminReview.js` — imported by this module but owned by P7. Stub nothing; let them execute, and assert only at the `workOrders.js` boundary.
- Real-browser concerns (CSP enforcement, service worker, real fetch). P3.

## A note on characterization

The temptation in Task 5 and Task 6 is to assert what the code *should* do. Don't. A characterization suite that encodes an intention rather than the behaviour goes red during P4's mechanical move and gets "fixed" by editing the test — which destroys the only signal the split had. Assert the observed string, the observed request, the observed class. Where the observed thing looks wrong, add a comment saying so and file it in Task 12.
