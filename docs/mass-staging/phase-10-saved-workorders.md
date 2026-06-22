# Phase 10 — Saved Work Orders (cards-first scan gate) *(implemented)*

> **Status:** ✅ Implemented 2026-06-22. Static + backend checks pass; **browser
> validation handed to the user** (per the manual-validation preference). This
> phase unifies the supervisor's "save work orders with rooms, then tap one to
> dispense" workflow with mass-staging — **no new table, no second system.**

## Problem

A supervisor must type a work-order number on every scan/stock transaction. The
real-world morning workflow is: receive a stack of work orders (each tied to a
room), enter them once, then just tap the right work order when scanning.
Mass-staging already models a **room carrying one work order** under a
**building stage**, so the requirement is a presentation change, not new data.

## The unified model (locked this session)

Saved work orders **are** mass-staging data — one storage model, two
presentations that differ only by a room-count display threshold:

- **Quick-add from the scan gate** captures **building + room + work order** and
  writes to the existing `mass_stages` / `mass_stage_rooms` tables:
  find-or-create the building's active (non-`completed`) stage, then append the
  room. The stage stays in `planning` (immediately scannable; the truck-load
  workflow remains optional).
- **Scan gate** shows every active room as a tappable work-order card (single-
  or multi-room alike). Tapping a card feeds its work order into the existing
  scan-and-go batch — a plain `dispense`, `transactions` untouched, **nothing
  written back to the stage** (locked decision #9).
- **Mass Stage page** shows a full planning card only when a building has
  **≥ 2 rooms**; single-room (or empty) buildings render as lightweight "Single
  work orders" entries. Adding a 2nd room to a building makes its card
  materialize automatically — the same data crossing a display threshold.

### Decisions (this phase)

| # | Topic | Decision |
|---|---|---|
| 12 | Saved WO storage | Reuse `mass_stages`/`mass_stage_rooms`; quick-add is find-or-create by building. No new table. |
| 13 | Card threshold | Mass Stage page renders a full card only for buildings with ≥ 2 rooms; single-room = lightweight entry. Display-only (data is always a stage). |
| 14 | Gate access | Cards-first gate + quick-add are **Supervisor+** for now. Technicians keep the free-text gate until the future "assign WOs to technicians" update gives them a scoped view. |

## What shipped

### Backend (`require_min_role(supervisor)`)

- `services/mass_staging.py` — `add_room_to_building(...)` (find-or-create the
  building's active stage, then reuse `create_stage` + `add_room`; race-safe via
  the existing partial unique index + `IntegrityError` handling) and
  `list_active_rooms(...)` (flat rooms across non-`completed` stages, skipping
  blank work orders, one eager-loaded query).
- `schemas/mass_stages.py` — `QuickRoomCreate {building_name, room_number,
  work_order_number}`, `ActiveRoom {stage_id, building_name, status, room_id,
  room_number, work_order_number, sort_order}`.
- `routers/mass_stages.py` — `POST /mass-stages/quick-room` (→ parent
  `MassStageSummary`) and `GET /mass-stages/active-rooms` (→ `list[ActiveRoom]`),
  both declared **before** `/{stage_id}` so the literal paths aren't parsed as a
  stage id.

### Frontend (Supervisor+)

- `static/api.js` — `apiQuickAddRoom`, `apiListActiveRooms`.
- `static/pages/transaction.html` + `static/views/transactions.js` — the
  `#wo-gate` becomes cards-first: `#wo-gate-cards` (tappable saved work orders)
  + a collapsible "Add a new work order" quick-add form. This **replaces** the
  Phase 8 two-`<select>` by-room picker. The free-text `#wo-gate-input` remains
  as the Technician surface and a Supervisor+ one-off fallback. The scan-and-go
  engine (`commitScannedItem`/`scanGoArmed`/`startBatch`) is unchanged.
- `static/views/massStage.js` — `renderStageList` splits stages by the
  ≥2-room threshold via `buildStageCard(stage, compact)` and `stageMetaText(...)`.
- `static/styles.css` — `.wo-card` grid + quick-add form; `.stage-card-compact`
  / `.ms-single-heading` for the lightweight entries (red/black/white tokens).

## Verification

1. `pytest -q` → **128 passed** (was 109; +quick-add/active-rooms DB tests and
   the parametrized Supervisor-gate test now covers both new routes).
2. `python -c "import app.main"` → `quick-room` + `active-rooms` registered
   ahead of `/{stage_id}`.
3. `node --check` on `transactions.js`, `massStage.js`, `api.js` → all parse.
4. **Manual (handed off):** Supervisor → Scan/Stock → cards (empty first run) →
   "Add a new work order" Building A / 101 / WO123 → card appears, batch starts →
   scan a dispense → History shows it on WO123. Add Room 102 to Building A → a
   2nd card appears and Building A shows as a **card** on the Mass Stage page
   (single-room Building B stays in "Single work orders"). Technician sees only
   the free-text gate.

## Out of scope (future)

- Supervisor → technician work-order **assignment** + per-tech scoped cards
  (`assigned_to_id` not added now).
- Any change to load/return/planned-item behavior.
