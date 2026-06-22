# Phase 11 — Work-order assignment + role-scoped visibility *(implemented)*

> **Status:** ✅ Implemented 2026-06-22. Backend + static checks pass; **browser
> validation handed to the user** (manual-validation preference). Builds on
> Phase 10 (saved work orders = `mass_stage_rooms`). Also a UI-only relabel:
> "Building / Room Number" → **"Community / Unit Number"**.

## Problem

Phase 10 made every active work order visible to every Supervisor+ on the scan
gate. Crews need ownership: a technician should see only the work orders
**assigned to them**, a supervisor only the ones **they created**, and
admins/owners **all** of them. Assignment is optional and is a Supervisor+
action (you assign to technicians).

## Visibility rule

| Role | Sees which work orders (rooms) |
|---|---|
| Technician | `assigned_to_id == me` |
| Supervisor | `created_by_id == me` |
| Admin / Owner | all |

Applied to the scan-gate cards (`GET /mass-stages/active-rooms`) and the Mass
Stage stage list (`GET /mass-stages/`, by `MassStage.created_by_id` for
supervisors). Always still excludes `completed` stages and blank work orders.

## Data model

`mass_stage_rooms` gains two nullable FKs to `users` (migration
`c2e4f6a8d0b1`, down_revision `c7e9a1b3d5f8`):
- `created_by_id` — work-order author (drives supervisor visibility).
- `assigned_to_id` — the technician it's assigned to (NULL = unassigned).

Both plain (non-cascade), each indexed for the scoped queries. **No backfill**:
pre-existing rooms have NULL for both, so they're visible only to Admin/Owner.
`MassStageRoom` adds viewonly `creator` / `assignee` relationships for username
display (no back-populate on `User`, like `Transaction.voided_by_id`).

## Backend

- `app/domain/errors.py` (+ `_errors.py`) — `InvalidAssigneeError` (400):
  a work order may be assigned only to a technician.
- `services/mass_staging.py`:
  - `_validate_assignee` — None ok; else must be an existing technician.
  - `_room_visible_to(room, user)` — the visibility rule above.
  - `add_room` / `add_room_to_building` — accept `created_by_id` +
    `assigned_to_id` (validated); creator is the actor.
  - `assign_room(db, stage_id, room_id, *, assigned_to_id)` — set/clear an
    assignee; allowed in planning or loading, not on a completed stage.
  - `list_active_rooms(db, *, user)` and `list_stages(db, *, status, user)` —
    role-scoped; active-rooms also returns creator/assignee usernames.
- `routers/mass_stages.py`:
  - `GET /active-rooms` gate lowered to `get_current_user` (any authenticated;
    scoped server-side) — technicians now use it.
  - New `PATCH /{stage_id}/rooms/{room_id}/assign` (Supervisor+) → `RoomAssign`.
  - `quick-room` / `add_room` thread creator + assignee; `list_stages` passes
    the user; `_room_detail` / active-rooms builder include assignee fields.
- Schemas: `RoomAssign`; `assigned_to_id` on `QuickRoomCreate` / `RoomCreate`;
  assignee fields on `ActiveRoom` / `RoomDetail`.

## Frontend

- **Scan gate** (`transaction.html` / `transactions.js`): the cards section now
  shows for **all roles** (server-scoped). Technicians see only their assigned
  cards — the quick-add form and the free-text gate are hidden for them; an
  empty list reads "No work orders assigned to you." Supervisor+ keep the
  quick-add (now with an optional **"Assign to"** technician `<select>` from
  `apiListUsers`) and the free-text fallback; their cards show an
  `Assigned: <name>` / `Unassigned` badge.
- **Mass Stage page** (`massStage.js`): each unit's editor (planning) gains an
  **"Assign to"** technician `<select>` (current assignee preselected) wired to
  `apiAssignRoom` via a new `assign-room` action; the assignee shows in the unit
  summary.
- **Relabel (UI text only):** "Building"→"Community" (e.g. *Scholars*),
  "Room"/"Room #"→"Unit"/"Unit Number" (e.g. *1121*), card meta `Room`→`Unit`,
  "Next Room"→"Next Unit", etc. Columns/IDs/data-attrs unchanged.

## Verification

1. `pytest -q` → **135 passed** (created_by recorded; non-technician assignee →
   `InvalidAssigneeError`; `assign_room` set/clear; per-role scoping of
   `list_active_rooms` + `list_stages`; active-rooms requires only auth).
2. `alembic upgrade head` ↔ `downgrade -1` clean; single head.
3. `node --check` on `transactions.js`, `massStage.js`, `api.js`.
4. **Manual (handed off):** Supervisor adds Community *Scholars* / Unit *1121*,
   assigns it to a technician + leaves one unassigned; that technician sees only
   the assigned card (no free-text box); an admin sees all; a second supervisor
   sees none of the first's.

## Out of scope / known limits

- Transactions page rework (explicitly next).
- Find-or-create mixed creators: a unit added by supervisor B into supervisor
  A's community is B's (visible to B on the gate), but the community card on the
  Mass Stage page is scoped by `stage.created_by` (A's). Acceptable; revisit if
  it bites.
- Pre-existing rooms (NULL creator/assignee) are Admin/Owner-only.
