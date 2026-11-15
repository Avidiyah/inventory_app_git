# User Requests Page Live (W5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This repo bars subagents unless the owner authorizes them for the task; default is inline execution.

**Goal:** The User Requests page patches in place on a live update, keeps open panels and typed fields, glows changed cards, and receives an event for every request change.

**Architecture:** One SQLAlchemy session listener collects every `UserRequest` changed in a flush and emits `user_request.changed` after commit; the per-route emits go. On the page, `render()` builds the cards detached and hands them to `morphInto` with a `skip` that keeps non-empty panels and typed fields. `isDirty` and W2's focus/scroll restore move into `morph.js` so both pages share them.

**Tech Stack:** FastAPI, SQLAlchemy 2, pytest (real `TestClient`); plain ES modules, idiomorph 0.8.0 via `morph.js`, Vitest + jsdom + msw.

**Spec:** `docs/superpowers/specs/2026-11-15-user-requests-live-design.md` (owner-approved 2026-11-15, all author's calls accepted). Rule numbers below are the spec's.

## Global Constraints

- CSP `default-src 'self'`: classes only, no inline style or script.
- `userRequests.js` (507) and `userRequestCards.js` (455) end under 500 lines; `morph.js` and `workOrderLiveBody.js` stay small.
- Delegated listeners on `listEl` stay as they are; no per-card wiring.
- Emits stay best-effort: a failed emit never fails a committed write (`realtime_service.emit` never raises).
- Envelope shape unchanged (`build_envelope(event_type, entity_id, request_id)`); subscribers (`userHub.js`, `workOrderRequests.js`, `userRequests.js`) need no change for the event.
- No push until the W1–W3 push has gone out and the owner's W5 phone check passes. W5 is its own push.
- Shared checkout: stage explicit paths only. Targeted tests only. Vitest from PowerShell at `C:\Users\mcclu\Desktop\inventory_app_git`; pytest from `backend\` with the main checkout's venv.
- An existing test that fails is a finding. Change it only when it asserts retired behaviour (list wiped on reload, route-level emit calls, `.value` prefill); name each in the commit body.

## Risk register

Spec risks 1–13 plus five found while planning (14–18). "Phone" means only a real device proves it.

| # | Hazard | Closed by |
|---|---|---|
| 1 | Open panel emptied by a patch | T4 skip; test per panel type |
| 2 | Prefilled price looks typed, never updates | T3 `value` attributes; T4 test |
| 3 | Card paired with the wrong neighbour | T3 ids; census test |
| 4 | Out-of-order responses | T5 sequence guard; test |
| 5 | Action message wiped by a live count | T5; test |
| 6 | Emit for a rolled-back write | T1 clear on `after_soft_rollback`; test |
| 7 | Event sent twice | T1 removes route emits; one-envelope tests |
| 8 | Listener in scripts or tests with no loop | `emit` works loop-less (its docstring); T1 script-style test |
| 9 | Bulk writes flood | T1 one envelope per id per commit; three-sibling test |
| 10 | Stale sibling list in a Fulfil panel | Unchanged server skip (`result.skipped`) |
| 11 | Button in a patched-in card dead | T4 test |
| 12 | iOS jump on insert above | T2 shared restore; Phone |
| 13 | Hub tile / work-order card lose events | T1 same event, superset of writers; Hub tests rerun |
| 14 | `after_flush` sees a new row before its id exists | `UserRequest.id` has `default=uuid.uuid4`, set at flush; T1 test on a create |
| 15 | Savepoint rolled back inside a committed transaction still emits its ids | Harmless extra invalidation (REST refetch); documented in the listener docstring, not fixed |
| 16 | Test suite fills the realtime handoff (`HANDOFF_QUEUE_MAX`) now that every request write emits | T1: check `test_realtime_*` reset fixture covers it; if not, clear `_handoff` in the existing autouse fixture |
| 17 | Refactoring W2's `patchBodyLive` onto the shared helper regresses the card body | T2 runs `bodyLive.test.js`, `bodyLiveCensus.test.js`, `listLive.test.js` unchanged |
| 18 | Source-string test asserts `subscribe(` in `views/userRequests.js` (`test_catalogue_requests.py:445`) | T3 keeps the subscribe in `userRequests.js` |
| 19 | Own inline price/count save removes its card while its typed field is held, so rule 7 blames "someone else"; the after-commit emit can land before the own reload | T4: acting card gets `data-saving` before the API call (cleared on failure); held ignores fields inside it |
| 20 | Tab or status change morphs list A into list B, so `morphInto` glows every card | T4: tab/status change wipes the list at render (`reset`), so it is a first draw |
| 21 | Admin Review highlight class is stripped by the next patch | Accepted: one-shot cue; focus stays |

## Review Focus

1. Fulfil panel open with a typed search; another login files a request → panel, search text and picked item survive; new card glows (T4).
2. Missing-price card prefilled `12.50`; another login edits the item price to `14` → card shows `14`; had the person typed, theirs stays (T3/T4).
3. Two live events in quick succession, responses back in reverse → the newer list wins (T5).
4. Save fails with an error, then a live event arrives → error stays (T5).
5. A correction on the Items/History side resolves a recount → exactly one envelope, after commit (T1).

---

### Task 1: Request events from one after-commit listener

**Goal:** Rule 9. Every `UserRequest` insert or change emits `user_request.changed` once per id per commit, after commit; nothing emits on rollback.

**Files:**
- Create: `backend/app/request_events.py`
- Modify: `backend/app/models.py` (import beside the `field_stamps` import at the end), `backend/app/routers/user_requests.py` (remove the four `emit_user_request_changed` calls and the import), `backend/app/routers/work_orders.py` (remove the call near line 1394 and the import if unused), `backend/app/routers/_stock_events.py` (drop the per-fact emit in `flush_stock_events`; keep the notification; delete `emit_user_request_changed` if nothing else calls it)
- Create: `backend/tests/test_request_events.py`

**Steps:**
- [ ] **Step 1: Write the failing tests** in `test_request_events.py`, capturing envelopes by monkeypatching `app.services.realtime.emit` (pattern: `_capture_emits` in `test_realtime_emit.py`). Real `TestClient`, one test per writer:
  - catalogue request filed (`POST /user-requests/catalogue-request`) → 1 envelope, `id` = new request id
  - material request filed → 1
  - recount filed by a short dispense (dispense route) → 1
  - missing-price request filed by adding an unpriced material to a work order → 1
  - item price edit resolving it (`PATCH /items/{id}` with price + link) → 1
  - correction resolving a recount → 1
  - transaction-driven resolve (`resolve_for_transaction` path: History void or work-order add with `material_request_id`) → 1
  - mark stocked → 1; resolve / reopen via `PATCH /user-requests/{id}` → 1 each
  - fulfil with three siblings → 4 envelopes, distinct ids
  - a write that raises before commit → 0
  - script-style write (plain `SessionLocal()`, no request scope, `commit()`) → 1 envelope, `request_id` null, no exception
  - unrelated commit (an item rename with no request) → 0
- [ ] **Step 2:** Run `pytest tests/test_request_events.py -q`. Expected: most fail (missing writers, duplicates where routes still emit).
- [ ] **Step 3: Implement** `request_events.py`, mirroring `field_stamps.py`:
  - `after_flush`: add `obj.id` for each `UserRequest` in `session.new` or `session.dirty` (dirty filtered by `session.is_modified(obj)`) to `session.info["request_events"]` (a set).
  - `after_commit`: pop the set; for each id, `realtime_service.emit(realtime_policy.build_envelope(event_type=EVENT_USER_REQUEST_CHANGED, entity_id=id, request_id=current_request_id()))`, each wrapped so one failure cannot stop the rest; log via `logger.exception`.
  - `after_soft_rollback`: pop the set.
  - Docstring states risk 15 and that this is the only emitter of the event.
- [ ] **Step 4:** Remove the route-level emits listed under Files.
- [ ] **Step 5:** Run `pytest tests/test_request_events.py tests/test_realtime_emit.py tests/test_realtime_domain.py tests/test_catalogue_requests.py tests/test_user_requests*.py tests/test_material_request*.py -q`. Expected: all pass. Check risk 16: if a `realtime.handoff_full` warning appears, extend the existing reset fixture.
- [ ] **Step 6:** Commit `feat(requests): emit user_request.changed from one after-commit listener (W5 T1)`.

**Test:** the per-writer envelope counts above.

### Task 2: Shared `isDirty` and focus/scroll restore in `morph.js`

**Goal:** Rules 4 and 11 reuse W2's code instead of copying it.

**Files:**
- Modify: `backend/static/morph.js` (add `isDirty`, `defaultOf`, `keepPlace`), `backend/static/views/workOrderLiveBody.js` (import them; delete its copies)
- Modify: `tests/frontend/unit/morph.test.js` (add cases)

**Steps:**
- [ ] **Step 1: Write failing unit tests** for `keepPlace(container)`: returns `restore()`; after a morph that moves the focused input, `restore()` refocuses it and restores its caret; with `CSS.supports("overflow-anchor","auto")` stubbed false, the first visible child's top offset is restored via `window.scrollBy`; with it true, no scroll call. `isDirty`/`defaultOf` move with their existing tests if any, else one test each (select with no `selected` option is clean; checkbox).
- [ ] **Step 2:** Run them; expected fail (not exported).
- [ ] **Step 3: Implement.** Move `defaultOf` and `isDirty` verbatim. `keepPlace(container)` holds the capture half of `patchBodyLive` (active, caret via `selectionOf`, anchor and its top) and returns the restore half (refocus with `preventScroll`, `setSelectionRange`, anchor correction when `overflow-anchor` is unsupported). `patchBodyLive` calls `const restore = keepPlace(bodyEl)` before the morph and `restore()` where its two blocks were. `workOrderLiveBody.js` re-exports `isDirty` so W3's `workOrderConflict.js` (its only other importer) keeps working.
- [ ] **Step 4:** Run `npx vitest run tests/frontend/unit/morph.test.js tests/frontend/views/workOrders/bodyLive.test.js tests/frontend/views/workOrders/bodyLiveCensus.test.js tests/frontend/views/workOrders/listLive.test.js` plus every file that imports `isDirty`. Expected: all pass, W2 tests unchanged (risk 17).
- [ ] **Step 5:** Commit `refactor(live): share isDirty and focus/scroll restore via morph.js (W5 T2)`.

**Test:** `keepPlace` cases; W2 suites unchanged.

### Task 3: Card ids, attribute prefill, and the file split

**Goal:** Rules 2 and 5; get both modules under 500 lines before T4 adds code.

**Files:**
- Modify: `backend/static/views/userRequestCards.js` (`buildRequestCard`: `card.id = "ureq-card-" + id`; missing-price inputs render `value="${escapeHtml(...)}"` in `missingPriceActions(request)` instead of the post-build `.value` block, which is deleted)
- Create: `backend/static/views/userRequestsForms.js` (`fulfillPayload(panel)` moved verbatim; new `editPayload(card, panel)` holding the edit-save validation and details building, returning `{ message, details }` or `{ error, focus }`)
- Modify: `backend/static/views/userRequests.js` (import both; edit-save branch shrinks to call `editPayload`)
- Create: `tests/frontend/views/userRequestsLiveCensus.test.js`
- Modify: `tests/frontend/views/userRequests.test.js` only if it asserts the `.value` prefill mechanism

**Steps:**
- [ ] **Step 1: Write the failing census test:** for one request of each type and status, `buildRequestCard` output has `id="ureq-card-<id>"`; ids are unique across a list of all of them; every `input`, `select`, `textarea` in a card is either inside `.user-request-panel` or has a `defaultValue` equal to the server value (price/link prefilled cards: `defaultValue === "12.5"` / the link; `isDirty` false).
- [ ] **Step 2:** Run; expected fail.
- [ ] **Step 3:** Implement the ids and attribute prefill; move the two payload builders. Keep `subscribe(USER_REQUEST_CHANGED_EVENT` in `userRequests.js` (risk 18).
- [ ] **Step 4:** Run `npx vitest run tests/frontend/views/userRequests*.test.js tests/frontend/views/userRequestsLiveCensus.test.js` and `pytest tests/test_catalogue_requests.py -q`. Expected: pass. `wc -l` both modules: under 500.
- [ ] **Step 5:** Commit `refactor(requests): card ids, attribute prefill, payload builders split out (W5 T3)`.

**Test:** census; existing request suites.

### Task 4: `render()` patches in place

**Goal:** Rules 1, 3, 4, 6, 7, 11, 12.

**Files:**
- Modify: `backend/static/views/userRequests.js`
- Create: `tests/frontend/views/userRequestsLive.test.js` (uses `openUserRequests()` and `connectFakeRealtime` from `helpers/userRequests.js`)

**Steps:**
- [ ] **Step 1: Write failing tests** (each: load, change state, fire the fake `user_request.changed`, await the reload):
  - Fulfil panel open with typed search and a picked item; a new request arrives → same panel element, search value and `dataset.pickedItemId` kept; new card has `just-changed`; unchanged cards do not.
  - Edit panel open with a typed message → kept; the card's status text still updates when the server changed it.
  - Close panel open → kept.
  - Typed recount count and reason → kept; untyped prefilled price on another card updates to the new server price.
  - Focused, untyped price input → kept while focused (W2 rule: focus protects).
  - Card removed by the server while its panel is open → card gone; message line reads "A request you were working on was closed or moved by someone else."
  - Card removed with nothing typed or open → gone, no message change beyond the count.
  - Button in a card inserted by a patch (Mark stocked) → its handler runs (risk 11).
  - Own Edit save → that card's panel closes; another card's open panel stays.
  - Tab change → all panels emptied; new list drawn; nothing glows on first draw of a tab.
  - Admin Review focus (`focusMissingPriceRequest`) still outlines and focuses the price input.
- [ ] **Step 2:** Run; expected fail.
- [ ] **Step 3: Implement:**
  - `render()`: build cards into a detached `div`; `const restore = keepPlace(listEl)`; record `held` = non-empty panels plus dirty fields in `listEl`; `morphInto(listEl, tree.childNodes, { skip, flashSelector: ".user-request-card", flashKey })` where `flashKey` joins the `textContent` of the card's children except `.user-request-panel`, so a panel opening never glows the card; `restore()`; if any `held` element is disconnected, set the rule 7 message.
  - `skip(el)`: true for `.user-request-panel` with children; true for the focused field; true for a dirty field; else false.
  - Own-save branches (close, edit, fulfil, count, price, stock, resolve/reopen): `closePanel(card)` before `await loadUserRequests()`.
  - Tab click and status change: empty every `.user-request-panel` before loading.
  - Remove `listEl.replaceChildren()` from `render()`; the catch path in `loadUserRequests` keeps it (a failed load is not a patch).
- [ ] **Step 4:** Run `npx vitest run tests/frontend/views/userRequests*.test.js tests/frontend/views/userHub.test.js`. Expected: pass.
- [ ] **Step 5:** Commit `feat(requests): live updates patch the list in place (W5 T4)`.

**Test:** the cases above.

### Task 5: Response ordering and the message line

**Goal:** Rules 8 and 10.

**Files:**
- Modify: `backend/static/views/userRequests.js`
- Modify: `tests/frontend/views/userRequestsLive.test.js`

**Steps:**
- [ ] **Step 1: Write failing tests:**
  - Two live loads; msw delays the first response past the second → the second's list is painted; the first is dropped.
  - Tab changed while a load is in flight → the old tab's response is dropped.
  - Action error shown, then a live event → error text unchanged; the list still patches.
  - Count line showing, live event with one more request → count text updates.
  - Live load shows no "Loading…" text; a Refresh click still does.
- [ ] **Step 2:** Run; expected fail.
- [ ] **Step 3: Implement:**
  - `let loadSeq = 0;` each `loadUserRequests({ live = false } = {})` takes `const seq = ++loadSeq` and returns early after the await when `seq !== loadSeq` (newest wins; a tab change starts a newer load).
  - `let countText = "";` `render()` writes the count line only when `!live || messageEl.textContent === countText || !messageEl.textContent`, then stores `countText = messageEl.textContent`. The rule 7 message, when set, wins.
  - `live` skips the "Loading…" message. The subscriber calls `loadUserRequests({ live: true })`; listeners that call it as an event handler pass no options (guard against the `Event` argument: `live === true`).
- [ ] **Step 4:** Run `npx vitest run tests/frontend/views/userRequests*.test.js`. Expected: pass; `wc -l backend/static/views/userRequests.js` under 500.
- [ ] **Step 5:** Commit `feat(requests): drop stale responses and keep action messages across live updates (W5 T5)`.

**Test:** the cases above.

### Task 6: Coverage check and docs

**Files:**
- Modify: `docs/current-state.md` (User Requests routing row: `userRequestsForms.js`, `request_events.py`, the new tests; one Hard Invariants line: "`user_request.changed` is emitted only by the after-commit listener in `app/request_events.py`"), `docs/endpoint-map.md` only if it names per-route emits for request routes

**Steps:**
- [ ] **Step 1:** Run `npm run test:ci` (the coverage gate CI uses). Expected: gate holds; `morph.js` and `userRequestsForms.js` fully covered.
- [ ] **Step 2:** `grep -rn "emit_user_request_changed" backend` → no hits outside tests' history.
- [ ] **Step 3:** Edit the docs within their word budgets.
- [ ] **Step 4:** Commit `docs: W5 live User Requests page`.

## After the last task

Not pushed until the W1–W3 push is out. Owner's check, two logins (A an Admin on the Requests page, B anyone filing or resolving), on a phone:

| Owner checks | Passes when |
|---|---|
| A opens Fulfil on a catalogue request and types a search; B files a new request | A's panel and search stay; the new card glows once |
| A types a price on a missing-price card; B edits that item's price on the Items page | A's typed price stays; on a card A did not touch, B's price appears |
| A has Edit open; B resolves that request | Card leaves the Open list; message says someone else closed it |
| B files a catalogue request from Find Item | It appears on A's page without a refresh |
| A scrolled down the list; B files a request (inserts at the top) | A's reading position does not jump |
| A's save fails (e.g. blank reason), then B acts | A's error stays |
| A taps Mark stocked on a card that arrived live | Works |

Then CI green on the W5 push.
