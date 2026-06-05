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
|Item notes (JSONB key-value)|✅ Working|
|Transaction history with pagination|✅ Working|
|Filter history by item (barcode lookup)|✅ Working|
|Filter history by user|✅ Working|
|Client-side item search (name / barcode)|✅ Working|
|Barcode scanning on Transaction page (image upload / mobile camera → filter + auto-open form)|✅ Working — backend `pyzbar` decode|
|Codebase modularization (domain / services / views split)|✅ Complete — backend logic isolated from FastAPI; frontend split into ES modules; element-ID and route contracts unchanged|
|Authentication (login / logout / session cookie)|✅ Working — HttpOnly session cookie, bcrypt password hashes, `/auth/login`, `/auth/logout`, `/auth/me`|
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

Shown by `views/auth.js` on boot when `GET /auth/me` returns 401, and again after logout. Username + password form posts to `/auth/login`; on success the app reveals itself and role-appropriate initial loads run. A header bar shows `username (role)` and a Logout button. A global 401 handler returns the user to the login screen if a session expires mid-use.

**Role-gated UI.** `applyRoleVisibility(role)` hides nav buttons and controls the current role cannot use (e.g. Technicians do not see Create Item / Create User / delete buttons). Backend dependencies are the authoritative check; the UI gating is convenience only.

---

### Create Item Page

Form with barcode, name, location, and starting quantity. Client validates barcode and name are non-empty and location is non-empty before sending.

---

### Saved Items Page

Table showing all items (barcode, name, quantity, location, notes summary, created date). Supports client-side text filter by name or barcode. Each row has an "Edit", "Edit Notes", "Correct", and delete button (Admin+ only; Supervisor/Technician see a read-only table). Items are ordered newest-first from the API.

**Item Editor** — inline section on the same page (hidden until triggered). Opens when "Edit" is clicked. Lets Admin+ change the barcode, name, and/or location of an existing item. Quantity is NOT editable here (use a Correction transaction). Changing the barcode prompts a confirm dialog ("Changing this barcode breaks any scanner labels still pointing at this row. Continue?"). Auto-closes after 1 second on success.

**Correction (quantity adjust)** — inline section on the same page (hidden until triggered). Opens when "Correct" is clicked. Lets Admin+ set the item to an absolute new quantity with a required reason. The backend computes the signed delta under the item row lock and records a `transaction_type = "adjust"` audit row carrying the delta and the reason; the append-only invariant is preserved (corrections are new rows, never UPDATEs to past transactions). A no-op (`new_quantity == current_quantity`) returns 400. Auto-closes after 1 second on success.

**Notes Editor** — inline section on the same page (hidden until triggered). Opens when "Edit Notes" is clicked on a row in the items table. Presents a row-per-key editor where each note has a key (text input), a type selector (String / Number / Boolean), and a type-appropriate value input. Rows can be added or removed. Saving replaces all notes atomically. Auto-closes after 1 second on success. Duplicate keys are validated client-side.

---

### Create User Page

Simple username form. Client validates username is non-empty before sending.

---

### Saved Users Page

Table listing all users with a delete button. Deleting a user who has transactions shows an error alert (API returns 400).

---

### Transaction Page

**Barcode scan** (top of the page) — a file input with `accept="image/*" capture="environment"` so phones open the rear camera and desktops open a file picker. The chosen image is POSTed to `/barcodes/decode` (backend pyzbar decode, in memory). On a single match the items table is filtered to that row and the Stock form auto-opens (Type defaults to Stock; one click flips to Dispense). On an unknown barcode, Owner/Admin see a "Create Item" shortcut that jumps to the Create Item page with the barcode prefilled. Multiple barcodes in one image show a chooser. Decode failures show a clear message and the manual table below stays usable. The scan resets automatically after a completed stock/dispense. Supported formats: UPC-A, UPC-E, EAN-13, EAN-8, Code128.

Displays all items in a table (barcode, name, current quantity) with "Stock" and "Dispense" buttons per row.

**New Transaction form** (hidden until triggered) — shows the selected item name, type selector (pre-filled from which button was clicked), a user dropdown, quantity field, and optional work order number. User selection is required before saving. If no users exist, the save button is disabled with an explanatory message. Closes automatically after 1.2 seconds on success and refreshes both the transaction table and the items list.

---

### History Page

Transaction history with three sub-tabs sharing a single results table:

**All Transactions** — loads immediately on page load; shows all transactions newest-first.

**By Item** — user enters a barcode, clicks "Look Up" to resolve it to an item ID, then transactions for that item are shown.

**By User** — user selects from a dropdown populated from the users cache; transactions for that user are shown.

**Pagination** — fixed page size of 10. Prev/Next buttons, page X of Y display. Page resets to 1 on tab or filter change.

**History table columns:** Timestamp, Item (name + barcode), Type (styled badge — `stock` green, `dispense` amber, `adjust` blue), Quantity, Work Order, User. For `adjust` rows the Work Order column displays the correction's reason instead (the field is overloaded to avoid widening the table for a value only adjust rows ever carry); the quantity is the signed delta (positive when stock was increased, negative when it was decreased).

---

## Data Flow

### On load

1. `showPage("create-item")` activates the Create Item tab.
2. `setHistoryTab("all")` initialises history state and triggers `loadHistory()`.
3. `loadItems()` — fetches `/items/`, populates `itemsCache`, renders items table.
4. `loadUsers()` — fetches `/users/`, populates `usersCache`, renders users table, populates user dropdowns.

### After creating/deleting an item

- `loadItems()` is called to refresh cache and re-render.

### After creating/deleting a user

- `loadUsers()` is called; this also refreshes both user dropdowns and rechecks transaction form state.

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
|Transaction user required|Frontend (user_id remains optional on backend; gap, see below)|
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

The frontend never calls `/db-test`.

---

## Known Gaps & Open Questions

- **No item editing.** Once created, an item's barcode, name, and location cannot be changed through the UI. There is no PATCH endpoint for those fields. *(Resolved: see Saved Items → Item Editor.)*
- **Quantity is read-only outside of transactions.** *(Resolved: see Saved Items → Correction. Quantity changes still flow through a transaction — corrections are recorded as `transaction_type = "adjust"` audit rows with a required reason — so the append-only invariant is preserved.)*
- **Transaction page has its own item fetch.** `loadTxnItems()` fetches `/items/` independently from `loadItems()`, so the two tables can briefly diverge if items change between calls.
- **Notes are fully replaced on every save.** There is no partial merge. Loading the editor, removing a row, and saving will permanently delete that note.
- **No soft deletes.** Deleting an item or user is permanent. Deletion of an item or user that has transactions is blocked by the service layer (`ItemHasTransactionsError` / `UserHasTransactionsError`, → 400) and pinned at the DB level by `ON DELETE RESTRICT` on the `transactions.item_id` and `transactions.user_id` FKs.

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
| barcode | Barcode scanning lives on the Transaction page only; capture via file upload + mobile camera (`<input type=file capture>`); success filters to the matching row and auto-opens the Stock/Dispense form | Smallest surface that delivers the value; reuses the existing exact `GET /items/{barcode}` lookup (no fuzzy search) |
| barcode | Decode on the **backend** with `pyzbar`, **not** `zxing-cpp` (the originally chosen library) and not a JS decoder | `zxing-cpp` has no prebuilt wheel for this Python 3.13 / Windows and needs a C++ toolchain to build (not available on the dev machine). `pyzbar` ships the native `zbar` DLLs in its wheel. Keeps symbology/format logic server-side and unit-tested. **Caveat:** on Windows pyzbar needs the VC++ 2013 runtime (`msvcr120.dll`). |
| auth | Cookie sessions (HttpOnly, `SameSite=Lax`, `Secure` in prod) over JWT bearer tokens | Single-origin SPA served by the same FastAPI process; cookies are simpler, can't be read by JS (XSS-resistant), and need no token storage on the client. |
| auth | Four-tier role hierarchy (Owner / Admin / Supervisor / Technician) with a strict "actor must outrank target" rule for create / reset / delete; Owner is bootstrap-only via `scripts/create_owner.py` | Captures the real workforce structure without inventing per-action permission flags; keeps the management rule trivially auditable and prevents any API caller from creating or escalating an Owner. |
| deploy | `SQL_ECHO` is now env-driven (defaults off); production `render.yaml` sets `SQL_ECHO=false` | Verbose SQL logging in production floods logs and risks leaking data. |
| deploy | Single Render service (Docker) serves both the API and the static SPA, with managed Postgres; HTTPS terminates at Render | Cheapest path to production for a co-located FastAPI + static SPA; HTTPS is also the prerequisite for the mobile camera scan flow. |
| delete-guard | `transactions.item_id` and `transactions.user_id` are pinned `ON DELETE RESTRICT`; the services pre-check for child rows and raise `ItemHasTransactionsError` / `UserHasTransactionsError` (→ 400) | The audit log is the system of record. A clean 400 from the service is more useful than a 500 from a DB integrity error, and the DB-level RESTRICT documents the invariant for any future writer. |
| corrections | Quantity corrections flow through a new `POST /transactions/adjust` route (Admin+) that records a `transaction_type = "adjust"` audit row with the signed delta in `transactions.quantity` and the required reason in a new `transactions.reason` column. The earlier "no direct quantity edit" decision is superseded — but the append-only invariant it was protecting is preserved, because corrections are *new rows*, not UPDATEs to past transactions. Split route (not a branch inside `POST /transactions/`) keeps the role gate and payload shape obvious. Reason as its own column (not overloading `work_order_number`) keeps the field's semantics clean. | Operators occasionally need to reconcile observed stock with the system value (e.g. discovered miscount); forcing them to fake a stock or dispense pollutes the audit log with a fictional transaction. A first-class correction with a mandatory reason captures the *why* and keeps the audit trail honest. |
