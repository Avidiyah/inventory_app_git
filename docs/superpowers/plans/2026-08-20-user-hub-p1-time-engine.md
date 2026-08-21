# User Hub P1 — Time Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the correct-by-construction time engine behind the User Hub — Central-day overlap arithmetic, the daily labor aggregate, the global stale-session sweep, and `GET /hub` — with no UI at all.

**Architecture:** A pure module (`domain/labor_day.py`) owns every day-boundary and overlap rule and is fully testable without a database. A service (`services/labor_summary.py`) turns `work_order_labor_sessions` + `work_order_labor` rows into one day's tracked minutes, timeline, and adjustments by calling that pure module. A second service (`services/hub.py`) composes the personal payload — counts, the `Start on…` picker, the clock, tools out — and one thin router exposes it at `GET /hub` behind `get_current_user`. The 12-hour cap sweep is widened from "one work order" to "one person, or everyone", reusing the existing `_apply_session_cap` rather than reimplementing it.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Pydantic v2, `zoneinfo`, pytest. Python 3.13 (`backend/venv`). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-20-user-hub-design.md` — read §3 (Time semantics), §4.1–4.2 (Architecture), §7 (`GET /hub` contract), §10 (Edge cases), §11 (Testing), §12 (Phasing). The 18 decisions in §2 are locked; this plan implements D1, D2, D5, D15 and nothing else.

---

## Global Constraints

- **P1 ships no UI.** No file under `backend/static/` is touched. No `pages/*.html` fragment is added to `SHELL_PARTS` — that is P2's job (spec §4.6). Do not add one; a fragment with no view module attached is dead markup.
- **Work on a branch.** `git checkout -b user-hub-p1-time-engine` before Task 1. Merging to `main` deploys to production (repo CI gate) — the merge is the owner's call, not the implementer's. Commit freely on the branch.
- **Day boundary is `America/Chicago`, calendar midnight to midnight** (D1). 8:00 AM is a display anchor only and never appears in arithmetic in this phase.
- **Derive on read** (D2). No new table, no migration, no scheduler. `work_order_labor_sessions` is already the audit record.
- **Tracked ≠ session ≠ billed** (spec §3.1). This phase produces **tracked** minutes only. No hub surface may display a billed figure under a "time worked" label, and nothing in this phase may call `wo.billed_labor_minutes` or `wo.labor_charge`.
- **`overlap_minutes` must not floor at 1.** `wo.capped_session_minutes` floors at 1 deliberately for its own job; flooring here would invent a minute on every midnight crossing (spec §3.3). The two functions are allowed to disagree.
- **Adjustments count toward every displayed total** (D15), and are always reported on their own line with the recorder's name — never silently merged into tracked time (D5).
- **Layer chain is fixed:** `routers → schemas/services → domain/models → database`. No aggregation logic in a router. No FastAPI or SQLAlchemy import in `app/domain/`.
- **Role gates are declarative.** `auth_deps.py:73` is the only place a role 403 is raised. `GET /hub` takes `Depends(get_current_user)` and no `require_min_role` — every authenticated role gets the personal block (spec §4.1).
- **Backend tests run from `backend/`** with `./venv/Scripts/python.exe -m pytest`. Pure tests (Tasks 1, 2, 5a) need nothing. DB-backed tests (Tasks 3, 4, 5b, 6) need the local Postgres on port 8801 reachable per `.env`'s `DATABASE_URL`; without it the `db` fixture skips.
- **Never truncate an existing file.** Every "Modify" step below is an append or an insertion. Read first, edit in place.
- **Commit message style:** `feat(user-hub): …` / `docs(user-hub): …`, matching the repo's conventional-commit history.

---

## Spec corrections carried by this plan

Two places where the spec's prose is thinner than its own contract. Both are recorded here rather than fixed silently, and neither reopens a locked decision.

**1. The running clock needs a second anchor (`day_counting_from`).** Spec §6.1 has the client compute today's live total from `closed_minutes_today + (now − started_at)`. That double-counts across midnight: a session that started 11:30 PM yesterday and is still running at 00:30 today has contributed **30** minutes to today, not 60. D1's midnight split *requires* the day figure to count from `max(started_at, day_start)`. The payload therefore carries **both**:

- `started_at` — what the clock widget shows as "started 8:12 AM" and ticks session-elapsed from.
- `day_counting_from` — what today's total ticks from. Equal to `started_at` on an ordinary day; equal to midnight Central on a session inherited from yesterday.

`running_minutes_today` is also sent so a non-ticking consumer (and every test) gets the number without doing the arithmetic.

**2. `tools_out` needs a `since`, which `user_custody` does not return.** Spec §5.2 says tool custody comes from `services/tools.py::user_custody` "unchanged", but §7's contract requires a `since` field and that function returns `(tool_id, name, barcode, quantity)`. Task 5 adds a sibling `user_custody_detail` that includes `since`; `user_custody` keeps its exact signature and every existing caller (user archival, force check-in) is untouched.

Two smaller gap-fills, noted so a reviewer does not read them as invention:

- **`startable` carries the raw place fields, not a composed `location` string.** There is no server-side location composer; `static/views/workOrders.js::placeMeta` composes `community` / `building_number` / `unit_number` and falls back to the free-text `location` column. The payload sends all four so P2 reuses that one composer.
- **`startable` ordering extends the spec's two-element rule.** §5.1 says "In-Progress first, then Assigned"; all four of `_TRACKING_START_STATUSES` are startable, so the order is In-Progress → On-Hold → Assigned → Created, then by work-order number.

---

### Task 1: Central day boundaries

Pure day arithmetic — the foundation every number in every later phase rests on. No database, no framework.

**Files:**
- Create: `backend/app/domain/labor_day.py`
- Test: `backend/tests/test_labor_day.py` (create)

**Interfaces:**
- Consumes: nothing (first task).
- Produces:
  - `labor_day.CENTRAL: ZoneInfo` — `ZoneInfo("America/Chicago")`, the same zone `domain/work_orders.py::NOTE_TIMEZONE` uses.
  - `labor_day.DISPLAY_ANCHOR_HOUR: int` — `8`. Declared now, consumed by P2's timeline strip.
  - `labor_day.as_utc(instant: datetime) -> datetime` — naive in, UTC-aware out.
  - `labor_day.day_bounds(day: date, *, tz=CENTRAL) -> tuple[datetime, datetime]` — the UTC instants `[start, end)` bracketing one Central calendar day.
  - `labor_day.central_date_of(instant: datetime, *, tz=CENTRAL) -> date`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_labor_day.py`:

```python
"""Pure tests for Central-day arithmetic.

Layer: unit (no DB, no HTTP). Every hub number in every later phase is
derived from these four functions, so they are tested exhaustively here --
including both DST transitions, which are the cases a hand-rolled
`timedelta(hours=24)` would get wrong.

2026 US DST transitions used below: spring forward Sunday 2026-03-08
(a 23-hour Central day), fall back Sunday 2026-11-01 (a 25-hour day).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, datetime, timedelta, timezone

from app.domain import labor_day


def test_summer_day_bounds_are_five_hours_behind_utc():
    # CDT is UTC-5, so a Central day runs 05:00Z to 05:00Z.
    start, end = labor_day.day_bounds(date(2026, 8, 20))
    assert start == datetime(2026, 8, 20, 5, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 8, 21, 5, 0, tzinfo=timezone.utc)


def test_winter_day_bounds_are_six_hours_behind_utc():
    # CST is UTC-6. A fixed offset would put this an hour wrong.
    start, end = labor_day.day_bounds(date(2026, 1, 15))
    assert start == datetime(2026, 1, 15, 6, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 1, 16, 6, 0, tzinfo=timezone.utc)


def test_spring_forward_day_is_twenty_three_hours_long():
    start, end = labor_day.day_bounds(date(2026, 3, 8))
    assert end - start == timedelta(hours=23)


def test_fall_back_day_is_twenty_five_hours_long():
    start, end = labor_day.day_bounds(date(2026, 11, 1))
    assert end - start == timedelta(hours=25)


def test_days_tile_with_no_gap_or_overlap():
    _, first_end = labor_day.day_bounds(date(2026, 8, 20))
    second_start, _ = labor_day.day_bounds(date(2026, 8, 21))
    assert first_end == second_start


def test_central_date_of_rolls_back_before_local_midnight():
    # 04:59Z on the 21st is 11:59 PM Central on the 20th.
    assert labor_day.central_date_of(
        datetime(2026, 8, 21, 4, 59, tzinfo=timezone.utc)
    ) == date(2026, 8, 20)
    assert labor_day.central_date_of(
        datetime(2026, 8, 21, 5, 0, tzinfo=timezone.utc)
    ) == date(2026, 8, 21)


def test_central_date_of_reads_a_naive_instant_as_utc():
    # Matches `work_orders.format_note_timestamp`: the app stores UTC, and a
    # naive value that slipped through must not be read as local time.
    assert labor_day.central_date_of(datetime(2026, 8, 21, 4, 59)) == date(2026, 8, 20)


def test_central_date_of_agrees_with_day_bounds_at_both_edges():
    day = date(2026, 11, 1)
    start, end = labor_day.day_bounds(day)
    assert labor_day.central_date_of(start) == day
    assert labor_day.central_date_of(end - timedelta(microseconds=1)) == day
    assert labor_day.central_date_of(end) == date(2026, 11, 2)


def test_as_utc_leaves_an_aware_instant_alone():
    aware = datetime(2026, 8, 20, 13, 12, tzinfo=timezone.utc)
    assert labor_day.as_utc(aware) is aware


def test_as_utc_stamps_a_naive_instant_as_utc():
    assert labor_day.as_utc(datetime(2026, 8, 20, 13, 12)) == datetime(
        2026, 8, 20, 13, 12, tzinfo=timezone.utc
    )


def test_display_anchor_is_eight_am():
    assert labor_day.DISPLAY_ANCHOR_HOUR == 8
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && ./venv/Scripts/python.exe -m pytest tests/test_labor_day.py -v
```

Expected: collection error — `ModuleNotFoundError: No module named 'app.domain.labor_day'`.

- [ ] **Step 3: Write the implementation**

Create `backend/app/domain/labor_day.py`:

```python
"""Pure Central-calendar-day arithmetic for tracked labor.

Layer: domain. No FastAPI, no SQLAlchemy, no database -- the same rule
every other module in this package follows, and the reason the whole of
the hub's time engine can be tested without Postgres.

A "day" here is `[00:00:00, 24:00:00)` in `America/Chicago`, the same zone
`domain.work_orders.NOTE_TIMEZONE` stamps the note log with, so the hub's
day and the note timeline never disagree about which day a stop belongs
to. DST is `zoneinfo`'s problem, not ours: a spring-forward day is 23
hours and a fall-back day is 25, and every function below works on
absolute UTC instants so the arithmetic is correct for both.

Deliberately *not* here: any notion of billing. This module produces
**tracked** minutes -- real wall-clock overlap -- which is a different
number from `work_orders.capped_session_minutes` (floors at 1, caps at
720) and from `work_orders.billed_labor_minutes` (rounds up to 30). See
the spec's Time Semantics section; blurring the three is the single most
likely way for the hub to ship subtly wrong.
"""

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

CENTRAL = ZoneInfo("America/Chicago")

# 8:00am. A *display* anchor for the timeline strip -- where the axis starts
# unless somebody clocked in earlier -- and never a day boundary. Consumed by
# the frontend in a later phase; declared here so the constant has one home.
DISPLAY_ANCHOR_HOUR = 8


def as_utc(instant: datetime) -> datetime:
    """Return `instant` as an aware UTC datetime.

    A naive value is *read* as UTC rather than as local time, matching
    `work_orders.format_note_timestamp`: every timestamp this app stores is
    UTC, and treating a stray naive one as local would silently shift a
    session by five or six hours.
    """
    if instant.tzinfo is None:
        return instant.replace(tzinfo=timezone.utc)
    return instant


def day_bounds(day: date, *, tz: ZoneInfo = CENTRAL) -> tuple[datetime, datetime]:
    """The UTC instants bracketing one Central calendar day, half-open.

    Built from local midnight on `day` and local midnight on the next day and
    then converted, rather than by adding 24 hours -- which is what makes the
    result 23 or 25 hours long across a DST transition instead of quietly
    wrong. Neither endpoint is ever ambiguous: US DST shifts at 2:00 AM local,
    so midnight is unaffected in both directions.
    """
    start_local = datetime.combine(day, time.min, tzinfo=tz)
    end_local = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def central_date_of(instant: datetime, *, tz: ZoneInfo = CENTRAL) -> date:
    """Which Central calendar day `instant` falls on."""
    return as_utc(instant).astimezone(tz).date()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && ./venv/Scripts/python.exe -m pytest tests/test_labor_day.py -v
```

Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/domain/labor_day.py backend/tests/test_labor_day.py
git commit -m "feat(user-hub): add Central-day boundary arithmetic"
```

---

### Task 2: Overlap and the midnight split

The arithmetic every later number depends on. Interval overlap, not a `started_at` range filter — a session running 11:30 PM Monday to 12:30 AM Tuesday gives 30 minutes to each day.

**Files:**
- Modify: `backend/app/domain/labor_day.py` (append two functions)
- Test: `backend/tests/test_labor_day.py` (append)

**Interfaces:**
- Consumes: `labor_day.as_utc`, `labor_day.day_bounds`, `labor_day.central_date_of` from Task 1.
- Produces:
  - `labor_day.overlap_minutes(start: datetime, end: datetime | None, window_start: datetime, window_end: datetime, *, now: datetime) -> int` — whole minutes a session occupies inside a window. `end=None` means still running and `now` stands in. Returns `0` when the session lies wholly outside the window. Does **not** floor at 1.
  - `labor_day.split_by_day(start: datetime, end: datetime | None, *, now: datetime, tz=CENTRAL) -> list[tuple[date, int]]` — one `(central_date, minutes)` pair per day the session actually contributes to, ascending by date. Days contributing 0 minutes are omitted.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_labor_day.py`:

```python
# --- overlap and the midnight split -------------------------------------

# The 2026-08-20 Central day, as UTC instants (CDT, UTC-5).
DAY = date(2026, 8, 20)
DAY_START = datetime(2026, 8, 20, 5, 0, tzinfo=timezone.utc)
DAY_END = datetime(2026, 8, 21, 5, 0, tzinfo=timezone.utc)


def _utc(month, day, hour, minute=0, second=0):
    return datetime(2026, month, day, hour, minute, second, tzinfo=timezone.utc)


def test_overlap_of_a_session_wholly_inside_the_window():
    # 8:12 AM - 10:31 AM Central == 13:12Z - 15:31Z. 2h19m.
    assert (
        labor_day.overlap_minutes(
            _utc(8, 20, 13, 12), _utc(8, 20, 15, 31), DAY_START, DAY_END,
            now=_utc(8, 20, 16, 0),
        )
        == 139
    )


def test_a_running_session_counts_up_to_now():
    assert (
        labor_day.overlap_minutes(
            _utc(8, 20, 13, 12), None, DAY_START, DAY_END, now=_utc(8, 20, 15, 59)
        )
        == 167
    )


def test_a_running_session_is_clamped_to_the_window_end():
    # `now` is tomorrow; today's share still stops at today's midnight.
    # 13:12Z to 05:00Z next day = 15h48m = 948 minutes.
    assert (
        labor_day.overlap_minutes(
            _utc(8, 20, 13, 12), None, DAY_START, DAY_END, now=_utc(8, 21, 12, 0)
        )
        == 948
    )


def test_a_session_that_started_before_the_window_is_clipped_to_it():
    # 23:30 Central Wed -> 00:30 Central Thu, measured against Thursday.
    assert (
        labor_day.overlap_minutes(
            _utc(8, 20, 4, 30), _utc(8, 20, 5, 30), DAY_START, DAY_END,
            now=_utc(8, 20, 6, 0),
        )
        == 30
    )


def test_a_session_wholly_before_the_window_contributes_nothing():
    assert (
        labor_day.overlap_minutes(
            _utc(8, 19, 14, 0), _utc(8, 19, 16, 0), DAY_START, DAY_END,
            now=_utc(8, 20, 16, 0),
        )
        == 0
    )


def test_a_session_wholly_after_the_window_contributes_nothing():
    assert (
        labor_day.overlap_minutes(
            _utc(8, 21, 14, 0), _utc(8, 21, 16, 0), DAY_START, DAY_END,
            now=_utc(8, 21, 16, 0),
        )
        == 0
    )


def test_a_session_that_merely_touches_the_boundary_contributes_nothing():
    # Ends exactly at the window's start instant. Nothing lies inside it.
    assert (
        labor_day.overlap_minutes(
            _utc(8, 20, 3, 0), DAY_START, DAY_START, DAY_END, now=_utc(8, 20, 6, 0)
        )
        == 0
    )


def test_overlap_does_not_floor_at_one_minute():
    # Deliberately unlike `work_orders.capped_session_minutes`, which floors at
    # 1 so a short visit survives `validate_labor_minutes`. Flooring here would
    # invent a minute on every midnight crossing.
    assert (
        labor_day.overlap_minutes(
            _utc(8, 20, 13, 0, 0), _utc(8, 20, 13, 0, 20), DAY_START, DAY_END,
            now=_utc(8, 20, 14, 0),
        )
        == 0
    )


def test_overlap_tolerates_an_end_before_its_start():
    # Defensive: a clock-skewed row must read as zero, never as negative time.
    assert (
        labor_day.overlap_minutes(
            _utc(8, 20, 15, 0), _utc(8, 20, 14, 0), DAY_START, DAY_END,
            now=_utc(8, 20, 16, 0),
        )
        == 0
    )


def test_overlap_reads_naive_timestamps_as_utc():
    assert (
        labor_day.overlap_minutes(
            datetime(2026, 8, 20, 13, 12),
            datetime(2026, 8, 20, 15, 31),
            DAY_START,
            DAY_END,
            now=_utc(8, 20, 16, 0),
        )
        == 139
    )


def test_split_by_day_divides_a_midnight_crossing():
    # 23:30 Central Thu -> 00:30 Central Fri.
    assert labor_day.split_by_day(
        _utc(8, 21, 4, 30), _utc(8, 21, 5, 30), now=_utc(8, 21, 6, 0)
    ) == [(date(2026, 8, 20), 30), (date(2026, 8, 21), 30)]


def test_split_by_day_omits_a_day_that_gains_nothing():
    # Ends exactly at midnight: Friday is not touched.
    assert labor_day.split_by_day(
        _utc(8, 21, 3, 0), _utc(8, 21, 5, 0), now=_utc(8, 21, 6, 0)
    ) == [(date(2026, 8, 20), 120)]


def test_split_by_day_follows_a_running_session_to_now():
    assert labor_day.split_by_day(
        _utc(8, 21, 4, 30), None, now=_utc(8, 21, 6, 0)
    ) == [(date(2026, 8, 20), 30), (date(2026, 8, 21), 60)]


def test_split_by_day_covers_every_day_a_long_session_spans():
    # 01:00 Central Thu -> 01:00 Central Sat: 23h + 24h + 1h.
    pairs = labor_day.split_by_day(
        _utc(8, 20, 6, 0), _utc(8, 22, 6, 0), now=_utc(8, 22, 7, 0)
    )
    assert [d for d, _ in pairs] == [
        date(2026, 8, 20),
        date(2026, 8, 21),
        date(2026, 8, 22),
    ]
    assert [m for _, m in pairs] == [1380, 1440, 60]
    assert sum(m for _, m in pairs) == 48 * 60


def test_split_by_day_returns_nothing_for_a_zero_length_session():
    instant = _utc(8, 20, 13, 0)
    assert labor_day.split_by_day(instant, instant, now=_utc(8, 20, 14, 0)) == []


def test_a_full_spring_forward_day_totals_twenty_three_hours():
    start, end = labor_day.day_bounds(date(2026, 3, 8))
    assert labor_day.split_by_day(start, end, now=end) == [(date(2026, 3, 8), 23 * 60)]


def test_a_full_fall_back_day_totals_twenty_five_hours():
    start, end = labor_day.day_bounds(date(2026, 11, 1))
    assert labor_day.split_by_day(start, end, now=end) == [
        (date(2026, 11, 1), 25 * 60)
    ]


def test_a_session_spanning_the_spring_forward_gap_loses_the_skipped_hour():
    # 1:30 AM CST -> 3:30 AM CDT is one real hour of work, because 2:00-2:59
    # did not happen. Instant-based arithmetic gets this right for free.
    pairs = labor_day.split_by_day(
        datetime(2026, 3, 8, 7, 30, tzinfo=timezone.utc),
        datetime(2026, 3, 8, 8, 30, tzinfo=timezone.utc),
        now=datetime(2026, 3, 8, 9, 0, tzinfo=timezone.utc),
    )
    assert pairs == [(date(2026, 3, 8), 60)]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && ./venv/Scripts/python.exe -m pytest tests/test_labor_day.py -v
```

Expected: the 11 Task-1 tests pass; the 18 new ones fail with `AttributeError: module 'app.domain.labor_day' has no attribute 'overlap_minutes'`.

- [ ] **Step 3: Write the implementation**

Append to `backend/app/domain/labor_day.py`:

```python
def overlap_minutes(
    start: datetime,
    end: Optional[datetime],
    window_start: datetime,
    window_end: datetime,
    *,
    now: datetime,
) -> int:
    """Whole minutes a session occupies inside a window.

    `end=None` means the clock is still running and `now` stands in for it --
    which is what makes a running session's contribution climb through the
    day. Returns 0 when the session lies wholly outside the window, and 0 when
    it merely touches a boundary: a stop at exactly midnight gives the next day
    nothing.

    **No floor at 1.** `work_orders.capped_session_minutes` floors at 1 so a
    twenty-second visit survives `validate_labor_minutes`; a daily timesheet
    has no such constraint, and flooring here would invent a minute on every
    midnight crossing. The two functions are allowed to disagree -- each is
    right for its own job.

    Rounding happens **once per (session, window) pair**, on the clipped
    span's total seconds. Summing a day's pairs can therefore differ from the
    session's own `minutes` column by up to a minute per crossing. That is
    accepted, and written down so a future reader does not treat it as a bug.
    Rounding is Python's `round` (half-to-even), the same rule
    `capped_session_minutes` uses.
    """
    stop = end if end is not None else now
    begin = max(as_utc(start), window_start)
    finish = min(as_utc(stop), window_end)
    if finish <= begin:
        return 0
    return round((finish - begin).total_seconds() / 60)


def split_by_day(
    start: datetime,
    end: Optional[datetime],
    *,
    now: datetime,
    tz: ZoneInfo = CENTRAL,
) -> list[tuple[date, int]]:
    """One `(central_date, minutes)` pair per day the session contributes to.

    Ascending by date. A day the session only touches -- a stop at exactly
    midnight, a start at exactly midnight -- contributes zero and is omitted
    rather than reported as an empty day, because "the session touched Friday"
    and "the session earned Friday nothing" are the same statement and the
    caller should not have to filter.
    """
    stop = end if end is not None else now
    first = central_date_of(start, tz=tz)
    last = central_date_of(stop, tz=tz)
    if last < first:
        return []

    pairs: list[tuple[date, int]] = []
    day = first
    while day <= last:
        window_start, window_end = day_bounds(day, tz=tz)
        minutes = overlap_minutes(start, end, window_start, window_end, now=now)
        if minutes > 0:
            pairs.append((day, minutes))
        day += timedelta(days=1)
    return pairs
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && ./venv/Scripts/python.exe -m pytest tests/test_labor_day.py -v
```

Expected: 29 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/domain/labor_day.py backend/tests/test_labor_day.py
git commit -m "feat(user-hub): add session/day overlap and midnight split"
```

---

### Task 3: The global stale-session sweep

Widen the 12-hour cap sweep from "one work order" to "one person, or everyone" (spec §3.5), so `GET /hub` can repair a forgotten clock before reading it. Reuses `_apply_session_cap` rather than reimplementing the cap.

**Files:**
- Modify: `backend/app/services/work_orders.py` — insert a public alias after `_TRACKING_START_STATUSES` (line ~2069) and a new function after `_apply_session_cap` (line ~2260)
- Test: `backend/tests/test_labor_summary.py` (create — spec §11 puts the sweep tests in the P1 service test file)

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `work_orders_service.sweep_stale_sessions(db: Session, *, technician_id: uuid.UUID | None = None) -> int` — closes every running session older than `LABOR_SESSION_MAX_MINUTES`, scoped to one person or unscoped, and commits if it closed anything. Returns the number of sessions closed.
  - `work_orders_service.TRACKING_START_STATUSES: tuple[str, ...]` — public alias of `_TRACKING_START_STATUSES`, read by `services/hub.py` in Task 6.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_labor_summary.py`:

```python
"""Database tests for the hub's time engine.

Covers the global stale-session sweep (this task) and the daily labor
aggregate (next task). Skips without a reachable Postgres, like every other
`db`-fixture test in this suite.

Seed helpers mirror `tests/test_work_orders_service.py` so the two files read
the same way.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.domain import roles
from app.domain import work_orders as wo
from app.models import (
    User,
    WorkOrder,
    WorkOrderLabor,
    WorkOrderLaborSession,
)
from app.services import auth
from app.services import work_orders as wos


# --- seed helpers --------------------------------------------------------

def _seed_user(db, role=roles.ROLE_TECHNICIAN, *, first_name="Jose", last_name="Rivera"):
    user = User(
        username=f"u-{uuid.uuid4().hex[:10]}",
        first_name=first_name,
        last_name=last_name,
        password_hash=auth.hash_password("hunter2"),
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def _seed_work_order(db, *, created_by, assigned_to=None, number=None):
    return wos.get_or_create_work_order(
        db,
        number=number or f"WO-{uuid.uuid4().hex[:8]}",
        created_by_id=created_by.id,
        assigned_to_id=assigned_to.id if assigned_to else None,
    )


def _seed_session(db, work_order, technician, *, started_at, ended_at=None):
    """A session written straight to the table.

    Bypasses `start_labor_session` on purpose: these tests need exact
    timestamps, including ones in the past, and the service always stamps
    `now`.
    """
    session = WorkOrderLaborSession(
        id=uuid.uuid4(),
        work_order_id=work_order.id,
        technician_id=technician.id,
        started_at=started_at,
        ended_at=ended_at,
    )
    db.add(session)
    db.flush()
    return session


# --- the global sweep ----------------------------------------------------

def test_sweep_closes_a_stale_session_at_the_capped_instant(db):
    tech = _seed_user(db)
    work_order = _seed_work_order(db, created_by=tech, assigned_to=tech)
    started = datetime.now(timezone.utc) - timedelta(hours=20)
    session = _seed_session(db, work_order, tech, started_at=started)

    closed = wos.sweep_stale_sessions(db, technician_id=tech.id)

    assert closed == 1
    db.refresh(session)
    # Closed at start + 720 minutes, NOT at sweep time: the billed figure has
    # to be right even though the flag is late.
    assert session.ended_at == started + timedelta(
        minutes=wo.LABOR_SESSION_MAX_MINUTES
    )
    assert session.auto_closed_at is not None


def test_sweep_writes_a_labor_row_capped_at_twelve_hours(db):
    tech = _seed_user(db)
    work_order = _seed_work_order(db, created_by=tech, assigned_to=tech)
    _seed_session(
        db, work_order, tech, started_at=datetime.now(timezone.utc) - timedelta(hours=20)
    )

    wos.sweep_stale_sessions(db, technician_id=tech.id)

    entries = (
        db.query(WorkOrderLabor)
        .filter(WorkOrderLabor.work_order_id == work_order.id)
        .all()
    )
    assert [e.minutes for e in entries] == [wo.LABOR_SESSION_MAX_MINUTES]


def test_sweep_does_not_auto_hold(db):
    # A supervisor's phone must not buzz because somebody opened a dashboard.
    tech = _seed_user(db)
    work_order = _seed_work_order(db, created_by=tech, assigned_to=tech)
    work_order.status = wo.STATUS_IN_PROGRESS
    db.flush()
    _seed_session(
        db, work_order, tech, started_at=datetime.now(timezone.utc) - timedelta(hours=20)
    )

    wos.sweep_stale_sessions(db, technician_id=tech.id)

    db.refresh(work_order)
    assert work_order.status == wo.STATUS_IN_PROGRESS


def test_sweep_leaves_a_fresh_session_running(db):
    tech = _seed_user(db)
    work_order = _seed_work_order(db, created_by=tech, assigned_to=tech)
    session = _seed_session(
        db, work_order, tech, started_at=datetime.now(timezone.utc) - timedelta(hours=2)
    )

    assert wos.sweep_stale_sessions(db, technician_id=tech.id) == 0
    db.refresh(session)
    assert session.ended_at is None


def test_sweep_is_idempotent(db):
    tech = _seed_user(db)
    work_order = _seed_work_order(db, created_by=tech, assigned_to=tech)
    _seed_session(
        db, work_order, tech, started_at=datetime.now(timezone.utc) - timedelta(hours=20)
    )

    assert wos.sweep_stale_sessions(db, technician_id=tech.id) == 1
    assert wos.sweep_stale_sessions(db, technician_id=tech.id) == 0


def test_a_scoped_sweep_leaves_other_peoples_clocks_alone(db):
    mine = _seed_user(db)
    theirs = _seed_user(db, first_name="Marisol", last_name="Chen")
    work_order = _seed_work_order(db, created_by=mine, assigned_to=mine)
    stale_other = _seed_session(
        db, work_order, theirs, started_at=datetime.now(timezone.utc) - timedelta(hours=20)
    )
    _seed_session(
        db, work_order, mine, started_at=datetime.now(timezone.utc) - timedelta(hours=20)
    )

    assert wos.sweep_stale_sessions(db, technician_id=mine.id) == 1
    db.refresh(stale_other)
    assert stale_other.ended_at is None


def test_an_unscoped_sweep_closes_every_stale_session(db):
    mine = _seed_user(db)
    theirs = _seed_user(db, first_name="Marisol", last_name="Chen")
    work_order = _seed_work_order(db, created_by=mine, assigned_to=mine)
    _seed_session(
        db, work_order, mine, started_at=datetime.now(timezone.utc) - timedelta(hours=20)
    )
    _seed_session(
        db, work_order, theirs, started_at=datetime.now(timezone.utc) - timedelta(hours=20)
    )

    assert wos.sweep_stale_sessions(db) == 2


def test_tracking_start_statuses_is_exported_for_the_hub_picker(db):
    # The hub's `Start on...` picker must offer exactly what
    # `start_labor_session` accepts, so it reads the same tuple.
    assert wos.TRACKING_START_STATUSES == (
        wo.STATUS_CREATED,
        wo.STATUS_ASSIGNED,
        wo.STATUS_IN_PROGRESS,
        wo.STATUS_ON_HOLD,
    )
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && ./venv/Scripts/python.exe -m pytest tests/test_labor_summary.py -v
```

Expected: 8 failures with `AttributeError: module 'app.services.work_orders' has no attribute 'sweep_stale_sessions'`. If they **skip** instead, the local Postgres on port 8801 is not running — start it before continuing; the sweep cannot be verified without it.

- [ ] **Step 3: Add the public status alias**

In `backend/app/services/work_orders.py`, immediately after the `_TRACKING_START_STATUSES` tuple closes (line ~2069), insert:

```python
# Public alias. The hub builds its `Start on...` picker from exactly the
# statuses this path accepts, so the picker can never offer a row that
# `start_labor_session` would then refuse. One tuple, two readers.
TRACKING_START_STATUSES = _TRACKING_START_STATUSES
```

- [ ] **Step 4: Write the sweep**

In `backend/app/services/work_orders.py`, immediately after `_apply_session_cap` returns (line ~2260), insert:

```python
def sweep_stale_sessions(
    db: Session, *, technician_id: Optional[uuid.UUID] = None
) -> int:
    """Close every over-cap running session, for one person or for everyone.

    `_apply_session_cap` repairs one work order, lazily, whenever somebody
    opens it -- which never fires for a session on a row nobody happens to
    look at. The hub is the first surface that reads sessions *across* work
    orders, so it is the first that can sweep them all, and it must: a
    technician who forgot to clock out on Tuesday would otherwise open their
    hub on Wednesday to a twenty-hour running clock spanning two days, a
    number that is both alarming and wrong.

    Scoped to `technician_id`, the cost is bounded to **at most one row** --
    the partial unique index permits one running session per person, so this
    is a single indexed lookup, not a scan. Unscoped, it is the whole
    company's running clocks, which is a handful.

    Two properties inherited from `_apply_session_cap`, both load-bearing:

    - **No auto-hold.** A status change (and the supervisor's phone buzzing)
      as a side effect of somebody opening a dashboard would be indefensible.
    - **The capped instant is authoritative.** A swept session still closes at
      `started_at + 720min`, so the billed figure is right and only the
      `auto_closed_at` flag is late.

    Idempotent, and safe against a concurrent caller: each work order is
    locked with `FOR UPDATE` before its sessions are touched, and rows are
    locked in a stable order so two dashboards loading at once cannot
    deadlock. A second caller simply finds nothing left to close.

    Returns the number of sessions closed, so the caller can log or skip work.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(
        minutes=wo.LABOR_SESSION_MAX_MINUTES
    )
    query = db.query(WorkOrderLaborSession.work_order_id).filter(
        WorkOrderLaborSession.ended_at.is_(None),
        WorkOrderLaborSession.started_at < cutoff,
    )
    if technician_id is not None:
        query = query.filter(WorkOrderLaborSession.technician_id == technician_id)
    work_order_ids = sorted({row[0] for row in query.all()}, key=str)

    closed = 0
    for work_order_id in work_order_ids:
        work_order = _get_locked(db, work_order_id)
        if work_order is None:
            continue
        # Counted before the sweep because `_apply_session_cap` reports only
        # whether anything changed. It recomputes the same list against the
        # now-locked row, which cannot have moved underneath us.
        stale = _stale_running_sessions(db, work_order)
        if not stale:
            continue
        closed += len(stale)
        _apply_session_cap(db, work_order)
    if closed:
        db.commit()
    return closed
```

Verify `uuid`, `Optional`, `datetime`, `timedelta`, `timezone`, and `WorkOrderLaborSession` are already imported at the top of the module — they are, but confirm rather than assume.

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd backend && ./venv/Scripts/python.exe -m pytest tests/test_labor_summary.py -v
```

Expected: 8 passed.

- [ ] **Step 6: Run the existing work-order suites for regressions**

The sweep shares `_apply_session_cap` and `_get_locked` with every tracking path.

```bash
cd backend && ./venv/Scripts/python.exe -m pytest tests/test_work_orders_service.py tests/test_work_orders_domain.py tests/test_work_orders_notifications.py -q
```

Expected: all pass, same counts as before the change.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/work_orders.py backend/tests/test_labor_summary.py
git commit -m "feat(user-hub): sweep stale labor sessions per user or globally"
```

---

### Task 4: The daily labor aggregate

One person, one Central day: tracked minutes from closed sessions, the running session's contribution *to that day*, hand-entered adjustments kept separate, and the timeline the strip will draw.

**Files:**
- Create: `backend/app/services/labor_summary.py`
- Test: `backend/tests/test_labor_summary.py` (append)

**Interfaces:**
- Consumes: `labor_day.day_bounds`, `labor_day.overlap_minutes`, `labor_day.as_utc` (Tasks 1–2).
- Produces (all frozen dataclasses, all fields exactly as named — Task 6 and Task 7 read them by attribute):
  - `labor_summary.TimelineEntry(work_order_id: uuid.UUID, number: str, started_at: datetime, ended_at: datetime | None, auto_closed: bool, minutes: int)`
  - `labor_summary.RunningSession(work_order_id: uuid.UUID, number: str, started_at: datetime, day_counting_from: datetime)`
  - `labor_summary.Adjustment(minutes: int, recorded_by_name: str, work_order_number: str)`
  - `labor_summary.DaySummary(day: date, closed_minutes: int, running_minutes: int, adjustment_minutes: int, running: RunningSession | None, timeline: list[TimelineEntry], adjustments: list[Adjustment])` with a `total_minutes` property returning `closed_minutes + running_minutes + adjustment_minutes`
  - `labor_summary.day_summary(db: Session, technician_id: uuid.UUID, day: date, *, now: datetime) -> DaySummary`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_labor_summary.py`:

```python
# --- the daily aggregate -------------------------------------------------

from datetime import date

from app.domain import labor_day
from app.services import labor_summary


def _seed_adjustment(db, work_order, technician, *, minutes, recorded_by, created_at):
    """A hand-entered labor row: no session points at it (spec D5)."""
    entry = WorkOrderLabor(
        id=uuid.uuid4(),
        work_order_id=work_order.id,
        technician_id=technician.id,
        minutes=minutes,
        recorded_by_id=recorded_by.id,
        created_at=created_at,
    )
    db.add(entry)
    db.flush()
    return entry


def _seed_tracked_labor(db, session, *, minutes):
    """A labor row produced by a session, linked the way `_close_session` links
    it. Must never be reported as an adjustment."""
    entry = WorkOrderLabor(
        id=uuid.uuid4(),
        work_order_id=session.work_order_id,
        technician_id=session.technician_id,
        minutes=minutes,
        recorded_by_id=session.technician_id,
        created_at=session.ended_at,
    )
    db.add(entry)
    db.flush()
    session.labor_id = entry.id
    db.flush()
    return entry


# The reference day: Thursday 2026-08-20 Central (CDT, UTC-5).
DAY = date(2026, 8, 20)
DAY_START = datetime(2026, 8, 20, 5, 0, tzinfo=timezone.utc)


def _at(hour, minute=0, day=20, month=8):
    return datetime(2026, month, day, hour, minute, tzinfo=timezone.utc)


def test_closed_sessions_sum_into_closed_minutes(db):
    tech = _seed_user(db)
    work_order = _seed_work_order(db, created_by=tech, assigned_to=tech)
    _seed_session(db, work_order, tech, started_at=_at(13, 12), ended_at=_at(15, 31))
    _seed_session(db, work_order, tech, started_at=_at(15, 47), ended_at=_at(16, 52))

    summary = labor_summary.day_summary(db, tech.id, DAY, now=_at(18, 0))

    assert summary.closed_minutes == 139 + 65
    assert summary.running_minutes == 0
    assert summary.running is None
    assert summary.total_minutes == 204


def test_a_running_session_reports_its_anchors(db):
    tech = _seed_user(db)
    work_order = _seed_work_order(db, created_by=tech, assigned_to=tech, number="88214")
    _seed_session(db, work_order, tech, started_at=_at(13, 12))

    summary = labor_summary.day_summary(db, tech.id, DAY, now=_at(15, 59))

    assert summary.running is not None
    assert summary.running.number == "88214"
    assert summary.running.started_at == _at(13, 12)
    # Started today, so today's total ticks from the same instant.
    assert summary.running.day_counting_from == _at(13, 12)
    assert summary.running_minutes == 167


def test_a_clock_inherited_from_yesterday_counts_only_from_midnight(db):
    # The correction the spec's payload sketch needs: a session that started
    # 11:30 PM yesterday and is still running at 12:30 AM has given *today*
    # thirty minutes, not sixty. `day_counting_from` is what the client ticks
    # today's total from.
    tech = _seed_user(db)
    work_order = _seed_work_order(db, created_by=tech, assigned_to=tech)
    _seed_session(db, work_order, tech, started_at=_at(4, 30, day=21))

    summary = labor_summary.day_summary(
        db, tech.id, date(2026, 8, 21), now=_at(5, 30, day=21)
    )

    day_start, _ = labor_day.day_bounds(date(2026, 8, 21))
    assert summary.running.started_at == _at(4, 30, day=21)
    assert summary.running.day_counting_from == day_start
    assert summary.running_minutes == 30


def test_a_session_from_another_day_is_excluded(db):
    tech = _seed_user(db)
    work_order = _seed_work_order(db, created_by=tech, assigned_to=tech)
    _seed_session(
        db, work_order, tech, started_at=_at(14, 0, day=19), ended_at=_at(16, 0, day=19)
    )

    summary = labor_summary.day_summary(db, tech.id, DAY, now=_at(18, 0))

    assert summary.closed_minutes == 0
    assert summary.timeline == []


def test_another_persons_session_is_excluded(db):
    mine = _seed_user(db)
    theirs = _seed_user(db, first_name="Marisol", last_name="Chen")
    work_order = _seed_work_order(db, created_by=mine, assigned_to=mine)
    _seed_session(db, work_order, theirs, started_at=_at(13, 0), ended_at=_at(15, 0))

    summary = labor_summary.day_summary(db, mine.id, DAY, now=_at(18, 0))

    assert summary.closed_minutes == 0


def test_the_timeline_is_ordered_and_carries_the_work_order_number(db):
    tech = _seed_user(db)
    first = _seed_work_order(db, created_by=tech, assigned_to=tech, number="88214")
    second = _seed_work_order(db, created_by=tech, assigned_to=tech, number="88190")
    _seed_session(db, second, tech, started_at=_at(15, 47), ended_at=_at(16, 52))
    _seed_session(db, first, tech, started_at=_at(13, 12), ended_at=_at(15, 31))

    summary = labor_summary.day_summary(db, tech.id, DAY, now=_at(18, 0))

    assert [e.number for e in summary.timeline] == ["88214", "88190"]
    assert [e.minutes for e in summary.timeline] == [139, 65]
    assert all(e.auto_closed is False for e in summary.timeline)


def test_an_auto_closed_session_is_flagged_on_the_timeline(db):
    tech = _seed_user(db)
    work_order = _seed_work_order(db, created_by=tech, assigned_to=tech)
    session = _seed_session(
        db, work_order, tech, started_at=_at(13, 0), ended_at=_at(15, 0)
    )
    session.auto_closed_at = _at(17, 0)
    db.flush()

    summary = labor_summary.day_summary(db, tech.id, DAY, now=_at(18, 0))

    assert summary.timeline[0].auto_closed is True


def test_a_session_that_only_touches_the_day_is_left_off_the_timeline(db):
    # Stopped exactly at midnight: it earned today nothing and there is
    # nothing to draw.
    tech = _seed_user(db)
    work_order = _seed_work_order(db, created_by=tech, assigned_to=tech)
    _seed_session(
        db, work_order, tech, started_at=_at(3, 0, day=21), ended_at=DAY_START + timedelta(days=1)
    )

    summary = labor_summary.day_summary(
        db, tech.id, date(2026, 8, 21), now=_at(8, 0, day=21)
    )

    assert summary.timeline == []
    assert summary.closed_minutes == 0


def test_a_hand_entered_row_is_reported_as_an_adjustment(db):
    tech = _seed_user(db)
    supervisor = _seed_user(
        db, roles.ROLE_SUPERVISOR, first_name="Marisol", last_name="Chen"
    )
    work_order = _seed_work_order(db, created_by=tech, assigned_to=tech, number="88190")
    _seed_adjustment(
        db, work_order, tech, minutes=30, recorded_by=supervisor, created_at=_at(19, 0)
    )

    summary = labor_summary.day_summary(db, tech.id, DAY, now=_at(20, 0))

    assert summary.adjustment_minutes == 30
    assert len(summary.adjustments) == 1
    assert summary.adjustments[0].minutes == 30
    assert summary.adjustments[0].recorded_by_name == "Marisol Chen"
    assert summary.adjustments[0].work_order_number == "88190"
    # Adjustments carry no start/stop, so there is nothing to draw.
    assert summary.timeline == []


def test_adjustments_are_included_in_the_day_total(db):
    # Decision D15: one number means one thing on every surface.
    tech = _seed_user(db)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    work_order = _seed_work_order(db, created_by=tech, assigned_to=tech)
    _seed_session(db, work_order, tech, started_at=_at(13, 0), ended_at=_at(18, 50))
    _seed_adjustment(
        db, work_order, tech, minutes=30, recorded_by=supervisor, created_at=_at(19, 0)
    )

    summary = labor_summary.day_summary(db, tech.id, DAY, now=_at(20, 0))

    assert summary.closed_minutes == 350
    assert summary.adjustment_minutes == 30
    assert summary.total_minutes == 380


def test_a_session_produced_labor_row_is_not_an_adjustment(db):
    tech = _seed_user(db)
    work_order = _seed_work_order(db, created_by=tech, assigned_to=tech)
    session = _seed_session(
        db, work_order, tech, started_at=_at(13, 0), ended_at=_at(15, 0)
    )
    _seed_tracked_labor(db, session, minutes=120)

    summary = labor_summary.day_summary(db, tech.id, DAY, now=_at(18, 0))

    assert summary.adjustments == []
    assert summary.adjustment_minutes == 0
    assert summary.total_minutes == 120


def test_an_adjustment_with_no_recorder_still_names_something(db):
    tech = _seed_user(db)
    work_order = _seed_work_order(db, created_by=tech, assigned_to=tech)
    entry = WorkOrderLabor(
        id=uuid.uuid4(),
        work_order_id=work_order.id,
        technician_id=tech.id,
        minutes=15,
        recorded_by_id=None,
        created_at=_at(19, 0),
    )
    db.add(entry)
    db.flush()

    summary = labor_summary.day_summary(db, tech.id, DAY, now=_at(20, 0))

    assert summary.adjustments[0].recorded_by_name == "Name unavailable"


def test_an_adjustment_is_filed_under_the_central_date_it_was_entered(db):
    # Known limitation, accepted for iteration 1: a correction entered Friday
    # for Tuesday's work lands on Friday.
    tech = _seed_user(db)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    work_order = _seed_work_order(db, created_by=tech, assigned_to=tech)
    # 04:00Z on the 21st is 11:00 PM Central on the 20th.
    _seed_adjustment(
        db, work_order, tech, minutes=45, recorded_by=supervisor,
        created_at=_at(4, 0, day=21),
    )

    assert labor_summary.day_summary(db, tech.id, DAY, now=_at(6, 0, day=21)).adjustment_minutes == 45
    assert labor_summary.day_summary(
        db, tech.id, date(2026, 8, 21), now=_at(6, 0, day=21)
    ).adjustment_minutes == 0


def test_an_empty_day_reports_zeros_not_none(db):
    tech = _seed_user(db)

    summary = labor_summary.day_summary(db, tech.id, DAY, now=_at(18, 0))

    assert summary.day == DAY
    assert summary.closed_minutes == 0
    assert summary.running_minutes == 0
    assert summary.adjustment_minutes == 0
    assert summary.total_minutes == 0
    assert summary.running is None
    assert summary.timeline == []
    assert summary.adjustments == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && ./venv/Scripts/python.exe -m pytest tests/test_labor_summary.py -v
```

Expected: the 8 sweep tests still pass; the 14 new ones fail with `ModuleNotFoundError: No module named 'app.services.labor_summary'`.

- [ ] **Step 3: Write the implementation**

Create `backend/app/services/labor_summary.py`:

```python
"""One person's tracked labor for one Central calendar day.

Layer: services. Owns every session/labor aggregate query the hub reads;
every *rule* it applies lives in `app.domain.labor_day`. That split is what
lets the arithmetic be tested exhaustively without a database and leaves this
module with nothing but SQL and assembly.

Derived on read (spec D2): there is no snapshot table and no nightly job.
`work_order_labor_sessions` is already the audit record, and a supervisor
correcting a historical session therefore corrects every total derived from
it, retroactively and for free.

Three numbers come out of here and they are deliberately kept apart:

- `closed_minutes`  -- sessions with a real stop, clipped to the day.
- `running_minutes` -- the open clock's share of *this* day as of `now`.
- `adjustment_minutes` -- hand-entered `work_order_labor` rows with no
  session behind them (spec D5). Counted in the total (D15), never merged
  into tracked time.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.domain import labor_day
from app.models import (
    User,
    WorkOrder,
    WorkOrderLabor,
    WorkOrderLaborSession,
)


@dataclass(frozen=True)
class TimelineEntry:
    """One block on the day's timeline strip.

    `minutes` is this session's share of *this* day, so a midnight crossing
    appears on both days with the two halves it actually contributed --
    which is why it is not simply `ended_at - started_at`.
    """

    work_order_id: uuid.UUID
    number: str
    started_at: datetime
    ended_at: Optional[datetime]
    auto_closed: bool
    minutes: int


@dataclass(frozen=True)
class RunningSession:
    """The caller's open clock, with the two anchors a live display needs.

    `started_at` is what the widget shows ("started 8:12 AM") and ticks
    *session* elapsed from. `day_counting_from` is what **today's total**
    ticks from -- the later of `started_at` and midnight. They differ only
    for a clock inherited from yesterday, and conflating them would report an
    hour of today's work for a session that has given today thirty minutes.
    """

    work_order_id: uuid.UUID
    number: str
    started_at: datetime
    day_counting_from: datetime


@dataclass(frozen=True)
class Adjustment:
    """A hand-entered labor row: minutes with no start, stop, or timeline
    block. Always shown on its own line, naming who recorded it."""

    minutes: int
    recorded_by_name: str
    work_order_number: str


@dataclass(frozen=True)
class DaySummary:
    day: date
    closed_minutes: int = 0
    running_minutes: int = 0
    adjustment_minutes: int = 0
    running: Optional[RunningSession] = None
    timeline: list[TimelineEntry] = field(default_factory=list)
    adjustments: list[Adjustment] = field(default_factory=list)

    @property
    def total_minutes(self) -> int:
        """The one number every hub surface shows for this day (spec D15)."""
        return self.closed_minutes + self.running_minutes + self.adjustment_minutes


def _sessions_touching_day(
    db: Session,
    technician_id: uuid.UUID,
    window_start: datetime,
    window_end: datetime,
) -> list[WorkOrderLaborSession]:
    """Every session of this person's that *overlaps* the window.

    Interval overlap, not a `started_at BETWEEN` filter: a session that began
    yesterday evening and ended this morning belongs to both days, and a range
    filter on the start alone would drop it from today entirely.
    """
    return (
        db.query(WorkOrderLaborSession)
        .options(joinedload(WorkOrderLaborSession.work_order))
        .filter(
            WorkOrderLaborSession.technician_id == technician_id,
            WorkOrderLaborSession.started_at < window_end,
            or_(
                WorkOrderLaborSession.ended_at.is_(None),
                WorkOrderLaborSession.ended_at > window_start,
            ),
        )
        .order_by(WorkOrderLaborSession.started_at)
        .all()
    )


def _adjustments_for_day(
    db: Session,
    technician_id: uuid.UUID,
    window_start: datetime,
    window_end: datetime,
) -> list[Adjustment]:
    """Labor rows with no session behind them, filed by when they were entered.

    The LEFT JOIN + `IS NULL` is the definition of "hand-entered": a stop
    writes its labor row and links it back through
    `work_order_labor_sessions.labor_id`, so an unlinked row is one a person
    typed. Filed under the Central date of `created_at` because that is the
    only date such a row carries -- see the spec's deferred-work list for why
    a Friday correction to Tuesday lands on Friday.
    """
    rows = (
        db.query(WorkOrderLabor, WorkOrder.number, User)
        .join(WorkOrder, WorkOrder.id == WorkOrderLabor.work_order_id)
        .outerjoin(
            WorkOrderLaborSession,
            WorkOrderLaborSession.labor_id == WorkOrderLabor.id,
        )
        .outerjoin(User, User.id == WorkOrderLabor.recorded_by_id)
        .filter(
            WorkOrderLabor.technician_id == technician_id,
            WorkOrderLaborSession.id.is_(None),
            WorkOrderLabor.created_at >= window_start,
            WorkOrderLabor.created_at < window_end,
        )
        .order_by(WorkOrderLabor.created_at)
        .all()
    )
    return [
        Adjustment(
            minutes=entry.minutes,
            recorded_by_name=(
                recorded_by.full_name if recorded_by is not None else "Name unavailable"
            ),
            work_order_number=number,
        )
        for entry, number, recorded_by in rows
    ]


def day_summary(
    db: Session,
    technician_id: uuid.UUID,
    day: date,
    *,
    now: datetime,
) -> DaySummary:
    """One person's tracked labor for one Central calendar day.

    `now` is injected rather than read here so the whole aggregate is
    deterministic under test and so a caller that reads several days shares
    one instant across all of them.

    Does **not** sweep stale sessions -- that is
    `services.work_orders.sweep_stale_sessions`, which the hub composer runs
    first. Keeping the repair out of the read means this function is
    side-effect-free and can be called for any day, including historical ones,
    without writing anything.
    """
    window_start, window_end = labor_day.day_bounds(day)

    closed_minutes = 0
    running_minutes = 0
    running: Optional[RunningSession] = None
    timeline: list[TimelineEntry] = []

    for session in _sessions_touching_day(db, technician_id, window_start, window_end):
        minutes = labor_day.overlap_minutes(
            session.started_at,
            session.ended_at,
            window_start,
            window_end,
            now=now,
        )
        is_running = session.ended_at is None
        if minutes <= 0 and not is_running:
            # Touched the boundary and earned nothing. Nothing to draw.
            continue

        number = session.work_order.number if session.work_order else ""
        timeline.append(
            TimelineEntry(
                work_order_id=session.work_order_id,
                number=number,
                started_at=labor_day.as_utc(session.started_at),
                ended_at=(
                    None if is_running else labor_day.as_utc(session.ended_at)
                ),
                auto_closed=session.auto_closed_at is not None,
                minutes=minutes,
            )
        )
        if is_running:
            running_minutes += minutes
            # At most one, by the partial unique index; the loop does not rely
            # on that, it just takes the latest.
            running = RunningSession(
                work_order_id=session.work_order_id,
                number=number,
                started_at=labor_day.as_utc(session.started_at),
                day_counting_from=max(
                    labor_day.as_utc(session.started_at), window_start
                ),
            )
        else:
            closed_minutes += minutes

    adjustments = _adjustments_for_day(db, technician_id, window_start, window_end)

    return DaySummary(
        day=day,
        closed_minutes=closed_minutes,
        running_minutes=running_minutes,
        adjustment_minutes=sum(a.minutes for a in adjustments),
        running=running,
        timeline=timeline,
        adjustments=adjustments,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && ./venv/Scripts/python.exe -m pytest tests/test_labor_summary.py -v
```

Expected: 22 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/labor_summary.py backend/tests/test_labor_summary.py
git commit -m "feat(user-hub): aggregate one person's tracked labor for one day"
```

---

### Task 5: Tool custody with a `since`

`GET /hub`'s `tools_out` needs how long each tool has been out. `user_custody` returns no timestamp and has two live callers that must not change, so a sibling function is added beside it and the balance walk goes in the pure domain module.

**Files:**
- Modify: `backend/app/domain/tools.py` (append)
- Modify: `backend/app/services/tools.py` (append after `user_custody`, line ~273)
- Test: `backend/tests/test_tools_domain.py` (append)
- Test: `backend/tests/test_tools_service.py` (append)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `domain.tools.custody_since(events: Sequence[tuple[str, Decimal, datetime]]) -> datetime | None` — events are `(transaction_type, quantity, created_at)` in chronological order; returns the timestamp of the checkout that opened the current unbroken custody spell, or `None` if nothing is outstanding.
  - `services.tools.user_custody_detail(db: Session, assigned_to_id: uuid.UUID) -> list[tuple[uuid.UUID, str, str, Decimal, datetime | None]]` — `(tool_id, name, barcode, quantity, since)` for every positive balance, ordered by `since` oldest first.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_tools_domain.py`. The file already imports `Decimal`, `pytest`, and `validate_return`, but **not** `datetime` — the import line below is required:

```python
# --- custody spell start -------------------------------------------------

from datetime import datetime, timezone

from app.domain import tools as tools_domain


def _t(hour):
    return datetime(2026, 8, 20, hour, 0, tzinfo=timezone.utc)


def test_custody_since_is_the_checkout_that_opened_the_current_spell():
    # Returned on Tuesday, taken out again on Wednesday: "since" is Wednesday.
    events = [
        ("checkout", Decimal("1"), _t(8)),
        ("return", Decimal("1"), _t(10)),
        ("checkout", Decimal("2"), _t(12)),
    ]
    assert tools_domain.custody_since(events) == _t(12)


def test_custody_since_survives_a_partial_return():
    # Still holding one of the two, so the spell never broke.
    events = [
        ("checkout", Decimal("2"), _t(8)),
        ("return", Decimal("1"), _t(10)),
    ]
    assert tools_domain.custody_since(events) == _t(8)


def test_custody_since_is_none_when_everything_came_back():
    events = [
        ("checkout", Decimal("1"), _t(8)),
        ("return", Decimal("1"), _t(10)),
    ]
    assert tools_domain.custody_since(events) is None


def test_custody_since_ignores_adjust_rows():
    # Correct Count has no custody holder and must not open or close a spell.
    events = [
        ("adjust", Decimal("-3"), _t(7)),
        ("checkout", Decimal("1"), _t(8)),
    ]
    assert tools_domain.custody_since(events) == _t(8)


def test_custody_since_of_nothing_is_none():
    assert tools_domain.custody_since([]) is None
```

Confirm `Decimal` is already imported in that test file; add `from decimal import Decimal` if not.

Append to `backend/tests/test_tools_service.py`. It already defines `_seed_user(db, role="technician")` and `_seed_tool(db, quantity=5)` (which creates a tool named `"Cordless Drill"`), and already imports `uuid`, `Decimal`, `datetime`/`timezone`, and `tools_service` — reuse all of them:

```python
# --- custody detail with a since ----------------------------------------

def test_user_custody_detail_reports_when_the_tool_went_out(db):
    holder = _seed_user(db)
    tool = _seed_tool(db)
    tools_service.checkout_tool(
        db,
        tool.id,
        quantity=Decimal("1"),
        assigned_to_id=holder.id,
        performed_by_id=holder.id,
    )

    rows = tools_service.user_custody_detail(db, holder.id)

    assert len(rows) == 1
    tool_id, name, barcode, quantity, since = rows[0]
    assert tool_id == tool.id
    assert name == "Cordless Drill"
    assert barcode == tool.barcode
    assert quantity == Decimal("1")
    assert since is not None


def test_user_custody_detail_omits_a_fully_returned_tool(db):
    holder = _seed_user(db)
    tool = _seed_tool(db)
    tools_service.checkout_tool(
        db,
        tool.id,
        quantity=Decimal("1"),
        assigned_to_id=holder.id,
        performed_by_id=holder.id,
    )
    tools_service.return_tool(
        db,
        tool.id,
        quantity=Decimal("1"),
        assigned_to_id=holder.id,
        performed_by_id=holder.id,
    )

    assert tools_service.user_custody_detail(db, holder.id) == []


def test_user_custody_detail_keeps_the_spell_open_after_a_partial_return(db):
    holder = _seed_user(db)
    tool = _seed_tool(db)
    tools_service.checkout_tool(
        db,
        tool.id,
        quantity=Decimal("2"),
        assigned_to_id=holder.id,
        performed_by_id=holder.id,
    )
    first_out = tools_service.user_custody_detail(db, holder.id)[0][4]
    tools_service.return_tool(
        db,
        tool.id,
        quantity=Decimal("1"),
        assigned_to_id=holder.id,
        performed_by_id=holder.id,
    )

    rows = tools_service.user_custody_detail(db, holder.id)

    assert rows[0][3] == Decimal("1")
    # Still holding one, so "since" never moved.
    assert rows[0][4] == first_out


def test_user_custody_detail_agrees_with_user_custody(db):
    # The two must never disagree about who holds what -- only about whether
    # a timestamp is included.
    holder = _seed_user(db)
    tool = _seed_tool(db)
    tools_service.checkout_tool(
        db,
        tool.id,
        quantity=Decimal("2"),
        assigned_to_id=holder.id,
        performed_by_id=holder.id,
    )

    plain = tools_service.user_custody(db, holder.id)
    detailed = tools_service.user_custody_detail(db, holder.id)

    assert [row[:4] for row in detailed] == plain
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && ./venv/Scripts/python.exe -m pytest tests/test_tools_domain.py tests/test_tools_service.py -v
```

Expected: existing tests pass; the new ones fail on `custody_since` / `user_custody_detail` not existing.

- [ ] **Step 3: Write the pure balance walk**

Append to `backend/app/domain/tools.py`:

```python
def custody_since(
    events: Sequence[tuple[str, Decimal, datetime]],
) -> Optional[datetime]:
    """When the current unbroken custody spell began, or None if nothing is out.

    `events` are `(transaction_type, quantity, created_at)` for one
    `(tool, holder)` pair, in chronological order. Walks the running balance
    and remembers the checkout that lifted it off zero; a return that brings
    it back to zero ends the spell, so a tool taken out, returned, and taken
    out again reads "since" the second checkout rather than the first.

    A *partial* return does not end the spell -- the holder never gave the
    tool back. `adjust` rows are skipped for the same reason `tool_custody`
    excludes them: a Correct Count has no custody holder.
    """
    balance = Decimal("0")
    since: Optional[datetime] = None
    for transaction_type, quantity, created_at in events:
        if transaction_type == "checkout":
            if balance <= 0:
                since = created_at
            balance += quantity
        elif transaction_type == "return":
            balance -= quantity
            if balance <= 0:
                balance = Decimal("0")
                since = None
    return since
```

`app/domain/tools.py` currently imports only `Decimal` and `ToolReturnExceedsCheckedOutError`, so add this above them:

```python
from datetime import datetime
from typing import Optional, Sequence
```

- [ ] **Step 4: Write the service query**

Append to `backend/app/services/tools.py`, directly after `user_custody`:

```python
def user_custody_detail(
    db: Session, assigned_to_id: uuid.UUID
) -> list[tuple[uuid.UUID, str, str, Decimal, Optional[datetime]]]:
    """`user_custody` plus how long each tool has been out.

    Returns `(tool_id, tool_name, barcode, quantity, since)`, oldest spell
    first, for every positive balance -- the same rows `user_custody`
    returns, in the same shape with one field appended.

    A separate function rather than a widened `user_custody` on purpose:
    that one feeds user archival and force check-in, neither of which cares
    when a tool went out, and changing a shipped return shape to add a field
    two callers would ignore is how a small addition becomes a regression.
    `since` comes from `domain.tools.custody_since`, so the "when did this
    spell start" rule is testable without a database.
    """
    outstanding = {
        tool_id: (name, barcode, quantity)
        for tool_id, name, barcode, quantity in user_custody(db, assigned_to_id)
    }
    if not outstanding:
        return []

    rows = (
        db.query(
            ToolTransaction.tool_id,
            ToolTransaction.transaction_type,
            ToolTransaction.quantity,
            ToolTransaction.created_at,
        )
        .filter(
            ToolTransaction.assigned_to_id == assigned_to_id,
            ToolTransaction.tool_id.in_(outstanding.keys()),
            ToolTransaction.transaction_type.in_(("checkout", "return")),
        )
        .order_by(ToolTransaction.created_at)
        .all()
    )
    events: dict[uuid.UUID, list[tuple[str, Decimal, datetime]]] = {}
    for tool_id, transaction_type, quantity, created_at in rows:
        events.setdefault(tool_id, []).append(
            (transaction_type, quantity, created_at)
        )

    detail = [
        (tool_id, name, barcode, quantity, custody_since(events.get(tool_id, [])))
        for tool_id, (name, barcode, quantity) in outstanding.items()
    ]
    # Oldest spell first: the tool somebody has been sitting on for a week is
    # the one worth reading first. Unknowns sort last.
    detail.sort(key=lambda row: (row[4] is None, row[4] or _OLDEST))
    return detail
```

`app/services/tools.py` already imports `ToolTransaction`, `uuid`, `datetime`, `timezone`, `Optional`, and `Decimal`. It imports the domain module as `from app.domain.tools import validate_return` — extend that line to `from app.domain.tools import custody_since, validate_return` rather than adding a second import of the same module.

`datetime.min` is naive and the stored timestamps are aware, so the sort key uses `datetime.min.replace(tzinfo=timezone.utc)`:

```python
    _OLDEST = datetime.min.replace(tzinfo=timezone.utc)
    detail.sort(key=lambda row: (row[4] is None, row[4] or _OLDEST))
```

Put `_OLDEST` at module scope beside the other constants rather than rebuilding it per call.

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd backend && ./venv/Scripts/python.exe -m pytest tests/test_tools_domain.py tests/test_tools_service.py -v
```

Expected: all pass, including every pre-existing test in both files.

- [ ] **Step 6: Commit**

```bash
git add backend/app/domain/tools.py backend/app/services/tools.py backend/tests/test_tools_domain.py backend/tests/test_tools_service.py
git commit -m "feat(user-hub): report how long each tool has been out"
```

---

### Task 6: Compose the personal hub payload

The service behind `GET /hub`: sweep, count, pick, aggregate, list tools. One place, so the router stays thin.

**Files:**
- Create: `backend/app/services/hub.py`
- Test: `backend/tests/test_hub_service.py` (create)

**Interfaces:**
- Consumes: `work_orders_service.sweep_stale_sessions`, `work_orders_service.TRACKING_START_STATUSES` (Task 3); `labor_summary.day_summary` and `labor_summary.DaySummary` (Task 4); `tools_service.user_custody_detail` (Task 5); `labor_day.central_date_of` (Task 1).
- Produces:
  - `hub.AssignedCounts(assigned: int, in_progress: int, ready_to_complete: int)`
  - `hub.StartableWorkOrder(work_order_id: uuid.UUID, number: str, status: str, community: str | None, building_number: str | None, unit_number: str | None, location: str | None)`
  - `hub.ToolOut(tool_id: uuid.UUID, name: str, barcode: str, quantity: Decimal, since: datetime | None)`
  - `hub.HubPayload(user: User, server_now: datetime, day: date, counts: AssignedCounts, clock: labor_summary.DaySummary, startable: list[StartableWorkOrder], tools_out: list[ToolOut])`
  - `hub.personal_hub(db: Session, user: User) -> HubPayload`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_hub_service.py`:

```python
"""Database tests for the personal hub payload.

Covers the count convention (a total and two subsets, not three disjoint
buckets), the `Start on...` picker's contents and order, and the sweep that
runs before the read. The time arithmetic itself is covered by
`test_labor_day.py` and `test_labor_summary.py`; this file only checks that
the composer wires them together.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.domain import labor_day
from app.domain import roles
from app.domain import work_orders as wo
from app.models import User, WorkOrderLaborSession, WorkOrderTechnician
from app.services import auth
from app.services import hub as hub_service
from app.services import work_orders as wos


def _seed_user(db, role=roles.ROLE_TECHNICIAN, *, first_name="Jose", last_name="Rivera"):
    user = User(
        username=f"u-{uuid.uuid4().hex[:10]}",
        first_name=first_name,
        last_name=last_name,
        password_hash=auth.hash_password("hunter2"),
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def _seed_work_order(db, *, created_by, assigned_to=None, number=None, status=None):
    work_order = wos.get_or_create_work_order(
        db,
        number=number or f"WO-{uuid.uuid4().hex[:8]}",
        created_by_id=created_by.id,
        assigned_to_id=assigned_to.id if assigned_to else None,
    )
    if status is not None:
        work_order.status = status
        db.flush()
    return work_order


def test_counts_are_a_total_and_two_subsets(db):
    # "8 assigned, 1 in progress, 2 ready" describes 8 work orders, not 11.
    tech = _seed_user(db)
    for _ in range(5):
        _seed_work_order(db, created_by=tech, assigned_to=tech, status=wo.STATUS_ASSIGNED)
    _seed_work_order(db, created_by=tech, assigned_to=tech, status=wo.STATUS_IN_PROGRESS)
    for _ in range(2):
        _seed_work_order(
            db, created_by=tech, assigned_to=tech, status=wo.STATUS_READY_TO_COMPLETE
        )

    payload = hub_service.personal_hub(db, tech)

    assert payload.counts.assigned == 8
    assert payload.counts.in_progress == 1
    assert payload.counts.ready_to_complete == 2


def test_counts_include_work_assigned_through_the_technician_table(db):
    # Assignment lives in two places -- the legacy `assigned_to_id` column and
    # `work_order_technicians` rows. Counting only one silently loses work.
    tech = _seed_user(db)
    creator = _seed_user(db, roles.ROLE_SUPERVISOR)
    work_order = _seed_work_order(db, created_by=creator, status=wo.STATUS_ASSIGNED)
    db.add(
        WorkOrderTechnician(work_order_id=work_order.id, technician_id=tech.id)
    )
    db.flush()

    assert hub_service.personal_hub(db, tech).counts.assigned == 1


def test_an_archived_work_order_is_excluded_everywhere(db):
    tech = _seed_user(db)
    work_order = _seed_work_order(
        db, created_by=tech, assigned_to=tech, status=wo.STATUS_ASSIGNED
    )
    work_order.archived_at = datetime.now(timezone.utc)
    db.flush()

    payload = hub_service.personal_hub(db, tech)

    assert payload.counts.assigned == 0
    assert payload.startable == []


def test_someone_elses_work_order_is_not_mine(db):
    mine = _seed_user(db)
    theirs = _seed_user(db, first_name="Marisol", last_name="Chen")
    _seed_work_order(db, created_by=theirs, assigned_to=theirs, status=wo.STATUS_ASSIGNED)

    assert hub_service.personal_hub(db, mine).counts.assigned == 0


def test_the_picker_offers_only_startable_statuses(db):
    tech = _seed_user(db)
    _seed_work_order(db, created_by=tech, assigned_to=tech, status=wo.STATUS_ASSIGNED)
    _seed_work_order(
        db, created_by=tech, assigned_to=tech, status=wo.STATUS_READY_TO_COMPLETE
    )
    _seed_work_order(db, created_by=tech, assigned_to=tech, status=wo.STATUS_COMPLETED)

    startable = hub_service.personal_hub(db, tech).startable

    assert [s.status for s in startable] == [wo.STATUS_ASSIGNED]


def test_the_picker_puts_live_work_first(db):
    tech = _seed_user(db)
    _seed_work_order(
        db, created_by=tech, assigned_to=tech, number="88301", status=wo.STATUS_CREATED
    )
    _seed_work_order(
        db, created_by=tech, assigned_to=tech, number="88302", status=wo.STATUS_ASSIGNED
    )
    _seed_work_order(
        db, created_by=tech, assigned_to=tech, number="88303", status=wo.STATUS_ON_HOLD
    )
    _seed_work_order(
        db, created_by=tech, assigned_to=tech, number="88304", status=wo.STATUS_IN_PROGRESS
    )

    startable = hub_service.personal_hub(db, tech).startable

    assert [s.number for s in startable] == ["88304", "88303", "88302", "88301"]


def test_the_picker_carries_the_raw_place_fields(db):
    # There is no server-side location composer; `workOrders.js::placeMeta`
    # owns that and needs all four inputs.
    tech = _seed_user(db)
    work_order = _seed_work_order(
        db, created_by=tech, assigned_to=tech, status=wo.STATUS_ASSIGNED
    )
    work_order.community = "Commons"
    work_order.building_number = "B3"
    work_order.unit_number = "214"
    db.flush()

    entry = hub_service.personal_hub(db, tech).startable[0]

    assert entry.community == "Commons"
    assert entry.building_number == "B3"
    assert entry.unit_number == "214"


def test_the_hub_sweeps_the_callers_forgotten_clock_before_reading(db):
    # Without this a technician who forgot to clock out on Tuesday opens the
    # hub on Wednesday to a twenty-hour running clock.
    tech = _seed_user(db)
    work_order = _seed_work_order(
        db, created_by=tech, assigned_to=tech, status=wo.STATUS_IN_PROGRESS
    )
    started = datetime.now(timezone.utc) - timedelta(hours=20)
    session = WorkOrderLaborSession(
        id=uuid.uuid4(),
        work_order_id=work_order.id,
        technician_id=tech.id,
        started_at=started,
    )
    db.add(session)
    db.flush()

    payload = hub_service.personal_hub(db, tech)

    assert payload.clock.running is None
    db.refresh(session)
    assert session.ended_at == started + timedelta(
        minutes=wo.LABOR_SESSION_MAX_MINUTES
    )


def test_the_payload_reports_the_servers_instant_and_central_day(db):
    tech = _seed_user(db)

    payload = hub_service.personal_hub(db, tech)

    assert payload.server_now.tzinfo is not None
    assert payload.day == labor_day.central_date_of(payload.server_now)
    assert payload.user.id == tech.id


def test_an_empty_hub_is_all_zeros_and_empty_lists(db):
    tech = _seed_user(db)

    payload = hub_service.personal_hub(db, tech)

    assert payload.counts.assigned == 0
    assert payload.startable == []
    assert payload.tools_out == []
    assert payload.clock.total_minutes == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && ./venv/Scripts/python.exe -m pytest tests/test_hub_service.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.services.hub'`.

- [ ] **Step 3: Write the implementation**

Create `backend/app/services/hub.py`:

```python
"""Composes the User Hub's payloads.

Layer: services. Called by `app/routers/hub.py`. Owns no rules of its own --
day arithmetic is `domain.labor_day`, the labor aggregate is
`services.labor_summary`, tool custody is `services.tools`, and the cap
sweep is `services.work_orders`. This module's whole job is to run them in
the right order and hand back one object the router can serialise, so the
router stays the thin translation layer every other one in this app is.

Phase 1 builds the **personal block** only -- the payload behind `GET /hub`,
which every authenticated role receives, Admin included. That is not
symmetry for its own sake: `POST /tracking/start` is already open to
Supervisor+ on any visible work order, precisely so a supervisor who does
the work records it, and a supervisor with a running clock and nowhere to
see it would be a regression. The crew, admin, and timesheet payloads are
later phases.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.domain import labor_day
from app.domain import work_orders as wo
from app.models import User, WorkOrder, WorkOrderTechnician
from app.services import labor_summary
from app.services import tools as tools_service
from app.services import work_orders as work_orders_service

# Picker order. The spec names the first two; the other two are startable as
# well, so they follow in the order somebody would actually reach for them --
# what I am on, what I paused, what I have been given, what exists.
_STARTABLE_ORDER = (
    wo.STATUS_IN_PROGRESS,
    wo.STATUS_ON_HOLD,
    wo.STATUS_ASSIGNED,
    wo.STATUS_CREATED,
)


@dataclass(frozen=True)
class AssignedCounts:
    """A total and two subsets of it -- **not** three disjoint buckets.

    `assigned` is every non-archived work order the caller is an assigned
    technician on, whatever its status; the other two count members of that
    same set. So "8 assigned, 1 in progress, 2 ready" describes 8 work
    orders, not 11, and the tiles are labelled to match.
    """

    assigned: int
    in_progress: int
    ready_to_complete: int


@dataclass(frozen=True)
class StartableWorkOrder:
    """One option in the `Start on...` picker.

    Carries the raw place fields rather than a composed string: there is no
    server-side location composer, and `static/views/workOrders.js::placeMeta`
    already owns that formatting for every card in the app. One composer, one
    spelling of an address.
    """

    work_order_id: uuid.UUID
    number: str
    status: str
    community: Optional[str]
    building_number: Optional[str]
    unit_number: Optional[str]
    location: Optional[str]


@dataclass(frozen=True)
class ToolOut:
    tool_id: uuid.UUID
    name: str
    barcode: str
    quantity: Decimal
    since: Optional[datetime]


@dataclass(frozen=True)
class HubPayload:
    user: User
    server_now: datetime
    day: date
    counts: AssignedCounts
    clock: labor_summary.DaySummary
    startable: list[StartableWorkOrder]
    tools_out: list[ToolOut]


def _assigned_work_orders(db: Session, user_id: uuid.UUID) -> list[WorkOrder]:
    """Every live work order this person is an assigned technician on.

    Assignment lives in two places -- the legacy singular `assigned_to_id`
    column and plural `work_order_technicians` rows -- and both are still
    populated, so both are matched. This is the same `or_` pair
    `_scoped_to_user` uses for a Technician's list, kept identical on purpose:
    the hub's count and the Work Orders page must never disagree about what
    somebody has been given.

    Loaded into Python rather than counted in SQL because the same rows feed
    three counts and the picker, and a technician's assignment list is tens of
    rows, not thousands.
    """
    return (
        db.query(WorkOrder)
        .filter(
            WorkOrder.archived_at.is_(None),
            or_(
                WorkOrder.assigned_to_id == user_id,
                WorkOrder.technician_assignments.any(
                    WorkOrderTechnician.technician_id == user_id
                ),
            ),
        )
        .order_by(WorkOrder.number)
        .all()
    )


def personal_hub(db: Session, user: User) -> HubPayload:
    """The `GET /hub` payload: what am I responsible for, and how long have I
    been working.

    **Not side-effect-free**, and deliberately so: the caller's stale clock is
    swept before anything is read (`sweep_stale_sessions`), so a session
    forgotten on Tuesday does not show up on Wednesday as a twenty-hour
    running total spanning two days. The cost is bounded to at most one row by
    the partial unique index, and it follows existing precedent --
    `get_work_order` already both sweeps sessions and heals orphaned material
    lines on a read.

    One `now` is taken after the sweep and used for the day, the aggregate,
    and the client's clock-skew anchor, so every number in the response
    describes the same instant.
    """
    work_orders_service.sweep_stale_sessions(db, technician_id=user.id)

    now = datetime.now(timezone.utc)
    day = labor_day.central_date_of(now)

    mine = _assigned_work_orders(db, user.id)
    counts = AssignedCounts(
        assigned=len(mine),
        in_progress=sum(1 for w in mine if w.status == wo.STATUS_IN_PROGRESS),
        ready_to_complete=sum(
            1 for w in mine if w.status == wo.STATUS_READY_TO_COMPLETE
        ),
    )

    startable = [
        StartableWorkOrder(
            work_order_id=w.id,
            number=w.number,
            status=w.status,
            community=w.community,
            building_number=w.building_number,
            unit_number=w.unit_number,
            location=w.location,
        )
        for w in sorted(
            (
                w
                for w in mine
                if w.status in work_orders_service.TRACKING_START_STATUSES
            ),
            key=lambda w: (_STARTABLE_ORDER.index(w.status), w.number or ""),
        )
    ]

    return HubPayload(
        user=user,
        server_now=now,
        day=day,
        counts=counts,
        clock=labor_summary.day_summary(db, user.id, day, now=now),
        startable=startable,
        tools_out=[
            ToolOut(
                tool_id=tool_id,
                name=name,
                barcode=barcode,
                quantity=quantity,
                since=since,
            )
            for tool_id, name, barcode, quantity, since in (
                tools_service.user_custody_detail(db, user.id)
            )
        ],
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && ./venv/Scripts/python.exe -m pytest tests/test_hub_service.py -v
```

Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/hub.py backend/tests/test_hub_service.py
git commit -m "feat(user-hub): compose the personal hub payload"
```

---

### Task 7: `GET /hub`

The response contract and the one route, wired into the app.

**Files:**
- Create: `backend/app/schemas/hub.py`
- Create: `backend/app/routers/hub.py`
- Modify: `backend/app/main.py:48-61` (router import) and `backend/app/main.py:306` (registration)
- Test: `backend/tests/test_route_role_gates.py` (append)
- Test: `backend/tests/test_hub_service.py` (append — one schema round-trip)

**Interfaces:**
- Consumes: `hub_service.personal_hub` and every dataclass from Task 6; `labor_summary.DaySummary` from Task 4.
- Produces: `GET /hub`, gated by `Depends(get_current_user)`, returning `HubResponse`.

Response shape, matching spec §7 plus the two documented corrections:

```json
{
  "user": {"id": "…", "first_name": "Jose", "last_name": "Rivera", "role": "technician"},
  "server_now": "2026-08-20T15:47:12Z",
  "day": "2026-08-20",
  "clock": {
    "running_session": {
      "work_order_id": "…", "number": "88214",
      "started_at": "2026-08-20T13:12:00Z",
      "day_counting_from": "2026-08-20T13:12:00Z"
    },
    "closed_minutes_today": 320,
    "running_minutes_today": 155,
    "adjustment_minutes_today": 30,
    "total_minutes_today": 505,
    "adjustments": [{"minutes": 30, "recorded_by_name": "Marisol Chen", "work_order_number": "88190"}]
  },
  "timeline": [{"work_order_id": "…", "number": "88214", "started_at": "…", "ended_at": null, "auto_closed": false, "minutes": 155}],
  "counts": {"assigned": 8, "in_progress": 1, "ready_to_complete": 2},
  "startable": [{"work_order_id": "…", "number": "88214", "status": "in_progress", "community": "Commons", "building_number": "B3", "unit_number": "214", "location": null}],
  "tools_out": [{"tool_id": "…", "name": "Hilti TE-2", "barcode": "T-001", "quantity": "1", "since": "2026-08-18T13:55:00Z"}]
}
```

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_route_role_gates.py` (add `from app.routers import hub as hub_router` to the router imports at the top):

```python
def test_the_hub_is_open_to_any_authenticated_role():
    # Every role gets the personal block, Admin included: `POST
    # /tracking/start` is already Supervisor+ on any visible row, so a
    # supervisor with a running clock and no way to see it would be a
    # regression. The rank-gated payloads are separate endpoints.
    assert _min_role_for(hub_router, "get_hub") is None


def test_the_hub_route_still_requires_a_session():
    # "No minimum role" must not mean "no gate". `get_current_user` is the
    # 401 boundary and has to be in the dependant tree.
    from app.auth_deps import get_current_user

    def _uses(dependant):
        return any(
            sub.call is get_current_user or _uses(sub)
            for sub in dependant.dependencies
        )

    assert _uses(_route(hub_router, "get_hub").dependant) is True
```

Append to `backend/tests/test_hub_service.py`:

```python
def test_the_payload_serialises_into_the_response_schema(db):
    # The handler is called directly -- its two parameters are `Depends`
    # defaults, so this needs no HTTP client. A field renamed on either side
    # of the service/schema boundary has to fail here rather than at runtime.
    from app.routers.hub import get_hub

    tech = _seed_user(db)
    work_order = _seed_work_order(
        db, created_by=tech, assigned_to=tech, number="88214",
        status=wo.STATUS_ASSIGNED,
    )
    wos.start_labor_session(db, work_order.id, user=tech)

    body = get_hub(user=tech, db=db).model_dump()

    assert body["user"]["role"] == roles.ROLE_TECHNICIAN
    assert body["counts"]["assigned"] == 1
    assert body["clock"]["running_session"]["number"] == "88214"
    assert body["clock"]["running_session"]["day_counting_from"] is not None
    assert body["clock"]["total_minutes_today"] == (
        body["clock"]["closed_minutes_today"]
        + body["clock"]["running_minutes_today"]
        + body["clock"]["adjustment_minutes_today"]
    )
    assert [e["number"] for e in body["timeline"]] == ["88214"]
    assert body["startable"][0]["status"] == wo.STATUS_IN_PROGRESS
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && ./venv/Scripts/python.exe -m pytest tests/test_route_role_gates.py tests/test_hub_service.py -v
```

Expected: import error / `ModuleNotFoundError` for `app.routers.hub` and `app.schemas.hub`.

- [ ] **Step 3: Write the schemas**

Create `backend/app/schemas/hub.py`:

```python
"""User Hub response contracts.

Layer: schemas. Consumed by `app/routers/hub.py`. Every model is
`from_attributes`, because the service hands back frozen dataclasses and the
router's whole body is one `model_validate` -- which also means a field
renamed on either side fails a test instead of quietly serialising as null.

Field names deliberately differ from the service's in one place: the clock
block's minute counts carry a `_today` suffix on the wire. The service
computes any day; this response is always about today, and the frontend
reads better for saying so.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, computed_field


class HubUser(BaseModel):
    """Who the payload is about. Deliberately not the full user record --
    no username, no timestamps; the hub needs an identity, not an account."""

    id: uuid.UUID
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: str

    model_config = {"from_attributes": True}


class HubRunningSession(BaseModel):
    """The caller's open clock, with both anchors the client ticks from.

    `started_at` drives the widget's session elapsed ("started 8:12 AM").
    `day_counting_from` drives *today's* total and equals midnight Central
    for a clock inherited from yesterday -- ticking the day total from
    `started_at` would report an hour for a session that has given today
    thirty minutes.
    """

    work_order_id: uuid.UUID
    number: str
    started_at: datetime
    day_counting_from: datetime

    model_config = {"from_attributes": True}


class HubAdjustment(BaseModel):
    minutes: int
    recorded_by_name: str
    work_order_number: str

    model_config = {"from_attributes": True}


class HubTimelineEntry(BaseModel):
    """One block on the day's strip. `minutes` is this session's share of
    *this* day, so a midnight crossing appears on both days at its real
    weight. `auto_closed` marks a session the 12-hour cap ended: an estimate
    a supervisor should correct, not a fact."""

    work_order_id: uuid.UUID
    number: str
    started_at: datetime
    ended_at: Optional[datetime] = None
    auto_closed: bool
    minutes: int

    model_config = {"from_attributes": True}


class HubClock(BaseModel):
    """Anchors, not a ticking number.

    The server sends what is fixed -- minutes already banked, when the open
    clock started -- and the client renders the live figure from
    `server_now` skew on a one-second interval. Polling for a number that
    changes every sixty seconds would fight the rate cap for no benefit.
    """

    running_session: Optional[HubRunningSession] = None
    closed_minutes_today: int
    running_minutes_today: int
    adjustment_minutes_today: int
    adjustments: list[HubAdjustment] = []

    @computed_field
    @property
    def total_minutes_today(self) -> int:
        """The one number every surface shows for today (spec D15):
        tracked plus running plus adjustments. The split is one expand
        away, never a different total."""
        return (
            self.closed_minutes_today
            + self.running_minutes_today
            + self.adjustment_minutes_today
        )

    model_config = {"from_attributes": True}


class HubCounts(BaseModel):
    """A total and two subsets of it, not three disjoint buckets:
    `assigned` is every live work order the caller is on, and the other two
    count members of that same set."""

    assigned: int
    in_progress: int
    ready_to_complete: int

    model_config = {"from_attributes": True}


class HubStartable(BaseModel):
    """One option in the `Start on...` picker. Place fields are raw; the
    frontend's existing `placeMeta` composes them."""

    work_order_id: uuid.UUID
    number: str
    status: str
    community: Optional[str] = None
    building_number: Optional[str] = None
    unit_number: Optional[str] = None
    location: Optional[str] = None

    model_config = {"from_attributes": True}


class HubToolOut(BaseModel):
    tool_id: uuid.UUID
    name: str
    barcode: str
    quantity: Decimal
    since: Optional[datetime] = None

    model_config = {"from_attributes": True}


class HubResponse(BaseModel):
    """`GET /hub`.

    `server_now` is the client's clock-skew anchor: it records
    `skew = server_now - Date.now()` at fetch time and renders elapsed
    against it, so a field phone with a wrong system clock still shows the
    right number.
    """

    user: HubUser
    server_now: datetime
    day: date
    clock: HubClock
    timeline: list[HubTimelineEntry] = []
    counts: HubCounts
    startable: list[HubStartable] = []
    tools_out: list[HubToolOut] = []

    model_config = {"from_attributes": True}
```

The service's `DaySummary` field names are `closed_minutes` / `running_minutes` / `adjustment_minutes` / `running`, while `HubClock` wants `closed_minutes_today` / `running_minutes_today` / `adjustment_minutes_today` / `running_session`. `from_attributes` will not bridge that, so the router builds `HubClock` explicitly — see Step 4. Do **not** rename the dataclass fields: `DaySummary` is reused by the timesheet grid in P3, which is not about today.

- [ ] **Step 4: Write the router**

Create `backend/app/routers/hub.py`:

```python
"""HTTP routes for the User Hub.

Layer: routers (FastAPI). Thin handlers only, mirroring
`app/routers/tools.py`. Payloads stack by rank rather than branching by
role, so each route carries exactly one declarative gate and `auth_deps.py`
stays the only place a role 403 is raised:

- `GET /hub`             any authenticated  -- the personal block (this phase)
- `GET /hub/crew`        supervisor+        -- later phase
- `GET /hub/admin`       techfm_oa+         -- later phase
- `GET /hub/timesheets`  supervisor+        -- later phase

**`GET /hub` is not side-effect-free.** It sweeps the caller's own over-cap
session before reading and therefore commits when it finds one. That follows
existing precedent rather than inventing it -- `get_work_order` already both
sweeps sessions and self-heals orphaned material lines on a read -- and the
sweep is idempotent under a row lock, so two tabs loading at once cannot
double-close a session.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth_deps import get_current_user
from app.database import get_db
from app.models import User
from app.schemas.hub import HubClock, HubResponse
from app.services import hub as hub_service

router = APIRouter(prefix="/hub", tags=["hub"])


@router.get("", response_model=HubResponse)
def get_hub(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The signed-in person's own block: counts, today's time, the clock,
    the `Start on...` picker, and tools they are holding.

    Open to every authenticated role, Admin included -- a supervisor can
    already start a clock on any work order they can see, so one with a
    running clock and nowhere to see it would be a regression.

    Built field by field rather than by `model_validate(payload)` because two
    names deliberately differ across the boundary: the service's `DaySummary`
    describes *a* day and is reused by the timesheet grid in a later phase,
    while this response is always about today and its fields say so. The
    nested models are all `from_attributes`, so the dataclasses below pass
    straight in.
    """
    payload = hub_service.personal_hub(db, user)
    clock = payload.clock
    return HubResponse(
        user=payload.user,
        server_now=payload.server_now,
        day=payload.day,
        clock=HubClock(
            running_session=clock.running,
            closed_minutes_today=clock.closed_minutes,
            running_minutes_today=clock.running_minutes,
            adjustment_minutes_today=clock.adjustment_minutes,
            adjustments=clock.adjustments,
        ),
        timeline=clock.timeline,
        counts=payload.counts,
        startable=payload.startable,
        tools_out=payload.tools_out,
    )
```

Pydantic v2 will not coerce a dataclass into a `from_attributes` model when it is passed to the constructor of an outer model in strict positions. If `HubResponse(...)` raises a validation error on any nested field, wrap that field explicitly — e.g. `user=HubUser.model_validate(payload.user)` — rather than loosening the model. Do this only for the fields that actually fail.

- [ ] **Step 5: Register the router**

In `backend/app/main.py`, add `hub,` to the `from app.routers import (...)` block between `barcodes,` and `items,` (line ~51), and add:

```python
app.include_router(hub.router)
```

between `app.include_router(barcodes.router)` and `app.include_router(items.router)` (line ~307).

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd backend && ./venv/Scripts/python.exe -m pytest tests/test_route_role_gates.py tests/test_hub_service.py -v
```

Expected: all pass, including the pre-existing `test_no_route_gate_is_left_at_the_admin_floor` (the hub has no `ROLE_ADMIN` gate, so it must not appear in `offenders`).

- [ ] **Step 7: Verify the route is mounted at the right path**

```bash
cd backend && ./venv/Scripts/python.exe -c "from app.main import app; print([r.path for r in app.routes if getattr(r, 'path', '').startswith('/hub')])"
```

Expected: `['/hub']` — not `/hub/` and not missing.

- [ ] **Step 8: Run the whole backend suite**

```bash
cd backend && ./venv/Scripts/python.exe -m pytest -q
```

Expected: everything passes. `test_docs_endpoints.py` may assert something about the OpenAPI surface — if it fails on the new route, read it and extend it deliberately rather than loosening it.

- [ ] **Step 9: Commit**

```bash
git add backend/app/schemas/hub.py backend/app/routers/hub.py backend/app/main.py backend/tests/test_route_role_gates.py backend/tests/test_hub_service.py
git commit -m "feat(user-hub): add GET /hub personal payload endpoint"
```

---

### Task 8: Register the endpoint in the docs

`docs/endpoint-map.md` is the repo's promise that you can answer "what does this endpoint return?" without opening the source. A new endpoint that is not in it breaks that promise.

**Files:**
- Modify: `docs/endpoint-map.md` — the Master Endpoint Index table, the Database → User View section, and the Request / Response Contracts section
- Modify: `docs/open-work.md` — mark P1 done, name P2 as next

**Interfaces:**
- Consumes: the finished `GET /hub` contract from Task 7.
- Produces: nothing code reads.

- [ ] **Step 1: Add the index row**

Read `docs/endpoint-map.md`'s Master Endpoint Index and add a row for `GET /hub` in the same column order the existing rows use (`# | METHOD | path | gate | router → service | tables | api.js wrapper | view`). Use id `H1`. The wrapper and view columns are `—` for now with a note that P2 adds them:

```
| H1 | GET | `/hub` | any authenticated | `hub.py` → `hub.personal_hub` → `work_orders.sweep_stale_sessions` + `labor_summary.day_summary` + `tools.user_custody_detail` | work_order_labor_sessions (r/w on sweep), work_order_labor (r; w on sweep), work_orders (r; row lock on sweep), work_order_technicians (r), tool_transactions (r), tools (r), users (r) | — (P2) | — (P2) |
```

- [ ] **Step 2: Add the read-flow entry**

In `## Direction A — Database → User View (read flows)`, add a new `### User Hub` subsection immediately before `### Cross-feature read`, matching the bullet style of `### Tools`:

```markdown
### User Hub
- **work_order_labor_sessions ⋈ work_orders** → `labor_summary.day_summary` →
  `GET /hub` → *(P2)*: today's tracked minutes and the timeline strip. Aggregated
  by **interval overlap** against the Central calendar day, not by a
  `started_at` range filter — a session running 11:30 PM Monday to 12:30 AM
  Tuesday gives 30 minutes to each day. The day is `[00:00, 24:00)` in
  `America/Chicago`, the same zone `NOTE_TIMEZONE` stamps the note log with, so
  the hub and the note timeline never disagree about which day a stop belongs
  to. DST is handled by `zoneinfo`: the day is 23 or 25 hours and the
  arithmetic is instant-based.
- **work_order_labor (no session) ⋈ users ⋈ work_orders** →
  `labor_summary._adjustments_for_day` → `GET /hub` → *(P2)*: hand-entered
  labor, identified by the LEFT JOIN to `work_order_labor_sessions` finding
  nothing. Reported on its own `Adjustments` line with the recorder's name,
  **counted in the day total**, and absent from the timeline — it carries no
  start or stop, so there is nothing to draw. Filed under the Central date of
  `created_at`, so a Friday correction to Tuesday's work lands on Friday
  (known limitation, iteration 1).
- **work_orders ⋈ work_order_technicians** → `hub.personal_hub` → `GET /hub` →
  *(P2)*: the three counts and the `Start on…` picker. Assignment is matched
  through **both** the legacy `assigned_to_id` column and
  `work_order_technicians` rows — the same `or_` pair
  `work_orders._scoped_to_user` uses — so the hub's count and the Work Orders
  page can never disagree about what somebody has been given. Counts are a
  total and two subsets of it, not three disjoint buckets.
- **tool_transactions ⋈ tools** → `tools.user_custody_detail` → `GET /hub` →
  *(P2)*: tools the caller is still holding, with how long each has been out.
  `since` is the checkout that opened the current unbroken spell
  (`domain.tools.custody_since`); a partial return does not end a spell.
- **Minutes on this endpoint are *tracked* minutes** — real wall-clock overlap.
  They are not `capped_session_minutes` (floors at 1, caps at 720) and not
  `billed_labor_minutes` (rounds up to 30 min at $62.50/hr). No hub surface
  shows a billed figure under a "time worked" label.
- **This GET is not side-effect-free.** It calls
  `work_orders.sweep_stale_sessions(technician_id=caller)` before reading, so a
  clock forgotten on Tuesday does not read as a 20-hour running total on
  Wednesday. Precedent: `get_work_order` already both sweeps sessions and heals
  orphaned material lines on a read. Bounded to at most one row by the partial
  unique index, idempotent, and taken under the same row lock the stop path
  uses. It does **not** auto-hold, and a swept session still closes at
  `started_at + 720min` — only the `auto_closed_at` flag is late.
```

- [ ] **Step 3: Add the response contract**

In `## Request / Response Contracts`, add a `### User Hub (`schemas/hub.py`)` subsection after `### Tools (`schemas/tools.py`)`, in that section's prose style:

```markdown
### User Hub (`schemas/hub.py`)

**`HubResponse`** — `GET /hub` (any authenticated role): `user: HubUser`,
`server_now: datetime`, `day: date` (Central), `clock: HubClock`,
`timeline: list[HubTimelineEntry] = []`, `counts: HubCounts`,
`startable: list[HubStartable] = []`, `tools_out: list[HubToolOut] = []`.
`server_now` is the client's clock-skew anchor — it records
`skew = server_now − Date.now()` at fetch time and renders elapsed against
it, so a field phone with a wrong system clock still shows the right number.

**`HubUser`**: `id`, `first_name?`, `last_name?`, `role`. Deliberately not the
full user record — no username, no timestamps; the hub needs an identity, not
an account.

**`HubClock`**: `running_session: HubRunningSession? = null`,
`closed_minutes_today: int`, `running_minutes_today: int`,
`adjustment_minutes_today: int`, `adjustments: list[HubAdjustment] = []`, and
a computed `total_minutes_today` = the sum of the three. Anchors, not a
ticking number: the server sends what is fixed and the client renders the live
figure on a 1-second interval, so nothing polls for a value that changes once
a minute. **`total_minutes_today` includes adjustments** — one number means
one thing on every surface, and the tracked/adjusted split is one expand away.

**`HubRunningSession`**: `work_order_id`, `number`, `started_at`,
`day_counting_from`. **Two anchors, and they are not interchangeable.**
`started_at` drives the widget's session elapsed ("started 8:12 AM");
`day_counting_from` drives *today's* total and equals midnight Central for a
clock inherited from yesterday. Ticking the day total from `started_at` would
report an hour for a session that has given today thirty minutes.

**`HubTimelineEntry`**: `work_order_id`, `number`, `started_at`, `ended_at?`,
`auto_closed: bool`, `minutes: int`. `minutes` is that session's share of
**this** day, so a midnight crossing appears on both days at its real weight
and is not `ended_at − started_at`. `auto_closed` marks a session the 12-hour
cap ended — an estimate a supervisor should correct, not a fact. A session
that only touches the day (a stop at exactly midnight) is omitted.

**`HubAdjustment`**: `minutes`, `recorded_by_name` (`"Name unavailable"` when
the recorder is unset), `work_order_number`.

**`HubCounts`**: `assigned`, `in_progress`, `ready_to_complete` — a **total and
two subsets of it**. `assigned` is every non-archived work order the caller is
an assigned technician on, whatever its status; the other two count members of
that same set. "8 assigned, 1 in progress, 2 ready" describes 8 work orders,
not 11.

**`HubStartable`**: `work_order_id`, `number`, `status`, `community?`,
`building_number?`, `unit_number?`, `location?` — one option in the
`Start on…` picker, limited to `work_orders.TRACKING_START_STATUSES` so the
picker can never offer a row `start_labor_session` would refuse. Ordered
In-Progress → On-Hold → Assigned → Created, then by number. Place fields are
raw; `static/views/workOrders.js::placeMeta` composes them, so one composer
owns every address in the app.

**`HubToolOut`**: `tool_id`, `name`, `barcode`, `quantity: Decimal`,
`since: datetime?` — oldest spell first.
```

- [ ] **Step 4: Update the backlog**

`docs/open-work.md` is the only backlog file and owns the full write-up for every open item. Add the User Hub phases to it as one item, following the file's existing entry format (a heading, what it is, why, and its current state). Record:

- **P1 · Time engine — shipped.** `domain/labor_day.py`, `services/labor_summary.py`, `services/hub.py`, `GET /hub`, and the global stale-session sweep. Backend only; no UI.
- **P2 · Technician hub — next.** The page fragment, tab shell, clock widget, technician dashboard, the `mountWorkOrderList({container, lockedFilter})` extraction from `views/workOrders.js`, and the nav/landing changes. Carries the schedule risk: if the extraction proves messier than it looks, the fallback is a read-only card list.
- **P3 · Supervisor hub.** `GET /hub/crew`, crew board, attention flags, the `labor.session.changed` realtime event (plus its row in `docs/notification-events.md`), **and** `GET /hub/timesheets` with the grid and CSV export. The larger of the two remaining phases.
- **P4 · Admin hub.** `GET /hub/admin`, the four tile groups, the conditional crew board, and widening the timesheet row scope from "my crew" to everyone.

Link each to `docs/superpowers/specs/2026-08-20-user-hub-design.md`. Do not create a second backlog file and do not add a separate index.

- [ ] **Step 5: Verify the docs suite still passes**

```bash
cd backend && ./venv/Scripts/python.exe -m pytest tests/test_docs_endpoints.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add docs/endpoint-map.md docs/open-work.md
git commit -m "docs(user-hub): register GET /hub in the endpoint map"
```

---

## Done when

- `./venv/Scripts/python.exe -m pytest -q` passes from `backend/` with Postgres up.
- `GET /hub` returns the payload above for a technician, a supervisor, and an admin, and 401 without a session cookie.
- A session backdated 20 hours is closed at `started_at + 720min`, flagged `auto_closed_at`, and leaves the work order's status alone.
- A session spanning midnight reports its two halves on the two days, and a running one inherited from yesterday reports `day_counting_from == ` today's midnight Central.
- No file under `backend/static/` changed, and `SHELL_PARTS` is untouched.

## Not in this phase

`GET /hub/crew`, `GET /hub/admin`, `GET /hub/timesheets`, the `labor.session.changed` realtime event, `domain/hub.py`'s attention thresholds, and every frontend file. P2 is the technician hub; P3 is the supervisor hub plus timesheets; P4 is admin.
