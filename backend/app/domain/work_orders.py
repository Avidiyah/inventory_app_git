"""Pure work-order rules (identity, status, entry mode, visibility scope).

Layer: pure domain (no SQLAlchemy, no FastAPI, no models) -- exercised by plain
unit tests, like `domain.mass_staging` and `domain.roles`.

A work order is a standalone entity whose identity is its `number` (unique
case-insensitively + trimmed). Its live lifecycle is `created -> assigned ->
in_progress -> completed -> review`, with `on_hold` as a supervisor-controlled
pause: technician assignment derives `assigned`, and the first material/labor
activity derives `in_progress`. `closed` is the row's `archived_at`, not
duplicated in `status`. `entry_mode` is the default mode
for newly logged materials: `dispense` moves stock, `retroactive` is a
stock-neutral paper backfill.
"""

import re
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional, Sequence
from urllib.parse import quote
from uuid import UUID
from zoneinfo import ZoneInfo

from app.domain import roles
from app.domain.errors import WorkOrderStateError


# --- identity ------------------------------------------------------------

def normalize_number(number: str) -> str:
    """The canonical comparison form of a work-order number: trimmed +
    lowercased. Mirrors the DB's `lower(btrim(number))` unique index, so
    find-or-create and the constraint agree on what "the same number" means.
    Internal whitespace is preserved (btrim only strips the ends)."""
    return number.strip().lower()


# --- status vocabulary ---------------------------------------------------

STATUS_CREATED = "created"
STATUS_ASSIGNED = "assigned"
STATUS_IN_PROGRESS = "in_progress"
STATUS_ON_HOLD = "on_hold"
STATUS_COMPLETED = "completed"
STATUS_REVIEW = "review"

ALL_STATUSES: tuple[str, ...] = (
    STATUS_CREATED,
    STATUS_ASSIGNED,
    STATUS_IN_PROGRESS,
    STATUS_ON_HOLD,
    STATUS_COMPLETED,
    STATUS_REVIEW,
)
# Every stored status is live. Closed work orders are archived and therefore do
# not carry a sixth status value.
ACTIVE_STATUSES: tuple[str, ...] = ALL_STATUSES


# --- entry mode vocabulary -----------------------------------------------

MODE_DISPENSE = "dispense"
MODE_RETROACTIVE = "retroactive"

ALL_MODES: tuple[str, ...] = (MODE_DISPENSE, MODE_RETROACTIVE)


# --- append-only notes ---------------------------------------------------

NOTE_TIMEZONE = ZoneInfo("America/Chicago")

# Written to the note log when a Technician's completion parks the work order
# On-Hold (`completion_target_status`). It is the only thing distinguishing that
# hold from an ordinary mid-job pause, so it is a constant rather than a string
# typed at the call site -- the Supervisor reading the log is the audience.
REVIEW_HOLD_NOTE = "Placed On-Hold for Supervisor Review"


def append_note_log(
    existing: Optional[str],
    note: str,
    *,
    author_name: str,
    occurred_at: datetime,
) -> str:
    """Append one server-authored plain-text entry to a Work Order note log.

    New entries use the requested ``[TIME] [MMDDYY] [User] text`` shape in the
    application's Central timezone. Existing free-form text is retained as-is,
    so notes written before the log format was introduced are never discarded.
    """
    body = note.strip()
    if not body:
        raise WorkOrderStateError("Note text is required.")
    author = author_name.strip() or "Name unavailable"
    instant = occurred_at
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    local = instant.astimezone(NOTE_TIMEZONE)
    hour = local.strftime("%I").lstrip("0") or "12"
    entry = (
        f"[{hour}:{local.strftime('%M %p')}] "
        f"[{local.strftime('%m%d%y')}] [{author}] {body}"
    )
    prior = (existing or "").rstrip()
    return f"{prior}\n\n{entry}" if prior else entry


# --- list-filter vocabulary ----------------------------------------------

COMMUNITY_SCHOLARS = "scholars"
COMMUNITY_CENTENNIAL = "centennial"
COMMUNITY_COMMONS = "commons"
COMMUNITY_YOUNG_HALL = "young_hall"
COMMUNITY_ACADEMICS = "academics"

COMMUNITY_LABELS: dict[str, str] = {
    COMMUNITY_SCHOLARS: "Scholars",
    COMMUNITY_CENTENNIAL: "Centennial",
    COMMUNITY_COMMONS: "Commons",
    COMMUNITY_YOUNG_HALL: "Young Hall",
    COMMUNITY_ACADEMICS: "Academics",
}

# A work order may mention several communities in one raw LOCATION value. Each
# named filter is therefore membership-based rather than an exclusive tag.
# Academics is the fallback for rows containing none of these known terms.
COMMUNITY_SEARCH_TERMS: dict[str, tuple[str, ...]] = {
    COMMUNITY_SCHOLARS: ("scholars",),
    COMMUNITY_CENTENNIAL: ("centennial",),
    COMMUNITY_COMMONS: ("commons", "cimarron", "cimmarron"),
    COMMUNITY_YOUNG_HALL: ("young hall",),
}

ALL_COMMUNITY_FILTERS: tuple[str, ...] = tuple(COMMUNITY_LABELS)


def normalize_community_filter(value: Optional[str]) -> Optional[str]:
    """Normalize and validate the Work Orders community query value.

    Blank means no community filter. Values are API identifiers, but accepting
    spaces as underscores keeps a hand-written ``Young Hall`` query friendly.
    """
    if value is None or not value.strip():
        return None
    normalized = value.strip().casefold().replace(" ", "_")
    if normalized not in ALL_COMMUNITY_FILTERS:
        raise WorkOrderStateError(
            "Community must be scholars, centennial, commons, young_hall, or academics."
        )
    return normalized


# Priority is raw text scraped from the vendor's "Priority Level" field, so the
# value set is open and this sentinel has to be something no vendor value could
# be. It selects the work orders NetFacilities enrichment never reached -- the
# ones the detail card labels "Not imported".
PRIORITY_FILTER_NONE = "__none__"


def normalize_priority_filter(value: Optional[str]) -> Optional[str]:
    """Normalize the Work Orders priority query value.

    Blank means no priority filter, and `PRIORITY_FILTER_NONE` passes through as
    the unimported sentinel. Anything else filters on itself.

    Deliberately unlike `normalize_community_filter`, which rejects values
    outside its fixed set: priority has no fixed set to validate against, and
    rejecting unknown text would make a level the vendor adds later unfilterable
    until someone changes this file.
    """
    if value is None or not value.strip():
        return None
    return value.strip()


def parse_schedule_date(value: Optional[str]) -> Optional[date]:
    """Parse the leading date from the import's raw schedule text.

    Vendor rows primarily use M/D/YYYY and sometimes append a time. ISO dates
    are accepted for explicit edits. Blank, malformed, and shifted CSV values
    stay valid raw metadata but are treated as unscheduled for filtering and
    ordering.
    """
    if value is None or not value.strip():
        return None
    raw = value.strip()
    slash = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})(?:\s|$)", raw)
    if slash:
        month, day, year = (int(part) for part in slash.groups())
        if year < 100:
            year += 2000
        try:
            return date(year, month, day)
        except ValueError:
            return None
    iso = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:\s|$)", raw)
    if iso:
        year, month, day = (int(part) for part in iso.groups())
        try:
            return date(year, month, day)
        except ValueError:
            return None
    return None


# --- labor billing -------------------------------------------------------

LABOR_RATE = Decimal("62.50")
LABOR_INCREMENT_MINUTES = 30


def validate_labor_minutes(minutes: int) -> None:
    """Labor entries are positive, whole-minute durations."""
    if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes <= 0:
        raise WorkOrderStateError("Labor minutes must be a positive whole number.")


def billed_labor_minutes(total_minutes: int) -> int:
    """Round combined work-order labor up to the next 30-minute increment."""
    if isinstance(total_minutes, bool) or not isinstance(total_minutes, int) or total_minutes < 0:
        raise WorkOrderStateError("Total labor minutes cannot be negative.")
    if total_minutes == 0:
        return 0
    return (
        (total_minutes + LABOR_INCREMENT_MINUTES - 1) // LABOR_INCREMENT_MINUTES
    ) * LABOR_INCREMENT_MINUTES


def labor_charge(total_minutes: int) -> Decimal:
    """Charge combined labor at $62.50/hour after increment rounding."""
    billed = billed_labor_minutes(total_minutes)
    return LABOR_RATE * Decimal(billed) / Decimal(60)


def effective_billable(quantity: Decimal, billable_quantity: Optional[Decimal]) -> Decimal:
    """Units actually charged on a material line: the billing override when one is
    set, otherwise the full recorded quantity. Shared by the card/detail
    responses and the CSV export so a work order's materials total is the same
    number wherever it is read."""
    return quantity if billable_quantity is None else billable_quantity


# --- validators ----------------------------------------------------------

def validate_status(status: str) -> None:
    """Raise `WorkOrderStateError` unless `status` is a live workflow state."""
    if status not in ALL_STATUSES:
        raise WorkOrderStateError(
            "Status must be created, assigned, in_progress, on_hold, completed, or review."
        )


# Back-compat alias: the only stored/settable statuses are the active ones.
validate_active_status = validate_status


def initial_status(assigned_to_id: object) -> str:
    """Status for a new work order: Assigned only when it has technicians.

    The argument accepts the legacy singular UUID or a plural collection; both
    have the same truthiness contract.
    """
    return STATUS_ASSIGNED if assigned_to_id else STATUS_CREATED


def reconcile_assignment_status(current_status: str, assigned_to_id: object) -> str:
    """Keep Created/Assigned aligned with technician assignment.

    Once work has advanced to In-Progress, On-Hold, or later, changing the technician
    must not silently move the lifecycle backward.
    """
    validate_status(current_status)
    if current_status in (STATUS_CREATED, STATUS_ASSIGNED):
        return initial_status(assigned_to_id)
    return current_status


def status_after_activity(current_status: str) -> str:
    """Advance a pre-work row when its first material or labor activity lands.

    On-Hold is intentionally stable: activity may still be recorded, but only a
    supervisor's explicit status edit resumes the lifecycle.
    """
    validate_status(current_status)
    if current_status in (STATUS_CREATED, STATUS_ASSIGNED):
        return STATUS_IN_PROGRESS
    return current_status


def completion_target_status(role: Optional[str]) -> str:
    """Where an assigned worker's walkthrough completion actually lands.

    A Technician finishes the work but does not get to declare it billable:
    their completion parks the row On-Hold for a supervisor to review.
    Supervisor and above -- and the `None`-role internal caller -- reach
    Completed directly.

    Keyed on role rather than on assignment, deliberately. A Supervisor may
    also be an assigned worker (`roles.WORK_ORDER_TECHNICIAN_ROLES`), and the
    UI routes every assignee through the same button, so an assignment-based
    rule would quietly take completion away from supervisors too.

    An unrecognised role ranks below Technician (`roles.rank` returns -1) and
    therefore lands On-Hold. A corrupt role value must never reach a billing
    state.
    """
    if role is None or roles.role_at_least(role, roles.ROLE_SUPERVISOR):
        return STATUS_COMPLETED
    return STATUS_ON_HOLD


def validate_mode(mode: str) -> None:
    """Raise `WorkOrderStateError` unless `mode` is `dispense` or
    `retroactive`."""
    if mode not in ALL_MODES:
        raise WorkOrderStateError("Mode must be dispense or retroactive.")


def affects_stock(mode: str) -> bool:
    """Whether logging a material in `mode` should move on-hand stock. Only
    `dispense` does; `retroactive` is a stock-neutral backfill."""
    return mode == MODE_DISPENSE


# --- attribute reconciliation (fill-blanks) ------------------------------

def is_blank(value) -> bool:
    """True for None or an all-whitespace string."""
    return value is None or (isinstance(value, str) and value.strip() == "")


def fill_blank(current, incoming):
    """Fill-blanks merge for a single attribute: keep a non-blank `current`,
    otherwise take `incoming`. Used by find-or-create so a later reference can
    populate empty attributes but never overwrites a value already set."""
    return current if not is_blank(current) else incoming


# --- CSV import ----------------------------------------------------------

# The mass work-order export's column headers, in order. `WORK ORDER` is the
# identity; `SYMPTOM/TASK` is the description; the rest map to new columns.
IMPORT_HEADERS: tuple[str, ...] = (
    "WORK ORDER",
    "LOCATION",
    "OUTPUT TO",
    "ASSIGNED TO",
    "SERVICE TYPE",
    "SCHEDULE DATE",
    "SYMPTOM/TASK",
)

# A missing imported task remains useful: the Work Orders page can send the user
# to the vendor's source record. Treat the number as one URL path segment, so a
# slash/hash/space cannot change the destination. A real task imported later may
# replace this deterministic fallback value.
NETFACILITIES_WORK_ORDER_URL = (
    "https://system.netfacilities.com/tools/viewworkorders"
)


def work_order_task_fallback(number: str) -> str:
    """Canonical NetFacilities task URL for one nonblank work-order number."""
    trimmed = number.strip()
    if not trimmed:
        raise WorkOrderStateError("Work order number is required for the task link.")
    return f"{NETFACILITIES_WORK_ORDER_URL}/{quote(trimmed, safe='')}"


def is_work_order_task_fallback(value: Optional[str], number: str) -> bool:
    """Whether ``value`` is the exact generated task URL for ``number``."""
    if is_blank(value) or is_blank(number):
        return False
    return value == work_order_task_fallback(number)

# --- CSV export ----------------------------------------------------------

# One row per work order. The seven `IMPORT_HEADERS` come first, spelled
# exactly as the import expects them, so an exported file can be fed straight
# back into `POST /work-orders/import` -- `parse_import_row` reads those by name
# and ignores everything after them. The remaining columns are what the app
# knows that the vendor CSV does not (status, assignment, billing, timestamps).
EXPORT_HEADERS: tuple[str, ...] = IMPORT_HEADERS + (
    "STATUS",
    "TECHNICIANS",
    "SUPERVISOR",
    "COMMUNITY",
    "BUILDING",
    "UNIT",
    "ENTRY MODE",
    "MATERIAL LINES",
    "MATERIALS TOTAL",
    "LABOR MINUTES",
    "BILLED LABOR MINUTES",
    "LABOR TOTAL",
    "TOTAL",
    "NOTES",
    "CREATED AT",
    "UPDATED AT",
    "COMPLETED AT",
    "ARCHIVED AT",
)

# The client-facing export: what a customer is billed, and nothing else. One
# row per work order carrying the number, the two charge totals, and the full
# receipt text (`domain.receipt`) in a single cell. Both totals are the BILLED
# amounts -- materials marked up, labor at the labor rate -- so they sum to the
# receipt's own Total line rather than disagreeing with the document beside
# them.
CLIENT_EXPORT_HEADERS: tuple[str, ...] = (
    "WORK ORDER",
    "MATERIAL TOTAL",
    "LABOR TOTAL",
    "RECEIPT",
)

EXPORT_VARIANT_FULL = "full"
EXPORT_VARIANT_CLIENT = "client"

ALL_EXPORT_VARIANTS: tuple[str, ...] = (EXPORT_VARIANT_FULL, EXPORT_VARIANT_CLIENT)


def validate_export_variant(variant: str) -> None:
    """Raise `WorkOrderStateError` unless `variant` is `full` (every column,
    re-importable) or `client` (number + charges + receipt)."""
    if variant not in ALL_EXPORT_VARIANTS:
        raise WorkOrderStateError("Export variant must be full or client.")


# Export scopes that are not one of `ALL_STATUSES`: every live work order, and
# the closed (archived) ones the live list deliberately hides.
EXPORT_SCOPE_ALL = "all"
EXPORT_SCOPE_ARCHIVED = "archived"


def validate_export_scope(scope: str) -> None:
    """Raise `WorkOrderStateError` unless `scope` is `all`, `archived`, or one
    live status. Keeps a typo'd query string from silently exporting
    everything."""
    if scope not in ALL_STATUSES + (EXPORT_SCOPE_ALL, EXPORT_SCOPE_ARCHIVED):
        raise WorkOrderStateError(
            "Export filter must be all, archived, or a live status."
        )


_VENDOR_TAG_RE = re.compile(r"\s*\([^)]*\)\s*$")


def normalize_assignee_name(raw: Optional[str]) -> Optional[str]:
    """Canonical comparison form of a CSV `ASSIGNED TO` name for matching it to a
    system user: drop a trailing parenthetical vendor tag, collapse internal
    whitespace, trim, lowercase. `"Hayden Hurst (Belfor)"` -> `"hayden hurst"`.
    Returns `None` for a blank/absent name (nothing to match)."""
    if is_blank(raw):
        return None
    without_tag = _VENDOR_TAG_RE.sub("", raw)
    collapsed = " ".join(without_tag.split())
    return collapsed.lower() or None


def parse_import_row(row: dict) -> dict:
    """Map one CSV export row (a `csv.DictReader` dict) to work-order attributes.

    Trims every value, turning blanks into `None`. Returns `number` plus the
    attribute kwargs `get_or_create_work_order` accepts. A row whose `number` is
    blank is a no-op the caller should skip (its `number` comes back `None`)."""
    def cell(header: str) -> Optional[str]:
        value = row.get(header)
        return value.strip() if isinstance(value, str) and value.strip() else None

    return {
        "number": cell("WORK ORDER"),
        "location": cell("LOCATION"),
        "output_to": cell("OUTPUT TO"),
        "vendor_assignee": cell("ASSIGNED TO"),
        "service_type": cell("SERVICE TYPE"),
        "schedule_date": cell("SCHEDULE DATE"),
        "description": cell("SYMPTOM/TASK"),
    }


# --- visibility scope ----------------------------------------------------

def can_view_work_order(
    role: str,
    *,
    created_by_id: Optional[UUID],
    assigned_to_id: Optional[UUID],
    user_id: Optional[UUID],
    supervisor_id: Optional[UUID] = None,
    assigned_to_ids: Optional[Sequence[UUID]] = None,
) -> bool:
    """Whether a user of `role` may see/act on a work order.

    TechFM OA and above (and a `None`-role internal caller) see all. A Supervisor sees
    unrouted work orders available to pick up, work orders routed to them, and
    work orders where they are assigned to perform technician work. A Technician
    sees only work orders assigned to them.
    """
    if role is None or roles.role_at_least(role, roles.ROLE_TECHFM_OA):
        return True
    technician_ids = tuple(assigned_to_ids or ())
    if assigned_to_id is not None and assigned_to_id not in technician_ids:
        technician_ids += (assigned_to_id,)
    if role == roles.ROLE_SUPERVISOR:
        return user_id is not None and (
            supervisor_id is None
            or supervisor_id == user_id
            or user_id in technician_ids
        )
    return user_id is not None and user_id in technician_ids
