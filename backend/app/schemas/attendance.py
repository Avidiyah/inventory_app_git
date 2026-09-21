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
    needs_review: bool
    has_open: bool
    punches: list[AttendanceWeekPunch]

    model_config = {"from_attributes": True}


class AttendanceWeekRow(BaseModel):
    user: HubUser
    days: list[AttendanceWeekDay]
    total_minutes: int

    model_config = {"from_attributes": True}


class AttendanceWeekDayTotal(BaseModel):
    date: date
    minutes: int

    model_config = {"from_attributes": True}


class AttendanceWeekResponse(BaseModel):
    """Clocked time only (§8): real wall-clock on shift, never rounded.
    `tracked` and `billed` join this payload additively in P4 -- the
    comparison sub-tab reads the same object this one does.

    `week_hours` is 168, or 167 / 169 across a DST transition. The grid's
    footer prints it so a short week does not read as missing hours."""

    week_start: date
    week_end: date
    server_now: datetime
    days: list[date]
    rows: list[AttendanceWeekRow]
    totals_by_day: list[AttendanceWeekDayTotal]
    total_minutes: int
    week_hours: int

    model_config = {"from_attributes": True}
