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


def week_bounds_containing(day: date) -> tuple[date, date]:
    """Return the Monday and Sunday containing ``day``, both inclusive.

    Callers pass an already-resolved Central calendar date, so this is pure
    date arithmetic. Keeping it here gives the timesheet and the later Admin
    billing view one definition of "current week."
    """
    start = day - timedelta(days=day.weekday())
    return start, start + timedelta(days=6)


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
