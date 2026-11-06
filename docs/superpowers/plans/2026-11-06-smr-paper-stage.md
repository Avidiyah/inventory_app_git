# SMR27 paper stage — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (no subagents in this repo). Steps use `- [ ]`.

**Goal:** the SMR page and card show where an order's paper stands (Not reviewed → Reviewed · undated → Reviewed · dated → Ready for invoice), filterable by stage and by pile, with a human-only Ready stamp.

**Architecture:** stage, closed week and Belfor-only are derived in `services/work_orders_smr.tile_for` from readings and lines already loaded; the Ready stamp is two columns on `work_orders` behind one endpoint shaped like the paper check. The page swaps one chip row for three client-side rows over the same payload.

**Tech stack:** FastAPI + SQLAlchemy + Alembic; vanilla ES modules; pytest (run from `backend\`), Vitest.

**Spec:** `docs/superpowers/specs/2026-11-06-smr-paper-stage-design.md` — read it first; this plan never restates it.

## Global constraints

- Ponytail: shortest working diff, reuse the paper-check shape, no new abstractions.
- Files under 500 lines; `smr.js` is 276, `services/work_orders_smr.py` 431 — if either passes 500, move the new chip rows to `smrFilters.js` / the stage helpers to `domain/work_orders_smr.py`.
- CSP: no inline styles; every tile class lives in `styles.css` under `#smr-page`.
- Copy exactly as the spec's tables: stage labels, chip labels, bar cell text, card row text, 409 text "Date a line first".
- Stage colors always carry the pill's words (never color alone).
- Commit per task with explicit paths (`git add <paths>`, never `-A`); no push without asking.

## Review focus

Inputs the spec implies but no table names; each is pinned by a test in the task that owns it:

1. A line removed (`exclusion_ground = removed`) is ignored for stage, weeks and Belfor-only, so an order whose only dated line was removed drops back to undated (Task 1).
2. An order with a reading and zero lines is `undated`, not `not_reviewed` (Task 1).
3. Belfor-only is false with no lines, and false when any line is `Unknown` vendor (Task 1).
4. `ready: true` twice keeps the first who/when; `ready: false` on an order never stamped is a no-op 200 (Task 2).
5. The saved chip memory from before this change (a single `chip` key such as `untouched`) must not crash the page: unknown saved chips fall back to the row defaults (Task 4).

---

### Task 1: stage, closed week, Belfor-only on the tile; Ready columns

**Goal:** `SmrTile` carries `stage`, `closed_week`, `belfor_only`, `ready`; `SmrCounts` carries the stage counts and drops the eight cells; the two Ready columns exist.

**Files:** `backend/app/models.py` (WorkOrder, beside `smr_paper_checked_*`), new `backend/alembic/versions/<id>_smr_ready_columns.py` (copy `7d9e1f3a4b52_smr_paper_check_columns.py`), `backend/app/domain/work_orders_smr_lines.py`, `backend/app/schemas/work_orders_smr.py`, `backend/app/services/work_orders_smr.py`, `backend/tests/test_smr_tiles.py`.

**Interfaces produced:**
- `rules.stage_for(readings, lines, ready_at) -> str` in `domain/work_orders_smr_lines.py`: `"ready" | "dated" | "undated" | "not_reviewed"` per the spec's rule table; `lines` already filtered of removed ones.
- `rules.belfor_only(lines) -> bool`.
- `SmrReadyOut(at: datetime, by_name: Optional[str])` with `from_order(work_order) -> Optional[SmrReadyOut]` (the `SmrPaperCheckOut` shape).
- `SmrTile.stage: str`, `closed_week: Optional[str]`, `belfor_only: bool`, `ready: Optional[SmrReadyOut]`.
- `SmrCounts`: keep `orders, archived, charged_hours, excluded_hours, blocks_not_pasted`; add `not_reviewed, undated, dated, ready, belfor_only: int = 0`; delete `edited, untouched, matched, short, no_target, paper_checked, short_checked, with_lines`.
- `WorkOrder.smr_ready_at`, `smr_ready_by_id`, relationship `smr_ready_by` (viewonly).

**Steps:**
- [ ] Write the failing tests in `test_smr_tiles.py` (helpers `_user`, `_sheet`, `lines_service.add_reading/add_line/edit_line` as `test_smr_lines.py` uses them):
  - `test_stage_not_reviewed_without_readings` — imported order: `stage == "not_reviewed"`, `closed_week == "Before W1"` (the fixture closes 05/21), `belfor_only is False`, `ready is None`, `page.counts.not_reviewed >= 1`.
  - `test_stage_undated_with_a_reading_and_no_dated_line` — add a reading with no date, then an excluded undated line: `stage == "undated"`; with the reading alone (no lines): still `"undated"`.
  - `test_stage_dated_by_any_week_charged_or_excluded` — one excluded line with `work_date=2026-06-02`: `stage == "dated"`, `"Week 2" in weeks`, `closed_week is None`; a placement-basis line with `week=1` and no date: `"dated"`.
  - `test_removed_lines_do_not_count` — date a line, then `edit_line(... status="excluded", exclusion_ground="removed")`: back to `"undated"`.
  - `test_belfor_only` — all-Belfor lines → True; Belfor + `Unknown` → False; no lines → False; `counts.belfor_only` counts it.
  - `test_ready_stage_needs_a_dated_line` — set `smr_ready_at` directly on a dated order → `"ready"`, `ready.by_name` set; remove its only dated line → `"undated"` while `ready` stays populated.
  - Update `test_smr_tiles_before_after_delta` (and any other) to drop `counts.edited`.
- [ ] Run: `pytest tests/test_smr_tiles.py -q` — expected: failures on the new names.
- [ ] Add the two columns + relationship to `WorkOrder`; write the migration (both columns nullable, FK users `ON DELETE SET NULL`, no backfill).
- [ ] Implement `stage_for` and `belfor_only` in the rules module; add `SmrReadyOut`; extend `SmrTile`/`SmrCounts`; in `tile_for` compute `closed_week = rules.week_label(rules.week_of(completed_at.date()))` only when stage is `undated`/`not_reviewed` and `completed_at` is set, else `None`; in `list_smr_tiles` replace the dropped sums with the five stage counts.
- [ ] Run: `pytest tests/test_smr_tiles.py tests/test_smr_lines.py tests/test_smr_export_xlsx.py -q` — expected: PASS (the export reads `counts` nowhere, but confirm).
- [ ] Commit: `feat(smr): paper stage, closed week and Belfor-only on the tile; ready columns`.

### Task 2: Ready endpoint and card detail fields

**Goal:** `PUT /work-orders/smr/{id}/ready` stamps or clears, Admin+, 409 unless dated; the card detail carries `smr_stage` and `smr_ready`.

**Files:** `backend/app/schemas/work_orders_smr.py` (`SmrReadyIn(ready: bool)`), `backend/app/services/work_orders_smr.py` (beside `set_paper_check`), `backend/app/routers/work_orders_smr.py` (beside the paper-check route), `backend/app/schemas/work_orders.py` (`WorkOrderDetail.smr_stage: Optional[str]`, `smr_ready: Optional[SmrReadyOut]`), `backend/app/routers/work_orders.py:570` (fill both when `is_smr`), new `backend/tests/test_smr_ready.py` (copy the TestClient scaffold of `test_smr_paper_check.py`).

**Interfaces produced:** `smr_service.set_ready(db, *, work_order_id, ready: bool, user) -> SmrTile`; raises `WorkOrderStateError("Date a line first.")` when `ready` and stage ≠ `dated`/`ready`. Deviation from the spec's POST: PUT, matching the paper check (log in the spec's Deviations).

**Steps:**
- [ ] Failing tests in `test_smr_ready.py`: technician → 403; admin on a `not_reviewed` order → 409 with `"Date a line first."` in `detail`; admin on a dated order → 200, body `stage == "ready"`, `ready.by_name == "Pat Keyer"`; a second `true` keeps the first `ready.at`; `false` → 200 `stage == "dated"`, `ready is None`; `false` on a never-stamped order → 200; `GET /work-orders/{id}` on the stamped order carries `smr_stage == "ready"` and `smr_ready.by_name`.
- [ ] Run: `pytest tests/test_smr_ready.py -q` — expected: 404s / attribute errors.
- [ ] Implement service (reuse `tile_for` to read the stage before and to build the return), route (`require_min_role(roles.ROLE_ADMIN)`, `responses=_forbidden(roles.ROLE_ADMIN)`), detail fields.
- [ ] Run: `pytest tests/test_smr_ready.py tests/test_smr_paper_check.py tests/test_smr_lines_routes.py -q` — expected: PASS.
- [ ] Commit: `feat(smr): Ready for invoice stamp (PUT /work-orders/smr/{id}/ready)`.

### Task 3: drop the NetFacilities Status filter

**Goal:** the SMR page sends no `status`; the dropdown, the param and its test are gone.

**Files:** `backend/static/pages/smr.html:14-26`, `backend/static/views/smrFilters.js` (`statusFilter`, `CONTROLS.status`, `SELECTS`), `backend/static/api.js:1068` (`apiListSmrTiles` loses `status`), `backend/app/services/work_orders_smr.py` + `backend/app/routers/work_orders_smr.py` (the `status` query param of the tiles route only; the work-orders list keeps its own), `backend/tests/test_smr_tiles.py::test_smr_tiles_filter_by_community_priority_status_and_date` (rename, drop the status assertion), `tests/frontend/views/smr.test.js` ("sends every control…", "Clear filters…", "fills the dropdowns…").

**Steps:**
- [ ] Edit the three Vitest cases to expect no `status` param and no `#smr-status-filter`; run `npx vitest run tests/frontend/views/smr.test.js` — expected: those three FAIL.
- [ ] Remove the markup, the control, the param on both sides, the pytest assertion.
- [ ] Run: `npx vitest run tests/frontend/views/smr.test.js` and `pytest tests/test_smr_tiles.py -q` — expected: PASS.
- [ ] Commit: `refactor(smr): drop the NetFacilities status filter from the SMR page`.

### Task 4: three chip rows, stage tiles, stage bar

**Goal:** the page renders Stage / Pile / Flags rows that combine, tiles colored and labeled by stage with the closed-week bubble and Belfor tag, and a bar led by stage counts.

**Files:** `backend/static/pages/smr.html:65-76` (three `<div class="smr-controls" data-row="stage|pile|flags">` groups; chips carry `data-row` + `data-filter`; the Hours / CSV / Export buttons stay in the last row), `backend/static/views/smr.js` (`matches`, `applyFilter`, `barHtml`, `tileHtml`, `STATE_LABEL` → `STAGE_LABEL`, chip wiring), `backend/static/views/smrFilters.js` (`savedChip`/`saveFilters` → `savedChips(): {stage, pile, flags}` / `saveFilters(chips)`), `backend/static/styles.css` (`#smr-page` ladder: replace `.smr-tile--untouched/--edited` with `.smr-tile--not_reviewed/--undated/--dated/--ready`, `.smr-tile-stage` pill, `.smr-tile-belfor` tag), `docs/design-system.md` (one line under "Two surface types": amber outline on SMR tiles is the second status-accent exception), `tests/frontend/views/smr.test.js`.

**Interfaces consumed:** Task 1's tile fields. **Produces:** `data-filter` values — stage row `not_reviewed | undated | dated | ready | all`; pile row `Before W1 | Week 1 … Week 7 | After W7 | Undated | belfor | all`; flags row `short | matched | block_pending | archived | all`.

**Rules for `matches(tile, chips)`:** stage chip equals `tile.stage` (or all); pile chip: `belfor` → `tile.belfor_only`, else label ∈ `tile.weeks` (or all); flags as today (`short`, `matched`, `block_pending`, `archived`). Chips combine with AND. Defaults: `not_reviewed` / `all` / `all`. A saved chip not in its row falls back to that row's default.

**Steps:**
- [ ] Rewrite the Vitest fixtures: `tile()` gains `stage: "not_reviewed", closed_week: "Before W1", belfor_only: false, ready: null`; `page().counts` becomes `{ orders, not_reviewed, undated, dated, ready, belfor_only, archived, charged_hours, excluded_hours, blocks_not_pasted }`. Replace the cases "renders one tile per order…", "filters tiles by edited…", "paper check: badge…", "paper lines: … chips" and the chip-memory cases with:
  - `renders stage counts first in the bar` — first five cells read `3 not reviewed`, `1 undated`, `0 dated`, `0 ready`, `1 Belfor only`.
  - `tiles carry the stage pill text, color class, closed-week bubble and Belfor tag` — `.smr-tile--undated .smr-tile-stage` text `Reviewed · undated`; a `not_reviewed` tile's undated bubble reads `Undated · closed Before W1`; `belfor_only` tile has `.smr-tile-belfor` text `Belfor`; a ready tile has class `smr-tile--ready` and pill `Ready for invoice`.
  - `the three chip rows combine` — default shows only not-reviewed tiles; click `Week 3` + `dated` → only the tile with both; `belfor` cuts across stages; `all`/`all`/`all` shows every tile.
  - `dropped chips are absent` — no `[data-filter="untouched"|"edited"|"checked"|"short_checked"|"has_lines"]`.
  - `chip memory saves three keys and ignores an unknown saved chip` — seed `sessionStorage smr.filters` with `{chip:"untouched"}` → defaults apply, no throw; click `Week 2` → saved `{..., pile:"Week 2"}`.
- [ ] Run: `npx vitest run tests/frontend/views/smr.test.js` — expected: new cases FAIL.
- [ ] Implement markup, `smr.js`, `smrFilters.js`, styles (amber: `--status-dispense` fill with white text on the pill, `--status-dispense-text` outline on the tile; dated: `--panel-border` outline, `--gray-500` pill; keep the two keycap shadows for red and green), the design-system line.
- [ ] Run: `npx vitest run tests/frontend/views/smr.test.js tests/frontend/unit/staticImports.test.js` — expected: PASS.
- [ ] Commit: `feat(smr): stage / pile / flags chip rows, stage-colored tiles, stage bar`.

### Task 5: Ready for invoice row on the card

**Goal:** the Paper corrections section shows the Ready row per the spec's three states; the buttons call the endpoint and refresh the card.

**Files:** `backend/static/api.js` (`apiSetSmrReady = (workOrderId, ready) => jsonRequest(\`/work-orders/smr/${workOrderId}/ready\`, "PUT", { ready })`, beside `apiSetSmrPaperCheck`), `backend/static/views/workOrderSmrLines.js` (`readyRowHtml(detail, editable)` rendered after `.wo-smr-totals`; actions `data-action="smr-ready"` / `"smr-not-ready"`), `backend/static/views/workOrderSmrActions.js` (the two branches → `apiSetSmrReady` then `refreshCard`), `backend/static/views/workOrderCardHtml.js:110-125` (the "NetFacilities Record Before Correction" `<details>` loses `open` and keys on `smr_readings.length || smr_lines.length`), `backend/static/styles.css` (`.wo-smr-ready` row), `tests/frontend/views/workOrders/smrLines.test.js` (renders the section already) and `actionCoverage.test.js` (every `data-action` must be routed).

**Interfaces consumed:** Task 2's `smr_stage`, `smr_ready`, endpoint.

**Steps:**
- [ ] Failing Vitest cases: `smr_stage: "dated"` → a button `Ready for invoice`; `"ready"` with `smr_ready: {at, by_name: "JM"}` → text `Ready for invoice · <stamp> by JM` and a `Not ready` button; `"undated"` → muted `Date a line to mark ready`, no button; a technician sees text only; clicking Ready PUTs `{ready: true}` and the card refetches; an order with readings renders the before-correction section collapsed.
- [ ] Run: `npx vitest run tests/frontend/views/workOrders/smrLines.test.js` — expected: FAIL.
- [ ] Implement.
- [ ] Run: `npx vitest run tests/frontend/views/workOrders` — expected: PASS (actionCoverage included).
- [ ] Commit: `feat(smr): Ready for invoice row on the card`.

### Task 6: export columns and docs

**Goal:** the Orders sheet carries `STAGE`, `READY AT`, `READY BY`, `BELFOR ONLY`; living docs state the new truth.

**Files:** `backend/app/services/work_orders_smr_xlsx.py:60-70` (append after `BLOCK PASTED AT`; values from `tile_for`), `backend/tests/test_smr_export_xlsx.py`, `docs/current-state.md` (row 115 test list + `smr.js`/`smrFilters.js`/`smr.html` lines + migration table row), `docs/endpoint-map.md` (S2 loses `status`; new row S14 `PUT /work-orders/smr/{id}/ready`, admin; S3 gains the four columns), the spec's `## Deviations` (PUT not POST, anything else that moved).

**Steps:**
- [ ] Failing test: export a dated, stamped order → the Orders header ends `… BLOCK PASTED AT, STAGE, READY AT, READY BY, BELFOR ONLY` and the row reads `ready`, a datetime, `Pat Keyer`, `TRUE`/`FALSE`.
- [ ] Run: `pytest tests/test_smr_export_xlsx.py -q` — expected: FAIL.
- [ ] Implement; edit the docs within their budgets (delete the stale Untouched/Edited phrasing in the same edit).
- [ ] Run: `pytest tests/test_smr_*.py tests/test_work_orders_smr_domain.py -q` and `npx vitest run tests/frontend` — expected: all PASS; record the counts in the commit body.
- [ ] Commit: `feat(smr): stage columns in the export; docs`.

### Task 7: in-app check (the user's)

Not a build task. After the user's go-ahead on pushing: the page defaults to Not reviewed, the Status dropdown is gone, a dated order offers Ready and turns green, an undated one does not, the Belfor chip cuts across weeks. Push only after they say so ([[inventory-app-ci-gate]]).
