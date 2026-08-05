# Endpoint Map: Database ↔ User View

Last reviewed: 2026-08-05

Purpose: a complete, self-contained trace of all 69 endpoints — wiring, contracts,
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
| 5 | GET | `/auth/me` | session | `auth_deps.get_current_user` | sessions (r), users (r) | `apiMe` | `auth.js`, `tools.js` (self profile) |
| 6 | GET | `/items/` | session | `items.py` → `items.list_items` (optional `q`) | items (r) | `apiListItems` | `items.js`, `addBarcode.js`, `transactions.js`, `massStage.js`, `workOrders.js` |
| 7 | GET | `/items/{barcode}` | session | `items.py` → `items.get_item_by_barcode` | items (r), item_barcodes (r) | `apiGetItemByBarcode` | `scan.js`, `addBarcode.js`, `history.js` |
| 8 | POST | `/items/` | admin+ | `items.py` → `items.create_item` | items (w), item_barcodes (r) | `apiCreateItem` | `items.js` |
| 9 | PATCH | `/items/{id}` | admin+ | `items.py` → `items.update_item` (+ `user_requests.resolve_missing_price_requests`) | items (w/lock), item_barcodes (r), user_requests (w when price+link complete) | `apiUpdateItem` | `itemEditor.js`, `userRequests.js` |
| 10 | PATCH | `/items/{id}/notes` | supervisor+ | `items.py` → `notes.replace_notes` | items (w) | `apiUpdateNotes` | `notes.js` |
| 11 | PATCH | `/items/{id}/barcodes` | admin+ | `items.py` → `items.replace_barcodes` | item_barcodes (w), items (r) | `apiUpdateBarcodes` | `itemEditor.js`, `addBarcode.js` |
| 12 | DELETE | `/items/{id}` | admin+ | `items.py` → `items.delete_item` | items (w, archive) | `apiDeleteItem` | `items.js` |
| 13 | POST | `/barcodes/decode` | session | `barcodes.py` → `barcodes.decode_image` | — (no persistence) | `apiDecodeBarcode` | `scan.js` |
| 14 | GET | `/users/` | supervisor+ | `users.py` → `users.list_users` | users (r) | `apiListUsers` | `users.js`, `transactions.js`, `massStage.js`, `workOrders.js`, `tools.js` (Admin/Owner only) |
| 15 | POST | `/users/` | outranks target | `users.py` → `users.create_user` | users (w) | `apiCreateUser` | `users.js` |
| 16 | POST | `/users/{id}/reset-password` | outranks target | `users.py` → `users.reset_password` | users (w) | `apiResetPassword` | `users.js` |
| 17 | POST | `/users/{id}/archive` | outranks target | `users.py` → `users.archive_user` + `tools.user_custody` (+ `tools.return_all_for_user` when `?force_return_tools=true`) | users (w), sessions (w, revoke), tools/tool_transactions (r, custody guard; w on force check-in) | `apiArchiveUser` | `users.js` |
| 18 | POST | `/users/{id}/restore` | outranks target | `users.py` → `users.restore_user` | users (w) | `apiRestoreUser` | `users.js` |
| 19 | DELETE | `/users/{id}` | outranks target | `users.py` → `users.delete_user` | users (w, hard) | `apiDeleteUser` | **API-only** (no UI; UI uses archive) |
| 20 | GET | `/transactions/` | supervisor+ | `transactions.py` → `history.list_history` | transactions (r), items (r), users (r) | `apiListTransactions` | `history.js` |
| 21 | POST | `/transactions/` | session + direction¹ | `transactions.py` → `transactions.apply_transaction` (+ `work_orders.resolve_work_order`, `attach_dispense_line`; User Request producers for shortage/missing price) | items (w), transactions (w), work_orders (r/w²), work_order_items (w³), user_requests (w on shortage or NULL/non-positive work-order price) | `apiCreateTransaction` | `transactions.js` |
| 22 | POST | `/transactions/adjust` | admin+ | `transactions.py` → `transactions.apply_correction` | items (w), transactions (w) | `apiCreateCorrection` | `correction.js` |
| 23 | PATCH | `/transactions/{id}/billing` | admin+ | `transactions.py` → `transactions.set_billable_quantity` | transactions (w) | `apiSetBillableQuantity` | `history.js` |
| 24 | DELETE | `/transactions/{id}` | supervisor+, or Technician's own linked dispense | `transactions.py` → `transactions.void_transaction` (+ `user_requests.resolve_for_transaction`) | transactions (w, soft), items (w), work_order_items (w⁴), user_requests (w if linked) | `apiVoidTransaction` | `history.js`, `transactions.js` |
| 25 | GET | `/work-orders/` | session scoped | `work_orders.py` → `work_orders.list_work_orders` (scheduled-date descending; joinable status/service/supervisor/community/date/number filters) | work_orders (r), work_order_items (r), work_order_technicians (r), users (r) | `apiListWorkOrders` | `workOrders.js`, `transactions.js`, `history.js`, `adminReview.js` |
| 26 | GET | `/work-orders/{id}` | session scoped | `work_orders.py` → `work_orders.get_work_order` | work_orders (r), work_order_items (r/w⁵), work_order_technicians (r), work_order_labor (r), items (r), users (r) | `apiGetWorkOrder` | `workOrders.js`, `history.js`, `adminReview.js` |
| 27 | GET | `/work-orders/lookup?number=` | supervisor+ scoped | `work_orders.py` → `work_orders.lookup_work_order` | work_orders (r, **incl. archived**) | `apiLookupWorkOrder` | `history.js` |
| 28 | PATCH | `/work-orders/{id}` | scoped; notes→tech+, operations→sup+, metadata→admin+; stale supervisor precondition→409 | `work_orders.py` → `work_orders.update_work_order` | work_orders (r/w, row lock; incl. notes/primary mirror), work_order_technicians (w), users (r) | `apiUpdateWorkOrder` | `workOrders.js`, `adminReview.js` (Return to In-Progress) |
| 29 | POST | `/work-orders/{id}/archive` | admin+ scoped; any live status | `work_orders.py` → `work_orders.archive_work_order` | work_orders (w, Closed/archive) | `apiArchiveWorkOrder` | `workOrders.js`, `adminReview.js` |
| 30 | POST | `/work-orders/{id}/items` | Technician+ scoped | `work_orders.py` → `work_orders.add_work_order_item` | items (w; negative expected count allowed in dispense mode), transactions (w), work_order_items (w), user_requests (w if stock is short or item is unpriced) | `apiAddWorkOrderItem` | `workOrders.js` |
| 31 | PATCH | `/work-orders/{id}/items/{wid}` | supervisor+ scoped | `work_orders.py` → `work_orders.update_work_order_item` | items (w), transactions (w, adjust), work_order_items (w) | `apiUpdateWorkOrderItem` | `workOrders.js` |
| 32 | PATCH | `/work-orders/{id}/items/{wid}/billing` | admin+ scoped | `work_orders.py` → `work_orders.set_work_order_item_billable` | work_order_items (w) | `apiSetWorkOrderItemBilling` | `workOrders.js` |
| 33 | DELETE | `/work-orders/{id}/items/{wid}` | supervisor+ scoped | `work_orders.py` → `work_orders.delete_work_order_item` | items (w), transactions (w, void), work_order_items (w), user_requests (w, resolve source-linked) | `apiDeleteWorkOrderItem` | `workOrders.js` |
| 34 | POST | `/mass-stages/` | supervisor+ | `mass_stages.py` → `mass_staging.create_stage` | mass_stages (w) | `apiCreateStage` | `massStage.js` |
| 35 | GET | `/mass-stages/` | supervisor+ scoped | `mass_stages.py` → `mass_staging.list_stages` | mass_stages (r) | `apiListStages` | `massStage.js` |
| 36 | GET | `/mass-stages/{id}` | supervisor+ | `mass_stages.py` → `mass_staging.get_stage` | mass_stages (r), mass_stage_work_orders (r), mass_stage_items (r), work_orders (r), items (r) | `apiGetStage` | `massStage.js` |
| 37 | PATCH | `/mass-stages/{id}` | supervisor+ | `mass_stages.py` → `mass_staging.update_stage` | mass_stages (w) | `apiUpdateStage` | `massStage.js` |
| 38 | DELETE | `/mass-stages/{id}` | supervisor+ | `mass_stages.py` → `mass_staging.delete_stage` | mass_stages (w), slots/items (cascade) | `apiDeleteStage` | `massStage.js` |
| 39 | POST | `/mass-stages/{id}/reuse` | supervisor+ | `mass_stages.py` → `mass_staging.reuse_stage` | mass_stages (w) | `apiReuseStage` | `massStage.js` |
| 40 | POST | `/mass-stages/{id}/work-orders` | supervisor+ | `mass_stages.py` → `mass_staging.add_work_order_to_stage` | mass_stage_work_orders (w), work_orders (r/w, **resolve** — 404 if not imported) | `apiAddStageWorkOrder` | `massStage.js` |
| 41 | DELETE | `/mass-stages/{id}/work-orders/{slot}` | supervisor+ | `mass_stages.py` → `mass_staging.delete_slot` | mass_stage_work_orders (w), mass_stage_items (cascade) | `apiDeleteStageWorkOrder` | `massStage.js` |
| 42 | POST | `/mass-stages/{id}/work-orders/{slot}/items` | supervisor+ | `mass_stages.py` → `mass_staging.add_item` | mass_stage_items (w) | `apiAddStageItem` | `massStage.js` |
| 43 | PATCH | `/mass-stages/{id}/work-orders/{slot}/items/{sid}` | supervisor+ | `mass_stages.py` → `mass_staging.update_item` | mass_stage_items (w) | `apiUpdateStageItem` | `massStage.js` |
| 44 | DELETE | `/mass-stages/{id}/work-orders/{slot}/items/{sid}` | supervisor+ | `mass_stages.py` → `mass_staging.delete_item` | mass_stage_items (w) | `apiDeleteStageItem` | `massStage.js` |
| 45 | POST | `/mass-stages/{id}/load` | supervisor+ | `mass_stages.py` → `mass_staging.load_item` | items (w), transactions (w), work_order_items (w), mass_stage_items (w), user_requests (w if unpriced) | `apiLoadStageItem` | `massStage.js` |
| 46 | POST | `/mass-stages/{id}/return` | supervisor+ | `mass_stages.py` → `mass_staging.return_item` | items (w, silent), work_order_items (w), mass_stage_items (w) | `apiReturnStageItem` | `massStage.js` |
| 47 | POST | `/tools/` | admin+ | `tools.py` → `tools_service.create_tool` | tools (w) | `apiCreateTool` | `tools.js` |
| 48 | GET | `/tools/` | session | `tools.py` → `tools_service.list_tools` + `tool_custody` | tools (r), tool_transactions (r), users (r) | `apiListTools` | `tools.js` |
| 49 | GET | `/tools/{barcode}` | session | `tools.py` → `tools_service.get_tool_by_barcode` + `tool_custody` | tools (r), tool_transactions (r), users (r) | `apiGetToolByBarcode` | `tools.js` |
| 50 | PATCH | `/tools/{tool_id}` | admin+ | `tools.py` → `tools_service.update_tool` | tools (w) | `apiUpdateTool` | `tools.js` |
| 51 | DELETE | `/tools/{tool_id}` | admin+ | `tools.py` → `tools_service.delete_tool` + `tool_custody` | tools (r/w, archive), tool_transactions (r, custody guard) | `apiDeleteTool` | `tools.js` |
| 52 | POST | `/tools/{tool_id}/checkout` | admin+ | `tools.py` → `tools_service.checkout_tool` | users (r, active-target guard), tools (w), tool_transactions (w) | `apiCheckoutTool` | `toolCheckout.js` |
| 53 | POST | `/tools/{tool_id}/return` | session | `tools.py` → `tools_service.return_tool` | tools (w), tool_transactions (w, r for cap check) | `apiReturnTool` | `toolReturn.js` |
| 54 | POST | `/tools/{tool_id}/adjust` | admin+ | `tools.py` → `tools_service.adjust_tool_quantity` | tools (w), tool_transactions (w) | `apiAdjustTool` | `toolCorrection.js` |
| 55 | POST | `/work-orders/import` | admin+ | `work_orders.py` → `work_orders.import_work_orders` | work_orders (r/w, locked find-or-create — **the only create path**), users (r, active-supervisor name-match) | `apiImportWorkOrders` | `workOrders.js` |
| 56 | POST | `/work-orders/{id}/restore` | supervisor+ scoped | `work_orders.py` → `work_orders.restore_work_order` | work_orders (w, un-archive) | `apiRestoreWorkOrder` | `history.js` |
| 57 | GET | `/items/search-index` | session | `items.py` → `items.list_item_search_index` | items (r; name/barcode projection only) | — | — (retained compatibility endpoint; current Find Item does not request it) |
| 58 | PATCH | `/users/{id}/name` | self or outranks target | `users.py` → `users.update_name` | users (w; first/last name + optional `username`) | `apiUpdateUserName` | `users.js` |
| 59 | POST | `/work-orders/{id}/labor` | supervisor+ scoped | `work_orders.py` → `work_orders.add_work_order_labor` | work_orders (r/w status), work_order_technicians (r), work_order_labor (w), users (r) | `apiAddWorkOrderLabor` | `workOrders.js` |
| 60 | PATCH | `/work-orders/{id}/labor/{labor_id}` | supervisor+ scoped | `work_orders.py` → `work_orders.update_work_order_labor` | work_order_labor (r/w) | `apiUpdateWorkOrderLabor` | `workOrders.js` |
| 61 | DELETE | `/work-orders/{id}/labor/{labor_id}` | supervisor+ scoped | `work_orders.py` → `work_orders.delete_work_order_labor` | work_order_labor (r/w) | `apiDeleteWorkOrderLabor` | `workOrders.js` |
| 62 | PATCH | `/users/{id}/role` | admin+ AND outranks both current and new role | `users.py` → `users.update_role` | users (w), sessions (w, revoke) | `apiUpdateUserRole` | `users.js` |
| 63 | GET | `/work-orders/export` | admin+, server-scoped | `work_orders.py` → `work_orders.export_work_orders_csv` (full: current live filters; client: unchanged scope dropdown; + `domain.receipt`) | work_orders (r), work_order_items (r), items (r), work_order_labor (r), users (r) | `apiExportWorkOrders` | `workOrders.js` |
| 64 | GET | `/work-orders/filter-options` | session scoped | `work_orders.py` → `work_orders.get_work_order_filter_options` | work_orders (r), work_order_technicians (r, scope), users (r) | `apiGetWorkOrderFilterOptions` | `workOrders.js` |
| 65 | GET | `/work-orders/legacy/archive` | owner exactly | `work_orders.py` → `work_orders.count_live_legacy_work_orders` | work_orders (r; live legacy count) | `apiGetLegacyWorkOrderArchivePreview` | `workOrders.js` |
| 66 | POST | `/work-orders/legacy/archive` | owner exactly | `work_orders.py` → `work_orders.archive_live_legacy_work_orders` | work_orders (w; atomic bulk soft-archive) | `apiArchiveLegacyWorkOrders` | `workOrders.js` |
| 67 | POST | `/work-orders/{id}/start` | technician+ scoped | `work_orders.py` → `work_orders.start_work_order` | work_orders (r/w, row lock) | `apiStartWorkOrder` | `transactions.js` |
| 68 | GET | `/user-requests/` | admin+ | `user_requests.py` → `user_requests.list_user_requests` | user_requests (r), items (r), work_orders (r), users (r) | `apiListUserRequests` | `userRequests.js` |
| 69 | PATCH | `/user-requests/{id}` | admin+ | `user_requests.py` → `user_requests.update_user_request` | user_requests (r/w), users (r) | `apiUpdateUserRequest` | `userRequests.js` |

(Rows 55–69 were appended out of resource order to keep the existing #1–54
numbering — and the footnote / per-table references to it — stable.)

Footnotes:
1. `POST /transactions/`: dispense = any authenticated user; stock = supervisor+ (`domain.roles.can_transact`). A Scan/Stock dispense may take expected quantity below zero and opens a recount request. Work Orders Add Item has the same deliberate exception; Work Order quantity edits and the other stock-out paths retain the strict no-overdraft domain rule.
2. work_orders: read when a scanned card passes `work_order_id`; resolved (read, plus a fill-blanks write) when a Supervisor+ passes a free-text `work_order_number` — 404 if that number was never imported.
3. work_order_items: a line is created/accumulated only for a `dispense` carrying a `work_order_id` (a stock-in writes none).
4. void walks the work_order_items line back (drops it at zero) when the voided row carries a `work_order_id`; it also resolves any request linked to the source transaction. Supervisor+ may void any eligible row, while a Technician may remove only their own work-order-linked dispense.
5. `get_work_order` lazily self-heals orphaned linked dispenses into lines on read (a write inside a read).

---

## Direction A — Database → User View (read flows)

What populates each screen. Format: **table → … → view → what the user sees**.

### Boot / session
- **sessions, users** → `auth_deps.get_current_user` → `GET /auth/me` → `apiMe` →
  `auth.js`: on load, 200 ⇒ enter app (nav visibility applied); 401 ⇒ login screen.
  The identity includes `created_at` / `archived_at`; `tools.js` uses those
  fields to render a self-only custody profile for Supervisor/Technician.
- **(static fragments)** → `main.py` shell assembly → `GET /` → browser: the SPA
  shell (`shell-head.html` + `pages/*.html` + `shell-tail.html`).

### Items
- **items** → `list_item_search_index` → `GET /items/search-index`: retained
  lightweight name/barcode projection endpoint with no current frontend
  consumer. Find Item makes no item request on entry and shows no native
  suggestion popup.
- **items** → `list_items` → `GET /items/` (optional `q`) → `apiListItems` →
  - `items.js`: explicit full-dataset Search/Enter results or Load All Items
    (Admin/Owner see price/link columns); typing alone does not render cards.
  - `addBarcode.js`: debounced name picker independent of the Find Item cache.
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
  - `users.js`: the account table (first/last/username; archived included,
    dimmed) and full-name History filter.
  - `transactions.js` / `massStage.js`: technician dropdowns rendered by full
    name.
  - `workOrders.js`: Edit Details locally searches the already-loaded active
    Technicians by full name, offers only unselected matches in a dropdown, and
    lists the draft assignment set below it. Save replaces `assigned_to_ids`.
  - `tools.js`: Admin/Owner's full-name active-user custody search (archived
    excluded).

### Transaction history
- **transactions ⋈ items ⋈ users** → `list_history` → `GET /transactions/` →
  `apiListTransactions` → `history.js`: the paginated History table. It renders
  the acting user's full name; no login username is returned. Admin/Owner get
  the Charge column (`item_price` × qty × 1.15) — **null for work-order rows**
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

### User requests
- **user_requests ⋈ items ⋈ work_orders ⋈ users** → `list_user_requests` →
  `GET /user-requests/?status=open|resolved` → `apiListUserRequests` →
  `userRequests.js`: Admin/Owner see recount disparities and missing-price/link
  tasks with item/barcode, affected work orders, current price/link, requestor,
  state, and resolution metadata. Missing-price cards expose both item fields
  inline; the page remains request-type-generic.

### Mass staging
- **mass_stages** → `list_stages` → `GET /mass-stages/` → `apiListStages` →
  `massStage.js`: the Community → Building → Unit tree.
- **mass_stages ⋈ slots ⋈ items ⋈ work_orders** → `get_stage` →
  `GET /mass-stages/{id}` → `apiGetStage` → `massStage.js`: stage detail (slots,
  planned/loaded/returned quantities).

### Tools
- **tools ⋈ tool_transactions ⋈ users** → `list_tools` + `tool_custody` →
  `GET /tools/` → `apiListTools` → `tools.js`: the Inventory table and the
  selected user's custody-card holdings (both derived from each tool's
  `custody` breakdown).
- **users** → `list_users(include_archived=false)` → `GET /users/` →
  `apiListUsers` → `tools.js`: Admin/Owner's searchable active-user picker.
  Supervisor/Technician skip this request and use `/auth/me` for a self-only
  card.
- **tools ⋈ tool_transactions ⋈ users** → `get_tool_by_barcode` +
  `tool_custody` → `GET /tools/{barcode}` → `apiGetToolByBarcode` →
  `tools.js`: either an Inventory lookup or a selected-user checkout
  confirmation, depending on scanner context.

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
  → **items** partial update (explicit null clears price/link). Once a positive
  price and nonblank product link exist, all open missing-price **user_requests** for
  that item resolve in the same commit.
- `notes.js` (Save notes) → `apiUpdateNotes` → `PATCH /items/{id}/notes` →
  `replace_notes` → **items.notes** JSONB replace.
- `itemEditor.js` / `addBarcode.js` (Save barcodes) → `apiUpdateBarcodes` →
  `PATCH /items/{id}/barcodes` → `replace_barcodes` → **item_barcodes** diff/replace.
- `items.js` (Archive) → `apiDeleteItem` → `DELETE /items/{id}` → `delete_item` →
  **items.archived_at** set (soft delete).

### Stock movement (the core write)
- `transactions.js` (initial gate load / live work-order-number filter) →
  `apiListWorkOrders` → `GET /work-orders/[?q=]` → client keeps scoped Created,
  Assigned, and In-Progress **work_orders** cards. Search only filters. Selecting
  In-Progress arms the batch; selecting Assigned and accepting the confirmation
  calls `apiStartWorkOrder` → `POST /work-orders/{id}/start`, atomically changes
  **work_orders.status** to In-Progress, and arms the batch without navigation.
  Selecting Created still confirms whether to open and expand Work Orders.
- `transactions.js` (scan-and-go / manual Add Stock / Take Out) →
  `apiCreateTransaction` → `POST /transactions/` → `apply_transaction` →
  **items.quantity** ±, **transactions** insert; if a `dispense` carries a
  `work_order_id`, also **work_order_items** line create/accumulate. A dispense
  beyond counted stock is committed with a negative expected count and creates
  one linked open **user_requests** `inventory_recount` row; the UI renders the
  result red with `Please re-count stock`. Any work-order material with a NULL
  or non-positive price (`$0.00` included) also
  creates or extends one item-level `missing_item_price` request with every
  affected work-order number. The manual item picker is hidden until a
  work-order card has been selected.
- `transactions.js` (Remove on a successful scan) → `apiVoidTransaction` →
  `DELETE /transactions/{id}` → `void_transaction` → reverses **items.quantity**,
  adjusts/deletes the **work_order_items** line, soft-voids the **transaction**,
  and resolves its linked **user_requests** row. Supervisor+ may remove eligible
  transactions; Technician is limited to their own work-order-linked dispense.
- `correction.js` (Correct count) → `apiCreateCorrection` →
  `POST /transactions/adjust` → `apply_correction` → **items.quantity** set,
  **transactions** insert (`adjust`, signed delta).
- `history.js` (Edit charge) → `apiSetBillableQuantity` →
  `PATCH /transactions/{id}/billing` → `set_billable_quantity` →
  **transactions.billable_quantity** (no stock change).
- `history.js` (Delete/Void) → `apiVoidTransaction` → `DELETE /transactions/{id}`
  → `void_transaction` → **transactions.voided_at** set, **items.quantity**
  reversed; walks the **work_order_items** line back if work-order-linked.

### User requests
- `userRequests.js` (Save price & link) → `apiUpdateItem` → `PATCH /items/{id}`
  → the inline price input uses `min="0.01"` and rejects zero or negative values,
  then writes **items.price/product_link** together; `update_item` auto-resolves
  the item's open missing-price **user_requests** only when a price greater than
  zero and a nonblank link both exist, removing the
  card from the default open queue while preserving resolved history.
- `userRequests.js` (recount-card Mark resolved / Reopen) → `apiUpdateUserRequest` →
  `PATCH /user-requests/{id}` → `update_user_request` → **user_requests.status**,
  `resolved_at`, `resolved_by_id`, and optional `resolution_note` update. Admin+
  only; reopening clears the resolution fields. Resolved missing-price cards are
  read-only audit entries in the page, although the generic endpoint accepts a
  reopen request from an API client.

### Users
- `users.js` (Create) → `apiCreateUser` → `POST /users/` → **users** insert.
- `users.js` (Edit Details) → `apiUpdateUserName` → `PATCH /users/{id}/name` →
  **users.first_name/last_name/username** update (self or manageable
  subordinate; a duplicate username is a 400).
- `users.js` (Edit Role) → `apiUpdateUserRole` → `PATCH /users/{id}/role` →
  **users.role** update + **sessions** delete (Admin+, and only for roles the
  actor outranks — so nobody promotes to their own level).
- `users.js` (Reset password) → `apiResetPassword` →
  `POST /users/{id}/reset-password` → **users.password_hash** update.
- `users.js` (🗑️ Archive) → `apiArchiveUser` → `POST /users/{id}/archive` →
  **users.archived_at** set + **sessions** delete (revoke). 409 while the user
  holds tools; the retry (`?force_return_tools=true`) writes a **return** row
  per held tool and restores their **tools.quantity** before archiving.
- `users.js` (Restore) → `apiRestoreUser` → `POST /users/{id}/restore` →
  **users.archived_at** cleared.
- *(API-only)* `apiDeleteUser` → `DELETE /users/{id}` → hard delete (blocked if
  transactions reference the user). No UI surfaces this.

### Work orders
Work orders are **import-only**: the CSV import is the one write that creates a
`work_orders` row. There is no create endpoint and no "new work order" form
anywhere in the UI; every other surface resolves an existing number and 404s on
one no import has brought in.

- `workOrders.js` (advanced filters) → `apiGetWorkOrderFilterOptions` for
  caller-scoped service/supervisor choices, then one `apiListWorkOrders` request
  carrying any active `status`, `service_type`, `supervisor_id`, `community`,
  `scheduled_date`, and `q`. The service adds every predicate with AND before
  applying the normal role scope. Community is membership-based over
  `community` + raw `location`; Commons includes Cimarron/Cimmarron,
  multi-location rows can match several named choices, and Academics means no
  known community term. The final rows sort by parsed scheduled date descending.
- `workOrders.js` (Import from CSV, Admin+) → `apiImportWorkOrders` →
  `POST /work-orders/import` → `import_work_orders` → per row **work_orders**
  lock/find-or-create live numbers with idempotent fill-blanks; supervisor
  routing fills only while the locked row is still NULL, so a manual reroute
  wins over a later or concurrent import. An archived match is counted as
  closed and ignored before merge/routing. Reads **users** to
  name-match the vendor `ASSIGNED TO` to a supervisor (`supervisor_id`) for live
  rows. *The only path that creates a work order.*
- `workOrders.js` (Re-archive legacy work orders..., Owner only) first calls
  `apiGetLegacyWorkOrderArchivePreview` → `GET /work-orders/legacy/archive` →
  `count_live_legacy_work_orders` and shows the returned live-row count in the
  shared modal. A zero count uses a message-only dialog; otherwise confirmation
  proceeds to the write flow below.
- `workOrders.js` (Export filtered CSV beside Search, Admin+) →
  `apiExportWorkOrders` → `GET /work-orders/export?scope=…&variant=full&…` →
  `export_work_orders_csv` → reads **work_orders** (+ lines, items, labor,
  users) and returns every row matching the current live status, service type,
  supervisor, community, scheduled date, and number filters. Predicates combine
  with AND under the same caller scope as the card list; the display cap does not
  apply. Rows use scheduled-date-descending order. The first seven columns are
  the import's own headers, so live rows re-import cleanly. The response filename
  is `MM-DD-YY_HH-MM_filter1-filter2.csv` (UTC), using every active filter value;
  `-` replaces the requested time colon because `:` is invalid on Windows.
- `workOrders.js` (For Client, Admin+) → same route with `variant=client` →
  four columns only: `WORK ORDER`, `MATERIAL TOTAL`, `LABOR TOTAL`, `RECEIPT`.
  Its existing scope dropdown remains authoritative; advanced page filters are
  not sent or applied. Its filename is `MM-DD-YY_HH-MM_client-scope.csv`.
  Both totals are the BILLED figures (materials marked up 15%, labor at the
  labor rate), so they sum to the receipt in the last cell. `RECEIPT` is the
  full Admin Review receipt text, built by `domain.receipt` — the Python port of
  `static/adminReviewReceipt.js`, pinned character-for-character by
  `tests/test_receipt.py`.
- `workOrders.js` (Edit details → Save, Supervisor+) → `apiUpdateWorkOrder` →
  `PATCH /work-orders/{id}` → `update_work_order` → **work_orders** update. The
  editor is a nested Edit details card, collapsed by default beneath the
  persistent read-only overview. Supervisor sees only routing (`supervisor_id`,
  `assigned_to_ids`) and status. The technician
  picker renders no complete user list: typing opens a case-insensitive full-name
  result dropdown, selected users are excluded, and each choice is added to a
  removable list below the search. The remaining row IDs are serialized as the
  replacement `assigned_to_ids` set.
  Admin/Owner also receives imported metadata inputs (`location`, `service_type`,
  `schedule_date`, `output_to`, `vendor_assignee`, `description`). Legacy place
  fields and number are read-only. The existing status selector offers
  In-Progress for Created/Assigned, so it replaces the former standalone start
  action while retaining rollback and On-Hold choices; On-Hold can resume to a
  non-Review step. Created/Assigned is normalized from technician presence.
  Review remains outside this selector. Save and Cancel re-fetch the card and
  restore the nested editor's default collapsed state. `number` is not editable — the import
  matches on it. The patch includes the editor's original `supervisor_id` as
  `expected_supervisor_id`; the service locks the row before comparing it. If a
  different supervisor already picked it up, the API returns 409 with `This
  Work Order was already assigned to [First] [Last]`; the one-button prompt
  reloads the page when dismissed. A successful transfer is returned through
  internal response scope so routing it away does not become a false 404.
- `workOrders.js` (mode / lifecycle actions, Supervisor+) →
  `apiUpdateWorkOrder` → same route. Only Supervisor+ receives the mode, Mark
  completed, Reopen, or Send to Review controls. Explicit Created/Assigned →
  In-Progress now comes from the existing Edit details status dropdown; material
  or labor activity still advances automatically, and the separate scoped Scan /
  Stock start route remains unchanged. Send to Review on a Completed card still requires reviewing the
  work and accepting a confirmation pop-up before the Review PATCH sends it to
  final Admin Review. Status-colored cards are gray/red/yellow/orange/blue/green for
  Created/Assigned/In-Progress/On-Hold/Completed/Review.
- `workOrders.js` renders Notes, Materials, and Supervisor+ Labor as native
  nested cards that are collapsed by default. Materials contains logged rows,
  the no-material state, Admin material total, and item search/quantity/Add
  controls. Material and Labor cards reopen after their write-triggered detail
  refreshes so changed data remains visible; Notes closes after a successful
  save. The existing API calls and permissions are unchanged.
- `workOrders.js` (Save notes, any in-scope user) → `apiUpdateWorkOrder` → same
  route with one nonblank `{notes}` entry → row-locked `append_note_log` →
  **work_orders.notes** append. The server prefixes Central `h:mm AM/PM`,
  `MMDDYY`, and the authenticated user's `full_name`; existing/legacy text is
  retained. The response returns the complete log. The browser replaces the
  visible log from that response, clears the new-note textarea, and closes the
  nested Notes card. Blank input is rejected client-side; null cannot clear the
  stored log.
- `workOrders.js` (Add/update/remove labor, Supervisor+ only) →
  `apiAddWorkOrderLabor` / `apiUpdateWorkOrderLabor` /
  `apiDeleteWorkOrderLabor` → `/work-orders/{id}/labor` or
  `/work-orders/{id}/labor/{labor_id}` →
  **work_order_labor**. Entries store actual whole minutes per assigned
  technician; Supervisor+ may manage any assigned technician. Detail billing
  sums minutes, rounds upward once to 30 minutes, and
  applies `$62.50/hour` (rate/charge Admin+ only). Add/update/remove re-fetches
  detail and reopens the Labor card.
- `adminReview.js` (Admin/Owner) → `apiListWorkOrders({status: "review"})` →
  Review cards → `apiGetWorkOrder` → `adminReviewReceipt.js`. The pure receipt
  builder uses authoritative override-aware work-order material lines with
  `+15%`, always appends `[x] Labor Hours` from billed minutes plus `labor_total`
  without another mark-up, and writes the combined Total. `pricingText.js` is
  shared with History so every priced line stays at or below 41 characters. The
  copied text deliberately omits a work-order-number header. Missing prices
  render `NO PRICE`, mark the total incomplete, and disable Close.
- `adminReview.js` (Return to In-Progress) → `apiUpdateWorkOrder` → `PATCH
  /work-orders/{id}` with `{status: "in_progress"}`. The card leaves the Review
  queue while the current receipt remains visible.
- `workOrders.js` (Archive, Admin+ on any expanded live card) → confirm →
  `apiArchiveWorkOrder` → `POST /work-orders/{id}/archive` → Admin+ service and
  route gates → **work_orders.archived_at** set (Closed), then reload the active
  list. `adminReview.js` uses the same endpoint for its receipt-aware Close
  action on Review rows. The row, lines, and transactions remain, and Admin
  Review keeps the receipt open for copying after its queue refresh.
- `workOrders.js` (Owner confirms Re-archive legacy work orders...) →
  `apiArchiveLegacyWorkOrders` → `POST /work-orders/legacy/archive` → Owner-exact
  route and service gates → one bulk **work_orders.archived_at** update for rows
  with `legacy=true AND archived_at IS NULL`. The response reports the actual
  affected count; the view shows it and reloads Work Orders. Already archived
  legacy rows and non-legacy rows are untouched.
- `history.js` (work-order filter names an archived work order) →
  `apiLookupWorkOrder` → `GET /work-orders/lookup?number=` → the one read that
  reports an archived work order → confirm → `apiRestoreWorkOrder` →
  `POST /work-orders/{id}/restore` → **work_orders.archived_at** cleared. This is
  the undo for archive now that there is no re-create path.
- `transactions.js` (scan gate, work-order-number filter) → `apiListWorkOrders`
  with `q` → pick an In-Progress result → batch starts without a status write.
  Picking Assigned and confirming calls the narrow start action and arms the
  batch in place; picking Created asks whether to navigate to the expanded Work
  Order for assignment. Cancel stays at the gate. An unknown
  number is refused in the view; a `POST /transactions/` carrying one is refused
  server-side by `resolve_work_order` (404).
- `workOrders.js` (Add material) → `apiAddWorkOrderItem` →
  `POST /work-orders/{id}/items` → `add_work_order_item` → **items.quantity** ∓
  (dispense mode), **transactions** insert, **work_order_items** line. If stock
  is insufficient, the expected count may become negative, one linked
  **user_requests** recount is inserted atomically, and the card reports
  `Please re-count stock` in red.
- `workOrders.js` (Update qty, Supervisor+) → `apiUpdateWorkOrderItem` →
  `PATCH /work-orders/{id}/items/{wid}` → `update_work_order_item` →
  **work_order_items.quantity** set, **items.quantity** corrected by delta,
  **transactions** insert (reconciling `adjust`); clears a now-too-large override.
- `workOrders.js` (Edit charge) → `apiSetWorkOrderItemBilling` →
  `PATCH /work-orders/{id}/items/{wid}/billing` → `set_work_order_item_billable`
  → **work_order_items.billable_quantity** (no stock change).
- `workOrders.js` (Remove material, Supervisor+) → `apiDeleteWorkOrderItem` →
  `DELETE /work-orders/{id}/items/{wid}` → `delete_work_order_item` →
  **items.quantity** returned, **work_order_items** row delete, **transactions**
  voided (the line's whole contributing set), and source-linked
  **user_requests** resolved.

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
  (+ **work_orders** resolve — 404 if that number was never imported — building
  match enforced).
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

### Tools
- `tools.js` (Add Tool, on the Add Item page) → `apiCreateTool` →
  `POST /tools/` → `create_tool` → **tools** insert (barcode checked
  against live tools only, via a partial unique index).
- `tools.js` (Edit) → `apiUpdateTool` → `PATCH /tools/{id}` →
  `update_tool` → **tools** partial update.
- `tools.js` (Archive) → `apiDeleteTool` → `DELETE /tools/{id}` →
  `delete_tool` → read **tool_transactions** custody aggregate; if clear,
  **tools.archived_at** set (soft delete), otherwise 400.
- `toolCheckout.js` (Check Out) → `apiCheckoutTool` →
  `POST /tools/{id}/checkout` → `checkout_tool` → validate/lock active
  **users** target → **tools.quantity** − (via
  `domain.quantity.apply_delta`, `"dispense"`), **tool_transactions** insert
  (`checkout`). Unknown/archived targets fail before either write.
- `toolReturn.js` (Check In) → `apiReturnTool` → `POST /tools/{id}/return`
  → `return_tool` → **tools.quantity** + (`apply_delta`, `"stock"`, after
  `domain.tools.validate_return` caps it to the user's outstanding
  balance), **tool_transactions** insert (`return`).
- `toolCorrection.js` (Correct Count) → `apiAdjustTool` →
  `POST /tools/{id}/adjust` → `adjust_tool_quantity` → **tools.quantity**
  set (via `apply_delta`, `"adjust"`, signed delta), **tool_transactions**
  insert (`adjust`, `assigned_to_id` NULL, `reason` required).

---

## Per-Table Index (who reads / who writes)

Quick reverse lookup: "which endpoints touch table X?"

| Table | Written by (endpoint #) | Read by (endpoint #) |
|-------|-------------------------|----------------------|
| `users` | 15, 16, 17, 18, 19, 58, 62 | 3, 5, 14, 20, 25–28 (assignee validation), 40, 55 (supervisor name-match), 59–61, 63–64, 68–69 |
| `sessions` | 3 (insert), 4 (delete), 17 (revoke), 19 (cascade), 62 (revoke) | every authenticated request (5 + all gated) |
| `items` | 8, 9, 10, 12, 21, 22, 24, 30, 31, 33, 45, 46 | 6, 7, 20, 26, 36, 63, 68 |
| `item_barcodes` | 8 (check), 11 | 7, 8 (uniqueness) |
| `transactions` | 21, 22, 23, 24, 30, 31, 33, 45 | 20, 24, 26 (self-heal) |
| `work_orders` | 21 (activity status), 28, 29, 40 (fill-blanks), 55 (import f-o-c), 59 (activity status), 67 (start) | 20–21, 25–29, 36, 40, 55, 59–61, 63–64, 67–68 |
| `work_order_items` | 21, 24, 30, 31, 32, 33, 45, 46 | 25, 26, 63 |
| `work_order_technicians` | 28, 40, 55 | 25, 26, 28, 59, 64 |
| `work_order_labor` | 59, 60, 61 | 26, 60, 61, 63 |
| `mass_stages` | 34, 37, 38, 39 | 35, 36 |
| `mass_stage_work_orders` | 40, 41 | 36 |
| `mass_stage_items` | 42, 43, 44, 45, 46 | 36 |
| `tools` | 47, 50, 51, 52, 53, 54 | 48, 49, 52, 53, 54 |
| `tool_transactions` | 52, 53, 54 | 48, 49, 53 (outstanding-balance check) |
| `user_requests` | 9 (price/link auto-resolve), 21 (shortage/unpriced), 24 (recount auto-resolve), 30/45 (unpriced), 69 | 68–69 |

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
`username: str`, `first_name?`, `last_name?`, derived `full_name: str`,
`role: str`, `created_at: datetime`, `archived_at: datetime? = null`. The
profile timestamps support self-service cards; an
authenticated user is normally active, but the nullable archive field keeps
the identity/status contract explicit.

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

**`ItemSearchIndexEntry`** — `GET /items/search-index`: `name`, `barcode`.
This deliberately excludes IDs, quantity, location, notes, price/link,
additional barcodes, and timestamps.

### Users (`schemas/users.py`)

**`UserCreate`** — `POST /users/`: `username`, `first_name`, and `last_name`
(all trimmed/non-blank), `password: str` (≥ 4), `role: str` (must be a recognized
role; whether the *caller* may assign it is checked in the router, not here).

**`UserNameUpdate`** — `PATCH /users/{id}/name`: required trimmed/non-blank
`first_name` + `last_name`, plus optional trimmed/non-blank `username`. The
target may be self or a subordinate; username uniqueness is enforced by the
database and a conflict returns 400.

**`UserRoleUpdate`** — `PATCH /users/{id}/role`: `role: str` (recognized role).
The Admin+ router requires the actor to strictly outrank both the target's
current role and the requested role; a successful service update revokes the
target's sessions.

**`UserResponse`** — `id`, `username`, nullable `first_name`/`last_name`, derived
`full_name`, `role`, `created_at`, `archived_at?` (null = active). Password hash
is never serialized. Legacy NULL names derive to `Name unavailable`.

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
`work_order_number?`, `reason?`, `created_at`, plus immediate-write fields
`recount_required: bool=false` and `item_quantity?` (authoritative post-write
expected stock; may be negative for an insufficient Scan/Stock or Work Orders
Add Item dispense).

**`TransactionHistoryItem`** — each row of `GET /transactions/`: `id`, `item_id`,
`item_barcode`, `item_name`, `user_id?`, `user_name?`, `transaction_type`,
`quantity`, `work_order_number?`, `work_order_id?`, `reason?`, `item_price?`,
`billable_quantity?`, `created_at`. `item_price`/`billable_quantity` are Admin/
Owner-only **and null for work-order rows** (they bill via the line); `work_order_id`
is always present (lets the copy-table resolve the work order). **`TransactionHistoryPage`**:
`items: list[...]`, `total: int`, `page: int`, `page_size: int`.

### User Requests (`schemas/user_requests.py`)

**`UserRequestUpdate`** — `PATCH /user-requests/{id}`: `status:
"open"|"resolved"`, `resolution_note: str?=null` (trimmed; blank becomes null).

**`UserRequestResponse`** — `id`, `request_type`, `status`, `message`, nullable
`item_id`/`item_name`/`item_barcode`/`item_price`/`item_product_link`,
`transaction_id`, `work_order_id`/
`work_order_number`, `created_by_id`/`created_by_name`, generic `details: dict`,
`created_at`, nullable `resolved_at`, `resolved_by_id`/`resolved_by_name`, and
`resolution_note`. The list endpoint returns `list[UserRequestResponse]` and
requires `status=open|resolved` (default `open`).

### Barcodes (`schemas/barcodes.py`)

Request is `multipart/form-data` file upload (FastAPI `UploadFile`), no JSON body.
**`BarcodeDecodeResponse`**: `barcodes: list[BarcodeMatch]`, each `BarcodeMatch =
{ text: str, format: str }`. Empty list = readable image, no symbol (200); an
unreadable image is a 400.

### Work Orders (`schemas/work_orders.py`)

There is no `WorkOrderCreate`: work orders are import-only, so the CSV upload is
the only request that can bring one into existence.

**List query** — `GET /work-orders/`: optional `status`, `service_type`,
`supervisor_id`, `community`, `scheduled_date` (ISO calendar date), `q`, and
`limit`. All filters combine with AND;
`service_type` is an exact trimmed case-insensitive match, `q` is a literal
case-insensitive number substring, and community values are `scholars`,
`centennial`, `commons`, `young_hall`, or `academics`.

**`WorkOrderFilterOptions`** — return of `GET /work-orders/filter-options`:
`service_types: list[str]`, `supervisors: list[{id, name}]`, and
`communities: list[{value, label}]`. Dynamic values come only from live work
orders visible to the caller; the community vocabulary is stable.

**CSV export query** — `GET /work-orders/export`: `scope=all|archived|<live
status>` and `variant=full|client`; optional `service_type`, `supervisor_id`,
`community`, `scheduled_date`, and `q` are applied only to `full`. Invalid values
return 400. The response is a UTF-8 `text/csv` attachment, not a Pydantic
response. `full` leads with the seven import headers and adds status,
assignments, billing totals, and timestamps. `client` remains scope-only and
returns `WORK ORDER`, `MATERIAL TOTAL`, `LABOR TOTAL`, and `RECEIPT`.

**`WorkOrderUpdate`** — `PATCH /work-orders/{id}` (partial, overwrite): `number?`,
`community?`, `building_number?`, `unit_number?`, `description?`, `notes?`, `status?`,
`entry_mode?`, `assigned_to_ids?` (complete replacement; empty clears).
`assigned_to_id?` remains a legacy-compatible singular alternative. ≥ 1 field
required; `status`/`entry_mode`
validated in the service. Live statuses are `created`, `assigned`, `in_progress`,
`on_hold`, `completed`, and `review`; Closed is `archived_at`, not a PATCH value.
Notes are trimmed per-entry text; every in-scope user may append one. The
service supplies timestamp/date/author metadata and preserves the prior log.
`status`, `entry_mode`, supervisor, and technician assignment require
Supervisor+; imported/legacy text metadata and number require Admin+.
`supervisor_id?` may be paired with `expected_supervisor_id?`, including an
explicit NULL expectation for pickup. The expectation is a concurrency
precondition, not a stored field and not an update by itself.

**`WorkOrderLookup`** — return of `GET /work-orders/lookup?number=`: `found: bool`,
`archived: bool`, `id: UUID?`, `number: str?`. Deliberately reports an *archived*
work order (which the list and detail routes hide) so History can offer a restore;
a work order the caller may not see reports `found=false`.

**`LegacyWorkOrderArchivePreview`** — return of Owner-only
`GET /work-orders/legacy/archive`: `count: int`, the number of rows currently
matching `legacy=true AND archived_at IS NULL`.

**`LegacyWorkOrderArchiveResult`** — return of Owner-only
`POST /work-orders/legacy/archive`: `archived: int`, the bulk update's actual
affected-row count (not a replay of the earlier preview).

**`WorkOrderItemCreate`** — `POST .../items`: `item_id: UUID`, `quantity: Decimal`
(> 0). **`WorkOrderItemUpdate`** — `PATCH .../items/{wid}`: `quantity: Decimal`
(> 0). **`WorkOrderItemBilling`** — `PATCH .../items/{wid}/billing`:
`billable_quantity: Decimal?=null` (≥ 0; upper bound vs line quantity enforced in
service).

**`WorkOrderLaborCreate`** — `POST .../labor`: `technician_id: UUID`,
`minutes: int` (> 0). **`WorkOrderLaborUpdate`** — `PATCH
.../labor/{labor_id}`: `minutes: int` (> 0). **`WorkOrderLaborDetail`**:
`id`, `technician_id`, `technician_name`, `minutes`.

**`WorkOrderCard`** — list rows: `id`, `number`, `community?`, `building_number?`,
`unit_number?`, `description?`, `status`, `entry_mode`, `created_by_id?`,
`assigned_to_id?`, `assigned_to_name?` (compatibility primary),
`assigned_to_ids`, `assigned_to_names`, `item_count`, plus the CSV-import
fields `location?`, `output_to?`, `vendor_assignee?`, `service_type?`,
`schedule_date?`, `supervisor_id?`, `supervisor_name?`, and `legacy` (bool).
`WorkOrderUpdate` additionally accepts `supervisor_id` and those text fields.
The service applies the Technician-notes / Supervisor-operations / Admin-metadata
matrix. **`WorkOrderImportResult`** (return of
`POST /work-orders/import`): `total`, `created`, `opened`, `closed`, `supervisors_matched`,
`supervisors_unmatched`, `skipped` (all int). The request is a `multipart/form-data`
CSV file upload (`UploadFile`), no JSON body. **`WorkOrderItemDetail`**:
`id`, `item_id`, `item_name`, `item_barcode`, `item_quantity` (live on-hand),
`quantity`, `mode`, `unit_price?`, `billable_quantity?` (last two Admin/Owner-only).
**`WorkOrderDetail`** = `WorkOrderCard` + `notes: str?` +
`items: list[WorkOrderItemDetail]` + `labor: list[WorkOrderLaborDetail]` +
`labor_minutes` + `labor_billed_minutes` + `materials_total?` (Admin/Owner; Σ
`effective_billable × unit_price`) + `labor_rate?` / `labor_total?`
(Admin/Owner; fixed rate after combined-duration rounding).

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
`assigned_to_id?`, `assigned_to_name?`, `items: list[StageItemDetail]`.
**`StageItemDetail`**: `id`, `item_id`, `item_name`, `item_barcode`,
`item_quantity` (on-hand), `planned_quantity`, `loaded_quantity`,
`returned_quantity`. **`MergedItem`** (per-item rollup for the load screen):
`item_id`, `item_name`, `item_barcode`, `on_hand`, `planned_total`,
`loaded_total`, `returned_total`, `overflow` (loaded beyond planned),
`net_consumed` (loaded − returned), `remaining_to_load` (planned − loaded).

### Tools (`schemas/tools.py`)

**`ToolCreate`** — `POST /tools/`: `barcode: str` (non-blank, trimmed),
`name: str` (non-blank, trimmed), `quantity: Decimal = 1` (≥ 0 — defaults to
1, not 0 like `ItemCreate`, since a tool is usually added because you have
one in hand).

**`ToolUpdate`** — `PATCH /tools/{id}` (partial): `barcode?`, `name?`; ≥ 1
field required, non-blank if sent. `quantity` is NOT editable here — only
via checkout/return.

**`ToolCustodyEntry`**: `user_id`, `user_name`, `quantity` — one user's current
outstanding balance for a tool (net > 0). Login usernames are omitted.

**`ToolResponse`** — any tool return: `id`, `barcode`, `name`, `quantity`,
`created_at`, `custody: list[ToolCustodyEntry] = []`. `custody` is
computed (`services.tools.tool_custody`) and set explicitly by the router,
not an ORM-mapped field — mirrors `ItemResponse.barcodes`.

**`ToolCheckoutCreate`** / **`ToolReturnCreate`** — same shape: `quantity:
Decimal` (> 0), `assigned_to_id: UUID` (required — the custody holder),
`work_order_id: UUID? = null`, `work_order_number: str? = null` (optional,
never required; no find-or-create — stored as-is).

**`ToolAdjustCreate`** — `POST /tools/{id}/adjust` ("Correct Count",
mirrors `CorrectionCreate`): `new_quantity: Decimal` (≥ 0, **absolute**
target — the service computes the signed delta), `reason: str` (non-blank).
No custody holder involved.

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
| `UserNotFoundError` | 404 | user id unknown; tool checkout also uses it when the target is archived (not an active checkout target) |
| `TransactionNotFoundError` | 404 | txn id unknown or already voided |
| `UserRequestNotFoundError` | 404 | user-request id unknown |
| `StageNotFoundError` | 404 | mass-stage id unknown |
| `RoomNotFoundError` | 404 | stage **slot** not found / not in the stage (name retains old "room") |
| `StageItemNotFoundError` | 404 | planned stage item not found (incl. loading an unplanned item) |
| `WorkOrderNotFoundError` | 404 | work order unknown, archived, or **out of visibility scope** (404 hides existence) |
| `WorkOrderAssignmentConflictError` | **409** | a routing patch's `expected_supervisor_id` differs from the freshly locked row; names its current supervisor when assigned |
| `WorkOrderStateError` | 400 | invalid live status/mode, close before Review, or number collision on edit |
| `ToolNotFoundError` | 404 | tool id/barcode unknown or archived |
| `DuplicateToolBarcodeError` | 400 | barcode held by a **live** tool (no archived-conflict/override flow, unlike items) |
| `ToolReturnExceedsCheckedOutError` | 400 | return quantity exceeds that user's current outstanding balance for the tool |
| `ToolHasOutstandingCustodyError` | 400 | archiving a tool while any user still has a positive outstanding balance |
| `DuplicateBarcodeError` | 400 | barcode held by a **live** item (primary or additional) |
| `ArchivedBarcodeConflictError` | **409** | barcode held only by an **archived** item; retry with `override_archived=true` |
| `DuplicateUsernameError` | 400 | username UNIQUE constraint fired |
| `DuplicateBuildingStageError` | 400 | a (community, building) already has an active stage |
| `InvalidStageTransitionError` | 400 | stage status move not `planning→loading→completed` |
| `InvalidAssigneeError` | 400 | work-order assignee missing or not a technician |
| `InvalidSupervisorError` | 400 | work-order routing target missing, archived, or not a Supervisor |
| `ReturnExceedsLoadedError` | 400 | mass-stage return > net loaded |
| `StageStateError` | 400 | mass-stage op illegal for current status (edit after planning, load before loading) |
| `ItemHasTransactionsError` | 400 | hard-deleting an item with txns/stage rows (FK RESTRICT) |
| `UserHasTransactionsError` | 400 | hard-deleting a user referenced by txns (FK RESTRICT) |
| `UserHasCheckedOutToolsError` | 400 | archiving a user before all outstanding tool custody is returned |
| `NegativeQuantityError` | 400 | a strict stock path (Work Order quantity edit, Mass Stage, correction, or reverse) would drive on-hand < 0; Scan/Stock and Work Orders Add Item dispenses deliberately bypass this and open recount requests |
| `NoChangeError` | 400 | correction `new_quantity` equals current (empty audit row) |
| `BillingQuantityError` | 400 | billing override negative, > recorded qty, or targets an `adjust` |
| `TransactionVoidError` | 400 | voiding would drive stock < 0 ("make a correction instead") |
| `UnreadableImageError` | 400 | uploaded bytes are not a decodable image |
| `InvalidCredentialsError` | **401** | bad username/password **or archived user** (indistinguishable) |
| `RoleManagementError` | **403** | actor does not outrank the target user, or a Technician tries to remove a transaction other than their own work-order-linked dispense |

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
- `services.transactions.apply_transaction` and
  `services.work_orders.add_work_order_item` are the intentional exceptions:
  Scan/Stock and Work Orders Add Item `dispense` operations subtract under the
  item-row lock even when the result is negative, then record a recount
  request. Work Order quantity edits and Mass Stage stock-outs continue to call
  strict `apply_delta`.
- `reverse_delta(current, type, qty)` (for void): undo `stock` = dispense, undo
  `dispense` = stock, undo `adjust` = apply negated delta. Same overdraft guard.

### Notes whitelist (`domain/notes_validation.py`)
- `notes` is a flat dict: keys non-blank strings (trimmed); values exactly one of
  `str | int | float | bool`. **`bool` checked before `int`** (bool subclasses int).
  Nested objects/arrays/None/other → `ValueError`.

### Work-order rules (`domain/work_orders.py`)
- Identity: `normalize_number(n) = n.strip().lower()` — mirrors the DB index
  `lower(btrim(number))`. Internal whitespace preserved.
- Stored/live statuses: `created`, `assigned`, `in_progress`, `on_hold`,
  `completed`, `review`; Closed is archive state. `initial_status(assigned_to_id)` and
  `reconcile_assignment_status` align only Created/Assigned with technician
  assignment without rewinding work underway. `status_after_activity` advances
  either pre-work state to In-Progress for material/labor activity but preserves
  On-Hold until an explicit supervisor edit. Modes: `dispense`,
  `retroactive`; `affects_stock(mode)` = `mode == "dispense"`.
- `validate_status` / `validate_mode` → `WorkOrderStateError` on anything else.
- `fill_blank(current, incoming)` = keep non-blank `current`, else `incoming`
  (the find-or-create merge; `is_blank` = None or all-whitespace).
- `can_view_work_order(role, created_by_id, assigned_to_id, assigned_to_ids,
  user_id, supervisor_id)`: admin/owner (and `None` internal role) → all;
  supervisor → unrouted or routed to them; technician → present in the plural assignment set (with the
  singular compatibility fallback).
- Labor constants/rules: `LABOR_RATE = Decimal("62.50")`, increment = 30 minutes;
  `billed_labor_minutes(total)` rounds the combined duration upward once and
  `labor_charge(total)` applies the hourly rate.
- Export constants/rules: scope is `all`, `archived`, or one live status;
  variants are `full` and `client`. `validate_export_scope` /
  `validate_export_variant` reject unknown values with `WorkOrderStateError`.

### Billing (`domain/billing.py`)
- `validate_billable_value(qty, billable)` — None passes (clear); else `0 ≤
  billable ≤ qty`, raise `BillingQuantityError`. Used by **work-order lines**.
- `validate_billable_quantity(type, qty, billable)` — same, plus only `stock`/
  `dispense` rows may be overridden (an `adjust` cannot). Used by **transactions**.

### Fixed-width receipt (`domain/receipt.py`)
- `build_work_order_receipt(materials, labor_billed_minutes, labor_total)` builds
  the client-export receipt with the same 41-character layout as
  `static/adminReviewReceipt.js`: effective material quantity, 15% markup,
  quantity/name truncation, `NO PRICE` / `Total (incomplete)`, an always-present
  labor line, and the grand total. `tests/test_receipt.py` pins the Python output
  against the frontend contract.

### Tool custody (`domain/tools.py`)
- `validate_return(outstanding, requested)` — raises
  `ToolReturnExceedsCheckedOutError` if `requested > outstanding`; the
  caller (`services.tools.return_tool`) computes `outstanding` via the
  same aggregate query `tool_custody` uses, scoped to one user. This is
  the only new arithmetic for tools — the on-hand quantity math itself
  directly reuses `domain.quantity.apply_delta` (checkout = `"dispense"`,
  return = `"stock"`), no tool-specific version exists.

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
- `update_item(id, **_UNSET sentinels)` → lock and partially update only
  non-`_UNSET` fields;
  changing `barcode` runs `_ensure_barcode_free(exclude=self)`; explicit `None`
  clears price/link. When a positive price and a nonblank product link exist, resolve
  every open `missing_item_price` request for the item in this commit.
  `IntegrityError` → `DuplicateBarcodeError`.
- `replace_barcodes(id, codes, override?)` → validate only **added** codes (skip
  retained; reject one equal to the item's own primary); then **diff** the child
  rows (remove dropped, append new, leave retained) to avoid an INSERT-before-DELETE
  collision on the global `UNIQUE(code)`.
- `get_item_by_barcode(code)` → outer-join `item_barcodes`, match primary OR alt,
  **archived excluded**; `ItemNotFoundError` if none. Codes globally unique ⇒ ≤ 1 row.
- `_search_pattern(search)` → trim and escape SQL `%`, `_`, and the escape
  character so search input is always treated as a literal substring.
- `list_items(search?)` → live items, newest first, no pagination. Omitted search
  preserves the full list; nonblank search matches name or primary barcode with
  case-insensitive substring semantics; explicit blank search returns `[]`.
- `list_item_search_index()` → live `(name, barcode)` rows only, ordered by both
  fields; this is the lightweight initial Find Item feed.
- `delete_item(id)` → set `archived_at` (soft delete; never hard — History joins
  need the row). Idempotent.

### `services/notes.py`
- `replace_notes(id, notes)` → assign `item.notes` then **`flag_modified(item,
  "notes")`** — required because SQLAlchemy compares JSONB by identity and would
  otherwise skip the commit. Caller pre-validates via `ItemNotesUpdate`.

### `services/users.py`
- `create_user(username, first_name, last_name, password_hash, role)` → insert;
  `IntegrityError` →
  `DuplicateUsernameError`. (Router hashes the password and checks `can_manage`.)
- `list_users(include_archived?)` → newest first; archived excluded unless asked
  (History "by user" passes True).
- `get_user(id)` → one or `UserNotFoundError` (router inspects role before acting).
- `update_name(id, first_name, last_name, username?)` → explicit display/import-
  identity replacement plus optional login-name correction. `PATCH
  /users/{id}/name` allows self or a manageable subordinate; duplicate username
  raises `DuplicateUsernameError`.
- `update_role(id, role)` → replace the role and delete all target sessions so
  the next login receives matching navigation/permissions. The router owns the
  Admin+ and strict-rank checks.
- `reset_password(id, hash)` → overwrite hash; sessions left intact.
- `archive_user(id, force_return_tools?, performed_by_id?)` → 🔒 lock the user →
  query `tools.user_custody`; raise `UserHasCheckedOutToolsError` while any
  balance remains unless force-return is explicit. The force path calls
  `tools.return_all_for_user` in the same transaction, restoring tool on-hand and
  recording ordinary return rows attributed to the actor. Then set `archived_at`
  and delete all target sessions. Idempotent once archived.
- `restore_user(id)` → clear `archived_at`.
- `delete_user(id)` → hard delete; `IntegrityError` (FK from `transactions.user_id`,
  RESTRICT) → `UserHasTransactionsError`. (API-only; UI uses archive.)

### `services/transactions.py`
- `apply_transaction(item_id, type, qty, user_id, work_order_number, work_order_id)`
  → 🔒 lock item. Stock uses strict `apply_delta`; dispense subtracts directly
  so an insufficient Scan/Stock count can become negative. Insert txn with
  `unit_price = item.price` snapshot → **if `dispense` and `work_order_id`:
  `flush()` then `attach_dispense_line`**. If dispensed quantity exceeded the
  non-negative recorded stock, create one transaction-linked
  `inventory_recount` **user_request** in the same commit. Return dynamic
  `recount_required` and authoritative `item_quantity`. (Stock-in writes no line.)
- `apply_correction(item_id, new_quantity, reason, user_id)` → 🔒 lock → `delta =
  new − current`; `NoChangeError` if 0 → `apply_delta("adjust", delta)` → insert
  `adjust` txn (no `unit_price`) → commit.
- `void_transaction(id, user_id, user_role)` → 🔒 lock txn row;
  `TransactionNotFoundError` if missing/already voided. Supervisor+ passes;
  Technician must own a work-order-linked dispense or receives 403. If
  `affects_stock`: 🔒 lock item, `reverse_delta`
  (`TransactionVoidError` if it would go < 0). If `work_order_id` and type in
  (dispense, adjust): walk the `work_order_items` line back (−qty for dispense, +qty
  for adjust), delete line at ≤ 0. Resolve the linked user request, stamp
  `voided_at`/`voided_by_id`, and commit.
- `set_billable_quantity(id, billable)` → `validate_billable_quantity`; update row
  only (no lock, no stock).

### `services/user_requests.py`
- `create_inventory_recount_request(transaction, item, work_order, user_id,
  recorded_before, dispensed, shortage)` → insert one open, generic
  `inventory_recount` row linked to the source transaction, item, work order, and
  requestor; snapshot disparity facts in JSONB `details` and use the message
  `Please re-count stock`.
- `create_or_update_missing_price_request(item, work_order, user)` → keep one
  open `missing_item_price` request per item and accumulate distinct affected
  work-order numbers in JSONB details. Because `SessionLocal` disables autoflush,
  inspect pending `Session.new` requests before querying persisted rows; this
  prevents one multi-work-order Mass Stage load from staging duplicates before
  its single commit.
- `resolve_missing_price_requests(item, actor)` → resolve every open request of
  that type with `Item price and product link added.`; caller owns the commit.
- `list_user_requests(status)` → filter by the router-validated `open|resolved`
  status, eager-load display relations, newest first.
- `update_user_request(id, status, note, actor_id)` → resolve with timestamp/
  actor/note, or reopen by clearing all resolution fields.
- `resolve_for_transaction(transaction_id, actor_id)` → resolve an open linked
  request with `Source transaction removed.` when its source Scan / Stock
  transaction is voided or its Work Order material line is removed.

### `services/work_orders.py`
**Import-only.** `get_or_create_work_order` is the sole creating path and the CSV
import is its sole caller; every other surface uses `resolve_work_order`, which
attaches to an existing number and refuses an unknown one. Both share the
`_merge_reference` fill-blanks merge.

- `get_or_create_work_order(number, **attrs, assigned_to_id, supervisor_id,
  created_by_id)` → **import path only.** Locked `find_by_number` (case-insensitive,
  includes archived). Archived exists: return untouched so import counts/ignores
  it. Live exists: `_merge_reference` fill-blanks (the `_ATTR_FIELDS` set also
  covers the CSV-import columns `location`/`output_to`/`vendor_assignee`/
  `service_type`/`schedule_date`), set assignee only if currently unassigned and
  `supervisor_id` only if currently unrouted; reconcile Created/Assigned from
  technician assignment. New: insert `assigned` only when a technician is
  supplied, otherwise `created`; supervisor routing is status-neutral and must
  target an active Supervisor. Race on the unique index → rollback, lock the
  winner, and apply the same fill-blank merge.
- `resolve_work_order(number, **attrs, assigned_to_id, supervisor_id)` → attach to
  an existing work order, never create. `find_by_number`; `WorkOrderNotFoundError`
  if unknown ("added by importing the CSV") or archived ("restore it first") — two
  distinct messages because archived is recoverable. On a hit, the same
  `_merge_reference` fill-blanks a reference has always applied. Used by the
  free-text transaction gate and Mass Stage's `add_work_order_to_stage`.
- `lookup_work_order(number, user)` → the scoped row **including an archived one**,
  else `None`. The one read that sees through the archive, so History can offer a
  restore for a number it can see all over the ledger.
- `restore_work_order(id, user)` → clear `archived_at` (scoped; a live work order
  passes through unchanged). The explicit undo for `archive_work_order` and the
  only way an archived work order returns to live views; CSV import ignores it.
  Material lines are still attached, so they return with it.
- `import_work_orders(csv_bytes, user)` → decode `utf-8-sig`, ignore an
  optional leading `sep=,` dialect hint, then `csv.DictReader`
  (quoted multi-line LOCATION handled natively); build a one-shot
  `_supervisor_lookup` keyed by normalized `first_name + last_name` over active
  supervisors. Missing/incomplete names do not enter the lookup; duplicate keys
  become ambiguous (`None`) instead of selecting a row. Per import row:
  `domain.parse_import_row`; skip a blank number; count and ignore an archived
  match; otherwise resolve `supervisor_id` by name-matching the `vendor_assignee`
  (miss/ambiguity stays unassigned) and funnel through `get_or_create_work_order`.
  Tally created/opened/closed/matched/unmatched/skipped. Idempotent for live rows
  (fill-blanks); the existing row is refreshed under `FOR UPDATE`, and imported
  routing fills only a still-NULL `supervisor_id`. Each created/opened row
  commits inside get-or-create.
- `list_work_orders_for_export(user, scope, service_type?, supervisor_id?,
  community?, scheduled_date?, search?)` → validate scope, select live/all, one
  live status, or archived rows, apply the shared predicates and caller scope,
  eager-load export relations, then sort by parsed scheduled date descending.
- `export_work_orders_csv(user, scope, variant, …filters)` → validate variant and
  write one CSV row per selected work order. `full` applies every supplied live
  page filter, uses `EXPORT_HEADERS`, and `_export_row`; `client` intentionally
  ignores the advanced predicates and keeps its scope-only
  `CLIENT_EXPORT_HEADERS`/receipt behavior.
- `list_work_orders(user, status?, service_type?, supervisor_id?, community?,
  scheduled_date?, search?, limit?)` → archived excluded. Every supplied filter
  is combined with AND, then `_scoped_to_user` enforces supervisor
  unassigned/self-routed or technician assignment visibility. Community searches structured/raw
  location text; scheduled date parses leading vendor/ISO dates exactly. Results
  sort by parsed schedule descending, invalid/blank values last, before `limit`.
- `get_work_order_filter_options(user)` → two scoped distinct queries over live
  work orders: normalized service type values and routed supervisor identities;
  returns those plus the stable community choices without exposing `/users` to
  technicians.
- `update_work_order(id, fields, expected_supervisor_id?)` → explicit overwrite
  for ordinary fields plus row-locked append semantics for nonblank `notes`.
  `domain.work_orders.append_note_log` adds Central time, `MMDDYY`, and the
  authenticated `user.full_name`; null does not erase the log.
  `_require_update_permissions` applies notes = Technician+,
  status/mode/routing/assignment = Supervisor+, and imported/legacy
  metadata = Admin+. `assigned_to_ids` synchronizes **work_order_technicians**
  and the singular compatibility mirror. Plural technician assignment reconciles
  Created/Assigned; an
  explicit pre-work rollback is normalized after assignment so those states
  cannot contradict technician presence. The work-order row is refreshed and
  locked before visibility/write checks. Supervisor routing is independent,
  targets only an active Supervisor, and compares an optional expected value;
  a stale value raises the named `WorkOrderAssignmentConflictError` (409).
  Completed/Review preserve `completed_at`; On-Hold/rollback/reopen clear it.
- `start_work_order(id, user)` → scoped-load and lock. Technician+ may move only
  Assigned → In-Progress; In-Progress is an idempotent success. Created, On-Hold,
  Completed, and Review reject the narrow action. Used by Scan/Stock so accepting
  an Assigned-card confirmation does not navigate away.
- `archive_work_order(id)` → require Admin+ in the service, scoped-load any live
  status, then set `archived_at` (Closed). Rows/lines/transactions remain.
- `count_live_legacy_work_orders(user)` → require Owner exactly in the service;
  count only `legacy=true AND archived_at IS NULL` rows for confirmation.
- `archive_live_legacy_work_orders(user)` → require Owner exactly in the
  service; issue one bulk update against the same predicate, set one UTC
  `archived_at` timestamp, commit atomically, and return the affected-row count.
- `get_work_order(id, user)` → scoped load (`WorkOrderNotFoundError` if unknown/
  archived/out-of-scope); **`_heal_orphan_lines`**: sum non-voided linked dispenses
  per item with no line and create the missing `work_order_items` rows (lazy
  backfill, stock-neutral), commit if any healed.
- `add_work_order_labor` / `update_work_order_labor` /
  `delete_work_order_labor` → scoped CRUD over **work_order_labor**. Create
  requires Supervisor+, requires the target to be assigned, and applies
  `status_after_activity`; update/delete also require Supervisor+ and do not
  rewind lifecycle status.
- `attach_dispense_line(work_order_id, item_id, qty, mode, transaction_id, user_id)`
  → the single "show a stock-out on the work order" home. It advances a
  Created/Assigned work order to In-Progress, leaves On-Hold unchanged, then finds the line by
  `(work_order_id, item_id)`: exists → `quantity += qty`, update `transaction_id`,
  promote `retroactive`→`dispense` if a dispense joins; else insert. **Never touches
  `items.quantity`** (caller owns the lock). If the locked item has a NULL or
  non-positive price, it
  also creates/extends the deduplicated missing-price/link User Request.
- `add_work_order_item(id, item_id, qty)` → Technician+ scoped load → 🔒 lock
  item → if mode moves stock, subtract directly and calculate any shortage →
  insert dispense txn (`affects_stock` per mode, `unit_price` snapshot) →
  `attach_dispense_line` → if short, insert a linked `inventory_recount`
  request. Retroactive mode remains stock-neutral. All writes commit together.
- `update_work_order_item(id, wid, qty)` → require Supervisor+; 🔒 lock item; `stock_delta = old − new`;
  if dispense-mode and ≠ 0: `apply_delta("adjust", stock_delta)` + append one
  reconciling `adjust` txn (originals untouched). Set `line.quantity`; **clear
  `billable_quantity` if it now exceeds the new quantity**.
- `set_work_order_item_billable(id, wid, billable)` → `validate_billable_value`
  against `line.quantity`; set `line.billable_quantity`. No stock.
- `delete_work_order_item(id, wid)` → require Supervisor+; 🔒 lock item; if dispense-mode, return
  `line.quantity` to stock (`apply_delta("stock")`); **void the line's whole
  contributing txn set** (located by `(work_order, item)`), resolve requests
  linked to each contributor, then delete the line. Commit the stock return,
  voids, request resolutions, and deletion atomically.
- `reduce_dispense_line(work_order_id, item_id, qty)` → inverse of attach (for a
  Mass Stage return): `quantity −= qty`, delete at ≤ 0. No lock, no stock. No-op if
  no line.

### `services/tools.py`
- `_ensure_barcode_free(code, exclude?)` → checks **live** tools only
  (`Tool.barcode == code AND archived_at IS NULL`); a match raises
  `DuplicateToolBarcodeError`. No archived-conflict/override flow like
  items — an archived tool's barcode is simply free (backed by the
  partial unique index `uq_tools_barcode_live`).
- `create_tool` / `update_tool` / `list_tools` / `get_tool_by_barcode` /
  `get_tool` → mirror the equivalent `services.items` functions (partial
  update via `_UNSET`), minus `location`/`price`/`product_link`.
- `delete_tool(id)` → 🔒 lock a live Tool → query `tool_custody`; raise
  `ToolHasOutstandingCustodyError` while any balance remains, otherwise set
  `archived_at` (soft delete).
- `_custody_query(tool_id)` → the shared aggregate: per `assigned_to_id`,
  `SUM(CASE WHEN transaction_type='checkout' THEN quantity ELSE -quantity
  END)`, filtered to `transaction_type IN ('checkout', 'return')`
  (excludes `adjust` rows, which carry no custody holder), `HAVING net >
  0`. `tool_custody(tool_id)` runs it unscoped (every holder);
  `_outstanding_for_user(tool_id, assigned_to_id)` filters to one user
  (used by `return_tool`'s cap check).
- `user_custody(assigned_to_id)` → inverse aggregate across all tool ledger
  rows (no `Tool.archived_at` filter), returning `(tool_id, name, barcode, net
  quantity)` for positive balances. It is used only by the user-archive guard,
  including protection against legacy custody on an archived tool; the
  frontend card independently inverts the existing live
  `ToolResponse.custody` lists.
- `checkout_tool(tool_id, qty, assigned_to_id, performed_by_id, ...)` →
  🔒 lock and require an active `User` target (`UserNotFoundError` if missing
  or archived) → 🔒 lock `Tool` row → `apply_delta(qty, "dispense", n)` (raises
  `NegativeQuantityError`, reused as-is from `domain.quantity`, if
  insufficient on-hand) → insert `ToolTransaction(type="checkout")` →
  commit.
- `return_tool(tool_id, qty, assigned_to_id, performed_by_id, ...)` →
  🔒 lock `Tool` row → `_outstanding_for_user` → `domain.tools
  .validate_return` (raises `ToolReturnExceedsCheckedOutError`) →
  `apply_delta(qty, "stock", n)` → insert `ToolTransaction(type="return")`
  → commit.
- `adjust_tool_quantity(tool_id, new_quantity, reason, performed_by_id)`
  ("Correct Count") → 🔒 lock `Tool` row → `delta = new_quantity -
  current`; `NoChangeError` if 0 (reused as-is from the items-correction
  vocabulary) → `apply_delta(qty, "adjust", delta)` → insert
  `ToolTransaction(type="adjust", assigned_to_id=None, reason=reason)` →
  commit. The only way to increase a bulk tool's on-hand count (no
  separate stock-in endpoint).

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
- `add_work_order_to_stage(id, number, unit?, assignee?)` → **resolve** the
  `WorkOrder` (via `services.work_orders.resolve_work_order`;
  `WorkOrderNotFoundError` if that number was never imported — a stage plans
  around existing work orders and cannot create one), enforce its
  community/building match the stage, link a `mass_stage_work_orders` slot.
  Planning only.
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
- **Tools (#47–53)** is the reference example of reusing
  `domain.quantity.apply_delta` for a *different* on-hand counter (tool
  custody instead of item stock) rather than writing new arithmetic —
  see `domain/tools.py` and `services/tools.py`.
