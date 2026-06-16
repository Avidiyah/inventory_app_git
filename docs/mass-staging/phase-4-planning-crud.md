# Phase 4 — Planning CRUD *(implemented)*

> **Status:** ✅ Implemented & verified 2026-06-16. Planning backend over HTTP,
> Supervisor+. **No stock touched** (load/return is Phase 5). Design source:
> [`phase-1-design-record.md`](phase-1-design-record.md) §3, §5, §7, §8.

## What shipped

The planning half of mass-staging: create a stage per building, add rooms (one
work order each), add/edit/remove planned items per room, list/read/transition/
delete stages. Mirrors the existing item stack (thin router → service → builder
helpers; `require_min_role`, `to_http`, `get_db`).

### Files

- New: `app/schemas/mass_stages.py`, `app/services/mass_staging.py`,
  `app/routers/mass_stages.py`, `tests/test_mass_stages_api.py`.
- Edit: `app/domain/errors.py` (+`StageStateError`), `app/routers/_errors.py`
  (+7 mappings), `app/main.py` (register router).

### Routes (all `require_min_role(supervisor)`)

| Method | Path |
|---|---|
| POST | `/mass-stages/` (201 `MassStageSummary`; 400 duplicate active building) |
| GET | `/mass-stages/` (`?status=`) |
| GET | `/mass-stages/{id}` (`MassStageDetail`: rooms → items) |
| PATCH | `/mass-stages/{id}` (rename / status transition) |
| DELETE | `/mass-stages/{id}` (cascades rooms/items) |
| POST | `/mass-stages/{id}/rooms` |
| PATCH/DELETE | `/mass-stages/{id}/rooms/{room_id}` |
| POST | `/mass-stages/{id}/rooms/{room_id}/items` (upsert) |
| PATCH/DELETE | `/mass-stages/{id}/rooms/{room_id}/items/{stage_item_id}` |

### Decisions realized / deviations

- **One generic state guard** `StageStateError` (400) for "operation not allowed
  in the current status" — used for plan edits outside `planning`, and the
  room-number uniqueness conflict (with a specific message). Avoids niche error
  proliferation; reused in P5 for load/return.
- **`add_item` upserts** by `(room_id, item_id)` — re-adding an item sets its
  planned quantity. **Deviation** from the design-record's "409 → use PATCH":
  idempotent upsert is simpler for the search-and-add UI and needs no new error.
  PATCH-by-`stage_item_id` is kept for explicit edits.
- Detail is rooms+items only; the `merged_items` rollup and the
  `loaded`/`returned` movement are **Phase 5** (the columns exist and read 0).
- `item_count` in the summary = distinct items across the stage (design R3).
- Status transitions go through `domain.mass_staging.validate_transition`;
  reaching `completed` stamps `completed_at`. Editability via `can_edit_plan`.

### Testing

Pure tests only this phase (per the agreed call — the repo has no DB harness;
it arrives in P5). `tests/test_mass_stages_api.py` covers schema validation,
the Supervisor+ gate on all 11 routes (parametrized introspection), and the
response builders. DB-bound behavior verified by a self-cleaning script (below).

## Verification (all green)

From `backend/` with the venv:
1. `python -c "import app.main"` → imports; 11 `/mass-stages` routes registered.
2. `pytest -q` → **102 passed** (was 84; +18).
3. Self-cleaning DB smoke: create stage; second active stage for same building →
   `DuplicateBuildingStageError`; add rooms; `add_item` upsert updates planned
   qty (10 → 12); detail shows 2 rooms; `planning → loading` ok; editing while
   `loading` → `StageStateError`; `loading → planning` → `InvalidStageTransitionError`;
   `delete_stage` cascades rooms away. Script deletes its test rows at the end.

## Next

Phase 5 — load + return services/routes (atomic per-room dispenses under the
item row lock; silent stock-add returns; `merged_items` rollup on detail) **and**
the DB/integration test harness for the concurrency-sensitive paths.
