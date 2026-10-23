"""Pure SMR27 audit rules (spec docs/superpowers/specs/2026-10-23-smr-audit-workflow-design.md).

Three things live here and nowhere else: how the vendor sheet maps onto a
work order, how a work order is frozen into a JSON snapshot (the baseline,
the edited check and the audit export all read this one serializer so the
BEFORE and AFTER phases are column-identical), and how labor splits into
real-technician minutes and anonymous Skilled Technician minutes that round
apart from each other."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional

from app.domain import work_orders as wo

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

# Snapshot keys that do not describe the order's billable state.
_NON_COMPARABLE_KEYS = frozenset({"taken_at", "source_row"})


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
    return {key: value for key, value in snap.items() if key not in _NON_COMPARABLE_KEYS}


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
