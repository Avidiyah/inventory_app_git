# Frontend Test Harness — P6e (`tools.js` + `toolCheckout.js` + `toolReturn.js` + `toolCorrection.js` + `subnav.js`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task, **inline in the session — no subagents** (`CLAUDE.md` forbids them here). Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Status: go-ahead given 2026-09-11 ("Begin work on p6e"). Fifth P6 chunk; the largest module left in the app.**

**Goal:** Characterization coverage for the Tools page and its three custody editors (1,044 lines with `subnav.js` and the new fixture) — the Add Tool form and its scan widget, `loadTools` by role, the user-first custody picker and card, checkout / check-in, the inventory table with its editor, correction and archive actions, the contextual scanner, and `resetToolsView`. Plus `subnav.js`'s own contract as a unit file (parent deviation 3) and the `tools.js` action audit.

**Architecture:** Tests only, on the P0 harness. This chunk builds the phase's one new fixture, `helpers/tools.js`, modelled on P5c's `helpers/items.js`: `tools.js` cannot be the entry point of its own module graph (parent deviation 8 — `tools → scan → transactions → nav → tools`, with `nav.js` reading the `toolsScanner` const before `tools.js` finishes evaluating), so the fixture primes through `mountView("views/nav.js")` and then `importView("views/tools.js")`. Every assertion runs against the real shell markup, the real `mountScanner`, the real `initSubNav` and the real confirm overlay; MSW answers `/tools/`, `/users/`, `/tools/{barcode}` and the four write endpoints.

**Tech Stack:** Vitest, jsdom, @testing-library/dom, @testing-library/user-event, msw.

**Spec:** `docs/superpowers/specs/2026-09-10-frontend-test-harness-design.md` §3.2–3.3
**Parent plan:** `docs/superpowers/plans/2026-09-11-frontend-test-harness-p6.md` (the P6e bullets are the requirement set; deviations 3, 4 and 8 scope this chunk)
**Depends on:** P5c (`helpers/items.js` as the pattern for a cyclic-graph fixture), P5d (`helpers/requests.js`, `helpers/dialogs.js::answerConfirm`), P5g (`helpers/media.js` stubs, the upload path), P5h (`helpers/actionAudit.js`), P1 (`format.js` / `roles.js` / `skeleton.js` units already own `filterRanked`, `formatUserName`, `roleLabel`, `friendlyError`, `skeletonTableRows`).

## Global constraints

- Tests only. No edit under `backend/static/` or `backend/app/`.
- Characterization, not correction. Findings → `docs/open-work.md` → `N-P6-CHARACTERIZED`.
- No `vi.mock` of any app module. Seams: `fetch` (MSW), fake timers, the browser stubs, the real confirm overlay. `vi.spyOn` on the object `mountScanner` **returned** (`toolsScanner.reset` / `.stopLive` / `.refreshPermissionState`) is allowed and calls through — it is a spy on a value the module exports, not a module mock.
- `onUnhandledRequest: "error"` stays on.
- **Fake timers are opt-in**, as in P6d: only a test that advances an auto-close (1000 ms) calls `vi.useFakeTimers()` *before* mounting and drives input through `userEvent.setup({advanceTimers: vi.advanceTimersByTime})`.
- One mount per test (`setup.js` resets modules per test). `afterEach`: `restoreTools()`.
- New factories get a drift row in `unit/api.endpoints.test.js` in the same commit.
- Commit messages end with the attribution lines the session provides.

## Already pinned — do not re-cover

- P5b: `resetToolsView()` reached on logout ("no throw" only — this chunk asserts what it clears).
- P5g: `mountScanner`'s own contract — the decode call, the multi-barcode chooser, the live camera lifecycle, `supports()` gating. This chunk drives the **upload** path only, as P5c did for Items, and asserts the two `onItemFound` / `onNotFound` callbacks `tools.js` supplies.
- P6d: `correctionPanel.js`'s validation ladder, submit, auto-close and failure path (parent deviation 4). `toolCorrection.js` here asserts only its wiring: the `tool-correction-*` ids, `POST /tools/{id}/adjust`, and the refresh.
- P1: `filterRanked`, `formatUserName`, `roleLabel`, `friendlyError`, `skeletonTableRows`.

## Two deviations from the parent's P6e text, decided here

| # | Deviation | Why |
| --- | --- | --- |
| D1 | **Four view files, not two.** The parent allowed `toolsCustody.test.js` / `toolsInventory.test.js` "if the 500-line cap forces it". Eighty-odd tests at this suite's density is ~1,300 lines, so the split is `toolsCustody` (load by role, picker, card, check-in entry), `toolsCheckout` (checkout picker + both custody editors), `toolsInventory` (Add Tool, the table, editor / correction / archive) and `toolsScan` (the contextual scanner, `resetToolsView`). | `CLAUDE.md`'s 500-line cap; two files would breach it by 150 %. |
| D2 | **The scanner's "Select an active user before scanning for checkout." guard is reached by a reload that drops the scanned-for user**, not by a self-selected supervisor. A supervisor never sets `scanPurpose = "checkout"` — `checkoutScanBtn` refuses them first with "Select an active user first." — so the `!canManageCustody()` half of that guard is unreachable through the UI. Assert the reachable half (`!user`) and file the other. | Characterization rule: assert what the code does; the parent bullet named a path the code cannot take. |

## Entry gate

- [x] `npm test` green (P6d close: 1525 / 52, 195 s).

---

### Task 1: `helpers/tools.js` + the two factories

**Files:** Create `tests/frontend/helpers/tools.js`. Modify `tests/frontend/helpers/factories.js`, `tests/frontend/unit/api.endpoints.test.js`.

- [x] **`tool()`** against `ToolResponse` (`backend/app/schemas/tools.py`): `id` (uuid), `barcode`, `name`, `quantity` (a string — Pydantic serialises Decimal that way, as `item()` already does), `created_at`, `custody: []`. **`toolCustodyEntry()`** against `ToolCustodyEntry`: `user_id`, `user_name`, `quantity` (string). Drift rows for both in `unit/api.endpoints.test.js`, schema path `backend/app/schemas/tools.py`.
- [x] **`mountTools({role, tools, users, handlers})`:** `server.use(...handlers, http.get("/tools/", …), http.get("/users/", …))` off its arguments (handlers first, as `mountItems` does); `stubUserMedia()`, `stubPermissions("prompt")`, `stubScrollIntoView()` (`toolCheckout.js`, `toolReturn.js`, the tool editor and `setActiveUserOption` all call it unguarded — the same class as the P5 finding; extend that `open-work.md` row rather than adding a new one); `setTestUser({role})`; `startRecording()`; `mountView("views/nav.js")` then `importView("views/tools.js")`; `clearRequests()`. Returns `{mod, currentUser, scrollIntoView}`. **As built** it also takes `currentUser` overrides (the signed-in user IS the roster below techfm_oa, so a card-date test must choose their `created_at`) and exports `custodyUser()`, because `UserResponse.id` is a UUID and the picker resolves a click by comparing it against `dataset.userId` — the shared `user()` factory's integer ids can never match.
- [x] **`el` getters** (byId closures, never captured nodes) over the custody ids (`tool-user-picker`, `-search`, `-results`, `-card`, `-name`, `-meta`, `-status`, `tool-user-custody-count`, `tool-user-holdings`, `tool-custody-message`, `tool-checkout-controls`, `-search`, `-results`, `-scan-btn`, `-picker-message`), the two editors (`tool-checkout-*`, `tool-return-*`), the inventory ids (`tools-thead-row`, `tools-tbody`, `tools-search`, `tools-message`, `tool-editor-*`, `tool-correction-*`), the Add Tool ids (`create-tool-btn`, `create-tool-message`, `tool-barcode`, `tool-name`, `tool-quantity`, `tool-scan-*`) and the scan ids (`tools-scan-*`). Plus `rows()`, `headers()`, `actionSelect(i)`, `userOptions()`, `checkoutOptions()`, `holdingRows()`, `subNavBtn(feature)`.
- [x] **`openTools(opts)`** = `mountTools(opts)` + `await mod.loadTools()` + `clearRequests()` — the fixture's normal entry, since nothing on this page loads at import.
- [x] Re-export `requests`, `requestFor`, `clearRequests`, `answerConfirm`, `upload`, and `answerDecode` / `answerToolLookup` (the `/barcodes/decode` and `/tools/{barcode}` answers, shaped like `helpers/items.js`'s pair). `restoreTools()` = `stopRecording()` + `restoreMediaStubs()` + `restoreBrowserStubs()`.
- [x] Smoke it against one throwaway test, then commit `test(p6e): the tools fixture and the tool/custody factories`.

---

### Task 2: `unit/subnav.test.js`

**Files:** Create `tests/frontend/unit/subnav.test.js`. Mounts the real shell (`mountShell()`) and imports `views/subnav.js` — no fixture, no fetch.

- [x] The button pre-marked `.active` in the markup wins over the first button; with none marked, the first wins.
- [x] The initial switch sets `hidden` on every non-matching `.feature-panel`, `.active` on exactly one `.sub-nav-btn`, and `pageEl.dataset.activeFeature`.
- [x] `fireInitialOnShow: false` does all of that **without** calling `onShow`; the default calls it once with `(name, null)`.
- [x] A click on a sub-nav button switches and calls `onShow(name, prev)` with the previous feature.
- [x] Re-selecting the active feature is a no-op — no second `onShow`, no DOM churn.
- [x] A click on the nav that is not a `.sub-nav-btn`, and a button with no `data-feature`, are ignored.
- [x] A page with no `.sub-nav` still initialises (the panels/buttons are found by `pageEl` query, the listener is simply not attached) — build a bare `<div class="page">` for this one rather than a shell page.
- [x] `showFeature` returned by the handle drives the same path as a click.
- [x] Run the file; commit `test(p6e): subnav — initial selection, the onShow contract, idempotence`.

---

### Task 3: `views/toolsCustody.test.js`

**Files:** Create `tests/frontend/views/toolsCustody.test.js`.

- [x] **`loadTools` by role:** techfm_oa / admin / owner fire `GET /tools/` **and** `GET /users/` (no `include_archived`), show `#tool-user-picker` and write "Search for a user to view tool custody."; supervisor / technician fire `/tools/` only, hide the picker, self-select from `getCurrentUser()` and paint the card with an empty custody message.
- [x] **The skeleton:** 5 columns for a custody manager, 4 below, before the fetch resolves.
- [x] **`/tools/` 500:** an error row with `colspan="5"` **for every role** — a non-manager's table has four columns, so the row spans one column too many (file it) — plus `friendlyError`'s detail in `#tool-custody-message`, and `getTools()` emptied.
- [x] **`/users/` 500:** "Could not load active users. Try again." (or the detail), `custodyUsers` emptied and the selection cleared (the card hidden).
- [x] **Archived users are dropped** and the rest name-sorted by `formatUserName`; **a selected user missing from a reload** → `clearSelectedUser()` (card hidden, both editors closed).
- [x] **User picker:** focus lists everyone, capped at 8 (mount 10); typing filters through `filterRanked`; editing the chosen name clears the selection and closes both editors; ArrowDown / ArrowUp wrap with `aria-activedescendant` and `.is-active` tracking; Enter picks the active option (and does nothing with no active option); Escape hides; a click on an option picks.
- [x] **The card:** `formatUserName`, `"<roleLabel> · Created <toLocaleString>"`, "Created date unavailable" for both a null and an unparseable `created_at`, "Active", the singular "1 tool record currently checked out" vs the plural, holdings rows (name, barcode, checked-out quantity, a Check In button per row) or "No tools currently checked out.", `#tool-checkout-controls` hidden below techfm_oa, and `userCard.focus()` on choose.
- [x] **A document click outside** `#tool-user-picker` hides the results; outside `#tool-checkout-controls` hides `#tool-checkout-results`.
- [x] **Check In → `openToolReturn`:** the return section shows "name (barcode)", "Name has N checked out", quantity prefilled to N and `max` = N; an open checkout editor is closed first; a Check In whose custody entry no longer matches the selected user is ignored.
- [x] Run the file; commit `test(p6e): tools custody — loadTools by role, the user picker, the card, check-in entry`.

---

### Task 4: `views/toolsCheckout.test.js`

**Files:** Create `tests/frontend/views/toolsCheckout.test.js`. Covers the checkout picker plus both custody editors (`toolCheckout.js`, `toolReturn.js`).

- [x] **Checkout picker:** focus lists tools with `quantity > 0`, name-sorted, capped at 8; the two empty copies ("No available tools match that search." with a query, "No tools are currently available." without); input closes an open checkout editor and re-renders; Escape hides the results; Enter clicks the first option; a click opens the editor with the tool name written into the search box, the results hidden and the return editor closed.
- [x] **`openToolCheckout` render:** "name (barcode) — N on hand", "Checking out to Name", quantity "1" focused and selected, `max` = on hand, the work-order field blank.
- [x] **Checkout validation:** nothing open → "Select a user and tool first."; a blank quantity and `0` → "Enter a quantity greater than zero."; over the limit → "Only N on hand." Each writes nothing and leaves the section open. (A `type="number"` input cannot hold `abc`, so the `!Number.isFinite` half of the first guard is unreachable from the DOM — the twin of P6d's correction finding; file it once for both editors.)
- [x] **Checkout save:** `POST /tools/{id}/checkout` with `{quantity, assigned_to_id, work_order_number}` — `null` for a blank work order, trimmed otherwise; "Checked out NAME to USER." with the `success` class; `onSaved` is `refreshTools`, so a second `GET /tools/` fires and the card repaints from the new payload; the section closes 1000 ms later on fake timers; a failure writes `friendlyError`'s copy and keeps it open.
- [x] **Checkout cancel** resets quantity to "1", drops `max`, clears the work order and the message, and hides the section.
- [x] **Return, the same five bullets** against `openToolReturn(tool, user, custody)`: "Select a checked-out tool first."; "Enter a quantity greater than zero."; "Only N checked out."; `POST /tools/{id}/return` with the same body shape; "Checked in NAME for USER."; the refresh, the 1000 ms close, the failure copy, and cancel (which resets quantity to "1", **not** to the outstanding balance).
- [x] **A failing `refreshTools` after a successful save** writes "The change was saved, but tool data could not be refreshed." (or the detail) into **both** `#tools-message` and `#tool-custody-message`, over the success copy the editor just wrote.
- [x] Run the file; commit `test(p6e): tool checkout and check-in — the picker, both ladders, the save sequence`.

---

### Task 5: `views/toolsInventory.test.js`

**Files:** Create `tests/frontend/views/toolsInventory.test.js`.

- [x] **Add Tool (create-item Tool tab):** "Enter a barcode and a tool name." for a blank barcode, a blank name and both; a blank quantity posts `1` while a filled one posts `parseFloat`; `POST /tools/` body `{barcode, name, quantity}`; success writes "Tool saved." and clears barcode / name with quantity back to "1"; a failure writes `friendlyError`'s copy and clears nothing.
- [x] **`toolScanWidget` (upload path):** a match → "Already in use by NAME." with the `error` class and `#tool-barcode` untouched; a 404 → `#tool-barcode` filled with the scanned code and `#tool-scan-controls` hidden; the toggle reveals the controls, and collapsing them calls `stopLive()` (spy on the exported widget).
- [x] **The table:** 5 headers for a custody manager (Barcode / Name / On Hand / Checked Out / Actions), 4 below; `filterRanked` over name and barcode as the search input fires; "No tools match that search." with a term and "No tools yet." without, each spanning the role's column count; the custody cell joins `user_name: quantity` with `<br>` and renders "—" when empty; the actions `<select>` renders for managers only, with the frozen three options.
- [x] **`edit`:** the editor opens prefilled with "Editing: name (barcode)"; a blank barcode or name → "Barcode and name are required." and no request; `PATCH /tools/{id}` with `{barcode, name}` → "Tool updated." → a refresh `GET /tools/` → the section closes 1000 ms later; a failure keeps it open with the detail.
- [x] **`correct` (wiring only, parent deviation 4):** `#tool-correction-section` opens on the chosen row with "Correcting: name (barcode)" and the current count; Save with a reason posts `POST /tools/{id}/adjust` `{new_quantity, reason}` and fires the refresh; `getCorrectingToolId()` tracks the open row.
- [x] **`delete`:** the real `confirmDialog('Archive "name"? Its history will be kept.')` — No writes nothing; Yes sends `DELETE /tools/{id}`, writes 'Archived "name".' and refreshes; an open editor **or** correction on that same tool is closed first, and one on a *different* tool is left open; a failure writes "Could not archive the tool. Try again." (or the detail).
- [x] **The select resets to the placeholder** after every action, and an action on a tool no longer in `getTools()` is ignored.
- [x] Run the file; commit `test(p6e): tools inventory — the table, the editor, correction wiring and archive`.

---

### Task 6: `views/toolsScan.test.js` + `views/toolsActionCoverage.test.js`

**Files:** Create `tests/frontend/views/toolsScan.test.js`, `tests/frontend/views/toolsActionCoverage.test.js`.

- [x] **Lookup path:** a found tool switches to the inventory feature, writes the barcode into `#tools-search`, re-renders the table filtered to that row, and calls the row's guarded `scrollIntoView({behavior: "smooth", block: "center"})`.
- [x] **The Scan sub-nav button:** restores the lookup heading / hint, calls `reset()` and `refreshPermissionState()` — the last one **twice**, because the button's own listener and the sub-nav's `onShow` both fire (pin the count rather than "at least once").
- [x] **"Scan Tool to Check Out":** with no selected user (or below techfm_oa) → "Select an active user first." in `#tool-checkout-picker-message` and no feature change; with one → both editors closed, the heading "Scan Tool for Checkout", the hint naming the user, `reset()`, the scan feature active and `refreshPermissionState()` called.
- [x] **A checkout scan that finds a tool** → back to the lookup context, the custody feature, the return editor closed and `openToolCheckout(tool, user)` rendered against the scanned tool.
- [x] **Quantity 0** → "NAME has no units on hand." and no editor.
- [x] **The `!user` guard (D2):** after arming the checkout context, a `loadTools()` reload whose `/users/` payload drops that user makes the next found scan write "Select an active user before scanning for checkout." File the `!canManageCustody()` half as unreachable through the UI.
- [x] **`onShow` transitions:** leaving scan calls `stopLive()` and restores the lookup context; leaving custody closes both editors and hides `#tool-checkout-results`; leaving inventory closes the editor and the correction panel.
- [x] **`resetToolsView`:** both search boxes cleared, the user results hidden, the card hidden, all four panels closed, `getTools()` empty, `toolsScanner.reset()` called (P5b asserted only "no throw"), the custody feature active and both message slots blank.
- [x] **The audit:** `auditActions` over `views/tools.js` with `renderedPattern: /<option value="([a-z-]+)">/g`, `handledPattern: /action (?:===|!==) "([a-z-]+)"/g` (the default misses `action !== "delete"`), frozen `["correct", "delete", "edit"]`, `behaviourDir` = the views directory with everything but this chunk's four files excluded. No helper change.
- [x] **Verify the audit bites:** comment out the `edit` tests locally, confirm the audit names `edit`, restore.
- [x] Run both files; commit `test(p6e): the contextual tool scanner, resetToolsView and the action audit`.

---

### Task 7: Findings, docs, parent plan

- [x] `docs/open-work.md` → `N-P6-CHARACTERIZED`: the `colspan="5"` error row on a four-column table; the unreachable `!Number.isFinite` half of both quantity guards; the unreachable `!canManageCustody()` half of the checkout-scan guard; the unguarded `scrollIntoView` row extended with `toolCheckout.js` / `toolReturn.js` / `tools.js`; whatever else the run surfaces.
- [x] `docs/current-state.md`: the Tools UI row no longer reads "manual UI check (no Vitest suite for these views yet)" (parent D7); the Vitest bullet names the new files with an updated count / time.
- [x] Parent plan: tick the P6e bullets; suite-budget row `P6e | 1647 / 58 | 165 s`.
- [x] `npm test` to completion — **1647 / 58, 164.5 s**; commit `docs: record P6e — the tools page and its custody editors`.

## Done when

- [x] Six commits plus the docs commit, each green at commit time.
- [x] Every export called by name: `loadTools`, `renderTools`, `resetToolsView`, `toolsScanner`, `toolScanWidget` (`tools.js`); `openToolCheckout`, `closeToolCheckout`, `setOnSaved` (`toolCheckout.js`); `openToolReturn`, `closeToolReturn`, `setOnSaved` (`toolReturn.js`); `openToolCorrection`, `closeToolCorrection`, `getCorrectingToolId`, `setOnSaved` (`toolCorrection.js`); `initSubNav` (`subnav.js`).
- [x] `tools.js`'s three row actions are named by the audit, and deleting one action's tests turns it red.
- [x] Findings filed; docs updated; the suite under the ~6-minute line.

## Deliberately not in P6e

- Any production change, and any fix for what characterization reveals.
- `correctionPanel.js`'s own ladder (P6d, parent deviation 4).
- `mountScanner`'s camera lifecycle and chooser (P5g).
- `users.js` and its audit (P6f), `push.js` (P6g).
