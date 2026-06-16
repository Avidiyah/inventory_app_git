# Phase 8 — Scan/Stock By-Room Mid-Job Dispense *(implemented)*

> **Status:** ✅ Implemented 2026-06-16; static checks pass, **browser
> validation handed to the user**. Frontend only — reuses the scan-and-go flow
> and the Phase-6 `apiListStages` / `apiGetStage` wrappers. No backend change.

## What shipped

On the **Scan / Stock** work-order gate, a Supervisor+ can start a batch by
picking a **building + room** from the mass-staging plan instead of typing a work
order (workflow step 13). The page resolves that room's work order, fills the
existing gate input, and the normal scan-and-go dispense proceeds. The resulting
transaction is an **ordinary dispense** carrying that work order — **nothing is
written back to the stage** (locked decision #9); the stage stays the plan/load
record.

### Files (all edits)

- `static/pages/transaction.html` — inside `#wo-gate`: `#wo-gate-byroom-toggle`
  (`hidden`, Supervisor+) + `#wo-gate-byroom` (building `<select>`, room
  `<select>`, note).
- `static/views/transactions.js` — `apiListStages`/`apiGetStage` imports + refs;
  `byRoomToggle.hidden = tech || active` in `showScanGoState` (Supervisor+, gate
  only); `loadBuildings` / `loadRoomsForBuilding` / `pickRoom` / `resetByRoom`;
  `resetByRoom()` from `changeWorkOrder` + `resetBatch`; toggle/select wiring.
- `static/styles.css` — `#wo-gate-byroom` layout.

### Behavior / decisions

- **Building then room** (two selects), because room numbers are unique only
  within a building; the room option text shows `Room {n} — WO {wo}`, surfacing
  the room→WO mapping directly. Selecting a room sets the gate's work-order input.
- **Role-gated**: the toggle shows only for Supervisor+ and only on the gate;
  Technicians never see it and never call the (403-for-them) stages endpoint.
  Stages are fetched **lazily** when the picker is opened.
- **Active buildings only**: the building list filters out `completed` stages.
- `startBatch()` / `changeWorkOrder()` / `resetBatch()` are otherwise unchanged —
  the picker just feeds a work order into the existing flow.

## Verification

1. `node --check static/views/transactions.js` → OK. ✓
2. `_assemble_index` contains `wo-gate-byroom-toggle` + `#wo-gate-building` +
   `#wo-gate-room`. ✓
3. `pytest -q` → 109 passed (no backend change). ✓
4. **Manual (handed off):** as Supervisor on Scan / Stock → "Use a building &
   room" → pick a building + room → Start → commit a dispense → it shows in
   History on that room's work order, and the stage's loaded totals are
   unchanged. As a Technician, the by-room toggle is absent.

## Next

Phase 9 (final) — reconcile the living docs (`spec.md`, `reference.md`,
`interfaces.md` + Decisions Log) with everything built, a red/black/white palette
polish pass over the new UI, and a full regression.
