# Frontend Test Harness — P7c (Low Stock) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task, **inline in the session — no subagents** (`CLAUDE.md` forbids them here). Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Status: go-ahead given 2026-09-14 ("Begin P7C"). Third P7 chunk; three follow.**

**Goal:** Characterization coverage for `views/lowStock.js` (267 lines: the list, the three recency buckets, the threshold control, the sequence guard, the realtime reload) and `views/lowStockCard.js` (196 lines: the card body, the additional-barcode rows, the item save at the `saveItemCore` wire, the count correction), plus the action audit for the card's four `data-action`s.

**Architecture:** Tests only, on the P0 harness. `lowStock.js` is the entry point despite the `lowStock ↔ lowStockCard` cycle (parent deviation 7): `mountView("views/lowStock.js")` after `setTestUser`. One page fixture, `helpers/lowStock.js`, since two test files mount it. One factory, `lowStockItem()`, with a drift row against `backend/app/schemas/items.py` (`LowStockItemResponse`). No timers in either module; fake timers only for the reconnect backoff. The clock is pinned with `vi.setSystemTime` so the bucket boundaries are exact.

**Spec:** `docs/superpowers/specs/2026-09-10-frontend-test-harness-design.md` §3.2–3.3
**Parent plan:** `docs/superpowers/plans/2026-09-14-frontend-test-harness-p7.md` (the P7c bullets are the requirement set; deviations 7, 8 and 9 apply)
**Depends on:** P1 (`saveItemCore`'s ladder, `confirmArchivedReuse`), P5d (`helpers/dialogs.js::answerConfirm`), P6d (`itemEditor.test.js` owns the barcodes-first order and the archived-reuse retry), P7a (`helpers/realtime.js`).

## Global constraints

- Tests only. No edit under `backend/static/` or `backend/app/`.
- Characterization, not correction. Findings → `docs/open-work.md` → `N-P7-CHARACTERIZED`.
- No `vi.mock` of any app module. Seams: `fetch` (MSW), `WebSocket` (`helpers/realtime.js`), `Date` (`vi.setSystemTime`), the real confirm overlay.
- `onUnhandledRequest: "error"` stays on.
- One mount per test. `afterEach`: `restoreLowStock()` (realtime disconnect + `stopRecording`); the global hook restores real timers and the real clock.
- Commit messages end with the attribution lines the session provides.

## Already pinned — do not re-cover

- P1 / P6d: `saveItemCore`'s order (barcodes PATCH first), the barcode-change warning text, the archived-reuse 409 → prompt → retry with `override_archived`. This chunk asserts the wire from the Low Stock card only: which requests, which bodies, and the card's own copy on success / cancel / failure.
- P5 (`views/nav.test.js`): `showPage("low-stock")` calls `loadLowStock`.

## Deviations from the parent's P7c text, decided here

| # | Deviation | Why |
| --- | --- | --- |
| D1 | The fixture pins the clock (`mountLowStock({now})`, default `LOW_STOCK_NOW = 2026-09-10T12:00Z`), not only the bucket tests. | The factory's `last_dispensed_at` is one hour before that instant; against the real clock every default row would land in `stale` and the tab-fallback would fire under every unrelated test. |
| D2 | The `EMPTY_TEXT` table is pinned as unreachable by construction, not by a test that reaches it: the fallback in `render` runs first, and an all-empty queue is answered earlier. The test asserts the message the fallback leaves and that none of the three strings ever paints. | Parent D5 names it; there is no input that reaches the branch. |
| D3 | `saveCorrection`'s `!Number.isFinite` half is pinned the way P7a pinned `userRequests.js`'s: a `type="number"` input sanitises non-numeric text to `""`, so the blank branch answers first. Filed as the same class. | Same shape as the N-P6 / N-P7 rows already on file. |

---

### Task 1: the factory and the drift row

- [x] `helpers/factories.js`: `lowStockItem(overrides)` = `item()` plus `low_stock_threshold: 5`, `quantity: "2"`, `dispensed_last_7_days: "4"`, `last_dispensed_at: "2026-09-10T11:00:00Z"`.
- [x] `unit/api.endpoints.test.js`: `["lowStockItem", "backend/app/schemas/items.py"]`.

### Task 2: `helpers/lowStock.js`

- [x] `mountLowStock({role = "admin", rows = [], handlers = [], now = LOW_STOCK_NOW, load = true})` — `vi.setSystemTime(now)`; handlers first, then `GET /items/low-stock → rows`; `setTestUser`; `startRecording`; `mountView("views/lowStock.js")`; `await loadLowStock()` unless `load: false`; `clearRequests()`. Returns `{mod, currentUser}`.
- [x] Getters: `el.list / message / refresh / tabs`, `tabBtn(bucket)`, `cards()`, `cardFor(id)`, `rowMessage(card)`, `editMessage(card)`, `thresholdInput(card)`, `listGets()`; `answerConfirm`, `confirmTitle` re-exported; `connectLowStock(page)`; `restoreLowStock()`.

### Task 3: `views/lowStock.test.js`

- [x] Load and cards: the loading copy, the card's tag / class / dataset, the summary through `quantityText`, the body fields, the threshold input attributes, the empty-queue copy, the failure copy with the list emptied, background skipping the loading copy, the two sequence-guard races.
- [x] Buckets: the six boundary rows (`it.each`), the tab labels, the counts summing, server order within a bucket, the fallback on first load and on a background reload, the click filter with no request, the no-op clicks, open cards restored by id.
- [x] Threshold: blur commit, Enter commit (`defaultPrevented`), the three invalid inputs, unchanged, the PATCH body, `defaultValue` + "Saved." + the background GET, failure revert, re-enabled either way.
- [x] Realtime: on the page, elsewhere, reconnect.

### Task 4: `views/lowStockCard.test.js`

- [x] The body: five fields prefilled, null price / link → `""`, a row per code, the correction count prefilled.
- [x] `add-barcode`, `remove-barcode`.
- [x] `save-item`: the required trio, the duplicate, blank rows skipped, the unchanged-list write, the changed-list writes, the barcode-change confirm (No, Yes), "Item saved." + reload, failure copy.
- [x] `save-correction`: the three validations, the POST body, "Count corrected." + reload, failure copy.
- [x] A `[data-action]` outside a card is ignored.

### Task 5: `views/lowStockActionCoverage.test.js`

- [x] `auditActions` — sources `[lowStockCard.js]`, default patterns, frozen `["add-barcode", "remove-barcode", "save-correction", "save-item"]`, behaviour file `lowStockCard.test.js` only.

### Task 6: the run, the findings, the commit

- [x] Success checks: `lowStockItem()` passes the drift guard; delete one action's tests and the audit names it. Restore.
- [x] Findings → `N-P7-CHARACTERIZED` (three rows: the message-class loss that leaves a card's next commit / save dead, the unreachable `EMPTY_TEXT` table, the dead `isFinite` half).
- [x] `npm test` green (1909 / 70, 223 s); wall-clock in the parent's table; committed. No push.
