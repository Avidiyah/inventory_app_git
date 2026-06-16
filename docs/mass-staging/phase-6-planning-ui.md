# Phase 6 — Planning UI *(implemented)*

> **Status:** ✅ Implemented 2026-06-16; static checks pass, **browser
> validation handed to the user** (per the manual-validation preference). First
> frontend phase: the Mass Stage page + planning workflow. Loading/returns UI is
> Phase 7.

## What shipped

The **Mass Stage** page (Supervisor+) for building a staging plan: create a
stage for a building, add rooms (each with one work order — "Next Room"), search
items and add them as planned estimates, edit/remove planned quantities, then
**Save Mass Stage** (status → `loading`). Stages and rooms are expandable
one-line cards (`<details>`); planned items are rows with an inline qty editor.

### Files

- New: `static/pages/mass-stage.html` (page fragment — create form + list
  container), `static/views/massStage.js` (the view).
- Edit: `static/shell-head.html` (nav button after "Scan / Stock"),
  `app/main.py` (`SHELL_PARTS` += `pages/mass-stage.html`),
  `static/views/nav.js` (`PAGE_ACCESS["mass-stage"]` = owner/admin/supervisor;
  `showPage` → `loadStages()`), `static/api.js` (11 planning wrappers),
  `static/main.js` (side-effect import), `static/styles.css` (MASS STAGE section).

### UI structure & decisions

- **Expandable cards** via native `<details>`/`<summary>` (accessible, no toggle
  JS); a custom caret replaces the default marker. Stage summary shows building
  name + status pill + room/item counts; room summary shows room # + WO + item
  count. Stage detail is **lazy-loaded** (`apiGetStage`) on first expand.
- **Add item by search**: a per-room search box filters a once-cached item list
  (`apiListItems`) and shows result buttons (the `addBarcode.js` chooser
  pattern); pick → enter qty → Add. Backend upserts by (room, item).
- **Inline planned-qty edit** (number input + Update) rather than a prompt;
  Remove per item; Remove room; Save / Delete per stage.
- **Event delegation** on `#mass-stage-list` for both `click` and `input`
  (data-action attributes), mirroring `items.js`. After any mutation the stage's
  detail is re-fetched and re-rendered, preserving which rooms were open and
  refreshing the summary counts.
- When status ≠ `planning` the plan renders **read-only** (loading/returns
  controls arrive in Phase 7).
- Pure CSS-token styling (red/black/white); status pill reuses the badge look
  (planning = blue, loading = amber, completed = green).

## Verification

1. Assembled shell (`_assemble_index`) contains the `mass-stage` nav button and
   `#mass-stage-page`, in the right nav order. ✓
2. `pytest -q` → 109 passed (no backend logic changed). ✓
3. `node --check` on `massStage.js`, `api.js`, `nav.js`, `main.js` → all parse. ✓
4. **Manual (handed off):** sign in as Supervisor → Mass Stage → create a
   building, add two rooms + work orders, add items by search, edit a qty, then
   Save Mass Stage (→ loading); confirm a Technician has no nav button.

## Next

Phase 7 — loading + returns UI: when a stage is `loading`, render the
`merged_items` list with a per-item **Staged** button (reusing the scan +
`#scan-confirm-overlay` flow) and an **Unused materials** return control.
