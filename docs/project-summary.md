# Project Summary

A self-hosted inventory + work-order staging system for physical materials tracked by barcode. Field crews scan items on a phone; Team Leads and admins review and bill from the office.

**Stack:** one FastAPI process serving the JSON API and a no-build static SPA (`backend/static`, ES modules); PostgreSQL via SQLAlchemy + Alembic; zbar/`@zxing/browser` scanning; one `/ws` WebSocket for cache invalidation (REST stays the source of truth); Docker + managed Postgres on Render (port 8124).

**Layers:** `routers -> schemas/services -> domain/models -> database`. Backend role gates are authoritative; frontend role hiding is UX only.

## Core domains

- **Items and transactions** - barcode-keyed stock, dispense, correct (append-only), void (reverses stock). A dispense beyond the recorded count is saved and raises a recount User Request. Prices are redacted below TechFM OA.
- **Work orders** - import-only entities identified by number; Created -> Assigned -> In-Progress -> Completed -> Review (On-Hold pauses, Closed is archived). Review needs a second person. Labor and materials bill from the order.
- **Mass staging** - truck-loading plans that reference work orders.
- **Tools** - ledger-derived custody; "who has what" is computed, never stored.
- **Users and roles** - `technician < Team Lead < techfm_oa < admin < owner`; role changes revoke sessions.
- **NetFacilities enrichment** - read-only backfill of imported orders; CSV import is the only create path.
- **Real-time invalidation** - `/ws` tells a view to refetch; never carries row data.

## Run and test

- Run: Uvicorn on port 8124 (startup sequence under Deployment in `docs/current-state.md`).
- Backend tests: `backend\venv\Scripts\python.exe -m pytest` (needs a reachable `DATABASE_URL`; `--collect-only -q` needs none).
- Frontend: Vitest, run from PowerShell at an uppercase-drive path.
- CI runs the suite and deploys `main` to Render on green.

Backlog: `docs/open-work.md`. Contracts and invariants: `docs/current-state.md`.
