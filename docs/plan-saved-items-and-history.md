# Plan: Saved Items + History UX Pass

Status: **Planning only — no code changes yet. All open questions
resolved (see Decision log at the bottom).**

This document tracks five related changes the user has asked for. It
captures *what* we want, *where* it lives in the current codebase, and
*how* it should behave. The Decision log records the answers we got
for every previously open question so the implementation phase has no
ambiguity.

---

## 1. Barcode scanner on the Saved Items page

### Goal
Re-use the camera/upload scanner that lives on the Transaction page so
it is also available on the Saved Items page. Scanning a barcode there
should help the user find the matching row in the items table.

### Where it lives today
- View: [backend/static/views/scan.js](backend/static/views/scan.js) — owns the file input, calls
  `apiDecodeBarcode`, then `apiGetItemByBarcode`, branches on
  0/1/many results, and on success calls
  `focusItemByBarcode(item)` from [backend/static/views/transactions.js](backend/static/views/transactions.js).
- Markup: `#txn-scan-section` in [backend/static/index.html](backend/static/index.html#L229-L238)
  (file input `#txn-scan-input`, message `#txn-scan-message`,
  chooser `#txn-scan-chooser`).
- API: `apiDecodeBarcode` in [backend/static/api.js](backend/static/api.js#L103) — already exists, no
  backend work needed.

### Proposed approach
1. Add a second scan section to the Saved Items page in
   [backend/static/index.html](backend/static/index.html#L95), above the search bar inside
   `#items-section`. New element ids prefixed `items-scan-…`
   (input, message, chooser) so they do not collide with the
   transaction page's ids.
2. Refactor [backend/static/views/scan.js](backend/static/views/scan.js) from a single hard-coded
   binding into a small `mountScanner({ inputEl, messageEl, chooserEl, onItemFound, allowCreate })`
   factory. The Transaction page wires it with
   `onItemFound = focusItemByBarcode`; the Saved Items page wires
   it with an `onItemFound` that:
   - Sets `itemsSearch.value = item.barcode`, calls `renderItems()`
     to filter the table to the one matching row, and
   - Scrolls that row into view (optional polish).
3. `allowCreate` stays `true` on Transaction (existing behaviour).
   On Saved Items the 404 branch keeps the same **"Create a new
   item for X" button shortcut** the Transaction page uses today
   (Q1.1 — option B). Because the Create Item form lives on the
   same page, the shortcut handler on Saved Items doesn't need to
   trigger a nav button: it pre-fills `#barcode` and scrolls to the
   `#create-item-section`. The shortcut button itself is still only
   shown to Owner/Admin (same gate the Transaction-page scanner uses
   today), even though the scanner control is shown to everyone
   (Q1.2).
4. **Visibility (Q1.2):** the scanner control is rendered for **all
   roles** on Saved Items. It is a read-only lookup aid; gating it
   would only frustrate Supervisor/Technician users who already use
   the same scanner on the Transaction page. The Create-Item
   shortcut inside the chooser remains Admin+ only.
5. No changes to [backend/static/api.js](backend/static/api.js), no backend changes.

### Resolved decisions
- **Q1.1 → B.** Use the existing "Create a new item for X" button
  shortcut on 404 (adapted to scroll to the same-page Create form
  instead of triggering a page nav).
- **Q1.2 → All roles.** Scanner visible to Owner / Admin /
  Supervisor / Technician on Saved Items. The Create-Item shortcut
  inside the chooser stays Admin+.

---

## 2. Replace per-row action buttons with a dropdown

### Goal
On the Saved Items table, swap the inline cluster of buttons
(`Edit`, `Edit Notes`, `Correct`, `🗑️`) in the **Actions** column for
a single dropdown (`<select>`) that lists the same actions; selecting
one performs that action immediately.

### Where it lives today
- Render: [backend/static/views/items.js](backend/static/views/items.js#L92-L107) builds the action
  cell as a `<div class="row-actions">` of four buttons (only when
  `roleAtLeast(getRole(), "admin")`).
- Click handling: same file, the delegated listener on
  `itemsTbody` (lines ~167-211) dispatches on
  `target.classList.contains(...)`.

### Proposed approach
1. Replace the per-row buttons with a single `<select class="row-actions-select" data-id="…">`
   containing a disabled, selected placeholder `Actions` (Q2.1) and
   one `<option>` per action the row's viewer can perform. Action
   set is gated per-role (see §3):
   - Owner / Admin: `edit`, `notes`, `correct`, `delete`.
   - Supervisor: `notes` only.
   - Technician: no dropdown — render `—` placeholder cell.

   For `delete` we look up the item name from `getItems()` by id
   at click time instead of encoding `data-name` on the element,
   so the markup stays small.
2. Replace the delegated `click` listener with a delegated
   `change` listener on `itemsTbody` that:
   - Reads `event.target.value` and `event.target.dataset.id`.
   - Branches into the same handlers we have today
     (`openItemEditor`, `openNotesEditor`, `openCorrection`,
     `apiDeleteItem` + cleanup).
   - Keeps the `confirm("Are you sure you want to delete …")`
     prompt for the delete branch (Q2.2) — dropdown changes are
     easier to fat-finger than button clicks, so the confirm is
     more valuable, not less.
   - Resets the `<select>` back to the placeholder so the user can
     pick the same action again later without it being a no-op.
3. Accessibility (Q2.3): each row's `<select>` gets a
   visually-hidden `<label>` (e.g. `Actions for <item name>`),
   produced inline with `class="sr-only"` or wrapped using the
   `aria-label` attribute. Add an `.sr-only` utility rule to
   [backend/static/styles.css](backend/static/styles.css) if one doesn't already exist.
4. CSS: add a `.row-actions-select` rule in
   [backend/static/styles.css](backend/static/styles.css) to match the existing button sizing /
   row alignment so the table doesn't visually shift.
5. Delete the now-unused `.edit-item-btn / .edit-notes-btn /
   .correct-item-btn / .delete-btn` rules from
   [backend/static/styles.css](backend/static/styles.css) **only after** confirming nothing else on
   the page (e.g. the item editor's own Save/Cancel) reuses those
   class names. Quick grep before deleting.

### Resolved decisions
- **Q2.1 → `Actions`** as the placeholder text (no ellipsis).
- **Q2.2 → Yes**, keep the `confirm()` prompt on delete.
- **Q2.3 → Yes**, add a per-row visually-hidden label /
  `aria-label` to the action `<select>`.

---

## 3. Restrict Saved Items actions (with a Supervisor carve-out for notes)

### Final rule (Q3.1)
Per-action minimum role on the Saved Items page:

| Action      | Minimum role |
|-------------|--------------|
| Edit item   | Admin        |
| Edit notes  | **Supervisor** |
| Correct qty | Admin        |
| Delete item | Admin        |

The carve-out for **Edit Notes** is intentional — notes are an
operational field (counts, locations, ad-hoc info), not an
administrative one, so Supervisors should be able to maintain them.
Technicians remain fully read-only on the Saved Items table.

### Current state
The frontend in [backend/static/views/items.js](backend/static/views/items.js#L91) currently uses a single
`canWrite = roleAtLeast(getRole(), "admin")` gate, so today
Supervisor sees no action cell at all. We have to broaden that
gate **per action** to land the Q3.1 rule.

### What needs to happen
1. **Frontend gating in `items.js`** — compute per-action visibility:
   ```js
   const canAdmin = roleAtLeast(getRole(), "admin");
   const canNotes = roleAtLeast(getRole(), "supervisor");
   ```
   Build the action `<select>`'s options conditionally so the
   Supervisor row only shows the single `notes` option (and the
   placeholder). Technician rows still get a `—` cell.
2. **Backend audit** — verify the routes match the table above
   (frontend gating is cosmetic only):
   - `PATCH /items/{id}` (edit) — should require Admin+.
   - `PATCH /items/{id}/notes` (notes) — should require **Supervisor+**.
     This may already be the case; flag and confirm during
     implementation. If it is currently Admin+, **relax** it to
     `require_min_role(roles.ROLE_SUPERVISOR)`.
   - `POST /transactions/adjust` (correct) — already Admin+ per the
     comment in [backend/static/api.js](backend/static/api.js#L168). Re-verify.
   - `DELETE /items/{id}` (delete) — should require Admin+.
   - To-do during implementation: grep [backend/app/routers/items.py](backend/app/routers/items.py)
     and [backend/app/routers/transactions.py](backend/app/routers/transactions.py) for
     `require_min_role(...)` on each route and record findings
     in the PR description.
3. After the dropdown change in §2, make sure Technician rows still
   render a sensible empty cell (e.g. `—`) and the `change`
   listener simply doesn't fire because no `<select>` exists.

### Resolved decisions
- **Q3.1 → Admin+ for edit / correct / delete, Supervisor+ for
  edit notes.** Backend `notes` route must be widened to match if
  it is currently Admin+.

---

## 4. History: filter by Work Order Number

### Goal
On the Transaction History page, let the user filter the displayed
table by Work Order Number, in addition to the existing
"By Item / By User" filters.

### Where it lives today
- View: [backend/static/views/history.js](backend/static/views/history.js) — tabs `all` /
  `item` / `user`, paged via `getHistoryState()` /
  `updateHistoryState()`.
- API client: `apiListTransactions({ page, pageSize, itemId, userId })`
  in [backend/static/api.js](backend/static/api.js#L135).
- Backend route: `GET /transactions/` in
  [backend/app/routers/transactions.py](backend/app/routers/transactions.py#L93) → `history_service.list_history(...)`
  in [backend/app/services/history.py](backend/app/services/history.py#L24) — accepts
  `item_id` and `user_id`; does **not** yet accept work order.
- Model column: `Transaction.work_order_number` already exists
  (nullable, set on stock/dispense rows).

### Proposed approach
1. **Backend**
   - Add an optional `work_order_number: Optional[str]` query
     parameter to `list_transactions` in
     [backend/app/routers/transactions.py](backend/app/routers/transactions.py#L93).
   - Plumb it through to `history_service.list_history(...)` in
     [backend/app/services/history.py](backend/app/services/history.py#L24).
   - Filter (Q4.2): **case-sensitive substring** match using
     `Transaction.work_order_number.like(f"%{value}%")` (not
     `ilike`). Trim whitespace; skip the filter entirely when the
     trimmed value is empty. Escape the SQL `LIKE` wildcards `%`
     and `_` in the user input so a literal `%` or `_` in a WO
     doesn't widen the match.
   - Combine with the existing `item_id` / `user_id` filters via
     AND. Update the router docstring to mention the new filter.
2. **Frontend — state**
   - In [backend/static/state.js](backend/static/state.js) add a `workOrder` field to
     `historyState` (default `null`) and surface it through
     `updateHistoryState`. Important: the WO filter **does not
     reset** when the user switches sub-tabs (it overlays them).
3. **Frontend — API**
   - Extend `apiListTransactions` in [backend/static/api.js](backend/static/api.js#L135) to accept
     and forward `workOrder` as `work_order_number`.
4. **Frontend — UI (Q4.1: overlay)**
   - Add a `filter-row` *above* `#history-tabs` in
     [backend/static/index.html](backend/static/index.html#L289) with a text input
     `#history-wo-filter` (placeholder `Filter by Work Order`) and
     a small `Clear` button. The filter is visible on every sub-tab.
   - On `input` (debounced ~250 ms) call
     `updateHistoryState({ workOrder: value || null, page: 1 })`
     then `loadHistory()`. The Clear button sets the input to `""`
     and fires the same handler.
   - Pass `workOrder` into `apiListTransactions` from
     [backend/static/views/history.js](backend/static/views/history.js#L75).
   - **Empty-state message (Q4.3):** when the page comes back with
     zero rows, compose the empty message from the active filters.
     Examples:
     - `No transactions found.` (no filters)
     - `No transactions match WO "1234".`
     - `No transactions match WO "1234" for user Alice.`
     - `No transactions match WO "1234" for item Widget (ABC123).`
     Built by joining a fixed prefix with the currently-active
     filter clauses, in [backend/static/views/history.js](backend/static/views/history.js)'s
     `renderHistory(data)`.

### Resolved decisions
- **Q4.1 → Overlay.** WO filter is always visible above the
  sub-tabs and composes with `item` / `user` filters via AND.
- **Q4.2 → Case-sensitive substring (`LIKE %value%`).** Escape
  `%` and `_` in the user input.
- **Q4.3 → Yes.** Empty-state message surfaces the active WO
  filter (and any combined filters).

---

## 5. History: "Copy table to clipboard" button

### Goal
Add a button near the History results that copies the currently
displayed table (header + all visible rows on the current page) to
the clipboard in a format that pastes cleanly into Excel / Google
Sheets / etc.

### Where it lives today
- Markup: `#history-results` block in
  [backend/static/index.html](backend/static/index.html#L322), wrapping `#history-table` and the
  pagination footer.
- Render: `renderHistory(data)` in [backend/static/views/history.js](backend/static/views/history.js).

### Proposed approach
1. Add a button `#history-copy-btn` inside `#history-results`,
   visually grouped with the pagination footer (top-right of the
   results area, above the table). Label: `Copy table`. The button
   is **disabled** (Q5.3) whenever the current page has zero rows
   (after `renderHistory()` paints).
2. **Scope (Q5.1): all pages matching the current filters**, not
   just the visible page. The button must therefore fetch the full
   filtered result set, not just read the DOM.
3. **Fetch strategy.** Re-use `apiListTransactions` with the same
   `itemId` / `userId` / `workOrder` filters as the current state,
   but paginate in a loop using the largest server-allowed page
   size (`page_size = 100`, the existing backend cap in
   [backend/app/routers/transactions.py](backend/app/routers/transactions.py#L98)) until we've
   collected `data.total` rows. Pseudocode:
   ```js
   const PAGE = 100;
   const all = [];
   let page = 1, total = Infinity;
   while (all.length < total) {
     const data = await apiListTransactions({
       page, pageSize: PAGE, itemId, userId, workOrder,
     });
     all.push(...data.items);
     total = data.total;
     if (data.items.length === 0) break;  // safety: avoid infinite loop
     page += 1;
   }
   ```
   While the loop runs, disable the button and show a "Copying…"
   status via `setMessage`. Cap the loop with a sane maximum
   (e.g. 100 pages = 10 000 rows) so a runaway dataset can't hang
   the browser — log a warning and copy what was fetched.
4. **Format.** TSV (tab-separated values) — spreadsheets paste TSV
   into separate columns automatically. **Include the column
   headers** (Q5.2) as the first row, matching the on-screen
   `<thead>` labels (`Timestamp`, `Item`, `Type`, `Quantity`,
   `Work Order`, `User`). Mirror the on-screen formatting from
   `renderHistory`:
   - Timestamp via `new Date(txn.created_at).toLocaleString()`.
   - Item as `"<name> (<barcode>)"`.
   - The overloaded fifth column: for `adjust` rows show
     `txn.reason || txn.work_order_number || ""`; for stock /
     dispense show `txn.work_order_number || ""`.
   - Username `|| ""` (empty cell for anonymous rows).
   Strip newlines / tabs inside cell text (replace with a single
   space) to keep the columns aligned.
5. **Helper boundary.** To avoid duplicating the per-row format
   logic between `renderHistory` and the copy path, extract a tiny
   pure helper in [backend/static/views/history.js](backend/static/views/history.js):
   ```js
   function formatRow(txn) { return [timestamp, item, type, qty, detail, user]; }
   ```
   Use it from both the table render and the TSV builder.
6. **Clipboard write.** `navigator.clipboard.writeText(tsv)`. On
   success, flash `Copied N rows.` via `setMessage` in
   `#history-results`. On failure (clipboard API blocked / insecure
   context / older browser), fall back to a hidden `<textarea>` +
   `document.execCommand("copy")`; if even that fails, leave the
   textarea visible and selected with an error message so the user
   can `Ctrl+C` manually.

### Resolved decisions
- **Q5.1 → All pages matching the current filters.** Implemented
  via a paginated loop using the existing `apiListTransactions`
  (`page_size = 100`) — no backend change needed.
- **Q5.2 → Yes**, include the column headers as the first TSV row.
- **Q5.3 → Yes**, disable the button when the table is empty.

---

## Cross-cutting notes

- **No new dependencies.** All five items use the existing API
  surface (or, for §4, a tiny additive change), the existing
  `roles.js` gating, and the existing `state.js` pattern. No new
  libraries, no migrations.
- **Backend migration impact:** none. §4 only adds a query
  parameter; no schema change is needed because
  `Transaction.work_order_number` already exists.
- **Backend policy change in §3:** if the notes route is currently
  Admin+, it gets **relaxed** to Supervisor+. That is a deliberate
  privilege widening — call it out in the PR description so a
  reviewer doesn't miss it.
- **Testing:** add backend tests for
  - the new `work_order_number` query parameter (substring match,
    empty value short-circuit, `%` / `_` escaping),
  - and the loosened minimum role on the notes route,
  in `tests/` (mirrors the existing `test_barcodes.py` /
  `test_roles.py` style). Frontend changes remain manual-test for
  now, consistent with the current codebase.
- **Docs:** after implementation, update
  [docs/feature-report.md](docs/feature-report.md) (user-visible features) and
  [docs/interfaces.md](docs/interfaces.md) (if the WO query parameter or the notes-route
  minimum role is part of the documented HTTP surface).

---

## Decision log

All questions are resolved. The implementation phase should treat
these as fixed.

| ID    | Question                                                              | Decision |
|-------|-----------------------------------------------------------------------|----------|
| Q1.1  | Unknown-barcode UX on Saved Items                                     | **B — keep the "Create a new item for X" shortcut button** (adapted to scroll to the same-page Create form). |
| Q1.2  | Show the Saved Items scanner to read-only roles?                      | **All roles.** The Create-Item shortcut inside the chooser stays Admin+. |
| Q2.1  | Action dropdown placeholder text                                      | **`Actions`** (no ellipsis). |
| Q2.2  | Keep `confirm()` for delete?                                          | **Yes.** |
| Q2.3  | Per-row hidden `<label>` / `aria-label` for the action `<select>`?    | **Yes.** |
| Q3.1  | Final per-action role rule on Saved Items                             | **Admin+ for edit / correct / delete; Supervisor+ for edit notes.** |
| Q4.1  | WO filter: overlay vs. dedicated tab                                  | **Overlay** above the existing sub-tabs; composes with `item` / `user` via AND. |
| Q4.2  | WO filter match mode                                                  | **Case-sensitive substring (`LIKE %value%`)**; escape `%` and `_`. |
| Q4.3  | Empty-state message includes the WO and other active filters?         | **Yes.** |
| Q5.1  | Copy scope                                                            | **All pages matching the current filters**, fetched via a paginated loop (`page_size = 100`). |
| Q5.2  | Include column headers in the copy?                                   | **Yes** — headers as the first TSV row. |
| Q5.3  | Disable Copy when the table is empty?                                 | **Yes.** |

---

## Suggested implementation order

1. §3 backend audit + notes-route relaxation (locks the role
   story before the UI is redesigned on top of it; small,
   isolated change with a dedicated test).
2. §2 dropdown swap, including the per-action role gating from §3
   on the frontend (so Supervisors see the notes-only dropdown).
3. §1 scanner factory + Saved Items mount (refactors `scan.js` —
   do it after §2 so we're not editing the same view twice).
4. §4 work-order filter end-to-end (backend → API client → state →
   UI), with the new backend test.
5. §5 copy-to-clipboard button (depends on §4 so the copied output
   reflects WO-filtered rows; uses the paginated-fetch loop).
