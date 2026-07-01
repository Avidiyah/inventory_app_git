# Endpoint Map: Database ↔ User View

Last reviewed: 2026-06-30

Purpose: a complete, self-contained trace of every endpoint — wiring, contracts,
rules, error behavior, and service algorithms — so an AI or developer can answer
"what does this endpoint send/return/do?" **without opening the source**. If you
find yourself about to read `schemas/`, `services/`, `domain/`, or `routers/`,
check here first; this file is meant to make that read unnecessary. Companion to
`docs/current-state.md` (invariants/data model).

Contents:

1. [Master Endpoint Index](#master-endpoint-index) — every endpoint, gate, service, tables, wrapper, view.
2. [Database → User View](#direction-a--database--user-view-read-flows) — read flows.
3. [User Input → Database](#direction-b--user-input--database-write-flows) — write flows.
4. [Per-Table Index](#per-table-index-who-reads--who-writes) — which endpoints touch each table.
5. [Request / Response Contracts](#request--response-contracts) — every schema, field by field, with validation.
6. [Error Catalog](#error-catalog) — every `DomainError`, its HTTP status, and when it fires.
7. [Domain Rules Quick Reference](#domain-rules-quick-reference) — roles, stock arithmetic, identity, lifecycles.
8. [Service Algorithm Reference](#service-algorithm-reference) — step-by-step internals of every non-trivial service.

## How To Read This

The stack is a fixed layer chain. Every feature is the same shape:

```
DB table  ─▶ models.py ─▶ services/*.py ─▶ routers/*.py ─▶ (HTTP) ─▶ static/api.js ─▶ static/views/*.js ─▶ user sees it
   ▲                                                                                                          │
   └──────────────────────────────── User Input ◀──────────────────────────────────────────────────────────┘
```

- **Read path (Database → User View):** a `GET` (or a write that returns fresh
  state) flows up the chain; the table is the source, the view is the sink.
- **Write path (User Input → Database):** a user action in a view calls an
  `api.js` wrapper → router → service → table.

Paths below are relative to `backend/`. `domain/*`, `routers/*`, `services/*`,
`models.py` are under `backend/app/`. `api.js`, `views/*` are under
`backend/static/`. Gates are enforced server-side (`auth_deps.py`); see
`current-state.md` → Roles And Access.

---

## Master Endpoint Index

Every HTTP endpoint, one row each. "Tables" lists what the call reads (r) and
writes (w).

| # | Method | Path | Gate | Router → Service | Tables | api.js wrapper | View(s) |
|---|--------|------|------|------------------|--------|----------------|---------|
| 1 | GET | `/` | public | `main.py` (shell assembly) | — | — (browser) | SPA boot |
| 2 | GET | `/db-test` | admin+ | `main.py` → `database.test_connection` | — | — | (diagnostic) |
| 3 | POST | `/auth/login` | public | `auth.py` → `auth.authenticate` + `create_session` | users (r), sessions (w) | `apiLogin` | `auth.js` |
| 4 | POST | `/auth/logout` | session | `auth.py` → `auth.delete_session` | sessions (w) | `apiLogout` | `auth.js` |
| 5 | GET | `/auth/me` | session | `auth_deps.get_current_user` | sessions (r), users (r) | `apiMe` | `auth.js` |
| 6 | GET | `/items/` | session | `items.py` → `items.list_items` | items (r) | `apiListItems` | `items.js`, `transactions.js`, `massStage.js`, `workOrders.js` |
| 7 | GET | `/items/{barcode}` | session | `items.py` → `items.get_item_by_barcode` | items (r), item_barcodes (r) | `apiGetItemByBarcode` | `scan.js`, `addBarcode.js`, `history.js` |
| 8 | POST | `/items/` | admin+ | `items.py` → `items.create_item` | items (w), item_barcodes (r) | `apiCreateItem` | `items.js` |
| 9 | PATCH | `/items/{id}` | admin+ | `items.py` → `items.update_item` | items (w), item_barcodes (r) | `apiUpdateItem` | `itemEditor.js` |
| 10 | PATCH | `/items/{id}/notes` | supervisor+ | `items.py` → `notes.replace_notes` | items (w) | `apiUpdateNotes` | `notes.js` |
| 11 | PATCH | `/items/{id}/barcodes` | admin+ | `items.py` → `items.replace_barcodes` | item_barcodes (w), items (r) | `apiUpdateBarcodes` | `itemEditor.js`, `addBarcode.js` |
| 12 | DELETE | `/items/{id}` | admin+ | `items.py` → `items.delete_item` | items (w, archive) | `apiDeleteItem` | `items.js` |
| 13 | POST | `/barcodes/decode` | session | `barcodes.py` → `barcodes.decode_image` | — (no persistence) | `apiDecodeBarcode` | `scan.js` |
| 14 | GET | `/users/` | supervisor+ | `users.py` → `users.list_users` | users (r) | `apiListUsers` | `users.js`, `transactions.js`, `massStage.js`, `workOrders.js` |
| 15 | POST | `/users/` | outranks target | `users.py` → `users.create_user` | users (w) | `apiCreateUser` | `users.js` |
| 16 | POST | `/users/{id}/reset-password` | outranks target | `users.py` → `users.reset_password` | users (w) | `apiResetPassword` | `users.js` |
| 17 | POST | `/users/{id}/archive` | outranks target | `users.py` → `users.archive_user` | users (w), sessions (w, revoke) | `apiArchiveUser` | `users.js` |
| 18 | POST | `/users/{id}/restore` | outranks target | `users.py` → `users.restore_user` | users (w) | `apiRestoreUser` | `users.js` |
| 19 | DELETE | `/users/{id}` | outranks target | `users.py` → `users.delete_user` | users (w, hard) | `apiDeleteUser` | **API-only** (no UI; UI uses archive) |
| 20 | GET | `/transactions/` | supervisor+ | `transactions.py` → `history.list_history` | transactions (r), items (r), users (r) | `apiListTransactions` | `history.js` |
| 21 | POST | `/transactions/` | session + direction¹ | `transactions.py` → `transactions.apply_transaction` (+ `work_orders.get_or_create_work_order`, `attach_dispense_line`) | items (w), transactions (w), work_orders (r/w²), work_order_items (w³) | `apiCreateTransaction` | `transactions.js` |
| 22 | POST | `/transactions/adjust` | admin+ | `transactions.py` → `transactions.apply_correction` | items (w), transactions (w) | `apiCreateCorrection` | `correction.js` |
| 23 | PATCH | `/transactions/{id}/billing` | admin+ | `transactions.py` → `transactions.set_billable_quantity` | transactions (w) | `apiSetBillableQuantity` | `history.js` |
| 24 | DELETE | `/transactions/{id}` | supervisor+ | `transactions.py` → `transactions.void_transaction` | transactions (w, soft), items (w), work_order_items (w⁴) | `apiVoidTransaction` | `history.js` |
| 25 | GET | `/work-orders/` | session scoped | `work_orders.py` → `work_orders.list_work_orders` | work_orders (r), work_order_items (r), users (r) | `apiListWorkOrders` | `workOrders.js`, `transactions.js`, `history.js` |
| 26 | GET | `/work-orders/{id}` | session scoped | `work_orders.py` → `work_orders.get_work_order` | work_orders (r), work_order_items (r/w⁵), items (r), users (r) | `apiGetWorkOrder` | `workOrders.js`, `history.js` |
| 27 | POST | `/work-orders/` | supervisor+ | `work_orders.py` → `work_orders.create_work_order` | work_orders (w), users (r) | `apiCreateWorkOrder` | `workOrders.js`, `transactions.js` |
| 28 | PATCH | `/work-orders/{id}` | scoped; priv→sup+ | `work_orders.py` → `work_orders.update_work_order` | work_orders (w), users (r) | `apiUpdateWorkOrder` | `workOrders.js` |
| 29 | POST | `/work-orders/{id}/archive` | supervisor+ scoped | `work_orders.py` → `work_orders.archive_work_order` | work_orders (w, archive) | `apiArchiveWorkOrder` | `workOrders.js` |
| 30 | POST | `/work-orders/{id}/items` | session scoped | `work_orders.py` → `work_orders.add_work_order_item` | items (w), transactions (w), work_order_items (w) | `apiAddWorkOrderItem` | `workOrders.js` |
| 31 | PATCH | `/work-orders/{id}/items/{wid}` | session scoped | `work_orders.py` → `work_orders.update_work_order_item` | items (w), transactions (w, adjust), work_order_items (w) | `apiUpdateWorkOrderItem` | `workOrders.js` |
| 32 | PATCH | `/work-orders/{id}/items/{wid}/billing` | admin+ scoped | `work_orders.py` → `work_orders.set_work_order_item_billable` | work_order_items (w) | `apiSetWorkOrderItemBilling` | `workOrders.js` |
| 33 | DELETE | `/work-orders/{id}/items/{wid}` | session scoped | `work_orders.py` → `work_orders.delete_work_order_item` | items (w), transactions (w, void), work_order_items (w) | `apiDeleteWorkOrderItem` | `workOrders.js` |
| 34 | POST | `/mass-stages/` | supervisor+ | `mass_stages.py` → `mass_staging.create_stage` | mass_stages (w) | `apiCreateStage` | `massStage.js` |
| 35 | GET | `/mass-stages/` | supervisor+ scoped | `mass_stages.py` → `mass_staging.list_stages` | mass_stages (r) | `apiListStages` | `massStage.js` |
| 36 | GET | `/mass-stages/{id}` | supervisor+ | `mass_stages.py` → `mass_staging.get_stage` | mass_stages (r), mass_stage_work_orders (r), mass_stage_items (r), work_orders (r), items (r) | `apiGetStage` | `massStage.js` |
| 37 | PATCH | `/mass-stages/{id}` | supervisor+ | `mass_stages.py` → `mass_staging.update_stage` | mass_stages (w) | `apiUpdateStage` | `massStage.js` |
| 38 | DELETE | `/mass-stages/{id}` | supervisor+ | `mass_stages.py` → `mass_staging.delete_stage` | mass_stages (w), slots/items (cascade) | `apiDeleteStage` | `massStage.js` |
| 39 | POST | `/mass-stages/{id}/reuse` | supervisor+ | `mass_stages.py` → `mass_staging.reuse_stage` | mass_stages (w) | `apiReuseStage` | `massStage.js` |
| 40 | POST | `/mass-stages/{id}/work-orders` | supervisor+ | `mass_stages.py` → `mass_staging.add_work_order_to_stage` | mass_stage_work_orders (w), work_orders (r/w, find-or-create) | `apiAddStageWorkOrder` | `massStage.js` |
| 41 | DELETE | `/mass-stages/{id}/work-orders/{slot}` | supervisor+ | `mass_stages.py` → `mass_staging.delete_slot` | mass_stage_work_orders (w), mass_stage_items (cascade) | `apiDeleteStageWorkOrder` | `massStage.js` |
| 42 | POST | `/mass-stages/{id}/work-orders/{slot}/items` | supervisor+ | `mass_stages.py` → `mass_staging.add_item` | mass_stage_items (w) | `apiAddStageItem` | `massStage.js` |
| 43 | PATCH | `/mass-stages/{id}/work-orders/{slot}/items/{sid}` | supervisor+ | `mass_stages.py` → `mass_staging.update_item` | mass_stage_items (w) | `apiUpdateStageItem` | `massStage.js` |
| 44 | DELETE | `/mass-stages/{id}/work-orders/{slot}/items/{sid}` | supervisor+ | `mass_stages.py` → `mass_staging.delete_item` | mass_stage_items (w) | `apiDeleteStageItem` | `massStage.js` |
| 45 | POST | `/mass-stages/{id}/load` | supervisor+ | `mass_stages.py` → `mass_staging.load_item` | items (w), transactions (w), work_order_items (w), mass_stage_items (w) | `apiLoadStageItem` | `massStage.js` |
| 46 | POST | `/mass-stages/{id}/return` | supervisor+ | `mass_stages.py` → `mass_staging.return_item` | items (w, silent), work_order_items (w), mass_stage_items (w) | `apiReturnStageItem` | `massStage.js` |

Footnotes:
1. `POST /transactions/`: dispense = any authenticated user; stock = supervisor+ (`domain.roles.can_transact`).
2. work_orders: read when a scanned card passes `work_order_id`; find-or-create (write) when a Supervisor+ passes a free-text `work_order_number`.
3. work_order_items: a line is created/accumulated only for a `dispense` carrying a `work_order_id` (a stock-in writes none).
4. void walks the work_order_items line back (drops it at zero) when the voided row carries a `work_order_id`.
5. `get_work_order` lazily self-heals orphaned linked dispenses into lines on read (a write inside a read).

---

## Direction A — Database → User View (read flows)

What populates each screen. Format: **table → … → view → what the user sees**.

### Boot / session
- **sessions, users** → `auth_deps.get_current_user` → `GET /auth/me` → `apiMe` →
  `auth.js`: on load, 200 ⇒ enter app (nav visibility applied); 401 ⇒ login screen.
- **(static fragments)** → `main.py` shell assembly → `GET /` → browser: the SPA
  shell (`shell-head.html` + `pages/*.html` + `shell-tail.html`).

### Items
- **items** → `list_items` → `GET /items/` → `apiListItems` →
  - `items.js`: the Find Item table (Admin/Owner see price/link columns).
  - `transactions.js`: the manual entry search-and-pick panel (every role;
    Supervisor+ additionally browse-all with an empty search).
  - `massStage.js` / `workOrders.js`: the "search and pick an item" picker.
- **items + item_barcodes** → `get_item_by_barcode` → `GET /items/{barcode}` →
  `apiGetItemByBarcode` →
  - `scan.js`: the resolved item after a scan/upload.
  - `addBarcode.js`: confirm the item an extra barcode will attach to.
  - `history.js`: the "by item" tab barcode lookup.

### Users
- **users** → `list_users` → `GET /users/` → `apiListUsers` →
  - `users.js`: the user table (archived included, dimmed).
  - `transactions.js` / `workOrders.js` / `massStage.js`: technician dropdowns
    for assignment; `history.js` uses it for the "by user" filter.

### Transaction history
- **transactions ⋈ items ⋈ users** → `list_history` → `GET /transactions/` →
  `apiListTransactions` → `history.js`: the paginated History table. Admin/Owner
  get the Charge column (`item_price` × qty × 1.15) — **null for work-order rows**
  (they bill via the line). Copy-table also reads this set; see cross-feature note.

### Work orders
- **work_orders ⋈ work_order_items ⋈ users** → `list_work_orders` →
  `GET /work-orders/` → `apiListWorkOrders` →
  - `workOrders.js`: the collapsible work-order cards.
  - `transactions.js`: the scan-gate active-work-order cards.
  - `history.js`: resolves a work order for the copy-table summary (by number).
- **work_orders ⋈ work_order_items ⋈ items** → `get_work_order` →
  `GET /work-orders/{id}` → `apiGetWorkOrder` →
  - `workOrders.js`: the expanded card body — materials lines, per-line charge
    (`unit_price`/`billable_quantity`, Admin/Owner), and `materials_total`.
  - `history.js`: per-work-order totals + line unit prices for the copy export.

### Mass staging
- **mass_stages** → `list_stages` → `GET /mass-stages/` → `apiListStages` →
  `massStage.js`: the Community → Building → Unit tree.
- **mass_stages ⋈ slots ⋈ items ⋈ work_orders** → `get_stage` →
  `GET /mass-stages/{id}` → `apiGetStage` → `massStage.js`: stage detail (slots,
  planned/loaded/returned quantities).

### Cross-feature read (copy-table billing summary)
`history.js` copy button reads `GET /transactions/` (all matching rows) **and**,
per distinct work order in the set, `GET /work-orders/{id}` (resolved from
`work_order_number` via `GET /work-orders/?q=`) to fill per-row work-order pricing
and append the authoritative **Work Order Summary** (`materials_total` + 15%).

---

## Direction B — User Input → Database (write flows)

What each user action persists. Format: **view (action) → api wrapper → endpoint →
service → table effect**.

### Auth
- `auth.js` (Login) → `apiLogin` → `POST /auth/login` → `authenticate` +
  `create_session` → **sessions** insert (cookie set); reads **users**.
- `auth.js` (Logout) → `apiLogout` → `POST /auth/logout` → `delete_session` →
  **sessions** delete.

### Items
- `items.js` (Create Item) → `apiCreateItem` → `POST /items/` → `create_item` →
  **items** insert (barcode uniqueness checked across **item_barcodes**).
- `itemEditor.js` (Save) → `apiUpdateItem` → `PATCH /items/{id}` → `update_item`
  → **items** partial update (explicit null clears price/link).
- `notes.js` (Save notes) → `apiUpdateNotes` → `PATCH /items/{id}/notes` →
  `replace_notes` → **items.notes** JSONB replace.
- `itemEditor.js` / `addBarcode.js` (Save barcodes) → `apiUpdateBarcodes` →
  `PATCH /items/{id}/barcodes` → `replace_barcodes` → **item_barcodes** diff/replace.
- `items.js` (Archive) → `apiDeleteItem` → `DELETE /items/{id}` → `delete_item` →
  **items.archived_at** set (soft delete).

### Stock movement (the core write)
- `transactions.js` (scan-and-go / manual Add Stock / Take Out) →
  `apiCreateTransaction` → `POST /transactions/` → `apply_transaction` →
  **items.quantity** ±, **transactions** insert; if a `dispense` carries a
  `work_order_id`, also **work_order_items** line create/accumulate. A free-text
  number find-or-creates a **work_orders** row first.
- `correction.js` (Correct count) → `apiCreateCorrection` →
  `POST /transactions/adjust` → `apply_correction` → **items.quantity** set,
  **transactions** insert (`adjust`, signed delta).
- `history.js` (Edit charge) → `apiSetBillableQuantity` →
  `PATCH /transactions/{id}/billing` → `set_billable_quantity` →
  **transactions.billable_quantity** (no stock change).
- `history.js` (Delete/Void) → `apiVoidTransaction` → `DELETE /transactions/{id}`
  → `void_transaction` → **transactions.voided_at** set, **items.quantity**
  reversed; walks the **work_order_items** line back if work-order-linked.

### Users
- `users.js` (Create) → `apiCreateUser` → `POST /users/` → **users** insert.
- `users.js` (Reset password) → `apiResetPassword` →
  `POST /users/{id}/reset-password` → **users.password_hash** update.
- `users.js` (🗑️ Archive) → `apiArchiveUser` → `POST /users/{id}/archive` →
  **users.archived_at** set + **sessions** delete (revoke).
- `users.js` (Restore) → `apiRestoreUser` → `POST /users/{id}/restore` →
  **users.archived_at** cleared.
- *(API-only)* `apiDeleteUser` → `DELETE /users/{id}` → hard delete (blocked if
  transactions reference the user). No UI surfaces this.

### Work orders
- `workOrders.js` / `transactions.js` (New work order) → `apiCreateWorkOrder` →
  `POST /work-orders/` → `create_work_order` → **work_orders** find-or-create.
- `workOrders.js` (mode / status / attributes / assignee) → `apiUpdateWorkOrder`
  → `PATCH /work-orders/{id}` → `update_work_order` → **work_orders** update.
- `workOrders.js` (Archive) → `apiArchiveWorkOrder` →
  `POST /work-orders/{id}/archive` → **work_orders.archived_at** set.
- `workOrders.js` (Add material) → `apiAddWorkOrderItem` →
  `POST /work-orders/{id}/items` → `add_work_order_item` → **items.quantity** ∓
  (dispense mode), **transactions** insert, **work_order_items** line.
- `workOrders.js` (Update qty) → `apiUpdateWorkOrderItem` →
  `PATCH /work-orders/{id}/items/{wid}` → `update_work_order_item` →
  **work_order_items.quantity** set, **items.quantity** corrected by delta,
  **transactions** insert (reconciling `adjust`); clears a now-too-large override.
- `workOrders.js` (Edit charge) → `apiSetWorkOrderItemBilling` →
  `PATCH /work-orders/{id}/items/{wid}/billing` → `set_work_order_item_billable`
  → **work_order_items.billable_quantity** (no stock change).
- `workOrders.js` (Remove material) → `apiDeleteWorkOrderItem` →
  `DELETE /work-orders/{id}/items/{wid}` → `delete_work_order_item` →
  **items.quantity** returned, **work_order_items** row delete, **transactions**
  voided (the line's whole contributing set).

### Mass staging
- `massStage.js` (Create stage) → `apiCreateStage` → `POST /mass-stages/` →
  **mass_stages** insert.
- `massStage.js` (Rename / transition) → `apiUpdateStage` →
  `PATCH /mass-stages/{id}` → **mass_stages** update.
- `massStage.js` (Delete) → `apiDeleteStage` → `DELETE /mass-stages/{id}` →
  **mass_stages** delete (slots/items cascade; does not reverse dispenses).
- `massStage.js` (Stage again) → `apiReuseStage` → `POST /mass-stages/{id}/reuse`
  → **mass_stages** insert (fresh empty stage).
- `massStage.js` (Add work order) → `apiAddStageWorkOrder` →
  `POST /mass-stages/{id}/work-orders` → **mass_stage_work_orders** insert
  (+ **work_orders** find-or-create, building match enforced).
- `massStage.js` (Remove slot) → `apiDeleteStageWorkOrder` →
  `DELETE /mass-stages/{id}/work-orders/{slot}` → **mass_stage_work_orders**
  delete (items cascade).
- `massStage.js` (Add / edit / remove planned item) → `apiAddStageItem` /
  `apiUpdateStageItem` / `apiDeleteStageItem` →
  `POST|PATCH|DELETE /mass-stages/{id}/work-orders/{slot}/items[/{sid}]` →
  **mass_stage_items** upsert/update/delete.
- `massStage.js` (Load) → `apiLoadStageItem` → `POST /mass-stages/{id}/load` →
  `load_item` → **items.quantity** −, **transactions** insert (per-slot dispense),
  **work_order_items** line per slot, **mass_stage_items.loaded_quantity** +.
- `massStage.js` (Return) → `apiReturnStageItem` → `POST /mass-stages/{id}/return`
  → `return_item` → **items.quantity** + (silent, no transaction row),
  **work_order_items** line reduced, **mass_stage_items.returned_quantity** +.

---

## Per-Table Index (who reads / who writes)

Quick reverse lookup: "which endpoints touch table X?"

| Table | Written by (endpoint #) | Read by (endpoint #) |
|-------|-------------------------|----------------------|
| `users` | 15, 16, 17, 18, 19 | 3, 5, 14, 20, 25–28 (assignee validation), 40 |
| `sessions` | 3 (insert), 4 (delete), 17 (revoke), 19 (cascade) | every authenticated request (5 + all gated) |
| `items` | 8, 9, 10, 12, 21, 22, 24, 30, 31, 33, 45, 46 | 6, 7, 20, 26, 36 |
| `item_barcodes` | 8 (check), 11 | 7, 8 (uniqueness) |
| `transactions` | 21, 22, 23, 24, 30, 31, 33, 45 | 20, 24, 26 (self-heal) |
| `work_orders` | 21 (f-o-c), 27, 28, 29, 40 (f-o-c) | 20–21, 25, 26, 36 |
| `work_order_items` | 21, 24, 30, 31, 32, 33, 45, 46 | 25, 26 |
| `mass_stages` | 34, 37, 38, 39 | 35, 36 |
| `mass_stage_work_orders` | 40, 41 | 36 |
| `mass_stage_items` | 42, 43, 44, 45, 46 | 36 |

f-o-c = find-or-create.

---

## Request / Response Contracts

Every wire shape, field by field. Types are Python/Pydantic; `?` = optional,
`=x` = default. "Validation" is what the schema rejects before the service runs.
Source: `app/schemas/*.py`.

### Auth (`schemas/auth.py`)

**`LoginRequest`** — body of `POST /auth/login`:
| Field | Type | Validation |
|-------|------|-----------|
| `username` | str | — |
| `password` | str | case-sensitive, not stripped |
| `remember` | bool=False | True ⇒ 12h-capped persistent session |

**`MeResponse`** — `POST /auth/login`, `GET /auth/me` return: `id: UUID`,
`username: str`, `role: str`. (Only what the frontend needs to gate UI.)

**`PasswordResetRequest`** — body of `POST /users/{id}/reset-password`:
`password: str` (≥ 4 chars, `MIN_PASSWORD_LENGTH`).

### Items (`schemas/items.py`)

**`ItemCreate`** — `POST /items/`:
| Field | Type | Validation |
|-------|------|-----------|
| `barcode` | str | uniqueness checked in service (cross-table) |
| `name` | str | — |
| `quantity` | Decimal=0 | ≥ 0 |
| `location` | str | non-blank (trimmed) |
| `price` | Decimal?=null | — |
| `product_link` | str?=null | — |
| `override_archived` | bool=False | confirm reuse of a barcode held by an archived item (see Error Catalog → 409) |

**`ItemUpdate`** — `PATCH /items/{id}` (partial): all of `barcode`, `name`,
`location`, `price`, `product_link` optional, plus `override_archived: bool=False`.
Rules: **≥ 1 real field required** (override flag alone doesn't count); `barcode`/
`name`/`location` are NOT NULL → sending them null/blank is rejected; `price`/
`product_link` sent as explicit `null` **clears** the column; **quantity is not
editable here** (use `POST /transactions/adjust`). Router forwards only sent
fields via `model_dump(exclude_unset=True)`.

**`ItemNotesUpdate`** — `PATCH /items/{id}/notes`: `notes: dict` (full replace),
validated by the notes whitelist (Domain Rules → Notes).

**`ItemBarcodesUpdate`** — `PATCH /items/{id}/barcodes`: `barcodes: list[str]`
(each trimmed, blanks dropped, in-list duplicate rejected) + `override_archived:
bool=False`. Full replace of *additional* codes only.

**`ItemResponse`** — any item return: `id`, `barcode`, `name`, `quantity`,
`location`, `notes: dict={}`, `barcodes: list[str]=[]` (additional codes),
`price?`, `product_link?`, `created_at`. **`price`/`product_link` are nulled
server-side below Admin** (`routers/items.py::_item_response`).

### Users (`schemas/users.py`)

**`UserCreate`** — `POST /users/`: `username: str` (non-blank), `password: str`
(≥ 4), `role: str` (must be a recognized role; whether the *caller* may assign it
is checked in the router, not here).

**`UserResponse`** — `id`, `username`, `role`, `created_at`, `archived_at?`
(null = active). Password hash is never serialized.

### Transactions & History (`schemas/transactions.py`)

**`TransactionCreate`** — `POST /transactions/`: `item_id: UUID`,
`transaction_type: "stock"|"dispense"` (literal; `adjust` is a separate route),
`quantity: Decimal` (> 0), `work_order_number: str?=null`, `work_order_id: UUID?=null`.

**`CorrectionCreate`** — `POST /transactions/adjust`: `item_id: UUID`,
`new_quantity: Decimal` (≥ 0; **absolute** target, service computes signed delta),
`reason: str` (non-blank).

**`BillingUpdate`** — `PATCH /transactions/{id}/billing`: `billable_quantity:
Decimal?=null` (bounds enforced in `domain.billing`).

**`TransactionResponse`** — create/adjust/billing return: `id`, `item_id`,
`user_id?`, `transaction_type`, `quantity`, `billable_quantity?`,
`work_order_number?`, `reason?`, `created_at`.

**`TransactionHistoryItem`** — each row of `GET /transactions/`: `id`, `item_id`,
`item_barcode`, `item_name`, `user_id?`, `username?`, `transaction_type`,
`quantity`, `work_order_number?`, `work_order_id?`, `reason?`, `item_price?`,
`billable_quantity?`, `created_at`. `item_price`/`billable_quantity` are Admin/
Owner-only **and null for work-order rows** (they bill via the line); `work_order_id`
is always present (lets the copy-table resolve the work order). **`TransactionHistoryPage`**:
`items: list[...]`, `total: int`, `page: int`, `page_size: int`.

### Barcodes (`schemas/barcodes.py`)

Request is `multipart/form-data` file upload (FastAPI `UploadFile`), no JSON body.
**`BarcodeDecodeResponse`**: `barcodes: list[BarcodeMatch]`, each `BarcodeMatch =
{ text: str, format: str }`. Empty list = readable image, no symbol (200); an
unreadable image is a 400.

### Work Orders (`schemas/work_orders.py`)

**`WorkOrderCreate`** — `POST /work-orders/`: `number: str` (non-blank, the
identity), `community?`, `building_number?`, `unit_number?`, `description?` (each
trimmed → null if blank), `assigned_to_id: UUID?` (must be a technician).

**`WorkOrderUpdate`** — `PATCH /work-orders/{id}` (partial, overwrite): `number?`,
`community?`, `building_number?`, `unit_number?`, `description?`, `status?`,
`entry_mode?`, `assigned_to_id?`. ≥ 1 field required; `status`/`entry_mode`
validated in the service.

**`WorkOrderItemCreate`** — `POST .../items`: `item_id: UUID`, `quantity: Decimal`
(> 0). **`WorkOrderItemUpdate`** — `PATCH .../items/{wid}`: `quantity: Decimal`
(> 0). **`WorkOrderItemBilling`** — `PATCH .../items/{wid}/billing`:
`billable_quantity: Decimal?=null` (≥ 0; upper bound vs line quantity enforced in
service).

**`WorkOrderCard`** — list rows: `id`, `number`, `community?`, `building_number?`,
`unit_number?`, `description?`, `status`, `entry_mode`, `created_by_id?`,
`assigned_to_id?`, `assigned_to_username?`, `item_count`. **`WorkOrderItemDetail`**:
`id`, `item_id`, `item_name`, `item_barcode`, `item_quantity` (live on-hand),
`quantity`, `mode`, `unit_price?`, `billable_quantity?` (last two Admin/Owner-only).
**`WorkOrderDetail`** = `WorkOrderCard` + `items: list[WorkOrderItemDetail]` +
`materials_total?` (Admin/Owner; Σ `effective_billable × unit_price`).

### Mass Stages (`schemas/mass_stages.py`)

**`MassStageCreate`** — `POST /mass-stages/`: `community: str`, `building_name: str`
(holds the building *number*); both non-blank. **`MassStageUpdate`** — `PATCH
/mass-stages/{id}`: `community?`, `building_name?`, `status?`; ≥ 1 required.
**`StageWorkOrderCreate`** — add slot: `work_order_number: str` (non-blank),
`unit_number?`, `assigned_to_id?`. **`StageItemCreate`** / **`StageItemUpdate`**:
`item_id`, `planned_quantity: Decimal` (> 0). **`LoadRequest`** / **`ReturnRequest`**:
`item_id: UUID`, `quantity: Decimal` (> 0).

Responses: **`MassStageSummary`** (list card): `id`, `community`, `building_name`,
`status`, `unit_count` (slots), `item_count` (distinct items), `created_at`.
**`MassStageDetail`**: + `work_orders: list[StageWorkOrderDetail]` +
`merged_items: list[MergedItem]`. **`StageWorkOrderDetail`** (a slot): `id` (slot
id), `work_order_id`, `work_order_number`, `unit_number?`, `status`, `sort_order`,
`assigned_to_id?`, `assigned_to_username?`, `items: list[StageItemDetail]`.
**`StageItemDetail`**: `id`, `item_id`, `item_name`, `item_barcode`,
`item_quantity` (on-hand), `planned_quantity`, `loaded_quantity`,
`returned_quantity`. **`MergedItem`** (per-item rollup for the load screen):
`item_id`, `item_name`, `item_barcode`, `on_hand`, `planned_total`,
`loaded_total`, `returned_total`, `overflow` (loaded beyond planned),
`net_consumed` (loaded − returned), `remaining_to_load` (planned − loaded).

---

## Error Catalog

Every `DomainError` subclass, its HTTP status (`routers/_errors.py::_STATUS_MAP`),
and the condition that raises it. Routers catch `DomainError` and call
`to_http(exc)`; an unmapped subclass defaults to **400**. `NegativeQuantityError`'s
user message is overridden to `"Insufficient stock to dispense."`. Unmapped
non-domain exceptions become FastAPI's default 500.

| Exception | HTTP | Raised when |
|-----------|------|-------------|
| `ItemNotFoundError` | 404 | item id/barcode unknown, or archived on a barcode lookup |
| `UserNotFoundError` | 404 | user id unknown |
| `TransactionNotFoundError` | 404 | txn id unknown or already voided |
| `StageNotFoundError` | 404 | mass-stage id unknown |
| `RoomNotFoundError` | 404 | stage **slot** not found / not in the stage (name retains old "room") |
| `StageItemNotFoundError` | 404 | planned stage item not found (incl. loading an unplanned item) |
| `WorkOrderNotFoundError` | 404 | work order unknown, archived, or **out of visibility scope** (404 hides existence) |
| `WorkOrderStateError` | 400 | invalid `status` (not in_progress/completed) or `entry_mode` (not dispense/retroactive); number collision on edit |
| `DuplicateBarcodeError` | 400 | barcode held by a **live** item (primary or additional) |
| `ArchivedBarcodeConflictError` | **409** | barcode held only by an **archived** item; retry with `override_archived=true` |
| `DuplicateUsernameError` | 400 | username UNIQUE constraint fired |
| `DuplicateBuildingStageError` | 400 | a (community, building) already has an active stage |
| `InvalidStageTransitionError` | 400 | stage status move not `planning→loading→completed` |
| `InvalidAssigneeError` | 400 | work-order assignee missing or not a technician |
| `ReturnExceedsLoadedError` | 400 | mass-stage return > net loaded |
| `StageStateError` | 400 | mass-stage op illegal for current status (edit after planning, load before loading) |
| `ItemHasTransactionsError` | 400 | hard-deleting an item with txns/stage rows (FK RESTRICT) |
| `UserHasTransactionsError` | 400 | hard-deleting a user referenced by txns (FK RESTRICT) |
| `NegativeQuantityError` | 400 | a dispense/adjust/void would drive on-hand < 0 |
| `NoChangeError` | 400 | correction `new_quantity` equals current (empty audit row) |
| `BillingQuantityError` | 400 | billing override negative, > recorded qty, or targets an `adjust` |
| `TransactionVoidError` | 400 | voiding would drive stock < 0 ("make a correction instead") |
| `UnreadableImageError` | 400 | uploaded bytes are not a decodable image |
| `InvalidCredentialsError` | **401** | bad username/password **or archived user** (indistinguishable) |
| `RoleManagementError` | **403** | actor does not outrank the target user |

Auth/gate errors are raised directly by `auth_deps.py` (not `DomainError`): **401**
no/invalid/expired session (`get_current_user`); **403** valid session but role too
low (`require_min_role`). Note: a few error class names (`RoomNotFoundError`,
`DuplicateBuildingStageError`) and their docstrings retain pre-rebuild "room"/
"building" wording but now apply to work-order slots / (community, building) stages.

---

## Domain Rules Quick Reference

Pure functions (no DB) in `domain/*.py` — the business rules, testable in isolation.

### Roles (`domain/roles.py`)
- Ranks: `technician 0 < supervisor 1 < admin 2 < owner 3`. Unknown role → rank −1.
- `role_at_least(role, min)` — the route-gate primitive (`>=` on rank).
- `can_transact(role, type)` — `dispense`: any valid role; `stock`: supervisor+; else False.
- `can_manage(actor, target)` — actor rank **strictly >** target rank (so no one
  manages their own level or an owner).
- `assignable_roles(actor)` — every role ranked strictly below the actor.

### Stock arithmetic (`domain/quantity.py`)
- `apply_delta(current, type, qty)`: `stock` → `current+qty`; `dispense` →
  `current−qty` (raise `NegativeQuantityError` if < 0); `adjust` → `current+qty`
  (signed; same < 0 guard). Inputs assumed pre-validated.
- `reverse_delta(current, type, qty)` (for void): undo `stock` = dispense, undo
  `dispense` = stock, undo `adjust` = apply negated delta. Same overdraft guard.

### Notes whitelist (`domain/notes_validation.py`)
- `notes` is a flat dict: keys non-blank strings (trimmed); values exactly one of
  `str | int | float | bool`. **`bool` checked before `int`** (bool subclasses int).
  Nested objects/arrays/None/other → `ValueError`.

### Work-order rules (`domain/work_orders.py`)
- Identity: `normalize_number(n) = n.strip().lower()` — mirrors the DB index
  `lower(btrim(number))`. Internal whitespace preserved.
- Statuses: `in_progress`, `completed` (both "active"/visible). Modes: `dispense`,
  `retroactive`. `affects_stock(mode)` = `mode == "dispense"`.
- `validate_status` / `validate_mode` → `WorkOrderStateError` on anything else.
- `fill_blank(current, incoming)` = keep non-blank `current`, else `incoming`
  (the find-or-create merge; `is_blank` = None or all-whitespace).
- `can_view_work_order(role, created_by_id, assigned_to_id, user_id)`: admin/owner
  (and `None` internal role) → all; supervisor → created by them; technician →
  assigned to them.

### Billing (`domain/billing.py`)
- `validate_billable_value(qty, billable)` — None passes (clear); else `0 ≤
  billable ≤ qty`, raise `BillingQuantityError`. Used by **work-order lines**.
- `validate_billable_quantity(type, qty, billable)` — same, plus only `stock`/
  `dispense` rows may be overridden (an `adjust` cannot). Used by **transactions**.

### Mass-stage lifecycle (`domain/mass_staging.py`)
- Status is forward-only: `planning → loading → completed`
  (`validate_transition`; any backward/same/unknown → `InvalidStageTransitionError`).
- Slots/items editable only in `planning`; load/return only in `loading`
  (else `StageStateError`).
- `allocate_return` caps a return at net-loaded across the item's slots
  (`ReturnExceedsLoadedError` if exceeded).

### Auth policy (`services/auth.py`, `auth_deps.py`)
- Password hash format: `scrypt$n$r$p$salt_hex$hash_hex` (n=2¹⁴, r=8, p=1,
  dklen=32, 16-byte salt). `verify_password` is constant-time (`hmac.compare_digest`)
  and returns False (never raises) on a malformed hash.
- Sessions: opaque `token_urlsafe(32)` row in `sessions`, carried by the HttpOnly,
  SameSite=Lax `session` cookie (Secure when `COOKIE_SECURE=true`). `remember=true`
  → `expires_at = now + 12h` (absolute cap, deleted on first request after expiry);
  else `expires_at = NULL` (browser-session, no server cap). **No idle timeout.**

---

## Service Algorithm Reference

Step-by-step internals of every non-trivial service function, so the logic need
not be re-read. "🔒" marks a `SELECT … FOR UPDATE` item-row lock (the
read-modify-write guard for `items.quantity`).

### `services/auth.py`
- `authenticate(username, password)` → find user by username; raise
  `InvalidCredentialsError` if missing **or archived** or password mismatch (all
  indistinguishable — no username enumeration).
- `create_session(user, remember)` → insert `sessions` row (`expires_at` per
  policy), return token.
- `get_active_session_user(token)` → load session; if expired-remembered, delete +
  return None; else return the owning user **unless archived** (defense in depth).
- `delete_session(token)` → delete by token (no-op if absent).

### `services/items.py`
- `_barcode_holder(code, exclude?)` → the item (live **or archived**) owning `code`
  as primary OR additional, excluding `exclude_item_id`. The cross-table uniqueness
  home (DB UNIQUE only covers primary-vs-primary and alt-vs-alt).
- `_ensure_barcode_free(code, exclude?, override_archived?)` → free: return; **live**
  holder: `DuplicateBarcodeError` (400); **archived** holder: `ArchivedBarcodeConflictError`
  (409) unless `override_archived`, then `_free_archived_holder`.
- `_free_archived_holder(holder, code)` → if holder has **no** history (no txns, no
  `mass_stage_items`): `db.delete` the whole archived item. If it **has** history:
  keep the shell, release only `code` — retire the primary (`"<barcode> (retired
  <id>)"`) if `code` is primary, else drop the matching additional row. Flush.
- `create_item(...)` → `_ensure_barcode_free` then insert; `IntegrityError` →
  `DuplicateBarcodeError`.
- `update_item(id, **_UNSET sentinels)` → partial: only non-`_UNSET` fields written;
  changing `barcode` runs `_ensure_barcode_free(exclude=self)`; explicit `None`
  clears price/link. `IntegrityError` → `DuplicateBarcodeError`.
- `replace_barcodes(id, codes, override?)` → validate only **added** codes (skip
  retained; reject one equal to the item's own primary); then **diff** the child
  rows (remove dropped, append new, leave retained) to avoid an INSERT-before-DELETE
  collision on the global `UNIQUE(code)`.
- `get_item_by_barcode(code)` → outer-join `item_barcodes`, match primary OR alt,
  **archived excluded**; `ItemNotFoundError` if none. Codes globally unique ⇒ ≤ 1 row.
- `list_items()` → live items, newest first, no pagination.
- `delete_item(id)` → set `archived_at` (soft delete; never hard — History joins
  need the row). Idempotent.

### `services/notes.py`
- `replace_notes(id, notes)` → assign `item.notes` then **`flag_modified(item,
  "notes")`** — required because SQLAlchemy compares JSONB by identity and would
  otherwise skip the commit. Caller pre-validates via `ItemNotesUpdate`.

### `services/users.py`
- `create_user(username, password_hash, role)` → insert; `IntegrityError` →
  `DuplicateUsernameError`. (Router hashes the password and checks `can_manage`.)
- `list_users(include_archived?)` → newest first; archived excluded unless asked
  (History "by user" passes True).
- `get_user(id)` → one or `UserNotFoundError` (router inspects role before acting).
- `reset_password(id, hash)` → overwrite hash; sessions left intact.
- `archive_user(id)` → set `archived_at` **and delete all the user's sessions**
  (immediate lockout). Idempotent.
- `restore_user(id)` → clear `archived_at`.
- `delete_user(id)` → hard delete; `IntegrityError` (FK from `transactions.user_id`,
  RESTRICT) → `UserHasTransactionsError`. (API-only; UI uses archive.)

### `services/transactions.py`
- `apply_transaction(item_id, type, qty, user_id, work_order_number, work_order_id)`
  → 🔒 lock item → `apply_delta` (stock/dispense) → insert txn with `unit_price =
  item.price` snapshot → **if `dispense` and `work_order_id`: `flush()` then
  `attach_dispense_line`** → commit. (Stock-in writes no line.)
- `apply_correction(item_id, new_quantity, reason, user_id)` → 🔒 lock → `delta =
  new − current`; `NoChangeError` if 0 → `apply_delta("adjust", delta)` → insert
  `adjust` txn (no `unit_price`) → commit.
- `void_transaction(id, user_id)` → 🔒 lock txn row; `TransactionNotFoundError` if
  missing/already voided. If `affects_stock`: 🔒 lock item, `reverse_delta`
  (`TransactionVoidError` if it would go < 0). If `work_order_id` and type in
  (dispense, adjust): walk the `work_order_items` line back (−qty for dispense, +qty
  for adjust), delete line at ≤ 0. Stamp `voided_at`/`voided_by_id`; commit.
- `set_billable_quantity(id, billable)` → `validate_billable_quantity`; update row
  only (no lock, no stock).

### `services/work_orders.py`
- `get_or_create_work_order(number, **attrs, created_by_id)` → `find_by_number`
  (case-insensitive, includes archived). Exists: un-archive if needed, `fill_blank`
  each attr, set assignee only if currently unassigned; commit. New: insert
  `in_progress`. Race on the unique index → rollback + reuse. The single
  find-or-create home (scan gate, free-text txn, Mass Stage all funnel here).
- `list_work_orders(user, status?, search?)` → newest first, archived excluded,
  scoped by `can_view_work_order` (supervisor → created, technician → assigned).
- `get_work_order(id, user)` → scoped load (`WorkOrderNotFoundError` if unknown/
  archived/out-of-scope); **`_heal_orphan_lines`**: sum non-voided linked dispenses
  per item with no line and create the missing `work_order_items` rows (lazy
  backfill, stock-neutral), commit if any healed.
- `attach_dispense_line(work_order_id, item_id, qty, mode, transaction_id, user_id)`
  → the single "show a stock-out on the work order" home. Find line by
  `(work_order_id, item_id)`: exists → `quantity += qty`, update `transaction_id`,
  promote `retroactive`→`dispense` if a dispense joins; else insert. **Never touches
  `items.quantity`** (caller owns the lock).
- `add_work_order_item(id, item_id, qty)` → scoped load → 🔒 lock item → if mode
  moves stock, `apply_delta("dispense")` → insert dispense txn (`affects_stock` per
  mode, `unit_price` snapshot) → `attach_dispense_line`.
- `update_work_order_item(id, wid, qty)` → 🔒 lock item; `stock_delta = old − new`;
  if dispense-mode and ≠ 0: `apply_delta("adjust", stock_delta)` + append one
  reconciling `adjust` txn (originals untouched). Set `line.quantity`; **clear
  `billable_quantity` if it now exceeds the new quantity**.
- `set_work_order_item_billable(id, wid, billable)` → `validate_billable_value`
  against `line.quantity`; set `line.billable_quantity`. No stock.
- `delete_work_order_item(id, wid)` → 🔒 lock item; if dispense-mode, return
  `line.quantity` to stock (`apply_delta("stock")`); **void the line's whole
  contributing txn set** (located by `(work_order, item)`); delete the line.
- `reduce_dispense_line(work_order_id, item_id, qty)` → inverse of attach (for a
  Mass Stage return): `quantity −= qty`, delete at ≤ 0. No lock, no stock. No-op if
  no line.

### `services/history.py`
- `list_history(item_id?, user_id?, work_order_number?, page, page_size,
  include_price)` → join `transactions ⋈ items ⋈ (outer) users`, exclude voided,
  AND the filters (`work_order_number` = case-sensitive `LIKE %…%`, `%`/`_`/`\`
  escaped), paginate (size ≤ 100), `total` = filtered count. Per row, `item_price`:
  **null if `not include_price` or `work_order_id` set**; else the frozen
  `unit_price` snapshot, falling back to live `item.price` only when the snapshot is
  NULL or 0. `billable_quantity` similarly null for work-order rows.

### `services/barcodes.py`
- `decode_image(bytes)` → PIL open (`UnreadableImageError` if it can't); `pyzbar`
  decode with **all** symbologies the installed zbar supports; map native type →
  canonical wire format (`_FORMAT_MAP`; unknown types pass through raw); collapse
  duplicate `(text, format)` preserving first-seen order. Empty list ≠ error.

### `services/mass_staging.py`
- `create_stage(community, building_name, user)` → pre-check the active-stage
  partial unique index (`DuplicateBuildingStageError`); insert a `planning` stage.
- `list_stages(user, status?)` → scoped (supervisor → own, admin/owner → all).
- `get_stage(id)` → builds `MassStageDetail` incl. the per-item `merged_items`
  rollup (planned/loaded/returned totals, overflow, net consumed, remaining).
- `update_stage(id, fields)` → rename and/or `validate_transition` the status.
- `delete_stage(id)` → delete (slots/items cascade); **does not reverse** load txns.
- `reuse_stage(id, user)` → requires a `completed` source; fresh empty `planning`
  stage for the same (community, building).
- `add_work_order_to_stage(id, number, unit?, assignee?)` → find-or-create the
  `WorkOrder` (via `services.work_orders`), enforce its community/building match the
  stage, link a `mass_stage_work_orders` slot. Planning only.
- `delete_slot` / `add_item` / `update_item` / `delete_item` → slot & planned-item
  edits; planning only (`StageStateError` otherwise).
- `load_item(id, item_id, qty)` → loading only; 🔒 lock item; allocate `qty` across
  the item's slot plans by `sort_order`; write a per-slot **dispense** carrying that
  slot's `work_order_id` (+ `attach_dispense_line`); increment
  `loaded_quantity`; decrement `items.quantity`.
- `return_item(id, item_id, qty)` → loading only; 🔒 lock item; `allocate_return`
  (cap at net-loaded) reverse-fills across slots; increment `returned_quantity`;
  **add stock back with no transaction row** (the one deliberate silent stock change);
  `reduce_dispense_line` so the work order reflects net consumption.

---

## Notes For Future Edits

- **Adding an endpoint?** Touch all four layers (router → service → `api.js`
  wrapper → view) and add a row to the Master Index + Per-Table Index here.
- **The single most-wired write** is `POST /transactions/` (#21): it fans into
  items, transactions, work_orders, and work_order_items. `attach_dispense_line`
  is the shared funnel every stock-out path (here, work-order item add, mass-stage
  load) goes through — see `current-state.md` → Work orders invariants.
- **Stock changes** only ever happen inside a service under a `SELECT … FOR
  UPDATE` item-row lock (#21, 22, 24, 30, 31, 33, 45, 46). The one silent
  stock change with no transaction row is mass-stage **return** (#46).
- **Cost/billing fields** (`item_price`, `billable_quantity`, `unit_price`,
  `materials_total`) are redacted server-side below Admin on #20, #25, #26.
