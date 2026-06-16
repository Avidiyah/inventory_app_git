# Phase 7 — Loading + Returns UI *(implemented)*

> **Status:** ✅ Implemented 2026-06-16; static checks pass, **browser
> validation handed to the user**. The `loading` / `completed` screen on the
> Mass Stage page. Frontend only — `/load`, `/return`, `merged_items` already
> exist (Phase 5).

## What shipped

When a stage is `loading`, the Mass Stage card now shows the execution screen:

- **Load list** — the per-item `merged_items` rollup. Each row: name + barcode, a
  stats line (Planned / Loaded / Remaining, plus an amber **+N over** flag when
  `overflow > 0`), a **load qty** input (defaulting to `remaining_to_load`) + a
  **Staged** button, and an **Unused** qty input + **Return** button.
- **Staged** → styled confirm dialog ("Load N × item onto the truck?") →
  `apiLoadStageItem` (real per-room dispenses, split behind the scenes). Per the
  user's call, **no camera** — quantity + confirm.
- **Unused materials** → `apiReturnStageItem` (silent stock-add; surfaces
  `ReturnExceedsLoadedError` via `friendlyError`).
- **Rooms** shown read-only (per-room / per-WO breakdown).
- **Mark Completed** (`loading → completed`); `completed` renders read-only with
  Returned / Consumed per item.

### Files (all edits — no new files, no backend change)

- `static/dom.js` — new shared `confirmDialog(message)` (the focus-trapped
  `#scan-confirm-overlay` driver).
- `static/views/transactions.js` — `confirmScan` now delegates to
  `confirmDialog`; removed its duplicate modal logic + unused overlay consts
  (scan-and-go behavior unchanged).
- `static/api.js` — `apiLoadStageItem`, `apiReturnStageItem`.
- `static/views/massStage.js` — `renderStageBody` dispatches by status;
  `renderLoadingBody` + `renderMergedHtml`; `load-item` / `return-item` /
  `complete-stage` handlers in the existing click delegation.
- `static/styles.css` — merged-list styles (`.ms-merged*`, `.ms-overflow`,
  `.ms-subhead`).

### Decisions realized

- **Reuse over duplication**: the confirm modal was extracted into
  `dom.confirmDialog` and is now shared by scan-and-go and the load action
  (rather than copying ~50 lines).
- `refreshStage` (Phase 6) re-fetches detail after each load/return, so the
  merged stats and the status pill stay current without a full reload.

## Verification

1. `node --check` on `massStage.js`, `dom.js`, `transactions.js`, `api.js` → all parse. ✓
2. `pytest -q` → 109 passed (no backend change). ✓
3. Grep → no dangling `scanConfirm*` refs; `confirmDialog` wired in both views. ✓
4. `_assemble_index` still serves the mass-stage page + `#scan-confirm-overlay`. ✓
5. **Manual (handed off):** open a `loading` stage → Staged a qty (confirm →
   stock drops; dispenses appear in History on the room work orders) → Return via
   Unused materials (stock returns, no History row) → Mark Completed (read-only).
   Also re-check the Transaction scan-and-go confirm dialog (shared modal).

## Next

Phase 8 — Scan/Stock **by-room mid-job dispense**: on the Transaction page, pick
a building + room to auto-fill its work order, then dispense normally (not added
to the stage). Then Phase 9 — doc reconcile + palette polish + regression.
