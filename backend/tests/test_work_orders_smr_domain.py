"""Pure tests for `domain.work_orders_smr` (spec 2026-10-23): sheet parsing,
the snapshot serializer, the edited check, deltas and split labor rounding.
No database: work orders are stand-ins with the attributes the module reads."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace as NS

import pytest

from app.domain import work_orders as wo
from app.domain.errors import WorkOrderStateError
from app.domain import work_orders_smr as smr


HEADERS = [
    "WORK ORDER", "CREATOR", "SERVICE TYPE", "SCHEDULE DATE", "COMPLETION DATE",
    "ASSIGNED TO", "FILED STATUS", "LOCATION",
    "Reccomended time and material needing added to WO for correct billing. ",
    "Reason for added time and material.",
]


def _row(**overrides):
    row = dict(zip(HEADERS, [
        "23281563", "Uri Butler", "SMR27 - Belfor", "05/15/2026", "05/21/2026",
        "Chris Coburn", "Closed", "Young Hall:1st Floor,Young Hall 108A-A,drawer",
        ".5 can WD-40", "WD-40 for treating drawer",
    ]))
    row.update(overrides)
    return row


def test_parse_smr_row_maps_sheet_headers():
    parsed = smr.parse_smr_row(_row())
    assert parsed["number"] == "23281563"
    assert parsed["closed"] is True
    assert parsed["attrs"] == {
        "location": "Young Hall:1st Floor,Young Hall 108A-A,drawer",
        "vendor_assignee": "Chris Coburn",
        "service_type": "SMR27 - Belfor",
        "schedule_date": "05/15/2026",
    }
    assert parsed["source_row"][HEADERS[8]] == ".5 can WD-40"
    assert parsed["source_row"]["CREATOR"] == "Uri Butler"


def test_parse_smr_row_canceled_is_not_closed_and_blank_number_is_none():
    assert smr.parse_smr_row(_row(**{"FILED STATUS": "Canceled"}))["closed"] is False
    assert smr.parse_smr_row(_row(**{"WORK ORDER": "  "}))["number"] is None


def _entry(minutes, technician_id="real", name="Pat Tech"):
    tech = None if technician_id is None else NS(id=technician_id, full_name=name)
    return NS(id=uuid.uuid4(), technician_id=technician_id, technician=tech,
              minutes=minutes, recorded_by=None, created_at=None, session=None)


def test_labor_split_rounds_skilled_separately():
    split = smr.labor_split([_entry(20), _entry(10, None)])
    assert (split.real_minutes, split.skilled_minutes) == (20, 10)
    assert (split.real_billed, split.skilled_billed) == (30, 30)
    assert split.labor_total == wo.labor_charge(30) * 2
    assert split.labor_total != wo.labor_charge(30)  # pooled 30 min would bill half


def _order(lines=(), entries=(), sessions=()):
    return NS(
        id=uuid.uuid4(), number="23281563", status="completed", archived_at=None,
        notes="n", smr_baseline=None, items=list(lines), labor_entries=list(entries),
        labor_sessions=list(sessions),
    )


def _line(qty="2", price="1.50", billable=None, name="Rags"):
    return NS(id=uuid.uuid4(), item_id=uuid.uuid4(), quantity=Decimal(qty),
              billable_quantity=None if billable is None else Decimal(billable),
              item=NS(name=name, barcode="BC1", price=Decimal(price)), created_at=None)


def test_snapshot_is_json_serialisable_and_totals_lines():
    order = _order(lines=[_line(), _line("1", "4.00", "0.5")], entries=[_entry(45), _entry(10, None)])
    snap = smr.snapshot(order, taken_at=datetime(2026, 10, 23, tzinfo=timezone.utc), source_row={"CREATOR": "x"})
    json.dumps(snap)
    assert snap["totals"] == {
        "materials_total": "5.00", "real_minutes": 45, "skilled_minutes": 10,
        "real_billed_minutes": 60, "skilled_billed_minutes": 30,
        "labor_total": str(wo.labor_charge(60) + wo.labor_charge(30)),
        "total": str(Decimal("5.00") + wo.labor_charge(60) + wo.labor_charge(30)),
    }
    assert snap["labor_entries"][1]["technician"] == smr.SKILLED_TECHNICIAN_LABEL
    assert snap["material_lines"][0]["line_total"] == "3.00"
    assert snap["source_row"] == {"CREATOR": "x"}


def test_is_edited_false_when_unchanged_and_without_baseline():
    order = _order(lines=[_line()], entries=[_entry(30)])
    assert smr.is_edited(order) is False
    order.smr_baseline = smr.snapshot(order, taken_at=datetime.now(timezone.utc), source_row=None)
    assert smr.is_edited(order) is False


def test_is_edited_detects_removed_line():
    order = _order(lines=[_line(), _line("1", "4.00")])
    order.smr_baseline = smr.snapshot(order, taken_at=datetime.now(timezone.utc), source_row=None)
    order.items.pop()
    assert smr.is_edited(order) is True


def test_deltas_subtract_baseline():
    before = _order(lines=[_line()], entries=[_entry(30)])
    base = smr.snapshot(before, taken_at=datetime.now(timezone.utc), source_row=None)
    after = _order(lines=[], entries=[_entry(30), _entry(15, None)])
    cur = smr.snapshot(after, taken_at=datetime.now(timezone.utc), source_row=None)
    d = smr.deltas(base, cur)
    assert d["materials_total"] == Decimal("-3.00")
    assert d["real_minutes"] == 0 and d["skilled_minutes"] == 15
    assert d["labor_total"] == wo.labor_charge(15)
    assert d["material_lines"] == -1
    assert d["total"] == wo.labor_charge(15) - Decimal("3.00")


# --- target match (spec 2026-10-23-smr-target-match) ----------------------

BREAKDOWN = ["WO#", "Unit#", "Closed Date", "Labor Type", "BELFOR HRS", "Add HRS",
             "Duplicate HRS", "Hours", "Labor $", "OT Hours", "OT $", "Total Material Cost", "Total L&M", ""]


def _brow(**o):
    row = dict(zip(BREAKDOWN, ["23281585", "Young Hall 108", "05/21/26", "SL", "", "", "", "1", "$62.50", "", "$0.00", "$9.38", "$71.88", ""]))
    row.update(o)
    return row


def test_parse_target_row_reads_hours_and_money():
    p = smr.parse_target_row(_brow(**{"Labor $": "$1,656.25", "Hours": "26.5"}))
    assert (p["number"], p["hours"], p["labor_total"], p["materials_total"], p["total"]) == (
        "23281585", Decimal("26.5"), Decimal("1656.25"), Decimal("9.38"), Decimal("71.88"))
    assert p["source_row"]["Unit#"] == "Young Hall 108"


def test_parse_target_row_blank_number_is_none_and_blank_money_is_zero():
    assert smr.parse_target_row(_brow(**{"WO#": ""})) is None
    parsed = smr.parse_target_row(_brow(**{"Total Material Cost": "", "Hours": ""}))
    assert parsed["materials_total"] == Decimal(0) and parsed["hours"] == Decimal(0)


def test_parse_target_row_rejects_non_numeric():
    with pytest.raises(WorkOrderStateError, match="23281585: Hours"):
        smr.parse_target_row(_brow(Hours="abc"))


def test_target_record_is_json_safe():
    rec = smr.target_record(smr.parse_target_row(_brow()), imported_at=datetime(2026, 10, 23, tzinfo=timezone.utc))
    assert rec["hours"] == "1" and rec["materials_total"] == "9.38" and rec["imported_at"].startswith("2026-10-23")
    assert rec["source_row"]["Unit#"] == "Young Hall 108"
    json.dumps(rec)


def _target(hours="2", material="67.16"):
    return {"hours": hours, "labor_total": "0.00", "materials_total": material, "total": "0.00", "source_row": {}}


def test_target_gap_short_order():
    g = smr.target_gap(_target(), billed_minutes=60, materials_total=Decimal("40.00"))
    assert g["current_hours"] == Decimal(1) and g["current_materials_total"] == Decimal("46.00")
    assert g["remaining_hours"] == Decimal(1) and g["remaining_materials_total"] == Decimal("21.16")
    assert g["gap_hours"] == Decimal(-1) and g["matched"] is False
    assert g["hours"] == Decimal(2) and g["materials_total"] == Decimal("67.16")


def test_target_gap_within_band_is_matched():
    g = smr.target_gap(_target(), billed_minutes=90, materials_total=Decimal("50.00"))  # 57.50 marked, 9.66 short
    assert g["matched"] is True and g["remaining_hours"] == Decimal("0.5")


def test_target_gap_just_outside_band_is_short():
    assert smr.target_gap(_target(), billed_minutes=60, materials_total=Decimal("58.40"))["matched"] is False
    assert smr.target_gap(_target(), billed_minutes=120, materials_total=Decimal("49.00"))["matched"] is False  # 56.35, 10.81 short


def test_target_gap_overshoot_is_matched():
    g = smr.target_gap(_target(), billed_minutes=240, materials_total=Decimal("100.00"))
    assert g["matched"] is True and g["remaining_hours"] == 0 and g["remaining_materials_total"] == 0
    assert g["gap_hours"] == Decimal(2)


def test_target_gap_zero_target_is_matched():
    assert smr.target_gap(_target("0", "0.00"), billed_minutes=0, materials_total=Decimal(0))["matched"] is True


def test_target_gap_none_without_target():
    assert smr.target_gap(None, billed_minutes=30, materials_total=Decimal(1)) is None
