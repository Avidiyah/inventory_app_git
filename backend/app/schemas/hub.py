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


class HubPriorityCounts(BaseModel):
    """High-priority live-work-order counts for the Priorities card.
    `unassigned` is omitted (stays `None`) for a Technician's personal
    payload, which has no such number."""

    assigned: int
    unassigned: Optional[int] = None

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
    priority: HubPriorityCounts
    startable: list[HubStartable] = []
    tools_out: list[HubToolOut] = []

    model_config = {"from_attributes": True}


# --- GET /hub/crew (P3a) ----------------------------------------------------


class HubLedCounts(BaseModel):
    """A total and two subsets of the work orders this supervisor leads --
    same convention as `HubCounts`."""

    total: int
    in_progress: int
    ready_to_complete: int

    model_config = {"from_attributes": True}


class HubCrewTechnician(BaseModel):
    """One card on the crew board. Minutes, never dollars -- cost figures
    stay redacted below TechFM OA (spec §9); nothing here needs one."""

    user: HubUser
    running_session: Optional[HubRunningSession] = None
    minutes_today: int
    assigned: int
    in_progress: int
    ready_to_complete: int
    last_worked: Optional[datetime] = None
    flags: list[str] = []

    model_config = {"from_attributes": True}


class HubAttentionItem(BaseModel):
    """One row in the "Needs attention" list. `detail` is a server-composed
    sentence -- spec §7 abbreviates this contract to exactly
    `{kind, subject, detail}`."""

    kind: str
    subject: str
    detail: str

    model_config = {"from_attributes": True}


class HubCrewResponse(BaseModel):
    """`GET /hub/crew`. Crew membership is derived from routing (D6); the
    supervisor's own row is excluded from both `technicians` and
    `crew_minutes_today` (D13)."""

    server_now: datetime
    led: HubLedCounts
    priority: HubPriorityCounts
    crew_on_clock: int
    crew_total: int
    crew_minutes_today: int
    technicians: list[HubCrewTechnician] = []
    attention: list[HubAttentionItem] = []

    model_config = {"from_attributes": True}


# --- GET /hub/admin (P4 slice 1) --------------------------------------------


class HubAdminPipeline(BaseModel):
    """Company-wide, unscoped work-order status counts -- six columns, not
    seven (`on_hold` has no column; see the service dataclass's docstring)."""

    created: int
    assigned: int
    in_progress: int
    ready_to_complete: int
    completed: int
    review: int

    model_config = {"from_attributes": True}


class HubAdminOnClockEntry(BaseModel):
    """One row of the company-wide "On the clock now" list."""

    technician_name: str
    work_order_number: str
    community: Optional[str]
    started_at: datetime
    elapsed_minutes: int
    flag: Optional[str]

    model_config = {"from_attributes": True}


class HubAdminExceptions(BaseModel):
    """The "Exceptions" tile group -- five open-work counts."""

    inventory_recounts: int
    missing_item_price: int
    item_requests: int
    admin_review_queue: int
    stale_work_orders: int

    model_config = {"from_attributes": True}


class HubAdminBilling(BaseModel):
    """Billing · this week (D12: current Central week for the $ figures;
    the average and sparkline look at the trailing 14 days instead -- see
    the service dataclass's docstring). `legacy_live_count` is `None`
    unless the viewer is the Owner, matching the existing Owner-exactly
    gate on the legacy re-archive endpoints."""

    materials_total: Decimal
    labor_total: Decimal
    total: Decimal
    avg_days_to_complete: Optional[float]
    completed_per_day: list[int]
    legacy_live_count: Optional[int]

    model_config = {"from_attributes": True}


class HubAdminResponse(BaseModel):
    """`GET /hub/admin`. Bucketed by account role, not by what work was
    clocked on -- a TechFM OA/Admin/Owner's own hours (if any) land in
    neither bucket; their own time is already the personal clock widget."""

    server_now: datetime
    supervisor_minutes_today: int
    technician_minutes_today: int
    pipeline: HubAdminPipeline
    priority: HubPriorityCounts
    on_the_clock: list[HubAdminOnClockEntry] = []
    exceptions: HubAdminExceptions
    billing: HubAdminBilling

    model_config = {"from_attributes": True}


# --- GET /hub/graphs -------------------------------------------------------


class HubGraphStatus(BaseModel):
    key: str
    label: str

    model_config = {"from_attributes": True}


class HubGraphDistribution(BaseModel):
    key: str
    label: str
    total: int
    counts: dict[str, int]

    model_config = {"from_attributes": True}


class HubGraphDurationRange(BaseModel):
    start: date
    end: date

    model_config = {"from_attributes": True}


class HubGraphDurationBucket(BaseModel):
    start: date
    end: date
    partial: bool
    circulating_avg_age_days: Optional[float] = None
    circulating_count: int
    closed_avg_days: Optional[float] = None
    closed_count: int

    model_config = {"from_attributes": True}


class HubGraphDuration(BaseModel):
    range: HubGraphDurationRange
    buckets: list[HubGraphDurationBucket] = []

    model_config = {"from_attributes": True}


class HubGraphsResponse(BaseModel):
    """`GET /hub/graphs`: a guided report for TechFM OA and above."""

    generated_at: datetime
    weeks: int
    statuses: list[HubGraphStatus] = []
    priority_high: HubGraphDistribution
    priority_medium: HubGraphDistribution
    communities: list[HubGraphDistribution] = []
    service_types: list[HubGraphDistribution] = []
    duration: HubGraphDuration

    model_config = {"from_attributes": True}


# --- GET /hub/timesheets (P3b) ---------------------------------------------


class HubTimesheetRange(BaseModel):
    start: date
    end: date

    model_config = {"from_attributes": True}


class HubTimesheetDay(BaseModel):
    """One adjustment-aware grid cell and its inline drill-down detail."""

    date: date
    tracked_minutes: int
    adjustment_minutes: int
    flags: list[str] = []
    sessions: list[HubTimelineEntry] = []
    adjustments: list[HubAdjustment] = []

    @computed_field
    @property
    def total_minutes(self) -> int:
        return self.tracked_minutes + self.adjustment_minutes

    model_config = {"from_attributes": True}


class HubTimesheetRow(BaseModel):
    user: HubUser
    days: list[HubTimesheetDay] = []
    total_minutes: int

    model_config = {"from_attributes": True}


class HubTimesheetDayTotal(BaseModel):
    date: date
    minutes: int

    model_config = {"from_attributes": True}


class HubTimesheetResponse(BaseModel):
    """Supervisor+ timesheets, scoped to the caller's routed crew in P3b."""

    range: HubTimesheetRange
    rows: list[HubTimesheetRow] = []
    crew_totals_by_day: list[HubTimesheetDayTotal] = []

    model_config = {"from_attributes": True}
