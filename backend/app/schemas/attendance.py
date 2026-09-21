"""Attendance response contracts.

Layer: schemas. Consumed by `app/routers/attendance.py`. Every model is
`from_attributes`, so a field renamed on either side fails a test instead of
quietly serialising as null -- the rule `schemas/hub.py` set.
"""

import uuid
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


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
