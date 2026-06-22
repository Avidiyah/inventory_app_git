# Mass-Staging — Roadmap & Design Anchor

> **Status:** ✅ COMPLETE (P1–9), plus **Phase 10** (saved work orders /
> cards-first scan gate) and **Phase 11** (work-order assignment + role-scoped
> visibility + Community/Unit relabel), both 2026-06-22. Backend (data model,
> domain logic, planning CRUD, load/return + merged list, ownership/assignment)
> and full UI (planning, loading/returns, by-room dispense, cards-first gate,
> assignment), with the living docs reconciled. Test count 60 → 135. This
> remains the source-of-truth anchor. See `phase-10-saved-workorders.md` and
> `phase-11-workorder-assignment.md`.
> Each of the 9 phases below gets its own doc in this folder
> (`phase-2-data-model.md`, etc.): the Plan tool is used at the **start** of a
> phase to plan its implementation, and the phase doc is authored **after**
> implementation as a record. Keep the locked-decisions and data-model sections
> here in sync if anything changes.

---

## Problem

Employees grab material in batches for an entire building rather than per
work order. Items (e.g. a can of spray paint) are often used partially and
returned. The current app only supports single-item scan-in/scan-out tied to
a free-text work order; there is no persisted notion of a building, its
rooms, or a planned staging list. Mass-Staging adds that.

### Real-world workflow (supervisor)

1. Sit down with a stack of work orders for one building.
2. Create a stage: enter **Building Name + #**.
3. Add a room: **room # + work order #**.
4. Estimate materials for that room.
5. Search items and add them to the room as **planned** (not a transaction).
6. Save, **Next Room**, repeat 3–5.
7. **Save Mass Stage** → consolidates all room-items into one load list.
8. Go to Scan / Stock loading view.
9–11. Per merged item, tap **Staged**, enter quantity, scan, load onto the
   truck. Loading removes from stock (real dispense).
12. Drive to the building and stage materials.
13. If unplanned material is needed mid-job, dispense it from Scan / Stock by
   entering the **room #** (the app finds that room's work order); this is a
   plain dispense, **not** added to the stage.
14. At building completion, **Unused materials** lets the supervisor enter
   leftovers, which are added back to stock.

---

## Locked decisions

| # | Topic | Decision |
|---|---|---|
| 1 | Room ↔ WO | **One work order per room.** Items plan *under a room*. |
| 2 | Staging | Loading = real `dispense` tied to the room's WO. Loaded qty may exceed planned; overflow is tracked. |
| 3 | Plan vs actual | Both stored per room-item (`planned_quantity`, `loaded_quantity`). |
| 4 | Returns | Silent stock-add, **stage-tracked only, no ledger row**. |
| 5 | Lifecycle | `planning → loading → completed`. |
| 6 | Consolidation | Merge same item across rooms into one load line; **split into per-room dispenses behind the scenes**. |
| 7 | Split rule | Fill rooms in planned order; overflow → last room's WO; under-load stops filling early. |
| 8 | Overflow | Derived, never stored: per-item `Σloaded − Σplanned`. |
| 9 | Mid-job extras | Plain scan-and-go dispense; room→WO looked up from the stage; not added to the stage. |
| 10 | Building uniqueness | One active (non-completed) stage per building. |
| 11 | Access | Supervisor / Admin / Owner. Technicians excluded. |

### Carried-in defaults (override any per-phase if desired)

1. Building identity stored as a single free-text `building_name` label ("Building Name + #").
2. The **Save Mass Stage** action flips status `planning → loading`.
3. Plan (rooms/items) is editable **only in Planning**; Loading is read-only plan + load/return.
4. Stage delete is allowed (Supervisor+) but **never reverses dispenses already written**.

---

## Data model (3 new tables)

**`mass_stages`** — `id`, `building_name`, `status` (`planning`/`loading`/`completed`),
`created_by_id`, `created_at`, `updated_at`, `completed_at?`.
Partial unique index `UNIQUE(building_name) WHERE status <> 'completed'` enforces
one-active-per-building at the DB level.

**`mass_stage_rooms`** — `id`, `stage_id` (FK→stages, CASCADE), `room_number`,
`work_order_number`, `sort_order` (drives fill-in-order + overflow→last),
`created_at`. `UNIQUE(stage_id, room_number)`.

**`mass_stage_items`** — `id`, `room_id` (FK→rooms, CASCADE), `item_id` (FK→items),
`planned_quantity`, `loaded_quantity` (default 0), `returned_quantity` (default 0),
`created_at`. `UNIQUE(room_id, item_id)`.

Derived (never stored): per-item **overflow** = `Σloaded − Σplanned`;
**net consumed** = `Σloaded − Σreturned`.

The `transactions` table is **not** modified. Loading writes ordinary `dispense`
rows (WO = room's WO), consistent with the lean-audit-row pattern. Stage tables
are the source of truth for the stage view; the ledger remains the source of
truth for stock.

### Two stock-touching actions

- **Load** (`POST /mass-stages/{id}/load` `{item_id, quantity}`): under a single
  `SELECT … FOR UPDATE` on the item, allocate qty across rooms that planned it
  (fill-in-order, overflow→last), create **one `dispense` per room allocation**
  + bump each room-item's `loaded_quantity` — all atomic. Overdraft guarded by
  `domain.quantity.apply_delta`.
- **Return** (`POST /mass-stages/{id}/return` `{item_id, quantity}`): under the
  item lock, add qty back to `item.quantity` with **no transaction row**, and
  increment `returned_quantity` (reverse-fill). Capped at net loaded.

---

## Layering (respects `domain → services → routers`)

- `domain/mass_staging.py` (pure, unit-tested): `allocate_load`, `allocate_return`, `validate_transition`.
- `services/mass_staging.py`: CRUD + load/return orchestration (reuses `domain.quantity.apply_delta`).
- `routers/mass_stages.py` (`/mass-stages`, Supervisor+).
- `schemas/mass_stages.py`: create/response/detail + merged-load + load/return bodies.
- Frontend: `static/pages/mass-stage.html`, `static/views/massStage.js`, `api.js` helpers, nav + `PAGE_ACCESS`.

---

## Phase roadmap

Dependency-ordered. Backend (P2–P5) is fully shippable and test-covered before
any frontend. Each phase maps to one Plan-tool invocation and has a clear
done-line so scope cannot bleed across prompts.

| P | Phase | Layer | Depends on | Stock impact | Verify |
|---|---|---|---|---|---|
| 1 | Design record + roadmap docs ✅ | docs | — | none | review |
| 2 | Data model + migration ✅ | DB | 1 | none | `alembic up/down` |
| 3 | Domain logic + errors ✅ | domain | 2 | none | `pytest` (pure) |
| 4 | Planning CRUD (schemas/service/router) ✅ | service+http | 3 | none | `pytest` + curl |
| 5 | Load + Return + merged list ✅ | service+http | 4 | **yes** | `pytest` |
| 6 | Frontend — Planning UI ✅ | frontend | 4 | none | manual |
| 7 | Frontend — Loading + Returns UI ✅ | frontend | 5,6 | yes | manual |
| 8 | Scan/Stock by-room mid-job dispense ✅ | frontend | 5,6 | yes | manual |
| 9 | Living-doc reconcile + polish + regression ✅ | docs+css | all | — | `pytest` + manual |

P2→P5 are strictly linear. P6 can start once P4 lands. P7/P8 need P5. P9 closes out.
The one architectural watch-item is **Phase 5's atomic multi-dispense** — the only
novel concurrency surface — so it carries the heaviest test load.

### Phase 1 — Design record & roadmap docs *(no code)*
- **Files:** this `roadmap.md`; per-phase docs authored after each phase's implementation; Decisions Log stub in `spec.md`.
- **Done:** docs reviewed; no behavioral change.

### Phase 2 — Data model & migration
- **Files:** `app/models.py` (+3 ORM classes); new `alembic/versions/<rev>_add_mass_staging.py` (down-revision `a7c9e1f3b5d2`); 3 tables + partial unique index.
- **Done:** `alembic upgrade head` then `downgrade -1` clean on local Postgres; models import; no routes yet.

### Phase 3 — Domain logic + errors *(pure, no DB/HTTP)*
- **Files:** new `app/domain/mass_staging.py` (`allocate_load`, `allocate_return`, `validate_transition`); `app/domain/errors.py` (+`StageNotFoundError`, `RoomNotFoundError`, `StageItemNotFoundError`, `DuplicateBuildingStageError`, `InvalidStageTransitionError`, `ReturnExceedsLoadedError`).
- **Tests:** allocation across multi-room / overflow / partial; transition matrix.
- **Done:** new unit tests pass; nothing wired in yet.

### Phase 4 — Planning CRUD
- **Files:** new `app/schemas/mass_stages.py`; new `app/services/mass_staging.py` (create w/ one-active guard, room add/edit/delete, planned-item add/update/delete, list, detail, status PATCH, stage delete); new `app/routers/mass_stages.py` (Supervisor+); register in `app/main.py`; map new errors in `routers/_errors.py`.
- **Tests:** CRUD happy paths, one-active-per-building, role gate 403, cascade deletes.
- **Done:** full planning backend end-to-end; **no stock touched**.

### Phase 5 — Load + Return + merged list
- **Files:** `services/mass_staging.py` (+`load_item`, `return_item`); `routers/mass_stages.py` (+`POST /{id}/load`, `POST /{id}/return`); detail response gains merged per-item rollup (planned/loaded/returned/overflow).
- **Invariants:** load = N atomic dispenses under one item lock, WO per room, overdraft guarded; return = silent stock-add, no ledger row, capped at net loaded.
- **Tests:** split correctness, overflow→last WO, overdraft 400, return cap, stock + txn-count assertions.
- **Done:** backend feature-complete and covered.

### Phase 6 — Frontend: Planning UI
- **Files:** new `static/pages/mass-stage.html`; nav button + `PAGE_ACCESS` in `views/nav.js`; new `static/views/massStage.js` (building cards → room cards → item cards, "Next Room", "Save Mass Stage"); `api.js` helpers; `main.js` wiring.
- **Done (manual):** create stage, add rooms/items, save → status `loading`.

### Phase 7 — Frontend: Loading + Returns UI
- **Files:** `views/massStage.js` (merged load list; per-item **Staged** button reusing `#scan-confirm-overlay` + scanner; quantity entry; **Unused materials** return inputs; status-driven view switch).
- **Done (manual):** stage items dispense to truck with correct WO split; returns add back silently; overflow visible.

### Phase 8 — Scan/Stock by-room mid-job dispense (step 13)
- **Files:** `static/pages/transaction.html` + `views/transactions.js` (a "by room" WO-picker sourced from stage rooms → reuses existing `POST /transactions/`); `api.js` lookup helper.
- **Done (manual):** pick building+room, scan, dispense tagged with that room's WO; no stage row created.

### Phase 9 — Living-doc reconcile + polish + regression
- **Files:** `spec.md` (feature row + page section + validation rules), `reference.md` (schema, routes, migration history), `interfaces.md` (models/schemas/services/router/view), Decisions Log entry; red/black/white palette polish; full `pytest` + manual smoke.
- **Done:** docs match code; suite green.

---

## Doc convention

- This folder (`docs/mass-staging/`) holds the roadmap (this file) plus one doc
  per phase, named `phase-<N>-<slug>.md`.
- The Plan tool is used at the **start** of each phase to plan its
  implementation; the phase doc is authored **after** that phase's
  implementation as a record of what shipped.
- Update the locked-decisions and data-model sections **here** if a phase forces a change.
