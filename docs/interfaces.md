# Module Interface Definitions

Current contracts for backend modules, frontend modules, and public endpoints. Optional fields are marked with `?`. `UUID` means a UUID string over JSON and `uuid.UUID` in Python.

---

## Backend Layers

```text
domain → services → routers
schemas → routers
models/database → services
```

- `app/domain/`: pure rules and exceptions. No FastAPI, SQLAlchemy, or Pydantic.
- `app/services/`: persistence and orchestration. No FastAPI request/response objects.
- `app/routers/`: HTTP dependencies, schema parsing, service calls, error mapping.
- `app/schemas/`: Pydantic request/response models.

---

## `app/database.py`

Exports:

- `normalize_db_url(url: str) -> str`
- `engine`
- `SessionLocal`
- `Base`
- `test_connection() -> tuple[str, str]`
- `get_db() -> Generator[Session, None, None]`

Inputs:

- `DATABASE_URL`, required.
- `SQL_ECHO`, optional, defaults false.

`get_db()` yields one SQLAlchemy session and always closes it.

---

## `app/models.py`

### `User`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | Primary key |
| `username` | str | Required, unique |
| `password_hash` | str | Required |
| `role` | str | Role vocabulary from `domain.roles` |
| `created_at` | datetime | tz-aware |
| `transactions` | list[`Transaction`] | Relationship |
| `sessions` | list[`AuthSession`] | Relationship, cascade delete-orphan |

### `AuthSession`

| Field | Type | Notes |
|---|---|---|
| `token` | str | Primary key |
| `user_id` | UUID | FK to users, cascade on delete |
| `created_at` | datetime | tz-aware |
| `last_active_at` | datetime | tz-aware |
| `user` | `User` | Relationship |

### `Item`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | Primary key |
| `barcode` | str | Required, unique |
| `name` | str | Required |
| `quantity` | Decimal | Required |
| `location` | str | Required |
| `notes` | dict | JSONB, default `{}` |
| `price` | Decimal? | Per-unit price; redacted below Admin by the router |
| `product_link` | str? | Product URL; redacted below Admin by the router |
| `created_at` | datetime | tz-aware |
| `archived_at` | datetime? | NULL = live; set = archived (soft delete), hidden from `list_items` and barcode lookups |
| `transactions` | list[`Transaction`] | Relationship |
| `alt_barcodes` | list[`ItemBarcode`] | Relationship, cascade delete-orphan; the item's *additional* barcodes |

### `ItemBarcode`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | Primary key |
| `item_id` | UUID | FK to items, `ON DELETE CASCADE` |
| `code` | str | Required, globally unique (an *additional* barcode for the item) |
| `created_at` | datetime | tz-aware |
| `item` | `Item` | Relationship |

### `Transaction`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | Primary key |
| `item_id` | UUID | FK to items |
| `user_id` | UUID? | FK to users, nullable for old rows |
| `transaction_type` | str | `stock`, `dispense`, or `adjust` |
| `quantity` | Decimal | Positive for stock/dispense; signed delta for adjust |
| `work_order_number` | str? | Stock/dispense detail |
| `reason` | str? | Correction detail |
| `created_at` | datetime | tz-aware |
| `voided_at` | datetime? | NULL = live; set = voided (soft delete), hidden from history |
| `voided_by_id` | UUID? | Who voided it (plain UUID, not an FK — hidden audit metadata) |

### `MassStage`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | Primary key |
| `building_name` | str | "Building Name + #" |
| `status` | str | `planning` / `loading` / `completed` |
| `created_by_id` | UUID? | FK to users (plain) |
| `created_at` / `updated_at` | datetime | tz-aware; `updated_at` has ORM `onupdate` |
| `completed_at` | datetime? | Set when status → `completed` |
| `rooms` | list[`MassStageRoom`] | Relationship, cascade delete-orphan, ordered by `sort_order` |

Partial unique index `uq_mass_stages_active_building` = `UNIQUE(building_name) WHERE status <> 'completed'`.

### `MassStageRoom`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | Primary key |
| `stage_id` | UUID | FK to mass_stages, `ON DELETE CASCADE` |
| `room_number` | str | Unique within the stage |
| `work_order_number` | str | The room's single work order |
| `sort_order` | int | Drives load fill / overflow |
| `created_at` | datetime | tz-aware |
| `stage` / `items` | rel. | `items` cascade delete-orphan |

`UniqueConstraint(stage_id, room_number)`.

### `MassStageItem`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | Primary key |
| `room_id` | UUID | FK to mass_stage_rooms, `ON DELETE CASCADE` |
| `item_id` | UUID | FK to items (plain) |
| `planned_quantity` | Decimal | Estimate (not a transaction) |
| `loaded_quantity` | Decimal | Default 0; accrues on load |
| `returned_quantity` | Decimal | Default 0; accrues on return |
| `room` / `item` | rel. | `item` one-way (no backref on `Item`) |

`UniqueConstraint(room_id, item_id)`. Overflow / net-consumed are derived, not stored.

---

## Domain Modules

### `app/domain/roles.py`

Exports:

- `ROLE_OWNER = "owner"`
- `ROLE_ADMIN = "admin"`
- `ROLE_SUPERVISOR = "supervisor"`
- `ROLE_TECHNICIAN = "technician"`
- `ALL_ROLES`
- `is_valid_role(role: str) -> bool`
- `rank(role: str) -> int`
- `role_at_least(role: str, minimum: str) -> bool`
- `can_manage(actor_role: str, target_role: str) -> bool`
- `assignable_roles(actor_role: str) -> list[str]`

Strict ordering: owner > admin > supervisor > technician.

### `app/domain/quantity.py`

`apply_delta(current: Decimal, transaction_type: str, quantity: Decimal) -> Decimal`

- `stock`: adds quantity.
- `dispense`: subtracts quantity and raises `NegativeQuantityError` below zero.
- `adjust`: applies signed delta and raises `NegativeQuantityError` below zero.

`reverse_delta(current: Decimal, transaction_type: str, quantity: Decimal) -> Decimal`

- Undoes a previously-applied transaction (used when voiding). Reuses `apply_delta` with the opposite operation, so it inherits the below-zero guard.

### `app/domain/notes_validation.py`

`validate_notes(notes: dict) -> dict[str, str | int | float | bool]`

Rejects blank keys, non-string keys, nested values, arrays, objects, and unsupported scalar types.

### `app/domain/mass_staging.py`

Pure mass-staging rules (no DB/HTTP), `Decimal`-based. Status vocabulary:
`STATUS_PLANNING` / `STATUS_LOADING` / `STATUS_COMPLETED`, `ALL_STATUSES`,
`ALLOWED_TRANSITIONS` (forward-only). Dataclasses (opaque `key`):
`RoomPlan(key, planned, loaded=0)`, `RoomLoaded(key, loaded, returned=0)`,
`Allocation(key, quantity)`.

- `allocate_load(rooms, quantity) -> list[Allocation]` — fill rooms in order up to
  `planned - loaded`; overflow onto the last room; under-load stops early. Empty
  `rooms` → `ValueError`.
- `allocate_return(rooms, quantity) -> list[Allocation]` — reverse-fill, capped at
  `Σ(loaded - returned)`; over-return → `ReturnExceedsLoadedError`.
- `validate_transition(current, target) -> None` — forward-only; otherwise
  `InvalidStageTransitionError`.
- `can_edit_plan(status) -> bool` (== planning); `can_load(status) -> bool` (== loading).

### `app/domain/errors.py`

Domain exceptions are translated by `routers/_errors.py`. Important errors include:

- `ItemNotFoundError`
- `UserNotFoundError`
- `DuplicateBarcodeError`
- `DuplicateUsernameError`
- `ItemHasTransactionsError`
- `UserHasTransactionsError`
- `NegativeQuantityError`
- `NoChangeError`
- `TransactionNotFoundError`
- `TransactionVoidError`
- `InvalidCredentialsError`
- `RoleManagementError`
- `UnreadableImageError`
- `StageNotFoundError`
- `RoomNotFoundError`
- `StageItemNotFoundError`
- `DuplicateBuildingStageError`
- `InvalidStageTransitionError(current, target)`
- `ReturnExceedsLoadedError(requested, returnable)`
- `StageStateError`

---

## Schemas

### Auth

`LoginRequest`

| Field | Type | Validation |
|---|---|---|
| `username` | str | Required |
| `password` | str | Required |

`MeResponse`

| Field | Type |
|---|---|
| `id` | UUID |
| `username` | str |
| `role` | str |

`PasswordResetRequest`

| Field | Type | Validation |
|---|---|---|
| `password` | str | Minimum configured length |

### Barcodes

`BarcodeMatch`

| Field | Type |
|---|---|
| `text` | str |
| `format` | str |

`BarcodeDecodeResponse`

| Field | Type |
|---|---|
| `barcodes` | list[`BarcodeMatch`] |

### Items

`ItemCreate`

| Field | Type | Validation |
|---|---|---|
| `barcode` | str | Required |
| `name` | str | Required |
| `quantity` | Decimal | Default `0`, must be >= 0 |
| `location` | str | Non-blank after strip |

`ItemUpdate`

| Field | Type | Validation |
|---|---|---|
| `barcode?` | str | Non-blank when present |
| `name?` | str | Non-blank when present |
| `location?` | str | Non-blank when present |

At least one field must be present.

`ItemNotesUpdate`

| Field | Type | Validation |
|---|---|---|
| `notes` | dict[str, scalar] | Delegates to `validate_notes` |

`ItemBarcodesUpdate`

| Field | Type | Validation |
|---|---|---|
| `barcodes` | list[str] | Each trimmed; blanks dropped; in-list duplicates rejected. Full replacement of the item's *additional* codes. |

`ItemResponse`

| Field | Type |
|---|---|
| `id` | UUID |
| `barcode` | str |
| `name` | str |
| `quantity` | Decimal |
| `location` | str |
| `notes` | dict[str, Any] |
| `barcodes` | list[str] — the item's *additional* codes (set by `_item_response` from `alt_barcodes`) |
| `price` | Decimal? (null below Admin) |
| `product_link` | str? (null below Admin) |
| `created_at` | datetime |

`price` / `product_link` are redacted to `null` for callers below Admin by `routers/items._item_response`, which wraps every item-returning route.

### Users

`UserCreate`

| Field | Type | Validation |
|---|---|---|
| `username` | str | Non-blank after strip |
| `password` | str | Minimum configured length |
| `role` | str | Must be recognized role |

`UserResponse`

| Field | Type |
|---|---|
| `id` | UUID |
| `username` | str |
| `role` | str |
| `created_at` | datetime |

### Transactions

`TransactionCreate`

| Field | Type | Validation |
|---|---|---|
| `item_id` | UUID | Required |
| `transaction_type` | `"stock" | "dispense"` | Required |
| `quantity` | Decimal | Must be > 0 |
| `work_order_number?` | str | Optional |

`CorrectionCreate`

| Field | Type | Validation |
|---|---|---|
| `item_id` | UUID | Required |
| `new_quantity` | Decimal | Must be >= 0 |
| `reason` | str | Non-blank after strip |

`TransactionResponse`

| Field | Type |
|---|---|
| `id` | UUID |
| `item_id` | UUID |
| `user_id` | UUID? |
| `transaction_type` | str |
| `quantity` | Decimal |
| `work_order_number` | str? |
| `reason` | str? |
| `created_at` | datetime |

`TransactionHistoryItem` adds `item_barcode`, `item_name`, `username`, and `item_price` (per-unit; `None` unless requester is Admin/Owner — the frontend multiplies it by `quantity` for the Price column).

`TransactionHistoryPage`

| Field | Type |
|---|---|
| `items` | list[`TransactionHistoryItem`] |
| `total` | int |
| `page` | int |
| `page_size` | int |

### Mass Stages

Requests (`schemas/mass_stages.py`): `MassStageCreate {building_name}`,
`MassStageUpdate {building_name?, status?}` (≥1), `RoomCreate {room_number,
work_order_number}`, `RoomUpdate {room_number?, work_order_number?}` (≥1),
`StageItemCreate {item_id, planned_quantity>0}`, `StageItemUpdate
{planned_quantity>0}`, `LoadRequest {item_id, quantity>0}`, `ReturnRequest
{item_id, quantity>0}`.

Responses (built by the router from ORM, not `from_attributes`):
- `StageItemDetail {id, item_id, item_name, item_barcode, item_quantity (on-hand), planned_quantity, loaded_quantity, returned_quantity}`
- `RoomDetail {id, room_number, work_order_number, sort_order, items[]}`
- `MassStageDetail {id, building_name, status, created_at, rooms[], merged_items[]}`
- `MassStageSummary {id, building_name, status, room_count, item_count, created_at}`
- `MergedItem {item_id, item_name, item_barcode, on_hand, planned_total, loaded_total, returned_total, overflow, net_consumed, remaining_to_load}`

---

## Services

### `services/auth.py`

- `hash_password(password: str) -> str`
- `verify_password(password: str, stored: str) -> bool`
- `authenticate(db, *, username, password) -> User`
- `create_session(db, user: User) -> str`
- `get_active_session_user(db, token: str) -> User | None`
- `delete_session(db, token: str) -> None`

### `services/barcodes.py`

- `decode_image(data: bytes) -> list[BarcodeMatch]`

Opens bytes with Pillow, decodes with pyzbar, filters to supported formats, dedupes `(text, format)`, and raises `UnreadableImageError` for unreadable image data.

### `services/items.py`

- `create_item(db, *, barcode, name, quantity, location, price?, product_link?) -> Item`
- `list_items(db) -> Sequence[Item]`
- `get_item_by_barcode(db, barcode) -> Item` — resolves against the primary `barcode` OR any `item_barcodes.code`; archived items excluded.
- `update_item(db, item_id, *, barcode?, name?, location?, price?, product_link?) -> Item`
- `replace_barcodes(db, item_id, codes) -> Item` — wholesale-replace the item's *additional* barcodes; rejects codes already in use (cross-table) or equal to the item's primary via `DuplicateBarcodeError`.
- `delete_item(db, item_id) -> None` — soft delete (sets `archived_at`).
- `_barcode_in_use(db, code, *, exclude_item_id?) -> bool` — internal cross-table uniqueness check (primary + additional).

### `services/notes.py`

- `replace_notes(db, item_id, notes: dict) -> Item`

### `services/transactions.py`

- `apply_transaction(db, *, item_id, transaction_type, quantity, user_id, work_order_number) -> Transaction`
- `apply_correction(db, *, item_id, new_quantity, reason, user_id) -> Transaction`
- `void_transaction(db, *, transaction_id, user_id) -> None`

All three lock the item row with `SELECT ... FOR UPDATE`. `void_transaction` soft-deletes the row (sets `voided_at` / `voided_by_id`) and reverses its stock effect via `domain.quantity.reverse_delta`; raises `TransactionNotFoundError` (unknown/already-voided) or `TransactionVoidError` (reversal would go negative).

### `services/history.py`

- `list_history(db, *, item_id?, user_id?, work_order_number?, page, page_size, include_price=False) -> TransactionHistoryPage`

Filters combine with AND, and voided rows are excluded (`voided_at IS NULL`). `work_order_number` is a case-sensitive escaped substring match. `include_price` (set from the requester's role by the router) carries the per-unit `item_price` into each row only for Admin/Owner.

### `services/users.py`

- `create_user(db, *, username, password_hash, role) -> User`
- `list_users(db) -> Sequence[User]`
- `get_user(db, user_id) -> User`
- `reset_password(db, user_id, password_hash) -> None`
- `delete_user(db, user_id) -> None`

### `services/mass_staging.py`

Planning CRUD + the two stock-touching actions. Raises the mass-staging domain
errors; gates editability via `domain.mass_staging.can_edit_plan` / `can_load`.

- `create_stage(db, *, building_name, created_by_id) -> MassStage` — one-active-per-building guard (`DuplicateBuildingStageError`).
- `list_stages(db, *, status?) -> Sequence[MassStage]`; `get_stage(db, stage_id) -> MassStage` (eager-loads rooms→items→item).
- `update_stage(db, stage_id, *, building_name?, status?) -> MassStage` — status change via `validate_transition`; stamps `completed_at`.
- `delete_stage(db, stage_id) -> None` (cascades rooms/items).
- `reuse_stage(db, stage_id, *, created_by_id) -> MassStage` — clone a *completed* stage into a fresh `planning` one (rooms copied with work orders cleared to `""`, no items); `StageStateError` if not completed, `DuplicateBuildingStageError` if the building is already active. `update_stage` also blocks the `→ loading` transition while any room's work order is blank (`StageStateError`).
- `add_room` / `update_room` / `delete_room` (planning only).
- `add_item(db, stage_id, room_id, *, item_id, planned_quantity) -> MassStageItem` — upsert by `(room, item)`; `update_item` / `delete_item` by `stage_item_id`.
- `load_item(db, stage_id, *, item_id, quantity, user_id) -> None` — under the item `FOR UPDATE`, allocate (`allocate_load`) and write one `dispense` per room slice + bump `loaded_quantity`; rolls back on `NegativeQuantityError`.
- `return_item(db, stage_id, *, item_id, quantity) -> None` — under the item lock, `allocate_return`, bump `returned_quantity`, add stock back with **no** transaction row.

---

## Routers

### `/auth`

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/auth/login` | `LoginRequest` | `MeResponse` + cookie |
| POST | `/auth/logout` | none | 204 |
| GET | `/auth/me` | none | `MeResponse` |

### `/items`

| Method | Path | Role | Body | Response |
|---|---|---|---|---|
| POST | `/items/` | Admin+ | `ItemCreate` | `ItemResponse` |
| GET | `/items/` | Authenticated | none | list[`ItemResponse`] (price/link null below Admin) |
| GET | `/items/{barcode}` | Authenticated | none | `ItemResponse` (price/link null below Admin) |
| PATCH | `/items/{item_id}` | Admin+ | `ItemUpdate` | `ItemResponse` |
| PATCH | `/items/{item_id}/notes` | Supervisor+ | `ItemNotesUpdate` | `ItemResponse` |
| PATCH | `/items/{item_id}/barcodes` | Admin+ | `ItemBarcodesUpdate` | `ItemResponse` |
| DELETE | `/items/{item_id}` | Admin+ | none | 204 |

### `/users`

| Method | Path | Rule | Body | Response |
|---|---|---|---|---|
| POST | `/users/` | actor outranks requested role | `UserCreate` | `UserResponse` |
| GET | `/users/` | Supervisor+ | none | list[`UserResponse`] |
| POST | `/users/{user_id}/reset-password` | actor outranks target | `PasswordResetRequest` | 204 |
| DELETE | `/users/{user_id}` | actor outranks target | none | 204 |

### `/transactions`

| Method | Path | Role | Body/query | Response |
|---|---|---|---|---|
| POST | `/transactions/` | Authenticated; `dispense` any role, `stock` Supervisor+ | `TransactionCreate` | `TransactionResponse` |
| POST | `/transactions/adjust` | Admin+ | `CorrectionCreate` | `TransactionResponse` |
| DELETE | `/transactions/{transaction_id}` | Supervisor+ | path id | `204` |
| GET | `/transactions/` | Supervisor+ | query filters | `TransactionHistoryPage` |

### `/mass-stages`

All routes Supervisor+. CRUD for stages/rooms/items plus the stock-touching
`/load` and `/return`. See `services/mass_staging.py` and `docs/mass-staging/`.

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/mass-stages/` | `MassStageCreate` | `MassStageSummary` |
| GET | `/mass-stages/` (`?status=`) | — | list[`MassStageSummary`] |
| GET | `/mass-stages/{id}` | — | `MassStageDetail` |
| PATCH | `/mass-stages/{id}` | `MassStageUpdate` | `MassStageSummary` |
| DELETE | `/mass-stages/{id}` | — | 204 |
| POST | `/mass-stages/{id}/rooms` | `RoomCreate` | `RoomDetail` |
| PATCH / DELETE | `…/rooms/{room_id}` | `RoomUpdate` / — | `RoomDetail` / 204 |
| POST | `…/rooms/{room_id}/items` | `StageItemCreate` | `StageItemDetail` |
| PATCH / DELETE | `…/items/{stage_item_id}` | `StageItemUpdate` / — | `StageItemDetail` / 204 |
| POST | `/mass-stages/{id}/load` | `LoadRequest` | `MergedItem` |
| POST | `/mass-stages/{id}/return` | `ReturnRequest` | `MergedItem` |
| POST | `/mass-stages/{id}/reuse` | — | `MassStageSummary` (fresh planning copy) |

### `/barcodes`

| Method | Path | Role | Body | Response |
|---|---|---|---|---|
| POST | `/barcodes/decode` | Authenticated | multipart `file` | `BarcodeDecodeResponse` |

### Root

| Method | Path | Role | Response |
|---|---|---|---|
| GET | `/` | Public | SPA shell, assembled by `read_root` from `shell-head.html` + `static/pages/*.html` + `shell-tail.html` (see `main.py::SHELL_PARTS`) |
| GET | `/db-test` | Admin+ | `{status, database, user}` |

The `/` document is built at request time by concatenating per-page HTML
fragments; the browser receives one complete document, so the Frozen DOM
contract (all page markup present on boot) is unchanged from the former
single `index.html`.

---

## Frontend Foundation Modules

### `static/api.js`

Fetch wrapper module. Sends credentials for cookie-authenticated requests. On non-2xx responses, throws `{ status, detail }`; returns `null` for 204.

Exports:

- `setUnauthorizedHandler(fn)`
- `apiLogin({ username, password })`
- `apiLogout()`
- `apiMe()`
- `apiListItems()`
- `apiCreateItem({ barcode, name, location, quantity })`
- `apiUpdateItem(itemId, patch)`
- `apiDeleteItem(itemId)`
- `apiUpdateNotes(itemId, notesDict)`
- `apiUpdateBarcodes(itemId, codes)`
- `apiGetItemByBarcode(barcode)`
- `apiListUsers()`
- `apiCreateUser({ username, password, role })`
- `apiResetPassword(userId, password)`
- `apiDeleteUser(userId)`
- `apiDecodeBarcode(file)`
- `apiListTransactions({ page, pageSize, itemId, userId, workOrder })`
- `apiCreateTransaction(payload)`
- `apiCreateCorrection({ itemId, newQuantity, reason })`
- `apiVoidTransaction(transactionId)`
- Mass staging: `apiListStages(status?)`, `apiCreateStage(buildingName)`, `apiGetStage(id)`, `apiUpdateStage(id, patch)`, `apiDeleteStage(id)`, `apiAddRoom(id, {roomNumber, workOrderNumber})`, `apiUpdateRoom(id, roomId, patch)`, `apiDeleteRoom(id, roomId)`, `apiAddStageItem(id, roomId, {itemId, plannedQuantity})`, `apiUpdateStageItem(id, roomId, stageItemId, {plannedQuantity})`, `apiDeleteStageItem(id, roomId, stageItemId)`, `apiLoadStageItem(id, {itemId, quantity})`, `apiReturnStageItem(id, {itemId, quantity})`, `apiReuseStage(id)`

### `static/state.js`

Owns client state:

- Items cache.
- Users cache.
- Current user.
- Selected transaction item.
- Editing notes/item/correction ids.
- History state: `{ tab, itemId, itemLabel, userId, workOrder, page, totalPages }`.

Exports getters/setters and `HISTORY_PAGE_SIZE = 10`.

### `static/roles.js`

Client mirror of the role hierarchy for UI visibility only:

- `roleAtLeast(role, minimum)`
- `canManage(actorRole, targetRole)`
- `assignableRoles(actorRole)`

### `static/dom.js`

- `setMessage(el, text, type)`
- `getNoteValueRaw(wrapper)`
- `confirmDialog(message) -> Promise<boolean>` — drives the shared `#scan-confirm-overlay` modal (focus-trapped); used by scan-and-go (`views/transactions.js`) and the mass-stage load action (`views/massStage.js`)

### `static/format.js`

- `escapeHtml`
- `formatNoteValue`
- `detectNoteType`
- `formatMoney` — formats a number/string amount as USD currency (`""` for null/blank/non-numeric)
- `safeHttpUrl` — returns the URL only if it is an `http(s)` link, else `""` (guards the product-link href)
- `formatError`
- `friendlyError` — maps a thrown `{ status, detail }` (or a network failure) to a short, field-friendly message (connection / session / permission / insufficient-stock), falling back to `formatError`

---

## Frontend Views

### `views/auth.js`

Exports:

- `initAuth()`

Owns login screen, logout, `/auth/me` boot flow, role visibility, and global 401 handling.

### `views/nav.js`

Exports:

- `showPage(pageName)`
- `canAccessPage(role, pageName)`
- `applyRoleVisibility(role)`

Also handles scanner lifecycle when entering/leaving scanner pages.

### `views/items.js`

Exports:

- `loadItems()`
- `renderItems()`
- `setOnDeletedSelectedItem(fn)`
- `itemsScanner`

Owns Create Item, Saved Items table, action dropdown, Saved Items scanner mount, and delete cleanup. `renderItems()` builds the `#items-table` header (`#items-thead-row`) and body together from a per-role column model, so column set/order can never desync. Technicians get a decluttered, quantity/location-first table (no Created / Actions columns); Supervisor+ keep the original order plus the Admin-only Price/Link columns.

### `views/massStage.js`

Exports:

- `loadStages()`

Owns the Mass Stage page (Supervisor+). Lists stages as expandable `<details>`
cards (lazy-loading detail on expand) and dispatches by status: a planning
renderer (rooms editor, Next Room, add-item search, Save Mass Stage) and a
loading/completed renderer (the `merged_items` load list with Staged / Unused
materials / Mark Completed). All actions go through one delegated `click` + `input`
handler on `#mass-stage-list`; mutations re-fetch + re-render the stage, preserving
open rooms. Uses `dom.confirmDialog` for the load confirmation.

### `views/itemEditor.js`

Exports:

- `openItemEditor(item)`
- `closeItemEditor()`
- `setOnSaved(fn)`

### `views/addBarcode.js`

Exports:

- `openAddBarcode(barcode)` — opens the Find Item "add a scanned code to an existing item" panel; searches items by name and appends the code to the chosen item's additional barcodes via `apiUpdateBarcodes` (re-fetching the item fresh first, since that PATCH is a wholesale replace).
- `closeAddBarcode()`
- `setOnSaved(fn)`

Wired from `views/items.js` as the Saved Items scanner's `onAddBarcode` callback; the shortcut button is rendered by `views/scan.js` on a 404 (Admin+).

### `views/correction.js`

Exports:

- `openCorrection(item)`
- `closeCorrection()`
- `getEditingCorrectionItemId()`
- `setOnSaved(fn)`

### `views/notes.js`

Exports:

- `openNotesEditor(itemId, itemName)`
- `closeNotesEditor()`
- `renderNotesSummary(notes)`
- `setOnSaved(fn)`

### `views/users.js`

Exports:

- `loadUsers()`
- `populateUserSelects()`

Owns create user, role dropdown population, user table, reset-password actions, and delete actions.

### `views/transactions.js`

Exports:

- `loadTxnItems()`
- `openTransactionForm(itemId, itemName, action, meta?)` — `meta` is an optional `{ quantity, location }` used to render the post-scan confirmation (large name + on-hand + location)
- `closeTransactionForm()`
- `focusItemByBarcode(item)`
- `setOnTransactionSaved(fn)`

**DOM contract note (UX overhaul, Phase 2):** `#transaction-type` is now a hidden
`<input>` (was a `<select>`) driven by a two-button segmented control
(`.seg-btn.seg-stock` / `.seg-btn.seg-dispense`). The submitted `transaction_type`
value contract is unchanged (`stock` | `dispense`). Worker tables (`#items-table`,
`#txn-items-table`, and `#history-table` in Phase 3) carry `class="stack-table"` and
their render functions emit `data-label` / `data-primary` per `<td>` so CSS can collapse
them to stacked cards below 640px.

**DOM contract note (scan-and-go confirm, 2026-06-10):** the per-scan confirmation
modal is an app-level overlay `#scan-confirm-overlay` (`.modal-overlay` → `.modal-box`)
holding `#scan-confirm-title`, `#scan-confirm-yes`, and `#scan-confirm-no`. It is
toggled via the `hidden` attribute (relies on the global `[hidden]{display:none!important}`)
and driven by `confirmScan(message)` in `views/transactions.js`. The scan-and-go
defaults also changed: `#scango-type` defaults to `dispense` (segmented `active` on
`.scango-seg-dispense`) and `#scango-quantity` defaults to `1`. A Supervisor+-only
opt-in button `#scango-advanced-toggle` reveals the direction toggle + manual table
(`#txn-items-section`) / form (`#transaction-section`); by default Supervisor+ get
the streamlined dispense-only flow (driven by the `supervisorAdvanced` flag in
`views/transactions.js`).

**Mass-staging additions (Phase 7–8):** `confirmScan(message)` now delegates to the
shared `dom.confirmDialog` (same `#scan-confirm-overlay`). The work-order gate gained a
Supervisor+ **by-room** picker (`#wo-gate-byroom-toggle` → `#wo-gate-building` /
`#wo-gate-room`): it lists active mass stages and fills `#wo-gate-input` with the chosen
room's work order, then runs the unchanged `startBatch()` — a plain dispense, not added
to the stage.

### `views/history.js`

Exports:

- `setHistoryTab(tab)`
- `loadHistory()`
- `renderHistory(data)`

Owns item/user/work-order filters, pagination, and copy-to-clipboard export.

### `views/scan.js`

Exports:

- `mountScanner(opts)`
- `txnScanner`
- `resetScan()`
- `autoStartTxnScan()` — starts the Transaction-page camera only if permission is already granted (never prompts); injected into `transactions.js` via `setScanAutostarter` (wired in `main.js`).

`mountScanner` accepts upload DOM handles, optional live camera handles, `onItemFound`, `allowCreate`, `onCreateShortcut`, and `onAddBarcode`. On a 404 (Admin+ only) the chooser renders the Create-Item shortcut (`onCreateShortcut`) and/or the Add-Barcode shortcut (`onAddBarcode`); each is shown only if its callback is supplied. Upload mode calls `/barcodes/decode`; live mode calls `apiGetItemByBarcode` directly after ZXing decode debounce. The returned object adds `autoStartIfPermitted()` (prompt-free auto-start), backed by the new `BarcodeDecoder.permissionGranted()` static.

---

## Barcode Scanner Contract

Upload mode:

```text
file input → apiDecodeBarcode(file) → 0/1/many result branch
```

Live mode:

```text
Scan button → getUserMedia → ZXing decode → 5-of-10 debounce → apiGetItemByBarcode(text)
```

Supported live DOM handles per page:

- `*-scan-video`
- `*-scan-scan-btn`
- `*-scan-upload-btn`
- `*-scan-torch-btn`
- `*-scan-aimbox`

`*` is `txn` or `items`.

Tracks are stopped on page leave, tab hidden, reset, cancel, or accepted scan.

