# User Hub P3b — Timesheets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Timesheets tab for the Supervisor hub — `GET /hub/timesheets`, the technician-by-day grid with per-cell session/adjustment drill-down, and CSV export — so a supervisor can answer "how many hours did my crew put in this week" and hand a payroll-ready file to a bookkeeper.

**Architecture:** Backend adds one new efficient range query (`services/labor_summary.py::crew_range_summaries`, one query per row-type across the whole date range rather than one per day) feeding a new service composer (`services/hub.py::timesheets_hub`) and a CSV serializer, exposed as two sibling routes — `GET /hub/timesheets` (JSON) and `GET /hub/timesheets/export` (CSV) — mirroring the existing `/work-orders` + `/work-orders/export` sibling-endpoint convention. Frontend adds a third tab to the existing `userHub.js` shell, fetched lazily on tab switch (never on page load), rendering a new `hubTimesheets.js` view that reuses the CSV-download pattern already established in `workOrders.js`.

**Tech Stack:** Vanilla ES modules (no framework, no build step), matching every existing view under `backend/static/views/`. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-20-user-hub-design.md` — read §4.1 (endpoint gate table, the `supervisor+`-gated-but-rank-scoped correction), §5.3 Tab 2 and §5.4 Tab 2 (the grid and drill-down mockups, shared component), §6.3 (attention thresholds, reused here), §7 `GET /hub/timesheets` contract and the CSV filename rule (D14), §12 (phasing — **D17 moved the grid into this phase; P4 only widens the row scope from "my crew" to "everyone", which this plan explicitly does not build**), §14.1 (the second audit pass — D15/D17 corrections this plan follows).

**P1/P2/P3a status:** shipped, unmerged, on `user-hub-p1-time-engine` / `user-hub-p2-technician-hub` / `user-hub-p3-crew` respectively. This plan continues on `user-hub-p3-crew`. Relevant prior art this phase reuses directly:

- `domain/labor_day.py`: `day_bounds`, `central_date_of`, `overlap_minutes`, `split_by_day` (already built, unused until now — this phase is its first caller), `CENTRAL`.
- `domain/hub.py`: `is_assigned_idle`, `FLAG_ASSIGNED_IDLE`, the flag-vocabulary convention.
- `services/labor_summary.py`: `DaySummary`, `TimelineEntry`, `RunningSession`, `Adjustment` dataclasses — the day-cell shape this phase batches across a range instead of building one day at a time.
- `services/hub.py::crew_hub`: the exact "who is my crew" derivation (D6) this phase's row scope reuses, via a small refactor.
- `schemas/hub.py`: `HubUser`, `HubTimelineEntry`, `HubAdjustment` — reused as-is inside the new day-cell schema.

---

## Global Constraints

- **P3b scopes every caller to their own routed crew, full stop.** Spec §7's abbreviated contract header (`GET /hub/timesheets?...` — techfm_oa+`) is stale — it predates the D17 correction recorded in §14.1 and contradicted by §4.1's own table two sections earlier (`supervisor+`, row-scoped by rank) and by §12's phasing table, which assigns "timesheet scope widened to everyone" to **P4** explicitly, as a service-layer change. This plan builds the `supervisor+` gate and the "my crew" row scope only. **Do not build a role branch inside `timesheets_hub` for TechFM OA+ seeing everyone — that is P4's job**, and building it now would ship an unreviewed guess at what "everyone" means (every user? every technician-or-supervisor? excluding archived?) that the spec explicitly defers.
- **The zero-day "assigned" flag is a documented interpretation, not a literal spec mechanism.** Spec §5.4's mockup shows `⚠` on a *past* day with zero tracked time ("D. Ortiz 0:00⚠" on a Tuesday). The app has no stored history of what was assigned on a past date — assignment is current-state only (`work_order_technicians` rows have no "as of" date). This plan reuses `domain.hub.is_assigned_idle` exactly as `/hub/crew` already does — comparing each day's own zero-minute total against the technician's *current* assigned-work-order count and the real wall-clock hour — applied uniformly across every day in the range. This is an approximation (a technician assigned work today reads as "should have worked" on every zero day in the visible range, not just days they were actually assigned something), accepted because inventing a fabricated assignment-history model would be worse, and it reuses the single existing predicate rather than adding a second one. Note this if a future session wants to sharpen it.
- **The supervisor's own hours are excluded from the grid**, by construction: the row scope reuses the exact same crew-derivation `crew_hub` uses for D6/D13 (technicians on work orders the supervisor leads, supervisor's own id discarded). A supervisor's own tracked time lives in their personal clock widget, not this grid — same reasoning D13 already established for the crew board, extended here rather than re-litigated.
- **The endpoint is not side-effect-free**, by the same reasoning P3a's `/hub/crew` router docstring already recorded for itself (spec §3.5 assigns the global sweep to `GET /hub/admin` only and is silent on `/hub/crew` and `/hub/timesheets`): a stale, over-cap running session inside the requested range would otherwise show an inflated, uncapped running-minutes figure instead of the swept, auto-closed estimate. Every technician in scope is swept individually before the range is read — same pattern, same idempotency guarantee (row lock, second concurrent caller finds nothing left to close).
- **CSV export shares `timesheets_hub`'s composition, not a parallel query path.** `GET /hub/timesheets/export` calls the same service function the JSON route calls, then serializes the result — so the numbers in the downloaded file can never drift from what the grid just showed the same caller, and the sweep only needs implementing once.
- **The `MAX_LIST_ROWS` cap (5000) applies to the two range-spanning queries** (`crew_range_summaries`'s session fetch and its adjustment fetch) via `services._list_cap`, per spec §7 — "consistent with the other six capped lists." It does **not** apply to `rows` (technician count) or `crew_totals_by_day` (day count), which are bounded by crew size and the 92-day range cap respectively and never realistically approach 5000.
- **The 92-day range cap raises a new domain error mapped to 422** (`TimesheetRangeTooLargeError`), per spec §7's explicit requirement ("returns 422 with a `detail` naming the limit"). This is the first 422 in `_STATUS_MAP` — every existing entry is 400/401/403/409/429.
- **CSV minute formatting is `H:MM`**, matching spec §5.4's mockup literally (`7:05`, `21:35`), not the `H h MM m` format the hub's tiles use elsewhere — this file is read by a bookkeeper, not a technician glancing at a phone.
- **The CSV filename's user suffix is the slugified `User.full_name`** (`app/models.py:70`, `"First Last"`, trimmed), per spec §7's literal instruction ("the user suffix is the slugified full name"). The spec's own example (`j-rivera`) is diagram shorthand consistent with the abbreviated first-name mockups used throughout the spec's ASCII art (`J. Rivera`, `M. Chen`) for column width, not a literal filename spec — a technician named "Jordan Rivera" gets `jordan-rivera.csv`, not `j-rivera.csv`.
- **No frontend test harness exists** (verified against the repo, same finding P2's plan recorded — no JS test runner configured). The frontend tasks below substitute a scripted manual-verification step via the `chrome-devtools` MCP tools for the automated test/run/pass cycle the backend tasks use.
- **No new realtime event, no polling.** The timesheet grid is a historical/audit surface (spec's own framing, §5.4: "This is the audit surface D2 promised"), not a live board — it fetches on tab switch and on explicit week navigation or CSV export, and nothing else. Do not wire it into the existing `CREW_SAFETY_REFRESH_MS` timer or the `labor.session.changed` subscriber; both are `/hub/crew`'s concern only.
- **`week_bounds_containing` (Monday–Sunday, Central) is new in `domain/labor_day.py`.** P4's `/hub/admin` billing default (D12, "the current Central week") will need the identical definition later — this plan is where that shared primitive is born; a future P4 session should reuse it rather than redefine "current week."
- **Commit message style:** `feat(user-hub): …` / `docs(user-hub): …`, matching P1/P2/P3a's history.
- **Stay on the current branch, `user-hub-p3-crew`.** No new branch — this phase continues P3a's branch per the spec's own P3 grouping (§12: "`GET /hub/timesheets` and the timesheet grid" are explicitly part of the P3 row, not a separate phase). Merging to `main` deploys to production — the merge is the owner's call.
- **Never truncate an existing file.** Every "Modify" step below is a targeted insertion at a located line. Read first, edit in place.

---

## File Structure

```
backend/app/domain/labor_day.py        EDIT  add week_bounds_containing (§Task 1)
backend/app/domain/errors.py           EDIT  add TimesheetRangeInvalidError, TimesheetRangeTooLargeError (§Task 2)
backend/app/routers/_errors.py         EDIT  register both in _STATUS_MAP (§Task 2)
backend/app/domain/hub.py              EDIT  add FLAG_RUNNING (§Task 3)
backend/app/services/labor_summary.py  EDIT  add crew_range_summaries (§Task 4)
backend/app/services/hub.py            EDIT  extract _led_work_orders/_crew_ids_from (§Task 5); add timesheets_hub (§Task 6); add timesheet_csv (§Task 7)
backend/app/schemas/hub.py             EDIT  add HubTimesheetRange/Day/Row/DayTotal/Response (§Task 8)
backend/app/routers/hub.py             EDIT  add GET /hub/timesheets, GET /hub/timesheets/export (§Task 9)
docs/endpoint-map.md                   EDIT  register H3, H4 + response schemas (§Task 10)
docs/open-work.md                      EDIT  P3b shipped, P4 next (§Task 11)
backend/static/api.js                  EDIT  add apiGetHubTimesheets, apiExportHubTimesheets (§Task 12)
backend/static/pages/user-hub.html     EDIT  add Timesheets tab button + panel (§Task 13)
backend/static/styles.css              EDIT  timesheet grid styles (§Task 13)
backend/static/views/hubTimesheets.js  NEW   grid render, drill-down, week nav, CSV button (§Task 14)
backend/static/views/userHub.js        EDIT  wire the third tab, lazy fetch, role gating (§Task 15)
```

---

### Task 1: `week_bounds_containing` — pure domain arithmetic

**Files:**
- Modify: `backend/app/domain/labor_day.py` (after `central_date_of`, ~line 64)
- Test: `backend/tests/test_labor_day.py`

**Interfaces:**
- Produces: `labor_day.week_bounds_containing(day: date) -> tuple[date, date]` — Monday and Sunday of the Central calendar week containing `day`, both inclusive.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_labor_day.py — append

def test_week_bounds_containing_mid_week():
    # Wednesday Aug 19, 2026 -> Monday Aug 17 through Sunday Aug 23.
    start, end = labor_day.week_bounds_containing(date(2026, 8, 19))
    assert start == date(2026, 8, 17)
    assert end == date(2026, 8, 23)


def test_week_bounds_containing_on_monday():
    start, end = labor_day.week_bounds_containing(date(2026, 8, 17))
    assert start == date(2026, 8, 17)
    assert end == date(2026, 8, 23)


def test_week_bounds_containing_on_sunday():
    start, end = labor_day.week_bounds_containing(date(2026, 8, 23))
    assert start == date(2026, 8, 17)
    assert end == date(2026, 8, 23)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_labor_day.py -k week_bounds -v`
Expected: FAIL with `AttributeError: module 'app.domain.labor_day' has no attribute 'week_bounds_containing'`

- [ ] **Step 3: Implement**

```python
# backend/app/domain/labor_day.py — insert after central_date_of (~line 64)

def week_bounds_containing(day: date) -> tuple[date, date]:
    """The Monday and Sunday, both inclusive, of the Central calendar week
    containing `day` -- the same Monday-start week spec §5.4's grid mockup
    uses ("Week of Aug 17 - Aug 23", a Monday through a Sunday).

    Pure date arithmetic -- `date.weekday()` (Monday=0) needs no timezone,
    since `day` is already a Central calendar date by the time it reaches
    here (every caller passes the output of `central_date_of`).
    """
    start = day - timedelta(days=day.weekday())
    return start, start + timedelta(days=6)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && python -m pytest tests/test_labor_day.py -v`
Expected: PASS, all tests including the three new ones and every pre-existing one in the file.

- [ ] **Step 5: Commit**

```bash
git add backend/app/domain/labor_day.py backend/tests/test_labor_day.py
git commit -m "feat(user-hub): add week_bounds_containing for the timesheet default range"
```

---

### Task 2: Timesheet range domain errors

**Files:**
- Modify: `backend/app/domain/errors.py` (end of file, after `ToolReturnExceedsCheckedOutError`, ~line 337)
- Modify: `backend/app/routers/_errors.py` (`_STATUS_MAP`, ~line 90)
- Test: `backend/tests/test_hub_service.py` (exercised indirectly by Task 6's tests; no standalone test needed for two plain exception classes)

**Interfaces:**
- Produces: `TimesheetRangeInvalidError` (400), `TimesheetRangeTooLargeError` (422, carries `.max_days`).

- [ ] **Step 1: Add the exception classes**

```python
# backend/app/domain/errors.py — append at end of file

class TimesheetRangeInvalidError(DomainError):
    """Raised by `services.hub.timesheets_hub` when the requested end date
    precedes the start date. Maps to 400."""


class TimesheetRangeTooLargeError(DomainError):
    """Raised by `services.hub.timesheets_hub` when the requested date range
    exceeds `services.hub.MAX_TIMESHEET_RANGE_DAYS` (spec §7, D14's
    surrounding text). Carries the limit so the message and any caller
    inspecting the exception see the same number. Maps to 422 -- the
    spec is explicit that this is not a plain 400 ("returns 422 with a
    detail naming the limit")."""

    def __init__(self, max_days: int):
        self.max_days = max_days
        super().__init__(f"Date range cannot exceed {max_days} days.")
```

- [ ] **Step 2: Register both in the status map**

Read `backend/app/routers/_errors.py` first to confirm the current line numbers around `_STATUS_MAP` (imports at the top of the file, dict starting ~line 30, closing brace ~line 90) before editing — the exact insertion point.

```python
# backend/app/routers/_errors.py — add to the imports near the top
from app.domain.errors import (
    # ...existing names...
    TimesheetRangeInvalidError,
    TimesheetRangeTooLargeError,
)
```

```python
# backend/app/routers/_errors.py — add inside _STATUS_MAP, near the other 400s
    TimesheetRangeInvalidError: 400,
    TimesheetRangeTooLargeError: 422,
```

- [ ] **Step 3: Verify the module still imports cleanly**

Run: `cd backend && python -c "from app.routers._errors import to_http; from app.domain.errors import TimesheetRangeTooLargeError; print(to_http(TimesheetRangeTooLargeError(92)).status_code, to_http(TimesheetRangeTooLargeError(92)).detail)"`
Expected: `422 Date range cannot exceed 92 days.`

- [ ] **Step 4: Commit**

```bash
git add backend/app/domain/errors.py backend/app/routers/_errors.py
git commit -m "feat(user-hub): add timesheet range validation errors"
```

---

### Task 3: `FLAG_RUNNING` — the day-cell running-clock flag

**Files:**
- Modify: `backend/app/domain/hub.py` (flag constants block, ~line 34-37)

**Interfaces:**
- Produces: `hub_domain.FLAG_RUNNING = "running"`.

- [ ] **Step 1: Add the constant**

```python
# backend/app/domain/hub.py — insert alongside the other FLAG_* constants (~line 37)
FLAG_RUNNING = "running"
```

Add one line to the module docstring's flag vocabulary list (~line 9-11) so it reads `long_session`, `approaching_cap`, `assigned_idle`, `stale_work_order`, `running` — this flag marks a day cell whose session is still open (spec §5.4's `●` marker), a presence fact rather than a threshold predicate, so it has no companion function the way the other four do; the composer in Task 6 sets it directly from `DaySummary.running is not None`.

- [ ] **Step 2: Verify import**

Run: `cd backend && python -c "from app.domain import hub; print(hub.FLAG_RUNNING)"`
Expected: `running`

- [ ] **Step 3: Commit**

```bash
git add backend/app/domain/hub.py
git commit -m "feat(user-hub): add the running-clock day-cell flag"
```

---

### Task 4: `crew_range_summaries` — batched range query

This is the core new query. It replaces what would otherwise be `day_summary()` called once per (technician, day) — for a 92-day range across a few dozen technicians, thousands of queries — with exactly two range-spanning queries (sessions, adjustments) whose rows are then distributed across the days they touch using `labor_day.split_by_day`, the same arithmetic `day_summary` already uses for one day at a time.

**Files:**
- Modify: `backend/app/services/labor_summary.py` (imports at top; new function after `crew_day_summaries`, ~line 270)
- Test: `backend/tests/test_labor_summary.py`

**Interfaces:**
- Consumes: `labor_day.split_by_day`, `labor_day.day_bounds`, `labor_day.as_utc`, `labor_day.central_date_of` (all existing); `list_limits.fetch_limit()`, `_list_cap.capped()` (existing, new callers).
- Produces: `labor_summary.crew_range_summaries(db, technician_ids: list[uuid.UUID], start_day: date, end_day: date, *, now: datetime) -> dict[uuid.UUID, list[DaySummary]]` — one list of `DaySummary`, ordered `start_day..end_day` inclusive, per technician id. Every requested day is present for every technician, zero-valued or not.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_labor_summary.py — append (uses this file's existing
# _seed_user/_seed_work_order/_seed_session helpers and `db` fixture; read
# the top of the file first to confirm their exact signatures before writing
# new tests, matching test_hub_service.py's helpers of the same names)

def test_crew_range_summaries_every_day_present_even_with_no_activity(db):
    tech = _seed_user(db)
    result = labor_summary.crew_range_summaries(
        db, [tech.id], date(2026, 8, 17), date(2026, 8, 19), now=NOW
    )
    days = result[tech.id]
    assert [d.day for d in days] == [date(2026, 8, 17), date(2026, 8, 18), date(2026, 8, 19)]
    assert all(d.total_minutes == 0 for d in days)


def test_crew_range_summaries_splits_a_session_across_two_days(db):
    tech = _seed_user(db)
    creator = _seed_user(db, first_name="Sam", last_name="Creator")
    wo_row = _seed_work_order(db, created_by=creator, assigned_to=tech)
    # 11:00 PM Aug 17 Central -> 1:00 AM Aug 18 Central, both in UTC.
    started = datetime(2026, 8, 18, 4, 0, tzinfo=timezone.utc)   # 11:00 PM CDT Aug 17
    ended = datetime(2026, 8, 18, 6, 0, tzinfo=timezone.utc)     # 1:00 AM CDT Aug 18
    _seed_session(db, wo_row, tech, started_at=started, ended_at=ended)

    result = labor_summary.crew_range_summaries(
        db, [tech.id], date(2026, 8, 17), date(2026, 8, 18), now=NOW
    )
    day17, day18 = result[tech.id]
    assert day17.closed_minutes == 60
    assert day18.closed_minutes == 60
    assert len(day17.timeline) == 1
    assert len(day18.timeline) == 1


def test_crew_range_summaries_running_session_marks_running(db):
    tech = _seed_user(db)
    creator = _seed_user(db, first_name="Sam", last_name="Creator")
    wo_row = _seed_work_order(db, created_by=creator, assigned_to=tech)
    started = NOW - timedelta(hours=1)
    _seed_session(db, wo_row, tech, started_at=started, ended_at=None)

    result = labor_summary.crew_range_summaries(
        db, [tech.id], labor_day.central_date_of(NOW), labor_day.central_date_of(NOW), now=NOW
    )
    today = result[tech.id][0]
    assert today.running is not None
    assert today.running_minutes == 60


def test_crew_range_summaries_adjustments_bucket_by_created_at_day(db):
    tech = _seed_user(db)
    creator = _seed_user(db, first_name="Sam", last_name="Creator")
    wo_row = _seed_work_order(db, created_by=creator, assigned_to=tech)
    from app.models import WorkOrderLabor
    window_start, _ = labor_day.day_bounds(date(2026, 8, 18))
    labor = WorkOrderLabor(
        id=uuid.uuid4(),
        work_order_id=wo_row.id,
        technician_id=tech.id,
        recorded_by_id=creator.id,
        minutes=30,
        created_at=window_start + timedelta(hours=2),
    )
    db.add(labor)
    db.flush()

    result = labor_summary.crew_range_summaries(
        db, [tech.id], date(2026, 8, 17), date(2026, 8, 19), now=NOW
    )
    day17, day18, day19 = result[tech.id]
    assert day17.adjustment_minutes == 0
    assert day18.adjustment_minutes == 30
    assert day19.adjustment_minutes == 0
    assert day18.adjustments[0].minutes == 30


def test_crew_range_summaries_empty_technician_list_returns_empty_dict(db):
    assert labor_summary.crew_range_summaries(db, [], date(2026, 8, 17), date(2026, 8, 18), now=NOW) == {}


def test_crew_range_summaries_matches_day_summary_for_one_day(db):
    # Cross-check: the batched range query must agree with the existing
    # one-day-at-a-time day_summary for the same technician and day.
    tech = _seed_user(db)
    creator = _seed_user(db, first_name="Sam", last_name="Creator")
    wo_row = _seed_work_order(db, created_by=creator, assigned_to=tech)
    started = NOW - timedelta(hours=3)
    ended = NOW - timedelta(hours=1)
    _seed_session(db, wo_row, tech, started_at=started, ended_at=ended)

    today = labor_day.central_date_of(NOW)
    single = labor_summary.day_summary(db, tech.id, today, now=NOW)
    ranged = labor_summary.crew_range_summaries(db, [tech.id], today, today, now=NOW)[tech.id][0]

    assert ranged.closed_minutes == single.closed_minutes
    assert ranged.running_minutes == single.running_minutes
    assert ranged.adjustment_minutes == single.adjustment_minutes
    assert ranged.total_minutes == single.total_minutes
```

Check the top of `backend/tests/test_labor_summary.py` for its existing `NOW` constant, `_seed_user`/`_seed_work_order`/`_seed_session` helper signatures, and import block before pasting — mirror them exactly rather than assuming; if any helper is named or shaped differently than `test_hub_service.py`'s (both files independently define similar helpers), match the local file's own versions.

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_labor_summary.py -k crew_range_summaries -v`
Expected: FAIL with `AttributeError: module 'app.services.labor_summary' has no attribute 'crew_range_summaries'`

- [ ] **Step 3: Implement**

```python
# backend/app/services/labor_summary.py — add to the import block at the top
from dataclasses import dataclass, field, replace
from datetime import timedelta

from app.domain import list_limits
from app.services import _list_cap
```

(`dataclass`/`field` are already imported; add `replace` to that existing line. `date`/`datetime` are already imported; add `timedelta` to that existing line rather than duplicating the import statement.)

```python
# backend/app/services/labor_summary.py — append after crew_day_summaries (~line 270)

def crew_range_summaries(
    db: Session,
    technician_ids: list[uuid.UUID],
    start_day: date,
    end_day: date,
    *,
    now: datetime,
) -> dict[uuid.UUID, list[DaySummary]]:
    """One `DaySummary` per (technician, day) across `[start_day, end_day]`
    inclusive, for every id in `technician_ids` -- the timesheet grid's data
    source.

    Two range-spanning queries (sessions, adjustments) rather than
    `day_summary`'s one query per day: a 92-day range across a few dozen
    technicians would otherwise issue thousands of queries. Each fetched row
    is distributed across the days it overlaps using `labor_day.split_by_day`
    -- the same arithmetic `day_summary` uses for one day, applied once per
    row instead of once per (row, day) pair reconstructed from scratch.

    Every requested day is present in the result for every technician, zero
    or not -- the grid has no missing cells. Verified against `day_summary`
    directly (see `test_crew_range_summaries_matches_day_summary_for_one_day`):
    for a single day the two functions must agree exactly.
    """
    if not technician_ids:
        return {}

    window_start, _ = labor_day.day_bounds(start_day)
    _, window_end = labor_day.day_bounds(end_day)

    day_range = [start_day + timedelta(days=n) for n in range((end_day - start_day).days + 1)]
    buckets: dict[uuid.UUID, dict[date, DaySummary]] = {
        tid: {day: DaySummary(day=day) for day in day_range} for tid in technician_ids
    }

    sessions = _list_cap.capped(
        db.query(WorkOrderLaborSession)
        .options(joinedload(WorkOrderLaborSession.work_order))
        .filter(
            WorkOrderLaborSession.technician_id.in_(technician_ids),
            WorkOrderLaborSession.started_at < window_end,
            or_(
                WorkOrderLaborSession.ended_at.is_(None),
                WorkOrderLaborSession.ended_at > window_start,
            ),
        )
        .order_by(WorkOrderLaborSession.started_at)
        .limit(list_limits.fetch_limit())
        .all(),
        what="hub_timesheet_sessions",
    )

    for session in sessions:
        technician_bucket = buckets.get(session.technician_id)
        if technician_bucket is None:
            continue
        number = session.work_order.number if session.work_order else ""
        is_running = session.ended_at is None
        for day, minutes in labor_day.split_by_day(session.started_at, session.ended_at, now=now):
            summary = technician_bucket.get(day)
            if summary is None:
                continue
            entry = TimelineEntry(
                work_order_id=session.work_order_id,
                number=number,
                started_at=labor_day.as_utc(session.started_at),
                ended_at=None if is_running else labor_day.as_utc(session.ended_at),
                auto_closed=session.auto_closed_at is not None,
                minutes=minutes,
            )
            running = summary.running
            if is_running:
                running = RunningSession(
                    work_order_id=session.work_order_id,
                    number=number,
                    started_at=labor_day.as_utc(session.started_at),
                    day_counting_from=max(
                        labor_day.as_utc(session.started_at), labor_day.day_bounds(day)[0]
                    ),
                )
            technician_bucket[day] = replace(
                summary,
                closed_minutes=summary.closed_minutes + (0 if is_running else minutes),
                running_minutes=summary.running_minutes + (minutes if is_running else 0),
                running=running,
                timeline=[*summary.timeline, entry],
            )

    adjustments = _list_cap.capped(
        db.query(WorkOrderLabor, WorkOrder.number, User)
        .join(WorkOrder, WorkOrder.id == WorkOrderLabor.work_order_id)
        .outerjoin(WorkOrderLaborSession, WorkOrderLaborSession.labor_id == WorkOrderLabor.id)
        .outerjoin(User, User.id == WorkOrderLabor.recorded_by_id)
        .filter(
            WorkOrderLabor.technician_id.in_(technician_ids),
            WorkOrderLaborSession.id.is_(None),
            WorkOrderLabor.created_at >= window_start,
            WorkOrderLabor.created_at < window_end,
        )
        .order_by(WorkOrderLabor.created_at)
        .limit(list_limits.fetch_limit())
        .all(),
        what="hub_timesheet_adjustments",
    )

    for entry, number, recorded_by in adjustments:
        day = labor_day.central_date_of(entry.created_at)
        technician_bucket = buckets.get(entry.technician_id)
        if technician_bucket is None or day not in technician_bucket:
            continue
        summary = technician_bucket[day]
        adjustment = Adjustment(
            minutes=entry.minutes,
            recorded_by_name=(
                recorded_by.full_name if recorded_by is not None else "Name unavailable"
            ),
            work_order_number=number,
        )
        technician_bucket[day] = replace(
            summary,
            adjustment_minutes=summary.adjustment_minutes + entry.minutes,
            adjustments=[*summary.adjustments, adjustment],
        )

    return {tid: [buckets[tid][day] for day in day_range] for tid in technician_ids}
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && python -m pytest tests/test_labor_summary.py -v`
Expected: PASS, all tests including the six new ones and every pre-existing one in the file.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/labor_summary.py backend/tests/test_labor_summary.py
git commit -m "feat(user-hub): add crew_range_summaries for the timesheet grid"
```

---

### Task 5: Extract crew-derivation helpers from `crew_hub` (refactor)

Pure refactor — no behavior change. Pulls the "who is my crew" query and derivation out of `crew_hub` into two small functions so `timesheets_hub` (Task 6) can reuse the exact same D6 membership logic instead of a second, potentially-drifting copy.

**Files:**
- Modify: `backend/app/services/hub.py` (`crew_hub`, ~line 308-343)
- Test: `backend/tests/test_hub_service.py` (no new tests — this step is verified by the existing `crew_hub` test suite passing unchanged)

**Interfaces:**
- Produces: `hub_service._led_work_orders(db, supervisor_id: uuid.UUID) -> list[WorkOrder]`; `hub_service._crew_ids_from(led_work_orders: list[WorkOrder], supervisor_id: uuid.UUID) -> set[uuid.UUID]`.
- Consumes (Task 6): both of the above.

- [ ] **Step 1: Read the current `crew_hub` body**

Read `backend/app/services/hub.py:308-368` (already captured above during planning) to confirm the exact lines to extract before editing.

- [ ] **Step 2: Extract the two helpers**

```python
# backend/app/services/hub.py — insert immediately before crew_hub (~line 308)

def _led_work_orders(db: Session, supervisor_id: uuid.UUID) -> list[WorkOrder]:
    """Every live work order this person leads -- the query half of D6's
    crew derivation, split out so `timesheets_hub` (P3b) can reuse it
    without a second copy of the same filter."""
    return (
        db.query(WorkOrder)
        .options(joinedload(WorkOrder.technicians))
        .filter(WorkOrder.archived_at.is_(None), WorkOrder.supervisor_id == supervisor_id)
        .all()
    )


def _crew_ids_from(led_work_orders: list[WorkOrder], supervisor_id: uuid.UUID) -> set[uuid.UUID]:
    """Distinct technicians across `led_work_orders`, both through the
    plural `work_order_technicians` table and the legacy singular
    `assigned_to_id` column -- the pure half of D6's crew derivation, with
    the supervisor's own id always excluded (D13)."""
    crew_ids: set[uuid.UUID] = set()
    for w in led_work_orders:
        for tech in w.technicians:
            crew_ids.add(tech.id)
        if w.assigned_to_id:
            crew_ids.add(w.assigned_to_id)
    crew_ids.discard(supervisor_id)
    return crew_ids
```

- [ ] **Step 3: Replace `crew_hub`'s inline derivation with the extracted calls**

In `crew_hub`, replace:

```python
    led_work_orders = (
        db.query(WorkOrder)
        .options(joinedload(WorkOrder.technicians))
        .filter(WorkOrder.archived_at.is_(None), WorkOrder.supervisor_id == user.id)
        .all()
    )
    led = LedCounts(
```

with:

```python
    led_work_orders = _led_work_orders(db, user.id)
    led = LedCounts(
```

and replace:

```python
    crew_ids: set[uuid.UUID] = set()
    for w in led_work_orders:
        for tech in w.technicians:
            crew_ids.add(tech.id)
        if w.assigned_to_id:
            crew_ids.add(w.assigned_to_id)
    crew_ids.discard(user.id)
```

with:

```python
    crew_ids = _crew_ids_from(led_work_orders, user.id)
```

- [ ] **Step 4: Run the full existing hub test suite to confirm no regression**

Run: `cd backend && python -m pytest tests/test_hub_service.py tests/test_hub_flags.py -v`
Expected: PASS, every test unchanged — this refactor must not alter `crew_hub`'s output for any existing test.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/hub.py
git commit -m "refactor(user-hub): extract crew-derivation helpers for reuse by timesheets"
```

---

### Task 6: `timesheets_hub` — the composed payload

**Files:**
- Modify: `backend/app/services/hub.py` (imports; new dataclasses and function, appended after `crew_hub`)
- Test: `backend/tests/test_hub_service.py`

**Interfaces:**
- Consumes: `_led_work_orders`, `_crew_ids_from` (Task 5), `labor_summary.crew_range_summaries` (Task 4), `hub_domain.FLAG_RUNNING` (Task 3), `hub_domain.is_assigned_idle`/`FLAG_ASSIGNED_IDLE` (existing), `TimesheetRangeInvalidError`/`TimesheetRangeTooLargeError` (Task 2), `work_orders_service.sweep_stale_sessions` (existing), `_assigned_work_orders`/`_assigned_counts` (existing, already private to this module).
- Produces: `hub_service.MAX_TIMESHEET_RANGE_DAYS = 92`; dataclasses `TimesheetDay`, `TimesheetRow`, `TimesheetDayTotal`, `TimesheetRange`, `HubTimesheetPayload`; `hub_service.timesheets_hub(db, user, *, start: date, end: date, user_id: Optional[uuid.UUID] = None, now: Optional[datetime] = None) -> HubTimesheetPayload`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_hub_service.py — append. NOW is this file's existing
# module-level constant (already used by the crew_hub tests above); reuse
# it rather than redefining. Import the two new error types at the top of
# the file alongside the existing `from app.domain import ...` lines:
#   from app.domain.errors import TimesheetRangeInvalidError, TimesheetRangeTooLargeError

def test_timesheets_hub_rows_scoped_to_routed_crew(db):
    supervisor = _seed_user(db, role=roles.ROLE_SUPERVISOR, first_name="Sam", last_name="Boss")
    crew_tech = _seed_user(db, first_name="Ana", last_name="Crew")
    other_tech = _seed_user(db, first_name="Not", last_name="Mine")
    _seed_work_order(db, created_by=supervisor, assigned_to=crew_tech, supervisor=supervisor)
    _seed_work_order(db, created_by=supervisor, assigned_to=other_tech)  # unrouted to this supervisor

    payload = hub_service.timesheets_hub(
        db, supervisor, start=date(2026, 8, 17), end=date(2026, 8, 17), now=NOW
    )

    assert [row.user.id for row in payload.rows] == [crew_tech.id]


def test_timesheets_hub_excludes_supervisors_own_row(db):
    supervisor = _seed_user(db, role=roles.ROLE_SUPERVISOR)
    crew_tech = _seed_user(db)
    _seed_work_order(db, created_by=supervisor, assigned_to=crew_tech, supervisor=supervisor)

    payload = hub_service.timesheets_hub(
        db, supervisor, start=date(2026, 8, 17), end=date(2026, 8, 17), now=NOW
    )

    assert supervisor.id not in [row.user.id for row in payload.rows]


def test_timesheets_hub_cell_and_row_totals_include_adjustments(db):
    supervisor = _seed_user(db, role=roles.ROLE_SUPERVISOR)
    tech = _seed_user(db)
    wo_row = _seed_work_order(db, created_by=supervisor, assigned_to=tech, supervisor=supervisor)
    day = date(2026, 8, 17)
    window_start, _ = labor_day.day_bounds(day)
    _seed_session(
        db, wo_row, tech,
        started_at=window_start + timedelta(hours=1),
        ended_at=window_start + timedelta(hours=2),
    )
    from app.models import WorkOrderLabor
    db.add(WorkOrderLabor(
        id=uuid.uuid4(), work_order_id=wo_row.id, technician_id=tech.id,
        recorded_by_id=supervisor.id, minutes=30, created_at=window_start + timedelta(hours=3),
    ))
    db.flush()

    payload = hub_service.timesheets_hub(db, supervisor, start=day, end=day, now=NOW)

    row = payload.rows[0]
    assert row.days[0].tracked_minutes == 60
    assert row.days[0].adjustment_minutes == 30
    assert row.days[0].total_minutes == 90
    assert row.total_minutes == 90


def test_timesheets_hub_crew_totals_by_day_sums_across_rows(db):
    supervisor = _seed_user(db, role=roles.ROLE_SUPERVISOR)
    tech_a = _seed_user(db, first_name="A")
    tech_b = _seed_user(db, first_name="B")
    day = date(2026, 8, 17)
    window_start, _ = labor_day.day_bounds(day)
    wo_a = _seed_work_order(db, created_by=supervisor, assigned_to=tech_a, supervisor=supervisor)
    wo_b = _seed_work_order(db, created_by=supervisor, assigned_to=tech_b, supervisor=supervisor)
    _seed_session(db, wo_a, tech_a, started_at=window_start, ended_at=window_start + timedelta(minutes=30))
    _seed_session(db, wo_b, tech_b, started_at=window_start, ended_at=window_start + timedelta(minutes=45))

    payload = hub_service.timesheets_hub(db, supervisor, start=day, end=day, now=NOW)

    assert payload.crew_totals_by_day[0].minutes == 75


def test_timesheets_hub_user_id_filter_narrows_to_one_technician(db):
    supervisor = _seed_user(db, role=roles.ROLE_SUPERVISOR)
    tech_a = _seed_user(db, first_name="A")
    tech_b = _seed_user(db, first_name="B")
    _seed_work_order(db, created_by=supervisor, assigned_to=tech_a, supervisor=supervisor)
    _seed_work_order(db, created_by=supervisor, assigned_to=tech_b, supervisor=supervisor)

    payload = hub_service.timesheets_hub(
        db, supervisor, start=date(2026, 8, 17), end=date(2026, 8, 17), user_id=tech_a.id, now=NOW
    )

    assert [row.user.id for row in payload.rows] == [tech_a.id]


def test_timesheets_hub_user_id_outside_crew_yields_empty_rows(db):
    supervisor = _seed_user(db, role=roles.ROLE_SUPERVISOR)
    tech = _seed_user(db)
    _seed_work_order(db, created_by=supervisor, assigned_to=tech, supervisor=supervisor)
    stranger = _seed_user(db)

    payload = hub_service.timesheets_hub(
        db, supervisor, start=date(2026, 8, 17), end=date(2026, 8, 17), user_id=stranger.id, now=NOW
    )

    assert payload.rows == []


def test_timesheets_hub_end_before_start_raises(db):
    supervisor = _seed_user(db, role=roles.ROLE_SUPERVISOR)
    with pytest.raises(TimesheetRangeInvalidError):
        hub_service.timesheets_hub(
            db, supervisor, start=date(2026, 8, 20), end=date(2026, 8, 17), now=NOW
        )


def test_timesheets_hub_range_over_92_days_raises(db):
    supervisor = _seed_user(db, role=roles.ROLE_SUPERVISOR)
    with pytest.raises(TimesheetRangeTooLargeError) as excinfo:
        hub_service.timesheets_hub(
            db, supervisor, start=date(2026, 1, 1), end=date(2026, 4, 15), now=NOW  # 105 days
        )
    assert excinfo.value.max_days == 92


def test_timesheets_hub_running_session_flags_running(db):
    supervisor = _seed_user(db, role=roles.ROLE_SUPERVISOR)
    tech = _seed_user(db)
    wo_row = _seed_work_order(db, created_by=supervisor, assigned_to=tech, supervisor=supervisor)
    _seed_session(db, wo_row, tech, started_at=NOW - timedelta(hours=1), ended_at=None)

    today = labor_day.central_date_of(NOW)
    payload = hub_service.timesheets_hub(db, supervisor, start=today, end=today, now=NOW)

    assert hub_domain.FLAG_RUNNING in payload.rows[0].days[0].flags


def test_timesheets_hub_sweeps_crew_before_reading(db):
    # A session started 20 hours ago with no stop must be swept (auto-closed
    # at the 12h cap) before the range is read -- otherwise the day would
    # show an inflated, uncapped running total instead of the swept estimate.
    supervisor = _seed_user(db, role=roles.ROLE_SUPERVISOR)
    tech = _seed_user(db)
    wo_row = _seed_work_order(db, created_by=supervisor, assigned_to=tech, supervisor=supervisor)
    started = NOW - timedelta(hours=20)
    _seed_session(db, wo_row, tech, started_at=started, ended_at=None)

    today = labor_day.central_date_of(NOW)
    payload = hub_service.timesheets_hub(db, supervisor, start=today, end=today, now=NOW)

    row = payload.rows[0]
    assert row.days[0].tracked_minutes <= 720  # capped, not the ~1200 minutes an unswept session would show
```

Before pasting, read `backend/tests/test_hub_service.py`'s current end-of-file state to confirm the exact `NOW` constant value and the `_seed_session`/`_seed_work_order` signatures still match what's used above (they were captured during planning from this same file).

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_hub_service.py -k timesheets_hub -v`
Expected: FAIL with `AttributeError: module 'app.services.hub' has no attribute 'timesheets_hub'`

- [ ] **Step 3: Implement**

```python
# backend/app/services/hub.py — add to the imports at the top
from app.domain.errors import TimesheetRangeInvalidError, TimesheetRangeTooLargeError
```

```python
# backend/app/services/hub.py — append after crew_hub and its dataclasses

# --- the timesheet payload (P3b) ---------------------------------------------

MAX_TIMESHEET_RANGE_DAYS = 92


@dataclass(frozen=True)
class TimesheetDay:
    """One grid cell: a technician's tracked and adjustment minutes for one
    day, plus the raw sessions/adjustments a click expands -- the exact
    `DaySummary` shape `crew_range_summaries` already produces, reshaped
    with the two fields the grid needs that `DaySummary` doesn't carry
    (`flags`, and `tracked_minutes` collapsing closed+running into one
    number the way the grid displays it)."""

    date: date
    tracked_minutes: int
    adjustment_minutes: int
    flags: list[str] = field(default_factory=list)
    sessions: list[labor_summary.TimelineEntry] = field(default_factory=list)
    adjustments: list[labor_summary.Adjustment] = field(default_factory=list)

    @property
    def total_minutes(self) -> int:
        """D15: tracked plus adjustments, the one number the grid shows;
        the split is one click away, never a different total."""
        return self.tracked_minutes + self.adjustment_minutes


@dataclass(frozen=True)
class TimesheetRow:
    user: User
    days: list[TimesheetDay] = field(default_factory=list)
    total_minutes: int = 0


@dataclass(frozen=True)
class TimesheetDayTotal:
    date: date
    minutes: int


@dataclass(frozen=True)
class TimesheetRange:
    start: date
    end: date


@dataclass(frozen=True)
class HubTimesheetPayload:
    range: TimesheetRange
    rows: list[TimesheetRow] = field(default_factory=list)
    crew_totals_by_day: list[TimesheetDayTotal] = field(default_factory=list)


def timesheets_hub(
    db: Session,
    user: User,
    *,
    start: date,
    end: date,
    user_id: Optional[uuid.UUID] = None,
    now: Optional[datetime] = None,
) -> HubTimesheetPayload:
    """The `GET /hub/timesheets` payload: this supervisor's crew, one row
    per technician, one cell per day in `[start, end]`.

    **P3b scopes every caller to their own routed crew** (D6) -- the same
    membership `crew_hub` derives, via the shared `_led_work_orders` /
    `_crew_ids_from` helpers, regardless of the caller's rank. Spec §12
    assigns widening TechFM OA+ to "everyone" to P4 as a service-layer
    change; the `supervisor+` gate this endpoint carries (§4.1) is
    unchanged by that later widening, so this function does not branch on
    role yet -- doing so now would ship an unreviewed guess at what
    "everyone" means.

    `user_id`, when given, narrows `rows` to that one technician --
    silently to zero rows if they are outside the caller's crew, rather
    than a 404 or 403: the id could be a stale link from before a routing
    change moved someone out, and an empty result is the honest,
    non-revealing answer either way.

    **Not side-effect-free**, for the same reason `/hub/crew` is not
    (spec §3.5 is silent on `/hub/crew` and this endpoint too): a stale
    running session inside the requested range would otherwise show an
    inflated, uncapped running-minutes figure instead of the swept,
    auto-closed estimate. Each technician in scope is swept individually
    before the range is read.

    Raises `TimesheetRangeInvalidError` if `end < start`, or
    `TimesheetRangeTooLargeError` if the inclusive range exceeds
    `MAX_TIMESHEET_RANGE_DAYS` (spec §7).
    """
    if end < start:
        raise TimesheetRangeInvalidError()
    if (end - start).days + 1 > MAX_TIMESHEET_RANGE_DAYS:
        raise TimesheetRangeTooLargeError(MAX_TIMESHEET_RANGE_DAYS)

    now = now or datetime.now(timezone.utc)

    led_work_orders = _led_work_orders(db, user.id)
    crew_ids = _crew_ids_from(led_work_orders, user.id)
    if user_id is not None:
        crew_ids = crew_ids & {user_id}

    for technician_id in crew_ids:
        work_orders_service.sweep_stale_sessions(db, technician_id=technician_id)

    range_summaries = labor_summary.crew_range_summaries(db, list(crew_ids), start, end, now=now)
    crew_users = (
        {u.id: u for u in db.query(User).filter(User.id.in_(crew_ids)).all()} if crew_ids else {}
    )

    rows: list[TimesheetRow] = []
    day_totals: dict[date, int] = {}
    for technician_id in sorted(crew_ids, key=lambda tid: crew_users[tid].full_name):
        assigned_count = _assigned_counts(_assigned_work_orders(db, technician_id)).assigned
        days: list[TimesheetDay] = []
        for summary in range_summaries[technician_id]:
            flags: list[str] = []
            if summary.running is not None:
                flags.append(hub_domain.FLAG_RUNNING)
            if hub_domain.is_assigned_idle(
                assigned_count=assigned_count, minutes_today=summary.total_minutes, now=now
            ):
                flags.append(hub_domain.FLAG_ASSIGNED_IDLE)
            day = TimesheetDay(
                date=summary.day,
                tracked_minutes=summary.closed_minutes + summary.running_minutes,
                adjustment_minutes=summary.adjustment_minutes,
                flags=flags,
                sessions=summary.timeline,
                adjustments=summary.adjustments,
            )
            days.append(day)
            day_totals[day.date] = day_totals.get(day.date, 0) + day.total_minutes
        rows.append(
            TimesheetRow(
                user=crew_users[technician_id],
                days=days,
                total_minutes=sum(day.total_minutes for day in days),
            )
        )

    day_range = [start + timedelta(days=n) for n in range((end - start).days + 1)]
    return HubTimesheetPayload(
        range=TimesheetRange(start=start, end=end),
        rows=rows,
        crew_totals_by_day=[
            TimesheetDayTotal(date=d, minutes=day_totals.get(d, 0)) for d in day_range
        ],
    )
```

(`field`, `timedelta` are already imported at the top of `services/hub.py` per Task 4's edit to the neighboring file — confirm `services/hub.py`'s own import block separately; it currently imports `field` from `dataclasses` already for `CrewTechnician`/`AttentionItem`, but `timedelta` needs adding to its existing `from datetime import date, datetime, timezone` line.)

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && python -m pytest tests/test_hub_service.py -v`
Expected: PASS, all tests including the ten new ones and every pre-existing one in the file.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/hub.py backend/tests/test_hub_service.py
git commit -m "feat(user-hub): compose the timesheets payload"
```

---

### Task 7: `timesheet_csv` — CSV serialization

**Files:**
- Modify: `backend/app/services/hub.py` (imports; new function appended after `timesheets_hub`)
- Test: `backend/tests/test_hub_service.py`

**Interfaces:**
- Consumes: `HubTimesheetPayload` (Task 6).
- Produces: `hub_service.timesheet_csv(payload: HubTimesheetPayload) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_hub_service.py — append

def test_timesheet_csv_formats_minutes_as_h_mm_and_includes_crew_total(db):
    supervisor = _seed_user(db, role=roles.ROLE_SUPERVISOR)
    tech = _seed_user(db, first_name="Jordan", last_name="Rivera")
    wo_row = _seed_work_order(db, created_by=supervisor, assigned_to=tech, supervisor=supervisor)
    day = date(2026, 8, 17)
    window_start, _ = labor_day.day_bounds(day)
    _seed_session(
        db, wo_row, tech,
        started_at=window_start + timedelta(hours=1),
        ended_at=window_start + timedelta(hours=1, minutes=5) + timedelta(hours=6),
    )

    payload = hub_service.timesheets_hub(db, supervisor, start=day, end=day, now=NOW)
    body = hub_service.timesheet_csv(payload)

    lines = body.strip("\r\n").split("\r\n")
    assert lines[0] == "Technician,2026-08-17,Total"
    assert lines[1].startswith("Jordan Rivera,")
    assert lines[1].endswith(",7:05")  # 6h05m matches the seeded session length
    assert lines[2].startswith("Crew total,")
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_hub_service.py -k timesheet_csv -v`
Expected: FAIL with `AttributeError: module 'app.services.hub' has no attribute 'timesheet_csv'`

- [ ] **Step 3: Implement**

```python
# backend/app/services/hub.py — add to the imports at the top
import csv
import io
```

```python
# backend/app/services/hub.py — append after timesheets_hub

def _format_hm(total_minutes: int) -> str:
    """`H:MM`, matching spec §5.4's grid mockup literally (`7:05`, `21:35`)
    -- this file goes to a bookkeeper, not a technician's phone, so it does
    not use the `H h MM m` wording the hub's tiles use elsewhere."""
    minutes = max(0, round(total_minutes))
    hours, mins = divmod(minutes, 60)
    return f"{hours}:{mins:02d}"


def timesheet_csv(payload: HubTimesheetPayload) -> str:
    """The timesheet grid as CSV text: one row per technician, one column
    per date in `payload`, a `Total` column, and a trailing `Crew total`
    row -- the same numbers the grid just displayed, since both are built
    from the same `HubTimesheetPayload`.

    `\\r\\n` line endings and a header row, matching
    `services.work_orders.export_work_orders_csv`'s existing convention.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    dates = [total.date for total in payload.crew_totals_by_day]
    writer.writerow(["Technician", *(d.isoformat() for d in dates), "Total"])
    for row in payload.rows:
        by_date = {day.date: day for day in row.days}
        writer.writerow(
            [
                row.user.full_name,
                *(_format_hm(by_date[d].total_minutes) for d in dates),
                _format_hm(row.total_minutes),
            ]
        )
    writer.writerow(
        [
            "Crew total",
            *(_format_hm(total.minutes) for total in payload.crew_totals_by_day),
            _format_hm(sum(total.minutes for total in payload.crew_totals_by_day)),
        ]
    )
    return buffer.getvalue()
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && python -m pytest tests/test_hub_service.py -v`
Expected: PASS, all tests.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/hub.py backend/tests/test_hub_service.py
git commit -m "feat(user-hub): serialize the timesheets payload as CSV"
```

---

### Task 8: Response schemas

**Files:**
- Modify: `backend/app/schemas/hub.py` (append after `HubCrewResponse`, end of file)

**Interfaces:**
- Consumes: `HubUser`, `HubTimelineEntry`, `HubAdjustment` (existing, this file).
- Produces: `HubTimesheetRange`, `HubTimesheetDay`, `HubTimesheetRow`, `HubTimesheetDayTotal`, `HubTimesheetResponse`.

- [ ] **Step 1: Add the schemas**

```python
# backend/app/schemas/hub.py — append at end of file

# --- GET /hub/timesheets (P3b) ----------------------------------------------


class HubTimesheetRange(BaseModel):
    start: date
    end: date

    model_config = {"from_attributes": True}


class HubTimesheetDay(BaseModel):
    """One grid cell. `sessions`/`adjustments` are the drill-down detail a
    click expands -- reusing `HubTimelineEntry`/`HubAdjustment` as-is, since
    a timesheet day and a personal-hub day describe the same underlying
    rows."""

    date: date
    tracked_minutes: int
    adjustment_minutes: int
    flags: list[str] = []
    sessions: list[HubTimelineEntry] = []
    adjustments: list[HubAdjustment] = []

    @computed_field
    @property
    def total_minutes(self) -> int:
        """D15: tracked plus adjustments, the one number the cell shows."""
        return self.tracked_minutes + self.adjustment_minutes

    model_config = {"from_attributes": True}


class HubTimesheetRow(BaseModel):
    user: HubUser
    days: list[HubTimesheetDay] = []
    total_minutes: int

    model_config = {"from_attributes": True}


class HubTimesheetDayTotal(BaseModel):
    date: date
    minutes: int

    model_config = {"from_attributes": True}


class HubTimesheetResponse(BaseModel):
    """`GET /hub/timesheets`. P3b scopes every caller to their own routed
    crew (D6); widening TechFM OA+ to see everyone is P4 (spec §12)."""

    range: HubTimesheetRange
    rows: list[HubTimesheetRow] = []
    crew_totals_by_day: list[HubTimesheetDayTotal] = []

    model_config = {"from_attributes": True}
```

- [ ] **Step 2: Verify the module imports and validates against the service payload**

Run:
```
cd backend && python -c "
from datetime import date
from app.schemas.hub import HubTimesheetResponse
from app.services.hub import HubTimesheetPayload, TimesheetRange
p = HubTimesheetPayload(range=TimesheetRange(start=date(2026,8,17), end=date(2026,8,17)))
r = HubTimesheetResponse.model_validate(p)
print(r.model_dump())
"
```
Expected: prints a dict with `range`, `rows: []`, `crew_totals_by_day: []` — no traceback.

- [ ] **Step 3: Commit**

```bash
git add backend/app/schemas/hub.py
git commit -m "feat(user-hub): add the timesheet response schemas"
```

---

### Task 9: Router — `GET /hub/timesheets` and `GET /hub/timesheets/export`

**Files:**
- Modify: `backend/app/routers/hub.py`
- Test: create `backend/tests/test_hub_router.py` if no router-level test file for `hub.py` already exists (check first — `test_hub_service.py`/`test_hub_flags.py` are service/domain level); otherwise append. Grep for an existing FastAPI `TestClient` test hitting `/hub/crew` before assuming one doesn't exist — P3a may have added one.

**Interfaces:**
- Consumes: `hub_service.timesheets_hub`, `hub_service.timesheet_csv` (Task 6/7), `HubTimesheetResponse` (Task 8), `labor_day.week_bounds_containing` (Task 1), `labor_day.central_date_of` (existing), `to_http`, `DomainError` (existing pattern from `routers/work_orders.py`).
- Produces: `GET /hub/timesheets` (JSON, `supervisor+`), `GET /hub/timesheets/export` (CSV, `supervisor+`).

- [ ] **Step 1: Check for an existing hub router test file**

Run: `cd backend && find tests -iname "*hub*router*" -o -iname "*test_hub_api*"`

If nothing is found, this task creates `backend/tests/test_hub_router.py` fresh. If something is found, read it and append there instead, matching its existing `TestClient`/fixture setup and any `_seed_*` helpers it already defines (do not redefine helpers that already exist in that file).

- [ ] **Step 2: Write the failing tests**

```python
# backend/tests/test_hub_router.py — write following the pattern of
# whatever existing router test file this app uses for authenticated
# requests (search for `TestClient` and `Depends(get_current_user)`
# overrides in the existing test suite, e.g. tests covering
# /work-orders/export, and mirror its login/auth fixture exactly rather
# than inventing a new one).

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, timedelta

import pytest


def test_get_hub_timesheets_defaults_to_current_central_week(client, supervisor_headers):
    response = client.get("/hub/timesheets", headers=supervisor_headers)
    assert response.status_code == 200
    body = response.json()
    assert "range" in body and "start" in body["range"] and "end" in body["range"]


def test_get_hub_timesheets_rejects_technician(client, technician_headers):
    response = client.get("/hub/timesheets", headers=technician_headers)
    assert response.status_code == 403


def test_get_hub_timesheets_422_over_range_cap(client, supervisor_headers):
    response = client.get(
        "/hub/timesheets",
        params={"start": "2026-01-01", "end": "2026-04-15"},  # 105 days
        headers=supervisor_headers,
    )
    assert response.status_code == 422
    assert "92" in response.json()["detail"]


def test_get_hub_timesheets_export_returns_csv_with_content_disposition(client, supervisor_headers):
    response = client.get(
        "/hub/timesheets/export",
        params={"start": "2026-08-17", "end": "2026-08-17"},
        headers=supervisor_headers,
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "timesheet_2026-08-17_to_2026-08-17.csv" in response.headers["content-disposition"]


def test_get_hub_timesheets_export_names_the_technician_when_filtered(
    client, supervisor_headers, routed_technician
):
    response = client.get(
        "/hub/timesheets/export",
        params={"start": "2026-08-17", "end": "2026-08-17", "user_id": str(routed_technician.id)},
        headers=supervisor_headers,
    )
    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    assert "timesheet_2026-08-17_to_2026-08-17_" in disposition
```

**Before finalizing this file**, check `backend/tests/conftest.py` (or wherever fixtures live) for the actual names of a `client`/`TestClient` fixture and an authenticated-supervisor-request fixture — the `supervisor_headers`/`technician_headers`/`routed_technician` names above are illustrative of the *shape* needed, not confirmed fixture names in this codebase. Grep `backend/tests/` for how an existing `supervisor+`-gated endpoint (e.g. `/hub/crew`, or `/work-orders/export`) is exercised in a router-level test, and match that file's exact fixture and auth-override pattern instead of the placeholders above.

- [ ] **Step 3: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_hub_router.py -v`
Expected: FAIL — either `404 Not Found` (route doesn't exist yet) or a fixture error if the fixture names in Step 2 needed correcting against the real conftest (fix the fixture names first if so, then re-run to confirm the 404).

- [ ] **Step 4: Implement**

```python
# backend/app/routers/hub.py — replace the full docstring's route list and
# add imports/routes. First, update the module docstring's four-route list
# (~lines 8-11) to remove "-- later phase" from /hub/timesheets and mark it
# current, matching how P3a already updated /hub/crew's line in this same
# docstring.

import re
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.auth_deps import get_current_user, require_min_role
from app.database import get_db
from app.domain import labor_day, roles
from app.domain.errors import DomainError
from app.models import User
from app.routers._errors import to_http
from app.schemas.hub import HubClock, HubCrewResponse, HubResponse, HubTimesheetResponse
from app.services import hub as hub_service
```

(Merge these with the existing import block rather than duplicating lines already present — `APIRouter`, `Depends`, `Session`, `get_current_user`, `require_min_role`, `get_db`, `User`, `hub_service`, and the existing schema imports are already there; add only what's missing: `re`, `date`, `datetime`, `timezone`, `Optional`, `Query`, `Response`, `labor_day`, `DomainError`, `to_http`, `HubTimesheetResponse`.)

```python
# backend/app/routers/hub.py — append after get_hub_crew

def _default_range(now: datetime) -> tuple[date, date]:
    """The current Central calendar week (D12), matching what P4's
    `/hub/admin` billing default will also use -- `week_bounds_containing`
    is the shared primitive both defaults are built on."""
    return labor_day.week_bounds_containing(labor_day.central_date_of(now))


def _resolve_range(start: Optional[date], end: Optional[date], now: datetime) -> tuple[date, date]:
    """`start`/`end` default together, not independently -- a caller that
    supplies only one is treated the same as supplying neither, rather than
    guessing what the missing half should be."""
    if start is not None and end is not None:
        return start, end
    return _default_range(now)


def _filename_slug(value) -> str:
    """Short filesystem-safe token, matching
    `routers/work_orders.py::_filename_slug` -- duplicated rather than
    imported across routers, consistent with this app having no shared
    router-utility module for a two-line regex."""
    return re.sub(r"[^a-z0-9]+", "-", str(value).strip().casefold()).strip("-")[:24]


def _timesheet_filename(payload: hub_service.HubTimesheetPayload, *, technician: Optional[User]) -> str:
    """`timesheet_<start>_to_<end>[_<user>].csv` (D14) -- ISO dates so a
    folder of these sorts chronologically; the user suffix is the
    slugified full name of the one technician `user_id` narrowed to."""
    stamp = f"{payload.range.start.isoformat()}_to_{payload.range.end.isoformat()}"
    if technician is not None:
        return f"timesheet_{stamp}_{_filename_slug(technician.full_name)}.csv"
    return f"timesheet_{stamp}.csv"


@router.get("/timesheets", response_model=HubTimesheetResponse)
def get_hub_timesheets(
    start: Optional[date] = Query(None),
    end: Optional[date] = Query(None),
    user_id: Optional[uuid.UUID] = Query(None),
    user: User = Depends(require_min_role(roles.ROLE_SUPERVISOR)),
    db: Session = Depends(get_db),
):
    """The Timesheets tab: this supervisor's crew, one row per technician,
    one cell per day. `start`/`end` default together to the current
    Central week (D12); both are inclusive Central calendar dates.

    Gates at `supervisor+` and scopes every caller to their own routed
    crew (D17, this phase) -- widening TechFM OA+ to everyone is P4.
    """
    now = datetime.now(timezone.utc)
    range_start, range_end = _resolve_range(start, end, now)
    try:
        payload = hub_service.timesheets_hub(
            db, user, start=range_start, end=range_end, user_id=user_id, now=now
        )
    except DomainError as exc:
        raise to_http(exc)
    return HubTimesheetResponse.model_validate(payload)


@router.get("/timesheets/export")
def export_hub_timesheets(
    start: Optional[date] = Query(None),
    end: Optional[date] = Query(None),
    user_id: Optional[uuid.UUID] = Query(None),
    user: User = Depends(require_min_role(roles.ROLE_SUPERVISOR)),
    db: Session = Depends(get_db),
):
    """Download the Timesheets tab as CSV (D14). Same scope, gate, and
    range defaults as `GET /hub/timesheets`; calls the same composer so the
    downloaded numbers can never drift from what the grid just showed.

    Declared as a sibling route rather than a `?format=csv` flag on
    `GET /hub/timesheets`, mirroring the existing `/work-orders` +
    `/work-orders/export` convention -- a CSV response can't share a
    Pydantic `response_model` with the JSON route.
    """
    now = datetime.now(timezone.utc)
    range_start, range_end = _resolve_range(start, end, now)
    try:
        payload = hub_service.timesheets_hub(
            db, user, start=range_start, end=range_end, user_id=user_id, now=now
        )
    except DomainError as exc:
        raise to_http(exc)
    body = hub_service.timesheet_csv(payload)
    technician = next((row.user for row in payload.rows if user_id and row.user.id == user_id), None)
    filename = _timesheet_filename(payload, technician=technician)
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
```

Add `import uuid` to the top of the file alongside the other new imports if it is not already present (check first — `hub.py`'s existing imports may not include it since `get_hub_crew` takes no path/query params today).

- [ ] **Step 5: Run to verify pass**

Run: `cd backend && python -m pytest tests/test_hub_router.py tests/test_hub_service.py tests/test_hub_flags.py tests/test_labor_summary.py tests/test_labor_day.py -v`
Expected: PASS, all tests.

- [ ] **Step 6: Run the full backend test suite**

Run: `cd backend && python -m pytest -q`
Expected: PASS, no regressions anywhere else in the app.

- [ ] **Step 7: Commit**

```bash
git add backend/app/routers/hub.py backend/tests/test_hub_router.py
git commit -m "feat(user-hub): add GET /hub/timesheets and its CSV export"
```

---

### Task 10: Register in `docs/endpoint-map.md`

**Files:**
- Modify: `docs/endpoint-map.md` (endpoint table ~line 138-139; response schema section ~line 1147-1166)

- [ ] **Step 1: Add H3 and H4 rows to the endpoint table**

Read `docs/endpoint-map.md:138-144` first (captured during planning) to insert correctly — H1/H2 exist, H3/H4 continue the sequence per the footnote's own instruction ("H1 is the first User Hub row... P2 onward add H2, H3, ...").

```markdown
| H3 | GET | `/hub/timesheets` | supervisor+ | `hub.py` → `hub.timesheets_hub` → `work_orders.sweep_stale_sessions` (per crew member) + `labor_summary.crew_range_summaries` | work_order_labor_sessions (r/w on per-member sweep), work_order_labor (r; w on sweep), work_orders (r; row lock on sweep), work_order_technicians (r), users (r) | `apiGetHubTimesheets` | `userHub.js`, `hubTimesheets.js` |
| H4 | GET | `/hub/timesheets/export` | supervisor+ | `hub.py` → `hub.timesheets_hub` + `hub.timesheet_csv` | same as H3 (read-only beyond H3's sweep) | `apiExportHubTimesheets` | `hubTimesheets.js` |
```

Update the footnote (~line 141-144) to read `...P2 onward add H2, H3, H4, …` instead of stopping at `H2, ….`

- [ ] **Step 2: Add the response schema docs**

Append after `HubAttentionItem`'s entry (~line 1166, before the `---` / `## Error Catalog` heading):

```markdown
**`HubTimesheetResponse`** — `GET /hub/timesheets` (supervisor+, P3b scopes
to the caller's own routed crew; TechFM OA+ seeing everyone is P4): `range:
HubTimesheetRange`, `rows: list[HubTimesheetRow] = []`,
`crew_totals_by_day: list[HubTimesheetDayTotal] = []`.

**`HubTimesheetRange`**: `start: date`, `end: date` — inclusive Central
calendar dates, defaulting together to the current Central week (D12).

**`HubTimesheetRow`**: `user: HubUser`, `days: list[HubTimesheetDay] = []`,
`total_minutes: int`.

**`HubTimesheetDay`**: `date`, `tracked_minutes: int`,
`adjustment_minutes: int`, `flags: list[str] = []`,
`sessions: list[HubTimelineEntry] = []`, `adjustments: list[HubAdjustment]
= []`, plus computed `total_minutes` (D15: tracked + adjustments). `flags`
draws from the same `domain/hub.py` vocabulary as the crew board, plus
`running` (this phase) for a day with an open session.

**`HubTimesheetDayTotal`**: `date`, `minutes` — the crew's summed total for
one day, across every row.
```

- [ ] **Step 3: Commit**

```bash
git add docs/endpoint-map.md
git commit -m "docs(user-hub): register GET /hub/timesheets and its CSV export"
```

---

### Task 11: Update `docs/open-work.md`

**Files:**
- Modify: `docs/open-work.md` (~lines 103-109)

- [ ] **Step 1: Replace the P3b/P4 bullets**

Replace:

```markdown
- **P3b · Timesheets — next.** `GET /hub/timesheets`, the grid, per-cell
  drill-down, and CSV export, reusing P3a's crew-scope query. D17 moved this
  down from P4, making the split P3a/P3b the larger of the two remaining
  phases.
- **P4 · Admin hub.** `GET /hub/admin`, the four tile groups, the conditional
  crew board, and widening the timesheet row scope from "my crew" to
  everyone.
```

with:

```markdown
- **P3b · Timesheets — shipped.** `GET /hub/timesheets`, `GET
  /hub/timesheets/export`, the grid with per-cell session/adjustment
  drill-down, and CSV export (D14 filename convention). Reuses P3a's D6
  crew-scope derivation; scopes every caller (including TechFM OA+) to
  their own routed crew, not "everyone" — that widening is P4's job.
  Built on `user-hub-p3-crew`; not yet merged.
- **P4 · Admin hub — next.** `GET /hub/admin`, the four tile groups, the
  conditional crew board (D16), and widening `/hub/timesheets`'s row scope
  from "my crew" to "everyone" for TechFM OA+ and above — a service-layer
  change to `services.hub.timesheets_hub`, not a new surface.
```

- [ ] **Step 2: Commit**

```bash
git add docs/open-work.md
git commit -m "docs(user-hub): mark P3b timesheets shipped, P4 next"
```

---

### Task 12: `api.js` — frontend wrappers

**Files:**
- Modify: `backend/static/api.js` (after `apiGetHubCrew`, ~line 490)

**Interfaces:**
- Produces: `apiGetHubTimesheets({start, end, userId})`, `apiExportHubTimesheets({start, end, userId})`.

- [ ] **Step 1: Add the two wrappers**

```javascript
// backend/static/api.js — insert after apiGetHubCrew (~line 490)

export async function apiGetHubTimesheets({ start = null, end = null, userId = null } = {}) {
  const params = new URLSearchParams();
  if (start) params.set("start", start);
  if (end) params.set("end", end);
  if (userId) params.set("user_id", userId);
  const qs = params.toString();
  return liveGet(`/hub/timesheets${qs ? `?${qs}` : ""}`);
}

// Download the Timesheets tab as CSV. Mirrors apiExportWorkOrders's
// blob + server-filename pattern exactly.
export async function apiExportHubTimesheets({ start = null, end = null, userId = null } = {}) {
  const params = new URLSearchParams();
  if (start) params.set("start", start);
  if (end) params.set("end", end);
  if (userId) params.set("user_id", userId);
  const response = await fetch(`/hub/timesheets/export?${params}`, {
    credentials: "include",
    cache: "no-store",
  });
  if (!response.ok) return parseResponse(response); // always throws
  const disposition = response.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename="?([^"]+)"?/i);
  return {
    blob: await response.blob(),
    filename: match ? match[1] : "timesheet.csv",
  };
}
```

- [ ] **Step 2: Verify syntax**

Run: `cd backend && node --check static/api.js`
Expected: no output (exit 0).

- [ ] **Step 3: Commit**

```bash
git add backend/static/api.js
git commit -m "feat(user-hub): add timesheet API wrappers"
```

---

### Task 13: Tab shell markup and grid CSS

**Files:**
- Modify: `backend/static/pages/user-hub.html`
- Modify: `backend/static/styles.css`

- [ ] **Step 1: Add the tab button and panel**

```html
<!-- backend/static/pages/user-hub.html — replace the <nav id="hub-tabs">
     block and the tabpanel divs -->

        <nav id="hub-tabs" class="hub-tabs" aria-label="User hub sections">
            <button type="button" class="hub-tab active" id="hub-tab-dashboard" data-hub-tab="dashboard" aria-selected="true" role="tab">Dashboard</button>
            <button type="button" class="hub-tab hidden" id="hub-tab-timesheets" data-hub-tab="timesheets" aria-selected="false" role="tab" hidden>Timesheets</button>
            <button type="button" class="hub-tab" id="hub-tab-work-orders" data-hub-tab="work-orders" aria-selected="false" role="tab">My Work Orders</button>
        </nav>

        <div class="hub-tabpanel active" id="hub-tabpanel-dashboard" role="tabpanel"></div>
        <div class="hub-tabpanel" id="hub-tabpanel-timesheets" role="tabpanel" hidden></div>
        <div class="hub-tabpanel" id="hub-tabpanel-work-orders" role="tabpanel" hidden></div>
```

(The Timesheets tab button starts `hidden` — Task 15's `userHub.js` unhides it for `supervisor+` viewers after the first `GET /hub` fetch resolves, the same moment it currently decides whether to fetch `/hub/crew`. Placed between Dashboard and My Work Orders to match spec §5.3's tab order.)

- [ ] **Step 2: Add the grid CSS**

```css
/* backend/static/styles.css — append after the .hub-crew-flag block (~line 2020) */

.hub-timesheet-toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: .75rem;
    flex-wrap: wrap;
    margin-bottom: .75rem;
}

.hub-timesheet-week-nav {
    display: flex;
    align-items: center;
    gap: .5rem;
}

.hub-timesheet-table {
    width: 100%;
    border-collapse: collapse;
    font-variant-numeric: tabular-nums;
}

.hub-timesheet-table th,
.hub-timesheet-table td {
    padding: .4rem .6rem;
    text-align: right;
    border-bottom: 1px solid var(--panel-rule-soft);
}

.hub-timesheet-table th:first-child,
.hub-timesheet-table td:first-child {
    text-align: left;
}

.hub-timesheet-table thead th {
    border-bottom: 2px solid var(--panel-rule);
    font-weight: 600;
}

.hub-timesheet-table tbody tr:nth-child(even) {
    background-color: var(--panel-well);
}

.hub-timesheet-table tfoot td {
    border-top: 2px solid var(--panel-rule);
    font-weight: 600;
}

.hub-timesheet-cell {
    cursor: pointer;
    background: none;
    border: none;
    font: inherit;
    font-variant-numeric: tabular-nums;
    color: inherit;
    padding: 0;
}

.hub-timesheet-cell:hover,
.hub-timesheet-cell:focus-visible {
    text-decoration: underline;
}

.hub-timesheet-flag {
    margin-left: .2rem;
    font-size: .85em;
}

.hub-timesheet-drilldown {
    background: var(--panel-nested);
    padding: .75rem 1rem;
    margin: .5rem 0 1rem;
    border-radius: var(--radius, .5rem);
}

.hub-timesheet-drilldown-row {
    display: flex;
    justify-content: space-between;
    gap: 1rem;
    padding: .2rem 0;
    border-bottom: 1px solid var(--panel-rule-soft);
    font-variant-numeric: tabular-nums;
}

.hub-timesheet-drilldown-row:last-child {
    border-bottom: none;
    font-weight: 600;
}
```

- [ ] **Step 3: Verify syntax**

Run: `cd backend && python -c "import re; content = open('static/pages/user-hub.html', encoding='utf-8').read(); assert content.count('<nav') == content.count('</nav>')"`
Expected: no output (exit 0) — trivial balance check since HTML fragments have no linter in this repo.

- [ ] **Step 4: Commit**

```bash
git add backend/static/pages/user-hub.html backend/static/styles.css
git commit -m "feat(user-hub): style the timesheet tab and grid"
```

---

### Task 14: `hubTimesheets.js` — the grid view

**Files:**
- Create: `backend/static/views/hubTimesheets.js`

**Interfaces:**
- Consumes: `escapeHtml` (`../format.js`, existing), the payload shape from `apiGetHubTimesheets` (Task 12) matching `HubTimesheetResponse` (Task 8).
- Produces: `mountHubTimesheets(container, payload, { onWeekChange }) -> void` — renders the grid; `onWeekChange(startISO, endISO)` is called when the ◀/▶ nav is clicked, so `userHub.js` (Task 15) owns the actual refetch (matching the existing `hubClock.js`'s `{ onChanged }` callback convention already established in this codebase).

- [ ] **Step 1: Write the module**

```javascript
// backend/static/views/hubTimesheets.js
//
// View: the Supervisor hub's Timesheets tab (spec §5.3 Tab 2, §5.4's grid
// mockup -- the same component both tabs share). Renders whatever
// `GET /hub/timesheets` payload `userHub.js` last fetched; makes no
// requests of its own except the CSV export download, which reuses the
// exact params the grid is currently showing so the file always matches
// the screen.
//
// D15: every total shown here already includes adjustments -- the split
// is one click away (the drill-down), never a second number on the grid.

import { escapeHtml } from "../format.js";
import { apiExportHubTimesheets } from "../api.js";

function formatHm(totalMinutes) {
  const minutes = Math.max(0, Math.round(totalMinutes));
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return `${h}:${String(m).padStart(2, "0")}`;
}

function shortDateLabel(iso) {
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleDateString([], { weekday: "short", month: "numeric", day: "numeric" });
}

const FLAG_GLYPHS = {
  running: "●",
  assigned_idle: "⚠",
};

function flagGlyphs(flags) {
  if (!flags.length) return "";
  return flags
    .map((f) => `<span class="hub-timesheet-flag" title="${escapeHtml(f.replace(/_/g, " "))}">${FLAG_GLYPHS[f] || "⚠"}</span>`)
    .join("");
}

function drilldownHtml(day) {
  const sessionRows = day.sessions
    .map((s) => {
      const started = new Date(s.started_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
      const ended = s.ended_at
        ? new Date(s.ended_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
        : "(running)";
      const estimate = s.auto_closed ? " — estimate" : "";
      return `<div class="hub-timesheet-drilldown-row"><span>${started} – ${ended} · WO ${escapeHtml(s.number)}${estimate}</span><span>${formatHm(s.minutes)}</span></div>`;
    })
    .join("");
  const adjustmentRows = day.adjustments
    .map(
      (a) =>
        `<div class="hub-timesheet-drilldown-row"><span>Adjustment · WO ${escapeHtml(a.work_order_number)} by ${escapeHtml(a.recorded_by_name)}</span><span>${formatHm(a.minutes)}</span></div>`
    )
    .join("");
  const trackedRow = `<div class="hub-timesheet-drilldown-row"><span>Tracked</span><span>${formatHm(day.tracked_minutes)}</span></div>`;
  const totalRow = `<div class="hub-timesheet-drilldown-row"><span>Total</span><span>${formatHm(day.total_minutes)}</span></div>`;
  if (!day.sessions.length && !day.adjustments.length) {
    return `<div class="hub-timesheet-drilldown"><p class="hint">No tracked time.</p></div>`;
  }
  return `<div class="hub-timesheet-drilldown">${sessionRows}${trackedRow}${adjustmentRows ? adjustmentRows + totalRow : ""}</div>`;
}

export function mountHubTimesheets(container, payload, { onWeekChange } = {}) {
  const dates = payload.crew_totals_by_day.map((t) => t.date);
  let expanded = null; // { rowIndex, date } | null

  function render() {
    const headerCells = dates.map((d) => `<th>${escapeHtml(shortDateLabel(d))}</th>`).join("");
    const bodyRows = payload.rows
      .map((row, rowIndex) => {
        const cells = row.days
          .map((day) => {
            const isExpanded = expanded && expanded.rowIndex === rowIndex && expanded.date === day.date;
            return `<td><button type="button" class="hub-timesheet-cell" data-row="${rowIndex}" data-date="${escapeHtml(day.date)}" aria-expanded="${isExpanded}">${formatHm(day.total_minutes)}${flagGlyphs(day.flags)}</button></td>`;
          })
          .join("");
        const name = `${row.user.first_name || ""} ${row.user.last_name || ""}`.trim() || "Unknown";
        const mainRow = `<tr><td>${escapeHtml(name)}</td>${cells}<td>${formatHm(row.total_minutes)}</td></tr>`;
        if (!expanded || expanded.rowIndex !== rowIndex) return mainRow;
        const day = row.days.find((d) => d.date === expanded.date);
        if (!day) return mainRow;
        return `${mainRow}<tr><td colspan="${dates.length + 2}">${drilldownHtml(day)}</td></tr>`;
      })
      .join("");
    const totalsRow = payload.crew_totals_by_day
      .map((t) => `<td>${formatHm(t.minutes)}</td>`)
      .join("");
    const grandTotal = payload.crew_totals_by_day.reduce((sum, t) => sum + t.minutes, 0);

    container.innerHTML = `
      <div class="hub-timesheet-toolbar">
        <div class="hub-timesheet-week-nav">
          <button type="button" class="hub-timesheet-prev" aria-label="Previous week">◀</button>
          <span>${escapeHtml(payload.range.start)} – ${escapeHtml(payload.range.end)}</span>
          <button type="button" class="hub-timesheet-next" aria-label="Next week">▶</button>
        </div>
        <button type="button" class="hub-timesheet-export">Export CSV</button>
      </div>
      ${
        payload.rows.length
          ? `<table class="hub-timesheet-table">
              <thead><tr><th>Technician</th>${headerCells}<th>Total</th></tr></thead>
              <tbody>${bodyRows}</tbody>
              <tfoot><tr><td>Crew total</td>${totalsRow}<td>${formatHm(grandTotal)}</td></tr></tfoot>
            </table>`
          : `<p class="hint">No one is currently routed to you. Your crew's hours appear here once a work order is assigned under your supervision.</p>`
      }`;

    container.querySelectorAll(".hub-timesheet-cell").forEach((btn) => {
      btn.addEventListener("click", () => {
        const rowIndex = Number(btn.dataset.row);
        const clickedDate = btn.dataset.date;
        expanded =
          expanded && expanded.rowIndex === rowIndex && expanded.date === clickedDate
            ? null
            : { rowIndex, date: clickedDate };
        render();
      });
    });

    const prevBtn = container.querySelector(".hub-timesheet-prev");
    const nextBtn = container.querySelector(".hub-timesheet-next");
    if (prevBtn) prevBtn.addEventListener("click", () => shiftWeek(-7));
    if (nextBtn) nextBtn.addEventListener("click", () => shiftWeek(7));

    const exportBtn = container.querySelector(".hub-timesheet-export");
    if (exportBtn) exportBtn.addEventListener("click", () => void downloadCsv(exportBtn));
  }

  function shiftWeek(days) {
    if (!onWeekChange) return;
    const start = new Date(`${payload.range.start}T00:00:00`);
    const end = new Date(`${payload.range.end}T00:00:00`);
    start.setDate(start.getDate() + days);
    end.setDate(end.getDate() + days);
    onWeekChange(start.toISOString().slice(0, 10), end.toISOString().slice(0, 10));
  }

  async function downloadCsv(button) {
    button.disabled = true;
    try {
      const { blob, filename } = await apiExportHubTimesheets({
        start: payload.range.start,
        end: payload.range.end,
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 0);
    } finally {
      button.disabled = false;
    }
  }

  render();
}
```

- [ ] **Step 2: Verify syntax**

Run: `cd backend && node --check static/views/hubTimesheets.js`
Expected: no output (exit 0).

- [ ] **Step 3: Commit**

```bash
git add backend/static/views/hubTimesheets.js
git commit -m "feat(user-hub): add the timesheet grid view"
```

---

### Task 15: Wire the third tab into `userHub.js`

**Files:**
- Modify: `backend/static/views/userHub.js`

**Interfaces:**
- Consumes: `apiGetHubTimesheets` (Task 12), `mountHubTimesheets` (Task 14).

- [ ] **Step 1: Add the import and tab panel entry**

```javascript
// backend/static/views/userHub.js — add to the import block near the top
import { apiGetHub, apiGetHubCrew, apiGetHubTimesheets } from "../api.js";
```

```javascript
// backend/static/views/userHub.js — replace the import of hubTimesheets alongside hubSupervisor
import { mountHubCrew } from "./hubSupervisor.js";
import { mountHubTimesheets } from "./hubTimesheets.js";
```

```javascript
// backend/static/views/userHub.js — extend tabPanels (~line 28-31)
const tabPanels = {
  dashboard: document.getElementById("hub-tabpanel-dashboard"),
  timesheets: document.getElementById("hub-tabpanel-timesheets"),
  "work-orders": document.getElementById("hub-tabpanel-work-orders"),
};
const timesheetsTabButton = document.getElementById("hub-tab-timesheets");
```

- [ ] **Step 2: Add timesheet fetch state and the fetch/render functions**

```javascript
// backend/static/views/userHub.js — add alongside the existing crew state (~line 35-38)
let timesheetRange = null; // { start, end } | null -- null until the tab is first opened
let latestTimesheetPayload = null;
let timesheetRequestId = 0;
```

```javascript
// backend/static/views/userHub.js — add near refreshCrew

async function loadTimesheets({ start = null, end = null } = {}) {
  const mount = tabPanels.timesheets;
  if (!mount) return;
  const requestId = ++timesheetRequestId;
  mount.innerHTML = `<p class="hint">Loading…</p>`;
  try {
    const payload = await apiGetHubTimesheets({ start, end });
    if (requestId !== timesheetRequestId) return;
    latestTimesheetPayload = payload;
    timesheetRange = { start: payload.range.start, end: payload.range.end };
    mountHubTimesheets(mount, payload, { onWeekChange: (s, e) => void loadTimesheets({ start: s, end: e }) });
  } catch (err) {
    if (requestId !== timesheetRequestId) return;
    mount.innerHTML = `<p class="error">${friendlyError(err, "Could not load timesheets.")}</p>`;
  }
}
```

- [ ] **Step 3: Wire tab switching to lazily fetch on first open, and role-gate the tab button**

Replace `renderActiveTab`'s body:

```javascript
// backend/static/views/userHub.js — replace renderActiveTab (~line 67-74)
function renderActiveTab() {
  if (activeTab === "dashboard") {
    mountHubDashboard(tabPanels.dashboard, latestPayload);
    renderCrew();
  } else if (activeTab === "timesheets") {
    if (!latestTimesheetPayload) {
      void loadTimesheets(timesheetRange || {});
    }
  } else {
    mountHubWorkOrders(tabPanels["work-orders"], latestPayload);
  }
}
```

Add the role gate to `loadUserHub`, alongside the existing crew-role check:

```javascript
// backend/static/views/userHub.js — inside loadUserHub, extend the existing
// "if (roleAtLeast(latestPayload.user.role, "supervisor"))" block (~line 131-136)
  if (roleAtLeast(latestPayload.user.role, "supervisor")) {
    await refreshCrew();
    startCrewSafetyRefresh();
    if (timesheetsTabButton) {
      timesheetsTabButton.hidden = false;
      timesheetsTabButton.classList.remove("hidden");
    }
  } else {
    stopCrewSafetyRefresh();
    if (timesheetsTabButton) {
      timesheetsTabButton.hidden = true;
      timesheetsTabButton.classList.add("hidden");
    }
  }
```

- [ ] **Step 4: Verify syntax**

Run: `cd backend && node --check static/views/userHub.js`
Expected: no output (exit 0).

- [ ] **Step 5: Commit**

```bash
git add backend/static/views/userHub.js
git commit -m "feat(user-hub): wire the timesheets tab into the hub shell"
```

---

### Task 16: Manual verification (browser)

No JS test harness exists (Global Constraints). This task substitutes a scripted manual pass via the `chrome-devtools` MCP tools for the automated frontend test/run/pass cycle.

- [ ] **Step 1: Start the dev server** (per [[manual-validation-preference]] — the user drives this themselves; do not start it automatically. Ask the user to confirm the server is running on the usual local port before proceeding, or pause here for them to start it.)

- [ ] **Step 2: Navigate and inspect as a Supervisor**

Use `mcp__chrome-devtools__navigate_page` to the app, log in as a seeded Supervisor account (per [[local-dev-credentials]]), open the User Hub via the header identity button, and click the "Timesheets" tab. Use `take_snapshot` to confirm:
- The tab is visible for this role and hidden when logged in as a Technician.
- The grid renders with a Technician column, one column per day of the current week, and a Total column.
- The default range matches the current Central week.

- [ ] **Step 3: Exercise the drill-down**

Click a cell with non-zero hours. Confirm the expanded row shows the session list (start–end, work order, minutes) and, if any exist, the adjustment line and a `Total` line matching the cell's own number (D15).

- [ ] **Step 4: Exercise week navigation**

Click ◀, then ▶. Confirm the date range in the toolbar updates and the grid refetches (use `list_network_requests` to confirm a fresh `GET /hub/timesheets?start=...&end=...` fires on each click).

- [ ] **Step 5: Exercise CSV export**

Click "Export CSV". Confirm a download fires (check via `list_network_requests` for the `GET /hub/timesheets/export` call and a 200 response) and that no console errors appear (`list_console_messages`).

- [ ] **Step 6: Confirm the tab is absent for a Technician**

Log in as a seeded Technician account. Confirm no "Timesheets" tab button is rendered (only Dashboard / My Work Orders).

- [ ] **Step 7: Report findings to the user**

Summarize what was verified and any issues found. Do not mark this task complete until the user has confirmed the live pass, per [[manual-validation-preference]].

---

## Self-Review Notes

- **Spec coverage:** §5.3 Tab 2 (grid + drill-down, Task 14/16) ✓. §5.4 Tab 2's shared-component promise (Task 14 is used unmodified by both Supervisor and Admin tabs — Admin's own tab wiring is P4) ✓. §7's `GET /hub/timesheets` contract (Task 6/8/9) ✓, including the 92-day cap and 422 (Task 2/6/9) and the `MAX_LIST_ROWS` application (Task 4). §7's CSV filename rule D14 (Task 9). §6.3's attention thresholds reused for the day-cell flags (Task 6). D15 (adjustments in every total) enforced at three layers: `TimesheetDay.total_minutes`, `TimesheetRow.total_minutes`, `crew_totals_by_day` (Task 6), and the CSV (Task 7). D17's rank-scoped-but-supervisor-gated endpoint (Task 9), explicitly **not** widened to "everyone" (Global Constraints, Task 6's docstring) — that's P4.
- **Explicitly out of scope, confirmed against §12:** the `user_id` filter's frontend control (no picker UI built — the backend param is wired and tested, but Task 14's grid always shows the full crew; a filter dropdown is deferred to whichever phase actually needs it), and any TechFM OA+ "everyone" row-scope branch (P4, per D17/§12).
- **Placeholder scan:** every step has real code or a real shell command; the one explicit exception is Task 9 Step 2's fixture names, which are flagged in-line as illustrative pending a grep against the actual `conftest.py` — this is a deliberate "verify against the repo before pasting" instruction, not an unfinished plan step, mirroring how P2's plan handled the same uncertainty for its own router-adjacent tests.
- **Type consistency:** `HubTimesheetPayload.range` (service) ↔ `HubTimesheetResponse.range` (schema) both nest a `{start, end}` object with matching field names throughout — `TimesheetDay`/`HubTimesheetDay`, `TimesheetRow`/`HubTimesheetRow`, `TimesheetDayTotal`/`HubTimesheetDayTotal` pairs use identical field names end to end so `model_validate` needs no field remapping, matching the `HubCrewResponse` precedent rather than `HubResponse`'s field-by-field precedent.
