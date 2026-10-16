"""Attendance response contracts.

Layer: schemas. Consumed by `app/routers/attendance.py`. Every model is
`from_attributes`, so a field renamed on either side fails a test instead of
quietly serialising as null -- the rule `schemas/hub.py` set.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.hub import HubAdjustment, HubUser


class AttendanceOpenPunch(BaseModel):
    """The caller's open punch: always today's, because a punch past its
    midnight reads closed (M1)."""

    id: uuid.UUID
    started_at: datetime
    start_source: str

    model_config = {"from_attributes": True}


class AttendanceMyPunch(BaseModel):
    """One of the caller's own open-week punches; `tags` holds `self` /
    `admin` edit marks (2026-10-16 self-edit)."""

    id: uuid.UUID
    started_at: datetime
    ended_at: Optional[datetime] = None
    needs_review: bool
    tags: list[str] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class AttendanceMeResponse(BaseModel):
    """`clocked_minutes_today` is the pay number: real wall-clock on shift,
    never rounded to 30 the way `billed_labor_minutes` is (8)."""

    server_now: datetime
    day: date
    open_punch: Optional[AttendanceOpenPunch] = None
    clocked_minutes_today: int
    week_punches: list[AttendanceMyPunch] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class AttendancePunchResponse(BaseModel):
    id: uuid.UUID
    started_at: datetime
    ended_at: Optional[datetime] = None
    start_source: str
    end_source: Optional[str] = None
    needs_review: bool

    model_config = {"from_attributes": True}


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
    lunch_waived: bool
    crosses_midnight: bool = False

    model_config = {"from_attributes": True}


class AttendanceWeekDay(BaseModel):
    date: date
    # Gross on-shift time; `paid_minutes = clocked_minutes - lunch_minutes`
    # (L3). Delta below stays on the gross number.
    clocked_minutes: int
    lunch_minutes: int
    lunch_waived: bool
    paid_minutes: int
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
    # The day rests on a forgotten clock; the leaderboard sets it aside.
    pending_review: bool
    punches: list[AttendanceWeekPunch]

    model_config = {"from_attributes": True}


class AttendanceWeekRow(BaseModel):
    user: HubUser
    days: list[AttendanceWeekDay]
    total_minutes: int
    paid_minutes: int
    tracked_minutes: int
    delta_minutes: int
    # Hand-entered labor on unflagged days; the Efficiency board adds it.
    adjustment_minutes: int = 0

    model_config = {"from_attributes": True}


class AttendanceWeekDayTotal(BaseModel):
    date: date
    minutes: int
    paid_minutes: int

    model_config = {"from_attributes": True}


class AttendanceWeekResponse(BaseModel):
    """Clocked time only (§8): real wall-clock on shift, never rounded.

    Clocked is the pay number (§8) and is never rounded. `tracked_minutes`
    and `delta_minutes` join it here for the leaderboard; the Hours
    grid reads the same object and ignores them. There is no billed column:
    `billed_labor_minutes` rounds a whole work order's combined labor, so no
    honest per-person-per-day billed number exists to put here.

    `week_hours` is 168, or 167 / 169 across a DST transition. The grid's
    footer prints it so a short week does not read as missing hours.

    `labor_rate` is billing's own $/hour, sent so the revenue leaderboard
    never carries a second copy of it."""

    week_start: date
    week_end: date
    server_now: datetime
    days: list[date]
    rows: list[AttendanceWeekRow]
    totals_by_day: list[AttendanceWeekDayTotal]
    total_minutes: int
    paid_minutes: int
    tracked_minutes: int
    delta_minutes: int
    week_hours: int
    labor_rate: Decimal
    reviewable_count: int

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


class WeekReviewResponse(BaseModel):
    """What `Mark all reviewed` accepted for one week."""

    punches: int
    sessions: int

    model_config = {"from_attributes": True}


class PunchEditRequest(BaseModel):
    """An omitted field means **unchanged**, never *clear*. `needs_review`
    only ever arrives as `false`: alone it is the "Looks right" action, and
    nothing but the midnight close may raise the flag."""

    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    needs_review: Optional[bool] = None
    # L2: remove (true) or restore (false) the day's flat lunch. Never
    # clears `needs_review`.
    lunch_waived: Optional[bool] = None
    reason: Optional[str] = None


class PersonWeekCompleted(BaseModel):
    work_order_id: uuid.UUID
    number: str
    location: Optional[str] = None
    completed_at: datetime
    status: str
    archived: bool

    model_config = {"from_attributes": True}


class PersonWeekChargedSpan(BaseModel):
    started_at: datetime
    ended_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class PersonWeekCharged(BaseModel):
    """One work order's charged minutes for one day, summed across that day's
    sessions on it; `spans` keeps each session's clock times."""

    work_order_id: uuid.UUID
    number: str
    minutes: int
    auto_closed: bool
    running: bool
    spans: list[PersonWeekChargedSpan]

    model_config = {"from_attributes": True}


class PersonWeekDay(BaseModel):
    date: date
    clocked_minutes: int
    lunch_minutes: int
    paid_minutes: int
    charged_minutes: int
    adjustment_minutes: int
    completed_count: int
    needs_review: bool
    has_open: bool
    completed: list[PersonWeekCompleted] = []
    charged: list[PersonWeekCharged] = []
    adjustments: list[HubAdjustment] = []
    punches: list[AttendanceWeekPunch] = []

    model_config = {"from_attributes": True}


class PersonWeekResponse(BaseModel):
    """`GET /hub/people/{user_id}/week`: one crew member's Central week,
    seven days always present. Wall-clock minutes only -- no billed number,
    no dollar figure (spec D9)."""

    user: HubUser
    archived: bool
    week_start: date
    week_end: date
    server_now: datetime
    days: list[PersonWeekDay]
    total_clocked_minutes: int
    total_paid_minutes: int
    total_charged_minutes: int
    total_adjustment_minutes: int
    total_completed: int
    reviewable: bool

    model_config = {"from_attributes": True}
