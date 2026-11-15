# Work Orders Live Card Body (Stage 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A live update to an open work order patches the card body in place and never changes anything the user has typed, picked or opened.

**Architecture:** A socket-driven refresh renders the new body into a detached element with the existing `renderBody`, then patches the on-screen body through `morphInto` with a `skip` rule. Every element the rule can leave alone, and every direct child of the body, carries an id, so the patcher pairs by identity and never by position. Repaints after the user's own save keep rebuilding the body, as today.

**Tech Stack:** Plain ES modules, vendored idiomorph 0.7.4, Vitest + jsdom. Task 5 only: FastAPI + pytest.

**Spec:** `docs/superpowers/specs/2026-11-14-work-order-live-rendering-design.md`, section "Stage 2: the card page body" (rules 1 to 12, and the practice table with its sources).

## Global Constraints

- Tasks 1 to 3 change no behaviour. Task 4 is the only switch; reverting its commit restores today's "defer while a section is open".
- Precondition for Task 4: Stage 1's real-browser check (list renders, no security-policy violation in the console) has passed.
- Security policy is `default-src 'self'`: no inline style or script. Classes and attributes only.
- `open` on any `<details>` belongs to the user; a patch never changes it.
- A repaint after the user's own action (`refreshCard`, `openDetail`) keeps writing `renderBody` straight into the body. Never route it through the patch: a saved field must come back empty.
- List cards and `mountWorkOrderList` are untouched.
- `workOrderList.js` is 882 lines and must stay under 1,000: new logic lives in `backend/static/views/workOrderLiveBody.js`.
- `heldWorkOrderCards()` keeps its meaning (a card with an open editor section); `workOrderRetry.js` depends on it.
- An existing test that fails is a finding. Change it only when it asserts the retired deferral, and name each such test in the commit body.
- Shared checkout: stage explicit paths only. No `Co-Authored-By` trailer. Targeted tests only, run from PowerShell at `C:\Users\mcclu\Desktop\inventory_app_git`.

## Risk register

Every hazard found in two audit passes, and where it is closed. "Phone" means only a real device can prove it.

| # | Hazard | Closed by |
|---|---|---|
| 1 | Typed, unfocused field wiped | T3 rules 1, 3 |
| 2 | Kept element paired with the wrong neighbour (duplicate or missing row; stray message where a hint belongs) | T2 identity invariant + census |
| 3 | Picked item or request id erased from the add row | T3 rule 1 |
| 4 | SMR entry row forgets the line it edits; Save would add a new line | T3 rule 1 |
| 5 | Typed hours end up beside a different default technician | T3 rule 1 (form is one unit) |
| 6 | A select with no `selected` option always reads as typed, so its form never updates | T3 dirty-select definition |
| 7 | Open charge editor destroyed (its buttons have direct listeners) | T3 rule 2 |
| 8 | Edit details state lost (technician picker, combos) | T3 rule 2 |
| 9 | Closed-but-stale Edit details saves old values over new | T4 catch-up on close |
| 10 | Message line blanked or moved | T2 keep-marker + id |
| 11 | Tab bar resets; a section the patch adds steals the visible tab | T3 tab restore |
| 12 | "I have read the notes" bypasses notes that arrived later | T3 rule 6 |
| 13 | Typed input discarded because the server removed its row or field | T3 notice (rule 5) |
| 14 | Out-of-order responses show old data | T4 one fetch per card |
| 15 | A stale live response lands after the user's own save | T4 paint counter |
| 16 | Response arrives after the user moved to another order; a 404 would replace the wrong page | T4 `isConnected` checks |
| 17 | Background refresh signs the user out mid-typing with no draft | T4 quiet 401 |
| 18 | Saved field not cleared | Own-save path unchanged; T4 test |
| 19 | A button element is reused for a different action between press and release | T2 action-button ids (a button with an id is only ever paired with the same id, so it is removed, and a removed element receives no click) |
| 20 | Buttons shift under a finger about to tap | T4 500 ms settle + glow |
| 31 | Someone else changed the very field the user is typing in; saving would silently replace it | T3 conflict notice (rule 12) |
| 32 | Manual scroll correction doubles the browser's own on Chrome and Firefox | T3 feature check |
| 33 | Duplicate ids make pairing undefined | T0 library warns; T2 census asserts no warning |
| 34 | Dropped-input and conflict messages not announced to screen readers | T2 `role="status"` on the message line |
| 21 | Field skipped only for focus stays stale after focus leaves | T4 catch-up on focusout |
| 22 | Stale `data-line` snapshot on an SMR row | T3 rule 3 (row updates around the field) |
| 23 | Draft replay after re-login races the reconnect refresh | T4 paint counter + test |
| 24 | Focus lost when the focused element's ancestor is moved | T3 refocus; Phone |
| 25 | Reading position jumps (iOS has no scroll anchoring) | T3 anchor restore; Phone |
| 26 | Security policy blocks the library | Stage 1 gate; precondition above |
| 27 | A future field is added outside the rules | T2 census fails |
| 28 | Material, labor and SMR-line changes send no live event | T5 (owner's call) |
| 29 | Two users saving the same field | Not changed: last write wins (separate design) |
| 30 | Order archived while typing: the card is replaced by "no longer available" | Accepted: nothing typed there could be saved |

## Review Focus

1. **Responses arrive out of order:** the body ends on the newest response. Test in Task 4.
2. **A line is removed above a row the user typed in:** the typed value stays on its own line; no duplicate or missing row. Test in Task 3.
3. **An SMR entry row in edit mode during an update:** it still saves to the line being edited. Test in Task 3.
4. **Crew changes while hours are typed in the add-labor row:** the technician shown does not change. Test in Task 3.
5. **The action bar changes as the user taps:** the tap does nothing. Tests in Tasks 3 and 4.

---

### Task 0: Vendor idiomorph 0.8.0

0.8.0 (2026-09-05) warns on duplicate ids during a morph and fixes focus restoration; both bear on this plan. It is ESM-only, which is what the app imports.

**Files:**
- Create: `backend/static/vendor/idiomorph-0.8.0.esm.js` (from `https://unpkg.com/idiomorph@0.8.0/dist/idiomorph.esm.js`, unmodified)
- Delete: `backend/static/vendor/idiomorph-0.7.4.esm.js`
- Modify: `backend/static/vendor/idiomorph-LICENSE.txt` (refresh from the 0.8.0 package), `backend/static/morph.js` (import path), `docs/current-state.md` (version in the vendored-file row)

- [ ] **Step 1:** Read the 0.8.0 entry in `https://github.com/bigskysoftware/idiomorph/blob/main/CHANGELOG.md`. If it lists a change to `morphStyle: "innerHTML"`, `ignoreActiveValue`, `beforeAttributeUpdated` or `beforeNodeMorphed` beyond those named above, stop and report.
- [ ] **Step 2:** Swap the file and the import.
- [ ] **Step 3:** Run `npx vitest run tests/frontend/unit/morph.test.js tests/frontend/views/workOrders/listLive.test.js tests/frontend/unit/staticImports.test.js`. Expected: PASS with no change to any test. A failure means stay on 0.7.4: revert this task and continue from Task 1.
- [ ] **Step 4:** Commit.

```bash
git add backend/static/vendor backend/static/morph.js docs/current-state.md
git commit -m "chore(vendor): idiomorph 0.8.0 (duplicate-id warnings, focus fixes)"
```

---

### Task 1: `morphInto` takes a `skip` rule

**Files:**
- Modify: `backend/static/morph.js`
- Test: `tests/frontend/unit/morph.test.js` (extend)

**Interfaces:**
- Produces: `morphInto(container, newNodes, { flashSelector, flashKey, skip = null })`. `skip(oldElement, newElement)` returning `true` leaves the old element and its subtree exactly as they are. Called for elements only.

- [ ] **Step 1: Write the failing tests**

```js
test("a skipped element keeps its attributes, children and field values")
test("siblings of a skipped element still update")
test("a skipped element absent from the new tree is still removed")
test("a skipped element with an id is never paired with a different id")  // new tree reorders and drops siblings
test("skip is not called for text nodes")              // skip throws on nodeType !== 1
test("with no skip, behaviour is unchanged")
```

- [ ] **Step 2: Run to verify failure**

Run: `npx vitest run tests/frontend/unit/morph.test.js`
Expected: the new tests FAIL.

- [ ] **Step 3: Implement**

Add `callbacks.beforeNodeMorphed: (oldNode, newNode) => !(skip && oldNode.nodeType === 1 && skip(oldNode, newNode))`. Add one test: `skip receives the new element it was paired with`.

- [ ] **Step 4: Run to verify pass**

Run: `npx vitest run tests/frontend/unit/morph.test.js tests/frontend/views/workOrders/listLive.test.js`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/static/morph.js tests/frontend/unit/morph.test.js
git commit -m "feat(ui): morphInto can leave chosen elements untouched"
```

---

### Task 2: Identity in the body markup; the census

**Files:**
- Create: `backend/static/views/workOrderLiveBody.js` (constants only in this task)
- Modify: `backend/static/views/workOrderCardHtml.js` (`renderBody` ~513, `renderLineHtml` ~650, `renderLaborEntryHtml` ~54, `laborSectionHtml` ~109, `detailsEditorHtml` ~417)
- Modify: `backend/static/views/workOrderSmrLines.js` (`lineRowHtml` ~42, `entryRowHtml` ~66, `blockHtml` ~149)
- Modify: `backend/static/views/workOrderPresenters.js` / `workOrderStatusActions.js` only where a direct child of the body is built (`crewLockHtml`, `priorWorkBannerHtml`, `chargingStripHtml`)
- Test: `tests/frontend/views/workOrders/bodyLiveCensus.test.js`

**Interfaces (ids; one card body exists in the document at a time):**

| Element | id |
|---|---|
| Direct children of `.wo-body`, in order | `wo-sec-charging`, `wo-sec-lock`, `wo-sec-prior`, `wo-sec-tabs`, `wo-sec-details`, `wo-sec-notes`, `wo-sec-materials`, `wo-sec-labor`, `wo-sec-invoice`, `wo-sec-actions`, `wo-sec-msg` |
| `.wo-item` / its `.wo-line-qty` | `wo-line-<id>` / `wo-line-qty-<id>` |
| labor `.wo-labor-entry` / its `.wo-labor-hours` | `wo-labor-<id>` / `wo-labor-hours-<id>` |
| `.wo-smr-line` / its `.wo-smr-l-hours` | `wo-smrline-<id>` / `wo-smrline-hours-<id>` |
| `.wo-add-item` | `wo-add-item` |
| `.wo-add-labor`: skilled, plain, SMR | `wo-add-skilled`, `wo-add-labor`, `wo-add-smr` |
| `.wo-edit-card` | `wo-edit-card` |
| `.wo-notes-input`, `.wo-notes-message` | `wo-notes-input`, `wo-notes-msg` |
| `.wo-smr-description-text` | `wo-smr-description` |
| `.wo-mode-select` | `wo-mode-select` |
| Every `[data-action]` button outside a row, an entry form and Edit details (action bar, More menu, ready row, invoice buttons, notes acknowledgement) | `wo-act-<data-action>` |

- `data-live-keep` on `#wo-sec-msg` and `#wo-notes-msg` (`setMessage` replaces the class).
- `role="status"` on `#wo-sec-msg`, present from first paint (WCAG 4.1.3 needs the role before the text arrives).
- `workOrderStatusActions.js` `BTN` strings keep `data-action="..."` verbatim (the action-coverage audit greps for it); the id is a separate attribute.
- From `workOrderLiveBody.js`:
  - `export const LIVE_FORMS = ".wo-add-item, .wo-add-labor"`
  - `export const LIVE_ROWS = ".wo-item, .wo-labor-entry"`
  - `export const SAVES_ON_CHANGE = ".wo-mode-select"`

- [ ] **Step 1: Write the failing tests**

Render the card page for Owner, Team Lead, Technician on the crew and Technician off the crew; each with a plain order and an SMR order holding two materials, two labor entries and two SMR lines, with and without a running clock and prior work.

```js
test("every direct child of the body carries a unique id")
test("every row and every entry form carries a unique id")
test("every field outside an entry form and outside Edit details carries a unique id")
test("no id is duplicated in the document")              // with the User Hub list also mounted
test("both message lines carry data-live-keep and an id")
test("every field is accounted for")
// each input, select, textarea in .wo-body is inside #wo-edit-card, or inside
// LIVE_FORMS, or has an id, or is readonly. On failure print its class list.
test("the message line is still the body's last child")
test("every action button outside a row, form and Edit details has the id wo-act-<its action>")
test("the message line has role=status before any message is set")
test("rendering any fixture twice and patching one into the other logs no duplicate-id warning")  // spy console.warn
```

- [ ] **Step 2: Run to verify failure**

Run: `npx vitest run tests/frontend/views/workOrders/bodyLiveCensus.test.js`
Expected: FAIL on ids. Note every field the census reports.

- [ ] **Step 3: Implement**

Add the ids and attributes in the builders. For a field the table does not list: inside a form whose fields act together, give the form a class in `LIVE_FORMS` and an id; otherwise give the field an id. Record each one in the commit body. Do not weaken the census.

- [ ] **Step 4: Run to verify pass, plus neighbours**

Run: `npx vitest run tests/frontend/views/workOrders tests/frontend/unit/staticImports.test.js`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/static/views/workOrderLiveBody.js backend/static/views/workOrderCardHtml.js backend/static/views/workOrderSmrLines.js backend/static/views/workOrderPresenters.js backend/static/views/workOrderStatusActions.js tests/frontend/views/workOrders/bodyLiveCensus.test.js
git commit -m "refactor(work-orders): card body elements carry ids; field census test"
```

---

### Task 3: `patchBodyLive` and the corruption matrix

**Files:**
- Modify: `backend/static/views/workOrderLiveBody.js`
- Modify: `backend/static/styles.css` (`.wo-field-conflict`, beside the work-order card rules)
- Test: `tests/frontend/views/workOrders/bodyLive.test.js`

**Interfaces:**
- Consumes: `morphInto(..., { skip })` (Task 1); ids, `data-live-keep`, constants (Task 2); `renderBody`, `showWorkOrderTab`, `syncWorkOrderTabs` from `workOrderCardHtml.js`; `setMessage` from `dom.js`.
- Produces: `export function patchBodyLive(detail, bodyEl, cardEl)` returning `{ deferred: boolean }`. Not yet called by the app.
- Produces: `export function isDirty(field)`, `export function isTouched(form)`.
- Produces: `export function actionsSettling(cardEl)`, true for 500 ms after a patch changed the text of `#wo-sec-actions` or `.wo-smr-ready`.

`skip(el)`, in order:
1. `el.hasAttribute("data-live-keep")` → skip.
2. `#wo-edit-card` and `el.open` → skip; `deferred = true`.
3. `el.matches(LIVE_FORMS) && isTouched(el)` → skip.
4. `el.matches(".wo-item")` containing `.charge-cancel` → skip.
5. `el.matches("input, select, textarea")`: skip when it is `document.activeElement` (and set `deferred = true` if it is not dirty), or when `isDirty(el)` and it does not match `SAVES_ON_CHANGE`. When a dirty field is skipped and the paired new element's default value differs from the old element's default value, record a conflict: someone else changed that field.

`isTouched(form)`: contains `document.activeElement`, or any dirty field, or has `dataset.itemId`, `dataset.materialRequestId` or a non-empty `dataset.lineId`.

`isDirty`: `input`/`textarea` `value !== defaultValue`; checkbox or radio `checked !== defaultChecked`; `select` when `value` differs from its default option's value, where the default option is the first with `defaultSelected`, else `options[0]`.

Around the patch, in this order:
1. Before: record the active tab (`bodyEl.dataset.woTab`), `.wo-notes-log` text, `document.activeElement` with its selection range, the text of `#wo-sec-actions` and `.wo-smr-ready`, an anchor (the active element if inside the body, else the first direct child whose `getBoundingClientRect().bottom > 0`) with its `top`, and the list of touched forms and dirty fields.
2. `renderBody(detail, document.createElement("div"))`, then `morphInto(bodyEl, tree.childNodes, { skip, flashSelector: "#wo-sec-actions", flashKey: textContent })`.
3. Tab: `showWorkOrderTab(bodyEl, before)` if that tab still exists, else `syncWorkOrderTabs(bodyEl, { settle: true })`.
4. Notes gate: if `cardEl.dataset.notesAck === "1"` and the log text is unchanged, hide `[data-action="ack-notes-wo"]` and enable every `[data-action="start-tracking-wo"]` (remove `title`); if it changed, `delete cardEl.dataset.notesAck`.
5. Dropped input: if any recorded form or field is no longer connected, `setMessage(#wo-sec-msg, "This work order changed while you were typing. Something you entered no longer applies.", "error")`.
   If a conflict was recorded and nothing was dropped: `setMessage(#wo-sec-msg, "Someone else changed a value you are editing. Saving yours will replace theirs.", "error")`, and add the class `wo-field-conflict` to each such field (removed by the next own-save repaint). One CSS rule in `styles.css`: an outline in the existing accent token.
6. Focus: if the recorded element is connected and is not `document.activeElement`, `focus({ preventScroll: true })` and restore its selection range. (iOS Safari has no `moveBefore`, so a moved element loses focus there.)
7. Scroll: only when `!CSS.supports("overflow-anchor", "auto")` (iOS Safari; Chrome and Firefox anchor by themselves and a second correction would jump): if the anchor is connected and its `top` moved, `window.scrollBy(0, newTop - oldTop)`.
8. Stamp the settle time when the recorded action text changed.

- [ ] **Step 1: Write the failing tests**

Each test opens the card page with `openCard`, sets the state, calls `patchBodyLive` with a changed detail, and asserts on the live document.

```js
// Review Focus 2
test("a line removed above a typed row: the typed quantity stays on its own line; rows match the server's order with no duplicate")
test("a typed row the server removed is gone, and the message line says input was dropped")
test("a typed quantity stays while its row's on-hand and name take the server's values")
test("an untouched row takes the server's quantity")
test("a picked add-material row keeps its item id, request id, search text and quantity")
test("the focused search keeps its open result list")
test("a half-typed note stays while the notes log shows the new note")
test("a typed labor hours box stays on its own entry when an entry is added above it")
// Review Focus 4
test("hours typed in the add-labor row: a crew change does not alter the technician shown or its options")
test("an untouched add-labor row takes the new crew")          // hazard 6: default select is not dirty
test("an add-labor row with a non-default technician picked is left alone")
// Review Focus 3
test("an SMR entry row in edit mode keeps its line id, fields, Save changes label and visible Cancel; the lines around it update")
test("a typed SMR hours box stays while its row's data-line takes the server's snapshot")
test("an open charge editor stays, and its Cancel still restores the cell")
test("an open Edit details form is untouched, the action bar updates, and deferred is true")
test("a closed Edit details form takes the server's values")
test("a focused, unchanged field is left alone and deferred is true")
test("the entry-mode select follows the server after the user changed it earlier")
test("the tab the user was on stays selected, also when the patch adds a section that is open by default")
test("both message lines keep their text and class, and the message line stays last")
test("a crew-lock hint that appears lands at the top, not in the message line")   // hazard 2
test("an acknowledged notes gate stays unlocked when the notes did not change")
test("new notes after an acknowledgement lock Begin Charging again and clear notesAck")
test("a typed note whose box the server removed (crew lock) raises the dropped-input message")
test("an update that removes the focused row does not throw and leaves focus in the document")
test("a focused field that the patch moved is focused again with its caret")
test("without native scroll anchoring, the page scrolls by the amount the anchor moved")   // stub CSS.supports false + getBoundingClientRect
test("with native scroll anchoring, the page is not scrolled by the patch")
test("a typed quantity whose saved value someone else changed is kept, outlined, and the message line warns that saving replaces theirs")
test("a typed quantity whose saved value did not change raises no warning")
test("across every pair of statuses and every role, no surviving element changes its data-action")   // Review Focus 5
test("sections and the More menu keep the open state the user gave them")
test("actionsSettling is true after the action bar's buttons change, false after 500 ms, and false when they did not change")
```

- [ ] **Step 2: Run to verify failure**

Run: `npx vitest run tests/frontend/views/workOrders/bodyLive.test.js`
Expected: FAIL, `patchBodyLive` is not exported.

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run to verify pass**

Run: `npx vitest run tests/frontend/views/workOrders/bodyLive.test.js tests/frontend/views/workOrders/bodyLiveCensus.test.js`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/static/views/workOrderLiveBody.js backend/static/styles.css tests/frontend/views/workOrders/bodyLive.test.js
git commit -m "feat(work-orders): patchBodyLive patches a card body around what the user touched"
```

---

### Task 4: Switch socket-driven refreshes to the patch

**Files:**
- Modify: `backend/static/views/workOrderList.js` (`refreshCardSummary` ~427, `runOrDeferListRefresh` ~508, `paintDetail` ~689, the status subscription ~840, the `toggle` listener ~865)
- Modify: `backend/static/views/workOrderActions.js` (click delegation ~112)
- Modify: `backend/static/api.js` (`parseResponse` ~69, `apiGetWorkOrder`)
- Modify: `docs/current-state.md` (one row for `workOrderLiveBody.js`; replace the "held card defers updates" statement)
- Test: `tests/frontend/views/workOrders/realtime.test.js` (extend; follow its socket-event pattern)

**Interfaces:**
- Consumes: `patchBodyLive`, `actionsSettling` (Task 3).
- Produces: `apiGetWorkOrder(id, { quiet401 = false } = {})`. With `quiet401`, a 401 rejects as usual but does not call the global unauthorized handler.

Behaviour on the card page only:
- The status subscription and `runOrDeferListRefresh` no longer test `isHeld`; they request a live refresh.
- Live refresh, one per card: a request while one is in flight sets a rerun flag and returns; the running one loops once more when it finishes.
- Each pass: read the card's paint counter; `await apiGetWorkOrder(id, { quiet401: true })`; then, in order: stop if `!cardEl.isConnected`; refetch if the counter changed; otherwise rewrite the summary and class, and if the card is open call `patchBodyLive` and set `dataset.loaded`, else `delete cardEl.dataset.loaded`.
- `cardEl.dataset.missedUpdate = "1"` when `deferred` is true; cleared otherwise.
- `paintDetail` increments the per-card paint counter (`WeakMap`).
- Catch-up: the `toggle` listener, and a new `focusout` listener on the list, request a live refresh for a card flagged `missedUpdate`.
- Errors: 404 shows "This work order is no longer available." only when the card is still connected; 401 and network failures change nothing.
- Click delegation: a click inside `#wo-sec-actions` or `.wo-smr-ready` while `actionsSettling(cardEl)` is ignored. (In-place reuse of a button is already impossible: Task 2's `wo-act-` ids.)

- [ ] **Step 1: Write the failing tests**

```js
test("an event while the Materials tab is open updates the lines")          // was: deferred
test("an event while a note is half-typed keeps the note and updates the status actions")
// Review Focus 1
test("two events whose responses arrive out of order end on the newer response")
test("three events in quick succession make at most two fetches")
test("a live response that a save's repaint overtook is dropped and refetched")
test("a response that arrives after the user opened another order changes nothing there")
test("a 404 that arrives after the user opened another order does not replace that order")
test("Edit details open during an event, then closed: the form shows the current values on reopen")
test("a field focused during an event catches up when focus leaves it")
test("a 401 on a live refresh does not call the unauthorized handler and changes nothing")
test("a 404 on a live refresh shows the unavailable message")
test("a network failure during a live refresh changes nothing on screen")
test("a draft replayed on reconnect ends with the saved entry shown and no stale overwrite")
test("heldWorkOrderCards still reports a card with an open section")
test("after the user's own save the saved field is empty")
// Review Focus 5
test("a status change removes the old action button from the document instead of relabelling it")
test("a tap on the action bar within 500 ms of its buttons changing does nothing; after 500 ms it works")
test("a keyboard-activated button still works")
```

- [ ] **Step 2: Run to verify failure**

Run: `npx vitest run tests/frontend/views/workOrders/realtime.test.js`
Expected: the new tests FAIL; existing deferral tests still pass.

- [ ] **Step 3: Implement**

Then rewrite each existing test that asserts "a held card is not refreshed" to the new rule, and list them in the commit body.

- [ ] **Step 4: Run to verify pass**

Run: `npx vitest run tests/frontend/views/workOrders tests/frontend/unit tests/frontend/views/hubTechnician.test.js tests/frontend/views/auth.test.js`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/static/views/workOrderList.js backend/static/views/workOrderActions.js backend/static/api.js tests/frontend/views/workOrders/realtime.test.js docs/current-state.md
git commit -m "feat(work-orders): live updates patch an open card around what the user is doing"
```

---

### Task 5 (owner's call): material, labor and SMR-line changes send the live event

Without this task, a patch runs only on status, details, notes, charging and signature changes.

**Files:**
- Modify: `backend/app/routers/work_orders.py` (items ~1368, ~1397, ~1417, ~1452; labor ~1468, ~1502, ~1528)
- Modify: `backend/app/routers/work_orders_smr.py` (lines ~259, ~289, ~304; ready ~169; paper-reviewed ~184; block ~356; pasted ~396)
- Modify: `docs/notification-events.md` only if it lists the emitting routes
- Test: the backend test file that already asserts `/hold` emits (find with `grep -rl _emit_status_changed tests`)

**Interfaces:**
- Consumes: `_emit_status_changed(work_order_id)`, after the service call succeeds, exactly as `/hold` does. No new event type.

- [ ] **Step 1: Write the failing tests** — one per route above, through a real `TestClient`: the route succeeds and one `work_order.status_changed` envelope carries the work order's id. One more: a route that fails validation emits nothing.
- [ ] **Step 2: Run to verify failure** — `pytest <that file> -k emits -q`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement** — one call per route. The line routes resolve the work order id from the line.
- [ ] **Step 4: Run to verify pass** — same command. Expected: PASS.
- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/work_orders.py backend/app/routers/work_orders_smr.py tests/<that file>
git commit -m "feat(realtime): material, labor and SMR-line changes announce the work order"
```

---

## After the last task

Not pushed until the owner's in-app check, two logins on one order, on a phone. Pushing `main` deploys.

| Owner checks | Passes when |
|---|---|
| Console on first load of a card | No security-policy violation |
| Type half a note; second login changes status | Note stays; status buttons change and glow once |
| Type a quantity on a line; second login saves a note | Your number is still on your line |
| Pick an item, do not press Add; second login changes status | Picked item and quantity stay |
| Open Edit details; second login changes priority; close and reopen | Form shows the new priority |
| Save a note | The note box is empty afterwards |
| Typing on iOS when the card changes above the field | Keyboard stays up; the field does not move |
| Tap a status button just as the second login changes status | Nothing happens; the new buttons work a moment later |
| With Task 5: second login adds a material while you read Materials | The line appears; reading position holds |

**Cannot be proved in jsdom, so the phone check is the gate:** focus and keyboard on iOS when an element moves, reading position, press-and-release ordering on touch, the security policy.
