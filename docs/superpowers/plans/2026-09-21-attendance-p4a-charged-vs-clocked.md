# Attendance P4a — Charged vs clocked, and its CSV

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A second Admin sub-tab that puts **clocked** beside **charged** for every person and day of the attendance week, names the gap in both directions, and exports the week as CSV — without a sweep, a row lock, or a commit on any read.

**Architecture:** `GET /hub/attendance/week` keeps its URL and its Admin floor and grows three numbers per day. The composition happens in a new `services/attendance_compare.py`, which calls the untouched clocked-only `attendance_week.week_payload` and the existing `labor_summary.crew_range_summaries`, so no module gains the job of holding two of §8's three numbers by accident. A new `GET /hub/attendance/export?week=` serializes the same object. The frontend gains `views/hubAttendanceCompare.js` and a third sub-nav feature; `hubTimesheetsTab.js` collapses its two week caches into one payload both Admin features read.

**Tech Stack:** FastAPI + SQLAlchemy + Pydantic v2 (backend), pytest (backend tests), vanilla ES modules + Vitest/MSW/jsdom (frontend).

**Spec:** `docs/superpowers/specs/2026-09-21-attendance-timesheet-design.md` — §4 (endpoints), §6 (frontend), §8 (three numbers), §9 (charged outside the shift), §11 (phasing). P3's plan for shape and conventions: `docs/superpowers/plans/2026-09-21-attendance-p3-punch-editing.md`.

## Global Constraints

**Six decisions taken at planning time. Where they differ from the spec, they win.**

1. **P4 is split.** This plan is **P4a**: the comparison grid and the export. **P4b** carries the live roster, the `attendance.changed` envelope, the move of the Timesheets tab to Admin+, and the §7 retirement of `GET /hub/timesheets`. Nothing here deletes a route.
2. **No billed column.** `domain.work_orders.billed_labor_minutes` rounds a *work order's combined* labor up to 30 minutes, across every technician and every day that touched it. There is no per-person-per-day billed number in this system, and any one this plan invented would be an approximation of an invoice sitting in a column labelled like a fact. The comparison is **clocked · charged · Δ**, both real wall-clock. The deferral is logged in `open-work.md` (Task 9), not re-opened here.
3. **Because P4b has not run yet, the Admin sub-nav has three buttons:** `Hours` · `Charged vs clocked` · `Crew time`. Below Admin nothing changes — no sub-nav, the crew grid alone. P4b removes the third button with the route behind it.
4. **Every read stays side-effect-free** (§4). A forgotten work-order clock is handled by a **pure read-side cap** — `capped_session_end`, Task 1 — which returns the instant `sweep_stale_sessions` would have written, without writing it. No P4 read may call `sweep_stale_sessions`.
5. **Adjustments are carried, never counted.** A hand-entered `work_order_labor` row has no start and no stop, so it is not wall-clock and cannot enter `tracked_minutes` or `delta_minutes`. It rides as its own field and prints only when non-zero — otherwise a day of pure adjustments reads as a day of idleness.
6. **Colour is never the only signal.** `docs/design-system.md` keeps status hues to badges, with `--color-success` / `--color-error` allowed as text or a left-accent rule. The comparison grid therefore flags a day with a glyph **and** a text label in the same cell; no cell's meaning depends on hue.

**Standing rules of this codebase, all load-bearing here:**

- **CSP drops `style=`.** `main.py:143` is `default-src 'self'` with no `style-src`; inline style attributes are silently discarded. Use classes.
- **No nested buttons.** A `<button>` inside a `<button>` is hoisted into a sibling.
- **Files stay under 500 lines.** `hubTimesheetsTab.js` is 247 and grows here; check it at Task 8.
- **Frontend tests assert zero live timers** after `stopClock()`. Nothing in P4a starts an interval — the ticking roster is P4b's problem.
- Commits end with `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`, matching the last five commits on `main`.

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/domain/work_orders.py` (modify) | `capped_session_end` — the cap as an instant, beside `capped_session_minutes` |
| `backend/app/domain/attendance.py` (modify) | `minutes_charged_outside_shift` — pure interval subtraction |
| `backend/app/services/labor_summary.py` (modify) | `crew_range_summaries(..., cap_running=False)` |
| `backend/app/services/attendance_compare.py` (create) | Joins clocked + tracked into one week object. The one module that holds two of §8's numbers |
| `backend/app/schemas/attendance.py` (modify) | Four new day fields, two new row fields, two new week fields |
| `backend/app/routers/hub.py` (modify) | Week route reads through `attendance_compare`; new `GET /hub/attendance/export` |
| `backend/static/api.js` (modify) | `apiExportHubAttendance` |
| `backend/static/views/hubAttendanceCompare.js` (create) | The comparison grid. Pure view: no fetch, no state |
| `backend/static/views/hubTimesheetsTab.js` (modify) | Third feature; one week payload shared by both Admin features |
| `backend/static/tips.js` (modify) | `hub.charged-vs-clocked` |
| `backend/static/styles.css` (modify) | `.hub-compare-*` |

Tests: `test_work_orders_domain.py`, `test_attendance_domain.py`, `test_labor_summary.py`, `test_attendance_compare_service.py` (new), `test_attendance_week_router.py`, `test_attendance_export_router.py` (new), `test_route_role_gates.py`, `tests/frontend/views/hubAttendanceCompare.test.js` (new), `hubTimesheetsTab.test.js`, `helpers/factories.js`, `helpers/endpointTable.js`, `unit/api.shapes.test.js`.

---

### Task 1: The cap as an instant, and an uncapped range read that can ask for it

**Files:**
- Modify: `backend/app/domain/work_orders.py` (beside `capped_session_minutes`, ~line 349)
- Modify: `backend/app/services/labor_summary.py::crew_range_summaries` (~line 273)
- Test: `backend/tests/test_work_orders_domain.py`, `backend/tests/test_labor_summary.py`

**Interfaces:**
- Produces: `work_orders.capped_session_end(started_at, ended_at, *, now) -> datetime`
- Produces: `labor_summary.crew_range_summaries(db, ids, start_day, end_day, *, now, cap_running=False)`

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_work_orders_domain.py`:

```python
def test_capped_session_end_returns_the_real_stop_for_a_closed_session():
    started = datetime(2026, 9, 14, 13, 0, tzinfo=timezone.utc)
    ended = datetime(2026, 9, 14, 21, 0, tzinfo=timezone.utc)
    now = datetime(2026, 9, 15, 9, 0, tzinfo=timezone.utc)
    assert wo.capped_session_end(started, ended, now=now) == ended


def test_capped_session_end_stands_now_in_for_a_running_session():
    started = datetime(2026, 9, 14, 13, 0, tzinfo=timezone.utc)
    now = datetime(2026, 9, 14, 17, 0, tzinfo=timezone.utc)
    assert wo.capped_session_end(started, None, now=now) == now


def test_capped_session_end_truncates_a_forgotten_clock_at_the_cap():
    # The sweep writes started_at + 720min; a read that must not write gets
    # the same instant from here instead of a 40-hour running session.
    started = datetime(2026, 9, 14, 13, 0, tzinfo=timezone.utc)
    now = datetime(2026, 9, 16, 13, 0, tzinfo=timezone.utc)
    assert wo.capped_session_end(started, None, now=now) == started + timedelta(
        minutes=wo.LABOR_SESSION_MAX_MINUTES
    )


def test_capped_session_end_never_truncates_a_closed_over_cap_session():
    # A supervisor may legitimately record a long closed session by hand.
    # The cap exists for clocks nobody stopped, not for recorded history.
    started = datetime(2026, 9, 14, 13, 0, tzinfo=timezone.utc)
    ended = started + timedelta(minutes=wo.LABOR_SESSION_MAX_MINUTES + 120)
    now = ended + timedelta(hours=1)
    assert wo.capped_session_end(started, ended, now=now) == ended
```

In `backend/tests/test_labor_summary.py`, beside the existing range-aggregate tests (~line 531):

```python
def test_crew_range_summaries_leaves_a_forgotten_clock_uncapped_by_default(db):
    # The existing timesheet caller sweeps first, so the default must not
    # change under it.
    tech = make_technician(db)
    started = datetime(2026, 9, 14, 13, 0, tzinfo=timezone.utc)
    make_running_session(db, technician=tech, started_at=started)
    now = datetime(2026, 9, 15, 13, 0, tzinfo=timezone.utc)

    summaries = labor_summary.crew_range_summaries(
        db, [tech.id], date(2026, 9, 14), date(2026, 9, 15), now=now
    )
    total = sum(day.running_minutes for day in summaries[tech.id])
    assert total == 24 * 60


def test_crew_range_summaries_caps_a_forgotten_clock_when_asked(db):
    tech = make_technician(db)
    started = datetime(2026, 9, 14, 13, 0, tzinfo=timezone.utc)
    make_running_session(db, technician=tech, started_at=started)
    now = datetime(2026, 9, 15, 13, 0, tzinfo=timezone.utc)

    summaries = labor_summary.crew_range_summaries(
        db, [tech.id], date(2026, 9, 14), date(2026, 9, 15),
        now=now, cap_running=True,
    )
    total = sum(day.running_minutes for day in summaries[tech.id])
    assert total == wo.LABOR_SESSION_MAX_MINUTES
```

Use whatever technician/session factories that file already imports; do not add new ones.

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && python -m pytest tests/test_work_orders_domain.py -k capped_session_end tests/test_labor_summary.py -k crew_range_summaries_ -v`
Expected: FAIL — `AttributeError: module 'app.domain.work_orders' has no attribute 'capped_session_end'`, and `TypeError: crew_range_summaries() got an unexpected keyword argument 'cap_running'`.

- [ ] **Step 3: Add the domain function**

In `backend/app/domain/work_orders.py`, directly after `capped_session_minutes`:

```python
def capped_session_end(
    started_at: datetime,
    ended_at: Optional[datetime],
    *,
    now: datetime,
) -> datetime:
    """The instant a session effectively ends, for a reader that must not write.

    `capped_session_minutes`'s sibling: same cap, expressed as a moment rather
    than a duration, because the day-splitting arithmetic in
    `domain.labor_day` takes instants.

    A closed session ends when it says it does -- including one longer than
    the cap, which is recorded history a supervisor entered, not a clock
    nobody stopped. A running session ends now, or at
    `started_at + LABOR_SESSION_MAX_MINUTES` if that is sooner: exactly the
    instant `services.work_orders.sweep_stale_sessions` would have written,
    which is what lets the attendance reads stay side-effect-free (spec §4)
    and still never show a forty-hour Tuesday.
    """
    if ended_at is not None:
        return as_utc(ended_at)
    moment = as_utc(now)
    cap = as_utc(started_at) + timedelta(minutes=LABOR_SESSION_MAX_MINUTES)
    return min(moment, cap)
```

Add `from datetime import timedelta` and the `as_utc` import from `app.domain.labor_day` only if this module does not already have them — check the header first, and reuse what is there.

- [ ] **Step 4: Add the flag to the range read**

In `crew_range_summaries`, change the signature to
`def crew_range_summaries(db, technician_ids, start_day, end_day, *, now, cap_running=False)`
and extend its docstring with:

```
    `cap_running=True` clips an open session at the 12-hour cap without
    writing anything, for the attendance reads that must not sweep (spec §4).
    The default is off: the timesheet caller sweeps before reading, and a
    swept session is already closed.
```

Inside the session loop, replace the single `split_by_day` call with:

```python
        stop = (
            wo.capped_session_end(session.started_at, session.ended_at, now=now)
            if cap_running
            else now
        )
        for day, minutes in labor_day.split_by_day(
            session.started_at, session.ended_at, now=stop
        ):
```

`split_by_day` uses `now` only as the stand-in end for an open session, so handing it the capped instant produces the capped split and nothing else changes. Import `from app.domain import work_orders as wo` at the top of `labor_summary.py` if it is not already imported.

- [ ] **Step 5: Run the tests**

Run: `cd backend && python -m pytest tests/test_work_orders_domain.py tests/test_labor_summary.py -q`
Expected: PASS, including every pre-existing test in both files.

- [ ] **Step 6: Commit**

```bash
git add backend/app/domain/work_orders.py backend/app/services/labor_summary.py backend/tests/test_work_orders_domain.py backend/tests/test_labor_summary.py
git commit -m "feat(attendance): the session cap as an instant, for reads that must not sweep"
```

---

### Task 2: Charged time no punch covers

**Files:**
- Modify: `backend/app/domain/attendance.py` (after `find_overlap`)
- Test: `backend/tests/test_attendance_domain.py`

**Interfaces:**
- Consumes: nothing from Task 1 (pure, independent).
- Produces: `attendance.minutes_charged_outside_shift(*, sessions, punches, window, now) -> int`, where `sessions` and `punches` are iterables of `(start, end_or_None)` instant pairs and `window` is a `(start, end)` UTC pair.

- [ ] **Step 1: Write the failing tests**

```python
DAY = labor_day.day_bounds(date(2026, 9, 14))


def _at(hour, minute=0):
    # 2026-09-14 Central, expressed in UTC (CDT, UTC-5).
    return datetime(2026, 9, 14, hour + 5, minute, tzinfo=timezone.utc)


NOW = _at(23)


def test_no_charged_time_outside_a_shift_that_contains_every_session():
    assert attendance.minutes_charged_outside_shift(
        sessions=[(_at(9), _at(11)), (_at(13), _at(16))],
        punches=[(_at(8), _at(17))],
        window=DAY, now=NOW,
    ) == 0


def test_an_hour_charged_before_punching_in_is_counted():
    assert attendance.minutes_charged_outside_shift(
        sessions=[(_at(7), _at(9))],
        punches=[(_at(8), _at(17))],
        window=DAY, now=NOW,
    ) == 60


def test_two_overlapping_sessions_are_one_minute_each_not_two():
    # The same minute charged on two work orders is one minute off shift.
    assert attendance.minutes_charged_outside_shift(
        sessions=[(_at(6), _at(7)), (_at(6, 30), _at(7, 30))],
        punches=[],
        window=DAY, now=NOW,
    ) == 90


def test_a_gap_between_two_punches_is_outside_the_shift():
    # Punched out for lunch, still charging.
    assert attendance.minutes_charged_outside_shift(
        sessions=[(_at(11), _at(14))],
        punches=[(_at(8), _at(12)), (_at(13), _at(17))],
        window=DAY, now=NOW,
    ) == 60


def test_only_the_part_inside_the_window_counts():
    # A session that starts the previous evening contributes only today.
    assert attendance.minutes_charged_outside_shift(
        sessions=[(_at(-2), _at(1))],   # 10 PM Sunday to 1 AM Monday
        punches=[],
        window=DAY, now=NOW,
    ) == 60


def test_an_open_session_and_an_open_punch_both_end_at_now():
    assert attendance.minutes_charged_outside_shift(
        sessions=[(_at(20), None)],
        punches=[(_at(20), None)],
        window=DAY, now=NOW,
    ) == 0


def test_no_sessions_is_zero_not_an_error():
    assert attendance.minutes_charged_outside_shift(
        sessions=[], punches=[(_at(8), _at(17))], window=DAY, now=NOW
    ) == 0
```

`_at` with a negative hour needs `datetime(2026, 9, 13, 22, ...)`; write that case out literally rather than relying on negative-hour arithmetic.

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && python -m pytest tests/test_attendance_domain.py -k outside_shift -v`
Expected: FAIL — `AttributeError: module 'app.domain.attendance' has no attribute 'minutes_charged_outside_shift'`.

- [ ] **Step 3: Write the function**

```python
Span = tuple[datetime, Optional[datetime]]


def _clipped(spans: Iterable[Span], window: tuple[datetime, datetime],
             *, now: datetime) -> list[list[datetime]]:
    """Every span, in UTC, trimmed to `window`, empty ones dropped. `None`
    for an end means still open and `now` stands in for it."""
    start_bound, end_bound = window
    moment = labor_day.as_utc(now)
    clipped: list[list[datetime]] = []
    for start, end in spans:
        begin = max(labor_day.as_utc(start), start_bound)
        stop = min(labor_day.as_utc(end) if end is not None else moment, end_bound)
        if stop > begin:
            clipped.append([begin, stop])
    return clipped


def _merged(spans: list[list[datetime]]) -> list[list[datetime]]:
    """Union of half-open intervals: sorted, non-overlapping, touching ones
    joined. Two work orders charged over the same minute are one minute."""
    merged: list[list[datetime]] = []
    for begin, stop in sorted(spans):
        if merged and begin <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], stop)
        else:
            merged.append([begin, stop])
    return merged


def minutes_charged_outside_shift(
    *,
    sessions: Iterable[Span],
    punches: Iterable[Span],
    window: tuple[datetime, datetime],
    now: datetime,
) -> int:
    """Charged minutes inside `window` that no punch covers (spec §9).

    Spec §9 allows charging outside a shift and flags it rather than refusing
    it -- "refusing the edit is how people end up editing Postgres by hand."
    This is that flag's number: how much, so an Admin can see whether it is a
    forgotten punch-in or a rounding artifact.

    Half-open on both sides, matching `find_overlap`: a session that starts
    exactly when a punch ends is wholly outside it.

    Rounded once, over the summed uncovered seconds -- not per span -- so a
    day of six short gaps cannot accumulate six half-minute roundings. The
    rule is Python's `round`, the same half-to-even
    `labor_day.overlap_minutes` uses.
    """
    charged = _merged(_clipped(sessions, window, now=now))
    if not charged:
        return 0
    covered = _merged(_clipped(punches, window, now=now))
    seconds = 0.0
    for begin, stop in charged:
        cursor = begin
        for shift_begin, shift_stop in covered:
            if shift_stop <= cursor:
                continue
            if shift_begin >= stop:
                break
            if shift_begin > cursor:
                seconds += (shift_begin - cursor).total_seconds()
            cursor = max(cursor, shift_stop)
            if cursor >= stop:
                break
        if cursor < stop:
            seconds += (stop - cursor).total_seconds()
    return round(seconds / 60)
```

`Iterable` and `Optional` are already imported in this module; `datetime` too.

- [ ] **Step 4: Run the tests**

Run: `cd backend && python -m pytest tests/test_attendance_domain.py -q`
Expected: PASS, whole file.

- [ ] **Step 5: Commit**

```bash
git add backend/app/domain/attendance.py backend/tests/test_attendance_domain.py
git commit -m "feat(attendance): the pure rule for charged time no punch covers"
```

---

### Task 3: The comparison payload

**Files:**
- Create: `backend/app/services/attendance_compare.py`
- Test: `backend/tests/test_attendance_compare_service.py`

**Interfaces:**
- Consumes: `work_orders.capped_session_end`, `crew_range_summaries(..., cap_running=True)` (Task 1); `attendance.minutes_charged_outside_shift` (Task 2); `attendance_week.week_payload`, `attendance_week.WeekPunch`, `attendance_week.DayTotal` (P2, unchanged).
- Produces: `attendance_compare.week_payload(db, *, week_start, now) -> CompareWeek`, with `CompareDay(date, clocked_minutes, tracked_minutes, delta_minutes, outside_shift_minutes, adjustment_minutes, needs_review, has_open, punches)`, `CompareRow(user, days, total_minutes, tracked_minutes, delta_minutes)`, `CompareWeek(week_start, week_end, server_now, days, rows, totals_by_day, total_minutes, tracked_minutes, delta_minutes, week_hours)`.

- [ ] **Step 1: Write the failing tests**

Model the fixtures on `backend/tests/test_attendance_week_service.py` — same `db` fixture, same punch/user helpers. Reuse its helpers by importing them if it exposes any; otherwise copy the smallest shape needed.

```python
MONDAY = date(2026, 9, 14)
NOW = datetime(2026, 9, 16, 15, 0, tzinfo=timezone.utc)


def test_a_day_on_shift_and_on_a_job_has_no_gap_in_either_direction(db):
    tech = make_technician(db)
    make_punch(db, tech, "2026-09-14T13:00Z", "2026-09-14T21:00Z")      # 8h
    make_session(db, tech, "2026-09-14T13:00Z", "2026-09-14T21:00Z")    # 8h
    week = attendance_compare.week_payload(db, week_start=MONDAY, now=NOW)

    monday = week.rows[0].days[0]
    assert (monday.clocked_minutes, monday.tracked_minutes) == (480, 480)
    assert monday.delta_minutes == 0
    assert monday.outside_shift_minutes == 0


def test_delta_is_clocked_minus_tracked_and_means_on_shift_not_on_a_job(db):
    tech = make_technician(db)
    make_punch(db, tech, "2026-09-14T13:00Z", "2026-09-14T21:00Z")      # 8h
    make_session(db, tech, "2026-09-14T13:00Z", "2026-09-14T19:00Z")    # 6h
    week = attendance_compare.week_payload(db, week_start=MONDAY, now=NOW)

    assert week.rows[0].days[0].delta_minutes == 120
    assert week.rows[0].delta_minutes == 120
    assert week.delta_minutes == 120


def test_charging_outside_the_shift_is_flagged_and_never_makes_delta_negative(db):
    tech = make_technician(db)
    make_punch(db, tech, "2026-09-14T14:00Z", "2026-09-14T21:00Z")      # 7h
    make_session(db, tech, "2026-09-14T13:00Z", "2026-09-14T21:00Z")    # 8h
    week = attendance_compare.week_payload(db, week_start=MONDAY, now=NOW)

    monday = week.rows[0].days[0]
    assert monday.delta_minutes == 0          # floored, never negative
    assert monday.outside_shift_minutes == 60


def test_both_gaps_can_be_non_zero_on_the_same_day(db):
    # An hour charged before punching in, and an idle hour after lunch.
    tech = make_technician(db)
    make_punch(db, tech, "2026-09-14T14:00Z", "2026-09-14T22:00Z")      # 8h
    make_session(db, tech, "2026-09-14T13:00Z", "2026-09-14T20:00Z")    # 7h
    week = attendance_compare.week_payload(db, week_start=MONDAY, now=NOW)

    monday = week.rows[0].days[0]
    assert monday.outside_shift_minutes == 60
    assert monday.delta_minutes == 60


def test_an_adjustment_is_carried_beside_the_two_wall_clock_numbers(db):
    tech = make_technician(db)
    make_punch(db, tech, "2026-09-14T13:00Z", "2026-09-14T21:00Z")
    make_adjustment(db, tech, minutes=30, created_at="2026-09-14T15:00Z")
    week = attendance_compare.week_payload(db, week_start=MONDAY, now=NOW)

    monday = week.rows[0].days[0]
    assert monday.adjustment_minutes == 30
    assert monday.tracked_minutes == 0        # no session, so no wall clock
    assert monday.delta_minutes == 480        # the whole shift reads as off-job


def test_a_forgotten_clock_is_capped_without_writing_anything(db):
    tech = make_technician(db)
    make_running_session(db, tech, "2026-09-14T13:00Z")
    later = datetime(2026, 9, 16, 13, 0, tzinfo=timezone.utc)

    week = attendance_compare.week_payload(db, week_start=MONDAY, now=later)
    tracked = sum(day.tracked_minutes for day in week.rows[0].days)
    assert tracked == 720
    # side-effect-free (spec §4): the session is still open in the database
    db.expire_all()
    assert reload_session(db, tech).ended_at is None


def test_the_clocked_half_is_exactly_what_the_hours_grid_reads(db):
    # One source for the pay number. If these ever differ, two tabs of the
    # same tab disagree about payroll.
    tech = make_technician(db)
    make_punch(db, tech, "2026-09-14T13:00Z", "2026-09-14T21:00Z")
    clocked = attendance_week.week_payload(db, week_start=MONDAY, now=NOW)
    compared = attendance_compare.week_payload(db, week_start=MONDAY, now=NOW)

    assert compared.total_minutes == clocked.total_minutes
    assert [d.minutes for d in compared.totals_by_day] == [
        d.minutes for d in clocked.totals_by_day
    ]
    assert compared.rows[0].days[0].punches == clocked.rows[0].days[0].punches
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && python -m pytest tests/test_attendance_compare_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.attendance_compare'`.

- [ ] **Step 3: Write the service**

```python
"""Charged against clocked: one week, per person per day.

Layer: services. Read-only and **side-effect-free** (spec §4) -- no sweep, no
row locks, no commit -- so the Timesheets tab may refetch it as often as it
likes, and P4b's live layer may poll it.

This is the one module that holds two of spec §8's three numbers at once, so
it is the one place they could be blurred. Three rules keep them apart:

- **Clocked** comes from `attendance_week.week_payload` and is passed through
  untouched. That module stays clocked-only; nothing here recomputes a pay
  number.
- **Tracked** is real wall-clock on jobs, from labor sessions, with a running
  session clipped at the 12-hour cap by `work_orders.capped_session_end`
  rather than by a sweep.
- **Billed is absent.** `billed_labor_minutes` rounds a *work order's
  combined* labor, across people and days; there is no per-person-per-day
  billed number, and inventing one would put an approximation of an invoice
  under a column labelled like a fact.

`delta_minutes` is `clocked - tracked` floored at zero: "on shift, not on a
job". `outside_shift_minutes` is the other direction -- charged time no punch
covers, which §9 allows and flags. Both can be non-zero on the same day.

A hand-entered labor adjustment has no start and no stop, so it is not
wall-clock: it rides in `adjustment_minutes` and is never added into tracked
or differenced into delta.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.domain import attendance, labor_day
from app.domain import work_orders as wo
from app.models import User
from app.services import attendance_week, labor_summary


@dataclass(frozen=True)
class CompareDay:
    date: date
    clocked_minutes: int
    tracked_minutes: int
    delta_minutes: int
    outside_shift_minutes: int
    adjustment_minutes: int
    needs_review: bool
    has_open: bool
    punches: list[attendance_week.WeekPunch]


@dataclass(frozen=True)
class CompareRow:
    user: User
    days: list[CompareDay]
    total_minutes: int          # clocked; the name the Hours grid already uses
    tracked_minutes: int
    delta_minutes: int


@dataclass(frozen=True)
class CompareWeek:
    week_start: date
    week_end: date
    server_now: datetime
    days: list[date]
    rows: list[CompareRow]
    totals_by_day: list[attendance_week.DayTotal]
    total_minutes: int
    tracked_minutes: int
    delta_minutes: int
    week_hours: int


def week_payload(db: Session, *, week_start: date, now: datetime) -> CompareWeek:
    """The comparison for the Central week beginning `week_start` (a Monday).

    `week_start` is resolved by `work_order_report.resolve_week` at the route,
    exactly as the Hours read resolves it -- the two sub-tabs share one week
    by construction, not by two agreeing implementations.
    """
    clocked = attendance_week.week_payload(db, week_start=week_start, now=now)
    user_ids = [row.user.id for row in clocked.rows]
    summaries: dict[uuid.UUID, list[labor_summary.DaySummary]] = (
        labor_summary.crew_range_summaries(
            db, user_ids, clocked.week_start, clocked.week_end,
            now=now, cap_running=True,
        )
        if user_ids
        else {}
    )
    bounds = {day: labor_day.day_bounds(day) for day in clocked.days}

    rows: list[CompareRow] = []
    week_tracked = 0
    week_delta = 0
    for row in clocked.rows:
        by_day = {
            summary.day: summary for summary in summaries.get(row.user.id, [])
        }
        days: list[CompareDay] = []
        row_tracked = 0
        row_delta = 0
        for day in row.days:
            summary = by_day.get(day.date)
            tracked = (
                summary.closed_minutes + summary.running_minutes if summary else 0
            )
            outside = attendance.minutes_charged_outside_shift(
                sessions=[
                    (
                        entry.started_at,
                        wo.capped_session_end(
                            entry.started_at, entry.ended_at, now=now
                        ),
                    )
                    for entry in (summary.timeline if summary else [])
                ],
                punches=[
                    (punch.started_at, punch.ended_at) for punch in day.punches
                ],
                window=bounds[day.date],
                now=now,
            )
            delta = max(0, day.clocked_minutes - tracked)
            row_tracked += tracked
            row_delta += delta
            days.append(
                CompareDay(
                    date=day.date,
                    clocked_minutes=day.clocked_minutes,
                    tracked_minutes=tracked,
                    delta_minutes=delta,
                    outside_shift_minutes=outside,
                    adjustment_minutes=(
                        summary.adjustment_minutes if summary else 0
                    ),
                    needs_review=day.needs_review,
                    has_open=day.has_open,
                    punches=day.punches,
                )
            )
        week_tracked += row_tracked
        week_delta += row_delta
        rows.append(
            CompareRow(
                user=row.user,
                days=days,
                total_minutes=row.total_minutes,
                tracked_minutes=row_tracked,
                delta_minutes=row_delta,
            )
        )

    return CompareWeek(
        week_start=clocked.week_start,
        week_end=clocked.week_end,
        server_now=clocked.server_now,
        days=clocked.days,
        rows=rows,
        totals_by_day=clocked.totals_by_day,
        total_minutes=clocked.total_minutes,
        tracked_minutes=week_tracked,
        delta_minutes=week_delta,
        week_hours=clocked.week_hours,
    )
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && python -m pytest tests/test_attendance_compare_service.py tests/test_attendance_week_service.py -q`
Expected: PASS. The week-service file must be untouched and still green — that is the check that the clocked half was not disturbed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/attendance_compare.py backend/tests/test_attendance_compare_service.py
git commit -m "feat(attendance): the charged-vs-clocked week payload"
```

---

### Task 4: The week route serves both sub-tabs

**Files:**
- Modify: `backend/app/schemas/attendance.py`
- Modify: `backend/app/routers/hub.py:155-181`
- Test: `backend/tests/test_attendance_week_router.py`

**Interfaces:**
- Consumes: `attendance_compare.week_payload` (Task 3).
- Produces: `GET /hub/attendance/week` returning `AttendanceWeekResponse` with `tracked_minutes`, `delta_minutes`, `outside_shift_minutes`, `adjustment_minutes` on each day; `tracked_minutes`, `delta_minutes` on each row and on the week.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_attendance_week_router.py`, matching how that file builds its client and Admin session:

```python
def test_the_week_read_carries_the_comparison_columns(client, admin_session, seeded_week):
    response = client.get("/hub/attendance/week?week=2026-09-14")
    assert response.status_code == 200
    body = response.json()

    day = body["rows"][0]["days"][0]
    assert set(day) >= {
        "clocked_minutes", "tracked_minutes", "delta_minutes",
        "outside_shift_minutes", "adjustment_minutes",
    }
    assert body["rows"][0]["tracked_minutes"] >= 0
    assert {"tracked_minutes", "delta_minutes"} <= set(body)


def test_a_non_monday_is_still_422_after_the_comparison_join(client, admin_session):
    assert client.get("/hub/attendance/week?week=2026-09-15").status_code == 422
```

Adapt the fixture names to whatever that file already uses; do **not** invent new fixtures. Drive the route through the real `TestClient` — a direct handler call will not exercise `Query` validation (see `docs/open-work.md`'s note on int-Literal query params).

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && python -m pytest tests/test_attendance_week_router.py -v`
Expected: FAIL — `KeyError`/assertion on the missing `tracked_minutes`.

- [ ] **Step 3: Extend the schemas**

In `backend/app/schemas/attendance.py`, add to `AttendanceWeekDay`, after `clocked_minutes`:

```python
    # The comparison columns (P4a, spec §8). Real wall-clock, both of them:
    # `tracked` is time on a job, `delta` is `clocked - tracked` floored at
    # zero -- on shift, not on a job. `outside_shift` is the other direction,
    # charged time no punch covers (§9), which is flagged, never refused.
    # `adjustment` is hand-entered labor with no start or stop: carried here,
    # never counted into either wall-clock number.
    tracked_minutes: int
    delta_minutes: int
    outside_shift_minutes: int
    adjustment_minutes: int
```

Add `tracked_minutes: int` and `delta_minutes: int` to `AttendanceWeekRow` and to `AttendanceWeekResponse`. All four are **required** — a field that silently defaulted to 0 would print a confident zero for a number that was never computed.

Replace the "`tracked` and `billed` join this payload additively in P4" sentence in `AttendanceWeekResponse`'s docstring with:

```
    Clocked is the pay number (§8) and is never rounded. `tracked_minutes`
    and `delta_minutes` join it here for the comparison sub-tab; the Hours
    grid reads the same object and ignores them. There is no billed column:
    `billed_labor_minutes` rounds a whole work order's combined labor, so no
    honest per-person-per-day billed number exists to put here.
```

- [ ] **Step 4: Point the route at the comparison service**

In `backend/app/routers/hub.py`, add `from app.services import attendance_compare` to the service imports, and change the last line of `get_hub_attendance_week` to:

```python
    return attendance_compare.week_payload(db, week_start=week_start, now=now)
```

Update that handler's docstring: the read serves **both** sub-tabs — Hours renders the clocked column and the punches, Charged vs clocked renders clocked, tracked and the two gaps — and it remains side-effect-free, now including the labor half, which is capped rather than swept.

- [ ] **Step 5: Run the backend suite**

Run: `cd backend && python -m pytest -q`
Expected: PASS. Watch for failures in `test_attendance_admin_router.py` and any schema-shape assertions — a required field added to a response model breaks any test constructing that model by hand.

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/attendance.py backend/app/routers/hub.py backend/tests/test_attendance_week_router.py
git commit -m "feat(attendance): the week read carries charged and the two gaps"
```

---

### Task 5: The CSV export

**Files:**
- Modify: `backend/app/services/attendance_compare.py` (add `week_csv`)
- Modify: `backend/app/routers/hub.py` (new route after the punch writes)
- Modify: `backend/tests/test_route_role_gates.py:~540`
- Test: `backend/tests/test_attendance_export_router.py` (create)

**Interfaces:**
- Consumes: `attendance_compare.week_payload` (Task 3).
- Produces: `attendance_compare.week_csv(payload: CompareWeek) -> str`; route `export_hub_attendance` at `GET /hub/attendance/export?week=`, `text/csv; charset=utf-8`, `attachment; filename="attendance_<week_start>.csv"`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_attendance_export_router.py`:

```python
def test_the_export_is_csv_with_the_week_in_its_filename(client, admin_session, seeded_week):
    response = client.get("/hub/attendance/export?week=2026-09-14")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"] == (
        'attachment; filename="attendance_2026-09-14.csv"'
    )


def test_every_person_gets_the_same_five_metric_rows(client, admin_session, seeded_week):
    lines = client.get("/hub/attendance/export?week=2026-09-14").text.splitlines()
    assert lines[0].split(",")[:2] == ["Person", "Metric"]
    assert lines[0].split(",")[-1] == "Week"
    metrics = [line.split(",")[1] for line in lines[1:6]]
    assert metrics == [
        "Clocked", "Charged", "Off job", "Charged outside shift", "Adjustments"
    ]


def test_the_figures_are_h_mm_and_the_last_block_is_the_company_total(
    client, admin_session, seeded_week
):
    lines = client.get("/hub/attendance/export?week=2026-09-14").text.splitlines()
    assert lines[1].split(",")[2] == "8:00"     # Monday, the seeded 8-hour shift
    assert lines[-5].split(",")[0] == "Company total"


def test_a_non_monday_is_422_exactly_as_the_week_read_is(client, admin_session):
    assert client.get("/hub/attendance/export?week=2026-09-15").status_code == 422


def test_below_admin_is_403(client, techfm_oa_session):
    assert client.get("/hub/attendance/export?week=2026-09-14").status_code == 403
```

And in `backend/tests/test_route_role_gates.py`, add `"export_hub_attendance"` to the expected offender set in `test_no_route_gate_is_left_at_the_admin_floor`, and replace the trailing "P4 adds `get_hub_attendance_live` and `export_hub_attendance`" sentences (there are two, one in each paragraph) with a single line:

```python
    # P4a adds the CSV export on the same grounds -- it *is* the pay record,
    # rendered for payroll. P4b adds `get_hub_attendance_live`.
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && python -m pytest tests/test_attendance_export_router.py tests/test_route_role_gates.py -v`
Expected: FAIL — 404 on the export path, and the role-gate set mismatching by one name.

- [ ] **Step 3: Write the serializer**

Append to `backend/app/services/attendance_compare.py` (and add `import csv`, `import io` at the top):

```python
def _hm(total_minutes: int) -> str:
    """Payroll-facing `H:MM`, the convention the hub's exports already use."""
    hours, minutes = divmod(max(0, round(total_minutes)), 60)
    return f"{hours}:{minutes:02d}"


# Five rows per person, always, in this order. A fixed block is what makes the
# file parseable: a metric that appears only when non-zero turns every reader
# into a state machine.
_METRICS: tuple[tuple[str, str], ...] = (
    ("Clocked", "clocked_minutes"),
    ("Charged", "tracked_minutes"),
    ("Off job", "delta_minutes"),
    ("Charged outside shift", "outside_shift_minutes"),
    ("Adjustments", "adjustment_minutes"),
)


def week_csv(payload: CompareWeek) -> str:
    """The comparison as payroll-friendly CSV: five metric rows per person,
    seven day columns, a week column, then the same block for the company.

    One header row and nothing above it -- a title line is the first thing a
    spreadsheet import gets wrong.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(
        ["Person", "Metric", *(day.isoformat() for day in payload.days), "Week"]
    )

    company: dict[str, list[int]] = {
        label: [0] * len(payload.days) for label, _ in _METRICS
    }
    for row in payload.rows:
        by_date = {day.date: day for day in row.days}
        name = row.user.full_name
        for label, field in _METRICS:
            cells = [getattr(by_date[day], field) if day in by_date else 0
                     for day in payload.days]
            for index, value in enumerate(cells):
                company[label][index] += value
            writer.writerow(
                [name, label, *(_hm(value) for value in cells), _hm(sum(cells))]
            )

    for label, _ in _METRICS:
        cells = company[label]
        writer.writerow(
            ["Company total", label, *(_hm(value) for value in cells),
             _hm(sum(cells))]
        )
    return buffer.getvalue()
```

- [ ] **Step 4: Add the route**

In `backend/app/routers/hub.py`, directly after `delete_hub_attendance_punch`:

```python
@router.get("/attendance/export")
def export_hub_attendance(
    week: Optional[date] = Query(None),
    user: User = Depends(require_min_role(roles.ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """The comparison week as CSV. Admin floor, same grounds as the read it
    serializes: this is the pay record, rendered for payroll.

    Same `week` contract as `GET /hub/attendance/week` -- a Monday, or absent
    for the week in progress, and a non-Monday is 422 from the same resolver.
    """
    now = datetime.now(timezone.utc)
    try:
        week_start = work_order_report.resolve_week(week, now)
    except DomainError as exc:
        raise to_http(exc) from exc
    payload = attendance_compare.week_payload(db, week_start=week_start, now=now)
    return Response(
        content=attendance_compare.week_csv(payload),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition":
                f'attachment; filename="attendance_{week_start.isoformat()}.csv"'
        },
    )
```

Add the route to the module docstring's route list, beside the existing `GET /hub/attendance/week` line.

- [ ] **Step 5: Run the backend suite**

Run: `cd backend && python -m pytest -q`
Expected: PASS, whole suite.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/attendance_compare.py backend/app/routers/hub.py backend/tests/test_attendance_export_router.py backend/tests/test_route_role_gates.py
git commit -m "feat(attendance): the weekly attendance CSV at the Admin floor"
```

---

### Task 6: The api.js wrapper

**Files:**
- Modify: `backend/static/api.js` (Attendance section, after `apiGetHubAttendanceWeek`)
- Modify: `tests/frontend/helpers/endpointTable.js:~142`
- Test: `tests/frontend/unit/api.shapes.test.js`

**Interfaces:**
- Produces: `apiExportHubAttendance({ week }) -> { blob, filename }`.

- [ ] **Step 1: Add the table row and the shape test (the failing tests)**

In `tests/frontend/helpers/endpointTable.js`, after the `apiGetHubAttendanceWeek` row:

```js
  { fn: "apiExportHubAttendance", args: [{}], url: "/hub/attendance/export", cache: "no-store" },
```

In `tests/frontend/unit/api.shapes.test.js`, beside the existing export-filename test:

```js
  it("apiExportHubAttendance sends the Monday and falls back to a named file", async () => {
    server.use(http.get("/hub/attendance/export", () => new HttpResponse("x")));
    const result = await api.apiExportHubAttendance({ week: "2026-09-14" });
    expect(lastUrl()).toBe("/hub/attendance/export?week=2026-09-14");
    expect(result.filename).toBe("attendance.csv");
  });
```

- [ ] **Step 2: Run them and watch them fail**

Run: `npx vitest run tests/frontend/unit/api.shapes.test.js tests/frontend/unit/api.endpoints.test.js`
Expected: FAIL — `api.apiExportHubAttendance is not a function`.

- [ ] **Step 3: Write the wrapper**

```js
// The comparison week as CSV. A blob, not a plain link like the report's
// xlsx: a 403 or a 500 on a link is a broken download with no message, and
// this button lives beside a grid that can say what went wrong.
export async function apiExportHubAttendance({ week = null } = {}) {
  const params = new URLSearchParams();
  if (week) params.set("week", week);
  const query = params.toString();
  const response = await rawFetch(`/hub/attendance/export${query ? `?${query}` : ""}`, {
    credentials: "include",
    cache: "no-store",
  });
  if (!response.ok) return parseResponse(response); // always throws
  const disposition = response.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename="?([^";]+)"?/i);
  return { blob: await response.blob(), filename: match ? match[1] : "attendance.csv" };
}
```

- [ ] **Step 4: Run the tests**

Run: `npx vitest run tests/frontend/unit/`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/static/api.js tests/frontend/helpers/endpointTable.js tests/frontend/unit/api.shapes.test.js
git commit -m "feat(attendance): api.js wrapper for the attendance CSV"
```

---

### Task 7: The comparison grid

**Files:**
- Create: `backend/static/views/hubAttendanceCompare.js`
- Modify: `backend/static/tips.js` (after `hub.timesheets`)
- Modify: `tests/frontend/helpers/factories.js::attendanceWeek` (~line 597)
- Test: `tests/frontend/views/hubAttendanceCompare.test.js` (create)

**Interfaces:**
- Consumes: the Task 4 payload; `apiExportHubAttendance` (Task 6).
- Produces: `mountHubAttendanceCompare(container, payload, { onWeekChange })`. Pure view: it fetches nothing but the export blob, holds no state, and re-renders only from the payload it was handed.

- [ ] **Step 1: Extend the factory, then write the failing test**

In `tests/frontend/helpers/factories.js`, give `attendanceWeek` the new fields so every existing caller keeps working: on `blank(date)` add `tracked_minutes: 0, delta_minutes: 0, outside_shift_minutes: 0, adjustment_minutes: 0`; on `monday` add `tracked_minutes: 420, delta_minutes: 60, outside_shift_minutes: 0, adjustment_minutes: 0`; on the row add `tracked_minutes: 420, delta_minutes: 60`; on the week object add `tracked_minutes: 420, delta_minutes: 60`.

`tests/frontend/views/hubAttendanceCompare.test.js`:

```js
import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { server } from "../helpers/handlers.js";
import { attendanceWeek } from "../helpers/factories.js";
import { mountView } from "../helpers/shell.js";

const user = () => userEvent.setup();

async function mount(payload = attendanceWeek(), options = {}) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const mod = await mountView("views/hubAttendanceCompare.js");
  mod.mountHubAttendanceCompare(host, payload, options);
  return host;
}

describe("the comparison grid", () => {
  it("prints clocked over charged with the gap between them", async () => {
    const host = await mount();
    const cell = host.querySelector(".hub-compare-cell");
    expect(cell.querySelector(".hub-compare-clocked").textContent).toBe("8:00");
    expect(cell.querySelector(".hub-compare-tracked").textContent).toBe("7:00");
    expect(cell.querySelector(".hub-compare-delta").textContent).toContain("1:00");
  });

  it("names every number in the cell's accessible label, not by colour alone", async () => {
    const host = await mount();
    const label = host.querySelector(".hub-compare-cell").getAttribute("aria-label");
    expect(label).toContain("8:00 clocked");
    expect(label).toContain("7:00 charged");
    expect(label).toContain("1:00 off job");
  });

  it("flags charged time outside the shift with a glyph and words", async () => {
    const payload = attendanceWeek();
    payload.rows[0].days[0].outside_shift_minutes = 45;
    const host = await mount(payload);
    const flag = host.querySelector(".hub-compare-flag-outside");
    expect(flag).not.toBeNull();
    expect(flag.textContent).toContain("0:45 charged outside shift");
  });

  it("shows an adjustment beside the wall-clock numbers, never inside them", async () => {
    const payload = attendanceWeek();
    payload.rows[0].days[0].adjustment_minutes = 30;
    const host = await mount(payload);
    const cell = host.querySelector(".hub-compare-cell");
    expect(cell.textContent).toContain("+0:30 adjusted");
    expect(cell.querySelector(".hub-compare-tracked").textContent).toBe("7:00");
  });

  it("hides the adjustment line when there is none", async () => {
    const host = await mount();
    expect(host.querySelector(".hub-compare-adjustment")).toBeNull();
  });

  it("pages the week by a whole week at a time", async () => {
    const weeks = [];
    const host = await mount(attendanceWeek(), { onWeekChange: (w) => weeks.push(w) });
    await user().click(host.querySelector(".hub-compare-prev"));
    await user().click(host.querySelector(".hub-compare-next"));
    expect(weeks).toEqual(["2026-09-07", "2026-09-21"]);
  });

  it("says a short week is short rather than letting it read as lost hours", async () => {
    const host = await mount(attendanceWeek({ week_hours: 167 }));
    expect(host.querySelector(".hub-compare-dst").textContent).toContain("167");
  });

  it("downloads the CSV and reports the filename", async () => {
    server.use(http.get("/hub/attendance/export", () => new HttpResponse("x", {
      headers: { "Content-Disposition": 'attachment; filename="attendance_2026-09-14.csv"' },
    })));
    const host = await mount();
    await user().click(host.querySelector(".hub-compare-export"));
    await vi.waitFor(() => expect(host.querySelector(".hub-compare-message").textContent)
      .toContain("attendance_2026-09-14.csv"));
  });

  it("explains a refused export without losing the grid", async () => {
    server.use(http.get("/hub/attendance/export", () =>
      HttpResponse.json({ detail: "Nope." }, { status: 403 })));
    const host = await mount();
    await user().click(host.querySelector(".hub-compare-export"));
    await vi.waitFor(() => expect(host.querySelector(".hub-compare-message").className)
      .toContain("error"));
    expect(host.querySelector(".hub-compare-table")).not.toBeNull();
  });

  it("says nobody clocked in rather than drawing an empty table", async () => {
    const host = await mount(attendanceWeek({ rows: [] }));
    expect(host.querySelector(".hub-compare-table")).toBeNull();
    expect(host.querySelector(".hub-compare-empty")).not.toBeNull();
  });
});
```

`URL.createObjectURL` does not exist in jsdom — check `tests/frontend/helpers/browserStubs.js` for the stub `hubTimesheets.test.js` uses for the same download and reuse it; do not write a second one.

- [ ] **Step 2: Run it and watch it fail**

Run: `npx vitest run tests/frontend/views/hubAttendanceCompare.test.js`
Expected: FAIL — cannot resolve `views/hubAttendanceCompare.js`.

- [ ] **Step 3: Write the view**

Copy the date/`formatHm`/`userName` helpers from `hubAttendanceHours.js` verbatim (both modules print `H:MM` and Central instants; `format.js`'s `N h M m` is a different rendering with the same name and must not be imported here — see `open-work.md`'s note on the two `formatHm`s).

The module's shape:

```js
// View: the Admin Timesheets tab's **Charged vs clocked** sub-feature.
//
// Layer: views. No fetch but the export blob, no state: everything on screen
// comes from the payload `hubTimesheetsTab.js` hands in -- the same payload
// the Hours grid reads, so the two sub-tabs cannot disagree about a week.
//
// **Three numbers, never blurred** (spec §8). Clocked is time on shift, the
// pay number. Charged is real wall-clock on jobs. Off job is `clocked -
// charged`, floored at zero, and means exactly that. There is no billed
// column: billing rounds a whole work order's labor up to 30 minutes, so no
// honest per-person-per-day billed number exists.
//
// Two flags, in opposite directions and both possible on one day: `⚠ charged
// outside shift` is time on a job that no punch covers (§9 allows it and
// flags it), and `+0:30 adjusted` is hand-entered labor, which has no start
// or stop and is therefore never inside either wall-clock number.
//
// Every flag prints its glyph *and* its words: design-system.md keeps status
// hues to badges, and nothing here may be readable by colour alone.
```

Cell markup — a `<div>`, not a `<button>`: there is no drill-down here, and the detail this grid could expand already has a home in Hours.

```js
function cellHtml(day) {
  const outside = day.outside_shift_minutes > 0
    ? `<span class="hub-compare-flag hub-compare-flag-outside"><span aria-hidden="true">⚠</span> ${escapeHtml(formatHm(day.outside_shift_minutes))} charged outside shift</span>`
    : "";
  const adjusted = day.adjustment_minutes > 0
    ? `<span class="hub-compare-adjustment">+${escapeHtml(formatHm(day.adjustment_minutes))} adjusted</span>`
    : "";
  return `<div class="hub-compare-cell" aria-label="${escapeHtml(cellLabel(day))}">
    <span class="hub-compare-clocked">${formatHm(day.clocked_minutes)}</span>
    <span class="hub-compare-tracked">${formatHm(day.tracked_minutes)}</span>
    <span class="hub-compare-delta">Δ ${formatHm(day.delta_minutes)}</span>
    ${outside}${adjusted}
  </div>`;
}
```

`cellLabel(day)` builds `"${name}, ${longDateLabel(day.date)}, 8:00 clocked, 7:00 charged, 1:00 off job"` plus `", 0:45 charged outside shift"` and `", 0:30 adjusted"` when non-zero — the whole cell in words, because a stack of three bare figures is unreadable to a screen reader.

The rest of the section, in order: a toolbar with `◀`/`▶` (`.hub-compare-prev` / `.hub-compare-next`, calling `onWeekChange(shiftMonday(payload.week_start, ∓7))`), the week label, `tipHtml("hub.charged-vs-clocked")` and an `Export CSV` button (`.hub-compare-export`); a `aria-live="polite"` `.hub-compare-message`; the table (`.hub-compare-table`, person column, seven day columns, a `Week` column showing `total_minutes` over `tracked_minutes` over `Δ delta_minutes`, and a `Company total` `tfoot` built the same way from `totals_by_day` / `tracked_minutes` / `delta_minutes`); the DST line (`.hub-compare-dst`, same copy as the Hours grid); and a legend:

```
Clocked = time on shift, the pay number. Charged = time on a work-order
clock. Δ = on shift, not on a job. ⚠ = charged with no punch covering it.
Adjusted = hand-entered labor, which has no start or stop and is counted in
neither column.
```

The export handler is the download dance from `hubTimesheets.js::downloadCsv`, unchanged but for the wrapper, the class names, and the `attendance` copy: disable the button, `Preparing export…`, blob → object URL → click → revoke, `Exported <filename>.` on success, `friendlyError(err, "Could not export attendance.")` on failure, re-enable in `finally`.

Empty state: when `payload.rows.length === 0`, render `<p class="hint hub-compare-empty">Nobody clocked in this week.</p>` in place of the table, keeping the toolbar.

Then in `tips.js`, after the `hub.timesheets` entry:

```js
  "hub.charged-vs-clocked": {
    label: "Charged vs clocked",
    text: "Clocked is time on shift, the number payroll uses. Charged is time on a work-order clock. The difference is time on shift with no job running. A warning flag means charged time that no punch covers, which is allowed and shown rather than refused. Hand-entered labor adjustments have no start or stop and are counted in neither column.",
  },
```

- [ ] **Step 4: Run the tests**

Run: `npx vitest run tests/frontend/views/hubAttendanceCompare.test.js tests/frontend/unit/tips.test.js`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/static/views/hubAttendanceCompare.js backend/static/tips.js tests/frontend/helpers/factories.js tests/frontend/views/hubAttendanceCompare.test.js
git commit -m "feat(attendance): the charged-vs-clocked grid"
```

---

### Task 8: One week payload, three sub-tabs

**Files:**
- Modify: `backend/static/views/hubTimesheetsTab.js`
- Test: `tests/frontend/views/hubTimesheetsTab.test.js`

**Interfaces:**
- Consumes: `mountHubAttendanceCompare` (Task 7).
- Produces: no new exports. `renderTimesheetsTab(panelEl, { role })` and `resetTimesheetsTab(panelEl)` keep their signatures.

- [ ] **Step 1: Write the failing tests**

Append to `tests/frontend/views/hubTimesheetsTab.test.js`, and update the two existing sub-nav assertions that expect **two** buttons to expect **three**:

```js
describe("Charged vs clocked", () => {
  it("gives an Admin three sub-tabs, opening on Hours", async () => {
    await openTimesheets({ role: "admin" });
    await vi.waitFor(() => expect(panel().querySelector(".hub-hours-table")).not.toBeNull());
    expect([...panel().querySelectorAll(".sub-nav-btn")].map((b) => b.dataset.feature))
      .toEqual(["hours", "compare", "crew"]);
  });

  it("reuses the week already fetched for Hours instead of fetching twice", async () => {
    await openTimesheets({ role: "admin" });
    await vi.waitFor(() => expect(panel().querySelector(".hub-hours-table")).not.toBeNull());
    await user().click(panel().querySelector('.sub-nav-btn[data-feature="compare"]'));
    await vi.waitFor(() => expect(panel().querySelector(".hub-compare-table")).not.toBeNull());
    expect(queries("/hub/attendance/week")).toHaveLength(1);
  });

  it("pages the week from the comparison and lands Hours on the same week", async () => {
    await openTimesheets({ role: "admin" });
    await vi.waitFor(() => expect(panel().querySelector(".hub-hours-table")).not.toBeNull());
    await user().click(panel().querySelector('.sub-nav-btn[data-feature="compare"]'));
    await vi.waitFor(() => expect(panel().querySelector(".hub-compare-table")).not.toBeNull());
    await user().click(panel().querySelector(".hub-compare-prev"));
    await vi.waitFor(() => expect(queries("/hub/attendance/week")).toHaveLength(2));
    expect(queries("/hub/attendance/week")[1]).toEqual({ week: "2026-09-07" });

    await user().click(panel().querySelector('.sub-nav-btn[data-feature="hours"]'));
    expect(panel().querySelector(".hub-hours-toolbar").textContent).toContain("Sep 7");
    expect(queries("/hub/attendance/week")).toHaveLength(2);
  });

  it("repaints both sub-tabs from one refetch after a punch edit", async () => {
    await openTimesheets({ role: "admin" });
    await vi.waitFor(() => expect(panel().querySelector(".hub-hours-table")).not.toBeNull());
    await user().click(panel().querySelector(".hub-hours-cell"));
    await user().click(panel().querySelector(".hub-hours-edit"));
    await user().click(panel().querySelector(".punch-editor-save"));
    await vi.waitFor(() => expect(queries("/hub/attendance/week")).toHaveLength(2));

    await user().click(panel().querySelector('.sub-nav-btn[data-feature="compare"]'));
    await vi.waitFor(() => expect(panel().querySelector(".hub-compare-table")).not.toBeNull());
    expect(queries("/hub/attendance/week")).toHaveLength(2);
  });

  it("gives a Supervisor no comparison sub-tab and no attendance fetch", async () => {
    await openTimesheets({ role: "supervisor" });
    await vi.waitFor(() => expect(panel().querySelector(".hub-timesheet-table")).not.toBeNull());
    expect(panel().querySelector('[data-feature="compare"]')).toBeNull();
    expect(queries("/hub/attendance/week")).toHaveLength(0);
  });
});
```

Confirm the punch-editor save button's class against `hubAttendancePunchEditor.js` before relying on `.punch-editor-save`, and match whatever the existing write tests in this file already click.

- [ ] **Step 2: Run them and watch them fail**

Run: `npx vitest run tests/frontend/views/hubTimesheetsTab.test.js`
Expected: FAIL — two sub-nav buttons, no `compare` feature.

- [ ] **Step 3: Rename the cache and add the feature**

The module currently keeps `hoursPayload` / `hoursWeek` / `hoursRequestId`. Both Admin features read the same endpoint, so collapse them into one cache — `weekPayload`, `week`, `weekRequestId` — and rename `loadHours` → `loadWeek`, `showHoursError` → `showWeekError`. The crew cache is untouched; P4b deletes it.

- `buildShell` gains the middle button and panel for Admin, unchanged below Admin:

```js
  const nav = canSeeHours(role)
    ? `<nav class="sub-nav hub-sub-nav" aria-label="Timesheet views">
         <button type="button" class="sub-nav-btn active" data-feature="hours">Hours</button>
         <button type="button" class="sub-nav-btn" data-feature="compare">Charged vs clocked</button>
         <button type="button" class="sub-nav-btn" data-feature="crew">Crew time</button>
       </nav>`
    : "";
```

with a matching `<section class="feature-panel" data-feature="compare" hidden></section>` beside the hours panel.

- `showWeekError` renders into **whichever** Admin feature is showing, so a failed load is not reported into a hidden panel: take the feature name as an argument, default to `panelEl.dataset.activeFeature`.
- `loadWeek(panelEl)` fetches once and calls `renderWeek(panelEl)`, which dispatches on `panelEl.dataset.activeFeature`: `hours` → the existing `renderHours`, `compare` → `renderCompare`.
- `renderCompare(panelEl)` mounts the new view with the shared week setter:

```js
function renderCompare(panelEl) {
  const mount = featurePanel(panelEl, "compare");
  if (!mount || !weekPayload) return;
  mountHubAttendanceCompare(mount, weekPayload, {
    onWeekChange: (nextWeek) => {
      week = nextWeek;
      void loadWeek(panelEl);
    },
  });
}
```

- `showFeature` gets a `compare` branch: repaint from `weekPayload` if it is there, else `loadWeek`. Both Admin features now share one `if (weekPayload) render… else loadWeek(…)` path — write it once and dispatch.
- `resetTimesheetsTab` clears the single week cache and bumps the single counter.
- Update the module header: three features today, `compare` reads the same payload as `hours`, and P4b removes `crew`.

- [ ] **Step 4: Check the file length**

Run: `npx eslint backend/static/views/hubTimesheetsTab.js && wc -l backend/static/views/hubTimesheetsTab.js`
Expected: clean, and under 500 lines. The rename should leave it near its current 247 — if it has grown past ~300, the crew half is the part to move out, and that is P4b's deletion, not a new module here.

- [ ] **Step 5: Run the frontend suite**

Run: `npx vitest run tests/frontend/views/hubTimesheetsTab.test.js tests/frontend/views/hubAttendanceHours.test.js tests/frontend/views/userHub.test.js`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/static/views/hubTimesheetsTab.js tests/frontend/views/hubTimesheetsTab.test.js
git commit -m "feat(attendance): the Charged vs clocked sub-tab, on one shared week"
```

---

### Task 9: Styles, docs, and the full-suite gate

**Files:**
- Modify: `backend/static/styles.css` (after the `.hub-hours-*` block P3 added)
- Modify: `docs/endpoint-map.md`, `docs/current-state.md`, `docs/open-work.md`

- [ ] **Step 1: Add the styles**

After the `.hub-hours-*` rules, add a `.hub-compare-*` block: the cell is a vertical stack (`display: grid; gap: 2px`), `.hub-compare-clocked` at the panel's normal weight, `.hub-compare-tracked` and `.hub-compare-delta` one step down in size and at `--color-text-muted` (use whatever muted token the Hours block already uses), `.hub-compare-flag-outside` in `--color-error` as **text**, and `.hub-compare-adjustment` in the same muted tone. Reuse `.hub-hours-table-wrap` / `.hub-hours-table` sizing rules by extending their selector lists rather than copying the declarations. No new colour token, no fill: `design-system.md` allows `--color-error` as text or a left-accent rule, and that is what this uses.

Check the result at phone width — seven numeric columns of three stacked figures is the layout most likely to overflow; the table wrapper already scrolls horizontally, so confirm it does here too.

- [ ] **Step 2: Endpoint map**

`docs/endpoint-map.md`: update the H8 row's service chain to `attendance_compare.week_payload` → `attendance_week.week_payload` + `labor_summary.crew_range_summaries` (`cap_running=True`), and its table list to add `work_order_labor_sessions (r)`, `work_order_labor (r)`, `work_orders (r)` — still no writes, still no locks. Add an H12 row for `GET /hub/attendance/export?week=`, **admin only**, `apiExportHubAttendance`, `hubAttendanceCompare.js`. Add `hubAttendanceCompare.js` to H8's frontend column. In the schemas section, extend the attendance week entry with the four new day fields and the two new row/week fields, and say plainly that there is no billed column and why.

- [ ] **Step 3: current-state.md**

Extend the Attendance row (line ~113) with `services/attendance_compare.py`, `static/views/hubAttendanceCompare.js`, the export route, and the new tests. Add one sentence to the three-numbers note at line ~378: the comparison shows clocked, charged and their difference; charged time no punch covers is flagged, not refused; adjustments are carried beside both and counted in neither; billed is deliberately absent because it rounds per work order. Delete anything the edit makes stale rather than letting both readings stand.

- [ ] **Step 4: open-work.md**

Rewrite IMP-041's remaining-work list: P4a shipped (comparison grid, export, the read-side cap). P4b remains — live roster, `attendance.changed`, the Timesheets tab's move to Admin+, the §7 retirement of `GET /hub/timesheets` (which also retires `MAX_TIMESHEET_RANGE_DAYS`, `TimesheetRangeInvalidError` and `TimesheetRangeTooLargeError`, whose only caller is `timesheets_hub`, contrary to spec §7's expectation). Add one bullet for the deferred billed column, naming the reason: billing rounds a work order's combined labor up to 30 minutes across people and days, so a per-person-per-day billed figure would be an approximation of an invoice in a column that reads as a fact.

- [ ] **Step 5: Run everything**

```bash
cd backend && python -m pytest -q
cd .. && npx vitest run
```
Expected: both green. The frontend suite's baseline before this plan is 87 files / 2186 tests; this plan adds one file and should add no failures anywhere else.

- [ ] **Step 6: Commit**

```bash
git add backend/static/styles.css docs/
git commit -m "docs(attendance): P4a — the comparison grid, the CSV, and what P4b still owes"
```

---

## What P4b inherits

Recorded here so the next plan does not re-derive it:

- **The live roster** (spec §6) — `GET /hub/attendance/live`, the `shift_state` colours, sorting red → yellow → green by longest idle, the `N not clocked in` footer, and client-side idle ticking from `started_at` + skew. It must decide that an open labor session past `LABOR_SESSION_MAX_MINUTES` is **not** "charging" — otherwise a forgotten clock reads green forever. `capped_session_end` (Task 1) is the function that answers it.
- **`attendance.changed`** — audience Admin, `id: None` like `labor.session.changed`, emitted from the four self-scoped punch routes and the three admin punch writes. The auto-punch on a work-order clock start needs no emit of its own: that route already emits `labor.session.changed`, which the live layer also subscribes to.
- **The retirement** (§7, D6) — delete routes H3/H4, `timesheets_hub` + `timesheet_csv`, `views/hubTimesheets.js`, the two api.js wrappers, the `crew` feature here, and their tests; move the Timesheets tab to Admin+ in `userHub.js`; amend the role-gate expected set again. **Keep** `labor_summary.crew_range_summaries` — P4a made the comparison its caller. **Keep** the `.hub-timesheet-table*` CSS: `hubGraphs.js` and `hubReport.js` both borrow those classes.
