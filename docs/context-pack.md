# Inventory App Context Pack — Current Project State

**Project:** Barcode-Based Inventory Management App  
**Current Phase:** Production-oriented internal app: auth, roles, barcode scanning, item editing, corrections, deployment config, and docs are all in place.  
**Environment:** Windows / PowerShell / local PostgreSQL / Python virtual environment  
**Backend Stack:** FastAPI + SQLAlchemy + psycopg 3 + PostgreSQL  
**Frontend:** Plain HTML / CSS / JavaScript ES modules; no build step  
**Deployment:** One Dockerized FastAPI service on Render plus one managed Postgres database  
**Repo Root:** `C:\Users\mcclu\Desktop\inventory_app_git`

Use this file as the quick handoff. For deeper details, use:

- `docs/spec.md` for product behavior.
- `docs/reference.md` for stable technical facts.
- `docs/interfaces.md` for module and endpoint contracts.
- `docs/deploy-render.md` for Render deployment.
- `docs/plan-live-capture.md` and `docs/plan-saved-items-and-history.md` for shipped design rationale.

---

## Executive Summary

This is a single-process inventory web app. FastAPI serves both the REST API and the static SPA. PostgreSQL is the system of record. Items are tracked by barcode, stock movements are append-only transaction rows, and the browser UI is role-gated while the backend enforces every authorization rule.

Implemented capabilities:

- Login, logout, `/auth/me`, HttpOnly cookie sessions, and sliding idle timeout.
- Four roles: `owner`, `admin`, `supervisor`, `technician`.
- Item create, list, lookup by barcode, edit barcode/name/location, notes editing, correction, and delete.
- User create, list, password reset, and delete with strict subordinate-management rules.
- Stock and dispense transactions attributed to the logged-in user.
- Paginated transaction history with item/user/work-order filters and copy-to-clipboard export.
- Barcode scan on Transaction and Saved Items pages:
  - Upload/still image decode through backend `pyzbar`.
  - Live camera decode through vendored `@zxing/browser`.
- Docker and Render deployment blueprint with managed Postgres and automatic Alembic migration on container start.

The largest remaining product gaps are soft deletes, partial/merge notes updates, broader frontend automated testing, and production observability/backups beyond the current Render setup.

---

## Architecture

```text
Browser SPA (static ES modules)
        ↓ fetch()
FastAPI Backend (routers → services → domain)
        ↓ SQLAlchemy / psycopg
PostgreSQL Database
```

Rules in force:

- The browser never talks directly to PostgreSQL.
- `app/domain/` stays pure: no FastAPI, SQLAlchemy, or Pydantic.
- `app/services/` owns persistence and orchestration, but not HTTP.
- `app/routers/` stays thin: dependencies, request schemas, service calls, error mapping.
- `backend/static/` owns frontend behavior with ES modules and no bundler.
- Schema changes go through SQLAlchemy models plus Alembic migrations.

---

## Technology Stack

| Layer | Technology | Notes |
|---|---|---|
| Runtime | Python 3.12 in Docker; local venv may differ | Dockerfile is authoritative for deploy |
| Backend framework | FastAPI | `Inventory Management API` |
| ASGI server | Uvicorn | Started by `entrypoint.sh` |
| ORM | SQLAlchemy 2 | Synchronous sessions |
| DB driver | psycopg 3 | URL normalized to `postgresql+psycopg://` |
| Database | PostgreSQL | Local dev plus Render managed Postgres |
| Migrations | Alembic | Run automatically on container start |
| Validation | Pydantic v2 | Request/response schemas |
| Config | `python-dotenv` + environment variables | `.env` for local; Render env vars for prod |
| Auth | Server-side sessions in Postgres | HttpOnly cookie named `session` |
| Password hashing | `hashlib.scrypt` | No third-party password library |
| Barcode upload decode | Pillow + pyzbar + native zbar | `libzbar0` installed in Docker |
| Barcode live decode | Vendored `@zxing/browser` UMD | Loaded from `backend/static/vendor/` |
| Frontend | Static HTML/CSS/JS ES modules | No React, HTMX, bundler, or Node build |
| Tests | pytest | Backend-focused tests |

---

## Database Schema

Current Alembic revisions:

| Revision | Description |
|---|---|
| `4f0a7ce7d1ac` | Initial `users`, `items`, `transactions` tables |
| `9a2c5d4e8b11` | Adds item JSONB attributes |
| `4c1e7f3a9b22` | Adds item location; renames attributes to notes |
| `a1b2c3d4e5f6` | Adds auth password hashes, roles, sessions table |
| `b2d3e4f5a6c7` | Restricts transaction foreign keys |
| `c3d4e5f6a7b8` | Adds correction reason to transactions |

Core tables:

- `users`: `id`, `username`, `password_hash`, `role`, `created_at`.
- `sessions`: opaque session `token`, `user_id`, `created_at`, `last_active_at`.
- `items`: `id`, `barcode`, `name`, `quantity`, `location`, `notes`, `created_at`.
- `transactions`: `id`, `item_id`, `user_id`, `transaction_type`, `quantity`, `work_order_number`, `reason`, `created_at`.

Important invariants:

- `items.barcode` and `users.username` are unique.
- Quantities use `Numeric` / Python `Decimal`, not floats.
- Stock and dispense use `SELECT ... FOR UPDATE` on the item row.
- Corrections are `transaction_type = "adjust"` rows, not edits to old history.
- Transaction foreign keys are restricted so referenced items/users cannot be deleted.
- `sessions.user_id` cascades so deleting a user deletes their login sessions.

---

## Auth And Roles

Auth is implemented and required. Public route: `POST /auth/login`. Everything else requires a valid session except static assets and the root SPA shell.

Role hierarchy:

```text
owner > admin > supervisor > technician
```

Route-level expectations:

- Any logged-in user: item list and barcode lookup, barcode decode, and **dispense** transactions (scan-and-go; Technician is dispense-only).
- Supervisor+: item notes, **stock** transactions, voids, user list, history.
- Admin+: create/edit/delete items, corrections, `/db-test`.
- User management: create, reset password, and delete only when the actor strictly outranks the target role.
- Owner is bootstrap-only via `backend/scripts/create_owner.py`; no API caller can create or manage an owner unless they outrank the target role, which no one does for owners.

The frontend mirrors these rules for convenience, but backend dependencies are authoritative.

---

## API Surface

### Auth

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/login` | Authenticate and set the session cookie |
| POST | `/auth/logout` | Delete server-side session and clear cookie |
| GET | `/auth/me` | Return current user identity and role |

### Items

| Method | Path | Purpose |
|---|---|---|
| POST | `/items/` | Create item |
| GET | `/items/` | List items newest-first |
| GET | `/items/{barcode}` | Lookup by barcode |
| PATCH | `/items/{item_id}` | Edit barcode, name, and/or location |
| PATCH | `/items/{item_id}/notes` | Replace notes JSONB |
| DELETE | `/items/{item_id}` | Delete unreferenced item |

### Users

| Method | Path | Purpose |
|---|---|---|
| POST | `/users/` | Create subordinate user with password and role |
| GET | `/users/` | List users newest-first |
| POST | `/users/{user_id}/reset-password` | Reset subordinate password |
| DELETE | `/users/{user_id}` | Delete subordinate unreferenced user |

### Transactions

| Method | Path | Purpose |
|---|---|---|
| POST | `/transactions/` | Record stock or dispense |
| POST | `/transactions/adjust` | Record correction to absolute quantity |
| GET | `/transactions/` | Paginated history with optional filters |

`GET /transactions/` supports `item_id`, `user_id`, `work_order_number`, `page`, and `page_size`.

### Barcodes And Utility

| Method | Path | Purpose |
|---|---|---|
| POST | `/barcodes/decode` | Decode uploaded image bytes in memory |
| GET | `/` | Serve the SPA shell |
| GET | `/db-test` | Admin-only DB connectivity probe |

---

## Frontend Shape

The frontend is a static SPA mounted at `/`. Main modules:

```text
backend/static/
  index.html
  styles.css
  main.js
  api.js
  state.js
  roles.js
  dom.js
  format.js
  scan/
    barcode-decoder.js
    frame-debouncer.js
  views/
    auth.js
    nav.js
    items.js
    itemEditor.js
    correction.js
    notes.js
    users.js
    transactions.js
    history.js
    scan.js
```

User-facing pages:

- Login screen.
- Create Item.
- Saved Items, including scanner, action dropdown, item editor, notes editor, correction flow.
- Create User.
- Saved Users, including reset password and delete actions where allowed.
- Transaction, including scanner and stock/dispense form.
- History, including item/user/work-order filters, pagination, and copy table.

---

## Deployment

Render deployment is defined in `render.yaml`:

- Web service: `inventory-app`, Docker runtime, root dir `backend`.
- Database: `inventory-db`, managed Postgres.
- `DATABASE_URL` is wired from the managed database.
- `COOKIE_SECURE=true` in production.
- `SQL_ECHO=false` in production.
- `entrypoint.sh` runs `alembic upgrade head`, then starts Uvicorn on `$PORT`.

Docker image:

- Base: `python:3.12-slim`.
- Installs `libzbar0` for `pyzbar`.
- Installs `backend/requirements.txt`.
- Copies app, static assets, Alembic config, scripts, and entrypoint.

---

## Development Rules

- Run backend commands from `backend\` unless the command explicitly expects repo root.
- Use Alembic for schema changes.
- Do not hand-create application tables in pgAdmin.
- Preserve the current layering.
- Keep frontend files separate; no inline JS/CSS migration and no frontend build step unless that is a deliberate stack change.
- Treat `docs/spec.md`, `docs/reference.md`, and `docs/interfaces.md` as living docs: update them with code changes.

Common commands:

```powershell
cd backend
uvicorn app.main:app --reload --port 8124
alembic upgrade head
pytest
```

---

## Current Gaps

- Hard deletes only; no soft-delete lifecycle.
- Notes update is full replacement only; no merge/patch behavior.
- Frontend has little/no automated test coverage.
- Render free tier has cold starts and limited persistence guarantees unless upgraded.
- Operational monitoring, alerting, and backup verification are not yet deeply documented.

