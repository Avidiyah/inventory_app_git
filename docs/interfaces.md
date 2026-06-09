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
| `transactions` | list[`Transaction`] | Relationship |

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

`ItemResponse`

| Field | Type |
|---|---|
| `id` | UUID |
| `barcode` | str |
| `name` | str |
| `quantity` | Decimal |
| `location` | str |
| `notes` | dict[str, Any] |
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

- `create_item(db, *, barcode, name, quantity, location) -> Item`
- `list_items(db) -> Sequence[Item]`
- `get_item_by_barcode(db, barcode) -> Item`
- `update_item(db, item_id, *, barcode?, name?, location?) -> Item`
- `delete_item(db, item_id) -> None`

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

### `/barcodes`

| Method | Path | Role | Body | Response |
|---|---|---|---|---|
| POST | `/barcodes/decode` | Authenticated | multipart `file` | `BarcodeDecodeResponse` |

### Root

| Method | Path | Role | Response |
|---|---|---|---|
| GET | `/` | Public | `static/index.html` |
| GET | `/db-test` | Admin+ | `{status, database, user}` |

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

Owns Create Item, Saved Items table, action dropdown, Saved Items scanner mount, and delete cleanup.

### `views/itemEditor.js`

Exports:

- `openItemEditor(item)`
- `closeItemEditor()`
- `setOnSaved(fn)`

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

`mountScanner` accepts upload DOM handles, optional live camera handles, `onItemFound`, `allowCreate`, and `onCreateShortcut`. Upload mode calls `/barcodes/decode`; live mode calls `apiGetItemByBarcode` directly after ZXing decode debounce.

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

