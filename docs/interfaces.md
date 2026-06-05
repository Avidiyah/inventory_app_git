# Module Interface Definitions

> Defines the input and output contract for every module and program in the system. Use this when adding features, refactoring, or wiring modules together — it tells you exactly what each unit expects to receive and what it promises to return, without reading implementation code.
> 
> **Notation:** Optional fields are marked `?`. Union types use `|`. Python types are used for backend; JS types for frontend. `UUID` always means a string in UUID v4 format.

---

## Table of Contents

1. [Backend — `app/database.py`](https://claude.ai/chat/f44b0f9e-2dc0-4b5d-8ed4-1914b68d09e8#1-backend--appdatabasepy)
2. [Backend — `app/models.py`](https://claude.ai/chat/f44b0f9e-2dc0-4b5d-8ed4-1914b68d09e8#2-backend--appmodelspy)
3. [Backend — `app/schemas.py`](https://claude.ai/chat/f44b0f9e-2dc0-4b5d-8ed4-1914b68d09e8#3-backend--appschemaspyy)
4. [Backend — `app/routers/items.py`](https://claude.ai/chat/f44b0f9e-2dc0-4b5d-8ed4-1914b68d09e8#4-backend--approutersitemspy)
5. [Backend — `app/routers/users.py`](https://claude.ai/chat/f44b0f9e-2dc0-4b5d-8ed4-1914b68d09e8#5-backend--approutersuserspy)
6. [Backend — `app/routers/transactions.py`](https://claude.ai/chat/f44b0f9e-2dc0-4b5d-8ed4-1914b68d09e8#6-backend--approuterstransactionspy)
7. [Backend — `app/main.py`](https://claude.ai/chat/f44b0f9e-2dc0-4b5d-8ed4-1914b68d09e8#7-backend--appmainpy)
8. [Alembic — `alembic/env.py`](https://claude.ai/chat/f44b0f9e-2dc0-4b5d-8ed4-1914b68d09e8#8-alembic--alembicenvpy)
9. [Frontend — `static/script.js` — Data & Network](https://claude.ai/chat/f44b0f9e-2dc0-4b5d-8ed4-1914b68d09e8#9-frontend--staticscriptjs--data--network)
10. [Frontend — `static/script.js` — UI Rendering](https://claude.ai/chat/f44b0f9e-2dc0-4b5d-8ed4-1914b68d09e8#10-frontend--staticscriptjs--ui-rendering)
11. [Frontend — `static/script.js` — State](https://claude.ai/chat/f44b0f9e-2dc0-4b5d-8ed4-1914b68d09e8#11-frontend--staticscriptjs--state)
12. [Frontend — `static/index.html`](https://claude.ai/chat/f44b0f9e-2dc0-4b5d-8ed4-1914b68d09e8#12-frontend--staticindexhtml)
13. [Frontend — `static/styles.css`](https://claude.ai/chat/f44b0f9e-2dc0-4b5d-8ed4-1914b68d09e8#13-frontend--staticstylescss)

---

## 1. Backend — `app/database.py`

### Purpose

Initialises the SQLAlchemy engine, session factory, and declarative base. Provides the FastAPI session dependency and a connectivity test helper.

---

### `engine` (module-level)

**Input:** `DATABASE_URL` environment variable (read via `os.getenv`) **Output:** `sqlalchemy.engine.Engine` — synchronous engine with `echo=True` and `connect_timeout=5` **Side effects:** Raises `RuntimeError` at import time if `DATABASE_URL` is not set.

---

### `SessionLocal` (module-level)

**Input:** None (configured from `engine`) **Output:** `sqlalchemy.orm.sessionmaker` factory — produces `Session` objects with `autoflush=False`, `autocommit=False`

---

### `Base` (module-level)

**Input:** None **Output:** `DeclarativeBase` subclass — all ORM models must inherit from this

---

### `test_connection() -> tuple[str, str]`

**Input:** None (uses module-level `engine`) **Output:** `(database_name: str, user_name: str)` — result of `SELECT current_database(), current_user` **Raises:** Any SQLAlchemy connection error if the DB is unreachable

---

### `get_db() -> Generator[Session, None, None]`

**Input:** None **Output:** Yields a `Session` instance **Side effects:** Always calls `db.close()` in `finally` — safe for FastAPI `Depends()`

---

## 2. Backend — `app/models.py`

### Purpose

Defines the three ORM models. Each is a pure SQLAlchemy mapping — no business logic lives here.

---

### `User`

|Attribute|Type|Notes|
|---|---|---|
|`id`|`UUID`|PK, auto-generated|
|`username`|`str`|NOT NULL, UNIQUE|
|`created_at`|`datetime` (tz-aware)|Auto-set on insert|
|`transactions`|`list[Transaction]`|Back-populated relationship|

---

### `Item`

|Attribute|Type|Notes|
|---|---|---|
|`id`|`UUID`|PK, auto-generated|
|`barcode`|`str`|NOT NULL, UNIQUE|
|`name`|`str`|NOT NULL|
|`quantity`|`Decimal`|NOT NULL, default `0`|
|`location`|`str`|NOT NULL|
|`notes`|`dict`|JSONB, NOT NULL, default `{}`|
|`created_at`|`datetime` (tz-aware)|Auto-set on insert|
|`transactions`|`list[Transaction]`|Back-populated relationship|

---

### `Transaction`

|Attribute|Type|Notes|
|---|---|---|
|`id`|`UUID`|PK, auto-generated|
|`item_id`|`UUID`|FK → `items.id`, NOT NULL|
|`user_id`|`UUID?`|FK → `users.id`, nullable|
|`transaction_type`|`str`|`"stock"` or `"dispense"`|
|`quantity`|`Decimal`|NOT NULL|
|`work_order_number`|`str?`|nullable|
|`created_at`|`datetime` (tz-aware)|Auto-set on insert|
|`item`|`Item`|Back-populated relationship|
|`user`|`User?`|Back-populated relationship|

---

## 3. Backend — `app/schemas.py`

### Purpose

Pydantic v2 models for request validation and response serialisation. All response schemas use `model_config = {"from_attributes": True}`.

---

### `ItemCreate` (request)

|Field|Type|Validation|
|---|---|---|
|`barcode`|`str`|required|
|`name`|`str`|required|
|`quantity`|`Decimal`|default `0`; must be ≥ 0|
|`location`|`str`|stripped; must be non-blank|

---

### `ItemResponse` (response)

|Field|Type|
|---|---|
|`id`|`UUID`|
|`barcode`|`str`|
|`name`|`str`|
|`quantity`|`Decimal`|
|`location`|`str`|
|`notes`|`dict[str, Any]`|
|`created_at`|`datetime`|

---

### `ItemNotesUpdate` (request)

|Field|Type|Validation|
|---|---|---|
|`notes`|`dict[str, Any]`|Keys: non-blank strings. Values: `str`, `int`, `float`, or `bool` only. No nested types.|

---

### `TransactionCreate` (request)

|Field|Type|Validation|
|---|---|---|
|`item_id`|`UUID`|required|
|`transaction_type`|`Literal["stock", "dispense"]`|required|
|`quantity`|`Decimal`|must be > 0|
|`work_order_number`|`str?`|optional|
|`user_id`|`UUID?`|optional|

---

### `TransactionResponse` (response)

|Field|Type|
|---|---|
|`id`|`UUID`|
|`item_id`|`UUID`|
|`user_id`|`UUID?`|
|`transaction_type`|`str`|
|`quantity`|`Decimal`|
|`work_order_number`|`str?`|
|`created_at`|`datetime`|

---

### `TransactionHistoryItem` (response — enriched row)

|Field|Type|
|---|---|
|`id`|`UUID`|
|`item_id`|`UUID`|
|`item_barcode`|`str`|
|`item_name`|`str`|
|`user_id`|`UUID?`|
|`username`|`str?`|
|`transaction_type`|`str`|
|`quantity`|`Decimal`|
|`work_order_number`|`str?`|
|`created_at`|`datetime`|

---

### `TransactionHistoryPage` (response — paginated wrapper)

|Field|Type|
|---|---|
|`items`|`list[TransactionHistoryItem]`|
|`total`|`int`|
|`page`|`int`|
|`page_size`|`int`|

---

### `UserCreate` (request)

|Field|Type|Validation|
|---|---|---|
|`username`|`str`|stripped; must be non-blank|

---

### `UserResponse` (response)

|Field|Type|
|---|---|
|`id`|`UUID`|
|`username`|`str`|
|`created_at`|`datetime`|

---

### `_validate_notes(notes: dict) -> dict` (internal helper)

**Input:** Raw dict from request **Output:** Cleaned `dict[str, str | int | float | bool]` **Raises:** `ValueError` for invalid key types, blank keys, or unsupported value types **Used by:** `ItemNotesUpdate.validate_notes` field validator

---

## 4. Backend — `app/routers/items.py`

Router prefix: `/items` — Tag: `items`

---

### `POST /items/` → `ItemResponse` (201)

**Input:** `ItemCreate` (request body), `Session` (injected) **Output:** `ItemResponse` of the created item **Errors:**

- `400` — barcode already exists (`IntegrityError` caught, rolled back)

**Side effects:** Inserts one row into `items`.

---

### `GET /items/` → `list[ItemResponse]` (200)

**Input:** `Session` (injected) **Output:** All items ordered by `created_at DESC` **Errors:** None

---

### `GET /items/{barcode}` → `ItemResponse` (200)

**Input:** `barcode: str` (path param), `Session` (injected) **Output:** Single item matching that barcode **Errors:**

- `404` — no item with that barcode

---

### `PATCH /items/{item_id}/notes` → `ItemResponse` (200)

**Auth:** Supervisor or above (`require_min_role(roles.ROLE_SUPERVISOR)`). Notes are an operational field, distinct from the Admin-only structural edits on `PATCH /items/{item_id}`.

**Input:** `item_id: UUID` (path param), `ItemNotesUpdate` (request body), `Session` (injected) **Output:** Updated `ItemResponse` **Errors:**

- `404` — item not found

**Side effects:** Replaces the entire `notes` JSONB field; calls `flag_modified` to force SQLAlchemy change detection.

---

### `DELETE /items/{item_id}` → `204 No Content`

**Input:** `item_id: UUID` (path param), `Session` (injected) **Output:** Empty body **Errors:**

- `404` — item not found

**Side effects:** Deletes the item row. Associated transactions remain (no explicit CASCADE defined).

---

## 5. Backend — `app/routers/users.py`

Router prefix: `/users` — Tag: `users`

---

### `POST /users/` → `UserResponse` (201)

**Input:** `UserCreate` (request body), `Session` (injected) **Output:** `UserResponse` of the created user **Errors:**

- `400` — username already exists

**Side effects:** Inserts one row into `users`.

---

### `GET /users/` → `list[UserResponse]` (200)

**Input:** `Session` (injected) **Output:** All users ordered by `created_at DESC` **Errors:** None

---

### `DELETE /users/{user_id}` → `204 No Content`

**Input:** `user_id: UUID` (path param), `Session` (injected) **Output:** Empty body **Errors:**

- `404` — user not found
- `400` — user has existing transactions (`IntegrityError` caught)

**Side effects:** Deletes the user row if no transactions reference it.

---

## 6. Backend — `app/routers/transactions.py`

Router prefix: `/transactions` — Tag: `transactions`

---

### `POST /transactions/` → `TransactionResponse` (201)

**Input:** `TransactionCreate` (request body), `Session` (injected) **Output:** `TransactionResponse` of the created transaction **Errors:**

- `404` — item not found
- `400` — dispense would make quantity negative

**Side effects:**

- Acquires `SELECT ... FOR UPDATE` lock on the item row
- Mutates `item.quantity` (adds for `stock`, subtracts for `dispense`)
- Inserts one row into `transactions`
- Both changes committed in a single transaction

---

### `GET /transactions/` → `TransactionHistoryPage` (200)

**Input:**

|Param|Type|Default|
|---|---|---|
|`item_id`|`UUID?` (query)|None|
|`user_id`|`UUID?` (query)|None|
|`work_order_number`|`str?` (query)|None|
|`page`|`int ≥ 1` (query)|`1`|
|`page_size`|`int` 1–100 (query)|`10`|

**Output:** `TransactionHistoryPage` — paginated list of enriched transaction rows **Query logic:** Joins `transactions → items` (inner) and `transactions → users` (outer). Filters by `item_id`, `user_id`, and `work_order_number` when provided (combined with AND). `work_order_number` is a case-sensitive substring match (`LIKE %value%`) with `%` and `_` escaped; empty / whitespace-only values are treated as "no filter". Orders by `created_at DESC`.

---

## 7. Backend — `app/main.py`

### Purpose

Assembles the FastAPI application: registers routers, mounts static files, defines root and health routes.

---

### `app` (module-level)

**Input:** None **Output:** `FastAPI` instance titled `"Inventory Management API"` **Routers registered:** `items.router`, `transactions.router`, `users.router` **Static mount:** `/static` → `./static/` directory

---

### `GET /` → `FileResponse`

**Input:** None **Output:** `static/index.html` served as a file response

---

### `GET /db-test` → `dict`

**Input:** None (calls `test_connection()`) **Output:**

```json
{ "status": "ok", "database": "<db_name>", "user": "<db_user>" }
```

**Errors:** Propagates any connection error from `test_connection()`

---

## 8. Alembic — `alembic/env.py`

### Purpose

Configures Alembic migration execution. Connects to the database and runs pending migrations against `Base.metadata`.

---

### Inputs

|Source|Value|
|---|---|
|Environment|`DATABASE_URL` (via `python-dotenv`)|
|`alembic.ini`|`sqlalchemy.url` (intentionally blank — overridden by env var in `run_migrations_online`)|
|`app/models.py`|`Base.metadata` — target schema for autogenerate|

---

### `run_migrations_offline() -> None`

**Input:** URL from `alembic.ini` `sqlalchemy.url` key **Output:** Migration SQL emitted to stdout (no live DB connection required)

---

### `run_migrations_online() -> None`

**Input:** `DATABASE_URL` env var; uses `NullPool` (no connection pooling) **Output:** Migrations applied to the live database **Side effects:** DDL statements executed and committed

---

## 9. Frontend — `static/script.js` — Data & Network

These functions are responsible for all API communication and cache population.

---

### `loadItems() → Promise<void>`

**Input:** None **Network:** `GET /items/` **Output:** Populates `itemsCache: Item[]`; calls `renderItems()` **Errors:** Logs to console on failure; does not surface to UI

---

### `loadUsers() → Promise<void>`

**Input:** None **Network:** `GET /users/` **Output:** Populates `usersCache: User[]`; renders users table; calls `populateUserSelects()` **Errors:** Logs to console

---

### `loadTxnItems() → Promise<void>`

**Input:** None **Network:** `GET /items/` (independent fetch — does not use `itemsCache`) **Output:** Renders the transaction page items table **Errors:** Logs to console

---

### `loadHistory() → Promise<void>`

**Input:** Reads from `historyState` (`tab`, `itemId`, `userId`, `page`) **Network:** `GET /transactions/?page=&page_size=10[&item_id=][&user_id=]` **Output:** Calls `renderHistory(data)` **Guard:** Returns early without fetching if `tab === "item"` and `itemId` is null, or `tab === "user"` and `userId` is null

---

### `createItemBtn` click handler

**Input:** DOM values — `barcode`, `name`, `location`, `quantity` **Validates:** barcode non-empty, name non-empty, location non-empty (client-side only) **Network:** `POST /items/` with `{ barcode, name, location, quantity: float }` **Output on success:** Success message; clears form; calls `loadItems()` **Output on error:** Error message from `data.detail`

---

### `createUserBtn` click handler

**Input:** DOM value — `username` **Validates:** username non-empty (client-side) **Network:** `POST /users/` with `{ username }` **Output on success:** Success message; clears input; calls `loadUsers()`

---

### `saveTransactionBtn` click handler

**Input:** `selectedItemId`, DOM values — `transaction-type`, `transaction-user`, `transaction-quantity`, `transaction-work-order` **Validates:** item selected, quantity > 0, user selected **Network:** `POST /transactions/` with `{ item_id, transaction_type, quantity, user_id, work_order_number? }` **Output on success:** Success message; calls `loadTxnItems()` + `loadItems()`; closes form after 1.2s

---

### `notesSaveBtn` click handler

**Input:** `editingNotesItemId`, all `.note-row` DOM elements **Validates:** duplicate keys (client-side); number fields non-empty and finite **Network:** `PATCH /items/{editingNotesItemId}/notes` with `{ notes: { ... } }` **Output on success:** "Notes saved." message; calls `loadItems()`; closes editor after 1s

---

### Delete item handler (`itemsTbody` delegation)

**Input:** `item.id`, `item.name` from button `data-*` **Validates:** `confirm()` dialog **Network:** `DELETE /items/{item_id}` **Output on success:** Calls `loadItems()`; closes transaction form / notes editor if that item was open

---

### Delete user handler (`usersTbody` delegation)

**Input:** `user.id`, `user.name` from button `data-*` **Validates:** `confirm()` dialog **Network:** `DELETE /users/{user_id}` **Output on success:** Calls `loadUsers()` **Output on error:** `alert(detail)`

---

### `historyItemLookupBtn` click handler

**Input:** DOM value — `history-item-barcode` **Network:** `GET /items/{barcode}` to resolve barcode → item ID **Output on success:** Sets `historyState.itemId`; calls `loadHistory()` **Output on error:** Clears `historyState.itemId`; hides results; shows error message

---

### `historyUserSelect` change handler

**Input:** Selected `user.id` **Output:** Sets `historyState.userId`; resets page to 1; calls `loadHistory()`

---

## 10. Frontend — `static/script.js` — UI Rendering

These functions take data and produce DOM output. They do not make network calls.

---

### `renderItems() → void`

**Input:** `itemsCache`, `itemsSearch.value` **Output:** Rebuilds `#items-tbody` — filters by name/barcode if search term is non-empty; shows empty-state row if no results

---

### `renderNotesSummary(notes: object) → string`

**Input:** Notes dict from an item **Output:** HTML string — comma-separated `key: value` pairs, or `<span class="empty">—</span>` if empty

---

### `populateUserSelects() → void`

**Input:** `usersCache` **Output:** Rebuilds option lists in `#transaction-user` and `#history-user-select`; preserves previously selected value if still valid; disables save button + shows warning if no users exist

---

### `openNotesEditor(itemId: string, itemName: string) → void`

**Input:** Item ID and display name **Output:** Populates `#notes-rows` from `itemsCache`; shows `#notes-editor-section`; scrolls to it **Guard:** Returns early if item not found in cache

---

### `closeNotesEditor() → void`

**Input:** None **Output:** Hides `#notes-editor-section`; clears rows; resets `editingNotesItemId`

---

### `addNoteRow(key?: string, type?: string, value?: any) → void`

**Input:** Optional pre-fill values (key, type, value) **Output:** Appends a `.note-row` div to `#notes-rows` containing key input, type selector, dynamic value input, and remove button **Behaviour:** Type selector change event calls `renderNoteValueInput` to swap the value input

---

### `renderNoteValueInput(wrapper: Element, type: string, currentValue: any) → void`

**Input:** Wrapper element, type string (`"string"`, `"number"`, `"boolean"`), current value **Output:** Replaces wrapper contents with the appropriate input element:

- `"boolean"` → `<select>` with `true`/`false` options
- `"number"` → `<input type="number" step="any">`
- `"string"` → `<input type="text">`

---

### `openTransactionForm(itemId: string, itemName: string, action: string) → void`

**Input:** Item ID, display name, action (`"stock"` or `"dispense"`) **Output:** Pre-fills and shows `#transaction-section`; scrolls to it; focuses quantity field **Guard:** Disables save button if `usersCache` is empty

---

### `closeTransactionForm() → void`

**Input:** None **Output:** Hides `#transaction-section`; resets `selectedItemId`

---

### `renderHistory(data: TransactionHistoryPage) → void`

**Input:** `TransactionHistoryPage` JSON response **Output:** Rebuilds `#history-tbody`; updates pagination controls (`historyPageInfo`, prev/next disabled state); shows `#history-results`

---

### `setHistoryTab(tab: "all" | "item" | "user") → void`

**Input:** Tab name **Output:** Updates active tab button; shows correct sub-panel; resets page to 1; calls `loadHistory()`

---

### `showPage(pageName: "entry" | "transaction" | "history") → void`

**Input:** Page name **Output:** Toggles `.active` class on `.page` divs and `.nav-btn` buttons; triggers `loadTxnItems()` or `loadHistory()` as appropriate

---

### `setMessage(element: HTMLElement, text: string, type: string) → void`

**Input:** A message paragraph element, text content, CSS class (`"success"`, `"error"`, or `""`) **Output:** Sets `textContent` and `className` on the element

---

### `formatError(detail: any, fallback: string) → string`

**Input:** API `detail` value (either a string or a Pydantic validation error array), fallback string **Output:** Human-readable error string — joins `.msg` fields if array, otherwise returns `detail` or `fallback`

---

### `escapeHtml(value: any) → string`

**Input:** Any value **Output:** String with `&`, `<`, `>`, `"`, `'` escaped to HTML entities. Returns `""` for `null`/`undefined`.

---

### Helper utilities

|Function|Input|Output|
|---|---|---|
|`formatNoteValue(v)`|Note value (any)|String — booleans become `"true"`/`"false"`|
|`detectNoteType(v)`|Note value (any)|`"boolean"`, `"number"`, or `"string"`|
|`getNoteValueRaw(wrapper)`|`.note-value-wrapper` element|Raw string value from the inner input/select|

---

## 11. Frontend — `static/script.js` — State

These are the module-level variables that carry state across user interactions. No function should mutate these outside of the rules below.

|Variable|Type|Set by|Read by|
|---|---|---|---|
|`itemsCache`|`Item[]`|`loadItems()`|`renderItems()`, `openNotesEditor()`, delete handlers|
|`usersCache`|`User[]`|`loadUsers()`|`populateUserSelects()`, transaction save handler|
|`selectedItemId`|`string \| null`|`openTransactionForm()`, `closeTransactionForm()`|Transaction save handler, item delete handler|
|`editingNotesItemId`|`string \| null`|`openNotesEditor()`, `closeNotesEditor()`|Notes save handler, item delete handler|
|`historyState.tab`|`"all"\|"item"\|"user"`|`setHistoryTab()`|`loadHistory()`|
|`historyState.itemId`|`string \| null`|barcode lookup handler|`loadHistory()`|
|`historyState.userId`|`string \| null`|user select handler|`loadHistory()`|
|`historyState.page`|`number`|pagination handlers, `setHistoryTab()`|`loadHistory()`, `renderHistory()`|
|`historyState.totalPages`|`number`|`renderHistory()`|Pagination button disabled state|
|`HISTORY_PAGE_SIZE`|`10` (constant)|—|`loadHistory()`, `renderHistory()`|

---

## 12. Frontend — `static/index.html`

### Purpose

Defines the full DOM structure. All elements are present on load; visibility is controlled by `hidden` attribute and `.active`/`.page` CSS classes toggled by the frontend view modules under `static/views/`.

### Element ID contract

The following IDs are required by the frontend view modules. Renaming or removing any of these will break the corresponding JS behaviour.

**Navigation**

- `#main-nav` — nav container with `.nav-btn[data-page]` children

**Create Item page**

- `#create-item-page`, `#create-item-section`
- `#barcode`, `#name`, `#location`, `#quantity`, `#create-item-btn`, `#create-item-message`

**Saved Items page**

- `#saved-items-page`, `#items-section`, `#items-search`, `#items-tbody`
- `#notes-editor-section`, `#notes-editor-selected`, `#notes-rows`, `#notes-add-row-btn`, `#notes-save-btn`, `#notes-cancel-btn`, `#notes-message`
- `#item-editor-section`, `#item-editor-selected`, `#item-editor-barcode`, `#item-editor-name`, `#item-editor-location`, `#item-editor-save-btn`, `#item-editor-cancel-btn`, `#item-editor-message`
- `#correction-section`, `#correction-selected`, `#correction-current`, `#correction-new-quantity`, `#correction-reason`, `#correction-save-btn`, `#correction-cancel-btn`, `#correction-message`

**Create User page**

- `#create-user-page`, `#create-user-section`
- `#username`, `#create-user-btn`, `#create-user-message`

**Saved Users page**

- `#saved-users-page`, `#users-section`, `#users-tbody`

**Transaction page**

- `#txn-scan-section`, `#txn-scan-input`, `#txn-scan-chooser`, `#txn-scan-message` (barcode scanning — see addendum L)
- `#transaction-page`, `#txn-items-section`, `#transaction-section`
- `#txn-items-tbody`, `#transaction-selected`, `#transaction-type`, `#transaction-user`
- `#transaction-quantity`, `#transaction-work-order`
- `#save-transaction-btn`, `#cancel-transaction-btn`, `#transaction-message`

**History page**

- `#history-page`, `#history-section`
- `#history-tabs` — container with `.sub-tab-btn[data-tab]` children
- `#history-all-panel`, `#history-item-panel`, `#history-user-panel`
- `#history-item-barcode`, `#history-item-lookup-btn`, `#history-item-message`
- `#history-user-select`, `#history-user-message`
- `#history-results`, `#history-table`, `#history-tbody`
- `#history-pagination`, `#history-prev-btn`, `#history-next-btn`, `#history-page-info`

### Script dependency

`/static/main.js` (ES module) must be loaded at the end of `<body>` via `<script type="module" src="/static/main.js"></script>`. It is the composition root: it imports the view modules (which wire their own event listeners on module load) and triggers the initial loaders (`showPage("create-item")`, `setHistoryTab("all")`, `loadItems()`, `loadUsers()`).

---

## 13. Frontend — `static/styles.css`

### Purpose

Purely presentational. Has no logic contract with JS, but the following CSS classes are applied and/or depended upon by the view modules under `static/views/` and `index.html`:

| Class                                                                               | Applied by                                        | Effect                                    |
| ----------------------------------------------------------------------------------- | ------------------------------------------------- | ----------------------------------------- |
| `.page`                                                                             | `index.html`                                      | `display: none` by default                |
| `.page.active`                                                                      | `showPage()` in JS                                | `display: block` — makes the page visible |
| `.nav-btn.active`                                                                   | `showPage()` in JS                                | Blue highlight on active nav button       |
| `.sub-tab-btn.active`                                                               | `setHistoryTab()` in JS                           | Blue underline on active sub-tab          |
| `.success`                                                                          | `setMessage()` in JS                              | Green text on feedback paragraphs         |
| `.error`                                                                            | `setMessage()` in JS                              | Red text on feedback paragraphs           |
| `.type-badge.stock`                                                                 | `renderHistory()` in JS                           | Green badge                               |
| `.type-badge.dispense`                                                              | `renderHistory()` in JS                           | Amber badge                               |
| `.type-badge.adjust`                                                                | `renderHistory()` in JS                           | Blue badge (correction / quantity adjust) |
| `.note-row`                                                                         | `addNoteRow()` in JS                              | Grid layout for key/type/value/remove     |
| `.note-key`, `.note-type`, `.note-value`, `.note-value-wrapper`, `.note-remove-btn` | `addNoteRow()` / `renderNoteValueInput()`         | Queried by class within note row logic    |
| `.edit-notes-btn`                                                                   | `index.html` (static) / `renderItems()` (dynamic) | Triggers notes editor on click            |
| `.correct-item-btn`                                                                 | `renderItems()` (dynamic)                         | Triggers correction (quantity adjust) on click |
| `.delete-btn`, `.delete-user-btn`                                                   | `renderItems()`, `loadUsers()`                    | Triggers delete confirmation on click     |
| `.stock-btn`, `.dispense-btn`                                                       | `loadTxnItems()`                                  | Triggers transaction form open            |
| `.empty`                                                                            | `renderNotesSummary()` in JS                      | Grey `—` placeholder                      |

---

# Modularization Addendum (v4)

This addendum documents the modules introduced when `app/schemas.py`, `app/routers/*.py`, and `static/script.js` were decomposed. It supersedes sections 3–6 and 9–11 for any conflicting detail. **Route paths, HTTP methods, status codes, response schemas, and element IDs are unchanged** — only file ownership has moved.

## A. Backend — `app/domain/` (pure, framework-free)

### `app/domain/errors.py`
**Exports:** `DomainError` (base), `ItemNotFoundError`, `UserNotFoundError`, `DuplicateBarcodeError`, `DuplicateUsernameError`, `UserHasTransactionsError`, `NegativeQuantityError(current: Decimal, requested: Decimal)`.
**Must NOT know about:** FastAPI, SQLAlchemy, Pydantic, HTTP.

### `app/domain/quantity.py`
**`apply_delta(current: Decimal, transaction_type: Literal["stock","dispense"], quantity: Decimal) -> Decimal`**
- `stock` → `current + quantity`; `dispense` → `current - quantity`.
- Raises `NegativeQuantityError` if a dispense would go below zero.

**Must NOT know about:** SQLAlchemy, FastAPI, models, sessions.

### `app/domain/notes_validation.py`
**`validate_notes(notes: dict) -> dict[str, str|int|float|bool]`** — same accept/reject behaviour as the legacy `_validate_notes` (interfaces.md §3); raises `ValueError`.
**Must NOT know about:** Pydantic, FastAPI, SQLAlchemy.

---

## B. Backend — `app/schemas/` (package)

Schema fields, types, and validation rules are **unchanged from §3**; only file location has moved. Importers may continue to use `from app.schemas import X` — the package `__init__.py` re-exports every symbol.

| Module | Owns |
|---|---|
| `app/schemas/items.py` | `ItemCreate`, `ItemResponse`, `ItemNotesUpdate` (delegates value-validation to `app.domain.notes_validation.validate_notes`) |
| `app/schemas/transactions.py` | `TransactionCreate`, `TransactionResponse`, `TransactionHistoryItem`, `TransactionHistoryPage` |
| `app/schemas/users.py` | `UserCreate`, `UserResponse` |

**Must NOT know about:** SQLAlchemy, FastAPI, network layer.

---

## C. Backend — `app/services/` (persistence + orchestration, no FastAPI)

### `app/services/items.py`
- `create_item(db, *, barcode, name, quantity, location) -> Item` — raises `DuplicateBarcodeError`.
- `list_items(db) -> Sequence[Item]` — ordered `created_at DESC`.
- `get_item_by_barcode(db, barcode) -> Item` — raises `ItemNotFoundError`.
- `delete_item(db, item_id) -> None` — raises `ItemNotFoundError`.

### `app/services/notes.py`
- `replace_notes(db, item_id, notes: dict) -> Item` — raises `ItemNotFoundError`; internally calls `flag_modified(item, "notes")`.

### `app/services/transactions.py`
- `apply_transaction(db, *, item_id, transaction_type, quantity, user_id, work_order_number) -> Transaction`.
- Acquires `SELECT … FOR UPDATE` on the item row; mutates `item.quantity` via `app.domain.quantity.apply_delta`; inserts the transaction; commits as one unit.
- Raises `ItemNotFoundError`, `NegativeQuantityError`.

### `app/services/history.py`
- `list_history(db, *, item_id, user_id, page, page_size) -> TransactionHistoryPage`.
- Joins `transactions → items` (inner) and `transactions → users` (outer); filters; orders `created_at DESC`.

### `app/services/users.py`
- `create_user(db, *, username) -> User` — raises `DuplicateUsernameError`.
- `list_users(db) -> Sequence[User]` — ordered `created_at DESC`.
- `delete_user(db, user_id) -> None` — raises `UserNotFoundError` or `UserHasTransactionsError`.

**All services MUST NOT know about:** FastAPI, `HTTPException`, request/response objects.

---

## D. Backend — `app/routers/_errors.py`

**`to_http(exc: DomainError) -> HTTPException`** — maps domain exceptions to status codes:

| Domain exception | HTTP status |
|---|---|
| `ItemNotFoundError`, `UserNotFoundError` | 404 |
| `DuplicateBarcodeError`, `DuplicateUsernameError`, `UserHasTransactionsError`, `NegativeQuantityError` | 400 |

`NegativeQuantityError` always serialises with detail `"Insufficient stock to dispense."`; all others use the exception's string form. **Must NOT know about:** SQLAlchemy, service internals.

---

## E. Backend — Routers (now thin)

Sections 4–6 above are still authoritative for paths, methods, status codes, and response schemas. The only change is that every handler now delegates to a service and translates `DomainError` via `to_http`:

- `app/routers/items.py` → `services.items` (CRUD), `services.notes` (PATCH notes)
- `app/routers/transactions.py` → `services.transactions` (POST), `services.history` (GET)
- `app/routers/users.py` → `services.users`

---

## F. Frontend — Foundation modules

### `static/state.js`
**Exports:** `getItems()/setItems(arr)`, `getUsers()/setUsers(arr)`, `getSelectedItemId()/setSelectedItemId(id)`, `getEditingNotesItemId()/setEditingNotesItemId(id)`, `getHistoryState()` (shallow copy) / `updateHistoryState(patch)`, constant `HISTORY_PAGE_SIZE = 10`.
Default `historyState`: `{ tab: "all", itemId: null, userId: null, page: 1, totalPages: 1 }`.
**Must NOT know about:** DOM, fetch.

### `static/api.js`
One async function per backend endpoint. Returns parsed JSON on success; on non-2xx throws `{ status, detail }`; returns `null` for 204.
Exports: `apiListItems`, `apiCreateItem({barcode,name,location,quantity})`, `apiDeleteItem(itemId)`, `apiUpdateNotes(itemId, notesDict)`, `apiGetItemByBarcode(barcode)`, `apiListUsers`, `apiCreateUser({username})`, `apiDeleteUser(userId)`, `apiListTransactions({page,pageSize,itemId,userId})`, `apiCreateTransaction(payload)`, `apiDecodeBarcode(file)` (multipart upload → `{barcodes:[...]}`).
**Must NOT know about:** DOM, state.

### `static/format.js`
Pure exports: `escapeHtml`, `formatNoteValue`, `detectNoteType`, `formatError` — semantics unchanged from §10.
**Must NOT know about:** DOM, fetch, state.

### `static/dom.js`
Exports: `setMessage(el, text, type)`, `getNoteValueRaw(wrapper)` — semantics unchanged from §10.
**Must NOT know about:** fetch, state, business logic.

---

## G. Frontend — Views (`static/views/`)

Each view module owns DOM queries against a specific section of `index.html`, wires its event listeners on module load, and exports the functions other modules need. Side-effect imports (e.g. `import "./views/history.js"`) ensure handlers register.

### `static/views/nav.js`
- **Exports:** `showPage(pageName)` — toggles `.active` on `.page` and `.nav-btn`; derives the page wrapper ID as `` `${pageName}-page` ``; triggers per-page side effects on activation: `saved-items → loadItems()`, `saved-users → loadUsers()`, `transaction → loadTxnItems()`, `history → loadHistory()`.
- **Accepted `pageName` values:** `"create-item" | "saved-items" | "create-user" | "saved-users" | "transaction" | "history"`.
- **Wires:** click on `#main-nav` `.nav-btn`.

### `static/views/items.js`
- **Exports:** `loadItems()`, `renderItems()`, `setOnDeletedSelectedItem(fn)` (callback for when the currently-selected transaction item is deleted).
- **Wires:** `#create-item-btn`, `#items-search`, delegated clicks on `#items-tbody` (delete + edit-notes).
- **Imports:** `views/notes.js` for `openNotesEditor`, `renderNotesSummary`, `setOnSaved` (registers `loadItems` as the post-notes-save refresh).

### `static/views/notes.js`
- **Exports:** `openNotesEditor(itemId, itemName)`, `closeNotesEditor()`, `renderNotesSummary(notes)`, `setOnSaved(fn)`.
- **Wires:** `#notes-add-row-btn`, `#notes-cancel-btn`, `#notes-save-btn`.
- Internal helpers `addNoteRow` and `renderNoteValueInput` are not exported.

### `static/views/users.js`
- **Exports:** `loadUsers()`, `populateUserSelects()`.
- **Wires:** `#create-user-btn`, delegated clicks on `#users-tbody`.

### `static/views/transactions.js`
- **Exports:** `loadTxnItems()`, `openTransactionForm(itemId, itemName, action)`, `closeTransactionForm()`, `focusItemByBarcode(item)` (narrow the table to the scanned item + open its form), `setOnTransactionSaved(fn)` (post-save reset hook, injected by `main.js`).
- **Wires:** delegated clicks on `#txn-items-tbody`, `#cancel-transaction-btn`, `#save-transaction-btn`.
- **Imports:** `views/items.js → loadItems` to refresh the items list after a transaction. Does **not** import `views/scan.js` (the dependency is one-way: scan → transactions).

### `static/views/scan.js`
- **Exports:** `resetScan()` (clears the scan input/message/chooser).
- **Wires:** `change` on `#txn-scan-input`, delegated clicks on `#txn-scan-chooser`.
- **Imports:** `api.js → apiDecodeBarcode, apiGetItemByBarcode`; `views/transactions.js → focusItemByBarcode`; `state.js → getRole`; `roles.js → roleAtLeast`. Navigates to the Create Item page by clicking the existing nav button (no `nav.js` import), keeping the module graph acyclic.

### `static/views/history.js`
- **Exports:** `loadHistory()`, `renderHistory(data)`, `setHistoryTab(tab)`.
- **Wires:** delegated clicks on `#history-tabs`, `#history-item-lookup-btn`, `#history-user-select` change, `#history-prev-btn`, `#history-next-btn`.

**All views MUST NOT know about:** other views' internal DOM details — cross-view interaction goes through exported functions and the state store.

---

## H. Frontend — `static/main.js` (composition root)

Imports each view module (loading registers its event handlers); registers `closeTransactionForm` as the "selected item deleted" callback on the items view; then runs the initial sequence:

```js
showPage("create-item");
setHistoryTab("all");
loadItems();
loadUsers();
```

**Must NOT know about:** any view's internal implementation.

---

## I. Network function → owning module map (replaces §9)

| Network function | Lives in |
|---|---|
| `apiListItems`, `apiCreateItem`, `apiDeleteItem`, `apiUpdateNotes`, `apiGetItemByBarcode`, `apiListUsers`, `apiCreateUser`, `apiDeleteUser`, `apiListTransactions`, `apiCreateTransaction` | `static/api.js` |
| `loadItems`, create-item handler, delete-item handler | `static/views/items.js` |
| `loadUsers`, create-user handler, delete-user handler | `static/views/users.js` |
| `loadTxnItems`, save-transaction handler | `static/views/transactions.js` |
| `loadHistory`, barcode-lookup handler, user-select handler | `static/views/history.js` |
| notes save handler | `static/views/notes.js` |

## J. UI render function → owning module map (replaces §10)

| Render function | Lives in |
|---|---|
| `renderItems`, items table | `static/views/items.js` |
| `renderNotesSummary`, `openNotesEditor`, `closeNotesEditor`, `addNoteRow`, `renderNoteValueInput` | `static/views/notes.js` |
| users table, `populateUserSelects` | `static/views/users.js` |
| transaction items table, `openTransactionForm`, `closeTransactionForm` | `static/views/transactions.js` |
| `renderHistory`, `setHistoryTab` | `static/views/history.js` |
| `showPage` | `static/views/nav.js` |
| `setMessage`, `getNoteValueRaw` | `static/dom.js` |
| `escapeHtml`, `formatNoteValue`, `detectNoteType`, `formatError` | `static/format.js` |

## K. State ownership (replaces §11)

All state listed in §11 now lives behind `static/state.js` getters/setters. The Set-by / Read-by table in §11 still applies — only the access mechanism has changed (e.g. `itemsCache` → `getItems()` / `setItems(arr)`; `historyState.page = n` → `updateHistoryState({ page: n })`).

---

## L. Barcode scanning (feature addendum)

End-to-end contract for the Transaction-page barcode scanner. Decoding is **backend** (`pyzbar` over native `zbar`), in memory, never persisted.

### Backend — `POST /barcodes/decode`
Router prefix `/barcodes`, tag `barcodes`. Gated **supervisor or above**.
- **Input:** `multipart/form-data`, one `file: UploadFile`.
- **Output:** `BarcodeDecodeResponse` → `{ "barcodes": [ { "text": str, "format": str } ] }`. `format` ∈ `{UPC_A, UPC_E, EAN_13, EAN_8, CODE_128}` (canonical; other symbologies are dropped). Duplicates collapsed.
- **Errors:** `400` (`UnreadableImageError`) when the bytes are not a decodable image. A readable image with no supported barcode is **not** an error — it returns `200` with `barcodes: []`.

### Backend — modules
- **`app/schemas/barcodes.py`** — `BarcodeMatch{text, format}`, `BarcodeDecodeResponse{barcodes}` (re-exported from `app.schemas`).
- **`app/services/barcodes.py`** — `decode_image(data: bytes) -> list[BarcodeMatch]`. Opens via Pillow (`UnreadableImageError` on failure), decodes with `pyzbar.decode` restricted to the five `ZBarSymbol`s, maps native type names → canonical, dedupes by `(text, format)`. No FastAPI/DB.
- **`app/domain/errors.py`** — `UnreadableImageError(DomainError)`, mapped to `400` in `routers/_errors.py`.
- **`app/routers/barcodes.py`** — thin handler; reads the upload, calls the service, translates `DomainError` via `to_http`.

### Frontend — flow
`apiDecodeBarcode(file)` → branch on `barcodes.length`: `0` shows a "no barcode" message (manual table stays usable); `1` resolves via `apiGetItemByBarcode` → `focusItemByBarcode` (filter + auto-open the Stock form) or, on `404`, an Owner/Admin-only "Create Item" shortcut that prefills `#barcode`; `>1` renders a chooser in `#txn-scan-chooser`. The scan UI auto-resets after a completed stock/dispense via `setOnTransactionSaved(resetScan)` wired in `main.js`.