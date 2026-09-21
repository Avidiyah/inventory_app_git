# Attendance P3 — the Admin punch edit, add, delete, and its audit

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an Admin correct the pay record from the Hours drill-down — edit a punch's times, add a missing punch, delete a wrong one, and clear a `needs_review` flag — with every write recorded in `attendance_punch_edits`.

**Architecture:** Three audited writes in `services/attendance.py` beside the existing punch writes, exposed as `POST` / `PATCH` / `DELETE /hub/attendance/punches` at the Admin floor in `routers/hub.py`. A punch is **soft**-deleted (`deleted_at`), because `attendance_punch_edits.punch_id` is `ON DELETE CASCADE` — a hard delete would erase the audit trail of the one write that most needs one. The drill-down gains an inline editor (`views/hubAttendancePunchEditor.js`) that reuses P1's `promptTime()` for each instant; `hubAttendanceHours.js` stays a pure view and `hubTimesheetsTab.js` owns the calls and the refetch.

**Tech Stack:** FastAPI + SQLAlchemy + Pydantic v2 + Alembic (backend), pytest (backend tests), vanilla ES modules + Vitest/MSW/jsdom (frontend).

**Spec:** `docs/superpowers/specs/2026-09-21-attendance-timesheet-design.md` — D2 (a day is a list of punches), §1 (audit table), §4 (endpoints), §6 (frontend), §9 (validation), §10 (testing), §11 (phasing). P2's plan, for shape and conventions: `docs/superpowers/plans/2026-09-21-attendance-p2-hours-grid.md`.

## Global Constraints

- **Five decisions taken at planning time, overriding the spec where they differ:**
  1. **No analog dial.** `promptTime()`'s dropdowns + nudge row shipped in P1 and are complete and keyboard-accessible; §6's dial is cut from P3 and logged in `open-work.md` instead. `dom.js` is **not** modified by this plan.
  2. **`reason` is an optional free-text field.** Blank is allowed; the audit row records who / when / field / old / new regardless.
  3. **Any admin write clears `needs_review`, and a separate "Looks right" clears it alone.** Both write audit rows.
  4. **No `⚠ charged outside shift` badge.** §9's advisory needs labor-session data the week payload does not carry until P4; the edit is still never refused. Deferred to P4.
  5. **Delete is soft** — `deleted_at` on `attendance_punches`, filtered out of every read.
- **Clocked only (§8).** Nothing in this phase reads `labor_summary` or `billed_labor_minutes`.
- **Admin floor**, `roles.ROLE_ADMIN`, not `ROLE_TECHFM_OA` (D1). `test_route_role_gates.py::test_no_route_gate_is_left_at_the_admin_floor`'s expected set grows to `{get_hub_report, export_hub_report, get_hub_attendance_week, add_hub_attendance_punch, edit_hub_attendance_punch, delete_hub_attendance_punch}`, with the reason written into the test.
- **D6 does not land here.** `GET /hub/timesheets` stays live and Supervisor-floored; the Timesheets *tab* stays supervisor+, only **Hours** is admin+. The retirement is P4.
- **The grid does not subscribe.** After a successful write the tab refetches the week (§6: "refetch after an edit, so an Admin correcting punches is not fighting a repaint"). `attendance.changed` is P4.
- **A `carried` punch row gets no buttons** (§9): a cross-midnight punch is owned by the day it started, and is editable only there.
- **CSP drops `style=`** — classes only in every template literal. **No nested buttons** — the drill-down's edit controls are siblings of the cell button, never inside it.
- **Files stay under 500 lines.** `hubAttendanceHours.js` is 202 and the editor lives in its own module to keep it that way. `dom.js` is 643 (pre-existing, untouched here).
- **Commit trailer:** every commit ends with `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.

---

## File Structure

| File | Responsibility |
|---|---|
| **Create** `backend/alembic/versions/c4a6e8b0d2f5_add_attendance_punch_deleted_at.py` | `deleted_at` column; the open-punch partial unique index rebuilt to `ended_at IS NULL AND deleted_at IS NULL`. |
| **Modify** `backend/app/models.py:620-655` | `deleted_at` column + the docstring line that says a delete is soft. |
| **Modify** `backend/app/services/attendance.py` | `live_punches()` base query; the three audited writes and the `_audit` helper. |
| **Modify** `backend/app/services/attendance_week.py:112-170` | Both queries filter `deleted_at IS NULL`. |
| **Modify** `backend/app/domain/errors.py:164-169` | `NoChangeError`'s docstring gains its second caller. |
| **Modify** `backend/app/schemas/attendance.py` | `PunchAddRequest`, `PunchEditRequest`. |
| **Modify** `backend/app/routers/hub.py` | The three Admin-floored write routes. |
| **Modify** `backend/tests/test_route_role_gates.py:530-545` | The amended Admin-floor expected set + a named pin. |
| **Create** `backend/tests/test_attendance_admin_service.py` | Add / edit / delete, audit rows, overlap, soft-delete invisibility. |
| **Create** `backend/tests/test_attendance_admin_router.py` | §9's status codes over real HTTP. |
| **Modify** `backend/static/api.js` | `apiAddAttendancePunch`, `apiEditAttendancePunch`, `apiDeleteAttendancePunch`. |
| **Modify** `tests/frontend/helpers/endpointTable.js` | Their wire-contract rows. |
| **Create** `backend/static/views/hubAttendancePunchEditor.js` | The inline editor row: two time buttons driving `promptTime()`, an optional reason input, Save / Delete / Cancel. Payload in, callbacks out; no fetch. |
| **Modify** `backend/static/views/hubAttendanceHours.js` | `[Edit]` / `[Looks right]` per punch row, `[+ Add punch]` per day, mounting the editor; new `onSavePunch` / `onAddPunch` / `onDeletePunch` / `onClearReview` callbacks. |
| **Modify** `backend/static/views/hubTimesheetsTab.js` | Wire those callbacks to the api wrappers and refetch the week. |
| **Modify** `backend/static/styles.css` | Editor row chrome. |
| **Create** `tests/frontend/views/hubAttendancePunchEditor.test.js` | Time buttons, reason, save/cancel/delete payloads. |
| **Modify** `tests/frontend/views/hubAttendanceHours.test.js` | Buttons present / withheld, editor mount, callback payloads. |
| **Modify** `tests/frontend/views/hubTimesheetsTab.test.js` | Write → refetch, and the error path. |
| **Modify** `docs/endpoint-map.md`, `docs/current-state.md`, `docs/open-work.md` | Three rows, one block, the IMP-041 trim. |

---

### Task 1: Soft delete — column, index, and every read path

**Files:**
- Create: `backend/alembic/versions/c4a6e8b0d2f5_add_attendance_punch_deleted_at.py`
- Modify: `backend/app/models.py:620-655`, `backend/app/services/attendance.py`, `backend/app/services/attendance_week.py`
- Test: `backend/tests/test_attendance_admin_service.py`

**Interfaces:**
- Produces: `AttendancePunch.deleted_at: Optional[datetime]`; `attendance.live_punches(db) -> Query[AttendancePunch]` — the base query every read path uses.

- [x] **Step 1: Write the failing test**

```python
# backend/tests/test_attendance_admin_service.py
"""The Admin's audited punch writes (spec D2, §1, §9).

A soft-deleted punch is gone for every purpose except the audit trail: the
partial unique index must not count it, and no read may return it.
"""
import os, sys, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone

from app.models import AttendancePunch, User
from app.services import attendance as attendance_service
from app.services import auth as auth_service


def _seed_user(db, role="technician"):
    user = User(username=f"u-{uuid.uuid4().hex[:10]}",
                password_hash=auth_service.hash_password("hunter2"), role=role)
    db.add(user); db.flush()
    return user


def test_a_soft_deleted_open_punch_does_not_block_a_new_punch_in(db):
    # The partial unique index is the reason this is a real risk: if it still
    # counted the deleted row, the insert would raise IntegrityError and the
    # person could never clock in again.
    user = _seed_user(db)
    now = datetime.now(timezone.utc)
    stale = AttendancePunch(id=uuid.uuid4(), user_id=user.id,
                            started_at=now - timedelta(hours=30),
                            start_source="manual", deleted_at=now)
    db.add(stale); db.commit()

    punch = attendance_service.punch_in(db, user=user, now=now)

    assert punch.ended_at is None
    assert attendance_service.open_punch_for(db, user.id).id == punch.id
```

- [x] **Step 2: Run it and watch it fail**

Run: `cd backend && python -m pytest tests/test_attendance_admin_service.py -v`
Expected: FAIL — `TypeError: 'deleted_at' is an invalid keyword argument for AttendancePunch`.

- [x] **Step 3: Add the column to the model**

In `backend/app/models.py`, inside `AttendancePunch`, after `created_at`:

```python
    # Soft delete (P3). `attendance_punch_edits.punch_id` is ON DELETE
    # CASCADE, so a hard delete would erase the audit trail of the very
    # write that most needs one -- a pay record vanishing with no record
    # that it existed. Every read filters this; only the audit sees it.
    deleted_at = Column(DateTime(timezone=True), nullable=True)
```

And amend the index tuple:

```python
    __table_args__ = (
        Index("ix_attendance_punches_user_started", "user_id", "started_at"),
        Index("uq_attendance_punches_open_user", "user_id",
              unique=True,
              postgresql_where=text("ended_at IS NULL AND deleted_at IS NULL")),
    )
```

- [x] **Step 4: Write the migration**

```python
# backend/alembic/versions/c4a6e8b0d2f5_add_attendance_punch_deleted_at.py
"""add attendance_punches.deleted_at

Revision ID: c4a6e8b0d2f5
Revises: b7d9f1a3c5e8
Create Date: 2026-09-21 18:00:00.000000

P3's delete is soft. `b7d9f1a3c5e8` reasoned that a deleted punch's own
deletion would be recorded "against the punch that is going away" -- which
the CASCADE then removes, leaving no trace of a deleted pay record. A
`deleted_at` keeps the row and its audit and makes a wrong delete a one-line
undo rather than a restore from backup.

The open-punch index is rebuilt rather than added to: a soft-deleted open
punch must not occupy the one open slot a person has.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c4a6e8b0d2f5"
down_revision: Union[str, Sequence[str], None] = "b7d9f1a3c5e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("attendance_punches",
                  sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.drop_index("uq_attendance_punches_open_user", table_name="attendance_punches")
    op.create_index(
        "uq_attendance_punches_open_user",
        "attendance_punches",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL AND deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_attendance_punches_open_user", table_name="attendance_punches")
    op.create_index(
        "uq_attendance_punches_open_user",
        "attendance_punches",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
    )
    op.drop_column("attendance_punches", "deleted_at")
```

- [x] **Step 5: Filter every read path**

In `backend/app/services/attendance.py`, add above `open_punch_for`:

```python
def live_punches(db: Session):
    """The base query for every read. A soft-deleted punch is gone for every
    purpose except the audit trail -- so this, not `db.query`, is what any
    new punch read starts from."""
    return db.query(AttendancePunch).filter(AttendancePunch.deleted_at.is_(None))
```

Rewrite `open_punch_for`'s body to `return live_punches(db).filter(...).first()` and `me_payload`'s `db.query(AttendancePunch)` to `live_punches(db)`, both keeping their existing filters.

In `backend/app/services/attendance_week.py`, add `AttendancePunch.deleted_at.is_(None),` as the first filter of **both** the `_population` `punched_ids` query and `week_payload`'s punch query.

- [x] **Step 6: Run the migration and the suite**

Run: `cd backend && alembic upgrade head && python -m pytest tests/test_attendance_admin_service.py tests/test_attendance_service.py tests/test_attendance_week_service.py -v`
Expected: PASS, all of them.

- [x] **Step 7: Commit**

```bash
git add backend/alembic/versions/c4a6e8b0d2f5_add_attendance_punch_deleted_at.py backend/app/models.py backend/app/services/attendance.py backend/app/services/attendance_week.py backend/tests/test_attendance_admin_service.py
git commit -m "feat(attendance): soft-delete a punch so its audit survives"
```

---

### Task 2: The three audited writes

**Files:**
- Modify: `backend/app/services/attendance.py`, `backend/app/domain/errors.py:164-169`
- Test: `backend/tests/test_attendance_admin_service.py`

**Interfaces:**
- Consumes: `live_punches` (Task 1); `domain.attendance.validate_punch_window`, `find_overlap`, `END_SOURCE_ADMIN_EDIT`.
- Produces:
  - `admin_add_punch(db, *, actor: User, user_id: uuid.UUID, started_at, ended_at, reason=None, now=None) -> AttendancePunch`
  - `admin_edit_punch(db, *, actor: User, punch_id, started_at=None, ended_at=None, needs_review=None, reason=None, now=None) -> AttendancePunch` — `None` means *unchanged*, never *clear*.
  - `admin_delete_punch(db, *, actor: User, punch_id, reason=None, now=None) -> AttendancePunch`

- [x] **Step 1: Write the failing tests**

Append to `backend/tests/test_attendance_admin_service.py`:

```python
from app.domain.errors import (NoChangeError, PunchNotFoundError,
                               PunchOverlapError, PunchTimeInvalidError)
from app.models import AttendancePunchEdit
import pytest


def _punch(db, user, *, start_h, end_h, now, needs_review=False):
    punch = AttendancePunch(
        id=uuid.uuid4(), user_id=user.id,
        started_at=now.replace(hour=start_h, minute=0, second=0, microsecond=0),
        ended_at=now.replace(hour=end_h, minute=0, second=0, microsecond=0),
        start_source="manual", end_source="manual", needs_review=needs_review)
    db.add(punch); db.flush()
    return punch


def test_add_writes_the_punch_and_one_created_audit_row(db):
    admin, tech = _seed_user(db, "admin"), _seed_user(db)
    now = datetime.now(timezone.utc)
    db.commit()

    punch = attendance_service.admin_add_punch(
        db, actor=admin, user_id=tech.id,
        started_at=now - timedelta(hours=4), ended_at=now - timedelta(hours=1),
        reason="forgot to clock in", now=now)

    rows = db.query(AttendancePunchEdit).filter_by(punch_id=punch.id).all()
    assert punch.end_source == "admin_edit"
    assert [r.field for r in rows] == ["created"]
    assert rows[0].edited_by_id == admin.id
    assert rows[0].old_value is None and rows[0].reason == "forgot to clock in"


def test_edit_writes_one_row_per_changed_field_and_clears_needs_review(db):
    admin, tech = _seed_user(db, "admin"), _seed_user(db)
    now = datetime.now(timezone.utc)
    punch = _punch(db, tech, start_h=8, end_h=15, now=now, needs_review=True)
    db.commit()
    new_end = punch.ended_at - timedelta(hours=1)

    attendance_service.admin_edit_punch(
        db, actor=admin, punch_id=punch.id, ended_at=new_end, now=now)

    fields = sorted(r.field for r in
                    db.query(AttendancePunchEdit).filter_by(punch_id=punch.id).all())
    assert fields == ["ended_at", "needs_review"]
    assert punch.needs_review is False and punch.end_source == "admin_edit"


def test_clearing_the_flag_alone_is_a_legal_edit(db):
    admin, tech = _seed_user(db, "admin"), _seed_user(db)
    now = datetime.now(timezone.utc)
    punch = _punch(db, tech, start_h=8, end_h=15, now=now, needs_review=True)
    db.commit()

    attendance_service.admin_edit_punch(
        db, actor=admin, punch_id=punch.id, needs_review=False, now=now)

    assert punch.needs_review is False
    assert punch.ended_at == now.replace(hour=15, minute=0, second=0, microsecond=0)


def test_an_edit_that_changes_nothing_is_refused(db):
    admin, tech = _seed_user(db, "admin"), _seed_user(db)
    now = datetime.now(timezone.utc)
    punch = _punch(db, tech, start_h=8, end_h=15, now=now)
    db.commit()
    with pytest.raises(NoChangeError):
        attendance_service.admin_edit_punch(db, actor=admin, punch_id=punch.id, now=now)


def test_an_edit_overlapping_another_punch_names_the_conflict(db):
    admin, tech = _seed_user(db, "admin"), _seed_user(db)
    now = datetime.now(timezone.utc)
    morning = _punch(db, tech, start_h=8, end_h=11, now=now)
    afternoon = _punch(db, tech, start_h=13, end_h=17, now=now)
    db.commit()
    with pytest.raises(PunchOverlapError) as caught:
        attendance_service.admin_edit_punch(
            db, actor=admin, punch_id=afternoon.id,
            started_at=morning.ended_at - timedelta(minutes=30), now=now)
    assert caught.value.punch_id == morning.id


def test_a_punch_may_not_be_reopened(db):
    admin, tech = _seed_user(db, "admin"), _seed_user(db)
    now = datetime.now(timezone.utc)
    punch = _punch(db, tech, start_h=8, end_h=15, now=now)
    db.commit()
    with pytest.raises(PunchTimeInvalidError):
        attendance_service.admin_edit_punch(
            db, actor=admin, punch_id=punch.id,
            started_at=punch.started_at + timedelta(hours=8), now=now)


def test_delete_is_soft_keeps_the_audit_and_hides_the_row(db):
    admin, tech = _seed_user(db, "admin"), _seed_user(db)
    now = datetime.now(timezone.utc)
    punch = _punch(db, tech, start_h=8, end_h=15, now=now)
    db.commit()

    attendance_service.admin_delete_punch(
        db, actor=admin, punch_id=punch.id, reason="duplicate", now=now)

    rows = db.query(AttendancePunchEdit).filter_by(punch_id=punch.id).all()
    assert [r.field for r in rows] == ["deleted"]
    assert rows[0].new_value is None and rows[0].old_value.startswith("20")
    assert punch.deleted_at is not None
    assert attendance_service.live_punches(db).filter_by(id=punch.id).first() is None


def test_a_deleted_punch_cannot_be_edited(db):
    admin, tech = _seed_user(db, "admin"), _seed_user(db)
    now = datetime.now(timezone.utc)
    punch = _punch(db, tech, start_h=8, end_h=15, now=now)
    db.commit()
    attendance_service.admin_delete_punch(db, actor=admin, punch_id=punch.id, now=now)
    with pytest.raises(PunchNotFoundError):
        attendance_service.admin_edit_punch(
            db, actor=admin, punch_id=punch.id, needs_review=False, now=now)
```

- [x] **Step 2: Run them and watch them fail**

Run: `cd backend && python -m pytest tests/test_attendance_admin_service.py -v`
Expected: FAIL — `AttributeError: module 'app.services.attendance' has no attribute 'admin_add_punch'`.

- [x] **Step 3: Implement the writes**

Append to `backend/app/services/attendance.py` (add `AttendancePunchEdit` to the `app.models` import, and `NoChangeError`, `PunchOverlapError`, `PunchTimeInvalidError` to the `app.domain.errors` import — `PunchNotFoundError` is already there):

```python
# --- The Admin's audited writes (D2, §1) ---------------------------------
#
# Every one of these writes `attendance_punch_edits` in the same transaction
# as the change: an unaudited correction to a pay record is the thing the
# table exists to make impossible. One row per field, values as text.


def _stamp(instant: Optional[datetime]) -> Optional[str]:
    return None if instant is None else labor_day.as_utc(instant).isoformat()


def _audit(db: Session, *, punch: AttendancePunch, actor: User, field: str,
           old: Optional[str], new: Optional[str], reason: Optional[str],
           now: datetime) -> None:
    db.add(AttendancePunchEdit(
        id=uuid.uuid4(), punch_id=punch.id, edited_by_id=actor.id,
        edited_at=now, field=field, old_value=old, new_value=new,
        reason=(reason or None)))


def _assert_no_overlap(db: Session, *, user_id: uuid.UUID, punch_id,
                       started_at: datetime, ended_at: Optional[datetime],
                       now: datetime) -> None:
    others = [
        (row.id, row.started_at, row.ended_at)
        for row in live_punches(db).filter(AttendancePunch.user_id == user_id).all()
        if row.id != punch_id
    ]
    clash = attendance.find_overlap(started_at, ended_at, others, now=now)
    if clash is not None:
        raise PunchOverlapError(
            "That overlaps another punch for this person.", punch_id=clash)


def _live_punch(db: Session, punch_id) -> AttendancePunch:
    punch = live_punches(db).filter(AttendancePunch.id == punch_id).first()
    if punch is None:
        raise PunchNotFoundError("That punch no longer exists.")
    return punch


def admin_add_punch(db: Session, *, actor: User, user_id: uuid.UUID,
                    started_at: datetime, ended_at: datetime,
                    reason: Optional[str] = None,
                    now: Optional[datetime] = None) -> AttendancePunch:
    """D2: a day is a list of punches, so an Admin can add one that was never
    clocked. Closed only -- an open punch is something a person is living
    through, not a record an Admin writes on their behalf, and the partial
    unique index would fight a second one anyway."""
    now = now or datetime.now(timezone.utc)
    if db.query(User).filter(User.id == user_id).first() is None:
        raise PunchNotFoundError("That person no longer exists.")
    attendance.validate_punch_window(started_at, ended_at, now=now)
    _assert_no_overlap(db, user_id=user_id, punch_id=None,
                       started_at=started_at, ended_at=ended_at, now=now)
    punch = AttendancePunch(
        id=uuid.uuid4(), user_id=user_id,
        started_at=labor_day.as_utc(started_at), ended_at=labor_day.as_utc(ended_at),
        start_source=attendance.START_SOURCE_MANUAL,
        end_source=attendance.END_SOURCE_ADMIN_EDIT)
    db.add(punch)
    db.flush()
    _audit(db, punch=punch, actor=actor, field="created", old=None,
           new=f"{_stamp(started_at)}/{_stamp(ended_at)}", reason=reason, now=now)
    db.commit()
    db.refresh(punch)
    return punch


def admin_edit_punch(db: Session, *, actor: User, punch_id,
                     started_at: Optional[datetime] = None,
                     ended_at: Optional[datetime] = None,
                     needs_review: Optional[bool] = None,
                     reason: Optional[str] = None,
                     now: Optional[datetime] = None) -> AttendancePunch:
    """Correct a punch. `None` means *unchanged*, never *clear*: clearing
    `ended_at` would re-open a shift somebody already left, and the open-punch
    index would then fight whatever they are living through today.

    Any change clears `needs_review` -- an Admin who has looked at a
    self-reported time has reviewed it. Passing `needs_review=False` alone is
    the "Looks right" action: reviewed, nothing to correct.
    """
    now = now or datetime.now(timezone.utc)
    punch = _live_punch(db, punch_id)
    new_start = labor_day.as_utc(started_at) if started_at is not None else punch.started_at
    new_end = labor_day.as_utc(ended_at) if ended_at is not None else punch.ended_at
    if punch.ended_at is not None and new_end is None:
        raise PunchTimeInvalidError("A closed punch cannot be re-opened.")
    attendance.validate_punch_window(new_start, new_end, now=now)
    _assert_no_overlap(db, user_id=punch.user_id, punch_id=punch.id,
                       started_at=new_start, ended_at=new_end, now=now)

    changes: list[tuple[str, Optional[str], Optional[str]]] = []
    if new_start != punch.started_at:
        changes.append(("started_at", _stamp(punch.started_at), _stamp(new_start)))
    if new_end != punch.ended_at:
        changes.append(("ended_at", _stamp(punch.ended_at), _stamp(new_end)))
    clearing = punch.needs_review and (needs_review is False or changes)
    if clearing:
        changes.append(("needs_review", "true", "false"))
    if not changes:
        raise NoChangeError("Nothing about that punch changed.")

    punch.started_at, punch.ended_at = new_start, new_end
    if any(field == "ended_at" for field, _old, _new in changes):
        punch.end_source = attendance.END_SOURCE_ADMIN_EDIT
    if clearing:
        punch.needs_review = False
    for field, old, new in changes:
        _audit(db, punch=punch, actor=actor, field=field, old=old, new=new,
               reason=reason, now=now)
    db.commit()
    db.refresh(punch)
    return punch


def admin_delete_punch(db: Session, *, actor: User, punch_id,
                       reason: Optional[str] = None,
                       now: Optional[datetime] = None) -> AttendancePunch:
    """Soft: the row and its audit stay, every read stops seeing it. A pay
    record that vanishes without a trace is exactly what §1's audit table is
    for, and `punch_id` is ON DELETE CASCADE."""
    now = now or datetime.now(timezone.utc)
    punch = _live_punch(db, punch_id)
    punch.deleted_at = now
    _audit(db, punch=punch, actor=actor, field="deleted",
           old=f"{_stamp(punch.started_at)}/{_stamp(punch.ended_at)}", new=None,
           reason=reason, now=now)
    db.commit()
    db.refresh(punch)
    return punch
```

Then extend `NoChangeError`'s docstring in `backend/app/domain/errors.py` with:

```python
    Also raised by `services.attendance.admin_edit_punch` when an edit
    changes no field: the same empty-audit-row problem, in the table where
    an empty row is worst.
```

- [x] **Step 4: Run the tests**

Run: `cd backend && python -m pytest tests/test_attendance_admin_service.py -v`
Expected: PASS (8 tests).

- [x] **Step 5: Commit**

```bash
git add backend/app/services/attendance.py backend/app/domain/errors.py backend/tests/test_attendance_admin_service.py
git commit -m "feat(attendance): audited admin add, edit, and delete of a punch"
```

---

### Task 3: The routes and the Admin floor

**Files:**
- Modify: `backend/app/schemas/attendance.py`, `backend/app/routers/hub.py`, `backend/tests/test_route_role_gates.py:530-545`
- Test: `backend/tests/test_attendance_admin_router.py`

**Interfaces:**
- Consumes: Task 2's three service functions.
- Produces: `POST /hub/attendance/punches` (`add_hub_attendance_punch`), `PATCH /hub/attendance/punches/{punch_id}` (`edit_hub_attendance_punch`), `DELETE /hub/attendance/punches/{punch_id}?reason=` (`delete_hub_attendance_punch`) — all returning `AttendancePunchResponse`, all `roles.ROLE_ADMIN`.

- [x] **Step 1: Write the failing tests**

```python
# backend/tests/test_attendance_admin_router.py
"""Status codes for the Admin punch writes (spec §9), over real HTTP.

TestClient, never a direct handler call: this repo has been bitten once by
FastAPI parsing a signature differently than a direct call does.
"""
import os, sys, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import AttendancePunch, User
from app.services import auth as auth_service


def _seed_user(db, role="technician"):
    user = User(username=f"u-{uuid.uuid4().hex[:10]}",
                password_hash=auth_service.hash_password("hunter2"), role=role)
    db.add(user); db.flush()
    return user


def _as(db, user):
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    client.cookies.set("session", auth_service.create_session(db, user))
    return client


def _punch(db, user, *, hours_ago, length_hours=3):
    now = datetime.now(timezone.utc)
    punch = AttendancePunch(
        id=uuid.uuid4(), user_id=user.id,
        started_at=now - timedelta(hours=hours_ago),
        ended_at=now - timedelta(hours=hours_ago - length_hours),
        start_source="manual", end_source="manual")
    db.add(punch); db.flush()
    return punch


def test_an_admin_adds_a_punch(db):
    admin, tech = _seed_user(db, "admin"), _seed_user(db); db.commit()
    now = datetime.now(timezone.utc)
    body = {"user_id": str(tech.id),
            "started_at": (now - timedelta(hours=5)).isoformat(),
            "ended_at": (now - timedelta(hours=2)).isoformat(),
            "reason": "paper timesheet"}
    try:
        with _as(db, admin) as client:
            response = client.post("/hub/attendance/punches", json=body)
    finally:
        del app.dependency_overrides[get_db]
    assert response.status_code == 200
    assert response.json()["end_source"] == "admin_edit"


def test_techfm_oa_is_refused(db):
    oa, tech = _seed_user(db, "techfm_oa"), _seed_user(db)
    punch = _punch(db, tech, hours_ago=6); db.commit()
    try:
        with _as(db, oa) as client:
            response = client.patch(f"/hub/attendance/punches/{punch.id}",
                                    json={"needs_review": False})
    finally:
        del app.dependency_overrides[get_db]
    assert response.status_code == 403


def test_a_future_end_is_400(db):
    admin, tech = _seed_user(db, "admin"), _seed_user(db)
    punch = _punch(db, tech, hours_ago=6); db.commit()
    ahead = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    try:
        with _as(db, admin) as client:
            response = client.patch(f"/hub/attendance/punches/{punch.id}",
                                    json={"ended_at": ahead})
    finally:
        del app.dependency_overrides[get_db]
    assert response.status_code == 400


def test_an_overlap_is_409(db):
    admin, tech = _seed_user(db, "admin"), _seed_user(db)
    first = _punch(db, tech, hours_ago=9)
    second = _punch(db, tech, hours_ago=4); db.commit()
    try:
        with _as(db, admin) as client:
            response = client.patch(
                f"/hub/attendance/punches/{second.id}",
                json={"started_at": (first.ended_at - timedelta(minutes=30)).isoformat()})
    finally:
        del app.dependency_overrides[get_db]
    assert response.status_code == 409


def test_an_unknown_punch_is_404(db):
    admin = _seed_user(db, "admin"); db.commit()
    try:
        with _as(db, admin) as client:
            response = client.delete(f"/hub/attendance/punches/{uuid.uuid4()}")
    finally:
        del app.dependency_overrides[get_db]
    assert response.status_code == 404


def test_delete_then_the_week_no_longer_shows_it(db):
    admin, tech = _seed_user(db, "admin"), _seed_user(db)
    punch = _punch(db, tech, hours_ago=5); db.commit()
    try:
        with _as(db, admin) as client:
            assert client.delete(
                f"/hub/attendance/punches/{punch.id}?reason=duplicate").status_code == 200
            week = client.get("/hub/attendance/week").json()
    finally:
        del app.dependency_overrides[get_db]
    ids = [entry["id"] for row in week["rows"] for day in row["days"]
           for entry in day["punches"]]
    assert str(punch.id) not in ids
```

- [x] **Step 2: Run them and watch them fail**

Run: `cd backend && python -m pytest tests/test_attendance_admin_router.py -v`
Expected: FAIL — 405/404 from FastAPI; the routes do not exist.

- [x] **Step 3: Add the request schemas**

Append to `backend/app/schemas/attendance.py`:

```python
class PunchAddRequest(BaseModel):
    """D2's `+ Add punch`. Closed only: `ended_at` is required, because an
    open punch is something a person is living through, not a record an
    Admin writes for them. `reason` is optional -- the audit row is written
    either way (who / when / field / old / new)."""

    user_id: uuid.UUID
    started_at: datetime
    ended_at: datetime
    reason: Optional[str] = None


class PunchEditRequest(BaseModel):
    """An omitted field means **unchanged**, never *clear*. `needs_review`
    only ever arrives as `false`: alone it is the "Looks right" action, and
    nothing but a D5 self-close may raise the flag."""

    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    needs_review: Optional[bool] = None
    reason: Optional[str] = None
```

- [x] **Step 4: Add the routes**

In `backend/app/routers/hub.py`, directly after `get_hub_attendance_week` (import `PunchAddRequest`, `PunchEditRequest`, `AttendancePunchResponse` from `app.schemas.attendance` and `attendance as attendance_service` from `app.services`):

```python
# The audited writes behind the Hours drill-down (D2, §1). Admin floor, same
# grounds as the week read: this is the pay record. Every one of them writes
# `attendance_punch_edits` in the same transaction as the change.


@router.post("/attendance/punches", response_model=AttendancePunchResponse)
def add_hub_attendance_punch(
    payload: PunchAddRequest,
    user: User = Depends(require_min_role(roles.ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """Add a punch nobody clocked. 400 on a bad window, 409 on an overlap."""
    try:
        return attendance_service.admin_add_punch(
            db, actor=user, user_id=payload.user_id,
            started_at=payload.started_at, ended_at=payload.ended_at,
            reason=payload.reason)
    except DomainError as exc:
        raise to_http(exc) from exc


@router.patch("/attendance/punches/{punch_id}", response_model=AttendancePunchResponse)
def edit_hub_attendance_punch(
    punch_id: uuid.UUID,
    payload: PunchEditRequest,
    user: User = Depends(require_min_role(roles.ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """Correct a punch, or clear its `needs_review` flag alone. An edit that
    changes nothing is a 400, not a silent empty audit row."""
    try:
        return attendance_service.admin_edit_punch(
            db, actor=user, punch_id=punch_id,
            started_at=payload.started_at, ended_at=payload.ended_at,
            needs_review=payload.needs_review, reason=payload.reason)
    except DomainError as exc:
        raise to_http(exc) from exc


@router.delete("/attendance/punches/{punch_id}", response_model=AttendancePunchResponse)
def delete_hub_attendance_punch(
    punch_id: uuid.UUID,
    reason: Optional[str] = Query(None),
    user: User = Depends(require_min_role(roles.ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """Soft delete: the row leaves every read and keeps its audit. `reason`
    rides the query string -- a DELETE body is not reliably carried."""
    try:
        return attendance_service.admin_delete_punch(
            db, actor=user, punch_id=punch_id, reason=reason)
    except DomainError as exc:
        raise to_http(exc) from exc
```

Add `import uuid` to the module imports if it is not already there.

- [x] **Step 5: Amend the role-gate test**

In `backend/tests/test_route_role_gates.py`, extend the expected set and the comment above it:

```python
    # P3's three audited writes join on the same grounds as the week read:
    # they *are* the pay record. P4 adds `get_hub_attendance_live` and
    # `export_hub_attendance`.
    assert offenders == {
        "get_hub_report",
        "export_hub_report",
        "get_hub_attendance_week",
        "add_hub_attendance_punch",
        "edit_hub_attendance_punch",
        "delete_hub_attendance_punch",
    }
```

And append a named pin beside `test_the_attendance_week_sits_above_techfm_oa`:

```python
@pytest.mark.parametrize(
    "endpoint_name",
    ["add_hub_attendance_punch", "edit_hub_attendance_punch",
     "delete_hub_attendance_punch"],
)
def test_the_punch_writes_sit_above_techfm_oa(endpoint_name):
    # Writing somebody's paid hours is the narrowest capability in the app.
    assert _min_role_for(hub_router, endpoint_name) == roles.ROLE_ADMIN
```

- [x] **Step 6: Run the backend suite**

Run: `cd backend && python -m pytest tests/test_attendance_admin_router.py tests/test_route_role_gates.py tests/test_attendance_week_router.py -v`
Expected: PASS.

- [x] **Step 7: Commit**

```bash
git add backend/app/schemas/attendance.py backend/app/routers/hub.py backend/tests/test_attendance_admin_router.py backend/tests/test_route_role_gates.py
git commit -m "feat(attendance): the Admin punch write routes at the Admin floor"
```

---

### Task 4: The api.js wrappers

**Files:**
- Modify: `backend/static/api.js:650-660`, `tests/frontend/helpers/endpointTable.js:137-142`
- Test: `tests/frontend/unit/api.endpoints.test.js` (driven by the table; no new file)

**Interfaces:**
- Produces: `apiAddAttendancePunch({ userId, startedAt, endedAt, reason })`, `apiEditAttendancePunch(punchId, { startedAt, endedAt, needsReview, reason })`, `apiDeleteAttendancePunch(punchId, reason)` — all resolving to the punch object.

- [x] **Step 1: Add the table rows (the failing test)**

In `tests/frontend/helpers/endpointTable.js`, after the `apiGetHubAttendanceWeek` row:

```js
  { fn: "apiAddAttendancePunch",
    args: [{ userId: "11111111-1111-4111-8111-111111111111",
             startedAt: "2026-09-21T13:00:00.000Z",
             endedAt: "2026-09-21T21:00:00.000Z", reason: "paper timesheet" }],
    method: "POST", url: "/hub/attendance/punches",
    body: { user_id: "11111111-1111-4111-8111-111111111111",
            started_at: "2026-09-21T13:00:00.000Z",
            ended_at: "2026-09-21T21:00:00.000Z", reason: "paper timesheet" } },
  { fn: "apiEditAttendancePunch",
    args: ["22222222-2222-4222-8222-222222222222",
           { endedAt: "2026-09-21T21:00:00.000Z" }],
    method: "PATCH",
    url: "/hub/attendance/punches/22222222-2222-4222-8222-222222222222",
    body: { ended_at: "2026-09-21T21:00:00.000Z" } },
  { fn: "apiDeleteAttendancePunch",
    args: ["22222222-2222-4222-8222-222222222222", "duplicate"],
    method: "DELETE",
    url: "/hub/attendance/punches/22222222-2222-4222-8222-222222222222?reason=duplicate" },
```

- [x] **Step 2: Run it and watch it fail**

Run: `npx vitest run tests/frontend/unit/api.endpoints.test.js`
Expected: FAIL — `apiAddAttendancePunch is not a function`.

- [x] **Step 3: Write the wrappers**

In `backend/static/api.js`, after `apiGetHubAttendanceWeek`:

```js
// The Admin punch writes (Admin only). Each one is audited server-side, so
// the UI never has to prove anything about who changed what.
//
// An omitted key means **unchanged** -- the PATCH body carries only what the
// editor actually touched, so a saved start time cannot quietly re-send a
// stale end time from a payload rendered a minute ago.
export async function apiAddAttendancePunch({ userId, startedAt, endedAt, reason = "" } = {}) {
  const body = { user_id: userId, started_at: startedAt, ended_at: endedAt };
  if (reason) body.reason = reason;
  return jsonRequest("/hub/attendance/punches", "POST", body);
}

export async function apiEditAttendancePunch(punchId, { startedAt, endedAt, needsReview, reason = "" } = {}) {
  const body = {};
  if (startedAt) body.started_at = startedAt;
  if (endedAt) body.ended_at = endedAt;
  if (needsReview === false) body.needs_review = false;
  if (reason) body.reason = reason;
  return jsonRequest(`/hub/attendance/punches/${encodeURIComponent(punchId)}`, "PATCH", body);
}

export async function apiDeleteAttendancePunch(punchId, reason = "") {
  const query = reason ? `?reason=${encodeURIComponent(reason)}` : "";
  return jsonRequest(
    `/hub/attendance/punches/${encodeURIComponent(punchId)}${query}`, "DELETE");
}
```

Check `jsonRequest`'s signature at the top of `api.js` first: if it requires a body argument, pass `{}` for the DELETE and drop the `body` assertion from that table row.

- [x] **Step 4: Run the tests**

Run: `npx vitest run tests/frontend/unit/api.endpoints.test.js tests/frontend/unit/api.shapes.test.js`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add backend/static/api.js tests/frontend/helpers/endpointTable.js
git commit -m "feat(attendance): api.js wrappers for the Admin punch writes"
```

---

### Task 5: The inline punch editor

**Files:**
- Create: `backend/static/views/hubAttendancePunchEditor.js`
- Test: `tests/frontend/views/hubAttendancePunchEditor.test.js`

**Interfaces:**
- Consumes: `promptTime({ title, help, initial })` from `../dom.js` (P1, unchanged).
- Produces: `mountPunchEditor(hostEl, { punch, date, onSave, onDelete, onCancel })`. `punch` is a week-payload punch or `null` for an add. `onSave({ startedAt, endedAt, reason })` receives ISO strings; `onDelete(reason)`; both may return a promise, during which the editor disables its buttons.

- [x] **Step 1: Write the failing test**

```js
// tests/frontend/views/hubAttendancePunchEditor.test.js
import { beforeEach, describe, expect, it, vi } from "vitest";

const promptTime = vi.fn();
vi.mock("../../../backend/static/dom.js", () => ({ promptTime }));

const { mountPunchEditor } = await import(
  "../../../backend/static/views/hubAttendancePunchEditor.js");

const PUNCH = {
  id: "22222222-2222-4222-8222-222222222222",
  started_at: "2026-09-21T13:00:00.000Z",
  ended_at: "2026-09-21T21:00:00.000Z",
  needs_review: false, minutes: 480, carried: false, open: false,
};

describe("the inline punch editor", () => {
  let host;
  beforeEach(() => {
    host = document.createElement("div");
    document.body.appendChild(host);
    promptTime.mockReset();
  });

  it("saves the picked start with the untouched end and the reason", async () => {
    promptTime.mockResolvedValue(new Date("2026-09-21T14:00:00.000Z"));
    const onSave = vi.fn().mockResolvedValue(undefined);
    mountPunchEditor(host, { punch: PUNCH, date: "2026-09-21", onSave });

    host.querySelector(".punch-editor-start").click();
    await Promise.resolve();
    host.querySelector(".punch-editor-reason").value = "clocked in late";
    host.querySelector(".punch-editor-save").click();
    await Promise.resolve();

    expect(onSave).toHaveBeenCalledWith({
      startedAt: "2026-09-21T14:00:00.000Z",
      endedAt: "2026-09-21T21:00:00.000Z",
      reason: "clocked in late",
    });
  });

  it("offers no delete when adding, and needs both times before saving", () => {
    const onSave = vi.fn();
    mountPunchEditor(host, { punch: null, date: "2026-09-21", onSave });
    expect(host.querySelector(".punch-editor-delete")).toBeNull();
    host.querySelector(".punch-editor-save").click();
    expect(onSave).not.toHaveBeenCalled();
    expect(host.querySelector(".punch-editor-message").textContent)
      .toMatch(/both a start and an end/i);
  });

  it("emits no nested buttons and no inline styles", () => {
    mountPunchEditor(host, { punch: PUNCH, date: "2026-09-21", onSave: vi.fn() });
    expect(host.querySelector("button button")).toBeNull();
    expect(host.innerHTML).not.toMatch(/style=/);
  });
});
```

- [x] **Step 2: Run it and watch it fail**

Run: `npx vitest run tests/frontend/views/hubAttendancePunchEditor.test.js`
Expected: FAIL — the module does not exist.

- [x] **Step 3: Write the editor**

```js
// backend/static/views/hubAttendancePunchEditor.js
//
// View: the inline editor that opens inside an Hours drill-down row.
//
// Layer: views (no fetch). Payload in, callbacks out -- `hubTimesheetsTab.js`
// owns the request and the refetch, exactly as it owns the week load.
//
// Two time *buttons* rather than a second modal: promptTime() (dom.js, P1) is
// already the picker, and nesting it under another overlay buys nothing. The
// buttons are siblings, never inside another button -- HTML hoists a nested
// one out and silently shifts the row.
//
// An omitted field means unchanged on the wire, so an untouched end time is
// still sent here as its original value and the tab decides what changed.

import { escapeHtml } from "../format.js";
import { promptTime } from "../dom.js";

const CENTRAL_TIME_ZONE = "America/Chicago";

function timeLabel(instant) {
  return new Date(instant).toLocaleTimeString([], {
    hour: "numeric", minute: "2-digit", timeZone: CENTRAL_TIME_ZONE,
  });
}

// The day the punch belongs to, so a picked time lands on the right date --
// promptTime resolves on its `initial`'s own calendar day and never rolls
// past midnight (its module comment says why).
function anchor(date, existing) {
  if (existing) return new Date(existing);
  const noon = new Date(`${date}T12:00:00`);
  return Number.isNaN(noon.getTime()) ? new Date() : noon;
}

export function mountPunchEditor(hostEl, { punch, date, onSave, onDelete, onCancel } = {}) {
  let startedAt = punch?.started_at || null;
  let endedAt = punch?.ended_at || null;
  let busy = false;

  function render() {
    hostEl.innerHTML = `<div class="punch-editor">
      <div class="punch-editor-times">
        <button type="button" class="secondary-btn punch-editor-start">
          Start: ${escapeHtml(startedAt ? timeLabel(startedAt) : "pick")}
        </button>
        <span aria-hidden="true">–</span>
        <button type="button" class="secondary-btn punch-editor-end">
          End: ${escapeHtml(endedAt ? timeLabel(endedAt) : "pick")}
        </button>
      </div>
      <label class="punch-editor-reason-label">
        <span class="sr-only">Reason (optional)</span>
        <input type="text" class="punch-editor-reason" placeholder="Reason (optional)" maxlength="200">
      </label>
      <div class="punch-editor-actions">
        <button type="button" class="punch-editor-save">Save</button>
        ${punch ? `<button type="button" class="danger-btn punch-editor-delete">Delete</button>` : ""}
        <button type="button" class="secondary-btn punch-editor-cancel">Cancel</button>
      </div>
      <p class="punch-editor-message" aria-live="polite"></p>
    </div>`;
    wire();
  }

  function say(text) {
    const target = hostEl.querySelector(".punch-editor-message");
    if (target) target.textContent = text;
  }

  function reason() {
    return hostEl.querySelector(".punch-editor-reason")?.value.trim() || "";
  }

  async function run(work) {
    if (busy) return;
    busy = true;
    hostEl.querySelectorAll("button").forEach((b) => { b.disabled = true; });
    try {
      await work();
    } finally {
      busy = false;
    }
  }

  async function pick(which) {
    const current = which === "start" ? startedAt : endedAt;
    const chosen = await promptTime({
      title: which === "start" ? "Punch in at" : "Punch out at",
      help: "Central time, on this day.",
      initial: anchor(date, current),
    });
    if (!chosen) return;
    const value = chosen.toISOString();
    if (which === "start") startedAt = value; else endedAt = value;
    const label = hostEl.querySelector(`.punch-editor-${which}`);
    if (label) {
      label.textContent = `${which === "start" ? "Start" : "End"}: ${timeLabel(value)}`;
    }
    say("");
  }

  function wire() {
    hostEl.querySelector(".punch-editor-start")
      ?.addEventListener("click", () => void pick("start"));
    hostEl.querySelector(".punch-editor-end")
      ?.addEventListener("click", () => void pick("end"));
    hostEl.querySelector(".punch-editor-save")?.addEventListener("click", () => {
      if (!startedAt || !endedAt) {
        say("Pick both a start and an end before saving.");
        return;
      }
      void run(() => onSave?.({ startedAt, endedAt, reason: reason() }));
    });
    hostEl.querySelector(".punch-editor-delete")?.addEventListener("click", () => {
      void run(() => onDelete?.(reason()));
    });
    hostEl.querySelector(".punch-editor-cancel")
      ?.addEventListener("click", () => onCancel?.());
  }

  render();
}
```

- [x] **Step 4: Run the tests**

Run: `npx vitest run tests/frontend/views/hubAttendancePunchEditor.test.js`
Expected: PASS (3 tests).

- [x] **Step 5: Commit**

```bash
git add backend/static/views/hubAttendancePunchEditor.js tests/frontend/views/hubAttendancePunchEditor.test.js
git commit -m "feat(attendance): the inline punch editor row"
```

---

### Task 6: The drill-down's buttons

**Files:**
- Modify: `backend/static/views/hubAttendanceHours.js:82-115` (`punchRowHtml`, `drilldownHtml`) and its `mountHubAttendanceHours` signature
- Test: `tests/frontend/views/hubAttendanceHours.test.js`

**Interfaces:**
- Consumes: `mountPunchEditor` (Task 5).
- Produces: `mountHubAttendanceHours(container, payload, { onWeekChange, onSavePunch, onAddPunch, onDeletePunch, onClearReview, canEdit })` — `onSavePunch(punchId, { startedAt, endedAt, reason })`, `onAddPunch(userId, { startedAt, endedAt, reason })`, `onDeletePunch(punchId, reason)`, `onClearReview(punchId)`. All optional; absent ones render no button, which keeps every existing caller and test valid.

- [x] **Step 1: Write the failing tests**

Append to `tests/frontend/views/hubAttendanceHours.test.js`:

```js
  it("offers Edit on an owned punch and withholds it on a carried one", () => {
    const payload = attendanceWeek();          // existing factory
    const row = payload.rows[0];
    row.days[0].punches = [
      { id: "p-own", started_at: "2026-09-14T13:00:00.000Z",
        ended_at: "2026-09-14T21:00:00.000Z", start_source: "manual",
        end_source: "manual", needs_review: false, minutes: 480,
        carried: false, open: false },
      { id: "p-carried", started_at: "2026-09-13T22:00:00.000Z",
        ended_at: "2026-09-14T02:00:00.000Z", start_source: "manual",
        end_source: "manual", needs_review: false, minutes: 120,
        carried: true, open: false },
    ];
    mountHubAttendanceHours(host, payload, { onSavePunch: vi.fn() });
    host.querySelector(".hub-hours-cell").click();

    const rows = host.querySelectorAll(".hub-hours-drilldown-row");
    expect(rows[0].querySelector(".hub-hours-edit")).not.toBeNull();
    expect(rows[1].querySelector(".hub-hours-edit")).toBeNull();
  });

  it("clears a needs_review flag through its own button", () => {
    const payload = attendanceWeek();
    payload.rows[0].days[0].punches = [
      { id: "p-flagged", started_at: "2026-09-14T13:00:00.000Z",
        ended_at: "2026-09-14T21:00:00.000Z", start_source: "manual",
        end_source: "self_reported", needs_review: true, minutes: 480,
        carried: false, open: false },
    ];
    const onClearReview = vi.fn();
    mountHubAttendanceHours(host, payload, { onClearReview, onSavePunch: vi.fn() });
    host.querySelector(".hub-hours-cell").click();
    host.querySelector(".hub-hours-clear-review").click();

    expect(onClearReview).toHaveBeenCalledWith("p-flagged");
  });

  it("renders no edit affordances at all when no callbacks are given", () => {
    const payload = attendanceWeek();
    mountHubAttendanceHours(host, payload, {});
    host.querySelector(".hub-hours-cell").click();
    expect(host.querySelector(".hub-hours-edit")).toBeNull();
    expect(host.querySelector(".hub-hours-add")).toBeNull();
  });
```

- [x] **Step 2: Run them and watch them fail**

Run: `npx vitest run tests/frontend/views/hubAttendanceHours.test.js`
Expected: FAIL — no `.hub-hours-edit` node.

- [x] **Step 3: Add the buttons and the editor mount**

In `backend/static/views/hubAttendanceHours.js`: import `{ mountPunchEditor }` from `./hubAttendancePunchEditor.js`, replace the module header's "Read-only in P2" paragraph with a line saying P3 added editing, take the four callbacks in the options object, and track `editing` (a punch id, `"add:<date>"`, or `null`) beside `expanded`, resetting it whenever `expanded` changes.

`punchRowHtml(punch, { canEdit })` appends, after its `<span>` pair:

```js
  // Spec §9: a carried punch is owned by the day it started, so it is
  // editable there and nowhere else.
  const controls = !canEdit || punch.carried ? "" : `<span class="hub-hours-row-actions">
      <button type="button" class="link-btn hub-hours-edit" data-punch="${escapeHtml(punch.id)}">Edit</button>
      ${punch.needs_review ? `<button type="button" class="link-btn hub-hours-clear-review" data-punch="${escapeHtml(punch.id)}">Looks right</button>` : ""}
    </span>`;
```

`drilldownHtml(day, name, { canEdit })` appends `+ Add punch` after its rows:

```js
  const add = canEdit
    ? `<button type="button" class="secondary-btn hub-hours-add" data-date="${escapeHtml(day.date)}">+ Add punch</button>`
    : "";
```

and reserves `<div class="hub-hours-editor" data-date="..."></div>` beneath them for the editor host.

In `render()`, after the existing cell wiring, wire the new buttons: `.hub-hours-edit` / `.hub-hours-add` set `editing` and re-render; `.hub-hours-clear-review` calls `onClearReview(button.dataset.punch)`. When `editing` is set, mount the editor into `.hub-hours-editor`:

```js
    const editorHost = container.querySelector(".hub-hours-editor");
    if (editorHost && editing) {
      const adding = editing.startsWith("add:");
      const punch = adding ? null : findPunch(editing);
      mountPunchEditor(editorHost, {
        punch,
        date: expanded.date,
        onSave: (values) => (adding
          ? onAddPunch?.(expandedUserId(), values)
          : onSavePunch?.(editing, values)),
        onDelete: (reason) => onDeletePunch?.(editing, reason),
        onCancel: () => { editing = null; render(); },
      });
    }
```

where `findPunch` scans the expanded day's `punches` and `expandedUserId()` reads `payload.rows[expanded.rowIndex].user.id`. `canEdit` is `Boolean(onSavePunch)`.

- [x] **Step 4: Run the tests**

Run: `npx vitest run tests/frontend/views/hubAttendanceHours.test.js`
Expected: PASS, including every pre-existing P2 test.

- [x] **Step 5: Check the file length**

Run: `wc -l backend/static/views/hubAttendanceHours.js`
Expected: under 500. If it is over, move `punchRowHtml` + `drilldownHtml` into the editor module — not a new split decision, just the same boundary drawn one function earlier.

- [x] **Step 6: Commit**

```bash
git add backend/static/views/hubAttendanceHours.js tests/frontend/views/hubAttendanceHours.test.js
git commit -m "feat(attendance): edit, add, and review controls in the Hours drill-down"
```

---

### Task 7: Wiring the writes to the week refetch

**Files:**
- Modify: `backend/static/views/hubTimesheetsTab.js:77-113`, `backend/static/styles.css`
- Test: `tests/frontend/views/hubTimesheetsTab.test.js`

**Interfaces:**
- Consumes: Task 4's wrappers, Task 6's callbacks.

- [x] **Step 1: Write the failing tests**

Append to `tests/frontend/views/hubTimesheetsTab.test.js` (MSW handlers in the existing style):

```js
  it("refetches the week after a punch edit", async () => {
    let weekCalls = 0;
    server.use(
      http.get("/hub/attendance/week", () => {
        weekCalls += 1;
        return HttpResponse.json(attendanceWeek());
      }),
      http.patch("/hub/attendance/punches/:id", () =>
        HttpResponse.json({ id: "p1", started_at: "2026-09-14T13:00:00.000Z",
                            ended_at: "2026-09-14T21:00:00.000Z",
                            start_source: "manual", end_source: "admin_edit",
                            needs_review: false })),
    );
    await mountTab({ role: "admin" });          // existing helper in this file
    await waitFor(() => expect(weekCalls).toBe(1));

    document.querySelector(".hub-hours-cell").click();
    document.querySelector(".hub-hours-edit").click();
    document.querySelector(".punch-editor-save").click();

    await waitFor(() => expect(weekCalls).toBe(2));
  });

  it("surfaces a 409 from an edit without losing the grid", async () => {
    server.use(
      http.get("/hub/attendance/week", () => HttpResponse.json(attendanceWeek())),
      http.patch("/hub/attendance/punches/:id", () =>
        HttpResponse.json({ detail: "That overlaps another punch for this person." },
                          { status: 409 })),
    );
    await mountTab({ role: "admin" });
    document.querySelector(".hub-hours-cell").click();
    document.querySelector(".hub-hours-edit").click();
    document.querySelector(".punch-editor-save").click();

    await waitFor(() => expect(document.querySelector(".punch-editor-message").textContent)
      .toMatch(/overlaps/i));
    expect(document.querySelector(".hub-hours-table")).not.toBeNull();
  });
```

- [x] **Step 2: Run them and watch them fail**

Run: `npx vitest run tests/frontend/views/hubTimesheetsTab.test.js`
Expected: FAIL — no `.hub-hours-edit` is wired, so the click finds nothing.

- [x] **Step 3: Wire the callbacks**

In `renderHours`, pass the four callbacks through. Each one awaits its write, then reloads:

```js
  // The write path is deliberately dumb: call, then refetch the week. The
  // grid holds no optimistic state, so a 409 leaves exactly what the server
  // last said on screen (spec §6: "refetch after an edit").
  async function write(panelEl, work) {
    try {
      await work();
      await loadHours(panelEl);
    } catch (err) {
      const message = document.querySelector(".punch-editor-message");
      if (message) message.textContent = friendlyError(err, "Could not save that punch.");
      else showHoursError(panelEl, err);
    }
  }
```

with `onSavePunch: (id, values) => write(panelEl, () => apiEditAttendancePunch(id, values))`, `onAddPunch: (userId, values) => write(panelEl, () => apiAddAttendancePunch({ userId, ...values }))`, `onDeletePunch: (id, reason) => write(panelEl, () => apiDeleteAttendancePunch(id, reason))`, and `onClearReview: (id) => write(panelEl, () => apiEditAttendancePunch(id, { needsReview: false }))`. `canEdit` follows from passing the callbacks only when `roleAtLeast(viewerRole, "admin")`.

- [x] **Step 4: Add the styles**

In `backend/static/styles.css`, beside the existing `.hub-hours-*` block: `.hub-hours-row-actions` (inline flex, small gap), `.punch-editor` (column flex, padded, panel background), `.punch-editor-times` (row flex, wrap), `.punch-editor-actions` (row flex, gap), `.punch-editor-message` (the `.hint` size, red when it carries an error class). Reuse the existing `--` design tokens; add no new colors.

- [x] **Step 5: Run the frontend suite**

Run: `npx vitest run`
Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add backend/static/views/hubTimesheetsTab.js backend/static/styles.css tests/frontend/views/hubTimesheetsTab.test.js
git commit -m "feat(attendance): wire the punch writes to the Hours refetch"
```

---

### Task 8: Docs and the full-suite gate

**Files:**
- Modify: `docs/endpoint-map.md:132`, `docs/current-state.md:113,1264-1290,1684`, `docs/open-work.md:53-70`

- [x] **Step 1: Run everything**

Run: `cd backend && python -m pytest -q` then `npx vitest run`
Expected: both green. `test_cascade_deletes_with_user` may fail on a dev database carrying real cloud-session rows — that is environmental, not this change.

- [x] **Step 2: Endpoint map**

Add three rows after H8, in the existing column order (`H9` / `H10` / `H11`): the method, the path, **admin only**, `hub.py` → `attendance.admin_add_punch` / `admin_edit_punch` / `admin_delete_punch`, tables `attendance_punches (r/w), attendance_punch_edits (w), users (r)`, the api wrapper, and `hubAttendanceHours.js`, `hubAttendancePunchEditor.js`, `hubTimesheetsTab.js`.

- [x] **Step 3: current-state.md**

In the Attendance row (line 113), replace "Read-only: editing punches is a later phase" with the Admin write surface, the soft delete, and the audit; add `hubAttendancePunchEditor.js`, `test_attendance_admin_service.py`, `test_attendance_admin_router.py` to its file and test lists. In the `attendance_punches` section (line 1264), replace "unwritten until the Admin edit phase" with one line on what writes it and one on `deleted_at`. Add the `c4a6e8b0d2f5` migration row. Delete, do not append: the budget is 16,500 words and history belongs to git.

- [x] **Step 4: open-work.md**

Rewrite IMP-041 to P4 only — charged vs clocked, the live roster, `attendance.changed`, the CSV, and the §7 retirement — and add one line under it recording that `promptTime()`'s analog dial was cut from P3 (the dropdowns + nudge row are complete and keyboard-accessible; the dial is optional polish) so a future session does not re-litigate it as an omission. Note there that the `⚠ charged outside shift` advisory (§9) rides with P4's labor join.

- [x] **Step 5: Commit**

```bash
git add docs/endpoint-map.md docs/current-state.md docs/open-work.md
git commit -m "docs(attendance): P3 punch editing, the soft delete, and the trimmed backlog"
```
