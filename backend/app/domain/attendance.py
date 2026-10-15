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
# and idle this long or longer reads red on the Admin roster (2).
IDLE_RED_MINUTES = 10

# L1: a flat lunch off any day long enough to have one.
LUNCH_MINUTES = 30
LUNCH_MIN_DAY_MINUTES = 360   # owner, 2026-10-15

START_SOURCE_MANUAL = "manual"
START_SOURCE_AUTO_WORK_ORDER = "auto_work_order"

END_SOURCE_MANUAL = "manual"
# The midnight close (M1): `services.attendance.sweep_open_punches` writes it.
END_SOURCE_AUTO_CLOCK_OUT = "auto_clock_out"
# Legacy rows from the retired self-close; nothing writes it any more.
END_SOURCE_SELF_REPORTED = "self_reported"
END_SOURCE_ADMIN_EDIT = "admin_edit"

# On shift and charging / on shift, idle briefly / on shift, idle long / off.
STATE_GREEN = "green"
STATE_YELLOW = "yellow"
STATE_RED = "red"
STATE_GRAY = "gray"


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
    consequence in 2 is that a slow start after arrival shows red before the
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


def shift_state(
    *,
    punch_started_at: Optional[datetime],
    labor_running: bool,
    last_labor_ended_at: Optional[datetime],
    now: datetime,
) -> str:
    """The roster color (2). Gray means no open punch -- not "absent";
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


def midnight_after(started_at: datetime) -> datetime:
    """The Central midnight that ends `started_at`'s day (M1). DST-safe
    because `day_bounds` is."""
    return labor_day.day_bounds(labor_day.central_date_of(started_at))[1]


def lunch_minutes(gross: int, *, waived: bool) -> int:
    """L1: the lunch a day's gross clocked minutes lose. No time-of-day logic
    and no gap detection -- one punch pair per day is the assumption."""
    return LUNCH_MINUTES if gross >= LUNCH_MIN_DAY_MINUTES and not waived else 0


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


def validate_punch_window(
    started_at: datetime,
    ended_at: Optional[datetime],
    *,
    now: datetime,
) -> None:
    """Spec 9's first two rows plus M4 (no punch crosses Central midnight).
    `ended_at=None` is an open punch, valid."""
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
    if end > midnight_after(start):
        raise PunchTimeInvalidError("A punch may not cross midnight.")


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
