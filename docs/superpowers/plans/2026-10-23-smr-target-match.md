# SMR27 Target Match Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import the client's per-order labor hours and material dollars from the Breakdown sheet as a target on each SMR order, and show target / charged / remaining / matched in the editor, on the SMR tiles and bar, and in the export.

**Architecture:** One JSONB column `smr_target`, one pure domain function `target_gap` that every surface calls, one Owner import route beside the existing SMR import. The editor and tiles already re-render after each edit, so the gap line needs no new wiring; the match rule lives in one place.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, openpyxl, vanilla ES modules, pytest, Vitest.

**Spec:** `docs/superpowers/specs/2026-10-23-smr-target-match-design.md`

## Global Constraints

- No new dependencies, no new tables. Files under 500 lines (`workOrderCardHtml.js` is already 574: add nothing but two one-line presenter calls there; new HTML goes in `workOrderPresenters.js`).
- Bands: `TARGET_HOURS_BAND = Decimal("0.5")`, `TARGET_MATERIAL_BAND = Decimal("10")`. Undershoot only: overshoot is matched.
- Current hours = `(real_billed_minutes + skilled_billed_minutes) / 60`. Current material = `materials_total * receipt.MARKUP_RATE` (`domain/receipt.py`, `Decimal("1.15")`).
- Targets attach only to orders with `smr_imported_at` set; unknown WO#s are counted, never created. Last duplicate row wins. Re-import overwrites `smr_target`; `smr_baseline` is never touched.
- Money cells: strip `$`, `,` and whitespace; blank = 0. Numbers stored in JSONB as strings (same as `smr_baseline`).
- Route gate: `roles.ROLE_OWNER` for the import. CSP: no inline `style=`; classes in `styles.css`.
- Commit per task with the `Co-Authored-By` and `Claude-Session` trailers from the session reminder. Stage explicit paths only (shared checkout). Do not push without asking (deploy gate).
- Targeted tests per task; the two full suites once at the end.

## Review Focus

1. A Breakdown row whose `Hours` or money cell is not a number (`abc`, `0602/26` in the wrong column): the whole import fails naming the WO# and column; nothing is written. (Task 2 `test_parse_target_row_rejects_non_numeric`.)
2. An order with real-technician hours only, above the target, and zero skilled hours: matched on hours; `remaining_hours == 0`. (Task 2 `test_target_gap_overshoot_is_matched`.)
3. A target of 0 h and $0 material (13 and 60 such rows): matched immediately with both remainings 0, never "short". (Task 2 `test_target_gap_zero_target_is_matched`.)
4. The footer row with a blank WO# and grand totals: skipped, not an error, not "unknown". (Task 3 `test_import_targets_skips_footer_and_unknown`.)
5. Price redaction: a Supervisor opening an SMR order gets `smr_target` with the money fields `None`, never a 500. (Task 4 `test_detail_target_redacts_money_below_techfm_oa`.)

---

### Task 1: Column and migration

**Files:**
- Modify: `backend/app/models.py:419-427` (after `smr_baseline`)
- Create: `backend/alembic/versions/6c8d0e2f3a41_smr_target_column.py` (down_revision `5b7c9d1e2f30`, the current head)
- Test: `backend/tests/test_models_smr.py`

**Interfaces:**
- Produces: `WorkOrder.smr_target: Optional[dict]` (JSONB, nullable).

- [ ] **Step 1: Extend the round-trip test**

In `test_smr_columns_round_trip`, add `smr_target={"hours": "1.5"}` to the `WorkOrder(...)` constructor and `assert reloaded.smr_target == {"hours": "1.5"}` after the baseline assertion.

- [ ] **Step 2: Run it to see it fail**

Run (from `backend/`): `venv/Scripts/python.exe -m pytest tests/test_models_smr.py -v`
Expected: FAIL, `TypeError: 'smr_target' is an invalid keyword argument`.

- [ ] **Step 3: Add the column and migration**

`models.py`: `smr_target = Column(JSONB, nullable=True)` with a two-line comment pointing at the new spec. Migration: `op.add_column("work_orders", sa.Column("smr_target", postgresql.JSONB(), nullable=True))`; downgrade drops it. Docstring: one sentence, spec path.

- [ ] **Step 4: Apply and verify**

Run: `venv/Scripts/python.exe -m alembic upgrade head` then the Step 2 command.
Expected: migration applies; test PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models.py backend/alembic/versions/6c8d0e2f3a41_smr_target_column.py backend/tests/test_models_smr.py
git commit -m "feat(smr): smr_target JSONB column for the client's per-order target"
```

---

### Task 2: Domain: target row parsing and the gap rule

**Files:**
- Modify: `backend/app/domain/work_orders_smr.py` (append after `deltas`)
- Test: `backend/tests/test_work_orders_smr_domain.py`

**Interfaces:**
- Produces:
  - `TARGET_REQUIRED_HEADERS: tuple[str, ...] = ("WO#", "Hours", "Total Material Cost")`
  - `TARGET_HOURS_BAND = Decimal("0.5")`, `TARGET_MATERIAL_BAND = Decimal("10")`
  - `parse_money(text: Optional[str], *, number: str, column: str) -> Decimal` — strips `$`, `,`, whitespace; blank/None → `Decimal(0)`; non-numeric → `WorkOrderStateError(f"Row {number}: {column} is not a number.")`
  - `parse_target_row(row: dict) -> Optional[dict]` — `None` when `WO#` is blank; else `{"number": str, "hours": Decimal, "labor_total": Decimal, "materials_total": Decimal, "total": Decimal, "source_row": dict}` (`source_row` = every cell trimmed, `None` keys dropped, exactly as `parse_smr_row` does). Reads `Hours`, `Labor $`, `Total Material Cost`, `Total L&M`.
  - `target_record(parsed: dict, *, imported_at: datetime) -> dict` — the JSONB value: `{"imported_at": iso, "hours": str, "labor_total": str, "materials_total": str, "total": str, "source_row": {...}}` using `_money`-style 2-dp strings for money and `str(Decimal)` for hours.
  - `target_gap(target: Optional[dict], *, billed_minutes: int, materials_total: Decimal) -> Optional[dict]` — `None` when `target` is falsy; else keys `hours, labor_total, materials_total, total` (Decimals from the record), `current_hours` (= `Decimal(billed_minutes) / 60`), `current_materials_total` (= `materials_total * receipt.MARKUP_RATE`, quantized to cents), `gap_hours`, `gap_materials_total` (current − target), `remaining_hours`, `remaining_materials_total` (`max(Decimal(0), -gap)`), `matched: bool` (`remaining_hours <= TARGET_HOURS_BAND and remaining_materials_total <= TARGET_MATERIAL_BAND`).

- [ ] **Step 1: Write the failing tests**

```python
BREAKDOWN = ["WO#", "Unit#", "Closed Date", "Labor Type", "BELFOR HRS", "Add HRS",
             "Duplicate HRS", "Hours", "Labor $", "OT Hours", "OT $", "Total Material Cost", "Total L&M", ""]

def _brow(**o):
    row = dict(zip(BREAKDOWN, ["23281585", "Young Hall 108", "05/21/26", "SL", "", "", "", "1", "$62.50", "", "$0.00", "$9.38", "$71.88", ""]))
    row.update(o); return row

def test_parse_target_row_reads_hours_and_money():
    p = smr.parse_target_row(_brow(**{"Labor $": "$1,656.25", "Hours": "26.5"}))
    assert (p["number"], p["hours"], p["labor_total"], p["materials_total"], p["total"]) == (
        "23281585", Decimal("26.5"), Decimal("1656.25"), Decimal("9.38"), Decimal("71.88"))
    assert p["source_row"]["Unit#"] == "Young Hall 108"

def test_parse_target_row_blank_number_is_none_and_blank_money_is_zero():
    assert smr.parse_target_row(_brow(**{"WO#": ""})) is None
    assert smr.parse_target_row(_brow(**{"Total Material Cost": "", "Hours": ""}))["materials_total"] == Decimal(0)

def test_parse_target_row_rejects_non_numeric():
    with pytest.raises(WorkOrderStateError, match="23281585: Hours"):
        smr.parse_target_row(_brow(Hours="abc"))

def test_target_record_is_json_safe():
    rec = smr.target_record(smr.parse_target_row(_brow()), imported_at=datetime(2026, 10, 23, tzinfo=timezone.utc))
    assert rec["hours"] == "1" and rec["materials_total"] == "9.38" and rec["imported_at"].startswith("2026-10-23")
    json.dumps(rec)

def _target(hours="2", material="67.16"):
    return {"hours": hours, "labor_total": "0.00", "materials_total": material, "total": "0.00", "source_row": {}}

def test_target_gap_short_order():
    g = smr.target_gap(_target(), billed_minutes=60, materials_total=Decimal("40.00"))
    assert g["current_hours"] == Decimal(1) and g["current_materials_total"] == Decimal("46.00")
    assert g["remaining_hours"] == Decimal(1) and g["remaining_materials_total"] == Decimal("21.16")
    assert g["gap_hours"] == Decimal(-1) and g["matched"] is False

def test_target_gap_within_band_is_matched():
    g = smr.target_gap(_target(), billed_minutes=90, materials_total=Decimal("50.00"))  # 57.50 marked, 9.66 short
    assert g["matched"] is True and g["remaining_hours"] == Decimal("0.5")

def test_target_gap_just_outside_band_is_short():
    assert smr.target_gap(_target(), billed_minutes=60, materials_total=Decimal("58.40"))["matched"] is False
    assert smr.target_gap(_target(), billed_minutes=120, materials_total=Decimal("49.00"))["matched"] is False  # 56.35, 10.81 short

def test_target_gap_overshoot_is_matched():
    g = smr.target_gap(_target(), billed_minutes=240, materials_total=Decimal("100.00"))
    assert g["matched"] is True and g["remaining_hours"] == 0 and g["remaining_materials_total"] == 0
    assert g["gap_hours"] == Decimal(2)

def test_target_gap_zero_target_is_matched():
    assert smr.target_gap(_target("0", "0.00"), billed_minutes=0, materials_total=Decimal(0))["matched"] is True

def test_target_gap_none_without_target():
    assert smr.target_gap(None, billed_minutes=30, materials_total=Decimal(1)) is None
```

Add `import pytest` and `from app.domain.errors import WorkOrderStateError` to the test imports.

- [ ] **Step 2: Run to see them fail**

Run: `venv/Scripts/python.exe -m pytest tests/test_work_orders_smr_domain.py -k "target" -v`
Expected: FAIL, `AttributeError: ... has no attribute 'parse_target_row'`.

- [ ] **Step 3: Implement the Interfaces block**

Import `from app.domain import receipt`. `current_materials_total` quantizes with `Decimal("0.01")`, `ROUND_HALF_UP`. Module docstring: add one sentence naming the target rule.

- [ ] **Step 4: Run to see them pass**

Same command. Expected: all `target` tests PASS; the rest of the file still PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/domain/work_orders_smr.py backend/tests/test_work_orders_smr_domain.py
git commit -m "feat(smr): target row parsing and the undershoot-only gap rule"
```

---

### Task 3: Target import route

**Files:**
- Modify: `backend/app/schemas/work_orders_smr.py` (after `SmrImportResult`)
- Modify: `backend/app/services/work_orders_smr.py` (after `import_smr`; generalize `_read_sheet`)
- Modify: `backend/app/routers/work_orders_smr.py` (after `import_smr`)
- Modify: `backend/tests/test_route_role_gates.py:661` (parametrize list)
- Test: `backend/tests/test_smr_import.py`

**Interfaces:**
- Consumes: Task 2 `parse_target_row`, `target_record`, `TARGET_REQUIRED_HEADERS`.
- Produces:
  - `SmrTargetImportResult(BaseModel)`: `total: int, targeted: int, skipped: int, unknown: int, unknown_numbers: list[str]` (first 50).
  - `_read_sheet(csv_bytes: bytes, *, required: tuple[str, ...] = smr.SMR_REQUIRED_HEADERS) -> list[dict]` (existing function gains the keyword; existing caller unchanged).
  - `import_smr_targets(db: Session, *, csv_bytes: bytes, user: User) -> SmrTargetImportResult`.
  - Route `POST /work-orders/smr/import-targets`, endpoint name `import_smr_targets`, `require_min_role(roles.ROLE_OWNER)`, same `read_capped` / `to_http` shape as `import_smr`.

- [ ] **Step 1: Write the failing tests**

```python
BREAKDOWN_HEADERS = "WO#,Unit#,Closed Date,Labor Type,BELFOR HRS,Add HRS,Duplicate HRS,Hours,Labor $,OT Hours,OT $,Total Material Cost,Total L&M,"

def _breakdown(rows):
    # Money cells are quoted: "$1,067.16" carries a comma.
    lines = [BREAKDOWN_HEADERS] + [f'{n},Young Hall 108,05/21/26,SL,,,,{h},$0.00,,$0.00,"{m}",$0.00,' for n, h, m in rows]
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")

def test_import_targets_attaches_last_row_wins(db):
    owner = _user(db, roles.ROLE_OWNER)
    number = _num()
    smr_service.import_smr(db, csv_bytes=_csv([(number, "Closed", "")]), user=owner)
    result = smr_service.import_smr_targets(db, csv_bytes=_breakdown([(number, "0.5", "$31.25"), (number, "1.5", "$1,067.16")]), user=owner)
    assert (result.total, result.targeted, result.unknown, result.skipped) == (2, 2, 0, 0)
    order = wos.find_by_number(db, number)
    assert order.smr_target["hours"] == "1.5" and order.smr_target["materials_total"] == "1067.16"
    assert order.smr_target["source_row"]["Unit#"] == "Young Hall 108"
    assert order.smr_baseline is not None and "hours" not in order.smr_baseline

def test_import_targets_skips_footer_and_unknown(db):
    owner = _user(db, roles.ROLE_OWNER)
    smr_number, live_number, ghost = _num(), _num(), _num()
    smr_service.import_smr(db, csv_bytes=_csv([(smr_number, "Closed", "")]), user=owner)
    wos.get_or_create_work_order(db, number=live_number, created_by_id=owner.id)  # not SMR
    sheet = _breakdown([(smr_number, "1", "$9.38"), (live_number, "1", "$1.00"), (ghost, "1", "$1.00"), ("", "4455.5", "$149,961.19")])
    result = smr_service.import_smr_targets(db, csv_bytes=sheet, user=owner)
    assert (result.total, result.targeted, result.unknown, result.skipped) == (4, 1, 2, 1)
    assert sorted(result.unknown_numbers) == sorted([live_number, ghost])
    assert wos.find_by_number(db, live_number).smr_target is None
    assert wos.find_by_number(db, ghost) is None

def test_import_targets_requires_breakdown_headers(db):
    owner = _user(db, roles.ROLE_OWNER)
    with pytest.raises(WorkOrderStateError, match="Total Material Cost"):
        smr_service.import_smr_targets(db, csv_bytes=_csv([]), user=owner)

def test_import_targets_rerun_overwrites(db):
    owner = _user(db, roles.ROLE_OWNER)
    number = _num()
    smr_service.import_smr(db, csv_bytes=_csv([(number, "Closed", "")]), user=owner)
    smr_service.import_smr_targets(db, csv_bytes=_breakdown([(number, "1", "$5.00")]), user=owner)
    smr_service.import_smr_targets(db, csv_bytes=_breakdown([(number, "2", "$6.00")]), user=owner)
    assert wos.find_by_number(db, number).smr_target["hours"] == "2"
```

Role gate: add `("import_smr_targets", roles.ROLE_OWNER)` to the parametrize list at `test_route_role_gates.py:661`.

- [ ] **Step 2: Run to see them fail**

Run: `venv/Scripts/python.exe -m pytest tests/test_smr_import.py tests/test_route_role_gates.py -k "target" -v`
Expected: FAIL (`no attribute 'import_smr_targets'`; gate test: endpoint not found).

- [ ] **Step 3: Implement**

Service loop: `parsed = smr.parse_target_row(row)`; `None` → `skipped += 1`; `existing = wos.find_by_number(db, parsed["number"])`; `existing is None or existing.smr_imported_at is None` → `unknown += 1`, append number; else `existing.smr_target = smr.target_record(parsed, imported_at=now)`, `targeted += 1`. One `db.commit()` after the loop. `unknown_numbers=unknown_numbers[:50]`. Router docstring: one sentence; `responses` like `import_smr`.

- [ ] **Step 4: Run to see them pass**

Same command, then `venv/Scripts/python.exe -m pytest tests/test_smr_import.py tests/test_route_role_gates.py -q`.
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/work_orders_smr.py backend/app/services/work_orders_smr.py backend/app/routers/work_orders_smr.py backend/tests/test_smr_import.py backend/tests/test_route_role_gates.py
git commit -m "feat(smr): Owner-only Breakdown sheet import sets each order's target"
```

---

### Task 4: Target on the detail and the tiles

**Files:**
- Modify: `backend/app/schemas/work_orders_smr.py` (`SmrTargetOut`, `SmrTile.target`, `SmrCounts`, `SmrTilesResponse.remaining`)
- Modify: `backend/app/schemas/work_orders.py:409-415` (`WorkOrderDetail.smr_target`)
- Modify: `backend/app/routers/work_orders.py:494-553` (`_detail`)
- Modify: `backend/app/services/work_orders_smr.py` (`tile_for`, `list_smr_tiles`)
- Test: `backend/tests/test_smr_tiles.py`, `backend/tests/test_work_order_skilled_labor.py`

**Interfaces:**
- Consumes: Task 2 `target_gap`.
- Produces:
  - `SmrTargetOut(BaseModel)`: `hours: Decimal, current_hours: Decimal, gap_hours: Decimal, remaining_hours: Decimal, matched: bool`, and `labor_total, total, materials_total, current_materials_total, gap_materials_total, remaining_materials_total: Optional[Decimal] = None` (None when redacted). Classmethod `from_gap(gap: dict, *, include_price: bool) -> "SmrTargetOut"`.
  - `WorkOrderDetail.smr_target: Optional[SmrTargetOut] = None` (import from `schemas.work_orders_smr`; that module already imports from `schemas.work_orders`, so move `SmrTargetOut` into `schemas/work_orders.py` next to `WorkOrderDetail` if a cycle appears, and re-export it from `work_orders_smr`).
  - `SmrTile.target: Optional[SmrTargetOut] = None`; `SmrCounts.matched: int`, `short: int`, `no_target: int`; `SmrTilesResponse.remaining: SmrRemaining` where `SmrRemaining(hours: Decimal, materials_total: Decimal)`.

- [ ] **Step 1: Write the failing tests**

`test_smr_tiles.py` (reuse `_sheet`, add a `_breakdown` like Task 3's):

```python
def test_smr_tiles_carry_target_and_match_counts(db):
    owner = _user(db)
    short, matched, none = [f"SMR-{uuid.uuid4().hex[:8]}" for _ in range(3)]
    smr_service.import_smr(db, csv_bytes=_sheet([short, matched, none]), user=owner)
    smr_service.import_smr_targets(db, csv_bytes=_breakdown([(short, "2", "$67.16"), (matched, "0.5", "$0.00")]), user=owner)
    wos.add_work_order_labor(db, wos.find_by_number(db, matched).id, user=owner, technician_id=None, minutes=30)
    page = smr_service.list_smr_tiles(db)
    mine = {t.number: t for t in page.tiles if t.number in (short, matched, none)}
    assert mine[none].target is None
    assert mine[short].target.matched is False and mine[short].target.remaining_hours == Decimal(2)
    assert mine[short].target.remaining_materials_total == Decimal("67.16")
    assert mine[matched].target.matched is True and mine[matched].target.current_hours == Decimal("0.5")
    assert page.counts.matched >= 1 and page.counts.short >= 1 and page.counts.no_target >= 1
    assert page.remaining.hours >= Decimal(2) and page.remaining.materials_total >= Decimal("67.16")
```

`test_work_order_skilled_labor.py` (reuse its `_detail` import and SMR-order helper):

```python
def test_detail_target_redacts_money_below_techfm_oa(db):
    # arrange an SMR order with a target of 1 h / $9.38 and a 30-min skilled entry
    full = _detail(wos.get_work_order(db, order.id, user=admin), include_price=True)
    assert full.smr_target.remaining_hours == Decimal("0.5") and full.smr_target.materials_total == Decimal("9.38")
    assert full.smr_target.current_materials_total == Decimal(0)
    redacted = _detail(wos.get_work_order(db, order.id, user=admin), include_price=False)
    assert redacted.smr_target.remaining_hours == Decimal("0.5")
    assert redacted.smr_target.materials_total is None and redacted.smr_target.remaining_materials_total is None

def test_detail_target_absent_without_target(db):
    assert _detail(wos.get_work_order(db, order.id, user=admin), include_price=True).smr_target is None
```

Check `_detail`'s real signature at `routers/work_orders.py:494` before writing the calls; match how the existing test at line 48 calls it.

- [ ] **Step 2: Run to see them fail**

Run: `venv/Scripts/python.exe -m pytest tests/test_smr_tiles.py tests/test_work_order_skilled_labor.py -k "target" -v`
Expected: FAIL (`SmrTile` has no attribute `target`; `WorkOrderDetail` has no `smr_target`).

- [ ] **Step 3: Implement**

`_detail`: `gap = smr.target_gap(work_order.smr_target, billed_minutes=split.real_billed + split.skilled_billed, materials_total=_materials_total(work_order))`; `smr_target=SmrTargetOut.from_gap(gap, include_price=include_price) if gap else None`. `tile_for`: same call with `current["totals"]["real_billed_minutes"] + ...["skilled_billed_minutes"]` and `Decimal(current["totals"]["materials_total"])`, `include_price=True` (tiles are Admin+). `list_smr_tiles`: `matched = sum(t.target.matched ...)`, `short = sum(target and not matched)`, `no_target = sum(t.target is None)`, `remaining` sums over `all_tiles`.

- [ ] **Step 4: Run to see them pass**

Same command, then `venv/Scripts/python.exe -m pytest tests/test_smr_tiles.py tests/test_work_order_skilled_labor.py tests/test_smr_exclusion.py -q`.
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/work_orders_smr.py backend/app/schemas/work_orders.py backend/app/routers/work_orders.py backend/app/services/work_orders_smr.py backend/tests/test_smr_tiles.py backend/tests/test_work_order_skilled_labor.py
git commit -m "feat(smr): target, remaining and matched on the detail and the tiles"
```

---

### Task 5: Export columns

**Files:**
- Modify: `backend/app/services/work_orders_smr_xlsx.py` (`_orders_sheet`, `_source_columns`)
- Test: `backend/tests/test_smr_export_xlsx.py`

**Interfaces:**
- Consumes: Task 2 `target_gap`.
- Produces: Orders sheet headers, inserted after the DELTA triples and before `_TRAIL`: `MATERIALS +15% AFTER`, `TARGET HOURS`, `TARGET LABOR $`, `TARGET MATERIAL $`, `TARGET TOTAL`, `GAP HOURS`, `GAP MATERIAL $`, `MATCHED` (`YES`/`NO`/blank), `TARGET IMPORTED AT`; then every Breakdown `source_row` column prefixed `BREAKDOWN ` (union across orders, Breakdown order via a `TARGET_SHEET_COLUMNS` tuple in the domain module, unknown after, blank header dropped). All blank when the order has no target.

- [ ] **Step 1: Write the failing test**

```python
def test_smr_export_target_and_gap_columns(db):
    owner = _user(db)
    number, bare = [f"SMR-{uuid.uuid4().hex[:8]}" for _ in range(2)]
    smr_service.import_smr(db, csv_bytes=_sheet([number, bare]), user=owner)
    smr_service.import_smr_targets(db, csv_bytes=_breakdown([(number, "2", "$67.16")]), user=owner)
    order = wos.find_by_number(db, number)
    _line(db, order, owner, qty="2", price="20.00")  # 40.00 base, 46.00 marked
    wos.add_work_order_labor(db, order.id, user=owner, technician_id=None, minutes=60)
    header, rows = _rows(_book(db)["Orders"])
    assert header[-6:] == ["EDITED", "SMR IMPORTED AT", "BASELINE AT", "LAST EDITED AT", "LAST EDITED BY", "ARCHIVED AT"]
    assert header.index("TARGET HOURS") > header.index("TOTAL DELTA")
    row = next(r for r in rows if r["WORK ORDER"] == number)
    assert (row["TARGET HOURS"], row["TARGET MATERIAL $"], row["MATERIALS +15% AFTER"]) == (2.0, 67.16, 46.0)
    assert (row["GAP HOURS"], row["GAP MATERIAL $"], row["MATCHED"]) == (-1.0, -21.16, "NO")
    assert row["BREAKDOWN Unit#"] == "Young Hall 108" and row["TARGET IMPORTED AT"] is not None
    empty = next(r for r in rows if r["WORK ORDER"] == bare)
    assert empty["TARGET HOURS"] is None and empty["MATCHED"] is None
```

Add a `_breakdown` helper as in Task 3.

- [ ] **Step 2: Run to see it fail**

Run: `venv/Scripts/python.exe -m pytest tests/test_smr_export_xlsx.py -k target -v`
Expected: FAIL, `KeyError: 'TARGET HOURS'`.

- [ ] **Step 3: Implement**

Add `_TARGET = (...)` header tuple and `_target_columns(orders)` (mirror of `_source_columns` over `smr_target["source_row"]`). In `_orders_sheet`, compute `gap` per order as Task 4's `tile_for` does and append `_num(...)` values; `GAP MATERIAL $` rounds to cents via the already-quantized gap.

- [ ] **Step 4: Run to see it pass**

Run: `venv/Scripts/python.exe -m pytest tests/test_smr_export_xlsx.py -q`
Expected: all PASS (existing `header[-6:]` assertion included).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/work_orders_smr_xlsx.py backend/app/domain/work_orders_smr.py backend/tests/test_smr_export_xlsx.py
git commit -m "feat(smr): target and gap columns on the Orders sheet"
```

---

### Task 6: SMR Labor Import button

**Files:**
- Modify: `backend/static/api.js:1003-1012` (after `apiImportSmr`)
- Modify: `backend/static/pages/integrations.html:23,31`
- Modify: `backend/static/views/workOrderIntegrations.js:33-34,53-54,400-425`
- Modify: `backend/static/tips.js:264-267`
- Test: `tests/frontend/helpers/endpointTable.js:40`, `tests/frontend/views/workOrders/integrations.test.js:169-200`

**Interfaces:**
- Produces: `apiImportSmrTargets(file)` → `POST /work-orders/smr/import-targets` multipart; `#wo-smr-targets-file`, `#wo-smr-targets-btn` ("SMR Labor Import", Owner-only, `tip` key `integrations.smrTargets`).

- [ ] **Step 1: Write the failing tests**

`endpointTable.js`: `{ fn: "apiImportSmrTargets", args: [uploadFile()], method: "POST", url: "/work-orders/smr/import-targets", multipart: true }`.

`integrations.test.js`, beside the SMR Import block:

```js
it("SMR Labor Import is Owner-only and reports targeted / unknown counts", async () => {
  // supervisor: hidden; owner: visible, click opens the file input,
  // change posts the file and the message reads
  // "SMR labor targets: 3 orders set, 2 unknown WO#s skipped."
  respond("post", "/work-orders/smr/import-targets", { total: 6, targeted: 3, skipped: 1, unknown: 2, unknown_numbers: ["1", "2"] });
  ...
  expect(requestFor("/work-orders/smr/import-targets", "POST")).not.toBeNull();
  expect(el("wo-import-message").textContent).toBe("SMR labor targets: 3 orders set, 2 unknown WO#s skipped.");
});
```

- [ ] **Step 2: Run to see them fail**

Run (repo root): `npx vitest run tests/frontend/unit/api.endpoints.test.js tests/frontend/views/workOrders/integrations.test.js`
Expected: FAIL (`apiImportSmrTargets is not a function`; element null).

- [ ] **Step 3: Implement**

`api.js`: copy `apiImportSmr` with the new path. `integrations.html`: second hidden file input and a `secondary-btn` next to `wo-smr-import-btn` with its `tip-btn`. `workOrderIntegrations.js`: `handleSmrTargetsImport` mirroring `handleSmrImport` with the message above; hide with the same Owner check. `tips.js`: `"integrations.smrTargets": { label: "SMR Labor Import (Owner)", text: "Imports the client's Breakdown sheet. Each WO#'s hours and material dollars become that SMR order's target; the SMR27 page and the editor show how far each order is from it. Rows for unknown WO#s are skipped." }`.

- [ ] **Step 4: Run to see them pass**

Same command plus `npx vitest run tests/frontend/unit/staticImports.test.js tests/frontend/unit/tips.test.js`.
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/static/api.js backend/static/pages/integrations.html backend/static/views/workOrderIntegrations.js backend/static/tips.js tests/frontend/helpers/endpointTable.js tests/frontend/views/workOrders/integrations.test.js
git commit -m "feat(smr): SMR Labor Import button posts the Breakdown sheet"
```

---

### Task 7: Editor target lines

**Files:**
- Modify: `backend/static/views/workOrderPresenters.js` (after `materialsTotalHtml`)
- Modify: `backend/static/views/workOrderCardHtml.js:125,526` (one call each)
- Modify: `backend/static/styles.css:5235` (after `.wo-materials-total .charge-marked`)
- Modify: `tests/frontend/helpers/factories.js` (`workOrderDetail` gains `smr_target: null`)
- Test: `tests/frontend/views/workOrders/render.test.js`

**Interfaces:**
- Produces: `targetLaborHtml(detail)` and `targetMaterialsHtml(detail)` → `""` unless `detail.smr && detail.smr_target`; otherwise `<div class="wo-target wo-target--matched|short">…</div>`. Copy (exact):
  - labor: `Client sheet: 2.0 h · Charged: 1.5 h · Remaining: 0.5 h · Within 0.5 h` / `… · Short by 1.0 h` / `… · Matched`
  - materials (money `null` → return `""`): `Client sheet: $67.16 · Charged (+15%): $0.00 · Remaining: $67.16 · Short by $67.16` / `… · Within $10` / `… · Matched`
  - State word per line: remaining `0` → `Matched`; `0 < remaining ≤ band` → `Within 0.5 h` / `Within $10`; above band → `Short by …`. Class `--matched` when remaining ≤ band for that line, else `--short`.
  - Hours formatted with one decimal via `Number(x).toFixed(1)`; money via `formatMoney`.

- [ ] **Step 1: Write the failing tests**

In `render.test.js`, near line 473:

```js
it("SMR order with a target shows the gap under labor and materials", async () => {
  const detail = workOrderDetail({ smr: true, smr_target: {
    hours: "2", current_hours: "1.5", gap_hours: "-0.5", remaining_hours: "0.5", matched: false,
    labor_total: "125.00", total: "192.16", materials_total: "67.16", current_materials_total: "0.00",
    gap_materials_total: "-67.16", remaining_materials_total: "67.16" } });
  // open as admin ...
  const targets = cardEl.querySelectorAll(".wo-target");
  expect(targets).toHaveLength(2);
  expect(targets[0].textContent).toBe("Client sheet: 2.0 h · Charged: 1.5 h · Remaining: 0.5 h · Within 0.5 h");
  expect(targets[0].classList.contains("wo-target--matched")).toBe(true);
  expect(targets[1].textContent).toBe("Client sheet: $67.16 · Charged (+15%): $0.00 · Remaining: $67.16 · Short by $67.16");
  expect(targets[1].classList.contains("wo-target--short")).toBe(true);
});

it("no target line without a target, and no money line when redacted", async () => {
  // smr: true, smr_target: null -> 0 .wo-target
  // smr: true, smr_target with materials_total: null (supervisor) -> 1 .wo-target (labor only)
});
```

- [ ] **Step 2: Run to see them fail**

Run: `npx vitest run tests/frontend/views/workOrders/render.test.js`
Expected: FAIL, `expected 0 to have length 2`.

- [ ] **Step 3: Implement**

Presenters per the Interfaces block; `workOrderCardHtml.js` inserts `${targetLaborHtml(detail)}` after `${laborSummaryHtml(detail)}` (line 125) and `${targetMaterialsHtml(detail)}` after `${materialsTotalHtml(detail)}` (line 526), adding both to the import at line 32. CSS: `.wo-target { text-align: right; font-size: var(--fs-sm); margin: 0 0 var(--space-3); }`, `.wo-target--matched { color: var(--color-success, #1a7f37); }`, `.wo-target--short { color: var(--color-brand); font-weight: var(--fw-bold); }` (check the token names at the top of `styles.css` and use the ones that exist).

- [ ] **Step 4: Run to see them pass**

Same command plus `npx vitest run tests/frontend/views/workOrders tests/frontend/unit/staticImports.test.js`.
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/static/views/workOrderPresenters.js backend/static/views/workOrderCardHtml.js backend/static/styles.css tests/frontend/helpers/factories.js tests/frontend/views/workOrders/render.test.js
git commit -m "feat(smr): editor shows client target, charged and remaining under labor and materials"
```

---

### Task 8: SMR page bar, filters and tiles

**Files:**
- Modify: `backend/static/views/smr.js` (`barHtml`, `tileHtml`, `matches`)
- Modify: `backend/static/pages/smr.html:63-68` (filter buttons)
- Modify: `backend/static/styles.css:5845` (after `.smr-tile-meta`)
- Test: `tests/frontend/views/smr.test.js`

**Interfaces:**
- Consumes: Task 4 payload: `counts.matched/short/no_target`, `remaining.hours/materials_total`, `tile.target`.
- Produces: buttons in order Untouched · Short · Edited · Archived · Matched · All (`id="smr-filter-short"`, `data-filter="short"`; `id="smr-filter-matched"`, `data-filter="matched"`); bar cells appended after `ARCHIVED`: `N MATCHED`, `N SHORT`, `N NO TARGET`, `REMAINING 123.5 H`, `REMAINING $4,567.89`; tile gains a line `<span class="smr-tile-target">` with `0.5 H · $67.16 TO GO`, `MATCHED`, or `NO TARGET`; `matches(tile, "short")` = `tile.target && !tile.target.matched`, `"matched"` = `tile.target?.matched === true`; `.smr-tile--matched` class when matched (styled `border-width: 3px`, no opacity change).

- [ ] **Step 1: Write the failing tests**

Extend `tile()` / payload factories in `smr.test.js` with `target: null`, `counts: {..., matched, short, no_target}`, `remaining: { hours: "2.5", materials_total: "134.32" }`, then:

```js
it("bar shows match counts and remaining; Short and Matched filters select by target", async () => {
  // tiles: A target short, B target matched, C no target
  expect(byId("smr-bar").textContent).toContain("1 MATCHED");
  expect(byId("smr-bar").textContent).toContain("1 SHORT");
  expect(byId("smr-bar").textContent).toContain("1 NO TARGET");
  expect(byId("smr-bar").textContent).toContain("REMAINING 2.5 H");
  expect(byId("smr-bar").textContent).toContain("REMAINING $134.32");
  expect(tiles()[0].querySelector(".smr-tile-target").textContent).toBe("2.0 H · $67.16 TO GO");
  expect(tiles()[1].querySelector(".smr-tile-target").textContent).toBe("MATCHED");
  expect(tiles()[2].querySelector(".smr-tile-target").textContent).toBe("NO TARGET");
  byId("smr-filter-short").click();
  expect(tiles().filter((t) => !t.hidden).map((t) => t.dataset.number)).toEqual(["A"]);
  byId("smr-filter-matched").click();
  expect(tiles().filter((t) => !t.hidden).map((t) => t.dataset.number)).toEqual(["B"]);
});
```

Also update the existing button-order assertion if one exists (`smr-controls` children ids).

- [ ] **Step 2: Run to see it fail**

Run: `npx vitest run tests/frontend/views/smr.test.js`
Expected: FAIL (`smr-filter-short` is null).

- [ ] **Step 3: Implement**

`smr.js`: add `targetLine(tile)` returning the three strings (hours `toFixed(1)`, money `formatMoney`); extend `barHtml`, `tileHtml`, `matches`, `tileState` (append `--matched` class alongside the existing state class, not instead). `smr.html`: two buttons. CSS: `#smr-page .smr-tile--matched { border-width: 3px; }`, `#smr-page .smr-tile-target { letter-spacing: .06em; font-weight: 700; }`.

- [ ] **Step 4: Run to see it pass**

Run: `npx vitest run tests/frontend/views/smr.test.js tests/frontend/views/nav.test.js tests/frontend/unit/staticImports.test.js`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/static/views/smr.js backend/static/pages/smr.html backend/static/styles.css tests/frontend/views/smr.test.js
git commit -m "feat(smr): Short and Matched filters, remaining-to-target on tiles and bar"
```

---

### Task 9: Docs, full suites, handoff

**Files:**
- Modify: `docs/endpoint-map.md:153-155` (row S4), `docs/current-state.md:272-280,722-735` (one line each for `smr_target`, `SmrTargetOut`, the route)
- Modify: `docs/superpowers/2026-10-23-smr-session-handoff.md` (State and Next sections only; ≤ 500 words)

- [ ] **Step 1: Docs**

`endpoint-map.md`: `| S4 | POST | /work-orders/smr/import-targets | **owner** | work_orders_smr.py → work_orders_smr.import_smr_targets | work_orders (r/w: sets smr_target on SMR orders only) | apiImportSmrTargets | workOrderIntegrations.js |`. `current-state.md`: extend the SMR bullet with the target column and the gap rule in one line each; delete a stale line if the budget is breached.

- [ ] **Step 2: Full suites**

Run (from `backend/`): `venv/Scripts/python.exe -m pytest tests -q -m "not e2e"`; (repo root): `npx vitest run`.
Expected: both green. If `test_cascade_deletes_with_user` fails on the dev DB, that is the known environmental failure (memory), not a regression; say so in the report.

- [ ] **Step 3: Handoff**

Update State (head commit, suites) and Next (the user's in-app check: Integrations → SMR Labor Import with `C:\Users\mcclu\Desktop\SMR27 Work Order Breakdown & Labor Hours - Work Order Breakdown.csv`; expected `targeted 668 / unknown 22 / skipped 1` on a DB that holds the 688-row import; then SMR27 → Short → tile → add Skilled hours and materials → watch the two lines → Export).

- [ ] **Step 4: Commit, do not push**

```bash
git add docs/endpoint-map.md docs/current-state.md docs/superpowers/2026-10-23-smr-session-handoff.md
git commit -m "docs(smr): target import route, gap rule and handoff"
```

Then ask the user before `git push` (production deploy).
