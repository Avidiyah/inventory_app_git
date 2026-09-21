"""Attendance response contracts.

Layer: schemas. Consumed by `app/routers/attendance.py`. Every model is
`from_attributes`, so a field renamed on either side fails a test instead of
quietly serialising as null -- the rule `schemas/hub.py` set.
"""

import uuid
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel

from app.schemas.hub import HubUser


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
    never rounded to 30 the way `billed_labor_minutes` is (8)."""

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


class AttendanceWeekPunch(BaseModel):
    """One punch's contribution to **one** day. `minutes` is clipped to that
    day; `carried` is true on every day after the one it started on, which
    spec §9 makes the owner of the punch. `open` means still on shift, so
    `minutes` is counted to `server_now` and climbs."""

    id: uuid.UUID
    started_at: datetime
    ended_at: Optional[datetime] = None
    start_source: str
    end_source: Optional[str] = None
    needs_review: bool
    minutes: int
    carried: bool
    open: bool

    model_config = {"from_attributes": True}


class AttendanceWeekDay(BaseModel):
    date: date
    clocked_minutes: int
    # The comparison columns (P4a, spec §8). Real wall-clock, both of them:
    # `tracked` is time on a job, `delta` is `clocked - tracked` floored at
    # zero -- on shift, not on a job. `outside_shift` is the other direction,
    # charged time no punch covers (§9), which is flagged, never refused.
    # `adjustment` is hand-entered labor with no start or stop: carried here,
    # never counted into either wall-clock number.
    tracked_minutes: int
    delta_minutes: int
    outside_shift_minutes: int
    adjustment_minutes: int
    needs_review: bool
    has_open: bool
    punches: list[AttendanceWeekPunch]

    model_config = {"from_attributes": True}


class AttendanceWeekRow(BaseModel):
    user: HubUser
    days: list[AttendanceWeekDay]
    total_minutes: int
    tracked_minutes: int
    delta_minutes: int

    model_config = {"from_attributes": True}


class AttendanceWeekDayTotal(BaseModel):
    date: date
    minutes: int

    model_config = {"from_attributes": True}


class AttendanceWeekResponse(BaseModel):
    """Clocked time only (§8): real wall-clock on shift, never rounded.

    Clocked is the pay number (§8) and is never rounded. `tracked_minutes`
    and `delta_minutes` join it here for the comparison sub-tab; the Hours
    grid reads the same object and ignores them. There is no billed column:
    `billed_labor_minutes` rounds a whole work order's combined labor, so no
    honest per-person-per-day billed number exists to put here.

    `week_hours` is 168, or 167 / 169 across a DST transition. The grid's
    footer prints it so a short week does not read as missing hours."""

    week_start: date
    week_end: date
    server_now: datetime
    days: list[date]
    rows: list[AttendanceWeekRow]
    totals_by_day: list[AttendanceWeekDayTotal]
    total_minutes: int
    tracked_minutes: int
    delta_minutes: int
    week_hours: int

    model_config = {"from_attributes": True}


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
