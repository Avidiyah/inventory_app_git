"""Pure attention-flag rules and thresholds for the User Hub.

Layer: domain. No FastAPI, no SQLAlchemy -- the same convention
`domain/labor_day.py` follows, and for the same reason: every threshold here
is fully unit-testable without a database and tunable in one place (spec
§6.3).

Predicates return flag strings rather than booleans. The payload carries a
small vocabulary (`long_session`, `approaching_cap`, `assigned_idle`,
`stale_work_order`) that the frontend renders as an icon plus a word, never
color alone -- required by spec §8 and by the fact that these are read in
jobsite glare.
"""

from datetime import datetime, timedelta
from typing import Optional

from app.domain.labor_day import CENTRAL

# 8 h running -- an early warning ahead of the 12 h cap.
LONG_SESSION_WARN_MINUTES = 480

# 11 h running -- the last hour before the 12 h cap truncates recorded time.
SESSION_CAP_WARN_MINUTES = 660

# Don't paint the crew board red before this Central hour: nobody has done
# a full day's nothing at 7:00 a.m.
IDLE_CHECK_HOUR = 10

# in_progress/on_hold with no labor-session activity for this many days
# reads as stale.
STALE_WORK_ORDER_DAYS = 3

FLAG_LONG_SESSION = "long_session"
FLAG_APPROACHING_CAP = "approaching_cap"
FLAG_ASSIGNED_IDLE = "assigned_idle"
FLAG_STALE_WORK_ORDER = "stale_work_order"


def session_flag(running_minutes: int) -> Optional[str]:
    """Which long-running-clock flag, if any, a running session earns.

    Checked highest-severity first: a session past the cap-warning line has
    also crossed the long-session line, and only the more specific flag
    should render.
    """
    if running_minutes >= SESSION_CAP_WARN_MINUTES:
        return FLAG_APPROACHING_CAP
    if running_minutes >= LONG_SESSION_WARN_MINUTES:
        return FLAG_LONG_SESSION
    return None


def is_assigned_idle(*, assigned_count: int, minutes_today: int, now: datetime) -> bool:
    """True when someone has work assigned, has tracked nothing today, and
    it is late enough in the Central day that the silence is meaningful.

    The `IDLE_CHECK_HOUR` guard is what keeps the board from reading as
    solid warnings at 7:00 a.m., before anyone could plausibly have started.
    """
    if assigned_count < 1 or minutes_today > 0:
        return False
    return now.astimezone(CENTRAL).hour >= IDLE_CHECK_HOUR


def is_stale_work_order(*, last_activity_at: Optional[datetime], now: datetime) -> bool:
    """True when a work order has had no labor-session activity -- a start
    or a stop -- for `STALE_WORK_ORDER_DAYS`.

    Callers pre-filter to `in_progress`/`on_hold` work orders and pass the
    most recent of any session's `started_at` or `ended_at` on that work
    order, so a session that is *currently running* always counts as recent
    activity through its own `started_at` -- there is no way for an active
    clock to read as stale.

    `last_activity_at=None` means no session has ever touched this work
    order, which is also stale: "no labor session for 3 days" trivially
    covers "no labor session ever."
    """
    if last_activity_at is None:
        return True
    return (now - last_activity_at) >= timedelta(days=STALE_WORK_ORDER_DAYS)
