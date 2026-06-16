# Phase 3 — Domain Logic & Errors *(implemented)*

> **Status:** ✅ Implemented & verified 2026-06-16. Pure domain layer — no DB,
> no HTTP, no wiring. Rationale: [`phase-1-design-record.md`](phase-1-design-record.md)
> §3–§4, §8.

## What shipped

The pure business logic Phases 4–5 will call, plus the domain error vocabulary
they raise. Mirrors `app/domain/quantity.py` (framework-free, `Decimal`,
`DomainError`s, exhaustively unit-tested).

### Files

- `backend/app/domain/errors.py` — +6 `DomainError` subclasses.
- `backend/app/domain/mass_staging.py` — new pure module.
- `backend/tests/test_mass_staging.py` — new tests (24 cases).

### Domain errors added

`StageNotFoundError`, `RoomNotFoundError`, `StageItemNotFoundError`,
`DuplicateBuildingStageError` (all raised by services in P4),
`InvalidStageTransitionError(current, target)` and
`ReturnExceedsLoadedError(requested, returnable)` (raised by the domain
functions below; carry structured attributes like `NegativeQuantityError`).
HTTP mapping in `routers/_errors.py` is **deferred to Phase 4** (no routes yet).

### `app/domain/mass_staging.py`

- **Status vocabulary** — `STATUS_PLANNING/LOADING/COMPLETED`, `ALL_STATUSES`,
  `ALLOWED_TRANSITIONS` (forward-only: planning→loading→completed). Text
  constants, mirroring `roles.py`.
- **Dataclasses** (frozen, opaque `key`): `RoomPlan(key, planned, loaded=0)`,
  `RoomLoaded(key, loaded, returned=0)`, `Allocation(key, quantity)`. The
  service builds these from ORM rows and maps results back, so the module never
  imports SQLAlchemy.
- **`allocate_load(rooms, quantity) -> [Allocation]`** — fills rooms in
  `sort_order` up to `planned - loaded`; overflow beyond total planned merges
  onto the last room; under-load stops early (later rooms omitted). One
  allocation per room, in order. Empty `rooms` → `ValueError` (caller-misuse
  guard; the service guards "item not planned" with `StageItemNotFoundError`
  first). `quantity` assumed validated > 0 upstream.
- **`allocate_return(rooms, quantity) -> [Allocation]`** — reverse-fill (last
  room gives back first), capped at `Σ(loaded - returned)`; over-return raises
  `ReturnExceedsLoadedError`.
- **`validate_transition(current, target)`** — raises
  `InvalidStageTransitionError` for anything outside the forward steps
  (covers backward, same-state, and unknown statuses).
- **Predicates** — `can_edit_plan(status)` (== planning),
  `can_load(status)` (== loading; return reuses it).

### Design choices realized

- Allocation inputs/outputs are opaque-keyed dataclasses → the domain stays
  framework-free and the functions are trivially unit-testable.
- Fill-in-order with exact `Decimal` arithmetic → no proportional rounding
  (the reason "fill in planned order" was chosen over "proportional").
- Non-re-validation of `quantity > 0` matches the `domain.quantity` stance
  (positivity is a schema/boundary concern).

### Deviations from plan

None.

## Verification (all green)

From `backend/` with the venv:
1. `python -c "import app.domain.mass_staging"` → imports cleanly.
2. `pytest tests/test_mass_staging.py -q` → 24 passed (load fill/overflow/
   under-load/incremental/empty; return reverse-fill/caps/attrs; transition
   matrix incl. unknown statuses; predicate truth tables).
3. `pytest -q` → 84 passed (was 60; +24), nothing else regressed.

## Next

Phase 4 — `schemas/mass_stages.py`, `services/mass_staging.py` (CRUD with the
one-active-per-building guard, cascade deletes, status PATCH), `routers/
mass_stages.py` (Supervisor+), registration in `main.py`, and the
`routers/_errors.py` HTTP mapping for the six new errors. Planning backend only;
**no stock touched** (load/return is P5).
