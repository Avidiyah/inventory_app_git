# Frontend Test Harness — P6d (`notes.js` + `itemEditor.js` + `addBarcode.js` + `correction.js` + `correctionPanel.js`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task, **inline in the session — no subagents** (`CLAUDE.md` forbids them here). Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Status: go-ahead given 2026-09-11 ("dp p6d"). Fourth P6 chunk; first one off the hub fixture.**

**Goal:** Characterization coverage for the four Saved Items sub-flow panels (644 lines with the shared panel helper) — the notes editor, the item editor and its `itemSave.js` write sequence, the add-a-scanned-barcode panel, and the correction panel `correction.js` builds from `correctionPanel.js`.

**Architecture:** Tests only, on P5c's `helpers/items.js` — `mountItems()` already installs `stubScrollIntoView` for exactly these panels. Three of the four open the way a user opens them, through a row's action `<select>` on a loaded row (`items.test.js`'s own pattern, which is this chunk's setup); `addBarcode.js` is entered by `openAddBarcode(code)` by name, because its production entry is `scan.js`'s 404 shortcut, which P5c already pins. Each panel's Save is driven through its real button, so `dom.js`'s real overlays answer the barcode-change warning and the archived-reuse 409.

**Tech Stack:** Vitest, jsdom, @testing-library/user-event, msw.

**Spec:** `docs/superpowers/specs/2026-09-10-frontend-test-harness-design.md` §3.2–3.3
**Parent plan:** `docs/superpowers/plans/2026-09-11-frontend-test-harness-p6.md` (P6d bullets are the requirement set; deviation 4 scopes `correctionPanel.js` here)
**Depends on:** P5c (`helpers/items.js`, the row-action opens), P5d (`helpers/dialogs.js::answerConfirm`), P1 (`format.js` / `dom.js` unit tests already own `formatNoteValue`, `detectNoteType`, `getNoteValueRaw`).

## Global constraints

- Tests only. No edit under `backend/static/` or `backend/app/`.
- Characterization, not correction. Findings → `docs/open-work.md` → `N-P6-CHARACTERIZED`.
- No `vi.mock` of any app module. Seams: `fetch` (MSW), fake timers, the real confirm overlay.
- `onUnhandledRequest: "error"` stays on.
- **Fake timers are opt-in here, unlike the hub.** `mountItems()` does not install them, and `items.test.js` runs on real ones. Every test that advances an auto-close (1000 ms) or the search debounce (200 ms) calls `vi.useFakeTimers()` *before* mounting and drives input through `userEvent.setup({advanceTimers: vi.advanceTimersByTime})`; `setup.js`'s `afterEach` restores real timers. A test that does not need them stays on real timers.
- One mount per test (`setup.js` resets modules per test).
- `afterEach`: `restoreItems()`.
- No new factory is expected; `item()` already carries `notes`, `barcodes`, `price` and `product_link`. If one is added it gets a drift row in the same commit.
- Commit messages end with the attribution lines the session provides.

## Already pinned — do not re-cover

- P5c (`items.test.js`): each row action opening its panel, the delete flow closing an open panel, the `setOnSaved` refresh in both list modes (search repeats the query, `none` refreshes nothing), the scan-404 shortcut that reaches `openAddBarcode`, the per-role action lists.
- P1: `formatNoteValue`, `detectNoteType`, `getNoteValueRaw`, `filterRanked`, `friendlyError`, `skeletonList`.
- P5e: `billingEditor.js` (struck from P6 entirely, parent deviation 2).

## Entry gate

- [ ] `npm test` green (P6c close: 1454 / 48, 145 s).

---

### Task 1: `notes.test.js`

**Files:** Create `tests/frontend/views/notes.test.js`.

Local helpers: `loadedRow(role, overrides)` = `mountItems` + Load all + wait for one row (the `items.test.js` form); `openNotes()` = `selectOptions(actionSelect(0), "notes")`; `noteRows()`; `keyOf(n)` / `typeOf(n)` / `valueOf(n)`; `save()` = click `#notes-save-btn`; `message()` = `#notes-message`.

- [ ] **`renderNotesSummary`** by name (imported from `views/notes.js`): no notes / `null` / a non-object → the `<span class="empty">—</span>`; `{a: 1, b: true}` → `a: 1, b: true` through `formatNoteValue`; a key and a string value carrying markup are escaped. Plus one assertion through the real notes cell of a loaded row, which is what production renders.
- [ ] **Open:** an item with no notes → exactly one blank row (key `""`, type `string`, a text value input); an item with three notes → a row each, keys in payload order, the type select set by `detectNoteType` (string / number / boolean) and the value control matching (`input[type=number][step=any]`, the `true`/`false` select).
- [ ] **Type swap:** changing a row's type re-renders the value control carrying the raw value across — string `5` → number keeps `5`; number `5` → boolean lands on `false`; string `true` → boolean lands on `true`; boolean → string keeps `"true"`.
- [ ] **Rows:** Add note appends a blank row; a row's `×` removes that row only.
- [ ] **Save, validation:** a blank key is skipped entirely (not sent); two rows sharing a key → "Two notes share a name. Make each note name different." and no request; a number row left blank → `Value for "k" is required.`; a number row holding `abc` → `Invalid number for "k".` (assert through a text→number swap so the DOM can hold it).
- [ ] **Save, success:** `PATCH /items/{id}/notes` with `{notes: {…}}` — a number as a number, a boolean as `true`/`false`, a string as a string — then "Notes saved." with the `success` class, `setOnSaved`'s callback awaited (a spy registered by name), and the panel closing 1000 ms later on fake timers.
- [ ] **Save, failure:** a 500 with a detail → that detail with the `error` class, the panel still open, `getEditingNotesItemId` unchanged.
- [ ] **No selection:** clicking Save with nothing open → "No item selected." and no request.
- [ ] **Cancel / close:** Cancel hides the panel, empties the rows, clears the message and nulls `getEditingNotesItemId` (read through `state.js`); `closeNotesEditor()` by name does the same.

- [ ] Run the file; commit `test(p6d): notes editor — summary, rows, the type ladder, save and close`.

---

### Task 2: `itemEditor.test.js`

**Files:** Create `tests/frontend/views/itemEditor.test.js`.

- [ ] **Open:** prefills barcode / name / location / price / product link (a null price and link → empty strings), one `.barcode-row` per additional code, `Editing: <name>`, and `getEditingItemId()` set; Add barcode appends a row, `×` removes one; `closeItemEditor()` clears the id, the rows and the message.
- [ ] **Validation:** any of barcode / name / location blank → "Barcode, name, and location are required." and no request; two additional rows with the same code → `The barcode "X" is listed twice. Remove the duplicate.`
- [ ] **The write sequence** (`itemSave.js`, the load-bearing order): an unchanged barcode list → only `PATCH /items/{id}` with `{barcode, name, location, price, product_link, override_archived: false}`, `price` through `parseFloat` and `product_link` null when blank; a changed list → `PATCH /items/{id}/barcodes` **first** with `{barcodes, override_archived: false}`, then the item PATCH.
- [ ] **Barcode-change warning:** editing the primary barcode prompts `BARCODE_CHANGE_WARNING` (assert the real overlay's title text against the imported constant); No → the message is cleared, the panel stays open, nothing is requested; Yes → both writes go.
- [ ] **Archived reuse:** a 409 on the item PATCH → "Barcode exists but is archived. Continue?" → Yes → the whole sequence retries with `override_archived: true` on both writes (four requests in order); No → `cancelled`, the message cleared, no retry.
- [ ] **Success:** "Item saved." with the `success` class, `setOnSaved` awaited, close after 1000 ms; a second save with no further list change sends no barcodes PATCH (the snapshot was updated).
- [ ] **Failure:** a 500 detail with the `error` class and the panel open; Save with nothing open → "No item selected."

- [ ] Run the file; commit `test(p6d): item editor — prefill, validation, the itemSave sequence, both prompts`.

---

### Task 3: `addBarcode.test.js`

**Files:** Create `tests/frontend/views/addBarcode.test.js`.

Entry: `openAddBarcode(code)` by name after `mountItems()` (P5c owns the scan-404 entry). Fake timers throughout — the search is debounced.

- [ ] **Open / close:** `Scanned code: <code>` with the code escaped, an empty search, hidden results, focus in the field; `closeAddBarcode()` hides the panel, empties and hides the results, clears the message and the pending timer (`vi.getTimerCount()` is 0).
- [ ] **Debounce:** typing renders `skeletonList(3)` immediately and fires `GET /items/?q=` only 200 ms later; a second keystroke inside the window leaves one request, for the latest term.
- [ ] **Narrowing:** the server's barcode-only match is dropped and the name match kept; a punctuation-insensitive hit survives (`2x4` against a name of `2"x4"` — the module's own argument); ten matches render eight buttons; no matches → "No items match that name."; a failing search → `friendlyError` in an `.error`.
- [ ] **Stale answer:** the first (gated) response resolves last and is discarded — the rendered list is the second term's.
- [ ] **Pick, No:** the confirm copy is `Add barcode <code> to "<name>"?`; No → no request, no message.
- [ ] **Pick, Yes:** "Adding…" → `GET /items/{item.barcode}` (a fresh read, by barcode) → `PATCH /items/{id}/barcodes` with `{barcodes: [...fresh.barcodes, code], override_archived: false}`; success copy `Added <code> to <name>.`, `setOnSaved` awaited, close after 1200 ms.
- [ ] **Archived reuse:** a 409 on the PATCH → the prompt → Yes → a retry with `override_archived: true`; No → `cancelled` and the message cleared.
- [ ] **Failure:** the fresh read or the PATCH failing → `friendlyError` with the `error` class, the panel open.

- [ ] Run the file; commit `test(p6d): add-barcode panel — the debounced search, narrowing, the append and its prompts`.

---

### Task 4: `correction.test.js`

**Files:** Create `tests/frontend/views/correction.test.js`.

Covers `correctionPanel.js` once, through its Saved Items host (parent deviation 4).

- [ ] **Open:** `Correcting: <name> (<barcode>)`, `Current count: <quantity>`, the new-quantity field prefilled with the current quantity and selected (assert `selectionStart` / `selectionEnd`), an empty reason, `getEditingCorrectionItemId()` set.
- [ ] **The validation ladder, in order:** nothing open → "No item selected."; blank → "Enter a valid new count."; `abc` (through a `value` assignment the number input accepts) → the same; `-1` → "Enter a count of zero or more."; a valid count with no reason → "Enter a reason for the correction." Each writes nothing.
- [ ] **Submit:** `POST /transactions/adjust` with `{item_id, new_quantity, reason}` (the number as a number, the reason trimmed) → "Count corrected." with the `success` class → `setOnSaved` awaited → close after 1000 ms with the fields cleared.
- [ ] **Failure:** a 500 detail with the `error` class, the panel open, `getEditingCorrectionItemId()` still set.
- [ ] **Cancel:** hides the panel, clears both fields and the message, nulls the editing id.

- [ ] Run the file; commit `test(p6d): correction panel — the ladder, the adjust POST, cancel`.

---

### Task 5: Findings, docs, parent plan

- [ ] `docs/open-work.md` → `N-P6-CHARACTERIZED`: whatever the run surfaces (the notes editor's blank-key skip and the number-required message both look like candidates; assert first, file what is real).
- [ ] `docs/current-state.md`: the Vitest bullet names the four files after the `items.js` clause; the Item CRUD row names its tests (the parent plan's "Done when"); count / time updated.
- [ ] Parent plan: tick the P6d bullets; suite-budget row `P6d | N / 52 | S s`.
- [ ] `npm test` to completion; commit `docs: record P6d — the Saved Items sub-flows`.

## Done when

- [ ] Five commits, each green.
- [ ] Every export called by name: `renderNotesSummary`, `openNotesEditor`, `closeNotesEditor`, `setOnSaved` (×3), `openItemEditor`, `closeItemEditor`, `openAddBarcode`, `closeAddBarcode`, `openCorrection`, `closeCorrection`, `getEditingCorrectionItemId` — and `createCorrectionPanel` through `correction.js`.
- [ ] Findings filed; docs updated.

## Deliberately not in P6d

- `items.js`'s own table, row actions and refresh modes (P5c).
- `scan.js`'s 404 shortcuts (P5g) and the camera.
- `lowStockCard.js`, the other `saveItemCore` caller (P7).
- `toolCorrection.js`'s wiring (P6e, deviation 4).
