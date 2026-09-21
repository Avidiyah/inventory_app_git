# Attendance P4b — the live roster, `attendance.changed`, and the retirement

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the attendance timesheet. A live roster strip that says who is on shift and who has a reason to be charging, an `attendance.changed` envelope that keeps it fresh, and the retirement of `GET /hub/timesheets` — after which Timesheets is an Admin+ tab with two sub-tabs and no third.

**Architecture:** A new `services/attendance_live.py` answers the roster in five bounded queries and adds exactly one rule to the domain state machine — an open labor session past `LABOR_SESSION_MAX_MINUTES` is **not** charging, decided by the same `work_orders.capped_session_end` the week read already uses. `GET /hub/attendance/live` serves it at the Admin floor, side-effect-free like every other attendance read. A new `routers/_attendance_events.py` emits `attendance.changed` from the six punch writes, on the `_stock_events.py` pattern. The frontend gains `views/hubAttendanceRoster.js`, which the comparison sub-tab mounts above its grid and ticks from `idle_since` + skew; `hubTimesheetsTab.js` loses its `crew` half and `views/hubTimesheets.js` goes with it.

**Tech Stack:** FastAPI + SQLAlchemy + Pydantic v2 (backend), pytest (backend tests), vanilla ES modules + Vitest/MSW/jsdom (frontend).

**Spec:** `docs/superpowers/specs/2026-09-21-attendance-timesheet-design.md` — §4 (endpoints), §5 (realtime), §6 (frontend), §7 (the retirement), §11 (phasing). P4a's plan for shape, conventions and what it handed forward: `docs/superpowers/plans/2026-09-21-attendance-p4a-charged-vs-clocked.md`.

## Global Constraints

**Seven decisions taken at planning time. Where they differ from the spec or from P4a's inherited notes, they win.**

1. **Six emitters, not seven.** P4a's note and `open-work.md` both say "the four self-scoped punch routes and the three admin punch writes." `routers/attendance.py` has four routes, but one of them is `GET /attendance/me`, a read. The emitter set is **three** self-scoped writes (`punch_in`, `punch_out`, `self_close`) plus **three** admin writes (`add_hub_attendance_punch`, `edit_hub_attendance_punch`, `delete_hub_attendance_punch`) — six. Correct the note when the docs are updated in Task 10.

2. **`attendance.changed` audience is Admin.** `labor.session.changed` is Supervisor+ because a crew board exists at that rank. Nothing below Admin can open the only consumer, so a lower audience would be pure noise. `id` is always `None`, like its sibling.

3. **The idle anchor moves into the domain.** `domain/attendance.py` gains `idle_anchor()`, and `idle_minutes()` is refactored to call it. The browser ticks from that instant and the server reports the minutes; one function owning the anchor is what stops the two disagreeing at the moment a card changes colour.

4. **No new timer.** The roster ticks on nothing of its own; it borrows `userHub.js`'s existing 1-second-equivalent lifecycle via exported `startHubRosterTicking` / `stopHubRosterTicking` hung off the same `visibilitychange` listener the clock uses, and the 60-second refetch is a call added inside `startCrewSafetyRefresh`'s existing interval. The frontend suite asserts `vi.getTimerCount() === 0` after `stopClock()`; a second interval would fail it.

5. **The roster's sort is the server's, and it is only re-sorted on a fetch.** A tick may recolour a card in place; it never reorders the list. A yellow that crosses ten minutes sits out of position for at most one poll, which is a smaller lie than a list that reshuffles under a reading eye.

6. **`labor_summary.crew_range_summaries` stays. `MAX_TIMESHEET_RANGE_DAYS`, `TimesheetRangeInvalidError` and `TimesheetRangeTooLargeError` go.** Spec §7 expects the opposite of the second half; it is wrong — `timesheets_hub` is their only caller, verified. The `.hub-timesheet-table*` CSS also stays: `hubGraphs.js:125` and `hubReport.js:111` both borrow those classes.

7. **Nothing is deleted before its replacement is green.** Tasks 1–7 add; Tasks 8–9 remove. A single commit per task, and the retirement never lands in the same commit as the feature that justifies it.

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/domain/attendance.py` | + `idle_anchor()`; `idle_minutes()` calls it |
| `backend/app/services/attendance_live.py` | **new** — the roster payload, five bounded queries, side-effect-free |
| `backend/app/schemas/attendance.py` | + `AttendanceLiveEntry`, `AttendanceLiveResponse` |
| `backend/app/routers/hub.py` | + `get_hub_attendance_live`; − the two timesheet routes and their four helpers |
| `backend/app/domain/realtime.py` | + `EVENT_ATTENDANCE_CHANGED` + its audience |
| `backend/app/routers/_attendance_events.py` | **new** — `emit_attendance_changed()`, one function |
| `backend/app/routers/attendance.py` | + emit on the three self-scoped writes |
| `backend/app/services/hub.py` | − `timesheets_hub`, `timesheet_csv`, the four timesheet dataclasses, `MAX_TIMESHEET_RANGE_DAYS` |
| `backend/app/schemas/hub.py` | − the five `HubTimesheet*` models |
| `backend/app/domain/errors.py`, `routers/_errors.py` | − the two timesheet range errors |
| `backend/static/api.js` | + `apiGetHubAttendanceLive`; − the two timesheet wrappers |
| `backend/static/views/hubAttendanceRoster.js` | **new** — the roster strip, ticking, the absent footer |
| `backend/static/views/hubAttendanceCompare.js` | + the roster mount above the grid |
| `backend/static/views/hubTimesheetsTab.js` | + the live cache, the poll, the subscription; − the `crew` half |
| `backend/static/views/hubTimesheets.js` | **deleted** |
| `backend/static/views/userHub.js` | Timesheets tab moves to Admin+; roster tick lifecycle |
| `backend/static/styles.css` | + `.hub-roster-*` |
| `backend/static/tips.js` | − `hub.timesheets` |

---

## Task 1: `idle_anchor` and the roster service

**Files:**
- Modify: `backend/app/domain/attendance.py:46-68`
- Create: `backend/app/services/attendance_live.py`
- Test: `backend/tests/test_attendance_domain.py` (append), `backend/tests/test_attendance_live_service.py` (create)

**Interfaces:**
- Consumes: `domain.attendance.shift_state` / `IDLE_RED_MINUTES` / the four `STATE_*` constants; `domain.work_orders.capped_session_end`; `services.attendance.live_punches`.
- Produces: `attendance_live.roster(db, *, now=None) -> LiveRoster`, and the frozen dataclasses `RosterEntry(user, state, punch_started_at, idle_since, idle_minutes, charging_since, work_order_number)` and `LiveRoster(server_now, idle_red_minutes, on_shift, absent, on_shift_count, charging_count, idle_count)`.

- [x] **Step 1: Write the failing domain test**

Append to `backend/tests/test_attendance_domain.py`:

```python
def test_idle_anchor_is_the_punch_when_there_is_no_labor():
    started = datetime(2026, 9, 21, 13, 0, tzinfo=timezone.utc)
    assert attendance.idle_anchor(
        punch_started_at=started, last_labor_ended_at=None
    ) == started


def test_idle_anchor_is_the_later_of_the_punch_and_the_last_stop():
    started = datetime(2026, 9, 21, 13, 0, tzinfo=timezone.utc)
    stopped = datetime(2026, 9, 21, 15, 30, tzinfo=timezone.utc)
    assert attendance.idle_anchor(
        punch_started_at=started, last_labor_ended_at=stopped
    ) == stopped
    # A stop from a previous shift never drags the anchor backwards.
    earlier = datetime(2026, 9, 20, 22, 0, tzinfo=timezone.utc)
    assert attendance.idle_anchor(
        punch_started_at=started, last_labor_ended_at=earlier
    ) == started


def test_idle_minutes_is_measured_from_the_anchor():
    started = datetime(2026, 9, 21, 13, 0, tzinfo=timezone.utc)
    now = datetime(2026, 9, 21, 13, 42, 30, tzinfo=timezone.utc)
    anchor = attendance.idle_anchor(
        punch_started_at=started, last_labor_ended_at=None
    )
    assert attendance.idle_minutes(
        punch_started_at=started, last_labor_ended_at=None, now=now
    ) == int((now - anchor).total_seconds() // 60) == 42
```

- [x] **Step 2: Run it to verify it fails**

Run: `cd backend && python -m pytest tests/test_attendance_domain.py -q -k idle_anchor`
Expected: FAIL — `module 'app.domain.attendance' has no attribute 'idle_anchor'`.

- [x] **Step 3: Add `idle_anchor` and refactor `idle_minutes`**

In `backend/app/domain/attendance.py`, insert above `idle_minutes` and rewrite its body:

```python
def idle_anchor(
    *,
    punch_started_at: datetime,
    last_labor_ended_at: Optional[datetime],
) -> datetime:
    """The instant idle time is measured from: the later of the punch and the
    last reason this person had to be charging.

    Split out of `idle_minutes` because the live roster ticks client-side.
    The browser counts seconds from this instant and the server reports the
    minutes; one function owning the anchor is what keeps the two from
    disagreeing at the moment a card changes colour.
    """
    anchor = labor_day.as_utc(punch_started_at)
    if last_labor_ended_at is not None:
        anchor = max(anchor, labor_day.as_utc(last_labor_ended_at))
    return anchor


def idle_minutes(
    *,
    punch_started_at: datetime,
    last_labor_ended_at: Optional[datetime],
    now: datetime,
) -> int:
    """Whole minutes since `idle_anchor`.

    With no labor yet, the punch itself is the anchor -- the accepted
    consequence in §2 is that a slow start after arrival shows red before the
    first job, which is correct information, not a false alarm.

    Truncated, not rounded: the row prints `idle 12m` beside the color, and a
    number that rounds up would cross `IDLE_RED_MINUTES` a half-minute before
    the color does.
    """
    anchor = idle_anchor(
        punch_started_at=punch_started_at,
        last_labor_ended_at=last_labor_ended_at,
    )
    seconds = (labor_day.as_utc(now) - anchor).total_seconds()
    return max(0, int(seconds // 60))
```

- [x] **Step 4: Run the domain suite**

Run: `cd backend && python -m pytest tests/test_attendance_domain.py -q`
Expected: PASS, every test — the refactor must not move an existing number.

- [x] **Step 5: Write the failing service test**

Create `backend/tests/test_attendance_live_service.py`. Model the fixtures on `backend/tests/test_attendance_compare_service.py` — same `db` fixture, same user/work-order helpers; read that file first and reuse its helper names rather than inventing parallel ones.

```python
"""The Admin live roster: who is on shift, who is charging, who is idle."""

from datetime import datetime, timedelta, timezone

from app.domain import attendance as attendance_domain
from app.domain import work_orders as wo
from app.services import attendance_live


def test_somebody_with_no_punch_is_absent_not_gray_on_the_strip(db, technician):
    now = datetime(2026, 9, 21, 15, 0, tzinfo=timezone.utc)
    payload = attendance_live.roster(db, now=now)
    assert [e.user.id for e in payload.absent] == [technician.id]
    assert payload.on_shift == []
    assert payload.on_shift_count == 0


def test_an_open_punch_with_a_running_clock_is_green_and_names_the_job(
    db, technician, work_order
):
    now = datetime(2026, 9, 21, 15, 0, tzinfo=timezone.utc)
    open_punch(db, technician, started_at=now - timedelta(hours=2))
    open_session(db, technician, work_order, started_at=now - timedelta(minutes=20))
    entry = attendance_live.roster(db, now=now).on_shift[0]
    assert entry.state == attendance_domain.STATE_GREEN
    assert entry.work_order_number == work_order.number
    assert entry.charging_since is not None
    assert entry.idle_since is None
    assert entry.idle_minutes == 0


def test_an_open_punch_with_no_clock_goes_yellow_then_red(db, technician):
    now = datetime(2026, 9, 21, 15, 0, tzinfo=timezone.utc)
    open_punch(db, technician, started_at=now - timedelta(minutes=5))
    assert attendance_live.roster(db, now=now).on_shift[0].state == (
        attendance_domain.STATE_YELLOW
    )
    later = now + timedelta(minutes=attendance_domain.IDLE_RED_MINUTES)
    entry = attendance_live.roster(db, now=later).on_shift[0]
    assert entry.state == attendance_domain.STATE_RED
    assert entry.idle_minutes >= attendance_domain.IDLE_RED_MINUTES


def test_a_clock_past_the_cap_is_not_charging(db, technician, work_order):
    """The failure this rule exists to stop: a forgotten clock reading green
    forever. Past `LABOR_SESSION_MAX_MINUTES` the session has effectively
    ended, and idle is measured from where a sweep would have closed it."""
    now = datetime(2026, 9, 21, 15, 0, tzinfo=timezone.utc)
    started = now - timedelta(minutes=wo.LABOR_SESSION_MAX_MINUTES + 60)
    open_punch(db, technician, started_at=started)
    open_session(db, technician, work_order, started_at=started)
    entry = attendance_live.roster(db, now=now).on_shift[0]
    assert entry.state == attendance_domain.STATE_RED
    assert entry.work_order_number is None
    assert entry.idle_minutes == 60


def test_the_strip_sorts_red_then_yellow_then_green_longest_idle_first(
    db, technician, technician_two, technician_three, work_order
):
    now = datetime(2026, 9, 21, 15, 0, tzinfo=timezone.utc)
    open_punch(db, technician, started_at=now - timedelta(minutes=45))
    open_punch(db, technician_two, started_at=now - timedelta(minutes=3))
    open_punch(db, technician_three, started_at=now - timedelta(hours=3))
    open_session(db, technician_three, work_order, started_at=now - timedelta(minutes=5))
    payload = attendance_live.roster(db, now=now)
    assert [e.state for e in payload.on_shift] == [
        attendance_domain.STATE_RED,
        attendance_domain.STATE_YELLOW,
        attendance_domain.STATE_GREEN,
    ]
    assert payload.on_shift_count == 3
    assert payload.charging_count == 1
    assert payload.idle_count == 2


def test_the_roster_writes_nothing(db, technician, work_order):
    """Spec §4: every attendance read is side-effect-free, which is what lets
    the sub-tab poll it. A forgotten clock is clipped on the way out, never
    swept."""
    now = datetime(2026, 9, 21, 15, 0, tzinfo=timezone.utc)
    started = now - timedelta(minutes=wo.LABOR_SESSION_MAX_MINUTES + 60)
    open_punch(db, technician, started_at=started)
    session = open_session(db, technician, work_order, started_at=started)
    attendance_live.roster(db, now=now)
    db.expire_all()
    assert session.ended_at is None


def test_an_admin_who_punches_in_is_not_colour_judged(db, admin_user):
    """Spec §6: the coloured roster covers `WORK_ORDER_TECHNICIAN_ROLES`
    only. Their hours still appear in the Hours grid."""
    now = datetime(2026, 9, 21, 15, 0, tzinfo=timezone.utc)
    open_punch(db, admin_user, started_at=now - timedelta(hours=1))
    payload = attendance_live.roster(db, now=now)
    assert payload.on_shift == []
    assert payload.absent == []
```

- [x] **Step 6: Run it to verify it fails**

Run: `cd backend && python -m pytest tests/test_attendance_live_service.py -q`
Expected: FAIL — `No module named 'app.services.attendance_live'`.

- [x] **Step 7: Write the service**

Create `backend/app/services/attendance_live.py`:

```python
"""The Admin live roster: who is on shift right now, and who is charging.

Layer: services. Read-only and **side-effect-free** (spec §4) -- no sweep, no
row locks, no commit -- which is what lets the Charged vs clocked sub-tab
poll it on the hub's existing 60-second safety timer.

Clocked only, again: nothing here produces a pay number or a billed one. It
answers "is this person at work, and do they have a reason to be charging",
and every rule behind that answer lives in `domain.attendance`.

**The one rule this module adds to the state machine:** an open labor session
past `work_orders.LABOR_SESSION_MAX_MINUTES` is *not* charging. A clock
nobody stopped would otherwise read green forever, which is the exact failure
the roster exists to catch. `work_orders.capped_session_end` decides it --
the same function the week read uses -- so the two surfaces cannot disagree
about a forgotten clock, and the abandoned session's capped end becomes the
idle anchor rather than the last *closed* session, which would read older
than it is.

Bounded queries, not N+1: one population read, one open-punch read, one
running-session read, one grouped `max(ended_at)`, one work-order number
lookup. None of them grows with the week, and a crew is tens of people.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.domain import attendance, labor_day, roles
from app.domain import work_orders as wo
from app.models import AttendancePunch, User, WorkOrder, WorkOrderLaborSession
from app.services import attendance as attendance_service


@dataclass(frozen=True)
class RosterEntry:
    """One card. `idle_since` and `charging_since` are the two instants the
    browser ticks from -- exactly one of them is set on an on-shift entry,
    and neither on an absent one."""

    user: User
    state: str
    punch_started_at: Optional[datetime]
    idle_since: Optional[datetime]
    idle_minutes: int
    charging_since: Optional[datetime]
    work_order_number: Optional[str]


@dataclass(frozen=True)
class LiveRoster:
    """`idle_red_minutes` rides along so the client can recolour a card
    between polls without a second copy of the threshold."""

    server_now: datetime
    idle_red_minutes: int
    on_shift: list[RosterEntry]
    absent: list[RosterEntry]
    on_shift_count: int
    charging_count: int
    idle_count: int


# Red first: the strip is read top-down by somebody looking for a problem.
_STATE_ORDER = {
    attendance.STATE_RED: 0,
    attendance.STATE_YELLOW: 1,
    attendance.STATE_GREEN: 2,
}


def _population(db: Session) -> list[User]:
    """Live Supervisors and Technicians only (spec §6). An Admin who punches
    in accrues hours in the Hours grid and is deliberately not colour-judged
    here -- the roster is about the crew on the ground."""
    return (
        db.query(User)
        .filter(
            User.role.in_(roles.WORK_ORDER_TECHNICIAN_ROLES),
            User.archived_at.is_(None),
        )
        .all()
    )


def roster(db: Session, *, now: Optional[datetime] = None) -> LiveRoster:
    now = now or datetime.now(timezone.utc)
    moment = labor_day.as_utc(now)
    people = _population(db)
    ids = [person.id for person in people]
    if not ids:
        return LiveRoster(
            server_now=now, idle_red_minutes=attendance.IDLE_RED_MINUTES,
            on_shift=[], absent=[], on_shift_count=0, charging_count=0,
            idle_count=0,
        )

    punches = {
        punch.user_id: punch
        for punch in attendance_service.live_punches(db)
        .filter(
            AttendancePunch.user_id.in_(ids),
            AttendancePunch.ended_at.is_(None),
        )
        .all()
    }
    running = {
        session.technician_id: session
        for session in db.query(WorkOrderLaborSession)
        .filter(
            WorkOrderLaborSession.technician_id.in_(ids),
            WorkOrderLaborSession.ended_at.is_(None),
        )
        .all()
    }
    last_closed = dict(
        db.query(
            WorkOrderLaborSession.technician_id,
            func.max(WorkOrderLaborSession.ended_at),
        )
        .filter(
            WorkOrderLaborSession.technician_id.in_(ids),
            WorkOrderLaborSession.ended_at.is_not(None),
        )
        .group_by(WorkOrderLaborSession.technician_id)
        .all()
    )
    numbers = (
        dict(
            db.query(WorkOrder.id, WorkOrder.number)
            .filter(
                WorkOrder.id.in_(
                    [session.work_order_id for session in running.values()]
                )
            )
            .all()
        )
        if running
        else {}
    )

    on_shift: list[RosterEntry] = []
    absent: list[RosterEntry] = []
    for person in people:
        punch = punches.get(person.id)
        if punch is None:
            absent.append(RosterEntry(
                user=person, state=attendance.STATE_GRAY, punch_started_at=None,
                idle_since=None, idle_minutes=0, charging_since=None,
                work_order_number=None,
            ))
            continue

        session = running.get(person.id)
        charging = False
        anchor = last_closed.get(person.id)
        if session is not None:
            effective_end = wo.capped_session_end(
                session.started_at, None, now=moment
            )
            charging = effective_end >= moment
            if not charging:
                # The forgotten clock's effective stop: the instant a sweep
                # would have written. Without it the abandoned session leaves
                # idle anchored on the last *closed* one, reading hours older
                # than the person actually is.
                anchor = (
                    effective_end if anchor is None
                    else max(labor_day.as_utc(anchor), effective_end)
                )

        state = attendance.shift_state(
            punch_started_at=punch.started_at, labor_running=charging,
            last_labor_ended_at=anchor, now=moment,
        )
        on_shift.append(RosterEntry(
            user=person,
            state=state,
            punch_started_at=punch.started_at,
            idle_since=None if charging else attendance.idle_anchor(
                punch_started_at=punch.started_at, last_labor_ended_at=anchor,
            ),
            idle_minutes=0 if charging else attendance.idle_minutes(
                punch_started_at=punch.started_at, last_labor_ended_at=anchor,
                now=moment,
            ),
            charging_since=session.started_at if charging else None,
            work_order_number=(
                numbers.get(session.work_order_id) if charging else None
            ),
        ))

    # Red, then yellow, then green; longest idle first inside a colour; name
    # to break a tie, so two equal rows do not swap places between polls.
    on_shift.sort(
        key=lambda e: (_STATE_ORDER[e.state], -e.idle_minutes, e.user.full_name)
    )
    absent.sort(key=lambda e: e.user.full_name)
    charging_count = sum(
        1 for entry in on_shift if entry.state == attendance.STATE_GREEN
    )
    return LiveRoster(
        server_now=now,
        idle_red_minutes=attendance.IDLE_RED_MINUTES,
        on_shift=on_shift,
        absent=absent,
        on_shift_count=len(on_shift),
        charging_count=charging_count,
        idle_count=len(on_shift) - charging_count,
    )
```

- [x] **Step 8: Run both suites**

Run: `cd backend && python -m pytest tests/test_attendance_live_service.py tests/test_attendance_domain.py tests/test_attendance_compare_service.py tests/test_attendance_week_service.py -q`
Expected: PASS. If a fixture name in Step 5 does not exist in `test_attendance_compare_service.py`, fix the *test* to use the real helper — do not add a parallel fixture.

- [x] **Step 9: Commit**

```bash
git add backend/app/domain/attendance.py backend/app/services/attendance_live.py backend/tests/test_attendance_live_service.py backend/tests/test_attendance_domain.py
git commit -m "feat(attendance): the live roster payload, and the idle anchor it ticks from"
```

---

## Task 2: `GET /hub/attendance/live`

**Files:**
- Modify: `backend/app/schemas/attendance.py` (append), `backend/app/routers/hub.py:157` (insert before `get_hub_attendance_week`), `backend/app/routers/hub.py:1-31` (module docstring)
- Modify: `backend/tests/test_route_role_gates.py:542-552`
- Test: `backend/tests/test_attendance_live_router.py` (create)

**Interfaces:**
- Consumes: `attendance_live.roster` from Task 1.
- Produces: `GET /hub/attendance/live` → `AttendanceLiveResponse`, Admin floor, no query parameters. Endpoint name `get_hub_attendance_live` — the name `test_route_role_gates.py` already names in its P4b comment.

- [x] **Step 1: Write the failing router test**

Create `backend/tests/test_attendance_live_router.py`, modelled on `backend/tests/test_attendance_week_router.py` (read it first; reuse its client and login helpers verbatim):

```python
"""`GET /hub/attendance/live` -- the roster, at the Admin floor."""


def test_the_roster_is_admin_only(client, as_role):
    for role in ("technician", "supervisor", "techfm_oa"):
        as_role(role)
        assert client.get("/hub/attendance/live").status_code == 403
    as_role("admin")
    assert client.get("/hub/attendance/live").status_code == 200


def test_the_roster_serialises_both_lists_and_the_three_counts(client, as_admin):
    body = client.get("/hub/attendance/live").json()
    assert set(body) == {
        "server_now", "idle_red_minutes", "on_shift", "absent",
        "on_shift_count", "charging_count", "idle_count",
    }
    assert body["idle_red_minutes"] == 10
    assert isinstance(body["on_shift"], list)
    assert isinstance(body["absent"], list)


def test_an_on_shift_entry_carries_the_two_tick_anchors(client, as_admin, punched_in_technician):
    entry = client.get("/hub/attendance/live").json()["on_shift"][0]
    assert set(entry) == {
        "user", "state", "punch_started_at", "idle_since", "idle_minutes",
        "charging_since", "work_order_number",
    }
    assert entry["punch_started_at"] is not None
    # Exactly one of the two anchors is set on any on-shift card.
    assert (entry["idle_since"] is None) != (entry["charging_since"] is None)
```

- [x] **Step 2: Run it to verify it fails**

Run: `cd backend && python -m pytest tests/test_attendance_live_router.py -q`
Expected: FAIL — 404 on every request; the route does not exist.

- [x] **Step 3: Add the schemas**

Append to `backend/app/schemas/attendance.py`:

```python
class AttendanceLiveEntry(BaseModel):
    """One roster card. Exactly one of `idle_since` / `charging_since` is set
    on an on-shift entry and neither on an absent one -- that is what the
    client ticks from, so it never has to guess which clock a card is
    running."""

    user: HubUser
    state: str
    punch_started_at: Optional[datetime] = None
    idle_since: Optional[datetime] = None
    idle_minutes: int
    charging_since: Optional[datetime] = None
    work_order_number: Optional[str] = None

    model_config = {"from_attributes": True}


class AttendanceLiveResponse(BaseModel):
    """The roster strip above Charged vs clocked (spec §6).

    `on_shift` is already sorted red -> yellow -> green, longest idle first;
    the client recolours a card between polls but never reorders the list.
    `absent` is everybody with no open punch, behind the `N not clocked in`
    footer. Both cover `WORK_ORDER_TECHNICIAN_ROLES` only.

    `idle_red_minutes` rides along so a card can cross the threshold
    client-side without a second copy of the number living in JavaScript."""

    server_now: datetime
    idle_red_minutes: int
    on_shift: list[AttendanceLiveEntry]
    absent: list[AttendanceLiveEntry]
    on_shift_count: int
    charging_count: int
    idle_count: int

    model_config = {"from_attributes": True}
```

- [x] **Step 4: Add the route**

In `backend/app/routers/hub.py`, extend the imports:

```python
from app.schemas.attendance import (
    AttendanceLiveResponse,
    AttendancePunchResponse,
    AttendanceWeekResponse,
    PunchAddRequest,
    PunchEditRequest,
)
from app.services import attendance as attendance_service
from app.services import attendance_compare
from app.services import attendance_live
```

Insert immediately above `get_hub_attendance_week`:

```python
@router.get("/attendance/live", response_model=AttendanceLiveResponse)
def get_hub_attendance_live(
    user: User = Depends(require_min_role(roles.ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """The roster strip: who is on shift, who is charging, who is idle and
    for how long, plus everybody with no open punch behind the footer.

    **Admin, not TechFM OA.** Same grounds as the week read beside it: this
    says where each person is right now, which is the pay record's live face
    (D1). `tests/test_route_role_gates.py` carries the matching exemption.

    No `week` and no parameters at all -- "now" is the only question it
    answers. Side-effect-free (spec §4): a clock nobody stopped is decided by
    `work_orders.capped_session_end` on the way out, never swept, which is
    what lets this be polled.
    """
    return attendance_live.roster(db, now=datetime.now(timezone.utc))
```

Add the route to the module docstring's list, after the `/hub/attendance/week` line:

```
- `GET /hub/attendance/live` admin only -- the roster: who is on shift and
  who has a reason to be charging, read-only and poll-safe
```

- [x] **Step 5: Amend the role-gate expectation**

In `backend/tests/test_route_role_gates.py`, replace the trailing comment line `# P4a adds the CSV export ... P4b adds \`get_hub_attendance_live\`.` with a statement of fact and add the name to the set:

```python
    # P4a adds the CSV export on the same grounds -- it *is* the pay record,
    # rendered for payroll. P4b adds the live roster: it says where each
    # person is right now, which is that record's live face, and TechFM OA
    # holding the operational toolkit is not a reason to hand them it.
    assert offenders == {
        "get_hub_report",
        "export_hub_report",
        "get_hub_attendance_week",
        "get_hub_attendance_live",
        "add_hub_attendance_punch",
        "edit_hub_attendance_punch",
        "delete_hub_attendance_punch",
        "export_hub_attendance",
    }
```

And add the individual pin beside `test_the_attendance_week_sits_above_techfm_oa`:

```python
def test_the_live_roster_sits_above_techfm_oa():
    # Pinned separately from the set above so a floor lowered by accident
    # names itself in the failure.
    assert _min_role_for(hub_router, "get_hub_attendance_live") == roles.ROLE_ADMIN
```

- [x] **Step 6: Run the router, gate and schema tests**

Run: `cd backend && python -m pytest tests/test_attendance_live_router.py tests/test_route_role_gates.py -q`
Expected: PASS.

- [x] **Step 7: Commit**

```bash
git add backend/app/schemas/attendance.py backend/app/routers/hub.py backend/tests/test_attendance_live_router.py backend/tests/test_route_role_gates.py
git commit -m "feat(attendance): GET /hub/attendance/live at the Admin floor"
```

---

## Task 3: the `attendance.changed` vocabulary

**Files:**
- Modify: `backend/app/domain/realtime.py:24-50` (`__all__`), `:91` (after `EVENT_USER_REQUEST_CHANGED`), `:96-108` (`_AUDIENCE_MIN_ROLE`)
- Test: `backend/tests/test_realtime_domain.py` (append)

**Interfaces:**
- Produces: `realtime.EVENT_ATTENDANCE_CHANGED == "attendance.changed"`, audience `roles.ROLE_ADMIN`. Task 4 imports it.

- [x] **Step 1: Write the failing test**

Append to `backend/tests/test_realtime_domain.py`:

```python
def test_attendance_events_reach_admin_and_above():
    for role in ("admin", "owner"):
        assert (
            realtime.audience_allows(realtime.EVENT_ATTENDANCE_CHANGED, role)
            is True
        ), role


def test_attendance_events_do_not_reach_techfm_oa_or_below():
    """Narrower than `labor.session.changed`, which is Supervisor+ because a
    crew board exists at that rank. The only consumer of this one is the
    Charged vs clocked sub-tab, which is Admin-only (D1), so anything lower
    is pure noise."""
    for role in ("techfm_oa", "supervisor", "technician"):
        assert (
            realtime.audience_allows(realtime.EVENT_ATTENDANCE_CHANGED, role)
            is False
        ), role


def test_attendance_changed_is_its_own_event_type():
    assert realtime.EVENT_ATTENDANCE_CHANGED == "attendance.changed"
    assert realtime.EVENT_ATTENDANCE_CHANGED != realtime.EVENT_LABOR_SESSION_CHANGED
```

- [x] **Step 2: Run it to verify it fails**

Run: `cd backend && python -m pytest tests/test_realtime_domain.py -q -k attendance`
Expected: FAIL — `module 'app.domain.realtime' has no attribute 'EVENT_ATTENDANCE_CHANGED'`.

- [x] **Step 3: Add the vocabulary entry**

In `backend/app/domain/realtime.py`, add `"EVENT_ATTENDANCE_CHANGED"` to `__all__` beside the other event names, then after `EVENT_USER_REQUEST_CHANGED`:

```python
# An attendance punch opened, closed, was self-closed (D5), or was corrected
# by an Admin. Like `labor.session.changed` this is a membership change to a
# board rather than one row's fields, so `id` is always `None` and the
# recipient refetches the roster and the week rather than targeting a card.
#
# Audience **Admin**, narrower than its sibling: the only consumer is the
# Charged vs clocked sub-tab, and nothing below Admin can open it. Not a
# security boundary -- P2 keeps row data out of the envelope -- but a lower
# audience here would be pure noise.
EVENT_ATTENDANCE_CHANGED = "attendance.changed"
```

And in `_AUDIENCE_MIN_ROLE`:

```python
    # The pay record's live face (D1). See the note on the constant.
    EVENT_ATTENDANCE_CHANGED: roles.ROLE_ADMIN,
```

- [x] **Step 4: Run it to verify it passes**

Run: `cd backend && python -m pytest tests/test_realtime_domain.py -q`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add backend/app/domain/realtime.py backend/tests/test_realtime_domain.py
git commit -m "feat(attendance): the attendance.changed vocabulary, audience Admin"
```

---

## Task 4: the six emitters

**Files:**
- Create: `backend/app/routers/_attendance_events.py`
- Modify: `backend/app/routers/attendance.py` (the three writes), `backend/app/routers/hub.py` (the three admin writes)
- Test: `backend/tests/test_realtime_emit.py` (append)

**Interfaces:**
- Consumes: `realtime.EVENT_ATTENDANCE_CHANGED` from Task 3.
- Produces: `_attendance_events.emit_attendance_changed()` — no arguments, always `entity_id=None`, best-effort. Called after the service returns, never before.

- [x] **Step 1: Write the failing tripwire test**

Append to `backend/tests/test_realtime_emit.py` (it already imports `inspect` and `_route_source`; add `from app.routers import attendance as attendance_router` and `from app.routers import hub as hub_router` to its imports if absent):

```python
def test_the_attendance_emitter_set_is_exactly_the_six_punch_writes():
    """Every write to the pay record invalidates the Admin roster; nothing
    else may. The two reads (`GET /attendance/me`, the week) are absent by
    design -- P4a's inherited note said "four self-scoped routes", but one of
    those four is a read, so the set is three plus three.

    The auto-punch on a work-order clock start needs no emit of its own: that
    route already emits `labor.session.changed`, which the live layer also
    subscribes to."""
    emitters = {
        route.endpoint.__name__
        for module in (attendance_router, hub_router)
        for route in module.router.routes
        if route.endpoint.__module__ == module.__name__
        and "emit_attendance_changed(" in inspect.getsource(route.endpoint)
    }

    assert emitters == {
        "punch_in",
        "punch_out",
        "self_close",
        "add_hub_attendance_punch",
        "edit_hub_attendance_punch",
        "delete_hub_attendance_punch",
    }


def test_a_punch_in_emits_an_attendance_changed_envelope(monkeypatch):
    user = SimpleNamespace(id=uuid.uuid4(), role=roles.ROLE_TECHNICIAN)
    envelopes = _capture_emits(monkeypatch)
    monkeypatch.setattr(
        attendance_router.attendance_service, "punch_in",
        lambda db, *, user: SimpleNamespace(id=uuid.uuid4()),
    )

    attendance_router.punch_in(user=user, db=None)

    assert [e["type"] for e in envelopes] == [
        realtime_policy.EVENT_ATTENDANCE_CHANGED
    ]
    assert envelopes[0]["id"] is None


def test_a_failed_punch_in_emits_nothing(monkeypatch):
    """The emit sits after the service returns, so a 409 on the already-open
    rule never tells an Admin something changed."""
    user = SimpleNamespace(id=uuid.uuid4(), role=roles.ROLE_TECHNICIAN)
    envelopes = _capture_emits(monkeypatch)

    def _refuse(db, *, user):
        raise PunchAlreadyOpenError("nope")

    monkeypatch.setattr(attendance_router.attendance_service, "punch_in", _refuse)

    with pytest.raises(HTTPException):
        attendance_router.punch_in(user=user, db=None)
    assert envelopes == []
```

- [x] **Step 2: Run it to verify it fails**

Run: `cd backend && python -m pytest tests/test_realtime_emit.py -q -k attendance`
Expected: FAIL — the emitter set is empty.

- [x] **Step 3: Write the shared emitter**

Create `backend/app/routers/_attendance_events.py`:

```python
"""The one call every punch-writing route makes after its write.

Layer: routers (shared helper), alongside `_errors.py` and `_stock_events.py`
-- which is the convention this repo already follows for emitting realtime
invalidations from the router rather than from a service.

It lives here rather than in either router because six routes across two
modules make the same call, and a second copy is how two surfaces end up
emitting two different event names.
"""

import logging

from app.domain import realtime as realtime_policy
from app.logging_config import current_request_id
from app.services import realtime as realtime_service

logger = logging.getLogger(__name__)


def emit_attendance_changed() -> None:
    """Invalidate the Admin roster and the comparison week after a punch
    write.

    Always `entity_id=None`: a punch changing is a membership change to
    *somebody's* on-shift state, not one card's field, so the recipient
    refetches rather than targeting a row -- the same reasoning
    `labor.session.changed` already uses.

    Best-effort by contract, like every other emission in this package: a
    dropped envelope costs one stale strip until the next 60-second poll and
    must never fail a durable write.
    """
    realtime_service.emit(
        realtime_policy.build_envelope(
            event_type=realtime_policy.EVENT_ATTENDANCE_CHANGED,
            entity_id=None,
            request_id=current_request_id(),
        )
    )
```

- [x] **Step 4: Call it from the three self-scoped writes**

In `backend/app/routers/attendance.py`, add `from app.routers._attendance_events import emit_attendance_changed` to the imports, extend the module docstring with one line, and in each of `punch_in`, `punch_out`, `self_close` capture the result and emit after it. `punch_in` becomes:

```python
@router.post("/punch-in", response_model=AttendancePunchResponse)
def punch_in(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Start a shift. 409 when one is already open (D4) -- the client reads
    the blocking punch back from `GET /attendance/me` and offers the
    self-close (D5) when it is stale."""
    try:
        punch = attendance_service.punch_in(db, user=user)
    except DomainError as exc:
        raise to_http(exc) from exc
    emit_attendance_changed()
    return punch
```

`punch_out` and `self_close` take the identical shape — bind the service result, emit, return. The emit is **after** the `try`, so a refusal emits nothing.

Docstring line to add, under the existing "Every route here is self-scoped" paragraph:

```
Every write here emits `attendance.changed` (audience Admin) so the Admin
roster does not wait out its 60-second poll. Best-effort, after the write.
```

- [x] **Step 5: Call it from the three admin writes**

In `backend/app/routers/hub.py`, add `from app.routers._attendance_events import emit_attendance_changed`, and give `add_hub_attendance_punch`, `edit_hub_attendance_punch` and `delete_hub_attendance_punch` the same bind-emit-return shape. `add_hub_attendance_punch` becomes:

```python
@router.post("/attendance/punches", response_model=AttendancePunchResponse)
def add_hub_attendance_punch(
    payload: PunchAddRequest,
    user: User = Depends(require_min_role(roles.ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """Add a punch nobody clocked. 400 on a bad window, 409 on an overlap."""
    try:
        punch = attendance_service.admin_add_punch(
            db, actor=user, user_id=payload.user_id,
            started_at=payload.started_at, ended_at=payload.ended_at,
            reason=payload.reason)
    except DomainError as exc:
        raise to_http(exc) from exc
    emit_attendance_changed()
    return punch
```

Also extend the comment block above the three writes (`hub.py:191-193`) with one sentence: each emits `attendance.changed` after its commit, so an Admin correcting a punch in one window sees the roster and the grid move in another.

- [x] **Step 6: Run the emit and attendance router suites**

Run: `cd backend && python -m pytest tests/test_realtime_emit.py tests/test_attendance_router.py tests/test_attendance_admin_router.py -q`
Expected: PASS. If Step 1's new tests need imports (`pytest`, `HTTPException`, `PunchAlreadyOpenError`) that the file lacks, add them.

- [x] **Step 7: Commit**

```bash
git add backend/app/routers/_attendance_events.py backend/app/routers/attendance.py backend/app/routers/hub.py backend/tests/test_realtime_emit.py
git commit -m "feat(attendance): emit attendance.changed from the six punch writes"
```

---

## Task 5: the api.js wrapper and the test fixtures

**Files:**
- Modify: `backend/static/api.js:653` (beside `apiGetHubAttendanceWeek`)
- Modify: `tests/frontend/helpers/endpointTable.js`, `tests/frontend/helpers/factories.js`, `tests/frontend/helpers/hub.js`
- Test: `tests/frontend/unit/api.endpoints.test.js` covers it through the table — no new test file.

**Interfaces:**
- Produces: `apiGetHubAttendanceLive()` — no arguments, `liveGet("/hub/attendance/live")`. `attendanceLive(overrides)` factory. `openHub({ attendanceLive })` option.

- [x] **Step 1: Add the table row (the failing test)**

In `tests/frontend/helpers/endpointTable.js`, beside the other attendance entries:

```js
  { fn: "apiGetHubAttendanceLive", args: [], url: "/hub/attendance/live", cache: "no-store" },
```

- [x] **Step 2: Run it to verify it fails**

Run: `npx vitest run tests/frontend/unit/api.endpoints.test.js`
Expected: FAIL — `apiGetHubAttendanceLive is not a function`.

- [x] **Step 3: Add the wrapper**

In `backend/static/api.js`, immediately after `apiGetHubAttendanceWeek`:

```js
// The roster strip. No parameters: "now" is the only question it answers,
// and the server is the one that knows what now is. Polled on the hub's
// existing 60-second safety timer and on `attendance.changed`.
export async function apiGetHubAttendanceLive() {
  return liveGet("/hub/attendance/live");
}
```

- [x] **Step 4: Add the factory**

In `tests/frontend/helpers/factories.js`, beside `attendanceWeek`:

```js
// The roster payload. Three cards, one of each colour, already in the order
// the server sends them -- red, yellow, green -- plus one absent person, so
// a test can assert the strip renders what it is given without re-sorting.
export function attendanceLive(overrides = {}) {
  return {
    server_now: "2026-09-16T15:00:00Z",
    idle_red_minutes: 10,
    on_shift: [
      {
        user: { id: "user-1", first_name: "Ann", last_name: "Lee", role: "technician" },
        state: "red",
        punch_started_at: "2026-09-16T13:00:00Z",
        idle_since: "2026-09-16T14:15:00Z",
        idle_minutes: 45,
        charging_since: null,
        work_order_number: null,
      },
      {
        user: { id: "user-2", first_name: "Bo", last_name: "Ruiz", role: "technician" },
        state: "yellow",
        punch_started_at: "2026-09-16T14:50:00Z",
        idle_since: "2026-09-16T14:57:00Z",
        idle_minutes: 3,
        charging_since: null,
        work_order_number: null,
      },
      {
        user: { id: "user-3", first_name: "Cy", last_name: "Nolan", role: "supervisor" },
        state: "green",
        punch_started_at: "2026-09-16T12:00:00Z",
        idle_since: null,
        idle_minutes: 0,
        charging_since: "2026-09-16T14:30:00Z",
        work_order_number: "WO-1042",
      },
    ],
    absent: [
      {
        user: { id: "user-4", first_name: "Dee", last_name: "Park", role: "technician" },
        state: "gray",
        punch_started_at: null,
        idle_since: null,
        idle_minutes: 0,
        charging_since: null,
        work_order_number: null,
      },
    ],
    on_shift_count: 3,
    charging_count: 1,
    idle_count: 2,
    ...overrides,
  };
}
```

- [x] **Step 5: Serve it from the hub fixture**

In `tests/frontend/helpers/hub.js`: add `attendanceLive` to the factory import, add `attendanceLive: live = null` to `mountHub`'s options, and add the handler beside the week's — **above** the bare `/hub` handler, as the comment there requires:

```js
    http.get("/hub/attendance/live", () => answer(live ?? attendanceLive())),
```

- [x] **Step 6: Run the endpoint suite**

Run: `npx vitest run tests/frontend/unit/api.endpoints.test.js tests/frontend/views/hubTimesheetsTab.test.js`
Expected: PASS — the fixture addition must not change any existing count.

- [x] **Step 7: Commit**

```bash
git add backend/static/api.js tests/frontend/helpers/
git commit -m "feat(attendance): api.js wrapper and fixtures for the live roster"
```

---

## Task 6: `views/hubAttendanceRoster.js`

**Files:**
- Create: `backend/static/views/hubAttendanceRoster.js`
- Modify: `backend/static/styles.css` (append a `.hub-roster-*` block)
- Test: `tests/frontend/views/hubAttendanceRoster.test.js` (create)

**Interfaces:**
- Consumes: the `attendanceLive()` shape from Task 5.
- Produces: `mountHubAttendanceRoster(container, payload)`, `startHubRosterTicking()`, `stopHubRosterTicking()`, `destroyHubAttendanceRoster()`. Tasks 7 and 9 import all four.

- [x] **Step 1: Write the failing view test**

Create `tests/frontend/views/hubAttendanceRoster.test.js`. This view is mounted directly (no hub shell), so it uses `mountView` on a bare container rather than `openHub` — model the harness on `tests/frontend/views/hubAttendancePunchEditor.test.js`, which does the same for its payload-in view. Read that file first and match its setup exactly.

```js
// The roster strip: what each colour says in words, what the footer hides,
// and that a card recolours on the tick without the list reordering.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { attendanceLive } from "../helpers/factories.js";

let view;
let host;

beforeEach(async () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-09-16T15:00:00Z"));
  host = document.createElement("div");
  document.body.appendChild(host);
  view = await import("../../../backend/static/views/hubAttendanceRoster.js");
});

afterEach(() => {
  view.destroyHubAttendanceRoster();
  expect(vi.getTimerCount()).toBe(0);
  host.remove();
  vi.useRealTimers();
});

const cards = () => [...host.querySelectorAll(".hub-roster-card")];

describe("the roster strip", () => {
  it("renders the server's order and never re-sorts it", () => {
    view.mountHubAttendanceRoster(host, attendanceLive());
    expect(cards().map((c) => c.dataset.state)).toEqual(["red", "yellow", "green"]);
  });

  it("says every state in words, not colour alone", () => {
    view.mountHubAttendanceRoster(host, attendanceLive());
    const text = cards().map((c) => c.textContent);
    expect(text[0]).toMatch(/idle/i);
    expect(text[2]).toMatch(/charging/i);
    expect(text[2]).toContain("WO-1042");
  });

  it("prints the three counts", () => {
    view.mountHubAttendanceRoster(host, attendanceLive());
    const counts = host.querySelector(".hub-roster-counts").textContent;
    expect(counts).toContain("3 on shift");
    expect(counts).toContain("1 charging");
    expect(counts).toContain("2 idle");
  });

  it("hides absent people behind an expandable footer", async () => {
    view.mountHubAttendanceRoster(host, attendanceLive());
    const footer = host.querySelector(".hub-roster-absent");
    expect(footer.tagName).toBe("DETAILS");
    expect(footer.open).toBe(false);
    expect(footer.querySelector("summary").textContent).toContain("1 not clocked in");
    expect(footer.textContent).toContain("Dee Park");
  });

  it("omits the footer entirely when everybody is clocked in", () => {
    view.mountHubAttendanceRoster(host, attendanceLive({ absent: [] }));
    expect(host.querySelector(".hub-roster-absent")).toBeNull();
  });

  it("ticks the idle figure without refetching", () => {
    view.mountHubAttendanceRoster(host, attendanceLive());
    const before = cards()[1].querySelector(".hub-roster-detail").textContent;
    vi.advanceTimersByTime(120000);
    const after = cards()[1].querySelector(".hub-roster-detail").textContent;
    expect(after).not.toBe(before);
    expect(cards()[1].dataset.state).toBe("yellow");
  });

  it("recolours a card that crosses the red threshold, in place", () => {
    view.mountHubAttendanceRoster(host, attendanceLive());
    expect(cards()[1].dataset.state).toBe("yellow");
    // Bo is 3 minutes idle at server_now; 8 more crosses 10.
    vi.advanceTimersByTime(8 * 60000);
    expect(cards()[1].dataset.state).toBe("red");
    // In place: the list order is the server's until the next fetch.
    expect(cards().map((c) => c.dataset.user)).toEqual(["user-1", "user-2", "user-3"]);
  });

  it("stops and restarts on the tab's visibility, leaving no timer behind", () => {
    view.mountHubAttendanceRoster(host, attendanceLive());
    view.stopHubRosterTicking();
    expect(vi.getTimerCount()).toBe(0);
    view.startHubRosterTicking();
    expect(vi.getTimerCount()).toBe(1);
  });

  it("escapes a name and a work-order number", () => {
    const payload = attendanceLive();
    payload.on_shift[2].work_order_number = "<img src=x>";
    payload.on_shift[0].user.last_name = "<b>Lee</b>";
    view.mountHubAttendanceRoster(host, payload);
    expect(host.querySelector("img")).toBeNull();
    expect(host.querySelector("b")).toBeNull();
  });
});
```

- [x] **Step 2: Run it to verify it fails**

Run: `npx vitest run tests/frontend/views/hubAttendanceRoster.test.js`
Expected: FAIL — cannot resolve `hubAttendanceRoster.js`.

- [x] **Step 3: Write the view**

Create `backend/static/views/hubAttendanceRoster.js`:

```js
// View: the live roster strip above Charged vs clocked.
//
// Layer: views. No fetch and no state but the tick: the payload arrives from
// hubTimesheetsTab.js, and everything on screen is derived from it.
//
// **Colour is never the only signal** (design-system.md). Every card prints
// what its rail means in words -- "idle 12m", "charging WO-1042" -- so the
// strip is readable with the hues removed.
//
// Ticking is the hubClock.js pattern: elapsed recomputed each second from an
// instant plus the server skew, never a counter incremented in place, so a
// backgrounded tab that misses a hundred ticks still snaps to the truth on
// its first tick back. A card that crosses `idle_red_minutes` is recoloured
// **in place**; the list order is the server's and changes only on a fetch,
// because a strip that reshuffles under a reading eye is worse than one row
// sitting out of position for a minute.
//
// The absent footer is `<details>`, not a button that toggles a panel: a
// button inside the strip's header row would be a button inside a button.

import { escapeHtml } from "../format.js";

const DEFAULT_IDLE_RED_MINUTES = 10;

let container = null;
let payload = null;
let skewMs = 0;
let tickHandle = null;

function serverNow() {
  return Date.now() + skewMs;
}

function minutesSince(iso) {
  if (!iso) return 0;
  return Math.max(0, Math.floor((serverNow() - new Date(iso).getTime()) / 60000));
}

// `45m`, `2h 05m`: the figure sits inside a sentence, so it reads as a
// duration rather than as the clock times the grids below print.
function formatElapsed(minutes) {
  if (minutes < 60) return `${minutes}m`;
  return `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m`;
}

function timeLabel(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function userName(user) {
  return `${user?.first_name || ""} ${user?.last_name || ""}`.trim() || "Unknown";
}

// The card's own colour, recomputed from the anchor so it can cross the
// threshold between polls. A charging card never changes: only a fetch can
// tell us a clock stopped.
function stateOf(entry) {
  if (entry.charging_since) return "green";
  if (!entry.idle_since) return entry.state;
  const threshold = payload?.idle_red_minutes ?? DEFAULT_IDLE_RED_MINUTES;
  return minutesSince(entry.idle_since) >= threshold ? "red" : "yellow";
}

// Plain text, set with textContent on every tick -- which is also why it is
// not built as HTML.
function detailText(entry, state) {
  if (state === "green") {
    const job = entry.work_order_number || "a job";
    return `charging ${job} · ${formatElapsed(minutesSince(entry.charging_since))}`;
  }
  return `idle ${formatElapsed(minutesSince(entry.idle_since))}`;
}

function cardHtml(entry) {
  const state = stateOf(entry);
  const name = userName(entry.user);
  const since = entry.punch_started_at
    ? `on shift since ${timeLabel(entry.punch_started_at)}`
    : "";
  return `<li class="hub-roster-card hub-roster-${escapeHtml(state)}"
    data-user="${escapeHtml(String(entry.user?.id ?? ""))}" data-state="${escapeHtml(state)}">
    <span class="hub-roster-name">${escapeHtml(name)}</span>
    <span class="hub-roster-detail">${escapeHtml(detailText(entry, state))}</span>
    <span class="hub-roster-since">${escapeHtml(since)}</span>
  </li>`;
}

function absentHtml(entries) {
  if (!entries.length) return "";
  const names = entries
    .map((entry) => `<li class="hub-roster-absent-name">${escapeHtml(userName(entry.user))}</li>`)
    .join("");
  return `<details class="hub-roster-absent">
    <summary>${entries.length} not clocked in</summary>
    <ul class="hub-roster-absent-list">${names}</ul>
  </details>`;
}

function render() {
  if (!container || !payload) return;
  const onShift = payload.on_shift || [];
  const counts = `${payload.on_shift_count} on shift · ${payload.charging_count} charging · ${payload.idle_count} idle`;
  const strip = onShift.length
    ? `<ul class="hub-roster-strip">${onShift.map(cardHtml).join("")}</ul>`
    : `<p class="hint hub-roster-empty">Nobody is clocked in right now.</p>`;
  container.innerHTML = `<section class="hub-roster" aria-labelledby="hub-roster-heading">
    <h4 id="hub-roster-heading" class="sr-only">On shift now</h4>
    <p class="hub-roster-counts" aria-live="polite">${escapeHtml(counts)}</p>
    ${strip}
    ${absentHtml(payload.absent || [])}
  </section>`;
}

// One pass per second. Each card's figure is rewritten as text; a card whose
// colour has changed forces a single re-render and the pass stops there,
// because the nodes it was walking are about to be replaced.
function tick() {
  if (!container || !payload) return;
  for (const entry of payload.on_shift || []) {
    const node = container.querySelector(
      `.hub-roster-card[data-user="${CSS.escape(String(entry.user?.id ?? ""))}"]`,
    );
    if (!node) continue;
    const state = stateOf(entry);
    if (node.dataset.state !== state) {
      render();
      return;
    }
    const detail = node.querySelector(".hub-roster-detail");
    if (detail) detail.textContent = detailText(entry, state);
  }
}

function stopTicking() {
  if (tickHandle !== null) {
    clearInterval(tickHandle);
    tickHandle = null;
  }
}

function startTicking() {
  stopTicking();
  tickHandle = setInterval(tick, 1000);
}

// Payload in, strip out. Re-mounting with a fresh payload is how a poll or an
// `attendance.changed` envelope lands -- and is also what re-sorts the list.
export function mountHubAttendanceRoster(mountEl, newPayload) {
  container = mountEl;
  payload = newPayload;
  skewMs = new Date(newPayload.server_now).getTime() - Date.now();
  render();
  startTicking();
}

// The tab-hide half of the safety net, called from userHub.js's existing
// `visibilitychange` listener beside `stopHubClockTicking` -- this view owns
// no timer of its own beyond the one that listener governs.
export function stopHubRosterTicking() {
  stopTicking();
}

export function startHubRosterTicking() {
  if (container) startTicking();
}

// A different person signed in, or the tab went away. Everything goes,
// including the interval -- the frontend suite asserts no timer survives.
export function destroyHubAttendanceRoster() {
  stopTicking();
  container = null;
  payload = null;
  skewMs = 0;
}
```

- [x] **Step 4: Add the CSS**

Append to `backend/static/styles.css`, after the `.hub-compare-*` block. Use the existing status-hue custom properties — read the `.hub-compare-flag-outside` rule and `docs/design-system.md` first and reuse the tokens already defined there rather than introducing new hex values.

```css
/* The live roster strip (attendance P4b). Status hue lives in a 4px left
   rail only -- the card's own text says what the colour means, so the hues
   stay inside the badge-only rule design-system.md sets. */
.hub-roster { margin-bottom: 1rem; }
.hub-roster-counts { font-weight: 600; margin: 0 0 0.5rem; }
.hub-roster-strip {
  display: flex; flex-wrap: wrap; gap: 0.5rem; list-style: none; margin: 0; padding: 0;
}
.hub-roster-card {
  display: flex; flex-direction: column; gap: 0.15rem;
  min-width: 11rem; padding: 0.5rem 0.65rem;
  border: 1px solid var(--panel-border); border-left-width: 4px; border-radius: 6px;
  background: var(--panel-bg);
}
.hub-roster-name { font-weight: 600; }
.hub-roster-detail { font-size: 0.85rem; }
.hub-roster-since { font-size: 0.78rem; opacity: 0.75; }
.hub-roster-green { border-left-color: var(--status-ok); }
.hub-roster-yellow { border-left-color: var(--status-warn); }
.hub-roster-red { border-left-color: var(--status-danger); }
.hub-roster-gray { border-left-color: var(--panel-border); }
.hub-roster-absent { margin-top: 0.6rem; font-size: 0.85rem; }
.hub-roster-absent-list { margin: 0.4rem 0 0; padding-left: 1.2rem; }
```

- [x] **Step 5: Run the view test**

Run: `npx vitest run tests/frontend/views/hubAttendanceRoster.test.js`
Expected: PASS, all ten.

- [x] **Step 6: Commit**

```bash
git add backend/static/views/hubAttendanceRoster.js backend/static/styles.css tests/frontend/views/hubAttendanceRoster.test.js
git commit -m "feat(attendance): the live roster strip, ticking from the idle anchor"
```

---

## Task 7: wiring the roster into the comparison sub-tab

**Files:**
- Modify: `backend/static/views/hubAttendanceCompare.js` (signature + one mount node), `backend/static/views/hubTimesheetsTab.js` (live cache, lazy load, subscription, reset), `backend/static/views/userHub.js` (the 60 s call + the tick lifecycle)
- Test: `tests/frontend/views/hubTimesheetsTab.test.js` (append), `tests/frontend/views/hubAttendanceCompare.test.js` (append)

**Interfaces:**
- Consumes: `apiGetHubAttendanceLive` (Task 5); `mountHubAttendanceRoster` / `destroyHubAttendanceRoster` / `startHubRosterTicking` / `stopHubRosterTicking` (Task 6); `EVENT_ATTENDANCE_CHANGED`'s wire name `"attendance.changed"` (Task 3).
- Produces: `hubTimesheetsTab.refreshTimesheetsLive(panelEl)` — a background refetch that is a no-op unless the comparison feature is showing. `userHub.js` calls it.

- [x] **Step 1: Write the failing tests**

Append to `tests/frontend/views/hubTimesheetsTab.test.js`, inside the `describe("Admin", ...)` block:

```js
  it("fetches the roster only when Charged vs clocked is opened", async () => {
    await openTimesheets({ role: "admin" });
    await vi.waitFor(() => expect(panel().querySelector(".hub-hours-table")).not.toBeNull());
    expect(queries("/hub/attendance/live")).toHaveLength(0);
    await user().click(panel().querySelector('.sub-nav-btn[data-feature="compare"]'));
    await vi.waitFor(() => expect(panel().querySelector(".hub-roster-strip")).not.toBeNull());
    expect(queries("/hub/attendance/live")).toHaveLength(1);
  });

  it("renders the comparison grid even when the roster fetch fails", async () => {
    await openTimesheets({
      role: "admin",
      handlers: [http.get("/hub/attendance/live", () => HttpResponse.json({ detail: "" }, { status: 500 }))],
    });
    await user().click(panel().querySelector('.sub-nav-btn[data-feature="compare"]'));
    await vi.waitFor(() => expect(panel().querySelector(".hub-compare-table")).not.toBeNull());
    expect(panel().querySelector(".hub-roster-strip")).toBeNull();
  });

  it("refetches the roster on attendance.changed while the sub-tab is open", async () => {
    const { emit } = await connectHub();
    await openTimesheets({ role: "admin" });
    await user().click(panel().querySelector('.sub-nav-btn[data-feature="compare"]'));
    await vi.waitFor(() => expect(queries("/hub/attendance/live")).toHaveLength(1));
    emit("attendance.changed");
    await vi.waitFor(() => expect(queries("/hub/attendance/live")).toHaveLength(2));
  });

  it("ignores attendance.changed while Hours is the open sub-tab", async () => {
    const { emit } = await connectHub();
    await openTimesheets({ role: "admin" });
    await vi.waitFor(() => expect(panel().querySelector(".hub-hours-table")).not.toBeNull());
    emit("attendance.changed");
    await vi.advanceTimersByTimeAsync(0);
    expect(queries("/hub/attendance/live")).toHaveLength(0);
  });

  it("refreshes the roster on the hub's 60-second timer and starts no timer of its own", async () => {
    await openTimesheets({ role: "admin" });
    await user().click(panel().querySelector('.sub-nav-btn[data-feature="compare"]'));
    await vi.waitFor(() => expect(queries("/hub/attendance/live")).toHaveLength(1));
    const before = vi.getTimerCount();
    await vi.advanceTimersByTimeAsync(60000);
    await vi.waitFor(() => expect(queries("/hub/attendance/live")).toHaveLength(2));
    expect(vi.getTimerCount()).toBe(before);
  });
```

`connectHub` and `http` / `HttpResponse` are already imported by this file if the crew arms use them; add whatever is missing to its import block.

- [x] **Step 2: Run them to verify they fail**

Run: `npx vitest run tests/frontend/views/hubTimesheetsTab.test.js`
Expected: FAIL — no `/hub/attendance/live` request is ever made.

- [x] **Step 3: Give the comparison view a roster mount**

In `backend/static/views/hubAttendanceCompare.js`: import `mountHubAttendanceRoster`, widen the signature, and put the mount node at the top of the section.

```js
import { mountHubAttendanceRoster } from "./hubAttendanceRoster.js";
```

```js
export function mountHubAttendanceCompare(container, payload, { onWeekChange, live = null } = {}) {
```

Inside `render()`, insert the mount immediately after the `<h3>`:

```js
      <div class="hub-roster-mount"></div>
```

and after the `container.innerHTML = ...` assignment, before the three `addEventListener` calls:

```js
    // The strip is a separate payload on a separate cadence. Absent -- a
    // failed or in-flight roster fetch -- the grid below still renders: the
    // comparison is the sub-tab's job and the roster is its headline, not
    // its precondition.
    if (live) {
      mountHubAttendanceRoster(container.querySelector(".hub-roster-mount"), live);
    }
```

Extend the module header with two sentences naming the strip and that cadence.

- [x] **Step 4: Hold the live payload in the tab**

In `backend/static/views/hubTimesheetsTab.js`:

Imports — add `apiGetHubAttendanceLive` to the api.js import, `subscribe` from `../realtime.js`, and `destroyHubAttendanceRoster` from `./hubAttendanceRoster.js`.

State, beside the week cache:

```js
// The roster's own cache, on its own cadence: the week is paged by hand and
// the strip is polled. Sharing one counter would let a week change discard
// a roster response that is still current.
let livePayload = null;
let liveRequestId = 0;
// The panel this module is mounted into, held so the module-level
// subscription below has something to refresh. Set on every render.
let hostPanel = null;
```

Loader and refresher:

```js
// A roster failure is deliberately silent: it leaves `livePayload` null, the
// comparison renders without its strip, and the next poll tries again. The
// alternative -- replacing a working grid with a retry box because a
// decorative strip 500'd -- is worse.
async function loadLive(panelEl) {
  const requestId = ++liveRequestId;
  try {
    const payload = await apiGetHubAttendanceLive();
    if (requestId !== liveRequestId) return;
    livePayload = payload;
    if (panelEl.dataset.activeFeature === "compare") renderCompare(panelEl);
  } catch (_err) {
    if (requestId !== liveRequestId) return;
  }
}

// Called by userHub.js on the hub's existing 60-second safety timer and on
// an `attendance.changed` envelope. A no-op unless the comparison is the
// open sub-tab: nothing else on screen reads either payload.
export function refreshTimesheetsLive(panelEl = hostPanel) {
  if (!panelEl || panelEl.dataset.activeFeature !== "compare") return;
  void loadLive(panelEl);
  void loadWeek(panelEl);
}
```

`renderCompare` passes it through:

```js
  mountHubAttendanceCompare(mount, weekPayload, {
    onWeekChange: changeWeek(panelEl),
    live: livePayload,
  });
```

`showFeature`'s compare arm also kicks the roster:

```js
  if (feature === "hours" || feature === "compare") {
    if (weekPayload) renderWeek(panelEl);
    else void loadWeek(panelEl);
    if (feature === "compare" && !livePayload) void loadLive(panelEl);
  }
```

`renderTimesheetsTab` records the panel: `hostPanel = panelEl;` right after the `viewerRole = role;` line.

`resetTimesheetsTab` clears all of it:

```js
  livePayload = null;
  liveRequestId += 1;
  hostPanel = null;
  destroyHubAttendanceRoster();
```

And the subscription, at module scope beside the exports — the pattern `userRequests.js` and `workOrderRequests.js` already use, which is what lets the sub-tab own its own event as spec §6 asks:

```js
// Spec §6: this sub-tab owns the `attendance.changed` subscription. Every
// punch write emits it (audience Admin), so a technician punching out moves
// the strip without waiting out the 60-second poll. Background by nature --
// a socket signal, not a user action -- and inert unless the comparison is
// the open sub-tab.
subscribe("attendance.changed", ({ activePage }) => {
  if (activePage !== "user-hub") return;
  refreshTimesheetsLive();
});
```

- [x] **Step 5: Hang the poll and the tick lifecycle off userHub.js**

In `backend/static/views/userHub.js`:

```js
import { startHubRosterTicking, stopHubRosterTicking } from "./hubAttendanceRoster.js";
import { refreshTimesheetsLive, renderTimesheetsTab, resetTimesheetsTab } from "./hubTimesheetsTab.js";
```

Inside `startCrewSafetyRefresh`'s interval callback, after the graphs line:

```js
    // The Timesheets tab's roster rides the hub's existing safety timer
    // rather than starting a second one; the call is inert unless Charged
    // vs clocked is the open sub-tab.
    if (activeTab === "timesheets") refreshTimesheetsLive(tabPanels.timesheets);
```

In the `visibilitychange` listener, beside the clock's two calls:

```js
  if (document.hidden) {
    stopHubClockTicking();
    stopHubRosterTicking();
    stopCrewSafetyRefresh();
    return;
  }
  if (!document.getElementById("user-hub-page").classList.contains("active")) return;
  startHubClockTicking();
  startHubRosterTicking();
  if (latestPayload) startCrewSafetyRefresh();
```

- [x] **Step 6: Add the comparison-view arm**

Append to `tests/frontend/views/hubAttendanceCompare.test.js`:

```js
  it("mounts the roster strip above the grid when given a live payload", () => {
    mount(attendanceWeek(), { live: attendanceLive() });
    const section = container.querySelector(".hub-compare");
    expect(section.querySelector(".hub-roster-strip")).not.toBeNull();
    // Above: the strip is the headline, the grid is the record.
    expect(section.querySelector(".hub-roster").compareDocumentPosition(
      section.querySelector(".hub-compare-table-wrap"),
    ) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("renders the grid with no strip when there is no live payload", () => {
    mount(attendanceWeek());
    expect(container.querySelector(".hub-compare-table")).not.toBeNull();
    expect(container.querySelector(".hub-roster-strip")).toBeNull();
  });
```

Match the existing file's `mount(...)` helper name and its cleanup — read it first; if its `afterEach` asserts zero timers, add `destroyHubAttendanceRoster()` to that teardown.

- [x] **Step 7: Run the frontend hub suites**

Run: `npx vitest run tests/frontend/views/hubTimesheetsTab.test.js tests/frontend/views/hubAttendanceCompare.test.js tests/frontend/views/hubAttendanceRoster.test.js tests/frontend/views/userHub.test.js`
Expected: PASS, and no suite leaves a timer behind.

- [x] **Step 8: Commit**

```bash
git add backend/static/views/ tests/frontend/views/
git commit -m "feat(attendance): the roster above Charged vs clocked, polled and subscribed"
```

---

## Task 8: the retirement, backend

**Files:**
- Modify: `backend/app/routers/hub.py` — delete `_default_range`, `_resolve_range`, `_filename_slug`, `_timesheet_filename`, `get_hub_timesheets`, `export_hub_timesheets`, the `HubTimesheetResponse` import, and the docstring's H3 line and its sweep paragraph
- Modify: `backend/app/services/hub.py` — delete `MAX_TIMESHEET_RANGE_DAYS`, `TimesheetDay`, `TimesheetRow`, `TimesheetDayTotal`, `TimesheetRange`, `HubTimesheetPayload`, `timesheets_hub`, `timesheet_csv`, and the two error imports
- Modify: `backend/app/schemas/hub.py:404-450` — delete the five `HubTimesheet*` models
- Modify: `backend/app/domain/errors.py:356-370`, `backend/app/routers/_errors.py:51-52,110-111`
- Modify: `backend/tests/test_hub_service.py`, `backend/tests/test_hub_router.py` — delete the timesheet arms

- [x] **Step 1: Confirm the blast radius before deleting anything**

```bash
cd backend && python -m pytest -q 2>&1 | tail -3
cd .. && grep -rn "timesheets_hub\|timesheet_csv\|HubTimesheet\|MAX_TIMESHEET_RANGE_DAYS\|TimesheetRange" --include="*.py" backend/ | grep -v __pycache__
```

Expected: a green baseline, and a reference list matching the four modules and two test files above. **Anything outside that list stops this task** — spec §7 asserts the set and P4a re-verified it; a surprise means the assertion has gone stale and must be re-derived before a line is removed.

Record the baseline test count; Step 6 compares against it.

- [x] **Step 2: Delete the two routes and their four helpers**

In `backend/app/routers/hub.py`, remove `_default_range`, `_resolve_range`, `_filename_slug`, `_timesheet_filename`, `get_hub_timesheets` and `export_hub_timesheets` (the contiguous block from `def _default_range` through the end of `export_hub_timesheets`), drop `HubTimesheetResponse` from the `app.schemas.hub` import, and drop `date` from the `datetime` import only if nothing else in the file still uses it — `get_hub_attendance_week` does, so it stays.

In the module docstring: delete the `- GET /hub/timesheets supervisor+` line, and rewrite the sweep paragraph's last two sentences, which now name a route that does not exist:

```
The personal and crew reads are not side-effect-free. They sweep over-cap
sessions before reading and therefore commit when they find one -- `GET /hub`
the caller's own, `GET /hub/crew` each crew member's individually (spec §3.5
assigns the global sweep to `GET /hub/admin` only and is silent on
`/hub/crew`; scoping the crew sweep to exactly the people it reads follows
the same reasoning `GET /hub` already applies to itself). This follows
existing precedent rather than inventing it -- `get_work_order` already both
sweeps sessions and self-heals orphaned material lines on a read -- and the
sweep is idempotent under a row lock, so two tabs loading at once cannot
double-close a session. Every `/hub/attendance/*` read is the exception and
writes nothing at all.
```

- [x] **Step 3: Delete the service and schema layers**

In `backend/app/services/hub.py`, remove the contiguous block from `MAX_TIMESHEET_RANGE_DAYS = 92` through the end of `timesheet_csv`, and remove `from app.domain.errors import TimesheetRangeInvalidError, TimesheetRangeTooLargeError` (line 30). Leave `labor_summary.crew_range_summaries` and every other import alone — `attendance_compare` is its caller now.

In `backend/app/schemas/hub.py`, delete `HubTimesheetRange`, `HubTimesheetDay`, `HubTimesheetRow`, `HubTimesheetDayTotal` and `HubTimesheetResponse`.

In `backend/app/domain/errors.py`, delete `TimesheetRangeInvalidError` and `TimesheetRangeTooLargeError`. In `backend/app/routers/_errors.py`, delete both names from the import block and both rows from the status map.

- [x] **Step 4: Delete the tests that covered them**

In `backend/tests/test_hub_service.py`: delete the twelve `test_timesheets_hub_*` / `test_timesheet_csv_*` functions (lines ~1201–1440) and the `TimesheetRangeInvalidError, TimesheetRangeTooLargeError` import.

In `backend/tests/test_hub_router.py`: delete the `HubTimesheetPayload` fixture (line ~29) and every arm that monkeypatches `"timesheets_hub"` or requests `/hub/timesheets`.

- [x] **Step 5: Add the tripwire that keeps them gone**

Append to `backend/tests/test_hub_router.py`:

```python
def test_the_timesheet_routes_are_gone():
    """D6: `GET /hub/timesheets` retired in P4b, subsumed by the Admin
    comparison sub-tab, at the accepted cost that a Supervisor loses the tab.
    Re-adding the path would silently restore a second, sweeping, answer to
    "how many hours" beside the pay record."""
    from app.main import app as fastapi_app

    paths = {route.path for route in fastapi_app.routes if isinstance(route, APIRoute)}
    assert "/hub/timesheets" not in paths
    assert "/hub/timesheets/export" not in paths
```

Add the `APIRoute` import if the file lacks it.

- [x] **Step 6: Run the whole backend suite**

Run: `cd backend && python -m pytest -q`
Expected: PASS, with the collected count down by exactly the arms removed in Step 4 plus one for the tripwire. A failure anywhere outside the files touched here means Step 1's reference list was incomplete — fix the reference, not the failing test.

Note: `test_cascade_deletes_with_user` fails on a dev database carrying real cloud-session rows. That is environmental and pre-existing; if it is the only red, say so rather than chasing it.

- [x] **Step 7: Commit**

```bash
git add backend/
git commit -m "refactor(attendance): retire GET /hub/timesheets and its range errors (D6)"
```

---

## Task 9: the retirement, frontend — and Timesheets moves to Admin+

**Files:**
- Delete: `backend/static/views/hubTimesheets.js`, `tests/frontend/views/hubTimesheets.test.js`
- Modify: `backend/static/api.js` (both wrappers), `backend/static/tips.js` (`hub.timesheets`), `backend/static/views/hubTimesheetsTab.js` (the `crew` half), `backend/static/views/userHub.js` (the tab's floor)
- Modify: `tests/frontend/helpers/endpointTable.js`, `helpers/factories.js`, `helpers/hub.js`, `unit/api.shapes.test.js`, `views/hubTimesheetsTab.test.js`, `views/userHub.test.js`

- [x] **Step 1: Write the failing floor test**

In `tests/frontend/views/userHub.test.js`, replace the arm that asserts a Supervisor sees the Timesheets tab with:

```js
  it("shows the Timesheets tab to an Admin and hides it below", async () => {
    // D6: the tab is the pay record now, so it moved up with the routes
    // behind it. A Supervisor keeps the Dashboard crew board, which shows
    // live crew status at their own scope.
    await openHub({ role: "supervisor" });
    expect(el.tab("timesheets").hidden).toBe(true);
    restoreHub();
    await openHub({ role: "admin" });
    expect(el.tab("timesheets").hidden).toBe(false);
  });
```

Match the file's own mount/teardown idiom — if it cannot mount twice in one test, split it into two.

In `tests/frontend/views/hubTimesheetsTab.test.js`, delete the whole `describe("below Admin", ...)` block and every arm that queries `/hub/timesheets`, and change the sub-nav count assertion from three buttons to two.

- [x] **Step 2: Run them to verify they fail**

Run: `npx vitest run tests/frontend/views/userHub.test.js tests/frontend/views/hubTimesheetsTab.test.js`
Expected: FAIL — the tab is still visible to a supervisor and the sub-nav still has three buttons.

- [x] **Step 3: Delete the view, the wrappers and the tip**

```bash
git rm backend/static/views/hubTimesheets.js tests/frontend/views/hubTimesheets.test.js
```

In `backend/static/api.js`, delete `apiGetHubTimesheets` and `apiExportHubTimesheets`. In `backend/static/tips.js`, delete the `"hub.timesheets"` entry — its only `tipHtml` caller went with the view, and `tips.test.js` audits used keys, not unused ones.

- [x] **Step 4: Cut the `crew` half out of the tab**

In `backend/static/views/hubTimesheetsTab.js`, delete: the `apiGetHubTimesheets` and `mountHubTimesheets` imports, `crewPayload` / `crewRange` / `crewRequestId`, `skeletonGrid`'s `cardCount` default if nothing else uses it, `canSeeHours`, `renderCrew`, `showCrewError`, `loadCrew`, and the crew arms of `buildShell`, `showFeature`, `renderTimesheetsTab` and `resetTimesheetsTab`.

`buildShell` loses its role branch entirely — the tab is Admin-only now, so there is exactly one shell:

```js
function buildShell(panelEl, role) {
  panelEl.innerHTML = `<nav class="sub-nav hub-sub-nav" aria-label="Timesheet views">
      <button type="button" class="sub-nav-btn active" data-feature="hours">Hours</button>
      <button type="button" class="sub-nav-btn" data-feature="compare">Charged vs clocked</button>
    </nav>
    <section class="feature-panel" data-feature="hours"></section>
    <section class="feature-panel" data-feature="compare" hidden></section>`;
  panelEl.dataset.timesheetsRole = role;
  delete panelEl.dataset.activeFeature;
  initSubNav(panelEl, {
    onShow: (feature) => showFeature(panelEl, feature),
    fireInitialOnShow: false,
  });
}
```

`showFeature` collapses to the two Admin features:

```js
function showFeature(panelEl, feature) {
  if (weekPayload) renderWeek(panelEl);
  else void loadWeek(panelEl);
  if (feature === "compare" && !livePayload) void loadLive(panelEl);
}
```

`renderTimesheetsTab`'s last line becomes `showFeature(panelEl, panelEl.dataset.activeFeature || "hours");`, and `roleAtLeast(viewerRole, "admin")` inside `renderHours` stays — the tab's floor and the write affordances' floor are the same rank now, but the view still renders only what it was handed a callback for, which is the property worth keeping.

Rewrite the module header: two sub-features, both Admin+, both reading one `GET /hub/attendance/week`; the roster is the comparison's own payload on its own cadence; `GET /hub/timesheets` is gone.

- [x] **Step 5: Move the tab to Admin+ in userHub.js**

In `backend/static/views/userHub.js`, add a floor of its own beside the other three in `loadUserHub`:

```js
  const canViewSupervisorTabs = roleAtLeast(payload.user.role, "supervisor");
  // D6: Timesheets is the pay record, so it sits with the report rather than
  // with the crew board. `canViewSupervisorTabs` still governs the crew
  // fetch, which a Supervisor keeps.
  const canViewTimesheets = roleAtLeast(payload.user.role, "admin");
```

Then change three uses: the reset guard becomes `if (userChanged || !canViewTimesheets) resetTimesheetsTab(tabPanels.timesheets);` — lifted out of the crew block into its own `if`, since the crew payload reset and the tab reset no longer share a condition; the fallback becomes `if (!canViewTimesheets && activeTab === "timesheets") activeTab = "home";`; and the visibility call becomes `setTimesheetsTabVisible(canViewTimesheets);`.

Update the module header's second paragraph: the Timesheets tab is Admin+, not Supervisor+.

- [x] **Step 6: Clean the test harness**

- `tests/frontend/helpers/endpointTable.js` — delete the two `apiGetHubTimesheets` / `apiExportHubTimesheets` rows.
- `tests/frontend/helpers/factories.js` — delete `hubTimesheets`.
- `tests/frontend/helpers/hub.js` — delete the `timesheets` option, its handler, and `hubTimesheets` from the factory import.
- `tests/frontend/unit/api.shapes.test.js` — delete the two timesheet arms (~lines 56, 145-147).
- `tests/frontend/views/userHub.test.js` — delete every remaining `/hub/timesheets` assertion (lines ~101, 150-158, 256-259) and the `hubTimesheets` import.

- [x] **Step 7: Run the whole frontend suite**

Run: `npx vitest run`
Expected: PASS. The file count drops by one (`hubTimesheets.test.js`) and rises by one (`hubAttendanceRoster.test.js`); the test count drops by the arms deleted here.

- [x] **Step 8: Commit**

```bash
git add -A backend/static tests/frontend
git commit -m "refactor(attendance): delete the crew timesheet view and move Timesheets to Admin+"
```

---

## Task 10: the docs, and the whole suite

**Files:**
- Modify: `docs/endpoint-map.md`, `docs/current-state.md`, `docs/open-work.md`, `docs/notification-events.md`
- Modify: this plan (tick every box)

Living docs are current-truth only: state what is true now and delete the rest. Budgets — `current-state.md` 16,500 words, `endpoint-map.md` 11,000, `open-work.md` 12,000. This task deletes more than it adds, so all three should come in under.

- [x] **Step 1: `docs/endpoint-map.md`**

- Delete rows **H3** and **H4**.
- Add a row for `GET /hub/attendance/live` after H12, numbered H13: **admin only**, `hub.py` → `attendance_live.roster` → `domain.attendance.shift_state` + `work_orders.capped_session_end`; reads attendance_punches, users, work_order_labor_sessions, work_orders — side-effect-free, no sweep, no row locks, no commit; `apiGetHubAttendanceLive`; `hubTimesheetsTab.js`, `hubAttendanceCompare.js`, `hubAttendanceRoster.js`.
- Line ~358: the side-effect-free note names `/hub/timesheets`; rewrite it for `GET /hub` and `/hub/crew` alone, and say the `/hub/attendance/*` reads write nothing.
- Delete the `HubTimesheetResponse` section (~923-939) and add an `AttendanceLiveResponse` section beside `AttendanceWeekResponse`: the two lists, the three counts, `idle_red_minutes`, and that exactly one of `idle_since` / `charging_since` is set per on-shift entry.
- Realtime tables (~754): add `attendance.changed` | Admin+ | the six punch writes; always `id: null` | `hubTimesheetsTab.js`. Update the `id`-is-null note at ~734 to name both always-null events.

- [x] **Step 2: `docs/notification-events.md`**

Add a row beside `labor.session.changed` (~275): `attendance.changed` | any caller authorized for the write | `punch-in`, `punch-out`, `self-close`, and the three `/hub/attendance/punches` writes | connected clients at **Admin** and above.

- [x] **Step 3: `docs/current-state.md`**

Find and rewrite every passage describing the Timesheets tab as Supervisor+ or naming the crew timesheet grid. The tab is Admin+ with two sub-tabs: **Hours** (clocked, with the audited punch editor) and **Charged vs clocked** (the roster strip over the comparison grid, with the CSV). Delete the `GET /hub/timesheets` description rather than marking it removed.

```bash
grep -n "timesheet\|Timesheet" docs/current-state.md
```

- [x] **Step 4: `docs/open-work.md`**

Close **IMP-041**. The three P4b bullets are done; what survives is the residue, which keeps its reasons:

```markdown
### IMP-041 — Attendance timesheet · shipped

- **Logged** 2026-09-21 · *User Hub / Attendance* · **closed** 2026-09-21 · spec
  `docs/superpowers/specs/2026-09-21-attendance-timesheet-design.md`

P1–P4b shipped: the punch record and its state machine, the self-scoped
routes, the work-order clock coupling, the Home tab, the Admin Timesheets tab
(Hours + Charged vs clocked), the audited punch editor, `GET
/hub/attendance/week` · `/export` · `/live`, the `attendance.changed`
envelope, and the retirement of `GET /hub/timesheets` (D6) — at its accepted
cost, that a Supervisor loses the tab and keeps the Dashboard crew board.

Two things were deliberately not built, and reopening either needs a new
reason, not a reminder:

- A **billed** column beside clocked and charged. `billed_labor_minutes`
  rounds a *work order's combined* labor up to 30 minutes across every
  technician and day that touched it, so no per-person-per-day billed number
  exists; one invented here would be an approximation of an invoice in a
  column that reads as a fact. Reopen only with a per-person billing rule
  behind it.
- `promptTime()`'s analog dial. The dropdowns + nudge row shipped in P1, are
  complete and keyboard-accessible, and the dial is optional polish.
```

- [x] **Step 5: Correct the inherited miscount**

P4a's plan and `open-work.md` both said "the four self-scoped punch routes". One of those four is `GET /attendance/me`, a read. The tripwire test in Task 4 records the correction; make sure no doc still says four.

```bash
grep -rn "four self-scoped" docs/
```

- [x] **Step 6: Tick this plan**

Mark every `- [ ]` in this file `- [x]`.

- [x] **Step 7: Run everything**

```bash
cd backend && python -m pytest -q
cd .. && npx vitest run
```

Expected: both green. The frontend baseline before this plan is 88 files; it stays 88 (one deleted, one added). If `test_cascade_deletes_with_user` is red, confirm it is the known environmental failure on a dev database with real cloud-session rows and say so — do not fix it here.

- [x] **Step 8: Commit**

```bash
git add docs/
git commit -m "docs(attendance): P4b closes the timesheet — the roster, the envelope, the retirement"
```

---

## Self-review notes

- **Spec coverage.** §4's `/hub/attendance/live` → Tasks 1–2. §5's envelope → Tasks 3–4. §6's roster (rail colours, red→yellow→green by longest idle, the `N not clocked in` footer, client-side ticking from an instant + skew, technician roles only) → Tasks 1, 6, 7. §7's retirement → Tasks 8–9. §11's phasing closes here. §6's "the comparison owns the subscription and the hub's existing 60 s safety poll" → Task 7, with the poll borrowed from `userHub.js`'s timer rather than duplicated (constraint 4).
- **Deliberate deviations, all recorded above:** six emitters not seven (constraint 1); the two range errors are deleted although spec §7 expects them kept, because `timesheets_hub` is their only caller (constraint 6).
- **Names used consistently:** `roster()`, `RosterEntry`, `LiveRoster`, `idle_anchor`, `emit_attendance_changed`, `apiGetHubAttendanceLive`, `mountHubAttendanceRoster` / `startHubRosterTicking` / `stopHubRosterTicking` / `destroyHubAttendanceRoster`, `refreshTimesheetsLive`, `get_hub_attendance_live`.
