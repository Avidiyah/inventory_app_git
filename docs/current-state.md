# Inventory App Current State

Last reviewed: 2026-06-25

Purpose of this file: give an AI or developer enough current-state context to
make technical changes without rereading the whole repository. Start here, then
open only the files named for the task.

This is the single durable repo documentation artifact. It replaces the previous
scattered docs.

## How To Use This Doc

For implementation work:

1. Read `Fast Orientation`, `Architecture Rules`, and `Hard Invariants`.
2. Use `Task Routing Map` to pick the relevant files.
3. Read the matching `Feature Context` and `API Surface` rows.
4. Run the focused tests named in `Test Map`.
5. Update this file if shipped behavior, routes, schema, deployment, or known
   gaps change.

For review/debugging work:

1. Use `Data Model` and `API Surface` to identify the contract.
2. Use `Known Gaps` to avoid confusing intentional limitations with regressions.
3. Use `Test Map` to find existing coverage and missing coverage.

If this file conflicts with code, trust the code and update this file as part of
the change.

## Fast Orientation

The app is a self-hosted inventory and work-order staging system for physical
materials tracked by barcode.

Runtime shape:

- FastAPI API and static SPA in one process.
- PostgreSQL persistence through SQLAlchemy and Alembic.
- Static no-build frontend under `backend/static`.
- Barcode upload decoding through backend `pyzbar`.
- Live camera scanning through vendored `@zxing/browser`.
- Render deployment: one Docker web service plus one managed Postgres.

Core workflows:

- Find/create/edit inventory items by barcode.
- Stock, dispense, correct, void, and bill transaction rows.
- Scan items into work-order batches.
- Create/assign/log standalone work orders (identity = number); dispense or
  retroactively backfill materials.
- Plan/load/return materials for a community/building by unit (truck staging).
- Review/copy transaction history.
- Manage users and role-scoped access.

## Architecture Rules

Backend layering:

```text
routers -> schemas/services -> domain/models -> database
```

Rules:

- Routers stay thin: parse schemas, enforce auth, call services, translate
  `DomainError` through `routers/_errors.py`.
- Services own database queries, transactions, row locks, and commits.
- Domain modules are pure rules with no FastAPI/SQLAlchemy imports.
- Models mirror physical schema; every schema change needs a model change and
  an Alembic migration.
- Pydantic schemas define request/response contracts, not permissions.
- Backend gates are authoritative. Frontend role visibility is UX only.
- Frontend is plain ES modules. No bundler, type checker, generated clients, or
  build-time route validation.
- Static shell HTML is assembled from fragments in `backend/app/main.py`.

## Task Routing Map

Use this table before searching broadly.

Path shorthand:

- `domain/*`, `routers/*`, `schemas/*`, `services/*`, `models.py`, and
  `auth_deps.py` mean files under `backend/app/`.
- `static/*` means files under `backend/static/`.
- `test_*.py` means files under `backend/tests/`.

| Task area | Read these first | Usual tests |
| --- | --- | --- |
| Auth/session/login/logout | `app/auth_deps.py`, `routers/auth.py`, `services/auth.py`, `schemas/auth.py`, `static/views/auth.js`, `static/api.js` | `test_auth_password.py`, `test_auth_session_lifetime.py` |
| Roles/permissions/user management | `domain/roles.py`, `routers/users.py`, `services/users.py`, `schemas/users.py`, `static/roles.js`, `static/views/users.js`, `static/views/nav.js` | `test_roles.py`, `test_route_role_gates.py` |
| Item CRUD/lookup/archive | `routers/items.py`, `services/items.py`, `schemas/items.py`, `models.py`, `static/views/items.js`, `static/views/itemEditor.js`, `static/api.js` | `test_item_barcodes.py`, `test_item_price_gating.py`, route-gate tests |
| Item notes | `domain/notes_validation.py`, `services/notes.py`, `schemas/items.py`, `routers/items.py`, `static/views/notes.js` | add/extend focused tests if behavior changes |
| Alternate barcodes | `models.py`, `services/items.py`, `schemas/items.py`, `routers/items.py`, `static/views/itemEditor.js`, `static/views/addBarcode.js` | `test_item_barcodes.py` |
| Stock/dispense/correction/void | `domain/quantity.py`, `services/transactions.py`, `routers/transactions.py`, `schemas/transactions.py`, `static/views/transactions.js`, `static/views/correction.js` | `test_quantity_reverse.py`, route-gate tests |
| Billing/charge override | `domain/billing.py`, `services/transactions.py`, `services/history.py`, `routers/transactions.py`, `schemas/transactions.py`, `static/views/history.js` | `test_billing_validation.py`, `test_item_price_gating.py` |
| History filters/export | `services/history.py`, `routers/transactions.py`, `schemas/transactions.py`, `static/views/history.js`, `static/api.js` | `test_history_wo_filter.py` |
| Barcode upload decode | `services/barcodes.py`, `routers/barcodes.py`, `schemas/barcodes.py`, `static/views/scan.js`, `static/api.js` | `test_barcodes.py` |
| Live camera scan | `static/scan/barcode-decoder.js`, `static/scan/frame-debouncer.js`, `static/views/scan.js`, `static/scan-test.html`, `static/scan-test.js` | manual browser/device check; unit tests cover backend decode only |
| Scan-and-go work-order batch | `static/views/transactions.js`, `static/views/scan.js`, `routers/transactions.py`, `services/transactions.py`, `static/pages/transaction.html` | transaction/domain tests plus manual UI check |
| Mass staging API/domain | `domain/mass_staging.py`, `services/mass_staging.py`, `routers/mass_stages.py`, `schemas/mass_stages.py`, `models.py` | `test_mass_staging.py`, `test_mass_staging_load.py`, `test_mass_stages_api.py` |
| Mass staging UI (community tree) | `static/views/massStage.js`, `static/pages/mass-stage.html`, `static/api.js`, then backend mass-stage files | mass-stage tests plus manual UI check |
| Work Orders API/domain | `domain/work_orders.py`, `services/work_orders.py`, `routers/work_orders.py`, `schemas/work_orders.py`, `models.py` | `test_work_orders_domain.py`, `test_work_orders_service.py`, `test_route_role_gates.py` |
| Work Orders UI | `static/views/workOrders.js`, `static/pages/work-orders.html`, `static/api.js`, then backend work-order files | work-order tests plus manual UI check |
| Deployment/runtime | `backend/Dockerfile`, `backend/entrypoint.sh`, `backend/alembic.ini`, `backend/app/database.py`, `render.yaml`, `requirements*.txt` | `git diff --check`; run tests if runtime deps change |
| Frontend navigation/layout | `static/shell-head.html`, `static/shell-tail.html`, `static/pages/*.html`, `static/views/nav.js`, `static/styles.css` | manual browser check; no frontend test harness |
| Database schema/migration | `models.py`, matching schemas/services, `backend/alembic/versions`, `database.py` | targeted DB-backed tests, then full pytest |

## File Map

Backend:

```text
backend/app/main.py              FastAPI app, routers, static mount, shell assembly
backend/app/auth_deps.py         cookie/session dependency and role gates
backend/app/database.py          engine/session setup and URL normalization
backend/app/models.py            SQLAlchemy schema model
backend/app/domain/*.py          pure business rules and domain errors
backend/app/domain/work_orders.py work-order status/mode/visibility rules
backend/app/routers/*.py         route handlers and auth gates
backend/app/routers/work_orders.py Work Orders page routes (server-scoped)
backend/app/schemas/*.py         request/response contracts
backend/app/services/*.py        DB-backed application logic
backend/app/services/work_orders.py Work Orders materials log (dispense/retro)
backend/alembic/versions/*.py    migrations
backend/scripts/create_owner.py  owner bootstrap
backend/scripts/import_local_data.ps1 local data import helper
```

Frontend:

```text
backend/static/main.js           frontend composition root
backend/static/api.js            fetch wrappers for every backend route
backend/static/state.js          shared client state
backend/static/roles.js          frontend mirror of role hierarchy
backend/static/format.js         display/error/safe-url helpers
backend/static/dom.js            DOM helpers and confirm dialog
backend/static/views/*.js        page/view modules
backend/static/views/workOrders.js Work Orders page view
backend/static/pages/*.html      SPA page fragments
backend/static/pages/work-orders.html Work Orders page fragment
backend/static/shell-*.html      shell fragments
backend/static/styles.css        global styles
backend/static/scan/*.js         live scanner wrapper/debouncer
backend/static/vendor/*          vendored ZXing browser library
```

Tests:

```text
backend/tests/test_auth_*.py
backend/tests/test_roles.py
backend/tests/test_route_role_gates.py
backend/tests/test_barcodes.py
backend/tests/test_item_*.py
backend/tests/test_billing_validation.py
backend/tests/test_history_wo_filter.py
backend/tests/test_quantity_reverse.py
backend/tests/test_mass_staging*.py
backend/tests/conftest.py
```

## Runtime And Stack

| Area | Current implementation |
| --- | --- |
| Python | 3.12 in Docker; local venv currently Python 3.13.7 |
| Web/API | FastAPI 0.136.3, Starlette 1.2.1, Uvicorn 0.48.0 |
| ORM/database | SQLAlchemy 2.0.50, psycopg 3.3.4, PostgreSQL |
| Migrations | Alembic 1.18.4 |
| Validation | Pydantic 2.13.4 |
| Env/config | python-dotenv 1.2.2 |
| Uploads | python-multipart 0.0.32 |
| Upload barcode decode | pyzbar 0.1.9, Pillow 12.2.0, native zbar |
| Live barcode decode | vendored `@zxing/browser` UMD 0.2.0 |
| Tests | pytest 9.0.3 |
| Fixture generation only | python-barcode 0.16.1 |

Deployment:

- Docker image: `python:3.12-slim`.
- Native package: Debian `libzbar0`.
- Entrypoint: `alembic upgrade head`, then Uvicorn on `${PORT:-8124}`.
- Render blueprint: `render.yaml`.
- Required env: `DATABASE_URL`.
- Production env should set `COOKIE_SECURE=true` and `SQL_ECHO=false`.
- Static assets are served with `Cache-Control: no-cache`.
- App sends `Permissions-Policy: camera=(self)`.
- Windows local pyzbar may need Visual C++ 2013 runtime (`msvcr120.dll`).

## Hard Invariants

These are the constraints most likely to break real behavior if missed.

Inventory/transactions:

- Quantities and prices use `Decimal`/`Numeric`, not floats in backend logic.
- Stock/dispense/correction/void operations lock the item row before changing
  quantity.
- Dispense cannot make on-hand quantity negative.
- Transactions are append-only. Corrections are new `adjust` rows with a
  required reason.
- Voiding is a soft delete: set `voided_at`/`voided_by_id`, hide from history,
  reverse stock effect.
- Voiding is rejected if reversal would make stock negative.
- Item archive is soft delete through `archived_at`.
- User archive is soft delete through `users.archived_at`: archived users
  cannot log in, sessions are revoked, and the row is retained for history.
  Hard delete still exists but is blocked if transactions reference the user.
- Stock/dispense snapshot `Item.price` into `transactions.unit_price`;
  history prefers the snapshot over the live price.
- Mass-stage unused returns add stock without transaction rows. This is the one
  deliberate silent stock change.
- `transactions.affects_stock` is TRUE for every ordinary stock/dispense/adjust.
  It is FALSE only for a *retroactive* work-order entry: such a row shows in
  History identically to a real dispense but did NOT move on-hand, so both its
  creation and its void skip the stock change. `void_transaction` branches on
  this flag (a stock-neutral void only soft-deletes the row).

Security/access:

- Backend role gates are source of truth.
- Frontend role hiding is only convenience.
- Sessions are server-side rows and carried by an HttpOnly `session` cookie.
- Passwords are case-sensitive, not stripped, minimum 4 characters.
- User management requires strict subordinate authority: actor rank must be
  greater than target role rank.
- Owner is bootstrap-only; API users cannot manage an owner.
- Admin/Owner cost fields are redacted server-side for lower roles.

Work orders:

- A work order is a standalone entity; **identity is its `number`**, unique
  case-insensitively + trimmed. Any surface using a number find-or-creates the
  one row (`services.work_orders.get_or_create_work_order`); references fill
  blank attributes but never overwrite non-blank ones.
- Status is two-state (`in_progress` / `completed`, reopenable; completed stays
  editable). Soft-archive via `archived_at`; an archived number stays reserved
  and is restored on reference.
- Logging a material writes a `dispense` transaction carrying `work_order_id` +
  number. `entry_mode` decides `affects_stock`: `dispense` moves stock,
  `retroactive` is stock-neutral (still shown in History). Mode is snapshotted
  per line; switching mode only affects subsequent entries.
- Editing a dispense-mode line auto-corrects stock by the delta and rewrites the
  linked transaction in place; deleting it returns the stock and voids the
  transaction. A deliberate, scoped exception to the append-only ledger, limited
  to work-order-originated rows (`work_order_items.transaction_id`).
- List/get/items are scoped server-side by
  `domain.work_orders.can_view_work_order`; out-of-scope/archived/unknown
  surface as 404. Create / attribute edits / archive are Supervisor+; an
  assignee must be a technician.

Mass staging:

- Stage status moves only `planning -> loading -> completed`.
- Slots/items are editable only in `planning`; loading/returning only in
  `loading`.
- Only one active non-completed stage per `(community, building_name)`.
- A stage references work orders through `mass_stage_work_orders` slots; adding
  one enforces the work order's community/building match the stage.
- Stage loading writes real per-slot `dispense` transactions carrying the slot's
  work order; returns reverse-fill across slots and write no ledger row.
- DB column names kept: `mass_stages.building_name` holds the building *number*.

Barcode:

- Primary item barcode and every additional barcode must be globally unique
  across both `items.barcode` and `item_barcodes.code`.
- Barcode lookup resolves primary or additional code to one live item.
- Archived items are hidden from barcode lookup.

Frontend:

- No build step. HTML ids/classes are runtime contracts with JS modules.
- Static shell is assembled in `main.py` from `shell-head.html`,
  `static/pages/*.html`, and `shell-tail.html`.
- Live camera must stop on page leave/tab hide to release track/torch.

## Roles And Access

Role order:

```text
owner > admin > supervisor > technician
```

| Capability | Rule |
| --- | --- |
| Login/logout/me | login public; logout/me require session |
| Dispense | any authenticated role |
| Stock | supervisor+ |
| History | supervisor+ |
| Void transaction | supervisor+ |
| Edit item notes | supervisor+ |
| Create/edit/archive item | admin+ |
| Correct count | admin+ |
| View item price/product link | admin+; server redaction below admin |
| Set billing override | admin+ |
| List users | supervisor+ |
| Create/reset/archive/restore/delete user | actor must outrank target |
| Mass-stage page/API | supervisor+ |
| Work Orders list/get/items | any authenticated user, server-scoped (technician: assigned; supervisor: created; admin/owner: all) |
| Create work order / edit attributes / assign / archive | supervisor+ (scoped) |
| Scan-gate work-order cards | any authenticated user (`GET /work-orders/?status=in_progress`, scoped) |

Scoping nuance:

- `GET /mass-stages/` list is scoped: supervisor sees own stages, admin/owner
  all. Direct stage-by-ID routes are supervisor+ gated but not additionally
  creator-scoped once the caller has a stage id.
- The `/work-orders` routes DO add real per-row creator/assignee scope checks
  (`services.work_orders`), because technicians reach them. A work order's
  `status`/`entry_mode`/materials are editable by any in-scope user; identity,
  location, and assignment edits require supervisor+.

## Data Model

Primary keys are UUIDs. Timestamps are timezone-aware.

### `users`

Fields: `id`, `username`, `password_hash`, `role`, `created_at`,
`archived_at`.

Relationships:

- one user to many transactions
- one user to many sessions

Rules:

- `archived_at = NULL` means active; a timestamp means archived (soft
  delete). An archived user cannot authenticate and is excluded from the
  default user list, but the row is retained so history still resolves
  their name.
- Archiving also deletes the user's sessions, so an active login ends
  immediately.

Password hash format: `scrypt$n$r$p$salt_hex$hash_hex`.

### `sessions`

Fields: `token`, `user_id`, `created_at`, `expires_at`.

Rules:

- `token` is the opaque cookie value and primary key.
- `user_id` cascades on user delete.
- `expires_at = NULL` means browser-session lifetime.
- remembered sessions get a 12-hour absolute cap.
- there is no idle timeout.

### `items`

Fields: `id`, `barcode`, `name`, `quantity`, `location`, `notes`, `price`,
`product_link`, `created_at`, `archived_at`.

Rules:

- `barcode` is canonical/display code.
- `notes` is JSONB with string keys and scalar values (`str`, `int`, `float`,
  `bool`).
- `archived_at` hides item from lists/lookups but keeps joins for history.
- `price` and `product_link` are cost-sensitive and server-redacted below
  Admin.

Update behavior:

- `PATCH /items/{id}` is a partial update keyed on Pydantic
  `model_fields_set`: any subset of `barcode`, `name`, `location`, `price`,
  `product_link` may be sent, and a price-only or product-link-only patch
  is accepted.
- An explicit `null` for the nullable `price` / `product_link` clears the
  stored value; `barcode` / `name` / `location` reject null or blank.
- Create Item UI still sends blank price as `0` (see Known Gaps).

### `item_barcodes`

Fields: `id`, `item_id`, `code`, `created_at`.

Rules:

- Additional package codes only; canonical code stays on `items.barcode`.
- `code` is unique inside this table.
- Services enforce cross-table uniqueness against primary barcodes.
- Child rows cascade if an item is truly hard-deleted. Normal item delete is
  archive, so cascade is not part of ordinary UI flow.

### `transactions`

Fields: `id`, `item_id`, `user_id`, `transaction_type`, `quantity`,
`unit_price`, `billable_quantity`, `work_order_number`, `work_order_id`,
`reason`, `affects_stock`, `created_at`, `voided_at`, `voided_by_id`.

Rules:

- `transaction_type`: `stock`, `dispense`, or `adjust`.
- Stock/dispense quantity is positive.
- Adjust quantity is signed delta.
- `reason` required for adjust.
- `work_order_id` is the FK link to the standalone work order;
  `work_order_number` is the denormalized snapshot kept for History (the router
  resolves both from a scanned card or by find-or-create).
- `unit_price` snapshots `Item.price` when a stock/dispense row is written
  (NULL for `adjust` and pre-snapshot rows). History reads this snapshot,
  falling back to live `Item.price` only when it is NULL, so editing an
  item price does not rewrite past line values.
- `billable_quantity = NULL` means bill full recorded quantity.
- `billable_quantity = 0` means record but do not charge.
- Billing override cannot exceed recorded quantity and cannot target `adjust`.
- `voided_by_id` is a plain UUID, not a second FK to users.
- `affects_stock` defaults TRUE. FALSE marks a retroactive work-order entry
  that shows in History like a dispense but never moved on-hand; create and
  void both skip the stock change for it.

### `work_orders`

Fields: `id`, `number`, `community`, `building_number`, `unit_number`,
`description`, `status`, `entry_mode`, `assigned_to_id`, `created_by_id`,
`created_at`, `updated_at`, `completed_at`, `archived_at`.

Rules:

- The standalone first-class entity. **Identity is `number`**, unique
  case-insensitively + trimmed via the functional index
  `uq_work_orders_number_ci` (`lower(btrim(number))`). Every surface
  find-or-creates by number through `services.work_orders.get_or_create_work_order`.
- `status` is two-state (`in_progress` / `completed`, reopenable).
- `entry_mode` (`dispense` / `retroactive`) is the default mode for newly logged
  materials.
- `assigned_to_id` (must be a technician) and `created_by_id` drive visibility
  scope (`domain.work_orders.can_view_work_order`).
- Soft delete via `archived_at`; an archived number stays reserved and is
  restored when referenced again.
- References fill blank attributes but never overwrite non-blank ones; explicit
  edits (`update_work_order`) overwrite.

### `work_order_items`

Fields: `id`, `work_order_id`, `item_id`, `quantity`, `mode`, `transaction_id`,
`created_by_id`, `created_at`, `updated_at`.

Rules:

- The editable "materials actually used" list for a work order, separate from
  `mass_stage_items` (truck planning). One row per item per work order
  (`UNIQUE(work_order_id, item_id)`); re-adding an item updates its row.
- `mode` snapshots the work order's `entry_mode` at logging time.
- `transaction_id` links the `Transaction` the line produced (so the entry shows
  in History). `work_order_id` FK is `ON DELETE CASCADE`; `item_id` is plain.

### `mass_stages`

Fields: `id`, `community`, `building_name`, `status`, `created_by_id`,
`created_at`, `updated_at`, `completed_at`.

Rules:

- A building's truck-staging plan; it **references** work orders (does not own
  them). `community` is the top tree level; `building_name` holds the building
  *number* (column name kept). `status`: `planning`, `loading`, `completed`.
- Partial unique index `uq_mass_stages_active_community_building` permits only
  one active non-completed stage per `(community, building_name)`.

### `mass_stage_work_orders`

Fields: `id`, `stage_id`, `work_order_id`, `sort_order`, `created_at`.

Rules:

- A work order's ordered slot in a stage's truck plan (replaces the old
  `mass_stage_rooms`). `UNIQUE(stage_id, work_order_id)`. `sort_order` drives
  load allocation. `stage_id` FK is `ON DELETE CASCADE`; `work_order_id` is a
  plain FK (the work order is independent).
- Adding a work order enforces its community/building match the stage.

### `mass_stage_items`

Fields: `id`, `stage_work_order_id`, `item_id`, `planned_quantity`,
`loaded_quantity`, `returned_quantity`, `created_at`.

Rules:

- One planned item row per slot/item pair (`UNIQUE(stage_work_order_id, item_id)`).
  Truck-plan estimates, distinct from `work_order_items` actuals.
- Planning does not move stock.
- Loading increments `loaded_quantity` and writes per-slot dispenses carrying
  the slot's work order; Returning increments `returned_quantity` and silently
  adds stock back. Net consumed is `loaded_quantity - returned_quantity`.

## API Surface

All routes except `POST /auth/login` and `GET /` require authentication unless
specified.

### App

| Method | Path | Gate | Behavior |
| --- | --- | --- | --- |
| GET | `/` | public | assembled SPA shell |
| GET | `/db-test` | admin+ | database/user probe |

### Auth

| Method | Path | Gate | Behavior |
| --- | --- | --- | --- |
| POST | `/auth/login` | public | authenticate, create session, set cookie |
| POST | `/auth/logout` | session | delete session, clear cookie |
| GET | `/auth/me` | session | return current user identity |

### Items

| Method | Path | Gate | Behavior |
| --- | --- | --- | --- |
| POST | `/items/` | admin+ | create item |
| GET | `/items/` | session | list non-archived items newest-first |
| GET | `/items/{barcode}` | session | lookup live item by primary or additional barcode |
| PATCH | `/items/{item_id}` | admin+ | partial edit of barcode/name/location/price/product link; explicit null clears price/link |
| PATCH | `/items/{item_id}/notes` | supervisor+ | replace notes object |
| PATCH | `/items/{item_id}/barcodes` | admin+ | replace additional barcodes |
| DELETE | `/items/{item_id}` | admin+ | archive item |

### Users

| Method | Path | Gate | Behavior |
| --- | --- | --- | --- |
| POST | `/users/` | actor outranks target role | create user |
| GET | `/users/` | supervisor+ | list users; `include_archived` adds archived users |
| POST | `/users/{user_id}/reset-password` | actor outranks target | reset password |
| POST | `/users/{user_id}/archive` | actor outranks target | archive (soft delete) user; revokes sessions |
| POST | `/users/{user_id}/restore` | actor outranks target | reactivate archived user |
| DELETE | `/users/{user_id}` | actor outranks target | hard delete unreferenced user |

### Transactions And History

| Method | Path | Gate | Behavior |
| --- | --- | --- | --- |
| POST | `/transactions/` | session plus direction rule | create stock/dispense |
| POST | `/transactions/adjust` | admin+ | absolute count correction |
| PATCH | `/transactions/{transaction_id}/billing` | admin+ | set/clear billing override |
| DELETE | `/transactions/{transaction_id}` | supervisor+ | void transaction and reverse stock effect |
| GET | `/transactions/` | supervisor+ | paginated history, voided rows excluded |

History filters:

- `item_id`
- `user_id`
- `work_order_number`
- `page`, default 1
- `page_size`, default 10, max 100

Filter behavior:

- filters combine with AND
- work-order filter is case-sensitive substring match
- SQL `%`, `_`, and escape characters are escaped
- Admin/Owner rows include `item_price` and `billable_quantity`
- Supervisor rows receive null for cost/billing fields

### Barcodes

| Method | Path | Gate | Behavior |
| --- | --- | --- | --- |
| POST | `/barcodes/decode` | session | decode uploaded image bytes, no persistence |

Readable image with no barcode returns `200 {"barcodes": []}`.
Unreadable image returns 400.

### Mass Stages

| Method | Path | Gate | Behavior |
| --- | --- | --- | --- |
| POST | `/mass-stages/` | supervisor+ | create planning stage (community + building) |
| GET | `/mass-stages/` | supervisor+ scoped | list stages, optional `status` |
| GET | `/mass-stages/{stage_id}` | supervisor+ | full stage detail (slots + planned items) |
| PATCH | `/mass-stages/{stage_id}` | supervisor+ | rename (community/building) and/or transition status |
| DELETE | `/mass-stages/{stage_id}` | supervisor+ | delete stage; does not reverse dispenses |
| POST | `/mass-stages/{stage_id}/reuse` | supervisor+ | fresh empty planning stage for the same building |
| POST | `/mass-stages/{stage_id}/work-orders` | supervisor+ | add a work order to the plan (find-or-create + enforce match) |
| DELETE | `/mass-stages/{stage_id}/work-orders/{slot_id}` | supervisor+ | remove a work order from the plan |
| POST | `/mass-stages/{stage_id}/work-orders/{slot_id}/items` | supervisor+ | add/upsert planned item |
| PATCH | `/mass-stages/{stage_id}/work-orders/{slot_id}/items/{stage_item_id}` | supervisor+ | edit planned quantity |
| DELETE | `/mass-stages/{stage_id}/work-orders/{slot_id}/items/{stage_item_id}` | supervisor+ | remove planned item |
| POST | `/mass-stages/{stage_id}/load` | supervisor+ | load merged item as per-slot dispenses |
| POST | `/mass-stages/{stage_id}/return` | supervisor+ | return unused material silently to stock |

The old `/quick-room`, `/active-rooms`, and per-room assign/edit routes are gone:
the scan gate lists `/work-orders/?status=in_progress` and creates via
`POST /work-orders/`; assignment/edits live on the work order.

### Work Orders

List/get/items are open to any authenticated user but **server-scoped**: a
technician sees/acts on only work orders assigned to them, a supervisor only
ones they created, admin/owner all. Create / attribute edits / archive are
Supervisor+. Out-of-scope, archived, or unknown work orders return 404.

| Method | Path | Gate | Behavior |
| --- | --- | --- | --- |
| GET | `/work-orders/` | session scoped | list in_progress/completed work orders; `status`, `q` (WO# search) filters |
| POST | `/work-orders/` | supervisor+ | create (or open, on number match) a work order |
| GET | `/work-orders/{id}` | session scoped | work-order detail + logged materials |
| PATCH | `/work-orders/{id}` | session scoped; attr/assignee/number edits supervisor+ | set status/entry_mode and/or attributes |
| POST | `/work-orders/{id}/archive` | supervisor+ scoped | soft-archive (number stays reserved) |
| POST | `/work-orders/{id}/items` | session scoped | log a material (mode = work order's entry_mode); upsert by item |
| PATCH | `/work-orders/{id}/items/{wo_item_id}` | session scoped | edit a material's quantity (dispense lines auto-correct stock) |
| DELETE | `/work-orders/{id}/items/{wo_item_id}` | session scoped | remove a material (dispense lines return stock; voids the linked txn) |

The `POST /transactions/` body now also accepts `work_order_id` (from a scanned
card); a free-text `work_order_number` from a Supervisor+ is find-or-created.

## Frontend Feature Context

### Login

Files: `views/auth.js`, `api.js`, `state.js`, `views/nav.js`,
`views/transactions.js`.

Behavior:

- Boot calls `/auth/me`.
- 401 shows login screen.
- Login success stores current user, applies nav visibility, resets any batch,
  and opens Transaction page.
- Any later 401 triggers global return to login.
- Logout tries `/auth/logout`, then locally returns to login even if request
  fails.

### Find/Add Item

Files: `views/items.js`, `views/itemEditor.js`, `views/addBarcode.js`,
`views/notes.js`, `views/correction.js`, `pages/saved-items.html`,
`pages/create-item.html`.

Behavior:

- Add Item is Admin+.
- Find Item list is available to all roles.
- Technician item table is simplified: no actions/created column, quantity and
  location near name.
- Supervisor+ can edit notes.
- Admin+ can edit item details/barcodes, correct count, and archive item.
- Admin/Owner see price/link columns.
- Unknown scan on Find Item offers Admin+ Create Item and Add Barcode shortcuts.

### Scan / Stock

Files: `views/transactions.js`, `views/scan.js`, `pages/transaction.html`,
`views/nav.js`, `api.js`.

Behavior:

- Every role lands here after login.
- Gate shows active work-order cards from `/work-orders/?status=in_progress`
  (scoped). Tapping a card starts a batch on that work order (id + number).
- Technician sees only assigned cards and cannot free-type a work order.
- Supervisor+ can quick-add a work order (number + optional community/building/
  unit/technician) which find-or-creates it, then starts the batch.
- Supervisor+ also has a free-text fallback (the typed number is find-or-created).
- Each committed scan carries `work_order_id` (+ number) on the transaction.
- Batch starts with quantity `1`.
- Default flow is dispense-only for every role.
- Supervisor+ can reveal manual entry and stock options.
- Live camera auto-starts only if permission is already granted.
- Scan resolves barcode, asks confirmation, then commits transaction.
- Unknown barcode does not offer create-item shortcut in this flow.
- Continuous live scan uses dwell and same-barcode cooldown to prevent double
  commits.

### Mass Stage

Files: `views/massStage.js`, `pages/mass-stage.html`, `api.js`, backend
mass-stage router/service/domain/schema/model.

Behavior:

1. Create stage for community/building.
2. Add work orders (each a unit slot referencing a standalone work order;
   community/building come from the stage, optional unit + technician). Adding
   find-or-creates the work order and enforces a building match.
3. Add planned items and quantities per slot.
4. Save stage: `planning -> loading`.
5. Load merged item quantities. Loads split across slots by `sort_order` and
   create real dispense transactions carrying each slot's work order.
6. Return unused material. Returns add stock and update slot tables only.
7. Mark completed.
8. Stage again from completed: a fresh empty planning stage for the same
   community + building (no slots copied).

UI display (community tree):

- the list is a three-tier collapsing tree: Community -> Building -> Unit
- the create row is a Community dropdown (3 seeds + in-use names + "+ New
  community…") plus a Building # input
- each unit shows an "Open work order →" link that navigates to the Work Orders
  page for its work order (`focusWorkOrder` + `showPage`); planned items are
  still edited inline in planning
- completed stages are read-only and terminal

### Work Orders

Files: `views/workOrders.js`, `pages/work-orders.html`, `api.js`, backend
work-order router/service/domain/schema/model.

Behavior:

- Any authenticated role, server-scoped (technician sees assigned, supervisor
  created, admin/owner all). Reached via the nav button or a Unit click in the
  Mass Stage tree.
- Supervisor+ get a "New work order" form (number + optional community/building/
  unit/assignee); re-using an existing number opens it.
- Filter by status (In progress / Completed / All), then search by number.
- Cards are collapsible; the body has a mode selector (Dispense / Retroactive),
  Mark completed / Reopen, a Supervisor+ attribute editor (community/building/
  unit/assignee) + Archive, and the logged materials with inline-editable
  quantities, add (search-and-pick), and remove.
- Dispense entries move stock and show in History like a Scan/Stock dispense;
  retroactive entries show in History identically but move no stock.
- Completed work orders stay fully editable (status is a flag + filter).

### History

Files: `views/history.js`, `pages/history.html`, `services/history.py`,
`routers/transactions.py`, `schemas/transactions.py`.

Behavior:

- Supervisor+ only.
- Tabs: all, by item, by user.
- Work-order filter overlays all tabs and combines with tab filters.
- Voided rows are hidden.
- Any row visible in History can be voided by the same role set.
- Admin/Owner Charge column shows base line value and `+15%` marked-up value.
- Billing editor can bill partial count, bill zero, or clear override.
- Copy table exports all matching rows, not just visible page.
- Export cap: 100 pages * 100 rows.
- Admin/Owner export includes billable qty, unit price, base value, marked-up
  value.

### Users

Files: `views/users.js`, `pages/create-user.html`, `pages/saved-users.html`,
`roles.js`, backend users/auth/roles files.

Behavior:

- Supervisor+ can list users.
- Create-user dropdown offers only subordinate roles.
- Row reset/archive/restore actions appear only for users the actor outranks.
- Password reset uses prompt and requires min length 4.
- The 🗑️ action archives (soft delete): the user can no longer log in but
  their history is kept and they can be restored. Archived rows render
  dimmed with an "(archived)" tag and a Restore action.
- The list loads with archived users included so the History "by user"
  filter can still select a departed user.

### Barcode Scanner

Files: `views/scan.js`, `scan/barcode-decoder.js`, `scan/frame-debouncer.js`,
`scan-test.html`, `scan-test.js`, `vendor/zxing-browser-*`, backend barcode
service/router/schema.

Behavior:

- Upload mode posts image bytes to `/barcodes/decode`.
- Live mode uses browser camera and ZXing directly, never `/barcodes/decode`.
- Live scanner requests environment camera, 1280x720 ideal, continuous focus
  best-effort.
- Torch button appears only if track reports torch capability.
- `scan-test.html` is an unauthenticated diagnostic harness, not part of SPA.

## Backend Feature Context

### Auth/Session

Files: `services/auth.py`, `routers/auth.py`, `auth_deps.py`,
`schemas/auth.py`, `models.py`.

Behavior:

- Login validates username/password against scrypt hash.
- `authenticate` rejects archived users (indistinguishable from bad
  credentials); `get_active_session_user` also filters archived users.
- Session token is random URL-safe string stored in `sessions`.
- Cookie is HttpOnly, SameSite=Lax, path `/`, Secure controlled by
  `COOKIE_SECURE`.
- Remembered login sets cookie max-age and server `expires_at` to 12 hours.
- Non-remembered login has no server cap and relies on browser session cookie.
- Expired remembered session is deleted on first request after expiry.

### Items

Files: `services/items.py`, `services/notes.py`, `routers/items.py`,
`schemas/items.py`, `models.py`.

Behavior:

- `list_items` returns live items only, newest-first, no pagination.
- `get_item_by_barcode` resolves primary or additional barcode for live items.
- `create_item` checks barcode across primary and additional code tables.
- `replace_barcodes` diffs child rows to avoid transient unique conflicts.
- `delete_item` archives by timestamp; hard delete is not normal path.
- `update_item` is a partial update via a `_UNSET` sentinel: only the
  fields the router forwards (`model_dump(exclude_unset=True)`) are
  written, and an explicit `None` clears nullable `price`/`product_link`.
- `_item_response` flattens additional barcode objects to `list[str]` and
  redacts price/link below admin.

### Transactions/Billing/History

Files: `domain/quantity.py`, `domain/billing.py`, `services/transactions.py`,
`services/history.py`, `routers/transactions.py`, `schemas/transactions.py`.

Behavior:

- `apply_transaction` locks item row, applies stock/dispense, inserts row
  with `unit_price` snapshotted from the locked item.
- `apply_correction` locks item row, computes signed delta, inserts `adjust`
  (no `unit_price` snapshot).
- `void_transaction` locks transaction row then item row, reverses effect.
- `set_billable_quantity` validates override and updates row only.
- `list_history` joins transactions/items/users, filters voided rows, paginates.
- History cost/billing fields are populated only when router passes
  `include_price=True` for Admin/Owner; `item_price` is the row's
  `unit_price` snapshot, falling back to live `Item.price` when NULL.

### Work Orders

Files: `domain/work_orders.py`, `services/work_orders.py`,
`routers/work_orders.py`, `schemas/work_orders.py`, `models.py`.

Behavior:

- `get_or_create_work_order` resolves a number (case-insensitive + trimmed) to
  the one row: fills blank attributes, restores an archived match, validates the
  assignee is a technician. The single home for find-or-create, used by the WO
  page, the scan gate, and Mass Stage.
- `list_work_orders` is scoped (technician/supervisor/admin), excludes archived,
  filters by status, and searches the number case-insensitively.
- `update_work_order` overwrites the supplied fields; completing stamps
  `completed_at`, reopening clears it; a number collision raises 400.
- `add/update/delete_work_order_item` lock the item row, write/rewrite/void the
  linked `dispense` transaction (`affects_stock` per the work order's mode), and
  auto-correct stock for dispense-mode edits/deletes.

### Mass Staging

Files: `domain/mass_staging.py`, `services/mass_staging.py`,
`routers/mass_stages.py`, `schemas/mass_stages.py`, `models.py`.

Behavior:

- `create_stage` enforces one active stage per (community, building).
- `add_work_order_to_stage` enforce-matches the work order's community/building
  to the stage, find-or-creates it via `services.work_orders`, and links a slot.
- `list_stages` is scoped for supervisor vs admin/owner; `get_stage` is not
  additionally scoped beyond Supervisor+.
- `reuse_stage` requires a completed source and makes a fresh empty stage for
  the same community + building.
- `add_item` upserts planned quantity by slot/item.
- `load_item` locks the item, allocates across slot plans, writes dispense rows
  carrying each slot's `work_order_id` + number, increments loaded quantities.
- `return_item` locks the item, reverse-allocates returns, increments returned
  quantities, adds stock without transaction rows.

## Migration History

Alembic head: `b3d5f7a9c1e4`.

| Revision | Meaning |
| --- | --- |
| `4f0a7ce7d1ac` | initial users/items/transactions |
| `9a2c5d4e8b11` | item JSONB attributes |
| `4c1e7f3a9b22` | item location, attributes -> notes |
| `a1b2c3d4e5f6` | auth password hashes, roles, sessions |
| `b2d3e4f5a6c7` | restrict transaction FKs |
| `c3d4e5f6a7b8` | transaction reason |
| `d4e5f6a7b8c9` | transaction void metadata |
| `e5f67b8c9d0` | item price/product link |
| `f6b8c0d2e4a1` | item archived_at |
| `a7c9e1f3b5d2` | additional item barcodes |
| `b1f3d5a7c9e2` | mass-stage tables |
| `c7e9a1b3d5f8` | session expires_at remember-me |
| `c2e4f6a8d0b1` | room creator/assignee |
| `e7f9a1c3b5d2` | transaction billable_quantity |
| `d8b2f4a6c1e3` | transaction unit_price (historical price snapshot) |
| `f1a3c5e7b9d4` | user archived_at (soft delete) |
| `b3d5f7a9c1e4` | standalone `work_orders` (number identity) + `work_order_items` + transaction `affects_stock`/`work_order_id` + `mass_stages.community` + `mass_stage_work_orders` slots (replaces rooms) |

## Test Map

Run all tests with the repo venv:

```powershell
backend\venv\Scripts\python.exe -m pytest backend\tests
```

The system Python may not have dependencies. The repo venv was verified to run
the suite.

Database-backed tests:

- use `backend/tests/conftest.py`
- require reachable Postgres through `DATABASE_URL`
- skip if DB is unreachable
- let services call `commit()` inside a rolled-back outer transaction

Coverage map:

| Test file | Covers |
| --- | --- |
| `test_auth_password.py` | scrypt password hashing/checking |
| `test_auth_session_lifetime.py` | remembered/non-remembered session lifecycle |
| `test_user_archive.py` | user archive blocks login, revokes sessions, list scoping |
| `test_item_update_partial.py` | partial item PATCH + clear price/link to null |
| `test_history_price_snapshot.py` | per-transaction unit_price snapshot + fallback |
| `test_roles.py` | role hierarchy and transaction/user-management rules |
| `test_route_role_gates.py` | important route minimum-role gates |
| `test_barcodes.py` | backend image decode and supported formats |
| `test_item_barcodes.py` | additional barcode uniqueness/lookup/update |
| `test_item_price_gating.py` | item price/link server redaction |
| `test_billing_validation.py` | pure billable quantity rules |
| `test_history_wo_filter.py` | work-order history filter escaping/combination |
| `test_quantity_reverse.py` | stock delta reversal for voids |
| `test_mass_staging.py` | pure mass-stage allocation/lifecycle rules |
| `test_mass_stages_api.py` | schemas, route gates, response builders |
| `test_mass_staging_load.py` | DB-backed slot load/return, add-work-order enforce-match, reuse |
| `test_work_orders_domain.py` | pure number normalization, 2-state validators, fill-blanks, visibility scope |
| `test_work_orders_service.py` | DB-backed find-or-create (case-insensitive/fill-blanks/restore), dispense/retroactive logging, edit auto-correct, delete reversal, stock-neutral void, archive, scoping |

No frontend test harness exists. For UI behavior, run backend tests plus manual
browser checks for changed pages.

## Known Gaps

Do not "fix" these accidentally unless the task asks for it.

- Notes saves replace the entire notes object; no partial merge.
- Create Item UI sends blank price as `0`.
- Mass-stage unused returns intentionally do not create transaction rows.
- Direct mass-stage detail/mutation routes are Supervisor+ gated but not
  creator/assignee scoped.
- Completed mass stages cannot be reopened.
- Stage deletion does not reverse load transactions already written.
- Frontend has no bundler/type checker; ID and module contract drift is manual.
- Work-order entries bend the append-only ledger on purpose: editing a
  dispense-mode line rewrites its linked transaction in place and auto-corrects
  stock (scoped to `work_order_items`-originated rows only).
- The `b3d5f7a9c1e4` migration is a clean rebuild: it WIPES all prior
  mass-stage/work-order data (stages, slots, planned items, logged materials).
  Inventory `items` and historical `transactions` are preserved (old txns keep
  their `work_order_number` string with `work_order_id` NULL).
- Work-order numbers are a single global namespace, unique case-insensitively;
  there is no per-community/building number scoping.
- A free-text work-order number on a transaction is find-or-created only for
  Supervisor+; a technician's scan must carry a `work_order_id` (from a card).
- Deferred work-order attributes not yet built: `priority`, `due_date`,
  `external_ref`/`source` (for future real-world WO integration).

## Documentation Policy

Keep this file optimized for technical execution:

- Prefer tables and routing maps over narrative.
- Keep source-of-truth statements tied to actual files.
- Document current behavior, not intended future behavior.
- Put implementation limitations in `Known Gaps`.
- Avoid reintroducing separate durable plan/spec/reference docs unless there is
  a temporary need and a cleanup date.
