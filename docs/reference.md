# Backend Reference — Stable Facts

> Use this document as a concise briefing when starting any AI-assisted task on this project. It covers architecture, data models, API contracts, validation rules, and key technical decisions that are unlikely to change often.

---

## Project Overview

An **inventory management system** with a Python/FastAPI backend, PostgreSQL database, and a static HTML/CSS/JS frontend served from the same process. Items are tracked by barcode; quantity changes are recorded as immutable transactions.

---

## Technology Stack

| Layer | Technology | Version |
|---|---|---|
| Language | Python | 3.13 |
| Web framework | FastAPI | 0.136.3 |
| ORM | SQLAlchemy | (installed in venv) |
| DB driver | psycopg (v3) + psycopg_binary | 3.3.4 |
| Migrations | Alembic | 1.18.4 |
| Validation | Pydantic v2 | 2.13.4 |
| Database | PostgreSQL | (external) |
| Config | python-dotenv | 1.2.2 |
| Frontend | Static files (HTML/CSS/JS) | served via FastAPI StaticFiles |
| Barcode decode | pyzbar (native `zbar`) + Pillow | 0.1.9 / 12.2.0 |
| File uploads | python-multipart | 0.0.32 |

---

## Project Structure

```
backend/
├── app/
│   ├── main.py          # FastAPI app, router registration, static mount
│   ├── database.py      # Engine, SessionLocal, Base, get_db dependency
│   ├── models.py        # SQLAlchemy ORM models
│   ├── domain/          # Pure, framework-free business rules
│   │   ├── errors.py        # Domain exception vocabulary
│   │   ├── quantity.py      # Stock/dispense arithmetic
│   │   └── notes_validation.py  # Notes dict validator
│   ├── schemas/         # Pydantic request/response schemas (package)
│   │   ├── items.py
│   │   ├── transactions.py
│   │   └── users.py
│   ├── services/        # Persistence + business orchestration (no FastAPI)
│   │   ├── items.py
│   │   ├── notes.py
│   │   ├── transactions.py
│   │   ├── history.py
│   │   └── users.py
│   └── routers/         # Thin HTTP handlers
│       ├── items.py
│       ├── transactions.py
│       ├── users.py
│       └── _errors.py       # Domain → HTTPException translator
├── alembic/             # Database migrations
│   └── versions/        # Migration scripts (see Migration History below)
├── static/              # Frontend ES modules
│   ├── index.html
│   ├── styles.css
│   ├── main.js              # Composition root
│   ├── state.js             # Client state store
│   ├── api.js               # Fetch wrappers per endpoint
│   ├── format.js            # Pure formatters / escapers
│   ├── dom.js               # Generic DOM helpers
│   └── views/               # One module per UI concern
│       ├── nav.js
│       ├── items.js
│       ├── notes.js
│       ├── users.js
│       ├── transactions.js
│       └── history.js
├── .env                 # DATABASE_URL environment variable
└── alembic.ini
```

---

## Database

**Connection:** Configured via `DATABASE_URL` in `.env`, loaded by `python-dotenv`.

**Format:** `postgresql+psycopg://<user>:<password>@<host>:<port>/<dbname>`

**Engine settings:**
- `echo=True` (SQL logging enabled)
- `connect_args={"connect_timeout": 5}`
- Sessions: `autoflush=False`, `autocommit=False`

**Session pattern:** Dependency injection via `get_db()` generator; session is always closed in `finally`.

---

## Data Models

### `users`

| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK, default `uuid4` |
| `username` | Text | NOT NULL, UNIQUE |
| `created_at` | DateTime (tz-aware) | default `utcnow` |

Relationships: one-to-many → `transactions`

---

### `items`

| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK, default `uuid4` |
| `barcode` | Text | NOT NULL, UNIQUE |
| `name` | Text | NOT NULL |
| `quantity` | Numeric | NOT NULL, default `0` |
| `location` | Text | NOT NULL |
| `notes` | JSONB | NOT NULL, default `{}` |
| `created_at` | DateTime (tz-aware) | default `utcnow` |

Relationships: one-to-many → `transactions`

**Notes on `notes` field:** Stores arbitrary key-value metadata. Keys must be non-blank strings; values must be `str`, `int`, `float`, or `bool`. Full replacement only (no partial merge) — the entire `notes` object is overwritten on PATCH.

---

### `transactions`

| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK, default `uuid4` |
| `item_id` | UUID | FK → `items.id`, NOT NULL |
| `user_id` | UUID | FK → `users.id`, nullable |
| `transaction_type` | Text | NOT NULL — `"stock"` or `"dispense"` |
| `quantity` | Numeric | NOT NULL |
| `work_order_number` | Text | nullable |
| `created_at` | DateTime (tz-aware) | default `utcnow` |

Transactions are **append-only** — never updated or deleted. Quantity changes always go through a transaction record.

---

## Migration History

| Revision | Description |
|---|---|
| `4f0a7ce7d1ac` | Initial schema: creates `users`, `items`, `transactions` tables |
| `9a2c5d4e8b11` | Adds `attributes` JSONB column to `items` (NOT NULL, server default `'{}'`) |
| `4c1e7f3a9b22` | Adds `location` column to `items`; renames `attributes` → `notes` |

---

## API Routes

### Items — prefix `/items`

| Method | Path | Description | Status |
|---|---|---|---|
| POST | `/items/` | Create item | 201 |
| GET | `/items/` | List all items (ordered by `created_at` DESC) | 200 |
| GET | `/items/{barcode}` | Get item by barcode | 200 / 404 |
| PATCH | `/items/{item_id}/notes` | Replace item notes entirely | 200 / 404 |
| DELETE | `/items/{item_id}` | Delete item | 204 / 404 |

### Users — prefix `/users`

| Method | Path | Description | Status |
|---|---|---|---|
| POST | `/users/` | Create user | 201 |
| GET | `/users/` | List all users (ordered by `created_at` DESC) | 200 |
| DELETE | `/users/{user_id}` | Delete user | 204 / 400 / 404 |

Note: Deleting a user with existing transactions returns `400`.

### Transactions — prefix `/transactions`

| Method | Path | Description | Status |
|---|---|---|---|
| POST | `/transactions/` | Create transaction (updates item quantity) | 201 |
| GET | `/transactions/` | List transactions with pagination | 200 |

GET `/transactions/` query params: `item_id` (UUID), `user_id` (UUID), `page` (int ≥ 1, default 1), `page_size` (int 1–100, default 10).

### Barcodes — prefix `/barcodes`

| Method | Path | Description | Status |
|---|---|---|---|
| POST | `/barcodes/decode` | Decode an uploaded image → barcodes found | 200 / 400 |

`multipart/form-data` with a single `file`. **Supervisor or above** (matches the Transaction page, the only scanning surface). The image is decoded **in memory and never persisted**, restricted to `UPC_A`, `UPC_E`, `EAN_13`, `EAN_8`, `CODE_128`. Response: `{"barcodes": [{"text": ..., "format": ...}, ...]}`. A readable image with no supported barcode returns `200` with an empty list; an unreadable file returns `400`. No database access — stateless, so no migration was required.

### Root / Utility

| Method | Path | Description |
|---|---|---|
| GET | `/` | Serves `static/index.html` |
| GET | `/db-test` | Returns DB name and connected user |

---

## Business Logic & Validation Rules

### Item creation
- `barcode` must be unique — duplicate returns `400`.
- `quantity` must be ≥ 0.
- `location` must not be blank (stripped before validation).

### Transaction creation
- `transaction_type` must be `"stock"` or `"dispense"` (Pydantic `Literal`).
- `quantity` must be > 0.
- **`stock`**: adds `quantity` to item's current quantity.
- **`dispense`**: subtracts `quantity`; returns `400` if result would be negative.
- Item row is locked with `SELECT ... FOR UPDATE` during the transaction to prevent race conditions.

### Notes update
- Full replacement only — the entire `notes` dict is replaced.
- Keys: non-blank strings.
- Values: `str`, `int`, `float`, or `bool` only. No nested objects or arrays.
- Uses `flag_modified(item, "notes")` to ensure SQLAlchemy tracks JSONB mutations.

### User creation
- `username` must not be blank (stripped).
- Must be unique — duplicate returns `400`.

---

## Pydantic Schemas Summary

| Schema | Purpose |
|---|---|
| `ItemCreate` | POST /items body |
| `ItemResponse` | Item read model (includes `notes`, `location`) |
| `ItemNotesUpdate` | PATCH /items/{id}/notes body |
| `TransactionCreate` | POST /transactions body |
| `TransactionResponse` | Minimal transaction read (no item/user names) |
| `TransactionHistoryItem` | Enriched transaction row (includes `item_barcode`, `item_name`, `username`) |
| `TransactionHistoryPage` | Paginated wrapper: `items`, `total`, `page`, `page_size` |
| `UserCreate` | POST /users body |
| `UserResponse` | User read model |

All response models use `model_config = {"from_attributes": True}` for ORM compatibility.

---

## Key Technical Decisions

- **UUIDs for all PKs** — not integer sequences; all IDs are `uuid.UUID` in Python and `UUID` type in Postgres.
- **Numeric for quantity** — uses `decimal.Decimal` in Python (not float) to avoid floating-point precision issues.
- **JSONB for notes** — flexible key-value metadata stored in Postgres JSONB; `flag_modified` required when mutating in-place.
- **Synchronous SQLAlchemy** — not async; standard `Session`, not `AsyncSession`.
- **No authentication** — the API has no auth layer; `user_id` on transactions is optional and informational only.
- **Static frontend co-located** — the FastAPI app mounts `./static/` and serves `index.html` at the root.
- **Backend barcode decoding** — uploaded images are decoded server-side with `pyzbar` (a ctypes wrapper over the native `zbar` C library), in memory only, never persisted. Chosen over a frontend JS decoder so the symbology/format logic lives in one unit-tested place (`app/services/barcodes.py`). **Windows gotcha:** pyzbar's bundled DLLs require the **Visual C++ 2013 Redistributable** (`msvcr120.dll`); without it the import fails with a missing `libiconv.dll`/`libzbar-64.dll`. (`zxing-cpp` was the original intent but has no prebuilt wheel for this Python/OS and needs a C++ toolchain to build — see `spec.md` decisions log.)

---

## Vendored Frontend Libraries

Third-party JS that ships in `backend/static/vendor/`. Each entry pins a version, records two SHA-256 hashes (upstream tarball + the file in the repo, which may differ from the tarball's copy if a post-extract transform was applied), and documents the exact update procedure so the next bump is mechanical.

### `zxing-browser-0.2.0.umd.min.js`

- **Library:** [`@zxing/browser`](https://www.npmjs.com/package/@zxing/browser)
- **Version:** `0.2.0`
- **Bundled peer:** `@zxing/library ^0.22.0` — inlined into the UMD bundle, no separate file shipped.
- **License:** MIT — full text in `backend/static/vendor/zxing-browser-LICENSE.txt` (must be redistributed with the library; do not delete on update).
- **Format:** UMD, single self-contained file. Exposes a `ZXingBrowser` global; loaded via plain `<script src=...>` (not an ES module).
- **Size:** 441,121 bytes.
- **Source URL:** `https://registry.npmjs.org/@zxing/browser/-/browser-0.2.0.tgz`
- **Tarball SHA-256:** `519E5F7E9540E085AE3AB430EA68C7013F8F36EAA3865AE8486135C286473448`
- **Vendored file SHA-256:** `066BC34EDFCDD4A33F0964AEEC967752A0DEA1CCAF36E58E319AC9FCB5070F6A`
- **Vendored on:** 2026-06-06
- **Used by:** Phase 1 spike at `/static/scan-test.html`; Phase 3 live barcode capture. See [`plan-live-capture.md`](plan-live-capture.md).

### Update procedure (PowerShell, from repo root)

When bumping the version, run these commands verbatim, replacing `<VER>` with the target version. Both hashes go into this document; the old file is overwritten in place.

```powershell
$ver = "<VER>"
$tarball = "browser-$ver.tgz"

# 1. Download from npm registry (no Node required).
Invoke-WebRequest `
    -Uri "https://registry.npmjs.org/@zxing/browser/-/$tarball" `
    -OutFile $tarball

# 2. Record tarball SHA-256 BEFORE extracting -- this is what npm published.
Get-FileHash -Algorithm SHA256 $tarball | Format-List

# 3. Extract to a scratch directory.
New-Item -ItemType Directory -Path .\_zxing-scratch -Force | Out-Null
tar -xzf $tarball -C .\_zxing-scratch

# 4. Inspect package.json "unpkg" field to confirm the UMD path; for 0.2.0
#    it is ./umd/zxing-browser.min.js. Check the bundle does NOT contain a
#    `sourceMappingURL` comment pointing at an unvendored .map file:
$umd = ".\_zxing-scratch\package\umd\zxing-browser.min.js"
(Get-Content $umd -Raw | Select-String -Pattern 'sourceMappingURL' -AllMatches).Matches.Count
# If non-zero, strip the offending comment before copying:
#   (Get-Content $umd -Raw) -replace '//# sourceMappingURL=.*$', '' | Set-Content $umd -NoNewline

# 5. Copy into vendor/ with the version in the filename.
Copy-Item $umd ".\backend\static\vendor\zxing-browser-$ver.umd.min.js"
Copy-Item ".\_zxing-scratch\package\LICENSE" `
          ".\backend\static\vendor\zxing-browser-LICENSE.txt"

# 6. Record the vendored file's SHA-256 AFTER any transform in step 4.
Get-FileHash -Algorithm SHA256 ".\backend\static\vendor\zxing-browser-$ver.umd.min.js" | Format-List

# 7. Clean up.
Remove-Item -Recurse -Force .\_zxing-scratch
Remove-Item $tarball

# 8. Delete the old `zxing-browser-<OLD>.umd.min.js`.
# 9. Update the script tag in any consumer (scan-test.html, real-flow HTML in Phase 3+).
# 10. Update this document: version, both hashes, vendored-on date, size.
```

A version mismatch between the filename, the script tag, and the hashes here is a review blocker.

