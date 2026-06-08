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
      notes_validation.py
      quantity.py
      roles.py
    routers/
      auth.py
      barcodes.py
      items.py
      transactions.py
      users.py
      _errors.py
    schemas/
      auth.py
      barcodes.py
      items.py
      transactions.py
      users.py
    services/
      auth.py
      barcodes.py
      history.py
      items.py
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
| `last_active_at` | timestamptz | Bumped on authenticated requests |

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

`price` and `product_link` are cost-sensitive: the items router redacts both to `null` for Supervisor/Technician before serialising, so they never reach a non-Admin client (the frontend also hides the columns). Notes keys must be non-blank strings. Values may be `str`, `int`, `float`, or `bool`. Notes updates replace the whole JSON object.

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
| GET | `/items/{barcode}` | Any logged-in user | Lookup item by barcode (`price`/`product_link` redacted below Admin) |
| PATCH | `/items/{item_id}` | Admin | Edit barcode, name, and/or location |
| PATCH | `/items/{item_id}/notes` | Supervisor | Replace notes |
| DELETE | `/items/{item_id}` | Admin | Delete unreferenced item |

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
- Deleting an item or user with transaction history is blocked.

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

