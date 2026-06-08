# Inventory Management System — Living Spec

> **How to use this document:** This is the evolving source of truth for what the system _does_ and _is intended to do_. Update it whenever a feature is added, changed, or removed. Use it alongside `reference.md` when briefing an AI — reference covers stable technical facts; this spec covers current behaviour, intent, and open questions.

---

## System Purpose

A self-hosted inventory management tool for tracking physical items by barcode. Operators can stock and dispense items, associate transactions with named users, attach free-form metadata (notes) to items, and review full transaction history. The backend and frontend are co-located in a single FastAPI process.

---

## Current State — Feature Summary

|Feature|Status|
|---|---|
|Create / list / delete items|✅ Working|
|Create / list / delete users|✅ Working|
|Stock and dispense transactions|✅ Working|
|Void (delete) a mis-clicked transaction|✅ Working — Supervisor+; soft delete, hidden from history, reverses stock|
|Item price & product link, shown to Admin/Owner only|✅ Working — columns on Find Item; History shows price × quantity; backend-gated|
|Item notes (JSONB key-value)|✅ Working|
|Transaction history with pagination|✅ Working|
|Filter history by item (barcode lookup)|✅ Working|
|Filter history by user|✅ Working|
|Client-side item search (name / barcode)|✅ Working|
|Barcode scanning on Transaction page (image upload / mobile camera → filter + auto-open form)|✅ Working — backend `pyzbar` decode|
|Codebase modularization (domain / services / views split)|✅ Complete — backend logic isolated from FastAPI; frontend split into ES modules; element-ID and route contracts unchanged|
|Authentication (login / logout / session cookie)|✅ Working — HttpOnly session cookie, scrypt password hashes, `/auth/login`, `/auth/logout`, `/auth/me`|
|Role-based access control (Owner / Admin / Supervisor / Technician)|✅ Working — backend enforces via `get_current_user` + role checks; frontend hides controls the role cannot use|
|Public deployment on Render (Docker + managed Postgres + HTTPS)|✅ Live — see `docs/deploy-render.md`|
|Edit item name, barcode, or location|✅ Working — inline editor on Saved Items, Admin+, with a confirm dialog when the barcode changes|
|Update item quantity directly|✅ Working — via Correction transaction on Saved Items (Admin+); writes an `adjust` audit row with required reason|
|Soft deletes for items and users|❌ Not implemented (hard delete only)|
|Partial / merge updates for item notes|❌ Not implemented (every save replaces all notes)|

---

## Pages & UI

The frontend is a single HTML page with a login gate and six tab-based views.

### Login Screen

Shown by `views/auth.js` on boot when `GET /auth/me` returns 401, and again after logout. Username + password form posts to `/auth/login`; the sign-in button reads "Sign In". On success the app reveals itself and role-appropriate initial loads run, and **every role lands on the Find Item page** (UX overhaul, Phase 1 — previously Owner/Admin landed on Create Item). A header bar shows `username (role)` and a Logout button. A global 401 handler returns the user to the login screen if a session expires mid-use.

**Role-gated UI.** `applyRoleVisibility(role)` hides nav buttons and controls the current role cannot use (e.g. Technicians do not see Create Item / Create User / delete buttons). Backend dependencies are the authoritative check; the UI gating is convenience only.

---

### Create Item Page

Form with barcode, name, location, and starting quantity. Client validates barcode and name are non-empty and location is non-empty before sending.

---

### Saved Items Page

Table showing all items (barcode, name, quantity, location, notes summary, created date). Supports client-side text filter by name or barcode (placeholder "Search name or barcode"). Each row exposes Edit Details / Notes / Correct Count / Delete Item actions via a single per-row Actions menu (Admin+ for edit/correct/delete; Supervisor+ for notes; Technician sees none). On narrow screens (≤639px) the table collapses to stacked cards. Items are ordered newest-first from the API.

**Price & Product Link columns (Admin/Owner only).** Two extra columns — **Price** (formatted USD currency) and **Link** (an "Open" anchor to `product_link`, or "—") — appear in the items table only for Admin/Owner. The backend redacts `price` / `product_link` to `null` for Supervisor/Technician, so the columns are both hidden client-side *and* unpopulated server-side (a lower role cannot read them from the raw API). A safe-URL guard renders `product_link` as a clickable link only when it is an `http(s)` URL. These are display-only for now — there is no UI to set price/product_link yet (populate via the DB or a future editor).

**Item Editor** — inline section on the same page (hidden until triggered). Opens when "Edit" is clicked. Lets Admin+ change the barcode, name, and/or location of an existing item. Quantity is NOT editable here (use a Correction transaction). Changing the barcode prompts a confirm dialog ("Changing this barcode breaks any scanner labels still pointing at this row. Continue?"). Auto-closes after 1 second on success.

**Correction (quantity adjust)** — inline section on the same page (hidden until triggered). Opens when "Correct" is clicked. Lets Admin+ set the item to an absolute new quantity with a required reason. The backend computes the signed delta under the item row lock and records a `transaction_type = "adjust"` audit row carrying the delta and the reason; the append-only invariant is preserved (corrections are new rows, never UPDATEs to past transactions). A no-op (`new_quantity == current_quantity`) returns 400. Auto-closes after 1 second on success.

**Notes Editor** — inline section on the same page (hidden until triggered). Opens when "Edit Notes" is clicked on a row in the items table. Presents a row-per-key editor where each note has a key (text input), a type selector (String / Number / Boolean), and a type-appropriate value input. Rows can be added or removed. Saving replaces all notes atomically. Auto-closes after 1 second on success. Duplicate keys are validated client-side.

---

### Create User Page

Simple username form (username, role, password). A plain-language description of the selected role is shown under the Role select (Technician/Supervisor/Admin/Owner). Client validates username is non-empty before sending.

---

### Saved Users Page

Table listing all users with a delete button. Deleting a user who has transactions shows an error alert (API returns 400).

---

### Transaction Page

**Barcode scan** (top of the page) — has live camera mode and upload mode. Live mode starts only from the Scan button, decodes in-browser with vendored `@zxing/browser`, accepts a barcode after the 5-of-10 frame debounce, and then calls `GET /items/{barcode}` directly. Upload mode opens a file picker / still-camera capture and POSTs the image to `/barcodes/decode` (backend pyzbar decode, in memory). On a single match the items table is filtered to that row and the Stock form auto-opens (Type defaults to Stock; one click flips to Dispense). On an unknown barcode, Owner/Admin see a "Create Item" shortcut that jumps to the Create Item page with the barcode prefilled. Multiple barcodes in one uploaded image show a chooser. Decode failures show a clear message and the manual table below stays usable. The scan resets automatically after a completed stock/dispense. Supported upload formats: UPC-A, UPC-E, EAN-13, EAN-8, Code128.

Displays all items in a table (barcode, name, current quantity) with "Add Stock" and "Take Out" buttons per row. On narrow screens (≤639px) the items table collapses to stacked cards (`class="stack-table"`).

**New Transaction form** (hidden until triggered) — shows the selected/scanned item (large name, plus on-hand quantity and location when known), a segmented **Add Stock / Take Out Stock** control (pre-filled from which button was clicked; submitted `transaction_type` stays `stock`/`dispense`), quantity field, and optional work order number. Transactions are attributed to the logged-in user server-side; the client cannot submit a transaction as someone else. Closes automatically after 1.2 seconds on success and refreshes both the transaction table and the items list.

---

### History Page

Transaction history with three sub-tabs sharing a single results table:

**All Transactions** — loads immediately on page load; shows all transactions newest-first.

**By Item** — user enters a barcode, clicks "Look Up" to resolve it to an item ID, then transactions for that item are shown.

**By User** — user selects from a dropdown populated from the users cache; transactions for that user are shown.

**Pagination** — fixed page size of 10. Prev/Next buttons, page X of Y display. Page resets to 1 on tab or filter change.

**History table columns:** Timestamp, Item (name + barcode), Type (styled badge — green "Added", amber "Taken Out", blue "Correction"; the CSS classes stay `stock`/`dispense`/`adjust` so colours are unchanged, only the visible label is humanised), Quantity, Work Order, User, Actions. For `adjust` rows the Work Order column displays the correction's reason instead (the field is overloaded to avoid widening the table for a value only adjust rows ever carry); the quantity is the signed delta (positive when stock was increased, negative when it was decreased). On narrow screens (≤639px) the table collapses to stacked cards (`class="stack-table"`).

**Price column (Admin/Owner only)** — a **Price** column appears between User and Actions, showing the **per-unit price × the row's quantity** (so a dispense of N shows `price × N`; for stock/adjust rows it is the value of that movement). Items with no price show "—". The per-unit `item_price` is sent by the backend only to Admin/Owner (Supervisors get `null`), and the column is hidden for non-Admin. The Copy-table export is unchanged (price is not included in the TSV).

**Void (delete) a transaction** — the Actions column shows a "Delete" button on every row (outline-red `.btn-danger`). The whole History page is gated to Supervisor+, which is exactly the set allowed to void, so the button needs no per-row role check. Clicking confirms, then `DELETE /transactions/{id}` *voids* the row: it is soft-deleted (kept in the DB stamped with who/when for the audit trail), removed from history entirely, and its effect on the item's on-hand quantity is reversed under the item row lock. A void that would drive stock below zero is refused with a 400 and a "make a correction instead" message. The Copy-table TSV is unaffected (Actions is a UI-only column). After a void the current page reloads; if it was the last row on a page past the first, the view steps back a page.

---

## Data Flow

### On load

1. `enterApp` calls `showPage("saved-items")` so every role lands on the Find Item page.
2. `setHistoryTab("all")` initialises history state and triggers `loadHistory()`.
3. `loadItems()` — fetches `/items/`, populates `itemsCache`, renders items table.
4. `loadUsers()` — fetches `/users/`, populates `usersCache`, renders the users table, and populates user selects used by history/user-management views where available.

### After creating/deleting an item

- `loadItems()` is called to refresh cache and re-render.

### After creating/deleting a user

- `loadUsers()` is called; this also refreshes user-facing selects.

### After saving a transaction

- `loadTxnItems()` and `loadItems()` are both called to reflect updated quantities.

### On navigation

- Navigating to **Saved Items** triggers `loadItems()`.
- Navigating to **Saved Users** triggers `loadUsers()`.
- Navigating to **Transaction** triggers `loadTxnItems()` (does not use `itemsCache`; separate fetch).
- Navigating to **History** triggers `loadHistory()` with current `historyState`.

---

## Client-Side State

|Variable|Type|Purpose|
|---|---|---|
|`itemsCache`|Array|Full items list from last `loadItems()` call|
|`usersCache`|Array|Full users list from last `loadUsers()` call|
|`selectedItemId`|string \| null|Item ID for the open transaction form|
|`editingNotesItemId`|string \| null|Item ID for the open notes editor|
|`historyState`|Object|Current history tab, filter IDs, page number, total pages|

`historyState` shape:

```js
{
  tab: "all" | "item" | "user",
  itemId: string | null,
  userId: string | null,
  page: number,
  totalPages: number,
}
```

---

## Validation Rules (Frontend + Backend)

|Rule|Enforced by|
|---|---|
|Barcode required on item create|Frontend|
|Name required on item create|Frontend|
|Location required on item create|Frontend + Backend|
|Quantity ≥ 0 on item create|Backend (Pydantic)|
|Barcode uniqueness|Backend (DB constraint → 400)|
|Username required and non-blank|Frontend + Backend|
|Username uniqueness|Backend (DB constraint → 400)|
|Transaction quantity > 0|Frontend + Backend|
|Transaction attribution|Backend derives `user_id` from the logged-in session; legacy/null `user_id` rows may still appear in history|
|Dispense cannot make quantity negative|Backend|
|Authenticated session required on every non-login route|Backend (`get_current_user` dependency → 401)|
|Role-based authorization on mutating routes|Backend (role checks in routers/services → 403)|
|Password minimum length / non-blank|Backend (`PasswordResetRequest`, `UserCreate`)|
|Note keys must be non-blank strings|Backend|
|Note values must be str, int, float, or bool|Backend|
|Duplicate note keys|Frontend only|
|At least one of barcode / name / location required on item update|Backend (`ItemUpdate` model validator) + Frontend (all three required, treated as non-blank)|
|Deleting item or user with transactions blocked|Backend (`ItemHasTransactionsError` / `UserHasTransactionsError` → 400; FKs are `ON DELETE RESTRICT`)|
|Correction `new_quantity` ≥ 0|Backend (`CorrectionCreate` field validator) + Frontend|
|Correction `reason` required (non-blank, stripped)|Backend (`CorrectionCreate` field validator) + Frontend|
|Correction must actually change quantity (`new_quantity != current`)|Backend (`NoChangeError` → 400; computed under `FOR UPDATE`)|
|Void requires Supervisor or above|Backend (`require_min_role(supervisor)` on `DELETE /transactions/{id}` → 403)|
|Item `price` / `product_link` visible to Admin/Owner only|Backend (`items._item_response` redacts below Admin on every item-returning route) + Frontend (columns hidden below Admin)|
|History per-unit `item_price` visible to Admin/Owner only|Backend (`list_history(include_price=...)` set from requester role) + Frontend (Price column hidden below Admin)|
|Void of an unknown / already-voided transaction blocked|Backend (`TransactionNotFoundError` → 404)|
|Void that would drive stock below zero blocked|Backend (`TransactionVoidError` → 400; reversal computed under `FOR UPDATE`)|

---

## API Usage by the Frontend

|Frontend action|API call|
|---|---|
|Log in|POST `/auth/login`|
|Log out|POST `/auth/logout`|
|Boot identity check|GET `/auth/me`|
|Decode barcode image|POST `/barcodes/decode` (multipart)|
|Load items|GET `/items/`|
|Create item|POST `/items/`|
|Edit item|PATCH `/items/{item_id}`|
|Delete item|DELETE `/items/{item_id}`|
|Update notes|PATCH `/items/{item_id}/notes`|
|Barcode lookup (history)|GET `/items/{barcode}`|
|Load users|GET `/users/`|
|Create user|POST `/users/` (password required)|
|Reset a user's password|POST `/users/{user_id}/reset-password`|
|Delete user|DELETE `/users/{user_id}`|
|Load transaction history|GET `/transactions/?page=&page_size=&[item_id=\|user_id=]`|
|Create transaction|POST `/transactions/`|
|Record a correction (quantity adjust)|POST `/transactions/adjust`|
|Void (delete) a transaction|DELETE `/transactions/{transaction_id}`|

The frontend never calls `/db-test`.

---

## Known Gaps & Open Questions

- **Transaction page has its own item fetch.** `loadTxnItems()` fetches `/items/` independently from `loadItems()`, so the two tables can briefly diverge if items change between calls.
- **Notes are fully replaced on every save.** There is no partial merge. Loading the editor, removing a row, and saving will permanently delete that note.
- **No soft deletes for items / users.** Deleting an item or user is permanent. Deletion of an item or user that has transactions is blocked by the service layer (`ItemHasTransactionsError` / `UserHasTransactionsError`, → 400) and pinned at the DB level by `ON DELETE RESTRICT` on the `transactions.item_id` and `transactions.user_id` FKs. (Note: a *voided* transaction is still a row referencing its item/user, so it continues to block that item/user's deletion — the audit row is retained, just hidden from history.)
- **Transactions have a soft-delete (void).** A mis-clicked transaction can be voided by a Supervisor+ (`DELETE /transactions/{id}`): the row is retained and stamped `voided_at` / `voided_by_id`, hidden from history, and its stock effect reversed. There is no UI to *un-void* a transaction yet — recovery would currently require a manual DB edit.

---

## Decisions Log

| Date  | Decision                                                | Reason                                                    |
| ----- | ------------------------------------------------------- | --------------------------------------------------------- |
| Early | Quantity uses `Decimal` / `Numeric`                     | Avoid float precision issues with inventory counts        |
| Early | Transactions are append-only, no direct quantity edit   | Preserves full audit trail                                |
| Early | UUIDs for all PKs                                       | Avoids sequential ID enumeration                          |
| v2    | Added JSONB `notes` (formerly `attributes`)             | Flexible metadata without schema migrations per new field |
| v3    | Added `location` column, renamed `attributes` → `notes` | Clearer semantics; location is a first-class field        |
| v3    | `FOR UPDATE` lock on item during transaction            | Prevents race condition on concurrent stock/dispense      |
| barcode | Barcode scanning lives on both Transaction and Saved Items. Upload mode uses file/still capture and backend `pyzbar`; live mode uses vendored `@zxing/browser`. Transaction success filters to the item and opens Stock/Dispense; Saved Items success filters to the row. | Delivers lookup where workers need it while keeping exact barcode resolution through `GET /items/{barcode}`. |
| barcode | Decode on the **backend** with `pyzbar`, **not** `zxing-cpp` (the originally chosen library) and not a JS decoder | `zxing-cpp` has no prebuilt wheel for this Python 3.13 / Windows and needs a C++ toolchain to build (not available on the dev machine). `pyzbar` ships the native `zbar` DLLs in its wheel. Keeps symbology/format logic server-side and unit-tested. **Caveat:** on Windows pyzbar needs the VC++ 2013 runtime (`msvcr120.dll`). |
| auth | Cookie sessions (HttpOnly, `SameSite=Lax`, `Secure` in prod) over JWT bearer tokens | Single-origin SPA served by the same FastAPI process; cookies are simpler, can't be read by JS (XSS-resistant), and need no token storage on the client. |
| auth | Four-tier role hierarchy (Owner / Admin / Supervisor / Technician) with a strict "actor must outrank target" rule for create / reset / delete; Owner is bootstrap-only via `scripts/create_owner.py` | Captures the real workforce structure without inventing per-action permission flags; keeps the management rule trivially auditable and prevents any API caller from creating or escalating an Owner. |
| deploy | `SQL_ECHO` is now env-driven (defaults off); production `render.yaml` sets `SQL_ECHO=false` | Verbose SQL logging in production floods logs and risks leaking data. |
| deploy | Single Render service (Docker) serves both the API and the static SPA, with managed Postgres; HTTPS terminates at Render | Cheapest path to production for a co-located FastAPI + static SPA; HTTPS is also the prerequisite for the mobile camera scan flow. |
| delete-guard | `transactions.item_id` and `transactions.user_id` are pinned `ON DELETE RESTRICT`; the services pre-check for child rows and raise `ItemHasTransactionsError` / `UserHasTransactionsError` (→ 400) | The audit log is the system of record. A clean 400 from the service is more useful than a 500 from a DB integrity error, and the DB-level RESTRICT documents the invariant for any future writer. |
| corrections | Quantity corrections flow through a new `POST /transactions/adjust` route (Admin+) that records a `transaction_type = "adjust"` audit row with the signed delta in `transactions.quantity` and the required reason in a new `transactions.reason` column. The earlier "no direct quantity edit" decision is superseded — but the append-only invariant it was protecting is preserved, because corrections are *new rows*, not UPDATEs to past transactions. Split route (not a branch inside `POST /transactions/`) keeps the role gate and payload shape obvious. Reason as its own column (not overloading `work_order_number`) keeps the field's semantics clean. | Operators occasionally need to reconcile observed stock with the system value (e.g. discovered miscount); forcing them to fake a stock or dispense pollutes the audit log with a fictional transaction. A first-class correction with a mandatory reason captures the *why* and keeps the audit trail honest. |
| item-price | Items carry an optional `price` (per-unit) and `product_link`, surfaced ONLY to Admin/Owner. Find Item gains Price + Link columns; History gains a Price column showing `price_per_unit × quantity` (the cost of what was dispensed/moved). The gate is enforced **server-side** — `items._item_response` and `history.list_history(include_price=...)` null the fields for Supervisor/Technician — not just hidden in the UI, because price is cost-sensitive and the spec's standing rule is that the backend is the authoritative access check. `price` is the *live* item price (not snapshotted per transaction), so historical line values reflect the current price. Display-only: no edit UI yet. | The owner wants cost visibility for senior roles without exposing margins to the floor crew; gating in the API (not just CSS) means a Supervisor opening devtools still cannot read prices. Computing `price × quantity` in History answers "how much did we consume" directly. |
| void-txn | A mis-clicked transaction can be deleted by Supervisor+ via `DELETE /transactions/{id}`. Implemented as a **soft delete ("void")**, not a hard delete: the row is kept (stamped `voided_at` + `voided_by_id`), excluded from the history view (`list_history` filters `voided_at IS NULL`), and its effect on `Item.quantity` is reversed under the same `SELECT ... FOR UPDATE` lock as stock/dispense (reversal arithmetic in `domain.quantity.reverse_delta`, unit-tested). A reversal that would make stock negative raises `TransactionVoidError` (400). Supervisor+ chosen because that is the existing History-page gate, so the whole set of viewers can self-correct. `voided_by_id` is a plain UUID rather than a second FK to `users`, to avoid disambiguating the existing `Transaction.user` relationship for what is hidden audit metadata. | Operators occasionally fat-finger a stock/dispense on a phone; forcing a compensating fake transaction (or a DB edit) to fix it is worse than letting them remove the bad row. Soft delete keeps the append-only audit trail honest (nothing is truly destroyed; who/when is recorded) while giving the crew a clean "undo" and keeping the history view uncluttered. |
| ux-overhaul-p1 | Field-friendly UX overhaul, Phase 1 (frontend only). Visible labels renamed: Create Item→"Add Item", Saved Items→"Find Item", Create User→"Add User", Saved Users→"Users", Transaction→"Scan / Stock"; "Log In"→"Sign In"; "Correct Quantity"→"Correct Count"; "Edit Notes"→"Notes"; type options→"Add Stock"/"Take Out Stock". All roles now land on Find Item after sign-in. Messages rewritten to crew-friendly wording via the new `format.friendlyError`. New red/black/white (Belfor) visual system via CSS tokens (primary 52px / inputs 48px / body 16px). Internal `data-page` values, element IDs, state classes, and `transaction_type` values are unchanged — the frozen DOM contract is intact. | The app workflow already works; the problem was clarity and confidence for a low-tech-tolerance construction crew on phones. See `docs/plan-ux-overhaul.md`, `docs/roadmap-ux-overhaul.md`, and `docs/design-spec-ux-overhaul.md`. |
