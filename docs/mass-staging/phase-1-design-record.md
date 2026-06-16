# Phase 1 — Design Record

> **Phase goal:** lock the full design rationale, data contracts, algorithms,
> and invariants so every later phase builds against a fixed target instead of
> re-deriving decisions per prompt. **No code, no schema, no behavior change.**
> Companion to [`roadmap.md`](roadmap.md) (the index); this file is the deep
> "why + exact contract." Mirrors the repo's existing `docs/plan-*.md` records.

---

## 1. Scope of Phase 1

**In scope:** this design record, the roadmap anchor (already written), and a
one-row stub in `spec.md`'s Decisions Log noting the feature is in progress.

**Out of scope (deferred to P2+):** ORM models, Alembic migration, domain
module, services, routers, schemas, frontend, tests. Nothing executable changes
in Phase 1.

**Done-line:** both docs reviewed and agreed; Decisions Log stub added; reviewer
confirms the contract below is what we build.

---

## 2. Rationale behind each locked decision

| # | Decision | Why this over the alternative |
|---|---|---|
| 1 | One WO per room; items plan under a room | Matches step 3 literally ("workorder# and room number" entered together). Room becomes the natural grouping unit; WO is an attribute, so per-room dispense attribution is trivial. |
| 2 | Loading = real `dispense` on the room's WO | Keeps one ledger / one source of truth for stock. Mass-stage tables only reference the existing transaction semantics rather than inventing a parallel stock log. |
| 3 | Store planned **and** loaded per room-item | Estimates and reality diverge (box-of-4 packaging). Keeping both makes overflow derivable and lets the supervisor see plan-vs-actual without a second system. |
| 4 | Returns = silent stock-add, no ledger row | The user's explicit choice. Returns are a stage-internal reconciliation, not a floor transaction. Trade-off accepted and documented in §6. |
| 5 | `planning → loading → completed` | Distinct guard rails per phase: planning is free editing with zero stock risk; loading is where stock moves; completed freezes the record. |
| 6 | Merge same item across rooms; split behind the scenes | The supervisor loads a truck by item, not by room. One "spray paint × 5" line is the real-world action; the per-room split is bookkeeping the app does, not a chore for the user. |
| 7 | Fill in planned order; overflow → last room | Deterministic and tap-free at load time. See §4 for the exact algorithm and why "last room" absorbs overage. |
| 8 | Overflow derived, never stored | `Σloaded − Σplanned` is always computable; a stored column would be a denormalized value that can drift. |
| 9 | Mid-job extras = plain dispense, not a stage row | Step 13 is an unplanned grab; forcing it into the plan would pollute the estimate. Room→WO lookup still comes from the stage so the WO is correct. |
| 10 | One active stage per building | Prevents two supervisors fragmenting one building's plan into rival lists. Enforced at the DB level (partial unique index) so it cannot be raced around. |
| 11 | Supervisor / Admin / Owner only | Mirrors the existing History/stock gate; the floor crew (Technician) keeps the streamlined dispense-only flow and never sees staging. |

---

## 3. State machine

```
        Save Mass Stage              Mark Completed
planning ───────────────▶ loading ──────────────▶ completed
   │                         │                         (terminal)
   └── delete ──────────────┴── delete ──────────────── delete
```

| State | Plan (rooms/items) | Load | Return | Stock moves |
|---|---|---|---|---|
| `planning` | editable | ✗ | ✗ | no |
| `loading` | read-only | ✓ | ✓ | yes (load only) |
| `completed` | read-only | ✗ | ✗ | no |

- **`planning → loading`** is triggered by the **Save Mass Stage** action
  (default #2). Load/return require `loading`.
- **`loading → completed`** is an explicit "Mark Completed" close. The
  *Unused materials* (return) step happens **while in `loading`**, just before
  marking completed — the stage stays in `loading` from the first truck load
  until the building is finished and leftovers are entered.
- No backward transitions (a written dispense is real; reverting status would
  not un-write it). `delete` is allowed from any state (Supervisor+) and cascades
  rooms/items but **does not** reverse dispenses already written.

> **Open point for review (R1):** should returns be permitted after `completed`
> (i.e. reopen for a late leftover)? **Default: no** — completed is terminal.
> Flag if you want a reopen path.

---

## 4. Allocation algorithms (pure domain logic — Phase 3 implements)

Both operate on the rooms that planned a given item, in `sort_order`. They are
pure functions (no DB/HTTP) so they unit-test exhaustively.

### 4.1 `allocate_load(rooms, quantity) -> [(room_id, qty)]`

Each room carries `planned` and `already_loaded`. Walk rooms in `sort_order`:

```
remaining = quantity
for room in rooms (ascending sort_order):
    capacity = max(0, room.planned - room.already_loaded)
    take = min(remaining, capacity)
    allocate take to room; remaining -= take
# overflow: anything past total remaining planned capacity
if remaining > 0:
    add remaining to the LAST room
```

- **Under-load** (`quantity` < total remaining capacity): filling stops early;
  later rooms get 0 this event. ✓ "under-load stops filling early."
- **Overflow** (`quantity` > total remaining capacity): the surplus lands on the
  last room's WO. ✓ "overflow → last room."
- **Order-independent total:** incremental loads sum to the same per-room result
  as one combined load (verified below).

**Worked example** — R101 planned 10, R102 planned 5 (order 1, 2), load 16 in one go:

| Room | capacity | allocated | loaded after |
|---|---|---|---|
| R101 | 10 | 10 | 10 |
| R102 | 5 | 5 (+1 overflow) | 6 |

Total 16; overflow = 16 − 15 = 1 on R102's WO.

**Incremental check** — load 8 then 8: R101→8/0, then R101→+2, R102→+5, overflow +1 → R101=10, R102=6. Identical.

**Guard:** loading an item that no room in the stage planned → `StageItemNotFoundError`
(that path is the mid-job plain dispense, not a stage load).

### 4.2 `allocate_return(rooms, quantity) -> [(room_id, qty)]`

Returns walk rooms in **reverse** `sort_order` (overage/leftover comes off the
last-filled room first), capped at each room's net loaded:

```
remaining = quantity
for room in rooms (descending sort_order):
    capacity = max(0, room.loaded - room.already_returned)
    take = min(remaining, capacity)
    return take from room; remaining -= take
if remaining > 0:
    raise ReturnExceedsLoadedError   # total returnable = Σ(loaded - returned)
```

> **Open point for review (R2):** reverse-fill is a sensible default (give back
> overflow first) but the per-room return split only affects per-room *net
> consumed* reporting — it never writes a ledger row and never changes which WO
> was billed (loads already did that). Flag if you'd prefer building-level-only
> return tracking instead of per-room.

### 4.3 `validate_transition(current, target) -> None | raises`

Allowed: `planning→loading`, `loading→completed`. Everything else (including any
backward move) raises `InvalidStageTransitionError`.

---

## 5. API contract (Phase 4 = CRUD, Phase 5 = load/return)

All routes under `/mass-stages`, gated `require_min_role(ROLE_SUPERVISOR)`.

| # | Method | Path | Body | Success | Phase | Notes |
|---|---|---|---|---|---|---|
| 1 | POST | `/mass-stages/` | `{building_name}` | 201 `MassStageSummary` | 4 | 400 `DuplicateBuildingStageError` if an active stage exists for the building. Starts `planning`. |
| 2 | GET | `/mass-stages/` | — (`?status=`) | 200 `list[MassStageSummary]` | 4 | Optional status filter. |
| 3 | GET | `/mass-stages/{id}` | — | 200 `MassStageDetail` | 4 | Rooms + items + merged rollup. 404 if unknown. |
| 4 | PATCH | `/mass-stages/{id}` | `{building_name?, status?}` | 200 `MassStageSummary` | 4 | Status change validated by §4.3 → 400 `InvalidStageTransitionError`. |
| 5 | DELETE | `/mass-stages/{id}` | — | 204 | 4 | Cascades rooms/items; does **not** reverse dispenses. |
| 6 | POST | `/mass-stages/{id}/rooms` | `{room_number, work_order_number}` | 201 `RoomDetail` | 4 | `planning` only. `UNIQUE(stage_id, room_number)`. |
| 7 | PATCH | `/mass-stages/{id}/rooms/{room_id}` | `{room_number?, work_order_number?}` | 200 `RoomDetail` | 4 | `planning` only. |
| 8 | DELETE | `/mass-stages/{id}/rooms/{room_id}` | — | 204 | 4 | `planning` only; cascades items. |
| 9 | POST | `/mass-stages/{id}/rooms/{room_id}/items` | `{item_id, planned_quantity}` | 201 `StageItemDetail` | 4 | `planning` only. 409 if item already on that room (use PATCH). |
| 10 | PATCH | `/mass-stages/{id}/rooms/{room_id}/items/{stage_item_id}` | `{planned_quantity}` | 200 `StageItemDetail` | 4 | `planning` only. |
| 11 | DELETE | `…/items/{stage_item_id}` | — | 204 | 4 | `planning` only. |
| 12 | POST | `/mass-stages/{id}/load` | `{item_id, quantity}` | 200 `MergedItem` | 5 | `loading` only. Atomic per-room dispenses. 400 overdraft / item-not-planned. |
| 13 | POST | `/mass-stages/{id}/return` | `{item_id, quantity}` | 200 `MergedItem` | 5 | `loading` only. 400 `ReturnExceedsLoadedError`. Silent stock-add. |

---

## 6. The return audit asymmetry (accepted invariant)

Loading writes `dispense` rows (stock ↓). A return adds stock back **without** a
transaction row (decision #4). Consequence, stated plainly so nobody "fixes" it
later by accident:

- The transaction ledger shows **gross dispensed** (what left the shelf onto the
  truck), which will be ≥ what was actually consumed.
- **Actual consumption** = `Σloaded − Σreturned`, available only from the stage
  tables (the `MergedItem` rollup).
- On-hand item quantity stays correct (load decrements, return increments).
- This is the **only** place stock changes without an append-only row. It is
  deliberate and isolated to the return path; do not generalize it.

---

## 7. Schema shapes (field-level; Phase 4 formalizes as Pydantic)

```
MassStageCreate   { building_name: str (non-blank) }
MassStageUpdate   { building_name?: str, status?: "planning"|"loading"|"completed" }
MassStageSummary  { id, building_name, status, room_count, item_count,
                    created_at, created_by_username? }
MassStageDetail   { id, building_name, status, created_at,
                    rooms: [RoomDetail], merged_items: [MergedItem] }
RoomDetail        { id, room_number, work_order_number, sort_order,
                    items: [StageItemDetail] }
StageItemDetail   { id, item_id, item_name, item_barcode,
                    planned_quantity, loaded_quantity, returned_quantity }
MergedItem        { item_id, item_name, item_barcode,
                    planned_total, loaded_total, returned_total,
                    overflow,            # max(0, loaded_total - planned_total)
                    net_consumed,        # loaded_total - returned_total
                    remaining_to_load }  # max(0, planned_total - loaded_total)
RoomCreate        { room_number: str (non-blank), work_order_number: str (non-blank) }
StageItemCreate   { item_id: UUID, planned_quantity: Decimal > 0 }
LoadRequest       { item_id: UUID, quantity: Decimal > 0 }
ReturnRequest     { item_id: UUID, quantity: Decimal > 0 }
```

---

## 8. Validation rules (consolidated)

| Rule | Enforced by |
|---|---|
| `building_name` non-blank (stripped) | schema + service |
| `room_number`, `work_order_number` non-blank | schema |
| `planned_quantity`, load/return `quantity` > 0 | schema (Pydantic) |
| One active stage per building | DB partial unique index + service pre-check (`DuplicateBuildingStageError`) |
| `UNIQUE(stage_id, room_number)` | DB constraint |
| `UNIQUE(room_id, item_id)` | DB constraint (409 on duplicate add) |
| Room/item writes only in `planning` | service (`InvalidStageTransitionError`/state guard) |
| Load/return only in `loading` | service |
| Load item must be planned in the stage | service (`StageItemNotFoundError`) |
| Return ≤ net loaded | domain (`ReturnExceedsLoadedError`) |
| Dispense cannot drive stock below zero | existing `domain.quantity.apply_delta` (`NegativeQuantityError`) |
| Supervisor+ on every route | router (`require_min_role`) |

New domain errors introduced (Phase 3): `StageNotFoundError`, `RoomNotFoundError`,
`StageItemNotFoundError`, `DuplicateBuildingStageError`, `InvalidStageTransitionError`,
`ReturnExceedsLoadedError` — each mapped to HTTP in `routers/_errors.py`.

---

## 9. Open points for review

- **R1** — Returns after `completed`? Default **no** (terminal). §3.
- **R2** — Per-room reverse-fill returns vs building-level-only return tracking.
  Default **per-room reverse-fill**. §4.2.
- **R3** — `item_count` in `MassStageSummary`: distinct items across the stage,
  vs total planned line-items. Default **distinct items**.

None of these block Phase 2 (data model); they affect Phase 4/5 service detail
and can be settled when those phase docs are authored.

---

## 10. Phase doc index

- [`roadmap.md`](roadmap.md) — anchor + all 9 phases.
- `phase-1-design-record.md` — this file.
- `phase-2-data-model.md` … `phase-9-docs-polish.md` — authored after each phase's implementation.
