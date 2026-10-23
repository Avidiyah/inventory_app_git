# SMR27 Audit Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import the SMR27 vendor sheet as closed-but-unarchived work orders with a frozen pre-audit baseline, let Admin+ re-charge them (including anonymous Skilled Technician labor) in the normal editor, show them only on a white-on-black SMR tile page, and export before/after/delta at summary and line level.

**Architecture:** New SMR modules beside the existing work-order stack (`domain/work_orders_smr.py`, `services/work_orders_smr.py`, `services/work_orders_smr_xlsx.py`, `routers/work_orders_smr.py`, `schemas/work_orders_smr.py`, `static/views/smr.js`, `static/pages/smr.html`), because `services/work_orders.py` is already 3,188 lines. Two new columns and one nullable FK; one shared "live" predicate keeps SMR rows off every existing surface. Baseline, edited-check and export all read one snapshot serializer.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, openpyxl (`_xlsx_theme.py`), vanilla ES modules, pytest, Vitest.

**Spec:** `docs/superpowers/specs/2026-10-23-smr-audit-workflow-design.md`

## Global Constraints

- No new dependencies, no new tables. Files under 500 lines (new modules split further if needed; `workOrder*.js` may reach 500).
- Role gates: SMR import and export Owner (`roles.ROLE_OWNER`); SMR view Admin+ (`roles.ROLE_ADMIN`); Skilled Technician labor Admin+ on SMR orders only.
- Labor rate and rounding reuse `wo.labor_charge` / `wo.billed_labor_minutes`; skilled minutes round separately from real minutes.
- SMR rows never appear on the live list, filter options, Hub, Graphs, weekly report, legacy archive, user-request lookup. Editor and NetFacilities enrichment candidate query do include them.
- Baseline written once, never overwritten. Snapshot includes `source_row` with every sheet column verbatim.
- CSP: no inline `style=`; SMR styling is a `.smr-*` class ladder in `styles.css`.
- Commit per task with the `Co-Authored-By` line from the session reminder. Do not push without asking (deploy gate).
- Targeted tests per task; full suites only at the end.

## Review Focus

1. Re-running SMR Import after edits: baseline must survive, edits must survive, counts must report `opened`/`restored`, never `created`. (Task 5 test `test_smr_import_rerun_keeps_baseline_and_edits`.)
2. A number present in the sheet twice, or a Canceled row for a number that is live in the app: skipped without touching the live row. (Task 5 `test_smr_import_canceled_row_leaves_live_row_alone`.)
3. Skilled Technician labor posted to a non-SMR order, or by a Supervisor on an SMR order: 422/403, no row written. (Task 4 `test_skilled_labor_rejected_off_smr_and_below_admin`.)
4. An SMR order archived after editing still exports and still shows on the tiles under ARCHIVED; the editor's archive guard still blocks edits. (Task 6 `test_smr_tiles_include_archived`, Task 7 `test_smr_export_includes_archived_orders`.)
5. Line deleted after baseline (material removed): BEFORE row present, AFTER row absent, delta negative, `edited` true. (Task 2 `test_is_edited_detects_removed_line`, Task 7 `test_smr_export_removed_line_shows_only_before`.)

---

### Task 1: Schema — SMR columns and nullable labor technician

**Files:**
- Create: `backend/alembic/versions/<rev>_smr_audit_columns.py` (down_revision `4f0a7ce7d1ac`)
- Modify: `backend/app/models.py` (`WorkOrder` ~line 404, `WorkOrderLabor` line 528)
- Test: `backend/tests/test_models_smr.py`

**Interfaces:**
- Produces: `WorkOrder.smr_imported_at: DateTime(tz) | None`, `WorkOrder.smr_baseline: JSONB | None`, `WorkOrderLabor.technician_id` nullable; `WorkOrderLabor.technician` relationship may be `None`.

- [ ] Write `test_smr_columns_round_trip(db)`: create a `WorkOrder` with `smr_imported_at=now`, `smr_baseline={"a": 1}`, a `WorkOrderLabor(technician_id=None, minutes=30)`; flush; reload; assert all three persist.
- [ ] Run `pytest backend/tests/test_models_smr.py -v` → FAIL (column does not exist).
- [ ] Add the two columns (`JSONB` from `sqlalchemy.dialects.postgresql`), make `technician_id` nullable, write the migration (`op.add_column` ×2, `op.alter_column(... nullable=True)`; downgrade reverses, deleting null-technician rows first). Update the `WorkOrderLabor` docstring: null technician = Skilled Technician line.
- [ ] `alembic upgrade head`; run the test → PASS.
- [ ] Commit: `feat(smr): add smr_imported_at, smr_baseline and nullable labor technician`.

### Task 2: Domain — sheet parsing, snapshot, edited, deltas, split labor

**Files:**
- Create: `backend/app/domain/work_orders_smr.py`
- Modify: `backend/app/domain/work_orders.py` (none; import from it)
- Test: `backend/tests/test_work_orders_smr_domain.py`

**Interfaces (Produces):**
```python
SMR_SERVICE_TYPE = "SMR27 - Belfor"
SKILLED_TECHNICIAN_LABEL = "Skilled Technician"
SMR_REQUIRED_HEADERS = ("WORK ORDER", "FILED STATUS", "LOCATION", "ASSIGNED TO", "SERVICE TYPE", "SCHEDULE DATE")
def parse_smr_row(row: dict) -> dict      # {"number", "closed": bool, "attrs": {location, vendor_assignee, service_type, schedule_date}, "source_row": dict}
def labor_split(entries) -> LaborSplit    # dataclass: real_minutes, skilled_minutes, real_billed, skilled_billed, labor_total (Decimal)
def snapshot(work_order, *, taken_at: datetime, source_row: dict | None) -> dict   # spec shape; totals via labor_split + material prices
def is_edited(work_order) -> bool         # snapshot(wo)[comparable keys] != wo.smr_baseline[same keys]; False when no baseline
def deltas(baseline: dict, current: dict) -> dict   # {materials_total, real_minutes, skilled_minutes, labor_total, total, material_lines} as Decimal/int differences
```
`snapshot` must be JSON-serialisable (Decimals as strings, datetimes ISO, UUIDs as str) and `is_edited` compares everything except `taken_at` and `source_row`.

- [ ] Write tests: `test_parse_smr_row_maps_sheet_headers` (uses the real header strings from the spec, including the two annotation columns in `source_row`; `closed` false for `Canceled`); `test_labor_split_rounds_skilled_separately` (real 20 + skilled 20 → billed 30 + 30, total = `labor_charge(30)*2`, not `labor_charge(40)`); `test_snapshot_is_json_serialisable`; `test_is_edited_false_when_unchanged`; `test_is_edited_detects_removed_line`; `test_deltas_subtract_baseline`.
- [ ] Run → FAIL (module missing).
- [ ] Implement the module. Material line total = `item.price * effective_billable(quantity, billable_quantity)`. Labor entry rows carry `technician: SKILLED_TECHNICIAN_LABEL` when `technician_id is None`.
- [ ] Run → PASS. Commit: `feat(smr): domain parsing, snapshot, edited check and split labor`.

### Task 3: One live predicate; exclude SMR from existing surfaces

**Files:**
- Modify: `backend/app/services/work_orders.py` (lines 1151, 1253, 1332 `scope == all/live`, 2024, 2048), `backend/app/services/hub.py` (175, 207, 413, 600, 627, 680, 1127, 1180), `backend/app/services/work_order_report.py` (125, 140), `backend/app/routers/user_requests.py` (190)
- Not modified: `backend/app/services/netfacilities.py:177`, editor `get_work_order` / update / labor / material paths.
- Test: `backend/tests/test_smr_exclusion.py`

**Interfaces (Produces):** `wos.live_work_orders()` → SQLAlchemy clause `and_(WorkOrder.archived_at.is_(None), WorkOrder.smr_imported_at.is_(None))`; `wos.not_smr()` → `WorkOrder.smr_imported_at.is_(None)` for the sites that filter on `archived_at` ranges (hub 1180, report 125/140).

- [ ] Write tests: `test_smr_row_absent_from_list_and_filter_options(db)`, `test_smr_row_absent_from_hub_counts(db)` (call the hub live-rows helper at 1127), `test_smr_row_absent_from_weekly_report(db)` (archived SMR row inside the window), `test_smr_row_still_enrichment_candidate(db)` (`netfacilities._load_candidates`), `test_editor_still_loads_smr_row(db)` (`wos.get_work_order`).
- [ ] Run → FAIL on the first three.
- [ ] Add the two helpers; replace each listed site. Do not touch export scope `archived` (SMR rows there are harmless but keep them out too: apply `not_smr()` at 1329 for consistency).
- [ ] Run new tests plus `pytest backend/tests/test_work_orders_service.py backend/tests/test_work_order_report.py backend/tests/test_hub*.py -q` → PASS.
- [ ] Commit: `feat(smr): keep SMR orders off live surfaces via one predicate`.

### Task 4: Skilled Technician labor (backend)

**Files:**
- Modify: `backend/app/schemas/work_orders.py` (`WorkOrderLaborCreate.technician_id: Optional[UUID]`, `WorkOrderLaborDetail.technician_id: Optional[UUID]`, `WorkOrderDetail` add `skilled_labor_minutes: int = 0`, `skilled_labor_billed_minutes: int = 0`, `smr: bool = False`; `WorkOrderCard` add `smr: bool = False`), `backend/app/services/work_orders.py` (`add_work_order_labor` 2146, `update_work_order_labor` 2197, `delete_work_order_labor` 2219, `_require_labor_editor` 2113, `work_order_totals` 1376), `backend/app/routers/work_orders.py` (`_labor_detail` 454, detail totals 538–543, card builder), `backend/app/services/hub.py:743`
- Test: `backend/tests/test_work_order_skilled_labor.py`

**Interfaces:**
- Consumes: `labor_split`, `SKILLED_TECHNICIAN_LABEL` (Task 2).
- Produces: `wos.add_work_order_labor(db, id, *, user, technician_id: uuid.UUID | None, minutes)`; `WorkOrderDetail.labor_minutes` = real minutes, `skilled_labor_minutes`, `labor_billed_minutes` = real billed, `skilled_labor_billed_minutes`, `labor_total` = combined; `_labor_detail` returns `technician_name="Skilled Technician"` for null; `WorkOrderCard.smr`/`WorkOrderDetail.smr` = `smr_imported_at is not None`.

- [ ] Write tests: `test_skilled_labor_added_on_smr_order_by_admin(db)` (row with null technician, detail shows split minutes and combined total); `test_skilled_labor_rejected_off_smr_and_below_admin(db)` (non-SMR → `InvalidAssigneeError`; Supervisor on SMR → `RoleManagementError`, the error `_require_labor_editor` already raises); `test_update_and_delete_skilled_entry(db)`; `test_hub_billing_ignores_skilled_minutes(db)`; `test_work_order_totals_split_rounding(db)`.
- [ ] Run → FAIL.
- [ ] Implement: in `add_work_order_labor`, when `technician_id is None`: require `work_order.smr_imported_at` and `roles.role_at_least(user.role, roles.ROLE_ADMIN)`, skip crew check. `_require_labor_editor` short-circuits the same way for update/delete of a null-technician entry. `work_order_totals` uses `labor_split`. Hub 743 sums only entries with `technician_id is not None`. Detail/card set `smr`.
- [ ] Run new tests plus `pytest backend/tests/test_work_order_billing.py backend/tests/test_work_orders_router.py -q` → PASS.
- [ ] Commit: `feat(smr): anonymous Skilled Technician labor on SMR orders`.

### Task 5: SMR import service and route

**Files:**
- Create: `backend/app/services/work_orders_smr.py`, `backend/app/routers/work_orders_smr.py`, `backend/app/schemas/work_orders_smr.py`
- Modify: `backend/app/main.py` (include router), `backend/tests/test_route_role_gates.py` (add the Owner gate case to the folded-gate parametrisation at 254 and the 403-doc case at 316)
- Test: `backend/tests/test_smr_import.py`

**Interfaces:**
- Consumes: `parse_smr_row`, `snapshot` (Task 2); `wos.find_by_number`, `wos.get_or_create_work_order`, `wos._supervisor_lookup`, `wo.work_order_task_fallback`; `routers._uploads.read_capped`.
- Produces: `import_smr(db, *, csv_bytes: bytes, user: User) -> SmrImportResult` (`total, created, opened, restored, skipped, baselined`); `POST /work-orders/smr/import` (Owner, multipart `file`, 413 on cap, 422 on missing required header) returning `SmrImportResult`.

- [ ] Write tests (CSV builder with the real sheet headers): `test_smr_import_creates_restores_and_baselines(db)` (new number → created; pre-archived number → `archived_at is None`, restored=1; both have `smr_imported_at`, `smr_baseline["source_row"]["CREATOR"]`); `test_smr_import_rerun_keeps_baseline_and_edits(db)` (add a labor entry, re-import, baseline unchanged, entry present, counts opened=…); `test_smr_import_canceled_row_leaves_live_row_alone(db)`; `test_smr_import_requires_filed_status_header(db)`; `test_smr_import_route_requires_owner` (TestClient, Admin → 403).
- [ ] Run → FAIL.
- [ ] Implement `import_smr`: same decode/`sep=,`/DictReader preflight as `import_work_orders`; for each closed row: `existing = find_by_number`; if archived → `existing.archived_at = None`, restored; then `get_or_create_work_order(..., description=fallback, replace_generated_description=False, **attrs)`; set `smr_imported_at` if null; set `smr_baseline = snapshot(wo, taken_at=now, source_row=row)` if null, after `db.flush()`. Router mirrors the existing import route (sync `def`, role gate before size check).
- [ ] Run → PASS; `pytest backend/tests/test_route_role_gates.py -q` → PASS.
- [ ] Commit: `feat(smr): Owner-only SMR sheet import with frozen baseline`.

### Task 6: SMR tiles endpoint

**Files:**
- Modify: `backend/app/services/work_orders_smr.py`, `backend/app/routers/work_orders_smr.py`, `backend/app/schemas/work_orders_smr.py`, `backend/tests/test_route_role_gates.py`
- Test: `backend/tests/test_smr_tiles.py`

**Interfaces:**
- Produces: `list_smr_tiles(db) -> SmrTilesResponse` with `imported_at`, `counts {orders, edited, untouched, archived}`, `delta {labor_total, materials_total, total}`, `tiles: [SmrTile]`; `SmrTile = {id, number, building_number, unit_number, location, vendor_assignee, status, archived_at, edited: bool, before: SmrTotals, after: SmrTotals, delta: SmrTotals, after_line_count: int}` where `SmrTotals = {materials_total, real_minutes, skilled_minutes, labor_total, total}`. `GET /work-orders/smr` (Admin+). Sorted: edited first, then number.

- [ ] Write tests: `test_smr_tiles_before_after_delta(db)`, `test_smr_tiles_include_archived(db)`, `test_smr_tiles_route_requires_admin`.
- [ ] Run → FAIL. Implement using `snapshot` + `deltas` + `is_edited` with eager loads for items/labor. Run → PASS.
- [ ] Commit: `feat(smr): tiles endpoint with before/after/delta`.

### Task 7: SMR export workbook

**Files:**
- Create: `backend/app/services/work_orders_smr_xlsx.py`
- Modify: `backend/app/routers/work_orders_smr.py`, `backend/tests/test_route_role_gates.py`
- Test: `backend/tests/test_smr_export_xlsx.py`

**Interfaces:**
- Consumes: `_xlsx_theme.setup_sheet/header_row/write_rows/title_block`, `snapshot`, `deltas`, `wos.export_row` + `wo.EXPORT_HEADERS`.
- Produces: `smr_workbook(db) -> bytes`; `SMR_XLSX_FILENAME = "smr27-audit-export.xlsx"`; `GET /work-orders/smr/export.xlsx` (Owner) with `Content-Disposition`. Sheets exactly as the spec table: `Orders`, `Material Lines`, `Labor Entries`, `Labor Sessions`; `PHASE` cell values `BEFORE` / `AFTER`; money and minutes written as numbers. `Orders` trailing columns: `EDITED` (`YES`/`NO`), `SMR IMPORTED AT`, `BASELINE AT`, `LAST EDITED AT` (max of `updated_at` and line `created_at`/session `edited_at` after baseline, blank if none), `LAST EDITED BY` (full name of the actor on the latest labor session edit or note-log entry after baseline, blank if none), `ARCHIVED AT`.

- [ ] Write tests (load with `openpyxl.load_workbook(io.BytesIO(...))`): `test_smr_export_sheets_and_phase_parity(db)` (same column headers for BEFORE and AFTER rows; Orders row has `BEFORE`/`AFTER`/`DELTA` triples for every numeric `EXPORT_HEADERS` column and the sheet's raw columns first); `test_smr_export_removed_line_shows_only_before(db)`; `test_smr_export_includes_archived_orders(db)`; `test_smr_export_route_requires_owner`.
- [ ] Run → FAIL. Implement. Run → PASS; `pytest backend/tests/test_xlsx_theme.py -q` still PASS.
- [ ] Commit: `feat(smr): Owner-only before/after audit workbook`.

### Task 8: SMR page, nav, styles, API helpers

**Files:**
- Create: `backend/static/pages/smr.html`, `backend/static/views/smr.js`
- Modify: `backend/app/main.py` (`SHELL_PARTS` after `pages/integrations.html`), `backend/static/views/nav.js` (`PAGE_LOADERS["smr"]`, `PAGE_ACCESS["smr"] = ["owner","admin"]`, nav button), `backend/static/api.js` (`apiListSmrTiles()`, `apiExportSmrXlsx = () => xlsxDownload("/work-orders/smr/export.xlsx", "GET")`), `backend/static/styles.css` (`.smr-*` ladder), `backend/static/views/workOrderList.js` (export an `openWorkOrderEditorByNumber(number)` if one does not already exist; `openWorkOrdersByNumberSearch` is the existing hand-off)
- Test: `tests/frontend/views/smr.test.js`, `tests/frontend/views/nav.test.js`

**Interfaces:**
- Consumes: `SmrTilesResponse` (Task 6).
- Produces: `loadSmr()`; DOM ids `smr-page`, `smr-bar`, `smr-filter-*` (`all|edited|untouched|archived`), `smr-export-btn` (hidden unless Owner), `smr-tiles`; tile `data-number`, class `smr-tile`, `smr-tile--untouched`, `smr-tile--archived`; empty copy `NO SMR ORDERS. OWNER: IMPORT FROM INTEGRATIONS.`

- [ ] Write Vitest tests (load via `importView` per `tests/frontend/setup.js`): renders bar counts and deltas from a seeded response; filter buttons narrow tiles; untouched tiles get `smr-tile--untouched`; export button hidden for Admin, shown for Owner and calls the download helper; tile click calls the editor hand-off with the number; nav test: `smr` in `PAGE_ACCESS` for owner/admin only.
- [ ] Run → FAIL. Implement. Styling: `#000` page background, `#fff` text, 1px `#fff` borders, `ui-monospace, "Courier New", monospace`, uppercase labels, zero radius/shadow, untouched opacity `.5`; overrides scoped under `#smr-page`.
- [ ] Run `npx vitest run tests/frontend/views/smr.test.js tests/frontend/views/nav.test.js` → PASS.
- [ ] Commit: `feat(smr): white-on-black SMR tiles page`.

### Task 9: Editor — Add Skilled Technician

**Files:**
- Modify: `backend/static/views/workOrderCardHtml.js` (`laborSectionHtml` 105–130), `backend/static/views/workOrderActions.js` (add `add-skilled-labor` beside `add-labor` 348), `backend/static/views/workOrderPresenters.js` (`laborSummaryHtml` shows `Skilled: <billed>` when `skilled_labor_minutes > 0`), `backend/static/api.js` (`apiAddWorkOrderLabor` sends `technician_id: null` when `technicianId` is null)
- Test: `tests/frontend/views/workOrders/editorActions.test.js`, `render.test.js`

**Interfaces:** Consumes `WorkOrderDetail.smr`, `skilled_labor_minutes`, `skilled_labor_billed_minutes`, labor entries with `technician_id: null`, `technician_name: "Skilled Technician"` (Task 4).

- [ ] Write tests: button `data-action="add-skilled-labor"` with input `.wo-new-skilled-hours` rendered above the Technician control only when `detail.smr` and role ≥ admin; clicking posts `{technician_id: null, minutes}`; a null-technician entry renders `Skilled Technician` with Update/Remove; summary shows the skilled line.
- [ ] Run → FAIL. Implement (button label text: `Add Skilled Technician`). Run → PASS.
- [ ] Commit: `feat(smr): Add Skilled Technician control in the labor section`.

### Task 10: Integrations — SMR Import button

**Files:**
- Modify: `backend/static/pages/integrations.html` (button `wo-smr-import-btn`, `input#wo-smr-import-file`, both `hidden`), `backend/static/views/workOrderIntegrations.js` (show for Owner only; on change → `apiImportSmr(file)`; message `SMR import: {created} created, {restored} restored, {opened} opened, {skipped} skipped.`), `backend/static/api.js` (`apiImportSmr(file)` → `POST /work-orders/smr/import` multipart), `backend/static/tips.js` (one tip `integrations.smr`)
- Test: `tests/frontend/views/workOrders/integrations.test.js`

- [ ] Write tests: button hidden for Admin, visible for Owner; selecting a file posts to `/work-orders/smr/import` and renders the summary line; a 403 renders the friendly error.
- [ ] Run → FAIL. Implement, same `secondary-btn` class as the enrich button. Run → PASS.
- [ ] Commit: `feat(smr): Owner-only SMR Import button in the NetFacilities card`.

### Task 11: Docs and final verification

**Files:**
- Modify: `docs/current-state.md` (one row in the component table, one line under API surface), `docs/endpoint-map.md` (three routes, Owner/Admin gates, `SmrImportResult`/`SmrTilesResponse` shapes), `docs/design-system.md` (one line: SMR page is a deliberate white-on-black departure), `docs/open-work.md` (close any SMR item if one exists)

- [ ] Edit the docs within their word budgets; delete something stale in the same edit if a budget breaks.
- [ ] Run `pytest backend/tests -q` and `npx vitest run` → all PASS (rerun `test_cascade_deletes_with_user` alone if it fails on the dev DB; known environmental).
- [ ] Run the SMR import against `C:\Users\mcclu\Desktop\Copy of SMR27 Work Orders - SMR27 Work Orders.csv` on the local app (port 8124) and confirm the summary reads 681 accounted (created + opened + restored) and 7 skipped. Report the numbers; do not push.
- [ ] Commit: `docs(smr): record the SMR audit workflow`.
