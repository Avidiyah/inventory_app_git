# Attendance P1 — punch record, coupling, Home tab

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the attendance punch as a durable record — table, pure domain, service, self-scoped routes — coupled both ways to the work-order clock, and surface it on a new Home tab that also takes over the quick-start work order.

**Architecture:** `attendance_punches` mirrors `work_order_labor_sessions` exactly: a partial unique index on the open row, a pure domain module for arithmetic, a service for the SQL. Coupling points one way — `services/attendance.py` calls `services/work_orders.py`, never the reverse — and the auto-punch-in half is wired at the route, not inside the 2,600-line work-orders service. The hub gains a Home tabpanel that hosts the existing `#hub-clock-mount` node by reparenting, so `hubClock.js` is not rewritten.

**Tech Stack:** FastAPI · SQLAlchemy 2.0 · Alembic · Postgres · pytest · vanilla ES modules · Vitest + jsdom + MSW

**Spec:** `docs/superpowers/specs/2026-09-21-attendance-timesheet-design.md` (P1 row of §11)

## Global Constraints

- **Day and week arithmetic comes from `app/domain/labor_day.py`.** Never redefine a day boundary, a week bound, or an overlap. `CENTRAL = America/Chicago`; a day is `[00:00, 24:00)` local.
- **`IDLE_RED_MINUTES = 10`** — one constant, declared in `app/domain/attendance.py`, nowhere else.
- **Three numbers stay apart** (spec §8): clocked (attendance), tracked (`labor_day.split_by_day`), billed (`billed_labor_minutes`, rounds to 30). P1 produces **clocked** only. Never round a clocked minute to 30.
- **Start sources:** `manual`, `auto_work_order`. **End sources:** `manual`, `auto_clock_out`, `self_reported`, `admin_edit`. P1 writes `manual`, `auto_work_order`, `self_reported` only.
- **No auto-close** (D4). No code path may close a punch on a read, a sweep, or a timer.
- **CSP drops `style=`** (`main.py:143`, `default-src 'self'`, no `style-src`). Inline style attributes in template literals are silently discarded — use classes, or CSSOM on a node the module owns.
- **No nested buttons.** A `<button>` inside a `<button>` is hoisted out into a sibling.
- **Domain layer is pure**: no FastAPI, no SQLAlchemy, no Pydantic in `app/domain/*`.
- **Commit trailer:** every commit ends with `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- Backend tests: `cd backend && venv/Scripts/python -m pytest`. Frontend: `npm test` from the repo root. Tests taking `db` need Postgres on `DATABASE_URL` (port 8801 locally).

## Decisions this plan makes that the spec left open

| # | Gap | Resolution |
|---|---|---|
| A | §9 says "labor start while a **stale** punch is open" without defining stale | `domain.attendance.is_stale(started_at, now)` = the punch began on an **earlier Central calendar day**. An open punch from today is a normal on-shift punch and blocks nothing. |
| B | §9 says the 409 "returns the stale punch"; `to_http` only carries a string `detail` | The 409 `detail` is a plain sentence naming the punch's start time (so `friendlyError` renders it). The structured punch reaches the UI from `GET /attendance/me`, which already carries it. `PunchAlreadyOpenError` keeps `punch_id` / `started_at` / `stale` as attributes for tests and P3. |
| C | §11 puts `promptTime()` in P3, but D5's self-close (P1) needs a stated time | P1 ships `promptTime()`'s **dropdown half** — hour / minute / AM-PM selects plus the `−15 −5 +5 +15` nudge row. §6 already says the dropdowns are complete alone. P3 layers the dial on the same export and adds its second caller. |
| D | The Work Orders page's Start button can now 409 on a stale punch, with no self-close prompt there | P1's 409 copy names the Home tab as the recovery. A shared prompt on the work-order card is filed in `open-work.md` for P2. |
| E | §11 P1 says "table + migration" (singular); §1 defines two tables | One migration creates both. `attendance_punch_edits` is unwritten until P3; creating it now avoids a second migration for one design section. |

---

### Task 1: The tables

**Files:**
- Create: `backend/alembic/versions/b7d9f1a3c5e8_add_attendance_punches.py`
- Modify: `backend/app/models.py` (append after `WorkOrderLaborSession`, which ends at `models.py:617`)
- Test: `backend/tests/test_attendance_model.py`

**Interfaces:**
- Produces: `app.models.AttendancePunch` (`id`, `user_id`, `started_at`, `ended_at`, `start_source`, `end_source`, `needs_review`, `created_at`) and `app.models.AttendancePunchEdit` (`id`, `punch_id`, `edited_by_id`, `edited_at`, `field`, `old_value`, `new_value`, `reason`).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_attendance_model.py
"""The one thing the table itself must guarantee: one open punch per person."""
import os, sys, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import AttendancePunch, User
from app.services import auth as auth_service


def _seed_user(db):
    user = User(username=f"u-{uuid.uuid4().hex[:10]}",
                password_hash=auth_service.hash_password("hunter2"), role="technician")
    db.add(user); db.flush()
    return user


def test_a_second_open_punch_is_refused_by_the_database(db):
    user = _seed_user(db)
    now = datetime.now(timezone.utc)
    db.add(AttendancePunch(user_id=user.id, started_at=now, start_source="manual"))
    db.flush()
    db.add(AttendancePunch(user_id=user.id, started_at=now, start_source="manual"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_a_closed_punch_leaves_room_for_the_next_one(db):
    user = _seed_user(db)
    now = datetime.now(timezone.utc)
    db.add(AttendancePunch(user_id=user.id, started_at=now - timedelta(hours=9),
                           ended_at=now - timedelta(hours=1),
                           start_source="manual", end_source="manual"))
    db.flush()
    db.add(AttendancePunch(user_id=user.id, started_at=now, start_source="manual"))
    db.flush()  # no IntegrityError
```

- [ ] **Step 2: Run it and watch it fail**

`cd backend && venv/Scripts/python -m pytest tests/test_attendance_model.py -v`
Expected: `ImportError: cannot import name 'AttendancePunch'`.

- [ ] **Step 3: Write the migration**

`down_revision` is `"e2f4a6c8b0d3"` (`add_work_order_report_weeks`, the current head — confirm with `venv/Scripts/python -m alembic heads` before writing). Copy the shape of `a2c4e6b8d0f1_add_work_order_labor_sessions.py`, including the `postgresql_where` partial index:

```python
"""add attendance_punches and attendance_punch_edits

Revision ID: b7d9f1a3c5e8
Revises: e2f4a6c8b0d3
Create Date: 2026-09-21 12:00:00.000000

The attendance record (spec 2026-09-21-attendance-timesheet-design.md §1):
on-shift time, separate from the billable `work_order_labor_sessions` record
and owned by Admin+. Nothing is backfilled -- there is no historical source
for "was this person at work," and inventing one from labor sessions would
put an estimate into a pay record.

`attendance_punch_edits` is created here although nothing writes it until
P3: §1 defines the pair as one unit, and a second migration for one design
section is churn.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b7d9f1a3c5e8"
down_revision: Union[str, Sequence[str], None] = "e2f4a6c8b0d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "attendance_punches",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("start_source", sa.Text(), nullable=False),
        sa.Column("end_source", sa.Text(), nullable=True),
        sa.Column("needs_review", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_attendance_punches_user_started",
                    "attendance_punches", ["user_id", "started_at"])
    # One open punch per person, in the database rather than in a service
    # check that races -- the mechanism
    # `uq_work_order_labor_sessions_running_technician` already uses.
    op.create_index(
        "uq_attendance_punches_open_user",
        "attendance_punches",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
    )
    op.create_table(
        "attendance_punch_edits",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("punch_id", sa.UUID(), nullable=False),
        sa.Column("edited_by_id", sa.UUID(), nullable=False),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("field", sa.Text(), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        # CASCADE: the audit row describes an edit to this punch and has no
        # meaning without it. A deleted punch's own deletion is itself
        # recorded by P3 against the punch that is going away, so nothing of
        # value survives the parent.
        sa.ForeignKeyConstraint(["punch_id"], ["attendance_punches.id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["edited_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_attendance_punch_edits_punch_id",
                    "attendance_punch_edits", ["punch_id"])


def downgrade() -> None:
    op.drop_index("ix_attendance_punch_edits_punch_id",
                  table_name="attendance_punch_edits")
    op.drop_table("attendance_punch_edits")
    op.drop_index("uq_attendance_punches_open_user",
                  table_name="attendance_punches")
    op.drop_index("ix_attendance_punches_user_started",
                  table_name="attendance_punches")
    op.drop_table("attendance_punches")
```

- [ ] **Step 4: Write the models**

Append to `backend/app/models.py`. Mirror `WorkOrderLaborSession`'s `__table_args__` exactly — the `Index(..., unique=True, postgresql_where=text("ended_at IS NULL"))` form — so the ORM metadata and the migration agree.

```python
class AttendancePunch(Base):
    """One stretch of being on shift, for one person.

    The payroll record, and deliberately not the billable one: a
    `WorkOrderLaborSession` says which customer is charged, this says whether
    somebody was at work. The gap between them is the whole point of the
    Admin timesheet (spec §8) and is never closed by code.

    `ended_at IS NULL` means on shift. There is **no auto-close** (D4): a
    punch forgotten on Tuesday stays open until a human resolves it, because
    nothing estimated may silently reach a pay record. The technician's own
    resolution sets `end_source='self_reported'` and `needs_review=True`
    (D5).
    """

    __tablename__ = "attendance_punches"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    start_source = Column(Text, nullable=False)
    end_source = Column(Text, nullable=True)
    needs_review = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    user = relationship("User", foreign_keys=[user_id], viewonly=True)
    edits = relationship("AttendancePunchEdit", back_populates="punch",
                         cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_attendance_punches_user_started", "user_id", "started_at"),
        Index("uq_attendance_punches_open_user", "user_id",
              unique=True, postgresql_where=text("ended_at IS NULL")),
    )


class AttendancePunchEdit(Base):
    """Append-only audit of an Admin's change to a punch (spec §1).

    Written by P3's `edit_punch` / `add_punch` / `delete_punch`; nothing in
    P1 writes here. One row per field changed, values stored as text so the
    table does not need a column per punch field.
    """

    __tablename__ = "attendance_punch_edits"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    punch_id = Column(UUID(as_uuid=True),
                      ForeignKey("attendance_punches.id", ondelete="CASCADE"),
                      nullable=False)
    edited_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    edited_at = Column(DateTime(timezone=True), nullable=False,
                       default=lambda: datetime.now(timezone.utc))
    field = Column(Text, nullable=False)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    reason = Column(Text, nullable=True)

    punch = relationship("AttendancePunch", back_populates="edits")

    __table_args__ = (Index("ix_attendance_punch_edits_punch_id", "punch_id"),)
```

Check the top of `models.py` already imports `Boolean` and `text`; add whichever is missing to the existing `from sqlalchemy import ...` line.

- [ ] **Step 5: Apply the migration and run the tests**

```
cd backend && venv/Scripts/python -m alembic upgrade head
venv/Scripts/python -m pytest tests/test_attendance_model.py -v
```
Expected: 2 passed. Then `venv/Scripts/python -m alembic downgrade -1 && venv/Scripts/python -m alembic upgrade head` to prove the downgrade runs.

- [ ] **Step 6: Commit**

```bash
git add backend/alembic/versions/b7d9f1a3c5e8_add_attendance_punches.py backend/app/models.py backend/tests/test_attendance_model.py
git commit -m "feat(attendance): attendance_punches and its audit table"
```

---

### Task 2: `domain/attendance.py` and the error vocabulary

**Files:**
- Create: `backend/app/domain/attendance.py`
- Modify: `backend/app/domain/errors.py` (append), `backend/app/routers/_errors.py` (import + `_STATUS_MAP`)
- Test: `backend/tests/test_attendance_domain.py`

**Interfaces:**
- Produces: `IDLE_RED_MINUTES`, `START_SOURCE_MANUAL`, `START_SOURCE_AUTO_WORK_ORDER`, `END_SOURCE_MANUAL`, `END_SOURCE_AUTO_CLOCK_OUT`, `END_SOURCE_SELF_REPORTED`, `END_SOURCE_ADMIN_EDIT`, `STATE_GREEN|YELLOW|RED|GRAY`, `idle_minutes(*, punch_started_at, last_labor_ended_at, now) -> int`, `shift_state(*, punch_started_at, labor_running, last_labor_ended_at, now) -> str`, `is_stale(punch_started_at, *, now) -> bool`, `validate_punch_window(started_at, ended_at, *, now) -> None`, `find_overlap(started_at, ended_at, existing, *, now) -> Optional[uuid.UUID]`.
- Produces: `PunchAlreadyOpenError(message, *, punch_id, started_at, stale)`, `PunchOverlapError(message, *, punch_id)`, `PunchTimeInvalidError`, `PunchNotFoundError`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_attendance_domain.py
"""Pure state-machine and validation rules -- no Postgres, no FastAPI."""
import os, sys, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone

import pytest

from app.domain import attendance, labor_day
from app.domain.errors import PunchTimeInvalidError

NOW = datetime(2026, 9, 21, 18, 0, tzinfo=timezone.utc)   # 1:00 PM Central, Monday


def test_no_open_punch_is_gray():
    assert attendance.shift_state(
        punch_started_at=None, labor_running=False,
        last_labor_ended_at=None, now=NOW) == attendance.STATE_GRAY


def test_a_running_labor_session_is_green_however_long_the_punch():
    assert attendance.shift_state(
        punch_started_at=NOW - timedelta(hours=6), labor_running=True,
        last_labor_ended_at=None, now=NOW) == attendance.STATE_GREEN


@pytest.mark.parametrize("idle,expected", [
    (0, attendance.STATE_YELLOW),
    (9, attendance.STATE_YELLOW),
    (10, attendance.STATE_RED),     # the edge is inclusive
    (11, attendance.STATE_RED),
])
def test_idle_minutes_pick_yellow_or_red_at_the_ten_minute_edge(idle, expected):
    assert attendance.shift_state(
        punch_started_at=NOW - timedelta(hours=4), labor_running=False,
        last_labor_ended_at=NOW - timedelta(minutes=idle), now=NOW) == expected


def test_idle_counts_from_the_punch_when_no_labor_has_run_yet():
    # The accepted consequence in §2: a slow start after arrival shows red.
    assert attendance.idle_minutes(
        punch_started_at=NOW - timedelta(minutes=25),
        last_labor_ended_at=None, now=NOW) == 25


def test_idle_counts_from_the_later_of_the_two_anchors():
    assert attendance.idle_minutes(
        punch_started_at=NOW - timedelta(hours=5),
        last_labor_ended_at=NOW - timedelta(minutes=3), now=NOW) == 3


def test_a_punch_from_an_earlier_central_day_is_stale():
    # 11:00 PM Central Sunday, read at 1:00 PM Central Monday.
    assert attendance.is_stale(datetime(2026, 9, 21, 4, 0, tzinfo=timezone.utc), now=NOW)


def test_a_punch_from_this_central_day_is_not_stale():
    assert not attendance.is_stale(NOW - timedelta(hours=6), now=NOW)


def test_the_central_day_is_what_decides_staleness_not_utc():
    # 8:00 PM Central Monday = 01:00 UTC Tuesday. Same Central day, not stale.
    later = datetime(2026, 9, 22, 2, 0, tzinfo=timezone.utc)   # 9:00 PM Central Mon
    assert not attendance.is_stale(datetime(2026, 9, 22, 1, 0, tzinfo=timezone.utc), now=later)


@pytest.mark.parametrize("started,ended,fragment", [
    (NOW - timedelta(hours=1), NOW - timedelta(hours=2), "after it starts"),
    (NOW - timedelta(hours=1), NOW - timedelta(hours=1), "after it starts"),
    (NOW + timedelta(minutes=1), None, "future"),
    (NOW - timedelta(hours=1), NOW + timedelta(minutes=1), "future"),
])
def test_invalid_windows_are_refused(started, ended, fragment):
    with pytest.raises(PunchTimeInvalidError) as exc:
        attendance.validate_punch_window(started, ended, now=NOW)
    assert fragment in str(exc.value)


def test_an_open_window_ending_nowhere_is_valid():
    attendance.validate_punch_window(NOW - timedelta(hours=1), None, now=NOW)


def test_overlap_names_the_conflicting_punch():
    other = uuid.uuid4()
    existing = [(other, NOW - timedelta(hours=3), NOW - timedelta(hours=1))]
    assert attendance.find_overlap(
        NOW - timedelta(hours=2), NOW - timedelta(minutes=30),
        existing, now=NOW) == other


def test_punches_that_only_touch_do_not_overlap():
    other = uuid.uuid4()
    existing = [(other, NOW - timedelta(hours=3), NOW - timedelta(hours=1))]
    assert attendance.find_overlap(
        NOW - timedelta(hours=1), NOW, existing, now=NOW) is None


def test_an_open_existing_punch_overlaps_everything_up_to_now():
    other = uuid.uuid4()
    existing = [(other, NOW - timedelta(hours=3), None)]
    assert attendance.find_overlap(
        NOW - timedelta(minutes=20), NOW - timedelta(minutes=10),
        existing, now=NOW) == other


def test_the_spring_forward_week_is_167_hours():
    # The attendance week IS the report's week, so this is labor_day's rule
    # being reused, not a parallel one. 2026-03-08 is the US spring forward.
    monday, sunday = labor_day.week_bounds_containing(datetime(2026, 3, 10).date())
    start, _ = labor_day.day_bounds(monday)
    _, end = labor_day.day_bounds(sunday)
    assert (end - start) == timedelta(hours=167)
```

- [ ] **Step 2: Run it and watch it fail**

`cd backend && venv/Scripts/python -m pytest tests/test_attendance_domain.py -v`
Expected: `ModuleNotFoundError: No module named 'app.domain.attendance'`.

- [ ] **Step 3: Write the four errors**

Append to `backend/app/domain/errors.py`:

```python
class PunchAlreadyOpenError(DomainError):
    """Raised when a punch-in, or a labor start behind a *stale* punch, finds
    an open `attendance_punches` row. Per D4 nothing auto-closes, so this is
    a conflict the caller resolves (D5's self-close), not a failure.

    Carries the offending punch so the router's message can name its start
    time and so P3 can act on it. The wire payload is a plain sentence; the
    structured punch reaches the UI from `GET /attendance/me`. Maps to 409."""

    def __init__(self, message: str, *, punch_id, started_at, stale: bool):
        super().__init__(message)
        self.punch_id = punch_id
        self.started_at = started_at
        self.stale = stale


class PunchOverlapError(DomainError):
    """Raised when a punch would overlap another punch for the same person.
    Open punches are guarded by the partial unique index; this is the domain
    check that covers *closed* punches, which D2 lets an Admin create.
    Carries the conflicting punch's id. Maps to 409."""

    def __init__(self, message: str, *, punch_id):
        super().__init__(message)
        self.punch_id = punch_id


class PunchTimeInvalidError(DomainError):
    """Raised for a punch window that ends at or before it starts, or that
    reaches into the future (spec §9). Maps to 400."""


class PunchNotFoundError(DomainError):
    """Raised when a punch write names a row that does not exist, or when a
    punch-out / self-close finds no open punch for the caller. Maps to 404."""
```

Add all four to `_errors.py`'s import block (alphabetical, beside `NoChangeError`) and to `_STATUS_MAP`:

```python
    PunchAlreadyOpenError: 409,
    PunchOverlapError: 409,
    PunchTimeInvalidError: 400,
    PunchNotFoundError: 404,
```

- [ ] **Step 4: Write `backend/app/domain/attendance.py`**

```python
"""Pure attendance rules: the shift state machine and punch validation.

Layer: domain. No FastAPI, no SQLAlchemy, no database -- the rule every
module in this package follows, and the reason the whole state machine is
tested without Postgres.

Day and week arithmetic is **not** here. `domain.labor_day` owns it, and is
reused unchanged so the attendance week is the same object as
`services.work_order_report.resolve_week`'s week rather than a parallel
definition free to drift.

The three numbers `labor_day` warns about stay apart here too: this module
produces *clocked* time only -- on shift, the pay number. It never rounds,
never floors, and never sees `billed_labor_minutes`.
"""

import uuid
from datetime import datetime
from typing import Iterable, Optional

from app.domain import labor_day
from app.domain.errors import PunchTimeInvalidError

# The one idle threshold, with one home. A punch that is open, not charging,
# and idle this long or longer reads red on the Admin roster (§2).
IDLE_RED_MINUTES = 10

START_SOURCE_MANUAL = "manual"
START_SOURCE_AUTO_WORK_ORDER = "auto_work_order"

END_SOURCE_MANUAL = "manual"
# Declared for completeness of the §1 vocabulary. Nothing writes it: D4
# forbids auto-close, so the value exists only so a future rule that needs
# it does not invent a sixth name.
END_SOURCE_AUTO_CLOCK_OUT = "auto_clock_out"
END_SOURCE_SELF_REPORTED = "self_reported"
END_SOURCE_ADMIN_EDIT = "admin_edit"

# On shift and charging / on shift, idle briefly / on shift, idle long / off.
STATE_GREEN = "green"
STATE_YELLOW = "yellow"
STATE_RED = "red"
STATE_GRAY = "gray"


def idle_minutes(
    *,
    punch_started_at: datetime,
    last_labor_ended_at: Optional[datetime],
    now: datetime,
) -> int:
    """Whole minutes since this person last had a reason to be charging.

    `now - max(punch.started_at, last_labor_session.ended_at)`. With no labor
    yet, the punch itself is the anchor -- the accepted consequence in §2 is
    that a slow start after arrival shows red before the first job, which is
    correct information, not a false alarm.

    Truncated, not rounded: the row prints `idle 12m` beside the color, and a
    number that rounds up would cross `IDLE_RED_MINUTES` a half-minute before
    the color does.
    """
    anchor = labor_day.as_utc(punch_started_at)
    if last_labor_ended_at is not None:
        anchor = max(anchor, labor_day.as_utc(last_labor_ended_at))
    seconds = (labor_day.as_utc(now) - anchor).total_seconds()
    return max(0, int(seconds // 60))


def shift_state(
    *,
    punch_started_at: Optional[datetime],
    labor_running: bool,
    last_labor_ended_at: Optional[datetime],
    now: datetime,
) -> str:
    """The roster color (§2). Gray means no open punch -- not "absent";
    somebody who never punched in has no state to judge."""
    if punch_started_at is None:
        return STATE_GRAY
    if labor_running:
        return STATE_GREEN
    idle = idle_minutes(
        punch_started_at=punch_started_at,
        last_labor_ended_at=last_labor_ended_at,
        now=now,
    )
    return STATE_RED if idle >= IDLE_RED_MINUTES else STATE_YELLOW


def is_stale(punch_started_at: datetime, *, now: datetime) -> bool:
    """Whether an open punch began on an **earlier Central calendar day**.

    The spec names a "stale punch" in D5 and §9 without defining it; this is
    that definition. Today's open punch is an ordinary on-shift punch and
    blocks nothing -- a technician who punched in this morning and starts a
    second job at noon must not be stopped. Yesterday's is the clerical error
    D5 exists to unblock, and blocking *that* is what would stop Wednesday's
    jobs.

    Built on `labor_day.central_date_of`, so a 9 PM punch read at 10 PM is
    the same day even though it crossed midnight UTC.
    """
    return labor_day.central_date_of(punch_started_at) < labor_day.central_date_of(now)


def validate_punch_window(
    started_at: datetime,
    ended_at: Optional[datetime],
    *,
    now: datetime,
) -> None:
    """Spec §9's first two rows. `ended_at=None` is an open punch, valid."""
    moment = labor_day.as_utc(now)
    start = labor_day.as_utc(started_at)
    if start > moment:
        raise PunchTimeInvalidError("A punch cannot start in the future.")
    if ended_at is None:
        return
    end = labor_day.as_utc(ended_at)
    if end > moment:
        raise PunchTimeInvalidError("A punch cannot end in the future.")
    if end <= start:
        raise PunchTimeInvalidError("A punch must end after it starts.")


def find_overlap(
    started_at: datetime,
    ended_at: Optional[datetime],
    existing: Iterable[tuple[uuid.UUID, datetime, Optional[datetime]]],
    *,
    now: datetime,
) -> Optional[uuid.UUID]:
    """The id of the first of `existing` that overlaps `[started_at, ended_at)`.

    `existing` is `(punch_id, started_at, ended_at)` triples -- plain values,
    not ORM rows, so this stays pure. `None` for either end means "still open"
    and `now` stands in for it.

    Half-open on both sides: a punch that ends exactly when the next begins
    does not overlap it, which is what makes punching out for lunch and
    straight back in a legal pair.

    Used by P3's Admin edits. P1 leaves closed-punch overlap unreachable,
    because nothing below Admin can create a closed punch at a chosen time.
    """
    moment = labor_day.as_utc(now)
    start = labor_day.as_utc(started_at)
    end = labor_day.as_utc(ended_at) if ended_at is not None else moment
    for punch_id, other_start, other_end in existing:
        o_start = labor_day.as_utc(other_start)
        o_end = labor_day.as_utc(other_end) if other_end is not None else moment
        if o_start < end and start < o_end:
            return punch_id
    return None
```

- [ ] **Step 5: Run the tests**

`cd backend && venv/Scripts/python -m pytest tests/test_attendance_domain.py -v`
Expected: all pass (no DB needed).

- [ ] **Step 6: Commit**

```bash
git add backend/app/domain/attendance.py backend/app/domain/errors.py backend/app/routers/_errors.py backend/tests/test_attendance_domain.py
git commit -m "feat(attendance): pure state machine, staleness, and punch validation"
```

---

### Task 3: `services/attendance.py`

**Files:**
- Create: `backend/app/services/attendance.py`
- Modify: `backend/app/services/work_orders.py` (one public accessor beside `_running_session_for_user`, `work_orders.py:2345`)
- Test: `backend/tests/test_attendance_service.py`

**Interfaces:**
- Consumes: Task 1's `AttendancePunch`; Task 2's whole surface.
- Produces: `open_punch_for(db, user_id) -> Optional[AttendancePunch]`, `punch_in(db, *, user, now=None, source=START_SOURCE_MANUAL) -> AttendancePunch`, `punch_out(db, *, user, now=None) -> AttendancePunch`, `self_close(db, *, user, ended_at, now=None) -> AttendancePunch`, `ensure_punch_for_labor_start(db, *, user, now=None) -> AttendancePunch`, `me_payload(db, *, user, now=None) -> AttendanceMe`, dataclasses `AttendanceMe(server_now, day, open_punch, clocked_minutes_today)` and `OpenPunch(id, started_at, start_source, stale)`.
- Produces: `app.services.work_orders.running_labor_session_for(db, user_id) -> Optional[WorkOrderLaborSession]`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_attendance_service.py
"""The coupling in both directions, the stale refusal, and the self-close."""
import os, sys, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone

import pytest

from app.domain import attendance as attendance_domain
from app.domain.errors import PunchAlreadyOpenError, PunchNotFoundError, PunchTimeInvalidError
from app.models import AttendancePunch, User
from app.services import attendance as attendance_service
from app.services import auth as auth_service
from app.services import work_orders as wo_service


def _seed_user(db, role="technician"):
    user = User(username=f"u-{uuid.uuid4().hex[:10]}",
                password_hash=auth_service.hash_password("hunter2"), role=role)
    db.add(user); db.flush()
    return user


def _seed_work_order(db, admin, technician):
    order = wo_service.get_or_create_work_order(
        db, number=f"WO-ATT-{uuid.uuid4().hex[:8]}", created_by_id=admin.id)
    wo_service.set_work_order_technicians(db, order.id, [technician.id], user=admin)
    db.commit()
    return order


def test_punch_in_opens_a_manual_punch(db):
    user = _seed_user(db)
    punch = attendance_service.punch_in(db, user=user)
    assert punch.ended_at is None
    assert punch.start_source == attendance_domain.START_SOURCE_MANUAL
    assert punch.needs_review is False


def test_punch_in_refuses_while_one_is_open_and_names_it(db):
    user = _seed_user(db)
    first = attendance_service.punch_in(db, user=user)
    with pytest.raises(PunchAlreadyOpenError) as exc:
        attendance_service.punch_in(db, user=user)
    assert exc.value.punch_id == first.id
    assert exc.value.stale is False


def test_starting_a_work_order_clock_off_shift_punches_in_automatically(db):
    admin, tech = _seed_user(db, "admin"), _seed_user(db)
    order = _seed_work_order(db, admin, tech)
    attendance_service.ensure_punch_for_labor_start(db, user=tech)
    wo_service.start_labor_session(db, order.id, user=tech)
    punch = attendance_service.open_punch_for(db, tech.id)
    assert punch is not None
    assert punch.start_source == attendance_domain.START_SOURCE_AUTO_WORK_ORDER


def test_an_open_punch_from_today_lets_a_labor_start_through_unchanged(db):
    tech = _seed_user(db)
    opened = attendance_service.punch_in(db, user=tech)
    assert attendance_service.ensure_punch_for_labor_start(db, user=tech).id == opened.id


def test_a_stale_punch_blocks_the_labor_start(db):
    tech = _seed_user(db)
    now = datetime.now(timezone.utc)
    db.add(AttendancePunch(user_id=tech.id, started_at=now - timedelta(days=2),
                           start_source=attendance_domain.START_SOURCE_MANUAL))
    db.commit()
    with pytest.raises(PunchAlreadyOpenError) as exc:
        attendance_service.ensure_punch_for_labor_start(db, user=tech)
    assert exc.value.stale is True


def test_punch_out_force_stops_the_running_work_order_clock(db):
    admin, tech = _seed_user(db, "admin"), _seed_user(db)
    order = _seed_work_order(db, admin, tech)
    attendance_service.punch_in(db, user=tech)
    wo_service.start_labor_session(db, order.id, user=tech)
    attendance_service.punch_out(db, user=tech)
    assert wo_service.running_labor_session_for(db, tech.id) is None
    assert attendance_service.open_punch_for(db, tech.id) is None


def test_punch_out_without_a_punch_is_a_404(db):
    with pytest.raises(PunchNotFoundError):
        attendance_service.punch_out(db, user=_seed_user(db))


def test_self_close_flags_the_punch_for_review_at_the_stated_time(db):
    tech = _seed_user(db)
    now = datetime.now(timezone.utc)
    started = now - timedelta(days=1, hours=6)
    db.add(AttendancePunch(user_id=tech.id, started_at=started,
                           start_source=attendance_domain.START_SOURCE_MANUAL))
    db.commit()
    stated = started + timedelta(hours=8)
    punch = attendance_service.self_close(db, user=tech, ended_at=stated)
    assert punch.ended_at == stated
    assert punch.end_source == attendance_domain.END_SOURCE_SELF_REPORTED
    assert punch.needs_review is True
    # And the next punch-in is unblocked -- the whole point of D5.
    assert attendance_service.punch_in(db, user=tech) is not None


def test_self_close_refuses_a_time_before_the_punch_started(db):
    tech = _seed_user(db)
    started = datetime.now(timezone.utc) - timedelta(hours=3)
    db.add(AttendancePunch(user_id=tech.id, started_at=started,
                           start_source=attendance_domain.START_SOURCE_MANUAL))
    db.commit()
    with pytest.raises(PunchTimeInvalidError):
        attendance_service.self_close(db, user=tech, ended_at=started - timedelta(hours=1))


def test_me_payload_sums_todays_clocked_minutes_without_rounding(db):
    tech = _seed_user(db)
    now = datetime.now(timezone.utc)
    db.add(AttendancePunch(user_id=tech.id, started_at=now - timedelta(minutes=47),
                           ended_at=now - timedelta(minutes=5),
                           start_source=attendance_domain.START_SOURCE_MANUAL,
                           end_source=attendance_domain.END_SOURCE_MANUAL))
    db.commit()
    payload = attendance_service.me_payload(db, user=tech, now=now)
    assert payload.open_punch is None
    assert payload.clocked_minutes_today == 42      # not 60, not 30
```

`test_me_payload_...` is only correct when "42 minutes ago" is still the same Central day as `now`; run the suite normally and, if it fails between 00:00 and 00:47 Central, pin `now` to a fixed mid-afternoon UTC instant and seed against it.

- [ ] **Step 2: Run it and watch it fail**

`cd backend && venv/Scripts/python -m pytest tests/test_attendance_service.py -v`
Expected: `ModuleNotFoundError: No module named 'app.services.attendance'`.

- [ ] **Step 3: Expose the running session from `services/work_orders.py`**

Immediately after `_running_session_for_user` (which ends around `work_orders.py:2366`), add:

```python
def running_labor_session_for(
    db: Session, user_id: uuid.UUID
) -> Optional[WorkOrderLaborSession]:
    """The public face of `_running_session_for_user`.

    `services.attendance` needs to know whether a clock is running in order to
    force-stop it on punch-out (D3) and to color the roster (§2). Exporting
    this one read is what lets the dependency point *one* way: attendance
    knows about labor, labor knows nothing about attendance.
    """
    return _running_session_for_user(db, user_id)
```

- [ ] **Step 4: Write `backend/app/services/attendance.py`**

```python
"""Attendance punches: the on-shift record and its coupling to the clock.

Layer: services. Owns every `attendance_punches` query; every *rule* lives in
`app.domain.attendance`, which is why the state machine is tested without a
database and this module is SQL plus assembly.

**The coupling lives here** (spec §3), in the caller of
`work_orders.start_labor_session`, not inside the ~2,600-line
`services/work_orders.py`. The dependency points one way: this module imports
work orders, work orders never imports this.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain import attendance, labor_day
from app.domain.errors import PunchAlreadyOpenError, PunchNotFoundError
from app.models import AttendancePunch, User
from app.services import work_orders as wo_service


@dataclass(frozen=True)
class OpenPunch:
    id: uuid.UUID
    started_at: datetime
    start_source: str
    stale: bool


@dataclass(frozen=True)
class AttendanceMe:
    """What the Home tab needs and nothing more. `clocked_minutes_today` is
    the *pay* number -- real wall-clock, never rounded to 30 (§8)."""

    server_now: datetime
    day: date
    open_punch: Optional[OpenPunch]
    clocked_minutes_today: int


def open_punch_for(db: Session, user_id: uuid.UUID) -> Optional[AttendancePunch]:
    """This person's open punch, or None. The partial unique index permits
    exactly one, so this is a single indexed lookup."""
    return (
        db.query(AttendancePunch)
        .filter(AttendancePunch.user_id == user_id, AttendancePunch.ended_at.is_(None))
        .first()
    )


def _already_open(punch: AttendancePunch, *, now: datetime) -> PunchAlreadyOpenError:
    stale = attendance.is_stale(punch.started_at, now=now)
    started = labor_day.as_utc(punch.started_at).astimezone(labor_day.CENTRAL)
    # Hour formatted by hand: `%-I` is glibc-only and `%#I` is Windows-only,
    # and this app runs on both.
    when = f"{started:%a} {started.hour % 12 or 12}:{started:%M %p}"
    message = (
        f"You are still punched in from {when}. Close it on your Home tab "
        "before starting again."
        if stale
        else f"You are already punched in since {when}."
    )
    return PunchAlreadyOpenError(message, punch_id=punch.id,
                                 started_at=punch.started_at, stale=stale)


def punch_in(
    db: Session,
    *,
    user: User,
    now: Optional[datetime] = None,
    source: str = attendance.START_SOURCE_MANUAL,
) -> AttendancePunch:
    """Open a punch. Refuses when one is open (D4), returning it on the
    exception so the UI can drive D5's prompt.

    The `IntegrityError` arm is the race the partial unique index exists to
    win: two taps that both pass the pre-check, one insert, the loser
    re-reads and reports the same conflict.
    """
    now = now or datetime.now(timezone.utc)
    existing = open_punch_for(db, user.id)
    if existing is not None:
        raise _already_open(existing, now=now)

    punch = AttendancePunch(
        id=uuid.uuid4(), user_id=user.id, started_at=now, start_source=source
    )
    db.add(punch)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        winner = open_punch_for(db, user.id)
        if winner is None:
            raise
        raise _already_open(winner, now=now) from exc
    db.refresh(punch)
    return punch


def punch_out(
    db: Session, *, user: User, now: Optional[datetime] = None
) -> AttendancePunch:
    """Close the punch **and** force-stop any running labor session (D3).

    Labor first, deliberately: `stop_labor_session` writes the labor row at
    its own `now`, and closing the punch first would leave a charged minute
    landing after the shift ended -- the exact shape §9 flags as a warning
    rather than a refusal, and there is no reason to manufacture one here.
    """
    now = now or datetime.now(timezone.utc)
    punch = open_punch_for(db, user.id)
    if punch is None:
        raise PunchNotFoundError("You are not punched in.")

    running = wo_service.running_labor_session_for(db, user.id)
    if running is not None:
        wo_service.stop_labor_session(db, running.work_order_id, user=user)

    punch.ended_at = now
    punch.end_source = attendance.END_SOURCE_MANUAL
    db.commit()
    db.refresh(punch)
    return punch


def self_close(
    db: Session, *, user: User, ended_at: datetime, now: Optional[datetime] = None
) -> AttendancePunch:
    """D5: the technician closes their own stale punch at a stated time.

    Flagged `needs_review` and `end_source='self_reported'` -- an estimate,
    labelled as one, that an Admin corrects in P3. Without this, D3 and D4
    together would let Tuesday's clerical error stop Wednesday's jobs.
    """
    now = now or datetime.now(timezone.utc)
    punch = open_punch_for(db, user.id)
    if punch is None:
        raise PunchNotFoundError("You have no open punch to close.")
    attendance.validate_punch_window(punch.started_at, ended_at, now=now)
    punch.ended_at = labor_day.as_utc(ended_at)
    punch.end_source = attendance.END_SOURCE_SELF_REPORTED
    punch.needs_review = True
    db.commit()
    db.refresh(punch)
    return punch


def ensure_punch_for_labor_start(
    db: Session, *, user: User, now: Optional[datetime] = None
) -> AttendancePunch:
    """Called immediately before `work_orders.start_labor_session` (D3).

    A technician who ignores the punch button still produces a correct
    timesheet: starting a clock off-shift opens a punch tagged
    `auto_work_order`. A *stale* punch refuses instead, because charging a
    job against a shift that started two days ago is not a record anyone can
    pay from.
    """
    now = now or datetime.now(timezone.utc)
    existing = open_punch_for(db, user.id)
    if existing is not None:
        if attendance.is_stale(existing.started_at, now=now):
            raise _already_open(existing, now=now)
        return existing
    return punch_in(db, user=user, now=now,
                    source=attendance.START_SOURCE_AUTO_WORK_ORDER)


def me_payload(
    db: Session, *, user: User, now: Optional[datetime] = None
) -> AttendanceMe:
    """The Home tab's state. Side-effect-free: no sweep, no row locks (§4)."""
    now = now or datetime.now(timezone.utc)
    today = labor_day.central_date_of(now)
    day_start, day_end = labor_day.day_bounds(today)

    punches = (
        db.query(AttendancePunch)
        .filter(
            AttendancePunch.user_id == user.id,
            AttendancePunch.started_at < day_end,
            or_(AttendancePunch.ended_at.is_(None),
                AttendancePunch.ended_at > day_start),
        )
        .all()
    )
    minutes = sum(
        labor_day.overlap_minutes(p.started_at, p.ended_at, day_start, day_end, now=now)
        for p in punches
    )
    open_row = next((p for p in punches if p.ended_at is None), None)
    return AttendanceMe(
        server_now=now,
        day=today,
        open_punch=None if open_row is None else OpenPunch(
            id=open_row.id,
            started_at=open_row.started_at,
            start_source=open_row.start_source,
            stale=attendance.is_stale(open_row.started_at, now=now),
        ),
        clocked_minutes_today=minutes,
    )
```

- [ ] **Step 5: Run the tests**

`cd backend && venv/Scripts/python -m pytest tests/test_attendance_service.py tests/test_attendance_domain.py tests/test_attendance_model.py -v`
Expected: all pass. If `set_work_order_technicians` is not the assignment helper's real name, find it with `grep -n "def set_work_order_technicians\|def assign" backend/app/services/work_orders.py` and fix the two calls in `_seed_work_order`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/attendance.py backend/app/services/work_orders.py backend/tests/test_attendance_service.py
git commit -m "feat(attendance): punch service with the two-way work-order clock coupling"
```

---

### Task 4: Schemas, router, and the D3 wire at the work-order route

**Files:**
- Create: `backend/app/schemas/attendance.py`, `backend/app/routers/attendance.py`
- Modify: `backend/app/main.py` (the `from app.routers import (...)` block at `main.py:48` and the `include_router` run at `main.py:306`), `backend/app/routers/work_orders.py` (`start_work_order_tracking`, `work_orders.py:1051`)
- Test: `backend/tests/test_attendance_router.py`

**Interfaces:**
- Consumes: Task 3's whole service surface.
- Produces: `GET /attendance/me`, `POST /attendance/punch-in`, `POST /attendance/punch-out`, `POST /attendance/self-close`. Response models `AttendanceMeResponse {server_now, day, open_punch, clocked_minutes_today}`, `AttendanceOpenPunch {id, started_at, start_source, stale}`, `AttendancePunchResponse {id, started_at, ended_at, start_source, end_source, needs_review}`. Request model `SelfCloseRequest {ended_at: datetime}`.

- [ ] **Step 1: Write the failing test**

Drive every case over real HTTP with `TestClient`, never by calling the handler — this repo has been bitten once by FastAPI query parsing (see `test_work_orders_router.py`'s module docstring). Copy its `_seed_user` / `dependency_overrides[get_db]` / `client.cookies.set("session", token)` scaffold verbatim.

```python
# backend/tests/test_attendance_router.py
"""Status codes at the route boundary (spec §9), over real HTTP."""
import os, sys, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.database import get_db
from app.domain import attendance as attendance_domain
from app.main import app
from app.models import AttendancePunch, User
from app.services import attendance as attendance_service
from app.services import auth as auth_service


def _seed_user(db, role="technician"):
    user = User(username=f"u-{uuid.uuid4().hex[:10]}",
                password_hash=auth_service.hash_password("hunter2"), role=role)
    db.add(user); db.flush()
    return user


def _client(db, token):
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    client.cookies.set("session", token)
    return client


def _as(db, user):
    return _client(db, auth_service.create_session(db, user))


def test_me_reports_no_punch_for_a_fresh_user(db):
    user = _seed_user(db); db.commit()
    try:
        with _as(db, user) as client:
            body = client.get("/attendance/me").json()
    finally:
        del app.dependency_overrides[get_db]
    assert body["open_punch"] is None
    assert body["clocked_minutes_today"] == 0


def test_punch_in_then_me_reports_the_open_punch(db):
    user = _seed_user(db); db.commit()
    try:
        with _as(db, user) as client:
            assert client.post("/attendance/punch-in").status_code == 200
            body = client.get("/attendance/me").json()
    finally:
        del app.dependency_overrides[get_db]
    assert body["open_punch"]["start_source"] == "manual"
    assert body["open_punch"]["stale"] is False


def test_a_second_punch_in_is_409(db):
    user = _seed_user(db); db.commit()
    try:
        with _as(db, user) as client:
            client.post("/attendance/punch-in")
            response = client.post("/attendance/punch-in")
    finally:
        del app.dependency_overrides[get_db]
    assert response.status_code == 409
    assert isinstance(response.json()["detail"], str)


def test_punch_out_without_a_punch_is_404(db):
    user = _seed_user(db); db.commit()
    try:
        with _as(db, user) as client:
            response = client.post("/attendance/punch-out")
    finally:
        del app.dependency_overrides[get_db]
    assert response.status_code == 404


def test_self_close_before_the_start_is_400(db):
    user = _seed_user(db)
    started = datetime.now(timezone.utc) - timedelta(days=1)
    db.add(AttendancePunch(user_id=user.id, started_at=started,
                           start_source=attendance_domain.START_SOURCE_MANUAL))
    db.commit()
    try:
        with _as(db, user) as client:
            response = client.post("/attendance/self-close", json={
                "ended_at": (started - timedelta(hours=1)).isoformat()})
    finally:
        del app.dependency_overrides[get_db]
    assert response.status_code == 400


def test_self_close_succeeds_and_flags_needs_review(db):
    user = _seed_user(db)
    started = datetime.now(timezone.utc) - timedelta(days=1, hours=8)
    db.add(AttendancePunch(user_id=user.id, started_at=started,
                           start_source=attendance_domain.START_SOURCE_MANUAL))
    db.commit()
    try:
        with _as(db, user) as client:
            body = client.post("/attendance/self-close", json={
                "ended_at": (started + timedelta(hours=8)).isoformat()}).json()
    finally:
        del app.dependency_overrides[get_db]
    assert body["needs_review"] is True
    assert body["end_source"] == "self_reported"


def test_every_attendance_route_requires_a_session(db):
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            assert client.get("/attendance/me").status_code == 401
            assert client.post("/attendance/punch-in").status_code == 401
    finally:
        del app.dependency_overrides[get_db]
```

- [ ] **Step 2: Run it and watch it fail**

`cd backend && venv/Scripts/python -m pytest tests/test_attendance_router.py -v`
Expected: 404s everywhere — the router is not registered.

- [ ] **Step 3: Write `backend/app/schemas/attendance.py`**

Every model `from_attributes`, matching `schemas/hub.py`'s rule, so the service dataclasses and ORM rows pass straight in.

```python
"""Attendance response contracts.

Layer: schemas. Consumed by `app/routers/attendance.py`. Every model is
`from_attributes`, so a field renamed on either side fails a test instead of
quietly serialising as null -- the rule `schemas/hub.py` set.
"""

import uuid
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


class AttendanceOpenPunch(BaseModel):
    """The caller's open punch. `stale` means it began on an earlier Central
    day, which is what drives the Home tab's self-close prompt (D5)."""

    id: uuid.UUID
    started_at: datetime
    start_source: str
    stale: bool

    model_config = {"from_attributes": True}


class AttendanceMeResponse(BaseModel):
    """`clocked_minutes_today` is the pay number: real wall-clock on shift,
    never rounded to 30 the way `billed_labor_minutes` is (§8)."""

    server_now: datetime
    day: date
    open_punch: Optional[AttendanceOpenPunch] = None
    clocked_minutes_today: int

    model_config = {"from_attributes": True}


class AttendancePunchResponse(BaseModel):
    id: uuid.UUID
    started_at: datetime
    ended_at: Optional[datetime] = None
    start_source: str
    end_source: Optional[str] = None
    needs_review: bool

    model_config = {"from_attributes": True}


class SelfCloseRequest(BaseModel):
    """The instant the technician states they actually left (D5). Required:
    there is no default, because a default would be the estimate D4 exists
    to keep out of a pay record."""

    ended_at: datetime
```

- [ ] **Step 4: Write `backend/app/routers/attendance.py`**

```python
"""HTTP routes for the attendance punch.

Layer: routers (FastAPI). Thin handlers only, mirroring `routers/hub.py`.

Every route here is **self-scoped**: the caller punches their own clock and
reads their own state, so the gate is `get_current_user` with no minimum
role -- an Admin has a shift too. The Admin+ reads and the audited writes are
separate endpoints in later phases (§4).

`GET /attendance/me` is side-effect-free: no sweep, no row locks, unlike
`GET /hub`. That is what will let the live roster poll it safely in P4.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth_deps import get_current_user
from app.database import get_db
from app.domain.errors import DomainError
from app.models import User
from app.routers._errors import to_http
from app.schemas.attendance import (
    AttendanceMeResponse,
    AttendancePunchResponse,
    SelfCloseRequest,
)
from app.services import attendance as attendance_service

router = APIRouter(prefix="/attendance", tags=["attendance"])


@router.get("/me", response_model=AttendanceMeResponse)
def get_attendance_me(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The Home tab's punch state: the open punch (if any) and today's
    clocked minutes."""
    return AttendanceMeResponse.model_validate(
        attendance_service.me_payload(db, user=user)
    )


@router.post("/punch-in", response_model=AttendancePunchResponse)
def punch_in(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Start a shift. 409 when one is already open (D4) -- the client reads
    the blocking punch back from `GET /attendance/me` and offers the
    self-close (D5) when it is stale."""
    try:
        return attendance_service.punch_in(db, user=user)
    except DomainError as exc:
        raise to_http(exc) from exc


@router.post("/punch-out", response_model=AttendancePunchResponse)
def punch_out(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """End the shift, force-stopping any running work-order clock (D3)."""
    try:
        return attendance_service.punch_out(db, user=user)
    except DomainError as exc:
        raise to_http(exc) from exc


@router.post("/self-close", response_model=AttendancePunchResponse)
def self_close(
    payload: SelfCloseRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Close a forgotten punch at a stated time (D5). The result is flagged
    `needs_review` -- an estimate, labelled as one."""
    try:
        return attendance_service.self_close(db, user=user, ended_at=payload.ended_at)
    except DomainError as exc:
        raise to_http(exc) from exc
```

Register it: add `attendance` to the `from app.routers import (` tuple in `main.py:48` (alphabetically first) and `app.include_router(attendance.router)` immediately before `app.include_router(auth.router)` at `main.py:306`.

- [ ] **Step 5: Wire D3's auto-punch-in at the work-order route**

In `backend/app/routers/work_orders.py`, import the service (`from app.services import attendance as attendance_service`) and add one call as the first statement inside `start_work_order_tracking`'s `try`:

```python
    try:
        # D3, one way only: starting a clock off-shift opens a punch, and a
        # stale punch refuses here rather than charging a job against a
        # shift that began two days ago. The coupling lives in
        # `services/attendance.py`, not inside `services/work_orders.py` --
        # attendance knows about labor, labor knows nothing about attendance.
        attendance_service.ensure_punch_for_labor_start(db, user=user)
        work_order = wo_service.start_labor_session(db, work_order_id, user=user)
```

`PunchAlreadyOpenError` inherits `DomainError`, so the existing `except DomainError as exc: raise to_http(exc)` arm already returns the 409 — no new handler.

- [ ] **Step 6: Add the router-level coupling test**

Append to `backend/tests/test_attendance_router.py`:

```python
def test_a_stale_punch_makes_the_work_order_start_a_409(db):
    from app.services import work_orders as wo_service
    admin, tech = _seed_user(db, "admin"), _seed_user(db)
    order = wo_service.get_or_create_work_order(
        db, number=f"WO-ATT-{uuid.uuid4().hex[:8]}", created_by_id=admin.id)
    wo_service.set_work_order_technicians(db, order.id, [tech.id], user=admin)
    db.add(AttendancePunch(user_id=tech.id,
                           started_at=datetime.now(timezone.utc) - timedelta(days=2),
                           start_source=attendance_domain.START_SOURCE_MANUAL))
    db.commit()
    try:
        with _as(db, tech) as client:
            response = client.post(f"/work-orders/{order.id}/tracking/start")
    finally:
        del app.dependency_overrides[get_db]
    assert response.status_code == 409
    assert "Home tab" in response.json()["detail"]


def test_starting_a_work_order_clock_off_shift_opens_a_punch(db):
    from app.services import work_orders as wo_service
    admin, tech = _seed_user(db, "admin"), _seed_user(db)
    order = wo_service.get_or_create_work_order(
        db, number=f"WO-ATT-{uuid.uuid4().hex[:8]}", created_by_id=admin.id)
    wo_service.set_work_order_technicians(db, order.id, [tech.id], user=admin)
    db.commit()
    try:
        with _as(db, tech) as client:
            assert client.post(f"/work-orders/{order.id}/tracking/start").status_code == 200
            body = client.get("/attendance/me").json()
    finally:
        del app.dependency_overrides[get_db]
    assert body["open_punch"]["start_source"] == "auto_work_order"
```

- [ ] **Step 7: Run the whole backend suite**

`cd backend && venv/Scripts/python -m pytest`
Expected: everything passes. `test_route_role_gates.py` is untouched — P1 adds no Admin-floor route, so its expected set still reads `{get_hub_report, export_hub_report}`. A known-environmental failure in `test_cascade_deletes_with_user` on a dev database with real cloud-session rows is not a regression.

- [ ] **Step 8: Commit**

```bash
git add backend/app/schemas/attendance.py backend/app/routers/attendance.py backend/app/main.py backend/app/routers/work_orders.py backend/tests/test_attendance_router.py
git commit -m "feat(attendance): self-scoped punch routes and the D3 auto-punch-in"
```

---

### Task 5: `api.js` wrappers

**Files:**
- Modify: `backend/static/api.js` (new `// --- Attendance ---` section after the Hub section, which ends at `api.js:~600`), `tests/frontend/helpers/endpointTable.js` (after the hub rows, `endpointTable.js:127-133`)
- Test: `tests/frontend/unit/api.endpoints.test.js` (its meta-test, no edit needed)

**Interfaces:**
- Produces: `apiGetAttendanceMe()`, `apiPunchIn()`, `apiPunchOut()`, `apiSelfClosePunch(endedAtIso)`.

- [ ] **Step 1: Add the four rows to `endpointTable.js` first**

The meta-test `has a row for every exported wrapper` fails on a wrapper with no row; adding the rows first makes the failure be about the missing wrapper instead.

```js
  // --- Attendance ---
  { fn: "apiGetAttendanceMe", args: [], url: "/attendance/me", cache: "no-store" },
  { fn: "apiPunchIn", args: [], method: "POST", url: "/attendance/punch-in", body: {} },
  { fn: "apiPunchOut", args: [], method: "POST", url: "/attendance/punch-out", body: {} },
  { fn: "apiSelfClosePunch", args: ["2026-09-21T18:00:00.000Z"], method: "POST",
    url: "/attendance/self-close", body: { ended_at: "2026-09-21T18:00:00.000Z" } },
```

- [ ] **Step 2: Run it and watch it fail**

`npm test -- tests/frontend/unit/api.endpoints.test.js`
Expected: `has no row for a wrapper that no longer exists` fails listing all four names.

- [ ] **Step 3: Add the wrappers**

```js
// --- Attendance ---------------------------------------------------
// The on-shift record, separate from the work-order clock above: these
// four are what a person does with their own shift. The Admin+ reads and
// the audited edits are later phases.
export async function apiGetAttendanceMe() {
  return liveGet("/attendance/me");
}

export async function apiPunchIn() {
  return jsonRequest("/attendance/punch-in", "POST", {});
}

export async function apiPunchOut() {
  return jsonRequest("/attendance/punch-out", "POST", {});
}

// `endedAtIso` is the instant the technician states they actually left --
// required, because a default here would be the estimate D4 keeps out of a
// pay record.
export async function apiSelfClosePunch(endedAtIso) {
  return jsonRequest("/attendance/self-close", "POST", { ended_at: endedAtIso });
}
```

- [ ] **Step 4: Run the tests**

`npm test -- tests/frontend/unit/api.endpoints.test.js`
Expected: pass, four new rows in the sweep.

- [ ] **Step 5: Commit**

```bash
git add backend/static/api.js tests/frontend/helpers/endpointTable.js
git commit -m "feat(attendance): api.js wrappers for the four punch routes"
```

---

### Task 6: `dom.js` gains `promptTime()`

**Files:**
- Modify: `backend/static/shell-tail.html` (new overlay after `#user-role-overlay`, `shell-tail.html:78-92`), `backend/static/dom.js` (append after `promptUserRole`, `dom.js:514`), `backend/static/styles.css`
- Test: `tests/frontend/unit/dom.promptTime.test.js`

**Interfaces:**
- Produces: `promptTime({ title, help, initial }) -> Promise<Date|null>`. `initial` is a `Date`; the resolved `Date` is on the same calendar day as `initial`, with the chosen hour/minute and seconds zeroed. Cancel resolves `null`.

- [ ] **Step 1: Write the failing test**

```js
// tests/frontend/unit/dom.promptTime.test.js
// The dropdown half of promptTime (spec §6). P3 layers the analog dial on
// the same export; these assertions must keep passing when it does.
import { beforeEach, describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { mountView } from "../helpers/shell.js";

let dom;
let user;
beforeEach(async () => {
  user = userEvent.setup({ document });
  dom = await mountView("dom.js");
});

const el = (id) => document.getElementById(id);
const initial = () => new Date(2026, 8, 21, 16, 40);   // Mon 21 Sep 2026, 4:40 PM local

describe("promptTime", () => {
  it("opens on the initial time, split across the three selects", async () => {
    const pending = dom.promptTime({ title: "When did you leave?", initial: initial() });
    expect(el("prompt-time-overlay").hidden).toBe(false);
    expect(el("prompt-time-title").textContent).toBe("When did you leave?");
    expect(el("prompt-time-hour").value).toBe("4");
    expect(el("prompt-time-minute").value).toBe("40");
    expect(el("prompt-time-meridiem").value).toBe("PM");
    await user.click(el("prompt-time-cancel"));
    await expect(pending).resolves.toBeNull();
  });

  it("resolves the chosen time on the initial's own calendar day", async () => {
    const pending = dom.promptTime({ initial: initial() });
    await user.selectOptions(el("prompt-time-hour"), "9");
    await user.selectOptions(el("prompt-time-minute"), "05");
    await user.selectOptions(el("prompt-time-meridiem"), "AM");
    await user.click(el("prompt-time-save"));
    const chosen = await pending;
    expect(chosen.getFullYear()).toBe(2026);
    expect(chosen.getMonth()).toBe(8);
    expect(chosen.getDate()).toBe(21);
    expect(chosen.getHours()).toBe(9);
    expect(chosen.getMinutes()).toBe(5);
    expect(chosen.getSeconds()).toBe(0);
  });

  it.each([[-15, "4", "25", "PM"], [-5, "4", "35", "PM"], [5, "4", "45", "PM"], [15, "4", "55", "PM"]])(
    "the %i nudge moves the selects",
    async (delta, hour, minute, meridiem) => {
      const pending = dom.promptTime({ initial: initial() });
      await user.click(document.querySelector(`[data-nudge="${delta}"]`));
      expect(el("prompt-time-hour").value).toBe(hour);
      expect(el("prompt-time-minute").value).toBe(minute);
      expect(el("prompt-time-meridiem").value).toBe(meridiem);
      await user.click(el("prompt-time-cancel"));
      await pending;
    });

  it("a nudge across noon flips the meridiem", async () => {
    const pending = dom.promptTime({ initial: new Date(2026, 8, 21, 11, 55) });
    await user.click(document.querySelector('[data-nudge="15"]'));
    expect(el("prompt-time-hour").value).toBe("12");
    expect(el("prompt-time-minute").value).toBe("10");
    expect(el("prompt-time-meridiem").value).toBe("PM");
    await user.click(el("prompt-time-cancel"));
    await pending;
  });

  it("a nudge never leaves the initial's calendar day", async () => {
    const pending = dom.promptTime({ initial: new Date(2026, 8, 21, 0, 5) });
    await user.click(document.querySelector('[data-nudge="-15"]'));
    expect(el("prompt-time-hour").value).toBe("12");
    expect(el("prompt-time-minute").value).toBe("00");
    expect(el("prompt-time-meridiem").value).toBe("AM");
    await user.click(el("prompt-time-save"));
    const chosen = await pending;
    expect(chosen.getDate()).toBe(21);
  });

  it("Escape cancels", async () => {
    const pending = dom.promptTime({ initial: initial() });
    await user.keyboard("{Escape}");
    await expect(pending).resolves.toBeNull();
    expect(el("prompt-time-overlay").hidden).toBe(true);
  });

  it("emits no inline style attribute -- CSP drops them", () => {
    const pending = dom.promptTime({ initial: initial() });
    expect(el("prompt-time-overlay").querySelectorAll("[style]")).toHaveLength(0);
    el("prompt-time-cancel").click();
    return pending;
  });

  it("nests no button inside a button", () => {
    const pending = dom.promptTime({ initial: initial() });
    el("prompt-time-overlay").querySelectorAll("button").forEach((btn) => {
      expect(btn.querySelector("button")).toBeNull();
    });
    el("prompt-time-cancel").click();
    return pending;
  });
});
```

- [ ] **Step 2: Run it and watch it fail**

`npm test -- tests/frontend/unit/dom.promptTime.test.js`
Expected: `dom.promptTime is not a function`.

- [ ] **Step 3: Add the overlay markup**

Insert into `backend/static/shell-tail.html` directly after `#user-role-overlay`'s closing `</div>`:

```html
    <!-- Time picker (dom.js promptTime). Dropdowns plus a nudge row; P3
         layers an analog dial over the same state. Complete and
         keyboard-accessible without the dial, which is why it ships first. -->
    <div id="prompt-time-overlay" class="modal-overlay" hidden>
        <div class="modal-box" role="dialog" aria-modal="true" aria-labelledby="prompt-time-title">
            <p id="prompt-time-title" class="modal-title">Pick a time</p>
            <p id="prompt-time-help" class="hint"></p>
            <div class="prompt-time-fields">
                <label for="prompt-time-hour" class="sr-only">Hour</label>
                <select id="prompt-time-hour"></select>
                <span aria-hidden="true">:</span>
                <label for="prompt-time-minute" class="sr-only">Minute</label>
                <select id="prompt-time-minute"></select>
                <label for="prompt-time-meridiem" class="sr-only">AM or PM</label>
                <select id="prompt-time-meridiem">
                    <option value="AM">AM</option>
                    <option value="PM">PM</option>
                </select>
            </div>
            <div class="prompt-time-nudge">
                <button type="button" class="secondary-btn" data-nudge="-15">&minus;15</button>
                <button type="button" class="secondary-btn" data-nudge="-5">&minus;5</button>
                <button type="button" class="secondary-btn" data-nudge="5">+5</button>
                <button type="button" class="secondary-btn" data-nudge="15">+15</button>
            </div>
            <p id="prompt-time-message" aria-live="polite"></p>
            <div class="modal-buttons">
                <button id="prompt-time-save">Save time</button>
                <button id="prompt-time-cancel" type="button" class="secondary-btn">Cancel</button>
            </div>
        </div>
    </div>
```

- [ ] **Step 4: Write `promptTime` in `dom.js`**

Follow `promptUserRole`'s exact shape: module-scope element lookups, a `Promise` with `cleanup()` / `done()` / focus restore / Escape / Tab-trap. Minute options are every minute `00`–`59` (the dropdown accepts any minute; only P3's dial snaps to 5).

```js
// --- Time picker ------------------------------------------------------
//
// Two callers earn this a place beside confirmDialog and promptUserRole
// rather than a home inside one view: the technician's D5 self-close prompt
// (P1) and the Admin punch edit (P3).
//
// Resolves a Date on `initial`'s own calendar day. A shift is picked, not
// dated -- the day comes from the punch being corrected, and letting a
// nudge roll past midnight would silently move a punch to another day and
// another timesheet row.
const promptTimeOverlay = document.getElementById("prompt-time-overlay");
const promptTimeTitle = document.getElementById("prompt-time-title");
const promptTimeHelp = document.getElementById("prompt-time-help");
const promptTimeHour = document.getElementById("prompt-time-hour");
const promptTimeMinute = document.getElementById("prompt-time-minute");
const promptTimeMeridiem = document.getElementById("prompt-time-meridiem");
const promptTimeMessage = document.getElementById("prompt-time-message");
const promptTimeSave = document.getElementById("prompt-time-save");
const promptTimeCancel = document.getElementById("prompt-time-cancel");

const MINUTES_IN_DAY = 24 * 60;

function fillTimeOptions() {
  if (promptTimeHour.options.length) return;   // idempotent across calls
  for (let h = 1; h <= 12; h += 1) {
    const option = document.createElement("option");
    option.value = String(h);
    option.textContent = String(h);
    promptTimeHour.appendChild(option);
  }
  for (let m = 0; m < 60; m += 1) {
    const option = document.createElement("option");
    option.value = String(m).padStart(2, "0");
    option.textContent = String(m).padStart(2, "0");
    promptTimeMinute.appendChild(option);
  }
}

function readPromptTimeMinutes() {
  const hour12 = Number(promptTimeHour.value) % 12;
  const hour24 = promptTimeMeridiem.value === "PM" ? hour12 + 12 : hour12;
  return hour24 * 60 + Number(promptTimeMinute.value);
}

function writePromptTimeMinutes(totalMinutes) {
  // Clamped, not wrapped: see the module comment above.
  const clamped = Math.min(MINUTES_IN_DAY - 1, Math.max(0, totalMinutes));
  const hour24 = Math.floor(clamped / 60);
  promptTimeHour.value = String(hour24 % 12 || 12);
  promptTimeMinute.value = String(clamped % 60).padStart(2, "0");
  promptTimeMeridiem.value = hour24 >= 12 ? "PM" : "AM";
}

export function promptTime({ title = "Pick a time", help = "", initial = new Date() } = {}) {
  return new Promise((resolve) => {
    if (!promptTimeOverlay) {
      resolve(null);
      return;
    }
    const previouslyFocused = document.activeElement;
    const focusables = [promptTimeHour, promptTimeMinute, promptTimeMeridiem,
                        promptTimeSave, promptTimeCancel];
    const day = new Date(initial.getFullYear(), initial.getMonth(), initial.getDate());

    fillTimeOptions();
    promptTimeTitle.textContent = title;
    promptTimeHelp.textContent = help;
    writePromptTimeMinutes(initial.getHours() * 60 + initial.getMinutes());
    setMessage(promptTimeMessage, "", "");
    promptTimeOverlay.hidden = false;
    promptTimeHour.focus();

    const nudgeRow = promptTimeOverlay.querySelector(".prompt-time-nudge");

    function onNudge(event) {
      const btn = event.target.closest("[data-nudge]");
      if (!btn) return;
      writePromptTimeMinutes(readPromptTimeMinutes() + Number(btn.dataset.nudge));
    }
    function cleanup() {
      promptTimeSave.removeEventListener("click", onSave);
      promptTimeCancel.removeEventListener("click", onCancel);
      nudgeRow.removeEventListener("click", onNudge);
      promptTimeOverlay.removeEventListener("click", onBackdrop);
      document.removeEventListener("keydown", onKey);
    }
    function done(value) {
      promptTimeOverlay.hidden = true;
      cleanup();
      if (previouslyFocused && typeof previouslyFocused.focus === "function") {
        try { previouslyFocused.focus(); } catch (_err) { /* element removed */ }
      }
      resolve(value);
    }
    function onSave() {
      const chosen = new Date(day);
      chosen.setHours(0, readPromptTimeMinutes(), 0, 0);
      done(chosen);
    }
    function onCancel() { done(null); }
    function onBackdrop(event) { if (event.target === promptTimeOverlay) done(null); }
    function onKey(event) {
      if (event.key === "Escape") { done(null); return; }
      if (event.key === "Enter" && focusables.slice(0, 3).includes(event.target)) {
        event.preventDefault();
        onSave();
        return;
      }
      if (event.key === "Tab") {
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault(); last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault(); first.focus();
        }
      }
    }

    promptTimeSave.addEventListener("click", onSave);
    promptTimeCancel.addEventListener("click", onCancel);
    nudgeRow.addEventListener("click", onNudge);
    promptTimeOverlay.addEventListener("click", onBackdrop);
    document.addEventListener("keydown", onKey);
  });
}
```

`chosen.setHours(0, minutes, 0, 0)` is deliberate: setting the minute field past 59 is how a single call carries both components without a second rounding step.

- [ ] **Step 5: Add the CSS**

Append beside the other modal rules in `backend/static/styles.css` (near `.modal-overlay`, `styles.css:3193`):

```css
.prompt-time-fields {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    margin: var(--space-3) 0;
}

.prompt-time-fields select {
    min-width: 72px;
}

.prompt-time-nudge {
    display: flex;
    gap: var(--space-2);
    margin-bottom: var(--space-3);
}

.prompt-time-nudge button {
    flex: 1;
    min-width: 0;
}
```

- [ ] **Step 6: Run the tests**

`npm test -- tests/frontend/unit/dom.promptTime.test.js tests/frontend/unit/dom.prompts.test.js tests/frontend/helpers/shell.test.js`
Expected: all pass. The shell test proves the new fragment still assembles.

- [ ] **Step 7: Commit**

```bash
git add backend/static/shell-tail.html backend/static/dom.js backend/static/styles.css tests/frontend/unit/dom.promptTime.test.js
git commit -m "feat(dom): promptTime() dropdown picker with a nudge row"
```

---

### Task 7: The Home tab

**Files:**
- Create: `backend/static/views/hubHome.js`, `tests/frontend/views/hubHome.test.js`
- Modify: `backend/static/pages/user-hub.html`, `backend/static/views/userHub.js`, `backend/static/styles.css`, `tests/frontend/helpers/hub.js`, `tests/frontend/helpers/factories.js`, `tests/frontend/views/userHub.test.js`
- Test: `tests/frontend/views/hubHome.test.js`, plus the existing `hubClock.test.js` and `userHub.test.js`

**Interfaces:**
- Consumes: Task 5's `apiGetAttendanceMe` / `apiPunchIn` / `apiPunchOut` / `apiSelfClosePunch`; Task 6's `promptTime`.
- Produces: `mountHubHome(mountEl, hubPayload, attendance, { onChanged })` from `views/hubHome.js`. `attendance` is the `GET /attendance/me` body or `null` (failed fetch); `onChanged` is awaited after every successful punch write.
- Produces: `attendanceMe(overrides)` factory in `tests/frontend/helpers/factories.js`.

- [ ] **Step 1: Write the failing test**

```js
// tests/frontend/views/hubHome.test.js
// The Home tab: the punch hero, the relocated quick-start clock, and the D5
// self-close prompt. The work-order clock's own behaviour stays in
// hubClock.test.js; this file only proves it landed here.
import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { requestFor, clearRequests } from "../helpers/requests.js";
import { el, openHub, restoreHub, stopClock } from "../helpers/hub.js";
import { attendanceMe, hubPayload } from "../helpers/factories.js";

afterEach(() => {
  stopClock();
  expect(vi.getTimerCount()).toBe(0);
  restoreHub();
});

const user = () => userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
const punch = () => el.panel("home").querySelector(".hub-punch");

describe("the Home tab is the hub's first tab", () => {
  it("is active on load and holds the clock widget", async () => {
    await openHub({ role: "technician" });
    expect(el.tab("home").classList.contains("active")).toBe(true);
    expect(el.panel("home").hidden).toBe(false);
    expect(el.panel("home").contains(el.clockMount())).toBe(true);
  });

  it("is where an Admin lands too -- the widget is no longer at the bottom", async () => {
    await openHub({ role: "admin" });
    expect(el.panel("home").contains(el.clockMount())).toBe(true);
  });
});

describe("off shift", () => {
  it("offers Punch in and reports today's clocked total", async () => {
    await openHub({ role: "technician",
      attendance: attendanceMe({ clocked_minutes_today: 95 }) });
    expect(punch().classList.contains("hub-punch-off")).toBe(true);
    expect(punch().querySelector(".hub-punch-today").textContent).toContain("1 h 35 m");
    expect(punch().querySelector('[data-action="hub-punch-in"]')).not.toBeNull();
  });

  it("punches in and refreshes", async () => {
    await openHub({ role: "technician", attendance: attendanceMe() });
    clearRequests();
    await user().click(punch().querySelector('[data-action="hub-punch-in"]'));
    expect(requestFor("/attendance/punch-in").method).toBe("POST");
  });
});

describe("on shift", () => {
  it("shows the elapsed hero and offers Punch out", async () => {
    const payload = hubPayload();
    await openHub({ role: "technician", hub: payload,
      attendance: attendanceMe({
        server_now: payload.server_now,
        open_punch: { id: "p1", started_at: "2026-09-10T10:00:00Z",
                      start_source: "manual", stale: false },
      }) });
    expect(punch().classList.contains("hub-punch-on")).toBe(true);
    expect(punch().querySelector(".hub-punch-hero").textContent).toBe("2 h 0 m");
    expect(punch().querySelector('[data-action="hub-punch-out"]')).not.toBeNull();
  });

  it("punches out at the wire", async () => {
    await openHub({ role: "technician",
      attendance: attendanceMe({ open_punch: { id: "p1",
        started_at: "2026-09-10T10:00:00Z", start_source: "manual", stale: false } }) });
    clearRequests();
    await user().click(punch().querySelector('[data-action="hub-punch-out"]'));
    expect(requestFor("/attendance/punch-out").method).toBe("POST");
  });
});

describe("a stale punch (D5)", () => {
  it("replaces the punch buttons with Close it", async () => {
    await openHub({ role: "technician",
      attendance: attendanceMe({ open_punch: { id: "p1",
        started_at: "2026-09-09T13:00:00Z", start_source: "manual", stale: true } }) });
    expect(punch().classList.contains("hub-punch-stale")).toBe(true);
    expect(punch().querySelector('[data-action="hub-punch-out"]')).toBeNull();
    expect(punch().querySelector('[data-action="hub-punch-self-close"]')).not.toBeNull();
  });

  it("sends the time the prompt returned, on the punch's own day", async () => {
    await openHub({ role: "technician",
      attendance: attendanceMe({ open_punch: { id: "p1",
        started_at: "2026-09-09T13:00:00Z", start_source: "manual", stale: true } }) });
    clearRequests();
    const typist = user();
    await typist.click(punch().querySelector('[data-action="hub-punch-self-close"]'));
    await typist.selectOptions(document.getElementById("prompt-time-meridiem"), "PM");
    await typist.selectOptions(document.getElementById("prompt-time-hour"), "5");
    await typist.selectOptions(document.getElementById("prompt-time-minute"), "30");
    await typist.click(document.getElementById("prompt-time-save"));
    const sent = JSON.parse(requestFor("/attendance/self-close").body);
    const endedAt = new Date(sent.ended_at);
    expect(endedAt.getHours()).toBe(17);
    expect(endedAt.getMinutes()).toBe(30);
    // The punch's own local calendar day, not today's.
    expect(endedAt.getDate()).toBe(new Date("2026-09-09T13:00:00Z").getDate());
  });

  it("cancelling the prompt sends nothing", async () => {
    await openHub({ role: "technician",
      attendance: attendanceMe({ open_punch: { id: "p1",
        started_at: "2026-09-09T13:00:00Z", start_source: "manual", stale: true } }) });
    clearRequests();
    const typist = user();
    await typist.click(punch().querySelector('[data-action="hub-punch-self-close"]'));
    await typist.click(document.getElementById("prompt-time-cancel"));
    expect(() => requestFor("/attendance/self-close")).toThrow();
  });
});

describe("a failed attendance fetch", () => {
  it("renders a retry inside the punch card rather than blanking Home", async () => {
    await openHub({ role: "technician",
      handlers: [http.get("/attendance/me", () => HttpResponse.json({ detail: "" }, { status: 500 }))] });
    expect(punch().querySelector(".hub-punch-retry")).not.toBeNull();
    // The work-order clock still mounted -- the two are independent.
    expect(el.clockMount().querySelector(".hub-clock")).not.toBeNull();
  });
});

it("emits no inline style attribute -- CSP drops them", async () => {
  await openHub({ role: "technician", attendance: attendanceMe() });
  expect(el.panel("home").querySelectorAll("[style]")).toHaveLength(0);
});
```

`requestFor` may not throw on a miss — check `tests/frontend/helpers/requests.js` and use whatever its miss behaviour is (`expect(requests().some(...)).toBe(false)` if it returns undefined).

- [ ] **Step 2: Extend the fixtures, then run it and watch it fail**

Add to `tests/frontend/helpers/factories.js`, beside `hubPayload`:

```js
// --- Attendance (backend/app/schemas/attendance.py) -------------------------
// `clocked_minutes_today` is the pay number -- real wall-clock, never the
// 30-minute-rounded billed figure.
export function attendanceMe(overrides = {}) {
  return {
    server_now: "2026-09-10T12:00:00Z",
    day: "2026-09-10",
    open_punch: null,
    clocked_minutes_today: 0,
    ...overrides,
  };
}
```

In `tests/frontend/helpers/hub.js`: import `attendanceMe`, add `attendance = null` to `mountHub`'s options, and register the handler **before** the bare `/hub` route (MSW takes the first match):

```js
    http.get("/attendance/me", () => answer(attendance ?? attendanceMe())),
    http.post("/attendance/punch-in", () => HttpResponse.json({})),
    http.post("/attendance/punch-out", () => HttpResponse.json({})),
    http.post("/attendance/self-close", () => HttpResponse.json({})),
```

`el.panel(name)` resolves by id, so the `el` map needs no new entry.

`npm test -- tests/frontend/views/hubHome.test.js`
Expected: `el.tab("home")` is null — the markup does not exist.

- [ ] **Step 3: Add the Home tab markup**

In `backend/static/pages/user-hub.html`, make Home the first tab button and the first panel, and drop `#hub-clock-mount` from its position above the tabs (the Home panel hosts it now):

```html
        <nav id="hub-tabs" class="hub-tabs" aria-label="User hub sections" role="tablist">
            <button type="button" class="hub-tab active" id="hub-tab-home" data-hub-tab="home" aria-controls="hub-tabpanel-home" aria-selected="true" role="tab">Home</button>
            <button type="button" class="hub-tab" id="hub-tab-dashboard" data-hub-tab="dashboard" aria-controls="hub-tabpanel-dashboard" aria-selected="false" role="tab">Dashboard</button>
            ... (timesheets / work-orders / graphs / report unchanged, all aria-selected="false") ...
        </nav>

        <div class="hub-tabpanel active" id="hub-tabpanel-home" role="tabpanel" aria-labelledby="hub-tab-home"></div>
        <div class="hub-tabpanel" id="hub-tabpanel-dashboard" role="tabpanel" aria-labelledby="hub-tab-dashboard" hidden></div>
        ... (the rest unchanged) ...

        <!-- The persistent work-order clock. Lives outside the tabpanels so
             its node survives a Home re-render; userHub.js reparents it into
             #hub-home-clock-slot on every Home render, which is what keeps
             hubClock.js's state and wiring intact (the trick placeClockMount
             used to move it for Admins). -->
        <section id="hub-clock-mount" aria-live="polite" hidden></section>
```

Remove `class="active"` and set `aria-selected="false"` on the Dashboard button; drop its `hidden`-less panel's `active` class and add `hidden`. Update the page's opening comment to say the clock mount is reparented into Home.

- [ ] **Step 4: Write `backend/static/views/hubHome.js`**

```js
// View: the User Hub's Home tab -- the hub's first tab and the app's landing
// surface.
//
// Layer: views. Two independent blocks, deliberately not merged: the
// attendance punch (am I at work?) and the work-order clock (what am I
// charging?). Blurring them is the single most likely way this feature ships
// subtly wrong -- see the spec's Time Semantics section.
//
// The clock is not rendered here. userHub.js reparents the existing
// `#hub-clock-mount` node into `#hub-home-clock-slot` after every render, so
// hubClock.js keeps its own state and wiring.

import { apiPunchIn, apiPunchOut, apiSelfClosePunch } from "../api.js";
import { escapeHtml, formatHm, friendlyError } from "../format.js";
import { promptTime, setMessage } from "../dom.js";

let container = null;
let hub = null;
let attendance = null;
let skewMs = 0;
let refreshCallback = null;

function nowWithSkew() {
  return Date.now() + skewMs;
}

function punchElapsedMinutes() {
  if (!attendance?.open_punch) return 0;
  return (nowWithSkew() - new Date(attendance.open_punch.started_at).getTime()) / 60000;
}

function shortTime(iso) {
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function shortDay(iso) {
  return new Date(iso).toLocaleDateString([], { weekday: "long" });
}

function errorPunchHtml() {
  return `
    <section class="hub-punch hub-punch-error">
      <p class="hub-punch-status">Could not load your shift.</p>
      <button type="button" class="secondary-btn hub-punch-retry" data-action="hub-punch-retry">Retry</button>
    </section>`;
}

// D5: a punch left open from an earlier day. No auto-close (D4), so the only
// way forward is the technician stating when they actually left -- flagged
// for an Admin rather than guessed at.
function stalePunchHtml() {
  const punch = attendance.open_punch;
  return `
    <section class="hub-punch hub-punch-on hub-punch-stale">
      <p class="hub-punch-status">⚠ Still punched in from ${escapeHtml(shortDay(punch.started_at))}, ${escapeHtml(shortTime(punch.started_at))}</p>
      <p class="hub-punch-note">Tell us when you actually left. A supervisor will check it.</p>
      <button type="button" class="hub-punch-btn" data-action="hub-punch-self-close">Close it</button>
      <p class="hub-punch-message" id="hub-punch-message"></p>
    </section>`;
}

function onShiftHtml() {
  const punch = attendance.open_punch;
  return `
    <section class="hub-punch hub-punch-on">
      <p class="hub-punch-status"><span class="hub-punch-dot"></span> ON SHIFT</p>
      <div class="hub-punch-row">
        <div>
          <p class="hub-punch-hero">${escapeHtml(formatHm(punchElapsedMinutes()))}</p>
          <p class="hub-punch-started">punched in ${escapeHtml(shortTime(punch.started_at))}</p>
        </div>
        <button type="button" class="hub-punch-btn" data-action="hub-punch-out">Punch out</button>
      </div>
      <p class="hub-punch-message" id="hub-punch-message"></p>
    </section>`;
}

function offShiftHtml() {
  return `
    <section class="hub-punch hub-punch-off">
      <p class="hub-punch-status">○ Not punched in</p>
      <div class="hub-punch-row">
        <p class="hub-punch-today">Today <strong>${escapeHtml(formatHm(attendance.clocked_minutes_today))}</strong></p>
        <button type="button" class="hub-punch-btn" data-action="hub-punch-in">Punch in</button>
      </div>
      <p class="hub-punch-message" id="hub-punch-message"></p>
    </section>`;
}

function punchHtml() {
  if (!attendance) return errorPunchHtml();
  if (!attendance.open_punch) return offShiftHtml();
  return attendance.open_punch.stale ? stalePunchHtml() : onShiftHtml();
}

// Today's own numbers, the same three the Dashboard tab leads with -- Home
// answers "what is in front of me" without a tab switch.
function countsHtml() {
  const counts = hub.counts;
  return `
    <div class="hub-tile-grid">
      <section class="hub-tile"><p class="hub-tile-label">Assigned to me</p><p class="hub-tile-value">${escapeHtml(String(counts.assigned))}</p><p class="hub-tile-sub">work orders</p></section>
      <section class="hub-tile"><p class="hub-tile-label">In progress</p><p class="hub-tile-value">${escapeHtml(String(counts.in_progress))}</p></section>
      <section class="hub-tile"><p class="hub-tile-label">Ready to complete</p><p class="hub-tile-value">${escapeHtml(String(counts.ready_to_complete))}</p></section>
    </div>`;
}

async function run(action, message) {
  const status = document.getElementById("hub-punch-message");
  try {
    await action();
  } catch (err) {
    setMessage(status, friendlyError(err, message), "error");
    return;
  }
  if (refreshCallback) await refreshCallback();
}

async function handleSelfClose() {
  const punch = attendance?.open_punch;
  if (!punch) return;
  // The prompt opens on the punch's OWN day, not today: a Date built from
  // `started_at` carries that day, and promptTime never leaves it.
  const chosen = await promptTime({
    title: "When did you leave?",
    help: `You punched in ${shortDay(punch.started_at)} at ${shortTime(punch.started_at)}.`,
    initial: new Date(punch.started_at),
  });
  if (!chosen) return;
  await run(() => apiSelfClosePunch(chosen.toISOString()), "Could not close that shift.");
}

export function mountHubHome(mountEl, hubPayload, attendancePayload, { onChanged } = {}) {
  container = mountEl;
  hub = hubPayload;
  attendance = attendancePayload;
  skewMs = new Date(hubPayload.server_now).getTime() - Date.now();
  refreshCallback = onChanged || null;

  container.innerHTML = `
    ${punchHtml()}
    <div id="hub-home-clock-slot"></div>
    ${countsHtml()}`;

  if (!container.dataset.wired) {
    container.dataset.wired = "1";
    container.addEventListener("click", (event) => {
      const action = event.target.closest("[data-action]")?.dataset.action;
      if (action === "hub-punch-in") void run(apiPunchIn, "Could not punch in.");
      else if (action === "hub-punch-out") void run(apiPunchOut, "Could not punch out.");
      else if (action === "hub-punch-self-close") void handleSelfClose();
      else if (action === "hub-punch-retry" && refreshCallback) void refreshCallback();
    });
  }
}
```

The punch hero does not tick. `mountHubClock`'s 1-second interval already repaints beside it, and a second interval on the same panel is a timer the `afterEach` zero-timer check would have to chase for a figure that changes once a minute. If the elapsed figure must tick, add it in P2 by reading `punchElapsedMinutes()` from `hubClock.js`'s existing tick.

- [ ] **Step 5: Wire it in `userHub.js`**

1. Import: `import { apiGetAttendanceMe } from "../api.js";` (add to the existing api import list) and `import { mountHubHome } from "./hubHome.js";`.
2. Add `home: document.getElementById("hub-tabpanel-home")` as the **first** entry of `tabPanels`.
3. `let activeTab = "home";` and `let latestAttendance = null;`.
4. Delete `placeClockMount` and its call; delete the `hubTabsNav` const if nothing else uses it. Unhide the clock mount in `renderHome` instead.
5. Add `renderHome` and call it from `renderActiveTab`'s new first arm:

```js
// The clock node is reparented, not re-rendered: moving it preserves
// hubClock.js's state and its delegated listener (the property
// placeClockMount relied on when it moved the widget for Admins).
function renderHome() {
  if (!latestPayload) return;
  mountHubHome(tabPanels.home, latestPayload, latestAttendance, { onChanged: refreshUserHub });
  const slot = tabPanels.home.querySelector("#hub-home-clock-slot");
  if (slot) {
    clockMount.hidden = false;
    slot.appendChild(clockMount);
  }
  mountHubClock(clockMount, latestPayload, { onChanged: refreshUserHub });
}
```

```js
function renderActiveTab() {
  if (activeTab === "home") {
    renderHome();
  } else if (activeTab === "dashboard") {
    ...
```

6. In `loadUserHub`, fetch attendance beside the hub payload and stop calling `mountHubClock` directly (`renderHome` owns it now):

```js
  // Every role has a shift, Admin included. A failure is not fatal to the
  // page: hubHome renders a retry inside the punch card and the work-order
  // clock beside it still mounts.
  try {
    latestAttendance = await apiGetAttendanceMe();
  } catch (_err) {
    latestAttendance = null;
  }
```

Place it after the `apiGetHub` block and before `showTab(activeTab)`. Replace the `placeClockMount(canViewAdminTiles); mountHubClock(clockMount, ...);` pair with nothing — `showTab` reaches `renderHome`.

7. On a user change, reset to Home: `if (userChanged) activeTab = "home";` and clear `latestAttendance = null;` in the same block.
8. Add `home` to the `tabButtons` click handler's existing pass-through (no change needed — it reads `dataset.hubTab`).

- [ ] **Step 6: Add the CSS**

Append after the `.hub-clock-*` block in `backend/static/styles.css` (around `styles.css:2162`). Reuse the clock's own scale so the two blocks read as siblings:

```css
/* The attendance punch on the Home tab. Deliberately shaped like the clock
   widget beside it -- same hero, same row -- because they are the same kind
   of statement about two different clocks. */
.hub-punch {
    margin-bottom: var(--space-4);
}

.hub-punch-status {
    font-weight: var(--fw-semibold);
    display: flex;
    align-items: center;
    gap: var(--space-2);
}

.hub-punch-on .hub-punch-status {
    color: var(--color-success);
}

.hub-punch-stale .hub-punch-status {
    color: var(--color-error);
}

.hub-punch-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background-color: var(--color-success);
    display: inline-block;
}

.hub-punch-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-4);
    margin-top: var(--space-3);
}

.hub-punch-hero {
    font-size: 2.5rem;
    line-height: 1.1;
    margin: 0;
}

.hub-punch-started,
.hub-punch-today,
.hub-punch-note {
    color: var(--text-panel-mute);
    margin: 0;
}

.hub-punch-btn {
    min-width: 96px;
}

.hub-punch-stale .hub-punch-btn {
    margin-top: var(--space-3);
}

.hub-punch-message:empty {
    display: none;
}
```

- [ ] **Step 7: Run the frontend suite**

`npm test`
Expected: `hubHome.test.js` passes. `hubClock.test.js` should pass unchanged — `el.clockMount()` resolves by id wherever the node sits, and Home is the active tab on load. `userHub.test.js` will need its default-tab and tab-order assertions updated; fix them to expect `home` rather than weakening them. Re-run until green.

- [ ] **Step 8: Commit**

```bash
git add backend/static/pages/user-hub.html backend/static/views/hubHome.js backend/static/views/userHub.js backend/static/styles.css tests/frontend/views/hubHome.test.js tests/frontend/helpers/hub.js tests/frontend/helpers/factories.js tests/frontend/views/userHub.test.js
git commit -m "feat(hub): Home tab with the attendance punch and the relocated quick-start clock"
```

---

### Task 8: Docs

**Files:**
- Modify: `docs/endpoint-map.md`, `docs/current-state.md`, `docs/open-work.md`

Living docs are current-truth only (CLAUDE.md → Documentation conventions). State what is true now; delete nothing that is still true; add no history.

- [ ] **Step 1: Add the four endpoint rows**

In `docs/endpoint-map.md`'s Master Endpoint Index, after the `H7` row, add an `A1`–`A4` block in the table's exact column order (`# | Method | Path | Gate | Router → Service | Tables | api.js wrapper | View(s)`):

| # | Method | Path | Gate | Router → Service | Tables | api.js wrapper | View(s) |
|---|---|---|---|---|---|---|---|
| A1 | GET | `/attendance/me` | any authenticated | `attendance.py` → `attendance.me_payload` → `labor_day.overlap_minutes` | attendance_punches (r) | `apiGetAttendanceMe` | `userHub.js`, `hubHome.js` |
| A2 | POST | `/attendance/punch-in` | any authenticated | `attendance.py` → `attendance.punch_in` | attendance_punches (r/w) | `apiPunchIn` | `hubHome.js` |
| A3 | POST | `/attendance/punch-out` | any authenticated | `attendance.py` → `attendance.punch_out` → `work_orders.stop_labor_session` | attendance_punches (r/w), work_order_labor_sessions (r/w), work_order_labor (w), work_orders (r; row lock) | `apiPunchOut` | `hubHome.js` |
| A4 | POST | `/attendance/self-close` | any authenticated | `attendance.py` → `attendance.self_close` | attendance_punches (r/w) | `apiSelfClosePunch` | `hubHome.js` |

Also amend the `POST /work-orders/{id}/tracking/start` row's service chain to lead with `attendance.ensure_punch_for_labor_start` and its Tables cell to include `attendance_punches (r/w)`. Add a one-line error note where the file catalogs error behavior: 409 from A2 and from tracking/start means an open (A2) or stale (tracking/start) punch; 404 from A3/A4 means no open punch; 400 from A4 means the stated time is invalid.

- [ ] **Step 2: Add the data model and invariants to `current-state.md`**

Add `attendance_punches` and `attendance_punch_edits` to the data-model section in the shape the neighbouring tables use. Add three invariants, one line each:

- One open punch per person, enforced by `uq_attendance_punches_open_user` (partial, `ended_at IS NULL`) — not by a service check.
- Nothing auto-closes a punch (D4). A punch open from an earlier Central day is *stale* (`domain.attendance.is_stale`) and blocks a work-order clock start until the technician self-closes it (`end_source=self_reported`, `needs_review=true`).
- Clocked ≠ tracked ≠ billed. Clocked comes from `attendance_punches` and is never rounded to 30 minutes.

- [ ] **Step 3: File the P2–P4 follow-ups in `open-work.md`**

One item, in the file's existing item format, naming: the Timesheets sub-nav + Hours grid (P2); `promptTime`'s analog dial and the Admin edit / add / delete with audit rows (P3); Charged vs clocked, the live roster, the `attendance.changed` envelope, the CSV export, and the `GET /hub/timesheets` retirement with its `test_route_role_gates.py` amendment (P4). Add the decision-D deferral by name: a shared self-close prompt on the work-order card, so a technician blocked there does not have to reach the Home tab.

- [ ] **Step 4: Verify and commit**

Re-read each edited section against the budgets in the file headers (`current-state.md` 16,500 · `endpoint-map.md` 11,000 · `open-work.md` 12,000); compress phrasing before dropping a fact. The `docs/` → Obsidian mirror runs automatically at turn end — do not sync by hand.

```bash
git add docs/endpoint-map.md docs/current-state.md docs/open-work.md
git commit -m "docs(attendance): P1 endpoints, punch invariants, and the P2-P4 backlog"
```

---

## Final verification

- [ ] `cd backend && venv/Scripts/python -m pytest` — green (the known environmental `test_cascade_deletes_with_user` failure on a dev DB with real cloud-session rows is not a regression).
- [ ] `npm test` from the repo root — green.
- [ ] `cd backend && venv/Scripts/python -m alembic upgrade head` then `downgrade -1` then `upgrade head` — both directions run.
- [ ] Manual check by the owner (the user validates manually; do not start the preview server): Home is the hub's first tab for every role; Punch in → hero ticks up beside the work-order clock; Track WO with no punch opens one; Punch out stops a running WO clock; a punch seeded a day back offers **Close it** and the picker sends that punch's own day.
