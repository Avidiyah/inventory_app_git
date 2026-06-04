# Inventory App Context Pack — Current Project State and Build Direction

**Project:** Barcode-Based Inventory Management App
**Current Phase:** Full vertical slice shipped — schema, API, and a modular frontend SPA are all working. Next frontier is the three roadmap features (barcode-scan search, auth + roles, web hosting).
**Environment:** Windows / PowerShell / Local PostgreSQL / Python virtual environment
**Backend Stack:** FastAPI + SQLAlchemy + psycopg + PostgreSQL
**Frontend:** Plain HTML / CSS / JavaScript (ES modules) in separate files — no build step
**Database:** PostgreSQL 18 local database named `inventory`
**PostgreSQL Port:** `8801`
**Application DB User:** `inventory_user`
**Repo Root:** `C:\Users\mcclu\Desktop\inventory_app_git`

> **Status note (2026-06-04):** This document was previously written as if the project had only just proven its database connection. That is no longer true. The schema, migrations, full API, and the whole frontend exist and work. The sections below now describe the *actual* current state. The companion docs — [`docs/reference.md`](reference.md) (stable facts), [`docs/spec.md`](spec.md) (current behaviour), [`docs/interfaces.md`](interfaces.md) (module contracts), and [`docs/feature-report.md`](feature-report.md) (the next three features) — are the detailed source of truth; this pack is the high-level handoff.

---

# 1. Executive Summary

This project is a local, self-hosted web-based inventory management application. Users create inventory items (each with a unique barcode), then stock or dispense quantities while preserving an append-only transaction history. Items also carry a free-form `notes` field and a `location`.

**The backend foundation is not just working — the entire MVP workflow is built.** The original proven path still holds:

```text
FastAPI → SQLAlchemy → psycopg → PostgreSQL on localhost:8801 → inventory database → inventory_user
```

On top of that, the following are all implemented and in the repo:

- Three applied Alembic migrations defining `users`, `items`, `transactions`.
- A complete REST API (create/list/lookup/delete items, notes editing, users, stock/dispense transactions, paginated history).
- A six-page single-page frontend, decomposed into ES modules.
- A clean `domain → services → routers` backend layering with Pydantic schemas.

**The immediate next build target is no longer "create an item in the app."** That milestone is done. The current roadmap is the three features in [`docs/feature-report.md`](feature-report.md):

1. **Barcode scan as a search filter** (camera/photo → decode → filter to the matching item).
2. **Password protection + roles** (the app still has no authentication).
3. **Host as a website** (currently local-only; needs HTTPS, managed Postgres, prod hardening).

Recommended order: **3 → 2 → 1** (hosting + HTTPS unblocks the camera; auth must land before any public exposure).

---

# 2. Original Project Goal (unchanged)

The app manages inventory through a barcode-driven workflow:

```text
Scan barcode → Find matching item → Choose Stock or Dispense → Enter quantity
  → Enter work-order number → Save transaction → Update item quantity → Preserve history
```

The barcode-scan step is the one piece of this workflow still on the roadmap (Feature 1). Everything downstream of "find the item" — choosing stock/dispense, quantity, work order, saving, and history — already works through the UI.

---

# 3. Confirmed Architecture

```text
Browser SPA (static ES modules)
        ↓ fetch()
FastAPI Backend (routers → services → domain)
        ↓ SQLAlchemy / psycopg
PostgreSQL Database
```

Architectural rules in force:

- **The frontend never connects directly to PostgreSQL.** All browser actions go through FastAPI endpoints, which validate, apply business rules, then talk to Postgres via SQLAlchemy.
- **Layering is enforced:** `app/domain/` is pure (no FastAPI/SQLAlchemy); `app/services/` does persistence + orchestration (no FastAPI); `app/routers/` are thin HTTP handlers that translate domain errors to HTTP. See [`docs/interfaces.md`](interfaces.md) for exact contracts.
- **Backend and frontend are co-located** in one FastAPI process: `main.py` serves the API and mounts `static/` to serve the SPA at `/`.

---

# 4. Confirmed Technology Stack

| Layer | Technology | Notes |
|---|---|---|
| Database | PostgreSQL 18 | Local, port **8801** |
| Backend framework | FastAPI | `title="Inventory Management API"` |
| ORM | SQLAlchemy | Synchronous `Session`, not async |
| DB driver | psycopg (v3) | Connection string uses `postgresql+psycopg://` |
| Migrations | Alembic | 3 migrations applied (see §6) |
| Validation | Pydantic v2 | Response models use `from_attributes=True` |
| Env vars | python-dotenv | Loads `.env` |
| Frontend | Plain HTML / CSS / JS (ES modules) | **No build step, no bundler** |

**Frontend rule (still in force):** HTML, JavaScript, and CSS stay in separate files. No React, no HTMX. The "single `script.js`" mentioned in earlier notes is obsolete — the JS is now split into ES modules (see §17).

---

# 5. PostgreSQL Setup Status

- PostgreSQL **18** installed locally on Windows and running.
- pgAdmin 4 connects successfully.
- Database: `inventory`. Application role: `inventory_user`. Port: **`8801`**.

**Important correction (still relevant):** do **not** assume the default `5432`. This machine's PostgreSQL instance runs on `localhost:8801`. Use 8801 in all local docs and setup.

pgAdmin is now an inspection/debugging tool only. Application tables are owned by SQLAlchemy models + Alembic migrations and must **not** be created by hand in pgAdmin.

---

# 6. Database Schema (live — three applied migrations)

| Revision | Description |
|---|---|
| `4f0a7ce7d1ac` | Initial schema: `users`, `items`, `transactions` |
| `9a2c5d4e8b11` | Adds `attributes` JSONB column to `items` |
| `4c1e7f3a9b22` | Adds `location` to `items`; renames `attributes` → `notes` |

### `users`
| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK, default `uuid4` |
| `username` | Text | NOT NULL, UNIQUE |
| `created_at` | DateTime (tz-aware) | default now |

### `items`
| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK, default `uuid4` |
| `barcode` | Text | NOT NULL, UNIQUE |
| `name` | Text | NOT NULL |
| `quantity` | **Numeric (`Decimal`)** | NOT NULL, default `0` |
| `location` | Text | NOT NULL |
| `notes` | JSONB | NOT NULL, default `{}` |
| `created_at` | DateTime (tz-aware) | default now |

### `transactions`
| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK, default `uuid4` |
| `item_id` | UUID | FK → `items.id`, NOT NULL |
| `user_id` | UUID | FK → `users.id`, **nullable** (RESTRICT on delete) |
| `transaction_type` | Text | NOT NULL — `"stock"` or `"dispense"` |
| `quantity` | Numeric (`Decimal`) | NOT NULL |
| `work_order_number` | Text | **nullable** |
| `created_at` | DateTime (tz-aware) | default now |

**Schema corrections vs. the old context pack:**
- **Quantity is `Decimal`/`Numeric`, not integer** — a deliberate decision to avoid float precision issues. Fractional quantities are representable.
- **`location` is a first-class NOT NULL column.** Location tracking was *not* deferred — it shipped.
- **`notes` (JSONB) exists** and has a full editor in the UI. The old pack didn't mention it at all.
- There is **no `updated_at`** column on any table.
- **`work_order_number` is nullable / optional**, and **`user_id` is nullable** — see the "decision vs. reality" note in §20.

---

# 7. pgAdmin / Stack Builder Status

- pgAdmin 4 works; server, `inventory` database, and `inventory_user` role are visible with permissions granted.
- **Stack Builder add-ons: not installed, not needed.** No PostGIS, ODBC/JDBC, .NET drivers, or spatial extensions are required.

---

# 8. Database and User Rules

- The app uses the `inventory` database and connects as `inventory_user`.
- The app must **not** connect as the `postgres` superuser; that account stays administrative-only.
- If Alembic ever fails to create tables, check schema-level privileges on `public` first. Expected dev grants:

```sql
GRANT ALL PRIVILEGES ON DATABASE inventory TO inventory_user;
GRANT USAGE, CREATE ON SCHEMA public TO inventory_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO inventory_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO inventory_user;
```

---

# 9. Connection String & `.env`

Format:

```env
DATABASE_URL=postgresql+psycopg://inventory_user:PASSWORD@localhost:8801/inventory
```

Location: `backend\.env` (under the repo root).

PowerShell note: do **not** type `DATABASE_URL=...` directly into the shell — that is not valid PowerShell syntax. The value belongs in the `.env` file.

**`@` in passwords:** `@` is a URL delimiter and must be percent-encoded as `%40` inside the connection string. An earlier auth failure traced to this; it has been resolved.

> ⚠️ **Security — action needed before any non-local use.** The current `.env` contains a **real, plaintext database password that is committed to the git repository.** That is worse than the earlier "typed in chat" concern. Before hosting (Feature 3): rotate the password, move it out of the committed `.env` into the host's secret store, and add `.env` to `.gitignore` (scrubbing it from history if the repo will ever be shared).

---

# 10. Backend Directory & Run Commands

Backend working directory: `backend\` (under the repo root). Run backend commands from there:

```powershell
uvicorn app.main:app --reload     # dev server
alembic upgrade head              # apply migrations
alembic revision --autogenerate -m "message"   # new migration
```

Do not run backend commands from the repo root, `backend\app`, or `backend\venv` unless a specific command requires it.

---

# 11. Python Virtual Environment & Packages

A working `venv` exists under `backend\venv` (prompt shows `(venv)` when active).

Installed packages: `fastapi`, `uvicorn`, `sqlalchemy`, `psycopg`, `python-dotenv`, `alembic`. On Windows, psycopg needed the binary wrapper:

```powershell
pip install "psycopg[binary]"
```

> **Gap:** there is currently **no committed `requirements.txt` or lockfile.** One will be required for hosting (Feature 3). Generate it from the working venv before deploying.

---

# 12. Confirmed Database Connection & API Health

The original connectivity test still passes and returns `('inventory', 'inventory_user')`, proving the `.env` → SQLAlchemy → psycopg → Postgres(8801) → `inventory`/`inventory_user` chain end to end.

The running app also exposes:
- `GET /` → serves the SPA (`static/index.html`).
- `GET /db-test` → `{ "status": "ok", "database": "inventory", "user": "inventory_user" }`.

---

# 13. Current API Surface (all implemented)

### Items — prefix `/items`
| Method | Path | Description |
|---|---|---|
| POST | `/items/` | Create item (400 on duplicate barcode) |
| GET | `/items/` | List all items, newest first |
| GET | `/items/{barcode}` | Lookup by barcode (404 if unknown) |
| PATCH | `/items/{item_id}/notes` | Replace the JSONB `notes` wholesale |
| DELETE | `/items/{item_id}` | Hard-delete item |

### Users — prefix `/users`
| Method | Path | Description |
|---|---|---|
| POST | `/users/` | Create user (400 on duplicate username) |
| GET | `/users/` | List all users, newest first |
| DELETE | `/users/{user_id}` | Delete user (400 if they have transactions) |

### Transactions — prefix `/transactions`
| Method | Path | Description |
|---|---|---|
| POST | `/transactions/` | Record stock/dispense; locks the item row, updates quantity |
| GET | `/transactions/` | Paginated, denormalised history; optional `item_id` / `user_id` filters |

Note: the paginated history is served by `GET /transactions/` (a stale code docstring referring to `/transactions/history` is inaccurate). Query params: `item_id`, `user_id`, `page` (≥1, default 1), `page_size` (1–100, default 10).

---

# 14. Frontend (implemented — modular SPA)

A single HTML shell with six tab-based pages, all wired through ES modules under `static/`:

- **Create Item** — barcode, name, location, starting quantity.
- **Saved Items** — table with client-side name/barcode filter; per-row delete and an inline **Notes editor** (key / type / value rows; full-replace on save).
- **Create User** — username form.
- **Saved Users** — table with delete (blocked if the user has transactions).
- **Transaction** — lists items with Stock/Dispense buttons; a form captures type, user, quantity, optional work-order number.
- **History** — All / By Item / By User sub-tabs over one paginated table (page size 10).

Module layout (no bundler — plain `<script type="module">`):

```text
static/
  index.html          # DOM shell; element-ID contract (see interfaces.md §12)
  styles.css
  main.js             # composition root: imports views, runs initial loaders
  state.js            # client state store (getters/setters)
  api.js              # one fetch wrapper per endpoint
  format.js           # pure formatters / escapers
  dom.js              # generic DOM helpers
  views/
    nav.js  items.js  notes.js  users.js  transactions.js  history.js
```

`api.js` already includes `apiGetItemByBarcode(barcode)` — the hook Feature 1's barcode scanner will reuse.

---

# 15. Backend File Structure (actual)

```text
backend/
  .env                # DATABASE_URL (contains a live committed password — see §9)
  alembic.ini
  alembic/
    env.py
    versions/         # 3 migration scripts (see §6)
  app/
    __init__.py
    main.py           # FastAPI app, router registration, static mount, /db-test
    database.py       # engine, SessionLocal, Base, get_db
    models.py         # User / Item / Transaction ORM models
    domain/           # pure rules: errors.py, quantity.py, notes_validation.py
    schemas/          # items.py, transactions.py, users.py (package, re-exported)
    services/         # items, notes, transactions, history, users
    routers/          # items, transactions, users, _errors (domain→HTTP)
  static/             # see §14
  venv/
```

---

# 16. Confirmed MVP Decisions — and how reality landed

The original decisions, annotated with current status:

| # | Decision | Status in code |
|---|---|---|
| Quantity model | `items.quantity` = current count; transactions = audit log | ✅ As decided — but stored as `Decimal`, not integer |
| Units | No unit system | ✅ None added |
| Barcode not found | Show "Item not found" and stop; no auto-create | ✅ `GET /items/{barcode}` returns 404 |
| Barcode uniqueness | One barcode = one item | ✅ UNIQUE constraint |
| Transaction terms | `stock` / `dispense` | ✅ Enforced via Pydantic `Literal` |
| Negative inventory | Never allowed, no admin override | ✅ `NegativeQuantityError` → 400 "Insufficient stock to dispense." |
| Users | Creatable in-app | ✅ Users CRUD exists |
| Locations | "No location for MVP" | ⚠️ **Superseded** — `location` shipped as a NOT NULL column |
| Categories | No categories | ✅ None |
| Work-order number | "Should be **required** on transactions" | ⚠️ **Not enforced** — `work_order_number` is optional/nullable in backend; frontend leaves it optional |
| Job/project | Handled via work-order number | ✅ No separate jobs table |
| Port | Use 8801 | ✅ |
| Frontend | Separate HTML/CSS/JS | ✅ — now ES modules, not one `script.js` |
| Deployment | Local only for now | ✅ Still local; hosting is Feature 3 |

**Two decisions to revisit explicitly:**
- **Work-order requirement.** The decision was "required," the implementation is "optional." Decide whether to enforce it (Pydantic + a NOT NULL migration + frontend validation) or to formally relax the decision.
- **User attribution.** `user_id` is optional in the backend though the frontend requires a selection. Auth (Feature 2) is the natural point to tighten this by deriving the user from the logged-in session.

Also new since the original decisions: the **JSONB `notes`** feature (flexible per-item metadata) — not in the original MVP list, now fully built with a UI editor.

---

# 17. Error Rules (enforced)

| Condition | Message / behaviour |
|---|---|
| Duplicate barcode on create | 400 "An item with this barcode already exists." |
| Negative starting quantity | Rejected (quantity must be ≥ 0) |
| Barcode lookup miss | 404 "Item not found." |
| Dispense below zero | 400 "Insufficient stock to dispense." (all permission levels) |
| Duplicate username | 400 |
| Delete user with transactions | 400 |
| Transaction quantity ≤ 0 | Rejected (must be > 0) |
| Invalid note key/value type | 400 (keys: non-blank strings; values: str/int/float/bool only) |

---

# 18. Development Rules Going Forward

- **Schema changes go through SQLAlchemy models + Alembic migrations.** Never create application tables by hand in pgAdmin.
- **Keep backend (`app/`) and frontend (`static/`) separate**, and keep `index.html` / `styles.css` / the JS modules in separate files — no inlining everything into the HTML.
- **Respect the layering:** domain stays pure; services own persistence; routers stay thin. Add new endpoints by extending a service and wiring a thin router (mirroring the existing pattern).
- **Local-first.** Don't introduce Docker/cloud/Supabase complexity until the hosting feature is deliberately tackled (Feature 3).

---

# 19. What Is Done

```text
PostgreSQL 18 installed, running, on port 8801
inventory database + inventory_user created, permissions granted
Python backend, venv, packages, psycopg[binary]
.env + DATABASE_URL working; connection test passes
FastAPI app + /db-test
Alembic initialized; 3 migrations applied
users / items / transactions tables live
SQLAlchemy models + Pydantic schemas + get_db dependency
domain / services / routers layering
Items: create / list / lookup-by-barcode / delete
Item notes (JSONB) with full editor + PATCH endpoint
Item location (first-class field)
Users: create / list / delete (with referential guard)
Transactions: stock / dispense with row lock + negative-stock guard
Paginated, denormalised transaction history (All / By Item / By User)
Six-page modular frontend SPA (no build step)
Companion docs: reference / spec / interfaces / feature-report
```

---

# 20. What Is Not Done Yet (the roadmap)

The MVP is built. The remaining work is the three features detailed in [`docs/feature-report.md`](feature-report.md):

1. **Barcode scan → search filter** *(Small–Medium, mostly frontend).* Camera capture / photo upload → decode (native `BarcodeDetector` + a vendored JS library fallback) → reuse `apiGetItemByBarcode` to filter to the item. DB and lookup endpoint already exist. **Needs HTTPS** for live camera.
2. **Password protection + roles** *(Medium–Large, every layer).* Add `password_hash` + `role` (+ migration), a hashing dep (`passlib[bcrypt]`/`argon2`), session strategy (cookie sessions recommended for this single-origin app), `auth` service/router, `get_current_user` / `require_role` dependencies on every mutating route, a login UI, and a seed path for the first admin. **The app currently has no auth — every route is open.**
3. **Host as a website** *(Medium, infra/config).* Pick a host (PaaS recommended), production ASGI serving, managed Postgres + `alembic upgrade head` on deploy, secrets via env, and hardening: make `echo=True` env-driven, commit a `requirements.txt`, consider disabling `/docs` publicly, add HTTPS.

**Dependencies between them:** HTTPS hosting (3) unblocks the camera (1); auth (2) must land before any public exposure from (3). Recommended order **3 → 2 → 1**, deploying privately behind a login first.

Smaller cleanups also outstanding (from the spec's "Known Gaps"): `echo=True` hardcoded in `database.py`; no item-field editing (name/barcode/location are create-only); no direct quantity correction outside transactions; notes are full-replace (no merge); deletes are hard (no soft delete).

---

# 21. Immediate Next Task & Recommended Prompt

The next meaningful step is **Feature 3 groundwork + Feature 2**, since they should ship together behind a login. A good concrete first task:

```text
Start hosting prep that also helps auth: make `echo` env-driven in database.py,
generate a committed requirements.txt from the venv, and move the DB password out of
the committed .env into an untracked secret. Then scaffold the auth migration
(password_hash + role on users) and the password-hashing dependency.
```

Recommended next prompt to continue cleanly:

```text
Let's implement Feature 2 (password protection + roles) from docs/feature-report.md:
add the users migration (password_hash, role), wire passlib/bcrypt, add an auth
service/router with cookie sessions, protect the mutating routes with
get_current_user / require_role, add a login screen, and a seed path for the first admin.
```

---

# 22. Handoff Summary

- This project is **past MVP** — schema, full API, and a modular SPA all work. Do **not** restart setup or rebuild item creation; it exists.
- Use `localhost:8801` and connect as `inventory_user`. Never use the `postgres` superuser for the app.
- Schema changes go through SQLAlchemy + Alembic, never hand-edited in pgAdmin.
- The forward work is the three features in [`docs/feature-report.md`](feature-report.md): barcode-scan search, auth + roles, and web hosting — in roughly the order **hosting/auth together, then scanning**.
- **Before anything leaves this machine:** rotate and de-commit the database password (it is currently in the tracked `.env`), and stand up authentication. The app has no access control today.
