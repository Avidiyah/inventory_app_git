# Phase 5 — Load + Return + Merged List *(implemented)*

> **Status:** ✅ Implemented & verified 2026-06-16. Completes the **backend**.
> The two stock-touching actions + the merged rollup, plus the repo's first DB
> test harness. Design source:
> [`phase-1-design-record.md`](phase-1-design-record.md) §3–§7.

## What shipped

The execution half of mass-staging, over HTTP (Supervisor+):

- **Load** (`POST /mass-stages/{id}/load`) — splits one merged load quantity
  across the rooms that planned the item (fill in `sort_order`, overflow → last),
  writing **one real `dispense` per room slice** on that room's work order and
  bumping each room's `loaded_quantity`. All slices commit atomically under a
  single `SELECT … FOR UPDATE` on the item row (same lock as
  `services/transactions.py`). Overdraft → `NegativeQuantityError` (rolled back,
  400).
- **Return** (`POST /mass-stages/{id}/return`) — "unused materials": adds stock
  back **with no ledger row** (the deliberate, isolated exception, design-record
  §6), reverse-filled across rooms, capped at net loaded
  (`ReturnExceedsLoadedError`, 400).
- **Merged rollup** — `merged_items` on the stage detail and as the load/return
  response: `planned_total`, `loaded_total`, `returned_total`, `overflow`,
  `net_consumed`, `remaining_to_load` per item.

### Files

- Edit: `app/schemas/mass_stages.py` (+`LoadRequest`, `ReturnRequest`,
  `MergedItem`; `merged_items` on `MassStageDetail`),
  `app/services/mass_staging.py` (+`load_item`, `return_item`, `_item_rooms`),
  `app/routers/mass_stages.py` (+`_merged_items`, `/load`, `/return`).
- New: `tests/conftest.py` (the `db` fixture), `tests/test_mass_staging_load.py`
  (7 DB integration tests).

### DB test harness (new for the repo)

`tests/conftest.py` provides a `db` fixture: a session joined to an external
transaction via SQLAlchemy 2.0 `join_transaction_mode="create_savepoint"`, so
service `commit()`s become savepoint releases and everything is rolled back at
teardown. Requires Postgres (`DATABASE_URL`); **skips** if unreachable so the
pure suite still runs without a DB. This is the substrate for any future
DB-bound tests.

### Decisions realized

- Load locks the **item row first**, then reads the per-room `loaded_quantity`
  fresh under the lock → concurrent loads of the same item serialise correctly.
- The overflow lands on the last room's WO (allocator), preserving per-WO
  attribution even for the merged line.
- Return writes **zero** transactions (verified by test) — the only place stock
  moves without an append-only row.

### Deviations

None.

## Verification (all green)

From `backend/` with the venv:
1. `python -c "import app.main"` → 13 `/mass-stages` routes (11 + load + return).
2. `pytest -q` → **109 passed** (102 + 7 DB integration tests, run against
   Postgres; they skip with no DB).
3. Real-commit smoke (separate from the rolled-back harness): load 16 of a
   10+5-planned item → dispenses `10 @ WO-1`, `6 @ WO-2`, stock −16; return 4 →
   stock +4 with **no** new transaction rows; temp data deleted afterward.
4. Concurrency: per-item `FOR UPDATE` mirrors the trusted `apply_transaction`
   lock; true multi-connection race testing is out of scope (single-threaded
   correctness + proven lock reuse).

## Backend complete

Phases 2–5 deliver the full mass-staging backend: schema, domain logic,
planning CRUD, and load/return. Remaining work is all frontend + docs:

- **Phase 6** — Mass Stage page, planning UI.
- **Phase 7** — loading + returns UI (merged list, Staged button, Unused materials).
- **Phase 8** — Scan/Stock by-room mid-job dispense.
- **Phase 9** — living-doc reconcile, palette polish, regression.
