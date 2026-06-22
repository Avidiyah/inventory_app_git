# Backend Reference — Stable Facts

Use this as a concise technical briefing. `docs/spec.md` covers product behavior; this file covers stack, schema, routes, and durable engineering decisions.

---

## Project Overview

Inventory management system with a Python/FastAPI backend, PostgreSQL database, and a static ES-module frontend served by the same FastAPI process. Items are tracked by barcode. Quantity changes are recorded as append-only transaction rows.

---

## Technology Stack

| Layer | Technology | Version / notes |
|---|---|---|
| Deploy runtime | Python | 3.12 via `backend/Dockerfile` |
| Web framework | FastAPI | 0.136.3 |
| ASGI server | Uvicorn | 0.48.0 |
| ORM | SQLAlchemy | 2.0.50 |
| DB driver | psycopg 3 + binary wheel | 3.3.4 |
| Migrations | Alembic | 1.18.4 |
| Validation | Pydantic v2 | 2.13.4 |
| Database | PostgreSQL | Local dev and Render managed Postgres |
| Config | python-dotenv | 1.2.2 |
| Frontend | Static HTML/CSS/JS modules | Served through FastAPI `StaticFiles` |
| Upload barcode decode | pyzbar + Pillow + native zbar | `libzbar0` installed in Docker |
| Live barcode decode | Vendored `@zxing/browser` | `backend/static/vendor/zxing-browser-0.2.0.umd.min.js` |
| File uploads | python-multipart | 0.0.32 |
| Tests | pytest | 9.0.3 in `requirements-dev.txt` |

---

## Project Structure

```text
backend/
  app/
    main.py
    auth_deps.py
    database.py
    models.py
    domain/
      errors.py
      mass_staging.py
      notes_validation.py
      quantity.py
      roles.py
    routers/
      auth.py
      barcodes.py
      items.py
      mass_stages.py
      transactions.py
      users.py
      _errors.py
    schemas/
      auth.py
      barcodes.py
      items.py
      mass_stages.py
      transactions.py
      users.py
    services/
      auth.py
      barcodes.py
      history.py
      items.py
      mass_staging.py
      notes.py
      transactions.py
      users.py
  alembic/
    versions/
  scripts/
    create_owner.py
    import_local_data.ps1
  static/
    api.js
    dom.js
    format.js
    index.html
    main.js
    roles.js
    state.js
    scan/
      barcode-decoder.js
      frame-debouncer.js
    vendor/
      zxing-browser-0.2.0.umd.min.js
      zxing-browser-LICENSE.txt
    views/
      auth.js
      correction.js
      history.js
      itemEditor.js
      items.js
      massStage.js
      nav.js
      notes.js
      scan.js
      transactions.js
      users.js
  Dockerfile
  entrypoint.sh
  requirements.txt
  requirements-dev.txt
render.yaml
```

---

## Database

`DATABASE_URL` is required. `app/database.py` normalizes `postgres://` and `postgresql://` URLs to the psycopg 3 SQLAlchemy dialect.

Engine settings:

- `echo` is controlled by `SQL_ECHO`; default is off.
- `connect_timeout` is 5 seconds.
- Sessions use `autoflush=False` and `autocommit=False`.
- `get_db()` yields one session per request and closes it in `finally`.

---

## Data Models

### `users`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | Primary key |
| `username` | Text | Required, unique |
| `password_hash` | Text | Required, scrypt hash |
| `role` | Text | `owner`, `admin`, `supervisor`, or `technician` |
| `created_at` | timestamptz | Set on insert |

Relationships: one-to-many to `transactions`, one-to-many to `sessions`.

### `sessions`

| Column | Type | Notes |
|---|---|---|
| `token` | Text | Primary key, opaque random token |
| `user_id` | UUID | FK to `users.id`, `ON DELETE CASCADE` |
| `created_at` | timestamptz | Set on insert |
| `expires_at` | timestamptz | Nullable. NULL = no server cap (non-remembered, ends on browser close); a timestamp = remembered session's absolute cap (login + 12h) |

### `items`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | Primary key |
| `barcode` | Text | Required, unique |
| `name` | Text | Required |
| `quantity` | Numeric | Required, current stock level |
| `location` | Text | Required |
| `notes` | JSONB | Required, default `{}` |
| `price` | Numeric nullable | Per-unit price; surfaced ONLY to Admin/Owner |
| `product_link` | Text nullable | URL to the product; surfaced ONLY to Admin/Owner |
| `created_at` | timestamptz | Set on insert |

`price` and `product_link` are cost-sensitive: the items router redacts both to `null` for Supervisor/Technician before serialising, so they never reach a non-Admin client (the frontend also hides the columns). Notes keys must be non-blank strings. Values may be `str`, `int`, `float`, or `bool`. Notes updates replace the whole JSON object. `archived_at` (timestamptz, nullable) implements item soft delete — a "delete" sets it and the item is hidden from `list_items` and barcode lookups while its row (and history) is retained.

### `item_barcodes`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | Primary key |
| `item_id` | UUID | FK to `items.id`, `ON DELETE CASCADE` |
| `code` | Text | Required, globally unique |
| `created_at` | timestamptz | Set on insert |

An item's **additional** barcodes (beyond its canonical `items.barcode`). A physical item often carries several codes on its packaging; each gets a row here so a scan of the primary or any additional code resolves to the same item (`services.items.get_item_by_barcode`). `code` is globally UNIQUE (guards alt-vs-alt); the primary-vs-alt overlap is enforced by the service pre-check `services.items._barcode_in_use`. The FK is `ON DELETE CASCADE` (alternates are owned config, not audit data), but items are soft-deleted via `archived_at` so the cascade only fires on a true row delete.

### `transactions`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | Primary key |
| `item_id` | UUID | FK to `items.id`, delete restricted |
| `user_id` | UUID nullable | FK to `users.id`, delete restricted |
| `transaction_type` | Text | `stock`, `dispense`, or `adjust` |
| `quantity` | Numeric | Positive for stock/dispense; signed delta for adjust |
| `work_order_number` | Text nullable | Used by stock/dispense |
| `reason` | Text nullable | Required by correction/adjust rows |
| `created_at` | timestamptz | Set on insert |
| `voided_at` | timestamptz nullable | NULL = live; a timestamp = voided (soft delete), hidden from history |
| `voided_by_id` | UUID nullable | Who voided the row (hidden audit metadata; deliberately not an FK) |

Transactions are append-only and never edited in place. A mis-clicked
transaction can be *voided* (Supervisor+): the row is retained for the
audit trail but stamped `voided_at` / `voided_by_id`, excluded from the
history view, and its effect on item stock is reversed under the item
row lock. A void that would drive stock below zero is rejected (400).

### `mass_stages`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | Primary key |
| `building_name` | Text | The "Building Name + #" label |
| `status` | Text | `planning`, `loading`, or `completed` |
| `created_by_id` | UUID nullable | FK to `users.id` (plain) |
| `created_at` / `updated_at` | timestamptz | `updated_at` bumped on ORM update |
| `completed_at` | timestamptz nullable | Set when status → `completed` |

A building's batch-staging plan. The partial unique index
`uq_mass_stages_active_building` (`UNIQUE(building_name) WHERE status <>
'completed'`) enforces at most one *active* stage per building.

### `mass_stage_rooms`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | Primary key |
| `stage_id` | UUID | FK to `mass_stages.id`, `ON DELETE CASCADE` |
| `room_number` | Text | Unique within a stage |
| `work_order_number` | Text | The room's single work order |
| `sort_order` | Integer | Entry order; drives load fill / overflow |
| `created_by_id` | UUID | FK to `users.id` (plain, nullable). Work-order author; a supervisor sees only rooms they created |
| `assigned_to_id` | UUID | FK to `users.id` (plain, nullable). The technician the work order is assigned to (NULL = unassigned); a technician sees only rooms assigned to them |
| `created_at` | timestamptz | Set on insert |

A room within a stage, paired with one work order. `UNIQUE(stage_id,
room_number)` (room numbers only distinguish within a stage). `created_by_id` /
`assigned_to_id` drive role-scoped visibility (admin/owner see all); each is
indexed.

### `mass_stage_items`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | Primary key |
| `room_id` | UUID | FK to `mass_stage_rooms.id`, `ON DELETE CASCADE` |
| `item_id` | UUID | FK to `items.id` (plain) |
| `planned_quantity` | Numeric | The estimate (not a transaction) |
| `loaded_quantity` | Numeric | Accrues as the item is staged onto the truck (default 0) |
| `returned_quantity` | Numeric | Accrues from unused-materials returns (default 0) |
| `created_at` | timestamptz | Set on insert |

One planned item per room (`UNIQUE(room_id, item_id)`). Per-item overflow
(`Σloaded − Σplanned`) and net consumed (`Σloaded − Σreturned`) are
derived, never stored. Owned plan data, so the FKs cascade from the room;
`item_id` is plain (blocks hard-deleting a referenced item — benign,
items are soft-deleted). The `transactions` table is unchanged: loading
writes ordinary `dispense` rows, and returns write none.

---

## Migration History

| Revision | Description |
|---|---|
| `4f0a7ce7d1ac` | Create initial users/items/transactions tables |
| `9a2c5d4e8b11` | Add item JSONB attributes |
| `4c1e7f3a9b22` | Add location and rename attributes to notes |
| `a1b2c3d4e5f6` | Add password hashes, roles, and sessions |
| `b2d3e4f5a6c7` | Restrict transaction foreign keys |
| `c3d4e5f6a7b8` | Add correction reason column |
| `d4e5f6a7b8c9` | Add transaction void columns (`voided_at`, `voided_by_id`) |
| `e5f67b8c9d0` | Add item `price` and `product_link` columns |
| `f6b8c0d2e4a1` | Add item `archived_at` (soft delete) |
| `a7c9e1f3b5d2` | Add `item_barcodes` table (additional barcodes per item) |
| `b1f3d5a7c9e2` | Add mass staging tables (`mass_stages`, `mass_stage_rooms`, `mass_stage_items`) |
| `c7e9a1b3d5f8` | Replace `sessions.last_active_at` with `expires_at` (remember-me) |
| `c2e4f6a8d0b1` | Add `created_by_id` + `assigned_to_id` to `mass_stage_rooms` (work-order ownership/assignment) |

---

## Authentication And Authorization

Auth endpoints:

- `POST /auth/login`
- `POST /auth/logout`
- `GET /auth/me`

Passwords use standard-library `hashlib.scrypt` and are stored as self-describing hash strings. Sessions are server-side rows and are carried by an HttpOnly `session` cookie with `SameSite=Lax`; `COOKIE_SECURE=true` is set in Render.

Roles:

```text
owner > admin > supervisor > technician
```

`require_min_role(minimum)` gates ordinary routes. User management uses `roles.can_manage(actor_role, target_role)`, meaning the actor must strictly outrank the target. Owner accounts are bootstrap-only and not manageable through the API.

---

## API Routes

### Auth

| Method | Path | Description |
|---|---|---|
| POST | `/auth/login` | Authenticate and set cookie |
| POST | `/auth/logout` | Delete session and clear cookie |
| GET | `/auth/me` | Current user identity and role |

### Items

| Method | Path | Minimum role | Description |
|---|---|---|---|
| POST | `/items/` | Admin | Create item |
| GET | `/items/` | Any logged-in user | List items newest-first (`price`/`product_link` redacted below Admin) |
| GET | `/items/{barcode}` | Any logged-in user | Lookup item by primary or additional barcode (`price`/`product_link` redacted below Admin) |
| PATCH | `/items/{item_id}` | Admin | Edit barcode, name, location, price, and/or product link |
| PATCH | `/items/{item_id}/notes` | Supervisor | Replace notes |
| PATCH | `/items/{item_id}/barcodes` | Admin | Replace the item's additional barcodes |
| DELETE | `/items/{item_id}` | Admin | Soft-delete (archive) an item |

### Users

| Method | Path | Minimum rule | Description |
|---|---|---|---|
| POST | `/users/` | Actor must outrank assigned role | Create user with password and role |
| GET | `/users/` | Supervisor | List users |
| POST | `/users/{user_id}/reset-password` | Actor must outrank target | Reset password |
| DELETE | `/users/{user_id}` | Actor must outrank target | Delete unreferenced user |

### Transactions

| Method | Path | Minimum role | Description |
|---|---|---|---|
| POST | `/transactions/` | Supervisor | Record stock or dispense |
| POST | `/transactions/adjust` | Admin | Record correction to absolute quantity |
| DELETE | `/transactions/{transaction_id}` | Supervisor | Void (soft-delete) a mis-clicked transaction; reverses its stock effect |
| GET | `/transactions/` | Supervisor | Paginated history (excludes voided rows) |

`GET /transactions/` query params:

- `item_id`
- `user_id`
- `work_order_number`
- `page`, default `1`
- `page_size`, default `10`, max `100`

`work_order_number` is a case-sensitive substring match using escaped SQL `LIKE`.

### Mass Stages

All routes require Supervisor or above (`require_min_role(supervisor)`) **except
`GET /active-rooms`**, which any authenticated user may call (the result is
role-scoped server-side, so technicians get only their assigned work orders).

| Method | Path | Description |
|---|---|---|
| POST | `/mass-stages/quick-room` | Scan-gate quick-add: find-or-create the building's active stage + append a room (community + unit + work order, optional technician assignee) → parent `MassStageSummary` |
| GET | `/mass-stages/active-rooms` | Work-order cards for the scan gate, **scoped to the caller** (technician → assigned, supervisor → created, admin/owner → all). Any authenticated user |
| PATCH | `/mass-stages/{id}/rooms/{room_id}/assign` | Assign a work order (room) to a technician, or clear it (null). Supervisor+ |
| POST | `/mass-stages/` | Create a `planning` stage for a building (400 if one is already active) |
| GET | `/mass-stages/` | List stages, optional `?status=` filter |
| GET | `/mass-stages/{id}` | Stage detail: rooms → items + the merged rollup |
| PATCH | `/mass-stages/{id}` | Rename and/or change status (forward-only transition) |
| DELETE | `/mass-stages/{id}` | Delete a stage (rooms/items cascade; does not reverse dispenses) |
| POST | `/mass-stages/{id}/rooms` | Add a room (planning only) |
| PATCH / DELETE | `/mass-stages/{id}/rooms/{room_id}` | Edit / remove a room (planning only) |
| POST | `/mass-stages/{id}/rooms/{room_id}/items` | Add/upsert a planned item (planning only) |
| PATCH / DELETE | `…/rooms/{room_id}/items/{stage_item_id}` | Edit qty / remove a planned item (planning only) |
| POST | `/mass-stages/{id}/load` | Stage a merged item onto the truck (per-room dispenses); loading only |
| POST | `/mass-stages/{id}/return` | Return unused materials (silent stock-add); loading only |
| POST | `/mass-stages/{id}/reuse` | "Stage again": fresh planning copy of a completed stage (rooms kept, work orders cleared, no items) |

`/load` and `/return` return the affected item's updated merged rollup.

### Barcodes And Utility

| Method | Path | Minimum role | Description |
|---|---|---|---|
| POST | `/barcodes/decode` | Any logged-in user | Decode uploaded image bytes |
| GET | `/` | Public | Serve SPA shell |
| GET | `/db-test` | Admin | Return current database and user |

---

## Business Rules

- Item starting quantity must be non-negative.
- Item location must be non-blank.
- Item update requires at least one of barcode, name, or location.
- Transaction quantity must be greater than zero.
- Dispense cannot reduce stock below zero.
- Stock/dispense locks the item row with `SELECT ... FOR UPDATE`.
- Correction sets an absolute new quantity, stores the signed delta, requires a non-blank reason, and rejects no-op corrections.
- Usernames are unique and non-blank.
- User passwords must meet the configured minimum length.
- User create/reset/delete actions require strict subordinate management.
- Items are soft-deleted (archived via `archived_at`), keeping history intact; deleting a *user* with transaction history is still blocked.
- Every barcode (an item's primary `barcode` or any additional `item_barcodes.code`) is globally unique across all items; a scan resolves the primary or any additional code to exactly one item.
- Mass staging: at most one active (non-completed) stage per building; status is forward-only `planning → loading → completed`; rooms/items are editable only while `planning`, load/return only while `loading`.
- A mass-stage load splits its quantity across the item's rooms (fill in `sort_order`, overflow onto the last room) into `dispense` rows on each room's work order, atomic under the item `SELECT ... FOR UPDATE`; an overdraw is rejected.
- An unused-materials return adds stock back **without** a transaction row (reverse-filled across rooms, capped at net loaded) — the only stock change with no append-only audit row.
- "Stage again" (`/reuse`) clones a completed stage's building + rooms into a fresh `planning` stage with work orders cleared (stored as empty strings — no migration) and no items; the completed stage is retained as the saved record. A stage cannot move to `loading` until every room has a non-blank work order.

---

## Key Technical Decisions

- UUID primary keys for core tables.
- `Numeric`/`Decimal` for quantities.
- Synchronous SQLAlchemy sessions.
- Static frontend co-located with the API.
- Server-side cookie sessions rather than JWT bearer tokens.
- scrypt password hashing from the standard library.
- Upload barcode decode on the backend with `pyzbar`.
- Live barcode decode in the browser with vendored `@zxing/browser`.
- Render deployment as one Docker web service plus one managed Postgres.
- Alembic migrations run at container startup.

---

## Vendored Frontend Library

### `zxing-browser-0.2.0.umd.min.js`

- Library: `@zxing/browser`
- Version: `0.2.0`
- Format: UMD global `ZXingBrowser`
- License: MIT, stored in `backend/static/vendor/zxing-browser-LICENSE.txt`
- Used by `backend/static/scan/barcode-decoder.js`
- Source URL: `https://registry.npmjs.org/@zxing/browser/-/browser-0.2.0.tgz`
- Tarball SHA-256: `519E5F7E9540E085AE3AB430EA68C7013F8F36EAA3865AE8486135C286473448`
- Vendored file SHA-256: `066BC34EDFCDD4A33F0964AEEC967752A0DEA1CCAF36E58E319AC9FCB5070F6A`

Keep the filename, script tag, license, and hash notes in sync when updating.

