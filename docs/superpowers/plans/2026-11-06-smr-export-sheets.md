# SMR export sheets (Task 8) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (this repo runs plans inline, no subagents). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Owner's `export.xlsx` carries the paper-correction record: nine new Orders columns and five new sheets (Paper Readings, Labor Lines, Line History, Correction Blocks, Workers).

**Architecture:** The existing `work_orders_smr_xlsx.py` keeps the Orders sheet and gains the nine columns; a sibling module `work_orders_smr_xlsx_lines.py` builds the five new sheets through the same `_lines_sheet` shape. One loader change: `smr_orders(db, history=True)` eager-loads edits, block users and reading creators so the workbook makes no per-row queries.

**Tech Stack:** openpyxl, SQLAlchemy selectinload, pytest with the `db` fixture.

**Spec:** `docs/superpowers/specs/2026-11-04-smr-paper-import-design.md` `## Export` (contract) and `## Deviations` (rulings). User rulings 2026-11-06 for this plan: CHANGE is measured against the NetFacilities record before correction (the BEFORE figure), not the Breakdown target; the nine columns sit after `PAPER CHECKED BY` and before `BREAKDOWN *`; Correction Blocks lists every version; Line History carries a `RUN ID` column parsed from `REASON`.

## Global Constraints

- No new dependencies. Files under 500 lines (`work_orders_smr_xlsx.py` is 243; `work_orders_smr.py` 419).
- Money and hours as numbers, never strings; datetimes tz-stripped through `_when`; `date` values written as-is (`_when` would fail on a `date`).
- Archived orders stay in the export (already true for `smr_orders`).
- Every consumer agrees on the charge figure: use `rules.lines_charge` / `smr.labor_figures`, never a parallel sum.
- Targeted tests only before push; ask before pushing `main`; stage explicit paths.

## Review Focus

1. Order with readings but no lines (note-only, undated): CORRECTED/CHANGE/EXCLUDED blank, LINES 0, READINGS n. Test in Task 2.
2. Order with lines but no block: BLOCK VERSION / BLOCK PASTED AT blank, not an error. Test in Task 2.
3. Line with `work_date` None on a placement basis: `WORK DATE` blank, `WEEK` filled; no `_when` call on a `date`. Test in Task 3.
4. Line whose `reading_id` is null (added in the app) or whose worker is None (unnamed headcount): PRINTING / WORKER / ALIASES blank. Test in Task 3.
5. Editor history row (reason is free text): `RUN ID` blank; import row (`reason` = `import <12 hex>`): `RUN ID` = that text. Test in Task 4.

---

### Task 1: Loader with history

**Files:**
- Modify: `backend/app/services/work_orders_smr.py:219-221`
- Test: `backend/tests/test_smr_export_lines_xlsx.py` (new; fixture shared by Tasks 2–5)

**Interfaces:**
- Produces: `smr_orders(db, *, history: bool = False) -> list[WorkOrder]`. With `history=True` adds `selectinload(WorkOrder.smr_lines).selectinload(SmrLaborLine.edits).selectinload(SmrLineEdit.edited_by)`, `selectinload(WorkOrder.smr_blocks).selectinload(SmrCorrectionBlock.generated_by)`, same for `pasted_by`, `selectinload(WorkOrder.smr_readings).selectinload(SmrPaperReading.created_by)` (add that relationship on the model if missing: `created_by = relationship("User", foreign_keys=[created_by_id], viewonly=True)`), `selectinload(WorkOrder.smr_lines).selectinload(SmrLaborLine.reading)`. The SMR page call at line 379 keeps the default.

- [ ] **Step 1: Write the fixture** in the new test file: `_order_with_paper(db, owner)` — `import_smr` one order (copy `_sheet` from `test_smr_export_xlsx.py`), `wos.add_work_order_labor(... minutes=60)` so BEFORE billed = 1.0 h, `add_worker(SmrWorkerIn(display_name="Ana Ruiz", vendor="Belfor", alias="A. Ruiz"))`, `add_reading(printing_no=1, work_date=date(2026,5,18), hours_as_read=Decimal("3.0"), raw_note="Ana Ruiz 2 h; 1 BT x 1 h")`, `add_line` charged (`worker_id`, `hours_each=2.0`, `reason_code="as_read"`, `reason="paper"`), `add_line` excluded (`vendor="BT Restoration"`, `headcount=1`, `hours_each=1.0`, `status="excluded"`, `exclusion_ground="awaiting invoice (GC, Week 7)"`), `edit_line` the charged line `hours_each=2.5` with `reason="paper re-read"`, `generate_block`, `mark_pasted`. Return `(number, order)`.
- [ ] **Step 2: Write the failing test** `test_smr_orders_history_loads_without_lazy_queries`: `orders = smr_service.smr_orders(db, history=True)`; `db.expunge_all()` is too blunt, so instead assert via `sqlalchemy.inspect(line).unloaded` that `"edits"` and `"reading"` are not in it for the fixture's line, and `"generated_by"` not unloaded on its block.
- [ ] **Step 3: Run** `backend\venv\Scripts\python.exe -m pytest tests\test_smr_export_lines_xlsx.py -v` → FAIL (unexpected keyword `history`).
- [ ] **Step 4: Implement** the keyword and options; keep `_with_lines` unchanged.
- [ ] **Step 5: Run** the test → PASS. Also `tests\test_smr_export_xlsx.py` → 5 PASS.
- [ ] **Step 6: Commit** `feat(smr): smr_orders(history=True) eager-loads edits, block users, reading creators`.

### Task 2: Nine Orders columns

**Files:**
- Modify: `backend/app/services/work_orders_smr_xlsx.py` (`_orders_sheet`, `smr_workbook`)
- Test: `backend/tests/test_smr_export_lines_xlsx.py`

**Interfaces:**
- Produces: module constant `_LINES = ("CORRECTED HOURS", "CORRECTED LABOR $", "CHANGE HOURS", "CHANGE $", "EXCLUDED HOURS", "LINES", "READINGS", "BLOCK VERSION", "BLOCK PASTED AT")` and `_lines_values(order: WorkOrder, baseline: dict) -> list` (nine values). Headers inserted between `list(_PAPER)` and the `BREAKDOWN` columns.
- Values: `lines = smr.correction_lines(order)`; `readings = len(order.smr_readings)`. Without lines: `[None]*5 + [0, readings, None, None]`. With lines: `charge = rules.lines_charge(lines)`; corrected hours `_num(charge.charged_hours)`; corrected $ `_num(charge.labor_total)`; before hours = `(baseline["totals"]["real_billed_minutes"] + baseline["totals"]["skilled_billed_minutes"]) / 60` as float; change hours = corrected − before; change $ = corrected $ − `_num(baseline["totals"]["labor_total"])`; excluded `_num(charge.excluded_hours)`; `charge.count`; readings; block = `lines_service.latest_block(order)` → `version` / `_when(pasted_at)` or None, None.
- `smr_workbook` calls `smr_service.smr_orders(db, history=True)`.

- [ ] **Step 1: Write the failing test** `test_smr_export_orders_line_columns`: fixture order row: `CORRECTED HOURS == 2.5`, `CORRECTED LABOR $ == float(Decimal("2.5") * wo.LABOR_RATE)`, `CHANGE HOURS == 1.5`, `CHANGE $ == corrected − baseline labor_total` (read `row["LABOR TOTAL BEFORE"]`), `EXCLUDED HOURS == 1.0`, `LINES == 2`, `READINGS == 1`, `BLOCK VERSION == 1`, `BLOCK PASTED AT is not None`. Header: `header.index("CORRECTED HOURS") == header.index("PAPER CHECKED BY") + 1`; `header[header.index("BLOCK PASTED AT") + 1].startswith("BREAKDOWN ")` only when a target exists, so assert instead `header[-6:] == TRAIL` unchanged. A second order imported with a reading and no lines (Review Focus 1 and 2): the five figures None, `LINES == 0`, `READINGS == 1`, block cells None.
- [ ] **Step 2: Run** → FAIL (KeyError `CORRECTED HOURS`).
- [ ] **Step 3: Implement** `_LINES`, `_lines_values`, the header/row insertion, the loader call.
- [ ] **Step 4: Run** new file + `tests\test_smr_export_xlsx.py` → all PASS.
- [ ] **Step 5: Commit** `feat(smr): export Orders sheet carries corrected hours, change, lines and block columns`.

### Task 3: Paper Readings + Labor Lines sheets

**Files:**
- Create: `backend/app/services/work_orders_smr_xlsx_lines.py`
- Modify: `backend/app/services/work_orders_smr_xlsx.py` (`smr_workbook` appends the sheets after `Labor Sessions`)
- Test: `backend/tests/test_smr_export_lines_xlsx.py`

**Interfaces:**
- Produces: `add_paper_sheets(workbook: Workbook, orders: list[WorkOrder], db: Session) -> None` creating, in order, `Paper Readings`, `Labor Lines`, then (Tasks 4–5) `Line History`, `Correction Blocks`, `Workers`. Each task adds its sheets to this one function.
- Cycle rule: the new module imports `_num`, `_when`, `TAB_COLOR` from `work_orders_smr_xlsx` at module top and defines a three-line `_sheet(workbook, title, headers, rows)` over `theme`; `work_orders_smr_xlsx.smr_workbook` imports `work_orders_smr_xlsx_lines` inside the function body with a one-line comment naming the cycle.
- Headers: `READING_HEADERS = ("WORK ORDER", "PRINTING", "WORK DATE", "HOURS AS READ", "RAW NOTE", "REVIEWER", "SOURCE", "LINES", "CREATED AT", "CREATED BY")`. `LINE_HEADERS = ("WORK ORDER", "LINE ID", "IMPORT KEY", "PRINTING", "WORK DATE", "DATE BASIS", "WEEK", "VENDOR", "WORKER", "ALIASES", "ALIAS ON PAPER", "HEADCOUNT", "HOURS EACH", "HOURS", "KIND", "REASON CODE", "STATUS", "EXCLUSION GROUND", "NOTE", "CREATED AT", "UPDATED AT")`. `LINE ID` = `str(line.id)`; `PRINTING` = `line.reading.printing_no` or None; `WORKER` = `worker.display_name`; `ALIASES` = `", ".join(worker.aliases)`; `HOURS` = `_num(rules.line_hours(line))`. Rows ordered by order number, then `(work_date is None, work_date, created_at)`.

- [ ] **Step 1: Write the failing test** `test_smr_export_readings_and_labor_lines_sheets`: `book.sheetnames[:6] == ["Orders", "Material Lines", "Labor Entries", "Labor Sessions", "Paper Readings", "Labor Lines"]`; one reading row: `PRINTING == 1`, `HOURS AS READ == 3.0`, `WORK DATE == datetime(2026,5,18)` (openpyxl reads dates back as datetime), `LINES == 2`, `CREATED BY == "Ola Owner"`; labor rows for the order, charged one: `WORKER == "Ana Ruiz"`, `ALIASES == "A. Ruiz"`, `HOURS EACH == 2.5`, `HOURS == 2.5`, `STATUS == "charged"`, `PRINTING == 1`; excluded one: `WORKER is None`, `EXCLUSION GROUND == "awaiting invoice (GC, Week 7)"`, `HOURS == 1.0`. Review Focus 3–4: add a third line via `add_line` with `work_date=None`, `date_basis=rules.WEEK_PLACEMENT_BASIS`, `week=3`, `reading_id=None` — if `SmrLineIn` has no `week` (Deviations say so), insert the `SmrLaborLine` row directly in the test and assert `WORK DATE is None`, `WEEK == 3`, `PRINTING is None`.
- [ ] **Step 2: Run** → FAIL (sheet names).
- [ ] **Step 3: Implement** the module and the call in `smr_workbook`.
- [ ] **Step 4: Run** new file + `tests\test_smr_export_xlsx.py` → PASS.
- [ ] **Step 5: Commit** `feat(smr): export Paper Readings and Labor Lines sheets`.

### Task 4: Line History sheet

**Files:**
- Modify: `backend/app/services/work_orders_smr_xlsx_lines.py`
- Test: `backend/tests/test_smr_export_lines_xlsx.py`

**Interfaces:**
- `HISTORY_HEADERS = ("WORK ORDER", "LINE ID", "IMPORT KEY", "FIELD", "OLD VALUE", "NEW VALUE", "REASON", "RUN ID", "EDITED AT", "EDITED BY")`. `_run_id(reason: Optional[str]) -> Optional[str]`: the reason itself when it matches `^import [0-9a-f]{12}$` (the import writes `f"import {digest.hexdigest()[:12]}"`, `work_orders_smr_import.py:47`), else None. Rows: every `line.edits` for every line, ordered by order number, line `created_at`, `edited_at`.

- [ ] **Step 1: Write the failing test** `test_smr_export_line_history_sheet`: rows for the charged line are `[("created", None), ("hours_each", "paper re-read")]` as `(FIELD, REASON)`; the `hours_each` row has `OLD VALUE == "2.0"`, `NEW VALUE == "2.5"` (text as the history stores it; read `SmrLineEdit` to confirm the Decimal formatting and pin whatever it writes), `RUN ID is None`, `EDITED BY == "Ola Owner"`. Insert one `SmrLineEdit(field="created", reason="import 0dc2a170e862", edited_by_id=owner.id, line_id=...)` directly and assert `RUN ID == "import 0dc2a170e862"`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(smr): export Line History sheet with run id`.

### Task 5: Correction Blocks + Workers sheets

**Files:**
- Modify: `backend/app/services/work_orders_smr_xlsx_lines.py`
- Test: `backend/tests/test_smr_export_lines_xlsx.py`

**Interfaces:**
- `BLOCK_HEADERS = ("WORK ORDER", "VERSION", "LATEST", "STALE", "GENERATED AT", "GENERATED BY", "PASTED AT", "PASTED BY", "LINES DIGEST", "TEXT")`. Every `order.smr_blocks` row, by order then version. `LATEST` = "YES"/"NO"; `STALE` = "YES"/"NO" from `lines_service.latest_block(order).stale` on the latest row, None on older rows. `TEXT` verbatim.
- `WORKER_HEADERS = ("NAME", "VENDOR", "ALIASES", "ADMIN", "LINKED USER", "CREATED AT", "ARCHIVED AT")`. `db.query(SmrWorker).options(selectinload(SmrWorker.user)).order_by(SmrWorker.vendor, SmrWorker.display_name).all()`; archived (merged-away) workers included with `ARCHIVED AT`.

- [ ] **Step 1: Write the failing test** `test_smr_export_blocks_and_workers_sheets`: after the fixture, `edit_line` the charged line again (`note="x"`, reason) so the block goes stale, then `generate_block` again (v2, fresh) → block rows for the order: `[(1, "NO", None), (2, "YES", "NO")]` as `(VERSION, LATEST, STALE)`; v1 `PASTED BY == "Ola Owner"`, v2 `PASTED AT is None`; v2 `TEXT` contains the order number and `LINES DIGEST` is 64 hex chars (check `block_rules.lines_digest` length and pin it). Workers: one row `NAME == "Ana Ruiz"`, `VENDOR == "Belfor"`, `ALIASES == "A. Ruiz"`, `ADMIN == "NO"`, `ARCHIVED AT is None`. `book.sheetnames[-3:] == ["Line History", "Correction Blocks", "Workers"]`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** new file + `tests\test_smr_export_xlsx.py` + `tests\test_smr_lines*.py` (whatever Task 6 named them) → PASS. `wc -l` both xlsx modules < 500.
- [ ] **Step 5: Commit** `feat(smr): export Correction Blocks and Workers sheets`.

### Task 6: Docs

**Files:**
- Modify: `docs/endpoint-map.md` (the `GET /work-orders/smr/export.xlsx` row: nine sheets), `docs/current-state.md` (the export module row and module table: add `work_orders_smr_xlsx_lines.py`), spec `## Deviations` (one line: CHANGE basis = BEFORE billed figure, not the target; RUN ID column added), `docs/superpowers/2026-11-06-smr-paper-import-session-handoff.md` (Task 8 done; Task 7 next).

- [ ] **Step 1: Edit** the four files within their word budgets; delete the Task 8 planning brief from the handoff.
- [ ] **Step 2: Commit** `docs(smr): export sheets shipped (Task 8)`. Do not push; ask the user.

## Self-review

- Spec coverage: nine columns (Task 2), five sheets (Tasks 3–5), numbers as numbers (Global), text included (Task 5). Owner gate unchanged (router untouched).
- Types: `smr_orders(db, history=True)` used in Task 2 as defined in Task 1; `_num`/`_when` imported from the existing module; `rules.line_hours`, `lines_service.latest_block` exist.
- Review Focus 1–5 each pinned to a task's test.
