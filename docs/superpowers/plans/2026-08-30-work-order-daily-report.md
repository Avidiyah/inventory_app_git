# Work Order Daily Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship an Admin-only daily digest tab on the User Hub — what closed, what is about to close, what arrived — rendered on the page and downloadable as one `SECTION`-prefixed CSV built from the same payload.

**Architecture:** A new service module `services/work_order_report.py` owns the whole feature: it derives two nested Central calendar windows from `domain/labor_day.py`, runs five section queries against `work_orders`, and returns one frozen `DailyReport` dataclass. Two thin `routers/hub.py` handlers render that payload — one as JSON via new `schemas/hub.py` models, one as CSV via `report_csv(payload)`. The CSV cells are precomputed into the payload by the shared `services.work_orders.export_row`, so the file and the screen cannot drift and the file still round-trips through the work-order importer.

**Tech Stack:** Python 3.13 · FastAPI · SQLAlchemy 2.0 ORM · Pydantic v2 · pytest (real Postgres via the `db` fixture) · vanilla ES modules + CSP-safe DOM for the frontend.

**Spec:** `docs/superpowers/specs/2026-08-30-work-order-daily-report-design.md` — read it alongside this plan. Every decision below argues from a numbered decision (R1–R12) or section (§3–§12) there.

---

## Global Constraints

- **Windows are Central calendar periods, derived server-side.** Both endpoints take **no query parameters** (R1, §5). Use `app.domain.labor_day` exclusively — `central_date_of`, `day_bounds`, `week_bounds_containing`. Never construct a `ZoneInfo` or do date arithmetic by hand.
- **Closed means `archived_at`, not `completed_at`** (R2). New means `created_at` (R4). Closing is a snapshot of live rows in `ready_to_complete` / `completed` / `review` (R3).
- **Route floor is `roles.ROLE_ADMIN`** for both handlers (R5, §6). This is the *only* pair of Admin-floored routes in the app; `tests/test_route_role_gates.py` must be updated deliberately or the suite fails.
- **`auto_closed_batch_id` does not exist on `WorkOrder` in this branch.** It arrives with `docs/superpowers/specs/2026-08-30-netfacilities-reconcile-design.md`. Until then `auto_closed` is a constant `False` and `auto_closed_count` is `0` (§4, R10). The field must exist in the contract from day one so the reconcile work is a one-line change, not a schema change.
- **Never add a fourth totals implementation.** Money and minutes come from `services.work_orders.work_order_totals` (introduced in Task 1), which is the same helper `export_row` uses (§5).
- **`export_row` output must stay byte-identical to the operational export's rows.** No badge columns, no timestamp reformatting (§5, §10). The `SECTION` cell goes *before* the 26 columns, which the importer ignores.
- **`closing` is the only capped section**, via `app.services._list_cap.capped(..., what="hub_report_closing")` at `MAX_LIST_ROWS`. The cap lives in the payload builder, never in a renderer, so page and CSV truncate identically (§7). `count` and `by_status` are always the true totals.
- **No inline `style=` attributes in any frontend file** — CSP silently drops them. Use classes, or CSSOM on a node the module owns.
- **No nested `<button>` elements** — HTML hoists them out into siblings and silently breaks flex rows.
- **Files stay under 500 lines** per `CLAUDE.md`. `work_order_report.py` and `hubReport.js` are new and must respect this.
- **Test command** (this worktree has no venv of its own):
  `cd backend && "C:/Users/mcclu/Desktop/inventory_app_git/backend/venv/Scripts/python.exe" -m pytest -q <target>`
- **Commit messages carry no `Co-Authored-By` trailer** (`CLAUDE.md`).
- **No subagents for research** in this repo unless the task says otherwise (`CLAUDE.md`).

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/services/work_orders.py` | *Modify.* Gains `WorkOrderTotals` + `work_order_totals()`; `_export_row` becomes public `export_row`. No behaviour change. |
| `backend/app/services/work_order_report.py` | **New.** Payload dataclasses, `daily_report(db, *, now)`, `report_csv(payload)`. The whole feature's logic. |
| `backend/app/schemas/hub.py` | *Modify.* `HubReportRow`, `HubReportClosedSection`, `HubReportClosingSection`, `HubReportNewSection`, `HubReportWeek`, `HubReportSections`, `HubReportResponse`. |
| `backend/app/routers/hub.py` | *Modify.* `get_hub_report` and `export_hub_report`, thin like the rest of the file. |
| `backend/tests/test_work_order_report.py` | **New.** Service + CSV tests (§11). |
| `backend/tests/test_route_role_gates.py` | *Modify.* The Admin-floor exemption set, plus a `techfm_oa` 403 pin. |
| `backend/tests/test_hub_router.py` | *Modify.* HTTP happy path for both endpoints via `TestClient`. |
| `backend/static/api.js` | *Modify.* `apiGetHubReport()`. |
| `backend/static/pages/user-hub.html` | *Modify.* Fifth tab button + panel, `hidden` by default. |
| `backend/static/views/userHub.js` | *Modify.* `viewerIsAdmin()`, tab reveal, lazy fetch, cache reset, non-Admin fallback. |
| `backend/static/views/hubReport.js` | **New.** Renders the three visual sections. |
| `backend/static/views/workOrders.js` | *Modify.* New export `openWorkOrdersByNumberSearch(number)` + the `pendingArchivedCheck` one-shot. |
| `backend/static/styles.css` | *Modify.* Report section/table styles. |
| `docs/endpoint-map.md`, `docs/current-state.md`, `docs/open-work.md` | *Modify.* Routes, the report surface, and the §10 follow-ons. |

### One design call this plan makes that the spec leaves open

R9 says "the CSV is a pure function of the JSON payload", but `export_row` needs the `WorkOrder` ORM object, which a payload of plain dataclasses does not carry. **Resolution:** each `ReportRow` carries an `export_cells: list` field holding its 26 rendered cells, computed once in the payload builder. `report_csv` then reads *only* the payload, exactly as R9 requires, and the Pydantic `HubReportRow` simply does not declare `export_cells`, so it never reaches the JSON. This keeps the single-query, single-render guarantee without handing ORM objects to a renderer.

---

## Task 1: Shared totals helper and a public `export_row`

Pure refactor. The report's row projection (Task 2) and the CSV (Task 3) both need the export's money, and the spec forbids a second implementation. Done first so later tasks consume a stable name.

**Files:**
- Modify: `backend/app/services/work_orders.py:1331-1385` (`_export_row`), `:1449` (the `build_row` selector)
- Test: `backend/tests/test_work_order_report.py` (new file, first two tests)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `services.work_orders.WorkOrderTotals` — frozen dataclass with `materials_total: Decimal`, `labor_minutes: int`, `labor_total: Decimal`, `total: Decimal`
  - `services.work_orders.work_order_totals(work_order: WorkOrder) -> WorkOrderTotals`
  - `services.work_orders.export_row(work_order: WorkOrder) -> list` (was `_export_row`)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_work_order_report.py` with the header and the first two tests. Helper factories here are reused by every later task in this file, so write them properly now.

```python
"""Service, CSV, and window tests for the Admin daily report.

Spec: docs/superpowers/specs/2026-08-30-work-order-daily-report-design.md
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.domain import labor_day
from app.domain import work_orders as wo
from app.models import Item, User, WorkOrder, WorkOrderItem, WorkOrderLabor
from app.services import work_orders as work_orders_service


def _user(db, role="technician"):
    user = User(
        username=f"u-{uuid.uuid4().hex[:8]}",
        first_name="Test",
        last_name=role.title(),
        password_hash="x",
        role=role,
    )
    db.add(user)
    db.commit()
    return user


def _work_order(db, **kwargs):
    """A work order with a unique number. Every column the report reads is
    settable; the defaults are a plain live row created 'now'."""
    fields = {
        "number": f"WO-{uuid.uuid4().hex[:10]}",
        "status": wo.STATUS_CREATED,
        "created_at": datetime.now(timezone.utc),
        "community": "Cedar Ridge",
        "location": "Bldg 3",
        "service_type": "Plumbing",
    }
    fields.update(kwargs)
    record = WorkOrder(id=uuid.uuid4(), **fields)
    db.add(record)
    db.commit()
    return record


def _priced_item(db, price):
    item = Item(id=uuid.uuid4(), name=f"part-{uuid.uuid4().hex[:8]}", price=price)
    db.add(item)
    db.commit()
    return item


def test_work_order_totals_matches_the_export_rows_money(db):
    item = _priced_item(db, Decimal("10.00"))
    order = _work_order(db)
    db.add(WorkOrderItem(id=uuid.uuid4(), work_order_id=order.id, item_id=item.id, quantity=3))
    db.add(WorkOrderLabor(id=uuid.uuid4(), work_order_id=order.id, minutes=90))
    db.commit()
    db.refresh(order)

    totals = work_orders_service.work_order_totals(order)
    row = work_orders_service.export_row(order)

    headers = list(wo.EXPORT_HEADERS)
    assert row[headers.index("MATERIALS TOTAL")] == f"{totals.materials_total:.2f}"
    assert row[headers.index("LABOR MINUTES")] == totals.labor_minutes
    assert row[headers.index("LABOR TOTAL")] == f"{totals.labor_total:.2f}"
    assert row[headers.index("TOTAL")] == f"{totals.total:.2f}"


def test_totals_sum_materials_and_labor(db):
    item = _priced_item(db, Decimal("10.00"))
    order = _work_order(db)
    db.add(WorkOrderItem(id=uuid.uuid4(), work_order_id=order.id, item_id=item.id, quantity=2))
    db.add(WorkOrderLabor(id=uuid.uuid4(), work_order_id=order.id, minutes=60))
    db.commit()
    db.refresh(order)

    totals = work_orders_service.work_order_totals(order)

    assert totals.materials_total == Decimal("20.00")
    assert totals.labor_minutes == 60
    assert totals.labor_total == wo.labor_charge(60)
    assert totals.total == totals.materials_total + totals.labor_total
```

Before running, confirm the real column names on `WorkOrderItem` and `WorkOrderLabor`:

```bash
grep -n "class WorkOrderItem" -A 20 backend/app/models.py
grep -n "class WorkOrderLabor" -A 20 backend/app/models.py
```

Fix the factory kwargs to match what you find — do not guess.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && "C:/Users/mcclu/Desktop/inventory_app_git/backend/venv/Scripts/python.exe" -m pytest -q tests/test_work_order_report.py -v`
Expected: FAIL — `AttributeError: module 'app.services.work_orders' has no attribute 'work_order_totals'`

- [ ] **Step 3: Write minimal implementation**

In `backend/app/services/work_orders.py`, immediately above `_export_row`, add the helper and rewrite `_export_row` as the public `export_row` that consumes it:

```python
@dataclass(frozen=True)
class WorkOrderTotals:
    """A work order's money and minutes, computed once.

    The single source for every surface that shows a work order's totals:
    the CSV export, Admin Review, and the Admin daily report. Adding a
    fourth independent computation is what this exists to prevent."""

    materials_total: Decimal
    labor_minutes: int
    labor_total: Decimal
    total: Decimal


def work_order_totals(work_order: WorkOrder) -> WorkOrderTotals:
    materials_total = Decimal(0)
    for line in work_order.items:
        price = line.item.price or Decimal(0)
        materials_total += price * wo.effective_billable(
            line.quantity, line.billable_quantity
        )
    labor_minutes = sum(entry.minutes for entry in work_order.labor_entries)
    labor_total = wo.labor_charge(labor_minutes)
    return WorkOrderTotals(
        materials_total=materials_total,
        labor_minutes=labor_minutes,
        labor_total=labor_total,
        total=materials_total + labor_total,
    )


def export_row(work_order: WorkOrder) -> list:
    """One work order as a row of `domain.work_orders.EXPORT_HEADERS` values.

    Public because the Admin daily report (`services/work_order_report.py`)
    renders the same cells into its `SECTION`-prefixed CSV. Changing this
    row's shape changes the operational export for every consumer and
    breaks the report's import round-trip -- treat it as a contract."""
    totals = work_order_totals(work_order)

    return [
        work_order.number,
        work_order.location or "",
        work_order.output_to or "",
        # The raw vendor name, matching what the import reads back.
        work_order.vendor_assignee or "",
        work_order.service_type or "",
        work_order.schedule_date or "",
        work_order.description or "",
        work_order.status,
        # Multi-technician work orders collapse to one semicolon-joined cell;
        # a comma would fight the CSV itself in every spreadsheet.
        "; ".join(technician.full_name for technician in work_order.technicians),
        work_order.supervisor.full_name if work_order.supervisor else "",
        work_order.community or "",
        work_order.building_number or "",
        work_order.unit_number or "",
        work_order.entry_mode,
        len(work_order.items),
        f"{totals.materials_total:.2f}",
        totals.labor_minutes,
        wo.billed_labor_minutes(totals.labor_minutes),
        f"{totals.labor_total:.2f}",
        f"{totals.total:.2f}",
        work_order.notes or "",
        _csv_timestamp(work_order.created_at),
        _csv_timestamp(work_order.updated_at),
        _csv_timestamp(work_order.completed_at),
        _csv_timestamp(work_order.archived_at),
    ]
```

Then update the one call site at `work_orders.py:1449`:

```python
    build_row = _client_export_row if is_client else export_row
```

Confirm `dataclass` and `Decimal` are already imported at the top of the module; add `from dataclasses import dataclass` if not.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `cd backend && "C:/Users/mcclu/Desktop/inventory_app_git/backend/venv/Scripts/python.exe" -m pytest -q tests/test_work_order_report.py tests/test_work_orders_export.py -v`
Expected: PASS. If `tests/test_work_orders_export.py` does not exist, find the export tests with `grep -rln "EXPORT_HEADERS" backend/tests` and run those instead. **The existing export tests passing unchanged is the whole point of this task** — a pure refactor that alters one exported byte is a failed task.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/work_orders.py backend/tests/test_work_order_report.py
git commit -m "refactor(work-orders): one totals helper, public export_row"
```

---

## Task 2: The report payload

The whole feature's logic, provable with no HTTP and no UI (§12.1).

**Files:**
- Create: `backend/app/services/work_order_report.py`
- Test: `backend/tests/test_work_order_report.py` (append)

**Interfaces:**
- Consumes: `services.work_orders.export_row`, `services.work_orders.work_order_totals` (Task 1); `domain.labor_day.{central_date_of, day_bounds, week_bounds_containing}`; `domain.list_limits.fetch_limit`; `services._list_cap.capped`.
- Produces:
  - `ReportRow` (frozen dataclass, fields listed in the implementation below, including `export_cells: list`)
  - `ClosedSection(count: int, auto_closed_count: int, rows: list[ReportRow])`
  - `ClosingSection(count: int, by_status: dict[str, int], truncated: bool, rows: list[ReportRow])`
  - `NewSection(count: int, rows: list[ReportRow])`
  - `ReportWeek(start: date, end: date)`
  - `ReportSections(closed_today, closed_week, closing, new_today, new_week)`
  - `DailyReport(generated_at: datetime, day: date, week: ReportWeek, sections: ReportSections)`
  - `SECTION_ORDER: tuple[str, ...]` = `("closed_today", "closed_week", "closing", "new_today", "new_week")`
  - `CLOSING_STATUSES: tuple[str, ...]` in lifecycle order
  - `daily_report(db: Session, *, now: datetime) -> DailyReport`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_work_order_report.py`. Add `from app.services import work_order_report` to the imports.

```python
# --- window derivation (R1, §4) --------------------------------------------

def _central_noon(year, month, day):
    """A UTC instant that is unambiguously midday on that Central date."""
    return datetime(year, month, day, 17, 0, tzinfo=timezone.utc)


def test_monday_reads_today_and_week_the_same(db):
    # 2026-08-24 is a Monday.
    now = _central_noon(2026, 8, 24)
    day_start, _ = labor_day.day_bounds(labor_day.central_date_of(now))
    _work_order(db, archived_at=day_start + timedelta(hours=2), status=wo.STATUS_COMPLETED)

    payload = work_order_report.daily_report(db, now=now)

    assert payload.day.isoformat() == "2026-08-24"
    assert payload.week.start.isoformat() == "2026-08-24"
    assert payload.week.end.isoformat() == "2026-08-30"
    assert payload.sections.closed_today.count == payload.sections.closed_week.count


def test_tuesday_week_covers_monday_and_tuesday(db):
    # The spec's own worked example: 6 closed Monday, 6 more on Tuesday.
    now = _central_noon(2026, 8, 25)
    monday_start, _ = labor_day.day_bounds(labor_day.central_date_of(_central_noon(2026, 8, 24)))
    tuesday_start, _ = labor_day.day_bounds(labor_day.central_date_of(now))
    for _ in range(6):
        _work_order(db, archived_at=monday_start + timedelta(hours=3), status=wo.STATUS_COMPLETED)
    for _ in range(6):
        _work_order(db, archived_at=tuesday_start + timedelta(hours=3), status=wo.STATUS_COMPLETED)

    payload = work_order_report.daily_report(db, now=now)

    assert payload.sections.closed_today.count == 6
    assert payload.sections.closed_week.count == 12


def test_a_close_at_2330_central_lands_in_that_central_day(db):
    now = _central_noon(2026, 8, 25)
    day_start, day_end = labor_day.day_bounds(labor_day.central_date_of(now))
    late = day_end - timedelta(minutes=30)
    order = _work_order(db, archived_at=late, status=wo.STATUS_COMPLETED)

    payload = work_order_report.daily_report(db, now=now)

    assert [row.number for row in payload.sections.closed_today.rows] == [order.number]


@pytest.mark.parametrize("month,day", [(3, 10), (11, 3)])
def test_dst_weeks_produce_sane_bounds(db, month, day):
    # 2026-03-08 springs forward, 2026-11-01 falls back; both weeks must still
    # be Monday-through-Sunday with a start strictly before now.
    now = _central_noon(2026, month, day)
    payload = work_order_report.daily_report(db, now=now)

    assert payload.week.start.weekday() == 0
    assert (payload.week.end - payload.week.start).days == 6
    week_start_at, _ = labor_day.day_bounds(payload.week.start)
    assert week_start_at < now


# --- sections (§4) ----------------------------------------------------------

def test_a_row_closed_today_is_in_both_closed_sections(db):
    now = _central_noon(2026, 8, 25)
    day_start, _ = labor_day.day_bounds(labor_day.central_date_of(now))
    order = _work_order(db, archived_at=day_start + timedelta(hours=1), status=wo.STATUS_COMPLETED)

    payload = work_order_report.daily_report(db, now=now)

    assert order.number in [row.number for row in payload.sections.closed_today.rows]
    assert order.number in [row.number for row in payload.sections.closed_week.rows]


def test_created_and_closed_today_appears_in_both_new_and_closed(db):
    now = _central_noon(2026, 8, 25)
    day_start, _ = labor_day.day_bounds(labor_day.central_date_of(now))
    stamp = day_start + timedelta(hours=1)
    order = _work_order(db, created_at=stamp, archived_at=stamp, status=wo.STATUS_COMPLETED)

    payload = work_order_report.daily_report(db, now=now)

    assert order.number in [row.number for row in payload.sections.new_today.rows]
    assert order.number in [row.number for row in payload.sections.closed_today.rows]


def test_closing_holds_exactly_the_three_live_statuses(db):
    now = _central_noon(2026, 8, 25)
    day_start, _ = labor_day.day_bounds(labor_day.central_date_of(now))
    wanted = {
        status: _work_order(db, status=status).number
        for status in (wo.STATUS_READY_TO_COMPLETE, wo.STATUS_COMPLETED, wo.STATUS_REVIEW)
    }
    _work_order(db, status=wo.STATUS_IN_PROGRESS)          # too early
    _work_order(db, status=wo.STATUS_ON_HOLD)              # too early
    _work_order(db, status=wo.STATUS_REVIEW,               # archived: belongs to closed_*
                archived_at=day_start + timedelta(hours=1))

    payload = work_order_report.daily_report(db, now=now)

    assert sorted(row.number for row in payload.sections.closing.rows) == sorted(wanted.values())
    assert payload.sections.closing.by_status == {
        wo.STATUS_READY_TO_COMPLETE: 1,
        wo.STATUS_COMPLETED: 1,
        wo.STATUS_REVIEW: 1,
    }


def test_closing_is_sorted_by_lifecycle_then_oldest_first(db):
    now = _central_noon(2026, 8, 25)
    base = now - timedelta(days=3)
    newer_ready = _work_order(db, status=wo.STATUS_READY_TO_COMPLETE, created_at=base + timedelta(hours=2))
    older_ready = _work_order(db, status=wo.STATUS_READY_TO_COMPLETE, created_at=base)
    review = _work_order(db, status=wo.STATUS_REVIEW, created_at=base)
    completed = _work_order(db, status=wo.STATUS_COMPLETED, created_at=base)

    payload = work_order_report.daily_report(db, now=now)

    assert [row.number for row in payload.sections.closing.rows] == [
        older_ready.number, newer_ready.number, completed.number, review.number,
    ]


def test_closed_sections_are_newest_close_first(db):
    now = _central_noon(2026, 8, 26)
    day_start, _ = labor_day.day_bounds(labor_day.central_date_of(now))
    older = _work_order(db, status=wo.STATUS_COMPLETED, archived_at=day_start + timedelta(hours=1))
    newer = _work_order(db, status=wo.STATUS_COMPLETED, archived_at=day_start + timedelta(hours=5))

    payload = work_order_report.daily_report(db, now=now)

    assert [row.number for row in payload.sections.closed_today.rows] == [newer.number, older.number]


def test_closing_truncation_caps_rows_but_not_counts(db, monkeypatch):
    # Lower the ceiling instead of building 5,001 rows -- `_list_cap` reads the
    # module at call time precisely so a test can do this.
    from app.domain import list_limits

    monkeypatch.setattr(list_limits, "MAX_LIST_ROWS", 2)
    now = _central_noon(2026, 8, 25)
    for _ in range(4):
        _work_order(db, status=wo.STATUS_REVIEW)

    payload = work_order_report.daily_report(db, now=now)

    assert payload.sections.closing.truncated is True
    assert len(payload.sections.closing.rows) == 2
    assert payload.sections.closing.count == 4
    assert payload.sections.closing.by_status[wo.STATUS_REVIEW] == 4


# --- R10 provenance ---------------------------------------------------------

def test_a_legacy_archived_row_is_flagged_and_a_hand_closed_one_is_not(db):
    now = _central_noon(2026, 8, 25)
    day_start, _ = labor_day.day_bounds(labor_day.central_date_of(now))
    _work_order(db, status=wo.STATUS_COMPLETED, legacy=True,
                archived_at=day_start + timedelta(hours=1))
    _work_order(db, status=wo.STATUS_COMPLETED, legacy=False,
                archived_at=day_start + timedelta(hours=2))

    payload = work_order_report.daily_report(db, now=now)
    flags = sorted((row.legacy, row.auto_closed) for row in payload.sections.closed_today.rows)

    # `auto_closed` is a constant False until the reconcile migration lands.
    assert flags == [(False, False), (True, False)]
    assert payload.sections.closed_today.auto_closed_count == 0


def test_report_row_money_matches_export_row(db):
    now = _central_noon(2026, 8, 25)
    day_start, _ = labor_day.day_bounds(labor_day.central_date_of(now))
    item = _priced_item(db, Decimal("7.50"))
    order = _work_order(db, status=wo.STATUS_COMPLETED,
                        archived_at=day_start + timedelta(hours=1))
    db.add(WorkOrderItem(id=uuid.uuid4(), work_order_id=order.id, item_id=item.id, quantity=4))
    db.add(WorkOrderLabor(id=uuid.uuid4(), work_order_id=order.id, minutes=45))
    db.commit()
    db.refresh(order)

    payload = work_order_report.daily_report(db, now=now)
    row = next(r for r in payload.sections.closed_today.rows if r.number == order.number)
    totals = work_orders_service.work_order_totals(order)

    assert (row.materials_total, row.labor_minutes, row.labor_total, row.total) == (
        totals.materials_total, totals.labor_minutes, totals.labor_total, totals.total,
    )
```

> **Note on test isolation:** the `db` fixture rolls back, but it runs against a *developer* Postgres that may already hold real work orders. Every count assertion above is therefore scoped to rows this test created, except where the section is filtered to a window no pre-existing row can fall into. If a count assertion fails on a populated database, scope it — do not relax it. (This is the same trap that broke `test_cascade_deletes_with_user`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && "C:/Users/mcclu/Desktop/inventory_app_git/backend/venv/Scripts/python.exe" -m pytest -q tests/test_work_order_report.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.work_order_report'`

- [ ] **Step 3: Write the implementation**

Create `backend/app/services/work_order_report.py`:

```python
"""The Admin daily report: what closed, what is closing, what arrived.

Layer: services. Owns the whole feature -- window derivation, the five
section queries, the row projection, and the CSV render -- so neither
`services/hub.py` nor `services/work_orders.py` (both long past the
500-line rule) grows a surface that belongs to neither.

Spec: docs/superpowers/specs/2026-08-30-work-order-daily-report-design.md

Two things about this module are load-bearing:

**One payload, two renderers.** `daily_report` composes everything; the
JSON route validates it and `report_csv` renders it. Neither renderer
queries. That is what makes the screen and the file incapable of
disagreeing (R9), including when the `closing` cap bites (§7).

**There is no status-history table.** So `closing` is a snapshot of
current state, not a delta, and a restore erases a close retroactively --
this is a live view, not an archival record (§3). Do not "fix" either by
inferring history from `updated_at`.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload, selectinload

from app.domain import labor_day
from app.domain import work_orders as wo
from app.domain.list_limits import fetch_limit
from app.models import WorkOrder, WorkOrderItem
from app.services._list_cap import capped
from app.services.work_orders import export_row, work_order_totals

# Lifecycle order, not alphabetical: this is the order the `closing` section
# sorts by and the order an Admin reads the pipeline in.
CLOSING_STATUSES: tuple[str, ...] = (
    wo.STATUS_READY_TO_COMPLETE,
    wo.STATUS_COMPLETED,
    wo.STATUS_REVIEW,
)

# The CSV's fixed section order (§5). Also the order the page renders.
SECTION_ORDER: tuple[str, ...] = (
    "closed_today",
    "closed_week",
    "closing",
    "new_today",
    "new_week",
)

CSV_SECTION_HEADER = "SECTION"


@dataclass(frozen=True)
class ReportRow:
    """One work order as the report shows it.

    `export_cells` is the row's 26 `EXPORT_HEADERS` values, rendered here so
    `report_csv` is a pure function of this payload (R9) without handing an
    ORM object to a renderer. It is deliberately absent from
    `schemas.hub.HubReportRow`, so it never reaches the JSON response."""

    work_order_id: UUID
    number: str
    # The row's `status` column as it stands. Archiving does not rewrite it,
    # so a closed row still reads `completed` or `review` -- the badge must
    # not be misread as "still open".
    status: str
    community: Optional[str]
    location: Optional[str]
    building_number: Optional[str]
    unit_number: Optional[str]
    service_type: Optional[str]
    priority: Optional[str]
    supervisor_name: Optional[str]
    technician_names: list[str]
    materials_total: Decimal
    labor_minutes: int
    labor_total: Decimal
    total: Decimal
    created_at: Optional[datetime]
    completed_at: Optional[datetime]
    archived_at: Optional[datetime]
    auto_closed: bool
    legacy: bool
    export_cells: list = field(default_factory=list)


@dataclass(frozen=True)
class ClosedSection:
    count: int
    auto_closed_count: int
    rows: list[ReportRow] = field(default_factory=list)


@dataclass(frozen=True)
class ClosingSection:
    count: int
    by_status: dict[str, int]
    truncated: bool
    rows: list[ReportRow] = field(default_factory=list)


@dataclass(frozen=True)
class NewSection:
    count: int
    rows: list[ReportRow] = field(default_factory=list)


@dataclass(frozen=True)
class ReportWeek:
    start: date
    end: date


@dataclass(frozen=True)
class ReportSections:
    closed_today: ClosedSection
    closed_week: ClosedSection
    closing: ClosingSection
    new_today: NewSection
    new_week: NewSection


@dataclass(frozen=True)
class DailyReport:
    generated_at: datetime
    day: date
    week: ReportWeek
    sections: ReportSections


def _auto_closed(work_order: WorkOrder) -> bool:
    """Whether the NetFacilities reconcile sweep closed this row (R10).

    `auto_closed_batch_id` arrives with the reconcile migration
    (2026-08-30-netfacilities-reconcile-design.md). Until it does this is a
    constant `False`; the contract is identical either way, so shipping the
    report first costs the reconcile work one line here and nothing else."""
    return getattr(work_order, "auto_closed_batch_id", None) is not None


def _base_query(db: Session):
    """Eager-load everything a row and its export cells read, so a section of
    N rows is a constant number of queries rather than 5N."""
    return db.query(WorkOrder).options(
        joinedload(WorkOrder.supervisor),
        selectinload(WorkOrder.technicians),
        selectinload(WorkOrder.items).joinedload(WorkOrderItem.item),
        selectinload(WorkOrder.labor_entries),
    )


def _row(work_order: WorkOrder) -> ReportRow:
    totals = work_order_totals(work_order)
    return ReportRow(
        work_order_id=work_order.id,
        number=work_order.number,
        status=work_order.status,
        community=work_order.community,
        location=work_order.location,
        building_number=work_order.building_number,
        unit_number=work_order.unit_number,
        service_type=work_order.service_type,
        priority=work_order.priority,
        supervisor_name=(
            work_order.supervisor.full_name if work_order.supervisor else None
        ),
        technician_names=[t.full_name for t in work_order.technicians],
        materials_total=totals.materials_total,
        labor_minutes=totals.labor_minutes,
        labor_total=totals.labor_total,
        total=totals.total,
        created_at=work_order.created_at,
        completed_at=work_order.completed_at,
        archived_at=work_order.archived_at,
        auto_closed=_auto_closed(work_order),
        legacy=bool(work_order.legacy),
        export_cells=export_row(work_order),
    )


def _closed_section(db: Session, *, start: datetime, end: datetime) -> ClosedSection:
    """Rows archived within [start, end), newest close first.

    Uncapped on purpose (§7): the window is the bound, and a report that
    silently omits closures while looking complete is a record-keeping
    problem, not a performance one -- the same reasoning that exempts the
    work-order export."""
    records = (
        _base_query(db)
        .filter(WorkOrder.archived_at >= start, WorkOrder.archived_at < end)
        .order_by(WorkOrder.archived_at.desc())
        .all()
    )
    rows = [_row(record) for record in records]
    return ClosedSection(
        count=len(rows),
        auto_closed_count=sum(1 for row in rows if row.auto_closed),
        rows=rows,
    )


def _new_section(db: Session, *, start: datetime, end: datetime) -> NewSection:
    records = (
        _base_query(db)
        .filter(WorkOrder.created_at >= start, WorkOrder.created_at < end)
        .order_by(WorkOrder.created_at.desc())
        .all()
    )
    rows = [_row(record) for record in records]
    return NewSection(count=len(rows), rows=rows)


def _closing_section(db: Session) -> ClosingSection:
    """Every live work order in a closing status, right now (R3).

    The only unbounded section, so the only capped one. `count` and
    `by_status` are separate aggregate queries rather than tallies over
    `rows`, so both stay true when the cap bites (§7)."""
    live = (WorkOrder.archived_at.is_(None), WorkOrder.status.in_(CLOSING_STATUSES))

    by_status = {
        status: count
        for status, count in db.query(WorkOrder.status, func.count())
        .filter(*live)
        .group_by(WorkOrder.status)
        .all()
    }
    count = sum(by_status.values())

    # SQL has no "order by this tuple's position", so sort in Python over a
    # bounded fetch: `fetch_limit()` is one more than the ceiling, which is
    # what makes truncation detectable without a second COUNT.
    records = _base_query(db).filter(*live).limit(fetch_limit()).all()
    records.sort(key=lambda r: (CLOSING_STATUSES.index(r.status), r.created_at))
    kept = capped(records, what="hub_report_closing")

    return ClosingSection(
        count=count,
        by_status=by_status,
        truncated=len(kept) < count,
        rows=[_row(record) for record in kept],
    )


def daily_report(db: Session, *, now: datetime) -> DailyReport:
    """The whole report for the Central day containing `now`.

    Parameterless by design (R1): the windows come from the clock, which is
    what makes this a daily report rather than a filter. `now` is injected
    so tests can freeze it."""
    today = labor_day.central_date_of(now)
    day_start, day_end = labor_day.day_bounds(today)
    week_start, week_end = labor_day.week_bounds_containing(today)
    week_start_at, _ = labor_day.day_bounds(week_start)

    # Today's upper bound is `day_end`, the week's is `now`: the week is
    # explicitly week-to-date, while the day stays a clean half-open Central
    # day. Nothing is stamped in the future, so the difference is immaterial.
    return DailyReport(
        generated_at=now,
        day=today,
        week=ReportWeek(start=week_start, end=week_end),
        sections=ReportSections(
            closed_today=_closed_section(db, start=day_start, end=day_end),
            closed_week=_closed_section(db, start=week_start_at, end=now),
            closing=_closing_section(db),
            new_today=_new_section(db, start=day_start, end=day_end),
            new_week=_new_section(db, start=week_start_at, end=now),
        ),
    )
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `cd backend && "C:/Users/mcclu/Desktop/inventory_app_git/backend/venv/Scripts/python.exe" -m pytest -q tests/test_work_order_report.py -v`
Expected: PASS, all tests.

If `test_closing_truncation_caps_rows_but_not_counts` fails because `count` includes pre-existing rows on your developer database, scope the assertion to the statuses this test used rather than lowering the bar.

- [ ] **Step 5: Check the file length**

Run: `wc -l backend/app/services/work_order_report.py`
Expected: under 500. If it is over, that is a signal to split the CSV renderer (Task 3) into its own module — say so rather than silently exceeding the limit.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/work_order_report.py backend/tests/test_work_order_report.py
git commit -m "feat(report): compose the Admin daily report payload"
```

---

## Task 3: The `SECTION`-prefixed CSV

**Files:**
- Modify: `backend/app/services/work_order_report.py` (append `report_csv` and `report_filename`)
- Test: `backend/tests/test_work_order_report.py` (append)

**Interfaces:**
- Consumes: `DailyReport`, `SECTION_ORDER`, `CSV_SECTION_HEADER`, `ReportRow.export_cells` (Task 2).
- Produces:
  - `report_csv(payload: DailyReport) -> str`
  - `report_filename(payload: DailyReport) -> str` → `"wo-report_YYYY-MM-DD.csv"`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_work_order_report.py`:

```python
# --- CSV (§5) ---------------------------------------------------------------

def _parse_csv(text):
    import csv as _csv
    return list(_csv.reader(io.StringIO(text)))


def test_csv_header_is_section_plus_the_export_headers(db):
    now = _central_noon(2026, 8, 25)
    payload = work_order_report.daily_report(db, now=now)

    rows = _parse_csv(work_order_report.report_csv(payload))

    assert tuple(rows[0]) == ("SECTION",) + wo.EXPORT_HEADERS


def test_csv_writes_sections_in_the_fixed_order(db):
    now = _central_noon(2026, 8, 25)
    day_start, _ = labor_day.day_bounds(labor_day.central_date_of(now))
    _work_order(db, status=wo.STATUS_COMPLETED, created_at=day_start + timedelta(hours=1),
                archived_at=day_start + timedelta(hours=2))
    _work_order(db, status=wo.STATUS_REVIEW, created_at=day_start + timedelta(hours=1))

    payload = work_order_report.daily_report(db, now=now)
    rows = _parse_csv(work_order_report.report_csv(payload))
    seen = []
    for row in rows[1:]:
        if not seen or seen[-1] != row[0]:
            seen.append(row[0])

    assert seen == [key for key in work_order_report.SECTION_ORDER if key in seen]


def test_a_csv_rows_26_cells_are_export_rows_output(db):
    now = _central_noon(2026, 8, 25)
    day_start, _ = labor_day.day_bounds(labor_day.central_date_of(now))
    order = _work_order(db, status=wo.STATUS_COMPLETED,
                        archived_at=day_start + timedelta(hours=1))
    db.refresh(order)

    payload = work_order_report.daily_report(db, now=now)
    rows = _parse_csv(work_order_report.report_csv(payload))
    written = next(r for r in rows[1:] if r[0] == "closed_today" and r[1] == order.number)
    expected = [str(cell) for cell in work_orders_service.export_row(order)]

    assert written[1:] == expected


def test_the_report_csv_still_reimports(db):
    # The round-trip guarantee: `parse_import_row` reads its seven headers by
    # name, so a column *before* them must not break re-import.
    now = _central_noon(2026, 8, 25)
    day_start, _ = labor_day.day_bounds(labor_day.central_date_of(now))
    order = _work_order(db, status=wo.STATUS_COMPLETED,
                        archived_at=day_start + timedelta(hours=1))

    payload = work_order_report.daily_report(db, now=now)
    reader = csv.DictReader(io.StringIO(work_order_report.report_csv(payload)))
    parsed = [wo.parse_import_row(row) for row in reader]

    assert order.number in [entry["number"] for entry in parsed]


def test_csv_uses_crlf_and_quotes_embedded_commas_and_newlines(db):
    now = _central_noon(2026, 8, 25)
    day_start, _ = labor_day.day_bounds(labor_day.central_date_of(now))
    _work_order(db, status=wo.STATUS_COMPLETED,
                archived_at=day_start + timedelta(hours=1),
                notes="one, two\nthree")

    payload = work_order_report.daily_report(db, now=now)
    text = work_order_report.report_csv(payload)

    assert text.endswith("\r\n")
    assert '"one, two\nthree"' in text
    assert len(_parse_csv(text)[0]) == len(wo.EXPORT_HEADERS) + 1


def test_filename_names_the_central_report_day(db):
    now = _central_noon(2026, 8, 25)
    payload = work_order_report.daily_report(db, now=now)

    assert work_order_report.report_filename(payload) == "wo-report_2026-08-25.csv"
```

Before running, confirm `parse_import_row`'s real name and return shape:

```bash
grep -n "def parse_import_row" -A 25 backend/app/domain/work_orders.py
```

Adjust the round-trip assertion to that function's actual output (it may return a dataclass rather than a dict) — do not guess.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && "C:/Users/mcclu/Desktop/inventory_app_git/backend/venv/Scripts/python.exe" -m pytest -q tests/test_work_order_report.py -k "csv or filename or reimport" -v`
Expected: FAIL — `AttributeError: module 'app.services.work_order_report' has no attribute 'report_csv'`

- [ ] **Step 3: Write the implementation**

Append to `backend/app/services/work_order_report.py`:

```python
def _section_rows(payload: DailyReport, key: str) -> list[ReportRow]:
    return getattr(payload.sections, key).rows


def report_csv(payload: DailyReport) -> str:
    """The whole report as one `SECTION`-prefixed CSV.

    A pure render of `payload` -- no queries, no clock -- so the file can
    never disagree with the screen, cap included (R9, §7).

    **The 26 cells after `SECTION` are `export_row`'s, verbatim.** That is
    what keeps the file re-importable: `parse_import_row` reads its seven
    headers by name and ignores every other column, a column *before* them
    included. Do not add the R10 badge columns here -- `export_row` is
    shared with the operational export and its consumers (§10).

    **A row can appear twice**, under `closed_today` and `closed_week` (or
    the two `new_*` keys). That is the nesting (R1) made filterable: a
    spreadsheet narrows on `SECTION`, where the page uses a badge.

    **Timestamp seam, deliberate:** `export_row` writes UTC while the
    sections are Central calendar periods, so a row closed at 8 PM Central
    on the 30th sits in `closed_today` with an `ARCHIVED AT` cell reading
    the 31st. The covered day is in the filename, not the cells. Do not
    "fix" this by reformatting the shared export."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow((CSV_SECTION_HEADER,) + wo.EXPORT_HEADERS)
    for key in SECTION_ORDER:
        for row in _section_rows(payload, key):
            writer.writerow([key, *row.export_cells])
    return buffer.getvalue()


def report_filename(payload: DailyReport) -> str:
    """Named for the period it covers, not the moment of export -- the
    timesheet convention (user-hub-design.md D14). This report *is* the
    day, so the day is the name."""
    return f"wo-report_{payload.day.isoformat()}.csv"
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `cd backend && "C:/Users/mcclu/Desktop/inventory_app_git/backend/venv/Scripts/python.exe" -m pytest -q tests/test_work_order_report.py -v`
Expected: PASS, all tests.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/work_order_report.py backend/tests/test_work_order_report.py
git commit -m "feat(report): render the report as one SECTION-prefixed CSV"
```

---

## Task 4: Schemas and the two Admin routes

Completes the shippable, UI-free slice (§12.3).

**Files:**
- Modify: `backend/app/schemas/hub.py` (append), `backend/app/routers/hub.py` (module docstring, imports, two handlers)
- Test: `backend/tests/test_route_role_gates.py:511-517`, `backend/tests/test_hub_router.py` (append)

**Interfaces:**
- Consumes: `services.work_order_report.{daily_report, report_csv, report_filename}` (Tasks 2–3).
- Produces: `schemas.hub.HubReportResponse`; route endpoint names `get_hub_report` and `export_hub_report` (the role-gate test matches on these exact names).

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_route_role_gates.py`, replace `assert offenders == set()` at line 517 with:

```python
    # The Admin daily report is the one genuinely Admin-only surface in the
    # app: a company-wide digest of what closed and what is closing, which
    # deliberately sits above TechFM OA despite OA holding the rest of the
    # admin toolkit. See
    # docs/superpowers/specs/2026-08-30-work-order-daily-report-design.md §6.
    # Lowering it to techfm_oa is a one-line change here plus the gate; nothing
    # else in the design depends on the floor.
    assert offenders == {"get_hub_report", "export_hub_report"}


def test_techfm_oa_cannot_reach_the_admin_daily_report():
    # The explicit pin for §6's accepted consequence: OA sees the admin tiles,
    # Graphs, and the work-order export, but not this report.
    assert _min_role_for(hub_router, "get_hub_report") == roles.ROLE_ADMIN
    assert _min_role_for(hub_router, "export_hub_report") == roles.ROLE_ADMIN
```

Append to `backend/tests/test_hub_router.py` — match the file's existing client/login fixtures rather than inventing new ones (read the top of the file first):

```python
def test_admin_daily_report_returns_the_five_sections(client, admin_token):
    response = client.get("/hub/report", headers={"Authorization": f"Bearer {admin_token}"})

    assert response.status_code == 200
    body = response.json()
    assert set(body["sections"]) == {
        "closed_today", "closed_week", "closing", "new_today", "new_week",
    }
    assert set(body["week"]) == {"start", "end"}
    assert "auto_closed_count" in body["sections"]["closed_today"]
    assert set(body["sections"]["closing"]) >= {"count", "by_status", "truncated", "rows"}
    assert "auto_closed_count" not in body["sections"]["new_today"]
    assert body["day"]


def test_admin_daily_report_row_never_leaks_export_cells(client, admin_token):
    body = client.get("/hub/report", headers={"Authorization": f"Bearer {admin_token}"}).json()
    for section in body["sections"].values():
        for row in section["rows"]:
            assert "export_cells" not in row


def test_techfm_oa_is_forbidden_from_the_report(client, techfm_oa_token):
    for path in ("/hub/report", "/hub/report/export"):
        response = client.get(path, headers={"Authorization": f"Bearer {techfm_oa_token}"})
        assert response.status_code == 403


def test_report_export_is_an_attachment_csv(client, admin_token):
    response = client.get("/hub/report/export", headers={"Authorization": f"Bearer {admin_token}"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    assert "wo-report_" in response.headers["content-disposition"]
    assert response.text.startswith("SECTION,WORK ORDER,")
```

These go through `TestClient`, not direct handler calls — the suite's standing convention, and the only way the gate is actually exercised.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && "C:/Users/mcclu/Desktop/inventory_app_git/backend/venv/Scripts/python.exe" -m pytest -q tests/test_route_role_gates.py tests/test_hub_router.py -v`
Expected: FAIL — the offenders set is empty (no such routes yet), and the `/hub/report` requests 404.

- [ ] **Step 3: Add the schemas**

Append to `backend/app/schemas/hub.py`:

```python
class HubReportRow(BaseModel):
    """The report's own display projection -- not the 26-column CSV row.

    `status` is the row's `status` column as it stands: archiving does not
    rewrite it, so a closed row still reads `completed` or `review`. The
    payload's `export_cells` is deliberately absent here, so the CSV's cells
    never travel in the JSON."""

    work_order_id: uuid.UUID
    number: str
    status: str
    community: Optional[str] = None
    location: Optional[str] = None
    building_number: Optional[str] = None
    unit_number: Optional[str] = None
    service_type: Optional[str] = None
    priority: Optional[str] = None
    supervisor_name: Optional[str] = None
    technician_names: list[str] = []
    materials_total: Decimal
    labor_minutes: int
    labor_total: Decimal
    total: Decimal
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    archived_at: Optional[datetime] = None
    auto_closed: bool
    legacy: bool

    model_config = {"from_attributes": True}


class HubReportClosedSection(BaseModel):
    count: int
    auto_closed_count: int
    rows: list[HubReportRow] = []

    model_config = {"from_attributes": True}


class HubReportClosingSection(BaseModel):
    # `by_status` and `count` are separate aggregates, not tallies over
    # `rows`, so the sub-counts stay true when `rows` is capped (§7).
    count: int
    by_status: dict[str, int] = {}
    truncated: bool
    rows: list[HubReportRow] = []

    model_config = {"from_attributes": True}


class HubReportNewSection(BaseModel):
    count: int
    rows: list[HubReportRow] = []

    model_config = {"from_attributes": True}


class HubReportWeek(BaseModel):
    # The calendar week's Monday and Sunday, for labelling. The *data* stops
    # at `generated_at` -- the week is evaluated week-to-date (R1).
    start: date
    end: date

    model_config = {"from_attributes": True}


class HubReportSections(BaseModel):
    closed_today: HubReportClosedSection
    closed_week: HubReportClosedSection
    closing: HubReportClosingSection
    new_today: HubReportNewSection
    new_week: HubReportNewSection

    model_config = {"from_attributes": True}


class HubReportResponse(BaseModel):
    generated_at: datetime
    day: date
    week: HubReportWeek
    sections: HubReportSections

    model_config = {"from_attributes": True}
```

Confirm `Decimal`, `date`, `datetime`, `uuid`, and `Optional` are already imported at the top of the file; add whatever is missing.

- [ ] **Step 4: Add the routes**

In `backend/app/routers/hub.py`, extend the module docstring's route table with:

```
- `GET /hub/report`      admin only         -- the Admin daily report (R5)
```

Add to the schema import line: `HubReportResponse`. Add `from app.services import work_order_report`. Then append the two handlers:

```python
@router.get("/report", response_model=HubReportResponse)
def get_hub_report(
    user: User = Depends(require_min_role(roles.ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """The company-wide daily digest: closed, closing, and new (R5).

    **Admin, not TechFM OA.** The one route in the app floored at Admin --
    `tests/test_route_role_gates.py` carries the matching exemption, so
    changing this floor means changing that test deliberately.

    No query parameters: the windows come from server time, which is what
    makes it a daily report rather than a filter."""
    payload = work_order_report.daily_report(db, now=datetime.now(timezone.utc))
    return HubReportResponse.model_validate(payload)


@router.get("/report/export")
def export_hub_report(
    user: User = Depends(require_min_role(roles.ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """The same payload as one `SECTION`-prefixed CSV (R7, R9).

    Composed from `daily_report` rather than from its own query, so the file
    and the screen -- truncation included -- cannot disagree."""
    payload = work_order_report.daily_report(db, now=datetime.now(timezone.utc))
    filename = work_order_report.report_filename(payload)
    return Response(
        content=work_order_report.report_csv(payload),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
```

- [ ] **Step 5: Run the whole backend suite**

Run: `cd backend && "C:/Users/mcclu/Desktop/inventory_app_git/backend/venv/Scripts/python.exe" -m pytest -q`
Expected: PASS, 0 failures. The role-gate test is the one most likely to surprise you — read its failure message carefully rather than editing the assertion to match reality.

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/hub.py backend/app/routers/hub.py backend/tests/test_route_role_gates.py backend/tests/test_hub_router.py
git commit -m "feat(report): expose GET /hub/report and its CSV export at the Admin floor"
```

---

## Task 5: `openWorkOrdersByNumberSearch` (R11)

The Work Orders page hides archived rows, so a closed report row cannot open a card — it routes to the exact-number search, which triggers the shipped restore prompt. Built before the report UI so Task 7 has a real handler to call.

**Files:**
- Modify: `backend/static/views/workOrders.js` — near `pendingSoloNumber` (`:152-157`), inside `loadWorkOrders` (`:952-1030`), and beside `focusWorkOrderNumber` (`:1330`)

**Interfaces:**
- Consumes: the existing `loadWorkOrders({ checkArchivedSearch })` parameter and `offerRestoreForExactArchivedSearch`.
- Produces: `export function openWorkOrdersByNumberSearch(number)` — sets the search filter and arms a one-shot so the *next* `loadWorkOrders` runs the archived-number check.

- [ ] **Step 1: Read the existing one-shot idiom**

```bash
sed -n '145,215p' backend/static/views/workOrders.js
sed -n '950,1035p' backend/static/views/workOrders.js
sed -n '1325,1360p' backend/static/views/workOrders.js
```

`pendingSoloNumber` is *not* the mechanism to reuse: `loadWorkOrders` returns early on a solo lookup, before the archived-number prompt (see the comment at `:1017`). The new flag must be independent.

- [ ] **Step 2: Add the one-shot flag**

Beside `let pendingSoloNumber = null;` at `:154`:

```javascript
// A second one-shot, independent of `pendingSoloNumber`: the solo lookup
// returns before the archived-number prompt, so a caller that wants the
// "Work Order has been closed. Restore?" path needs its own flag. Consumed
// by the next `loadWorkOrders`, which is the one `showPage` triggers.
let pendingArchivedCheck = false;
```

- [ ] **Step 3: Consume it in `loadWorkOrders`**

At the top of `loadWorkOrders`, immediately after the signature's destructuring and *before* the `pendingSoloNumber` block at `:966`:

```javascript
  if (pendingArchivedCheck) {
    pendingArchivedCheck = false;
    checkArchivedSearch = true;
  }
```

`checkArchivedSearch` is already a destructured parameter (`:954`), so this simply promotes the one-shot into it. Verify that reassignment is legal where you put it — if the parameter is `const`-bound by the surrounding style, introduce a local `let shouldCheckArchived = checkArchivedSearch || pendingArchivedCheck;` and use that at `:1024` instead.

- [ ] **Step 4: Add the export**

Beside `focusWorkOrderNumber` at `:1330`:

```javascript
// R11: a closed work order has no card page -- the list hides archived rows.
// Routing to its exact number instead lands the Admin on the shipped "Work
// Order has been closed. Restore?" prompt, which is the useful destination.
// Reset the other controls so a stale status/community filter cannot hide
// the very row we just navigated to.
export function openWorkOrdersByNumberSearch(number) {
  resetWorkOrderFilters();
  setWorkOrderSearchValue(number);
  pendingArchivedCheck = true;
}
```

`resetWorkOrderFilters` and `setWorkOrderSearchValue` are placeholders for whatever this file already calls. Find the real ones before writing:

```bash
grep -n "function resetFilters\|clearFilters\|filters.q =\|searchInput" backend/static/views/workOrders.js | head -20
```

Use the existing helpers. If the file mutates a `filters` object and a DOM input directly, do exactly that — do not add an abstraction layer for one caller.

- [ ] **Step 5: Verify nothing else broke**

Run: `cd backend && "C:/Users/mcclu/Desktop/inventory_app_git/backend/venv/Scripts/python.exe" -m pytest -q`
Expected: PASS. (The JS has no test harness; this run only proves you did not break a template the backend serves.)

Then check the module still parses:

```bash
node --check backend/static/views/workOrders.js
```

- [ ] **Step 6: Commit**

```bash
git add backend/static/views/workOrders.js
git commit -m "feat(work-orders): route a closed number to the exact-search restore prompt"
```

---

## Task 6: The Report tab shell

Plumbing only — the tab exists, is Admin-gated, and fetches. The body comes in Task 7.

**Files:**
- Modify: `backend/static/api.js` (beside `apiGetHubTimesheets`, `:506`), `backend/static/pages/user-hub.html:15,21`, `backend/static/views/userHub.js`

**Interfaces:**
- Consumes: `GET /hub/report` (Task 4).
- Produces: `apiGetHubReport()`; DOM ids `hub-tab-report` / `hub-tabpanel-report`; `userHub.js` internal `viewerIsAdmin()` and a `latestReport` cache.

- [ ] **Step 1: Add the API function**

In `backend/static/api.js`, after `apiGetHubGraphs` (`:502`):

```javascript
export async function apiGetHubReport() {
  // No parameters: the windows are server-derived (R1).
  return liveGet("/hub/report");
}
```

The CSV needs no wrapper — it is a plain link, as the timesheet export is.

- [ ] **Step 2: Add the tab button and panel**

In `backend/static/pages/user-hub.html`, after the Graphs button on line 15:

```html
            <button type="button" class="hub-tab hidden" id="hub-tab-report" data-hub-tab="report" aria-controls="hub-tabpanel-report" aria-selected="false" role="tab" hidden>Report</button>
```

And after the Graphs panel on line 21:

```html
        <div class="hub-tabpanel" id="hub-tabpanel-report" role="tabpanel" aria-labelledby="hub-tab-report" hidden></div>
```

Both carry `hidden` **and** `class="hidden"`, matching Timesheets and Graphs — the class is what the stylesheet acts on, the attribute is what assistive tech reads.

- [ ] **Step 3: Wire the tab in `userHub.js`**

Read the Graphs wiring first — it is the exact pattern to copy:

```bash
grep -n "graphs" backend/static/views/userHub.js
```

Then make five changes, mirroring Graphs at each point:

1. Beside `graphsTabButton` (`:50`): `const reportTabButton = document.getElementById("hub-tab-report");`
2. A viewer predicate beside `viewerCanSeeAdminTiles` (`:127`):

```javascript
// Admin, not TechFM OA -- the one place this app draws the line above OA
// (spec §6). Matches the route's own floor.
function viewerIsAdmin() {
  return Boolean(latestPayload) && roleAtLeast(latestPayload.user.role, "admin");
}
```

3. A reveal beside the Graphs one (`:218-219`):

```javascript
  reportTabButton.hidden = !visible;
  reportTabButton.classList.toggle("hidden", !visible);
```

Call it with `viewerIsAdmin()`, not the OA predicate.

4. Lazy fetch in the `showTab`/render branch beside `activeTab === "graphs"` (`:179`, `:282`):

```javascript
  } else if (activeTab === "report") {
    void loadReport();
  }
```

with, beside `loadGraphs`:

```javascript
let latestReport = null;

async function loadReport({ background = false } = {}) {
  const panel = tabPanels.report;
  if (!background && !latestReport) renderReportSkeleton(panel);
  try {
    latestReport = await apiGetHubReport();
  } catch (error) {
    renderReportError(panel, error);
    return;
  }
  renderHubReport(panel, latestReport);
}
```

`renderReportSkeleton`, `renderReportError`, and `renderHubReport` come from `hubReport.js` in Task 7. **For this task, stub them** in `hubReport.js` so the tab is exercisable:

```javascript
export function renderReportSkeleton(panel) {
  panel.replaceChildren();
  const note = document.createElement("p");
  note.className = "hub-report-loading";
  note.textContent = "Loading the daily report…";
  panel.append(note);
}

export function renderReportError(panel, error) {
  panel.replaceChildren();
  const note = document.createElement("p");
  note.className = "hub-report-error";
  note.textContent = "Could not load the daily report.";
  panel.append(note);
  console.error("[hubReport]", error);
}

export function renderHubReport(panel, payload) {
  panel.replaceChildren();
  const note = document.createElement("p");
  note.textContent = `Report for ${payload.day} — ${payload.sections.closed_today.count} closed today.`;
  panel.append(note);
}
```

5. Reset and fall back in `loadUserHub`, beside the Graphs lines at `:433-435`:

```javascript
  if (userChanged) latestReport = null;
  if (!viewerIsAdmin() && activeTab === "report") activeTab = "dashboard";
```

The cache reset must sit **with** the admin-state reset, not after `showTab` — otherwise a role change renders the previous Admin's report for one frame.

Also add `"report"` to the `tabPanels` map and to whatever list drives `showTab`'s panel loop (`:96`). And re-fetch on tab re-entry, matching Graphs (§9 "Refresh").

- [ ] **Step 4: Verify**

```bash
node --check backend/static/api.js
node --check backend/static/views/userHub.js
node --check backend/static/views/hubReport.js
cd backend && "C:/Users/mcclu/Desktop/inventory_app_git/backend/venv/Scripts/python.exe" -m pytest -q
```

Then, manually (the JS has no harness): start the app, log in as `owner`, open the User Hub, confirm the Report tab appears and shows the stub line; log in as a non-Admin and confirm the tab is absent.

- [ ] **Step 5: Commit**

```bash
git add backend/static/api.js backend/static/pages/user-hub.html backend/static/views/userHub.js backend/static/views/hubReport.js
git commit -m "feat(hub): add the Admin-only lazy Report tab"
```

---

## Task 7: `hubReport.js` — the rendered report

**Files:**
- Modify: `backend/static/views/hubReport.js` (replace the Task 6 stub), `backend/static/styles.css`

**Interfaces:**
- Consumes: the `HubReportResponse` JSON (Task 4); `openWorkOrdersByNumberSearch` and `focusWorkOrderNumber` from `workOrders.js` (Task 5); `showPage` from wherever `userHub.js` imports it.
- Produces: `renderHubReport(panel, payload)`, `renderReportSkeleton(panel)`, `renderReportError(panel, error)` — signatures unchanged from the Task 6 stubs.

Layout target (§9):

```
Daily Report                          Thu, Aug 30 2026   [ Download CSV ]
Week of Aug 24 – Aug 30 · week to date

┌ Closed ──────────────────────────────────────────────────────────────┐
│   Today  20 (14 in NetFacilities)   This week  31 (14 in NetFacilities)│
│   [closed_week rows; today's rows carry a Today badge]                │
└───────────────────────────────────────────────────────────────────────┘
┌ Closing ─────────────────────────────────────────────────────────────┐
│   In the pipeline  9    ready to complete 4 · completed 3 · review 2  │
└───────────────────────────────────────────────────────────────────────┘
┌ New ─────────────────────────────────────────────────────────────────┐
│   Today  4           This week  21                                    │
└───────────────────────────────────────────────────────────────────────┘
```

- [ ] **Step 1: Build the row table**

Three visual sections, not five: Closed and New each render their **week** rows with today's marked, rather than repeating rows in a second table (§9). Build the "today" set by number from the `*_today` section:

```javascript
const todayNumbers = new Set(payload.sections.closed_today.rows.map((r) => r.number));
```

Columns (R12): Number · Status · Community / Location · Service type · Supervisor · Technicians · timestamp. The timestamp column header is `Closed` (`archived_at`) in the Closed section and `Created` (`created_at`) in Closing and New. Money stays in the CSV.

Compose the location cell from `community`, `building_number`, `unit_number`, `location` the way the Work Orders card already does — find it and reuse rather than reinventing:

```bash
grep -n "building_number" backend/static/views/workOrders.js | head
```

Wrap each table in the existing `.hub-timesheet-table-wrap` so a narrow screen scrolls the table, not the page.

- [ ] **Step 2: Make each row clickable (R11)**

The number cell holds a real `<button>` — keyboard-reachable, and **not** nested inside another button:

```javascript
button.addEventListener("click", () => {
  // A closed row has no card page: the list hides archived rows, so route to
  // the exact-number search and let the shipped restore prompt fire (R11).
  if (row.archived_at === null) {
    focusWorkOrderNumber(row.number);
  } else {
    openWorkOrdersByNumberSearch(row.number);
  }
  showPage("work-orders");
});
```

- [ ] **Step 3: Headers, badges, and the caveat**

- Closed header: `Today <count>` and `This week <count>`. Append ` (${n} in NetFacilities)` **only when** that section's `auto_closed_count` is non-zero (R10). With the reconcile migration not yet landed this is always absent — correct, not a bug.
- Closing header: `In the pipeline <count>` then `ready to complete N · completed N · review N`, read from `by_status`, **never** by counting rows (§7).
- Badges, all neutral, following the design system's badge-only status-accent rule — red stays the brand primary and never means "bad": `Today`, `Closed in NetFacilities` (`auto_closed`), `Legacy` (`legacy`).
- When `payload.sections.closing.truncated`, render a plain notice above the table saying the list is capped.
- Per-section empty states in plain words — "Nothing closed yet today.", not an empty table.
- One footnote under the Closed section (§3.2): restoring a closed work order — by hand, by the auto-close undo, or by a NetFacilities reappearance — removes it from these numbers. **This is a live view, not an archival record.**
- Render `generated_at` in the header so the viewer can see how stale the view is. Format all timestamps in Central, client-side.

- [ ] **Step 4: The download link**

A plain anchor to `/hub/report/export`, matching the timesheet export. No `fetch`, no blob.

- [ ] **Step 5: Styles**

Add report styles to `backend/static/styles.css` under a `hub-report-*` prefix. **No inline `style=` attributes anywhere** — CSP drops them silently, so a style that "does nothing" is the expected symptom of that mistake, not a browser bug.

- [ ] **Step 6: Verify**

```bash
node --check backend/static/views/hubReport.js
grep -n 'style="' backend/static/views/hubReport.js   # must return nothing
```

Then manually, per §11's frontend note: as `owner`, open the Report tab and check both R11 click branches (a Closing row opens its card; a Closed row lands on the restore prompt), the Closing sub-counts, an empty section's wording, and the CSV download's filename.

- [ ] **Step 7: Commit**

```bash
git add backend/static/views/hubReport.js backend/static/styles.css
git commit -m "feat(report): render the daily report on the hub"
```

---

## Task 8: Docs

**Files:**
- Modify: `docs/endpoint-map.md`, `docs/current-state.md`, `docs/open-work.md`

Per the doc-routing rule, `docs/` is a fixed set of seven files and `open-work.md` is the only backlog — do not create new doc files or archives.

- [ ] **Step 1: `docs/endpoint-map.md`**

Add both routes in the file's existing format, marked **admin only** — and note that this is the only Admin floor in the app.

- [ ] **Step 2: `docs/current-state.md`**

Describe the Report tab: Admin-only, company-wide, two nested Central windows evaluated week-to-date, and the §3.2 caveat that it is a live view rather than an archival record.

- [ ] **Step 3: `docs/open-work.md`**

Log the three §10 follow-ons as separate entries:
1. **`work_order_status_events`** — the fix for both §3.1 (Closing as a real delta) and §3.2 (audit-grade close history).
2. **Export audit logging** — this report's export joins the set the 2026-08-23 DEC commits to logging; add it to that sink's checklist when it lands.
3. **Real pagination for `closing`** — triggered by `event=list.truncated` with `list=hub_report_closing`.

- [ ] **Step 4: Run the docs tests**

Run: `cd backend && "C:/Users/mcclu/Desktop/inventory_app_git/backend/venv/Scripts/python.exe" -m pytest -q tests/test_docs_endpoints.py -v`
Expected: PASS. That test asserts the endpoint map matches the real routes, so it is the one that catches a missed entry.

- [ ] **Step 5: Full suite and commit**

```bash
cd backend && "C:/Users/mcclu/Desktop/inventory_app_git/backend/venv/Scripts/python.exe" -m pytest -q
git add docs/
git commit -m "docs(report): document the Admin daily report and its follow-ons"
```

---

## Verification before calling this done

Do not claim completion on any of these without pasting the actual output.

- [ ] `cd backend && "C:/Users/mcclu/Desktop/inventory_app_git/backend/venv/Scripts/python.exe" -m pytest -q` — 0 failures.
- [ ] `node --check` clean on all four touched JS files.
- [ ] `grep -rn 'style="' backend/static/views/hubReport.js` — no matches.
- [ ] `wc -l backend/app/services/work_order_report.py backend/static/views/hubReport.js` — both under 500.
- [ ] Manual: Report tab visible as Admin, absent for every lower role.
- [ ] Manual: both R11 click branches land where §9 says.
- [ ] Manual: the CSV downloads as `wo-report_<today>.csv`, opens in a spreadsheet with `SECTION` as the first column, and re-imports through the Work Orders import.
