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
|Codebase modularization (domain / services / views split)|✅ Complete — backend logic isolated from FastAPI; frontend split into ES modules; element-ID and route contracts unchanged|
|Authentication / access control|❌ Not implemented|
|Edit item name, barcode, or location|❌ Not implemented|
|Update item quantity directly|❌ Not implemented (must go through transaction)|

---

## Pages & UI

The frontend is a single HTML page with six tab-based views:

### Create Item Page

Form with barcode, name, location, and starting quantity. Client validates barcode and name are non-empty and location is non-empty before sending.

---

### Saved Items Page

Table showing all items (barcode, name, quantity, location, notes summary, created date). Supports client-side text filter by name or barcode. Each row has an "Edit Notes" button and a delete button. Items are ordered newest-first from the API.

**Notes Editor** — inline section on the same page (hidden until triggered). Opens when "Edit Notes" is clicked on a row in the items table. Presents a row-per-key editor where each note has a key (text input), a type selector (String / Number / Boolean), and a type-appropriate value input. Rows can be added or removed. Saving replaces all notes atomically. Auto-closes after 1 second on success. Duplicate keys are validated client-side.

---

### Create User Page

Simple username form. Client validates username is non-empty before sending.

---

### Saved Users Page

Table listing all users with a delete button. Deleting a user who has transactions shows an error alert (API returns 400).

---

### Transaction Page

Displays all items in a table (barcode, name, current quantity) with "Stock" and "Dispense" buttons per row.

**New Transaction form** (hidden until triggered) — shows the selected item name, type selector (pre-filled from which button was clicked), a user dropdown, quantity field, and optional work order number. User selection is required before saving. If no users exist, the save button is disabled with an explanatory message. Closes automatically after 1.2 seconds on success and refreshes both the transaction table and the items list.

---

### History Page

Transaction history with three sub-tabs sharing a single results table:

**All Transactions** — loads immediately on page load; shows all transactions newest-first.

**By Item** — user enters a barcode, clicks "Look Up" to resolve it to an item ID, then transactions for that item are shown.

**By User** — user selects from a dropdown populated from the users cache; transactions for that user are shown.

**Pagination** — fixed page size of 10. Prev/Next buttons, page X of Y display. Page resets to 1 on tab or filter change.

**History table columns:** Timestamp, Item (name + barcode), Type (styled badge), Quantity, Work Order, User.

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
|Transaction user required|Frontend (user_id optional on backend)|
|Dispense cannot make quantity negative|Backend|
|Note keys must be non-blank strings|Backend|
|Note values must be str, int, float, or bool|Backend|
|Duplicate note keys|Frontend only|
|Deleting user with transactions blocked|Backend (400)|

---

## API Usage by the Frontend

|Frontend action|API call|
|---|---|
|Load items|GET `/items/`|
|Create item|POST `/items/`|
|Delete item|DELETE `/items/{item_id}`|
|Update notes|PATCH `/items/{item_id}/notes`|
|Barcode lookup (history)|GET `/items/{barcode}`|
|Load users|GET `/users/`|
|Create user|POST `/users/`|
|Delete user|DELETE `/users/{user_id}`|
|Load transaction history|GET `/transactions/?page=&page_size=&[item_id=\|user_id=]`|
|Create transaction|POST `/transactions/`|

The frontend never calls `/db-test`.

---

## Known Gaps & Open Questions

- **No authentication.** Any user with network access can create, delete, or modify anything. This is a known gap.
- **No item editing.** Once created, an item's barcode, name, and location cannot be changed through the UI. There is no PATCH endpoint for those fields.
- **Quantity is read-only outside of transactions.** There is no way to correct a quantity directly; all changes must go through stock/dispense transactions.
- **User required in frontend but optional in backend.** `user_id` is nullable in the DB and optional in `TransactionCreate`. The frontend enforces selection, but direct API calls can omit it.
- **Transaction page has its own item fetch.** `loadTxnItems()` fetches `/items/` independently from `loadItems()`, so the two tables can briefly diverge if items change between calls.
- **Notes are fully replaced on every save.** There is no partial merge. Loading the editor, removing a row, and saving will permanently delete that note.
- **No soft deletes.** Deleting an item or user is permanent. Deleting an item with transactions is currently allowed (cascade behaviour depends on DB FK settings — not explicitly defined in the migration as CASCADE or RESTRICT).
- **`echo=True` on the engine.** SQL logging is on in what appears to be a production config. Should likely be toggled by environment.

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
