# Attendance P2 — Timesheets sub-nav, the Hours grid, and the card self-close

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Admins a Monday-anchored weekly grid of *clocked* attendance hours — read-only, with a per-day drill-down of the punch rows behind each cell — and let a technician resolve a stale punch from the work-order card instead of navigating to the Home tab.

**Architecture:** One new Admin-floored read, `GET /hub/attendance/week`, assembled in a new `services/attendance_week.py` that reuses `domain/labor_day.py` for every day boundary so the attendance week *is* the work-order report's week. The Timesheets tabpanel gains a sub-nav (`views/subnav.js`, unchanged) hosting **Hours** (new, admin+) beside today's existing crew grid; the tab's lazy-load machinery moves out of `userHub.js` into a `views/hubTimesheetsTab.js` that owns both sub-features. The work-order card's 409 on Start is resolved by re-reading `GET /attendance/me` — no new backend contract.

**Tech Stack:** FastAPI + SQLAlchemy + Pydantic v2 (backend), pytest (backend tests), vanilla ES modules + Vitest/MSW/jsdom (frontend).

**Spec:** `docs/superpowers/specs/2026-09-21-attendance-timesheet-design.md` — §4 (endpoints), §6 (frontend), §8 (time semantics), §9 (validation), §10 (testing), §11 (phasing). P1's plan, for shape and conventions: `docs/superpowers/plans/2026-09-21-attendance-p1-punch-and-home.md`.

## Global Constraints

- **Three numbers stay apart (§8).** P2 ships **clocked** only — real wall-clock on shift, from `attendance_punches`. Nothing in this phase reads `billed_labor_minutes` or `labor_summary`. `tracked` / `billed` are added to the same payload additively in P4.
- **Week definition is borrowed, never redefined.** `work_order_report.resolve_week` resolves `?week=`; `labor_day.day_bounds` / `week_bounds_containing` bracket the days. A non-Monday is **422**, matching `resolve_week`.
- **The new read is Admin-floored** (`roles.ROLE_ADMIN`, not `ROLE_TECHFM_OA`). It is a pay record (D1). `tests/test_route_role_gates.py::test_no_route_gate_is_left_at_the_admin_floor`'s expected set grows to `{get_hub_report, export_hub_report, get_hub_attendance_week}`, with the reason written into the test — the way that test is built to require.
- **D6 does not land in this phase.** `GET /hub/timesheets` stays live and Supervisor-floored; the Timesheets *tab* stays supervisor+. Only the **Hours** sub-feature is admin+. The retirement is P4.
- **Read-only.** No edit, add or delete of punches; no `attendance_punch_edits` writes; no `promptTime` in the grid. Those are P3.
- **Side-effect-free read (§4).** No `sweep_stale_sessions`, no row locks, no commit on the week endpoint.
- **CSP drops `style=`.** No inline style attributes in any template literal; use classes.
- **No nested buttons.** A cell is a `<button>`; nothing inside it may be a button.
- **Cross-midnight punches are owned by the day they started (§9).** The following day's cell carries the minutes and the punch row is marked `carried` — P3 reads that flag to withhold the edit button.
- **Files stay under 500 lines.** `userHub.js` is already 616 (standing note `N-HUB-TAB-SHELL`); Task 5 moves ~45 lines out of it and adds ~12, so it shrinks. The `hubTabs.js` extraction that note describes is explicitly **not** in scope.
- **Commit trailer:** every commit in this plan ends with `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.

---

## File Structure

| File | Responsibility |
|---|---|
| **Create** `backend/app/services/attendance_week.py` | Assemble the week payload: population, one range query for punches, per-day clipping, tallies. Kept out of `services/attendance.py` (which owns punch *writes*) because P4 grows this module with the charged join, the live roster, and the CSV. |
| **Modify** `backend/app/schemas/attendance.py` | Add the five week response models. Reuses `schemas.hub.HubUser` for identity. |
| **Modify** `backend/app/routers/hub.py` | Add `GET /hub/attendance/week`, Admin floor, `resolve_week` for `?week=`. |
| **Modify** `backend/tests/test_route_role_gates.py` | Amend the Admin-floor expected set, with the reason. |
| **Create** `backend/tests/test_attendance_week_service.py` | Population, clipping, carried minutes, open punches, DST week, tallies. |
| **Create** `backend/tests/test_attendance_week_router.py` | 200 / 403 / 422 over real HTTP. |
| **Modify** `backend/static/api.js` | `apiGetHubAttendanceWeek({ week })`. |
| **Modify** `tests/frontend/helpers/endpointTable.js` | Its wire-contract row. |
| **Create** `backend/static/views/hubAttendanceHours.js` | Render the Hours grid + drill-down. Pure view: payload in, DOM out, one `onWeekChange` callback. Mirrors `hubTimesheets.js`. |
| **Create** `backend/static/views/hubTimesheetsTab.js` | Own the Timesheets tabpanel: build the sub-nav shell once, `initSubNav`, and both sub-features' lazy loads, caches and request counters. Absorbs `loadTimesheets` + `showTimesheetLoadError` from `userHub.js`. |
| **Modify** `backend/static/views/userHub.js` | Delegate the whole Timesheets tab to the new module; drop the absorbed functions and state. |
| **Modify** `backend/static/styles.css` | Hours grid + sub-nav-inside-a-tabpanel spacing. `.sub-nav` / `.sub-nav-btn` chrome already exists and is reused unchanged. |
| **Create** `tests/frontend/views/hubAttendanceHours.test.js` | Grid, tally, drill-down, flags, DST footer, empty state. |
| **Create** `tests/frontend/views/hubTimesheetsTab.test.js` | Sub-nav presence by role, lazy fetch per feature, week paging, error + retry. |
| **Modify** `tests/frontend/helpers/factories.js`, `helpers/hub.js`, `helpers/handlers.js` | `attendanceWeek()` factory and its MSW handler. |
| **Modify** `backend/static/views/workOrderActions.js` | The D5 self-close on a Start 409. |
| **Create** `tests/frontend/views/workOrderStartPunch.test.js` | The 409 → prompt → self-close → retry path, and the non-stale 409 path. |
| **Modify** `docs/endpoint-map.md`, `docs/current-state.md`, `docs/open-work.md` | One row / one block / backlog trim. |

---

### Task 1: The week payload service

**Files:**
- Create: `backend/app/services/attendance_week.py`
- Test: `backend/tests/test_attendance_week_service.py`

**Interfaces:**
- Consumes: `app.domain.labor_day` (`day_bounds`, `central_date_of`, `overlap_minutes`, `as_utc`), `app.domain.roles.WORK_ORDER_TECHNICIAN_ROLES`, `app.models.AttendancePunch`, `app.models.User`.
- Produces: `week_payload(db, *, week_start: date, now: datetime) -> AttendanceWeek`, and the frozen dataclasses `AttendanceWeek`, `WeekRow`, `WeekDay`, `WeekPunch`, `DayTotal`. Task 2's schemas validate straight off these attribute names.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_attendance_week_service.py`:

```python
"""The Hours payload: population, per-day clipping, tallies (spec §6).

Clocked minutes only (§8) -- nothing here reads a labor session or a billed
number. Day boundaries come from `domain.labor_day`, so the DST case is a
test of the reuse, not of re-derived arithmetic.
"""
import os, sys, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, datetime, timedelta, timezone

from app.domain import labor_day
from app.models import AttendancePunch, User
from app.services import attendance_week
from app.services import auth as auth_service


def _user(db, role="technician", first="Ann", last="Lee"):
    user = User(username=f"u-{uuid.uuid4().hex[:10]}",
                password_hash=auth_service.hash_password("hunter2"),
                role=role, first_name=first, last_name=last)
    db.add(user); db.flush()
    return user


def _punch(db, user, started_at, ended_at=None, needs_review=False):
    punch = AttendancePunch(id=uuid.uuid4(), user_id=user.id, started_at=started_at,
                            ended_at=ended_at, start_source="manual",
                            end_source=None if ended_at is None else "manual",
                            needs_review=needs_review)
    db.add(punch); db.flush()
    return punch


# Monday 2026-09-14 08:00 Central == 13:00 UTC (CDT).
MONDAY = date(2026, 9, 14)
NOW = datetime(2026, 9, 20, 23, 0, tzinfo=timezone.utc)


def _row_for(payload, user):
    return next(row for row in payload.rows if row.user.id == user.id)


def test_a_closed_punch_lands_on_its_own_day(db):
    user = _user(db)
    _punch(db, user, datetime(2026, 9, 14, 13, 0, tzinfo=timezone.utc),
           datetime(2026, 9, 14, 21, 0, tzinfo=timezone.utc))
    db.commit()

    payload = attendance_week.week_payload(db, week_start=MONDAY, now=NOW)

    row = _row_for(payload, user)
    monday = next(day for day in row.days if day.date == MONDAY)
    assert monday.clocked_minutes == 480
    assert row.total_minutes == 480
    assert len(monday.punches) == 1
    assert monday.punches[0].carried is False
    assert monday.punches[0].open is False


def test_a_cross_midnight_punch_carries_into_the_next_day(db):
    user = _user(db)
    # 10 PM Central Monday -> 2 AM Central Tuesday: 2h Monday, 2h Tuesday.
    _punch(db, user, datetime(2026, 9, 15, 3, 0, tzinfo=timezone.utc),
           datetime(2026, 9, 15, 7, 0, tzinfo=timezone.utc))
    db.commit()

    row = _row_for(attendance_week.week_payload(db, week_start=MONDAY, now=NOW), user)
    by_date = {day.date: day for day in row.days}
    assert by_date[MONDAY].clocked_minutes == 120
    assert by_date[MONDAY].punches[0].carried is False
    assert by_date[MONDAY + timedelta(days=1)].clocked_minutes == 120
    assert by_date[MONDAY + timedelta(days=1)].punches[0].carried is True
    assert row.total_minutes == 240


def test_an_open_punch_counts_to_now_and_is_flagged(db):
    user = _user(db)
    _punch(db, user, NOW - timedelta(hours=2))
    db.commit()

    row = _row_for(attendance_week.week_payload(db, week_start=MONDAY, now=NOW), user)
    today = next(day for day in row.days if day.date == labor_day.central_date_of(NOW))
    assert today.clocked_minutes == 120
    assert today.punches[0].open is True
    assert today.has_open is True


def test_needs_review_propagates_to_the_day(db):
    user = _user(db)
    _punch(db, user, datetime(2026, 9, 14, 13, 0, tzinfo=timezone.utc),
           datetime(2026, 9, 14, 21, 0, tzinfo=timezone.utc), needs_review=True)
    db.commit()

    row = _row_for(attendance_week.week_payload(db, week_start=MONDAY, now=NOW), user)
    monday = next(day for day in row.days if day.date == MONDAY)
    assert monday.needs_review is True
    assert monday.punches[0].needs_review is True


def test_live_crew_appear_with_zero_hours(db):
    user = _user(db, role="technician")
    db.commit()

    payload = attendance_week.week_payload(db, week_start=MONDAY, now=NOW)

    row = _row_for(payload, user)
    assert row.total_minutes == 0
    assert len(row.days) == 7
    assert all(day.clocked_minutes == 0 for day in row.days)


def test_an_admin_who_punched_is_included_though_not_crew(db):
    admin = _user(db, role="admin", first="Dee", last="Ops")
    _punch(db, admin, datetime(2026, 9, 14, 13, 0, tzinfo=timezone.utc),
           datetime(2026, 9, 14, 14, 0, tzinfo=timezone.utc))
    db.commit()

    payload = attendance_week.week_payload(db, week_start=MONDAY, now=NOW)

    assert _row_for(payload, admin).total_minutes == 60


def test_an_archived_user_without_punches_is_absent(db):
    gone = _user(db, first="Old", last="Hand")
    gone.archived_at = NOW
    db.commit()

    payload = attendance_week.week_payload(db, week_start=MONDAY, now=NOW)

    assert all(row.user.id != gone.id for row in payload.rows)


def test_rows_sort_by_name_and_totals_add_up(db):
    zed = _user(db, first="Zed", last="Aaron")
    amy = _user(db, first="Amy", last="Zephyr")
    _punch(db, zed, datetime(2026, 9, 14, 13, 0, tzinfo=timezone.utc),
           datetime(2026, 9, 14, 14, 0, tzinfo=timezone.utc))
    _punch(db, amy, datetime(2026, 9, 14, 13, 0, tzinfo=timezone.utc),
           datetime(2026, 9, 14, 15, 0, tzinfo=timezone.utc))
    db.commit()

    payload = attendance_week.week_payload(db, week_start=MONDAY, now=NOW)

    names = [f"{row.user.first_name} {row.user.last_name}" for row in payload.rows]
    assert names.index("Amy Zephyr") < names.index("Zed Aaron")
    assert payload.total_minutes == 180
    assert next(t for t in payload.totals_by_day if t.date == MONDAY).minutes == 180


def test_the_spring_forward_week_is_167_hours(db):
    # 2026-03-08 is the US spring-forward Sunday; its week starts 2026-03-02.
    payload = attendance_week.week_payload(
        db, week_start=date(2026, 3, 2),
        now=datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc))

    assert payload.week_hours == 167
    assert payload.week_start == date(2026, 3, 2)
    assert payload.week_end == date(2026, 3, 8)
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `cd backend && python -m pytest tests/test_attendance_week_service.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'app.services.attendance_week'`.

- [ ] **Step 3: Write the implementation**

Create `backend/app/services/attendance_week.py`:

```python
"""The Admin Hours payload: one week of clocked time, per person per day.

Layer: services. Read-only and **side-effect-free** (spec §4) -- no sweep, no
row locks, no commit -- which is what will let P4's live sub-tab poll it.

Kept out of `services/attendance.py` on purpose: that module owns the punch
*writes* and their coupling to the work-order clock. This one owns the
week-shaped read, and P4 grows it with the charged column, the live roster,
and the CSV.

**Clocked only** (spec §8). Nothing here touches a labor session or
`billed_labor_minutes`. Mixing the three numbers is the likeliest way this
feature ships subtly wrong, so the module that produces the pay number does
not import the modules that produce the other two.

Every day boundary comes from `domain.labor_day`, so the week is the same
object `services.work_order_report.resolve_week` resolves rather than a
parallel definition free to drift -- and the DST week is correct because
`labor_day.day_bounds` already is.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.domain import labor_day, roles
from app.models import AttendancePunch, User


@dataclass(frozen=True)
class WeekPunch:
    """One punch, as it contributes to **one** day.

    A punch that crosses midnight appears twice -- once per day it touches --
    with `minutes` clipped to that day and `carried=True` on every day after
    the one it started on. Spec §9: the punch is owned by the day it started,
    so P3 offers its edit button only where `carried` is False.
    """

    id: uuid.UUID
    started_at: datetime
    ended_at: Optional[datetime]
    start_source: str
    end_source: Optional[str]
    needs_review: bool
    minutes: int
    carried: bool
    open: bool


@dataclass(frozen=True)
class WeekDay:
    date: date
    clocked_minutes: int
    needs_review: bool
    has_open: bool
    punches: list[WeekPunch]


@dataclass(frozen=True)
class WeekRow:
    user: User
    days: list[WeekDay]
    total_minutes: int


@dataclass(frozen=True)
class DayTotal:
    date: date
    minutes: int


@dataclass(frozen=True)
class AttendanceWeek:
    week_start: date
    week_end: date
    server_now: datetime
    days: list[date]
    rows: list[WeekRow]
    totals_by_day: list[DayTotal]
    total_minutes: int
    week_hours: int


def _week_days(week_start: date) -> list[date]:
    return [week_start + timedelta(days=offset) for offset in range(7)]


def _week_window(week_start: date) -> tuple[datetime, datetime]:
    """Half-open UTC bracket of the Central week: Monday 00:00 through the
    next Monday 00:00. Built the same way `work_order_report.week_window`
    builds it, from `labor_day.day_bounds`, so the two cannot drift."""
    start, _ = labor_day.day_bounds(week_start)
    _, end = labor_day.day_bounds(week_start + timedelta(days=6))
    return start, end


def _population(db: Session, window_start: datetime, window_end: datetime) -> list[User]:
    """Every live Supervisor and Technician, plus anyone else who punched
    inside the window.

    The first set is the crew the grid exists to pay and is present at zero
    hours, because an absent week is information. The second is spec §6's
    accepted consequence: an Admin who punches in accrues hours here even
    though the P4 roster never color-judges them.
    """
    crew = (
        db.query(User)
        .filter(
            User.role.in_(roles.WORK_ORDER_TECHNICIAN_ROLES),
            User.archived_at.is_(None),
        )
        .all()
    )
    punched_ids = {
        row[0]
        for row in db.query(AttendancePunch.user_id)
        .filter(
            AttendancePunch.started_at < window_end,
            or_(
                AttendancePunch.ended_at.is_(None),
                AttendancePunch.ended_at > window_start,
            ),
        )
        .distinct()
        .all()
    }
    extra_ids = punched_ids - {person.id for person in crew}
    extra = (
        db.query(User).filter(User.id.in_(extra_ids)).all() if extra_ids else []
    )
    return crew + extra


def _sort_key(person: User) -> str:
    return (person.full_name or "").casefold()


def week_payload(
    db: Session, *, week_start: date, now: datetime
) -> AttendanceWeek:
    """The Hours grid for the Central week beginning `week_start` (a Monday).

    `week_start` is already resolved by `work_order_report.resolve_week`, so
    a non-Monday never reaches here -- the 422 is raised at the route.
    """
    days = _week_days(week_start)
    window_start, window_end = _week_window(week_start)
    people = _population(db, window_start, window_end)
    by_id = {person.id: person for person in people}

    punches = (
        db.query(AttendancePunch)
        .filter(
            AttendancePunch.user_id.in_(list(by_id)),
            AttendancePunch.started_at < window_end,
            or_(
                AttendancePunch.ended_at.is_(None),
                AttendancePunch.ended_at > window_start,
            ),
        )
        .order_by(AttendancePunch.started_at)
        .all()
        if by_id
        else []
    )
    punches_by_user: dict[uuid.UUID, list[AttendancePunch]] = {
        person_id: [] for person_id in by_id
    }
    for punch in punches:
        punches_by_user[punch.user_id].append(punch)

    # Day bounds computed once for all seven days, not once per person-day.
    bounds = {day: labor_day.day_bounds(day) for day in days}
    totals_by_day: dict[date, int] = {day: 0 for day in days}
    rows: list[WeekRow] = []

    for person in sorted(people, key=_sort_key):
        week_days: list[WeekDay] = []
        row_total = 0
        for day in days:
            day_start, day_end = bounds[day]
            day_punches: list[WeekPunch] = []
            for punch in punches_by_user[person.id]:
                minutes = labor_day.overlap_minutes(
                    punch.started_at, punch.ended_at, day_start, day_end, now=now
                )
                if minutes == 0:
                    continue
                day_punches.append(
                    WeekPunch(
                        id=punch.id,
                        started_at=punch.started_at,
                        ended_at=punch.ended_at,
                        start_source=punch.start_source,
                        end_source=punch.end_source,
                        needs_review=bool(punch.needs_review),
                        minutes=minutes,
                        carried=labor_day.central_date_of(punch.started_at) < day,
                        open=punch.ended_at is None,
                    )
                )
            day_minutes = sum(entry.minutes for entry in day_punches)
            row_total += day_minutes
            totals_by_day[day] += day_minutes
            week_days.append(
                WeekDay(
                    date=day,
                    clocked_minutes=day_minutes,
                    needs_review=any(entry.needs_review for entry in day_punches),
                    has_open=any(entry.open for entry in day_punches),
                    punches=day_punches,
                )
            )
        rows.append(WeekRow(user=person, days=week_days, total_minutes=row_total))

    return AttendanceWeek(
        week_start=week_start,
        week_end=week_start + timedelta(days=6),
        server_now=now,
        days=days,
        rows=rows,
        totals_by_day=[DayTotal(date=day, minutes=totals_by_day[day]) for day in days],
        total_minutes=sum(totals_by_day.values()),
        # 167 or 169 across a DST transition. The grid's footer says so rather
        # than letting an Admin read a short week as missing hours.
        week_hours=round((window_end - window_start).total_seconds() / 3600),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_attendance_week_service.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/attendance_week.py backend/tests/test_attendance_week_service.py
git commit -m "$(cat <<'EOF'
feat(attendance): the weekly clocked-hours payload

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: The Admin-floored route and its schemas

**Files:**
- Modify: `backend/app/schemas/attendance.py`
- Modify: `backend/app/routers/hub.py`
- Modify: `backend/tests/test_route_role_gates.py:505` (the expected set)
- Test: `backend/tests/test_attendance_week_router.py`

**Interfaces:**
- Consumes: `attendance_week.week_payload` from Task 1; `work_order_report.resolve_week`; `schemas.hub.HubUser`.
- Produces: `GET /hub/attendance/week?week=YYYY-MM-DD` returning `AttendanceWeekResponse`; the endpoint function name `get_hub_attendance_week`, which Task 2's role-gate amendment and P4's retirement both name.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_attendance_week_router.py`:

```python
"""`GET /hub/attendance/week` at the route boundary.

Every case goes through `TestClient` rather than calling the handler
directly -- this repo has been bitten once by FastAPI parsing a signature
differently than a direct call does.
"""
import os, sys, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import AttendancePunch, User
from app.services import auth as auth_service


def _seed_user(db, role="technician", first="Ann", last="Lee"):
    user = User(username=f"u-{uuid.uuid4().hex[:10]}",
                password_hash=auth_service.hash_password("hunter2"),
                role=role, first_name=first, last_name=last)
    db.add(user); db.flush()
    return user


def _as(db, user):
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    client.cookies.set("session", auth_service.create_session(db, user))
    return client


def test_an_admin_reads_the_week(db):
    admin = _seed_user(db, role="admin", first="Dee", last="Ops")
    tech = _seed_user(db)
    db.add(AttendancePunch(
        id=uuid.uuid4(), user_id=tech.id,
        started_at=datetime(2026, 9, 14, 13, 0, tzinfo=timezone.utc),
        ended_at=datetime(2026, 9, 14, 21, 0, tzinfo=timezone.utc),
        start_source="manual", end_source="manual"))
    db.commit()
    try:
        with _as(db, admin) as client:
            response = client.get("/hub/attendance/week", params={"week": "2026-09-14"})
    finally:
        del app.dependency_overrides[get_db]

    assert response.status_code == 200
    body = response.json()
    assert body["week_start"] == "2026-09-14"
    assert body["week_end"] == "2026-09-20"
    assert len(body["days"]) == 7
    row = next(r for r in body["rows"] if r["user"]["id"] == str(tech.id))
    assert row["total_minutes"] == 480
    assert row["days"][0]["punches"][0]["minutes"] == 480


def test_techfm_oa_is_refused(db):
    # D1: this is the pay record, and it sits above the rest of the admin
    # toolkit that TechFM OA holds.
    oa = _seed_user(db, role="techfm_oa", first="Oa", last="Person")
    db.commit()
    try:
        with _as(db, oa) as client:
            response = client.get("/hub/attendance/week", params={"week": "2026-09-14"})
    finally:
        del app.dependency_overrides[get_db]
    assert response.status_code == 403


def test_a_technician_is_refused(db):
    tech = _seed_user(db)
    db.commit()
    try:
        with _as(db, tech) as client:
            response = client.get("/hub/attendance/week")
    finally:
        del app.dependency_overrides[get_db]
    assert response.status_code == 403


def test_a_non_monday_is_422(db):
    admin = _seed_user(db, role="admin", first="Dee", last="Ops")
    db.commit()
    try:
        with _as(db, admin) as client:
            response = client.get("/hub/attendance/week", params={"week": "2026-09-15"})
    finally:
        del app.dependency_overrides[get_db]
    assert response.status_code == 422


def test_no_week_means_the_week_in_progress(db):
    admin = _seed_user(db, role="admin", first="Dee", last="Ops")
    db.commit()
    try:
        with _as(db, admin) as client:
            body = client.get("/hub/attendance/week").json()
    finally:
        del app.dependency_overrides[get_db]
    assert datetime.fromisoformat(body["week_start"]).weekday() == 0
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `cd backend && python -m pytest tests/test_attendance_week_router.py -v`
Expected: every case 404 (`assert 404 == 200`) — the route does not exist.

- [ ] **Step 3: Add the schemas**

Append to `backend/app/schemas/attendance.py` (and add `from app.schemas.hub import HubUser` to its imports):

```python
class AttendanceWeekPunch(BaseModel):
    """One punch's contribution to **one** day. `minutes` is clipped to that
    day; `carried` is true on every day after the one it started on, which
    spec §9 makes the owner of the punch. `open` means still on shift, so
    `minutes` is counted to `server_now` and climbs."""

    id: uuid.UUID
    started_at: datetime
    ended_at: Optional[datetime] = None
    start_source: str
    end_source: Optional[str] = None
    needs_review: bool
    minutes: int
    carried: bool
    open: bool

    model_config = {"from_attributes": True}


class AttendanceWeekDay(BaseModel):
    date: date
    clocked_minutes: int
    needs_review: bool
    has_open: bool
    punches: list[AttendanceWeekPunch]

    model_config = {"from_attributes": True}


class AttendanceWeekRow(BaseModel):
    user: HubUser
    days: list[AttendanceWeekDay]
    total_minutes: int

    model_config = {"from_attributes": True}


class AttendanceWeekDayTotal(BaseModel):
    date: date
    minutes: int

    model_config = {"from_attributes": True}


class AttendanceWeekResponse(BaseModel):
    """Clocked time only (§8): real wall-clock on shift, never rounded.
    `tracked` and `billed` join this payload additively in P4 -- the
    comparison sub-tab reads the same object this one does.

    `week_hours` is 168, or 167 / 169 across a DST transition. The grid's
    footer prints it so a short week does not read as missing hours."""

    week_start: date
    week_end: date
    server_now: datetime
    days: list[date]
    rows: list[AttendanceWeekRow]
    totals_by_day: list[AttendanceWeekDayTotal]
    total_minutes: int
    week_hours: int

    model_config = {"from_attributes": True}
```

- [ ] **Step 4: Add the route**

In `backend/app/routers/hub.py`, extend the imports:

```python
from app.schemas.attendance import AttendanceWeekResponse
from app.services import attendance_week
```

and add the route immediately after `get_hub_graphs` (before the timesheet block, so the Admin-floored reads sit together with `report` below them):

```python
@router.get("/attendance/week", response_model=AttendanceWeekResponse)
def get_hub_attendance_week(
    week: Optional[date] = Query(None),
    user: User = Depends(require_min_role(roles.ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """The Hours grid: one Central week of clocked attendance, per person
    per day, with the punch rows behind every cell.

    **Admin, not TechFM OA.** This is the pay record (D1), so it sits above
    the rest of the admin toolkit -- `tests/test_route_role_gates.py` carries
    the matching exemption, and changing this floor means changing that test
    deliberately.

    `week` is a Monday; absent means the week in progress. Resolved by
    `work_order_report.resolve_week`, so a non-Monday is 422 here for exactly
    the same reason it is on `GET /hub/report`.

    Side-effect-free (spec §4): no sweep, no row locks, unlike
    `GET /hub/timesheets` -- which is what will let P4's live sub-tab poll.
    """
    now = datetime.now(timezone.utc)
    try:
        week_start = work_order_report.resolve_week(week, now)
    except DomainError as exc:
        raise to_http(exc) from exc
    return attendance_week.week_payload(db, week_start=week_start, now=now)
```

Add the line to the module docstring's route list, above the `GET /hub/report` line:

```
- `GET /hub/attendance/week` admin only -- the weekly clocked-hours grid
```

- [ ] **Step 5: Amend the role-gate expectation**

In `backend/tests/test_route_role_gates.py`, replace the assertion in
`test_no_route_gate_is_left_at_the_admin_floor`:

```python
    # The Admin daily report is the one genuinely Admin-only surface in the
    # app: a company-wide digest of what closed and what is closing, which
    # deliberately sits above TechFM OA despite OA holding the rest of the
    # admin toolkit -- the admin hub tiles, Graphs, and the work-order export.
    # See docs/superpowers/specs/2026-08-30-work-order-daily-report-design.md
    # §6. If that proves wrong in use, lowering the floor to techfm_oa is a
    # one-line change in the gate plus removing this exemption; nothing else in
    # the design depends on it.
    #
    # The attendance week joins it for a different reason: it is the payroll
    # record (2026-09-21-attendance-timesheet-design.md D1), and TechFM OA
    # holding the operational toolkit is not a reason to hand them everyone's
    # paid hours. P4 adds `get_hub_attendance_live` and
    # `export_hub_attendance` to this set on the same grounds.
    assert offenders == {
        "get_hub_report",
        "export_hub_report",
        "get_hub_attendance_week",
    }
```

Add the matching explicit pin beside `test_the_admin_daily_report_sits_above_techfm_oa`:

```python
def test_the_attendance_week_sits_above_techfm_oa():
    # The pay record is Admin-only (D1). Pinned separately from the set above
    # so a floor lowered by accident names itself in the failure.
    assert _min_role_for(hub_router, "get_hub_attendance_week") == roles.ROLE_ADMIN
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_attendance_week_router.py tests/test_route_role_gates.py -v`
Expected: all pass, including the two amended/added gate tests.

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas/attendance.py backend/app/routers/hub.py backend/tests/test_attendance_week_router.py backend/tests/test_route_role_gates.py
git commit -m "$(cat <<'EOF'
feat(attendance): GET /hub/attendance/week at the Admin floor

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: The api.js wrapper

**Files:**
- Modify: `backend/static/api.js` (the `--- Attendance ---` block, after `apiSelfClosePunch`)
- Modify: `tests/frontend/helpers/endpointTable.js:141`
- Test: `tests/frontend/unit/api.endpoints.test.js` (existing meta-test; no new file)

**Interfaces:**
- Produces: `apiGetHubAttendanceWeek({ week = null } = {})` → the `AttendanceWeekResponse` body. Tasks 4 and 5 import it.

- [ ] **Step 1: Write the failing test**

Add to `tests/frontend/helpers/endpointTable.js`, directly under the `apiSelfClosePunch` row:

```js
  { fn: "apiGetHubAttendanceWeek", args: [{}], url: "/hub/attendance/week", cache: "no-store" },
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `npx vitest run tests/frontend/unit/api.endpoints.test.js`
Expected: FAIL — the table names a wrapper `api.js` does not export.

- [ ] **Step 3: Write the wrapper**

Append to the `--- Attendance ---` block in `backend/static/api.js`:

```js
// The Admin Hours grid. `week` is a Monday (YYYY-MM-DD); omitted means the
// week in progress. Anything else is a 422 from the server, deliberately --
// the UI only ever sends Mondays.
export async function apiGetHubAttendanceWeek({ week = null } = {}) {
  const query = week ? `?week=${encodeURIComponent(week)}` : "";
  return jsonRequest(`/hub/attendance/week${query}`, "GET", null, { cache: "no-store" });
}
```

Match the exact `jsonRequest` call shape used by the neighbouring `apiGetHubReport` — copy its argument list rather than the sketch above if they differ.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npx vitest run tests/frontend/unit/api.endpoints.test.js tests/frontend/unit/api.shapes.test.js`
Expected: PASS. If `api.shapes.test.js` pins `?week=` permutations for `apiGetHubReport`, add the parallel case for this wrapper there.

- [ ] **Step 5: Commit**

```bash
git add backend/static/api.js tests/frontend/helpers/endpointTable.js tests/frontend/unit/api.shapes.test.js
git commit -m "$(cat <<'EOF'
feat(attendance): api.js wrapper for the weekly hours grid

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: The Hours grid view

**Files:**
- Create: `backend/static/views/hubAttendanceHours.js`
- Modify: `backend/static/styles.css`
- Modify: `tests/frontend/helpers/factories.js`
- Test: `tests/frontend/views/hubAttendanceHours.test.js`

**Interfaces:**
- Consumes: the `AttendanceWeekResponse` shape from Task 2; `escapeHtml` from `../format.js`.
- Produces: `mountHubAttendanceHours(container, payload, { onWeekChange } = {})`, where `onWeekChange(mondayIso)` receives a `YYYY-MM-DD` Monday. Task 5 calls it.
- Produces: `attendanceWeek({ ... })` factory in `tests/frontend/helpers/factories.js`.

- [ ] **Step 1: Write the factory**

Add to `tests/frontend/helpers/factories.js`:

```js
// One Monday-anchored attendance week. Defaults to the week of 2026-09-14
// with a single 8-hour Monday for one technician -- enough to assert the
// grid, the tally and one drill-down without every test building rows.
export function attendanceWeek(overrides = {}) {
  const days = ["2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17",
                "2026-09-18", "2026-09-19", "2026-09-20"];
  const blank = (date) => ({
    date, clocked_minutes: 0, needs_review: false, has_open: false, punches: [],
  });
  const monday = {
    ...blank("2026-09-14"),
    clocked_minutes: 480,
    punches: [{
      id: "punch-1",
      started_at: "2026-09-14T13:00:00Z",
      ended_at: "2026-09-14T21:00:00Z",
      start_source: "manual",
      end_source: "manual",
      needs_review: false,
      minutes: 480,
      carried: false,
      open: false,
    }],
  };
  return {
    week_start: "2026-09-14",
    week_end: "2026-09-20",
    server_now: "2026-09-16T15:00:00Z",
    days,
    rows: [{
      user: { id: "user-1", first_name: "Ann", last_name: "Lee", role: "technician" },
      days: [monday, ...days.slice(1).map(blank)],
      total_minutes: 480,
    }],
    totals_by_day: days.map((date) => ({ date, minutes: date === "2026-09-14" ? 480 : 0 })),
    total_minutes: 480,
    week_hours: 168,
    ...overrides,
  };
}
```

- [ ] **Step 2: Write the failing test**

Create `tests/frontend/views/hubAttendanceHours.test.js`:

```js
// The Admin Hours grid: cells, tally, drill-down, flags, DST footer.
//
// A pure view test -- the module fetches nothing, so the payload goes in
// directly and no MSW handler is involved.

import { beforeEach, describe, expect, it, vi } from "vitest";
import { attendanceWeek } from "../helpers/factories.js";
import { mountHubAttendanceHours } from "../../../backend/static/views/hubAttendanceHours.js";

let host;

beforeEach(() => {
  document.body.innerHTML = `<div id="host"></div>`;
  host = document.getElementById("host");
});

const cells = () => Array.from(host.querySelectorAll(".hub-hours-cell"));

describe("the grid", () => {
  it("renders one row per person and seven day cells", () => {
    mountHubAttendanceHours(host, attendanceWeek());
    expect(host.querySelectorAll("tbody tr")).toHaveLength(1);
    expect(cells()).toHaveLength(7);
    expect(host.textContent).toContain("Ann Lee");
  });

  it("prints clocked time as h:mm and tallies the week", () => {
    mountHubAttendanceHours(host, attendanceWeek());
    expect(cells()[0].textContent).toContain("8:00");
    expect(host.querySelector(".hub-hours-row-total").textContent).toContain("8:00");
    expect(host.querySelector("tfoot").textContent).toContain("8:00");
  });

  it("shows the empty state when nobody is in the payload", () => {
    mountHubAttendanceHours(host, attendanceWeek({ rows: [], totals_by_day: [], total_minutes: 0 }));
    expect(host.querySelector(".hub-hours-empty")).not.toBeNull();
    expect(host.querySelector("table")).toBeNull();
  });
});

describe("the drill-down", () => {
  it("opens a day's punch rows on a cell click and closes on a second", () => {
    mountHubAttendanceHours(host, attendanceWeek());
    cells()[0].click();
    expect(host.querySelector(".hub-hours-drilldown")).not.toBeNull();
    expect(host.querySelector(".hub-hours-drilldown").textContent).toContain("8:00");
    expect(cells()[0].getAttribute("aria-expanded")).toBe("true");
    cells()[0].click();
    expect(host.querySelector(".hub-hours-drilldown")).toBeNull();
  });

  it("says so when a day has no punches", () => {
    mountHubAttendanceHours(host, attendanceWeek());
    cells()[1].click();
    expect(host.querySelector(".hub-hours-drilldown").textContent).toContain("No punches");
  });

  it("marks a carried punch and offers no edit affordance", () => {
    const week = attendanceWeek();
    week.rows[0].days[1] = {
      date: "2026-09-15", clocked_minutes: 120, needs_review: false, has_open: false,
      punches: [{ id: "punch-1", started_at: "2026-09-15T03:00:00Z",
                  ended_at: "2026-09-15T07:00:00Z", start_source: "manual",
                  end_source: "manual", needs_review: false, minutes: 120,
                  carried: true, open: false }],
    };
    mountHubAttendanceHours(host, week);
    cells()[1].click();
    const drill = host.querySelector(".hub-hours-drilldown");
    expect(drill.textContent).toContain("carried from");
    expect(drill.querySelectorAll("button")).toHaveLength(0);
  });
});

describe("flags", () => {
  it("flags a needs_review day in the cell and the drill-down", () => {
    const week = attendanceWeek();
    week.rows[0].days[0].needs_review = true;
    week.rows[0].days[0].punches[0].needs_review = true;
    week.rows[0].days[0].punches[0].end_source = "self_reported";
    mountHubAttendanceHours(host, week);
    expect(cells()[0].querySelector(".hub-hours-flag-review")).not.toBeNull();
    cells()[0].click();
    expect(host.querySelector(".hub-hours-drilldown").textContent).toContain("needs review");
  });

  it("flags an open punch as running", () => {
    const week = attendanceWeek();
    week.rows[0].days[0].has_open = true;
    week.rows[0].days[0].punches[0].open = true;
    week.rows[0].days[0].punches[0].ended_at = null;
    week.rows[0].days[0].punches[0].end_source = null;
    mountHubAttendanceHours(host, week);
    expect(cells()[0].querySelector(".hub-hours-flag-open")).not.toBeNull();
    cells()[0].click();
    expect(host.querySelector(".hub-hours-drilldown").textContent).toContain("running");
  });
});

describe("the week bar", () => {
  it("steps back and forward by whole weeks", () => {
    const onWeekChange = vi.fn();
    mountHubAttendanceHours(host, attendanceWeek(), { onWeekChange });
    host.querySelector(".hub-hours-prev").click();
    expect(onWeekChange).toHaveBeenCalledWith("2026-09-07");
    host.querySelector(".hub-hours-next").click();
    expect(onWeekChange).toHaveBeenCalledWith("2026-09-21");
  });

  it("names a short DST week in the footer and stays quiet on a normal one", () => {
    mountHubAttendanceHours(host, attendanceWeek());
    expect(host.querySelector(".hub-hours-dst")).toBeNull();
    mountHubAttendanceHours(host, attendanceWeek({ week_hours: 167 }));
    expect(host.querySelector(".hub-hours-dst").textContent).toContain("167");
  });
});

describe("the CSP rule", () => {
  it("emits no inline style attributes", () => {
    mountHubAttendanceHours(host, attendanceWeek());
    expect(host.innerHTML).not.toMatch(/\sstyle="/);
  });
});
```

- [ ] **Step 3: Run it to make sure it fails**

Run: `npx vitest run tests/frontend/views/hubAttendanceHours.test.js`
Expected: FAIL — cannot resolve `views/hubAttendanceHours.js`.

- [ ] **Step 4: Write the view**

Create `backend/static/views/hubAttendanceHours.js`:

```js
// View: the Admin Timesheets tab's **Hours** sub-feature.
//
// Layer: views (no fetch, no state beyond which cell is open). The payload
// owns both the grid and every cell's drill-down, so opening detail never
// starts another request -- the rule hubTimesheets.js established.
//
// **Clocked time only** (spec §8): what this prints is time on shift, the pay
// number, never rounded to 30 minutes the way a billed number is. The
// comparison against tracked and billed is a different sub-tab, in P4.
//
// Read-only in P2. Editing a punch -- `[Edit]` per row, `[+ Add punch]` per
// day -- is P3, and lands inside `drilldownHtml` below. A `carried` punch
// never gets one: spec §9 gives a cross-midnight punch to the day it started.

import { escapeHtml } from "../format.js";

const CENTRAL_TIME_ZONE = "America/Chicago";

// `8:00`, not format.js's `8 h 0 m`: a seven-column grid of hours reads as a
// column of clock times. hubTimesheets.js makes the same local choice.
function formatHm(totalMinutes) {
  const minutes = Math.max(0, Math.round(Number(totalMinutes) || 0));
  return `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, "0")}`;
}

function isoDate(iso) {
  return new Date(`${iso}T00:00:00Z`);
}

function shortDateLabel(iso) {
  return isoDate(iso).toLocaleDateString([], {
    weekday: "short", month: "numeric", day: "numeric", timeZone: "UTC",
  });
}

function longDateLabel(iso) {
  return isoDate(iso).toLocaleDateString([], {
    weekday: "long", month: "short", day: "numeric", year: "numeric", timeZone: "UTC",
  });
}

function weekLabel(start, end) {
  const options = { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" };
  return `${isoDate(start).toLocaleDateString([], options)} – ${isoDate(end).toLocaleDateString([], options)}`;
}

// Punch instants are rendered in Central, not the viewer's zone: the week
// boundaries are Central by construction, so a Chicago 11 PM punch must not
// print as a different day for an Admin reading from another timezone.
function timeLabel(instant) {
  return new Date(instant).toLocaleTimeString([], {
    hour: "numeric", minute: "2-digit", timeZone: CENTRAL_TIME_ZONE,
  });
}

function dayLabel(instant) {
  return new Date(instant).toLocaleDateString([], {
    weekday: "short", timeZone: CENTRAL_TIME_ZONE,
  });
}

function userName(user) {
  return `${user?.first_name || ""} ${user?.last_name || ""}`.trim() || "Unknown";
}

function cellFlagsHtml(day) {
  let html = "";
  if (day.has_open) {
    html += `<span class="hub-hours-flag hub-hours-flag-open"><span aria-hidden="true">●</span><span class="sr-only"> still on shift</span></span>`;
  }
  if (day.needs_review) {
    html += `<span class="hub-hours-flag hub-hours-flag-review"><span aria-hidden="true">&#9888;</span><span class="sr-only"> needs review</span></span>`;
  }
  return html;
}

function cellFlagLabels(day) {
  const labels = [];
  if (day.has_open) labels.push("still on shift");
  if (day.needs_review) labels.push("needs review");
  return labels.join(", ");
}

function punchRowHtml(punch) {
  const ended = punch.open ? "running" : timeLabel(punch.ended_at);
  const notes = [];
  // Why the row is here rather than on its own day -- without this a two-hour
  // Tuesday cell with a punch stamped 10 PM Monday reads as a data error.
  if (punch.carried) notes.push(`carried from ${escapeHtml(dayLabel(punch.started_at))}`);
  if (punch.start_source === "auto_work_order") notes.push("auto, from a work-order clock");
  if (punch.needs_review) notes.push("needs review");
  const suffix = notes.length
    ? ` <span class="hub-hours-punch-note">${notes.join(" · ")}</span>`
    : "";
  return `<div class="hub-hours-drilldown-row">
    <span>${escapeHtml(timeLabel(punch.started_at))} – ${escapeHtml(ended)}${suffix}</span>
    <span>${formatHm(punch.minutes)}</span>
  </div>`;
}

function drilldownHtml(day, name) {
  const rows = day.punches.map(punchRowHtml).join("");
  const empty = day.punches.length
    ? ""
    : `<p class="hint hub-hours-no-detail">No punches recorded.</p>`;
  return `<div class="hub-hours-drilldown">
    <div class="hub-hours-drilldown-heading">
      <strong>${escapeHtml(name)} · ${escapeHtml(longDateLabel(day.date))}</strong>
      <strong>${formatHm(day.clocked_minutes)} clocked</strong>
    </div>
    ${rows}${empty}
  </div>`;
}

function shiftMonday(iso, days) {
  const monday = isoDate(iso);
  monday.setUTCDate(monday.getUTCDate() + days);
  return monday.toISOString().slice(0, 10);
}

export function mountHubAttendanceHours(container, payload, { onWeekChange } = {}) {
  let expanded = null;

  function render() {
    const headers = payload.days
      .map((day) => `<th scope="col">${escapeHtml(shortDateLabel(day))}</th>`)
      .join("");
    const rows = payload.rows
      .map((row, rowIndex) => {
        const name = userName(row.user);
        const byDate = new Map(row.days.map((day) => [day.date, day]));
        const cells = payload.days
          .map((dateValue) => {
            const day = byDate.get(dateValue) || {
              date: dateValue, clocked_minutes: 0, needs_review: false,
              has_open: false, punches: [],
            };
            const isExpanded = expanded?.rowIndex === rowIndex && expanded?.date === dateValue;
            const flags = cellFlagLabels(day);
            const label = `${name}, ${longDateLabel(dateValue)}, ${formatHm(day.clocked_minutes)} clocked${flags ? `, ${flags}` : ""}`;
            return `<td><button type="button" class="hub-hours-cell" data-row="${rowIndex}" data-date="${escapeHtml(dateValue)}" aria-label="${escapeHtml(label)}" aria-expanded="${isExpanded}" aria-controls="hub-hours-detail-${rowIndex}">${formatHm(day.clocked_minutes)}${cellFlagsHtml(day)}</button></td>`;
          })
          .join("");
        const mainRow = `<tr><th scope="row">${escapeHtml(name)}</th>${cells}<td class="hub-hours-row-total">${formatHm(row.total_minutes)}</td></tr>`;
        if (expanded?.rowIndex !== rowIndex) return mainRow;
        const day = byDate.get(expanded.date);
        if (!day) return mainRow;
        return `${mainRow}<tr class="hub-hours-detail-row"><td colspan="${payload.days.length + 2}" id="hub-hours-detail-${rowIndex}">${drilldownHtml(day, name)}</td></tr>`;
      })
      .join("");
    const totals = payload.totals_by_day
      .map((entry) => `<td>${formatHm(entry.minutes)}</td>`)
      .join("");
    // 167 or 169. Said out loud so a short week does not read as lost hours.
    const dst = payload.week_hours === 168
      ? ""
      : `<p class="hint hub-hours-dst">Daylight saving: this week is ${escapeHtml(String(payload.week_hours))} hours long, not 168.</p>`;
    const table = payload.rows.length
      ? `<div class="hub-hours-table-wrap">
          <table class="hub-hours-table">
            <caption class="sr-only">Clocked hours for ${escapeHtml(payload.week_start)} through ${escapeHtml(payload.week_end)}</caption>
            <thead><tr><th scope="col">Person</th>${headers}<th scope="col">Week</th></tr></thead>
            <tbody>${rows}</tbody>
            <tfoot><tr><th scope="row">Company total</th>${totals}<td>${formatHm(payload.total_minutes)}</td></tr></tfoot>
          </table>
        </div>`
      : `<p class="hint hub-hours-empty">Nobody clocked in this week.</p>`;

    container.innerHTML = `<section class="hub-hours" aria-labelledby="hub-hours-heading">
      <h3 id="hub-hours-heading" class="sr-only">Clocked hours</h3>
      <div class="hub-hours-toolbar">
        <div class="hub-hours-week-nav">
          <button type="button" class="secondary-btn hub-hours-prev" aria-label="Previous week">◀</button>
          <strong>${escapeHtml(weekLabel(payload.week_start, payload.week_end))}</strong>
          <button type="button" class="secondary-btn hub-hours-next" aria-label="Next week">▶</button>
        </div>
      </div>
      <p class="hub-hours-message" aria-live="polite"></p>
      ${table}
      ${dst}
    </section>`;

    container.querySelectorAll(".hub-hours-cell").forEach((button) => {
      button.addEventListener("click", () => {
        const picked = { rowIndex: Number(button.dataset.row), date: button.dataset.date };
        expanded =
          expanded?.rowIndex === picked.rowIndex && expanded?.date === picked.date
            ? null
            : picked;
        render();
      });
    });
    container.querySelector(".hub-hours-prev")?.addEventListener("click", () => {
      onWeekChange?.(shiftMonday(payload.week_start, -7));
    });
    container.querySelector(".hub-hours-next")?.addEventListener("click", () => {
      onWeekChange?.(shiftMonday(payload.week_start, 7));
    });
  }

  render();
}
```

- [ ] **Step 5: Add the styles**

Append to `backend/static/styles.css`, beside the `.hub-timesheet-*` block (find it with `grep -n "hub-timesheet-table" backend/static/styles.css` and put this immediately after that block so the two grids stay together):

```css
/* --- Hub: the Admin Hours grid (attendance, clocked time) ---------------
   Deliberately the same chrome as `.hub-timesheet-table` above: the two
   grids answer different questions (paid vs charged) and an Admin reads
   them minutes apart, so a different look would imply a difference that
   isn't there. Separate class names because P4 replaces the timesheet one
   and this must not inherit that change. */
.hub-hours-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  flex-wrap: wrap;
  margin-bottom: 0.75rem;
}

.hub-hours-week-nav {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.hub-hours-table-wrap { overflow-x: auto; }

.hub-hours-table {
  width: 100%;
  border-collapse: collapse;
}

.hub-hours-table th,
.hub-hours-table td {
  padding: 0.4rem 0.6rem;
  text-align: right;
  white-space: nowrap;
}

.hub-hours-table th[scope="row"],
.hub-hours-table thead th:first-child,
.hub-hours-table tfoot th { text-align: left; }

.hub-hours-cell {
  background: none;
  border: 1px solid transparent;
  border-radius: 4px;
  padding: 0.2rem 0.45rem;
  font: inherit;
  color: inherit;
  cursor: pointer;
}

.hub-hours-cell:hover,
.hub-hours-cell[aria-expanded="true"] { border-color: var(--accent); }

.hub-hours-flag { margin-left: 0.3rem; }
.hub-hours-flag-open { color: var(--accent); }
.hub-hours-flag-review { color: var(--warning); }

.hub-hours-detail-row > td { padding: 0; }

.hub-hours-drilldown {
  padding: 0.6rem 0.8rem;
  text-align: left;
}

.hub-hours-drilldown-heading,
.hub-hours-drilldown-row {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.2rem 0;
}

.hub-hours-punch-note {
  opacity: 0.75;
  font-size: 0.9em;
}

.hub-hours-dst { margin-top: 0.5rem; }
```

Confirm `--accent` and `--warning` are the token names this sheet uses (`grep -n "^\s*--" backend/static/styles.css | head -40`); substitute the real ones if they differ. `docs/design-system.md` is the authority.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `npx vitest run tests/frontend/views/hubAttendanceHours.test.js`
Expected: 11 passed.

- [ ] **Step 7: Commit**

```bash
git add backend/static/views/hubAttendanceHours.js backend/static/styles.css tests/frontend/helpers/factories.js tests/frontend/views/hubAttendanceHours.test.js
git commit -m "$(cat <<'EOF'
feat(attendance): the read-only Hours grid with its per-day drill-down

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: The Timesheets sub-nav and the tab controller

**Files:**
- Create: `backend/static/views/hubTimesheetsTab.js`
- Modify: `backend/static/views/userHub.js` (remove `loadTimesheets`, `showTimesheetLoadError`, the four timesheet state variables and the `mountHubTimesheets` import; delegate from `renderActiveTab` and `loadUserHub`)
- Modify: `backend/static/styles.css` (sub-nav inside a tabpanel)
- Modify: `tests/frontend/helpers/handlers.js`, `tests/frontend/helpers/hub.js`
- Test: `tests/frontend/views/hubTimesheetsTab.test.js`; existing `tests/frontend/views/userHub.test.js`

**Interfaces:**
- Consumes: `mountHubAttendanceHours` (Task 4), `apiGetHubAttendanceWeek` (Task 3), `mountHubTimesheets` (existing), `apiGetHubTimesheets` (existing), `initSubNav` from `./subnav.js`.
- Produces:
  - `renderTimesheetsTab(panelEl, { role })` — build-or-repaint; called from `userHub.js::renderActiveTab`.
  - `resetTimesheetsTab(panelEl)` — drop caches, bump request counters, clear the panel; called from `userHub.js::loadUserHub` on a user change or a role that loses the tab.

**Sub-nav shape.** Admin+ sees two buttons — **Hours** (default, `data-feature="hours"`) and **Crew time** (`data-feature="crew"`, today's `mountHubTimesheets` grid). Below Admin sees no sub-nav at all and gets the crew grid directly, byte-identical to today, so every existing Timesheets test keeps passing. D6 (Timesheets becomes Admin+ and the crew grid retires) is P4, not this phase.

- [ ] **Step 1: Add the MSW handler and hub fixture wiring**

In `tests/frontend/helpers/hub.js`, add `attendanceWeek` to the `factories.js` import, add `attendanceWeek = null` to `mountHub`'s options, and register its handler beside the existing `/hub/timesheets` one:

```js
    http.get("*/hub/attendance/week", () =>
      answer(attendanceWeek ?? factoriesAttendanceWeek())),
```

Follow the exact `answer(...)` / default-factory idiom the neighbouring `timesheets` handler uses — a number stays an HTTP status to fail with.

- [ ] **Step 2: Write the failing test**

Create `tests/frontend/views/hubTimesheetsTab.test.js`:

```js
// The Timesheets tabpanel: who sees the sub-nav, which feature fetches
// what, and that each fetches only when opened.

import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { attendanceWeek } from "../helpers/factories.js";
import { el, mountHub, queries, unmountHub } from "../helpers/hub.js";

afterEach(async () => { await unmountHub(); });

describe("below Admin", () => {
  it("shows the crew grid with no sub-nav", async () => {
    await mountHub({ role: "supervisor" });
    el.tab("timesheets").click();
    await vi.runOnlyPendingTimersAsync();
    expect(el.panel("timesheets").querySelector(".sub-nav")).toBeNull();
    expect(el.panel("timesheets").querySelector(".hub-timesheet-table")).not.toBeNull();
    expect(queries("/hub/attendance/week")).toHaveLength(0);
  });
});

describe("Admin", () => {
  it("opens on Hours and fetches only the attendance week", async () => {
    await mountHub({ role: "admin" });
    el.tab("timesheets").click();
    await vi.runOnlyPendingTimersAsync();
    const panel = el.panel("timesheets");
    expect(panel.querySelectorAll(".sub-nav-btn")).toHaveLength(2);
    expect(panel.querySelector(".hub-hours-table")).not.toBeNull();
    expect(queries("/hub/attendance/week")).toHaveLength(1);
    expect(queries("/hub/timesheets")).toHaveLength(0);
  });

  it("fetches the crew grid only when that sub-tab is opened", async () => {
    await mountHub({ role: "admin" });
    el.tab("timesheets").click();
    await vi.runOnlyPendingTimersAsync();
    el.panel("timesheets").querySelector('[data-feature="crew"]').click();
    await vi.runOnlyPendingTimersAsync();
    expect(queries("/hub/timesheets")).toHaveLength(1);
    expect(el.panel("timesheets").querySelector(".hub-timesheet-table")).not.toBeNull();
  });

  it("keeps each sub-tab's payload across a switch back", async () => {
    await mountHub({ role: "admin" });
    el.tab("timesheets").click();
    await vi.runOnlyPendingTimersAsync();
    const panel = el.panel("timesheets");
    panel.querySelector('[data-feature="crew"]').click();
    await vi.runOnlyPendingTimersAsync();
    panel.querySelector('[data-feature="hours"]').click();
    await vi.runOnlyPendingTimersAsync();
    expect(queries("/hub/attendance/week")).toHaveLength(1);
  });

  it("pages the week and sends a Monday", async () => {
    await mountHub({ role: "admin", attendanceWeek: attendanceWeek() });
    el.tab("timesheets").click();
    await vi.runOnlyPendingTimersAsync();
    el.panel("timesheets").querySelector(".hub-hours-prev").click();
    await vi.runOnlyPendingTimersAsync();
    expect(queries("/hub/attendance/week").at(-1)).toEqual({ week: "2026-09-07" });
  });

  it("explains a failed Hours load and retries", async () => {
    await mountHub({ role: "admin", attendanceWeek: 500 });
    el.tab("timesheets").click();
    await vi.runOnlyPendingTimersAsync();
    const panel = el.panel("timesheets");
    expect(panel.querySelector(".hub-hours-message.error")).not.toBeNull();
    panel.querySelector(".hub-hours-retry").click();
    await vi.runOnlyPendingTimersAsync();
    expect(queries("/hub/attendance/week")).toHaveLength(2);
  });
});
```

Import `vi` from `vitest` alongside the rest, and match `hub.js`'s actual unmount/teardown export name (it may be `stopClock` rather than `unmountHub` — read the file and use what is there).

- [ ] **Step 3: Run it to make sure it fails**

Run: `npx vitest run tests/frontend/views/hubTimesheetsTab.test.js`
Expected: FAIL — no `.sub-nav` in the panel, no `/hub/attendance/week` request.

- [ ] **Step 4: Write the tab controller**

Create `backend/static/views/hubTimesheetsTab.js`:

```js
// View: the User Hub's Timesheets tabpanel.
//
// Layer: views. Owns the panel's shell, its sub-nav, and both sub-features'
// lazy loads, caches and request counters -- the machinery that used to live
// in userHub.js beside four other tabs' copies of it.
//
// Two sub-features today:
//   hours -- P2's read-only clocked-hours grid, `GET /hub/attendance/week`,
//            Admin+ only, because it is the pay record (D1).
//   crew  -- the existing Supervisor+ charged-time grid, `GET /hub/timesheets`.
//
// Below Admin there is no sub-nav: one button is not a navigation, and the
// crew grid then renders exactly as it did before this module existed. P4
// replaces `crew` with **Charged vs clocked** and retires
// `GET /hub/timesheets` (D6); the swap is confined to this file plus the
// module it mounts.
//
// The shell is built once and `initSubNav` wired once -- rebuilding the
// panel's innerHTML would drop that listener. Each feature renders into its
// own `.feature-panel`, so a repaint of one never disturbs the other.

import { apiGetHubAttendanceWeek, apiGetHubTimesheets } from "../api.js";
import { escapeHtml, friendlyError } from "../format.js";
import { roleAtLeast } from "../roles.js";
import { skeletonCard } from "../skeleton.js";
import { mountHubAttendanceHours } from "./hubAttendanceHours.js";
import { mountHubTimesheets } from "./hubTimesheets.js";
import { initSubNav } from "./subnav.js";

let subNav = null;
let viewerRole = null;

let hoursPayload = null;
let hoursWeek = null;
let hoursRequestId = 0;

let crewPayload = null;
let crewRange = null;
let crewRequestId = 0;

function canSeeHours(role) {
  return roleAtLeast(role, "admin");
}

function featurePanel(panelEl, feature) {
  return panelEl.querySelector(`.feature-panel[data-feature="${feature}"]`);
}

function buildShell(panelEl, role) {
  const nav = canSeeHours(role)
    ? `<nav class="sub-nav hub-sub-nav" aria-label="Timesheet views">
         <button type="button" class="sub-nav-btn active" data-feature="hours">Hours</button>
         <button type="button" class="sub-nav-btn" data-feature="crew">Crew time</button>
       </nav>`
    : "";
  const hoursPanel = canSeeHours(role)
    ? `<section class="feature-panel" data-feature="hours"></section>`
    : "";
  panelEl.innerHTML = `${nav}${hoursPanel}<section class="feature-panel" data-feature="crew"${canSeeHours(role) ? " hidden" : ""}></section>`;
  panelEl.dataset.timesheetsRole = role;
  delete panelEl.dataset.activeFeature;
  subNav = initSubNav(panelEl, {
    onShow: (feature) => loadFeature(panelEl, feature),
    // The initial switch must not fetch at build time: the caller loads the
    // opening feature itself, right below, once the shell exists.
    fireInitialOnShow: false,
  });
}

function loadFeature(panelEl, feature) {
  if (feature === "hours") void loadHours(panelEl);
  else void loadCrew(panelEl, crewRange || {});
}

// --- Hours ---------------------------------------------------------------

function renderHours(panelEl) {
  const mount = featurePanel(panelEl, "hours");
  if (!mount || !hoursPayload) return;
  mountHubAttendanceHours(mount, hoursPayload, {
    onWeekChange: (week) => {
      hoursWeek = week;
      void loadHours(panelEl);
    },
  });
}

function showHoursError(panelEl, err) {
  const mount = featurePanel(panelEl, "hours");
  if (!mount) return;
  const message = escapeHtml(friendlyError(err, "Could not load clocked hours."));
  mount.innerHTML = `<div class="hub-hours-load-error"><p class="hub-hours-message error">${message} <button type="button" class="secondary-btn hub-hours-retry">Retry</button></p></div>`;
  mount.querySelector(".hub-hours-retry")?.addEventListener("click", () => {
    void loadHours(panelEl);
  });
}

async function loadHours(panelEl) {
  const mount = featurePanel(panelEl, "hours");
  if (!mount) return;
  const requestId = ++hoursRequestId;
  if (!hoursPayload) mount.innerHTML = skeletonCard({ lines: 6 });
  try {
    const payload = await apiGetHubAttendanceWeek({ week: hoursWeek });
    if (requestId !== hoursRequestId) return;
    hoursPayload = payload;
    hoursWeek = payload.week_start;
    renderHours(panelEl);
  } catch (err) {
    if (requestId !== hoursRequestId) return;
    showHoursError(panelEl, err);
  }
}

// --- Crew time (unchanged behaviour, moved) ------------------------------

function showCrewError(panelEl, err, requestedRange) {
  const mount = featurePanel(panelEl, "crew");
  if (!mount) return;
  const message = escapeHtml(friendlyError(err, "Could not load timesheets."));
  let status = mount.querySelector(".hub-timesheet-message");
  if (!status) {
    mount.innerHTML = `<div class="hub-timesheet-load-error"><p class="hub-timesheet-message error"></p></div>`;
    status = mount.querySelector(".hub-timesheet-message");
  }
  status.className = "hub-timesheet-message error";
  status.innerHTML = `${message} <button type="button" class="secondary-btn hub-timesheet-retry">Retry</button>`;
  status.querySelector(".hub-timesheet-retry")?.addEventListener("click", () => {
    void loadCrew(panelEl, requestedRange);
  });
}

async function loadCrew(panelEl, { start = null, end = null } = {}) {
  const mount = featurePanel(panelEl, "crew");
  if (!mount) return;
  const requestedRange = { start, end };
  const requestId = ++crewRequestId;
  const existingStatus = mount.querySelector(".hub-timesheet-message");
  if (crewPayload && existingStatus) {
    existingStatus.className = "hub-timesheet-message";
    existingStatus.textContent = "Loading…";
  } else if (!crewPayload) {
    mount.innerHTML = skeletonCard({ lines: 6 });
  }
  try {
    const payload = await apiGetHubTimesheets({ start, end });
    if (requestId !== crewRequestId) return;
    crewPayload = payload;
    crewRange = { start: payload.range.start, end: payload.range.end };
    mountHubTimesheets(mount, payload, {
      onWeekChange: (rangeStart, rangeEnd) =>
        void loadCrew(panelEl, { start: rangeStart, end: rangeEnd }),
      isAdminPlus: roleAtLeast(viewerRole, "techfm_oa"),
    });
  } catch (err) {
    if (requestId !== crewRequestId) return;
    showCrewError(panelEl, err, requestedRange);
  }
}

// --- The tab's two entry points ------------------------------------------

// Called on every render of the Timesheets tab. Builds the shell the first
// time (and whenever the viewer's role changes what the shell contains),
// then repaints or lazily loads whichever feature is showing.
export function renderTimesheetsTab(panelEl, { role } = {}) {
  if (!panelEl) return;
  viewerRole = role;
  if (panelEl.dataset.timesheetsRole !== role || !panelEl.querySelector(".feature-panel")) {
    buildShell(panelEl, role);
  }
  const feature = panelEl.dataset.activeFeature || (canSeeHours(role) ? "hours" : "crew");
  if (feature === "hours") {
    if (hoursPayload) renderHours(panelEl);
    else void loadHours(panelEl);
  } else if (crewPayload) {
    mountHubTimesheets(featurePanel(panelEl, "crew"), crewPayload, {
      onWeekChange: (start, end) => void loadCrew(panelEl, { start, end }),
      isAdminPlus: roleAtLeast(role, "techfm_oa"),
    });
  } else {
    void loadCrew(panelEl, crewRange || {});
  }
}

// A different person signed in, or this viewer no longer has the tab. Both
// caches go, both request counters move so an in-flight response for the
// previous viewer is discarded on arrival, and the panel is emptied.
export function resetTimesheetsTab(panelEl) {
  hoursPayload = null;
  hoursWeek = null;
  hoursRequestId += 1;
  crewPayload = null;
  crewRange = null;
  crewRequestId += 1;
  subNav = null;
  viewerRole = null;
  if (!panelEl) return;
  delete panelEl.dataset.timesheetsRole;
  delete panelEl.dataset.activeFeature;
  panelEl.replaceChildren();
}
```

- [ ] **Step 5: Rewire `userHub.js`**

Delete from `backend/static/views/userHub.js`:
- the `apiGetHubTimesheets` name from the `../api.js` import and the `mountHubTimesheets` import line;
- `let latestTimesheetPayload`, `let timesheetRange`, `let timesheetRequestId`;
- the whole `showTimesheetLoadError` function and the whole `loadTimesheets` function.

Add the import:

```js
import { renderTimesheetsTab, resetTimesheetsTab } from "./hubTimesheetsTab.js";
```

Replace the `timesheets` arm of `renderActiveTab`:

```js
  } else if (activeTab === "timesheets") {
    renderTimesheetsTab(tabPanels.timesheets, { role: latestPayload.user.role });
  } else if (activeTab === "graphs") {
```

Replace the timesheet lines inside `loadUserHub`'s reset block:

```js
  if (userChanged || !canViewSupervisorTabs) {
    latestCrewPayload = null;
    crewError = null;
    crewRequestId += 1;
    resetTimesheetsTab(tabPanels.timesheets);
  }
```

- [ ] **Step 6: Add the sub-nav spacing**

Append to `backend/static/styles.css`, immediately after the `.hub-hours-*` block from Task 4:

```css
/* A sub-nav nested inside a hub tabpanel sits directly under the tab strip,
   so it needs the breathing room the page-level `.sub-nav` gets from its
   page header. Chrome itself is inherited from `.sub-nav` unchanged. */
.hub-tabpanel .hub-sub-nav { margin-bottom: 0.75rem; }
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `npx vitest run tests/frontend/views/hubTimesheetsTab.test.js tests/frontend/views/userHub.test.js tests/frontend/views/hubAdmin.test.js tests/frontend/views/hubSupervisor.test.js`
Expected: all pass. `userHub.test.js` may assert timesheet markup directly on the panel; where it does, point the assertion at `.feature-panel[data-feature="crew"]` and say why in a comment.

- [ ] **Step 8: Commit**

```bash
git add backend/static/views/hubTimesheetsTab.js backend/static/views/userHub.js backend/static/styles.css tests/frontend/helpers/hub.js tests/frontend/helpers/handlers.js tests/frontend/views/hubTimesheetsTab.test.js tests/frontend/views/userHub.test.js
git commit -m "$(cat <<'EOF'
feat(hub): Timesheets sub-nav hosting Hours beside the crew grid

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Self-close a stale punch from the work-order card

**Files:**
- Modify: `backend/static/views/workOrderActions.js` (the `start-tracking-wo` branch, ~line 207)
- Test: `tests/frontend/views/workOrderStartPunch.test.js`

**Why this exists.** P1's 409 on Start says *"Close it on your Home tab before starting again."* A technician standing at a unit should not have to navigate away and back. The card asks `GET /attendance/me` on the 409 — which is what the P1 router docstring already says the client does — and if the blocking punch is `stale`, opens the same `promptTime` prompt the Home tab uses, self-closes, and retries the Start. A non-stale 409 keeps today's inline message.

**No backend change.** The 409 body is a plain sentence by design; `GET /attendance/me` is the structured read, and it is side-effect-free.

**Interfaces:**
- Consumes: `apiGetAttendanceMe`, `apiSelfClosePunch` (both exist), `promptTime` from `../dom.js`, `apiStartWorkOrderTracking`, `refreshCard`.
- Produces: nothing exported; a behaviour change inside the existing delegation.

- [ ] **Step 1: Write the failing test**

Create `tests/frontend/views/workOrderStartPunch.test.js`:

```js
// Starting a work-order clock behind a stale attendance punch (D5).
//
// The card resolves it in place: 409 -> read the blocking punch from
// GET /attendance/me -> promptTime -> self-close -> retry the Start.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// `promptTime` is the only piece this test stubs: it is a modal that
// tests/frontend/unit/dom.promptTime.test.js already covers on its own.
vi.mock("../../../backend/static/dom.js", async () => {
  const actual = await vi.importActual("../../../backend/static/dom.js");
  return { ...actual, promptTime: vi.fn() };
});

// Mount the Work Orders page with one in-progress card the viewer can start.
// Use the existing work-order harness (tests/frontend/helpers/workOrders.js
// or whatever this repo's Work Orders fixture is named); follow the shape
// of the nearest existing workOrders*.test.js rather than inventing one.

describe("a stale punch blocking Start", () => {
  it("prompts, self-closes, and starts the clock", async () => {
    // GIVEN: POST /work-orders/:id/tracking/start answers 409 once, then 200.
    // AND:   GET /attendance/me reports an open punch with stale: true.
    // AND:   promptTime resolves to a Date.
    // WHEN:  the technician taps "W.O. Received, Begin Charging".
    // THEN:  POST /attendance/self-close is sent with that instant, and
    //        the Start is retried and succeeds.
    expect(requests().filter((r) => r.url.includes("/attendance/self-close"))).toHaveLength(1);
    expect(requests().filter((r) => r.url.includes("/tracking/start"))).toHaveLength(2);
  });

  it("does nothing further when the prompt is dismissed", async () => {
    // promptTime resolves null -> no self-close, no retry, the 409's message
    // stays on the card.
    expect(requests().filter((r) => r.url.includes("/attendance/self-close"))).toHaveLength(0);
    expect(card.querySelector(".wo-message").textContent).toContain("still punched in");
  });

  it("leaves a non-stale 409 as an inline message", async () => {
    // GET /attendance/me reports stale: false -> no prompt at all.
    expect(promptTime).not.toHaveBeenCalled();
    expect(card.querySelector(".wo-message.error")).not.toBeNull();
  });

  it("falls back to the inline message when /attendance/me itself fails", async () => {
    // The recovery must never swallow the original error.
    expect(card.querySelector(".wo-message.error")).not.toBeNull();
  });
});
```

Fill the `GIVEN/WHEN/THEN` bodies from the nearest existing work-order card test — read `tests/frontend/views/workOrders/` (or `workOrdersActions.test.js`) first and reuse its mount helper, its MSW override idiom and its `requests()` recorder verbatim. The assertions above are the contract; the setup is this repo's existing one.

- [ ] **Step 2: Run it to make sure it fails**

Run: `npx vitest run tests/frontend/views/workOrderStartPunch.test.js`
Expected: FAIL — no self-close request is sent and Start is attempted once.

- [ ] **Step 3: Write the implementation**

In `backend/static/views/workOrderActions.js`, add to the `../api.js` import list: `apiGetAttendanceMe`, `apiSelfClosePunch`. Add `promptTime` to the `../dom.js` import.

Add above the click delegation (beside the other module-level helpers):

```js
// D5, on the card instead of the Home tab.
//
// A Start blocked by a punch left open on an earlier day is a clerical error,
// not a refusal to work -- and P1's 409 copy sends the technician to the Home
// tab to fix it, which is a page away from the unit they are standing in.
// This resolves it in place.
//
// The 409's body is a plain sentence by design, so the structured punch comes
// from `GET /attendance/me` (side-effect-free, and exactly what that route's
// docstring says the client does). Only a *stale* punch prompts: an ordinary
// "already punched in since 8:12" 409 is information, not a problem to solve.
//
// Returns true when the punch was closed and the caller should retry.
async function resolveStalePunch(err) {
  if (err?.status !== 409) return false;
  let me;
  try {
    me = await apiGetAttendanceMe();
  } catch (_err) {
    // The recovery must never swallow the original error.
    return false;
  }
  const punch = me?.open_punch;
  if (!punch?.stale) return false;
  const startedAt = new Date(punch.started_at);
  const chosen = await promptTime({
    title: "When did you leave?",
    help: `You are still punched in from ${startedAt.toLocaleDateString([], { weekday: "long" })} at ${startedAt.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}. Close it and we'll start your clock.`,
    // The prompt opens on the punch's OWN day, not today -- the rule
    // hubHome.js::handleSelfClose follows, and promptTime never leaves it.
    initial: startedAt,
  });
  if (!chosen) return false;
  await apiSelfClosePunch(chosen.toISOString());
  return true;
}
```

Replace the `start-tracking-wo` branch:

```js
    if (action === "start-tracking-wo") {
      try {
        await apiStartWorkOrderTracking(workOrderId);
      } catch (err) {
        // A stale punch is resolvable here; anything else falls through to
        // the shared inline handler below.
        if (!(await resolveStalePunch(err))) throw err;
        await apiStartWorkOrderTracking(workOrderId);
      }
      await refreshCard(cardEl);
    } else if (action === "stop-tracking-wo") {
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npx vitest run tests/frontend/views/workOrderStartPunch.test.js tests/frontend/views/workOrders`
Expected: all pass, including the existing action-coverage meta-test (this branch keeps the same `data-action`, so no coverage row changes).

- [ ] **Step 5: Commit**

```bash
git add backend/static/views/workOrderActions.js tests/frontend/views/workOrderStartPunch.test.js
git commit -m "$(cat <<'EOF'
feat(attendance): resolve a stale punch from the work-order card

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Full verification and the docs

**Files:**
- Modify: `docs/endpoint-map.md` (one Master Endpoint Index row)
- Modify: `docs/current-state.md` (the attendance block)
- Modify: `docs/open-work.md` (`IMP-041`)

- [ ] **Step 1: Run the whole backend suite**

Run: `cd backend && python -m pytest -q`
Expected: pass. `test_cascade_deletes_with_user` may fail on a dev database carrying real cloud-session rows — that is a known environmental failure, not a regression; note it and move on.

- [ ] **Step 2: Run the whole frontend suite**

Run: `npx vitest run`
Expected: pass. The netfacilities enrichment give-up test is a known flake; re-run it alone before treating it as a break.

- [ ] **Step 3: Add the endpoint-map row**

In `docs/endpoint-map.md`'s Master Endpoint Index, add the row next to the other `/hub` entries, matching the surrounding column order exactly:

```
| `GET /hub/attendance/week` | admin | `apiGetHubAttendanceWeek` | `views/hubTimesheetsTab.js` | Weekly clocked hours per person per day, with punch rows |
```

- [ ] **Step 4: Update `current-state.md`**

In the attendance block P1 added, replace the "what is left" sentence with the present truth — current-truth only, no history:

```markdown
- **Hours grid** — `GET /hub/attendance/week` (admin) → `services/attendance_week.py`
  → Timesheets ▸ **Hours**. Clocked minutes only; punch rows per day behind each
  cell; a cross-midnight punch carries into the next day's cell and is marked
  there. Read-only — editing is P3.
- The Timesheets tab hosts a sub-nav for admin+ (**Hours** ▸ **Crew time**);
  below Admin it renders the crew grid alone. `views/hubTimesheetsTab.js` owns
  the panel's shell, caches and lazy loads.
- A Start blocked by a stale punch self-closes from the work-order card, not
  only the Home tab.
```

- [ ] **Step 5: Trim `IMP-041`**

In `docs/open-work.md`, rewrite the `IMP-041` body so P2 is gone and P3/P4 stand as the remaining work:

```markdown
P1 and P2 shipped: the table, the state machine, the four self-scoped routes,
the work-order clock coupling, the Home tab, `GET /hub/attendance/week`, the
Timesheets sub-nav, the read-only Hours grid, and the card-side self-close.
What is left:

- **P3** — `promptTime`'s analog dial (the dropdown half shipped in P1, on the
  same export), and the Admin edit / add / delete writing
  `attendance_punch_edits`. The Hours drill-down is where the buttons land; a
  `carried` punch row deliberately has none (§9).
- **P4** — Charged vs clocked, the live roster, the `attendance.changed`
  envelope, the CSV export, and retiring `GET /hub/timesheets` — which drops
  the `crew` sub-feature from `hubTimesheetsTab.js`, moves the Timesheets tab
  to Admin+ (D6), and needs `test_route_role_gates.py`'s expected set amended
  again in the same change.
```

- [ ] **Step 6: Commit**

```bash
git add docs/endpoint-map.md docs/current-state.md docs/open-work.md
git commit -m "$(cat <<'EOF'
docs(attendance): P2 Hours grid, the sub-nav, and the trimmed backlog

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 7: Hand back for manual validation**

Do **not** start the preview server. Report: the suites' results verbatim, the new route, and the two screens to check by hand —
1. Sign in as `owner`, open the hub ▸ Timesheets: the sub-nav shows **Hours** first; the grid covers the current Monday–Sunday; a cell click opens that day's punch rows; the week arrows page.
2. Sign in as a Supervisor: Timesheets looks exactly as it did before, with no sub-nav.
3. With a punch left open from yesterday, tap **W.O. Received, Begin Charging** on a work order: the time prompt appears on the card and the clock starts after it is answered.

---

## Self-Review

**Spec coverage (P2 rows only).** §4's `GET /hub/attendance/week` → Task 2. §4's Admin floor + role-gates amendment → Task 2 Step 5. §6's `initSubNav`-hosted sub-nav → Task 5. §6's Monday grid, per-user tally, company total, cell-click drill-down, `needs_review` flag, "static, refetch after an edit" → Task 4. §8's clocked-only discipline → global constraint, enforced by `attendance_week.py` importing neither `labor_summary` nor `work_orders`. §9's non-Monday 422 → Task 2. §9's cross-midnight ownership → Task 1 (`carried`) and Task 4 (the drill-down note, no buttons). §10's `tests/frontend/views/hubAttendance.test.js` row → split across `hubAttendanceHours.test.js` and `hubTimesheetsTab.test.js`; the roster/live half of that row is P4. Open-work's "decision D deferral: a self-close prompt on the work-order card" → Task 6. §2's DST footer → Task 1 (`week_hours`) and Task 4.

**Out of scope, deliberately:** editing (P3), Charged vs clocked, the live roster, `attendance.changed`, CSV, and D6's retirement (P4); `N-HUB-TAB-SHELL`'s `hubTabs.js` extraction (its own change).

**Type consistency.** `week_payload(db, *, week_start, now)` returns `AttendanceWeek`; `WeekDay.clocked_minutes` (not `total_minutes`, which is the *row*'s field) and `WeekPunch.minutes` are the two per-cell numbers, and the schemas, the factory and the view all use those exact names. `onWeekChange` takes **one** argument here (a Monday string), unlike `hubTimesheets.js`'s two-argument `(start, end)` — the two grids are paged differently and the two modules never share the callback.
