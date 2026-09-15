# Frontend Test Harness — P7 (Remainder, then close the gate) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan chunk-by-chunk, **inline in the session — no subagents** (`CLAUDE.md` forbids them here). Each chunk gets its own plan file (`2026-09-1x-frontend-test-harness-p7<x>-<module>.md`) written at the start of its session, as P5b–P6g did; this file is the requirement set those plans argue from. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Coverage for the nine files the roadmap leaves to P7 — `userRequests.js` + `userRequestCards.js`, `adminReview.js`, `lowStock.js` + `lowStockCard.js`, `workOrderRequests.js` + `catalogueRequest.js`, `scan-test.js`, `service-worker.js` (2,714 lines, 28 commits) — then the coverage threshold turned blocking and the harness folded into the living docs. These nine are the only files under 60 % in today's report; everything else is P0–P6.

**Architecture:** Tests only, on the P0 harness and the P5/P6 fixtures. Three page views get a fixture each (`helpers/userRequests.js`, `helpers/lowStock.js`, an inline mount for Admin Review); the Request card mounts through P2's `helpers/workOrders.js::openCard`, which already answers `/work-orders/:id/requests`; `catalogueRequest.js` and `service-worker.js` mount directly; `scan-test.js` gets the one new document fixture in the phase (`helpers/scanTest.js`), built the way `shell.js` builds the shell. Four of the views subscribe to realtime, so one shared `helpers/realtime.js` replaces a fifth inline copy of the fake-socket wiring.

**Tech Stack:** Vitest, jsdom, @testing-library/dom, @testing-library/user-event, msw.

**Spec:** `docs/superpowers/specs/2026-09-10-frontend-test-harness-design.md` §3.2–3.3, §5, §6
**Roadmap:** `docs/superpowers/plans/2026-09-10-frontend-test-harness-roadmap.md` (P7)
**Depends on:** P0–P6, all landed. P2's `helpers/workOrders.js`, P5d's `helpers/requests.js` + `helpers/dialogs.js`, P5g's `helpers/media.js` (`stubCanvas`, `stubRaf`, `stubVideo`, `stubZXing`, `stubUserMedia`, `stubPermissions`), P5h's `helpers/actionAudit.js`, P1's `unit/itemSave.test.js` and `unit/adminReviewReceipt.test.js`.

## Entry gate — verified 2026-09-14 for this plan

- [x] `npm run test:ci` green, run to completion: **1738 tests / 62 files, 182 s**; 82.56 % statements / 72.71 % branches / 88.18 % functions / 84.16 % lines. The report already lists untested files (`scan-test.js`, `service-worker.js` at 0 %), so the roadmap's "a new file without a test is visible" check holds with no config change.
- [x] `pytest -m e2e` green — re-run at P7f, 2026-09-15: **18 passed, 1709 deselected, 52 s**.
- [x] No other session is mid-commit in this checkout.
- [x] **No push until P7f is committed** (owner decision, 2026-09-14). Pushing `main` deploys production. P7a–P7d went out before that decision; P7e and P7f are held.

## Global constraints

- **Tests only.** No change under `backend/static/` or `backend/app/`. `vitest.config.js` and `.github/workflows/ci.yml` change in P7f and nowhere else.
- **Characterization, not correction.** Assert what the code does; comment the assertion where it looks wrong; file it under `N-P7-CHARACTERIZED` in `docs/open-work.md` at the chunk's close.
- **No `vi.mock` of any app module.** Seams: `fetch` (MSW), `WebSocket` (`helpers/fakeSocket.js`), timers, browser globals (`helpers/media.js`, `helpers/browserStubs.js`, a `self` stub for the worker), the shell's real dialog overlays.
- **`onUnhandledRequest: "error"` stays on.**
- **Mount before import.** All nine capture element ids or attach listeners at import.
- **Fake timers where the module has a timer** (`userRequests.js` 250 ms debounce; `scan-test.js` 500 ms focus retry) with `vi.getTimerCount()` 0 in `afterEach`; real timers elsewhere.
- **Factories, not literals.** `userRequest()` and `lowStockItem()` land in `helpers/factories.js` with drift rows in `unit/api.endpoints.test.js` in the same commit. The counts payload (`dict[str, dict[str, int]]`, no response model) is an inline literal.
- **One chunk, one session, one green suite.** Done = `npm test` green, the chunk's success check passes, findings filed.
- Commit messages end with the attribution lines the session provides.

## Ten deviations from the roadmap text, decided here

1. **P7 is six chunks.** The roadmap's P7 is one section over nine files plus the gate; the standing rule (P5's D1) makes the chunk the unit of work.
2. **`scan-test.js` is covered in Vitest, not excluded from coverage.** Its own document fixture parses `scan-test.html` the way `shell.js` parses the shell. Excluding it was rejected: it is the highest-churn file in the phase (7 commits) and holds the field-tested levers (crop, TRY_HARDER, 720p, 3-consecutive) the production decoder was tuned from; every seam it needs exists since P5g.
3. **`service-worker.js` is covered in Vitest, not E2E.** A ~25-line `self` stub (`vi.stubGlobal("self", …)` then `importView`) is not the disproportionate case the roadmap's step 2 allows for, so the E2E fallback is not taken. `importView`, not `new Function`, so v8 sees the file.
4. **`catalogueRequest.js` mounts directly.** It imports only `api.js` / `format.js`; its host wirings are already pinned (P2 `editorActions.test.js` for `work_orders`, P5c `items.test.js` for `find_item`, P7d for `request_card`). Its file asserts the document-level form lifecycle once, plus the pure `catalogueRequestPromptHtml` contract.
5. **`workOrderRequests.js` mounts through `openCard`.** `workOrderList.js::paintDetail` calls `mountWorkOrderRequests(cardEl, detail, {items: getAllItems()})`, so the fixture's `requests` and `items` arguments are the whole setup. P2 already pins `material_request_id` on the `add-item` wire (`editorActions.test.js` 376–382), so `add-requested` is asserted at the dataset stamp and no further.
6. **Admin Review gets no fixture file.** One consumer; a local `mountAdminReview()` in the test file, as P6g did for push. `adminReview.js` imports the `workOrders.js` barrel and nothing imports it back, so it is the entry point of its own graph.
7. **`lowStock.js` is the entry point despite the `lowStock ↔ lowStockCard` cycle.** The only cross-binding read is `loadLowStock`, a hoisted function declaration, and neither module calls the other at top level — the P5c/P6e TDZ hazard does not arise. Record, do not work around.
8. **Three audits, not five.** `lowStockCard.js` (default `data-action` patterns), `workOrderRequests.js` (`data-request-action="…"` / `action === "…"`; P2's audit excludes this file by name, `actionCoverage.test.js` 22–26), and the User Requests pair (rendered in `userRequestCards.js`, handled in `userRequests.js`; `sources` takes both; class-name patterns as P6f's did). `adminReview.js` and `catalogueRequest.js` have single-wired buttons and no delegation table — no audit, per P6's deviation 6.
9. **`helpers/realtime.js` is new and shared.** `connectFakeRealtime(activePage)` → `{emit(type, extra), reconnect(), setActivePage(name), disconnect()}` wrapping `installFakeWebSocket` + `setActivePageGetter` + `connectRealtime`, exactly what `helpers/hub.js` 112–121 and `views/workOrders/realtime.test.js` 33–36 each do inline. Those two are left as they are; adoption is not P7 work.
10. **The gate covers all four metrics.** Statements, branches, functions and lines each at its `npm run test:ci` value at P7e's close, minus 2, rounded down. Ratcheted by hand at phase closes; `thresholds.autoUpdate` is not used because it rewrites `vitest.config.js` on every local run.

## Chunk sequencing

Churn order, with the two cheap page fixtures ahead of the expensive Work Orders mount, the new document fixture second to last, and the gate last by definition.

| Chunk | Module(s) | Lines | Commits | Why here |
| --- | --- | --- | --- | --- |
| P7a | `userRequests.js` + `userRequestCards.js` + `helpers/userRequests.js` + `helpers/realtime.js` + `userRequest()` + the audit | 878 | 8 | Highest churn in the phase; the page every other request surface resolves into. |
| P7b | `adminReview.js` | 210 | 4 | Small, own entry point; may share a session with P7a as P6b did with P6a. |
| P7c | `lowStock.js` + `lowStockCard.js` + `helpers/lowStock.js` + `lowStockItem()` + the audit | 463 | 5 | Second page fixture; the `itemSave.js` wire from a second host. |
| P7d | `workOrderRequests.js` + `catalogueRequest.js` + the audit | 414 | 3 | Rides P2's fixture, the phase's most expensive mount per test. |
| P7e | `scan-test.js` + `service-worker.js` + `helpers/scanTest.js` | 749 | 8 | The only new document; the only non-SPA code. |
| P7f | the gate + the docs | — | — | Needs P7e's number. |

---

### P7a — User Requests

**Files.** Create `tests/frontend/helpers/userRequests.js`, `tests/frontend/helpers/realtime.js`, `tests/frontend/views/userRequests.test.js` (the page, tabs, cards), `tests/frontend/views/userRequestsActions.test.js` (the row actions), `tests/frontend/views/userRequestsFulfil.test.js` (the fulfilment panel — landed as three view files, not two; chunk plan D3), `tests/frontend/views/userRequestsActionCoverage.test.js`. Modify `helpers/factories.js` (`userRequest()` against `UserRequestResponse`: every field of the schema with `request_type: "material_request"`, `status: "open"`, `details: {quantity: "2", product_link: null, note: null}`, string Decimals, `work_order_archived: false`, `skipped: []`, `updated: false`), `unit/api.endpoints.test.js` (drift row).

- [x] **`helpers/userRequests.js`:** `mountUserRequests({role = "admin", requests = [], counts = {}, handlers = []})` — `server.use(...handlers, GET /user-requests/counts → counts, GET /user-requests/ → requests narrowed by the `status` and `type` query params)` so a tab or status switch is observable; `setTestUser`; `startRecording`; `mountView("views/userRequests.js")`; `await loadUserRequests()`; `clearRequests()`. `el` getters (status, tabs, refresh, list, message), `cards()`, `cardFor(id)`, `tab(type)`, `panelOf(card)`; `answerConfirm` re-exported; `restoreUserRequests()` = `stopRecording` + realtime disconnect.
- [x] **`helpers/realtime.js`:** deviation 9. `disconnect()` calls `disconnectRealtime()` and `ws.restore()`; every fixture's restore calls it so no reconnect timer survives a test.
- [x] **Tabs and status:** the import-time `selectTab("material_request")` (Material active, `aria-selected`, Open/Stocked/Resolved); a tab click → active swap, options rebuilt (the default tab drops Stocked; a current value no longer offered → `open`, kept when offered), `GET /user-requests/?status=…&type=…`; counts → `(n)` per tab, blank for zero or missing, a counts 500 swallowed with the list intact; refresh and a status change reload; the message copy — `No open material requests.`, `1 open request.`, `N open requests.`; a failed list → `friendlyError` copy, list emptied.
- [x] **Cards, through the list:** classes `user-request-{status}` / `user-request-type-{type}`, dataset id / itemId (`""` for null) / requestType; heading per type (`searched_text || "Unnamed item"`, `item_name || "Unknown item"`); `requestTypeLabel` four labels + the snake-case fallback, `statusLabel`; the four bodies — material (`stock_cycles > 1` line, the Stocked line, the link line with `rel="noopener"`, "Requested by Unknown"), catalogue (the Find-Item hint when no work order; "Added as"), recount (the three frozen figures), missing price (`work_order_numbers` joined vs the single number); `formatDate` (null → "Unknown time", unparseable → the raw string, else `toLocaleString()`); the resolution block only when resolved; an open missing-price card prefills price and link from `item_price` / `item_product_link`; actions per type × status (material open: stock + resolve + edit; stocked: the waiting hint naming the work order or "the work order" + resolve + edit; resolved: reopen + edit; catalogue open: the `work_order_archived` warning + Fulfil + Edit, else "Fulfilled as X." / "Fulfilled."; recount open: the count fix with `id="user-request-count-{id}"`; missing price open: the two inputs); the three `tipHtml` keys render a `.tip-btn` (they are JS strings, outside P1's `data-tip` audit).
- [x] **Resolve / reopen:** confirm "Resolve this user request?" / "Reopen this user request?" — No → nothing; Yes → disabled → `PATCH /user-requests/{id}` with `status` and the other three keys null → reload; failure → re-enabled + "Could not resolve that request." / "…reopen…".
- [x] **Mark stocked:** confirm "Mark this item as stocked and notify the crew?" → `POST /user-requests/{id}/mark-stocked` `{}` → reload; failure copy, re-enabled.
- [x] **Edit:** open → `editFormHtml` per type (catalogue: text / qty / note; material: qty / link / note; recount and missing price: the snapshot hint only); cancel empties the panel; save — blank message → "The message cannot be blank."; material: an invalid `type=url` value → "Enter a valid product link.", details `{quantity: raw || "1", product_link: null when blank, note: null when blank}`; catalogue: blank text → "Describe the item that was searched for.", details `{searched_text, quantity, note}`; the other two → `details: null`; → `PATCH` `{message, details}` (status and note null) → reload; failure → re-enabled + copy.
- [x] **Fulfil (catalogue):** open → `fulfillFormHtml` (link mode checked, search and new-item name prefilled from `searched_text`, create pane hidden), then `GET /user-requests/{id}/siblings` → `siblingsHtml` (none → "No other open requests match this material."; rows pre-checked, `(closed — will be skipped)`, "no work order", qty `"1"` default, "Unknown"; the title's count and plural) or the 500 hint "Could not check for related requests…"; the mode radio toggles the panes; search — an input clears the pick and "Selected:" text, blank → results emptied, 250 ms debounce (fake timers) → `GET /items/?q=` → ≤ 8 `itemChoiceHtml` buttons (`formatMoney(price) || "no price"`), the no-match hint, a 500 → the `<p class="error">`; a pick → `dataset.pickedItemId`, "Selected: name", results emptied; save — link mode with no pick → "Search and pick an item first."; create mode → barcode / name / location required in that order, `quantity: Number(value || 0)`, `price` null when blank, `product_link` null when blank; confirm "Fulfil this catalogue request?" plus the sibling clause when any box is checked → `POST /user-requests/{id}/fulfill` `{item_id, new_item, sibling_ids}` → reload → a non-empty `result.skipped` joined into an error message *after* the reload's own copy; failure → copy + re-enabled; cancel empties the panel.
- [x] **Count correction:** blank / non-finite / negative → "Enter the corrected count (zero or more)." + focus; blank reason → "Enter a reason for the correction." + focus; → `POST /transactions/adjust` `{item_id, new_quantity, reason}` → reload; failure copy, re-enabled.
- [x] **Price + link:** blank / ≤ 0 → "Enter an item price greater than $0.00." + focus; blank or invalid link → "Enter a valid product link." + focus; → `PATCH /items/{id}` `{price, product_link}` → reload; failure copy.
- [x] **Realtime:** `user_request.changed` on `user-requests` → reload; on another page → nothing; a reconnect on the page → reload.
- [x] **Audit:** sources `[userRequestCards.js, userRequests.js]`; `renderedPattern: /<button[^>]*class="[^"]*\b(user-request-[a-z-]+)\b/g`; `handledPattern: /event\.target\.closest\("\.(user-request-(?!card|item-search|mode)[a-z-]+)"\)/g` — the three structural selectors excluded by name; frozen `["user-request-action", "user-request-count-save", "user-request-edit-cancel", "user-request-edit-open", "user-request-edit-save", "user-request-fulfill-cancel", "user-request-fulfill-open", "user-request-fulfill-save", "user-request-item-pick", "user-request-price-save", "user-request-stock"]`; behaviour files this chunk's, via `behaviourExclude` as P6e/P6f did.

**Test.** `npm test` green; timers 0; `userRequest()` passes the drift guard; every export of `userRequestCards.js` called by name. Delete one action's tests; the audit names it. Restore.

---

### P7b — Admin Review

**Files.** Create `tests/frontend/views/adminReview.test.js`. No factory: `workOrderCard()`, `workOrderDetail()`, `workOrderItem()` (P2) are the shapes.

- [x] **`mountAdminReview({role = "admin", cards = [], details = [], handlers = []})`, local:** `server.use(...handlers, GET /work-orders/:id off `details`, GET /work-orders/ → cards)`; `setTestUser`; `startRecording`; `mountView("views/adminReview.js")`; `await loadAdminReview()`; `clearRequests()`; `connectFakeRealtime("admin-review")`.
- [x] **`loadAdminReview`:** "Loading Review work orders…" then `GET /work-orders/?status=review` (assert the query); a `<button class="… admin-review-card">` per card with `workOrderCardClass` (P2 owns it — assert `admin-review-card` and the urgent class only), `aria-label`, the number, "Review", `locationText` (` · ` join, "No location"), `assignedNames` ("Unassigned", falsy names dropped); "No work orders are waiting for Admin Review." vs `1 work order waiting for review.` / `N work orders…`; a failed foreground load → list emptied + "Could not load Admin Review."; a failed background load → list and message untouched; `background: true` skips the loading copy; the request-id race — an older, slower list answer (a handler the test resolves by hand) never repaints over a newer one.
- [x] **Select:** click → "Building receipt…" → `GET /work-orders/{id}` → title `WO n Receipt`, textarea value equal to `buildAdminReviewReceipt(detail).text` computed in the test (P1 owns the text), section unhidden, `.selected` moved, Reopen enabled, Close disabled iff a line has no `unit_price` with "Cannot close until a price is added for: …" vs "Receipt ready — select all and copy."; textarea focused and scrolled to origin; the list message cleared; a failed detail → "Could not load that work order."; a stale selection (two clicks, the first answering last) discarded.
- [x] **Reopen:** no selection → nothing; confirm "Return WO n to In-Progress for corrections?" No → nothing; Yes → both buttons disabled → `PATCH /work-orders/{id}` `{status: "in_progress"}` → the list reloads → "WO n returned to In-Progress. The receipt remains available for reference." — **both buttons stay disabled after success** until another card is selected; file it. Failure → Reopen re-enabled, Close re-enabled iff no missing prices, "Could not return that work order.".
- [x] **Close:** confirm "Close WO n? It will leave the live work-order views." → `POST /work-orders/{id}/archive` → reload → "WO n closed. The receipt remains available for copying."; failure → both re-enabled + "Could not close that work order.".
- [x] **Realtime:** `work_order.review_queue.changed` on the page → a background reload that keeps the receipt, the selection and re-applies `.selected` to the rebuilt card; on another page → nothing; reconnect → reload.

**Test.** `npm test` green. Success check: rename `admin-review-close-btn` in `pages/admin-review.html`; the module's import throws on the null listener and the file goes red. Revert.

---

### P7c — Low Stock

**Files.** Create `tests/frontend/helpers/lowStock.js`, `tests/frontend/views/lowStock.test.js` (list, buckets, threshold), `tests/frontend/views/lowStockCard.test.js` (the card body), `tests/frontend/views/lowStockActionCoverage.test.js`. Modify `helpers/factories.js` (`lowStockItem()` = `item()` plus `low_stock_threshold: 5`, `quantity: "2"`, `dispensed_last_7_days: "4"`, `last_dispensed_at` one hour before the test clock; drift row against `backend/app/schemas/items.py`).

- [x] **`helpers/lowStock.js`:** `mountLowStock({role = "admin", rows = [], handlers = []})` — `GET /items/low-stock → rows`; `setTestUser`; `startRecording`; `mountView("views/lowStock.js")` (deviation 7); `await loadLowStock()`; `clearRequests()`. Getters: list, message, refresh, tabs, `tabBtn(bucket)`, `cards()`, `cardFor(id)`, `rowMessage(card)`, `editMessage(card)`; `answerConfirm` re-exported; `restoreLowStock()`. Bucket tests pin the clock with `vi.setSystemTime`.
- [x] **Load and cards:** "Loading low stock..." then a `<details class="low-stock-card">` per row with dataset id / barcode / barcodes JSON; summary name, `N on hand` through `quantityText` (`"3.00"` → `3`), `7-day used: N`; body barcode, location, the threshold input (`value`, `aria-label`, `min="1"`), the row message, then the card body; "Nothing is below its threshold." on an empty queue; failure → "Could not load low stock." + list emptied; the sequence guard — an older, slower answer discarded, and an older failure ignored.
- [x] **Buckets:** `< 24 h` → day, `< 7 d` → week, else / null / unparseable → stale; exactly 24 h is week (exclusive); tab labels `Label (n)`; the three counts sum to the queue; server order kept within a bucket; the chosen tab falls to the first filled bucket when its own is empty — on first load and on a background reload that emptied it; a tab click filters with no request, a same-bucket or non-bucket click is a no-op; open cards restored by id after a reload. **`EMPTY_TEXT` is unreachable:** the fallback runs before it and an all-empty queue is answered earlier — file it.
- [x] **Threshold:** commit on blur (capture) and on Enter (`preventDefault` → blur); non-integer / `< 1` / blank → value reverted to `defaultValue` + "Threshold must be a whole number of at least 1."; unchanged → no request; changed → disabled meanwhile → `PATCH /items/{id}/low-stock-threshold` `{low_stock_threshold}` → `defaultValue` updated, "Saved.", a background reload (second `GET`, no loading copy); failure → reverted + "Could not save that threshold."; re-enabled either way.
- [x] **Card body (`lowStockCard.js`):** the five fields prefilled (`""` for a null price / link), a row per additional code; `add-barcode` appends an empty row; `remove-barcode` removes its row; `save-item` — the required trio → "Barcode, name, and location are required."; a duplicate → `The barcode "X" is listed twice. Remove the duplicate.`; blank rows skipped; `saveItemCore` at the wire only (P1 owns the ladder): an unchanged list → `PATCH /items/{id}` alone with `price` parsed / null and `product_link` null when blank; a changed list → `PATCH /items/{id}/barcodes` first; a changed primary → the barcode-change confirm, No → `cancelled` → message cleared, no request, Yes → both writes; "Item saved." → background reload; failure → "Could not save the changes. Try again."; `save-correction` — blank / non-finite → "Enter a valid new count."; negative → "Enter a count of zero or more."; blank reason → "Enter a reason for the correction."; → `POST /transactions/adjust` `{item_id, new_quantity, reason}` → "Count corrected." → background reload; failure copy; a `[data-action]` outside a card ignored.
- [x] **Realtime:** `item.low_stock.changed` on `low-stock` → background reload; elsewhere → nothing.
- [x] **Audit:** sources `[lowStockCard.js]`, default patterns, frozen `["add-barcode", "remove-barcode", "save-correction", "save-item"]`.

**Test.** `npm test` green; `lowStockItem()` passes the drift guard. Delete one action's tests; the audit names it. Restore.

---

### P7d — The Request card and the catalogue prompt

**Files.** Create `tests/frontend/views/workOrders/requests.test.js` (the P2 family directory, P2's fixture), `tests/frontend/views/workOrders/requestsActionCoverage.test.js`, `tests/frontend/views/catalogueRequest.test.js`. No factory: `userRequest()` (P7a) is the request shape; `item()` the catalogue.

- [x] **Mount (via `mountWorkOrders({requests, items, cards, details})` + `openCard(0)`):** `requestFormHtml` + "Loading requests…" then the list and the stocked lines (a local `openCardWithRequests()` waits for `.wo-request-list` to settle); a failed `GET /work-orders/{id}/requests` → `<p class="error">` "Could not load requests." with `.wo-requested-lines` left empty.
- [x] **`requestListHtml`:** live vs resolved; "No open requests on this work order."; the resolved `<details>` "Show resolved (n)"; a line's type tag (Catalogue / Material), name (`searched_text || "Unnamed item"` / `item_name || "Unknown item"`), `qty details.quantity || "1"`, status label, `created_by_name || "Unknown"` · `formatWhen` (blank / raw / `toLocaleString`); Cancel only for material ∧ open ∧ `created_by_id === me` — the four-way matrix.
- [x] **`stockedLinesHtml`:** material ∧ stocked only; dataset request / item / name / quantity; `on hand item_quantity ?? "?"`.
- [x] **Search (document `input`):** other inputs ignored; typing clears `dataset.itemId` and the on-hand line; blank → hidden + emptied; `filterRanked` over the mount's `items` by name and barcode, ≤ 8 pick buttons with dataset id / name / quantity; no match → "No matching items." + the prompt with `source="request_card"`, the card's id and the searched text.
- [x] **pick / send / cancel / add-requested:** pick → `dataset.itemId`, the search filled, results hidden, `N on hand — Staff will verify the count.` vs `0 on hand.`, qty focused; send — no item → "Search and pick an item first."; qty ≤ 0 / NaN → "Enter a quantity greater than zero."; an invalid link → "Enter a valid product link." + focus; → disabled, "Sending…", `POST /user-requests/material-request` `{item_id, work_order_id, quantity, product_link|null, note|null}` → a second requests fetch → "Request sent. Staff have been notified." vs `updated: true` → "Updated your earlier request."; failure → re-enabled + "Could not send that request."; cancel → confirm "Cancel this material request?" No → nothing, Yes → `POST /user-requests/{id}/cancel` `{}` → refetch; failure → re-enabled + the copy in the card's positional message (`helpers/workOrders.js::message`); add-requested → `.wo-add-item` dataset itemId + materialRequestId, the search and qty filled, results hidden, the Materials section opened, qty focused — and no further (deviation 5).
- [x] **Realtime `user_request.changed`:** every open card refetches; a card with focus inside an open section is skipped; a closed card skipped; no page gate.
- [x] **Audit:** sources `[workOrderRequests.js]`, `renderedPattern: /data-request-action="([a-z-]+)"/g`, `handledPattern: /action === "([a-z-]+)"/g`, frozen `["add-requested", "cancel", "pick", "send"]`, behaviour files this chunk's.
- [x] **`catalogueRequest.test.js` (direct `mountView`, the prompt injected into `#app-root`):** `catalogueRequestPromptHtml` — an unknown source throws by name; blank / whitespace text → `""`; the three sources; `data-work-order-id` only when given; escaping. Open → the form with the text prefilled, qty 1, text focused; cancel → the button again; submit — blank text → "Describe the item you need." + focus; qty ≤ 0 / NaN → "Enter a quantity greater than zero." + focus; → disabled, "Sending…", `POST /user-requests/catalogue-request` `{searched_text, quantity, note|null, work_order_id|null, source}` → the whole prompt replaced by "Catalogue request sent to staff."; failure → re-enabled + `friendlyError` copy; a click outside any `.catalogue-request` ignored.

**Test.** `npm test` green. Delete one action's tests; the audit names it. Restore. Success check: rename `data-request-action="send"` in `workOrderRequests.js`; the audit and the send tests go red. Revert.

---

### P7e — The scan harness and the service worker

**Files.** Create `tests/frontend/helpers/scanTest.js`, `tests/frontend/views/scanTest.test.js` (boot, state, start / stop, torch, logs, knobs), `tests/frontend/views/scanTestDecode.test.js` (the frame loop, debounce, diagnostics), `tests/frontend/unit/serviceWorker.test.js`. Modify `helpers/media.js` (`stubClipboard({reject = null})` through the private `define`; helper change, allowed).

- [x] **`helpers/scanTest.js`:** `mountScanTest({zxing = true, permission = "prompt", media = {}, clipboard = {}})` — parse `backend/static/scan-test.html` with `DOMParser`, scripts stripped, replace `document.documentElement`; `stubCanvas()` **before** import (the module calls `getContext` at import); `stubRaf()`; `stubUserMedia(media)`; `stubPermissions(permission)`; `stubClipboard(clipboard)`; `stubZXing({ZXingBrowser: {BarcodeFormat: {UPC_A: 14, UPC_E: 15, EAN_13: 7, EAN_8: 6, CODE_128: 4}}})` when `zxing`; `importView("scan-test.js")`; `stubVideo(els.video)` after. Returns `{els, raf, canvas, media, zxing}`; `restoreScanTest()` = `restoreMediaStubs()`.
- [x] **Boot:** no global → the `<p>` inserted and the import rejects "ZXingBrowser global missing"; with it → the two boot log lines, `permissionsPrecheck` (no `navigator.permissions` → the unsupported line; `denied` → state "blocked" + the err line; a throwing `query` → warn), dashes everywhere in `renderDiag`.
- [x] **Config and reader:** `configSummary` strings from every knob; `buildReader` hints — key 2 the five formats, key 3 `true`, each absent when unchecked — rebuilt on Start and on the formats / TRY_HARDER change only while streaming; the crop change logs and re-renders; a debounce change logs and resets the window; a resolution change logs the warn.
- [x] **State machine:** the pill text / class and the Start / Stop `disabled` matrix over idle, requesting, streaming, stopping, error, blocked.
- [x] **Start:** the `startBtnLock` reentrancy; `getUserMedia` constraints (`facingMode: {ideal: "environment"}`, width / height from the resolution radio, `focusMode: {ideal: "continuous"}`, `audio: false`); `NotAllowedError` → blocked, any other → error; torch capability (`true` → "yes" + button shown; `false` → "exposed but unsupported"; absent → "no"; `getCapabilities` throwing → "n/a (threw)"); the focus fallback — not continuous ∧ continuous supported → after 500 ms (fake timers) `applyConstraints({advanced: [{focusMode: "continuous"}]})`, its success and throw branches logged; `play()` rejecting → warn; aimbox unhidden, `startTimestamp` set, streaming, one frame queued.
- [x] **Frame loop (`raf.flush()`):** no intrinsic size → re-queued only; crop on → the aim-box rect (80 % width, 3:1, centred, `Math.round`) vs off → the full frame; canvas resized only when the region changed; `drawImage` arguments; a miss (the reader throws) → an attempt recorded, no hit; a hit → `onHit`; `renderDiag` — resolution / facing / focus from the track, region `w x h  (p% of frame)`, attempts per second over the rolling 30, `p%  (h/t)`, mean latency, the window `n× text  |  …` and "(empty)"; every rolling list capped at 30.
- [x] **Hits and acceptance:** latest `text (FORMAT) [supported]` vs `[UNSUPPORTED]` through `formatName` (incl. `UNKNOWN(n)`); the window capped at 10; the consecutive streak reset by a different text and kept across misses; accept once and sticky — window mode → `count=5/10`, consecutive mode → `consecutive=3`, the accept log line and time-to-accept. **`"n/a"` for a null `startTimestamp` is unreachable** (a hit needs streaming, which sets it) — file it.
- [x] **Stop / reset / torch / copy:** stop while idle → nothing; otherwise `cancelAnimationFrame`, every track stopped (a throw → warn), `srcObject` null, state cleared, torch text reset, aimbox hidden, idle; `resetWindow` clears the window / streak / accept, keeps or nulls `startTimestamp` by state, dashes, logs; `toggleTorch` — no track → nothing; `applyConstraints({advanced: [{torch}]})` flips the label; a throw → err; `copyLogs` — `JSON.parse` the written text and assert its fields; a rejecting `writeText` → warn + the dump; `visibilitychange` hidden while streaming → stop; `beforeunload` → tracks stopped, a throw swallowed; the log ring capped at 200 with `scrollTop` at the bottom.
- [x] **`serviceWorker.test.js`:** a local `mountServiceWorker()` — `fakeSelf` with `addEventListener` capturing listeners by type, `skipWaiting`, `clients: {claim, matchAll, openWindow}`, `registration: {showNotification}`, all `vi.fn`; `vi.stubGlobal("self", fakeSelf)`; `importView("service-worker.js")`; `fire(type, event)`; `afterEach` → `vi.unstubAllGlobals()`. Install → `skipWaiting`; activate → `waitUntil(clients.claim())`; push — no `data` → the fallback title / body; JSON `{title, body}` → shown with `icon`, `badge`, `tag: "inventory-notification"`; a missing field → that field's fallback; `json()` throwing → the fallback; `notificationclick` — `notification.close()`, `matchAll({type: "window", includeUncontrolled: true})`, the first client with `focus` focused, a client without `focus` skipped, none → `openWindow("/")`, no `openWindow` → `undefined`; every `waitUntil` promise awaited.

**Test.** `npm test` green; timers 0. Success check: change `AIMBOX_WIDTH_FRAC` to `0.5`; the crop test names the rect. Revert.

---

### P7f — The gate, then the docs

**Files.** Modify `vitest.config.js`, `.github/workflows/ci.yml`, `docs/current-state.md`, `docs/open-work.md`, `docs/project-summary.md`, `docs/superpowers/plans/2026-09-10-frontend-test-harness-roadmap.md`, this file.

- [x] `npm run test:ci` once, on an idle machine; record all four percentages and the wall-clock in this file's table.
- [x] **`vitest.config.js`:** `thresholds: {statements, branches, functions, lines}` each at its measured value minus 2, rounded down (deviation 10); replace the "Advisory in P0" comment with one line — ratcheted by hand at each phase close; no `autoUpdate`.
- [x] **`ci.yml`:** the frontend job's comment (lines 173–174) → coverage is blocking; thresholds live in `vitest.config.js`.
- [x] **Success check 1:** set `lines` to `100` → `npm run test:ci` exits non-zero with `ERROR: Coverage for lines … does not meet global threshold`. Revert. Record the exit code in the commit body.
- [x] **Success check 2:** untested-file visibility already holds (entry gate); record, no change.
- [x] **`current-state.md`:** rewrite the Vitest bullet (§Verification, one ~600-word paragraph) as a table keyed by fixture — module family · helper · what is pinned — net negative on words (the doc is ~1,000 words over its 16,500 budget); rows 97 (Low stock), 101 (User Requests), 105 (Live camera scan), 114 (Admin Review) name their test files; "Remaining views: uncovered, roadmap P7. Coverage reported, not gated, until P7." → the four thresholds.
- [x] **`open-work.md`:** PRO-008 evidence rewritten — harness complete, gate blocking at the four numbers, the remaining "Done when" is the browser journeys; status stays `In progress` (retiring it is the owner's call). New `N-P7-CHARACTERIZED` in the P6 table form (defect, pinned by) with every finding filed by P7a–P7e.
- [x] **`project-summary.md`** line 235–236: delete "there is no frontend test harness".
- [x] **Roadmap:** the P7 status row (date, chunk count, suite size, wall-clock, the four percentages, the four thresholds); "P7 | Not started — the only uncovered phase" → landed; the status block's push note.
- [x] **This file:** tick the boxes, the table, "Done when".
- [x] Commit. **Do not push.** Tell the owner the branch is ready and that pushing deploys.

**Test.** `npm run test:ci` green under the thresholds; `pytest -m e2e` green; the doc budgets in `CLAUDE.md` respected or net-improved.

---

## Suite budget

P6 closed at 182 s (coverage on, this machine, today). P7 adds an estimated 350–450 tests; P7d rides the Work Orders mount (P6d-class cost per test), P7e's document is small. Expect the close under 5 minutes.

- [x] Record wall-clock at each chunk's close, in the commit body and here.
- [x] Past ~6 minutes locally: stop and raise it. Closed at 173-183 s, well inside it.

| Close of | Tests / files | Wall-clock | Stmts / Branch / Funcs / Lines |
| --- | --- | --- | --- |
| P6 (entry) | 1738 / 62 | 182 s (`test:ci`) | 82.56 / 72.71 / 88.18 / 84.16 |
| P7a | 1812 / 66 | 198 s (`npm test`) | not measured — the gate reads P7e's close |
| P7b | 1848 / 67 | 169 s (`npm test`) | not measured — the gate reads P7e's close |
| P7c | 1909 / 70 | 223 s (`npm test`; a first run hit a `waitFor` flake in `auth.test.js`'s deep-link test, green alone and on rerun) | not measured — the gate reads P7e's close |
| P7d | 1983 / 74 | 174 s (`npm test`) | not measured — the gate reads P7e's close |
| P7e | 2076 / 77 | 173 s (`npm run test:ci`) | 96.30 / 86.68 / 98.54 / 98.29 |
| P7f | 2076 / 77 | 190 s (`npm run test:ci`) | thresholds: 94 / 84 / 96 / 96 (P7e minus 2, floored) |

## Done when

- [x] All six chunks committed, each green at commit time.
- [x] Every export of the nine files exercised; the three audits name their actions.
- [x] Findings filed under `N-P7-CHARACTERIZED`.
- [x] `npm run test:ci` fails on a coverage regression (success check 1 recorded).
- [x] `current-state.md`, `open-work.md`, `project-summary.md` and the roadmap read as above.
- [x] Nothing pushed.

## Deliberately not in P7

- Any production change, including the three findings this plan already names (D5).
- Re-covering `buildAdminReviewReceipt` (P1), `saveItemCore`'s ladder (P1, P6d), `workOrderCardClass` (P2), the `add-item` wire (P2), the two host prompts for `catalogueRequest.js` (P2, P5c).
- Adopting `helpers/realtime.js` in `helpers/hub.js` or `views/workOrders/realtime.test.js`.
- New E2E journeys; PRO-008's browser-journey "Done when".
- Pushing `main`.

## Drift register — found while planning P7 (2026-09-14)

| # | Drift | Where | Action |
| --- | --- | --- | --- |
| D1 | Roadmap P7 step 4 says to remove the "no frontend tests" line from `open-work.md`; that line lives in `project-summary.md` (line 236). `open-work.md`'s PRO-008 carries the status instead. | roadmap P7 | **File** — P7f edits the right file. |
| D2 | Roadmap P7 step 1 says `scan/barcode-decoder.js` and `scan/frame-debouncer.js` "moved to P5" — true and done; the sentence is history. | roadmap P7 | Delete at P7f. |
| D3 | The roadmap's coverage phrasing ("statements / lines") tracks two metrics; v8 reports four and the gate needs all four (deviation 10). | roadmap status rows | P7f's row records four. |
| D4 | `current-state.md` row 114 (Admin Review) still reads "manual UI check"; row 105 (Live camera scan) does not name `scan-test.js` under a test; row 97 (Low stock) names no frontend test. All true until P7 — listed so P7f does not miss them. | `current-state.md` | Closed by P7f. |
| D5 | The `EMPTY_TEXT` table in `lowStock.js` and the `"n/a"` time-to-accept in `scan-test.js` are unreachable; the Admin Review buttons stay disabled after a successful reopen. Found reading for this plan, not yet pinned. | P7b, P7c, P7e | Pinned and filed by those chunks. |
