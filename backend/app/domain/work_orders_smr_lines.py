"""Pure rules for SMR27 paper-correction lines (spec
docs/superpowers/specs/2026-11-04-smr-paper-import-design.md).

The vocabulary the CSVs and the editor share (vendors, kinds, grounds,
reason codes, date bases), what a line is worth, when a line may be
`charged`, the Mon-Sun week numbering from 05/25/2026, the per-reading
arithmetic tie the import re-checks, and the two CSV row parsers. No
FastAPI, no SQLAlchemy: lines arrive as plain dicts (the CSVs) or as
objects with the column names as attributes (ORM rows, test stand-ins)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Iterable, Optional

from app.domain import work_orders as wo
from app.domain.errors import WorkOrderStateError

STATUS_CHARGED = "charged"
STATUS_EXCLUDED = "excluded"
STATUSES: tuple[str, ...] = (STATUS_CHARGED, STATUS_EXCLUDED)

# `Admin` lines are admin names read on paper, always excluded (ground
# `admin, never charged`); `Unknown` is a vendor nobody could place.
VENDORS: tuple[str, ...] = (
    "Belfor", "Green Choice", "XXL Construction", "BT Restoration", "Unknown", "Admin",
)
KINDS: tuple[str, ...] = ("field", "assessment", "audit", "staging", "material preparation", "clean-up")

DATE_BASIS_PAPER = "paper"
# Decision 13, generalised by the user on 2026-11-06: the two bases allowed
# to charge with a blank day. A Week 1 placement carries `week = 1` (crew
# sheets); a week placement carries the week the weekly reports put the
# hours in, read from the CSV. The block prints "week of <that Monday>".
WEEK1_PLACEMENT_BASIS = "Week 1 placement (crew sheets, Supplement)"
WEEK_PLACEMENT_BASIS = "week placement (weekly reports)"
PLACEMENT_BASES: tuple[str, ...] = (WEEK1_PLACEMENT_BASIS, WEEK_PLACEMENT_BASIS)
DATE_BASES: tuple[str, ...] = (
    DATE_BASIS_PAPER,
    "paper (date in note)",
    "closed date (Young Hall rule)",
    *PLACEMENT_BASES,
)

GROUND_UNDATED = "undated"
GROUND_REMOVED = "removed"
# Hours the paper shows and the review counted, which the Week Reports then
# dropped (audit/staging on accurately billed orders, printings dated into a
# week no report carries): kept as lines, excluded, inside the tie (2026-11-06).
GROUND_NOT_CHARGED_REPORTS = "read, not charged (weekly reports)"
# User 2026-11-09: an order carries at most 0.5 h each of assessment, audit
# and staging, whatever the paper shows; the extra stays as a line, excluded.
GROUND_OVERHEAD_ONCE = "overhead counted once"
# The draft CSV's spellings. If the final files use the design's snake_case
# names this tuple changes, nothing else does.
GROUNDS: tuple[str, ...] = (
    GROUND_UNDATED,
    "before Week 1",
    "after 07/12 (no invoices)",
    "awaiting invoice (GC, Week 7)",
    "reprint (no hours added)",
    "note only",
    "paper not found",
    "read, not charged (user)",
    GROUND_NOT_CHARGED_REPORTS,
    "admin, never charged",
    "vendor unknown",
    GROUND_REMOVED,
    GROUND_OVERHEAD_ONCE,
)
# Excluded lines whose hours the paper's own figure still counted: the
# review read them and did not charge them. Every other ground was never in
# `hours_as_read`.
TIE_COUNTED_GROUNDS: tuple[str, ...] = (
    GROUND_UNDATED, "before Week 1", "after 07/12 (no invoices)", GROUND_NOT_CHARGED_REPORTS, GROUND_OVERHEAD_ONCE,
)

# `as_read`: the line records what the paper says, no finding behind it. The
# import fills it where paper_lines.csv left the code blank (user 2026-11-06).
REASON_AS_READ = "as_read"
REASON_CODES: tuple[str, ...] = (
    REASON_AS_READ, "crew_as_one", "crew_as_individuals", "arithmetic", "overhead_added", "overhead_twice",
    "accurate", "over_billed", "not_on_paper", "unit_mismatch", "date_found",
    "manual_check", "awaiting_invoice", "belfor_only", "time_gap", "held_out",
    "hours_on_paper_above_billed", "crew_size_not_given", "cleanup_spread",
)

WEEK1_START = date(2026, 5, 25)
LAST_WEEK = 7
TIE_TOLERANCE = Decimal("0.5")
HALF_HOUR = Decimal("0.5")
CENT = Decimal("0.01")  # 0.5 h steps at 62.50 are exact cents; this only drops the trailing zero


# --- weeks --------------------------------------------------------------

def week_of(day: date) -> int:
    """Mon-Sun week number counted from 05/25/2026 as week 1. Zero or less is
    before Week 1; eight or more is after Week 7."""
    return (day - WEEK1_START).days // 7 + 1


def week_label(week: Optional[int]) -> str:
    if week is None:
        return ""
    if week < 1:
        return "Before W1"
    if week > LAST_WEEK:
        return "After W7"
    return f"Week {week}"


def week_for(work_date: Optional[date], date_basis: str, week: Optional[int] = None) -> Optional[int]:
    """The `week` a line stores: from its date; 1 for a Week 1 placement;
    the given week for a week placement; otherwise none."""
    if work_date is not None:
        return week_of(work_date)
    if date_basis == WEEK1_PLACEMENT_BASIS:
        return 1
    return week if date_basis == WEEK_PLACEMENT_BASIS else None


# --- paper stage (spec 2026-11-06) -----------------------------------------

STAGE_READY, STAGE_DATED, STAGE_UNDATED, STAGE_NOT_REVIEWED = "ready", "dated", "undated", "not_reviewed"
STAGES: tuple[str, ...] = (STAGE_NOT_REVIEWED, STAGE_UNDATED, STAGE_DATED, STAGE_READY)


def stage_for(readings, lines, ready_at) -> str:
    """Where the order's paper stands; `lines` already without removed ones.
    A Ready stamp only shows while a line still carries a week."""
    if any(line.week is not None for line in lines):
        return STAGE_READY if ready_at is not None else STAGE_DATED
    return STAGE_UNDATED if readings else STAGE_NOT_REVIEWED


def belfor_only(lines) -> bool:
    """At least one line and every one is Belfor's."""
    lines = list(lines)
    return bool(lines) and all(line.vendor == "Belfor" for line in lines)


# --- worth ---------------------------------------------------------------

def line_hours(line) -> Decimal:
    return Decimal(line.headcount) * Decimal(line.hours_each)


@dataclass(frozen=True)
class LinesCharge:
    charged_hours: Decimal
    excluded_hours: Decimal
    labor_total: Decimal
    count: int


def lines_charge(lines) -> LinesCharge:
    """Charged lines at the labor rate, no pooled rounding: the lines are
    already in 0.5 h steps (D9). Excluded hours ride along for the tiles."""
    charged = excluded = Decimal(0)
    count = 0
    for line in lines:
        count += 1
        if line.status == STATUS_CHARGED:
            charged += line_hours(line)
        else:
            excluded += line_hours(line)
    return LinesCharge(
        charged_hours=charged,
        excluded_hours=excluded,
        labor_total=(charged * wo.LABOR_RATE).quantize(CENT),
        count=count,
    )


# --- status rules --------------------------------------------------------

def is_half_hours(value: Decimal) -> bool:
    return (Decimal(value) * 2) % 1 == 0


def validate_line_state(
    *, status: str, work_date: Optional[date], date_basis: str, exclusion_ground: Optional[str],
    headcount: int, hours_each: Decimal, vendor: str, kind: str, reason_code: str,
    week: Optional[int] = None,
) -> None:
    """The DB checks, as words, before the row is flushed. `week` is the
    week a week placement names; every other basis derives its own."""
    if status not in STATUSES:
        raise WorkOrderStateError(f"Line status must be one of: {', '.join(STATUSES)}.")
    if date_basis not in DATE_BASES:
        raise WorkOrderStateError(f"Unknown date basis: {date_basis}.")
    if date_basis == WEEK_PLACEMENT_BASIS and work_date is None and week not in range(1, LAST_WEEK + 1):
        raise WorkOrderStateError(f"A week placement needs its week (1 to {LAST_WEEK}).")
    if status == STATUS_CHARGED and work_date is None and date_basis not in PLACEMENT_BASES:
        raise WorkOrderStateError("A charged line needs a work date (or a placement basis).")
    if exclusion_ground is not None and exclusion_ground not in GROUNDS:
        raise WorkOrderStateError(f"Unknown exclusion ground: {exclusion_ground}.")
    if status == STATUS_CHARGED and exclusion_ground is not None:
        raise WorkOrderStateError("A charged line carries no exclusion ground.")
    if headcount < 1:
        raise WorkOrderStateError("Headcount must be at least 1.")
    if not is_half_hours(hours_each):
        raise WorkOrderStateError("Hours must be in 0.5 h steps.")
    if vendor not in VENDORS:
        raise WorkOrderStateError(f"Unknown vendor: {vendor}.")
    for token in kinds_of(kind):
        if token not in KINDS:
            raise WorkOrderStateError(f"Unknown kind: {token}.")
    if reason_code not in REASON_CODES:
        raise WorkOrderStateError(f"Unknown reason code: {reason_code}.")


def kinds_of(kind: str) -> list[str]:
    """`assessment, audit` -> ['assessment', 'audit']; stored as given (user)."""
    return [token.strip() for token in (kind or "").split(",") if token.strip()]


def apply_date(status: str, exclusion_ground: Optional[str], work_date: Optional[date]) -> tuple[str, Optional[str]]:
    """Dating an `undated` line charges it at once, no second approval (D10).
    Any other line keeps its status."""
    if status == STATUS_EXCLUDED and exclusion_ground == GROUND_UNDATED and work_date is not None:
        return STATUS_CHARGED, None
    return status, exclusion_ground


# --- the tie check -------------------------------------------------------

@dataclass(frozen=True)
class TieFailure:
    reading_id: str
    wo: str
    printing_no: int
    expected: Decimal
    found: Decimal

    def __str__(self) -> str:
        return (
            f"Reading {self.reading_id} (WO {self.wo}, printing {self.printing_no}): "
            f"lines total {self.found} h, paper read {self.expected} h."
        )


def _counts_toward(reading: dict, line: dict) -> bool:
    if line["status"] != STATUS_CHARGED and line.get("exclusion_ground") not in TIE_COUNTED_GROUNDS:
        return False
    reading_date, line_date = reading.get("work_date"), line.get("work_date")
    if reading_date is not None and line_date is not None and week_of(line_date) != week_of(reading_date):
        return False  # the note dated the line itself, into another week
    return True


def tie_hours(reading: dict, lines: Iterable[dict]) -> Decimal:
    return sum(
        (Decimal(line["headcount"]) * Decimal(line["hours_each"]) for line in lines if _counts_toward(reading, line)),
        Decimal(0),
    )


def check_tie(reading: dict, lines: Iterable[dict]) -> Optional[TieFailure]:
    """None when the reading's lines tie to `hours_as_read` within 0.5 h, or
    when the reading carries no hours. Otherwise the failure, named."""
    expected = reading.get("hours_as_read")
    if expected is None:
        return None
    found = tie_hours(reading, lines)
    if abs(found - Decimal(expected)) <= TIE_TOLERANCE:
        return None
    return TieFailure(
        reading_id=str(reading["reading_id"]), wo=str(reading["wo"]),
        printing_no=int(reading["printing_no"]), expected=Decimal(expected), found=found,
    )


# --- CSV rows ------------------------------------------------------------

READING_REQUIRED_HEADERS: tuple[str, ...] = (
    "reading_id", "wo", "printing_no", "work_date", "hours_as_read", "raw_note",
)
LINE_REQUIRED_HEADERS: tuple[str, ...] = (
    "line_id", "reading_id", "wo", "work_date", "vendor", "worker", "headcount", "hours_each",
    "kind", "reason_code", "status", "exclusion_ground",
)
_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y")


def _text(row: dict, key: str) -> Optional[str]:
    value = row.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def parse_date(text: Optional[str], *, where: str) -> Optional[date]:
    if text is None:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise WorkOrderStateError(f"{where}: work_date {text!r} is not a date.")


def _decimal(text: Optional[str], *, where: str, column: str) -> Optional[Decimal]:
    if text is None:
        return None
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise WorkOrderStateError(f"{where}: {column} {text!r} is not a number.") from exc


def parse_reading_row(row: dict) -> dict:
    """One `paper_readings.csv` row. `csv_row` (the source row in
    paper_review.csv) and `reviewer` are optional; unknown columns ride along
    unread."""
    reading_id = _text(row, "reading_id")
    if reading_id is None:
        raise WorkOrderStateError("A reading row has no reading_id.")
    where = f"Reading {reading_id}"
    wo_number, printing = _text(row, "wo"), _text(row, "printing_no")
    if wo_number is None or printing is None or not printing.isdigit():
        raise WorkOrderStateError(f"{where}: wo and printing_no are required.")
    return {
        "reading_id": reading_id,
        "wo": wo_number,
        "printing_no": int(printing),
        "work_date": parse_date(_text(row, "work_date"), where=where),
        "hours_as_read": _decimal(_text(row, "hours_as_read"), where=where, column="hours_as_read"),
        "raw_note": (row.get("raw_note") or "").strip(),
        "reviewer": _text(row, "reviewer"),
        "csv_row": _text(row, "csv_row"),
    }


def parse_line_row(row: dict) -> dict:
    """One `paper_lines.csv` row, validated against the vocabulary above.
    `date_basis` defaults to `paper`, `reason_code` to `as_read`; `week` is
    read for a week placement only, otherwise derived (a date always wins)."""
    line_id = _text(row, "line_id")
    if line_id is None:
        raise WorkOrderStateError("A line row has no line_id.")
    where = f"Line {line_id}"
    reading_id, wo_number = _text(row, "reading_id"), _text(row, "wo")
    if reading_id is None or wo_number is None:
        raise WorkOrderStateError(f"{where}: reading_id and wo are required.")
    headcount_text = _text(row, "headcount") or "1"
    if not headcount_text.isdigit():
        raise WorkOrderStateError(f"{where}: headcount {headcount_text!r} is not a whole number.")
    hours_each = _decimal(_text(row, "hours_each"), where=where, column="hours_each")
    if hours_each is None:
        raise WorkOrderStateError(f"{where}: hours_each is required.")
    date_basis = _text(row, "date_basis") or DATE_BASIS_PAPER
    week = None
    if date_basis == WEEK_PLACEMENT_BASIS:  # the one basis that reads the column
        week_text = _text(row, "week")
        if week_text is not None and not week_text.isdigit():
            raise WorkOrderStateError(f"{where}: week {week_text!r} is not a whole number.")
        week = int(week_text) if week_text is not None else None
    parsed = {
        "line_id": line_id,
        "reading_id": reading_id,
        "wo": wo_number,
        "work_date": parse_date(_text(row, "work_date"), where=where),
        "date_basis": date_basis,
        "vendor": _text(row, "vendor") or "",
        "worker": _text(row, "worker"),
        "alias_on_paper": _text(row, "alias_on_paper"),
        "headcount": int(headcount_text),
        "hours_each": hours_each,
        "kind": ", ".join(kinds_of(row.get("kind") or "")) or "field",
        "reason_code": _text(row, "reason_code") or REASON_AS_READ,
        "status": (_text(row, "status") or "").casefold(),
        "exclusion_ground": _text(row, "exclusion_ground"),
        "note": _text(row, "note"),
    }
    # User 2026-11-06: paper hours bill where read. A row the review held
    # out because its week's report never carried the order lands charged;
    # the ground is retired, and the load needs no second pass.
    if parsed["exclusion_ground"] == GROUND_NOT_CHARGED_REPORTS:
        parsed["status"], parsed["exclusion_ground"] = STATUS_CHARGED, None
    try:
        validate_line_state(
            status=parsed["status"], work_date=parsed["work_date"], date_basis=parsed["date_basis"],
            exclusion_ground=parsed["exclusion_ground"], headcount=parsed["headcount"],
            hours_each=parsed["hours_each"], vendor=parsed["vendor"], kind=parsed["kind"],
            reason_code=parsed["reason_code"], week=week,
        )
    except WorkOrderStateError as exc:
        raise WorkOrderStateError(f"{where}: {exc}") from exc
    parsed["week"] = week_for(parsed["work_date"], parsed["date_basis"], week)
    return parsed
