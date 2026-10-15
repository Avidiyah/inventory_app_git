# Attendance Midnight Close and Lunch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** No punch survives the Central midnight after its start, and a flat 30-minute lunch comes off every 6-hour day as its own Admin-removable number.

**Architecture:** One domain helper, `capped_end`, decides the midnight cap; every read calls it, and a lazy sweep writes it from the existing sweep call sites. P1 deletes the self-close flow. P2 adds one column (`lunch_waived`), computes lunch and paid minutes in `attendance_week`, and lets the other reads inherit them.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic + Pydantic (`from_attributes`), vanilla ES modules, pytest (`db` fixture, `TestClient`), vitest + jsdom + MSW.

**Spec:** `docs/superpowers/specs/2026-10-15-attendance-midnight-close-and-lunch-design.md`. Read it first; this plan does not restate M1–M5 or L1–L4.

## Global Constraints

- Paths are relative to `backend/` unless they start with `tests/frontend` or `docs/`.
- pytest from `backend/`: `venv/Scripts/python -m pytest <file> -q`. vitest from the repo root: `npx vitest run <file>`.
- Targeted tests only. Commit after each task on `main`; **never push** (pushing main deploys).
- `LUNCH_MINUTES = 30`, `LUNCH_MIN_DAY_MINUTES = 360`.
- Error copy is exact: `"A punch may not cross midnight."`, `"You are already punched in since {when}."`.
- Audit reasons are exact: `"Lunch removed by an Admin"`, `"Lunch restored by an Admin"`.
- No `style=` attributes (CSP drops them). No nested `<button>`. Files stay ≤ 500 lines.
- **Deviation from the spec:** the spec's `effective_end` and `punch_needs_review` collapse into one helper, `capped_end`, a sibling of `work_orders.capped_session_end`. "Needs review" for a capped punch is `stored or capped`.
- **Deviation from the spec:** the drill-down shows `No lunch deducted [Restore lunch]` whenever the day is waived; the client never learns the threshold.

## Review Focus

1. A forgotten Sunday punch read on Monday of the next week: it counts on Sunday only, flagged, and Monday reads 0. Pinned in Task 3 (`test_a_forgotten_sunday_punch_stays_on_sunday`).
2. "Looks right" on a legacy cross-midnight punch must succeed, not 400 (M4 only checks changed times). Pinned in Task 2 (`test_looks_right_on_a_legacy_cross_midnight_punch_succeeds`).
3. A DST-transition day: midnight is local midnight, not start + 24 h. Pinned in Task 1 (`test_midnight_after_across_dst`).
4. Exactly 6:00 gross deducts lunch; 5:59 does not. Pinned in Task 6 (`test_lunch_at_the_threshold`).
5. The day's earliest punch is carried from yesterday: the lunch button targets the first non-carried punch. Pinned in Task 9 (`lunch button targets the first non-carried punch`).

---

## Phase 1 — midnight close (M1–M5)

### Task 1: Domain rules

**Files:**
- Modify: `app/domain/attendance.py` (delete `is_stale` at 110–123; add helpers; extend `validate_punch_window`)
- Test: `tests/test_attendance_domain.py` (delete the three staleness tests at 52–64)

**Interfaces:**
- Produces: `midnight_after(started_at: datetime) -> datetime`; `capped_end(started_at, ended_at: Optional[datetime], *, now) -> Optional[datetime]` (stored end if set; the midnight if open and `now >= midnight`; else `None` = still open); `validate_punch_window` raises on a cross-midnight end.

- [ ] **Step 1: Write the failing tests** (replace the deleted staleness tests)

```python
CT = labor_day.CENTRAL

def test_midnight_after_is_the_next_central_midnight():
    # 8:00 PM Central Mon 9/21 = 01:00 UTC Tue; its midnight is 05:00 UTC Tue.
    start = datetime(2026, 9, 22, 1, 0, tzinfo=timezone.utc)
    assert attendance.midnight_after(start) == datetime(2026, 9, 22, 5, 0, tzinfo=timezone.utc)

def test_midnight_after_across_dst():
    fall = datetime(2026, 11, 1, 9, 0, tzinfo=CT)       # DST ends that night
    spring = datetime(2026, 3, 8, 9, 0, tzinfo=CT)      # DST starts that morning
    assert attendance.midnight_after(fall) == datetime(2026, 11, 2, 6, 0, tzinfo=timezone.utc)
    assert attendance.midnight_after(spring) == datetime(2026, 3, 9, 5, 0, tzinfo=timezone.utc)

def test_capped_end():
    start = NOW - timedelta(hours=6)                          # today
    yesterday = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
    midnight = datetime(2026, 9, 21, 5, 0, tzinfo=timezone.utc)
    assert attendance.capped_end(start, None, now=NOW) is None
    assert attendance.capped_end(yesterday, None, now=NOW) == midnight
    assert attendance.capped_end(start, NOW, now=NOW) == NOW

def test_a_punch_may_not_cross_midnight():
    start = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
    with pytest.raises(PunchTimeInvalidError, match="may not cross midnight"):
        attendance.validate_punch_window(start, datetime(2026, 9, 21, 5, 1, tzinfo=timezone.utc), now=NOW)
    attendance.validate_punch_window(start, datetime(2026, 9, 21, 5, 0, tzinfo=timezone.utc), now=NOW)
```

- [ ] **Step 2: Run, expect FAIL** (`AttributeError: midnight_after`): `venv/Scripts/python -m pytest tests/test_attendance_domain.py -q`

- [ ] **Step 3: Implement** (replace `is_stale`)

```python
def midnight_after(started_at: datetime) -> datetime:
    """The Central midnight that ends `started_at`'s day (M1). DST-safe
    because `day_bounds` is."""
    return labor_day.day_bounds(labor_day.central_date_of(started_at))[1]


def capped_end(started_at: datetime, ended_at: Optional[datetime], *,
               now: datetime) -> Optional[datetime]:
    """Where a punch ends for every read (M1/M2). The stored end when set;
    the midnight after the start once `now` reaches it; else None (still on
    shift). Sibling of `work_orders.capped_session_end`: reads compute the
    cap, `services.attendance.sweep_open_punches` writes it lazily."""
    if ended_at is not None:
        return labor_day.as_utc(ended_at)
    midnight = midnight_after(started_at)
    return midnight if labor_day.as_utc(now) >= midnight else None
```

In `validate_punch_window`, after the `end <= start` check:

```python
    if end > midnight_after(start):
        raise PunchTimeInvalidError("A punch may not cross midnight.")
```

Update the docstring: "Spec 9's first two rows plus M4."

- [ ] **Step 4: Run, expect PASS.** `grep -rn is_stale app` must show only `domain/hub.py`'s `is_stale_work_order` once Tasks 2–3 land; callers break until then, so commit Tasks 1–3 together (Step 5 of Task 3).

---

### Task 2: Sweep, call sites, write-side deletions

**Files:**
- Modify: `app/services/attendance.py` (`_already_open`, `punch_in`, `punch_out`, delete `self_close`, `ensure_punch_for_labor_start`, `admin_edit_punch`, `admin_clock_out`, `mark_week_reviewed`; new `sweep_open_punches`)
- Modify: `app/domain/errors.py:380-392` (`PunchAlreadyOpenError` loses `stale`; docstring now says the caller's sweep runs first)
- Modify: `app/services/hub.py` (import `attendance as attendance_service`; sweep beside lines 244, 489, 889)
- Modify: `app/routers/work_orders.py:1126-1130` (comment only: no stale refusal)
- Test: `tests/test_attendance_service.py` (delete stale-blocks-start and the three `self_close` tests)

**Interfaces:**
- Consumes: `attendance.midnight_after`, `attendance.capped_end`.
- Produces: `sweep_open_punches(db, *, now=None, user_id=None) -> int`.

- [ ] **Step 1: Write the failing tests**

```python
YESTERDAY_7AM = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)   # 7:00 AM CDT Sun
MIDNIGHT = datetime(2026, 9, 21, 5, 0, tzinfo=timezone.utc)
NOW = datetime(2026, 9, 21, 18, 0, tzinfo=timezone.utc)

def _open_punch(db, user, started_at):
    punch = AttendancePunch(id=uuid.uuid4(), user_id=user.id, started_at=started_at,
                            start_source=attendance_domain.START_SOURCE_MANUAL)
    db.add(punch); db.commit()
    return punch

def test_sweep_closes_yesterday_at_midnight_and_leaves_today(db):
    tech, other = _seed_user(db), _seed_user(db)
    old = _open_punch(db, tech, YESTERDAY_7AM)
    today = _open_punch(db, other, NOW - timedelta(hours=2))
    assert attendance_service.sweep_open_punches(db, now=NOW) == 1
    db.refresh(old); db.refresh(today)
    assert old.ended_at == MIDNIGHT
    assert old.end_source == attendance_domain.END_SOURCE_AUTO_CLOCK_OUT
    assert old.needs_review is True
    assert today.ended_at is None
    assert attendance_service.sweep_open_punches(db, now=NOW) == 0
    assert db.query(AttendancePunchEdit).count() == 0

def test_sweep_leaves_the_work_order_clock_running(db):
    admin, tech = _seed_user(db, "admin"), _seed_user(db)
    order = _seed_work_order(db, admin, tech)
    wo_service.start_labor_session(db, order.id, user=tech)
    _open_punch(db, tech, datetime.now(timezone.utc) - timedelta(days=1))
    assert attendance_service.sweep_open_punches(db) == 1
    assert wo_service.running_labor_session_for(db, tech.id) is not None

def test_punch_in_after_a_forgotten_day_succeeds(db):
    tech = _seed_user(db)
    _open_punch(db, tech, YESTERDAY_7AM)
    punch = attendance_service.punch_in(db, user=tech, now=NOW)
    assert punch.started_at == NOW

def test_labor_start_after_a_forgotten_day_opens_a_fresh_punch(db):
    tech = _seed_user(db)
    _open_punch(db, tech, YESTERDAY_7AM)
    punch = attendance_service.ensure_punch_for_labor_start(db, user=tech, now=NOW)
    assert punch.started_at == NOW
    assert punch.start_source == attendance_domain.START_SOURCE_AUTO_WORK_ORDER

def test_punch_out_after_midnight_closes_at_midnight_and_reports_not_punched_in(db):
    tech = _seed_user(db)
    old = _open_punch(db, tech, YESTERDAY_7AM)
    with pytest.raises(PunchNotFoundError):
        attendance_service.punch_out(db, user=tech, now=NOW)
    db.refresh(old)
    assert old.ended_at == MIDNIGHT

def test_looks_right_on_a_legacy_cross_midnight_punch_succeeds(db):
    admin, tech = _seed_user(db, role="admin"), _seed_user(db)
    legacy = AttendancePunch(id=uuid.uuid4(), user_id=tech.id, started_at=YESTERDAY_7AM,
                             ended_at=MIDNIGHT + timedelta(hours=2), start_source="manual",
                             end_source="self_reported", needs_review=True)
    db.add(legacy); db.commit()
    attendance_service.admin_edit_punch(db, actor=admin, punch_id=legacy.id,
                                        needs_review=False, now=NOW)
    db.refresh(legacy)
    assert legacy.needs_review is False

def test_an_admin_edit_across_midnight_is_refused(db):
    admin, tech = _seed_user(db, role="admin"), _seed_user(db)
    punch = attendance_service.admin_add_punch(db, actor=admin, user_id=tech.id,
        started_at=YESTERDAY_7AM, ended_at=YESTERDAY_7AM + timedelta(hours=8), now=NOW)
    with pytest.raises(PunchTimeInvalidError, match="cross midnight"):
        attendance_service.admin_edit_punch(db, actor=admin, punch_id=punch.id,
                                            ended_at=MIDNIGHT + timedelta(minutes=1), now=NOW)

def test_mark_week_reviewed_accepts_a_midnight_close(db):
    admin, tech = _seed_user(db, role="admin"), _seed_user(db)
    old = _open_punch(db, tech, YESTERDAY_7AM)
    result = attendance_service.mark_week_reviewed(db, actor=admin,
        week_start=date(2026, 9, 14), now=NOW)   # Mon 9/14 – Sun 9/20
    db.refresh(old)
    assert result.punches == 1 and old.needs_review is False
```

Also delete the `assert exc.value.stale is False` line from `test_punch_in_refuses_while_one_is_open_and_names_it`.

- [ ] **Step 2: Run, expect FAIL** (`AttributeError: sweep_open_punches`).

- [ ] **Step 3: Implement**

```python
def sweep_open_punches(db: Session, *, now: Optional[datetime] = None,
                       user_id: Optional[uuid.UUID] = None) -> int:
    """M1/M2: close every live punch still open from an earlier Central day
    at that day's midnight, `auto_clock_out`, flagged. Idempotent; commits
    only when it closed something; no audit row (no actor -- the source and
    flag are the record, as `auto_closed_at` is for a session). Never stops
    a work-order clock (M3). Emits nothing: every read computes the cap."""
    now = now or datetime.now(timezone.utc)
    today_start, _ = labor_day.day_bounds(labor_day.central_date_of(now))
    query = live_punches(db).filter(AttendancePunch.ended_at.is_(None),
                                    AttendancePunch.started_at < today_start)
    if user_id is not None:
        query = query.filter(AttendancePunch.user_id == user_id)
    expired = query.all()
    for punch in expired:
        punch.ended_at = attendance.midnight_after(punch.started_at)
        punch.end_source = attendance.END_SOURCE_AUTO_CLOCK_OUT
        punch.needs_review = True
    if expired:
        db.commit()
    return len(expired)
```

- `_already_open`: keep the hand-formatted `when`; message is only `f"You are already punched in since {when}."`; construct `PunchAlreadyOpenError(message, punch_id=..., started_at=...)`.
- First line after `now = ...` in `punch_in`, `punch_out`, `ensure_punch_for_labor_start`: `sweep_open_punches(db, now=now, user_id=user.id)`. In `admin_clock_out`: `user_id=user_id`.
- `ensure_punch_for_labor_start`: drop the stale branch, so `if existing is not None: return existing`. Rewrite its docstring without "stale".
- Delete `self_close` whole.
- `admin_edit_punch`: wrap validation so M4 only applies to changed times:

```python
    if (new_start, new_end) != (punch.started_at, punch.ended_at):
        attendance.validate_punch_window(new_start, new_end, now=now)
        _assert_no_overlap(db, user_id=punch.user_id, punch_id=punch.id,
                           started_at=new_start, ended_at=new_end, now=now)
```

  Docstring: "a self-reported time" → "a midnight-closed or self-reported time".
- `mark_week_reviewed`: after `wo_service.sweep_stale_sessions(db, now=now)` add `sweep_open_punches(db, now=now)`. Replace the docstring's "An open punch is left alone…" paragraph with: "Punches still open from an earlier day are swept first, so a midnight close is accepted with the rest."
- `services/hub.py`: `attendance_service.sweep_open_punches(db, now=now, user_id=user.id)` after line 244's sweep; `user_id=technician_id` inside the 489 loop; `sweep_open_punches(db, now=now)` after 889. No import cycle: `services/attendance` imports only `work_orders`.

- [ ] **Step 4: Run, expect PASS**: `tests/test_attendance_service.py tests/test_attendance_domain.py`.

---

### Task 3: Read-side cap

**Files:**
- Modify: `app/services/attendance.py:205-245` (`me_payload`, `OpenPunch` loses `stale`)
- Modify: `app/services/attendance_week.py:185-218`
- Modify: `app/services/attendance_compare.py:150-155` and the `reviewable_count` comment at 86–88
- Modify: `app/services/attendance_live.py:145-155`
- Test: `tests/test_attendance_week_service.py` (delete open-counts-to-now across days and cross-midnight-carries); `tests/test_attendance_compare_service.py` (delete earlier-day pending and review-leaves-open-punch); `tests/test_attendance_live_service.py`; `tests/test_attendance_router.py` (`/me` test at line 60 drops `stale`)

**Interfaces:**
- Consumes: `attendance.capped_end`, `attendance.END_SOURCE_AUTO_CLOCK_OUT`.
- Produces: `WeekPunch` for a capped punch carries `ended_at=midnight`, `end_source="auto_clock_out"`, `needs_review=True`, `open=False`, exactly as after a sweep.

- [ ] **Step 1: Write the failing tests**

```python
# test_attendance_week_service.py
def test_a_punch_past_midnight_reads_closed_and_flagged_before_any_sweep(db):
    tech = _seed_user(db)
    _open_punch(db, tech, YESTERDAY_7AM)            # Sun 9/20 7:00 AM CDT
    week = attendance_week.week_payload(db, week_start=date(2026, 9, 14), now=NOW)
    sunday = next(r for r in week.rows if r.user.id == tech.id).days[6]
    assert sunday.clocked_minutes == 17 * 60
    assert sunday.needs_review and not sunday.has_open
    assert sunday.punches[0].end_source == "auto_clock_out"

def test_a_forgotten_sunday_punch_stays_on_sunday(db):
    tech = _seed_user(db)
    _open_punch(db, tech, YESTERDAY_7AM)
    week = attendance_week.week_payload(db, week_start=date(2026, 9, 21), now=NOW)
    monday = next(r for r in week.rows if r.user.id == tech.id).days[0]
    assert monday.clocked_minutes == 0 and monday.punches == []

# test_attendance_live_service.py
def test_a_punch_past_midnight_is_absent_not_red(db):
    tech = _seed_user(db)
    _open_punch(db, tech, YESTERDAY_7AM)
    roster = attendance_live.roster(db, now=NOW)
    assert tech.id in {e.user.id for e in roster.absent}

# test_attendance_service.py
def test_me_payload_does_not_count_yesterdays_open_punch_into_today(db):
    tech = _seed_user(db)
    _open_punch(db, tech, YESTERDAY_7AM)
    me = attendance_service.me_payload(db, user=tech, now=NOW)
    assert me.open_punch is None and me.clocked_minutes_today == 0
```

Match the existing helpers and `roster`'s real signature in each file (copy `_open_punch` from Task 2 where absent).

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement**

`me_payload`:

```python
    minutes = sum(
        labor_day.overlap_minutes(
            p.started_at, attendance.capped_end(p.started_at, p.ended_at, now=now),
            day_start, day_end, now=now)
        for p in punches
    )
    open_row = next((p for p in punches
                     if attendance.capped_end(p.started_at, p.ended_at, now=now) is None), None)
```

Drop `stale=` from `OpenPunch(...)` and the `stale` field from the dataclass.

`week_payload` inner loop:

```python
                end = attendance.capped_end(punch.started_at, punch.ended_at, now=now)
                capped = punch.ended_at is None and end is not None
                minutes = labor_day.overlap_minutes(
                    punch.started_at, end, day_start, day_end, now=now)
                ...
                        ended_at=end,
                        end_source=attendance.END_SOURCE_AUTO_CLOCK_OUT if capped else punch.end_source,
                        needs_review=bool(punch.needs_review) or capped,
                        ...
                        open=end is None,
```

Import `from app.domain import attendance, labor_day, roles`. Update the `WeekPunch` docstring: a crossing punch is legacy-only (M4).

`attendance_compare`: `pending = bool(flagged_punches or flagged_sessions)`; drop the `is_stale` clause. A capped punch is flagged, so it lands in `reviewable`, which is correct now that review sweeps first. Fix the comment at 86–88 and the module docstring line 30 ("a punch still open from an earlier day" goes).

`attendance_live`: at the top of the per-person loop:

```python
        punch = punches.get(person.id)
        if punch is not None and attendance.capped_end(
                punch.started_at, None, now=moment) is not None:
            punch = None   # past its midnight: closed for every read (M1)
```

- [ ] **Step 4: Run, expect PASS**: the four test files above plus `tests/test_person_week_service.py`.

- [ ] **Step 5: Commit Tasks 1–3**

```bash
git add app/domain app/services app/routers/work_orders.py tests
git commit -m "feat(attendance): an open punch ends at the Central midnight after its start"
```

---

### Task 4: Routes, schemas, frontend deletions

**Files:**
- Modify: `app/routers/attendance.py` (delete `self_close` route, `SelfCloseRequest` import; `punch_in` docstring)
- Modify: `app/schemas/attendance.py` (delete `SelfCloseRequest`; drop `AttendanceOpenPunch.stale` and its docstring sentence; `PunchEditRequest` docstring: "nothing but the midnight close may raise the flag")
- Modify: `static/api.js:629-634` (delete `apiSelfClosePunch`)
- Modify: `static/views/hubHome.js` (delete `stalePunchHtml`, `handleSelfClose`, the self-close click arm, `apiSelfClosePunch` and `promptTime` imports; `punchHtml` returns `onShiftHtml()` when open)
- Modify: `static/views/workOrderActions.js` (delete `resolveStalePunch` and its comment block at 105–138, the `apiSelfClosePunch`/`promptTime`/`apiGetAttendanceMe` imports if now unused, and at 293–295 replace the retry with `throw err;`)
- Test: `tests/test_attendance_router.py` (delete self-close ×2 and the stale 409 test at 126), `tests/frontend/helpers/endpointTable.js:140-141`, `tests/frontend/helpers/hub.js:63`, `tests/frontend/views/hubHome.test.js` ("Close it"), `tests/frontend/views/workOrderStartPunch.test.js` (the four stale tests)

- [ ] **Step 1: Write the failing tests**

```python
def test_self_close_route_is_gone(db):
    # use this file's existing authenticated-client helper
    response = client.post("/attendance/self-close", json={"ended_at": "2026-09-21T18:00:00Z"})
    assert response.status_code in (404, 405)
```

```js
// workOrderStartPunch.test.js — keep one: any 409 stays inline
it("shows a punch 409 inline without prompting", async () => {
  // reuse the file's existing 409 handler setup with detail
  // "You are already punched in since Mon 7:02 AM."
  // assert the inline message text and that no prompt-time overlay opened
});
```

Write the JS test body from the deleted tests' own setup (same MSW handler, same card mount); assert `document.getElementById("prompt-time-overlay").hidden` stays true.

- [ ] **Step 2: Run, expect FAIL** (the route still exists).

- [ ] **Step 3: Delete the code listed above.** Then `grep -rn "stale\b\|self.close\|SelfClose" app static | grep -iv "stale_work\|staleSession\|stale cached"` should show only unrelated hits.

- [ ] **Step 4: Run, expect PASS**: `tests/test_attendance_router.py tests/test_route_role_gates.py`, then `npx vitest run tests/frontend/views/hubHome.test.js tests/frontend/views/workOrderStartPunch.test.js tests/frontend/unit/api.shapes.test.js`.

- [ ] **Step 5: Commit**: `feat(attendance): delete the self-close flow`.

---

### Task 5: P1 docs

**Files:** `docs/current-state.md` (Hard Invariants 442–445, 457–460; `attendance_punches` rules 1408–1409), `docs/endpoint-map.md` (A4 row removed, H9/H10 notes, `attendance.changed` row, `/attendance/me` shape), `docs/notification-events.md` (`attendance.changed` trigger list loses self-close), `docs/open-work.md` (IMP-041 status).

- [ ] **Step 1:** Rewrite each to current truth: open punches end at Central midnight (`auto_clock_out`, flagged, swept lazily from the hub reads, punch-in/out, labor start, Admin clock-out, and week review); no punch crosses midnight on any time write; no self-close. Delete superseded D4/D5 text. Respect each doc's word budget.
- [ ] **Step 2: Commit**: `docs(attendance): midnight close is current truth`.

---

## Phase 2 — lunch (L1–L4)

### Task 6: Column, migration, lunch rule

**Files:**
- Create: `alembic/versions/c8e2f4a6b1d3_add_attendance_lunch_waived.py`
- Modify: `app/models.py:~687` (after `needs_review`)
- Modify: `app/domain/attendance.py` (constants + `lunch_minutes`)
- Test: `tests/test_attendance_domain.py`

**Interfaces:**
- Produces: `AttendancePunch.lunch_waived: bool`; `lunch_minutes(gross: int, *, waived: bool) -> int`.

- [ ] **Step 1: Write the failing test**

```python
def test_lunch_at_the_threshold():
    assert attendance.lunch_minutes(360, waived=False) == 30
    assert attendance.lunch_minutes(359, waived=False) == 0
    assert attendance.lunch_minutes(600, waived=True) == 0
```

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement**

```python
LUNCH_MINUTES = 30
LUNCH_MIN_DAY_MINUTES = 360   # owner, 2026-10-15

def lunch_minutes(gross: int, *, waived: bool) -> int:
    """L1: a flat lunch off any day long enough to have one. No time-of-day
    logic and no gap detection -- one punch pair per day is the assumption."""
    return LUNCH_MINUTES if gross >= LUNCH_MIN_DAY_MINUTES and not waived else 0
```

Model: `lunch_waived = Column(Boolean, nullable=False, default=False, server_default=text("false"))`.

Migration:

```python
"""add attendance_punches.lunch_waived

Revision ID: c8e2f4a6b1d3
Revises: a7c3e9f1b2d4
Create Date: 2026-10-15 12:00:00.000000

L2: an Admin's per-day "no lunch" waiver. No data migration.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c8e2f4a6b1d3"
down_revision: Union[str, Sequence[str], None] = "a7c3e9f1b2d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("attendance_punches", sa.Column(
        "lunch_waived", sa.Boolean(), nullable=False, server_default=sa.text("false")))


def downgrade() -> None:
    op.drop_column("attendance_punches", "lunch_waived")
```

- [ ] **Step 4:** `venv/Scripts/python -m alembic upgrade head` against the local DB (port 8801), then run the domain tests and expect PASS.
- [ ] **Step 5: Commit**: `feat(attendance): lunch_waived column and the flat lunch rule`.

---

### Task 7: The waiver write

**Files:**
- Modify: `app/services/attendance.py` (`admin_edit_punch`)
- Modify: `app/schemas/attendance.py` (`PunchEditRequest.lunch_waived: Optional[bool] = None`)
- Modify: `app/routers/hub.py:274-277` (pass `lunch_waived=payload.lunch_waived`)
- Test: `tests/test_attendance_service.py`, `tests/test_attendance_admin_router.py`

**Interfaces:**
- Produces: `admin_edit_punch(..., lunch_waived: Optional[bool] = None)`; audit field `lunch_waived`, values `"false"`/`"true"`.

- [ ] **Step 1: Write the failing tests**

```python
def test_waiving_lunch_writes_an_audit_row_and_keeps_needs_review(db):
    admin, tech = _seed_user(db, role="admin"), _seed_user(db)
    old = _open_punch(db, tech, YESTERDAY_7AM)
    attendance_service.sweep_open_punches(db, now=NOW)          # flagged
    attendance_service.admin_edit_punch(db, actor=admin, punch_id=old.id,
        lunch_waived=True, reason="Lunch removed by an Admin", now=NOW)
    db.refresh(old)
    assert old.lunch_waived is True and old.needs_review is True
    edit = db.query(AttendancePunchEdit).filter_by(punch_id=old.id).one()
    assert (edit.field, edit.old_value, edit.new_value) == ("lunch_waived", "false", "true")
```

Router test: PATCH `{"lunch_waived": true}` returns 200, and PATCH with a cross-midnight `ended_at` returns 400. Copy the client/auth setup from that file. Check the audit model's real column names before asserting.

- [ ] **Step 2: Run, expect FAIL** (unexpected kwarg).
- [ ] **Step 3: Implement.** In `admin_edit_punch`, keep `clearing` keyed to time changes only (L4), then append the waiver:

```python
    clearing = punch.needs_review and (needs_review is False or bool(changes))
    if clearing:
        changes.append(("needs_review", "true", "false"))
    if lunch_waived is not None and lunch_waived != bool(punch.lunch_waived):
        changes.append(("lunch_waived", str(bool(punch.lunch_waived)).lower(),
                        str(lunch_waived).lower()))
    if not changes:
        raise NoChangeError("Nothing about that punch changed.")
    ...
    if lunch_waived is not None:
        punch.lunch_waived = lunch_waived
```

Docstring: "Toggling `lunch_waived` never clears `needs_review` (L4)."

- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit**: `feat(attendance): Admins waive a day's lunch through the punch PATCH`.

---

### Task 8: Lunch and paid on every read, CSV

**Files:**
- Modify: `app/services/attendance_week.py` (`WeekPunch.lunch_waived`; `WeekDay` + `lunch_minutes`, `lunch_waived`, `paid_minutes`; `WeekRow.paid_minutes`; `DayTotal.paid_minutes`; `AttendanceWeek.paid_minutes`)
- Modify: `app/services/attendance_compare.py` (`CompareDay` gains the three, `CompareRow.paid_minutes`, `CompareWeek.paid_minutes`; `_METRICS` gains `("Lunch", "lunch_minutes")`, `("Paid", "paid_minutes")` after Clocked; "Five rows" → "Seven rows")
- Modify: `app/services/person_week.py` (`PersonDay.lunch_minutes`, `paid_minutes`; `PersonWeek.total_paid_minutes`)
- Modify: `app/schemas/attendance.py` (`AttendanceWeekPunch`, `AttendanceWeekDay`, `AttendanceWeekRow`, `AttendanceWeekDayTotal`, `AttendanceWeekResponse`, `PersonWeekDay`, `PersonWeekResponse`)
- Test: `tests/test_attendance_week_service.py`, `tests/test_person_week_service.py`, `tests/test_attendance_compare_service.py`, `tests/test_attendance_export_router.py`

- [ ] **Step 1: Write the failing tests**

```python
def _closed(db, user, start, hours, waived=False):
    p = AttendancePunch(id=uuid.uuid4(), user_id=user.id, started_at=start,
                        ended_at=start + timedelta(hours=hours), start_source="manual",
                        end_source="manual", lunch_waived=waived)
    db.add(p); db.commit()
    return p

MON_7AM = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)

def test_lunch_comes_off_a_long_day_and_not_a_short_one(db):
    tech = _seed_user(db)
    _closed(db, tech, MON_7AM, 8)
    _closed(db, tech, MON_7AM + timedelta(days=1), 5)
    row = _row(attendance_week.week_payload(db, week_start=date(2026, 9, 14), now=NOW), tech)
    mon, tue = row.days[0], row.days[1]
    assert (mon.clocked_minutes, mon.lunch_minutes, mon.paid_minutes) == (480, 30, 450)
    assert (tue.lunch_minutes, tue.paid_minutes) == (0, 300)
    assert row.paid_minutes == 750

def test_a_waiver_on_any_punch_waives_the_day(db):
    tech = _seed_user(db)
    _closed(db, tech, MON_7AM, 4)
    _closed(db, tech, MON_7AM + timedelta(hours=5), 4, waived=True)
    mon = _row(attendance_week.week_payload(db, week_start=date(2026, 9, 14), now=NOW), tech).days[0]
    assert mon.lunch_waived and mon.lunch_minutes == 0 and mon.paid_minutes == 480
```

Also add: `totals_by_day[0].paid_minutes == 450` and week `paid_minutes`; compare `delta_minutes` on the 8 h day with no labor == 480 (gross, L3); person week `days[0].paid_minutes == 450` and `total_paid_minutes`; the CSV header block's second and third metric rows read `Lunch` `0:30` and `Paid` `7:30`. `_row` = `next(r for r in week.rows if r.user.id == tech.id)`.

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.** In `week_payload`, after `day_minutes`:

```python
            waived = any(e.lunch_waived for e in day_punches if not e.carried)
            lunch = attendance.lunch_minutes(day_minutes, waived=waived)
            paid = day_minutes - lunch
            row_paid += paid
            paid_by_day[day] += paid
```

Set `lunch_waived=bool(punch.lunch_waived)` on each `WeekPunch`. Thread `row_paid` into `WeekRow`, `paid_by_day` into each `DayTotal`, and `sum(paid_by_day.values())` into `AttendanceWeek.paid_minutes`. In `attendance_compare`, copy `day.lunch_minutes`, `day.lunch_waived`, and `day.paid_minutes` into `CompareDay`, `row.paid_minutes` into `CompareRow`, and `clocked.paid_minutes` into `CompareWeek`; leave `delta` on `day.clocked_minutes`. In `person_week`, `lunch_minutes`/`paid_minutes` come from `clocked_day` (0 when absent), and `total_paid_minutes=sum(d.paid_minutes for d in out)`. Add every field as `int`/`bool` to the matching schema; do not add defaults.

- [ ] **Step 4: Run, expect PASS**: the four files plus `tests/test_attendance_router.py`.
- [ ] **Step 5: Commit**: `feat(attendance): lunch and paid minutes on the week, profile, and CSV`.

---

### Task 9: Frontend: paid everywhere, lunch line

**Files:**
- Modify: `static/api.js` (`apiEditAttendancePunch` gains `lunchWaived`)
- Modify: `static/views/hubAttendanceHours.js` (heading, lunch line, auto-closed note, grid cells/totals → paid, `onToggleLunch` wiring)
- Modify: `static/views/hubAttendanceDay.js` (lines 52, 60, 104 → paid; pass `onToggleLunch`; wire `.hub-hours-lunch` like `.hub-hours-clear-review` at 152)
- Modify: `static/views/hubTimesheetsTab.js:~167` (`onToggleLunch` in `writes`)
- Modify: `static/views/userProfile.js` (`dayHtml` + `weekHtml` print paid; lunch note in `dayBodyHtml`; "auto-closed at midnight" punch note)
- Modify: `static/styles.css` (`.hub-hours-lunch-line`, matching `.hub-hours-drilldown-row`)
- Test: `tests/frontend/views/hubAttendanceHours.test.js`, `hubAttendanceDay.test.js`, `userProfile.test.js`, `tests/frontend/helpers/endpointTable.js`, `tests/frontend/unit/api.shapes.test.js`

**Interfaces:**
- Consumes: day `lunch_minutes`, `lunch_waived`, `paid_minutes`; row/week `paid_minutes`; `totals_by_day[].paid_minutes`; person `total_paid_minutes`.
- Produces: `onToggleLunch(punchId: string, waived: boolean)`.

- [ ] **Step 1: Write the failing tests**

```js
import { drilldownHtml } from "../../../backend/static/views/hubAttendanceHours.js"; // match the file's import style

const punch = (id, extra = {}) => ({ id, started_at: "2026-09-14T12:00:00Z",
  ended_at: "2026-09-14T20:00:00Z", start_source: "manual", end_source: "manual",
  needs_review: false, minutes: 480, carried: false, open: false, lunch_waived: false, ...extra });
const day = (extra = {}) => ({ date: "2026-09-14", clocked_minutes: 480, lunch_minutes: 30,
  lunch_waived: false, paid_minutes: 450, needs_review: false, has_open: false,
  punches: [punch("p1")], ...extra });

it("prints paid in the heading and a removable lunch line", () => {
  const html = drilldownHtml(day(), "Ann", { canEdit: true });
  expect(html).toContain("7:30 paid");
  expect(html).toContain("Lunch −0:30");
  expect(html).toMatch(/data-punch="p1"[^>]*data-waive="true"[^>]*>Remove lunch/);
});

it("offers Restore lunch on a waived day", () => {
  const html = drilldownHtml(day({ lunch_minutes: 0, lunch_waived: true, paid_minutes: 480 }), "Ann", { canEdit: true });
  expect(html).toContain("No lunch deducted");
  expect(html).toMatch(/data-waive="false"[^>]*>Restore lunch/);
});

it("prints no lunch line under the threshold", () => {
  expect(drilldownHtml(day({ clocked_minutes: 300, lunch_minutes: 0, paid_minutes: 300 }), "Ann", {}))
    .not.toContain("unch");
});

it("lunch button targets the first non-carried punch", () => {
  const html = drilldownHtml(day({ punches: [punch("p0", { carried: true }), punch("p1")] }), "Ann", { canEdit: true });
  expect(html).toMatch(/hub-hours-lunch" data-punch="p1"/);
});

it("labels a midnight-closed punch", () => {
  const html = drilldownHtml(day({ punches: [punch("p1", { end_source: "auto_clock_out", needs_review: true })] }), "Ann", { canEdit: true });
  expect(html).toContain("auto-closed at midnight");
});
```

Also: the grid cell for that day prints `7:30`; clicking Remove lunch calls `onToggleLunch("p1", true)` (mount with a spy, following the file's existing clear-review test). In `userProfile.test.js`, the day summary prints paid and the body contains `lunch −0:30`. In `endpointTable.js`, `apiEditAttendancePunch` with `{ lunchWaived: true }` sends `{ lunch_waived: true }`. Fixtures in `hubAttendanceDay.test.js` and the existing hours tests need `paid_minutes`/`lunch_minutes` added.

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.** In `api.js`:

```js
export async function apiEditAttendancePunch(punchId, { startedAt, endedAt, needsReview, lunchWaived, reason = "" } = {}) {
  ...
  if (typeof lunchWaived === "boolean") body.lunch_waived = lunchWaived;
```

In `hubAttendanceHours.js`:

```js
// L2: the waiver rides on the day's first punch it owns. A carried punch
// belongs to yesterday, so it never carries today's lunch.
function lunchLineHtml(day, canEdit) {
  const anchor = day.punches.find((p) => !p.carried);
  let text;
  let waive;
  if (day.lunch_minutes > 0) { text = `Lunch −${formatHm(day.lunch_minutes)}`; waive = true; }
  else if (day.lunch_waived) { text = "No lunch deducted"; waive = false; }
  else return "";
  const button = canEdit && anchor
    ? `<button type="button" class="hub-link-btn hub-hours-lunch" data-punch="${escapeHtml(anchor.id)}" data-waive="${waive}">${waive ? "Remove lunch" : "Restore lunch"}</button>`
    : "";
  return `<div class="hub-hours-drilldown-row hub-hours-lunch-line"><span>${text}</span><span>${button}</span></div>`;
}
```

In `drilldownHtml`, the heading becomes `${formatHm(day.paid_minutes)} paid`, and `${lunchLineHtml(day, canEdit)}` goes after `${rows}`. In `punchRowHtml`, push `"auto-closed at midnight"` when `punch.end_source === "auto_clock_out"`, before `needs review`. Grid lines 161–193: `clocked_minutes` → `paid_minutes` (the placeholder day gains `paid_minutes: 0, lunch_minutes: 0, lunch_waived: false`), `row.total_minutes` → `row.paid_minutes`, `entry.minutes` → `entry.paid_minutes`, `payload.total_minutes` → `payload.paid_minutes`, and aria "clocked" → "paid". Wire the button:

```js
    container.querySelectorAll(".hub-hours-lunch").forEach((button) => {
      button.addEventListener("click", () =>
        onToggleLunch?.(button.dataset.punch, button.dataset.waive === "true"));
    });
```

In `hubTimesheetsTab.js` `writes`:

```js
      onToggleLunch: (id, waived) => write(panelEl, () => apiEditAttendancePunch(id, {
        lunchWaived: waived,
        reason: waived ? "Lunch removed by an Admin" : "Lunch restored by an Admin",
      })),
```

Pass it through to `mountHubAttendanceHours` and `mountHubAttendanceDayPage` the way `onClearReview` goes. `hubTimesheetLeaderboard.js` stays untouched (L3: uncharged stays gross).

`userProfile.js`: `dayBand(day.paid_minutes)`, `formatHm(day.paid_minutes)`, `formatHm(payload.total_paid_minutes)`, and a column header "Clocked" → "Paid" if one exists. `dayBodyHtml` adds `` day.lunch_minutes ? `<p class="hint">lunch −${formatHm(day.lunch_minutes)}</p>` : "" `` before the lists. The punch notes gain `"auto-closed at midnight"` for `auto_clock_out`.

- [ ] **Step 4: Run, expect PASS**: `npx vitest run tests/frontend/views/hubAttendanceHours.test.js tests/frontend/views/hubAttendanceDay.test.js tests/frontend/views/userProfile.test.js tests/frontend/views/hubTimesheetLeaderboard.test.js tests/frontend/unit/api.shapes.test.js`.
- [ ] **Step 5: Commit**: `feat(users): Hours, day page, and profile print paid; Admins remove or restore lunch`.

---

### Task 10: P2 docs

**Files:** `docs/current-state.md` (`attendance_punches` gains `lunch_waived`; lunch rule L1–L4), `docs/endpoint-map.md` (PATCH body, `AttendanceWeekDay`/row/total shapes, person-week shape, CSV metric list), `docs/open-work.md` (IMP-041 closed or narrowed to the night-shift non-goal).

- [ ] **Step 1:** Write current truth, one line each: the lunch constants, paid vs. gross (delta stays gross), the waiver on the day's first non-carried punch, and that the waiver never clears review.
- [ ] **Step 2: Commit**: `docs(attendance): flat lunch and paid minutes are current truth`.

Then stop for the user's in-app check. Do not push.
