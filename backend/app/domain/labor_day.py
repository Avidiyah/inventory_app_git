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
