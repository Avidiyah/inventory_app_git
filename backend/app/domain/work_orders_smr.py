"""Pure SMR27 audit rules (spec docs/superpowers/specs/2026-10-23-smr-audit-workflow-design.md).

Three things live here and nowhere else: how the vendor sheet maps onto a
work order, how a work order is frozen into a JSON snapshot (the baseline,
the edited check and the audit export all read this one serializer so the
BEFORE and AFTER phases are column-identical), and how labor splits into
real-technician minutes and anonymous Skilled Technician minutes that round
apart from each other.

The target rule (spec 2026-10-23-smr-target-match) lives at the bottom: the
client's Breakdown sheet row becomes a per-order target, and `target_gap`
says how far the live order still is from it, undershoot only."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Optional

from app.domain import receipt
from app.domain import work_orders as wo
from app.domain.errors import WorkOrderStateError

SMR_SERVICE_TYPE = "SMR27 - Belfor"
SKILLED_TECHNICIAN_LABEL = "Skilled Technician"
SMR_CLOSED_STATUS = "closed"

# The sheet's own headers. `WORK ORDER` is identity, `FILED STATUS` decides
# whether a row is imported at all; the rest fill the same columns the mass
# import fills. Every other column (CREATOR, COMPLETION DATE, the two
# annotation columns) rides along verbatim in the snapshot's `source_row`.
SMR_REQUIRED_HEADERS: tuple[str, ...] = (
    "WORK ORDER",
    "FILED STATUS",
    "LOCATION",
    "ASSIGNED TO",
    "SERVICE TYPE",
    "SCHEDULE DATE",
)

# The snapshot keys that describe billable state. Status, archive time and
# notes change when an order is finished or worked, not when it is re-charged,
# so they are frozen for the record but never make an order "edited".
_COMPARABLE_KEYS = ("totals", "material_lines", "labor_entries", "labor_sessions")

# The vendor sheet's own column order. JSONB does not keep key order, so the
# export re-sorts `source_row` keys by this list, unknown columns after.
SMR_SHEET_COLUMNS: tuple[str, ...] = (
    "WORK ORDER", "CREATOR", "SERVICE TYPE", "SCHEDULE DATE", "COMPLETION DATE",
    "ASSIGNED TO", "FILED STATUS", "LOCATION",
)


def _cell(row: dict, header: str) -> Optional[str]:
    value = row.get(header)
    return value.strip() if isinstance(value, str) and value.strip() else None


def parse_smr_row(row: dict) -> dict:
    """Map one sheet row (a `csv.DictReader` dict) to import inputs.

    `number` is `None` for a blank work-order cell (skip the row). `closed` is
    whether FILED STATUS is `Closed`; anything else (Canceled) is skipped.
    `attrs` are the `get_or_create_work_order` kwargs; `source_row` is every
    cell as read, trimmed, so the export can hand analytics the raw sheet."""
    status = (_cell(row, "FILED STATUS") or "").casefold()
    return {
        "number": _cell(row, "WORK ORDER"),
        "closed": status == SMR_CLOSED_STATUS,
        "attrs": {
            "location": _cell(row, "LOCATION"),
            "vendor_assignee": _cell(row, "ASSIGNED TO"),
            "service_type": _cell(row, "SERVICE TYPE"),
            "schedule_date": _cell(row, "SCHEDULE DATE"),
        },
        "source_row": {
            key: (value.strip() if isinstance(value, str) else value)
            for key, value in row.items()
            if key is not None
        },
    }


@dataclass(frozen=True)
class LaborSplit:
    real_minutes: int
    skilled_minutes: int
    real_billed: int
    skilled_billed: int
    labor_total: Decimal


def is_skilled(entry) -> bool:
    """A labor entry with no technician is an anonymous Skilled Technician line."""
    return entry.technician_id is None


def labor_split(entries) -> LaborSplit:
    """Real and skilled minutes, each rounded to the 30-minute increment on its
    own, charged at the one labor rate. Pooled rounding would under-bill the
    skilled hours the vendor sheet lists separately."""
    real = sum(e.minutes for e in entries if not is_skilled(e))
    skilled = sum(e.minutes for e in entries if is_skilled(e))
    return LaborSplit(
        real_minutes=real,
        skilled_minutes=skilled,
        real_billed=wo.billed_labor_minutes(real),
        skilled_billed=wo.billed_labor_minutes(skilled),
        labor_total=wo.labor_charge(real) + wo.labor_charge(skilled),
    )


def _money(value: Decimal) -> str:
    return f"{value:.2f}"


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _name(user) -> Optional[str]:
    return getattr(user, "full_name", None) if user is not None else None


def line_total(line) -> Decimal:
    price = line.item.price or Decimal(0)
    return price * wo.effective_billable(line.quantity, line.billable_quantity)


def snapshot(work_order, *, taken_at: datetime, source_row: Optional[dict]) -> dict:
    """Freeze a work order's billable state as plain JSON (Decimals as strings,
    datetimes ISO, UUIDs as str). Written once as `smr_baseline`; recomputed
    live for the AFTER phase."""
    lines = [
        {
            "id": str(line.id),
            "item_id": str(line.item_id),
            "item_name": line.item.name,
            "barcode": line.item.barcode,
            "quantity": str(line.quantity),
            "billable_quantity": (
                str(line.billable_quantity) if line.billable_quantity is not None else None
            ),
            "unit_price": _money(line.item.price or Decimal(0)),
            "line_total": _money(line_total(line)),
            "created_at": _iso(line.created_at),
        }
        for line in work_order.items
    ]
    split = labor_split(work_order.labor_entries)
    materials_total = sum((line_total(line) for line in work_order.items), Decimal(0))
    return {
        "taken_at": _iso(taken_at),
        "source_row": source_row,
        "status": work_order.status,
        "archived_at": _iso(work_order.archived_at),
        "notes": work_order.notes,
        "totals": {
            "materials_total": _money(materials_total),
            "real_minutes": split.real_minutes,
            "skilled_minutes": split.skilled_minutes,
            "real_billed_minutes": split.real_billed,
            "skilled_billed_minutes": split.skilled_billed,
            "labor_total": _money(split.labor_total),
            "total": _money(materials_total + split.labor_total),
        },
        "material_lines": lines,
        "labor_entries": [
            {
                "id": str(entry.id),
                "technician": (
                    SKILLED_TECHNICIAN_LABEL if is_skilled(entry) else _name(entry.technician)
                ),
                "minutes": entry.minutes,
                "recorded_by": _name(entry.recorded_by),
                "created_at": _iso(entry.created_at),
            }
            for entry in work_order.labor_entries
        ],
        "labor_sessions": [
            {
                "id": str(session.id),
                "technician": _name(session.technician),
                "started_at": _iso(session.started_at),
                "ended_at": _iso(session.ended_at),
                "minutes": session.labor.minutes if session.labor is not None else None,
                "auto_closed": session.auto_closed_at is not None,
                "reviewed_at": _iso(session.reviewed_at),
            }
            for session in work_order.labor_sessions
        ],
    }


def _comparable(snap: dict) -> dict:
    return {key: snap.get(key) for key in _COMPARABLE_KEYS}


def sheet_column_order(columns) -> list[str]:
    """Known sheet columns in sheet order, then any others alphabetically."""
    known = [c for c in SMR_SHEET_COLUMNS if c in columns]
    return known + sorted(c for c in columns if c not in SMR_SHEET_COLUMNS)


def is_edited(work_order) -> bool:
    """Whether anything billable changed since the baseline. No baseline means
    nothing to compare against, so False."""
    baseline = work_order.smr_baseline
    if not baseline:
        return False
    current = snapshot(work_order, taken_at=datetime.min, source_row=None)
    return _comparable(current) != _comparable(baseline)


_DELTA_MONEY = ("materials_total", "labor_total", "total")
_DELTA_INT = ("real_minutes", "skilled_minutes")


def deltas(baseline: dict, current: dict) -> dict:
    """Current minus baseline for every number analytics will sum."""
    before, after = baseline["totals"], current["totals"]
    out: dict = {
        key: Decimal(after[key]) - Decimal(before[key]) for key in _DELTA_MONEY
    }
    out.update({key: after[key] - before[key] for key in _DELTA_INT})
    out["material_lines"] = len(current["material_lines"]) - len(baseline["material_lines"])
    return out


# --- target match (spec 2026-10-23-smr-target-match) ----------------------

# The Breakdown sheet's headers the import reads by name; the rest ride along
# in the target's `source_row`.
TARGET_REQUIRED_HEADERS: tuple[str, ...] = ("WO#", "Hours", "Total Material Cost")

# The sheet's own column order, for the export (the blank trailing header is
# dropped on read).
TARGET_SHEET_COLUMNS: tuple[str, ...] = (
    "WO#", "Unit#", "Closed Date", "Labor Type", "BELFOR HRS", "Add HRS", "Duplicate HRS",
    "Hours", "Labor $", "OT Hours", "OT $", "Total Material Cost", "Total L&M",
)

# Matched = within the band below the target, or anywhere above it. The client
# knows they were under-charged, so overshoot is never a failure (user, D3).
TARGET_HOURS_BAND = Decimal("0.5")
TARGET_MATERIAL_BAND = Decimal("10")

_CENT = Decimal("0.01")


def parse_money(text: Optional[str], *, number: str, column: str) -> Decimal:
    """`$1,656.25` -> Decimal; blank -> 0; anything else names the row and column."""
    cleaned = (text or "").replace("$", "").replace(",", "").strip()
    if not cleaned:
        return Decimal(0)
    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise WorkOrderStateError(f"Row {number}: {column} is not a number.") from exc


def parse_target_row(row: dict) -> Optional[dict]:
    """Map one Breakdown row to a target. `None` for a blank WO# (the footer)."""
    number = _cell(row, "WO#")
    if number is None:
        return None

    def money(column: str) -> Decimal:
        return parse_money(row.get(column), number=number, column=column)

    return {
        "number": number,
        "hours": money("Hours"),
        "labor_total": money("Labor $"),
        "materials_total": money("Total Material Cost"),
        "total": money("Total L&M"),
        "source_row": {
            key: (value.strip() if isinstance(value, str) else value)
            for key, value in row.items()
            if key
        },
    }


def target_record(parsed: dict, *, imported_at: datetime) -> dict:
    """The JSONB value: Decimals as strings, the stamp ISO, the raw row kept."""
    return {
        "imported_at": _iso(imported_at),
        "hours": str(parsed["hours"]),
        "labor_total": _money(parsed["labor_total"]),
        "materials_total": _money(parsed["materials_total"]),
        "total": _money(parsed["total"]),
        "source_row": parsed["source_row"],
    }


def target_gap(target: Optional[dict], *, billed_minutes: int, materials_total: Decimal) -> Optional[dict]:
    """How far the live order is from the client's target. Hours are what the
    client is billed (real + skilled, each already rounded); material is the
    receipt figure, base total with the mark-up. `None` without a target."""
    if not target:
        return None
    hours = Decimal(target["hours"])
    material = Decimal(target["materials_total"])
    current_hours = Decimal(billed_minutes) / Decimal(60)
    current_material = (materials_total * receipt.MARKUP_RATE).quantize(_CENT, rounding=ROUND_HALF_UP)
    gap_hours = current_hours - hours
    gap_material = current_material - material
    remaining_hours = max(Decimal(0), -gap_hours)
    remaining_material = max(Decimal(0), -gap_material)
    return {
        "hours": hours,
        "labor_total": Decimal(target["labor_total"]),
        "materials_total": material,
        "total": Decimal(target["total"]),
        "current_hours": current_hours,
        "current_materials_total": current_material,
        "gap_hours": gap_hours,
        "gap_materials_total": gap_material,
        "remaining_hours": remaining_hours,
        "remaining_materials_total": remaining_material,
        "matched": remaining_hours <= TARGET_HOURS_BAND and remaining_material <= TARGET_MATERIAL_BAND,
    }
