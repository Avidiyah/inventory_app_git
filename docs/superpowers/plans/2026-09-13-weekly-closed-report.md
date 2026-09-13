# Weekly Closed Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Admin daily report with a week-selectable, lazily frozen record of closed work orders, rendered as one six-column tab per service type.

**Architecture:** The stored record is the JSON response (`HubReportResponse`), so the service returns Pydantic objects directly, the freeze stores `model_dump_json`, and both renderers (screen, workbook) consume one shape. The old sections, buckets, charts, and Data sheet are deleted, not adapted.

**Tech Stack:** FastAPI, SQLAlchemy 2 + Alembic (Postgres JSONB), openpyxl 3.1, vanilla ES modules, pytest, vitest + msw.

**Spec:** `docs/superpowers/specs/2026-09-13-weekly-closed-report-design.md` (W1–W13). Read it first; this plan does not restate it.

## Global Constraints

- Backend commands run from `backend/` with `./venv/Scripts/python.exe -m pytest`; frontend from the repo root with `npm test`.
- Files stay under 500 lines. No new files beyond those listed.
- One commit per task, suite green at each commit. No push (push deploys production).
- Central time via `app.domain.labor_day` only; never hand-roll offsets.
- Commit messages carry no Co-Authored-By trailer.

---

### Task 1: Storage and the week error

**Goal:** Additive groundwork that breaks nothing: the table, the ORM model, the 422 error.

**Files:**
- Create: `backend/alembic/versions/e2f4a6c8b0d3_add_work_order_report_weeks.py` (down_revision `d1e3f5a7b9c2`)
- Modify: `backend/app/models.py` (append after `NetFacilitiesCloudSession`), `backend/app/domain/errors.py`, `backend/app/routers/_errors.py` (`_STATUS_MAP`)
- Test: `backend/tests/test_work_order_report_weeks.py` (new)

**Produces:**
```python
class WorkOrderReportWeek(Base):
    __tablename__ = "work_order_report_weeks"
    week_start = Column(Date, primary_key=True)
    frozen_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    schema_version = Column(Integer, nullable=False)
    payload = Column(JSONB, nullable=False)

class ReportWeekError(DomainError): ...   # _STATUS_MAP[ReportWeekError] = 422
```

**Steps:**
1. Test: inserting a `WorkOrderReportWeek` with `week_start=date(2026, 9, 7)`, `schema_version=1`, `payload={"a": 1}` reads back with a tz-aware `frozen_at`; a second insert of the same key raises `IntegrityError`.
2. Run it; fails on import.
3. Write the migration (mirror `fcbc2524ea62_*.py`'s header shape; `downgrade` drops the table), the model, the error class, the status map entry.
4. `alembic upgrade head` against the dev DB; rerun test; run `tests/test_route_role_gates.py` to confirm nothing shifted.
5. Commit: `feat(report): work_order_report_weeks table and ReportWeekError`.

---

### Task 2: Backend cut-over — schema, service, freeze, workbook, routes

One commit because the schema, service, renderer, and routes consume each other; splitting them leaves the app unimportable between commits. Tests are still written before each piece.

**Goal:** `GET /hub/report?week=` and `/hub/report/export?week=` serve the weekly closed record per W1–W10, W12, W13.

**Files:**
- Rewrite: `backend/app/services/work_order_report.py`, `backend/app/services/work_order_report_xlsx.py`
- Modify: `backend/app/schemas/hub.py` (replace `HubReportRow` … `HubReportResponse`), `backend/app/routers/hub.py` (the two report handlers + header docstring line), `backend/app/services/_xlsx_theme.py` (delete `kpi`, `table_of`, `notes_row_height`, `pie_of`, `column_chart_of`, `place`, `BUCKET_COLORS`, `SERIES_COLORS`, chart imports, and the notes constants)
- Delete: `backend/app/services/work_order_report_buckets.py`, `backend/app/services/work_order_report_xlsx_charts.py`, `backend/tests/test_work_order_report_buckets.py`
- Rewrite tests: `backend/tests/test_work_order_report.py`, `backend/tests/test_work_order_report_xlsx.py`; replace the four report tests in `backend/tests/test_hub_router.py` (lines 228–294)

**Produces (exact names later tasks and tests use):**
```python
# schemas/hub.py
class HubReportRow(BaseModel):
    work_order_id: uuid.UUID
    number: str
    assigned_to: Optional[str] = None      # WorkOrder.vendor_assignee
    location: Optional[str] = None
    service_type: Optional[str] = None     # raw
    service_type_label: str                # normalize_service_type()[1]
    community: str                         # primary community KEY, e.g. "scholars"
    schedule_date: Optional[str] = None    # raw text
    priority: Optional[str] = None
    archived_at: datetime

class HubReportResponse(BaseModel):
    week_start: date
    week_end: date
    status: Literal["in_progress", "completed"]
    generated_at: datetime
    frozen_at: Optional[datetime] = None
    count: int
    rows: list[HubReportRow]

# services/work_order_report.py
SCHEMA_VERSION = 1
def resolve_week(week: Optional[date], now: datetime) -> date        # W7; raises ReportWeekError
def week_window(week_start: date) -> tuple[datetime, datetime]       # UTC half-open, W1
def is_completed(week_start: date, now: datetime) -> bool            # W2
def weekly_report(db, *, week_start: date, now: datetime) -> HubReportResponse   # live compute
def report_for_week(db, *, week_start: date, now: datetime) -> HubReportResponse # W2/W5 dispatch
def row_sort_key(row: HubReportRow) -> tuple                         # (label.casefold(), community index, number)

# services/work_order_report_xlsx.py
XLSX_MEDIA_TYPE, HEADERS = ("WORK ORDER","ASSIGNED TO","LOCATION","SERVICE TYPE","SCHEDULE DATE","PRIORITY")
WIDTHS = {"A": 14, "B": 22, "C": 34, "D": 18, "E": 14, "F": 10}
EMPTY_SHEET = "Report"; EMPTY_TEXT = "No work orders closed this week."
def report_xlsx(payload: HubReportResponse) -> bytes
def report_xlsx_filename(payload) -> str      # f"wo-report_{payload.week_start.isoformat()}.xlsx"
def sheet_name(label: str, taken: set[str]) -> str   # strip : \ / ? * [ ], cut to 31, suffix " (2)" on collision
```

**Steps:**

*2a — schema and service (`test_work_order_report.py`; keep its `_user`/`_work_order` helpers, add `vendor_assignee`, `priority`, `schedule_date`, `archived_at` kwargs).*
1. Tests, all red first:
   - `resolve_week`: `None` → this Monday (freeze `now` with a fixed UTC instant and compute the expected Monday through `labor_day`); a past Monday returns itself; a Tuesday raises `ReportWeekError`; next Monday raises.
   - `week_window`: `week_window(date(2026,9,7))` == `(day_bounds(2026-09-07)[0], day_bounds(2026-09-13)[1])`.
   - `is_completed`: false at Sunday 23:59:59 Central, true at Monday 00:00:00 Central of the following week (build instants with `datetime(..., tzinfo=labor_day.CENTRAL)`).
   - `weekly_report` window edges: rows archived at Sunday 23:59:59 Central and Monday 00:00:00 Central of week W; only the first is in W's `rows`; the second is in W+1's. Use a week far in the past (e.g. 2021) so dev rows cannot collide.
   - A restored row (`archived_at=None`) is absent. A live row is absent.
   - Row projection: `assigned_to` is `vendor_assignee`; `service_type_label` for `"  plumbing "` is `"plumbing"` and for `None` is `"Unspecified"`; `community` for `location="Scholars 12-304"` is `"scholars"` and for a location naming two communities is the first in `ALL_COMMUNITY_FILTERS`; a location naming none is `"academics"`.
   - Ordering: three rows with labels `b`, `A`, `a` and mixed communities come back sorted by `row_sort_key`; assert the exact number sequence.
   - `count == len(rows)`; `status == "in_progress"` when `now` is inside the week, `"completed"` when after; `frozen_at is None` from `weekly_report`.
2. Replace `schemas/hub.py`'s report classes with the two above (delete `HubReportClosedSection`, `HubReportClosingSection`, `HubReportNewSection`, `HubReportWeek`, `HubReportSections`).
3. Rewrite `work_order_report.py`: module docstring (three sentences, cite spec), the functions above. `_closed_rows` queries `WorkOrder` columns only (`id, number, vendor_assignee, location, service_type, community, priority, schedule_date, archived_at`) with `archived_at >= start, archived_at < end`; builds `HubReportRow`s; sorts by `row_sort_key`. `resolve_week` messages: `"week must be a Monday (YYYY-MM-DD)."`, `"week cannot be in the future."`
4. Green. Delete `work_order_report_buckets.py` and its test file.

*2b — freeze (same test file, `class TestFreeze`).*
5. Tests:
   - First `report_for_week` for a completed past week inserts exactly one `WorkOrderReportWeek` row (count rows for that `week_start` before/after) and returns `status="completed"`, `frozen_at` not None, `schema_version` 1.
   - After the freeze, archive a new row into that week and restore a frozen one; the second call's `rows` equal the first's (compare `model_dump()` minus `frozen_at`).
   - The current week never inserts (`weekly_report` path; `frozen_at is None`).
   - Concurrency: monkeypatch `db.get` to return `None` on its first call only, so the code path takes the insert branch when a row already exists; assert no exception and the returned payload equals the pre-existing stored one (this exercises `on_conflict_do_nothing` + re-read without threads).
6. Implement:
   ```python
   def report_for_week(db, *, week_start, now):
       if not is_completed(week_start, now):
           return weekly_report(db, week_start=week_start, now=now)
       stored = db.get(WorkOrderReportWeek, week_start)
       if stored is None:
           payload = weekly_report(db, week_start=week_start, now=now)
           db.execute(
               insert(WorkOrderReportWeek)
               .values(week_start=week_start, schema_version=SCHEMA_VERSION,
                       payload=json.loads(payload.model_dump_json()))
               .on_conflict_do_nothing(index_elements=["week_start"])
           )
           db.commit()
           stored = db.get(WorkOrderReportWeek, week_start)
       return HubReportResponse.model_validate(stored.payload).model_copy(
           update={"frozen_at": stored.frozen_at})
   ```
   `insert` is `sqlalchemy.dialects.postgresql.insert`.
7. Green.

*2c — workbook (`test_work_order_report_xlsx.py`; build payloads with `HubReportResponse(...)` directly, no DB).*
8. Tests:
   - Sheet names for rows labelled `Window Repair`, `Maintenance`, `SMR27 - Belfor` are `["Maintenance", "SMR27 - Belfor", "Window Repair"]`.
   - `sheet_name("A/B: C?", set())` == `"A B  C"` (each forbidden char becomes a space, then strip); a 40-char label is cut to 31; a name already in `taken` gets `" (2)"`.
   - On a tab with rows in `scholars` and `academics` only: `A1` is the label, `A2` is `f"Closed {ws} – {we} · N work orders"`, `A3` reads `"Completed · frozen YYYY-MM-DD HH:MM Central"` (or `"In progress · generated …"`), `A5` is `"Scholars"`, row 6 is `HEADERS`, row 7 the first row's six raw values, then a blank row, then `"Academics"` heading, header, rows. Centennial/Commons/Young Hall headings absent.
   - Cell values are the raw strings (`schedule_date` `"7/21/2026"` stays a string; `None` writes an empty cell).
   - Empty payload: exactly one sheet `"Report"`, `A5` == `EMPTY_TEXT`.
   - Filename is the Monday. Column widths equal `WIDTHS`. `sheet_view.showGridLines` is False.
9. Rewrite `work_order_report_xlsx.py`: group `payload.rows` by `service_type_label` in order of first appearance (already sorted); per group create the sheet via `sheet_name`, `theme.setup_sheet(sheet, tab_color=theme.MUTED, freeze=None)`, `theme.set_widths`, `theme.title_block`; cursor from row 5: for each community key in `wo.ALL_COMMUNITY_FILTERS` with rows, `theme.section(sheet, r, wo.COMMUNITY_LABELS[key])`, `theme.header_row(sheet, r+1, HEADERS)`, `theme.write_rows(sheet, r+2, cells)`, then one blank row. Delete the `_xlsx_theme` chart helpers and the charts module.
10. Green.

*2d — routes (`test_hub_router.py`).*
11. Tests: replace the four report tests with: JSON body keys `{week_start, week_end, status, generated_at, frozen_at, count, rows}`; `?week=2026-09-08` (a Tuesday) → 422 on both routes; a far-past Monday → 200 with `status == "completed"`; export is an attachment named `wo-report_<monday>.xlsx` with `content-type == XLSX_MEDIA_TYPE` and loads in openpyxl; the two 403 tests unchanged.
12. Router: both handlers gain `week: Optional[date] = Query(None)`; body:
    ```python
    now = datetime.now(timezone.utc)
    try:
        week_start = work_order_report.resolve_week(week, now)
    except DomainError as exc:
        raise to_http(exc) from exc
    payload = work_order_report.report_for_week(db, week_start=week_start, now=now)
    ```
    JSON route returns `payload`; export wraps `report_xlsx(payload)` as before. Update the header docstring's `/hub/report` line to `admin only -- the weekly closed record`. Function names `get_hub_report` / `export_hub_report` unchanged (W12).
13. Full backend suite green (`test_route_role_gates.py` untouched and passing; `test_solo_card` may be pre-existing red, see memory).
14. Commit: `feat(report): weekly closed record with frozen weeks, six-column service-type workbook`.

---

### Task 3: Frontend — week picker and mirrored sections

**Goal:** The Report tab renders the weekly record per spec §7.

**Files:**
- Modify: `backend/static/api.js` (`apiGetHubReport`), `backend/static/views/userHub.js` (report state + `loadReport`), `backend/static/styles.css` (add `.hub-report-weeknav`, `.hub-report-status`, reuse existing `.hub-report-*` rules; delete `.hub-report-counts`, `-count*`, `-breakdown`, `-subcount`, `-truncated`, `-footnote`, `-badge` rules)
- Rewrite: `backend/static/views/hubReport.js`
- Tests: rewrite `tests/frontend/views/hubReport.test.js`; reshape `hubReport`/`hubReportRow` in `tests/frontend/helpers/factories.js`; adjust `userHub.test.js` lines 214–222 and 292–298 only if they break (they match by URL fragment, so they should not).

**Produces:**
```js
// api.js
export async function apiGetHubReport({ week = null } = {})   // GET /hub/report or /hub/report?week=YYYY-MM-DD
// hubReport.js
export function mountHubReport(panel, payload, { onSelectWeek })  // onSelectWeek(mondayIsoOrNull)
export function renderReportSkeleton(panel); export function renderReportError(panel, err, onRetry)
// userHub.js: module state `reportWeek` (null = current week); loadReport({ background, week })
```

**Steps:**
1. Factories: `hubReport()` → `{ week_start: "2026-09-07", week_end: "2026-09-13", status: "in_progress", generated_at, frozen_at: null, count: 0, rows: [] }`; `hubReportRow()` → `{ work_order_id, number: "7001", assigned_to: "Belfor Dispatch", location: "Scholars 12-304", service_type: "Maintenance", service_type_label: "Maintenance", community: "scholars", schedule_date: "7/21/2026", priority: "Normal", archived_at: "2026-09-10T15:00:00Z" }`.
2. Tests (red):
   - Header: `.hub-report-week` reads `Week of Sep 7 – Sep 13, 2026`; `.hub-report-status` reads `In progress · generated <central stamp>` for the fixture and `Completed · frozen <central stamp>` when `status: "completed", frozen_at: "…"`; `.hub-report-download` href is `/hub/report/export?week=2026-09-07`; `.hub-report-count` reads `41 closed work orders` when `count: 41`.
   - Arrows: `◀` triggers a fetch of `/hub/report?week=2026-08-31`; `▶` is disabled while `status` is `in_progress`; on a completed week `▶` fetches `week=2026-09-14`; `This week` fetches `/hub/report` with no query. Assert via `requestFor`.
   - Sections: rows with labels `Maintenance` ×2 and `Window Repair` ×1 render two `.hub-report-section`s in payload order with `h3` text `Maintenance (2)` / `Window Repair (1)`; headers are `Community | Number | Assigned to | Location | Schedule date | Priority | Closed`; a row's cells are `Scholars | 7001 | Belfor Dispatch | Scholars 12-304 | 7/21/2026 | Normal | <central stamp>`; nulls render `—`.
   - Empty: `.hub-report-empty` reads `No work orders closed this week.`
   - Hand-off: clicking a number calls `openWorkOrdersByNumberSearch` (every row is archived) and swaps to Work Orders — keep the existing test body.
   - Re-entry: after `◀`, leaving and re-entering the tab re-fetches `week=2026-08-31`, not the current week.
   - Loading/failure: keep the two existing tests.
3. `api.js`: build the URL with `URLSearchParams` when `week` is set.
4. `hubReport.js`: community label map `{scholars:"Scholars", centennial:"Centennial", commons:"Commons", young_hall:"Young Hall", academics:"Academics"}`; Monday arithmetic in UTC (`new Date(iso+"T00:00:00Z")` ± 7 days → `toISOString().slice(0,10)`); group rows by `service_type_label` preserving order; every number button carries `data-archived="1"`.
5. `userHub.js`: `reportWeek` state; `loadReport` passes `{ week: reportWeek }`; `mountHubReport(mount, payload, { onSelectWeek: (w) => { reportWeek = w; void loadReport(); } })`; reset `reportWeek = null` where `latestReportPayload` is reset on user change.
6. `npm test` green.
7. Commit: `feat(report): week picker and service-type sections on the Report tab`.

---

### Task 4: Docs

**Goal:** Living docs state the new truth; the backlog loses items the change retires.

**Files:** `docs/current-state.md` (the "User Hub Report" row), `docs/endpoint-map.md` (H6/H7 rows and the `HubReportResponse` paragraph), `docs/open-work.md` (line 36 list, delete `N-REPORT-CLOSING-PAGINATION`, narrow `N-WO-STATUS-EVENTS` to note frozen weeks satisfy this report's reconcile trigger, keep `N-REPORT-EXPORT-AUDIT` but say "Excel export").

**Steps:**
1. Rewrite the three places per spec §3–§7 in the docs' clipped-bullet form; delete every mention of sections, buckets, pies, `Data` sheet, and `hub_report_closing`.
2. Stay within each doc's word budget; delete a stale line if an edit breaches it.
3. Commit: `docs: record the weekly closed report`.

---

## Self-review

- **Spec coverage:** W1–W2 (Task 2a), W3 (2a), W4 (2b/2d), W5–W6 (2b), W7 (2a/2d), W8–W10 (2c), W11 (3), W12 (2d), W13 (2b: `SCHEMA_VERSION`, no re-freeze path exists), §4 (1), §8 test list (2a–2d, 3), §9 (4). No gaps.
- **Type consistency:** `HubReportRow.community` is the community *key*; the workbook and screen both map it through `COMMUNITY_LABELS`. `frozen_at` is `None` from `weekly_report` and filled by `report_for_week`. `resolve_week` raises `ReportWeekError`, mapped to 422 in Task 1.
