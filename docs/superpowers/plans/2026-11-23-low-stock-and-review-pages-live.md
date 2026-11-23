# Low Stock, Admin Review and SMR Admin Review Live (W6) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This repo bars subagents unless the owner authorizes them for the task; default is inline execution.

**Goal:** Low Stock, Admin Review and SMR Admin Review patch in place on a live update, keep what the user has open or typed, and the open receipt or block always matches the server.

**Architecture:** One SQLAlchemy session listener emits `item.low_stock.changed` after commit for every changed item that is low before or after the change; the route and drain emits go. Each page builds its cards detached and hands them to `morphInto` with a `skip`. Both review pages share one small helper that refetches the selected order on an event and repaints only when the text or status differs.

**Tech Stack:** FastAPI, SQLAlchemy 2, pytest (real `TestClient`); plain ES modules, idiomorph 0.8.0 via `morph.js`, Vitest + jsdom + msw.

**Spec:** `docs/superpowers/specs/2026-11-23-low-stock-and-review-pages-live-design.md`. Rule numbers below are the spec's.

## Global Constraints

- CSP: classes only, no inline style or script.
- Every file stays under 500 lines (`adminReview.js` is 287, `lowStock.js` 267).
- Delegated listeners on the list elements stay; no per-card wiring.
- Emits are best-effort: a failed emit never fails a committed write.
- Envelope shape and audiences unchanged. No new event type, no new route.
- Subscribe handlers receive `{ activePage, envelope, reason }`; `reason === "reconnect"` or a missing `envelope.id` means "anything may have changed".
- One push for all of W6, after the owner's phone check. Pushing deploys: ask first.
- Shared checkout: stage explicit paths only. Targeted tests only. Vitest from PowerShell at `C:\Users\mcclu\Desktop\inventory_app_git` (`npx vitest run <file>`); pytest from `backend\` with the main checkout's venv.
- An existing test that fails is a finding. Change it only when it asserts retired behaviour (list wiped on reload, route-level low-stock emits, `restoreOpenCards`); name each in the commit body.
- Exact copy (spec rules 5–7):
  - `"An item you were editing is no longer low."`
  - `"This order was changed by someone else. The receipt is up to date."` / `"… The block is up to date."`
  - `"WO <number> was closed or sent back by someone else. The receipt remains for reference."` / `"… The block remains for reference."`

## Risk register

Spec risks 1–13 plus four found while planning.

| # | Hazard | Closed by |
|---|---|---|
| 1 | Typed value or added barcode row lost | T2 skip; tests per field type |
| 2 | Saved fields look typed forever | T3; test |
| 3 | `data-barcode(s)` change under a typed barcode | Accepted (spec) |
| 4 | Emit for a rolled-back write, or twice | T1 listener + removed route emits; envelope counts |
| 5 | Listener cannot tell "low before" | T1 reads attribute history in `after_flush` (still present there; `session.is_modified` in `request_events.py` relies on the same) |
| 6 | Bulk writes flood the page | T1 one envelope per id per commit; T2 coalescing |
| 7 | Live refresh steals focus or opens the picker | T5; test |
| 8 | Text replaced mid-copy | Accepted (owner pick) |
| 9 | Own action shows the "someone else" note | T5 compares before repainting and sets the own message last; test |
| 10 | Buttons act on a gone order | T5 disables; test |
| 11 | Tile paired with the wrong neighbour | T2/T4 ids; T6 census |
| 12 | iOS jump or lost caret | `keepPlace`; Phone |
| 13 | Pinned emitter tests and `current-state.md` stale | T1, T6 |
| 14 | Archived flag in "low before/after" | Ignored on purpose: the rule is quantity versus threshold only. An archive of a low item emits (it is low before and after); an extra event for an archived item is one harmless refetch. |
| 15 | A core-SQL item write bypasses the listener | None exists in `backend/app` (checked 2026-11-23); T1 docstring names the ceiling |
| 16 | Tab change morphs tab A into tab B and glows every card | T2: a tab change wipes the list first (first draw), as W5 does |
| 17 | Test suite fills the realtime handoff queue now that more writes emit | T1: confirm the existing autouse reset covers it, as W5 T1 did |

## Review Focus

1. Card open with a typed new count; another login dispenses the item → count and reason stay, "on hand" updates and the card glows (T2).
2. Threshold just saved; another login then changes the same threshold → the card shows theirs (T3).
3. Bulk stock write touching 50 low items → at most two list fetches (T2).
4. SMR block on screen; another login edits a labor line → status reads stale, Regenerate appears, note shown, focus untouched (T5).
5. Own Archive while the same order's event arrives → own "archived" message, never the "someone else" note (T5).

---

### Task 1: Low-stock events from one after-commit listener

**Files:**
- Create: `backend/app/item_events.py`
- Modify: `backend/app/models.py` (register beside `request_events`, line ~1312), `backend/app/routers/items.py` (remove the two `emit_low_stock_changed` calls, lines ~113 and ~429, and the import), `backend/app/routers/_stock_events.py` (remove `emit_low_stock_changed` and the per-crossing emit; keep `notify_item_low_stock`)
- Test: create `backend/tests/test_item_events.py`; update `backend/tests/test_low_stock_triggers.py:150-170`, `backend/tests/test_stock_events_flush.py:79-93`, any `test_realtime_emit.py` / `test_items_low_stock.py` case that patches a route-level emit

**Interfaces:**
- Produces: `item.low_stock.changed` with `id = str(item.id)`, once per item per commit, for every ORM write to an `Item` where `is_low(old quantity, old threshold) or is_low(new quantity, new threshold)`. Module attribute `item_events.realtime_service` (tests monkeypatch its `emit`).

- [ ] **Step 1: Write the failing tests** in `test_item_events.py`, copying the `sent` fixture and seed helpers from `test_request_events.py` (patch `item_events.realtime_service.emit`). Threshold 6 unless stated.

| Test | Write | Expect ids |
|---|---|---|
| `test_dispense_of_a_low_item_emits_once` | quantity 4 → 3 via `apply_transaction` | `[item.id]` |
| `test_restock_that_clears_the_condition_emits` | 4 → 20 | `[item.id]` |
| `test_dispense_that_crosses_into_low_emits` | 8 → 5 | `[item.id]` |
| `test_healthy_item_stays_silent` | 20 → 19 | `[]` |
| `test_correction_emits` | `apply_correction` on a low item | `[item.id]` |
| `test_threshold_edit_emits` | `PATCH /items/{id}/low-stock-threshold` 6 → 2 on quantity 4 | `[item.id]` |
| `test_name_edit_of_a_low_item_emits` | item update route, name only | `[item.id]` |
| `test_name_edit_of_a_healthy_item_stays_silent` | same, quantity 20 | `[]` |
| `test_create_below_threshold_emits` | `POST /items` quantity 1 | `[new id]` |
| `test_archive_of_a_low_item_emits` | `DELETE /items/{id}` | `[item.id]` |
| `test_rollback_emits_nothing` | change a low item, `db.rollback()` | `[]` |
| `test_two_writes_in_one_commit_emit_once` | two flushes on one item, one commit | `[item.id]` |
| `test_untouched_item_in_the_session_stays_silent` | load a low item, commit another row | `[]` |

- [ ] **Step 2: Run** `pytest tests/test_item_events.py -q` → FAIL (module missing).
- [ ] **Step 3: Implement `item_events.py`** on the `request_events.py` pattern: `after_flush` notes ids into `session.info["item_events"]`, `after_soft_rollback` forgets, `after_commit` emits with the guarded loop. For a dirty item, old values come from `sqlalchemy.inspect(obj).attrs.<name>.history.deleted` (fall back to the current value when empty); new items are judged on current values only; use `domain.low_stock.is_low`. Docstring names risks 14 and 15.
- [ ] **Step 4: Remove the route and drain emits**; register the module in `models.py`.
- [ ] **Step 5: Update the retired assertions**: the two flush tests now expect no envelope from `flush_stock_events` (push scheduling assertions stay).
- [ ] **Step 6: Run** `pytest tests/test_item_events.py tests/test_low_stock_triggers.py tests/test_stock_events_flush.py tests/test_items_low_stock.py tests/test_low_stock_buffer.py tests/test_realtime_emit.py tests/test_request_events.py -q` → PASS.
- [ ] **Step 7: Commit** `feat(low-stock): one after-commit listener announces every change to a low item (W6 T1)`.

### Task 2: Low Stock patches in place

**Files:**
- Modify: `backend/static/views/lowStock.js`, `backend/static/views/lowStockCard.js` (add/remove barcode handler only)
- Test: create `tests/frontend/views/lowStockLive.test.js`; update `tests/frontend/views/lowStock.test.js` where it asserts a rebuild

**Interfaces:**
- Consumes: `morphInto`, `isDirty`, `keepPlace` from `../morph.js`.
- Produces: card id `low-stock-card-<row.id>`; `data-touched` on `.ls-barcode-rows` after an add or remove; exported `loadLowStock({ background })` unchanged in signature; card attribute `data-saving` (set by T3) exempts a card from the rule 5 message.

- [ ] **Step 1: Write the failing tests** in `lowStockLive.test.js` using `mountLowStock`, `connectLowStock` and `realtime.emit("item.low_stock.changed", { id })`:

| Test | Assert |
|---|---|
| `keeps a typed new count and reason through a live update` | both values unchanged; `.low-stock-count` shows the new quantity |
| `keeps a typed name, price and threshold` | values unchanged |
| `keeps a focused field and its caret` | `document.activeElement` is the same node |
| `keeps an added barcode row` | row count unchanged after the update |
| `keeps a row message that is showing text` | text unchanged |
| `updates an untouched open card and leaves it open` | new name, price and count; `card.open === true`; same DOM node as before |
| `glows a changed card, not an unchanged one` | `just-changed` on one only |
| `first draw and a tab change glow nothing` | no `just-changed` |
| `removes a card that left the list and says so when it held typed input` | card gone; page message `"An item you were editing is no longer low."`, class `error` |
| `removes an untouched card silently` | page message unchanged |
| `a card that moved to another tab counts as removed` | same message |
| `coalesces live events into one fetch plus one rerun` | 5 events while a fetch is pending → `listGets()` length 2 |
| `a button in a patched-in card works` | Add barcode adds a row |

- [ ] **Step 2: Run** `npx vitest run tests/frontend/views/lowStockLive.test.js` → FAIL.
- [ ] **Step 3: Implement in `lowStock.js`:**
  - `buildCard` sets `card.id`.
  - `render({ reset = false } = {})`: builds into a detached `div`, wipes first when `reset` (tab change) or when the list is empty of cards; computes `held` (dirty fields, `[data-touched]` blocks) outside `[data-saving]` before the patch; `keepPlace` → `morphInto(listEl, tree.childNodes, { skip, flashSelector: ".low-stock-card" })` → restore; if a held element is no longer connected, set the rule 5 message.
  - `skip(el)`: true for a field that is focused or `isDirty`; for `.ls-barcode-rows[data-touched]`; for `.low-stock-row-message` or `.low-stock-edit-message` with text.
  - Delete `openCardIds` / `restoreOpenCards` and the header comment's "Nothing is patched in place" paragraph.
  - Coalescing for background loads: module flags `loading` and `rerun`; a background call while `loading` sets `rerun` and returns; the finishing load runs once more if `rerun`. Foreground loads keep `loadSequence`.
  - A background render leaves the page message alone when it is showing the rule 5 message or an error.
- [ ] **Step 4: In `lowStockCard.js`** set `data-touched` on the card's `.ls-barcode-rows` in the `add-barcode` and `remove-barcode` branches.
- [ ] **Step 5: Run** the new file plus `lowStock.test.js`, `lowStockCard.test.js`, `lowStockActionCoverage.test.js` → PASS (retired rebuild assertions updated and named).
- [ ] **Step 6: Commit** `feat(low-stock): live updates patch the list in place (W6 T2)`.

### Task 3: Low Stock own saves leave the card clean

**Files:**
- Modify: `backend/static/views/lowStock.js` (`commitThreshold`), `backend/static/views/lowStockCard.js` (`saveItem`, `saveCorrection`)
- Test: add to `tests/frontend/views/lowStockLive.test.js`

**Interfaces:**
- Consumes: T2's `skip`, `data-touched`, `data-saving`.
- Produces: in `lowStockCard.js`, `settle(card, selector)`: for every field under `card.querySelector(selector)` sets `defaultValue = value`, and removes `data-touched` inside it.

- [ ] **Step 1: Write the failing tests:**

| Test | Assert |
|---|---|
| `a just-saved item takes a later live change` | save name "A"; live update to "B" → field shows "B" |
| `a just-saved threshold takes a later live change` | same for the threshold |
| `a saved correction empties the reason and keeps "Count corrected."` | reason `""`, message text kept |
| `saving one section keeps the other section's typed values` | Save item with a typed correction count → count kept |
| `a save that removes its own card shows no "no longer low" message` | correction above threshold → card gone, page message not the rule 5 text |
| `a failed save leaves the fields typed` | 500 → values kept, `data-saving` absent |

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Each save sets `card.dataset.saving = ""` before the API call and deletes it on failure (on success the reload removes or patches the card; delete it after the reload settles). On success: `saveItem` → `settle(card, ".low-stock-edit")`; `saveCorrection` → empty the reason, then `settle(card, ".low-stock-correction")`; `commitThreshold` already sets `defaultValue`. Then `loadLowStock({ background: true })` as now.
- [ ] **Step 4: Run** `lowStockLive.test.js`, `lowStockCard.test.js`, `lowStock.test.js` → PASS.
- [ ] **Step 5: Commit** `feat(low-stock): own saves leave the card clean for the next live update (W6 T3)`.

### Task 4: Review queues patch in place; SMR Admin Review listens

**Files:**
- Modify: `backend/static/views/adminReview.js` (`buildCard`, `renderQueue`), `backend/static/views/smrAdminReview.js` (`buildCard`, `renderQueue`, `loadSmrAdminReview`, new `subscribe`)
- Test: add a `describe("live queue")` to `tests/frontend/views/adminReview.test.js` and `tests/frontend/views/smrAdminReview.test.js`

**Interfaces:**
- Produces: tile ids `review-card-<id>` and `smr-review-card-<id>`; `loadSmrAdminReview({ background = false } = {})`.

- [ ] **Step 1: Write the failing tests** (both files unless marked):

| Test | Assert |
|---|---|
| `a live reload keeps an unchanged tile's DOM node` | same node before and after |
| `keeps the selected class on the selected tile` | class present after reload |
| `glows a new or changed tile only` | `just-changed` on one |
| `first load glows nothing` | none |
| `a background load leaves an action or error message alone` | list message unchanged when it is not a count |
| SMR: `reloads the queue on work_order.status.changed while the page is active` | one `GET /work-orders/smr` |
| SMR: `ignores the event on another page` | no request |
| SMR: `reloads on reconnect` | one request |
| SMR: `a background load shows no "Loading" line` | message never `"Loading SMR orders…"` |

- [ ] **Step 2: Run** both files → new tests FAIL.
- [ ] **Step 3: Implement.** Both `renderQueue`s: build tiles into a detached `div`, `keepPlace` → `morphInto(listEl, tree.childNodes, { flashSelector: ".admin-review-card" })` → restore. The count message is written only on a foreground load or when the line is empty or already a count (track `countText` as `userRequests.js` does). `smrAdminReview.js`: `background` skips the loading line and, on error, changes nothing; add `subscribe("work_order.status.changed", …)` gated on `activePage === "smr-admin-review"`.
- [ ] **Step 4: Run** both files → PASS.
- [ ] **Step 5: Commit** `feat(review): review queues patch in place; SMR Admin Review updates live (W6 T4)`.

### Task 5: The open receipt or block refreshes itself

**Files:**
- Create: `backend/static/views/reviewLiveDetail.js`
- Modify: `backend/static/views/adminReview.js`, `backend/static/views/smrAdminReview.js`
- Test: create `tests/frontend/views/reviewLiveDetail.test.js`; add `describe("live detail")` to both page test files

**Interfaces:**
- Consumes: T4's subscriptions; `apiGetWorkOrder`.
- Produces:

```js
// Refetches the selected order and reports what happened. Never throws.
// Returns "same" | "changed" | "gone" | "skipped" (no selection, a newer
// selection won, or a network/401 failure).
export async function refreshSelected({
  getSelected,   // () => detail | null
  fetchDetail,   // (id) => Promise<detail>   (apiGetWorkOrder)
  isStale,       // () => boolean  true when the user selected something else meanwhile
  inQueue,       // (detail) => boolean
  signature,     // (detail) => string  everything the panel shows
  repaint,       // (detail) => void    text, status line, buttons; no focus, select or picker
  markGone,      // (detail | null) => void
})
```

  A 404 is "gone"; any other failure is "skipped".

- [ ] **Step 1: Write the failing helper tests** in `reviewLiveDetail.test.js` with plain stubs: `same` calls neither `repaint` nor `markGone`; `changed` calls `repaint` once with the fresh detail; not in queue → `markGone`; 404 → `markGone`; 500 → `skipped`, nothing called; `isStale()` true after the fetch → `skipped`; no selection → no fetch.
- [ ] **Step 2: Write the failing page tests:**

| Test | Page | Assert |
|---|---|---|
| `refreshes the receipt when the selected order's materials change` | Admin Review | new text; message `"This order was changed by someone else. The receipt is up to date."` |
| `does not focus, select or open the price picker on a live refresh` | Admin Review | `document.activeElement` unchanged; overlay hidden even when the fresh detail is unpriced; Close disabled |
| `an unchanged order shows no note` | both | message unchanged, one detail fetch |
| `an event for another order leaves the receipt alone` | both | no detail fetch |
| `marks the order gone when it left Review` | Admin Review | text kept; Reopen and Close disabled; `"WO 5001 was closed or sent back by someone else. The receipt remains for reference."` |
| `refreshes the block and status when labor changes` | SMR | status reads stale; Regenerate visible; `"… The block is up to date."` |
| `marks the order gone when it is archived or no longer ready` | SMR | all five action buttons disabled; `"… The block remains for reference."` |
| `own Archive shows its own message` | both | final message is the own-action text |
| `a tile tapped during the refresh wins` | both | panel shows the tapped order |
| `refreshes on reconnect` | both | one detail fetch |

- [ ] **Step 3: Run** → FAIL.
- [ ] **Step 4: Implement `reviewLiveDetail.js`**, then wire each page:
  - Admin Review: add `subscribe("work_order.status.changed", …)` (page gate; run when `reason === "reconnect"`, the id is missing, or it equals `selectedDetail.id`); also call the refresh from the existing review-queue handler under the same id rule. `inQueue`: `status === "review" && !archived_at`. `signature`: receipt text + missing-price list. Split `renderReceipt` so `repaint` reuses the text/buttons part without `focus()`, `select()` or `openUnpricedPicker`.
  - SMR: call the refresh from T4's handler under the same id rule. `inQueue`: the detail is ready to invoice and not archived (use the same field the tile filter reads; if the detail lacks `stage`, check the refreshed tile list instead). `signature`: block text + `blockStatusText(block)` + `pasted_at`. `repaint` reuses `renderBlock` minus its message.
  - `markGone` on both: disable the action buttons, set the rule 7 message; `selectedDetail` stays so NetFacilities and Print still work.
  - Own actions: while `runAction` / `changeBlock` / reopen / close is running, the live refresh is skipped (module flag `acting`), so the own message is the last one written.
- [ ] **Step 5: Run** the three files plus `adminReview.test.js` and `smrAdminReview.test.js` in full → PASS.
- [ ] **Step 6: Commit** `feat(review): the open receipt or block refreshes itself (W6 T5)`.

### Task 6: Census, coverage and docs

**Files:**
- Test: create `tests/frontend/views/w6LiveCensus.test.js`
- Modify: `docs/current-state.md` (real-time section, Low Stock and Admin Review rows, Hard Invariants), `backend/app/domain/realtime.py` (the `EVENT_ITEM_LOW_STOCK_CHANGED` comment now says "any change to a low item")

- [ ] **Step 1: Census test:** every `.low-stock-card` and `.admin-review-card` on the three pages has a unique id of the T2/T4 form; every field inside a Low Stock card is reachable by the skip rule (lives in a card with an id).
- [ ] **Step 2: Run** `npx vitest run tests/frontend/views/w6LiveCensus.test.js tests/frontend/staticImports.test.js` → PASS.
- [ ] **Step 3: Coverage gate:** `npx vitest run --coverage` once; `reviewLiveDetail.js` must meet the repo threshold. Add a test only for an uncovered branch.
- [ ] **Step 4: Docs.** `current-state.md`: fix "Three events"; replace the Admin Review bullet ("never replace the open receipt") with rules 6–7; add the Low Stock patch rules in two lines; add to Hard Invariants: "`item.low_stock.changed` is emitted only by the after-commit listener in `app/item_events.py`; never emit it from a route." Delete what these lines supersede.
- [ ] **Step 5: Commit** `docs: W6 live Low Stock and review pages`.

## After the last task

- Owner's phone check, two logins, local server on the LAN (recipe: `docs/superpowers/2026-11-15-live-rendering-w2-w3-session-handoff.md`):

| Check | Pass when |
|---|---|
| Type a new count on a Low Stock card; other login dispenses that item | Count and reason stay; "on hand" updates and glows |
| Other login restocks an item you are typing in | Card leaves; "An item you were editing is no longer low." |
| SMR Admin Review block open; other login edits its labor | Status goes stale, note appears, nothing jumps |
| Admin Review receipt open; other login closes that order | Text stays, buttons grey out, note appears |
| Scroll mid-list on the phone during updates | Reading position holds |

- Then: ask before pushing (deploys), and watch CI.
