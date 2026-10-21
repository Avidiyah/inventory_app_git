# User Profile Per-Person Weekly History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An Admin/Owner clicks a crew member's name on the Users page and reads that person's week: per day, work orders completed, labor charged, time clocked.

**Architecture:** One new read-only service (`person_week.py`) composes three existing reads (attendance week row, labor range summaries, one completed-WO query) into a seven-day payload; one new Admin-gated route serializes it; one new frontend panel (`userProfile.js`) replaces the users table in place. Shared week helpers are extracted from the Hours grid into `hubWeek.js`.

**Tech Stack:** FastAPI + SQLAlchemy + Pydantic (`from_attributes`), vanilla ES modules, pytest (`db` fixture, `TestClient`), vitest + jsdom + MSW.

**Spec:** `docs/superpowers/specs/2026-10-15-user-profile-week-design.md` — read it first; this plan does not restate D1–D10 or the response shape.

## Global Constraints

- All paths below are relative to `backend/` unless they start with `tests/frontend` or `docs/`.
- Route gate `require_min_role(roles.ROLE_ADMIN)`; target roles exactly `roles.WORK_ORDER_TECHNICIAN_ROLES + (roles.ROLE_TECHFM_OA,)`.
- The read must not commit, lock, or sweep. Use `cap_running=True`. Never read `billed_labor_minutes`.
- `userProfile.js` ≤ 500 lines. No `style=` attributes (CSP drops them). No nested `<button>`.
- Run targeted tests only (bounded diff). Commit after each task; do not push (pushing main deploys).
- Run pytest from `backend/` with the venv: `venv/Scripts/python -m pytest <file> -q`. Run vitest from repo root: `npx vitest run <file>`.
- Name the domain error `PersonNotProfilableError` (spec says `PersonNotProfilable`; repo convention suffixes `Error`).

## Review Focus

1. Sunday-night charged session crossing into Monday of the *next* week: Monday minutes must not appear in this week. Pinned in Task 2 (`test_a_session_crossing_the_week_end_is_clipped`).
2. Target user with a punch but no labor and no WO: still seven days, zero charged, zero completed. Pinned in Task 2 (`test_seven_days_always_present`).
3. Target with no attendance row at all (never punched, archived so not in `_population`): seven zero days, not a KeyError. Pinned in Task 2 (`test_archived_target_with_no_punches_is_allowed`).
4. `week` later than the current week → 422 from `resolve_week`, not a 200 empty page. Pinned in Task 3 (`test_a_future_week_is_422`).
5. Week step past the current week on the client: the server 422 must land as the friendly error + Retry, not a blank panel. Pinned in Task 7 (`shows the error and a Retry on failure`).

---

### Task 1: Schemas and the domain error

**Files:**
- Modify: `app/domain/errors.py` (append after `PunchNotFoundError`)
- Modify: `app/routers/_errors.py` (import + `_STATUS_MAP`)
- Modify: `app/schemas/hub.py` (append at end)
- Test: `tests/test_person_week_service.py` (created here with one schema test; Task 2 adds the rest)

**Interfaces:**
- Produces: `PersonNotProfilableError(DomainError)` → 403; `PersonWeekResponse`, `PersonWeekDay`, `PersonWeekCompleted`, `PersonWeekCharged` Pydantic models, all `from_attributes`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_person_week_service.py
"""`services.person_week`: one person's week, composed from the attendance
week, the labor range summaries, and one completed-work-order query (spec
2026-10-15-user-profile-week-design.md). Side-effect-free."""
import os, sys, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, datetime, timedelta, timezone

import pytest

from app.domain import roles
from app.domain.errors import PersonNotProfilableError, UserNotFoundError
from app.models import (
    AttendancePunch, User, WorkOrder, WorkOrderLabor, WorkOrderLaborSession,
    WorkOrderTechnician,
)
from app.services import auth as auth_service
from app.services import person_week


def test_person_not_profilable_maps_to_403():
    from app.routers._errors import to_http
    assert to_http(PersonNotProfilableError("x")).status_code == 403


def test_response_models_are_from_attributes():
    from app.schemas.hub import (
        PersonWeekCharged, PersonWeekCompleted, PersonWeekDay, PersonWeekResponse,
    )
    for model in (PersonWeekCharged, PersonWeekCompleted, PersonWeekDay, PersonWeekResponse):
        assert model.model_config.get("from_attributes") is True
```

- [ ] **Step 2: Run it to verify it fails**

Run: `venv/Scripts/python -m pytest tests/test_person_week_service.py -q`
Expected: FAIL — `ImportError: cannot import name 'PersonNotProfilableError'`.

- [ ] **Step 3: Add the error and its status**

Append to `app/domain/errors.py`:

```python
class PersonNotProfilableError(DomainError):
    """Raised by `services.person_week.week_payload` when the target is an
    Admin or Owner (spec D2): the profile shows crew roles only. Maps to 403
    -- the account exists, this surface refuses it."""
```

In `app/routers/_errors.py`: add `PersonNotProfilableError,` to the import list (alphabetical, after `NoChangeError`) and add `PersonNotProfilableError: 403,` to `_STATUS_MAP` next to `RoleManagementError: 403,`.

- [ ] **Step 4: Add the schemas**

Append to `app/schemas/hub.py` (reuse `HubUser`, `HubAdjustment`; import `AttendanceWeekPunch` from `app.schemas.attendance` at the top of the file):

```python
class PersonWeekCompleted(BaseModel):
    work_order_id: uuid.UUID
    number: str
    location: Optional[str] = None
    completed_at: datetime

    model_config = {"from_attributes": True}


class PersonWeekCharged(BaseModel):
    """One work order's charged minutes for one day, summed across that day's
    sessions on it."""

    work_order_id: uuid.UUID
    number: str
    minutes: int
    auto_closed: bool
    running: bool

    model_config = {"from_attributes": True}


class PersonWeekDay(BaseModel):
    date: date
    clocked_minutes: int
    charged_minutes: int
    adjustment_minutes: int
    completed_count: int
    needs_review: bool
    has_open: bool
    completed: list[PersonWeekCompleted] = []
    charged: list[PersonWeekCharged] = []
    adjustments: list[HubAdjustment] = []
    punches: list[AttendanceWeekPunch] = []

    model_config = {"from_attributes": True}


class PersonWeekResponse(BaseModel):
    """`GET /hub/people/{user_id}/week`: one crew member's Central week,
    seven days always present. Wall-clock minutes only -- no billed number,
    no dollar figure (spec D9)."""

    user: HubUser
    archived: bool
    week_start: date
    week_end: date
    server_now: datetime
    days: list[PersonWeekDay]
    total_clocked_minutes: int
    total_charged_minutes: int
    total_adjustment_minutes: int
    total_completed: int
    reviewable: bool

    model_config = {"from_attributes": True}
```

- [ ] **Step 5: Run the two tests; expect PASS**

Run: `venv/Scripts/python -m pytest tests/test_person_week_service.py -q` (the `from app.services import person_week` import will fail until Task 2 — create an empty `app/services/person_week.py` containing only the module docstring from Task 2 Step 3 so the file imports.)

- [ ] **Step 6: Commit**

```bash
git add app/domain/errors.py app/routers/_errors.py app/schemas/hub.py app/services/person_week.py tests/test_person_week_service.py
git commit -m "feat(hub): person-week schemas and PersonNotProfilableError"
```

---

### Task 2: `services/person_week.py`

**Files:**
- Create: `app/services/person_week.py`
- Test: `tests/test_person_week_service.py`

**Interfaces:**
- Consumes: `attendance_week.week_payload(db, week_start=, now=) -> AttendanceWeek` (`.rows[i].user.id`, `.days[j]` = `WeekDay(date, clocked_minutes, needs_review, has_open, punches)`); `labor_summary.crew_range_summaries(db, [id], start, end, now=, cap_running=True) -> {id: [DaySummary]}` (`DaySummary.closed_minutes/running_minutes/adjustment_minutes/timeline/adjustments`; `TimelineEntry.work_order_id/number/ended_at/auto_closed/minutes/needs_review`); `labor_day.day_bounds(date)`, `labor_day.central_date_of(dt)`.
- Produces: `week_payload(db, *, user_id, week_start, now) -> PersonWeek` whose attribute names equal the schema field names in Task 1 exactly.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_person_week_service.py`)

```python
MONDAY = date(2026, 9, 14)
NOW = datetime(2026, 9, 20, 23, 0, tzinfo=timezone.utc)
# Central day boundaries in UTC (CDT): 05:00Z is midnight.
def _utc(day, hour, minute=0):
    return datetime(2026, 9, day, hour, minute, tzinfo=timezone.utc)


def _user(db, role=roles.ROLE_TECHNICIAN, first="Ann", last="Lee", archived=False):
    user = User(username=f"u-{uuid.uuid4().hex[:10]}",
                password_hash=auth_service.hash_password("hunter2"),
                role=role, first_name=first, last_name=last,
                archived_at=NOW if archived else None)
    db.add(user); db.flush()
    return user


def _wo(db, created_by, *, completed_at=None, crew=(), number=None, location="Bldg 4"):
    work_order = WorkOrder(id=uuid.uuid4(), number=number or f"WO-{uuid.uuid4().hex[:6]}",
                           status="completed" if completed_at else "created",
                           created_by_id=created_by.id, completed_at=completed_at,
                           location=location)
    db.add(work_order); db.flush()
    for tech in crew:
        db.add(WorkOrderTechnician(work_order_id=work_order.id, technician_id=tech.id))
    db.flush()
    return work_order


def _session(db, work_order, tech, started_at, ended_at=None, auto_closed=False):
    session = WorkOrderLaborSession(
        id=uuid.uuid4(), work_order_id=work_order.id, technician_id=tech.id,
        started_at=started_at, ended_at=ended_at,
        auto_closed_at=ended_at if auto_closed else None)
    db.add(session); db.flush()
    return session


def _punch(db, user, started_at, ended_at=None, needs_review=False):
    punch = AttendancePunch(id=uuid.uuid4(), user_id=user.id, started_at=started_at,
                            ended_at=ended_at, start_source="manual",
                            end_source=None if ended_at is None else "manual",
                            needs_review=needs_review)
    db.add(punch); db.flush()
    return punch


def _payload(db, user, week_start=MONDAY):
    return person_week.week_payload(db, user_id=user.id, week_start=week_start, now=NOW)


def _day(payload, day):
    return next(d for d in payload.days if d.date == day)


def test_seven_days_always_present(db):
    tech = _user(db)
    _punch(db, tech, _utc(14, 13), _utc(14, 21))
    db.commit()
    payload = _payload(db, tech)
    assert [d.date for d in payload.days] == [MONDAY + timedelta(days=i) for i in range(7)]
    assert _day(payload, MONDAY).clocked_minutes == 480
    assert payload.total_clocked_minutes == 480
    assert payload.total_charged_minutes == 0
    assert payload.total_completed == 0
    assert payload.user.id == tech.id and payload.archived is False
    assert payload.week_end == MONDAY + timedelta(days=6)


def test_completed_is_bucketed_by_central_day(db):
    tech = _user(db)
    # 11:30 PM Central Monday == 04:30Z Tuesday: a UTC bucket would say Tuesday.
    _wo(db, tech, completed_at=_utc(15, 4, 30), crew=[tech], number="WO-1")
    db.commit()
    payload = _payload(db, tech)
    assert _day(payload, MONDAY).completed_count == 1
    assert _day(payload, MONDAY).completed[0].number == "WO-1"
    assert _day(payload, MONDAY).completed[0].location == "Bldg 4"
    assert _day(payload, MONDAY + timedelta(days=1)).completed_count == 0
    assert payload.total_completed == 1


def test_every_crew_member_is_credited_and_no_crew_credits_nobody(db):
    a, b, c = _user(db), _user(db, first="Bo"), _user(db, first="Cy")
    _wo(db, a, completed_at=_utc(16, 15), crew=[a, b, c])
    _wo(db, a, completed_at=_utc(16, 16), crew=[])
    db.commit()
    for person in (a, b, c):
        assert _payload(db, person).total_completed == 1


def test_a_reopened_work_order_drops_off(db):
    tech = _user(db)
    # services/work_orders.py clears completed_at on reopen; the column is the
    # only signal, so None is what the profile sees.
    _wo(db, tech, completed_at=None, crew=[tech])
    db.commit()
    assert _payload(db, tech).total_completed == 0


def test_charged_collapses_two_sessions_on_one_work_order(db):
    tech = _user(db)
    wo = _wo(db, tech, crew=[tech], number="WO-7")
    _session(db, wo, tech, _utc(14, 13), _utc(14, 15))
    _session(db, wo, tech, _utc(14, 16), _utc(14, 17), auto_closed=True)
    db.commit()
    monday = _day(_payload(db, tech), MONDAY)
    assert monday.charged_minutes == 180
    assert len(monday.charged) == 1
    assert monday.charged[0].number == "WO-7"
    assert monday.charged[0].minutes == 180
    assert monday.charged[0].auto_closed is True
    assert monday.charged[0].running is False


def test_adjustments_are_shown_but_never_summed_into_charged(db):
    tech = _user(db)
    wo = _wo(db, tech, crew=[tech])
    _session(db, wo, tech, _utc(14, 13), _utc(14, 14))
    db.add(WorkOrderLabor(id=uuid.uuid4(), work_order_id=wo.id, technician_id=tech.id,
                          minutes=30, recorded_by_id=tech.id, created_at=_utc(14, 18)))
    db.commit()
    payload = _payload(db, tech)
    monday = _day(payload, MONDAY)
    assert monday.charged_minutes == 60
    assert monday.adjustment_minutes == 30
    assert monday.adjustments[0].minutes == 30
    assert payload.total_charged_minutes == 60
    assert payload.total_adjustment_minutes == 30


def test_a_running_session_is_capped_and_marked_running_without_writing(db):
    tech = _user(db)
    wo = _wo(db, tech, crew=[tech])
    session = _session(db, wo, tech, NOW - timedelta(hours=20))
    db.commit()
    payload = _payload(db, tech)
    charged = [c for d in payload.days for c in d.charged]
    assert charged and all(c.running for c in charged)
    assert payload.total_charged_minutes == 12 * 60
    db.refresh(session)
    assert session.ended_at is None


def test_a_session_crossing_the_week_end_is_clipped(db):
    tech = _user(db)
    wo = _wo(db, tech, crew=[tech])
    # Sunday 10 PM Central -> Monday 2 AM Central: only 2h belong to this week.
    _session(db, wo, tech, _utc(21, 3), _utc(21, 7))
    db.commit()
    assert _payload(db, tech).total_charged_minutes == 120


def test_needs_review_and_reviewable_follow_punches_and_sessions(db):
    tech = _user(db)
    _punch(db, tech, _utc(15, 13), _utc(15, 21), needs_review=True)
    db.commit()
    payload = _payload(db, tech)
    assert _day(payload, MONDAY + timedelta(days=1)).needs_review is True
    assert payload.reviewable is True


def test_an_open_punch_sets_has_open(db):
    tech = _user(db)
    _punch(db, tech, NOW - timedelta(hours=1))
    db.commit()
    payload = _payload(db, tech)
    assert any(d.has_open for d in payload.days)


def test_archived_target_with_no_punches_is_allowed(db):
    tech = _user(db, archived=True)
    db.commit()
    payload = _payload(db, tech)
    assert payload.archived is True
    assert len(payload.days) == 7
    assert payload.total_clocked_minutes == 0


@pytest.mark.parametrize("role", [roles.ROLE_SUPERVISOR, roles.ROLE_TECHFM_OA])
def test_team_lead_and_techfm_oa_are_profilable(db, role):
    person = _user(db, role=role)
    db.commit()
    assert _payload(db, person).user.role == role


@pytest.mark.parametrize("role", [roles.ROLE_ADMIN, roles.ROLE_OWNER])
def test_admin_and_owner_targets_raise(db, role):
    person = _user(db, role=role)
    db.commit()
    with pytest.raises(PersonNotProfilableError):
        _payload(db, person)


def test_unknown_user_raises_not_found(db):
    with pytest.raises(UserNotFoundError):
        person_week.week_payload(db, user_id=uuid.uuid4(), week_start=MONDAY, now=NOW)
```

- [ ] **Step 2: Run; expect FAIL** with `AttributeError: module 'app.services.person_week' has no attribute 'week_payload'`.

- [ ] **Step 3: Implement the service**

```python
# app/services/person_week.py
"""One crew member's week, one row per day: completed work orders, charged
labor, clocked time. Spec: 2026-10-15-user-profile-week-design.md.

Layer: services. Read-only and side-effect-free -- no sweep, no row locks,
no commit (D8); an open labor session is clipped at the cap on read.

Composition only, no new maths: the clocked column is the target's row of
`attendance_week.week_payload`, the charged column is
`labor_summary.crew_range_summaries` collapsed per work order per day, and
the completed column is one query bucketed by `labor_day.central_date_of`.
Wall-clock minutes throughout; never `billed_labor_minutes` (D9).

ponytail: whole-population attendance read; add a `user_ids` filter to
`attendance_week._population` if the roster grows past ~100.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.domain import labor_day, roles
from app.domain.errors import PersonNotProfilableError, UserNotFoundError
from app.models import User, WorkOrder, WorkOrderTechnician
from app.services import attendance_week, labor_summary

PROFILABLE_ROLES: tuple[str, ...] = (
    *roles.WORK_ORDER_TECHNICIAN_ROLES, roles.ROLE_TECHFM_OA,
)


@dataclass(frozen=True)
class PersonCompleted:
    work_order_id: uuid.UUID
    number: str
    location: str | None
    completed_at: datetime


@dataclass(frozen=True)
class PersonCharged:
    work_order_id: uuid.UUID
    number: str
    minutes: int
    auto_closed: bool
    running: bool


@dataclass(frozen=True)
class PersonDay:
    date: date
    clocked_minutes: int
    charged_minutes: int
    adjustment_minutes: int
    completed_count: int
    needs_review: bool
    has_open: bool
    completed: list[PersonCompleted]
    charged: list[PersonCharged]
    adjustments: list[labor_summary.Adjustment]
    punches: list[attendance_week.WeekPunch]


@dataclass(frozen=True)
class PersonWeek:
    user: User
    archived: bool
    week_start: date
    week_end: date
    server_now: datetime
    days: list[PersonDay]
    total_clocked_minutes: int
    total_charged_minutes: int
    total_adjustment_minutes: int
    total_completed: int
    reviewable: bool


def _collapse_charged(timeline: list[labor_summary.TimelineEntry]) -> list[PersonCharged]:
    """One line per work order per day, in first-seen order."""
    by_wo: dict[uuid.UUID, PersonCharged] = {}
    for entry in timeline:
        prior = by_wo.get(entry.work_order_id)
        by_wo[entry.work_order_id] = PersonCharged(
            work_order_id=entry.work_order_id,
            number=entry.number,
            minutes=(prior.minutes if prior else 0) + entry.minutes,
            auto_closed=(prior.auto_closed if prior else False) or entry.auto_closed,
            running=(prior.running if prior else False) or entry.ended_at is None,
        )
    return list(by_wo.values())


def _completed_by_day(
    db: Session, user_id: uuid.UUID, window_start: datetime, window_end: datetime
) -> dict[date, list[PersonCompleted]]:
    rows = (
        db.query(WorkOrder)
        .join(WorkOrderTechnician, WorkOrderTechnician.work_order_id == WorkOrder.id)
        .filter(
            WorkOrderTechnician.technician_id == user_id,
            WorkOrder.completed_at.isnot(None),
            WorkOrder.completed_at >= window_start,
            WorkOrder.completed_at < window_end,
        )
        .order_by(WorkOrder.completed_at)
        .all()
    )
    buckets: dict[date, list[PersonCompleted]] = {}
    for work_order in rows:
        completed_at = labor_day.as_utc(work_order.completed_at)
        buckets.setdefault(labor_day.central_date_of(completed_at), []).append(
            PersonCompleted(
                work_order_id=work_order.id, number=work_order.number,
                location=work_order.location, completed_at=completed_at,
            )
        )
    return buckets


def week_payload(
    db: Session, *, user_id: uuid.UUID, week_start: date, now: datetime
) -> PersonWeek:
    """`week_start` is a Monday already resolved by
    `work_order_report.resolve_week`. Raises `UserNotFoundError` (404) and
    `PersonNotProfilableError` (403, Admin/Owner target) here, not at the
    route, so no future caller can skip the check."""
    person = db.get(User, user_id)
    if person is None:
        raise UserNotFoundError("User not found.")
    if person.role not in PROFILABLE_ROLES:
        raise PersonNotProfilableError("Only crew accounts have a profile.")

    week_end = week_start + timedelta(days=6)
    window_start, _ = labor_day.day_bounds(week_start)
    _, window_end = labor_day.day_bounds(week_end)
    days = [week_start + timedelta(days=i) for i in range(7)]

    clocked = attendance_week.week_payload(db, week_start=week_start, now=now)
    row = next((r for r in clocked.rows if r.user.id == user_id), None)
    clocked_by_day = {d.date: d for d in row.days} if row else {}
    summaries = labor_summary.crew_range_summaries(
        db, [user_id], week_start, week_end, now=now, cap_running=True,
    ).get(user_id, [])
    summary_by_day = {s.day: s for s in summaries}
    completed_by_day = _completed_by_day(db, user_id, window_start, window_end)

    out: list[PersonDay] = []
    for day in days:
        clocked_day = clocked_by_day.get(day)
        summary = summary_by_day.get(day, labor_summary.DaySummary(day=day))
        completed = completed_by_day.get(day, [])
        out.append(PersonDay(
            date=day,
            clocked_minutes=clocked_day.clocked_minutes if clocked_day else 0,
            charged_minutes=summary.closed_minutes + summary.running_minutes,
            adjustment_minutes=summary.adjustment_minutes,
            completed_count=len(completed),
            needs_review=bool(clocked_day and clocked_day.needs_review)
                or any(e.needs_review for e in summary.timeline),
            has_open=bool(clocked_day and clocked_day.has_open),
            completed=completed,
            charged=_collapse_charged(summary.timeline),
            adjustments=list(summary.adjustments),
            punches=list(clocked_day.punches) if clocked_day else [],
        ))

    return PersonWeek(
        user=person,
        archived=person.archived_at is not None,
        week_start=week_start,
        week_end=week_end,
        server_now=now,
        days=out,
        total_clocked_minutes=sum(d.clocked_minutes for d in out),
        total_charged_minutes=sum(d.charged_minutes for d in out),
        total_adjustment_minutes=sum(d.adjustment_minutes for d in out),
        total_completed=sum(d.completed_count for d in out),
        reviewable=any(d.needs_review for d in out),
    )
```

- [ ] **Step 4: Run; expect all PASS**

Run: `venv/Scripts/python -m pytest tests/test_person_week_service.py -q`. If the running-session cap test disagrees by a few minutes, check `work_orders.capped_session_end`: the cap is `LABOR_SESSION_MAX_MINUTES`; use that constant in the assertion instead of `12 * 60` if it differs.

- [ ] **Step 5: Commit**

```bash
git add app/services/person_week.py tests/test_person_week_service.py
git commit -m "feat(hub): person_week service composes one crew member's week"
```

---

### Task 3: Route `GET /hub/people/{user_id}/week`

**Files:**
- Modify: `app/routers/hub.py` (import + new handler after `get_hub_attendance_week`; add a line to the module docstring list)
- Modify: `tests/test_route_role_gates.py:548-558` (exemption set) and append one pin test
- Test: `tests/test_person_week_router.py`

**Interfaces:**
- Consumes: `person_week.week_payload`, `PersonWeekResponse`.
- Produces: endpoint function named `get_hub_person_week` (the gate test keys on this name).

- [ ] **Step 1: Write the failing router tests**

```python
# tests/test_person_week_router.py
"""`GET /hub/people/{user_id}/week` at the route boundary, via TestClient."""
import os, sys, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import User, WorkOrder, WorkOrderLaborSession, WorkOrderTechnician
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


def _get(db, viewer, target_id, **params):
    try:
        with _as(db, viewer) as client:
            return client.get(f"/hub/people/{target_id}/week", params=params)
    finally:
        del app.dependency_overrides[get_db]


def test_an_admin_reads_a_technicians_week(db):
    admin = _seed_user(db, role="admin", first="Dee", last="Ops")
    tech = _seed_user(db)
    wo = WorkOrder(id=uuid.uuid4(), number="WO-9", status="completed",
                   created_by_id=admin.id,
                   completed_at=datetime(2026, 9, 16, 15, 0, tzinfo=timezone.utc))
    db.add(wo); db.flush()
    db.add(WorkOrderTechnician(work_order_id=wo.id, technician_id=tech.id))
    db.commit()
    response = _get(db, admin, tech.id, week="2026-09-14")
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["id"] == str(tech.id)
    assert body["week_start"] == "2026-09-14" and body["week_end"] == "2026-09-20"
    assert len(body["days"]) == 7
    assert body["days"][2]["completed"][0]["number"] == "WO-9"
    assert body["total_completed"] == 1
    assert "billed" not in response.text


def test_week_omitted_is_the_current_week(db):
    admin = _seed_user(db, role="admin")
    tech = _seed_user(db)
    db.commit()
    body = _get(db, admin, tech.id).json()
    assert datetime.fromisoformat(body["week_start"]).weekday() == 0


def test_techfm_oa_viewer_is_refused(db):
    oa = _seed_user(db, role="techfm_oa")
    tech = _seed_user(db)
    db.commit()
    assert _get(db, oa, tech.id, week="2026-09-14").status_code == 403


def test_owner_target_is_403(db):
    admin = _seed_user(db, role="admin")
    owner = _seed_user(db, role="owner")
    db.commit()
    assert _get(db, admin, owner.id, week="2026-09-14").status_code == 403


def test_unknown_user_is_404(db):
    admin = _seed_user(db, role="admin")
    db.commit()
    assert _get(db, admin, uuid.uuid4(), week="2026-09-14").status_code == 404


def test_a_non_monday_is_422(db):
    admin = _seed_user(db, role="admin")
    tech = _seed_user(db)
    db.commit()
    assert _get(db, admin, tech.id, week="2026-09-15").status_code == 422


def test_a_future_week_is_422(db):
    admin = _seed_user(db, role="admin")
    tech = _seed_user(db)
    db.commit()
    future = datetime.now(timezone.utc).date() + timedelta(days=14)
    monday = future - timedelta(days=future.weekday())
    assert _get(db, admin, tech.id, week=monday.isoformat()).status_code == 422


def test_the_read_does_not_sweep_an_open_session(db):
    admin = _seed_user(db, role="admin")
    tech = _seed_user(db)
    wo = WorkOrder(id=uuid.uuid4(), number="WO-open", status="in_progress",
                   created_by_id=admin.id)
    db.add(wo); db.flush()
    session = WorkOrderLaborSession(
        id=uuid.uuid4(), work_order_id=wo.id, technician_id=tech.id,
        started_at=datetime.now(timezone.utc) - timedelta(hours=20))
    db.add(session); db.commit()
    assert _get(db, admin, tech.id).status_code == 200
    db.expire_all()
    assert db.get(WorkOrderLaborSession, session.id).ended_at is None
```

- [ ] **Step 2: Run; expect 404s** (route not registered): `venv/Scripts/python -m pytest tests/test_person_week_router.py -q`.

- [ ] **Step 3: Add the route**

In `app/routers/hub.py`: add `PersonWeekResponse` to the `app.schemas.hub` import and `from app.services import person_week`. Add to the docstring list: `` - `GET /hub/people/{user_id}/week` admin only -- one crew member's week ``. Insert after `get_hub_attendance_week`:

```python
@router.get("/people/{user_id}/week", response_model=PersonWeekResponse)
def get_hub_person_week(
    user_id: uuid.UUID,
    week: Optional[date] = Query(None),
    user: User = Depends(require_min_role(roles.ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """One crew member's Central week, one row per day: completed, charged,
    clocked. **Admin, not TechFM OA** -- same grounds as the attendance week
    it is built from. Target must be Technician, Team Lead, or TechFM OA
    (403 otherwise, raised in the service); archived targets are allowed.
    Same `week` contract as `GET /hub/attendance/week`. Side-effect-free."""
    now = datetime.now(timezone.utc)
    try:
        week_start = work_order_report.resolve_week(week, now)
        payload = person_week.week_payload(
            db, user_id=user_id, week_start=week_start, now=now)
    except DomainError as exc:
        raise to_http(exc) from exc
    return PersonWeekResponse.model_validate(payload)
```

- [ ] **Step 4: Register the Admin floor in the gate test**

In `tests/test_route_role_gates.py`, add `"get_hub_person_week",` to the `offenders` set (after `"review_hub_attendance_week",`) with the comment `# The per-person profile is the pay record read one name at a time.`. Append after `test_the_live_roster_sits_above_techfm_oa`:

```python
def test_the_person_week_sits_above_techfm_oa():
    # One person's clocked and charged week is the pay record (D1).
    assert _min_role_for(hub_router, "get_hub_person_week") == roles.ROLE_ADMIN
```

- [ ] **Step 5: Run; expect PASS**

Run: `venv/Scripts/python -m pytest tests/test_person_week_router.py tests/test_route_role_gates.py tests/test_hub_router.py -q`

- [ ] **Step 6: Commit**

```bash
git add app/routers/hub.py tests/test_person_week_router.py tests/test_route_role_gates.py
git commit -m "feat(hub): GET /hub/people/{user_id}/week, admin only"
```

---

### Task 4: Extract `hubWeek.js` and add `apiGetPersonWeek`

**Files:**
- Create: `static/views/hubWeek.js`
- Modify: `static/views/hubAttendanceHours.js:26-50,140-144` (delete local `formatHm`, `isoDate`, `weekLabel`, `shiftMonday`; import them)
- Modify: `static/api.js` (after `apiGetHubAttendanceWeek`)
- Test: `tests/frontend/unit/hubWeek.test.js`

**Interfaces:**
- Produces: `export function formatHm(totalMinutes): "h:mm"`, `isoDate(iso): Date`, `weekLabel(start, end): string`, `shiftMonday(iso, days): "YYYY-MM-DD"`; `apiGetPersonWeek(userId, { week = null } = {})` → `GET /hub/people/{userId}/week[?week=]`.

- [ ] **Step 1: Write the failing unit test**

```javascript
// tests/frontend/unit/hubWeek.test.js
import { describe, expect, it } from "vitest";
import { formatHm, shiftMonday, weekLabel } from "../../../backend/static/views/hubWeek.js";

describe("hubWeek helpers", () => {
  it("prints minutes as h:mm, floored at zero", () => {
    expect(formatHm(480)).toBe("8:00");
    expect(formatHm(65)).toBe("1:05");
    expect(formatHm(-5)).toBe("0:00");
    expect(formatHm(undefined)).toBe("0:00");
  });
  it("shifts a Monday by whole weeks in UTC", () => {
    expect(shiftMonday("2026-09-14", 7)).toBe("2026-09-21");
    expect(shiftMonday("2026-09-14", -7)).toBe("2026-09-07");
  });
  it("labels a week from its two dates", () => {
    expect(weekLabel("2026-09-14", "2026-09-20")).toContain("Sep 14");
    expect(weekLabel("2026-09-14", "2026-09-20")).toContain("Sep 20");
  });
});
```

- [ ] **Step 2: Run; expect FAIL** (module missing): `npx vitest run tests/frontend/unit/hubWeek.test.js`

- [ ] **Step 3: Create the module and swap the imports**

```javascript
// backend/static/views/hubWeek.js
// Pure week helpers shared by the Admin week surfaces (Hours grid, user
// profile). No DOM, no fetch. Dates are ISO `YYYY-MM-DD` Mondays computed in
// UTC so a viewer's zone cannot move the week boundary.

// `8:00`, not format.js's `8 h 0 m`: a column of hours reads as clock times.
export function formatHm(totalMinutes) {
  const minutes = Math.max(0, Math.round(Number(totalMinutes) || 0));
  return `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, "0")}`;
}

export function isoDate(iso) {
  return new Date(`${iso}T00:00:00Z`);
}

export function weekLabel(start, end) {
  const options = { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" };
  return `${isoDate(start).toLocaleDateString([], options)} – ${isoDate(end).toLocaleDateString([], options)}`;
}

export function shiftMonday(iso, days) {
  const monday = isoDate(iso);
  monday.setUTCDate(monday.getUTCDate() + days);
  return monday.toISOString().slice(0, 10);
}
```

In `hubAttendanceHours.js`: delete the local `formatHm`, `isoDate`, `weekLabel`, and `shiftMonday` function bodies and add `import { formatHm, isoDate, shiftMonday, weekLabel } from "./hubWeek.js";` under the existing imports. Keep `shortDateLabel`/`longDateLabel` (they call `isoDate`).

In `static/api.js`, after `apiGetHubAttendanceWeek`:

```javascript
// One crew member's week for the Users-page profile. `week` is a Monday;
// absent means the week in progress. Admin only.
export async function apiGetPersonWeek(userId, { week = null } = {}) {
  const params = new URLSearchParams();
  if (week) params.set("week", week);
  const query = params.toString();
  const path = `/hub/people/${encodeURIComponent(userId)}/week`;
  return liveGet(query ? `${path}?${query}` : path);
}
```

- [ ] **Step 4: Run; expect PASS, and the Hours grid unchanged**

Run: `npx vitest run tests/frontend/unit/hubWeek.test.js tests/frontend/views/hubAttendanceHours.test.js tests/frontend/views/hubTimesheetsTab.test.js`

- [ ] **Step 5: Commit**

```bash
git add backend/static/views/hubWeek.js backend/static/views/hubAttendanceHours.js backend/static/api.js tests/frontend/unit/hubWeek.test.js
git commit -m "refactor(hub): extract week helpers to hubWeek.js; add apiGetPersonWeek"
```

---

### Task 5: `userProfile.js` panel

**Files:**
- Create: `static/views/userProfile.js`
- Modify: `static/styles.css` (append one block)
- Test: `tests/frontend/views/userProfile.test.js`; factory in `tests/frontend/helpers/factories.js`

**Interfaces:**
- Consumes: `apiGetPersonWeek`, `hubWeek.js` helpers, `escapeHtml`/`friendlyError`/`formatUserName` from `format.js`, `roleLabel` from `roles.js`, `skeletonTableRows` from `skeleton.js`.
- Produces: `export function mountUserProfile(container, user, { onBack } = {})` — `user` is a `/users/` list row (`id, first_name, last_name, role, archived_at`). Renders header + week picker + 7-row `<details>` table. Work-order number buttons carry class `user-profile-wo-btn` and `data-number`; on click the module dynamic-imports `./workOrders.js` (for `openWorkOrdersByNumberSearch`) and `./nav.js` (for `showPage`) so `users.js`'s import graph stays small.

- [ ] **Step 1: Add the factory** (append to `tests/frontend/helpers/factories.js`)

```javascript
export function personWeek(overrides = {}) {
  const days = ["2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17",
                "2026-09-18", "2026-09-19", "2026-09-20"];
  const blank = (date) => ({
    date, clocked_minutes: 0, charged_minutes: 0, adjustment_minutes: 0,
    completed_count: 0, needs_review: false, has_open: false,
    completed: [], charged: [], adjustments: [], punches: [],
  });
  const monday = {
    ...blank("2026-09-14"),
    clocked_minutes: 480, charged_minutes: 180, adjustment_minutes: 30, completed_count: 1,
    completed: [{ work_order_id: "wo-1", number: "WO-1", location: "Bldg 4",
                  completed_at: "2026-09-14T20:00:00Z" }],
    charged: [{ work_order_id: "wo-1", number: "WO-1", minutes: 180,
                auto_closed: true, running: false }],
    adjustments: [{ minutes: 30, recorded_by_name: "Dee Ops", work_order_number: "WO-1" }],
    punches: [{ id: "punch-1", started_at: "2026-09-14T13:00:00Z",
                ended_at: "2026-09-14T21:00:00Z", start_source: "manual",
                end_source: "manual", needs_review: false, minutes: 480,
                carried: false, open: false }],
  };
  return {
    user: { id: "10000000-0000-4000-8000-000000000001", first_name: "Ann", last_name: "Lee", role: "technician" },
    archived: false,
    week_start: "2026-09-14", week_end: "2026-09-20",
    server_now: "2026-09-16T15:00:00Z",
    days: [monday, ...days.slice(1).map(blank)],
    total_clocked_minutes: 480, total_charged_minutes: 180,
    total_adjustment_minutes: 30, total_completed: 1, reviewable: false,
    ...overrides,
  };
}
```

- [ ] **Step 2: Write the failing view tests**

```javascript
// tests/frontend/views/userProfile.test.js
// The Users-page profile panel: header, week picker, seven <details> rows,
// totals, the drill-down lists, the Work Orders hand-off, and the error/retry
// state. Fetches through MSW; the hand-off modules are mocked.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../helpers/handlers.js";
import { clearRequests, requests, startRecording, stopRecording } from "../helpers/requests.js";
import { personWeek } from "../helpers/factories.js";

// `vi.mock` is hoisted above every import, so the fns it closes over must be
// hoisted too.
const { openSearch, showPage } = vi.hoisted(() => ({ openSearch: vi.fn(), showPage: vi.fn() }));
vi.mock("../../../backend/static/views/workOrders.js", () => ({ openWorkOrdersByNumberSearch: openSearch }));
vi.mock("../../../backend/static/views/nav.js", () => ({ showPage }));

const { mountUserProfile } = await import("../../../backend/static/views/userProfile.js");

const USER = { id: "10000000-0000-4000-8000-000000000001", first_name: "Ann",
               last_name: "Lee", role: "technician", archived_at: null };
let host;
const flush = () => new Promise((r) => setTimeout(r, 0));
const weekQueries = () => requests()
  .filter((r) => r.url.includes("/hub/people/"))
  .map((r) => Object.fromEntries(new URL(r.url, "http://t").searchParams));

function serve(payloadOrStatus) {
  server.use(http.get("/hub/people/:id/week", ({ request }) => {
    if (typeof payloadOrStatus === "number") {
      return HttpResponse.json({ detail: "week cannot be in the future." }, { status: payloadOrStatus });
    }
    const week = new URL(request.url).searchParams.get("week");
    return HttpResponse.json(week ? { ...payloadOrStatus, week_start: week } : payloadOrStatus);
  }));
}

async function mount(user = USER, options = {}) {
  mountUserProfile(host, user, options);
  await flush(); await flush();
}

beforeEach(() => {
  document.body.innerHTML = `<div id="host"></div>`;
  host = document.getElementById("host");
  startRecording(); clearRequests();
  openSearch.mockClear(); showPage.mockClear();
});
afterEach(() => stopRecording());

const rows = () => Array.from(host.querySelectorAll("details.user-profile-day"));

describe("the panel", () => {
  it("renders the header, seven day rows and the week totals", async () => {
    serve(personWeek());
    await mount();
    expect(host.querySelector(".user-profile-header").textContent).toContain("Ann Lee");
    expect(host.querySelector(".user-profile-header").textContent).toContain("Technician");
    expect(rows()).toHaveLength(7);
    expect(rows()[0].querySelector("summary").textContent).toContain("8:00");
    expect(rows()[0].querySelector("summary").textContent).toContain("3:00");
    expect(host.querySelector("tfoot, .user-profile-totals").textContent).toContain("8:00");
    expect(host.querySelector(".user-profile-totals").textContent).toContain("1");
  });

  it("tags an archived person", async () => {
    serve(personWeek({ archived: true }));
    await mount({ ...USER, archived_at: "2026-09-01T00:00:00Z" });
    expect(host.querySelector(".user-profile-header").textContent).toContain("(archived)");
  });

  it("steps the week and refetches with the shifted Monday", async () => {
    serve(personWeek());
    await mount();
    clearRequests();
    host.querySelector(".user-profile-prev").click();
    await flush(); await flush();
    expect(weekQueries()).toEqual([{ week: "2026-09-07" }]);
    host.querySelector(".user-profile-next").click();
    await flush(); await flush();
    expect(weekQueries().at(-1)).toEqual({ week: "2026-09-14" });
  });

  it("lists completed, charged, adjustments and punches inside a day", async () => {
    serve(personWeek());
    await mount();
    const body = rows()[0].querySelector(".user-profile-day-body").textContent;
    expect(body).toContain("WO-1");
    expect(body).toContain("Bldg 4");
    expect(body).toContain("auto-stopped");
    expect(body).toContain("Dee Ops");
    expect(body).toContain("0:30");
    expect(rows()[1].querySelector(".user-profile-day-body").textContent).toContain("Nothing recorded");
  });

  it("flags a day that needs review and notes an open shift", async () => {
    const week = personWeek();
    week.days[1] = { ...week.days[1], needs_review: true, has_open: true, clocked_minutes: 60 };
    serve(week);
    await mount();
    expect(rows()[1].querySelector(".hub-hours-flag-review")).not.toBeNull();
    expect(rows()[1].querySelector("summary").textContent).toContain("on shift");
  });

  it("hands a work order number to the Work Orders page", async () => {
    serve(personWeek());
    await mount();
    rows()[0].querySelector(".user-profile-wo-btn").click();
    await flush(); await flush();
    expect(openSearch).toHaveBeenCalledWith("WO-1");
    expect(showPage).toHaveBeenCalledWith("work-orders");
  });

  it("calls onBack from the Back link", async () => {
    serve(personWeek());
    const onBack = vi.fn();
    await mount(USER, { onBack });
    host.querySelector(".user-profile-back").click();
    expect(onBack).toHaveBeenCalled();
  });

  it("shows the error and a Retry on failure, and recovers", async () => {
    serve(422);
    await mount();
    expect(host.querySelector(".user-profile-error").textContent).toContain("future");
    serve(personWeek());
    host.querySelector(".user-profile-retry").click();
    await flush(); await flush();
    expect(rows()).toHaveLength(7);
  });
});
```

- [ ] **Step 3: Run; expect FAIL** (module missing): `npx vitest run tests/frontend/views/userProfile.test.js`

- [ ] **Step 4: Implement the panel**

```javascript
// backend/static/views/userProfile.js
// View: one crew member's week on the Users page -- per day, work orders
// completed, labor charged, time clocked. Read-only (spec
// 2026-10-15-user-profile-week-design.md).
//
// Layer: views. Owns its fetch (`apiGetPersonWeek`) and one piece of state,
// the week. Each day is a native <details>: totals in the summary, the four
// lists in the body, no JS toggle state. Wall-clock minutes only; no money.
//
// `users.js` dynamic-imports this module on the first profile click, and this
// module dynamic-imports the Work Orders hand-off on the first number click,
// so the Users page's import graph stays as small as it is today.

import { apiGetPersonWeek } from "../api.js";
import { escapeHtml, formatUserName, friendlyError } from "../format.js";
import { roleLabel } from "../roles.js";
import { skeletonTableRows } from "../skeleton.js";
import { formatHm, isoDate, shiftMonday, weekLabel } from "./hubWeek.js";

const CENTRAL_TIME_ZONE = "America/Chicago";

function dayLabel(iso) {
  return isoDate(iso).toLocaleDateString([], {
    weekday: "short", month: "numeric", day: "numeric", timeZone: "UTC",
  });
}

function timeLabel(instant) {
  return new Date(instant).toLocaleTimeString([], {
    hour: "numeric", minute: "2-digit", timeZone: CENTRAL_TIME_ZONE,
  });
}

function woButton(number) {
  return `<button type="button" class="hub-link-btn user-profile-wo-btn" data-number="${escapeHtml(number)}">${escapeHtml(number)}</button>`;
}

function listHtml(title, items) {
  if (!items.length) return "";
  return `<h4 class="user-profile-list-title">${title}</h4><ul class="user-profile-list">${items.join("")}</ul>`;
}

function dayBodyHtml(day) {
  const completed = day.completed.map((wo) =>
    `<li>${woButton(wo.number)}${wo.location ? ` · ${escapeHtml(wo.location)}` : ""}</li>`);
  const charged = day.charged.map((c) => {
    const marks = [];
    if (c.auto_closed) marks.push("auto-stopped");
    if (c.running) marks.push("running");
    const note = marks.length ? ` <span class="hub-hours-punch-note">${marks.join(" · ")}</span>` : "";
    return `<li>${woButton(c.number)} · ${formatHm(c.minutes)}${note}</li>`;
  });
  const adjustments = day.adjustments.map((a) =>
    `<li>${formatHm(a.minutes)} · recorded by ${escapeHtml(a.recorded_by_name)} · ${woButton(a.work_order_number)}</li>`);
  const punches = day.punches.map((p) => {
    const ended = p.open ? "running" : timeLabel(p.ended_at);
    const notes = [];
    if (p.carried) notes.push("carried");
    if (p.start_source === "auto_work_order") notes.push("auto, from a work-order clock");
    if (p.needs_review) notes.push("needs review");
    const note = notes.length ? ` <span class="hub-hours-punch-note">${notes.join(" · ")}</span>` : "";
    return `<li>${escapeHtml(timeLabel(p.started_at))} – ${escapeHtml(ended)} · ${formatHm(p.minutes)}${note}</li>`;
  });
  const html = listHtml("Completed", completed) + listHtml("Charged", charged)
    + listHtml("Adjustments", adjustments) + listHtml("Punches", punches);
  return html || `<p class="hint">Nothing recorded.</p>`;
}

function flagsHtml(day) {
  return day.needs_review
    ? `<span class="hub-hours-flag hub-hours-flag-review"><span aria-hidden="true">&#9888;</span><span class="sr-only"> needs review</span></span>`
    : "";
}

function dayHtml(day) {
  const onShift = day.has_open ? ` <span class="hub-hours-punch-note">(on shift)</span>` : "";
  return `<details class="user-profile-day">
    <summary class="user-profile-summary">
      <span class="user-profile-col-day">${escapeHtml(dayLabel(day.date))}${flagsHtml(day)}</span>
      <span class="user-profile-col">${formatHm(day.clocked_minutes)}${onShift}</span>
      <span class="user-profile-col">${formatHm(day.charged_minutes)}</span>
      <span class="user-profile-col">${day.completed_count}</span>
    </summary>
    <div class="user-profile-day-body">${dayBodyHtml(day)}</div>
  </details>`;
}

function weekHtml(payload) {
  return `<div class="user-profile-week-nav">
      <button type="button" class="secondary-btn user-profile-prev" aria-label="Previous week">◀</button>
      <strong>${escapeHtml(weekLabel(payload.week_start, payload.week_end))}</strong>
      <button type="button" class="secondary-btn user-profile-next" aria-label="Next week">▶</button>
    </div>
    <div class="user-profile-summary user-profile-head" aria-hidden="true">
      <span class="user-profile-col-day">Day</span><span class="user-profile-col">Clocked</span>
      <span class="user-profile-col">Charged</span><span class="user-profile-col">Completed</span>
    </div>
    ${payload.days.map(dayHtml).join("")}
    <div class="user-profile-summary user-profile-totals">
      <span class="user-profile-col-day">Week</span>
      <span class="user-profile-col">${formatHm(payload.total_clocked_minutes)}</span>
      <span class="user-profile-col">${formatHm(payload.total_charged_minutes)}</span>
      <span class="user-profile-col">${payload.total_completed}</span>
    </div>
    ${payload.total_adjustment_minutes ? `<p class="hint">Adjustments this week: ${formatHm(payload.total_adjustment_minutes)} (shown per day, not counted as charged).</p>` : ""}`;
}

export function mountUserProfile(container, user, { onBack } = {}) {
  let week = null;
  let requestId = 0;
  const archived = user.archived_at ? ` <span class="muted">(archived)</span>` : "";

  container.innerHTML = `<section class="user-profile" aria-labelledby="user-profile-heading">
    <div class="user-profile-header">
      <button type="button" class="hub-link-btn user-profile-back">‹ Back to users</button>
      <h3 id="user-profile-heading">${escapeHtml(formatUserName(user))}${archived}</h3>
      <p class="muted">${escapeHtml(roleLabel(user.role))}</p>
    </div>
    <div class="user-profile-body"></div>
  </section>`;
  const body = container.querySelector(".user-profile-body");
  container.querySelector(".user-profile-back").addEventListener("click", () => onBack?.());

  async function openWorkOrder(number) {
    const [{ openWorkOrdersByNumberSearch }, { showPage }] = await Promise.all([
      import("./workOrders.js"), import("./nav.js"),
    ]);
    openWorkOrdersByNumberSearch(number);
    showPage("work-orders");
  }

  function wire(payload) {
    body.querySelector(".user-profile-prev").addEventListener("click", () => load(shiftMonday(payload.week_start, -7)));
    body.querySelector(".user-profile-next").addEventListener("click", () => load(shiftMonday(payload.week_start, 7)));
    body.querySelectorAll(".user-profile-wo-btn").forEach((button) => {
      button.addEventListener("click", () => { void openWorkOrder(button.dataset.number); });
    });
  }

  async function load(requested) {
    const id = ++requestId;
    body.innerHTML = `<table class="stack-table"><tbody>${skeletonTableRows(4, 7)}</tbody></table>`;
    try {
      const payload = await apiGetPersonWeek(user.id, { week: requested });
      if (id !== requestId) return;
      week = payload.week_start;
      body.innerHTML = weekHtml(payload);
      wire(payload);
    } catch (err) {
      if (id !== requestId) return;
      body.innerHTML = `<p class="user-profile-error error">${escapeHtml(friendlyError(err, "Could not load this week."))} <button type="button" class="secondary-btn user-profile-retry">Retry</button></p>`;
      body.querySelector(".user-profile-retry").addEventListener("click", () => load(requested ?? week));
    }
  }

  void load(week);
}
```

Append to `static/styles.css`:

```css
/* --- Users page: per-person weekly profile ------------------------------ */
.user-profile-header { display: flex; flex-wrap: wrap; align-items: baseline; gap: var(--space-2) var(--space-3); margin-bottom: var(--space-3); }
.user-profile-header h3 { margin: 0; }
.user-profile-week-nav { display: flex; align-items: center; gap: var(--space-2); margin-bottom: var(--space-2); }
.user-profile-summary { display: grid; grid-template-columns: 1.6fr 1fr 1fr 1fr; gap: var(--space-2); padding: var(--space-2) var(--space-3); align-items: center; }
.user-profile-head { font-size: var(--fs-xs); text-transform: uppercase; color: var(--text-muted); }
.user-profile-day { border-top: 1px solid var(--border); }
.user-profile-day > summary { cursor: pointer; list-style: none; }
.user-profile-day > summary::-webkit-details-marker { display: none; }
.user-profile-day[open] > summary { background: var(--panel-well); }
.user-profile-day-body { padding: 0 var(--space-3) var(--space-3); }
.user-profile-list-title { margin: var(--space-2) 0 var(--space-1); font-size: var(--fs-xs); text-transform: uppercase; color: var(--text-muted); }
.user-profile-list { margin: 0; padding-left: var(--space-4); }
.user-profile-totals { border-top: 2px solid var(--border); font-weight: 600; }
```

If any `--space-*`, `--fs-xs`, `--panel-well`, `--border`, or `--text-muted` token does not exist in `styles.css` (`grep -n "^\s*--border:" backend/static/styles.css`), substitute the closest existing token rather than a literal value.

- [ ] **Step 5: Run; expect PASS**

Run: `npx vitest run tests/frontend/views/userProfile.test.js`. Check the module is under 500 lines: `wc -l backend/static/views/userProfile.js`.

- [ ] **Step 6: Commit**

```bash
git add backend/static/views/userProfile.js backend/static/styles.css tests/frontend/views/userProfile.test.js tests/frontend/helpers/factories.js
git commit -m "feat(users): per-person weekly profile panel"
```

---

### Task 6: Wire the Users page

**Files:**
- Modify: `static/pages/saved-users.html` (add the container)
- Modify: `static/views/users.js` (name button, swap/back, delegation branch)
- Modify: `tests/frontend/views/usersActionCoverage.test.js:17-20` (frozen list)
- Test: `tests/frontend/views/users.test.js` (append a `describe`)

**Interfaces:**
- Consumes: `mountUserProfile(container, user, { onBack })` from Task 5.
- Produces: `button.user-profile-btn[data-id]` in the First Name cell for Admin+ viewers on `technician | supervisor | techfm_oa` rows; `#user-profile` container; `#users-table` hidden while the profile shows.

- [ ] **Step 1: Write the failing tests** (append to `tests/frontend/views/users.test.js`)

```javascript
describe("the profile hand-off", () => {
  const PROFILE_ROLES = ["technician", "supervisor", "techfm_oa"];
  const crew = () => ROLES.map((role) => userFactory({ role }));

  it.each(["owner", "admin"])("renders a name button only on crew rows for an %s", async (role) => {
    const users = crew();
    await openUsers({ role, users });
    for (const target of users) {
      const button = rowFor(target.username).querySelector(".user-profile-btn");
      expect(Boolean(button), `${role} -> ${target.role}`).toBe(PROFILE_ROLES.includes(target.role));
    }
  });

  it.each(["techfm_oa", "supervisor", "technician"])("renders no name button for a %s viewer", async (role) => {
    await openUsers({ role, users: crew() });
    expect(document.querySelectorAll(".user-profile-btn")).toHaveLength(0);
  });

  it("swaps the table for the profile and Back restores it without refetching", async () => {
    const users = crew();
    const tech = users.find((u) => u.role === "technician");
    server.use(http.get("/hub/people/:id/week", () => HttpResponse.json({
      user: tech, archived: false, week_start: "2026-09-14", week_end: "2026-09-20",
      server_now: "2026-09-16T15:00:00Z", days: [], total_clocked_minutes: 0,
      total_charged_minutes: 0, total_adjustment_minutes: 0, total_completed: 0, reviewable: false,
    })));
    await openUsers({ role: "admin", users });
    rowFor(tech.username).querySelector(".user-profile-btn").click();
    await vi.waitFor(() => expect(document.querySelector(".user-profile-header")).not.toBeNull());
    expect(document.getElementById("users-table").hidden).toBe(true);
    expect(document.querySelector(".user-profile-header").textContent).toContain(tech.last_name);
    document.querySelector(".user-profile-back").click();
    expect(document.getElementById("users-table").hidden).toBe(false);
    expect(document.getElementById("user-profile").hidden).toBe(true);
    expect(requestFor("/users/")).toBeNull();
    expect(rows().length).toBe(users.length);
  });
});
```

- [ ] **Step 2: Run; expect FAIL** (no `.user-profile-btn`): `npx vitest run tests/frontend/views/users.test.js`

- [ ] **Step 3: Add the container**

In `static/pages/saved-users.html`, after `<p id="users-message"></p>` and still inside `#users-section`:

```html
            <div id="user-profile" hidden></div>
```

- [ ] **Step 4: Wire `users.js`**

Add module-level nodes next to `usersMessage`:

```javascript
const usersTable = document.getElementById("users-table");
const userProfile = document.getElementById("user-profile");
// Roles whose name opens the weekly profile, for an Admin+ viewer only.
const PROFILE_ROLES = ["technician", "supervisor", "techfm_oa"];
```

In `renderUsersTable()`, compute per row and replace the First Name cell:

```javascript
    const canProfile = roleAtLeast(actorRole, "admin") && PROFILE_ROLES.includes(user.role);
    const firstName = escapeHtml(user.first_name || "Name unavailable");
    const firstNameCell = canProfile
      ? `<button type="button" class="user-profile-btn hub-link-btn" data-id="${user.id}">${firstName}</button>`
      : firstName;
```

and use `${firstNameCell}${archivedTag}` in the `First Name` `<td>`.

Add two functions after `renderUsersTable`:

```javascript
async function showProfile(user) {
  const { mountUserProfile } = await import("./userProfile.js");
  usersTable.hidden = true;
  userProfile.hidden = false;
  mountUserProfile(userProfile, user, { onBack: hideProfile });
}

// Back restores the table as it was: no refetch, the cache is still current.
function hideProfile() {
  userProfile.hidden = true;
  userProfile.innerHTML = "";
  usersTable.hidden = false;
}
```

Call `hideProfile()` as the first line of `renderUsersTable()` so a reload after an edit never leaves a stale profile open. In the `usersTbody` click delegation, add before the `edit-user-name-btn` branch:

```javascript
  if (target.classList.contains("user-profile-btn")) {
    const user = getUsers().find((candidate) => candidate.id === target.dataset.id);
    if (user) await showProfile(user);
    return;
  }
```

- [ ] **Step 5: Update the action audit**

In `tests/frontend/views/usersActionCoverage.test.js` add `"user-profile-btn",` to `frozen` (alphabetical: after `"restore-user-btn"`). The `hub-link-btn` second class is excluded by the audit's first-class capture, which is why `user-profile-btn` is listed first in the `class` attribute.

- [ ] **Step 6: Run; expect PASS**

Run: `npx vitest run tests/frontend/views/users.test.js tests/frontend/views/usersActions.test.js tests/frontend/views/usersActionCoverage.test.js`

- [ ] **Step 7: Commit**

```bash
git add backend/static/pages/saved-users.html backend/static/views/users.js tests/frontend/views/users.test.js tests/frontend/views/usersActionCoverage.test.js
git commit -m "feat(users): open a crew member's weekly profile from the Users page"
```

---

### Task 7: Docs, served-source check, full targeted run

**Files:**
- Modify: `docs/endpoint-map.md` (one row after H15 in the User Hub table; one line in the `AttendanceWeekResponse` contract area pointing at `PersonWeekResponse`)
- Modify: `docs/current-state.md` (one feature row after the `Attendance (...)` row, line ~113)

- [ ] **Step 1: Endpoint map row** (match the H8 row's column order: id · method · path · gate · chain · tables · api fn · views)

```
| H16 | GET | `/hub/people/{user_id}/week?week=` | **admin only** | `hub.py` → `work_order_report.resolve_week` + `person_week.week_payload` → `attendance_week.week_payload` (target row) + `labor_summary.crew_range_summaries` (`cap_running=True`) + one `work_orders ⋈ work_order_technicians` query by `completed_at` | users (r), attendance_punches (r), work_order_labor_sessions (r), work_order_labor (r), work_orders (r), work_order_technicians (r) — side-effect-free; target must be Technician/Team Lead/TechFM OA (403), archived allowed, unknown 404 | `apiGetPersonWeek` | `users.js`, `userProfile.js`, `hubWeek.js` |
```

Add under the response-contract section near `AttendanceWeekResponse` (line ~951): `` **`PersonWeekResponse`** — `GET /hub/people/{user_id}/week` (**admin only**): `user`, `archived`, `week_start/week_end`, `server_now`, seven `days` (`clocked_minutes`, `charged_minutes` = closed + capped running, `adjustment_minutes` shown never summed, `completed_count`, `needs_review`, `has_open`, and the four detail lists), week totals, `reviewable`. Wall-clock minutes, no money. ``

- [ ] **Step 2: current-state row**

```
| User profile (per-person weekly history on the Users page) | `services/person_week.py`, `schemas/hub.py` (`PersonWeek*`), `routers/hub.py` (`GET /hub/people/{user_id}/week`, **admin only**), `static/views/userProfile.js`, `static/views/hubWeek.js` (shared week helpers, also used by `hubAttendanceHours.js`), `static/views/users.js`, `static/pages/saved-users.html`, `static/api.js`, `static/styles.css` | `test_person_week_service.py`, `test_person_week_router.py`, `test_route_role_gates.py`, `tests/frontend/views/userProfile.test.js`, `users.test.js`, `unit/hubWeek.test.js` | Admin/Owner clicks a Technician, Team Lead, or TechFM OA name; the table is replaced by a Mon–Sun week of `<details>` rows (clocked · charged · completed) with the detail lists inside. Read-only, side-effect-free; "completed" = crew member on a work order whose `completed_at` falls on that Central day (reopen clears it); wall-clock minutes, no billed number or dollars |
```

If either doc is over its word budget after the edit, delete one stale line in the same edit (budgets in each doc's header).

- [ ] **Step 3: Run the bounded suites**

```
cd backend && venv/Scripts/python -m pytest tests/test_person_week_service.py tests/test_person_week_router.py tests/test_route_role_gates.py tests/test_hub_router.py tests/test_attendance_week_router.py tests/test_docs_endpoints.py -q
cd .. && npx vitest run tests/frontend/unit/hubWeek.test.js tests/frontend/views/userProfile.test.js tests/frontend/views/users.test.js tests/frontend/views/usersActions.test.js tests/frontend/views/usersActionCoverage.test.js tests/frontend/views/hubAttendanceHours.test.js tests/frontend/views/hubTimesheetsTab.test.js tests/frontend/views/nav.test.js
```

Expected: all PASS. `test_docs_endpoints.py` exists and may check that every route appears in `endpoint-map.md`; if it fails, the H16 path string must match the route exactly.

- [ ] **Step 4: Commit**

```bash
git add docs/endpoint-map.md docs/current-state.md
git commit -m "docs: user profile weekly history (H16)"
```

Do not push: pushing main deploys. Hand the branch to the user for the in-app check (Users page as Admin: click a technician, step a week back, expand a day, open a work order number, Back).

---

## Self-review notes

- Spec coverage: D1/D2 (Task 2 roles + Task 3 gate), D3 (archived test), D4 (completed query + reopen test), D5 (`resolve_week` in route, `shiftMonday` in picker), D6 (Task 6 swap/back), D7 (`<details>`), D8 (no commit; router no-sweep test), D9 (no billed read; `"billed" not in response.text`), D10 (nothing added). Docs rows in Task 7.
- Deviation from spec: `users.test.js` already exists, so the new cases are a `describe` appended there, not a new file. Error class is `PersonNotProfilableError`. `userProfile.js` is loaded by dynamic `import()` from `users.js` and itself dynamic-imports the Work Orders hand-off, to keep the Users-page module graph (and its test fixture) unchanged.
- Skipped: swapping `hubTimesheetLeaderboard.js`'s duplicate helpers to `hubWeek.js` (spec lists Hours only); one-line follow-up if wanted.
